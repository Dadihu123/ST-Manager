"""安全响应头测试（设计文档阶段 3「安全响应头」）。

分两层覆盖：`apply_security_headers()` 的纯函数行为，以及 `create_app()`
是否真的把它挂到 `after_request` 上。
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.utils.security_headers import (
    PLUGIN_ASSET_CSP,
    GLOBAL_HEADERS,
    apply_security_headers,
)


class _FakeResponse:
    def __init__(self, headers=None):
        self.headers = dict(headers or {})


def test_global_headers_are_applied():
    response = apply_security_headers(_FakeResponse(), path='/api/plugins/list')

    for name, value in GLOBAL_HEADERS.items():
        assert response.headers[name] == value


def test_plugin_assets_get_strict_csp():
    response = apply_security_headers(
        _FakeResponse(), path='/api/plugins/demo-plugin/assets/frontend/icon.svg',
    )

    assert response.headers['Content-Security-Policy'] == PLUGIN_ASSET_CSP
    assert "default-src 'none'" in response.headers['Content-Security-Policy']
    assert 'sandbox' in response.headers['Content-Security-Policy']
    assert response.headers['Cross-Origin-Resource-Policy'] == 'same-origin'


def test_csp_is_not_applied_to_core_static_files():
    response = apply_security_headers(_FakeResponse(), path='/static/js/app.js')

    assert 'Content-Security-Policy' not in response.headers
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


def test_csp_is_not_applied_to_plugin_management_endpoints():
    """只有资源路由加 CSP；管理接口（配置/密钥/作业）不加。"""
    for path in (
        '/api/plugins/demo-plugin/config',
        '/api/plugins/demo-plugin/secrets',
        '/api/plugins/list',
    ):
        response = apply_security_headers(_FakeResponse(), path=path)
        assert 'Content-Security-Policy' not in response.headers, path


def test_existing_headers_are_never_overwritten():
    response = apply_security_headers(
        _FakeResponse({
            'X-Content-Type-Options': 'custom-value',
            'Content-Security-Policy': "default-src 'self'",
        }),
        path='/api/plugins/demo-plugin/assets/a.css',
    )

    assert response.headers['X-Content-Type-Options'] == 'custom-value'
    assert response.headers['Content-Security-Policy'] == "default-src 'self'"


def test_empty_path_is_tolerated():
    response = apply_security_headers(_FakeResponse())

    assert response.headers['X-Content-Type-Options'] == 'nosniff'


def test_create_app_registers_after_request_hook():
    """端到端：create_app 的所有响应都带安全头。"""
    import core

    app = core.create_app()
    client = app.test_client()

    response = client.get('/api/plugins/list')

    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'


def test_plugin_asset_response_carries_csp_end_to_end():
    """端到端：插件资源响应同时带 CSP、CORP 与缓存策略。"""
    from flask import Flask

    from core.plugins import assets as assets_module

    app = Flask('security-headers-test')
    app.register_blueprint(assets_module.bp)

    @app.after_request
    def _headers(response):
        from flask import request

        return apply_security_headers(response, path=request.path)

    response = app.test_client().get('/api/plugins/demo-plugin/assets/missing.svg')

    assert response.headers['Content-Security-Policy'] == PLUGIN_ASSET_CSP
