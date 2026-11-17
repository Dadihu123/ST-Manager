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
    assert [call.args[0] for call in jobs.call_args_list] == ['upsert_card']
    with sqlite3.connect(db) as conn:
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
    from core.services import index_job_worker

    client, _, db, cache, _ = library
    # Persist a real recovery job without running a background worker.
    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(index_job_worker, '_set_jobs_state', Mock())
    monkeypatch.setattr(cards.ctx, 'index_wakeup', Mock())
    monkeypatch.setattr(card_index_sync_service, 'enqueue_index_job', index_job_worker.enqueue_index_job)
    apply = card_service.apply_card_increment
    payload = {'id': card_id, 'ui_only': True, 'ui_summary': 'committed-note'}
    if explicit_fields:
        payload['ui_only_fields'] = ['ui_summary']
    with monkeypatch.context() as failure:
        failure.setattr(card_service, 'apply_card_increment', Mock(side_effect=RuntimeError('injected failure')))
        result = client.post('/api/update_card', json=payload).get_json()
    assert not result['success'] and result['ui_data_saved'] and result['index_sync_pending'] and result['retryable']
    assert result['canonical_ui']['ui_summary'] == 'committed-note'
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT summary_preview FROM index_entities_v2 WHERE entity_id = ?',
                            ('card::' + card_id,)).fetchone()[0] == ''
        assert conn.execute("SELECT status FROM index_jobs WHERE entity_id = ?", (card_id,)).fetchone()[0] == 'pending'
    calls = Mock(wraps=apply)
    monkeypatch.setattr(card_service, 'apply_card_increment', calls)
    retry = client.post('/api/update_card', json=payload).get_json()
    assert retry['success'], retry
    calls.assert_called_once()
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT summary_preview FROM index_entities_v2 WHERE entity_id = ?',
                            ('card::' + card_id,)).fetchone()[0] == 'committed-note'
        assert 'committed-note' in conn.execute('SELECT content FROM index_search_fast_v2 WHERE entity_id = ?',
                                               ('card::' + card_id,)).fetchone()[0]
    if card_id != 'bundle/old.png':
        assert cache.id_map[card_id]['ui_summary'] == 'committed-note'


def test_ui_cache_revalidates_primary_after_temporary_access_failure(monkeypatch, tmp_path):
    path = tmp_path / 'ui.json'
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(path))
    assert ui_store.save_ui_data({'hero': {'summary': 'previous'}})
    assert ui_store.save_ui_data({'hero': {'summary': 'latest'}})
    with monkeypatch.context() as failure:
        failure.setattr(ui_store, '_file_version', Mock(side_effect=PermissionError('temporary')))
        assert ui_store.load_ui_data()['hero']['summary'] == 'previous'
    assert ui_store.is_ui_data_degraded()
    read = Mock(wraps=ui_store._read_json_file)
    monkeypatch.setattr(ui_store, '_read_json_file', read)
    recovered = ui_store.load_ui_data()
    assert recovered['hero']['summary'] == 'latest'
    assert read.call_count == 1  # Matching stat alone cannot establish read access recovery.
    assert not ui_store.is_ui_data_degraded()
    recovered['hero']['summary'] = 'writable again'
    assert ui_store.save_ui_data(recovered)
    assert json.loads(path.read_text())['hero']['summary'] == 'writable again'


@pytest.mark.parametrize('cached_disk', [False, True])
def test_failed_normalization_is_not_cached_and_retries_persistence(monkeypatch, tmp_path, cached_disk):
    path = tmp_path / 'ui.json'
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(path))
    original = {'hero': {'summary': 'disk', 'import_time': 'invalid', 'resource_folder': 'cards'}}
    path.write_text(json.dumps(original), encoding='utf-8')
    if cached_disk:
        assert ui_store.save_ui_data(original)
        ui_store._mark_ui_data_degraded('revalidate primary after transient access failure')
    version = ui_store._file_version(str(path))
    with monkeypatch.context() as failure:
        failure.setattr(ui_store, '_write_ui_data_file_atomic', Mock(side_effect=PermissionError('temporary')))
        normalized = ui_store.load_ui_data()
    assert json.loads(path.read_text()) == original
    assert 'import_time' not in normalized['hero'] and normalized['hero']['resource_folder'] == ''
    assert ui_store._ui_snapshot is None or ui_store._ui_snapshot[0] != version
    assert version not in ui_store._file_stats_cache
    assert ui_store.load_ui_data()['hero'] == {'summary': 'disk', 'resource_folder': ''}
    assert json.loads(path.read_text())['hero'] == {'summary': 'disk', 'resource_folder': ''}
    # Even a caller retaining the failed normalized view has the genuine disk origin.
    assert ui_store.update_ui_data(lambda data: data.update(_plugins_v1={'new': True}))
    normalized['hero']['summary'] = 'edited'
    assert ui_store.save_ui_data(normalized)
    assert ui_store.load_ui_data()['_plugins_v1'] == {'new': True}


def test_ui_cache_detaches_callers_and_invalidates_external_replacement(monkeypatch, tmp_path):
    path = tmp_path / 'ui.json'
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(path))
    ui_store.save_ui_data({'a': {'summary': 'old', 'nested': [1]}})
    read = Mock(wraps=ui_store._read_json_file)
    monkeypatch.setattr(ui_store, '_read_json_file', read)
    first = ui_store.load_ui_data()
    first['a']['nested'].append(2)
    assert ui_store.load_ui_data()['a']['nested'] == [1]
    assert read.call_count == 0
    replacement = tmp_path / 'replacement'
    replacement.write_text(json.dumps({'a': {'summary': 'external'}}))
    os.replace(replacement, path)
    assert ui_store.load_ui_data()['a']['summary'] == 'external'
    assert read.call_count == 1
    ui_store.save_ui_data(ui_store.load_ui_data())
    assert read.call_count == 1  # guard and backup reuse the validated snapshot


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
    path = tmp_path / 'ui.json'
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(path))
    first = ui_store.load_ui_data()
    second = ui_store.load_ui_data()
    first['a'] = {'summary': 'a'}
    second['b'] = {'summary': 'b'}
    assert ui_store.save_ui_data(first) and ui_store.save_ui_data(second)
    assert set(ui_store.load_ui_data()) == {'a', 'b'}
    original_bytes = path.read_bytes()
    monkeypatch.setattr(ui_store, '_file_version', Mock(side_effect=PermissionError('denied')))
    assert set(ui_store.load_ui_data()) == {'a'}  # Readable backup remains available for display.
    assert ui_store.is_ui_data_degraded()
    assert ui_store.save_ui_data({}) is False
    assert path.read_bytes() == original_bytes
    ui_store._clear_ui_data_degraded()


def test_chat_list_builds_binding_projection_once_and_card_filter_reads_only_related(monkeypatch, tmp_path):
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
    monkeypatch.setattr(chats, 'load_chat_data', lambda: {})
    monkeypatch.setattr(chats, 'save_chat_data', lambda data: True)
    (root / 'one.jsonl').write_text('{}\n')
    (root / 'two.jsonl').write_text('{}\n')
    refresh = Mock(return_value=({}, False, None, [], []))
    monkeypatch.setattr(chats, '_refresh_chat_entry', refresh)
    table = Mock(wraps=chats._build_binding_table)
    monkeypatch.setattr(chats, '_build_binding_table', table)
    monkeypatch.setattr(chats, '_build_binding_info', Mock(side_effect=AssertionError('per-chat scan')))
    app = Flask(__name__)
    app.register_blueprint(chats.bp)
    client = app.test_client()
    monkeypatch.setattr(chats, '_iter_chat_files', lambda: [str(root / name) for name in ('one.jsonl', 'two.jsonl')])
    response = client.get('/api/chats/list').get_json()
    assert response['success'] and response['total'] == 2
    assert table.call_count == 1
    table.reset_mock()
    refresh.reset_mock()
    monkeypatch.setattr(chats, '_iter_chat_files', Mock(side_effect=AssertionError('unrelated directory')))
    response = client.get('/api/chats/list?card_id=hero.png').get_json()
    assert response['success'] and [item['id'] for item in response['items']] == ['one.jsonl']
    assert response['items'][0]['bound_card_count'] == 2
    assert [call.args[0] for call in refresh.call_args_list] == ['one.jsonl']
    assert table.call_count == 1


def test_chat_inaccessible_directory_does_not_cleanup(monkeypatch):
    monkeypatch.setattr(chats, 'load_chat_data', lambda: {'keep.jsonl': {'notes': 'keep'}})
    monkeypatch.setattr(chats, 'load_ui_data', lambda: {})
    monkeypatch.setattr(chats, '_iter_chat_files', Mock(side_effect=PermissionError('unavailable')))
    save = Mock()
    monkeypatch.setattr(chats, 'save_chat_data', save)
    app = Flask(__name__)
    app.register_blueprint(chats.bp)
    assert app.test_client().get('/api/chats/list').get_json()['success'] is False
    save.assert_not_called()


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
