"""插件 manifest v3 解析与校验（设计文档 §4 / §4.9 / §11.1）。

`manifest.json` 是插件的唯一权威声明；catalog 里的同名元数据只是快照。
校验失败一律拒绝加载（D8），并把原因交给上层持久化到
`ui_data._plugins_v1.<id>.load_error` 供 UI 展示。

职责边界（S1）：**规则本体在 `core/plugins/contract.py`**（纯标准库、可被
`stm-plugin-check` 原样嵌入）；本模块是宿主侧的薄封装：

1. 读取 manifest 文件（缺失 / 超过 256KB / 非法 JSON 的 IO 级错误）；
2. 调 `contract.validate_manifest(strict=False)`（宿主宽容模式）；
3. 把契约 issue 转成 `PluginManifestError` / `PluginApiVersionError`（带 code/field/hint/user_msg）；
4. 解析插件内路径（backend 包、frontend entry/styles、global_styles、插件图标）；
5. 组装 `PluginManifest` 快照（`to_dict()` 形状见实现日志 S2）。

两级校验：宿主宽容（节点级问题丢弃 + 警告），CLI 严格（同样问题升级为错误）。
"""

import json
import logging
import os
from dataclasses import dataclass, field

from core.plugins import contract
from core.plugins import contributions as contributions_module
from core.plugins.contract import (  # noqa: F401 - 供其它模块/测试沿用 manifest 的公开符号
    compare_versions,
    parse_requirement,
    parse_semver,
    satisfies_requirement,
)
from core.plugins.errors import PluginApiVersionError, PluginManifestError
from core.plugins.icons import is_host_icon_name, sprite_for_icon
from core.utils.paths import is_under_base
from core.version import APP_VERSION

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = 'manifest.json'
MAX_MANIFEST_BYTES = contract.MAX_MANIFEST_BYTES

DEFAULT_MANIFEST_VERSION = contract.MANIFEST_VERSION
SUPPORTED_MANIFEST_VERSIONS = contract.SUPPORTED_MANIFEST_VERSIONS

# 结构键白名单（D3）：出现白名单以外的键即拒绝加载（契约侧定义，非 `x-` 前缀）
KNOWN_TOP_LEVEL_KEYS = contract.KNOWN_TOP_LEVEL_KEYS
KNOWN_BACKEND_KEYS = contract.KNOWN_BACKEND_KEYS
KNOWN_FRONTEND_KEYS = contract.KNOWN_FRONTEND_KEYS
LEGACY_FRONTEND_KEYS = contract.LEGACY_FRONTEND_KEYS

PLUGIN_ID_PATTERN = contract.PLUGIN_ID_PATTERN
SEMVER_PATTERN = contract.SEMVER_PATTERN
ENTRY_NAME_PATTERN = contract.ENTRY_NAME_PATTERN
JOB_TYPE_PATTERN = contract.JOB_TYPE_PATTERN
REQUIREMENT_PATTERN = contract.REQUIREMENT_PATTERN
KNOWN_HOOKS = contract.KNOWN_HOOKS


def _plugin_user_msg(plugin_label: str) -> str:
    """面向普通用户的一句话错误提示（D3）。"""
    return f'插件「{plugin_label}」的清单格式不正确，请联系插件作者更新。'


def _load_manifest_payload(plugin_dir: str) -> dict:
    """读取 manifest.json（IO / 大小 / JSON 层错误由宿主负责）。"""
    manifest_path = os.path.join(plugin_dir, MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        raise PluginManifestError(f'缺少 {MANIFEST_FILENAME}')

    try:
        size = os.path.getsize(manifest_path)
    except OSError as exc:
        raise PluginManifestError(f'无法读取 manifest: {exc}') from exc

    if size > MAX_MANIFEST_BYTES:
        raise PluginManifestError(f'manifest 过大（{size} 字节，上限 {MAX_MANIFEST_BYTES}）')

    try:
        with open(manifest_path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as exc:
        raise PluginManifestError(f'manifest 不是合法 JSON: {exc}') from exc
    except OSError as exc:
        raise PluginManifestError(f'读取 manifest 失败: {exc}') from exc

    if not isinstance(payload, dict):
        raise PluginManifestError('manifest 顶层必须是对象')
    return payload


def _resolve_plugin_path(plugin_dir: str, raw_value, *, field_name: str, must_exist: bool = True) -> str:
    """把插件内的相对路径解析为绝对路径，并校验未越出插件目录。"""
    value = str(raw_value or '').replace('\\', '/').strip()
    if not value:
        raise PluginManifestError(f'{field_name} 不能为空', field=field_name)
    if value.startswith('/') or os.path.isabs(value):
        raise PluginManifestError(f'{field_name} 必须是插件内相对路径: {value}', field=field_name)
    drive, _ = os.path.splitdrive(value)
    if drive:
        raise PluginManifestError(f'{field_name} 不能包含盘符: {value}', field=field_name)
    if '..' in value.split('/'):
        raise PluginManifestError(f'{field_name} 不能包含上级目录: {value}', field=field_name)

    target = os.path.realpath(os.path.join(plugin_dir, value.replace('/', os.sep)))
    if not is_under_base(target, plugin_dir, resolve_symlinks=True):
        raise PluginManifestError(f'{field_name} 越出插件目录: {value}', field=field_name)
    if must_exist and not os.path.exists(target):
        raise PluginManifestError(f'{field_name} 指向的路径不存在: {value}', field=field_name)
    return target


def _normalize_rel_path(plugin_dir: str, raw_value, *, field_name: str) -> str:
    """解析路径并返回归一化的相对路径（正斜杠、去掉前导 `/`）。"""
    _resolve_plugin_path(plugin_dir, raw_value, field_name=field_name)
    return str(raw_value or '').replace('\\', '/').strip().lstrip('/')


def _select_error(raw: dict, issues: list):
    """从契约 issues 里挑出要抛出的第一条错误。

    v2 manifest 会同时触发「未知顶层键 permissions」「manifest_version=2」
    「api_version=2」「frontend.entries 已废弃」等多个错误；为了让用户看到
    最可行动的提示，**显式声明了整数 api_version 且不受支持**时优先报版本错误
    （`PluginApiVersionError`，路由层映射 409 + 「升级主程序」）。
    其余情况按契约产出顺序取第一条。
    """
    errors = [issue for issue in issues if issue.get('severity') == contract.SEVERITY_ERROR]
    if not errors:
        return None

    raw_api_version = raw.get('api_version')
    if (
        isinstance(raw_api_version, int)
        and not isinstance(raw_api_version, bool)
        and raw_api_version not in contract.SUPPORTED_API_VERSIONS
    ):
        for issue in errors:
            if issue.get('code') == 'api_version_unsupported':
                return issue
    return errors[0]


def _raise_for_issue(issue, plugin_label: str):
    """把一条契约 error issue 转成宿主异常（保留 code/field/hint/user_msg）。"""
    message = str(issue.get('message') or issue.get('code') or 'manifest 校验失败')
    code = str(issue.get('code') or '')
    field_name = str(issue.get('field') or '')
    hint = str(issue.get('hint') or '')

    if code == 'api_version_unsupported':
        raise PluginApiVersionError(
            message,
            field=field_name or 'api_version',
            hint=hint,
            user_msg=f'插件「{plugin_label}」需要更新版本的主程序，请先升级主程序。',
        )
    raise PluginManifestError(
        message,
        field=field_name,
        hint=hint,
        user_msg=_plugin_user_msg(plugin_label),
        code=code,
    )


def _warnings_from_issues(issues: list) -> list:
    """把契约 warning issues 转成人类可读文本（宿主宽松：全部只警告）。"""
    warnings = []
    for issue in issues or []:
        if issue.get('severity') != contract.SEVERITY_WARNING:
            continue
        text = contributions_module.issue_to_warning(issue)
        if text:
            warnings.append(text)
    return warnings


def _resolve_plugin_icon(plugin_dir: str, raw_icon: str, warnings: list) -> str:
    """插件图标：宿主图标名（`wand`）或插件内资源路径（`frontend/assets/icon.svg`）。

    与 `entries[].icon` 同源规则（D4）：不合法只警告 + 返回空串，不拒绝加载。
    """
    if not raw_icon:
        return ''
    if is_host_icon_name(raw_icon):
        if sprite_for_icon(raw_icon):
            return raw_icon
        warnings.append(f'icon: 引用了不存在的宿主图标 {raw_icon}，已忽略')
        return ''
    try:
        return _resolve_plugin_path(plugin_dir, raw_icon, field_name='icon')
    except PluginManifestError as exc:
        warnings.append(f'icon: {exc}')
        logger.warning('插件 %s 的 icon 不可用: %s', plugin_dir, exc)
        return ''


@dataclass
class PluginManifest:
    """一份已通过校验的插件声明（v3 契约快照）。"""

    plugin_id: str
    name: str
    version: str
    api_version: int
    plugin_dir: str
    author: str = ''
    description: str = ''
    homepage: str = ''
    license: str = ''
    icon: str = ''
    min_app_version: str = ''
    manifest_version: int = DEFAULT_MANIFEST_VERSION

    backend_entry: str = ''
    backend_register: str = 'register'
    backend_jobs: list = field(default_factory=list)
    backend_hooks: list = field(default_factory=list)

    frontend_entry: str = ''
    frontend_entry_rel: str = ''
    frontend_styles: list = field(default_factory=list)
    frontend_styles_rel: list = field(default_factory=list)
    frontend_global_styles: list = field(default_factory=list)
    frontend_global_styles_rel: list = field(default_factory=list)
    frontend_render_mode: str = contract.DEFAULT_RENDER_MODE
    frontend_contributions: dict = field(default_factory=contributions_module.empty_contributions)

    capabilities: list = field(default_factory=list)
    requires: dict = field(default_factory=dict)
    config_schema: dict = field(default_factory=dict)
    secret_schema: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @property
    def has_backend(self) -> bool:
        return bool(self.backend_entry)

    @property
    def has_frontend(self) -> bool:
        if self.frontend_entry or self.frontend_styles or self.frontend_global_styles:
            return True
        contributions = self.frontend_contributions or {}
        if any(contributions.get(kind) for kind in ('menus', 'slots', 'commands')):
            return True
        return self.frontend_render_mode == 'custom'

    @property
    def is_frontend_only(self) -> bool:
        return self.has_frontend and not self.has_backend

    def data_dir(self) -> str:
        """插件私有数据目录 `data/plugins/<id>/data/`。"""
        return os.path.join(self.plugin_dir, 'data')

    def to_dict(self) -> dict:
        """返回给前端的只读快照（S2 定稿形状；无 `entries` / `permissions` 别名）。"""
        return {
            'id': self.plugin_id,
            'name': self.name,
            'version': self.version,
            'api_version': self.api_version,
            'manifest_version': self.manifest_version,
            'author': self.author,
            'description': self.description,
            'homepage': self.homepage,
            'license': self.license,
            'icon': self.icon,
            'min_app_version': self.min_app_version,
            'backend': self.has_backend,
            'frontend': self.has_frontend,
            'frontend_only': self.is_frontend_only,
            'frontend_entry': self.frontend_entry_rel,
            'frontend_styles': list(self.frontend_styles_rel),
            'frontend_global_styles': list(self.frontend_global_styles_rel),
            'render_mode': self.frontend_render_mode,
            'capabilities': list(self.capabilities),
            'requires': dict(self.requires),
            'jobs': list(self.backend_jobs),
            'hooks': list(self.backend_hooks),
            'contributions': contributions_module.snapshot(self.frontend_contributions),
            'config_schema': dict(self.config_schema),
            'secret_schema': dict(self.secret_schema),
        }

    @classmethod
    def load(cls, plugin_dir: str, *, expected_id: str = '', check_dir_name: bool = True) -> 'PluginManifest':
        """读取并校验 `plugin_dir/manifest.json`。

        Args:
            plugin_dir: 插件根目录绝对路径。
            expected_id: 期望的插件 id（安装流程用于防止「清单说装 A、实际装成 B」）。
            check_dir_name: 是否要求目录名等于 `id`。已安装插件必须为 True；
                安装阶段解压出的目录名不可控（GitHub 归档顶层是 `repo-branch`），
                此时传 False —— 安装完成后目录会被重命名为 id，约束自然成立。

        Raises:
            PluginManifestError: 结构非法。
            PluginApiVersionError: api_version 与主程序契约不兼容（D8）。
        """
        plugin_dir = os.path.realpath(str(plugin_dir or ''))
        if not plugin_dir or not os.path.isdir(plugin_dir):
            raise PluginManifestError(f'插件目录不存在: {plugin_dir}')

        raw = _load_manifest_payload(plugin_dir)
        normalized, issues = contract.validate_manifest(raw, strict=False)

        error = _select_error(raw, issues)
        if error is not None:
            plugin_label = str(raw.get('name') or raw.get('id') or '').strip() or '未知插件'
            _raise_for_issue(error, plugin_label)

        plugin_id = normalized['id']
        warnings = _warnings_from_issues(issues)

        dir_name = os.path.basename(plugin_dir.rstrip(os.sep))
        if check_dir_name and plugin_id != dir_name:
            raise PluginManifestError(
                f'id ({plugin_id}) 与目录名 ({dir_name}) 不一致',
                field='id',
                hint='已安装插件的目录名必须等于 manifest 的 id；安装流程会自动重命名目录。',
            )
        if expected_id and plugin_id != expected_id:
            raise PluginManifestError(
                f'id ({plugin_id}) 与预期 ({expected_id}) 不一致',
                field='id',
            )

        min_app_version = normalized['min_app_version']
        if min_app_version and compare_versions(APP_VERSION, min_app_version) < 0:
            raise PluginManifestError(
                f'插件要求主程序 >= {min_app_version}，当前为 {APP_VERSION}（请升级主程序）',
                field='min_app_version',
                user_msg=f'插件「{normalized["name"]}」需要更高版本的主程序，请先升级主程序。',
            )

        # ---------------- backend ----------------
        backend_entry = ''
        backend_register = 'register'
        raw_backend = normalized['backend']
        if raw_backend:
            entry_name = raw_backend['entry']
            backend_entry = _resolve_plugin_path(
                plugin_dir, entry_name, field_name='backend.entry', must_exist=False,
            )
            init_py = os.path.join(backend_entry, '__init__.py')
            if not os.path.isfile(init_py):
                raise PluginManifestError(
                    f'backend.entry 缺少 __init__.py: {entry_name}', field='backend.entry',
                )
            backend_register = raw_backend['register']

        # ---------------- frontend ----------------
        frontend_entry = ''
        frontend_entry_rel = ''
        frontend_styles = []
        frontend_styles_rel = []
        frontend_global_styles = []
        frontend_global_styles_rel = []
        frontend_render_mode = contract.DEFAULT_RENDER_MODE
        frontend_contributions = contributions_module.empty_contributions()

        raw_frontend = normalized['frontend']
        if raw_frontend:
            frontend_render_mode = raw_frontend['render_mode']
            frontend_contributions = raw_frontend['contributions']

            if raw_frontend['entry']:
                frontend_entry = _resolve_plugin_path(
                    plugin_dir, raw_frontend['entry'], field_name='frontend.entry',
                )
                frontend_entry_rel = _normalize_rel_path(
                    plugin_dir, raw_frontend['entry'], field_name='frontend.entry',
                )
            for index, style in enumerate(raw_frontend['styles']):
                frontend_styles.append(_resolve_plugin_path(
                    plugin_dir, style, field_name=f'frontend.styles[{index}]',
                ))
                frontend_styles_rel.append(_normalize_rel_path(
                    plugin_dir, style, field_name=f'frontend.styles[{index}]',
                ))

            # global_styles 受能力位门控：没声明 ui.global_styles 时宿主拒绝注入
            if contract.CAPABILITY_UI_GLOBAL_STYLES in normalized['capabilities']:
                for index, style in enumerate(raw_frontend['global_styles']):
                    frontend_global_styles.append(_resolve_plugin_path(
                        plugin_dir, style, field_name=f'frontend.global_styles[{index}]',
                    ))
                    frontend_global_styles_rel.append(_normalize_rel_path(
                        plugin_dir, style, field_name=f'frontend.global_styles[{index}]',
                    ))

            if not (
                frontend_entry or frontend_styles or frontend_global_styles_rel
                or any(frontend_contributions.get(kind) for kind in ('menus', 'slots', 'commands'))
            ):
                warnings.append('frontend 段未声明 entry / styles / contributions')

        # 图标检查：宿主图标名需存在；插件资源路径需存在于插件目录内
        warnings.extend(contributions_module.check_contribution_icons(frontend_contributions))
        icon = _resolve_plugin_icon(plugin_dir, normalized['icon'], warnings)

        return cls(
            plugin_id=plugin_id,
            name=normalized['name'],
            version=normalized['version'],
            api_version=normalized['api_version'],
            plugin_dir=plugin_dir,
            author=normalized['author'],
            description=normalized['description'],
            homepage=normalized['homepage'],
            license=normalized['license'],
            icon=icon,
            min_app_version=min_app_version,
            manifest_version=normalized['manifest_version'],
            backend_entry=backend_entry,
            backend_register=backend_register,
            backend_jobs=list(raw_backend['jobs']) if raw_backend else [],
            backend_hooks=list(raw_backend['hooks']) if raw_backend else [],
            frontend_entry=frontend_entry,
            frontend_entry_rel=frontend_entry_rel,
            frontend_styles=frontend_styles,
            frontend_styles_rel=frontend_styles_rel,
            frontend_global_styles=frontend_global_styles,
            frontend_global_styles_rel=frontend_global_styles_rel,
            frontend_render_mode=frontend_render_mode,
            frontend_contributions=frontend_contributions,
            capabilities=list(normalized['capabilities']),
            requires=dict(normalized['requires']),
            config_schema=dict(normalized['config_schema']),
            secret_schema=dict(normalized['secret_schema']),
            warnings=warnings,
            raw=raw,
        )
