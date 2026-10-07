"""插件静态资源路由（设计文档 8.5）。

安全要求：
- `plugin_id` 正则校验（路径安全第一道闸门）。
- `os.path.realpath` 边界检查，**复用** `core/utils/paths.py:is_under_base()`，
  不再新增第 5 份 `_is_under_base`。
- 扩展名白名单：`.js/.mjs/.css/.svg/.png/.webp/.json/.woff2/.map`。
  **不提供** `.py`、`.md`、`.env` 等。
- 响应头 `Cache-Control: no-cache`（开发期语义；生产可按 manifest 版本加 `?v=`）。
"""

import logging
import mimetypes
import os
import re

from flask import Blueprint, jsonify, send_file

from core.plugins import registry
from core.utils.paths import is_under_base

logger = logging.getLogger(__name__)

PLUGIN_ID_PATTERN = re.compile(r'^[a-z][a-z0-9-]{1,63}$')

ALLOWED_EXTENSIONS = frozenset({
    '.js', '.mjs', '.css', '.svg', '.png', '.webp', '.json', '.woff2', '.map',
})

DEFAULT_MIME_TYPES = {
    '.js': 'text/javascript; charset=utf-8',
    '.mjs': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.svg': 'image/svg+xml',
    '.png': 'image/png',
    '.webp': 'image/webp',
    '.json': 'application/json; charset=utf-8',
    '.woff2': 'font/woff2',
    '.map': 'application/json; charset=utf-8',
}

bp = Blueprint('plugin_assets', __name__)


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
        response = send_file(target, mimetype=mime_type, conditional=False, max_age=0)
    except OSError as exc:
        logger.warning('插件 %s 的资源读取失败 %s: %s', plugin_id, target, exc)
        return jsonify({'success': False, 'msg': '资源读取失败', 'error': 'plugin_asset_invalid'}), 404

    response.headers['Cache-Control'] = 'no-cache'
    return response
