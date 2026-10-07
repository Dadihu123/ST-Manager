"""插件发现、加载与失败隔离（设计文档 4.2–4.5）。

加载策略：
- 用 `importlib.util.spec_from_file_location` + `MODULE_PREFIX` 显式构造模块，
  **不注入 `sys.path`**，否则多个插件的 `backend/` 包会互相覆盖。
- 逐插件 `try/except`：任何单个插件失败都不得中断 `create_app()`。
- `enabled` 只在 `load_all()` 时从 `ui_data._plugins_v1.<id>.enabled` 读一次。
- 失败原因持久化到 `ui_data._plugins_v1.<id>.load_error`，供管理 UI 展示。
"""

import importlib.util
import logging
import os
import sys
import threading
import traceback

from core.config import DATA_DIR
from core.data.ui_store import load_ui_data_or_empty, update_ui_data
from core.plugins.api import PluginAPI
from core.plugins.errors import PluginApiVersionError, PluginLoadError, PluginManifestError
from core.plugins.manifest import PLUGIN_ID_PATTERN, PluginManifest

logger = logging.getLogger(__name__)

MODULE_PREFIX = 'st_plugin_'
PLUGINS_DIRNAME = 'plugins'
PLUGIN_UI_NAMESPACE = '_plugins_v1'


class PluginState:
    """单个插件的运行时状态（供管理 UI 与内部查询）。"""

    __slots__ = (
        'plugin_id', 'plugin_dir', 'enabled', 'loaded', 'load_error',
        'manifest', 'api', 'module', 'restart_required', 'warnings',
    )

    def __init__(self, plugin_id: str, plugin_dir: str = ''):
        self.plugin_id = plugin_id
        self.plugin_dir = plugin_dir
        self.enabled = True
        self.loaded = False
        self.load_error = ''
        self.manifest = None
        self.api = None
        self.module = None
        self.restart_required = False
        self.warnings = []

    @property
    def has_backend(self) -> bool:
        return bool(self.manifest and self.manifest.has_backend)

    @property
    def has_frontend(self) -> bool:
        return bool(self.manifest and self.manifest.has_frontend)

    @property
    def header(self) -> dict:
        manifest = self.manifest
        return {
            'id': self.plugin_id,
            'name': manifest.name if manifest else self.plugin_id,
            'version': manifest.version if manifest else '',
            'enabled': bool(self.enabled),
            'loaded': bool(self.loaded),
            'backend': bool(manifest and manifest.has_backend),
            'frontend': bool(manifest and manifest.has_frontend),
            'frontend_only': bool(manifest and manifest.is_frontend_only),
            'permissions': list(manifest.permissions) if manifest else [],
            'load_error': self.load_error,
            'restart_required': bool(self.restart_required),
            'warnings': list(self.warnings or []),
            'author': manifest.author if manifest else '',
            'description': manifest.description if manifest else '',
            'homepage': manifest.homepage if manifest else '',
            'icon': manifest.icon if manifest else '',
            'installed': bool(manifest),
        }

    def detail(self) -> dict:
        payload = self.header
        if self.manifest:
            payload['manifest'] = self.manifest.to_dict()
        return payload


_states = {}
_states_lock = threading.RLock()
_states_initialized = False


def plugins_dir() -> str:
    """插件根目录 `data/plugins/`。"""
    return os.path.join(str(DATA_DIR), PLUGINS_DIRNAME)


def discover_plugin_dirs() -> list:
    """扫描插件根目录，返回形如 `data/plugins/<id>` 的目录列表（按名称排序）。"""
    root = plugins_dir()
    if not os.path.isdir(root):
        return []

    found = []
    try:
        entries = sorted(os.listdir(root))
    except OSError as exc:
        logger.warning('读取插件目录失败: %s', exc)
        return []

    for name in entries:
        if not PLUGIN_ID_PATTERN.match(name):
            continue
        full_path = os.path.join(root, name)
        if not os.path.isdir(full_path):
            continue
        found.append(full_path)
    return found


# ------------------------------------------------------------------ 状态访问


def _read_enabled_map() -> dict:
    """一次性读取各插件的 enabled 标志（缺省 true）。"""
    ui_data = load_ui_data_or_empty()
    namespace = ui_data.get(PLUGIN_UI_NAMESPACE)
    if not isinstance(namespace, dict):
        return {}

    result = {}
    for plugin_id, entry in namespace.items():
        if not isinstance(entry, dict):
            continue
        result[str(plugin_id)] = bool(entry.get('enabled', True))
    return result


def _read_ui_entry(plugin_id: str) -> dict:
    ui_data = load_ui_data_or_empty()
    namespace = ui_data.get(PLUGIN_UI_NAMESPACE)
    if not isinstance(namespace, dict):
        return {}
    entry = namespace.get(plugin_id)
    return entry if isinstance(entry, dict) else {}


def _persist_ui_entry(plugin_id: str, patch: dict) -> bool:
    if not patch:
        return True

    def mutator(ui_data):
        namespace = ui_data.get(PLUGIN_UI_NAMESPACE)
        if not isinstance(namespace, dict):
            namespace = {}
            ui_data[PLUGIN_UI_NAMESPACE] = namespace
        entry = namespace.get(plugin_id)
        if not isinstance(entry, dict):
            entry = {}
            namespace[plugin_id] = entry
        entry.update(patch)

    return bool(update_ui_data(mutator))


def _persist_load_error(plugin_id: str, error: str) -> None:
    current = _read_ui_entry(plugin_id)
    if current.get('load_error', '') == error:
        return
    _persist_ui_entry(plugin_id, {'load_error': error})


def get_state(plugin_id: str):
    with _states_lock:
        return _states.get(str(plugin_id or ''))


def read_ui_entry(plugin_id: str) -> dict:
    """读取 `ui_data._plugins_v1.<id>`（公开入口，供路由层复用）。"""
    return _read_ui_entry(str(plugin_id or ''))


def get_api(plugin_id: str):
    state = get_state(plugin_id)
    return state.api if state is not None else None


def get_manifest(plugin_id: str):
    state = get_state(plugin_id)
    return state.manifest if state is not None else None


def list_states() -> list:
    with _states_lock:
        return [state for _, state in sorted(_states.items())]


def is_loaded(plugin_id: str) -> bool:
    state = get_state(plugin_id)
    return bool(state and state.loaded)


def set_enabled(plugin_id: str, enabled: bool) -> bool:
    """写入 enabled 标志（只影响下次启动的加载行为）。"""
    return _persist_ui_entry(str(plugin_id or ''), {'enabled': bool(enabled)})


def set_restart_required(plugin_id: str, flag: bool) -> None:
    plugin_id = str(plugin_id or '')
    with _states_lock:
        state = _states.get(plugin_id)
        if state is not None:
            state.restart_required = bool(flag)
    _persist_ui_entry(plugin_id, {'restart_required': bool(flag)})


def set_enabled_setting(plugin_id: str, enabled: bool) -> bool:
    """写 enabled 并同步运行时状态（仅内存，重启后生效）。"""
    ok = set_enabled(plugin_id, enabled)
    with _states_lock:
        state = _states.get(plugin_id)
        if state is not None:
            state.enabled = bool(enabled)
    return ok


def drop_state(plugin_id: str) -> None:
    """卸载后清理运行时状态与订阅。"""
    from core.plugins import hooks, jobs

    plugin_id = str(plugin_id or '')
    hooks.unregister_plugin(plugin_id)
    jobs.unregister_plugin_handlers(plugin_id)

    with _states_lock:
        _states.pop(plugin_id, None)


def register_external_state(state: PluginState) -> None:
    """登记一个未加载成功的插件状态（安装后尚未重启时展示用）。"""
    with _states_lock:
        _states[state.plugin_id] = state


def reset_for_tests() -> None:
    """清空全部状态（仅测试用）。"""
    global _states_initialized
    with _states_lock:
        _states.clear()
        _states_initialized = False


# ------------------------------------------------------------------ 加载


def _build_module_name(plugin_id: str) -> str:
    return f'{MODULE_PREFIX}{plugin_id.replace("-", "_")}'


def _load_backend_module(manifest: PluginManifest):
    """把 `data/plugins/<id>/backend/` 加载为独立模块 `st_plugin_<id>`。"""
    package_path = manifest.backend_entry
    init_py = os.path.join(package_path, '__init__.py')
    if not os.path.isfile(init_py):
        raise PluginManifestError(f'{init_py} 不存在')

    module_name = _build_module_name(manifest.plugin_id)
    spec = importlib.util.spec_from_file_location(
        module_name,
        init_py,
        submodule_search_locations=[package_path],
    )
    if spec is None or spec.loader is None:
        raise PluginManifestError(f'无法为插件 {manifest.plugin_id} 构造模块 spec')

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # 加载失败不留残骸，避免下次加载命中半初始化的模块
        sys.modules.pop(module_name, None)
        raise
    return module


def _instantiate_plugin(app, manifest: PluginManifest):
    """执行插件的 `register(api)`。"""
    api = PluginAPI(manifest, app)
    module = _load_backend_module(manifest)

    register_func = getattr(module, manifest.backend_register, None)
    if not callable(register_func):
        raise PluginLoadError(
            f'插件 {manifest.plugin_id} 缺少入口函数 {manifest.backend_register}(api)'
        )

    register_func(api)
    # route() 收集到的默认蓝图在 register 返回后统一注册
    api.finalize()
    return api, module


def _mark_loaded(state: PluginState, manifest: PluginManifest, api, module) -> None:
    state.manifest = manifest
    state.api = api
    state.module = module
    state.loaded = True
    state.load_error = ''
    state.enabled = True
    state.warnings = list(manifest.warnings or [])
    _persist_load_error(state.plugin_id, '')


def _mark_failed(plugin_id: str, plugin_dir: str, manifest, error: str) -> None:
    with _states_lock:
        state = _states.get(plugin_id) or PluginState(plugin_id, plugin_dir)
        state.plugin_dir = plugin_dir or state.plugin_dir
        state.loaded = False
        state.load_error = error
        if manifest is not None:
            state.manifest = manifest
            state.warnings = list(manifest.warnings or [])
        _states[plugin_id] = state

    _persist_load_error(plugin_id, error)


def load_all(app=None) -> dict:
    """发现并加载全部插件；单个插件失败只记录，不抛出。"""
    global _states_initialized

    with _states_lock:
        _states.clear()
        _states_initialized = True

    enabled_map = _read_enabled_map()
    summary = {'loaded': [], 'failed': [], 'disabled': []}

    for plugin_dir in discover_plugin_dirs():
        plugin_id = os.path.basename(plugin_dir.rstrip(os.sep))
        enabled = enabled_map.get(plugin_id, True)

        try:
            manifest = PluginManifest.load(plugin_dir)
        except PluginApiVersionError as exc:
            _mark_failed(plugin_id, plugin_dir, None, str(exc))
            logger.error('插件 %s 的 API 版本不受支持，已跳过: %s', plugin_id, exc)
            summary['failed'].append(plugin_id)
            continue
        except PluginManifestError as exc:
            _mark_failed(plugin_id, plugin_dir, None, f'manifest 校验失败: {exc}')
            logger.error('插件 %s 的 manifest 校验失败，已跳过: %s', plugin_id, exc)
            summary['failed'].append(plugin_id)
            continue
        except Exception as exc:  # noqa: BLE001 - 兜底，任何异常都不能中断 create_app
            _mark_failed(plugin_id, plugin_dir, None, f'{type(exc).__name__}: {exc}')
            logger.exception('插件 %s 的 manifest 解析出现未预期异常', plugin_id)
            summary['failed'].append(plugin_id)
            continue

        if not enabled:
            with _states_lock:
                state = PluginState(plugin_id, plugin_dir)
                state.manifest = manifest
                state.enabled = False
                state.warnings = list(manifest.warnings or [])
                state.restart_required = bool(_read_ui_entry(plugin_id).get('restart_required', False))
                _states[plugin_id] = state
            logger.info('插件 %s 已被禁用，跳过加载', plugin_id)
            summary['disabled'].append(plugin_id)
            continue

        if not manifest.has_backend:
            # 纯前端插件：没有后端注册逻辑，但仍然登记状态供前端加载
            with _states_lock:
                state = PluginState(plugin_id, plugin_dir)
                state.manifest = manifest
                state.loaded = True
                state.enabled = True
                state.warnings = list(manifest.warnings or [])
                state.restart_required = False
                _states[plugin_id] = state
            _persist_load_error(plugin_id, '')
            logger.info('插件 %s 为纯前端插件，等待前端 PluginHost 加载', plugin_id)
            summary['loaded'].append(plugin_id)
            continue

        try:
            api, module = _instantiate_plugin(app, manifest)
        except Exception:  # noqa: BLE001 - 失败隔离：坏插件不得阻止应用启动
            error_text = traceback.format_exc()
            _mark_failed(plugin_id, plugin_dir, manifest, error_text.strip().splitlines()[-1])
            logger.exception('插件 %s 加载失败，已跳过', plugin_id)
            summary['failed'].append(plugin_id)
            continue

        with _states_lock:
            state = PluginState(plugin_id, plugin_dir)
            _mark_loaded(state, manifest, api, module)
            state.restart_required = bool(_read_ui_entry(plugin_id).get('restart_required', False))
            _states[plugin_id] = state
        summary['loaded'].append(plugin_id)

    if summary['loaded'] or summary['failed'] or summary['disabled']:
        logger.info(
            '插件加载完成：成功 %s / 失败 %s / 禁用 %s',
            len(summary['loaded']), len(summary['failed']), len(summary['disabled']),
        )
    return summary


def load_single(app, plugin_dir: str) -> PluginState:
    """加载单个插件（安装流程校验用，不登记路由）。"""
    plugin_id = os.path.basename(str(plugin_dir).rstrip(os.sep))
    manifest = PluginManifest.load(plugin_dir)
    if not manifest.has_backend:
        state = PluginState(plugin_id, plugin_dir)
        state.manifest = manifest
        return state

    api, module = _instantiate_plugin(app, manifest)
    state = PluginState(plugin_id, plugin_dir)
    _mark_loaded(state, manifest, api, module)
    return state
