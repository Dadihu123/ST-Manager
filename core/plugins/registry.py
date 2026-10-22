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
from core.plugins import contract
from core.plugins import contributions as contributions_module
from core.plugins.api import PluginAPI
from core.plugins.errors import PluginApiVersionError, PluginLoadError, PluginManifestError
from core.plugins.manifest import PLUGIN_ID_PATTERN, PluginManifest, satisfies_requirement

logger = logging.getLogger(__name__)

MODULE_PREFIX = 'st_plugin_'
PLUGINS_DIRNAME = 'plugins'
PLUGIN_UI_NAMESPACE = '_plugins_v1'

#: 安装来源记录在 `_plugins_v1.<id>` 下的键名（写入见 `installer.build_install_source`）。
INSTALL_SOURCE_KEY = 'install_source'


class PluginState:
    """单个插件的运行时状态（供管理 UI 与内部查询）。"""

    __slots__ = (
        'plugin_id', 'plugin_dir', 'enabled', 'loaded', 'load_error',
        'load_error_detail', 'manifest', 'api', 'module', 'restart_required',
        'warnings',
    )

    def __init__(self, plugin_id: str, plugin_dir: str = ''):
        self.plugin_id = plugin_id
        self.plugin_dir = plugin_dir
        self.enabled = True
        self.loaded = False
        self.load_error = ''
        self.load_error_detail = {}
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
        return self.build_header(read_install_source(self.plugin_id))

    def build_header(self, install_source: dict) -> dict:
        """构造列表载荷。

        `install_source` 由调用方传入（而不是在这里读 ui_data）：`/api/plugins/list`
        与 `/api/plugins/catalog` 都是**按插件循环**的，逐次读取会把整个 ui_data.json
        重复解析 N 遍。批量路径请用 `read_install_sources()` 一次读好后传进来。
        """
        manifest = self.manifest
        # 失败插件的贡献不进列表载荷（S2）：否则前端会为一个加载失败的插件渲染入口。
        contributes = manifest is not None and not self.load_error
        return {
            'id': self.plugin_id,
            'name': manifest.name if manifest else self.plugin_id,
            'version': manifest.version if manifest else '',
            'api_version': manifest.api_version if manifest else 0,
            'manifest_version': manifest.manifest_version if manifest else 0,
            'enabled': bool(self.enabled),
            'loaded': bool(self.loaded),
            'backend': bool(manifest and manifest.has_backend),
            'frontend': bool(manifest and manifest.has_frontend),
            'frontend_only': bool(manifest and manifest.is_frontend_only),
            'capabilities': list(manifest.capabilities) if contributes else [],
            'contributions': (
                contributions_module.snapshot(manifest.frontend_contributions) if contributes
                else contributions_module.empty_contributions()
            ),
            'render_mode': (
                manifest.frontend_render_mode if contributes else contract.DEFAULT_RENDER_MODE
            ),
            'load_error': self.load_error,
            'load_error_detail': dict(self.load_error_detail or {}),
            'restart_required': bool(self.restart_required),
            'warnings': list(self.warnings or []),
            'author': manifest.author if manifest else '',
            'description': manifest.description if manifest else '',
            'homepage': manifest.homepage if manifest else '',
            # 安装来源外链：已解析的网页地址 + 结构化记录，供管理 UI 展示。
            # 解析优先级见 `_resolve_source_url`；解析不出时为空串，前端据此不渲染按钮。
            'source_url': _resolve_source_url(install_source, manifest),
            'install_source': dict(install_source or {}),
            'icon': manifest.icon if manifest else '',
            'installed': bool(manifest),
        }

    def detail(self, install_source: dict | None = None) -> dict:
        """列表载荷 + 完整 manifest 快照。

        `install_source` 留空表示「自己读一次」（单插件路径）；批量路径应显式传入，
        避免每个插件重复解析 ui_data.json。
        """
        payload = self.header if install_source is None else self.build_header(install_source)
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


def _persist_load_error(plugin_id: str, error: str, detail: dict | None = None) -> None:
    """持久化加载失败信息。

    `load_error` 保留为人类可读摘要（向后兼容既有 UI 与测试），
    `load_error_detail` 携带 D3 的结构化字段（code/field/msg/hint/user_msg）。
    """
    patch = {}
    current = _read_ui_entry(plugin_id)
    if current.get('load_error', '') != error:
        patch['load_error'] = error

    detail = detail or {}
    if current.get('load_error_detail') != detail:
        patch['load_error_detail'] = detail

    if patch:
        _persist_ui_entry(plugin_id, patch)


def get_state(plugin_id: str):
    with _states_lock:
        return _states.get(str(plugin_id or ''))


def read_ui_entry(plugin_id: str) -> dict:
    """读取 `ui_data._plugins_v1.<id>`（公开入口，供路由层复用）。"""
    return _read_ui_entry(str(plugin_id or ''))


def read_install_source(plugin_id: str) -> dict:
    """读取 `_plugins_v1.<id>.install_source`；缺失或畸形时返回空字典。"""
    record = _read_ui_entry(str(plugin_id or '')).get(INSTALL_SOURCE_KEY)
    return dict(record) if isinstance(record, dict) else {}


def read_install_sources() -> dict:
    """一次性读取全部插件的安装来源记录 `{plugin_id: record}`。

    批量渲染（`/api/plugins/list`、`/api/plugins/catalog`）用这个，避免按插件重复
    解析整个 ui_data.json。
    """
    ui_data = load_ui_data_or_empty()
    namespace = ui_data.get(PLUGIN_UI_NAMESPACE)
    if not isinstance(namespace, dict):
        return {}

    result = {}
    for plugin_id, entry in namespace.items():
        if not isinstance(entry, dict):
            continue
        record = entry.get(INSTALL_SOURCE_KEY)
        if isinstance(record, dict):
            result[str(plugin_id)] = dict(record)
    return result


def persist_install_source(plugin_id: str, record: dict) -> bool:
    """写入安装来源记录（保留同命名空间下的其它键）。

    覆盖式写入：重装 / 更新同一插件只刷新这一条记录，不会产生重复项。
    """
    plugin_id = str(plugin_id or '')
    if not plugin_id or not isinstance(record, dict) or not record:
        return False
    return _persist_ui_entry(plugin_id, {INSTALL_SOURCE_KEY: dict(record)})


def _resolve_source_url(record: dict, manifest) -> str:
    """按优先级解析「安装来源」网页地址。

    1. 持久化的安装来源 `install_source.url`——最可信，记录的是用户实际执行的那次安装；
    2. manifest 的 `homepage`——插件作者声明的项目主页；
    3. 已知 repo 时派生的 `https://github.com/<repo>`（老安装记录只有 repo 时兜底）。

    都没有则返回空串：UI 据此**不渲染按钮**，而不是造一个点不开的链接。
    """
    url = str((record or {}).get('url') or '').strip()
    if url:
        return url

    homepage = str(getattr(manifest, 'homepage', '') or '').strip()
    if homepage:
        return homepage

    # 局部导入：installer 顶层 `from core.plugins import registry`，这里反向依赖会成环。
    from core.plugins.installer import build_repo_url

    return build_repo_url(str((record or {}).get('repo') or ''))


def resolve_source_url(plugin_id: str, manifest=None) -> str:
    """解析插件「安装来源」网页地址（供管理 UI 渲染外链，无来源时返回空串）。"""
    return _resolve_source_url(read_install_source(plugin_id), manifest)


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
    """卸载后清理运行时状态与订阅（hooks / 作业处理器 / CLI 子命令）。"""
    from core.plugins import cli, hooks, jobs

    plugin_id = str(plugin_id or '')
    hooks.unregister_plugin(plugin_id)
    jobs.unregister_plugin_handlers(plugin_id)
    cli.unregister_plugin(plugin_id)

    with _states_lock:
        _states.pop(plugin_id, None)


def register_external_state(state: PluginState) -> None:
    """登记一个未加载成功的插件状态（安装后尚未重启时展示用）。"""
    with _states_lock:
        _states[state.plugin_id] = state


def refresh_manifest(plugin_id: str, plugin_dir: str = '') -> PluginManifest | None:
    """安装 / 更新 / 卸载后，把**磁盘上的新 manifest** 同步进内存状态。

    为什么必须做：`installer.install_plugin_dir()` 用 `os.replace` 换掉了插件
    目录，但内存里的 `state.manifest` 还是进程启动时读的那份。不同步的后果是
    `catalog.check_updates()` 拿陈旧版本去比远端版本，于是**刚更新完仍报有更新**
    ——用户点一次更新、再检查一次又说有更新，形成死循环（磁盘其实早就是新版）。

    语义：只更新「声明层」信息（manifest / warnings / plugin_dir），
    **不**重新加载代码——Python 模块已经在 `sys.modules` 里，热重载有类身份变化
    与蓝图重复注册的陷阱（见设计文档 3.2）。因此这里同时把 `restart_required`
    置为 True，让 UI 如实提示「需重启生效」。

    Returns:
        刷新后的 manifest；目录或 manifest 不可读时返回 None（保持原状态不动）。
    """
    plugin_id = str(plugin_id or '')
    directory = str(plugin_dir or '') or os.path.join(plugins_dir(), plugin_id)

    try:
        manifest = PluginManifest.load(directory, check_dir_name=False)
    except Exception:  # noqa: BLE001 - 刷新失败不应影响安装结果
        logger.warning('刷新插件 %s 的内存 manifest 失败', plugin_id, exc_info=True)
        return None

    with _states_lock:
        state = _states.get(plugin_id)
        if state is None:
            # 首次安装（进程内还没有该插件的状态）→ 登记一个「待重启加载」的状态
            state = PluginState(plugin_id, directory)
            state.enabled = True
            _states[plugin_id] = state
        state.plugin_dir = directory
        state.manifest = manifest
        state.warnings = list(manifest.warnings or [])
        state.restart_required = True

    _persist_ui_entry(plugin_id, {'restart_required': True})
    return manifest


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
    state.load_error_detail = {}
    state.enabled = True
    state.warnings = list(manifest.warnings or [])
    _persist_load_error(state.plugin_id, '')


def _mark_failed(plugin_id: str, plugin_dir: str, manifest, error, *,
                 detail: dict | None = None, prefix: str = '') -> None:
    """记录加载失败。

    `error` 可以是字符串（摘要）或异常对象；异常对象会同时取出 D3 的结构化字段
    （`load_error_detail`）。`prefix` 用于给摘要加上既有 UI 依赖的前缀。
    """
    if isinstance(error, BaseException):
        exc = error
        if detail is None and hasattr(exc, 'as_detail'):
            detail = exc.as_detail()
        error_text = f'{prefix}{exc}'
    else:
        error_text = f'{prefix}{error}'

    with _states_lock:
        state = _states.get(plugin_id) or PluginState(plugin_id, plugin_dir)
        state.plugin_dir = plugin_dir or state.plugin_dir
        state.loaded = False
        state.load_error = error_text
        state.load_error_detail = dict(detail or {})
        if manifest is not None:
            state.manifest = manifest
            state.warnings = list(manifest.warnings or [])
        _states[plugin_id] = state

    _persist_load_error(plugin_id, error_text, detail)


def _register_disabled_state(plugin_id: str, plugin_dir: str, manifest: PluginManifest) -> None:
    with _states_lock:
        state = PluginState(plugin_id, plugin_dir)
        state.manifest = manifest
        state.enabled = False
        state.warnings = list(manifest.warnings or [])
        state.restart_required = False
        _states[plugin_id] = state


def _register_frontend_only_state(plugin_id: str, plugin_dir: str, manifest: PluginManifest) -> None:
    with _states_lock:
        state = PluginState(plugin_id, plugin_dir)
        state.manifest = manifest
        state.loaded = True
        state.enabled = True
        state.warnings = list(manifest.warnings or [])
        state.restart_required = False
        _states[plugin_id] = state
    _persist_load_error(plugin_id, '')


def resolve_dependencies(candidates: dict) -> tuple:
    """校验插件间依赖并给出加载顺序（被依赖者在前）。

    Args:
        candidates: `{plugin_id: {'dir': str, 'manifest': PluginManifest, 'enabled': bool}}`

    Returns:
        `(order, errors)`：`order` 是依赖已满足的插件 id（拓扑序），
        `errors` 记录其余插件无法加载的原因（缺失 / 被禁用 / 版本不满足 / 循环依赖）。
    """
    errors = {}

    for plugin_id, item in candidates.items():
        for dep_id, constraint in (item['manifest'].requires or {}).items():
            dependency = candidates.get(dep_id)
            if dependency is None:
                errors[plugin_id] = f'缺少依赖插件: {dep_id} {constraint}'
                break
            if not dependency['enabled']:
                errors[plugin_id] = f'依赖插件已被禁用: {dep_id}'
                break
            if not satisfies_requirement(dependency['manifest'].version, constraint):
                errors[plugin_id] = (
                    f'依赖版本不满足: {dep_id} 需要 {constraint}，'
                    f'已安装 {dependency["manifest"].version}'
                )
                break

    order = []
    resolved = set()
    visiting = set()
    stack = []

    def visit(plugin_id: str) -> bool:
        if plugin_id in resolved:
            return True
        if plugin_id in visiting:
            cycle = stack[stack.index(plugin_id):] + [plugin_id]
            message = '检测到循环依赖: ' + ' → '.join(cycle)
            for member in cycle[:-1]:
                errors.setdefault(member, message)
            return False

        visiting.add(plugin_id)
        stack.append(plugin_id)
        ok = True
        for dep_id in (candidates[plugin_id]['manifest'].requires or {}):
            if dep_id not in candidates or dep_id in errors:
                errors.setdefault(plugin_id, '依赖链中存在无法加载的插件')
                ok = False
                continue
            if not visit(dep_id):
                errors.setdefault(plugin_id, '依赖链中存在无法加载的插件')
                ok = False
        stack.pop()
        visiting.discard(plugin_id)

        if ok:
            resolved.add(plugin_id)
            order.append(plugin_id)
        return ok

    for plugin_id in sorted(candidates):
        if plugin_id in errors:
            continue
        visit(plugin_id)

    return order, errors


def load_all(app=None) -> dict:
    """发现并加载全部插件；单个插件失败只记录，不抛出。

    两阶段：先解析全部 manifest，再按依赖顺序加载（被依赖者先加载）。
    依赖缺失、被禁用、版本不满足或循环依赖都会记入该插件的 `load_error` 并跳过。
    """
    global _states_initialized

    with _states_lock:
        _states.clear()
        _states_initialized = True

    enabled_map = _read_enabled_map()
    summary = {'loaded': [], 'failed': [], 'disabled': []}

    # === 阶段 1：发现 + manifest 校验 ===
    candidates = {}
    for plugin_dir in discover_plugin_dirs():
        plugin_id = os.path.basename(plugin_dir.rstrip(os.sep))

        try:
            manifest = PluginManifest.load(plugin_dir)
        except PluginApiVersionError as exc:
            _mark_failed(plugin_id, plugin_dir, None, exc)
            logger.error('插件 %s 的 API 版本不受支持，已跳过: %s', plugin_id, exc)
            summary['failed'].append(plugin_id)
            continue
        except PluginManifestError as exc:
            # 保留「manifest 校验失败: 」前缀：load_error 是既有 UI 依赖的人类可读摘要
            _mark_failed(plugin_id, plugin_dir, None, exc, prefix='manifest 校验失败: ')
            logger.error('插件 %s 的 manifest 校验失败，已跳过: %s', plugin_id, exc)
            summary['failed'].append(plugin_id)
            continue
        except Exception as exc:  # noqa: BLE001 - 兜底，任何异常都不能中断 create_app
            _mark_failed(plugin_id, plugin_dir, None, f'{type(exc).__name__}: {exc}')
            logger.exception('插件 %s 的 manifest 解析出现未预期异常', plugin_id)
            summary['failed'].append(plugin_id)
            continue

        candidates[plugin_id] = {
            'dir': plugin_dir,
            'manifest': manifest,
            'enabled': enabled_map.get(plugin_id, True),
        }

    # === 阶段 2：依赖解析 + 拓扑排序 ===
    order, dependency_errors = resolve_dependencies(candidates)

    # === 阶段 3：按序加载 ===
    failed_ids = set()
    for plugin_id in order:
        item = candidates[plugin_id]
        plugin_dir = item['dir']
        manifest = item['manifest']

        blocked = [dep for dep in (manifest.requires or {}) if dep in failed_ids]
        if blocked:
            message = '依赖链中存在无法加载的插件'
            _mark_failed(plugin_id, plugin_dir, manifest, message)
            logger.error('插件 %s 的依赖 %s 加载失败，已跳过', plugin_id, blocked)
            summary['failed'].append(plugin_id)
            failed_ids.add(plugin_id)
            continue

        if not item['enabled']:
            _register_disabled_state(plugin_id, plugin_dir, manifest)
            logger.info('插件 %s 已被禁用，跳过加载', plugin_id)
            summary['disabled'].append(plugin_id)
            continue

        if not manifest.has_backend:
            # 纯前端插件：没有后端注册逻辑，但仍然登记状态供前端加载
            _register_frontend_only_state(plugin_id, plugin_dir, manifest)
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
            failed_ids.add(plugin_id)
            continue

        with _states_lock:
            state = PluginState(plugin_id, plugin_dir)
            _mark_loaded(state, manifest, api, module)
            state.restart_required = False
            _states[plugin_id] = state
        summary['loaded'].append(plugin_id)

    # === 依赖未满足 / 被禁用的落后者 ===
    for plugin_id, item in candidates.items():
        if plugin_id in order:
            continue
        if not item['enabled']:
            _register_disabled_state(plugin_id, item['dir'], item['manifest'])
            summary['disabled'].append(plugin_id)
            continue

        message = dependency_errors.get(plugin_id, '依赖未满足')
        _mark_failed(plugin_id, item['dir'], item['manifest'], message)
        logger.error('插件 %s 依赖未满足，已跳过: %s', plugin_id, message)
        summary['failed'].append(plugin_id)

    if summary['loaded'] or summary['failed'] or summary['disabled']:
        logger.info(
            '插件加载完成：成功 %s / 失败 %s / 禁用 %s',
            len(summary['loaded']), len(summary['failed']), len(summary['disabled']),
        )

    # 本轮加载完成后，「重启生效」标记已消费完毕，全部清零
    # 否则禁用/安装后重启，旧的 restart_required 持久化标志会再次残留
    _clear_restart_required_flags()
    return summary


def _clear_restart_required_flags() -> None:
    """把 `_plugins_v1.<id>.restart_required` 持久化标志统一清零。

    `load_all()` 是一次新的启动，运行到这里说明「重启生效」的语义已达成。
    不归零的话：禁用 → 重启 → 标志仍是 true → 管理页继续显示「重启生效」。
    """
    def mutator(ui_data):
        namespace = ui_data.get(PLUGIN_UI_NAMESPACE)
        if not isinstance(namespace, dict):
            return
        for entry in namespace.values():
            if isinstance(entry, dict) and entry.get('restart_required'):
                entry['restart_required'] = False

    try:
        update_ui_data(mutator)
    except Exception:  # noqa: BLE001 - 标志清理失败不影响主流程
        logger.warning('清理 restart_required 标志失败', exc_info=True)


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
