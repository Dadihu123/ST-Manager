import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import world_info as world_info_api
from core.services import wi_entry_history_service as history_service


CARD_UID = '12345678-1234-4234-8234-123456789abc'
CARD_ID = 'cards/hero.json'


def test_root_move_keeps_history_and_remaps_legacy_before_purge(tmp_path, monkeypatch):
    import hashlib
    import shutil

    old = tmp_path / 'old'
    new = tmp_path / 'new'
    relative = 'data/library/lorebooks/book.json'
    book = old / relative
    book.parent.mkdir(parents=True)
    book.write_text('{}')
    (old / 'resources').mkdir()
    (old / 'cards').mkdir()
    db = old / 'history.db'
    monkeypatch.setattr(history_service, 'BASE_DIR', str(old))
    monkeypatch.setattr(history_service, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(history_service, 'load_config', lambda: {
        'world_info_dir': 'data/library/lorebooks', 'resources_dir': 'resources'})
    stable = history_service.build_scope_key('global', file_path=str(book))
    history_service.append_entry_history_records('global', '', str(book), [
        {'entry_uid': 'one', 'snapshot': {'content': 'saved'}}])
    # 模拟迁移前版本仍遗留的绝对路径 scope（根信息已记入数据库）。
    legacy = hashlib.sha1(('global|' + str(book).replace('\\', '/')).encode()).hexdigest()
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE wi_entry_history SET scope_key = ?', (legacy,))
    shutil.copytree(old, new)
    monkeypatch.setattr(history_service, 'BASE_DIR', str(new))
    monkeypatch.setattr(history_service, 'DEFAULT_DB_PATH', str(new / 'history.db'))
    assert history_service.build_scope_key('global', file_path=str(new / relative)) == stable
    history_service.purge_orphaned_entry_history(cards_root=new / 'cards',
        world_info_root=new / 'data/library/lorebooks', resources_root=new / 'resources')
    records = history_service.list_entry_history_records('global', '', str(new / relative), 'one')
    assert records[0]['snapshot']['content'] == 'saved'
    assert db.is_file(), '迁移不得删除原数据库'


def test_resolve_card_uid_prefers_cache_and_falls_back_to_metadata_db(tmp_path):
    cache = SimpleNamespace(
        id_map={CARD_ID: {'card_uid': CARD_UID.upper()}},
        bundle_map={},
    )
    assert history_service.resolve_card_uid(CARD_ID, cache=cache) == CARD_UID

    db_path = tmp_path / 'cards.db'
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE card_metadata (id TEXT PRIMARY KEY, card_uid TEXT)')
        conn.execute(
            'INSERT INTO card_metadata (id, card_uid) VALUES (?, ?)',
            (CARD_ID, CARD_UID),
        )
        conn.commit()

    empty_cache = SimpleNamespace(id_map={}, bundle_map={})
    assert history_service.resolve_card_uid(
        CARD_ID,
        cache=empty_cache,
        db_path=str(db_path),
    ) == CARD_UID


def test_resolve_card_uid_uses_bundle_logical_card_identity_for_versions():
    cache = SimpleNamespace(
        id_map={
            'cards/hero-main.json': {'card_uid': CARD_UID},
            'cards/hero-version.json': {
                'card_uid': '12345678-1234-4234-8234-abcdefabcdef',
            },
        },
        bundle_map={'cards': 'cards/hero-main.json'},
    )

    assert history_service.resolve_card_uid(
        'cards/hero-version.json',
        cache=cache,
    ) == CARD_UID


def test_embedded_history_list_reads_legacy_path_scope_with_stable_card_uid(monkeypatch, tmp_path):
    db_path = tmp_path / 'history.db'
    monkeypatch.setattr(history_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(world_info_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(
        world_info_api.ctx,
        'cache',
        SimpleNamespace(
            id_map={CARD_ID: {'card_uid': CARD_UID}},
            bundle_map={},
        ),
    )

    snapshot = {
        'st_manager_uid': 'entry-1',
        'comment': 'Legacy version',
        'content': 'before the UUID migration',
    }
    assert history_service.append_entry_history_records(
        source_type='embedded',
        source_id=CARD_ID,
        file_path='',
        records=[{'entry_uid': 'entry-1', 'snapshot': snapshot}],
    ) == 1

    app = Flask(__name__)
    app.register_blueprint(world_info_api.bp)
    response = app.test_client().post(
        '/api/world_info/entry_history/list',
        json={
            'source_type': 'embedded',
            'source_id': CARD_UID,
            'card_id': CARD_ID,
            'legacy_source_id': CARD_ID,
            'entry_uid': 'entry-1',
        },
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert [item['snapshot'] for item in payload['items']] == [snapshot]
