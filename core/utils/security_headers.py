"""统一响应头加固（设计文档阶段 3「安全响应头」）。

分两层，都不依赖清理现有内联脚本：

1. **全局**：`X-Content-Type-Options: nosniff`（禁止 MIME 嗅探）与
   `Referrer-Policy: strict-origin-when-cross-origin`（跨站只带来源，不带路径）。
2. **插件资源**：`/api/plugins/<id>/assets/<path>` 的资源可能被直接导航打开
   （典型是 SVG），因此额外下发严格 CSP + `sandbox`，禁用脚本与表单。

**为什么不下发全站 CSP**：现有页面大量使用内联 `<script>` 与 `onclick`，
`default-src 'self'` 会直接破坏功能（设计文档阶段 3 已标注该前置条件）。
需要全站 CSP 时，先完成内联脚本外移，再在本模块中加 `Content-Security-Policy`。
"""

import logging

logger = logging.getLogger(__name__)

GLOBAL_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
}

# 插件静态资源：按「文档」处理（可能被 iframe / 直接导航加载）
PLUGIN_ASSET_CSP = (
    "default-src 'none'; "
    "img-src 'self' data:; "
    "style-src 'unsafe-inline'; "
    "font-src 'self'; "
    "sandbox"
)

PLUGIN_ASSET_PREFIX = '/api/plugins/'
PLUGIN_ASSET_MARKER = '/assets/'


def apply_security_headers(response, *, path: str = ''):
    """给响应补上安全头（已显式设置的同名头不会被覆盖）。"""
    for name, value in GLOBAL_HEADERS.items():
        response.headers.setdefault(name, value)

    request_path = str(path or '')
    if request_path.startswith(PLUGIN_ASSET_PREFIX) and PLUGIN_ASSET_MARKER in request_path:
        response.headers.setdefault('Content-Security-Policy', PLUGIN_ASSET_CSP)
        # 插件资源一律同源加载；禁止被其他站点内联引用
        response.headers.setdefault('Cross-Origin-Resource-Policy', 'same-origin')

    return response
