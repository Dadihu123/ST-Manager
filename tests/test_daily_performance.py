"""Behavior and operation-count checks, using only synthetic isolated resources."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sqlite3
from unittest.mock import Mock

from flask import Flask
import pytest

from core.api.v1 import cards, chats
from core.data import ui_store
from core.data.cache import GlobalMetadataCache
from core.services import card_service, card_index_sync_service
from core.services import index_build_service
from test_card_index_jobs import _init_index_db, _create_card_metadata_table, _seed_card_index_projection


@pytest.fixture(autouse=True)
def reset_degraded_state():
    ui_store._clear_ui_data_degraded()
    yield
    ui_store._clear_ui_data_degraded()


@pytest.fixture
def library(monkeypatch, tmp_path):
    root = tmp_path / 'cards'
    root.mkdir()
    db = tmp_path / 'metadata.db'
    _init_index_db(db)
    with sqlite3.connect(db) as conn:
        _create_card_metadata_table(conn)
        for card_id in ('hero.png', 'bundle/main.png', 'bundle/old.png'):
            path = root / card_id
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'card body must never be parsed by a UI patch')
            _seed_card_index_projection(conn, card_id=card_id, source_path=path, tags=['sample'])
    cache = GlobalMetadataCache()
    for card_id in ('hero.png', 'bundle/main.png'):
        cache.id_map[card_id] = {'id': card_id, 'filename': card_id.split('/')[-1], 'tags': ['sample'],
                                 'ui_summary': 'original', 'category': '',
                                 'source_update': {'last_status': 'unchecked'}}
    cache.id_map['bundle/main.png'].update(is_bundle=True, bundle_dir='bundle',
        versions=[{'id': 'bundle/main.png'}, {'id': 'bundle/old.png'}])
    cache.bundle_map = {'bundle': 'bundle/main.png'}
    cache.initialized = True
    monkeypatch.setattr(cards.ctx, 'cache', cache)
    monkeypatch.setattr(cards, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(cards, 'DEFAULT_DB_PATH', str(db))
    from core.data import local_state_repository
    monkeypatch.setattr(local_state_repository, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(index_build_service, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(tmp_path / 'ui.json'))
    ui_store._clear_ui_data_degraded()
    ui_store.save_ui_data({
        'hero.png': {'summary': 'original', 'link': 'keep', 'resource_folder': 'assets', 'unknown': [1]},
        'bundle': {'summary': 'original', 'link': 'keep', 'resource_folder': 'shared',
                   '_version_remarks': {'bundle/old.png': {'summary': 'old', 'extension': True}}},
    })
    jobs = Mock()
    monkeypatch.setattr(card_index_sync_service, 'enqueue_index_job', jobs)
    app = Flask(__name__)
    app.register_blueprint(cards.bp)
    return app.test_client(), root, db, cache, jobs


@pytest.mark.parametrize('card_id', ['hero.png', 'bundle/main.png', 'bundle/old.png'])
@pytest.mark.parametrize('cold', [False, True])
def test_note_patch_never_reads_body_and_is_searchable(library, monkeypatch, card_id, cold):
    client, root, db, cache, jobs = library
    before = (root / card_id).read_bytes(), (root / card_id).stat().st_mtime_ns
    if cold:
        cache.id_map.clear()
    forbidden = Mock(side_effect=AssertionError('unrelated expensive operation'))
    for module in (cards, card_service):
        for name in ('extract_card_info', 'write_card_metadata', 'calculate_token_count',
                     'get_file_hash_and_size', 'update_card_cache', 'reconcile_card_ui_fields'):
            if hasattr(module, name):
                monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(cache, '_rebuild_global_tags_locked', forbidden)
    monkeypatch.setattr(cards, 'auto_run_forum_tags_on_link_update', forbidden)
    result = client.post('/api/update_card', json={
        'id': card_id, 'ui_only': True, 'ui_only_fields': ['ui_summary'], 'ui_summary': 'unique-note',
    }).get_json()
    assert result['success'], result
    assert result['file_modified'] is False
    assert result['canonical_ui']['id'] == card_id
    assert result['canonical_ui']['ui_summary'] == 'unique-note'
    assert ((root / card_id).read_bytes(), (root / card_id).stat().st_mtime_ns) == before
    forbidden.assert_not_called()
    jobs.assert_not_called()  # UI commit already made the projection and durable intent.
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE job_type='upsert_card' "
                            "AND status IN ('pending','running')").fetchone()[0] == 0
        assert conn.execute('SELECT summary_preview FROM index_entities_v2 WHERE entity_id = ?',
                            ('card::' + card_id,)).fetchone()[0] == 'unique-note'
        assert 'unique-note' in conn.execute('SELECT content FROM index_search_fast_v2 WHERE entity_id = ?',
                                              ('card::' + card_id,)).fetchone()[0]
    if card_id == 'bundle/old.png':
        assert result['updated_card']['ui_summary'] == 'original'
        assert ui_store.load_ui_data()['bundle']['_version_remarks'][card_id]['extension'] is True
        if not cold:
            assert cache.id_map['bundle/main.png']['ui_summary'] == 'original'


def test_patch_preserves_fields_and_runs_only_real_side_effects(library, monkeypatch):
    client, _, _, _, jobs = library
    source = Mock(return_value=None)
    prepare = Mock(return_value={})
    monkeypatch.setattr(cards, 'auto_run_forum_tags_on_link_update', source)
    monkeypatch.setattr(cards, 'prepare_source_link_for_card', prepare)
    for fields in ({'ui_summary': 'changed'}, {'source_link': 'keep'}, {'resource_folder': ''}):
        assert client.post('/api/update_card', json={'id': 'hero.png', 'ui_only': True, **fields}).get_json()['success']
    saved = ui_store.load_ui_data()['hero.png']
    assert (saved['link'], saved['resource_folder'], saved['unknown']) == ('keep', 'assets', [1])
    source.assert_not_called()
    prepare.assert_not_called()
    jobs.reset_mock()
    result = client.post('/api/update_card', json={'id': 'hero.png', 'ui_only': True,
        'source_link': '', 'resource_folder': '', 'ui_only_fields': ['source_link', 'resource_folder']}).get_json()
    assert result['success']
    assert result['canonical_ui']['resource_folder'] == result['canonical_ui']['source_link'] == ''
    assert [call.args[0] for call in jobs.call_args_list] == ['upsert_world_owner']
    source.assert_called_once()
    prepare.assert_called_once()


def test_bundle_ui_patch_honors_legacy_version_target(library):
    client, _, _, cache, _ = library
    result = client.post('/api/update_card', json={
        'id': 'bundle/main.png', 'ui_only': True, 'ui_summary': 'targeted note',
        'save_ui_to_bundle': True, 'bundle_dir': 'bundle', 'version_id': 'bundle/old.png',
    }).get_json()
    assert result['success']
    assert result['canonical_ui']['id'] == 'bundle/old.png'
    assert result['updated_card']['ui_summary'] == 'original'
    assert cache.id_map['bundle/main.png']['ui_summary'] == 'original'
    assert ui_store.load_ui_data()['bundle']['_version_remarks']['bundle/old.png']['summary'] == 'targeted note'


def test_source_reset_preserves_concurrent_card_and_plugin_commits(library, monkeypatch):
    from core.services import forum_update_service

    client, _, _, _, _ = library
    real_prepare = forum_update_service.prepare_source_link_for_card

    def concurrent_prepare(*args, **kwargs):
        # A different writer commits after the first UI save but before source actions.
        assert ui_store.update_ui_data(lambda data: data.update({
            'other.png': {'summary': 'concurrent'}, '_plugins_v1': {'example': {'saved': True}},
        }))
        return real_prepare(*args, **kwargs)

    monkeypatch.setattr(cards, 'prepare_source_link_for_card', concurrent_prepare)
    monkeypatch.setattr(cards, 'auto_run_forum_tags_on_link_update', lambda *_: None)
    result = client.post('/api/update_card', json={
        'id': 'hero.png', 'ui_only': True, 'source_link': 'https://example.test/new',
    }).get_json()
    assert result['success'], result
    saved = ui_store.load_ui_data()
    assert saved['other.png']['summary'] == 'concurrent'
    assert saved['_plugins_v1']['example']['saved'] is True
    assert saved['hero.png']['_source_update_v1']['source_url'] == 'https://example.test/new'
    # Direct service callers may still supply a stale plain dictionary.
    assert real_prepare('hero.png', source_link='https://example.test/newer', ui_data={})['success']
    assert ui_store.load_ui_data()['_plugins_v1']['example']['saved'] is True


def test_source_actions_report_only_canonical_fields_they_modified(library, monkeypatch):
    client, _, _, _, _ = library
    monkeypatch.setattr(cards, 'auto_run_forum_tags_on_link_update', lambda *_: {
        'run': True, 'result': {'final_tags': ['fetched-tag'],
                              'creator_sync': {'success': True, 'changed': True, 'creator': 'fetched-author'}},
    })
    result = client.post('/api/update_card', json={
        'id': 'hero.png', 'ui_only': True, 'source_link': 'https://example.test/source',
    }).get_json()
    assert result['success'], result
    assert result['canonical_fields'] == {'tags': ['fetched-tag'], 'creator': 'fetched-author'}
    assert result['updated_card']['tags'] == ['fetched-tag']
    assert result['updated_card']['creator'] == 'fetched-author'


@pytest.mark.parametrize('card_id', ['hero.png', 'bundle/main.png', 'bundle/old.png'])
@pytest.mark.parametrize('explicit_fields', [False, True])
def test_same_note_retry_repairs_index_after_partial_commit(library, monkeypatch, card_id, explicit_fields):
    client, _, db, cache, _ = library
    from core.data import local_state_repository as state
    payload = {'id': card_id, 'ui_only': True, 'ui_summary': 'committed-note'}
    if explicit_fields:
        payload['ui_only_fields'] = ['ui_summary']
    original = state.Repository().export_snapshot()
    with monkeypatch.context() as failure:
        failure.setattr(index_build_service, 'apply_card_increment', Mock(side_effect=RuntimeError('SQL projection failed')))
        result = client.post('/api/update_card', json=payload).get_json()
    assert not result['success'] and result['ui_data_save_failed']
    assert state.Repository().export_snapshot() == original
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT summary_preview FROM index_entities_v2 WHERE entity_id=?',
                            ('card::' + card_id,)).fetchone()[0] != 'committed-note'
    retry = client.post('/api/update_card', json=payload).get_json()
    assert retry['success'], retry
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT summary_preview FROM index_entities_v2 WHERE entity_id=?',
                            ('card::' + card_id,)).fetchone()[0] == 'committed-note'
        assert 'committed-note' in conn.execute('SELECT content FROM index_search_fast_v2 WHERE entity_id=?',
                                               ('card::' + card_id,)).fetchone()[0]
    if card_id != 'bundle/old.png':
        assert cache.id_map[card_id]['ui_summary'] == 'committed-note'

def test_ui_cache_revalidates_primary_after_temporary_access_failure(monkeypatch, tmp_path):
    from core.data import local_state_repository as state
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(tmp_path / 'ui.json'))
    assert ui_store.save_ui_data({'hero': {'summary': 'latest'}})
    with monkeypatch.context() as failure:
        failure.setattr(state, 'connect', Mock(side_effect=PermissionError('temporary')))
        with pytest.raises(state.LocalStateError):
            ui_store.load_ui_data()['hero']
        assert not ui_store.save_ui_data({'new': {}})
    recovered = ui_store.load_ui_data()
    assert recovered['hero']['summary'] == 'latest'
    recovered['hero']['summary'] = 'writable again'
    assert ui_store.save_ui_data(recovered)
    assert state.Repository().get('hero')['summary'] == 'writable again'

@pytest.mark.parametrize('cached_disk', [False, True])
def test_failed_normalization_is_not_cached_and_retries_persistence(monkeypatch, tmp_path, cached_disk):
    from core.data import local_state_repository as state
    path = tmp_path / 'ui.json'
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(path))
    original = {'hero': {'summary': 'disk', 'import_time': 'invalid', 'resource_folder': 'cards'}}
    path.write_text(json.dumps(original), encoding='utf-8')
    activate = state._activate
    with monkeypatch.context() as failure:
        failure.setattr(state, '_activate', Mock(side_effect=OSError('temporary')))
        with pytest.raises(state.LocalStateError):
            state.initialize()
    assert json.loads(path.read_text()) == original
    normalized = ui_store.load_ui_data()
    assert normalized['hero'] == {'summary': 'disk', 'resource_folder': ''}
    assert ui_store.update_ui_data(lambda data: data.update(_plugins_v1={'new': True}))
    normalized['hero']['summary'] = 'edited'
    assert ui_store.save_ui_data(normalized)
    assert ui_store.load_ui_data()['_plugins_v1'] == {'new': True}

def test_ui_cache_detaches_callers_and_invalidates_external_replacement(monkeypatch, tmp_path):
    from core.data import local_state_repository as state
    path = tmp_path / 'ui.json'
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(path))
    assert ui_store.save_ui_data({'a': {'summary': 'old', 'nested': [1]}})
    first = ui_store.load_ui_data()
    first['a']['nested'].append(2)
    assert ui_store.load_ui_data()['a']['nested'] == [1]
    # External committed SQL changes become visible; stale migration JSON is ignored.
    state.Repository().update_fields('a', {'summary': 'external'})
    path.write_text('{"a":{"summary":"stale JSON"}}')
    assert ui_store.load_ui_data()['a']['summary'] == 'external'
    first['a']['summary'] = 'conflict'
    assert not ui_store.save_ui_data(first)

def test_concurrent_legacy_read_modify_write_merges_fields(monkeypatch, tmp_path):
    from copy import deepcopy
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(tmp_path / 'ui.json'))
    ui_store.save_ui_data({'hero': {'summary': 'old', 'favorite': False, 'unknown': {'a': 1}}})
    snapshots = [deepcopy(ui_store.load_ui_data()) for _ in range(12)]
    for i, snapshot in enumerate(snapshots):
        snapshot['hero']['unknown'][str(i)] = i
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(ui_store.save_ui_data, snapshots))
    result = ui_store.load_ui_data()['hero']
    assert result['summary'] == 'old'
    assert result['unknown'] == {'a': 1, **{str(i): i for i in range(12)}}


def test_tags_skip_equal_and_rebuild_on_real_change_and_deletion(monkeypatch):
    cache = GlobalMetadataCache()
    cache.id_map = {key: {'id': key, 'tags': tags, 'source_update': {'last_status': 'ok'}}
                    for key, tags in [('a', ['one']), ('b', ['two'])]}
    rebuild = Mock(wraps=cache._rebuild_global_tags_locked)
    monkeypatch.setattr(cache, '_rebuild_global_tags_locked', rebuild)
    cache.update_card_data('a', {'tags': [' one ', 'one']})
    cache.update_tags_update('a', ['one'])
    assert rebuild.call_count == 0
    cache.update_card_data('a', {'tags': ['three']})
    assert cache.global_tags == ['three', 'two']
    cache.delete_card_update('b')
    assert cache.global_tags == ['three']


def test_reload_does_io_without_cache_lock_and_retries_concurrent_update(library, monkeypatch):
    from core.data import cache as cache_module

    _, root, db, cache, _ = library
    monkeypatch.setattr(cache_module, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(cache_module, 'DEFAULT_DB_PATH', str(db))
    reads = []

    def read_with_writer():
        assert cache.lock.acquire(blocking=False), 'UI I/O must not hold the cache lock'
        cache.lock.release()
        snapshot = ui_store.load_ui_data()
        reads.append(True)
        if len(reads) == 1:
            ui_store.update_ui_data(lambda data: data['hero.png'].update(summary='concurrent note'))
            cache.update_card_data('hero.png', {'ui_summary': 'concurrent note'})
        return snapshot

    monkeypatch.setattr(cache_module, 'load_ui_data', read_with_writer)
    cache.reload_from_db(strict=True)
    assert len(reads) == 2
    assert cache.id_map['hero.png']['ui_summary'] == 'concurrent note'


def test_ui_first_writers_and_stat_access_failure_preserve_data(monkeypatch, tmp_path):
    from core.data import local_state_repository as state
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(tmp_path / 'ui.json'))
    first, second = ui_store.load_ui_data(), ui_store.load_ui_data()
    first['a'], second['b'] = {'summary': 'a'}, {'summary': 'b'}
    assert ui_store.save_ui_data(first) and ui_store.save_ui_data(second)
    assert set(ui_store.load_ui_data()) == {'a', 'b'}
    with monkeypatch.context() as failure:
        failure.setattr(state.Repository, 'get_many', Mock(side_effect=state.LocalStateError('denied')))
        assert not ui_store.update_ui_data(lambda data: data.__setitem__('c', {}))
    assert set(ui_store.load_ui_data()) == {'a', 'b'}

def test_chat_list_card_filter_work_is_independent_of_unrelated_files(monkeypatch, tmp_path):
    from contextlib import closing
    from core.data import local_state_repository as state
    from core.services import chat_catalog_service as catalog

    root = tmp_path / 'chats'
    root.mkdir()
    cache = GlobalMetadataCache()
    cache.initialized = True
    cache.id_map = {'hero.png': {'id': 'hero.png', 'char_name': 'Hero'},
                    'other.png': {'id': 'other.png', 'char_name': 'Other'}}
    monkeypatch.setattr(chats.ctx, 'cache', cache)
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(root))
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(tmp_path / 'ui.json'))
    ui_store.save_ui_data({'hero.png': {'chat_ids': ['one.jsonl']},
                           'other.png': {'chat_ids': ['one.jsonl', 'two.jsonl']}})
    for filename in ('one.jsonl', 'two.jsonl'):
        (root / filename).write_text('{"chat_metadata": {}}\n', encoding='utf-8')
    with closing(state.connect()) as conn, conn:
        catalog.ensure_schema(conn)
    catalog.reconcile(root)
    refresh = Mock(side_effect=AssertionError('unrelated file read'))
    monkeypatch.setattr(chats, '_refresh_chat_entry', refresh)
    monkeypatch.setattr(chats, '_build_binding_table', Mock(side_effect=AssertionError('full bindings scan')))
    monkeypatch.setattr(chats, '_build_binding_info', Mock(side_effect=AssertionError('per-chat scan')))
    app = Flask(__name__)
    app.register_blueprint(chats.bp)
    client = app.test_client()
    monkeypatch.setattr(chats, '_iter_chat_files', Mock(side_effect=AssertionError('directory walk')))
    response = client.get('/api/chats/list').get_json()
    assert response['success'] and response['total'] == 2
    response = client.get('/api/chats/list?card_id=hero.png').get_json()
    assert response['success'] and [item['id'] for item in response['items']] == ['one.jsonl']
    assert response['items'][0]['bound_card_count'] == 2
    with closing(state.connect()) as conn, conn:
        conn.execute("""INSERT INTO chat_files SELECT root,'unrelated-'||value,revision,
            parse_version,mtime,size,name,character,preview,facts FROM chat_files,
            (WITH RECURSIVE numbers(value) AS (VALUES(1) UNION ALL SELECT value+1 FROM numbers WHERE value<1000)
            SELECT value FROM numbers) WHERE chat_id='two.jsonl'""")
    work = []
    connect = state.connect

    def monitored(*args, **kwargs):
        conn = connect(*args, **kwargs)
        conn.set_progress_handler(lambda: work.append(1) or 0, 100)
        return conn

    monkeypatch.setattr(state, 'connect', monitored)
    assert client.get('/api/chats/list?card_id=hero.png').get_json() == response
    assert len(work) < 20
    refresh.assert_not_called()


def test_reader_detail_range_keep_bindings_and_local_state(monkeypatch, tmp_path):
    from core.data import chat_store

    root = tmp_path / 'chats'
    root.mkdir()
    path = root / 'reader.jsonl'
    path.write_text('\n'.join(json.dumps(line) for line in [
        {'user_name': 'User', 'character_name': 'Hero'},
        *[{'name': 'Hero', 'is_user': False, 'mes': f'floor {i}', 'send_date': ''}
          for i in range(1, 6)],
    ]) + '\n')
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(root))
    monkeypatch.setattr(chat_store, 'CHAT_DATA_FILE', str(tmp_path / 'chat_data.json'))
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(tmp_path / 'ui.json'))
    cache = GlobalMetadataCache()
    cache.id_map = {'hero.png': {'id': 'hero.png', 'char_name': 'Hero'}}
    monkeypatch.setattr(chats.ctx, 'cache', cache)
    ui_store.save_ui_data({'hero.png': {'chat_ids': ['reader.jsonl']}})
    chat_store.save_chat_data({'reader.jsonl': {'favorite': True, 'notes': 'local note',
        'bookmarks': [{'floor': 3, 'label': 'saved'}], 'last_view_floor': 4, 'extension': 'keep'}})
    app = Flask(__name__)
    app.register_blueprint(chats.bp)
    client = app.test_client()
    saved_bookmarks = chat_store.load_chat_data()['reader.jsonl']['bookmarks']
    detail = client.post('/api/chats/detail', json={'id': 'reader.jsonl'}).get_json()
    assert detail['success']
    assert detail['chat']['bound_card_id'] == 'hero.png'
    assert detail['chat']['favorite'] and detail['chat']['notes'] == 'local note'
    assert detail['chat']['bookmarks'] == saved_bookmarks
    first = client.post('/api/chats/range', json={'id': 'reader.jsonl', 'page_size': 2, 'page': 1}).get_json()
    second = client.post('/api/chats/range', json={'id': 'reader.jsonl', 'page_size': 2, 'page': 2}).get_json()
    assert first['success'] and second['success']
    assert [message['mes'] for message in first['range']['raw_messages']] == ['floor 1', 'floor 2']
    assert [message['mes'] for message in second['range']['raw_messages']] == ['floor 3', 'floor 4']
    assert second['range']['last_view_floor'] == 4
    assert chat_store.load_chat_data()['reader.jsonl']['extension'] == 'keep'



def test_cache_reload_batches_ui_without_reading_all_pngs(library, monkeypatch):
    from core.utils import png_metadata
    from core.data import local_state_repository as state
    client, root, db, cache, jobs = library
    from core.data import cache as cache_module
    monkeypatch.setattr(cache_module, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(cache_module, 'CARDS_FOLDER', str(root))
    # This check guards work count, independent of wall-clock timing or digest-cache size.
    with sqlite3.connect(db) as conn:
        conn.executemany("INSERT INTO card_metadata(id,char_name,tags,category,last_modified) VALUES (?,?,'[]','',1)",
                         [(f'card{i}.png', f'card{i}') for i in range(1000)])
    state.Repository().replace_snapshot({f'card{i}.png': {'import_time': 1} for i in range(1000)})
    cache.reload_from_db(strict=True)
    calls = []
    connect = sqlite3.connect
    def counted(*args, **kwargs):
        calls.append(args[0])
        return connect(*args, **kwargs)
    def no_scan(*args, **kwargs):
        raise AssertionError('cache reload must not scan PNG bodies')
    versions = []
    get_version = cache_module.card_image_file_version
    def counted_version(*args, **kwargs):
        versions.append(args[0])
        return get_version(*args, **kwargs)
    monkeypatch.setattr(sqlite3, 'connect', counted)
    monkeypatch.setattr(cache_module, 'card_image_file_version', counted_version)
    monkeypatch.setattr(png_metadata, '_scan_png', no_scan)
    cache.reload_from_db(strict=True)
    assert len(calls) < 10
    assert versions == []
    assert len(cache.cards) >= 1000


def test_cache_reload_rechecks_image_revision_when_file_version_changes(library, monkeypatch):
    from PIL import Image
    from core.data import cache as cache_module
    from core.utils.image import card_image_file_version, card_image_revision
    client, root, db, cache, _jobs = library
    monkeypatch.setattr(cache_module, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(cache_module, 'CARDS_FOLDER', str(root))
    image_path = root / 'hero.png'
    Image.new('RGB', (8, 8), 'blue').save(image_path)

    cache.reload_from_db(strict=True)
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            'SELECT file_hash, last_modified FROM card_metadata WHERE id=?', ('hero.png',)
        ).fetchone()
    cache.update_card_data('hero.png', {'file_hash': row[0], 'last_modified': row[1]})
    old_revision = cache.id_map['hero.png']['image_revision']
    old_stat = image_path.stat()
    old_bytes = image_path.read_bytes()
    old_quick_version = card_image_file_version(image_path)
    old_full_version = card_image_file_version(image_path, include_change_time=True)
    assert cache._image_file_versions.get('hero.png') is None

    Image.new('RGB', (8, 8), 'magenta').save(image_path)
    os.utime(image_path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
    changed_stat = image_path.stat()
    assert image_path.read_bytes() != old_bytes
    assert changed_stat.st_size == old_stat.st_size
    assert changed_stat.st_mtime_ns == old_stat.st_mtime_ns
    assert changed_stat.st_ino == old_stat.st_ino
    if os.name == 'nt':
        assert card_image_file_version(image_path) == old_quick_version
    assert card_image_file_version(image_path, include_change_time=True) != old_full_version

    real_revision = card_image_revision
    revision_calls = []

    def tracked_revision(path):
        revision_calls.append(path)
        return real_revision(path)

    monkeypatch.setattr(cache_module, 'card_image_revision', tracked_revision)
    cache.reload_from_db(strict=True)

    fresh_revision = real_revision(str(image_path))
    assert revision_calls == [str(image_path)]
    assert cache.id_map['hero.png']['image_revision'] == fresh_revision != old_revision
    assert cache.id_map['hero.png']['image_url'].endswith(
        cache.id_map['hero.png']['image_revision']
    )
    with sqlite3.connect(db) as conn:
        assert conn.execute(
            'SELECT file_hash, last_modified FROM card_metadata WHERE id=?', ('hero.png',)
        ).fetchone() == row


def test_note_projection_only_acknowledges_matching_projection_work(library):
    client, root, db, _cache, _jobs = library
    source_path = str(root / 'hero.png')
    protected = [
        ({'refresh_file': True, 'operation_kind': 'replace'}, 'pending'),
        ({'refresh_file': True, 'operation_kind': 'convert', 'old_id': 'hero.json'}, 'running'),
        ({'refresh_file': True, 'operation_kind': 'rename', 'old_id': 'old.png'}, 'failed'),
        ({'remove_entity_ids': ['old.png']}, 'pending'),
        ({'ui_key': 'other', 'ui_revision': 0}, 'pending'),
        ({'ui_key': 'hero.png', 'ui_revision': 10**8}, 'pending'),
        ({'source_revision': 'different file version'}, 'pending'),
    ]
    with sqlite3.connect(db) as conn:
        previous_source = conn.execute(
            "SELECT source_revision FROM index_entities_v2 WHERE entity_id='card::hero.png'"
        ).fetchone()[0]
        protected_ids = []
        for payload, status in protected:
            protected_ids.append(conn.execute(
                "INSERT INTO index_jobs(job_type,entity_id,source_path,payload_json,status) VALUES ('upsert_card',?,?,?,?)",
                ('hero.png', source_path, json.dumps(payload), status),
            ).lastrowid)
        ui_job = conn.execute(
            "INSERT INTO index_jobs(job_type,entity_id,source_path,payload_json) VALUES ('upsert_card',?,?,?)",
            ('hero.png', source_path, json.dumps({'ui_key': 'hero.png', 'ui_revision': 0})),
        ).lastrowid
    # The UI path must not read these unindexed file bytes or claim them as projected.
    (root / 'hero.png').write_bytes(b'new file contents awaiting refresh')
    result = client.post('/api/update_card', json={
        'id': 'hero.png', 'ui_only': True, 'ui_only_fields': ['ui_summary'],
        'ui_summary': 'note with recovery work outstanding',
    }).get_json()
    assert result['success'], result
    with sqlite3.connect(db) as conn:
        for job_id, (_payload, status) in zip(protected_ids, protected):
            assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (job_id,)).fetchone()[0] == status
        assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (ui_job,)).fetchone()[0] == 'done'
        assert conn.execute(
            "SELECT source_revision FROM card_ui_projections WHERE card_id='hero.png'"
        ).fetchone()[0] == previous_source
