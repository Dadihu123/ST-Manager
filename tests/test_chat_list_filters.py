import errno
import json
import os
import subprocess
import sys
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from io import BytesIO
from types import SimpleNamespace

import pytest
from flask import Flask

from core.api.v1 import chats
from core.data import chat_store, local_state_repository as state, ui_store
from core.services import chat_catalog_service as catalog


@pytest.fixture
def library(monkeypatch, tmp_path):
    db = tmp_path / 'test.db'
    root = tmp_path / 'chat'
    root.mkdir()
    monkeypatch.setattr(state, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(chat_store, 'CHAT_DATA_FILE', str(tmp_path / 'chat.json'))
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(tmp_path / 'ui.json'))
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(root))
    state.initialize()
    valid = '96b71299-c1d3-4337-b78a-1b23d1d05375'
    stale = '025f39e1-ecad-4aac-b836-efb87448117a'
    cache = SimpleNamespace(id_map={
        'a.png': dict(char_name='Alpha', card_uid=valid),
        'z.png': dict(char_name='Zeta'),
        'old.png': dict(char_name='Replacement', card_uid=valid),
    }, bundle_map={}, lock=threading.RLock())
    monkeypatch.setattr(chats.ctx, 'cache', cache)
    with closing(state.connect()) as conn, conn:
        catalog.ensure_schema(conn)
        state.Repository('chat')._put(conn, 'fav.jsonl', dict(
            favorite=True, display_name='收藏 🐉', notes='notes %_', last_view_floor=2))
        ui = state.Repository('ui')
        ui._put(conn, 'a.png', dict(chat_ids=['fav.jsonl'], card_uid=valid))
        ui._put(conn, 'z.png', dict(chat_ids=['fav.jsonl']))
        ui._put(conn, 'old.png', dict(chat_ids=['plain.jsonl'], card_uid=stale))
    for name in ('fav.jsonl', 'plain.jsonl'):
        (root / name).write_text('\n'.join(map(json.dumps, [
            {'chat_metadata': {}, 'user_name': 'User'}, {'mes': 'First', 'is_user': True},
            {'mes': 'Second', 'is_user': False},
        ])), encoding='utf-8')
    app = Flask(__name__)
    app.register_blueprint(chats.bp)
    return app.test_client(), root, db


@pytest.mark.parametrize('favorite,expected,bound', [('included', 'fav.jsonl', 1), ('excluded', 'plain.jsonl', 0)])
def test_chat_filters_and_stats_use_projected_files(library, monkeypatch, favorite, expected, bound):
    client, root, _ = library
    assert client.get('/api/chats/list').status_code == 503
    catalog.reconcile(root)
    with monkeypatch.context() as patch:
        def unexpected(*args, **kwargs):
            pytest.fail('hot list accessed a file, chat parser, or whole binding table')

        patch.setattr(catalog, 'walk_directory_strict', unexpected)
        patch.setattr(catalog, '_inspect', unexpected)
        patch.setattr(chats, '_build_binding_table', unexpected)
        data = client.get('/api/chats/list', query_string={'fav_filter': favorite}).get_json()
        assert data['success']
        assert [item['id'] for item in data['items']] == [expected]
        assert data['stats'] == {'favorites': bound, 'bound': bound, 'unbound': 1 - bound}
        assert client.get('/api/chats/list?card_id=old.png').get_json()['total'] == 0
        target = client.get('/api/chats/list?card_id=a.png&search=%25_').get_json()
        assert [record['card_name'] for record in target['items'][0]['bound_cards']] == ['Alpha', 'Zeta']


def test_reconcile_failure_and_root_switch_preserve_authority(library, monkeypatch, tmp_path):
    client, root, db = library
    catalog.reconcile(root)
    (root / 'fav.jsonl').unlink()
    with monkeypatch.context() as patch:
        def broken(*args):
            raise PermissionError('inaccessible child')
        patch.setattr(catalog, 'walk_directory_strict', broken)
        with pytest.raises(PermissionError):
            catalog.reconcile(root)
        stale = client.get('/api/chats/list').get_json()
        assert stale['index_stale'] and stale['total'] == 2
    catalog.reconcile(root)
    assert client.get('/api/chats/list').get_json()['total'] == 1
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT count(*) FROM chat_local_state WHERE key='fav.jsonl'").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM chat_card_bindings WHERE chat_id='fav.jsonl'").fetchone()[0] == 2
    new_root = tmp_path / 'new'
    new_root.mkdir()
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(new_root))
    assert client.get('/api/chats/list').status_code == 503
    catalog.reconcile(new_root)
    assert client.get('/api/chats/list').get_json()['total'] == 0


def test_reader_and_save_remain_compatible(library):
    client, root, _ = library
    catalog.reconcile(root)
    detail = client.post('/api/chats/detail', json={'id': 'fav.jsonl'}).get_json()['chat']
    assert (detail['notes'], detail['bound_card_count'], detail['message_count']) == ('notes %_', 2, 2)
    result = client.post('/api/chats/range', json={'id': 'fav.jsonl', 'page': 2, 'page_size': 1}).get_json()['range']
    assert (result['start_floor'], result['last_view_floor']) == (2, 2)
    assert result['raw_messages'][0]['mes'] == 'Second'
    assert client.post('/api/chats/update_meta', json={'id': 'fav.jsonl', 'last_view_floor': 1}).get_json()['success']
    assert client.post('/api/chats/save', json={'id': 'fav.jsonl', 'metadata': {'custom': 'kept'},
                                              'raw_messages': [{'is_user': True, 'mes': 'new'}]}
                       ).get_json()['success']
    row = client.get('/api/chats/list?card_id=a.png').get_json()['items'][0]
    assert (row['message_count'], row['last_view_floor']) == (1, 1)
    assert client.get('/api/chats/list').get_json()['total'] == 2
    updated = client.post('/api/chats/detail', json={'id': 'fav.jsonl'}).get_json()['chat']
    assert updated['metadata']['custom'] == 'kept'


def test_import_rebind_and_delete_are_visible_without_reconcile(library, monkeypatch, tmp_path):
    client, root, db = library
    monkeypatch.setattr(chats, 'TRASH_FOLDER', str(tmp_path / 'trash'))
    catalog.reconcile(root)
    with (root / 'plain.jsonl').open('rb') as stream:
        payload = BytesIO(stream.read())
    result = client.post('/api/chats/import', data={
        'files': (payload, 'import.jsonl'), 'card_id': 'a.png',
    }).get_json()
    assert result['success'], result
    imported = result['items'][0]
    assert imported['bound_card_id'] == 'a.png'
    visible = client.get('/api/chats/list?card_id=a.png&search=import').get_json()
    assert visible['items'] == [imported]
    moved = client.post('/api/chats/bind', json={'id': imported['id'], 'card_id': 'z.png'}).get_json()
    assert moved['success'] and moved['moved'], moved
    assert moved['id'] == 'Zeta/import.jsonl'
    assert client.get('/api/chats/list?card_id=a.png&search=import').get_json()['total'] == 0
    visible = client.get('/api/chats/list?card_id=z.png&search=import').get_json()
    assert visible['items'] == [moved['chat']]
    with closing(state.connect(db)) as conn:
        assert not conn.execute('SELECT 1 FROM chat_file_moves').fetchone()
    assert client.post('/api/chats/delete', json={'id': moved['id']}).get_json()['success']
    assert client.get('/api/chats/list?search=import').get_json()['total'] == 0
    assert state.Repository('chat').get(moved['id']) is None
    assert not state.binding_keys([moved['id']])


def test_reconcile_does_not_overwrite_a_concurrent_save(library, monkeypatch):
    client, root, _ = library
    catalog.reconcile(root)
    target = root / 'fav.jsonl'
    original = catalog._inspect
    captured, resume = threading.Event(), threading.Event()
    outcomes = []

    def pause(*args, **kwargs):
        result = original(*args, **kwargs)
        if threading.current_thread() is worker and args[1] == str(target):
            captured.set()
            assert resume.wait(10)
        return result

    monkeypatch.setattr(catalog, '_inspect', pause)
    worker = threading.Thread(target=lambda: outcomes.append(catalog.reconcile(root)))
    worker.start()
    try:
        assert captured.wait(10)
        saved = client.post('/api/chats/save', json={'id': 'fav.jsonl', 'raw_messages': [
            {'is_user': True, 'mes': 'concurrent text'}]}).get_json()
        assert saved['success'], saved
    finally:
        resume.set()
        worker.join(10)
    assert outcomes == [False]
    assert client.get('/api/chats/list?search=concurrent').get_json()['total'] == 1


def test_duplicate_events_and_missed_delete_converge_after_restart(library):
    client, root, _ = library
    catalog.reconcile(root)
    old, new = root / 'fav.jsonl', root / 'renamed.jsonl'
    old.rename(new)
    catalog._apply_events(root, [str(new), str(old), str(new)])
    catalog._apply_events(root, [str(old), str(new)])
    assert client.get('/api/chats/list').get_json()['total'] == 3
    catalog.reconcile(root)
    assert client.get('/api/chats/list').get_json()['total'] == 2
    assert state.Repository('chat').get('fav.jsonl')['notes'] == 'notes %_'
    new.unlink()
    # No event is delivered. Fresh reconciliation sees source files plus the persisted projection.
    catalog.reconcile(root)
    assert [item['id'] for item in client.get('/api/chats/list').get_json()['items']] == ['plain.jsonl']


def test_reconcile_recovers_interrupted_chat_move_without_discarding_state(library):
    client, root, db = library
    catalog.reconcile(root)
    target = 'Alpha/fav.jsonl'
    (root / 'Alpha').mkdir()
    catalog.prepare_move(root, 'fav.jsonl', target)
    (root / 'fav.jsonl').rename(root / target)
    # Simulate process exit immediately after the filesystem rename.
    catalog.reconcile(root)
    found = client.get('/api/chats/list?card_id=a.png').get_json()['items'][0]
    assert (found['id'], found['favorite'], found['notes'], found['last_view_floor']) == (
        target, True, 'notes %_', 2)
    assert [item['card_name'] for item in found['bound_cards']] == ['Alpha', 'Zeta']
    with closing(state.connect(db)) as conn:
        assert not conn.execute('SELECT 1 FROM chat_file_moves').fetchone()
    catalog.reconcile(root)
    assert client.get('/api/chats/list?card_id=a.png').get_json()['total'] == 1


@pytest.mark.parametrize('fault', ('replaced', 'conflict', 'cross_volume'))
def test_interrupted_http_chat_move_preserves_identity_and_state(library, monkeypatch, fault):
    client, root, db = library
    catalog.reconcile(root)
    chat = state.Repository('chat')
    chat.update_fields('fav.jsonl', {'bookmarks': [{'id': 'mark', 'floor': 2, 'label': 'my mark'}]})
    original = chat.get('fav.jsonl')
    owners = state.binding_keys(['fav.jsonl'])
    original_rename = catalog._rename_without_replace

    def simulated_cross_volume(source, target, *, expected):
        if source == str(root / 'fav.jsonl'):
            raise OSError(errno.EXDEV, 'different volume')
        return original_rename(source, target, expected=expected)

    def interrupted(*args, **kwargs):
        raise OSError('exit after moving the file and before SQL commit')

    with monkeypatch.context() as inj:
        inj.setattr(catalog, 'finish_move', interrupted)
        if fault == 'cross_volume':
            inj.setattr(catalog, '_rename_without_replace', simulated_cross_volume)
        result = client.post('/api/chats/bind', json={'id': 'fav.jsonl', 'card_id': 'a.png'}).get_json()
        assert not result['success']
    dest = root / 'Alpha/fav.jsonl'
    assert dest.is_file() and not (root / 'fav.jsonl').exists()
    if fault == 'replaced':
        copy = dest.with_name('replacement.tmp')
        copy.write_bytes(dest.read_bytes())
        old_inode = dest.stat().st_ino
        copy.replace(dest)
        assert dest.stat().st_ino != old_inode
    if fault == 'conflict':
        chat.update_fields('Alpha/fav.jsonl', {'notes': 'destination', 'last_view_floor': 9})
    for _ in range(2):
        catalog.reconcile(root)
    with closing(state.connect(db)) as conn:
        intent = conn.execute('SELECT * FROM chat_file_moves').fetchone()
    if fault == 'cross_volume':
        assert not intent and chat.get('fav.jsonl') is None
        assert chat.get('Alpha/fav.jsonl') == original
        assert state.binding_keys(['Alpha/fav.jsonl']) == [(key, 'Alpha/fav.jsonl') for key, _ in owners]
        assert client.get('/api/chats/list?card_id=a.png').get_json()['items'][0]['id'] == 'Alpha/fav.jsonl'
    else:
        assert intent and chat.get('fav.jsonl') == original and state.binding_keys(['fav.jsonl']) == owners
        assert client.get('/api/chats/list').get_json()['index_stale']
        if fault == 'conflict':
            assert chat.get('Alpha/fav.jsonl')['notes'] == 'destination'


def test_reused_chat_path_has_fresh_state_and_old_values_are_recoverable(library):
    client, root, db = library
    catalog.reconcile(root)
    original = state.Repository('chat').get('fav.jsonl')
    target = root / 'fav.jsonl'
    target.unlink()
    catalog.reconcile(root)
    assert client.get('/api/chats/list?search=fav.jsonl').get_json()['total'] == 0
    target.write_text('{"chat_metadata":{}}\n{"mes":"replacement","is_user":true}', encoding='utf-8')
    catalog._apply_events(root, [str(target)])
    row = next(row for row in client.get('/api/chats/list').get_json()['items'] if row['id'] == 'fav.jsonl')
    assert (row['preview'], row['notes'], row['favorite'], row['bound_card_count']) == ('replacement', '', False, 0)
    with closing(state.connect(db)) as conn:
        archived, bindings = conn.execute('SELECT payload,bindings FROM chat_retired_state').fetchone()
    assert json.loads(archived) == original
    assert set(json.loads(bindings)['owners']) == {'a.png', 'z.png'}


def test_chat_roots_own_independent_state_and_bindings(library, monkeypatch, tmp_path):
    from core import config
    from core.plugins.api import PluginAPI

    client, root_a, _ = library
    root_b = tmp_path / 'chats-b'
    root_b.mkdir()
    chat_id = 'fav.jsonl'
    src_b = root_b / chat_id
    src_b.write_text('{"chat_metadata":{}}\n{"mes":"B original","is_user":true}', encoding='utf-8')
    catalog.reconcile(root_a)
    original_a = state.Repository('chat').get(chat_id)
    owners_a = state.binding_keys([chat_id])

    def configure(root):
        monkeypatch.setattr(chats, 'CHATS_FOLDER', str(root))
        monkeypatch.setattr(config, 'CHATS_FOLDER', str(root))
        catalog.reconcile(root)

    def read_list():
        return next(row for row in client.get('/api/chats/list').get_json()['items'] if row['id'] == chat_id)

    configure(root_b)
    row = read_list()
    assert (row['preview'], row['notes'], row['favorite'], row['bound_cards']) == ('B original', '', False, [])
    assert client.get('/api/chats/list?card_id=a.png').get_json()['total'] == 0
    assert client.post('/api/chats/range', json={'id': chat_id}).get_json()['range']['last_view_floor'] == 0
    assert PluginAPI._get_chat(None, chat_id)['notes'] == ''
    update = client.post('/api/chats/update_meta', json={'id': chat_id, 'notes': 'B private', 'favorite': True}).get_json()
    assert update['success'], update
    assert client.post('/api/chats/detail', json={'id': chat_id}).get_json()['chat']['notes'] == 'B private'
    assert PluginAPI._list_chats(None)[0]['notes'] == 'B private'

    # Ensure a second root's namespaced binding participates in both SQL paths.
    b_key = catalog.root_prefix(root_b) + chat_id
    with state.Repository('ui').transaction() as conn:
        ui = state.Repository('ui')
        card = ui.get('a.png', conn=conn)
        card['chat_ids'].append(b_key)
        ui._put(conn, 'a.png', card)
    assert client.get('/api/chats/list?card_id=a.png').get_json()['items'][0]['id'] == chat_id

    # Replace B at the same path after confirmed absence. Only B's state retires.
    src_b.unlink()
    catalog.reconcile(root_b)
    src_b.write_text('{"chat_metadata":{}}\n{"mes":"B replacement","is_user":true}', encoding='utf-8')
    assert client.post('/api/chats/detail', json={'id': chat_id}).get_json()['chat']['notes'] == ''
    assert client.post('/api/chats/update_meta', json={'id': chat_id, 'notes': 'do not misassign'}).status_code == 409
    catalog.reconcile(root_b)
    row = read_list()
    assert (row['preview'], row['notes'], row['favorite'], row['bound_cards']) == ('B replacement', '', False, [])
    assert state.Repository('chat').get(b_key) is None
    assert state.binding_keys([b_key]) == []

    configure(root_a)
    row = read_list()
    assert (row['notes'], row['favorite'], row['bound_card_count']) == ('notes %_', True, 2)
    assert state.Repository('chat').get(chat_id) == original_a
    assert state.binding_keys([chat_id]) == owners_a


def test_chat_root_alias_keeps_one_state_and_one_catalog(library, monkeypatch, tmp_path, directory_alias):
    from core import config
    from core.plugins.api import PluginAPI

    client, root, db = library
    chat_id = 'fav.jsonl'
    assert catalog.reconcile(root)
    owners = state.binding_keys([chat_id])
    alias = directory_alias(tmp_path / 'alongside', root)
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(alias))
    monkeypatch.setattr(config, 'CHATS_FOLDER', str(alias))
    assert catalog.register_root(alias)[1] == ''

    def read_list():
        response = client.get('/api/chats/list?card_id=a.png').get_json()
        assert response['success'] and response['total'] == 1
        return response

    def check_item(item, notes):
        assert (item['id'], item['notes'], item['favorite'], item['bound_card_count']) == (chat_id, notes, True, 2)

    with monkeypatch.context() as patch:
        def unexpected(*args, **kwargs):
            pytest.fail('hot alias list must not resolve or enumerate the root')
        patch.setattr(catalog, 'physical_root', unexpected)
        patch.setattr(catalog, 'walk_directory_strict', unexpected)
        check_item(read_list()['items'][0], 'notes %_')
    check_item(client.post('/api/chats/detail', json={'id': chat_id}).get_json()['chat'], 'notes %_')
    assert PluginAPI._get_chat(None, chat_id)['notes'] == 'notes %_'
    check_item(client.post('/api/chats/update_meta', json={'id': chat_id, 'notes': 'alias edit'}).get_json()['chat'],
               'alias edit')
    check_item(read_list()['items'][0], 'alias edit')

    verify_root = catalog.physical_root
    with monkeypatch.context() as patch:
        def temporarily_inaccessible(path):
            if catalog.root_key(path) == catalog.root_key(alias):
                raise PermissionError('inaccessible alias')
            return verify_root(path)
        patch.setattr(catalog, 'physical_root', temporarily_inaccessible)
        with pytest.raises(PermissionError, match='inaccessible alias'):
            catalog.reconcile(alias)
        stale = read_list()
        assert stale['index_stale']
        check_item(stale['items'][0], 'alias edit')
        assert not client.post('/api/chats/update_meta', json={'id': chat_id, 'notes': 'wrong'}).get_json()['success']
    assert catalog.reconcile(alias)
    assert not read_list()['index_stale']
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(root))
    check_item(read_list()['items'][0], 'alias edit')
    assert state.binding_keys([chat_id]) == owners
    with closing(state.connect(db)) as conn:
        conn.row_factory = None
        key = catalog.root_key(catalog.physical_root(root))
        assert conn.execute('SELECT root,prefix FROM chat_state_roots').fetchall() == [(key, '')]
        assert conn.execute('SELECT DISTINCT root FROM chat_files').fetchall() == [(key,)]
        assert conn.execute('SELECT key FROM chat_local_state WHERE key LIKE ?', ('%' + chat_id,)).fetchall() == [(chat_id,)]


def test_inaccessible_initial_alias_reserves_legacy_chat_state(library, monkeypatch, tmp_path, directory_alias):
    client, root, _ = library
    alias = tmp_path / 'initial-location'
    with monkeypatch.context() as patch:
        def unexpected(*args, **kwargs):
            pytest.fail('startup must not resolve the configured library')

        patch.setattr(catalog, 'physical_root', unexpected)
        catalog.claim_legacy_root(alias)
    other = tmp_path / 'different-library'
    other.mkdir()
    (other / 'fav.jsonl').write_bytes((root / 'fav.jsonl').read_bytes())
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(other))
    assert catalog.reconcile(other)
    assert client.get('/api/chats/list').get_json()['items'][0]['notes'] == ''
    assert catalog.root_prefix(other)

    directory_alias(alias, root)
    assert catalog.reconcile(alias)
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(alias))
    item = client.get('/api/chats/list?card_id=a.png').get_json()['items'][0]
    assert (item['notes'], item['favorite'], item['bound_card_count']) == ('notes %_', True, 2)
    assert catalog.root_prefix(alias) == catalog.root_prefix(root) == ''


@pytest.mark.parametrize('via_alias', [False, True])
def test_restored_initial_alias_merges_legacy_and_interim_state(library, monkeypatch, tmp_path, directory_alias, via_alias):
    client, root, db = library
    alias = tmp_path / 'initial-location'
    catalog.claim_legacy_root(alias)
    assert catalog.reconcile(root)
    chat, ui = state.Repository('chat'), state.Repository('ui')
    prefix = catalog.root_prefix(root)
    assert prefix
    favorite, other = 'fav.jsonl', 'plain.jsonl'
    chat.update_fields(favorite, {'bookmarks': [{'id': 'legacy', 'floor': 1, 'created_at': 1}]})
    original = chat.get(favorite)
    assert client.get('/api/chats/list?fav_filter=included').get_json()['total'] == 0
    edit = client.post('/api/chats/update_meta', json={
        'id': favorite, 'notes': 'new note', 'bookmarks': [{'id': 'new', 'floor': 2, 'created_at': 2}],
    }).get_json()
    assert edit['success']
    assert client.post('/api/chats/update_meta', json={'id': other, 'notes': 'only interim'}).get_json()['success']
    interim = chat.get(prefix + favorite)
    ui.update_fields('a.png', {'chat_ids': [favorite, prefix + favorite, prefix + other]})
    ui.update_fields('_stale_card_bindings_v1', {'orphan': {'chat_ids': [favorite, prefix + favorite]}})

    directory_alias(alias, root)
    assert catalog.reconcile(alias if via_alias else root)
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(alias))
    assert catalog.root_prefix(alias) == catalog.root_prefix(root) == prefix
    result = client.get('/api/chats/list?fav_filter=included&card_id=a.png').get_json()
    item, = result['items']
    assert (item['id'], item['notes'], item['favorite'], item['last_view_floor'], item['bound_card_count']) == (
        favorite, 'new note', True, 2, 2)
    detail = client.post('/api/chats/detail', json={'id': favorite}).get_json()['chat']
    assert [item['id'] for item in detail['bookmarks']] == ['legacy', 'new']
    assert chat.get(prefix + other)['notes'] == 'only interim'
    assert chat.get(favorite) is None
    assert not state.binding_keys([favorite])
    assert ui.get('a.png')['chat_ids'] == [prefix + favorite, prefix + other]
    assert ui.get('_stale_card_bindings_v1')['orphan']['chat_ids'] == [prefix + favorite]
    with closing(state.connect(db)) as conn:
        assert not conn.execute('SELECT 1 FROM chat_legacy_root_claim').fetchone()
        old, active = conn.execute('SELECT legacy_payload,active_payload FROM chat_root_merge_conflicts').fetchone()
        assert (json.loads(old), json.loads(active)) == (original, interim)
    assert catalog.reconcile(alias)
    assert chat.get(prefix + favorite)['notes'] == 'new note'


@pytest.mark.parametrize('had_interim_values', [False, True])
def test_initial_alias_recovery_keeps_explicit_defaults(library, tmp_path, directory_alias, had_interim_values):
    client, root, db = library
    chat_id = 'fav.jsonl'
    state.Repository('chat').update_fields(chat_id, {'bookmarks': [{'id': 'old', 'floor': 1, 'created_at': 1}]})
    alias = tmp_path / 'initial-location'
    catalog.claim_legacy_root(alias)
    assert catalog.reconcile(root)
    if had_interim_values:
        result = client.post('/api/chats/update_meta', json={
            'id': chat_id, 'notes': 'new notes', 'display_name': 'new name', 'favorite': True,
            'last_view_floor': 1, 'bookmarks': [{'id': 'new', 'floor': 2, 'created_at': 2}],
        }).get_json()
        assert result['success'], result
    cleared = {'notes': '', 'display_name': '', 'favorite': False, 'last_view_floor': 0, 'bookmarks': []}
    result = client.post('/api/chats/update_meta', json={'id': chat_id, **cleared}).get_json()
    assert result['success'], result
    assert {key: result['chat'][key] for key in cleared} == cleared

    directory_alias(alias, root)
    assert catalog.reconcile(root)
    detail = client.post('/api/chats/detail', json={'id': chat_id}).get_json()['chat']
    assert {key: detail[key] for key in cleared} == cleared
    assert detail['bound_card_count'] == 2
    with closing(state.connect(db)) as conn:
        old, active = conn.execute('SELECT legacy_payload,active_payload FROM chat_root_merge_conflicts').fetchone()
        assert json.loads(old)['notes'] == 'notes %_'
        assert {key: json.loads(active)[key] for key in cleared} == cleared


@pytest.mark.parametrize('removed_via_api', [False, True])
def test_initial_alias_recovery_retires_pre_replacement_state(library, monkeypatch, tmp_path, directory_alias,
                                                             removed_via_api):
    client, root, db = library
    chat_id = 'fav.jsonl'
    chat, ui = state.Repository('chat'), state.Repository('ui')
    original = chat.get(chat_id)
    ui.update_fields('_stale_card_bindings_v1', {'old-owner': {'chat_ids': [chat_id]}})
    alias = tmp_path / 'initial-location'
    catalog.claim_legacy_root(alias)
    assert catalog.reconcile(root)
    prefix = catalog.root_prefix(root)
    old = root / chat_id
    if removed_via_api:
        monkeypatch.setattr(chats, 'TRASH_FOLDER', str(tmp_path / 'trash'))
        deleted = client.post('/api/chats/delete', json={'id': chat_id}).get_json()
        assert deleted['success'], deleted
        moved = next((tmp_path / 'trash').rglob('*.jsonl'))
    else:
        moved = old.rename(tmp_path / 'original.jsonl')
    assert catalog.reconcile(root)
    old.write_text('{"chat_metadata":{}}\n{"mes":"new conversation","is_user":true}', encoding='utf-8')
    assert not os.path.samefile(old, moved)
    assert catalog.reconcile(root)
    # The replacement can acquire its own state while the original locator is inaccessible.
    updated = client.post('/api/chats/update_meta', json={'id': chat_id, 'notes': 'replacement note'}).get_json()
    assert updated['success'], updated
    ui.update_fields('a.png', {'chat_ids': [chat_id, prefix + chat_id]})

    directory_alias(alias, root)
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(alias))
    assert catalog.reconcile(alias)
    detail = client.post('/api/chats/detail', json={'id': chat_id}).get_json()['chat']
    assert (detail['preview'], detail['notes'], detail['favorite'], detail['bound_card_count']) == (
        'new conversation', 'replacement note', False, 1)
    assert ui.get('a.png')['chat_ids'] == [prefix + chat_id]
    assert ui.get('_stale_card_bindings_v1')['old-owner']['chat_ids'] == []
    assert chat.get(chat_id) is None
    with closing(state.connect(db)) as conn:
        payload, bindings = conn.execute('SELECT payload,bindings FROM chat_retired_state WHERE chat_id=?',
                                         (chat_id,)).fetchone()
    assert json.loads(payload) == original
    assert set(json.loads(bindings)['owners']) == {'a.png', 'z.png'}
    assert set(json.loads(bindings)['stale']) == {'old-owner'}


@pytest.mark.parametrize('outcome', ['moved', 'returned', 'replaced', 'unbound', 'crash'])
def test_alias_claim_follows_confirmed_file_moves_and_binding_intent(library, monkeypatch, tmp_path, directory_alias,
                                                               outcome):
    client, root, db = library
    source = 'fav.jsonl'
    alias = tmp_path / 'unavailable-location'
    catalog.claim_legacy_root(alias)
    assert catalog.reconcile(root)
    state.Repository('ui').update_fields('_stale_card_bindings_v1', {'old-owner': {'chat_ids': [source]}})

    def bind(chat_id, card_id='', *, unbind=False):
        return client.post('/api/chats/bind', json={'id': chat_id, 'card_id': card_id, 'unbind': unbind}).get_json()

    def read(chat_id):
        return client.post('/api/chats/detail', json={'id': chat_id}).get_json()['chat']

    def replace(chat_id):
        path = root / chat_id
        replacement = path.with_suffix('.tmp')
        replacement.write_text('{"chat_metadata":{}}\n{"mes":"different conversation","is_user":true}',
                               encoding='utf-8')
        if path.exists():
            assert not os.path.samefile(path, replacement)
        replacement.replace(path)

    if outcome == 'unbound':
        reply = bind(source, unbind=True)
        assert reply['success'] and not reply['bound_cards']
        target, expected_owners = source, []
    elif outcome == 'crash':
        # The filesystem move completed but the SQLite publication transaction never committed.
        target, expected_owners = 'Alpha/fav.jsonl', ['a.png', 'z.png']
        (root / 'Alpha').mkdir()
        catalog.move_file(root, source, target)
    else:
        reply = bind(source, 'a.png')
        assert reply['success'] and reply['moved']
        target, expected_owners = reply['id'], ['a.png']
        edit = client.post('/api/chats/update_meta', json={'id': target, 'last_view_floor': 0}).get_json()
        assert edit['success']
        if outcome == 'returned':
            intermediate = target
            monkeypatch.setattr(chats, '_resolve_chat_folder_name', lambda **kwargs: '')
            reply = bind(target, 'z.png')
            assert reply['success'] and reply['id'] == source, reply
            target, expected_owners = reply['id'], ['z.png']
            (root / intermediate).parent.mkdir(exist_ok=True)
            replace(intermediate)
        elif outcome == 'replaced':
            replace(target)
            expected_owners = []
        else:
            rewrite = client.post('/api/chats/save', json={
                'id': target, 'raw_messages': [{'mes': 'edited conversation', 'is_user': True}],
            }).get_json()
            assert rewrite['success'], rewrite
            replace(source)

    directory_alias(alias, root)
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(alias))
    assert catalog.reconcile(alias)
    item = read(target)
    assert [card['card_id'] for card in item['bound_cards']] == expected_owners
    assert item['notes'] == ('' if outcome == 'replaced' else 'notes %_')
    assert item['favorite'] == (outcome != 'replaced')
    assert item['last_view_floor'] == (2 if outcome in ('unbound', 'crash') else 0)
    if outcome in ('moved', 'returned'):
        reused = read(source if outcome == 'moved' else intermediate)
        assert (reused['preview'], reused['notes'], reused['bound_card_count']) == ('different conversation', '', 0)
    if outcome == 'moved':
        assert item['preview'] == 'edited conversation'
    if outcome != 'crash':
        ui = state.Repository('ui')
        assert ui.get('_stale_card_bindings_v1')['old-owner']['chat_ids'] == []
    with closing(state.connect(db)) as conn:
        assert not conn.execute('SELECT 1 FROM chat_legacy_claim_moves').fetchone()
        assert not conn.execute('SELECT 1 FROM chat_legacy_root_claim').fetchone()
        if outcome == 'replaced':
            assert any(json.loads(row[0])['notes'] == 'notes %_' for row in conn.execute(
                "SELECT payload FROM chat_retired_state WHERE revision LIKE 'legacy:%'"))


@pytest.mark.parametrize('outcome', ['returned', 'replaced', 'before-first-scan', 'inaccessible', 'deleted'])
def test_alias_claim_keeps_moved_chat_state_during_temporary_absence(library, monkeypatch, tmp_path,
                                                                    directory_alias, outcome):
    client, root, db = library
    alias, source = tmp_path / 'unavailable-location', 'fav.jsonl'
    catalog.claim_legacy_root(alias)
    assert catalog.reconcile(root)
    prefix = catalog.root_prefix(root)
    result = client.post('/api/chats/bind', json={'id': source, 'card_id': 'a.png'}).get_json()
    assert result['success'] and result['moved'], result
    target = result['id']
    edit = client.post('/api/chats/update_meta', json={'id': target, 'last_view_floor': 3}).get_json()
    assert edit['success']
    expected = catalog.observed_revision(root, target)
    path = root / target
    if outcome == 'deleted':
        trash = tmp_path / 'trash'
        monkeypatch.setattr(chats, 'TRASH_FOLDER', str(trash))
        assert client.post('/api/chats/delete', json={'id': target}).get_json()['success']
        parked = next(trash.rglob('*.jsonl'))
    else:
        parked = path.rename(tmp_path / 'parked.jsonl')

    directory_alias(alias, root)
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(alias))
    if outcome == 'inaccessible':
        observe = catalog.observed_revision

        def inaccessible(root, chat_id):
            if chat_id == target:
                raise PermissionError('inaccessible target')
            return observe(root, chat_id)

        with monkeypatch.context() as patch:
            patch.setattr(catalog, 'observed_revision', inaccessible)
            with pytest.raises(PermissionError, match='inaccessible target'):
                catalog.reconcile(alias)
        with closing(state.connect(db)) as conn:
            assert conn.execute('SELECT 1 FROM chat_legacy_root_claim').fetchone()
            assert conn.execute('SELECT 1 FROM chat_legacy_claim_moves').fetchone()
            assert not conn.execute('SELECT 1 FROM chat_missing_files').fetchone()
            assert not conn.execute('SELECT 1 FROM chat_retired_state').fetchone()

    if outcome == 'before-first-scan':
        assert catalog.register_root(alias)[1] == prefix
        with closing(state.connect(db)) as conn:
            assert conn.execute('SELECT 1 FROM chat_files WHERE chat_id=?', (target,)).fetchone()
    else:
        assert catalog.reconcile(alias)
        ids = [item['id'] for item in client.get('/api/chats/list').get_json()['items']]
        assert target not in ids

    with closing(state.connect(db)) as conn:
        assert not conn.execute('SELECT 1 FROM chat_legacy_root_claim').fetchone()
        missing = conn.execute('SELECT revision FROM chat_missing_files WHERE chat_id=?', (target,)).fetchone()
        assert (missing[0] if missing else None) == (None if outcome == 'deleted' else expected)
        if outcome != 'deleted':
            assert not conn.execute('SELECT 1 FROM chat_retired_state').fetchone()

    birth_time = catalog._birthtime_ns(parked.stat())
    if outcome == 'replaced':
        path.write_text('{"chat_metadata":{}}\n{"mes":"different conversation","is_user":true}', encoding='utf-8')
        assert not os.path.samefile(parked, path)
        assert client.post('/api/chats/update_meta', json={'id': target, 'notes': 'unsafe'}).status_code == 409
    else:
        if outcome == 'returned' and birth_time:
            with parked.open('a', encoding='utf-8') as stream:
                stream.write('\n{"mes":"added while parked","is_user":true}')
        path.parent.mkdir(exist_ok=True)
        parked.rename(path)

    if outcome == 'before-first-scan':
        catalog._apply_events(alias, [str(alias / target)])
        assert not catalog.needs_reidentify(root, target)
    for _ in range(2):
        assert catalog.reconcile(alias)
        detail = client.post('/api/chats/detail', json={'id': target}).get_json()['chat']
        if outcome in ('replaced', 'deleted'):
            assert (detail['notes'], detail['favorite'], detail['last_view_floor'], detail['bound_cards']) == (
                '', False, 0, [])
        else:
            assert (detail['notes'], detail['favorite'], detail['last_view_floor']) == ('notes %_', True, 3)
            assert [card['card_id'] for card in detail['bound_cards']] == ['a.png']
            if outcome == 'returned' and birth_time:
                assert detail['message_count'] == 3
    with closing(state.connect(db)) as conn:
        assert not conn.execute('SELECT 1 FROM chat_missing_files WHERE chat_id=?', (target,)).fetchone()
        if outcome == 'replaced':
            payload, bindings = conn.execute('SELECT payload,bindings FROM chat_retired_state WHERE chat_id=?',
                                             (target,)).fetchone()
            assert json.loads(payload)['notes'] == 'notes %_'
            assert json.loads(payload)['last_view_floor'] == 3
            assert set(json.loads(bindings)['owners']) == {'a.png'}


@pytest.mark.parametrize('via_alias', [False, True])
def test_initial_claim_is_rechecked_after_waiting_for_write_lock(library, monkeypatch, tmp_path, directory_alias,
                                                              via_alias):
    client, intended, db = library
    chat_id = 'fav.jsonl'
    unrelated = tmp_path / 'unrelated-library'
    unrelated.mkdir()
    (unrelated / chat_id).write_bytes((intended / chat_id).read_bytes())
    alias = tmp_path / 'initial-location'
    catalog.claim_legacy_root(alias)
    assert catalog.reconcile(intended) and catalog.reconcile(unrelated)
    directory_alias(alias, unrelated)
    seen = threading.Event()
    resolve = catalog.physical_root

    def observe(path):
        physical = resolve(path)
        if catalog.root_key(path) == catalog.root_key(alias) and os.path.samefile(physical, unrelated):
            seen.set()
        return physical

    monkeypatch.setattr(catalog, 'physical_root', observe)
    with ThreadPoolExecutor(max_workers=1) as worker:
        with catalog._writes:
            pending = worker.submit(catalog.register_root, alias if via_alias else unrelated)
            assert seen.wait(5)
            if os.name == 'nt':
                alias.rmdir()
            else:
                alias.unlink()
            directory_alias(alias, intended)
        physical, _ = pending.result(timeout=5)
    assert os.path.samefile(physical, intended if via_alias else unrelated)
    if not via_alias:
        with closing(state.connect(db)) as conn:
            assert conn.execute('SELECT root FROM chat_legacy_root_claim').fetchone()[0] == catalog.root_key(alias)
    assert catalog.reconcile(alias)
    for configured, expected in ((alias, ('notes %_', True, 2)), (unrelated, ('', False, 0))):
        monkeypatch.setattr(chats, 'CHATS_FOLDER', str(configured))
        result = client.post('/api/chats/detail', json={'id': chat_id}).get_json()
        assert result['success'], result
        item = result['chat']
        assert (item['notes'], item['favorite'], item['bound_card_count']) == expected


def test_retargeted_chat_root_alias_cannot_commit_to_original_library(library, monkeypatch, tmp_path, directory_alias):
    client, original, _ = library
    chat_id = 'fav.jsonl'
    assert catalog.reconcile(original)
    second = tmp_path / 'second-library'
    second.mkdir()
    (second / chat_id).write_bytes((original / chat_id).read_bytes())
    alias = directory_alias(tmp_path / 'configured-location', original)
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(alias))
    assert catalog.reconcile(alias)
    previous = state.Repository('chat').get(chat_id)
    save = chats.save_chat_data

    def retarget(snapshot, **kwargs):
        if os.name == 'nt':
            os.rmdir(alias)
        else:
            alias.unlink()
        directory_alias(alias, second)
        return save(snapshot, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(chats, 'save_chat_data', retarget)
        update = client.post('/api/chats/update_meta', json={'id': chat_id, 'notes': 'cross-root edit'}).get_json()
        assert not update['success']
    assert state.Repository('chat').get(chat_id) == previous
    assert catalog.reconcile(alias)
    item = client.get('/api/chats/list').get_json()['items'][0]
    assert (item['notes'], item['favorite'], item['bound_card_count']) == ('', False, 0)
    assert catalog.root_prefix(alias) == catalog.root_prefix(second) != catalog.root_prefix(original)


def test_chat_edited_outside_root_retains_state_when_same_file_returns(library, tmp_path):
    client, root, _ = library
    catalog.reconcile(root)
    target = root / 'fav.jsonl'
    if not catalog._birthtime_ns(target.stat()):
        pytest.skip('filesystem does not expose creation time to distinguish reused inodes')
    original = state.Repository('chat').get('fav.jsonl')
    owners = state.binding_keys(['fav.jsonl'])
    moved = target.rename(tmp_path / 'paused.jsonl')
    catalog.reconcile(root)
    with moved.open('a', encoding='utf-8') as stream:
        stream.write('\n{"mes":"added while moved","is_user":true}')
    moved.rename(target)
    catalog.reconcile(root)
    item = client.get('/api/chats/list?card_id=a.png').get_json()['items'][0]
    assert (item['id'], item['notes'], item['favorite'], item['message_count']) == ('fav.jsonl', 'notes %_', True, 3)
    page = client.post('/api/chats/range', json={'id': 'fav.jsonl'}).get_json()['range']
    assert page['raw_messages'][-1]['mes'] == 'added while moved'
    assert state.Repository('chat').get('fav.jsonl') == original
    assert state.binding_keys(['fav.jsonl']) == owners


def test_chat_metadata_cannot_commit_to_old_path_after_a_move(library, monkeypatch):
    client, root, _ = library
    catalog.reconcile(root)
    original = state.Repository('chat').get('fav.jsonl')
    save = chats.save_chat_data

    def race(snapshot, **kwargs):
        result = client.post('/api/chats/bind', json={'id': 'fav.jsonl', 'card_id': 'a.png'}).get_json()
        assert result['success'] and result['moved'], result
        return save(snapshot, **kwargs)

    monkeypatch.setattr(chats, 'save_chat_data', race)
    response = client.post('/api/chats/update_meta', json={'id': 'fav.jsonl', 'notes': 'stale'}).get_json()
    assert not response['success']
    assert state.Repository('chat').get('fav.jsonl') is None
    assert state.Repository('chat').get('Alpha/fav.jsonl')['notes'] == original['notes']


def test_plugin_chat_reads_combine_authoritative_state_with_latest_file_facts(library, monkeypatch):
    from core import config
    from core.plugins.api import PluginAPI

    _, root, _ = library
    monkeypatch.setattr(config, 'CHATS_FOLDER', str(root))
    catalog.reconcile(root)
    (root / 'fav.jsonl').write_text('{"chat_metadata":{}}\n{"mes":"latest","is_user":true}', encoding='utf-8')
    catalog.reconcile(root)
    # These domain methods do not require a running plugin host.
    for item in (PluginAPI._get_chat(None, 'fav.jsonl'),
                 next(row for row in PluginAPI._list_chats(None) if row['id'] == 'fav.jsonl')):
        assert (item['preview'], item['message_count'], item['notes'], item['favorite']) == (
            'latest', 1, 'notes %_', True)


def test_restart_rolls_back_chat_move_transaction_and_recovers_once(library):
    _, root, db = library
    catalog.reconcile(root)
    source, target = 'fav.jsonl', 'Alpha/fav.jsonl'
    original = state.Repository('chat').get(source)
    driver = '''
import os
import sys
import threading
from types import SimpleNamespace

from flask import Flask
from core.api.v1 import chats
from core.data import local_state_repository as state
from core.services import chat_catalog_service as catalog

root, db, phase = sys.argv[1:]
state.DEFAULT_DB_PATH = db
chats.CHATS_FOLDER = root
chats.ctx.cache = SimpleNamespace(id_map={
    'a.png': dict(char_name='Alpha', card_uid='96b71299-c1d3-4337-b78a-1b23d1d05375'),
    'z.png': dict(char_name='Zeta'),
}, bundle_map={}, lock=threading.RLock())
if phase == 'recover':
    assert catalog.reconcile(root)
else:
    original = catalog._apply_recovered_move
    def exit_after_writing(conn, *args):
        original(conn, *args)
        os._exit(73)
    catalog._apply_recovered_move = exit_after_writing
    app = Flask(__name__)
    app.register_blueprint(chats.bp)
    response = app.test_client().post('/api/chats/bind', json={'id': 'fav.jsonl', 'card_id': 'a.png'})
    raise RuntimeError(response.get_json())
'''
    args = [sys.executable, '-X', 'utf8', '-c', driver, str(root), str(db)]
    result = subprocess.run([*args, 'exit'], capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 73, (result.stdout, result.stderr)
    assert not (root / source).exists() and (root / target).is_file()
    assert state.Repository('chat').get(source) == original
    assert state.Repository('chat').get(target) is None
    for _ in range(2):
        result = subprocess.run([*args, 'recover'], capture_output=True, text=True, encoding='utf-8', timeout=30)
        assert result.returncode == 0, (result.stdout, result.stderr)
    assert state.Repository('chat').get(source) is None
    assert state.Repository('chat').get(target) == original
    assert state.binding_keys([source, target]) == [('a.png', target), ('z.png', target)]
    with closing(state.connect(db)) as conn:
        assert not conn.execute('SELECT 1 FROM chat_file_moves').fetchone()
