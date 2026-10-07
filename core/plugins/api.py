"""PluginAPI 门面（设计文档 10.2）。

插件通过 `register(api)` 拿到这个对象，它是插件与主程序之间的**唯一**契约面。
设计原则（4.6）：
1. 门面方法内部处理全部核心约定（`suppress_fs_events`、卡片锁、`update_ui_data`），
   插件作者不需要知道这些细节。
2. 核心能力一律复用既有服务层，不重复实现。
3. `permissions` 只做声明与审计（D7），不做执行门控。
4. `migrate()` 强制 `plugin_<id>_` 表名前缀，防止插件污染核心 schema。
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
from core.version import APP_VERSION

logger = logging.getLogger(__name__)

PLUGIN_UI_NAMESPACE = '_plugins_v1'
TAG_ORDER_KEY = '_tag_order_v1'
PLUGIN_DATA_QUOTA_BYTES = 256 * 1024
PLUGIN_DATA_QUOTA_WARN_BYTES = int(PLUGIN_DATA_QUOTA_BYTES * 0.8)


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


class PluginAPI:
    """插件能力门面。每个已加载插件持有独立实例。"""

    def __init__(self, manifest, app=None):
        self._manifest = manifest
        self._app = app
        self.plugin_id = manifest.plugin_id
        self.manifest = manifest.to_dict()
        self.app_version = APP_VERSION
        self._default_blueprint = None
        self._default_registered = False
        self._active_run_id = None

    # ---------------------------------------------------------------- 配置

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

    def get_config(self) -> dict:
        """读取插件配置：`config_schema` 默认值打底 + 用户保存值。"""
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

    def set_config(self, patch: dict) -> bool:
        """浅合并写入插件配置（只接受 `config_schema` 声明过的键）。"""
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

    # ---------------------------------------------------------------- 密钥

    def get_secret(self, key: str):
        """读取密钥：环境变量 > `secrets.json` > 非 secret 项的 schema 默认值。"""
        value = secrets_store.get_secret(self.plugin_id, key)
        if value is not None and value != '':
            return value

        spec = ((self._manifest.secret_schema or {}).get('properties') or {}).get(str(key))
        if isinstance(spec, dict) and not spec.get('secret') and 'default' in spec:
            return spec['default']
        return None

    def set_secret(self, key: str, value) -> bool:
        """写入密钥；`None` / 空串表示清除该项。"""
        return secrets_store.set_secret(self.plugin_id, key, value)

    def list_secrets(self) -> dict:
        """返回 `{key: {set, hint, updated_at}}`，secret 项永不返回明文。"""
        return secrets_store.describe_secrets(self.plugin_id, self._manifest.secret_schema)

    # ---------------------------------------------------------------- 事件

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

    # ---------------------------------------------------------------- HTTP

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

    def blueprint(self, bp: Blueprint) -> bool:
        """注册插件蓝图（自动加 `/api/plugins/<id>` 前缀 + 冲突检查）。"""
        return self._register_blueprint(bp)

    def _ensure_default_blueprint(self) -> Blueprint:
        if self._default_blueprint is None:
            name = f'plugin_{self.plugin_id.replace("-", "_")}'
            self._default_blueprint = Blueprint(name, __name__)
        return self._default_blueprint

    def route(self, rule: str, methods=None):
        """装饰器：把视图函数注册到本插件的默认蓝图。

        规则先收集在默认蓝图上，等插件的 `register(api)` 返回后由
        `finalize()` 统一注册（Flask 禁止在蓝图注册后继续添加规则）。
        """
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
        """注册 `route()` 收集到的默认蓝图（由 registry 在 `register()` 之后调用）。"""
        if self._default_blueprint is None or self._default_registered:
            return True
        self._default_registered = self._register_blueprint(self._default_blueprint)
        return self._default_registered

    # ---------------------------------------------------------------- 作业

    def register_job(self, job_type: str, handler) -> None:
        """注册作业处理器。`job_type` 必须已在 manifest 的 `backend.jobs` 声明。"""
        from core.plugins import jobs

        declared = set(self._manifest.backend_jobs or [])
        job_type = str(job_type or '').strip()
        if declared and job_type not in declared:
            raise ValueError(f'job_type {job_type!r} 未在 manifest.backend.jobs 中声明')
        jobs.register_job_handler(self.plugin_id, job_type, handler)

    def submit_job(self, job_type: str, *, items, payload=None) -> str:
        """提交作业，返回 run_id。

        `payload` 会明文落库，**禁止**写入密钥值；需要密钥时只放
        `{"secret_ref": "key_name"}`，由 worker 运行时用 `get_secret()` 解析。
        """
        from core.plugins import jobs

        return jobs.submit_job(self.plugin_id, job_type, items, payload)

    def get_job(self, run_id: str):
        """读取作业详情（含进度、条目与最近事件）；不存在或**非本插件作业**时返回 None。"""
        from core.plugins import jobs

        return jobs.get_job_detail(run_id, plugin_id=self.plugin_id)

    def cancel_job(self, run_id: str) -> bool:
        """请求取消本插件的作业（协作式：处理器下次 `should_cancel()` 时退出）。

        非本插件的 run_id 会抛 `job_not_found`——作业按 `plugin_id` 隔离。
        """
        from core.plugins import jobs

        return jobs.cancel_job(run_id, plugin_id=self.plugin_id)

    def retry_job(self, run_id: str, *, only_failed: bool = True) -> str:
        """重跑本插件的作业；`only_failed=True` 时只重置失败条目，返回 run_id。"""
        from core.plugins import jobs

        return jobs.retry_job(run_id, only_failed=only_failed, plugin_id=self.plugin_id)

    def pause_job(self, run_id: str) -> bool:
        """暂停本插件的作业（D6 审批流：等待人工处理后由 `resume_job` 恢复）。"""
        from core.plugins import jobs

        return jobs.pause_job(run_id, plugin_id=self.plugin_id)

    def resume_job(self, run_id: str) -> bool:
        """恢复本插件被暂停的作业，返回是否成功。"""
        from core.plugins import jobs

        return jobs.resume_job(run_id, plugin_id=self.plugin_id)

    # ---------------------------------------------------------------- CLI

    def register_cli(self, name: str, handler, description: str = '') -> None:
        """注册一个 CLI 子命令（N2）：`python app.py plugin <id> <name> [args…]`。

        `handler(namespace)` 接收 `argparse.Namespace`，字段约定见
        `core/plugins/cli.py` 的模块文档（`args` / `options` 与退出码规则）。
        """
        from core.plugins import cli as cli_module

        cli_module.register_cli(self.plugin_id, name, handler, description)

    # ---------------------------------------------------------------- 数据

    def db(self):
        """主库连接（Provisional，建议只读）。"""
        return job_store.connect(ensure_schema=False)

    def table_prefix(self) -> str:
        """插件私有表的强制前缀：`plugin_<id（连字符转下划线）>_`。"""
        return f"plugin_{self.plugin_id.replace('-', '_')}_"

    def migrate(self, statements) -> None:
        """执行建表语句；表名与索引名强制 `plugin_<id>_` 前缀。"""
        if isinstance(statements, str):
            statements = [statements]
        if not isinstance(statements, (list, tuple)):
            raise ValueError('migrate 需要语句列表')

        prefix = self.table_prefix()
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

    def data_dir(self) -> str:
        """插件私有数据目录 `data/plugins/<id>/data/`（不存在时创建）。"""
        target = os.path.join(self._manifest.plugin_dir, 'data')
        try:
            os.makedirs(target, exist_ok=True)
        except OSError as exc:
            logger.warning('插件 %s 的 data 目录创建失败: %s', self.plugin_id, exc)
        return target

    # ------------------------------------------------------------ 核心能力

    def _resolve_card_path(self, card_id) -> str:
        card_id = str(card_id or '').strip().replace('\\', '/')
        if not card_id or card_id.startswith('/') or '..' in card_id.split('/'):
            return ''
        full_path = os.path.realpath(os.path.join(str(CARDS_FOLDER), card_id.replace('/', os.sep)))
        if not is_under_base(full_path, str(CARDS_FOLDER), resolve_symlinks=True):
            return ''
        return full_path

    def read_card(self, card_id: str):
        """读取角色卡完整数据（含内嵌世界书）。"""
        full_path = self._resolve_card_path(card_id)
        if not full_path or not os.path.isfile(full_path):
            return None
        info = extract_card_info(full_path)
        if not isinstance(info, dict):
            return None
        info.setdefault('id', str(card_id or '').strip().replace('\\', '/'))
        return info

    def read_cards(self, card_ids) -> dict:
        """批量读取角色卡，返回 `{card_id: card|None}`。"""
        result = {}
        for card_id in card_ids or []:
            key = str(card_id or '').strip().replace('\\', '/')
            if not key:
                continue
            result[key] = self.read_card(key)
        return result

    def _card_tags(self, info: dict) -> list:
        data_block = info.get('data') if isinstance(info.get('data'), dict) else info
        tags = data_block.get('tags') or []
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.split(',') if part.strip()]
        return _normalize_tag_list(tags)

    def _sync_card_index(self, card_id: str, full_path: str, card_data: dict) -> None:
        """同步内存缓存、数据库行与索引增量。"""
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

    def write_card_fields(self, card_id: str, patch: dict) -> bool:
        """改写角色卡字段（内部：卡片锁 + `suppress_fs_events` + 缓存/索引同步）。"""
        if not isinstance(patch, dict) or not patch:
            return False

        card_id = str(card_id or '').strip().replace('\\', '/')
        full_path = self._resolve_card_path(card_id)
        if not full_path or not os.path.isfile(full_path):
            return False

        lock = ctx.get_card_lock(card_id) if hasattr(ctx, 'get_card_lock') else None
        if lock is None:
            lock = contextlib.nullcontext()

        with lock:
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

            with self.suppress_fs_events():
                if not write_card_metadata(full_path, info):
                    logger.error('插件 %s 写入卡片 %s 失败', self.plugin_id, card_id)
                    return False

            self._sync_card_index(card_id, full_path, info)
        return True

    def apply_tags(self, card_ids, *, add=(), remove=(), replace: bool = False) -> dict:
        """批量写入标签。

        **D4：默认合并**（`replace=False`），不清空既有标签；`replace=True` 才整组替换。
        """
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

            lock = ctx.get_card_lock(card_id) if hasattr(ctx, 'get_card_lock') else None
            if lock is None:
                lock = contextlib.nullcontext()

            with lock:
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

                with self.suppress_fs_events():
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

    def read_tag_library(self) -> dict:
        """读取标签库：全部标签、排序、分类体系与治理偏好。"""
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

    def read_worldbook(self, source: dict):
        """读取世界书内容（global / resource / embedded 三类来源）。"""
        kind, path, card_id = self._resolve_worldbook_source(source)
        if not kind or not path or not os.path.isfile(path):
            return None

        if kind == 'embedded':
            card = self.read_card(card_id)
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

    def write_worldbook(self, source: dict, data: dict, *, expected_revision: str = '') -> dict:
        """写回世界书（含 `source_revision` 乐观锁与条目历史记账）。"""
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

        lock = ctx.get_card_lock(card_id) if (kind == 'embedded' and card_id) else None
        if lock is None:
            lock = contextlib.nullcontext()

        with lock, self.suppress_fs_events():
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

    def snapshot_card(self, card_id: str, *, remark: str = '') -> str | None:
        """为角色卡创建快照，返回快照文件绝对路径。"""
        full_path = self._resolve_card_path(card_id)
        if not full_path or not os.path.isfile(full_path):
            return None

        backups_root = os.path.join(str(DATA_DIR), 'system', 'backups', 'cards')
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

        with self.suppress_fs_events():
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

    # ---- ui_data ----

    def ui_data_read(self) -> dict:
        """只读快照：仅本插件的 `_plugins_v1.<id>` 命名空间。"""
        entry = self._plugin_entry(load_ui_data_or_empty())
        try:
            return json.loads(json.dumps(entry, ensure_ascii=False))
        except (TypeError, ValueError):
            return dict(entry)

    def ui_data_update(self, mutator) -> bool:
        """在锁内修改本插件的命名空间（禁止直接读写整个 ui_data，避免 lost update）。

        超过 `PLUGIN_DATA_QUOTA_BYTES`（N4）时整次写入被拒绝并返回 False：
        回调抛出的内部信号会中断 `update_ui_data` 的保存流程，磁盘内容保持不变。
        """
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

    # ---- 文件系统 ----

    @contextlib.contextmanager
    def suppress_fs_events(self, seconds: float = 1.5):
        """抑制文件系统事件的上下文管理器。

        写 `data/library/` 或 `data/system/` 下的文件前必须使用，否则会触发扫描器/
        监控重扫；写 `data/plugins/<id>/data/` 无需使用。
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

    # ---- 通知与日志 ----

    def notify(self, level: str, message: str) -> None:
        """写入日志，并在有活跃作业时追加一条 `log` 事件（供前端实时展示）。"""
        self.log(level, message)

    def log(self, level: str, message: str, **extra) -> None:
        """带插件前缀的日志。"""
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
