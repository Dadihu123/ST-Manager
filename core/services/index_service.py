import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from copy import deepcopy
from typing import Any

from core.config import CARDS_FOLDER, DEFAULT_DB_PATH, load_config
from core.context import ctx
from core.data.index_runtime_store import ensure_index_runtime_schema
from core.data.ui_store import load_ui_data
from core.services import index_build_service
from core.services.index_job_worker import enqueue_index_job as enqueue_index_job
from core.services.index_job_worker import start_index_job_worker
from core.services.index_upgrade_service import rebuild_scope_generation
from core.utils.image import extract_card_info


logger = logging.getLogger(__name__)


SUPPORTED_REBUILD_SCOPES = {'cards', 'worldinfo'}


def _sync_runtime_rebuild_dependencies():
    """Keep legacy rebuild wrappers aligned with the current v2 rebuild modules."""
    from core.services import index_upgrade_service

    cards_root = _get_cards_root() or CARDS_FOLDER
    return index_upgrade_service, {
        'DEFAULT_DB_PATH': DEFAULT_DB_PATH,
        'CARDS_FOLDER': cards_root,
        'load_config': load_config,
        'extract_card_info': extract_card_info,
    }, {
        'DEFAULT_DB_PATH': DEFAULT_DB_PATH,
        'CARDS_FOLDER': cards_root,
        'load_config': load_config,
        'load_ui_data': load_ui_data,
        'extract_card_info': extract_card_info,
    }


@contextmanager
def _temporary_runtime_rebuild_dependencies():
    index_upgrade_service, upgrade_overrides, build_overrides = _sync_runtime_rebuild_dependencies()
    sentinel = object()
    upgrade_originals = {name: getattr(index_upgrade_service, name, sentinel) for name in upgrade_overrides}
    build_originals = {name: getattr(index_build_service, name, sentinel) for name in build_overrides}

    try:
        for name, value in upgrade_overrides.items():
            setattr(index_upgrade_service, name, value)
        for name, value in build_overrides.items():
            setattr(index_build_service, name, value)
        yield
    finally:
        for name, value in upgrade_originals.items():
            if value is sentinel:
                delattr(index_upgrade_service, name)
            else:
                setattr(index_upgrade_service, name, value)
        for name, value in build_originals.items():
            if value is sentinel:
                delattr(index_build_service, name)
            else:
                setattr(index_build_service, name, value)


def _ensure_runtime_schema_ready():
    with sqlite3.connect(DEFAULT_DB_PATH, timeout=60) as conn:
        ensure_index_runtime_schema(conn)


def get_index_status() -> dict[str, Any]:
    with ctx.index_lock:
        snapshot = deepcopy(dict(ctx.index_state))

    try:
        with sqlite3.connect(DEFAULT_DB_PATH, timeout=60) as conn:
            conn.row_factory = sqlite3.Row

            schema_rows = conn.execute(
                'SELECT component, applied_version, state, last_error FROM index_schema_state'
            ).fetchall()
            schema_map = {str(row['component']): row for row in schema_rows}

            db_row = schema_map.get('db')
            runtime_row = schema_map.get('index_runtime')
            schema_state = 'ready'
            for row in (db_row, runtime_row):
                if not row:
                    schema_state = 'empty'
                    continue
                if str(row['state'] or '') not in ('ready', ''):
                    schema_state = str(row['state'] or 'empty')
                    break

            snapshot['schema'] = {
                'db_version': int((db_row['applied_version'] if db_row else 0) or 0),
                'index_runtime_version': int((runtime_row['applied_version'] if runtime_row else 0) or 0),
                'state': schema_state,
                'message': str(snapshot.get('schema', {}).get('message') or ''),
            }

            build_rows = conn.execute(
                'SELECT scope, active_generation, building_generation, state, phase, items_written, last_error FROM index_build_state'
            ).fetchall()
    except sqlite3.OperationalError:
        return snapshot

    persisted_scopes: dict[str, dict[str, Any]] = {}
    for row in build_rows:
        scope = str(row['scope'] or '')
        if scope not in ('cards', 'worldinfo'):
            continue
        persisted_scopes[scope] = {
            'state': str(row['state'] or 'empty'),
            'phase': str(row['phase'] or ''),
            'active_generation': int(row['active_generation'] or 0),
            'building_generation': int(row['building_generation'] or 0),
            'items_written': int(row['items_written'] or 0),
            'last_error': str(row['last_error'] or ''),
        }

    for scope in ('cards', 'worldinfo'):
        if scope in persisted_scopes:
            snapshot[scope] = persisted_scopes[scope]

    pending_jobs = int(snapshot.get('jobs', {}).get('pending_jobs') or snapshot.get('pending_jobs') or 0)
    worker_state = str(snapshot.get('jobs', {}).get('worker_state') or 'idle')
    active_scope = str(snapshot.get('scope') or 'cards')
    if active_scope not in ('cards', 'worldinfo'):
        active_scope = 'cards'

    if pending_jobs > 0 or worker_state in ('waiting', 'processing'):
        snapshot['state'] = 'building' if pending_jobs > 0 or worker_state == 'processing' else 'idle'
        snapshot['scope'] = active_scope
    else:
        ready_scope = next(
            (
                scope
                for scope in ('cards', 'worldinfo')
                if str(snapshot.get(scope, {}).get('state') or '') == 'ready'
            ),
            active_scope,
        )
        snapshot['scope'] = ready_scope
        snapshot['state'] = str(snapshot.get(ready_scope, {}).get('state') or snapshot['schema']['state'] or 'empty')

    snapshot['pending_jobs'] = pending_jobs
    snapshot['jobs'] = {
        'pending_jobs': pending_jobs,
        'worker_state': worker_state,
    }
    snapshot['progress'] = int(snapshot.get('progress') or 0)
    snapshot['message'] = str(snapshot.get('message') or '')

    # 全量扫描（磁盘校验）与索引构建共用同一展示通道：
    # 扫描进行时优先呈现扫描状态，避免用户看到「无任何活动」却持续占用资源。
    if bool(snapshot.get('scan_active')):
        snapshot['state'] = 'building'
        snapshot['scope'] = 'scan'
        snapshot['message'] = str(snapshot.get('scan_message') or 'scanning')
    snapshot['scan_active'] = bool(snapshot.get('scan_active'))
    snapshot['scan_message'] = str(snapshot.get('scan_message') or '')
    return snapshot


def _set_index_state(**updates):
    with ctx.index_lock:
        ctx.index_state.update(updates)


def request_index_rebuild(scope: str = 'cards') -> str:
    if scope not in SUPPORTED_REBUILD_SCOPES:
        raise ValueError(f'unsupported rebuild scope: {scope}')
    enqueue_index_job('rebuild_scope', payload={'scope': scope})
    _set_index_state(state='building', scope=scope, message='queued rebuild')
    return scope


def _get_cards_root() -> str:
    cfg = load_config()
    cards_dir = cfg.get('cards_dir', '')
    if cards_dir and os.path.isabs(cards_dir):
        return cards_dir
    base_dir = os.path.dirname(DEFAULT_DB_PATH)
    if cards_dir:
        return os.path.abspath(os.path.join(base_dir, '..', '..', '..', cards_dir))
    return ''


def rebuild_card_index():
    _ensure_runtime_schema_ready()
    with _temporary_runtime_rebuild_dependencies():
        rebuild_scope_generation('cards', reason='legacy_rebuild_compat')


def rebuild_worldinfo_index():
    _ensure_runtime_schema_ready()
    with _temporary_runtime_rebuild_dependencies():
        rebuild_scope_generation('worldinfo', reason='legacy_rebuild_compat')


def _bootstrap_index():
    cfg = load_config()
    if cfg.get('index_auto_bootstrap', True):
        request_index_rebuild('cards')


def start_index_service():
    threading.Thread(target=_bootstrap_index, daemon=True).start()
    start_index_job_worker()
