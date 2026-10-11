"""插件静态资源路由（设计文档 8.5）。

安全要求：
- `plugin_id` 正则校验（路径安全第一道闸门）。
- `os.path.realpath` 边界检查，**复用** `core/utils/paths.py:is_under_base()`，
  不再新增第 5 份 `_is_under_base`。
- 扩展名白名单：`.js/.mjs/.css/.svg/.png/.webp/.gif/.avif/.json/.woff2/.map`。
  **不提供** `.py`、`.md`、`.env` 等。
- 响应头 `Cache-Control: private, no-cache`：**必须先向服务器校验**才能复用。
  这里刻意**不用** `immutable` / 长 `max-age`（曾经是
  `private, max-age=31536000, immutable`），因为那个策略的前提不成立：

  版本参数 `?v=<插件版本>` 由 `pluginHost.js:withAssetVersion` 加在**入口** URL 上，
  但 ES 模块的相对 import **不继承查询串**：

      new URL('./panel.js', '.../plugin.js?v=0.1.0').href  →  '.../panel.js'

  实测（真实 Chrome）插件 6 个子模块的请求 URL 全都不带 `?v=`：
  `panel.js` / `petview.js` / `announce.js` / `clock.js` / `physics.js` /
  `statemachine.js`。这些 URL **恒定不变**，一旦给了 `immutable` 就是永久缓存 ——
  改代码、**重装插件**、甚至硬刷新都可能仍执行旧模块（实测复现：改磁盘代码后
  普通刷新仍是旧代码）。

  改成 `no-cache` 后：`conditional=True` + ETag / Last-Modified 仍然生效，
  内容未变时返回 **304 无响应体**，代价只有一次条件请求 —— 对本地桌面应用
  可以忽略，而正确性拿回来了。
- `conditional=True` 让 ETag / `Last-Modified` 真正生效（`If-None-Match` → 304），
  并顺带支持 `Range` 请求（`Accept-Ranges: bytes`）。
- 响应头 `Content-Security-Policy`（严格 + `sandbox`）与 `Cross-Origin-Resource-Policy`：
  资源可能被直接导航打开（典型是 SVG），见 `core/utils/security_headers.py`。
"""

import logging
import mimetypes
import os
import re

from flask import Blueprint, jsonify, request, send_file

from core.plugins import registry
from core.utils.paths import is_under_base
from core.utils.security_headers import apply_security_headers

logger = logging.getLogger(__name__)

PLUGIN_ID_PATTERN = re.compile(r'^[a-z][a-z0-9-]{1,63}$')

ALLOWED_EXTENSIONS = frozenset({
    '.js', '.mjs', '.css', '.svg', '.png', '.webp', '.gif', '.avif', '.json', '.woff2', '.map',
})

DEFAULT_MIME_TYPES = {
    '.js': 'text/javascript; charset=utf-8',
    '.mjs': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.webp': 'image/webp',
    '.gif': 'image/gif',
    '.avif': 'image/avif',
    '.json': 'application/json; charset=utf-8',
    '.woff2': 'font/woff2',
    '.map': 'application/json; charset=utf-8',
}

# 资产必须**先校验**才能复用（`no-cache`）。
#
# 曾经是 `private, max-age=31536000, immutable`，前提是「URL 带 `?v=<插件版本>`，
# 版本变化即 URL 变化」。但该前提对 **ES 模块的子导入不成立** —— 查询串不会被
# 相对 import 继承（`new URL('./panel.js', '.../plugin.js?v=0.1.0')` → `'.../panel.js'`），
# 实测插件 6 个子模块的请求 URL 全都不带 `?v=` 且恒定不变。
# 于是 `immutable` 让它们**永久缓存**：改代码、重装插件、硬刷新都可能仍跑旧模块。
#
# 改 `no-cache` 后配合 `conditional=True`，内容未变时仍是 **304 无响应体**，
# 代价只有一次条件请求；本地桌面应用完全可以忽略，正确性则是必须的。
ASSET_CACHE_CONTROL = 'private, no-cache'

bp = Blueprint('plugin_assets', __name__)


@bp.after_request
def _asset_security_headers(response):
    """资源路由自带加固：蓝图被单独挂载（测试或嵌入）时也不失保护。"""
    return apply_security_headers(response, path=request.path)


def _plugin_dir(plugin_id: str) -> str:
    """已安装插件的目录；未安装或目录缺失时返回空串。"""
    state = registry.get_state(plugin_id)
    if state is not None and state.plugin_dir and os.path.isdir(state.plugin_dir):
        return state.plugin_dir

    candidate = os.path.join(registry.plugins_dir(), plugin_id)
    return candidate if os.path.isdir(candidate) else ''


def _resolve_asset_path(plugin_dir: str, filename: str) -> str:
    """把请求路径解析为插件目录内的绝对路径；非法时返回空串。"""
    relative = str(filename or '').replace('\\', '/').strip()
    if not relative or relative.startswith('/'):
        return ''
    if '..' in relative.split('/'):
        return ''

    extension = os.path.splitext(relative)[1].lower()
    if extension not in ALLOWED_EXTENSIONS:
        return ''

    target = os.path.realpath(os.path.join(plugin_dir, relative.replace('/', os.sep)))
    if not is_under_base(target, plugin_dir, resolve_symlinks=True):
        return ''
    if not os.path.isfile(target):
        return ''
    return target


@bp.route('/api/plugins/<plugin_id>/assets/<path:filename>', methods=['GET'])
def get_plugin_asset(plugin_id: str, filename: str):
    """返回插件内的静态资源。"""
    plugin_id = str(plugin_id or '')
    if not PLUGIN_ID_PATTERN.match(plugin_id):
        return jsonify({'success': False, 'msg': '插件 id 非法', 'error': 'plugin_not_found'}), 404

    plugin_dir = _plugin_dir(plugin_id)
    if not plugin_dir:
        return jsonify({'success': False, 'msg': '插件不存在', 'error': 'plugin_not_found'}), 404

    target = _resolve_asset_path(plugin_dir, filename)
    if not target:
        return jsonify({'success': False, 'msg': '资源不存在或类型不受支持', 'error': 'plugin_asset_invalid'}), 404

    extension = os.path.splitext(target)[1].lower()
    mime_type = DEFAULT_MIME_TYPES.get(extension) or mimetypes.guess_type(target)[0] or 'application/octet-stream'

    try:
        # conditional=True 才会处理 If-None-Match / If-Modified-Since（304）与 Range 请求。
        response = send_file(target, mimetype=mime_type, conditional=True)
    except OSError as exc:
        logger.warning('插件 %s 的资源读取失败 %s: %s', plugin_id, target, exc)
        return jsonify({'success': False, 'msg': '资源读取失败', 'error': 'plugin_asset_invalid'}), 404

    response.headers['Cache-Control'] = ASSET_CACHE_CONTROL
    return response
