"""插件管理 API 蓝图（设计文档 9 / 10.4）。

统一响应格式（对齐既有约定）：
    { "success": true, ... } / { "success": false, "msg": "...", "error": "<code>" }

错误码见 `core/plugins/errors.py`，与 10.4 的表格一一对应。
"""

import functools
import json
import logging
import os
import queue
import re
import time

from flask import Blueprint, Response, jsonify, request

from core.data.ui_store import ENTRY_LAYOUT_KEY
from core.plugins import catalog, hooks, icons, installer, jobs, registry
from core.plugins import secrets as secrets_store
from core.plugins.errors import (
    PluginError,
    PluginJobNotFoundError,
    PluginNotFoundError,
    PluginSseLimitError,
)
from core.utils.paths import is_under_base

logger = logging.getLogger(__name__)

bp = Blueprint('plugins', __name__)

RESTART_REQUIRED_HINT = '插件已变更，重启应用后生效'

README_CANDIDATES = ('README.md', 'readme.md', 'README.MD', 'README.txt')
CHANGELOG_CANDIDATES = ('CHANGELOG.md', 'CHANGELOG.MD', 'changelog.md', 'CHANGELOG.txt')
MAX_DOCUMENT_BYTES = 256 * 1024

# 入口布局偏好：单个键与整份布局的体积上限，防止畸形前端撑爆 ui_data。
MAX_ENTRY_LAYOUT_BYTES = 64 * 1024
ENTRY_LAYOUT_KEYS = ('order', 'pinned', 'hidden', 'groups', 'shortcuts')


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


@bp.after_request
def _no_store_for_management_api(response):
    """插件管理接口一律不缓存：响应含配置、密钥掩码与运行状态。"""
    response.headers['Cache-Control'] = 'no-store'
    return response


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
    """已安装插件列表（含 enabled / load_error / 是否纯前端 / 重启提示）。

    条目（`entries`）与归属分级（`tier`）一并带出：前端入口注册表据此建表，
    不再依赖插件自行渲染浮层（D1 / D5）。
    """
    tiers = catalog.plugin_tiers()
    items = []
    for state in registry.list_states():
        payload = state.detail()
        payload['style_scope_errors'] = installer.read_style_scope_errors(state.plugin_id)
        payload['style_declaration_warnings'] = installer.read_style_declaration_warnings(
            state.plugin_id,
        )
        payload['tier'] = tiers.get(state.plugin_id, 'community')
        if state.load_error:
            payload['load_error'] = state.load_error
        items.append(payload)

    return jsonify({
        'success': True,
        'items': items,
        'plugins_dir': registry.plugins_dir(),
        'restart_hint': RESTART_REQUIRED_HINT,
    })


@bp.route('/api/plugins/ui-icons', methods=['GET'])
@_handle_plugin_errors
def list_ui_icons():
    """宿主图标名清单（D4）。

    插件用 `api.ui.icon(name)` 引用宿主图标；本接口让插件作者与设置页能查询
    合法名字。整表承诺 Stable：只增不改，删除/改名走 deprecation。
    """
    return jsonify({'success': True, 'icons': icons.list_host_icons()})


@bp.route('/api/plugins/ui-tokens', methods=['GET'])
@_handle_plugin_errors
def list_ui_tokens():
    """宿主 CSS 令牌清单（D12）。

    插件样式里 `var(--x)` 引用的令牌若不在本清单内且无回退值，安装期会被记为
    警告（不拒绝加载）。
    """
    return jsonify({'success': True, 'tokens': sorted(installer.resolve_known_tokens())})


# ------------------------------------------------------------------ 核心事件流


@bp.route('/api/plugins/events', methods=['GET'])
@_handle_plugin_errors
def stream_core_events():
    """核心事件的 SSE 流（设计文档 6.7）。

    背景：后端在 9 处核心流程末尾 `hooks.emit(...)`，但前端 `api.on()` 只做
    `window.addEventListener`，因此 `api.on('card.updated', h)` **永远不会被调用**；
    「扫描完成」「索引重建完毕」这类无 UI 触发的变更前端更是无从得知。

    约定：
    - **只广播 `CORE_EVENTS`**。插件的自定义事件（`<id>:` 前缀）不进这条流：
      那是插件间通信，语义是 best-effort、不保证顺序，不能靠广播流给强保证。
    - 一次连接服务一个插件的**全部**订阅（前端 `api.on()` 复用同一条流），
      因此配额按**连接数**计，与订阅数量无关。
    - 负载为 `{event, payload, ts}`，payload **原样**来自 `hooks.emit()`——
      这是广播信道，**不放**任何插件密钥或额外拼装的敏感内容。
    - 非核心事件名不接受（返回结构化 400，便于插件作者发现拼写错误）。
    """
    # 可选的事件名过滤：`?events=card.updated,scan.completed`（缺省 = 全部核心事件）
    raw_events = str(request.args.get('events') or '').strip()
    if raw_events:
        requested = [item.strip() for item in raw_events.split(',') if item.strip()]
        unknown = [item for item in requested if not hooks.is_core_event(item)]
        if unknown:
            return jsonify({
                'success': False,
                'msg': f'事件名不在核心事件集合内: {unknown}',
                'error': 'invalid_payload',
                'events': sorted(hooks.CORE_EVENTS),
            }), 400
        wanted = frozenset(requested)
    else:
        wanted = hooks.CORE_EVENTS

    bucket = hooks.subscribe_core_events()
    if bucket is None:
        # 超限时给结构化错误（429），**不静默挂住**——否则前端只会看到连接不动。
        stats = hooks.event_stream_stats()
        raise PluginSseLimitError(
            f'核心事件流连接数已达上限 {stats["max"]}，请稍后重试'
        )

    def generate():
        last_heartbeat = time.monotonic()
        try:
            # 首帧告诉客户端流已就绪（前端据此把「降级」提示收起来）
            yield jobs.sse_frame('ready', {
                'events': sorted(wanted),
                'heartbeat': hooks.EVENT_STREAM_HEARTBEAT_INTERVAL_SECONDS,
            })

            while True:
                try:
                    record = bucket.get(timeout=hooks.EVENT_STREAM_POLL_INTERVAL_SECONDS)
                except queue.Empty:
                    record = None

                # 被过滤掉的事件不提前 `continue`：否则该连接在高频无关事件下
                # 会一直有数据可取，心跳永远轮不到。
                if record is not None and record['event'] in wanted:
                    yield jobs.sse_frame(hooks.EVENT_STREAM_FRAME_NAME, record)
                    last_heartbeat = time.monotonic()
                    continue

                now = time.monotonic()
                if now - last_heartbeat >= hooks.EVENT_STREAM_HEARTBEAT_INTERVAL_SECONDS:
                    last_heartbeat = now
                    yield ': heartbeat\n\n'
        except GeneratorExit:  # 客户端断开
            raise
        except Exception:  # noqa: BLE001 - 流内异常不能让响应挂死
            logger.exception('核心事件流异常')
        finally:
            hooks.unsubscribe_core_events(bucket)

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive',
    })


# ------------------------------------------------------------------ 入口布局


def _sanitize_entry_layout(patch: dict) -> dict:
    """裁剪入口布局补丁：只保留已知键，单键不超过 64KB。"""
    cleaned = {}
    for key in ENTRY_LAYOUT_KEYS:
        if key not in patch:
            continue
        value = patch[key]
        if value is None:
            cleaned[key] = None
            continue
        try:
            encoded = json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            logger.warning('入口布局字段 %s 无法序列化，已忽略', key)
            continue
        if len(encoded.encode('utf-8')) > MAX_ENTRY_LAYOUT_BYTES:
            logger.warning('入口布局字段 %s 超出体积上限，已忽略', key)
            continue
        cleaned[key] = value
    return cleaned


def _read_entry_layout() -> dict:
    from core.data.ui_store import load_ui_data_or_empty

    layout = load_ui_data_or_empty().get(ENTRY_LAYOUT_KEY)
    return layout if isinstance(layout, dict) else {}


@bp.route('/api/plugins/entries/layout', methods=['GET'])
@_handle_plugin_errors
def get_entry_layout():
    """入口布局偏好（顺序 / 固定 / 隐藏 / 分组 / 快捷键）。

    宿主侧偏好，与插件本身无关：插件被禁用时入口消失但偏好保留，
    卸载时才由安装器剪除（D6）。
    """
    return jsonify({'success': True, 'layout': _read_entry_layout()})


@bp.route('/api/plugins/entries/layout', methods=['POST'])
@_handle_plugin_errors
def save_entry_layout():
    """合并写入入口布局偏好。

    只接受字符串键与 JSON 可序列化值；单键上限由 `_sanitize_entry_layout` 裁剪，
    避免一个畸形前端把 ui_data 撑爆。
    """
    body = request.get_json(silent=True) or {}
    patch = body.get('layout') if isinstance(body.get('layout'), dict) else body
    if not isinstance(patch, dict) or not patch:
        return jsonify({
            'success': False, 'msg': '没有需要保存的布局项', 'error': 'invalid_payload',
        }), 400

    cleaned = _sanitize_entry_layout(patch)
    if not cleaned:
        return jsonify({
            'success': False, 'msg': '没有需要保存的布局项', 'error': 'invalid_payload',
        }), 400

    def mutator(ui_data):
        layout = ui_data.get(ENTRY_LAYOUT_KEY)
        if not isinstance(layout, dict):
            layout = {}
            ui_data[ENTRY_LAYOUT_KEY] = layout
        layout.update(cleaned)

    from core.data.ui_store import update_ui_data

    if not update_ui_data(mutator):
        return jsonify({'success': False, 'msg': '布局保存失败', 'error': 'ui_data_write_failed'}), 500
    return jsonify({'success': True, 'layout': _read_entry_layout()})


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


# ------------------------------------------------------------------ 插件存储


def _read_storage(plugin_id: str) -> dict:
    entry = registry.read_ui_entry(plugin_id)
    bucket = entry.get('storage')
    return dict(bucket) if isinstance(bucket, dict) else {}


def _write_storage(plugin_id: str, bucket: dict) -> bool:
    """整体替换本插件的 storage 命名空间（前端已合并好再提交）。"""
    from core.data.ui_store import update_ui_data

    def mutator(ui_data):
        namespace = ui_data.get('_plugins_v1')
        if not isinstance(namespace, dict):
            namespace = {}
            ui_data['_plugins_v1'] = namespace
        entry = namespace.get(plugin_id)
        if not isinstance(entry, dict):
            entry = {}
            namespace[plugin_id] = entry
        entry['storage'] = dict(bucket)

    return bool(update_ui_data(mutator))


@bp.route('/api/plugins/<plugin_id>/storage', methods=['GET'])
@_handle_plugin_errors
def get_plugin_storage(plugin_id):
    """插件键值存储（`api.storage.*` 的持久化后端）。

    落在 `ui_data._plugins_v1.<id>.storage`，与 `config` / 作业数据同一命名空间，
    卸载时随 `_clear_ui_namespace` 一并清理。
    """
    _require_state(plugin_id)
    return jsonify({'success': True, 'storage': _read_storage(plugin_id)})


@bp.route('/api/plugins/<plugin_id>/storage', methods=['POST'])
@_handle_plugin_errors
def save_plugin_storage(plugin_id):
    """整体写入插件存储；受与 `api.ui_data_update` 相同的体积配额约束。

    请求体必须是 `{"storage": {...}}`。这里**不**像 config 那样回退到「整个 body
    就是载荷」：storage 是插件自由键值空间，回退会让 `{"storage": [1,2]}` 这种
    畸形请求被当成合法载荷写进去（键名恰好是 `storage`），语义太脆。
    """
    from core.plugins.api import PLUGIN_DATA_QUOTA_BYTES

    _require_state(plugin_id)
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict) or 'storage' not in body:
        return jsonify({
            'success': False, 'msg': '请求体缺少 storage 字段', 'error': 'invalid_payload',
        }), 400

    bucket = body.get('storage')
    if not isinstance(bucket, dict):
        return jsonify({'success': False, 'msg': '存储内容必须是对象', 'error': 'invalid_payload'}), 400

    try:
        size = len(json.dumps(bucket, ensure_ascii=False).encode('utf-8'))
    except (TypeError, ValueError):
        return jsonify({'success': False, 'msg': '存储内容无法序列化', 'error': 'invalid_payload'}), 400

    if size > PLUGIN_DATA_QUOTA_BYTES:
        return jsonify({
            'success': False,
            'msg': f'存储体积 {size} 字节，超过 {PLUGIN_DATA_QUOTA_BYTES} 字节上限',
            'error': 'quota_exceeded',
        }), 413

    if not _write_storage(plugin_id, bucket):
        return jsonify({'success': False, 'msg': '存储写入失败', 'error': 'ui_data_write_failed'}), 500
    return jsonify({'success': True, 'storage': _read_storage(plugin_id)})


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


@bp.route('/api/plugins/catalog/update', methods=['POST'])
@_handle_plugin_errors
def update_from_catalog():
    """把已安装插件更新到 catalog 指向的最新版本。

    实现即「重新安装」：`installer.install_from_catalog` 已经是
    「下载 → 校验 → 原子替换」，覆盖安装天然就是更新，无需单独的更新路径。
    参考 SillyTavern `POST /api/extensions/update`：那边用 `git pull`，
    本项目插件是解压目录（无 `.git`），所以走同一套归档替换。

    安全：`plugin_id` 必须**已安装**且在 catalog 里存在——否则用户可以用这个
    端点安装任意 catalog 条目（那是 `/catalog/install` 的职责，且它有自己的确认）。
    """
    body = request.get_json(silent=True) or {}
    plugin_id = str(body.get('id') or '').strip()
    if not plugin_id:
        return jsonify({'success': False, 'msg': '缺少插件 id', 'error': 'invalid_payload'}), 400

    state = registry.get_state(plugin_id)
    if state is None or state.manifest is None:
        return jsonify({
            'success': False,
            'msg': f'插件未安装: {plugin_id}',
            'error': 'plugin_not_installed',
        }), 404

    entry = catalog.find_catalog_entry(plugin_id)

    # 覆盖安装前记录版本，便于前端提示「vX → vY」
    previous_version = state.manifest.version

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
        'previous_version': previous_version,
        'msg': (
            f'已更新 {result["id"]} v{previous_version} → v{result["version"]}，'
            f'重启应用后生效'
        ),
    })


@bp.route('/api/plugins/install_upload', methods=['POST'])
@_handle_plugin_errors
def install_upload():
    """手动上传 zip 安装（离线兜底）。

    可选表单字段 `expected_id`：与 catalog 路径一致地绑定插件 id（D9.3）。
    留空表示不校验。
    """
    upload = request.files.get('file')
    if upload is None or not upload.filename:
        return jsonify({'success': False, 'msg': '未收到上传文件', 'error': 'invalid_payload'}), 400

    expected_id = str(request.form.get('expected_id') or '').strip()
    result = installer.install_from_upload(
        upload, source_label='upload', expected_id=expected_id,
    )
    return jsonify({
        'success': True,
        'restart_required': True,
        'result': result,
        'msg': f'已安装 {result["id"]} v{result["version"]}，重启应用后生效',
    })


@bp.route('/api/plugins/install_github', methods=['POST'])
@_handle_plugin_errors
def install_github():
    """从 GitHub 仓库安装：接受 `owner/repo` 或完整 https://github.com/owner/repo URL。"""
    body = request.get_json(silent=True) or {}
    repo_raw = str(body.get('repo') or '').strip()
    repo = _normalize_github_repo(repo_raw)
    ref = str(body.get('ref') or '').strip()
    subdir = str(body.get('subdir') or '').strip()

    from flask import current_app

    entry = {
        'id': repo.split('/')[-1],
        'source': {'type': 'github', 'repo': repo, 'ref': ref or 'main', 'subdir': subdir},
    }
    result = installer.install_from_catalog(
        current_app._get_current_object(),
        entry,
        ref=ref,
        subdir=subdir,
    )
    return jsonify({
        'success': True,
        'restart_required': True,
        'result': result,
        'msg': f'已安装 {result["id"]} v{result["version"]}，重启应用后生效',
    })


_GITHUB_URL_PATTERN = re.compile(
    r'^(?:https?://(?:www\.)?github\.com/|git@github\.com:)?'
    r'([A-Za-z0-9._-]+/[A-Za-z0-9._-]+?)(?:\.git)?/?$'
)


def _normalize_github_repo(raw: str) -> str:
    """把 GitHub URL 或 `owner/repo` 统一归一成 `owner/repo`，其它形式抛错。"""
    value = str(raw or '').strip()
    match = _GITHUB_URL_PATTERN.match(value)
    if match:
        return match.group(1)
    # 退到 owner/repo 直接校验（会在 validate_repo 里抛错）
    return value


def _read_plugin_document(plugin_dir: str, names) -> dict:
    """读取插件目录下的文档文件（固定文件名白名单 + realpath 边界检查）。"""
    plugin_dir = str(plugin_dir or '')
    if not plugin_dir or not os.path.isdir(plugin_dir):
        return {'found': False, 'name': '', 'content': '', 'truncated': False, 'msg': ''}

    for name in names:
        candidate = os.path.realpath(os.path.join(plugin_dir, name))
        if not is_under_base(candidate, plugin_dir, resolve_symlinks=True):
            continue
        if not os.path.isfile(candidate):
            continue

        try:
            size = os.path.getsize(candidate)
        except OSError:
            continue

        if size > MAX_DOCUMENT_BYTES:
            return {
                'found': True, 'name': name, 'content': '', 'truncated': True,
                'msg': f'文档超过 {MAX_DOCUMENT_BYTES // 1024}KB，已跳过',
            }

        try:
            with open(candidate, 'r', encoding='utf-8') as handle:
                content = handle.read()
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning('读取插件文档 %s 失败: %s', candidate, exc)
            return {'found': False, 'name': name, 'content': '', 'truncated': False, 'msg': str(exc)}

        return {'found': True, 'name': name, 'content': content, 'truncated': False, 'msg': ''}

    return {'found': False, 'name': '', 'content': '', 'truncated': False, 'msg': ''}


@bp.route('/api/plugins/<plugin_id>/readme', methods=['GET'])
@_handle_plugin_errors
def get_plugin_readme(plugin_id):
    """插件文档：README 与 CHANGELOG。

    `.md` 不在插件资源路由的白名单内（8.5），因此文档单独提供，
    只读插件根目录下的固定文件名。
    """
    state = _require_state(plugin_id)

    return jsonify({
        'success': True,
        'readme': _read_plugin_document(state.plugin_dir, README_CANDIDATES),
        'changelog': _read_plugin_document(state.plugin_dir, CHANGELOG_CANDIDATES),
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
    detail = jobs.get_job_detail(run_id, plugin_id=plugin_id)
    if detail is None:
        raise PluginJobNotFoundError(f'作业不存在: {run_id}')
    return jsonify({'success': True, 'job': detail})


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>/events', methods=['GET'])
@_handle_plugin_errors
def stream_plugin_job_events(plugin_id, run_id):
    """SSE 事件流（`Last-Event-ID` 断线续传）。"""
    _require_state(plugin_id)

    raw_last_id = request.headers.get('Last-Event-ID', '0')
    try:
        last_event_id = int(raw_last_id)
    except (TypeError, ValueError):
        last_event_id = 0

    # 归属校验在 jobs.stream_job_events 内完成（返回 job_not_found 的 done 帧）
    return jobs.stream_job_events(run_id, last_event_id=last_event_id, plugin_id=plugin_id)


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>/cancel', methods=['POST'])
@_handle_plugin_errors
def cancel_plugin_job(plugin_id, run_id):
    _require_state(plugin_id)
    return jsonify({'success': jobs.cancel_job(run_id, plugin_id=plugin_id)})


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>/pause', methods=['POST'])
@_handle_plugin_errors
def pause_plugin_job(plugin_id, run_id):
    _require_state(plugin_id)
    return jsonify({'success': jobs.pause_job(run_id, plugin_id=plugin_id)})


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>/resume', methods=['POST'])
@_handle_plugin_errors
def resume_plugin_job(plugin_id, run_id):
    _require_state(plugin_id)
    return jsonify({'success': jobs.resume_job(run_id, plugin_id=plugin_id)})


@bp.route('/api/plugins/<plugin_id>/jobs/<run_id>/retry', methods=['POST'])
@_handle_plugin_errors
def retry_plugin_job(plugin_id, run_id):
    _require_state(plugin_id)
    body = request.get_json(silent=True) or {}
    only_failed = body.get('only_failed', True)
    new_run = jobs.retry_job(run_id, only_failed=bool(only_failed), plugin_id=plugin_id)
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
        plugin_id=plugin_id,
    )
    return jsonify({'success': True})
