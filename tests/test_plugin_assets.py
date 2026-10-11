"""插件静态资源路由测试（设计文档 8.5 / 13.1）。"""

import os
import sys

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import assets as assets_module
from core.plugins import registry as registry_module
from tests.plugins_test_support import write_plugin


@pytest.fixture
def asset_app(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    with open(os.path.join(plugin_dir, 'frontend', 'secret.env'), 'w', encoding='utf-8') as handle:
        handle.write('TOKEN=1\n')
    with open(os.path.join(plugin_dir, 'backend', '__init__.py'), 'a', encoding='utf-8') as handle:
        handle.write('\n')

    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))
    monkeypatch.setattr(registry_module, '_states', {'demo-plugin': _state(plugin_dir)})

    app = Flask('plugin-assets-test')
    app.register_blueprint(assets_module.bp)
    return app


def _state(plugin_dir):
    state = registry_module.PluginState('demo-plugin', plugin_dir)
    return state


def test_serves_allowlisted_asset(asset_app):
    client = asset_app.test_client()

    response = client.get('/api/plugins/demo-plugin/assets/frontend/plugin.js')

    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'private, no-cache'
    assert 'activate' in response.get_data(as_text=True)


def test_asset_cache_control_forces_revalidation(asset_app):
    """资产必须**先校验**（`no-cache`），不得给 `immutable` / 长 `max-age`。

    ⚠️ 这里断言**字面量**取值（而不是只跟 `ASSET_CACHE_CONTROL` 比），
    否则把常量改回强缓存测试也照样绿 —— 策略本身必须被钉住。

    **为什么不能是强缓存**（真实踩过，有复现脚本）：版本参数 `?v=<插件版本>`
    只加在**入口** URL 上，而 ES 模块的相对 import **不继承查询串**：

        new URL('./panel.js', '.../plugin.js?v=0.1.0').href  →  '.../panel.js'

    实测插件 6 个子模块（`panel.js` / `petview.js` / `announce.js` / `clock.js` /
    `physics.js` / `statemachine.js`）的请求 URL 全都不带 `?v=`，因此**恒定不变**。
    给它们 `immutable` + 一年 `max-age` 就等于永久缓存：改代码、**重装插件**、
    甚至硬刷新都可能仍执行旧模块（实测：改磁盘代码后普通刷新仍是旧代码）。

    这正是「修好 bug 并重装插件，用户却仍看到旧行为」的根因。
    """
    client = asset_app.test_client()

    cache_control = client.get('/api/plugins/demo-plugin/assets/frontend/plugin.js').headers['Cache-Control']

    assert cache_control == 'private, no-cache'
    assert assets_module.ASSET_CACHE_CONTROL == 'private, no-cache'
    directives = {item.strip() for item in cache_control.split(',')}

    # private：资产与登录态同源，不允许中间代理缓存
    assert 'private' in directives, cache_control
    # 必须校验
    assert 'no-cache' in directives, cache_control
    # 不得永久缓存（子模块 URL 不带版本，强缓存会导致插件更新不生效）
    assert 'immutable' not in directives, cache_control
    assert 'no-store' not in directives, cache_control
    assert not any(item.startswith('max-age=') for item in directives), (
        f'不得给 max-age（子模块 URL 恒定，长缓存会导致更新不生效）: {cache_control}'
    )


def test_conditional_request_returns_304(asset_app):
    """D5：`conditional=True` 后 ETag / Last-Modified 必须真的生效。"""
    client = asset_app.test_client()
    url = '/api/plugins/demo-plugin/assets/frontend/plugin.js'

    first = client.get(url)
    etag = first.headers['ETag']
    assert etag

    revalidate = client.get(url, headers={'If-None-Match': etag})

    assert revalidate.status_code == 304, '条件请求必须回 304（修复前恒为 200）'
    assert revalidate.get_data() == b''
    # 304 也必须带缓存策略，否则浏览器会退回启发式新鲜度
    assert revalidate.headers['Cache-Control'] == 'private, no-cache'

    by_date = client.get(url, headers={'If-Modified-Since': first.headers['Last-Modified']})

    assert by_date.status_code == 304


def test_stale_etag_still_returns_full_body(asset_app):
    """条件请求不得削弱正确性：不匹配的 ETag 仍然返回完整资源。"""
    client = asset_app.test_client()
    url = '/api/plugins/demo-plugin/assets/frontend/plugin.js'

    response = client.get(url, headers={'If-None-Match': '"stale-etag"'})

    assert response.status_code == 200
    assert b'activate' in response.get_data()


def test_asset_supports_range_requests(asset_app):
    """D5：`conditional=True` 顺带打开 Range（原 `conditional=False` 时不支持）。"""
    client = asset_app.test_client()
    url = '/api/plugins/demo-plugin/assets/frontend/plugin.js'

    full = client.get(url).get_data()
    partial = client.get(url, headers={'Range': 'bytes=0-9'})

    assert partial.status_code == 206, '修复前恒为 200 + 全量响应'
    assert partial.get_data() == full[:10]
    assert partial.headers['Content-Range'] == f'bytes 0-9/{len(full)}'
    assert partial.headers['Accept-Ranges'] == 'bytes'


def test_asset_response_carries_security_headers(asset_app):
    client = asset_app.test_client()

    response = client.get('/api/plugins/demo-plugin/assets/frontend/plugin.js')

    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert "default-src 'none'" in response.headers['Content-Security-Policy']
    assert 'sandbox' in response.headers['Content-Security-Policy']
    assert response.headers['Cross-Origin-Resource-Policy'] == 'same-origin'


def test_rejects_disallowed_extension(asset_app):
    client = asset_app.test_client()

    assert client.get('/api/plugins/demo-plugin/assets/backend/__init__.py').status_code == 404
    assert client.get('/api/plugins/demo-plugin/assets/frontend/secret.env').status_code == 404


def test_rejects_path_traversal(asset_app, tmp_path):
    outside = tmp_path.parent / 'outside.js'
    outside.write_text('window.pwned = true;', encoding='utf-8')
    client = asset_app.test_client()

    assert client.get('/api/plugins/demo-plugin/assets/../../outside.js').status_code in (404, 308)
    assert client.get('/api/plugins/demo-plugin/assets/..%2f..%2foutside.js').status_code == 404


def test_rejects_invalid_plugin_id(asset_app):
    client = asset_app.test_client()

    assert client.get('/api/plugins/Demo_Plugin/assets/frontend/plugin.js').status_code == 404


def test_unknown_plugin_returns_404(asset_app):
    client = asset_app.test_client()

    assert client.get('/api/plugins/unknown-plugin/assets/frontend/plugin.js').status_code == 404


def test_missing_file_returns_404(asset_app):
    client = asset_app.test_client()

    assert client.get('/api/plugins/demo-plugin/assets/frontend/missing.js').status_code == 404


def test_json_asset_is_served_with_json_mime(asset_app, tmp_path):
    with open(tmp_path / 'demo-plugin' / 'frontend' / 'manifest-snapshot.json', 'w', encoding='utf-8') as handle:
        handle.write('{"a": 1}')
    client = asset_app.test_client()

    response = client.get('/api/plugins/demo-plugin/assets/frontend/manifest-snapshot.json')

    assert response.status_code == 200
    assert response.mimetype == 'application/json'


def test_gif_and_avif_assets_are_served_with_correct_mime(asset_app, tmp_path):
    """D5：`.gif` / `.avif` 可直接当插件图片资产用（此前一律 404）。"""
    frontend = tmp_path / 'demo-plugin' / 'frontend'
    for name, payload in (('idle.gif', b'GIF89a'), ('idle.avif', b'\x00\x00\x00 ftypavif')):
        (frontend / name).write_bytes(payload)

    client = asset_app.test_client()

    for name, mime in (('idle.gif', 'image/gif'), ('idle.avif', 'image/avif')):
        response = client.get(f'/api/plugins/demo-plugin/assets/frontend/{name}')

        assert response.status_code == 200, name
        assert response.mimetype == mime, name
        # 实测：`img-src 'self'` 按 scheme 放行，扩展名不需要逐个进 CSP
        assert "img-src 'self' data:" in response.headers['Content-Security-Policy'], name
        assert response.headers['X-Content-Type-Options'] == 'nosniff', name


def test_allowed_extensions_all_have_declared_mime_types():
    """白名单每项都要有显式 MIME：遗漏会落回 `mimetypes.guess_type`（平台相关）。"""
    missing = sorted(assets_module.ALLOWED_EXTENSIONS - set(assets_module.DEFAULT_MIME_TYPES))

    assert missing == [], f'白名单缺少 MIME 条目: {missing}'


def test_allowed_extensions_are_the_expected_set():
    """白名单是安全边界（**不提供** `.py` / `.md` / `.env`），必须逐项锁死。"""
    assert assets_module.ALLOWED_EXTENSIONS == frozenset({
        '.js', '.mjs', '.css', '.svg', '.png', '.webp', '.gif', '.avif', '.json', '.woff2', '.map',
    })
    assert '.py' not in assets_module.ALLOWED_EXTENSIONS
    assert '.env' not in assets_module.ALLOWED_EXTENSIONS
    assert '.md' not in assets_module.ALLOWED_EXTENSIONS
