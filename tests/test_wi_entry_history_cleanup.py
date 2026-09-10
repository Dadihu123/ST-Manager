import json
import sqlite3
import sys
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.api.v1 import world_info as world_info_api
from core.services import wi_entry_history_service as history_service
from core.services import scan_service


def _history_item(uid, content):
    return {
        'entry_uid': uid,
        'snapshot': {
            'st_manager_uid': uid,
            'content': content,
        },
    }


def _list_history(db_path, source_type, source_id, file_path, entry_uid):
    return history_service.list_entry_history_records(
        source_type=source_type,
        source_id=source_id,
        file_path=file_path,
        entry_uid=entry_uid,
    )


def test_reconcile_entry_history_removes_deleted_entry_uids(monkeypatch, tmp_path):
    db_path = tmp_path / 'history.db'
    book_path = tmp_path / 'world.json'
    monkeypatch.setattr(history_service, 'DEFAULT_DB_PATH', str(db_path))

    assert history_service.append_entry_history_records(
        source_type='global',
        source_id='',
        file_path=str(book_path),
        records=[
            _history_item('keep', 'keep-old'),
            _history_item('deleted', 'deleted-old'),
        ],
    ) == 2

    removed = history_service.reconcile_entry_history_scope(
        source_type='global',
        source_id='',
        file_path=str(book_path),
        active_entry_uids=['keep'],
    )

    assert removed == 1
    assert _list_history(db_path, 'global', '', str(book_path), 'keep')
    assert _list_history(db_path, 'global', '', str(book_path), 'deleted') == []


def test_move_and_purge_entry_history_handles_legacy_lorebook_scope(monkeypatch, tmp_path):
    db_path = tmp_path / 'history.db'
    old_path = tmp_path / 'old.json'
    new_path = tmp_path / 'new.json'
    monkeypatch.setattr(history_service, 'DEFAULT_DB_PATH', str(db_path))

    assert history_service.append_entry_history_records(
        source_type='lorebook',
        source_id='',
        file_path=str(old_path),
        records=[_history_item('entry-1', 'before-move')],
    ) == 1

    assert history_service.move_entry_history_scope(
        source_type='global',
        file_path=str(old_path),
        target_source_type='global',
        target_file_path=str(new_path),
        fallback_contexts=[
            {
                'source_type': 'lorebook',
                'file_path': str(old_path),
            },
        ],
    ) == 1

    assert _list_history(db_path, 'global', '', str(new_path), 'entry-1')
    assert history_service.purge_entry_history_scope(
        source_type='global',
        file_path=str(new_path),
        fallback_contexts=[
            {
                'source_type': 'lorebook',
                'file_path': str(new_path),
            },
        ],
    ) == 1
    assert _list_history(db_path, 'global', '', str(new_path), 'entry-1') == []


def test_purge_orphaned_entry_history_keeps_only_existing_sources(monkeypatch, tmp_path):
    db_path = tmp_path / 'history.db'
    cards_root = tmp_path / 'cards'
    global_root = tmp_path / 'lorebooks'
    resources_root = tmp_path / 'resources'
    existing_card = cards_root / 'hero.json'
    existing_global = global_root / 'shared.json'
    existing_resource = resources_root / 'pack' / 'lorebooks' / 'resource.json'
    for path in (existing_card, existing_global, existing_resource):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}', encoding='utf-8')

    card_uid = '12345678-1234-4234-8234-123456789abc'
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE card_metadata (id TEXT PRIMARY KEY, card_uid TEXT)')
        conn.execute(
            'INSERT INTO card_metadata (id, card_uid) VALUES (?, ?)',
            ('hero.json', card_uid),
        )

    monkeypatch.setattr(history_service, 'DEFAULT_DB_PATH', str(db_path))
    for source_type, source_id, file_path, uid in (
        ('embedded', card_uid, '', 'card-entry'),
        ('global', '', str(existing_global), 'global-entry'),
        ('resource', '', str(existing_resource), 'resource-entry'),
        ('global', '', str(tmp_path / 'missing.json'), 'missing-entry'),
    ):
        history_service.append_entry_history_records(
            source_type=source_type,
            source_id=source_id,
            file_path=file_path,
            records=[_history_item(uid, uid)],
        )

    removed = history_service.purge_orphaned_entry_history(
        cards_root=str(cards_root),
        world_info_root=str(global_root),
        resources_root=str(resources_root),
    )

    assert removed == 1
    assert _list_history(db_path, 'embedded', card_uid, '', 'card-entry')
    assert _list_history(db_path, 'global', '', str(existing_global), 'global-entry')
    assert _list_history(db_path, 'resource', '', str(existing_resource), 'resource-entry')
    assert _list_history(db_path, 'global', '', str(tmp_path / 'missing.json'), 'missing-entry') == []


def test_external_worldinfo_update_reconciles_removed_entry(monkeypatch, tmp_path):
    db_path = tmp_path / 'history.db'
    book_path = tmp_path / 'world.json'
    book_path.write_text(
        json.dumps({
            'entries': [
                {'st_manager_uid': 'keep', 'content': 'current'},
            ],
        }),
        encoding='utf-8',
    )
    monkeypatch.setattr(history_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db_path))

    history_service.append_entry_history_records(
        source_type='lorebook',
        source_id='',
        file_path=str(book_path),
        records=[
            _history_item('keep', 'old'),
            _history_item('deleted', 'old'),
        ],
    )

    scan_service._reconcile_worldinfo_history_file(str(book_path), 'global')

    assert _list_history(db_path, 'global', '', str(book_path), 'keep')
    assert _list_history(db_path, 'global', '', str(book_path), 'deleted') == []


def test_worldinfo_save_cleans_history_for_removed_entry(monkeypatch, tmp_path):
    lorebooks_root = tmp_path / 'lorebooks'
    lorebooks_root.mkdir()
    book_path = lorebooks_root / 'shared.json'
    old_content = {
        'name': 'Shared',
        'entries': [
            {
                'st_manager_uid': 'keep',
                'content': 'keep',
            },
            {
                'st_manager_uid': 'deleted',
                'content': 'deleted',
            },
        ],
    }
    book_path.write_text(json.dumps(old_content), encoding='utf-8')
    db_path = tmp_path / 'history.db'

    monkeypatch.setattr(world_info_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(history_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(
        world_info_api,
        'load_config',
        lambda: {
            'world_info_dir': str(lorebooks_root),
            'resources_dir': str(tmp_path / 'resources'),
        },
    )
    monkeypatch.setattr(world_info_api, '_enqueue_worldinfo_file_refresh', lambda *_args, **_kwargs: None)

    history_service.append_entry_history_records(
        source_type='lorebook',
        source_id='',
        file_path=str(book_path),
        records=[
            _history_item('keep', 'keep-old'),
            _history_item('deleted', 'deleted-old'),
        ],
    )

    app = Flask(__name__)
    app.register_blueprint(world_info_api.bp)
    client = app.test_client()
    detail = client.post(
        '/api/world_info/detail',
        json={'source_type': 'global', 'file_path': str(book_path)},
    ).get_json()
    response = client.post(
        '/api/world_info/save',
        json={
            'save_mode': 'overwrite',
            'file_path': str(book_path),
            'content': {
                'name': 'Shared',
                'entries': [old_content['entries'][0]],
            },
            'source_revision': detail['source_revision'],
        },
    )

    assert response.get_json()['success'] is True
    assert _list_history(db_path, 'global', '', str(book_path), 'keep')
    assert _list_history(db_path, 'global', '', str(book_path), 'deleted') == []


def test_card_update_removing_embedded_worldbook_clears_history(monkeypatch, tmp_path):
    from core.api.v1 import cards as cards_api
    from core.utils.card_identity import normalize_card_uid
    from threading import RLock

    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    card_path = cards_dir / 'hero.json'
    card_path.write_text(json.dumps({'data': {'name': 'Hero'}}), encoding='utf-8')
    db_path = tmp_path / 'history.db'
    card_uid = '12345678-1234-4234-8234-123456789abc'

    old_info = {
        'data': {
            'name': 'Hero',
            'tags': [],
            'character_book': {
                'name': 'Hero WI',
                'entries': [
                    {
                        'st_manager_uid': 'entry-1',
                        'content': 'before',
                    },
                ],
            },
        },
    }

    class _FakeCache:
        bundle_map = {}
        cards = []
        lock = RLock()

        def __init__(self):
            self.id_map = {'hero.json': {'card_uid': card_uid}}

        def update_card_data(self, card_id, payload):
            return {
                'id': card_id,
                'image_url': '/cards_file/hero.json',
                **payload,
            }

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(history_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: json.loads(json.dumps(old_info)))
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'hero.json': {}})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 0))
    monkeypatch.setattr(cards_api, 'get_import_time', lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)
    monkeypatch.setattr(
        cards_api,
        'update_card_cache',
        lambda *_args, **_kwargs: {
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': True,
        },
    )
    monkeypatch.setattr(cards_api, 'sync_card_index_jobs', lambda **_kwargs: {})
    monkeypatch.setattr(cards_api, '_apply_card_index_increment_now', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_refresh_source_after_update', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'auto_run_forum_tags_on_link_update', lambda _card_id: None)
    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    history_service.append_entry_history_records(
        source_type='embedded',
        source_id=normalize_card_uid(card_uid),
        file_path='',
        records=[_history_item('entry-1', 'previous')],
    )

    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)
    response = app.test_client().post(
        '/api/update_card',
        json={
            'id': 'hero.json',
            'char_name': 'Hero',
            'tags': [],
            'character_book': None,
            'card_uid': card_uid,
        },
    )

    assert response.get_json()['success'] is True
    assert _list_history(db_path, 'embedded', card_uid, '', 'entry-1') == []
