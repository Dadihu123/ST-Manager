"""插件 manifest 解析与校验（设计文档第 2 部分）。

manifest.json 是插件的唯一权威声明；catalog 里的同名元数据只是快照。
校验失败一律拒绝加载（D8），并把原因交给上层持久化到
`ui_data._plugins_v1.<id>.load_error` 供 UI 展示。
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field

from core.plugins.errors import PluginApiVersionError, PluginManifestError
from core.utils.paths import is_under_base
from core.version import APP_VERSION, SUPPORTED_PLUGIN_API_VERSIONS

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = 'manifest.json'
MAX_MANIFEST_BYTES = 256 * 1024

# 目录名 = plugin id：小写、连字符、不以数字开头（路径安全第一道闸门）
PLUGIN_ID_PATTERN = re.compile(r'^[a-z][a-z0-9-]{1,63}$')
# 语义化版本 X.Y.Z[-pre][+build]
SEMVER_PATTERN = re.compile(r'^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$')
# 后端入口包名 / 模块名
ENTRY_NAME_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
# 作业类型：小写点分名（如 ai.analyze）
JOB_TYPE_PATTERN = re.compile(r'^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$')
# 依赖版本约束：`>=1.0.0` / `>1.0.0` / `<=1.0.0` / `<1.0.0` / `==1.0.0` / `1.0.0` / `*`
REQUIREMENT_PATTERN = re.compile(
    r'^(>=|>|<=|<|==|=)?\s*(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?|\*)$'
)

# 已知事件集合（与 hooks.CORE_EVENTS 保持一致，避免循环导入这里重复声明）
KNOWN_HOOKS = frozenset({
    'app.ready',
    'card.created',
    'card.updated',
    'card.deleted',
    'card.moved',
    'tag.applied',
    'tag.deleted',
    'worldbook.saved',
    'worldbook.entry_changed',
    'scan.completed',
    'index.job_done',
})

# 权限白名单（D7：只做声明与审计，不做执行门控）
KNOWN_PERMISSIONS = frozenset({
    'cards.read', 'cards.write',
    'worldbook.read', 'worldbook.write',
    'tags.read', 'tags.write',
    'secrets.read', 'network.outbound', 'jobs.run',
})

_SCHEMA_TYPES = frozenset({'string', 'integer', 'number', 'boolean', 'enum'})
_SCHEMA_ALLOWED_KEYS = frozenset({
    'type', 'title', 'description', 'default', 'minimum', 'maximum',
    'enum', 'secret', 'required', 'properties',
})


def parse_semver(value) -> tuple | None:
    """把语义化版本解析为可比较的元组；非法返回 None。"""
    if not isinstance(value, str) or not SEMVER_PATTERN.match(value.strip()):
        return None
    core = value.strip().split('+', 1)[0].split('-', 1)[0]
    parts = core.split('.')
    try:
        return tuple(int(part) for part in parts)
    except ValueError:
        return None


def compare_versions(left: str, right: str) -> int:
    """比较两个语义化版本：left > right 返回 1，相等返回 0，更小返回 -1。

    无法解析的一侧按 -1 处理（调用方应先做格式校验）。
    """
    parsed_left = parse_semver(left)
    parsed_right = parse_semver(right)
    if parsed_left is None or parsed_right is None:
        return -1
    if parsed_left > parsed_right:
        return 1
    if parsed_left < parsed_right:
        return -1
    return 0


def parse_requirement(constraint) -> tuple | None:
    """解析依赖版本约束，返回 `(操作符, 版本)`；`*` 的版本为 `'*'`。

    无操作符视为**精确匹配**（`"1.2.3"` 等价 `"==1.2.3"`）。
    """
    text = str(constraint or '').strip()
    if not text:
        return None
    match = REQUIREMENT_PATTERN.match(text)
    if not match:
        return None
    operator = match.group(1) or '=='
    return operator, match.group(2)


def satisfies_requirement(version: str, constraint) -> bool:
    """判断 `version` 是否满足依赖约束。"""
    parsed = parse_requirement(constraint)
    if parsed is None:
        return False

    operator, target = parsed
    if target == '*':
        return parse_semver(version) is not None

    current = parse_semver(version)
    expected = parse_semver(target)
    if current is None or expected is None:
        return False

    if operator == '>=':
        return current >= expected
    if operator == '>':
        return current > expected
    if operator == '<=':
        return current <= expected
    if operator == '<':
        return current < expected
    return current == expected


def _load_manifest_payload(plugin_dir: str) -> dict:
    manifest_path = os.path.join(plugin_dir, MANIFEST_FILENAME)
    if not os.path.isfile(manifest_path):
        raise PluginManifestError(f'缺少 {MANIFEST_FILENAME}')

    try:
        size = os.path.getsize(manifest_path)
    except OSError as exc:
        raise PluginManifestError(f'无法读取 manifest: {exc}') from exc

    if size > MAX_MANIFEST_BYTES:
        raise PluginManifestError(f'manifest 过大（{size} 字节）')

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
        raise PluginManifestError(f'{field_name} 不能为空')
    if value.startswith('/') or os.path.isabs(value):
        raise PluginManifestError(f'{field_name} 必须是插件内相对路径: {value}')
    drive, _ = os.path.splitdrive(value)
    if drive:
        raise PluginManifestError(f'{field_name} 不能包含盘符: {value}')
    if '..' in value.split('/'):
        raise PluginManifestError(f'{field_name} 不能包含上级目录: {value}')

    target = os.path.realpath(os.path.join(plugin_dir, value.replace('/', os.sep)))
    if not is_under_base(target, plugin_dir, resolve_symlinks=True):
        raise PluginManifestError(f'{field_name} 越出插件目录: {value}')
    if must_exist and not os.path.exists(target):
        raise PluginManifestError(f'{field_name} 指向的路径不存在: {value}')
    return target


def _normalize_string_list(raw_value, *, field_name: str) -> list:
    if raw_value in (None, ''):
        return []
    if not isinstance(raw_value, list):
        raise PluginManifestError(f'{field_name} 必须是数组')
    normalized = []
    for item in raw_value:
        if not isinstance(item, str) or not item.strip():
            raise PluginManifestError(f'{field_name} 只能是非空字符串')
        value = item.strip()
        if value not in normalized:
            normalized.append(value)
    return normalized


def _validate_schema(raw_schema, *, field_name: str) -> dict:
    """校验 JSON Schema 子集，非法则回退为空表单（不阻断加载，见 2.2）。"""
    if not raw_schema:
        return {}
    if not isinstance(raw_schema, dict) or raw_schema.get('type') != 'object':
        logger.warning('%s 不是 object 结构，已回退为空表单', field_name)
        return {}

    properties = raw_schema.get('properties') or {}
    if not isinstance(properties, dict):
        logger.warning('%s.properties 不是对象，已回退为空表单', field_name)
        return {}

    cleaned_properties = {}
    for key, spec in properties.items():
        name = str(key or '').strip()
        if not name or not isinstance(spec, dict):
            logger.warning('%s 中的字段 %r 非法，已忽略', field_name, key)
            continue

        schema_type = spec.get('type')
        if schema_type not in _SCHEMA_TYPES:
            logger.warning('%s.%s 的 type=%r 不受支持，已忽略该字段', field_name, name, schema_type)
            continue

        entry = {'type': schema_type}
        for option in ('title', 'description'):
            if isinstance(spec.get(option), str):
                entry[option] = spec[option]
        for option in ('minimum', 'maximum'):
            if isinstance(spec.get(option), (int, float)) and not isinstance(spec.get(option), bool):
                entry[option] = spec[option]
        if isinstance(spec.get('default'), (str, int, float, bool)):
            entry['default'] = spec['default']
        if isinstance(spec.get('enum'), list) and spec['enum']:
            entry['enum'] = [item for item in spec['enum'] if isinstance(item, (str, int, float, bool))]
        if bool(spec.get('secret')):
            entry['secret'] = True

        unknown = set(spec.keys()) - _SCHEMA_ALLOWED_KEYS
        if unknown:
            logger.warning('%s.%s 含未支持的属性 %s，已忽略', field_name, name, sorted(unknown))

        cleaned_properties[name] = entry

    cleaned = {'type': 'object', 'properties': cleaned_properties}
    required = raw_schema.get('required')
    if isinstance(required, list):
        cleaned['required'] = [
            str(item) for item in required
            if isinstance(item, str) and item in cleaned_properties
        ]
    return cleaned


@dataclass
class PluginManifest:
    """一份已通过校验的插件声明。"""

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

    backend_entry: str = ''
    backend_register: str = 'register'
    backend_jobs: list = field(default_factory=list)
    backend_hooks: list = field(default_factory=list)

    frontend_entry: str = ''
    frontend_entry_rel: str = ''
    frontend_styles: list = field(default_factory=list)
    frontend_styles_rel: list = field(default_factory=list)
    frontend_panels: list = field(default_factory=list)
    frontend_settings_tab: dict = field(default_factory=dict)
    frontend_detail_tab: dict = field(default_factory=dict)

    permissions: list = field(default_factory=list)
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
        return bool(self.frontend_entry)

    @property
    def is_frontend_only(self) -> bool:
        return self.has_frontend and not self.has_backend

    def data_dir(self) -> str:
        """插件私有数据目录 `data/plugins/<id>/data/`。"""
        return os.path.join(self.plugin_dir, 'data')

    def to_dict(self) -> dict:
        """返回给前端的只读快照。"""
        return {
            'id': self.plugin_id,
            'name': self.name,
            'version': self.version,
            'api_version': self.api_version,
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
            'permissions': list(self.permissions),
            'requires': dict(self.requires),
            'jobs': list(self.backend_jobs),
            'hooks': list(self.backend_hooks),
            'panels': list(self.frontend_panels),
            'settings_tab': dict(self.frontend_settings_tab),
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
        warnings = []

        raw_id = raw.get('id')
        plugin_id = str(raw_id or '').strip()
        if not PLUGIN_ID_PATTERN.match(plugin_id):
            raise PluginManifestError(f'id 不符合 ^[a-z][a-z0-9-]{{1,63}}$: {raw_id!r}')

        dir_name = os.path.basename(plugin_dir.rstrip(os.sep))
        if check_dir_name and plugin_id != dir_name:
            raise PluginManifestError(f'id ({plugin_id}) 与目录名 ({dir_name}) 不一致')
        if expected_id and plugin_id != expected_id:
            raise PluginManifestError(f'id ({plugin_id}) 与预期 ({expected_id}) 不一致')

        version = raw.get('version')
        if parse_semver(version) is None:
            raise PluginManifestError(f'version 不是合法语义化版本: {version!r}')

        api_version = raw.get('api_version')
        if isinstance(api_version, bool) or not isinstance(api_version, int):
            raise PluginManifestError(f'api_version 必须是整数: {api_version!r}')
        if api_version not in SUPPORTED_PLUGIN_API_VERSIONS:
            raise PluginApiVersionError(
                f'插件需要 api_version {api_version}，当前主程序仅支持 '
                f'{list(SUPPORTED_PLUGIN_API_VERSIONS)}（需更新主程序）'
            )

        min_app_version = str(raw.get('min_app_version') or '').strip()
        if min_app_version:
            if parse_semver(min_app_version) is None:
                raise PluginManifestError(f'min_app_version 不是合法语义化版本: {min_app_version!r}')
            if compare_versions(APP_VERSION, min_app_version) < 0:
                raise PluginManifestError(
                    f'插件要求主程序 >= {min_app_version}，当前为 {APP_VERSION}（请升级主程序）'
                )

        backend = raw.get('backend') or {}
        if backend and not isinstance(backend, dict):
            raise PluginManifestError('backend 必须是对象')
        frontend = raw.get('frontend') or {}
        if frontend and not isinstance(frontend, dict):
            raise PluginManifestError('frontend 必须是对象')
        if not backend and not frontend:
            raise PluginManifestError('backend 与 frontend 至少要有一个')

        backend_entry = ''
        backend_register = 'register'
        if backend:
            raw_entry = backend.get('entry') or ''
            entry_name = str(raw_entry).replace('\\', '/').strip().strip('/')
            if not entry_name or not all(
                ENTRY_NAME_PATTERN.match(part) for part in entry_name.split('/')
            ):
                raise PluginManifestError(f'backend.entry 非法: {raw_entry!r}')
            backend_entry = _resolve_plugin_path(
                plugin_dir, entry_name, field_name='backend.entry', must_exist=False,
            )
            init_py = os.path.join(backend_entry, '__init__.py')
            if not os.path.isfile(init_py):
                raise PluginManifestError(f'backend.entry 缺少 __init__.py: {entry_name}')

            raw_register = str(backend.get('register') or 'register').strip()
            if not ENTRY_NAME_PATTERN.match(raw_register):
                raise PluginManifestError(f'backend.register 非法: {raw_register!r}')
            backend_register = raw_register

        backend_jobs = []
        for job_type in _normalize_string_list(backend.get('jobs'), field_name='backend.jobs'):
            if not JOB_TYPE_PATTERN.match(job_type):
                raise PluginManifestError(f'backend.jobs 项非法: {job_type!r}')
            backend_jobs.append(job_type)

        backend_hooks = []
        for hook_name in _normalize_string_list(backend.get('hooks'), field_name='backend.hooks'):
            if hook_name not in KNOWN_HOOKS:
                warnings.append(f'忽略未知 hook: {hook_name}')
                logger.warning('插件 %s 声明了未知 hook %s，已忽略', plugin_id, hook_name)
                continue
            backend_hooks.append(hook_name)

        frontend_entry = ''
        frontend_entry_rel = ''
        frontend_styles = []
        frontend_styles_rel = []
        if frontend:
            raw_frontend_entry = frontend.get('entry') or ''
            if raw_frontend_entry:
                frontend_entry = _resolve_plugin_path(
                    plugin_dir, raw_frontend_entry, field_name='frontend.entry',
                )
                frontend_entry_rel = str(raw_frontend_entry).replace('\\', '/').strip().lstrip('/')
            for style in _normalize_string_list(frontend.get('styles'), field_name='frontend.styles'):
                frontend_styles.append(
                    _resolve_plugin_path(plugin_dir, style, field_name='frontend.styles')
                )
                frontend_styles_rel.append(str(style).replace('\\', '/').strip().lstrip('/'))
            if not frontend_entry and not frontend_styles:
                warnings.append('frontend 段未声明 entry 与 styles')

        permissions = []
        for permission in _normalize_string_list(raw.get('permissions'), field_name='permissions'):
            if permission not in KNOWN_PERMISSIONS:
                warnings.append(f'忽略未知权限声明: {permission}')
                logger.warning('插件 %s 声明了未知权限 %s，已忽略', plugin_id, permission)
                continue
            permissions.append(permission)

        requires = {}
        raw_requires = raw.get('requires')
        if raw_requires is not None and not isinstance(raw_requires, dict):
            warnings.append('requires 必须是对象（{plugin_id: 版本约束}），已忽略')
        elif isinstance(raw_requires, dict):
            for raw_dep_id, raw_constraint in raw_requires.items():
                dep_id = str(raw_dep_id or '').strip()
                constraint = str(raw_constraint or '').strip()
                if not PLUGIN_ID_PATTERN.match(dep_id):
                    warnings.append(f'忽略非法依赖 id: {raw_dep_id!r}')
                    continue
                if dep_id == plugin_id:
                    warnings.append('忽略对自身的依赖声明')
                    continue
                if parse_requirement(constraint) is None:
                    warnings.append(f'忽略依赖 {dep_id} 的非法版本约束: {constraint!r}')
                    continue
                requires[dep_id] = constraint

        icon = ''
        raw_icon = raw.get('icon')
        if raw_icon:
            try:
                icon = _resolve_plugin_path(plugin_dir, raw_icon, field_name='icon')
            except PluginManifestError as exc:
                warnings.append(str(exc))
                logger.warning('插件 %s 的 icon 不可用: %s', plugin_id, exc)

        panels = []
        raw_panels = frontend.get('panels') if isinstance(frontend, dict) else None
        if isinstance(raw_panels, list):
            for item in raw_panels:
                if isinstance(item, dict) and str(item.get('id') or '').strip():
                    panels.append(dict(item))

        settings_tab = frontend.get('settings_tab') if isinstance(frontend, dict) else None
        detail_tab = frontend.get('detail_tab') if isinstance(frontend, dict) else None

        return cls(
            plugin_id=plugin_id,
            name=str(raw.get('name') or plugin_id),
            version=str(version),
            api_version=int(api_version),
            plugin_dir=plugin_dir,
            author=str(raw.get('author') or ''),
            description=str(raw.get('description') or ''),
            homepage=str(raw.get('homepage') or ''),
            license=str(raw.get('license') or ''),
            icon=icon,
            min_app_version=min_app_version,
            backend_entry=backend_entry,
            backend_register=backend_register,
            backend_jobs=backend_jobs,
            backend_hooks=backend_hooks,
            frontend_entry=frontend_entry,
            frontend_entry_rel=frontend_entry_rel,
            frontend_styles=frontend_styles,
            frontend_styles_rel=frontend_styles_rel,
            frontend_panels=panels,
            frontend_settings_tab=dict(settings_tab) if isinstance(settings_tab, dict) else {},
            frontend_detail_tab=dict(detail_tab) if isinstance(detail_tab, dict) else {},
            permissions=permissions,
            requires=requires,
            config_schema=_validate_schema(raw.get('config_schema'), field_name='config_schema'),
            secret_schema=_validate_schema(raw.get('secret_schema'), field_name='secret_schema'),
            warnings=warnings,
            raw=raw,
        )
