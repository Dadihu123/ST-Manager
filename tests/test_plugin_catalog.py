"""官方插件目录测试（设计文档 3.1–3.3 / 13.1）。

覆盖：清单解析与安全约束（只接受 owner/repo）、包内兜底、远端拉取与缓存、
离线降级、更新检查（Release 优先 / 回退远端 manifest / 24h 缓存）。
"""

import json
import os
import sys
import time

import pytest
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import catalog as catalog_module
from core.plugins import registry
from core.plugins.errors import PluginCatalogError
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import write_plugin

BUNDLED_CATALOG = {
    'schema_version': 1,
    'updated_at': '2026-01-01T00:00:00Z',
    'plugins': [
        {
            'id': 'demo-plugin',
            'name': '示例插件',
            'description': '内置条目',
            'source': {'type': 'github', 'repo': 'owner/demo-plugin', 'ref': 'main'},
            'version': '0.1.0',
        },
    ],
}


class _FakeResponse:
    def __init__(self, *, status_code=200, payload=None, body=b'', chunk_size=4096):
        self.status_code = status_code
        self._payload = payload
        self._body = body
        self._chunk_size = chunk_size
        self.closed = False

    def json(self):
        if self._payload is None:
            raise ValueError('no json payload')
        return self._payload

    def iter_content(self, chunk_size=65536):
        step = min(chunk_size, self._chunk_size)
        for start in range(0, len(self._body), step):
            yield self._body[start:start + step]

    def close(self):
        self.closed = True


@pytest.fixture
def catalog_env(tmp_path, monkeypatch):
    bundled_path = tmp_path / 'bundled-catalog.json'
    bundled_path.write_text(json.dumps(BUNDLED_CATALOG, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(catalog_module, 'CACHE_DIR', str(tmp_path))
    monkeypatch.setattr(catalog_module, 'CACHE_FILE', str(tmp_path / '_catalog_cache.json'))
    monkeypatch.setattr(catalog_module, 'bundled_catalog_path', lambda: str(bundled_path))

    config = {
        'plugin_catalog_url': 'https://raw.githubusercontent.com/owner/repo/main/static/plugins/catalog.json',
        'plugin_catalog_remote_enabled': True,
        'plugin_catalog_cache_hours': 6,
    }
    monkeypatch.setattr(catalog_module, 'load_config', lambda: dict(config))
    monkeypatch.setattr(registry, 'list_states', lambda: [])

    return {'tmp_path': tmp_path, 'bundled_path': bundled_path, 'config': config}


def _stub_get(monkeypatch, responder):
    """用 responder(url, kwargs) -> _FakeResponse 替换 requests.get。"""
    def fake_get(url, **kwargs):
        response = responder(url, kwargs)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(catalog_module.requests, 'get', fake_get)


# ------------------------------------------------------------------ 解析


def test_repository_bundled_catalog_is_valid_json():
    """仓库自带的包内清单必须可解析。"""
    bundled = catalog_module.load_bundled_catalog()

    assert bundled['schema_version'] == catalog_module.CATALOG_SCHEMA_VERSION
    assert isinstance(bundled['plugins'], list)


def test_bundled_catalog_lists_official_ai_assistant():
    """官方 AI 助手插件必须在包内清单里，且 tier = official。

    `tier` 决定该插件的入口能用哪些 kind（D5），也决定坞是否默认把它放进槽位
    （D6：community 默认进溢出菜单）。这些**只能由宿主仓库的 catalog 决定**，
    插件 manifest 无权声明——所以这条断言是「官方」这一事实的唯一落点。
    """
    bundled = catalog_module.load_bundled_catalog()
    entries = {item['id']: item for item in bundled['plugins']}

    assert 'stm-ai-assistant' in entries, '包内清单必须包含官方 AI 助手插件'
    entry = entries['stm-ai-assistant']

    assert entry['tier'] == 'official'
    assert entry['source']['repo'] == 'Dadihu123/ST-Manager-AI-Assistant'
    assert entry['source']['type'] == 'github'
    # source.repo 必须是 owner/repo（防 SSRF，catalog 不接受任意 URL）
    assert catalog_module.REPO_PATTERN.match(entry['source']['repo'])
    assert entry['api_version'] == 3
    # 能力披露取代 v2 的 permissions：官方 AI 助手的能力位与旧权限一一对应
    assert entry['capabilities'] == [
        'cards.read', 'cards.write',
        'worldbook.read', 'worldbook.write',
        'tags.read', 'tags.write',
        'secrets.read', 'network.outbound', 'jobs.run',
    ]
    assert 'permissions' not in entry, 'v3 catalog 不再有 permissions 键'


def test_bundled_catalog_lists_official_pet():
    """官方桌面宠物插件必须在包内清单里，且 tier = official。

    与 AI 助手同一条信任模型：`tier` 只能由宿主仓库的 catalog 决定。
    该插件走自绘渲染（`render_mode: custom`），因此能力位只有 `ui.custom`；
    这里钉住「catalog 不得多写」——能力位是安装前披露给用户的依据。
    """
    bundled = catalog_module.load_bundled_catalog()
    entries = {item['id']: item for item in bundled['plugins']}

    assert 'stm-pet' in entries, '包内清单必须包含官方桌面宠物插件'
    entry = entries['stm-pet']

    assert entry['tier'] == 'official'
    assert entry['source']['repo'] == 'Dadihu123/ST-Manager-Pet'
    assert entry['source']['type'] == 'github'
    assert catalog_module.REPO_PATTERN.match(entry['source']['repo'])
    assert entry['source']['ref'] == 'main'
    assert entry['api_version'] == 3
    assert entry['min_app_version'] == '1.0.0'
    assert entry['capabilities'] == ['ui.custom']
    assert entry['homepage'] == 'https://github.com/Dadihu123/ST-Manager-Pet'
    # 归档结构：仓库根目录直接含 manifest.json（无需 subdir）
    assert entry['source']['subdir'] == ''


def test_bundled_catalog_entries_are_all_installable():
    """每条官方条目都要能被 installer 接受（repo/ref/subdir 形状合法）。

    防止「清单里写了但装不上」：repo 走 `validate_repo`、ref 走 `validate_ref`、
    subdir 走 `validate_subdir`，三者都是安装路径上的真实校验点。
    """
    from core.plugins.installer import validate_ref, validate_repo, validate_subdir

    bundled = catalog_module.load_bundled_catalog()
    assert bundled['plugins'], '包内清单不应为空'

    for entry in bundled['plugins']:
        source = entry['source']
        assert validate_repo(source['repo']) == source['repo'], entry['id']
        assert validate_ref(source['ref']) == source['ref'], entry['id']
        assert validate_subdir(source['subdir']) == source['subdir'], entry['id']


def test_tier_for_plugin_resolves_official_from_bundled_catalog():
    """加载期只读本地（缓存 + 包内清单），不发起网络请求。"""
    assert catalog_module.tier_for_plugin('stm-ai-assistant') == 'official'
    assert catalog_module.tier_for_plugin('stm-pet') == 'official'
    # 未知插件一律 community（安全的一侧）
    assert catalog_module.tier_for_plugin('nope-not-installed') == 'community'


def test_tier_is_disclosure_only():
    """ADR-0008：tier 只做信任披露，不再限制贡献类型。

    v2 的「community 不能声明 nav/status」准入规则已随 `entries` 一起删除；
    这里钉住 tier 归一化行为（未知值按 community）与合法分级集合。
    """
    assert catalog_module.PLUGIN_TIERS == ('official', 'verified', 'community')
    assert catalog_module.DEFAULT_PLUGIN_TIER == 'community'
    assert catalog_module.normalize_tier('official') == 'official'
    assert catalog_module.normalize_tier('VERIFIED') == 'verified'
    assert catalog_module.normalize_tier('unknown-tier') == 'community'
    assert catalog_module.normalize_tier(None) == 'community'


def test_parse_catalog_normalizes_entries():
    parsed = catalog_module.parse_catalog(BUNDLED_CATALOG)

    assert len(parsed['plugins']) == 1
    entry = parsed['plugins'][0]
    assert entry['id'] == 'demo-plugin'
    assert entry['source']['repo'] == 'owner/demo-plugin'
    assert entry['source']['ref'] == 'main'
    assert entry['source']['sha256'] == ''


def test_parse_catalog_drops_arbitrary_urls():
    payload = {
        'plugins': [
            {'id': 'evil', 'source': {'type': 'github', 'repo': 'https://evil.example/x.zip'}},
            {'id': 'ok', 'source': {'repo': 'owner/ok'}},
        ],
    }

    parsed = catalog_module.parse_catalog(payload)

    assert [entry['id'] for entry in parsed['plugins']] == ['ok']


def test_parse_catalog_drops_entries_without_id_or_source():
    payload = {
        'plugins': [
            {'source': {'repo': 'owner/a'}},
            {'id': 'no-source'},
            'not-a-dict',
        ],
    }

    assert catalog_module.parse_catalog(payload)['plugins'] == []


def test_parse_catalog_deduplicates_ids():
    payload = {
        'plugins': [
            {'id': 'dup', 'source': {'repo': 'owner/a'}},
            {'id': 'dup', 'source': {'repo': 'owner/b'}},
        ],
    }

    parsed = catalog_module.parse_catalog(payload)

    assert len(parsed['plugins']) == 1
    assert parsed['plugins'][0]['source']['repo'] == 'owner/a'


def test_parse_catalog_rejects_non_object_payload():
    with pytest.raises(PluginCatalogError):
        catalog_module.parse_catalog(['not', 'an', 'object'])


def test_parse_catalog_keeps_optional_sha256():
    payload = {'plugins': [{
        'id': 'demo-plugin',
        'source': {'repo': 'owner/demo', 'sha256': 'A' * 64},
    }]}

    entry = catalog_module.parse_catalog(payload)['plugins'][0]

    assert entry['source']['sha256'] == 'a' * 64


def test_parse_catalog_discloses_capabilities_not_permissions():
    """v3：catalog 用 `capabilities` 披露能力位（取代 v2 的 `permissions`）。"""
    payload = {'schema_version': 3, 'plugins': [{
        'id': 'demo-plugin',
        'source': {'repo': 'owner/demo'},
        'api_version': 3,
        'capabilities': ['cards.read', 'ui.custom'],
    }]}

    entry = catalog_module.parse_catalog(payload)['plugins'][0]

    assert entry['api_version'] == 3
    assert entry['capabilities'] == ['cards.read', 'ui.custom']
    assert 'permissions' not in entry


def test_bundled_catalog_schema_version_is_three():
    bundled = catalog_module.load_bundled_catalog()

    assert bundled['schema_version'] == 3
    assert catalog_module.CATALOG_SCHEMA_VERSION == 3


# ------------------------------------------------------------------ 拉取与缓存


def test_get_catalog_fetches_remote_and_caches(catalog_env, monkeypatch):
    calls = []

    def responder(url, kwargs):
        calls.append(url)
        body = json.dumps({
            'schema_version': 1,
            'updated_at': '2026-02-02T00:00:00Z',
            'plugins': [{'id': 'remote-plugin', 'source': {'repo': 'owner/remote-plugin'}}],
        }).encode('utf-8')
        return _FakeResponse(body=body)

    _stub_get(monkeypatch, responder)

    first = catalog_module.get_catalog()
    assert first['source'] == 'remote'
    assert first['offline'] is False
    assert [item['id'] for item in first['items']] == ['remote-plugin']
    assert len(calls) == 1

    # 缓存新鲜期内不再发起网络请求
    second = catalog_module.get_catalog()
    assert second['source'] == 'cache'
    assert [item['id'] for item in second['items']] == ['remote-plugin']
    assert len(calls) == 1


def test_get_catalog_refresh_bypasses_cache(catalog_env, monkeypatch):
    calls = []

    def responder(url, kwargs):
        calls.append(url)
        return _FakeResponse(body=json.dumps({'plugins': []}).encode('utf-8'))

    _stub_get(monkeypatch, responder)

    catalog_module.get_catalog()
    catalog_module.get_catalog(refresh=True)

    assert len(calls) == 2


def test_get_catalog_falls_back_to_bundled_when_offline(catalog_env, monkeypatch):
    _stub_get(monkeypatch, lambda url, kwargs: requests.ConnectionError('offline'))

    result = catalog_module.get_catalog()

    assert result['source'] == 'bundled'
    assert result['offline'] is True
    assert [item['id'] for item in result['items']] == ['demo-plugin']
    assert '离线' in result['msg']


@pytest.mark.parametrize('status_code', [404, 500, 403])
def test_get_catalog_reports_http_errors_as_offline(catalog_env, monkeypatch, status_code):
    _stub_get(monkeypatch, lambda url, kwargs: _FakeResponse(status_code=status_code, body=b''))

    result = catalog_module.get_catalog()

    assert result['offline'] is True
    assert f'HTTP {status_code}' in result['msg']


def test_catalog_404_message_points_at_the_real_cause(catalog_env, monkeypatch):
    """404 要说清「远端没有这个文件」，而不是笼统的 HTTP 错误。

    远端目录是主程序仓库里的一个文件，404 几乎总是「本地改了但没 push」，
    与网络故障的排查方向完全不同。消息里带上 URL 与判断依据，用户能自查。
    """
    _stub_get(monkeypatch, lambda url, kwargs: _FakeResponse(status_code=404, body=b''))

    result = catalog_module.get_catalog()

    assert result['offline'] is True
    assert '远端目录不存在' in result['msg']
    # 给出 URL，用户能自己核对
    assert catalog_env['config']['plugin_catalog_url'] in result['msg']
    # 指出真实原因
    assert '推送' in result['msg'] or '默认分支' in result['msg']


def test_catalog_404_hint_does_not_leak_into_other_errors(catalog_env, monkeypatch):
    """500 等其它错误不应带上 404 的「未推送」提示（避免误导排查方向）。"""
    _stub_get(monkeypatch, lambda url, kwargs: _FakeResponse(status_code=500, body=b''))

    result = catalog_module.get_catalog()

    assert '远端目录不存在' not in result['msg']
    assert '推送' not in result['msg']


def test_get_catalog_rejects_broken_json(catalog_env, monkeypatch):
    _stub_get(monkeypatch, lambda url, kwargs: _FakeResponse(body=b'{not json'))

    result = catalog_module.get_catalog()

    assert result['offline'] is True
    assert result['source'] == 'bundled'


def test_get_catalog_rejects_oversized_payload(catalog_env, monkeypatch):
    monkeypatch.setattr(catalog_module, 'MAX_CATALOG_BYTES', 64)
    _stub_get(monkeypatch, lambda url, kwargs: _FakeResponse(body=b'x' * 4096))

    result = catalog_module.get_catalog()

    assert result['offline'] is True
    assert '大小上限' in result['msg']


def test_get_catalog_uses_bundled_when_remote_disabled(catalog_env, monkeypatch):
    catalog_env['config']['plugin_catalog_remote_enabled'] = False
    calls = []
    _stub_get(monkeypatch, lambda url, kwargs: calls.append(url) or _FakeResponse())

    result = catalog_module.get_catalog()

    assert calls == []
    assert result['source'] == 'bundled'
    assert result['offline'] is False
    assert '远端目录已关闭' in result['msg']


def test_get_catalog_ignores_stale_cache(catalog_env, monkeypatch):
    cache_path = catalog_env['tmp_path'] / '_catalog_cache.json'
    cache_path.write_text(json.dumps({
        'catalog': {'plugins': [{'id': 'stale'}], 'fetched_at': time.time() - 7 * 3600},
    }), encoding='utf-8')

    _stub_get(monkeypatch, lambda url, kwargs: _FakeResponse(
        body=json.dumps({'plugins': [{'id': 'fresh', 'source': {'repo': 'owner/fresh'}}]}).encode('utf-8'),
    ))

    result = catalog_module.get_catalog()

    assert result['source'] == 'remote'
    assert [item['id'] for item in result['items']] == ['fresh']


def test_find_catalog_entry_raises_for_unknown_id(catalog_env, monkeypatch):
    _stub_get(monkeypatch, lambda url, kwargs: requests.ConnectionError('offline'))

    with pytest.raises(PluginCatalogError, match='不存在'):
        catalog_module.find_catalog_entry('nope')


def test_find_catalog_entry_returns_match(catalog_env, monkeypatch):
    _stub_get(monkeypatch, lambda url, kwargs: requests.ConnectionError('offline'))

    entry = catalog_module.find_catalog_entry('demo-plugin')

    assert entry['source']['repo'] == 'owner/demo-plugin'


# ------------------------------------------------------------------ 更新检查


def _installed_state(tmp_path, version='0.1.0'):
    plugin_dir = write_plugin(tmp_path / 'installed', 'demo-plugin')
    with open(os.path.join(plugin_dir, 'manifest.json'), 'r', encoding='utf-8') as handle:
        payload = json.load(handle)
    payload['version'] = version
    with open(os.path.join(plugin_dir, 'manifest.json'), 'w', encoding='utf-8') as handle:
        json.dump(payload, handle, ensure_ascii=False)

    state = registry.PluginState('demo-plugin', plugin_dir)
    state.manifest = PluginManifest.load(plugin_dir)
    return state


def test_check_updates_uses_latest_release(catalog_env, monkeypatch):
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])

    def responder(url, kwargs):
        if 'api.github.com' in url:
            return _FakeResponse(payload={'tag_name': 'v0.2.0'})
        if 'raw.githubusercontent.com' in url:
            return _FakeResponse(body=json.dumps(BUNDLED_CATALOG).encode('utf-8'))
        return requests.ConnectionError('unexpected')

    _stub_get(monkeypatch, responder)

    result = catalog_module.check_updates(force=True)

    assert result['success'] is True
    assert len(result['updates']) == 1
    update = result['updates'][0]
    assert update['id'] == 'demo-plugin'
    assert update['installed'] == '0.1.0'
    assert update['available'] == '0.2.0'
    assert update['channel'] == 'stable'
    assert update['repo'] == 'owner/demo-plugin'


def test_check_updates_falls_back_to_remote_manifest(catalog_env, monkeypatch):
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])

    def responder(url, kwargs):
        if 'api.github.com' in url:
            return _FakeResponse(status_code=404, payload={})
        if 'raw.githubusercontent.com' in url and url.endswith('manifest.json'):
            return _FakeResponse(payload={'version': '0.3.0'})
        return _FakeResponse(body=json.dumps(BUNDLED_CATALOG).encode('utf-8'))

    _stub_get(monkeypatch, responder)

    result = catalog_module.check_updates(force=True)

    assert result['updates'][0]['available'] == '0.3.0'


def test_check_updates_ignores_same_or_older_versions(catalog_env, monkeypatch):
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'], '0.9.0')])

    def responder(url, kwargs):
        if 'api.github.com' in url:
            return _FakeResponse(payload={'tag_name': 'v0.2.0'})
        return _FakeResponse(body=json.dumps(BUNDLED_CATALOG).encode('utf-8'))

    _stub_get(monkeypatch, responder)

    assert catalog_module.check_updates(force=True)['updates'] == []


def test_check_updates_marks_has_update_flag(catalog_env, monkeypatch):
    """每条记录都带 `has_update`，前端才能区分「有更新」与「已是最新」。"""
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])

    def responder(url, kwargs):
        if 'api.github.com' in url:
            return _FakeResponse(payload={'tag_name': 'v0.2.0'})
        return _FakeResponse(body=json.dumps(BUNDLED_CATALOG).encode('utf-8'))

    _stub_get(monkeypatch, responder)

    update = catalog_module.check_updates(force=True)['updates'][0]
    assert update['has_update'] is True


def test_remote_manifest_is_the_authoritative_version_source(catalog_env, monkeypatch):
    """版本以**远端 manifest** 为准，catalog 里的 `version` 只是发布方写的快照。

    改了仓库 manifest 但忘了同步 catalog 时，必须以仓库为准——否则用户会
    永远看不到更新（catalog 是包内/缓存文件，不会自己更新）。
    """
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])

    # catalog 声明 0.1.0（与已安装相同），但远端 manifest 已经是 0.5.0
    stale_catalog = json.loads(json.dumps(BUNDLED_CATALOG))
    stale_catalog['plugins'][0]['version'] = '0.1.0'

    def responder(url, kwargs):
        if 'api.github.com' in url:
            return _FakeResponse(status_code=404, payload={})
        if url.endswith('manifest.json'):
            return _FakeResponse(payload={'version': '0.5.0'})
        return _FakeResponse(body=json.dumps(stale_catalog).encode('utf-8'))

    _stub_get(monkeypatch, responder)

    result = catalog_module.check_updates(force=True)

    assert result['updates'][0]['available'] == '0.5.0'
    assert result['updates'][0]['installed'] == '0.1.0'


def test_check_updates_collects_errors_without_failing(catalog_env, monkeypatch):
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])

    def responder(url, kwargs):
        if 'api.github.com' in url:
            return _FakeResponse(status_code=403, payload={})
        if url.endswith('manifest.json'):
            return _FakeResponse(status_code=404, payload={})
        return _FakeResponse(body=json.dumps(BUNDLED_CATALOG).encode('utf-8'))

    _stub_get(monkeypatch, responder)

    result = catalog_module.check_updates(force=True)

    assert result['success'] is True
    assert result['updates'] == []
    assert result['errors'] and result['errors'][0]['id'] == 'demo-plugin'


def test_check_updates_uses_cached_result_unless_forced(catalog_env, monkeypatch):
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    calls = []

    def responder(url, kwargs):
        calls.append(url)
        if 'api.github.com' in url:
            return _FakeResponse(payload={'tag_name': 'v0.5.0'})
        return _FakeResponse(body=json.dumps(BUNDLED_CATALOG).encode('utf-8'))

    _stub_get(monkeypatch, responder)

    first = catalog_module.check_updates(force=True)
    calls_after_first = len(calls)
    second = catalog_module.check_updates()

    assert first['updates'][0]['available'] == '0.5.0'
    assert second['source'] == 'cache'
    assert second['updates'][0]['available'] == '0.5.0'
    assert len(calls) == calls_after_first


def test_check_updates_skips_plugins_not_in_catalog(catalog_env, monkeypatch):
    other_dir = write_plugin(catalog_env['tmp_path'] / 'other', 'other-plugin')
    state = registry.PluginState('other-plugin', other_dir)
    state.manifest = PluginManifest.load(other_dir)
    monkeypatch.setattr(registry, 'list_states', lambda: [state])

    _stub_get(monkeypatch, lambda url, kwargs: requests.ConnectionError('offline'))

    assert catalog_module.check_updates(force=True)['updates'] == []


def test_check_updates_sends_github_token_when_configured(catalog_env, monkeypatch, tmp_path):
    from core.plugins import secrets as secrets_module

    monkeypatch.setattr(secrets_module, 'SECRETS_FILE', str(tmp_path / 'secrets.json'))
    assert secrets_module.set_app_secret('github_token', 'ghp_test_token') is True
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    seen_headers = {}

    def responder(url, kwargs):
        if 'api.github.com' in url:
            seen_headers.update(kwargs.get('headers') or {})
            return _FakeResponse(payload={'tag_name': 'v0.2.0'})
        return _FakeResponse(body=json.dumps(BUNDLED_CATALOG).encode('utf-8'))

    _stub_get(monkeypatch, responder)

    catalog_module.check_updates(force=True)

    assert seen_headers.get('Authorization') == 'Bearer ghp_test_token'
    assert seen_headers.get('Accept') == 'application/vnd.github+json'


def test_app_secret_supports_environment_override(monkeypatch, tmp_path):
    from core.plugins import secrets as secrets_module

    monkeypatch.setattr(secrets_module, 'SECRETS_FILE', str(tmp_path / 'secrets.json'))
    monkeypatch.setenv('STM_APP_GITHUB_TOKEN', 'ghp_from_env')

    assert secrets_module.get_app_secret('github_token') == 'ghp_from_env'
    assert secrets_module.app_env_var_name('github_token') == 'STM_APP_GITHUB_TOKEN'


def test_reset_cache_for_tests(catalog_env):
    cache_path = catalog_env['tmp_path'] / '_catalog_cache.json'
    cache_path.write_text('{}', encoding='utf-8')

    catalog_module.reset_cache_for_tests()

    assert not cache_path.exists()
