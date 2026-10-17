"""PluginAPI 门面（设计文档 10.2；插件 API 全面放开方案 §3）。

插件通过 `register(api)` 拿到这个对象，它是插件与主程序之间的**唯一**契约面。

形状：**域命名空间**。`PluginAPI` 类体本身只剩三个公开成员——
`on` / `emit`（EventEmitter 惯用法，与前端 `api.on` / `api.off` / `api.emit` 对齐）
和 `estimate_tokens`（跨域工具），其余能力全部挂在 `__init__` 里构造的**域实例**上：

```python
api.cards.*      api.tags.*       api.worldbook.*   api.backups.*
api.jobs.*       api.private.*    api.config.*      api.secrets.*
api.http.*       api.cli.*        api.log.*         api.index.*
api.chats.*      api.presets.*    api.extensions.*
```

设计原则（4.6，本文件继续遵守）：

1. **能力面全面放开，机制内部化**：能做什么（读/写卡片、移动、标签治理、
   世界书、快照、索引…）全部开放；怎么做才不破坏一致性（卡片锁、
   `suppress_fs_events`、缓存/索引同步、`db_session` 重试、路径安全校验、原子写）
   一律留在本文件与各域内部，插件看不到也不该看到。
2. 核心能力一律复用既有服务层，不重复实现；一致性机制**只此一份**，
   各域通过转发调用（见 `core/plugins/domains/_base.py`）。
3. `permissions` 只做声明与审计（D7），不做执行门控。
4. `migrate()` 强制 `plugin_<id>_` 表名前缀，防止插件污染核心 schema。

> **域必须是实例属性，不能是 `@property`**：`tools/gen_plugin_api_docs.py` 用
> AST 静态解析与运行时反射两条路径收集公开方法，`@property` 会让两者不一致，
> `test_ast_and_introspection_agree_on_public_methods` 会失败（方案 §3.5）。

> **下划线前缀的方法不是插件契约**：它们是对外禁用、供域与宿主内部调用的机制层，
> 文档生成器不会把它们算进公开方法。子类化 `PluginAPI` 不是受支持的用法。
"""

import contextlib
import json
import logging
import os
import re
import shutil
from datetime import datetime

from flask import Blueprint

from core.config import BASE_DIR, CARDS_FOLDER, DATA_DIR, load_config
from core.context import ctx
from core.data.ui_store import (
    get_tag_management_prefs,
    get_tag_taxonomy,
    load_ui_data,
    load_ui_data_or_empty,
    set_tag_management_prefs,
    set_tag_taxonomy,
    update_ui_data,
)
from core.plugins import hooks, job_store
from core.plugins import secrets as secrets_store
from core.plugins.errors import PluginLoadError
from core.services.tag_management_service import build_known_tag_set, filter_governed_tags
from core.utils.filesystem import cleanup_old_snapshots, write_snapshot_file
from core.utils.hash import get_file_hash_and_size
from core.utils.image import extract_card_info, find_sidecar_image, write_card_metadata
from core.utils.paths import is_under_base
from core.utils.source_revision import build_file_source_revision
from core.utils.text import estimate_text_tokens
from core.version import APP_VERSION

logger = logging.getLogger(__name__)

PLUGIN_UI_NAMESPACE = '_plugins_v1'
TAG_ORDER_KEY = '_tag_order_v1'
PLUGIN_DATA_QUOTA_BYTES = 256 * 1024
PLUGIN_DATA_QUOTA_WARN_BYTES = int(PLUGIN_DATA_QUOTA_BYTES * 0.8)

#: 分类名长度上限（分类名可能来自 AI 输出，必须夹紧）
CATEGORY_NAME_MAX_LENGTH = 64

#: Windows 非法字符 + 路径分隔符：分类名与文件名一律拒绝
_INVALID_NAME_CHARS = set('\\/:*?"<>|')

#: 分类重命名/创建时要避开的保留目录名（`core/consts.RESERVED_RESOURCE_NAMES`）
_RESERVED_CATEGORY_NAMES = frozenset({
    'notes', 'backups', 'lorebooks', 'thumbnails', 'cards', 'trash',
})


class _PluginDataQuotaExceeded(Exception):
    """内部信号：插件 ui_data 命名空间超过配额，用于中断本次保存（N4）。"""


def _measure_namespace(entry) -> int | None:
    """命名空间序列化后的字节数；无法序列化时返回 None（不阻断写入）。"""
    try:
        return len(json.dumps(entry, ensure_ascii=False).encode('utf-8'))
    except (TypeError, ValueError):
        return None


# 允许通过 write_card_fields 改写的卡片字段
CARD_FIELD_KEYS = frozenset({
    'name', 'description', 'first_mes', 'mes_example', 'creator',
    'character_version', 'tags', 'alternate_greetings', 'system_prompt',
    'post_history_instructions', 'personality', 'scenario', 'creator_notes',
})

_MIGRATION_PATTERN = re.compile(
    r'^\s*CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)',
    re.IGNORECASE,
)


class _BlueprintProbe:
    """收集蓝图将要注册的路由规则（只读探针，不改动蓝图状态）。"""

    def __init__(self):
        self.rules = []

    def add_url_rule(self, rule, endpoint=None, view_func=None, **options):
        self.rules.append((rule, frozenset(options.get('methods') or ('GET',))))

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def _normalize_tag_list(tags) -> list:
    if isinstance(tags, str):
        tags = [tags]
    elif not isinstance(tags, (list, tuple, set)):
        return []

    result = []
    seen = set()
    for item in tags:
        if item is None:
            continue
        tag = str(item).strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        result.append(tag)
    return result


def _is_valid_category_name(name) -> bool:
    """分类**单段**名称校验（方案 §P0-1 的安全提醒）。

    分类名很可能来自 AI 输出，因此这里强制：非空、不含路径分隔符与 Windows
    非法字符、不是 `.` / `..`、长度 ≤ 64、不在保留名列表里。
    """
    if not isinstance(name, str):
        return False
    value = name.strip()
    if not value or value in ('.', '..'):
        return False
    if len(value) > CATEGORY_NAME_MAX_LENGTH:
        return False
    if '\x00' in value:
        return False
    if any(char in _INVALID_NAME_CHARS for char in value):
        return False
    if value.lower() in _RESERVED_CATEGORY_NAMES:
        return False
    return True


def _is_valid_category_path(path, *, allow_empty: bool = False) -> bool:
    """分类**路径**校验：先拒绝绝对路径/盘符，再逐段走 `_is_valid_category_name`。

    `'根目录'`（主程序 UI 里表示根的关键字）等价于空串。
    """
    if path is None:
        return False

    raw = str(path).strip()
    if raw in ('', '根目录'):
        return allow_empty

    # 绝对路径与盘符一律拒绝——**不能**先 strip('/') 再判断，
    # 否则 `/abs/path` 会被静默归一成相对路径 `abs/path` 而绕过校验。
    if raw.startswith(('/', '\\')):
        return False
    if os.path.splitdrive(raw)[0]:
        return False
    if os.path.isabs(raw):
        return False

    value = raw.replace('\\', '/').strip('/')
    if not value:
        return False
    if len(value) > CATEGORY_NAME_MAX_LENGTH * 4:
        return False
    return all(_is_valid_category_name(part) for part in value.split('/'))


class PluginAPI:
    """插件能力门面。每个已加载插件持有独立实例。

    域对象在 `__init__` 里**构造一次**并作为实例属性挂上：保证
    `api.cards is api.cards`（插件的 `isinstance` / 缓存不会失效），
    也让 AST 与反射两条收集路径保持一致（见模块文档）。
    """

    def __init__(self, manifest, app=None):
        self._manifest = manifest
        self._app = app
        self.plugin_id = manifest.plugin_id
        self.manifest = manifest.to_dict()
        self.app_version = APP_VERSION
        self._default_blueprint = None
        self._default_registered = False
        self._active_run_id = None

        # ---- 域实例（实例属性，不是 @property：见模块文档）----
        # 域名→类 的唯一来源是 `DOMAIN_CLASSES`；这里按它构造，保证
        # `api.cards is api.cards`，也让文档生成器与测试能枚举同一份清单。
        from core.plugins.domains import DOMAIN_CLASSES

        for domain_name, domain_class in DOMAIN_CLASSES.items():
            setattr(self, domain_name, domain_class(self))

    # ================================================================ 事件

    def on(self, event: str, handler) -> None:
        """订阅事件（核心事件或本插件的自定义事件）。"""
        hooks.register(event, handler, plugin_id=self.plugin_id)

    def emit(self, event: str, payload: dict) -> None:
        """派发事件；插件自定义事件必须以 `<plugin_id>:` 开头。"""
        name = str(event or '').strip()
        if not hooks.is_core_event(name):
            name = hooks.build_custom_event_name(self.plugin_id, name)
            if not name:
                raise ValueError(f'插件自定义事件必须以 "{self.plugin_id}:" 开头: {event}')
        hooks.emit(name, payload if isinstance(payload, dict) else {})

    # ================================================================ 工具

    def estimate_tokens(self, text) -> int:
        """通用文本 token 估算，与前端 `api.estimateTokens` **同一公式**。

        公式：`ceil(CJK 数 + 非 CJK 数 / 3.5)`。后端卡片级估算
        （`core/utils/text.py:calculate_token_count`）与前端
        （`static/js/pluginHost.js:estimateTokens`）都收敛到同一实现，
        三处永不漂移。
        """
        return estimate_text_tokens(text)

    # ==================================================== 机制层（非契约）

    # 下面所有下划线成员都是**内部机制**，不属于插件契约：
    # 域通过 `DomainBase` 转发调用它们，保证一致性口径只有一份。

    # ---- 蓝图与路由 ----

    def _check_route_conflicts(self, blueprint, prefix: str) -> list:
        probe = _BlueprintProbe()
        for deferred in getattr(blueprint, 'deferred_functions', ()) or ():
            try:
                deferred(probe)
            except Exception:  # noqa: BLE001 - 探针失败不应阻断注册
                logger.debug('蓝图探针执行失败', exc_info=True)

        if self._app is None:
            return []

        existing = {}
        for rule in self._app.url_map.iter_rules():
            methods = frozenset(rule.methods or ())
            existing.setdefault(rule.rule, set()).update(methods - {'HEAD', 'OPTIONS'})

        conflicts = []
        for rule, methods in probe.rules:
            full_rule = f'{prefix}{rule}' if rule != '/' else f'{prefix}/'
            occupied = existing.get(full_rule)
            if occupied and (set(methods) & set(occupied)):
                conflicts.append(full_rule)
        return conflicts

    def _register_blueprint(self, blueprint) -> bool:
        """注册插件蓝图，前缀强制为 `/api/plugins/<plugin_id>`。"""
        if self._app is None:
            raise PluginLoadError('插件 API 未绑定 Flask 应用，无法注册蓝图')
        if not isinstance(blueprint, Blueprint):
            raise PluginLoadError(f'blueprint() 需要 Flask Blueprint，收到 {type(blueprint).__name__}')

        prefix = f'/api/plugins/{self.plugin_id}'
        conflicts = self._check_route_conflicts(blueprint, prefix)
        if conflicts:
            logger.error('插件 %s 的路由与既有路由冲突，已拒绝注册: %s', self.plugin_id, conflicts)
            return False

        try:
            self._app.register_blueprint(blueprint, url_prefix=prefix)
        except Exception as exc:  # noqa: BLE001 - 注册失败要给出可读原因
            logger.error('插件 %s 蓝图注册失败: %s', self.plugin_id, exc)
            return False
        return True

    def _ensure_default_blueprint(self) -> Blueprint:
        if self._default_blueprint is None:
            name = f'plugin_{self.plugin_id.replace("-", "_")}'
            self._default_blueprint = Blueprint(name, __name__)
        return self._default_blueprint

    def _route(self, rule: str, methods=None):
        """装饰器：把视图函数注册到本插件的默认蓝图。"""
        def decorator(func):
            bp = self._ensure_default_blueprint()
            bp.add_url_rule(
                rule,
                endpoint=func.__name__,
                view_func=func,
                methods=list(methods or ('GET',)),
            )
            return func

        return decorator

    def finalize(self) -> bool:
        """注册 `_route()` 收集到的默认蓝图（由 registry 在 `register()` 之后调用）。"""
        if self._default_blueprint is None or self._default_registered:
            return True
        self._default_registered = self._register_blueprint(self._default_blueprint)
        return self._default_registered

    # ---- 配置 ----

    def _plugin_entry(self, ui_data: dict, *, create: bool = False) -> dict:
        namespace = ui_data.get(PLUGIN_UI_NAMESPACE)
        if not isinstance(namespace, dict):
            if not create:
                return {}
            namespace = {}
            ui_data[PLUGIN_UI_NAMESPACE] = namespace

        entry = namespace.get(self.plugin_id)
        if not isinstance(entry, dict):
            if not create:
                return {}
            entry = {}
            namespace[self.plugin_id] = entry
        return entry

    def _get_config(self) -> dict:
        config = {}
        properties = (self._manifest.config_schema or {}).get('properties') or {}
        for key, spec in properties.items():
            if isinstance(spec, dict) and 'default' in spec:
                config[key] = spec['default']

        entry = self._plugin_entry(load_ui_data_or_empty())
        stored = entry.get('config')
        if isinstance(stored, dict):
            config.update(stored)
        return config

    def _set_config(self, patch: dict) -> bool:
        if not isinstance(patch, dict):
            return False

        allowed = set(((self._manifest.config_schema or {}).get('properties') or {}).keys())
        filtered = {key: value for key, value in patch.items() if key in allowed} if allowed else dict(patch)
        if not filtered:
            return False

        def mutator(ui_data):
            entry = self._plugin_entry(ui_data, create=True)
            current = entry.get('config')
            merged = dict(current) if isinstance(current, dict) else {}
            merged.update(filtered)
            entry['config'] = merged

        return bool(update_ui_data(mutator))

    # ---- 密钥 ----

    def _get_secret(self, key: str):
        value = secrets_store.get_secret(self.plugin_id, key)
        if value is not None and value != '':
            return value

        spec = ((self._manifest.secret_schema or {}).get('properties') or {}).get(str(key))
        if isinstance(spec, dict) and not spec.get('secret') and 'default' in spec:
            return spec['default']
        return None

    def _set_secret(self, key: str, value) -> bool:
        return secrets_store.set_secret(self.plugin_id, key, value)

    def _list_secrets(self) -> dict:
        return secrets_store.describe_secrets(self.plugin_id, self._manifest.secret_schema)

    # ---- 私有数据 ----

    def _table_prefix(self) -> str:
        return f"plugin_{self.plugin_id.replace('-', '_')}_"

    def _migrate(self, statements) -> None:
        if isinstance(statements, str):
            statements = [statements]
        if not isinstance(statements, (list, tuple)):
            raise ValueError('migrate 需要语句列表')

        prefix = self._table_prefix()
        cleaned = []
        for statement in statements:
            text = str(statement or '').strip().rstrip(';')
            if not text:
                continue
            match = _MIGRATION_PATTERN.match(text)
            if not match:
                raise ValueError(f'migrate 只允许 CREATE TABLE / CREATE INDEX 语句: {text[:60]}')
            name = match.group(1)
            if not name.startswith(prefix):
                raise ValueError(f'表名/索引名必须以 {prefix} 开头: {name}')
            cleaned.append(text)

        if not cleaned:
            return

        conn = job_store.connect(ensure_schema=False)
        try:
            for text in cleaned:
                conn.execute(text)
            conn.commit()
        finally:
            conn.close()

    def _data_dir(self) -> str:
        target = os.path.join(self._manifest.plugin_dir, 'data')
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as exc:
            logger.warning('插件 %s 的 data 目录创建失败: %s', self.plugin_id, exc)
        return target

    def _ui_data_read(self) -> dict:
        entry = self._plugin_entry(load_ui_data_or_empty())
        try:
            return json.loads(json.dumps(entry, ensure_ascii=False))
        except (TypeError, ValueError):
            return dict(entry)

    def _ui_data_update(self, mutator) -> bool:
        if not callable(mutator):
            return False

        # `update_ui_data` 不捕获 mutator 异常，因此用它中断保存即可原子回滚
        rejected = {'reason': ''}

        def _inner(ui_data):
            entry = self._plugin_entry(ui_data, create=True)
            result = mutator(entry)
            if isinstance(result, dict):
                entry.clear()
                entry.update(result)

            size = _measure_namespace(entry)
            if size is None:
                return None
            if size > PLUGIN_DATA_QUOTA_BYTES:
                rejected['reason'] = (
                    f'命名空间体积 {size} 字节，超过 {PLUGIN_DATA_QUOTA_BYTES} 字节上限'
                )
                raise _PluginDataQuotaExceeded(rejected['reason'])
            if size > PLUGIN_DATA_QUOTA_WARN_BYTES:
                logger.warning(
                    '插件 %s 的 ui_data 命名空间已达 %s 字节（上限 %s），即将被拒绝',
                    self.plugin_id, size, PLUGIN_DATA_QUOTA_BYTES,
                )
            return None

        try:
            saved = bool(update_ui_data(_inner))
        except _PluginDataQuotaExceeded:
            saved = False

        if not saved and rejected['reason']:
            logger.warning('插件 %s 的 ui_data 写入被拒绝：%s', self.plugin_id, rejected['reason'])
        return saved

    # ---- 日志 ----

    def _write_log(self, level: str, message: str, **extra) -> None:
        normalized = str(level or 'info').strip().lower()
        log_method = getattr(logger, normalized, None)
        if not callable(log_method):
            log_method = logger.info

        text = str(message or '')
        if extra:
            try:
                text = f'{text} | {json.dumps(extra, ensure_ascii=False)}'
            except (TypeError, ValueError):
                pass
        log_method('[plugin:%s] %s', self.plugin_id, text)

        if not self._active_run_id:
            return
        try:
            from core.plugins import jobs

            jobs.append_log_event(str(self._active_run_id), normalized, text)
        except Exception:  # noqa: BLE001
            logger.debug('插件 %s 追加作业日志失败', self.plugin_id, exc_info=True)

    def bind_job(self, run_id):
        """把当前执行上下文绑定到某个作业（worker 内部使用）。"""
        self._active_run_id = str(run_id) if run_id else None

    # ---- 文件系统（机制内部化，不再对外暴露）----

    @contextlib.contextmanager
    def _suppress_fs_events(self, seconds: float = 1.5):
        """抑制文件系统事件的上下文管理器。

        写 `data/library/` 或 `data/system/` 下的文件前必须使用，否则会触发扫描器/
        监控重扫；写 `data/plugins/<id>/data/` 无需使用。

        这是**机制层**：插件不直接调它，写卡片/世界书走域方法时由域内部抑制。
        """
        from core.services.scan_service import suppress_fs_events as _suppress

        try:
            _suppress(seconds)
        except Exception:  # noqa: BLE001
            logger.debug('插件 %s 无法开启 fs 事件抑制', self.plugin_id, exc_info=True)
        try:
            yield
        finally:
            try:
                _suppress(seconds)
            except Exception:  # noqa: BLE001
                pass

    def _card_lock(self, card_id):
        """取卡片写锁；宿主未提供时返回 nullcontext（不阻断调用）。"""
        lock = ctx.get_card_lock(card_id) if hasattr(ctx, 'get_card_lock') else None
        return lock if lock is not None else contextlib.nullcontext()

    def _resolve_card_path(self, card_id) -> str:
        card_id = str(card_id or '').strip().replace('\\', '/')
        if not card_id or card_id.startswith('/') or '..' in card_id.split('/'):
            return ''
        full_path = os.path.realpath(os.path.join(str(CARDS_FOLDER), card_id.replace('/', os.sep)))
        if not is_under_base(full_path, str(CARDS_FOLDER), resolve_symlinks=True):
            return ''
        return full_path

    # ---- 卡片核心机制 ----

    def _card_tags(self, info: dict) -> list:
        data_block = info.get('data') if isinstance(info.get('data'), dict) else info
        tags = data_block.get('tags') or []
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.split(',') if part.strip()]
        return _normalize_tag_list(tags)

    def _sync_card_index(self, card_id: str, full_path: str, card_data: dict) -> None:
        """同步内存缓存、数据库行与索引增量。

        这是现有实现里最容易漏掉的一环：**任何**改动卡片的位置或内容的域方法
        都必须走它，否则会出现「插件改完卡片后列表不刷新」这类难查的 bug。
        """
        data_block = card_data.get('data') if isinstance(card_data.get('data'), dict) else card_data
        tags = self._card_tags(card_data)
        char_name = data_block.get('name') or card_data.get('name') or ''
        try:
            mtime = os.path.getmtime(full_path)
        except OSError:
            mtime = 0.0

        cache = getattr(ctx, 'cache', None)
        if cache is not None:
            try:
                cache.update_card_data(card_id, {
                    'char_name': char_name,
                    'description': data_block.get('description', ''),
                    'first_mes': data_block.get('first_mes', ''),
                    'mes_example': data_block.get('mes_example', ''),
                    'creator': data_block.get('creator', ''),
                    'char_version': data_block.get('character_version', ''),
                    'tags': tags,
                    'last_modified': mtime,
                })
            except Exception:  # noqa: BLE001 - 缓存同步失败不应影响写盘结果
                logger.warning('插件 %s 同步卡片缓存失败', self.plugin_id, exc_info=True)

        try:
            file_hash, file_size = get_file_hash_and_size(full_path)
        except Exception:  # noqa: BLE001
            file_hash, file_size = '', 0

        try:
            conn = job_store.connect(ensure_schema=False)
            try:
                conn.execute(
                    '''
                    UPDATE card_metadata
                    SET char_name = ?, description = ?, first_mes = ?, mes_example = ?,
                        tags = ?, creator = ?, char_version = ?, last_modified = ?,
                        file_hash = ?, file_size = ?
                    WHERE id = ?
                    ''',
                    (
                        char_name,
                        data_block.get('description', ''),
                        data_block.get('first_mes', ''),
                        data_block.get('mes_example', ''),
                        json.dumps(tags, ensure_ascii=False),
                        data_block.get('creator', ''),
                        data_block.get('character_version', ''),
                        mtime,
                        file_hash,
                        file_size,
                        card_id,
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            logger.warning('插件 %s 同步卡片数据库行失败', self.plugin_id, exc_info=True)

        try:
            from core.services.index_job_worker import enqueue_index_job

            enqueue_index_job('upsert_card', card_id, card_id)
        except Exception:  # noqa: BLE001 - 索引未就绪时忽略
            logger.debug('插件 %s 触发索引增量失败', self.plugin_id, exc_info=True)

    # ---- 卡片读写 ----

    def _read_card(self, card_id: str):
        full_path = self._resolve_card_path(card_id)
        if not full_path or not os.path.isfile(full_path):
            return None
        info = extract_card_info(full_path)
        if not isinstance(info, dict):
            return None
        info.setdefault('id', str(card_id or '').strip().replace('\\', '/'))
        return info

    def _read_cards(self, card_ids) -> dict:
        result = {}
        for card_id in card_ids or []:
            key = str(card_id or '').strip().replace('\\', '/')
            if not key:
                continue
            result[key] = self._read_card(key)
        return result

    def _write_card_fields(self, card_id: str, patch: dict) -> bool:
        if not isinstance(patch, dict) or not patch:
            return False

        card_id = str(card_id or '').strip().replace('\\', '/')
        full_path = self._resolve_card_path(card_id)
        if not full_path or not os.path.isfile(full_path):
            return False

        with self._card_lock(card_id):
            info = extract_card_info(full_path)
            if not isinstance(info, dict):
                return False

            data_block = info.get('data') if isinstance(info.get('data'), dict) else None
            for key, value in patch.items():
                if key not in CARD_FIELD_KEYS:
                    continue
                info[key] = value
                if data_block is not None:
                    data_block[key] = value

            with self._suppress_fs_events():
                if not write_card_metadata(full_path, info):
                    logger.error('插件 %s 写入卡片 %s 失败', self.plugin_id, card_id)
                    return False

            self._sync_card_index(card_id, full_path, info)
        return True

    def _apply_tags(self, card_ids, *, add=(), remove=(), replace: bool = False) -> dict:
        ids = [str(item or '').strip().replace('\\', '/') for item in (card_ids or [])]
        ids = [item for item in ids if item]
        if not ids:
            return {'updated': 0, 'added': [], 'removed': [], 'failed': []}

        ui_data = load_ui_data()
        governance = filter_governed_tags(
            _normalize_tag_list(add),
            ui_data=ui_data,
            known_tags=build_known_tag_set(ui_data=ui_data),
        )
        accepted_add = governance['accepted']
        remove_set = set(_normalize_tag_list(remove))

        updated = 0
        added_all = []
        removed_all = []
        failed = []

        for card_id in ids:
            full_path = self._resolve_card_path(card_id)
            if not full_path or not os.path.isfile(full_path):
                failed.append(card_id)
                continue

            with self._card_lock(card_id):
                info = extract_card_info(full_path)
                if not isinstance(info, dict):
                    failed.append(card_id)
                    continue

                data_block = info.get('data') if isinstance(info.get('data'), dict) else info
                before = self._card_tags(info)
                after = list(accepted_add) if replace else list(before)

                if not replace:
                    existing = set(after)
                    for tag in accepted_add:
                        if tag not in existing:
                            after.append(tag)
                            existing.add(tag)

                if remove_set:
                    after = [item for item in after if item not in remove_set]

                after = _normalize_tag_list(after)
                if after == before:
                    continue

                data_block['tags'] = after
                if data_block is not info:
                    info['tags'] = after

                with self._suppress_fs_events():
                    if not write_card_metadata(full_path, info):
                        failed.append(card_id)
                        continue

                self._sync_card_index(card_id, full_path, info)
                updated += 1
                added_all.extend([tag for tag in after if tag not in before])
                removed_all.extend([tag for tag in before if tag not in after])

        return {
            'updated': updated,
            'added': _normalize_tag_list(added_all),
            'removed': _normalize_tag_list(removed_all),
            'failed': failed,
            'skipped_unknown': governance['skipped_unknown'],
            'skipped_blacklist': governance['skipped_blacklist'],
        }

    # ---- 本地备注（ui_data）----

    def _resolve_ui_key(self, card_id: str) -> str:
        """解析 `ui_data` 键：bundle 卡片返回 bundle_dir，否则返回 card_id。"""
        try:
            from core.services.card_service import resolve_ui_key

            return str(resolve_ui_key(card_id) or '').strip().replace('\\', '/') or card_id
        except Exception:  # noqa: BLE001 - 缓存未就绪时退化为主键
            logger.debug('插件 %s 解析 ui_key 失败', self.plugin_id, exc_info=True)
            return card_id

    def _bundle_cover_id(self, bundle_dir: str):
        """取 bundle 的封面版本 id（版本级备注的向后兼容需要它）。"""
        cache = getattr(ctx, 'cache', None)
        bundle_map = getattr(cache, 'bundle_map', {}) if cache else {}
        id_map = getattr(cache, 'id_map', {}) if cache else {}
        if not isinstance(bundle_map, dict) or not isinstance(id_map, dict):
            return None

        main_bundle_id = bundle_map.get(bundle_dir)
        if not main_bundle_id:
            return None
        bundle_card = id_map.get(main_bundle_id)
        versions = bundle_card.get('versions') if isinstance(bundle_card, dict) else None
        if isinstance(versions, list) and versions and isinstance(versions[0], dict):
            return versions[0].get('id')
        return None

    def _read_card_note(self, card_id: str) -> str:
        """读本地备注（`ui_data[<ui_key>]` 的 `summary`；bundle 走版本级备注）。"""
        key = str(card_id or '').strip().replace('\\', '/')
        if not key:
            return ''

        ui_data = load_ui_data_or_empty()
        ui_key = self._resolve_ui_key(key)
        parent_dir = os.path.dirname(key).replace('\\', '/')

        from core.data.ui_store import get_version_remark

        # bundle 内的版本卡片：备注挂在 bundle 目录的版本级条目上
        cache = getattr(ctx, 'cache', None)
        bundle_map = getattr(cache, 'bundle_map', {}) if cache else {}
        if isinstance(bundle_map, dict) and parent_dir in bundle_map:
            remark = get_version_remark(ui_data, parent_dir, key, self._bundle_cover_id(parent_dir))
            if isinstance(remark, dict):
                return str(remark.get('summary') or '')

        entry = ui_data.get(ui_key)
        if not isinstance(entry, dict):
            return ''

        remarks = entry.get('_version_remarks')
        if isinstance(remarks, dict) and key in remarks and isinstance(remarks[key], dict):
            return str(remarks[key].get('summary') or '')
        return str(entry.get('summary') or '')

    def _write_card_note(self, card_id: str, text: str) -> bool:
        """写本地备注（锁内合并写入 `ui_data`，保住并发的 link / resource_folder）。"""
        key = str(card_id or '').strip().replace('\\', '/')
        if not key:
            return False

        full_path = self._resolve_card_path(key)
        if not full_path or not os.path.exists(full_path):
            return False

        summary = '' if text is None else str(text)
        ui_key = self._resolve_ui_key(key)
        parent_dir = os.path.dirname(key).replace('\\', '/')

        cache = getattr(ctx, 'cache', None)
        bundle_map = getattr(cache, 'bundle_map', {}) if cache else {}
        is_bundle_version = isinstance(bundle_map, dict) and parent_dir in bundle_map

        from core.data.ui_store import set_version_remark

        def mutator(ui_data):
            entry = ui_data.get(ui_key)
            if not isinstance(entry, dict):
                entry = {}
                ui_data[ui_key] = entry

            if is_bundle_version:
                cover_id = self._bundle_cover_id(parent_dir)
                set_version_remark(
                    ui_data, parent_dir, key,
                    {
                        'summary': summary,
                        'link': entry.get('link', ''),
                        'resource_folder': entry.get('resource_folder', ''),
                    },
                    cover_id,
                )
                return

            entry['summary'] = summary

        return bool(update_ui_data(mutator))

    # ---- 卡片移动与分类 ----

    def _move_cards(self, card_ids, target_category: str) -> dict:
        """批量移动卡片（照抄 `/api/move_card` 的机制，不简化）。"""
        from core.services.card_service import move_card_internal

        ids = [str(item or '').strip().replace('\\', '/') for item in (card_ids or [])]
        ids = [item for item in ids if item]
        # 校验前**不要** strip('/')：`/abs/path` 会被静默归一成相对路径而绕过校验。
        raw_target = str(target_category or '').strip().replace('\\', '/')
        if raw_target == '根目录':
            raw_target = ''
        target = raw_target.strip('/')

        moved = []
        failed = []

        if not (raw_target == '' or _is_valid_category_path(raw_target)):
            return {
                'count': 0, 'moved': [], 'category_counts': {},
                'failed': [{'old_id': item, 'msg': f'非法目标分类: {target_category}'} for item in ids],
            }

        # 一次批量移动会触发几百次文件事件，抑制窗口要覆盖整个循环
        with self._suppress_fs_events(5.0):
            for card_id in ids:
                if not _is_valid_category_path(card_id):
                    failed.append({'old_id': card_id, 'msg': '非法卡片路径'})
                    continue

                try:
                    success, new_id, message = move_card_internal(card_id, target)
                except Exception as exc:  # noqa: BLE001 - 单张失败不影响其余
                    logger.exception('插件 %s 移动卡片 %s 失败', self.plugin_id, card_id)
                    failed.append({'old_id': card_id, 'msg': str(exc)})
                    continue

                if not success:
                    failed.append({'old_id': card_id, 'msg': message or 'Move failed'})
                    continue

                new_id = str(new_id or '').replace('\\', '/')
                new_category = new_id.rsplit('/', 1)[0] if '/' in new_id else ''
                moved.append({
                    'old_id': card_id,
                    'new_id': new_id,
                    'new_filename': os.path.basename(new_id),
                    'new_category': new_category,
                })

        catalog = getattr(ctx, 'cache', None)
        category_counts = dict(getattr(catalog, 'category_counts', {}) or {}) if catalog else {}

        if moved:
            try:
                hooks.emit('card.moved', {
                    'moves': [
                        {'old_id': item['old_id'], 'new_id': item['new_id']} for item in moved
                    ],
                })
            except Exception:  # noqa: BLE001 - 通知失败不影响移动结果
                logger.debug('插件 %s 派发 card.moved 失败', self.plugin_id, exc_info=True)

        return {
            'count': len(moved),
            'moved': moved,
            'failed': failed,
            'category_counts': category_counts,
        }

    def _list_categories(self) -> list:
        """全部分类路径（含子分类），相对 `CARDS_FOLDER`。"""
        root = str(CARDS_FOLDER)
        found = set()

        cache = getattr(ctx, 'cache', None)
        visible = getattr(cache, 'visible_folders', None) if cache else None
        if isinstance(visible, (list, tuple, set)):
            for item in visible:
                path = str(item or '').strip().replace('\\', '/').strip('/')
                if path and _is_valid_category_path(path):
                    found.add(path)

        try:
            for current_root, dirs, _files in os.walk(root):
                rel = os.path.relpath(current_root, root).replace('\\', '/')
                if rel in ('.', ''):
                    for name in dirs:
                        if _is_valid_category_name(name):
                            found.add(name)
                    continue
                if _is_valid_category_path(rel):
                    found.add(rel)
        except OSError:
            logger.debug('插件 %s 遍历卡片目录失败', self.plugin_id, exc_info=True)

        return sorted(found)

    def _create_category(self, name: str, *, parent: str = '') -> bool:
        """创建分类目录（幂等）；分类名与父路径都强制白名单校验。"""
        leaf = str(name or '').strip()
        if not _is_valid_category_name(leaf):
            self._write_log('warning', f'拒绝创建非法分类名: {name!r}')
            return False

        parent_raw = str(parent or '').strip().replace('\\', '/')
        if parent_raw == '根目录':
            parent_raw = ''
        # 校验前不 strip('/')：绝对父路径必须被拒绝
        if not (parent_raw == '' or _is_valid_category_path(parent_raw)):
            self._write_log('warning', f'拒绝创建分类：非法父路径 {parent!r}')
            return False
        parent_path = parent_raw.strip('/')

        rel_path = f'{parent_path}/{leaf}' if parent_path else leaf
        target = os.path.join(str(CARDS_FOLDER), rel_path.replace('/', os.sep))
        if not is_under_base(os.path.realpath(target), str(CARDS_FOLDER), resolve_symlinks=True):
            return False

        if os.path.isdir(target):
            return True

        try:
            with self._suppress_fs_events():
                os.makedirs(target, exist_ok=True)
        except OSError as exc:
            self._write_log('error', f'创建分类失败: {exc}')
            return False

        cache = getattr(ctx, 'cache', None)
        visible = getattr(cache, 'visible_folders', None) if cache else None
        if isinstance(visible, list) and rel_path not in visible:
            visible.append(rel_path)
            visible.sort()
        return True

    def _rename_category(self, old_path: str, new_path: str) -> bool:
        """重命名 / 移动分类（含 DB 与 `ui_data` 前缀迁移）。"""
        from core.data.db_session import get_db
        from core.services.card_service import (
            rename_folder_in_db,
            rename_folder_in_ui,
            sync_folder_prefix_after_fs_move,
        )

        old_raw = str(old_path or '').strip().replace('\\', '/')
        new_raw = str(new_path or '').strip().replace('\\', '/')
        # 校验前不 strip('/')：绝对路径必须被拒绝，而不是被归一成相对路径
        if not _is_valid_category_path(old_raw) or not _is_valid_category_path(new_raw):
            self._write_log('warning', f'拒绝重命名分类：非法路径 {old_path!r} → {new_path!r}')
            return False

        old_rel = old_raw.strip('/')
        new_rel = new_raw.strip('/')
        old_full = os.path.join(str(CARDS_FOLDER), old_rel.replace('/', os.sep))
        new_full = os.path.join(str(CARDS_FOLDER), new_rel.replace('/', os.sep))
        real_root = os.path.realpath(str(CARDS_FOLDER))
        if not is_under_base(os.path.realpath(old_full), real_root, resolve_symlinks=True):
            return False
        if not is_under_base(os.path.realpath(new_full), real_root, resolve_symlinks=True):
            return False

        if not os.path.isdir(old_full) or os.path.exists(new_full):
            return False

        try:
            with self._suppress_fs_events(4.0):
                os.renames(old_full, new_full)
        except OSError as exc:
            self._write_log('error', f'分类重命名失败: {exc}')
            return False

        try:
            ui_data = load_ui_data()
            try:
                conn = get_db()
                sync_folder_prefix_after_fs_move(
                    conn=conn, ui_data=ui_data, old_path=old_rel, new_path=new_rel,
                )
            finally:
                pass
        except Exception:  # noqa: BLE001 - 同步失败时回退到全量重载
            self._write_log('warning', '分类已重命名，但数据库/UI 前缀同步失败，将触发全量重载')
            try:
                from core.services.cache_service import schedule_reload

                schedule_reload(reason='plugin:rename_category')
            except Exception:  # noqa: BLE001
                logger.debug('插件 %s 触发重载失败', self.plugin_id, exc_info=True)
            # 兜底：DB 与 ui_data 的旧前缀单独迁移一次
            try:
                rename_folder_in_db(old_rel, new_rel)
                ui_data = load_ui_data()
                if rename_folder_in_ui(ui_data, old_rel, new_rel):
                    from core.data.ui_store import save_ui_data

                    save_ui_data(ui_data)
            except Exception:  # noqa: BLE001
                logger.warning('插件 %s 分类前缀兜底迁移失败', self.plugin_id, exc_info=True)

        cache = getattr(ctx, 'cache', None)
        visible = getattr(cache, 'visible_folders', None) if cache else None
        if isinstance(visible, list):
            remapped = []
            for item in visible:
                text = str(item or '')
                if text == old_rel:
                    remapped.append(new_rel)
                elif text.startswith(old_rel + '/'):
                    remapped.append(new_rel + text[len(old_rel):])
                else:
                    remapped.append(text)
            visible[:] = sorted({item for item in remapped if item})
        return True

    # ---- 卡片结构化查询 ----

    def _list_cards(self, *, query: str = '', category: str = '', tags=(),
                    exclude_tags=(), limit: int = 100, offset: int = 0,
                    sort: str = '', **filters) -> dict:
        """结构化查询卡片（走索引，不用裸 SQL、不做全表扫）。"""
        from core.services.card_index_query_service import query_indexed_cards

        page_size = int(limit) if int(limit or 0) > 0 else 0
        page = 1
        if page_size and offset:
            page = (max(0, int(offset)) // page_size) + 1

        payload = {
            'search': query,
            'category': category,
            'include_tags': _normalize_tag_list(tags),
            'exclude_tags': _normalize_tag_list(exclude_tags),
            'page': page,
            'page_size': page_size or 10000,
            'sort': sort,
            **filters,
        }

        result = query_indexed_cards(payload)
        items = result.get('cards') or []
        if offset and page_size:
            items = items[offset % page_size:]
        return {
            'items': items,
            'total': int(result.get('total_count') or 0),
            'index_ready': bool(result.get('index_ready')),
        }

    def _count_cards(self, **filters) -> int:
        """按与 `_list_cards` 相同的条件计数（只取总数）。"""
        payload = dict(filters)
        payload['limit'] = 0
        payload['offset'] = 0
        # 计数不需要拉数据，把页大小压到 1 只取 total
        payload['page_size'] = 1
        payload['page'] = 1
        return int(self._list_cards(**payload).get('total') or 0)

    # ---- 标签 ----

    def _read_tag_library(self) -> dict:
        ui_data = load_ui_data_or_empty()
        cache = getattr(ctx, 'cache', None)
        tags = list(getattr(cache, 'global_tags', []) or [])
        if not tags:
            tags = self._read_tags_from_db()

        raw_order = ui_data.get(TAG_ORDER_KEY)
        if isinstance(raw_order, dict):
            order = _normalize_tag_list(raw_order.get('order'))
            order_enabled = bool(raw_order.get('enabled', bool(order)))
            order_enabled_keys = raw_order.get('enabled_keys')
        else:
            order = _normalize_tag_list(raw_order)
            order_enabled = bool(order)
            order_enabled_keys = None

        return {
            'tags': tags,
            'order': order,
            'order_enabled': order_enabled,
            'order_enabled_keys': order_enabled_keys,
            'taxonomy': get_tag_taxonomy(ui_data),
            'prefs': get_tag_management_prefs(ui_data),
        }

    def _read_tags_from_db(self) -> list:
        pool = set()
        try:
            conn = job_store.connect(ensure_schema=False)
            try:
                rows = conn.execute('SELECT tags FROM card_metadata').fetchall()
            finally:
                conn.close()
        except Exception:  # noqa: BLE001
            logger.warning('插件 %s 读取标签库失败', self.plugin_id, exc_info=True)
            return []

        for row in rows:
            try:
                for tag in json.loads(row['tags'] or '[]'):
                    if tag:
                        pool.add(str(tag))
            except (TypeError, ValueError):
                continue
        return sorted(pool)

    def _read_tag_taxonomy(self) -> dict:
        return get_tag_taxonomy(load_ui_data_or_empty())

    def _update_tag_taxonomy(self, patch: dict) -> bool:
        if not isinstance(patch, dict) or not patch:
            return False

        def mutator(ui_data):
            current = get_tag_taxonomy(ui_data)
            merged = dict(current)
            merged.update(patch)
            set_tag_taxonomy(ui_data, merged)

        return bool(update_ui_data(mutator))

    def _read_tag_prefs(self) -> dict:
        return get_tag_management_prefs(load_ui_data_or_empty())

    def _update_tag_prefs(self, patch: dict) -> bool:
        if not isinstance(patch, dict) or not patch:
            return False

        def mutator(ui_data):
            current = get_tag_management_prefs(ui_data)
            merged = dict(current)
            merged.update(patch)
            set_tag_management_prefs(ui_data, merged)

        return bool(update_ui_data(mutator))

    def _create_tags(self, tags) -> dict:
        """把标签加入分类体系（不写任何卡片）。"""
        wanted = _normalize_tag_list(tags)
        if not wanted:
            return {'created': [], 'existing': [], 'failed': []}

        ui_data = load_ui_data_or_empty()
        known = build_known_tag_set(ui_data=ui_data)
        library = set(self._read_tag_library().get('tags') or [])

        created = []
        existing = []
        failed = []
        taxonomy = get_tag_taxonomy(ui_data)
        tag_to_category = taxonomy.get('tag_to_category')
        if not isinstance(tag_to_category, dict):
            tag_to_category = {}

        for tag in wanted:
            if tag in known or tag in library:
                existing.append(tag)
                continue
            if not _is_valid_tag_name(tag):
                failed.append(tag)
                continue
            tag_to_category[tag] = tag_to_category.get(tag, '')
            created.append(tag)

        if not created:
            return {'created': [], 'existing': existing, 'failed': failed}

        def mutator(current):
            current_taxonomy = get_tag_taxonomy(current)
            merged = dict(current_taxonomy)
            merged_tags = merged.get('tag_to_category')
            if not isinstance(merged_tags, dict):
                merged_tags = {}
            else:
                merged_tags = dict(merged_tags)
            for tag in created:
                merged_tags.setdefault(tag, '')
            merged['tag_to_category'] = merged_tags
            set_tag_taxonomy(current, merged)

        if not update_ui_data(mutator):
            return {'created': [], 'existing': existing, 'failed': failed + created}

        return {'created': created, 'existing': existing, 'failed': failed}

    def _merge_tags(self, replace_rules) -> dict:
        """按规则合并标签（只计算，不写卡片）。"""
        from core.automation.tag_merge import merge_tags_with_rules, parse_merge_rules

        rules = parse_merge_rules(replace_rules) if not isinstance(replace_rules, dict) or any(
            key in ('replace_rules', 'merge_rules', 'source_tags', 'from_tags', 'target_tag', 'target')
            for key in (replace_rules or {})
        ) else dict(replace_rules)

        if not isinstance(rules, dict) or not rules:
            return {'tags': [], 'changed': False, 'replacements': [], 'replace_rules': {}, 'cycles': []}

        result = merge_tags_with_rules(sorted(self._read_tag_library().get('tags') or []), rules)
        result['replace_rules'] = rules
        result['cycles'] = _detect_rule_cycles(rules)
        return result

    # ---- 世界书 ----

    def _resolve_worldbook_source(self, source) -> tuple:
        """解析世界书来源，返回 `(kind, abs_path, card_id)`；无法解析时全为空串。"""
        payload = source if isinstance(source, dict) else {}
        source_type = str(payload.get('source_type') or payload.get('type') or '').strip().lower()
        card_id = str(payload.get('card_id') or '').strip().replace('\\', '/')
        file_path = str(payload.get('file_path') or '').strip()

        if source_type in ('embedded', 'card') or card_id:
            full_path = self._resolve_card_path(card_id)
            if full_path and os.path.isfile(full_path):
                return 'embedded', full_path, card_id
            return '', '', ''

        if not file_path:
            return '', '', ''

        config = load_config()
        raw_wi = config.get('world_info_dir', 'lorebooks')
        wi_root = os.path.abspath(raw_wi if os.path.isabs(raw_wi) else os.path.join(BASE_DIR, raw_wi))
        resolved = os.path.abspath(file_path if os.path.isabs(file_path) else os.path.join(BASE_DIR, file_path))

        if is_under_base(resolved, wi_root, resolve_symlinks=True):
            return 'global', resolved, ''

        raw_res = config.get('resources_dir', 'data/assets/card_assets')
        res_root = os.path.abspath(raw_res if os.path.isabs(raw_res) else os.path.join(BASE_DIR, raw_res))
        if is_under_base(resolved, res_root, resolve_symlinks=True):
            relative = os.path.relpath(resolved, res_root).replace('\\', '/')
            if '/lorebooks/' in f'/{relative}/':
                return 'resource', resolved, ''

        return '', '', ''

    def _read_worldbook(self, source: dict):
        kind, path, card_id = self._resolve_worldbook_source(source)
        if not kind or not path or not os.path.isfile(path):
            return None

        if kind == 'embedded':
            card = self._read_card(card_id)
            if not isinstance(card, dict):
                return None
            data_block = card.get('data') if isinstance(card.get('data'), dict) else card
            book = data_block.get('character_book')
            if not book:
                return None
            if isinstance(book, dict) and isinstance(book.get('entries'), list):
                return {'entries': book['entries']}
            return {'entries': book if isinstance(book, list) else []}

        try:
            with open(path, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning('插件 %s 读取世界书失败 %s: %s', self.plugin_id, path, exc)
            return None

        if isinstance(payload, dict):
            payload.setdefault('source_revision', build_file_source_revision(path))
        return payload

    def _write_worldbook(self, source: dict, data: dict, *, expected_revision: str = '') -> dict:
        kind, path, card_id = self._resolve_worldbook_source(source)
        if not kind or not path:
            return {'success': False, 'msg': '世界书来源无法解析', 'error': 'source_invalid'}
        if not isinstance(data, dict):
            return {'success': False, 'msg': 'data 必须是对象', 'error': 'invalid_payload'}

        if expected_revision:
            current_revision = build_file_source_revision(path)
            if current_revision != expected_revision:
                return {
                    'success': False,
                    'msg': '世界书已被其他操作修改，请刷新后重试',
                    'error': 'revision_conflict',
                    'source_revision': current_revision,
                }

        lock = self._card_lock(card_id) if (kind == 'embedded' and card_id) else contextlib.nullcontext()

        with lock, self._suppress_fs_events():
            if kind == 'embedded':
                card = extract_card_info(path)
                if not isinstance(card, dict):
                    return {'success': False, 'msg': '无法解析宿主角色卡', 'error': 'card_unreadable'}
                data_block = card.get('data') if isinstance(card.get('data'), dict) else None
                if data_block is None:
                    card['character_book'] = data
                else:
                    data_block['character_book'] = data
                if not write_card_metadata(path, card):
                    return {'success': False, 'msg': '写入角色卡失败', 'error': 'write_failed'}
                self._sync_card_index(card_id, path, card)
            else:
                try:
                    with open(path, 'w', encoding='utf-8') as handle:
                        json.dump(data, handle, ensure_ascii=False, indent=2)
                except OSError as exc:
                    return {'success': False, 'msg': f'写入失败: {exc}', 'error': 'write_failed'}

                try:
                    self._record_worldbook_history(path, data)
                except Exception:  # noqa: BLE001 - 历史记账失败不影响写回结果
                    logger.warning('插件 %s 世界书历史记账失败', self.plugin_id, exc_info=True)

        return {'success': True, 'source_revision': build_file_source_revision(path)}

    def _record_worldbook_history(self, path: str, data: dict) -> None:
        """把本次写入登记到世界书条目历史（与路由层保存行为保持一致）。"""
        from core.services.wi_entry_history_service import (
            append_entry_history_records,
            reconcile_entry_history_scope,
        )

        entries = data.get('entries') if isinstance(data.get('entries'), list) else []
        records = []
        for item in entries:
            if not isinstance(item, dict):
                continue
            uid = item.get('uid') if item.get('uid') is not None else item.get('id')
            records.append({
                'entry_uid': str(uid) if uid is not None else '',
                'content': json.dumps(item, ensure_ascii=False),
                'reason': f'plugin:{self.plugin_id}',
            })

        append_entry_history_records(
            source_type='lorebook', source_id='', file_path=path, records=records,
        )
        reconcile_entry_history_scope(
            source_type='lorebook',
            source_id='',
            file_path=path,
            active_entry_uids=[record['entry_uid'] for record in records if record['entry_uid']],
        )

    # ---- 快照 ----

    def _snapshot_root(self) -> str:
        return os.path.join(str(DATA_DIR), 'system', 'backups', 'cards')

    def _snapshot_card(self, card_id: str, *, remark: str = '') -> str | None:
        full_path = self._resolve_card_path(card_id)
        if not full_path or not os.path.isfile(full_path):
            return None

        backups_root = self._snapshot_root()
        name_no_ext = os.path.splitext(os.path.basename(full_path))[0]
        ext = os.path.splitext(full_path)[1]
        safe_dir_name = re.sub(r'[\\/:*?"<>|]', '_', name_no_ext).strip() or 'unnamed_backup'
        target_dir = os.path.join(backups_root, safe_dir_name)

        try:
            os.makedirs(target_dir, exist_ok=True)
        except OSError as exc:
            logger.error('插件 %s 创建快照目录失败: %s', self.plugin_id, exc)
            return None

        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S-%f')
        safe_remark = re.sub(r'[\\/:*?"<>|]', '-', str(remark or '').strip())
        if safe_remark:
            backup_name = f'{name_no_ext}_{timestamp}__KEY__{safe_remark}{ext}'
        else:
            backup_name = f'{name_no_ext}_{timestamp}{ext}'
        dst_path = os.path.join(target_dir, backup_name)

        try:
            limit = load_config().get('snapshot_limit_manual', 20)
            cleanup_old_snapshots(target_dir, max(1, min(int(limit), 200)), prefix_filter=None)
        except Exception:  # noqa: BLE001
            logger.debug('插件 %s 清理旧快照失败', self.plugin_id, exc_info=True)

        with self._suppress_fs_events():
            if not write_snapshot_file(full_path, dst_path, None, ext.lower() == '.png'):
                return None

            if ext.lower() != '.png':
                sidecar = find_sidecar_image(full_path)
                if sidecar:
                    sidecar_ext = os.path.splitext(sidecar)[1]
                    side_name = (
                        f'{name_no_ext}_{timestamp}__KEY__{safe_remark}{sidecar_ext}'
                        if safe_remark else f'{name_no_ext}_{timestamp}{sidecar_ext}'
                    )
                    try:
                        shutil.copy2(sidecar, os.path.join(target_dir, side_name))
                    except OSError:
                        logger.debug('插件 %s 复制伴生图失败', self.plugin_id, exc_info=True)

        return dst_path

    def _list_card_snapshots(self, card_id: str) -> list:
        full_path = self._resolve_card_path(card_id)
        if not full_path:
            return []

        name_no_ext = os.path.splitext(os.path.basename(full_path))[0]
        safe_dir_name = re.sub(r'[\\/:*?"<>|]', '_', name_no_ext).strip() or 'unnamed_backup'
        target_dir = os.path.join(self._snapshot_root(), safe_dir_name)
        if not os.path.isdir(target_dir):
            return []

        ext = os.path.splitext(full_path)[1].lower()
        items = []
        try:
            names = os.listdir(target_dir)
        except OSError:
            return []

        for name in names:
            if not name.lower().endswith(('.json', '.png')):
                continue
            # 伴生图（与快照同名的图片）不是独立快照，跳过
            if ext == '.json' and not name.lower().endswith('.json'):
                continue
            if ext == '.png' and not name.lower().endswith('.png'):
                continue

            full = os.path.join(target_dir, name)
            try:
                stat = os.stat(full)
            except OSError:
                continue

            remark = ''
            marker = '__KEY__'
            if marker in name:
                stem = os.path.splitext(name)[0]
                remark = stem.split(marker, 1)[1]

            # `write_snapshot_file` 走 `shutil.copy2`，**会保留源文件的 mtime**，
            # 所以同一张卡的所有快照 mtime 相同、不能用来排序。
            # 真正的创建时刻在文件名的时间戳里（`%Y-%m-%d_%H-%M-%S-%f`）。
            match = _SNAPSHOT_TIMESTAMP_PATTERN.search(name)
            stamp = match.group(1) if match else ''

            items.append({
                'path': full,
                'name': name,
                'created_at': (
                    datetime.strptime(stamp, '%Y-%m-%d_%H-%M-%S-%f').strftime('%Y-%m-%d %H:%M:%S')
                    if stamp else datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
                ),
                'mtime': stat.st_mtime,
                'size': stat.st_size,
                'remark': remark,
                'is_auto': '__AUTO__' in name,
            })

        # 文件名时间戳倒序；解析不出时间戳的退到 mtime，再退到文件名
        items.sort(
            key=lambda item: (_snapshot_stamp_key(item['name']), item['mtime'], item['name']),
            reverse=True,
        )
        return items

    def _restore_card_snapshot(self, card_id: str, snapshot_path: str) -> dict:
        """恢复快照（恢复前自动再快照一次当前状态）。

        卡片文件缺失时**允许恢复**（等于把快照还原成卡片），
        因此这里是「可恢复已删除的卡片」这条能力的落点。
        """
        full_path = self._resolve_card_path(card_id)
        if not full_path:
            return {'success': False, 'msg': '卡片 id 非法或路径越界', 'error': 'card_not_found'}

        candidate = os.path.abspath(str(snapshot_path or ''))
        if not candidate or not os.path.isfile(candidate):
            return {'success': False, 'msg': '快照文件不存在', 'error': 'snapshot_not_found'}

        # 只允许恢复**本卡片**备份目录里的文件，防止借插件读写任意路径
        expected_dir = os.path.realpath(self._snapshot_card_dir(card_id, full_path))
        if not is_under_base(os.path.realpath(candidate), expected_dir, resolve_symlinks=True):
            return {'success': False, 'msg': '快照不属于该卡片', 'error': 'snapshot_out_of_scope'}

        safety = self._snapshot_card(card_id, remark='before-restore') if os.path.isfile(full_path) else None

        with self._card_lock(card_id), self._suppress_fs_events():
            try:
                target_dir = os.path.dirname(full_path)
                if target_dir:
                    os.makedirs(target_dir, exist_ok=True)
                shutil.copy2(candidate, full_path)
                sidecar_src = _sidecar_for_snapshot(candidate)
                if sidecar_src:
                    sidecar_dst = find_sidecar_image(full_path)
                    target_sidecar = sidecar_dst or os.path.splitext(full_path)[0] + os.path.splitext(sidecar_src)[1]
                    shutil.copy2(sidecar_src, target_sidecar)
            except OSError as exc:
                return {
                    'success': False, 'msg': f'恢复失败: {exc}', 'error': 'restore_failed',
                    'safety_snapshot': safety or '',
                }

            info = extract_card_info(full_path)
            if isinstance(info, dict):
                self._sync_card_index(card_id, full_path, info)

        return {
            'success': True,
            'msg': '',
            'error': '',
            'safety_snapshot': safety or '',
        }

    def _snapshot_card_dir(self, card_id: str, full_path: str) -> str:
        name_no_ext = os.path.splitext(os.path.basename(full_path))[0]
        safe_dir_name = re.sub(r'[\\/:*?"<>|]', '_', name_no_ext).strip() or 'unnamed_backup'
        return os.path.join(self._snapshot_root(), safe_dir_name)

    # ---- 索引 ----

    def _index_status(self) -> dict:
        from core.services.index_service import get_index_status

        return get_index_status()

    def _index_search(self, query: str, *, scope: str = 'cards', limit: int = 50,
                      offset: int = 0, category: str = '', tags=(),
                      search_mode: str = 'fast') -> dict:
        scope_name = str(scope or 'cards').strip().lower()
        page_size = max(1, int(limit or 50))
        page = (max(0, int(offset or 0)) // page_size) + 1

        if scope_name == 'worldinfo':
            from core.services.worldinfo_index_query_service import query_worldinfo_index

            result = query_worldinfo_index({
                'search': query,
                'search_mode': 'fulltext' if str(search_mode).lower() == 'fulltext' else 'fast',
                'category': category,
                'page': page,
                'page_size': page_size,
            })
            return {
                'items': result.get('items') or [],
                'total': int(result.get('total') or 0),
                'index_ready': bool(result.get('index_ready')),
            }

        if scope_name != 'cards':
            raise ValueError(f'不支持的索引 scope: {scope}')

        from core.services.card_index_query_service import query_indexed_cards

        result = query_indexed_cards({
            'search': query,
            'search_mode': 'fulltext' if str(search_mode).lower() == 'fulltext' else 'fast',
            'category': category,
            'include_tags': _normalize_tag_list(tags),
            'page': page,
            'page_size': page_size,
        })
        return {
            'items': result.get('cards') or [],
            'total': int(result.get('total_count') or 0),
            'index_ready': bool(result.get('index_ready')),
        }

    def _request_index_rebuild(self, scope: str = 'cards') -> str:
        from core.services.index_service import request_index_rebuild

        return request_index_rebuild(scope)

    # ---- 会话 / 预设 / 扩展资源（P2 读取）----

    def _list_chats(self, *, search: str = '', favorite=None, limit: int = 0) -> list:
        from core.data.chat_store import load_chat_data

        needle = str(search or '').strip().lower()
        items = []
        for chat_id, entry in (load_chat_data() or {}).items():
            payload = dict(entry) if isinstance(entry, dict) else {}
            payload['id'] = str(chat_id)
            if needle and needle not in str(chat_id).lower():
                continue
            if favorite is not None and bool(payload.get('favorite')) is not bool(favorite):
                continue
            items.append(payload)

        items.sort(key=lambda item: str(item.get('id') or ''))
        if limit and int(limit) > 0:
            return items[: int(limit)]
        return items

    def _get_chat(self, chat_id: str):
        key = str(chat_id or '').strip()
        if not key:
            return None

        from core.data.chat_store import load_chat_data

        entry = (load_chat_data() or {}).get(key)
        if not isinstance(entry, dict):
            return None
        payload = dict(entry)
        payload['id'] = key
        return payload

    def _st_client(self):
        from core.services.st_client import get_st_client

        return get_st_client()

    def _list_presets(self, *, search: str = '', limit: int = 0) -> list:
        needle = str(search or '').strip().lower()
        items = []
        for item in self._st_client().list_presets() or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name') or '')
            filename = str(item.get('filename') or '')
            if needle and needle not in name.lower() and needle not in filename.lower():
                continue
            items.append(item)

        if limit and int(limit) > 0:
            return items[: int(limit)]
        return items

    def _read_preset(self, file_path: str):
        raw = str(file_path or '').strip()
        if not raw:
            return None

        target = os.path.abspath(raw)
        allowed_roots = []
        try:
            root = self._st_client().get_presets_dir()
            if root:
                allowed_roots.append(os.path.abspath(root))
        except Exception:  # noqa: BLE001 - ST 未配置时退化到主程序预设目录
            logger.debug('插件 %s 解析 ST 预设目录失败', self.plugin_id, exc_info=True)

        config = load_config()
        raw_presets = config.get('presets_dir', 'data/library/presets')
        allowed_roots.append(os.path.abspath(
            raw_presets if os.path.isabs(raw_presets) else os.path.join(BASE_DIR, raw_presets)
        ))

        if not any(is_under_base(target, root, resolve_symlinks=True) for root in allowed_roots):
            return None

        try:
            with open(target, 'r', encoding='utf-8') as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning('插件 %s 读取预设失败 %s: %s', self.plugin_id, target, exc)
            return None

    def _list_regex_scripts(self) -> list:
        try:
            return self._st_client().list_regex_scripts() or []
        except Exception:  # noqa: BLE001 - ST 未配置时返回空列表
            logger.warning('插件 %s 读取全局正则脚本失败', self.plugin_id, exc_info=True)
            return []

    def _list_scripts(self) -> list:
        try:
            return self._st_client().list_scripts() or []
        except Exception:  # noqa: BLE001
            logger.warning('插件 %s 读取脚本资源失败', self.plugin_id, exc_info=True)
            return []


def _is_valid_tag_name(tag) -> bool:
    """标签名合法性（避免把控制字符或超长串写进分类体系）。"""
    if not isinstance(tag, str):
        return False
    value = tag.strip()
    if not value or len(value) > 128:
        return False
    return not any(char in value for char in '\x00\r\n')


def _detect_rule_cycles(rules: dict) -> list:
    """检测替换规则里的环（`a→b→a`），返回涉及的起始标签列表。"""
    cycles = []
    for start in rules:
        seen = set()
        current = start
        while current in rules:
            if current in seen:
                cycles.append(str(start))
                break
            seen.add(current)
            current = str(rules.get(current) or '').strip()
            if not current:
                break
    return sorted(set(cycles))


def _sidecar_for_snapshot(snapshot_path: str) -> str:
    """快照文件对应的伴生图（快照命名与卡片一致，只换扩展名）。"""
    base = os.path.splitext(snapshot_path)[0]
    for ext in ('.png', '.webp', '.jpg', '.jpeg', '.jfif'):
        candidate = base + ext
        if os.path.isfile(candidate):
            return candidate
    return ''


#: 快照文件名里的创建时间戳（`{name}_{timestamp}__KEY__{remark}{ext}`）
_SNAPSHOT_TIMESTAMP_PATTERN = re.compile(r'_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}-\d{6})(?:__KEY__|$)')


def _snapshot_stamp_key(name: str) -> str:
    """取快照文件名里的时间戳（用于排序）；取不到返回空串。"""
    match = _SNAPSHOT_TIMESTAMP_PATTERN.search(str(name or ''))
    return match.group(1) if match else ''
