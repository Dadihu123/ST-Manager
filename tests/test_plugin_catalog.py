"""官方插件目录测试（设计文档 3.1–3.3 / 13.1）。

覆盖：清单解析与安全约束（只接受 owner/repo）、包内兜底、远端拉取与缓存、
离线降级、更新检查（Release 优先 / 回退远端 manifest / 24h 缓存）。
"""

import json
import os
import re
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
    # 发布后钉 tag + sha256：安装拿到的必须是显式发布过的归档，而不是分支最新代码。
    # 不写死具体版本号（每次发版都要改，反而容易漏）；断言的是**一致性**：
    # ref 必须是 vX.Y.Z 形式的 tag，且与条目 version 对齐——两者错位时，
    # 「检查更新」会报有新版本、真正安装却按旧 ref 拉到旧代码。
    ref = entry['source']['ref']
    assert catalog_module.TAG_PATTERN.match(ref), f'ref 必须是发布 tag: {ref!r}'
    assert ref.lstrip('v') == entry['version'], (
        f'source.ref ({ref}) 必须与条目 version ({entry["version"]}) 对齐'
    )
    assert len(entry['source']['sha256']) == 64
    assert re.fullmatch(r'[0-9a-f]{64}', entry['source']['sha256']), 'sha256 必须是小写十六进制'
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
    # 发布后钉 tag + sha256：安装拿到的必须是显式发布过的归档，而不是分支最新代码
    assert entry['source']['ref'] == 'v0.4.0'
    assert len(entry['source']['sha256']) == 64
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


def _stub_catalog_entry(monkeypatch, *, min_app_version='', release_channel='', subdir=''):
    """把官方目录换成一条带 `min_app_version` 的条目（`check_updates` 只读 `get_catalog`）。"""
    entry = {
        'id': 'demo-plugin',
        'name': '示例插件',
        'source': {
            'type': 'github',
            'repo': 'owner/demo-plugin',
            'ref': 'main',
            'subdir': subdir,
            'release_channel': release_channel or 'stable',
        },
        'version': '0.2.0',
        'min_app_version': min_app_version,
    }
    monkeypatch.setattr(
        catalog_module,
        'get_catalog',
        lambda **kwargs: {
            'success': True,
            'items': [entry],
            'source': 'remote',
            'offline': False,
            'updated_at': '',
            'msg': '',
        },
    )


def test_check_updates_flags_plugins_needing_a_newer_host(catalog_env, monkeypatch):
    """要求更高主程序版本的更新必须标出来，前端才能置灰按钮并说明原因。

    不标的话，旧主程序会先看到「发现 1 个可用更新」，点下去才被安装阶段的
    `min_app_version` 校验拒掉——用户看到的是「更新失败」，像 bug 而不像
    「前置条件没满足」。
    """
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    _stub_catalog_entry(monkeypatch, min_app_version='99.0.0')

    def responder(url, kwargs):
        if 'api.github.com' in url:
            return _FakeResponse(payload={'tag_name': 'v0.2.0'})
        return requests.ConnectionError('unexpected')

    _stub_get(monkeypatch, responder)

    update = catalog_module.check_updates(force=True)['updates'][0]
    assert update['min_app_version'] == '99.0.0'
    assert update['requires_app_update'] is True


def test_check_updates_does_not_flag_satisfied_host_requirement(catalog_env, monkeypatch):
    """门槛已被当前主程序满足时不能误报，否则更新按钮会被无谓置灰。"""
    from core.version import APP_VERSION

    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    _stub_catalog_entry(monkeypatch, min_app_version=APP_VERSION)

    def responder(url, kwargs):
        if 'api.github.com' in url:
            return _FakeResponse(payload={'tag_name': 'v0.2.0'})
        return requests.ConnectionError('unexpected')

    _stub_get(monkeypatch, responder)

    update = catalog_module.check_updates(force=True)['updates'][0]
    assert update['min_app_version'] == APP_VERSION
    assert update['requires_app_update'] is False


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


# ------------------------------------------------------------------ 更新说明


CHANGELOG_WITH_ANCHORS = '\n\n'.join([
    '# 插件变更日志',
    '没有锚点的旧内容（必须被忽略）',
    '\n'.join(['<!-- release: 0.3.0 -->', '## 0.3.0（2026-09-01）', '- 0.3.0 的改动', '<!-- /release -->']),
    '\n'.join(['<!-- release: 0.2.0 -->', '## 0.2.0（2026-08-01）', '- 0.2.0 的改动', '<!-- /release -->']),
    '\n'.join(['<!-- release: 0.1.0 -->', '## 0.1.0（2026-07-01）', '- 0.1.0 的改动', '<!-- /release -->']),
])


def _release_notes_responder(*, tag='v0.2.0', body=None, changelog=CHANGELOG_WITH_ANCHORS, calls=None):
    """stable 渠道的标准 responder：Release + 远端 CHANGELOG.md。"""
    def responder(url, kwargs):
        if calls is not None:
            calls.append(url)
        if 'api.github.com' in url:
            payload = {'tag_name': tag}
            if body is not None:
                payload['body'] = body
            return _FakeResponse(payload=payload)
        if url.endswith('CHANGELOG.md'):
            if isinstance(changelog, Exception):
                return changelog
            return _FakeResponse(body=changelog.encode('utf-8'))
        if url.endswith('manifest.json'):
            return _FakeResponse(status_code=404, payload={})
        return _FakeResponse(body=json.dumps(BUNDLED_CATALOG).encode('utf-8'))

    return responder


def test_check_updates_returns_release_body_as_notes(catalog_env, monkeypatch):
    """Release 正文就是「本次更新说明」，且不额外发请求（复用同一个响应体）。"""
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    calls = []
    _stub_get(monkeypatch, _release_notes_responder(body='## 本次修复\n- 修好了 X', calls=calls))

    update = catalog_module.check_updates(force=True)['updates'][0]

    assert update['release_notes_source'] == 'release'
    assert '修好了 X' in update['release_notes']
    assert update['release_notes_truncated'] is False
    assert not [url for url in calls if url.endswith('CHANGELOG.md')], '有 Release 正文时不该再拉 CHANGELOG'


def test_check_updates_falls_back_to_remote_changelog(catalog_env, monkeypatch):
    """Release 没有正文时回退远端 CHANGELOG，且只切出 `(installed, available]`。"""
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    _stub_get(monkeypatch, _release_notes_responder(body=''))

    update = catalog_module.check_updates(force=True)['updates'][0]

    assert update['available'] == '0.2.0'
    assert update['release_notes_source'] == 'changelog'
    notes = update['release_notes']
    assert '## 0.2.0' in notes and '0.2.0 的改动' in notes
    # 已安装的版本不该重复展示，比目标更新的版本更不该出现
    assert '## 0.1.0' not in notes
    assert '## 0.3.0' not in notes
    # 无锚点旧内容永远不进说明
    assert '没有锚点的旧内容' not in notes


def test_check_updates_requests_changelog_at_release_tag_first(catalog_env, monkeypatch):
    """CHANGELOG 优先按发布 tag 取（vX.Y.Z → X.Y.Z → ref → main）。"""
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    calls = []
    _stub_get(monkeypatch, _release_notes_responder(body='', calls=calls))

    catalog_module.check_updates(force=True)

    changelog_calls = [url for url in calls if url.endswith('CHANGELOG.md')]
    assert changelog_calls, '应请求远端 CHANGELOG.md'
    assert '/v0.2.0/' in changelog_calls[0]


def test_check_updates_dev_channel_skips_release_and_uses_changelog(catalog_env, monkeypatch):
    """dev 渠道直接读远端 manifest，不该请求 Release；说明来自 CHANGELOG。"""
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    _stub_catalog_entry(monkeypatch, release_channel='dev')
    calls = []

    def responder(url, kwargs):
        calls.append(url)
        if url.endswith('CHANGELOG.md'):
            return _FakeResponse(body=CHANGELOG_WITH_ANCHORS.encode('utf-8'))
        if url.endswith('manifest.json'):
            return _FakeResponse(payload={'version': '0.2.0'})
        return requests.ConnectionError('unexpected')

    _stub_get(monkeypatch, responder)

    update = catalog_module.check_updates(force=True)['updates'][0]

    assert not [url for url in calls if 'api.github.com' in url], 'dev 渠道不该请求 Release API'
    assert update['release_notes_source'] == 'changelog'
    assert '0.2.0 的改动' in update['release_notes']


def test_check_updates_survives_unreachable_changelog(catalog_env, monkeypatch):
    """CHANGELOG 连不上不能让更新检查失败，记录也要在（说明为空）。"""
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    _stub_get(monkeypatch, _release_notes_responder(body='', changelog=requests.ConnectionError('offline')))

    result = catalog_module.check_updates(force=True)

    assert result['success'] is True
    assert len(result['updates']) == 1
    update = result['updates'][0]
    assert update['has_update'] is True
    assert update['release_notes'] == ''
    assert update['release_notes_source'] == ''
    assert update['release_notes_truncated'] is False


def test_check_updates_marks_oversized_notes_as_truncated(catalog_env, monkeypatch):
    """超长说明按 UTF-8 字节截断并标记 truncated。"""
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    # 中文 3 字节/字：超上限，且必须切在多字节边界上
    _stub_get(monkeypatch, _release_notes_responder(body='中' * 20000))

    update = catalog_module.check_updates(force=True)['updates'][0]

    assert update['release_notes_truncated'] is True
    encoded = update['release_notes'].encode('utf-8')
    assert len(encoded) <= catalog_module.MAX_RELEASE_NOTES_BYTES
    assert encoded.decode('utf-8') == update['release_notes'], '截断不能切坏多字节字符'


def test_truncate_notes_cuts_at_a_line_boundary(monkeypatch):
    """截断点必须退到换行：至少不能把某一行切一半。

    注意边界：markdown 的硬换行（80 列折行）在源文件里也是 `\\n`，所以「完整行」
    不等于「完整句子」——真实插件的 CHANGELOG 就是硬换行的。这里只钉住行级完整，
    句子级覆盖靠 16KB 上限让常见升级路径不触发截断（见下面的覆盖率用例）。
    """
    line = '中' * 40  # 120 字节
    text = '\n'.join(f'{line}-{index}' for index in range(400))

    notes, truncated = catalog_module._truncate_notes(text)

    assert truncated is True
    assert len(notes.encode('utf-8')) <= catalog_module.MAX_RELEASE_NOTES_BYTES
    # 结果总是完整的行：notes + '\n' 是原文的前缀（说明切在某个换行处）
    assert text.startswith(notes + '\n'), '截断结果必须以完整行结尾'
    assert not notes.endswith('\n'), '不该把切点所在的那个换行留在正文末尾'
    # 被留下的每一行都还是完整行
    assert all(item in text for item in notes.split('\n'))


def test_truncate_notes_falls_back_to_bytes_for_single_long_line():
    """整段是一整行超长文本时没有换行可用，退回按字节切且不抛异常。"""
    text = '中' * 20000  # 单行，60000 字节

    notes, truncated = catalog_module._truncate_notes(text)

    assert truncated is True
    assert notes
    assert len(notes.encode('utf-8')) <= catalog_module.MAX_RELEASE_NOTES_BYTES
    assert notes.encode('utf-8').decode('utf-8') == notes, '不能切坏多字节字符'


def test_truncate_notes_leaves_content_at_limit_untouched():
    """恰好等于上限时原样返回（不 strip、不加尾巴），且不标记截断。"""
    head = '前' * 100 + '\n' + '后' * 100
    exact = head.encode('utf-8')
    # 用 ASCII 空格补齐到恰好等于上限（空格 1 字节，不影响多字节边界）
    at_limit = (exact + b' ' * (catalog_module.MAX_RELEASE_NOTES_BYTES - len(exact))).decode('utf-8')

    notes, truncated = catalog_module._truncate_notes(at_limit)

    assert truncated is False
    assert notes == at_limit, '未超限必须原样返回'


def test_release_notes_cover_the_typical_previous_to_latest_upgrade(catalog_env):
    """最常见的升级路径（上一版 → 最新版）必须能完整放进上限。

    实测真实插件 0.4.0 → 0.4.1 的说明是 11501 字节；8KB 只能覆盖 71%，
    用户读到的是半句话。这里按同量级（~11.5KB）造夹具钉住「能完整覆盖」。
    """
    line = '- 第 0 条修复说明，描述一个具体问题'  # 50 字节/行
    # 230 行 ≈ 11.7KB，对齐实测的 0.4.0 → 0.4.1（11501 字节）
    body = '\n'.join(f'{line}{index}' for index in range(230))
    body_bytes = len(body.encode('utf-8'))
    assert 8 * 1024 < body_bytes <= catalog_module.MAX_RELEASE_NOTES_BYTES, (
        f'夹具要落进 (8KB, 上限] 区间才验得出回归，实际 {body_bytes} 字节'
    )

    notes, truncated = catalog_module._truncate_notes(body)

    assert truncated is False, f'{body_bytes} 字节的常规说明不该被截断'
    assert notes == body


def test_check_updates_covers_typical_upgrade_end_to_end(catalog_env, monkeypatch):
    """端到端：0.4.0 → 0.4.1 这类真实升级的说明要能完整落到 release_notes。"""
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    body = '\n'.join(f'- 第 {index} 条修复说明，描述一个具体问题' for index in range(230))

    _stub_get(monkeypatch, _release_notes_responder(body=body))

    update = catalog_module.check_updates(force=True)['updates'][0]

    assert update['release_notes_truncated'] is False
    assert update['release_notes'] == body


def test_check_updates_skips_changelog_request_when_no_update(catalog_env, monkeypatch):
    """没有更新时不去取说明——否则每轮检查都白多一次网络请求。"""
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'], '0.9.0')])
    calls = []
    _stub_get(monkeypatch, _release_notes_responder(body='', calls=calls))

    assert catalog_module.check_updates(force=True)['updates'] == []
    assert not [url for url in calls if url.endswith('CHANGELOG.md')]


def test_cache_stores_truncated_notes_only(catalog_env, monkeypatch):
    """缓存里存的必须是截断后的说明：24h 缓存文件不能被更新说明撑大。"""
    monkeypatch.setattr(registry, 'list_states', lambda: [_installed_state(catalog_env['tmp_path'])])
    _stub_get(monkeypatch, _release_notes_responder(body='x' * 40000))

    catalog_module.check_updates(force=True)

    with open(catalog_env['tmp_path'] / '_catalog_cache.json', 'r', encoding='utf-8') as handle:
        cached = json.load(handle)
    cached_note = cached['updates']['updates'][0]['release_notes']
    assert len(cached_note.encode('utf-8')) <= catalog_module.MAX_RELEASE_NOTES_BYTES


def test_latest_release_keeps_the_documented_error_messages(catalog_env, monkeypatch):
    """`仓库没有 Release` 是回退链的触发条件，文案不能漂。"""
    _stub_get(monkeypatch, lambda url, kwargs: _FakeResponse(status_code=404, payload={}))
    with pytest.raises(PluginCatalogError, match='仓库没有 Release'):
        catalog_module._latest_release('owner/demo-plugin')

    _stub_get(monkeypatch, lambda url, kwargs: _FakeResponse(status_code=500, payload={}))
    with pytest.raises(PluginCatalogError, match='HTTP 500'):
        catalog_module._latest_release('owner/demo-plugin')

    _stub_get(monkeypatch, lambda url, kwargs: _FakeResponse(payload={'tag_name': ''}))
    with pytest.raises(PluginCatalogError, match='tag_name'):
        catalog_module._latest_release('owner/demo-plugin')


def test_latest_release_returns_version_and_body(catalog_env, monkeypatch):
    _stub_get(monkeypatch, lambda url, kwargs: _FakeResponse(
        payload={'tag_name': 'v0.4.1', 'body': '### 修复\n- 一条'},
    ))

    release = catalog_module._latest_release('owner/demo-plugin')

    assert release == {'version': '0.4.1', 'notes': '### 修复\n- 一条', 'notes_truncated': False}


def test_latest_release_treats_missing_body_as_empty(catalog_env, monkeypatch):
    """Release 没有 body / body 不是字符串时按空处理，绝不抛异常。"""
    for payload in ({'tag_name': 'v0.4.1'}, {'tag_name': 'v0.4.1', 'body': None}, {'tag_name': 'v0.4.1', 'body': 42}):
        _stub_get(monkeypatch, lambda url, kwargs, payload=payload: _FakeResponse(payload=payload))

        release = catalog_module._latest_release('owner/demo-plugin')

        assert release['notes'] == ''
        assert release['notes_truncated'] is False
