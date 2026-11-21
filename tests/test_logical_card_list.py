import json
import sqlite3
from contextlib import closing

import pytest
from flask import Flask

from core.api.v1 import cards
from core.data import card_list_projection, db_session, local_state_repository as state, ui_store
from core.data.cache import GlobalMetadataCache
from core.services import card_index_query_service, index_build_service, index_upgrade_service


@pytest.fixture
def library(monkeypatch, tmp_path):
    root = tmp_path / 'cards'
    root.mkdir()
    db = str(tmp_path / 'cards.db')
    for module in (cards, db_session, state, index_build_service, index_upgrade_service):
        monkeypatch.setattr(module, 'DEFAULT_DB_PATH', db)
        if hasattr(module, 'CARDS_FOLDER'):
            monkeypatch.setattr(module, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(tmp_path / 'ui.json'))
    from core.data import cache, chat_store
    monkeypatch.setattr(chat_store, 'CHAT_DATA_FILE', str(tmp_path / 'chat.json'))
    monkeypatch.setattr(cache, 'DEFAULT_DB_PATH', db)
    monkeypatch.setattr(cache, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(cards.ctx, 'cache', GlobalMetadataCache())
    monkeypatch.setattr(cards, 'load_config', lambda: {})
    state.initialize()
    records = [
        ('a.json', 'Alpha', '', 'A', 10, ['red'], 2, 1),
        ('foo%_/b.json', '北方 🐉', 'foo%_', '作者', 20, ['red', 'blue'], 10, 0),
        ('foo%_/child/c.json', '北方 🐉', 'foo%_/child', '作者', 20, ['blue'], 12, 0),
        ('fooXY/d.json', 'Delta', 'fooXY', 'B', 30, ['green'], 7, 0),
        ('secret/e.json', 'Secret', 'secret', 'A', 40, ['hidden'], 9, 0),
        ('foo%_/bundle/v1.json', 'Bundle', 'foo%_/bundle', 'A', 45, ['old'], 5, 0),
        ('foo%_/bundle/v2.json', 'Bundle', 'foo%_/bundle', 'A', 50, ['blue'], 7, 0),
    ]
    for card_id, name, *_ in records:
        path = root / card_id
        path.parent.mkdir(exist_ok=True, parents=True)
        path.write_text(json.dumps({'data': {'name': name}}), encoding='utf-8')
    (root / 'foo%_/bundle/.bundle').touch()
    (root / 'empty').mkdir()
    with closing(state.connect()) as conn, conn:
        db_session._initialize_database(conn, is_existing_db=True, schema_only=True)
        conn.executemany('INSERT INTO card_metadata '
                         '(id,char_name,category,creator,last_modified,tags,token_count,is_favorite) '
                         'VALUES (?,?,?,?,?,?,?,?)',
                         ((cid, n, cat, by, mt, json.dumps(tags), tokens, fav)
                          for cid, n, cat, by, mt, tags, tokens, fav in records))
        ui = state.Repository('ui')
        ui._put(conn, ui_store.ISOLATED_CATEGORIES_KEY, {'paths': ['secret']})
        ui._put(conn, 'foo%_/bundle', {ui_store.VERSION_REMARKS_KEY: {
            'foo%_/bundle/v1.json': {'summary': 'v1 only'}, 'foo%_/bundle/v2.json': {'summary': 'v2 only'}}})
    cards.ctx.cache.reload_from_db(strict=True)
    app = Flask(__name__)
    app.register_blueprint(cards.bp)
    app.teardown_appcontext(db_session.close_connection)
    return app.test_client(), db, root


def test_sql_list_matches_legacy_scope_filters_and_statistics(library, monkeypatch):
    client, _, _ = library
    cases = [{}, {'category': 'foo%_'}, {'category': 'foo%_', 'recursive': 'false'},
             {'category': '根目录', 'recursive': 'false'}, {'category': 'secret'},
             {'category': 'secret', 'search_scope': 'all_dirs'}, {'category': 'foo%_', 'search_scope': 'full',
              'tags': 'red', 'fav_filter': 'included', 'token_min': 8},
             {'category': 'foo%_', 'search_scope': 'all_dirs', 'all_dirs_only_with_filters': 'true'},
             {'search': '🐉'}, {'search_type': 'creator', 'search': '作者'},
             {'search_type': 'filename', 'search': 'v2'}, {'search_type': 'tags', 'search': 'lu'},
             {'search': 'v2 only'}, {'search': 'v1 only'},
             {'tags': 'blue|||red', 'excluded_tags': 'green'},
             {'favorites_first': 'true', 'fav_filter': 'included'},
             {'modified_date_to': '1970-01-01', 'import_date_from': '1970-01-01', 'token_max': 10}]
    # All sorts use rows with distinct values for the old/new ordering comparison.
    cases.extend({'sort': sort, 'excluded_tags': 'blue'} for sort in (
        'date_asc', 'date_desc', 'name_asc', 'name_desc', 'import_asc', 'import_desc', 'token_asc', 'token_desc'))
    legacy = [client.get('/api/list_cards', query_string=case).get_json() for case in cases]
    index_upgrade_service.rebuild_scope_generation('cards')

    class NoScan:
        def __iter__(self):
            pytest.fail('hot route scanned the card cache')

    monkeypatch.setattr(cards.ctx.cache, 'cards', NoScan())
    for case, before in zip(cases, legacy):
        after = client.get('/api/list_cards', query_string=case).get_json()
        assert after is not None
        for key in ('total_count', 'library_total', 'global_tags', 'sidebar_tags', 'category_counts', 'all_folders'):
            assert after[key] == before[key], (case, key)
        after_ids = [card['id'] for card in after['cards']]
        before_ids = [card['id'] for card in before['cards']]
        if 'sort' not in case:
            after_ids, before_ids = sorted(after_ids), sorted(before_ids)
        assert after_ids == before_ids, case
    page_ids = []
    for page in range(1, 7):
        result = client.get('/api/list_cards?sort=date_desc&page_size=1&page=' + str(page)).get_json()
        page_ids.extend(card['id'] for card in result['cards'])
    assert len(page_ids) == len(set(page_ids)) == 5
    position = client.post('/api/find_card_page', json=dict(card_id='foo%_/bundle/v1.json',
                           category='', sort='date_desc', page_size=1)).get_json()
    assert position['found_id'] == page_ids[position['page'] - 1] == 'foo%_/bundle/v2.json'
    assert client.get('/api/list_cards?search=北方&search_mode=fulltext').get_json()['total_count'] == 2
    monkeypatch.setattr(card_index_query_service, 'supports_fts5', lambda: False)
    assert client.get('/api/list_cards?search=🐉&search_mode=fulltext').get_json()['total_count'] == 2


def test_hot_card_page_work_does_not_grow_with_library(library, monkeypatch):
    client, _, _ = library
    with state.Repository('ui').transaction() as conn:
        state.Repository('ui').delete(ui_store.ISOLATED_CATEGORIES_KEY, conn=conn)
    index_upgrade_service.rebuild_scope_generation('cards')
    ticks = []
    connect = card_index_query_service._connect

    def monitored(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_progress_handler(lambda: ticks.append(1) or 0, 50)
        return conn

    monkeypatch.setattr(card_index_query_service, '_connect', monitored)
    url = '/api/list_cards?sort=date_desc&page=1&page_size=2'
    client.get(url)  # Populate the statistics cache before measuring.
    ticks.clear()
    small = client.get(url).get_json()
    small_work = len(ticks)
    with closing(state.connect()) as conn, conn:
        conn.executemany('INSERT INTO card_metadata(id,char_name,category,last_modified,tags,token_count) '
                         "VALUES (?,'Synthetic','',1,'[]',10)",
                         ((f'synthetic-{i}.json',) for i in range(2000)))
    index_upgrade_service.rebuild_scope_generation('cards')
    client.get(url)
    ticks.clear()
    large = client.get(url).get_json()
    assert large['cards'] == small['cards']
    assert large['total_count'] == small['total_count'] + 2000
    assert len(ticks) <= small_work + 2


def test_failed_activation_and_save_during_build(library, monkeypatch):
    client, db, root = library
    index_upgrade_service.rebuild_scope_generation('cards')
    original = index_upgrade_service.activate_generation
    with monkeypatch.context() as patch:
        patch.setattr(index_upgrade_service, 'activate_generation', lambda *args, **kwargs: False)
        with pytest.raises(RuntimeError, match='未激活'):
            index_upgrade_service.rebuild_scope_generation('cards')
        assert client.get('/api/list_cards').get_json()['total_count'] == 5
        with closing(sqlite3.connect(db)) as conn:
            assert conn.execute("SELECT state,active_generation,building_generation FROM index_build_state "
                                "WHERE scope='cards'").fetchone() == ('failed', 1, 0)

    old_build = card_list_projection.build

    def build_then_save(conn, generation, directory):
        old_build(conn, generation, directory)
        saved = client.post('/api/update_card', json=dict(id='a.json', ui_only=True,
                            ui_only_fields=['ui_summary'], ui_summary='新备注 🐉')).get_json()
        assert saved['success'], saved
        assert client.get('/api/list_cards?search=新备注').get_json()['total_count'] == 1
        assert client.get('/api/list_cards?search_mode=fulltext&search=新备注').get_json()['total_count'] == 1

    monkeypatch.setattr(card_list_projection, 'build', build_then_save)
    monkeypatch.setattr(index_upgrade_service, 'activate_generation', original)
    index_upgrade_service.rebuild_scope_generation('cards')
    assert client.get('/api/list_cards?search=新备注').get_json()['total_count'] == 1
    (root / 'foo%_/bundle/.bundle').unlink()
    card_list_projection.refresh_active_folders(db, root)
    assert client.get('/api/list_cards').get_json()['total_count'] == 6


def test_wrong_root_cannot_activate_before_successful_scan(library, monkeypatch, tmp_path):
    from core.data.index_runtime_store import SCAN_STATE_CARD_ROOT, set_scan_state

    client, db, root = library
    index_upgrade_service.rebuild_scope_generation('cards')
    new_root = tmp_path / 'new-cards'
    new_root.mkdir()
    monkeypatch.setattr(cards, 'CARDS_FOLDER', str(new_root))
    monkeypatch.setattr(index_upgrade_service, 'CARDS_FOLDER', str(new_root))
    unavailable = client.get('/api/list_cards').get_json()
    assert unavailable['index_ready'] is False and unavailable['cards'] == []
    with pytest.raises(OSError, match='新卡片目录'):
        index_upgrade_service.rebuild_scope_generation('cards')
    with closing(sqlite3.connect(db)) as conn, conn:
        assert conn.execute("SELECT active_generation FROM index_build_state WHERE scope='cards'").fetchone()[0] == 1
        conn.execute('DELETE FROM card_metadata')
        set_scan_state(conn, SCAN_STATE_CARD_ROOT, card_list_projection.root_key(new_root), commit=False)
    index_upgrade_service.rebuild_scope_generation('cards')
    assert client.get('/api/list_cards').get_json()['library_total'] == 0


def test_build_and_query_on_sqlite_without_fts(request, monkeypatch):
    from core.data import sqlite_capabilities

    monkeypatch.setattr(sqlite_capabilities, '_fts5_available', False)
    client, db, _ = request.getfixturevalue('library')
    index_upgrade_service.rebuild_scope_generation('cards')
    with closing(sqlite3.connect(db)) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='card_list_fts'").fetchone()
    assert client.get('/api/list_cards?search=北方&search_mode=fulltext').get_json()['total_count'] == 2


def test_created_empty_folder_is_visible_in_the_next_page(library, monkeypatch):
    client, _, _ = library
    monkeypatch.setattr(cards, 'schedule_reload', lambda **_: None)
    index_upgrade_service.rebuild_scope_generation('cards')
    assert client.post('/api/create_folder', json={'name': 'empty%_2', 'parent': 'empty'}).get_json()['success']
    result = client.get('/api/list_cards?category=empty').get_json()
    assert 'empty/empty%_2' in result['all_folders']
    assert result['category_counts']['empty/empty%_2'] == result['total_count'] == 0


def test_get_serves_snapshot_under_writer_and_marker_failure(library, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    client, db, root = library
    index_upgrade_service.rebuild_scope_generation('cards')
    with closing(state.connect(db)) as conn, conn:
        conn.executemany('INSERT INTO card_metadata(id,char_name,category,tags) VALUES (?,?,?,?)',
                         ((f'foo%_/bulk-{i}.json', 'New', 'foo%_', '[]') for i in range(2000)))
    before = client.get('/api/list_cards?page_size=1').get_json()
    assert before['index_stale'] and before['total_count'] == 5

    def fail_probe(*args):
        raise PermissionError('marker unavailable')

    with monkeypatch.context() as patch, closing(state.connect(db)) as writer:
        patch.setattr(card_list_projection, '_is_bundle', fail_probe)
        original = card_index_query_service._connect

        def short_timeout(*args):
            conn = original(*args)
            conn.execute('PRAGMA busy_timeout=100')
            return conn

        patch.setattr(card_index_query_service, '_connect', short_timeout)
        writer.execute('BEGIN IMMEDIATE')

        def fetch(_):
            response = client.application.test_client().get('/api/list_cards?page_size=1')
            return response.status_code, response.get_json()

        with ThreadPoolExecutor(max_workers=2) as workers:
            assert list(workers.map(fetch, range(2))) == [(200, before)] * 2
        writer.rollback()
        with pytest.raises(PermissionError):
            card_list_projection.drain_active_batch(db, root, limit=100)
    assert card_list_projection.drain_active_batch(db, root, limit=100)
    with closing(state.connect(db)) as conn:
        assert conn.execute('SELECT count(*) FROM card_list_dirty').fetchone()[0] == 1900


def test_scan_b_then_switch_back_to_a_does_not_publish_b(library, monkeypatch, tmp_path):
    from core.data import cache
    from core.services import card_service, index_job_worker, scan_service

    client, db, root_a = library
    root_b = tmp_path / 'root-b'
    root_b.mkdir()
    (root_b / 'only-b.json').write_text(json.dumps({
        'spec': 'chara_card_v2', 'spec_version': '2.0',
        'data': {'name': 'B only', 'description': 'test', 'first_mes': 'hello'},
    }), encoding='utf-8')
    for module in (index_job_worker, card_service, scan_service):
        monkeypatch.setattr(module, 'DEFAULT_DB_PATH', db)
    monkeypatch.setattr(scan_service, 'schedule_reload', lambda **_: None)

    def select(root):
        for module in (cards, index_upgrade_service, scan_service, cache, card_service):
            monkeypatch.setattr(module, 'CARDS_FOLDER', str(root))

    select(root_a)
    index_upgrade_service.rebuild_scope_generation('cards')
    select(root_b)
    scan_service._perform_scan_logic_inner(db, str(root_b))
    with closing(state.connect(db)) as conn:
        assert [row[0] for row in conn.execute('SELECT id FROM card_metadata')] == ['only-b.json']
    select(root_a)
    for query in ('', '?search=B+only&search_mode=fulltext'):
        page = client.get(f'/api/list_cards{query}').get_json()
        assert page['index_ready'] is False and page['cards'] == []
    assert not client.post('/api/find_card_page', json={'card_id': 'only-b.json'}).get_json()['success']
    assert not card_list_projection.drain_active_batch(db, root_a)
    with closing(state.connect(db)) as conn:
        assert not conn.execute("SELECT 1 FROM card_list_items WHERE card_id='only-b.json'").fetchone()


def test_token_null_survives_display_and_still_filters_as_zero(library):
    client, db, _ = library
    with closing(state.connect(db)) as conn, conn:
        conn.execute("UPDATE card_metadata SET token_count=NULL WHERE id='a.json'")
        conn.execute("UPDATE card_metadata SET token_count=0 WHERE id='fooXY/d.json'")
    index_upgrade_service.rebuild_scope_generation('cards')
    result = client.get('/api/list_cards?token_max=0&sort=token_asc').get_json()
    assert [(item['id'], item['token_count']) for item in result['cards']] == [('a.json', None), ('fooXY/d.json', 0)]
