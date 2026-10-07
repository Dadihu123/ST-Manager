"""插件管理 API 蓝图（设计文档 9 / 10.4）。

统一响应格式（对齐既有约定）：
    { "success": true, ... } / { "success": false, "msg": "...", "error": "<code>" }

错误码见 `core/plugins/errors.py`，与 10.4 的表格一一对应。
"""

import functools
import logging

from flask import Blueprint, jsonify, request

from core.plugins import catalog, installer, jobs, registry
from core.plugins import secrets as secrets_store
from core.plugins.errors import PluginError, PluginNotFoundError

logger = logging.getLogger(__name__)

bp = Blueprint('plugins', __name__)

RESTART_REQUIRED_HINT = '插件已变更，重启应用后生效'


def _handle_plugin_errors(func):
    """把插件异常映射为结构化 JSON 错误。"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except PluginError as exc:
            logger.warning('插件接口 %s 失败: %s', func.__name__, exc.message)
            return jsonify(exc.to_dict()), exc.http_status
        except Exception as exc:  # noqa: BLE001 - 不让 traceback 泄漏到响应
            logger.exception('插件接口 %s 未预期异常', func.__name__)
            return jsonify({'success': False, 'msg': str(exc), 'error': 'internal_error'}), 500

    return wrapper


def _require_state(plugin_id: str):
    state = registry.get_state(plugin_id)
    if state is None:
        raise PluginNotFoundError(f'插件不存在: {plugin_id}')
    return state


def _read_config(plugin_id: str) -> dict:
    manifest = registry.get_manifest(plugin_id)
    config = {}
    if manifest is not None:
        for key, spec in ((manifest.config_schema or {}).get('properties') or {}).items():
            if isinstance(spec, dict) and 'default' in spec:
                config[key] = spec['default']

    entry = registry.read_ui_entry(plugin_id)
    stored = entry.get('config')
    if isinstance(stored, dict):
        config.update(stored)
    return config


def _write_config(plugin_id: str, patch: dict) -> bool:
    if not isinstance(patch, dict) or not patch:
        return False

    manifest = registry.get_manifest(plugin_id)
    allowed = set(((manifest.config_schema or {}).get('properties') or {}).keys()) if manifest else set()
    filtered = {key: value for key, value in patch.items() if key in allowed} if allowed else dict(patch)
    if not filtered:
        return False

    def mutator(ui_data):
        namespace = ui_data.get('_plugins_v1')
        if not isinstance(namespace, dict):
            namespace = {}
            ui_data['_plugins_v1'] = namespace
        entry = namespace.get(plugin_id)
        if not isinstance(entry, dict):
            entry = {}
            namespace[plugin_id] = entry
        current = entry.get('config')
        merged = dict(current) if isinstance(current, dict) else {}
        merged.update(filtered)
        entry['config'] = merged

    from core.data.ui_store import update_ui_data

    return bool(update_ui_data(mutator))


# ------------------------------------------------------------------ 已安装


@bp.route('/api/plugins/list', methods=['GET'])
@_handle_plugin_errors
def list_plugins():
    """已安装插件列表（含 enabled / load_error / 是否纯前端 / 重启提示）。"""
    items = []
    for state in registry.list_states():
        payload = state.detail()
        payload['style_scope_errors'] = installer.read_style_scope_errors(state.plugin_id)
        if state.load_error:
            payload['load_error'] = state.load_error
        items.append(payload)

    return jsonify({
        'success': True,
        'items': items,
        'plugins_dir': registry.plugins_dir(),
        'restart_hint': RESTART_REQUIRED_HINT,
    })


@bp.route('/api/plugins/<plugin_id>/config', methods=['GET'])
@_handle_plugin_errors
def get_plugin_config(plugin_id):
    _require_state(plugin_id)
    return jsonify({'success': True, 'config': _read_config(plugin_id)})


@bp.route('/api/plugins/<plugin_id>/config', methods=['POST'])
@_handle_plugin_errors
def save_plugin_config(plugin_id):
    _require_state(plugin_id)
    body = request.get_json(silent=True) or {}
    patch = body.get('config') if isinstance(body.get('config'), dict) else body
    if not _write_config(plugin_id, patch):
        return jsonify({'success': False, 'msg': '没有可保存的配置项', 'error': 'invalid_payload'}), 400
    return jsonify({'success': True, 'config': _read_config(plugin_id)})


@bp.route('/api/plugins/<plugin_id>/secrets', methods=['GET'])
@_handle_plugin_errors
def get_plugin_secrets(plugin_id):
    state = _require_state(plugin_id)
    schema = state.manifest.secret_schema if state.manifest else {}
    return jsonify({
        'success': True,
        'secrets': secrets_store.describe_secrets(plugin_id, schema),
    })


@bp.route('/api/plugins/<plugin_id>/secrets', methods=['POST'])
@_handle_plugin_errors
def save_plugin_secrets(plugin_id):
    _require_state(plugin_id)
    body = request.get_json(silent=True) or {}
    payload = body.get('secrets') if isinstance(body.get('secrets'), dict) else body
    if not isinstance(payload, dict) or not payload:
        return jsonify({'success': False, 'msg': '没有需要写入的密钥项', 'error': 'invalid_payload'}), 400

    if secrets_store.is_degraded():
        return jsonify({
            'success': False,
            'msg': '密钥文件当前不可读，已拒绝写入以保护既有数据',
            'error': 'secret_read_failed',
        }), 503

    failed = []
    for key, value in payload.items():
        if not secrets_store.set_secret(plugin_id, str(key), value):
            failed.append(str(key))

    if failed:
        return jsonify({'success': False, 'msg': f'写入失败: {failed}', 'error': 'secret_write_failed'}), 500
    return jsonify({'success': True})


@bp.route('/api/plugins/<plugin_id>/secrets/<key>', methods=['DELETE'])
@_handle_plugin_errors
def delete_plugin_secret(plugin_id, key):
    _require_state(plugin_id)
    if not secrets_store.delete_secret(plugin_id, key):
        return jsonify({'success': False, 'msg': '清除失败', 'error': 'secret_write_failed'}), 500
    return jsonify({'success': True})


# ------------------------------------------------------------------ 生命周期


@bp.route('/api/plugins/<plugin_id>/enable', methods=['POST'])
@_handle_plugin_errors
def enable_plugin(plugin_id):
    """启用插件（后端插件需重启生效）。"""
    state = _require_state(plugin_id)
    registry.set_enabled_setting(plugin_id, True)
    restart_required = bool(state.has_backend)
    registry.set_restart_required(plugin_id, restart_required)
    installer._log_action(plugin_id, 'enable', source='local', detail={'restart_required': restart_required})
    return jsonify({
        'success': True,
        'restart_required': restart_required,
        'msg': RESTART_REQUIRED_HINT if restart_required else '已启用',
    })


@bp.route('/api/plugins/<plugin_id>/disable', methods=['POST'])
@_handle_plugin_errors
def disable_plugin(plugin_id):
    """禁用插件：保留代码，但重启后完全不加载（D9）。"""
    state = _require_state(plugin_id)
    cancelled = installer.cancel_plugin_jobs(plugin_id)
    registry.set_enabled_setting(plugin_id, False)
    restart_required = bool(state.has_backend)
    registry.set_restart_required(plugin_id, restart_required)
    installer._log_action(
        plugin_id, 'disable', source='local',
        detail={'restart_required': restart_required, 'cancelled_jobs': cancelled},
    )
    return jsonify({
        'success': True,
        'restart_required': restart_required,
        'cancelled_jobs': cancelled,
        'msg': RESTART_REQUIRED_HINT if restart_required else '已禁用',
    })


@bp.route('/api/plugins/uninstall', methods=['POST'])
@_handle_plugin_errors
def uninstall_plugin():
    """卸载插件（目录进回收站；默认清理 ui_data 命名空间与密钥）。"""
    body = request.get_json(silent=True) or {}
    plugin_id = str(body.get('id') or '').strip()
    _require_state(plugin_id)
    result = installer.uninstall_plugin(plugin_id, keep_data=bool(body.get('keep_data')))
    return jsonify({
        'success': True,
        'restart_required': True,
        'result': result,
        'msg': f'已卸载 {plugin_id}，重启应用后完全移除',
    })


# ------------------------------------------------------------------ 目录与安装


@bp.route('/api/plugins/catalog', methods=['GET'])
@_handle_plugin_errors
def get_catalog():
    """官方插件目录（远端优先，失败回退包内清单）。"""
    refresh = str(request.args.get('refresh') or '').lower() in ('1', 'true', 'yes')
    payload = catalog.get_catalog(refresh=refresh)
    installed = {state.plugin_id: state.header for state in registry.list_states()}

    items = []
    for entry in payload.get('items') or []:
        item = dict(entry)
        current = installed.get(entry['id'])
        item['installed'] = bool(current and current.get('installed'))
        item['installed_version'] = current.get('version', '') if current else ''
        items.append(item)

    return jsonify({
        'success': True,
        'items': items,
        'source': payload.get('source', ''),
        'offline': payload.get('offline', False),
        'updated_at': payload.get('updated_at', ''),
        'msg': payload.get('msg', ''),
    })


@bp.route('/api/plugins/catalog/install', methods=['POST'])
@_handle_plugin_errors
def install_from_catalog():
    body = request.get_json(silent=True) or {}
    plugin_id = str(body.get('id') or '').strip()
    entry = catalog.find_catalog_entry(plugin_id)

    from flask import current_app

    result = installer.install_from_catalog(
        current_app._get_current_object(),
        entry,
        ref=str(body.get('ref') or ''),
        subdir=str(body.get('subdir') or ''),
    )
    return jsonify({
        'success': True,
        'restart_required': True,
        'result': result,
        'msg': f'已安装 {result["id"]} v{result["version"]}，重启应用后生效',
    })


@bp.route('/api/plugins/catalog/check_updates', methods=['POST'])
@_handle_plugin_errors
def check_catalog_updates():
    body = request.get_json(silent=True) or {}
    payload = catalog.check_updates(force=bool(body.get('force')))
    return jsonify({'success': True, **payload})


@bp.route('/api/plugins/install_upload', methods=['POST'])
@_handle_plugin_errors
def install_upload():
    """手动上传 zip 安装（离线兜底）。"""
    upload = request.files.get('file')
    if upload is None or not upload.filename:
        return jsonify({'success': False, 'msg': '未收到上传文件', 'error': 'invalid_payload'}), 400

    result = installer.install_from_upload(upload, source_label='upload')
    return jsonify({
        'success': True,
        'restart_required': True,
        'result': result,
        'msg': f'已安装 {result["id"]} v{result["version"]}，重启应用后生效',
    })


# ------------------------------------------------------------------ 作业


@bp.route('/api/plugins/<plugin_id>/jobs', methods=['GET'])
@_handle_plugin_errors
def list_plugin_jobs(plugin_id):
    _require_state(plugin_id)
    limit = max(1, min(int(request.args.get('limit', 50) or 50), 200))
    offset = max(0, int(request.args.get('offset', 0) or 0))
    statuses = [item for item in (request.args.get('status') or '').split(',') if item]
    payload = jobs.list_plugin_jobs(plugin_id, limit=limit, offset=offset, statuses=statuses or None)
    return jsonify({'success': True, **payload})


@bp.route('/api/plugins/<plugin_id>/jobs', methods=['POST'])
@_handle_plugin_errors
def create_plugin_job(plugin_id):
    """创建作业（服务端已注册处理器时使用；插件自身的 HTTP 接口更常见）。"""
    _require_state(plugin_id)
    body = request.get_json(silent=True) or {}
    job_type = str(body.get('job_type') or '').strip()
    items = body.get('items')
    payload = body.get('payload') if isinstance(body.get('payload'), dict) else {}

    run_id = jobs.submit_job(plugin_id, job_type, items, payload)
    return jsonify({'success': True, 'run_id': run_id})


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>', methods=['GET'])
@_handle_plugin_errors
def get_plugin_job(plugin_id, run_id):
    _require_state(plugin_id)
    detail = jobs.get_job_detail(run_id)
    if not detail or detail.get('plugin_id') != plugin_id:
        from core.plugins.errors import PluginJobNotFoundError

        raise PluginJobNotFoundError(f'作业不存在: {run_id}')
    return jsonify({'success': True, 'job': detail})


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>/events', methods=['GET'])
@_handle_plugin_errors
def stream_plugin_job_events(plugin_id, run_id):
    """SSE 事件流（`Last-Event-ID` 断线续传）。"""
    _require_state(plugin_id)
    detail = jobs.get_job_detail(run_id, items_limit=1, items_offset=0)
    if not detail or detail.get('plugin_id') != plugin_id:
        from core.plugins.errors import PluginJobNotFoundError

        raise PluginJobNotFoundError(f'作业不存在: {run_id}')

    raw_last_id = request.headers.get('Last-Event-ID', '0')
    try:
        last_event_id = int(raw_last_id)
    except (TypeError, ValueError):
        last_event_id = 0

    return jobs.stream_job_events(run_id, last_event_id=last_event_id)


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>/cancel', methods=['POST'])
@_handle_plugin_errors
def cancel_plugin_job(plugin_id, run_id):
    _require_state(plugin_id)
    return jsonify({'success': jobs.cancel_job(run_id)})


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>/pause', methods=['POST'])
@_handle_plugin_errors
def pause_plugin_job(plugin_id, run_id):
    _require_state(plugin_id)
    return jsonify({'success': jobs.pause_job(run_id)})


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>/resume', methods=['POST'])
@_handle_plugin_errors
def resume_plugin_job(plugin_id, run_id):
    _require_state(plugin_id)
    return jsonify({'success': jobs.resume_job(run_id)})


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>/retry', methods=['POST'])
@_handle_plugin_errors
def retry_plugin_job(plugin_id, run_id):
    _require_state(plugin_id)
    body = request.get_json(silent=True) or {}
    only_failed = body.get('only_failed', True)
    new_run = jobs.retry_job(run_id, only_failed=bool(only_failed))
    return jsonify({'success': True, 'run_id': new_run})


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>/items/<item_key>/review', methods=['POST'])
@_handle_plugin_errors
def review_plugin_job_item(plugin_id, run_id, item_key):
    """逐条审批（D6）。"""
    _require_state(plugin_id)
    body = request.get_json(silent=True) or {}
    status = str(body.get('status') or 'done').strip()
    jobs.review_item(
        run_id, item_key,
        status=status,
        result=body.get('result'),
        error=str(body.get('error') or ''),
    )
    return jsonify({'success': True})
