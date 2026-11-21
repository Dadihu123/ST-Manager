"""Real file/plugin/index regressions for synchronous card-save side effects."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
from unittest.mock import Mock

from PIL import Image
import pytest

from core.api.v1 import cards
from core.data import db_session, ui_store
from core.plugins import api as plugin_api, hooks, job_store
from core.plugins.api import PluginAPI
from core.plugins.manifest import PluginManifest
from core.services import card_service, index_build_service, index_job_worker
from core.services import wi_entry_history_service as history
from core.utils.image import extract_card_info, write_card_metadata
from core.utils.source_revision import build_file_source_revision
from tests.plugins_test_support import write_plugin
from test_daily_performance import library
from test_detail_modal_advanced_editor_contracts import run_detail_modal_runtime_check

REAL_ENQUEUE_INDEX_JOB = index_job_worker.enqueue_index_job


@pytest.fixture
def isolated_library(library, monkeypatch, tmp_path):
    client, root, db, cache, jobs = library
    cfg = {'world_info_dir': str(tmp_path / 'lorebooks'),
           'resources_dir': str(tmp_path / 'resources'), 'cards_dir': str(root)}
    for path in (cfg['world_info_dir'], cfg['resources_dir']):
        Path(path).mkdir()
    for module in (db_session, card_service, history, index_job_worker, job_store):
        monkeypatch.setattr(module, 'DEFAULT_DB_PATH', str(db))
    for module in (plugin_api, history):
        monkeypatch.setattr(module, 'CARDS_FOLDER', str(root))
    for module in (cards, plugin_api, index_build_service, history):
        monkeypatch.setattr(module, 'load_config', lambda: cfg)
    monkeypatch.setattr(index_job_worker, 'enqueue_index_job', jobs)
    client.application.teardown_appcontext(db_session.close_connection)
    # Fail closed if any path overlooked above tries to open a database outside this fixture.
    connect = sqlite3.connect

    def isolated_connect(path, *args, **kwargs):
        assert Path(path).resolve().is_relative_to(tmp_path.resolve()), path
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', isolated_connect)
    return client, root, db, cache, jobs, cfg


def write_png(path, book=None):
    data = {'name': 'Hero', 'description': 'before-hook', 'creator': 'before-author',
            'tags': ['sample'], 'extensions': {'unknown': {'keep': True}}}
    if book:
        data['character_book'] = {'name': book, 'entries': [
            {'uid': 1, 'keys': ['key'], 'content': book + '-content'},
        ]}
    Image.new('RGB', (8, 8), 'blue').save(path)
    assert write_card_metadata(str(path), {'spec': 'chara_card_v3', 'spec_version': '3.0', 'data': data})


@pytest.mark.parametrize('old_book', ['OldBook', None])
@pytest.mark.parametrize('cold', [False, True])
def test_nonleader_shared_binding_reconciles_matching_owner_files(isolated_library, old_book, cold):
    client, root, db, cache, jobs, cfg = isolated_library
    books = {'bundle/main.png': 'MainBook', 'bundle/old.png': old_book}
    before = {}
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("UPDATE index_build_state SET active_generation=1, state='ready' WHERE scope='worldinfo'")
        for card_id, book in books.items():
            write_png(root / card_id, book)
            before[card_id] = (root / card_id).read_bytes(), (root / card_id).stat().st_mtime_ns
            conn.execute('UPDATE card_metadata SET has_character_book=?, character_book_name=? WHERE id=?',
                         (int(bool(book)), book or '', card_id))
        conn.commit()
        for folder in ('shared', 'new-shared'):
            path = Path(cfg['resources_dir']) / folder / 'lorebooks' / (folder + '.json')
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'name': folder, 'entries': {}}), encoding='utf-8')
        for card_id in books:
            assert index_build_service.apply_worldinfo_owner_increment(conn, card_id, str(root / card_id))
    if cold:
        cache.id_map.clear()
        cache.bundle_map.clear()
    response = client.post('/api/update_card', json={
        'id': 'bundle/old.png', 'ui_only': True, 'save_ui_to_bundle': True, 'bundle_dir': 'bundle',
        'version_id': 'bundle/old.png', 'ui_only_fields': ['resource_folder'], 'resource_folder': 'new-shared',
    }).get_json()
    assert response['success'], response
    owner_jobs = [call.kwargs for call in jobs.call_args_list if call.args[0] == 'upsert_world_owner']
    assert {job['entity_id'] for job in owner_jobs} == set(books)
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        for job in owner_jobs:
            assert job['source_path'] == str(root / job['entity_id'])
            assert index_build_service.apply_worldinfo_owner_increment(conn, job['entity_id'], job['source_path'])
        for card_id, book in books.items():
            row = conn.execute('SELECT name,source_path FROM index_entities_v2 WHERE entity_id=?',
                               ('world::embedded::' + card_id,)).fetchone()
            if book:
                assert (row['name'], row['source_path']) == (book, str(root / card_id))
                content = conn.execute('SELECT content FROM index_search_full_v2 WHERE entity_id=?',
                                       ('world::embedded::' + card_id,)).fetchone()[0]
                other_book = 'OldBook' if book == 'MainBook' else 'MainBook'
                assert book + '-content' in content and other_book + '-content' not in content
            else:
                assert row is None
            resources = conn.execute("SELECT name FROM index_entities_v2 WHERE owner_entity_id=? AND entity_type='world_resource'",
                                     ('card::' + card_id,)).fetchall()
            assert [row[0] for row in resources] == ['new-shared']
            assert ((root / card_id).read_bytes(), (root / card_id).stat().st_mtime_ns) == before[card_id]


@pytest.mark.parametrize('card_id', ['hero.png', 'bundle/main.png', 'bundle/old.png'])
@pytest.mark.parametrize('continued_input', [False, True])
def test_sync_plugin_body_survives_next_frontend_save(isolated_library, tmp_path, card_id, continued_input):
    client, root, _db, _cache, _jobs, _cfg = isolated_library
    write_png(root / card_id)
    api = PluginAPI(PluginManifest.load(write_plugin(tmp_path, 'save-side-effect')))
    called = []

    def update_from_plugin(payload):
        called.append(payload)
        if len(called) == 1:
            assert api.cards.write_fields(card_id, {'description': 'written-by-synchronous-hook',
                                                   'creator': 'hook-author', 'tags': ['hook-tag']})

    api.on('card.updated', update_from_plugin)
    try:
        revision = build_file_source_revision(str(root / card_id))
        response = client.post('/api/update_card', json={
            'id': card_id, 'ui_only': True, 'ui_only_fields': ['ui_summary'],
            'ui_summary': 'new note', 'source_revision': revision,
        }).get_json()
        assert response['success'], response
        assert response['canonical_body'] and response['file_modified']
        assert response['canonical_fields_id'] == card_id
        assert response['canonical_fields']['description'] == 'written-by-synchronous-hook'
        assert response['canonical_ui']['source_revision'] == build_file_source_revision(str(root / card_id))
        assert response['canonical_ui']['source_revision'] != revision
        captured = tmp_path / 'next_payload.json'
        # Execute the actual field-draft and detail component, with the real cleaner.
        setup = {'id': card_id, 'filename': os.path.basename(card_id), 'char_name': 'Hero',
                 'description': 'before-hook', 'creator': 'before-author', 'tags': ['sample'],
                 'source_link': 'keep', 'resource_folder': 'assets', 'ui_summary': 'original',
                 'source_revision': revision, 'extensions': {'unknown': {'keep': True}}}
        run_detail_modal_runtime_check('const initial = ' + json.dumps(setup) + ';\n'
            + 'const response = ' + json.dumps(response) + ';\n'
            + 'const payloadPath = ' + json.dumps(str(captured)) + ';\n'
            + 'const continuedInput = ' + json.dumps(continued_input) + ';\n' + """
const {writeFileSync} = await import('node:fs');
const cleaner = await import('data:text/javascript,' + encodeURIComponent(readFileSync('static/js/utils/data.js', 'utf8')));
globalThis.__getCleanedV3Data = cleaner.getCleanedV3Data;
modal.$store = {global: {showToast() {}, setTagTaxonomy() {}}};
modal.activeCard = initial.id.startsWith('bundle/')
  ? {id: 'bundle/main.png', filename: 'main.png', is_bundle: true, bundle_dir: 'bundle'}
  : {id: initial.id, filename: initial.filename, is_bundle: false};
modal.editingData = modal._normalizeEditingDataShape(initial);
modal.originalDataJson = JSON.stringify(modal.editingData);
let refreshes = 0;
modal.refreshActiveCardDetail = () => { refreshes++; };
let persisted;
globalThis.__rebaseBaseline = (_data, fields, values) => { persisted = {fields, values}; };
let finish;
globalThis.__updateCard = () => new Promise(resolve => { finish = resolve; });
modal.editingData.ui_summary = 'new note';
const saving = modal.saveChanges();
if (continuedInput) {
  modal.editingData.creator = 'new author draft';
  modal.editingData.character_book_raw = 'unfinished raw editor draft';
}
finish(response);
if (!(await saving)) throw new Error('save failed');
if (modal.editingData.description !== 'written-by-synchronous-hook') throw new Error('plugin body not absorbed');
if (modal.editingData.tags[0] !== 'hook-tag') throw new Error('plugin tags not absorbed');
if (continuedInput) {
  if (modal.editingData.creator !== 'new author draft' || !modal.hasUnsavedChanges) throw new Error('new input lost');
  modal.editingData.creator = 'hook-author';
}
if (modal.hasUnsavedChanges || refreshes) throw new Error('canonical body must establish baseline without a detail request');
if (continuedInput && modal.editingData.character_book_raw !== 'unfinished raw editor draft') {
  throw new Error('new raw editor input must survive canonical response');
}
if (!continuedInput && (!persisted.fields.includes('character_book_raw') || persisted.values.character_book_raw !== '')) {
  throw new Error('raw editor reset must update the snapshot baseline as well');
}
modal.editingData.personality = 'next user edit';
globalThis.__updateCard = async payload => { writeFileSync(payloadPath, JSON.stringify(payload)); return {success: false}; };
await modal.saveChanges();
""")
        next_payload = json.loads(captured.read_text())
        assert next_payload['description'] == 'written-by-synchronous-hook'
        assert next_payload['source_revision'] == response['canonical_ui']['source_revision']
        saved = client.post('/api/update_card', json=next_payload)
        assert saved.status_code == 200 and saved.get_json()['success'], saved.get_json()
        body = extract_card_info(str(root / card_id))['data']
        assert body['description'] == 'written-by-synchronous-hook'
        assert body['creator'] == 'hook-author' and body['tags'] == ['hook-tag']
        assert body['personality'] == 'next user edit'
        assert body['extensions']['unknown'] == {'keep': True}
    finally:
        hooks.unregister('card.updated', update_from_plugin)


@pytest.mark.parametrize('read_failure', [False, True])
def test_hook_write_then_raise_never_pairs_old_body_with_new_revision(isolated_library, monkeypatch, tmp_path, read_failure):
    client, root, _db, _cache, _jobs, _cfg = isolated_library
    card_path = root / 'hero.png'
    write_png(card_path)
    revision = build_file_source_revision(str(card_path))
    api = PluginAPI(PluginManifest.load(write_plugin(tmp_path, 'partial-hook')))

    def partial_hook(_payload):
        assert api.cards.write_fields('hero.png', {'description': 'committed-before-hook-error'})
        raise RuntimeError('handler failed after its write')

    api.on('card.updated', partial_hook)
    try:
        if read_failure:
            monkeypatch.setattr(cards, 'extract_card_info', lambda _path: None)
        response = client.post('/api/update_card', json={
            'id': 'hero.png', 'ui_only': True, 'ui_summary': 'new note', 'source_revision': revision,
        }).get_json()
        assert extract_card_info(str(card_path))['data']['description'] == 'committed-before-hook-error'
        if read_failure:
            assert not response['success'] and response['detail_reload_required'] and response['ui_data_saved']
            assert 'canonical_ui' not in response and 'updated_card' not in response
        else:
            assert response['success'] and response['canonical_body']
            assert response['canonical_fields']['description'] == 'committed-before-hook-error'
            assert response['canonical_ui']['source_revision'] != revision
    finally:
        hooks.unregister('card.updated', partial_hook)


@pytest.mark.parametrize('card_id', ['hero.png', 'bundle/main.png', 'bundle/old.png'])
@pytest.mark.parametrize('save_kind', ['note', 'resource_folder', 'body'])
@pytest.mark.parametrize('continued_input', [False, True])
def test_sync_plugin_note_survives_next_frontend_save(
        isolated_library, monkeypatch, tmp_path, card_id, save_kind, continued_input):
    client, root, _db, cache, _jobs, _cfg = isolated_library
    path = root / card_id
    write_png(path)
    before = path.read_bytes(), path.stat().st_mtime_ns
    revision = build_file_source_revision(str(path))
    is_bundle = card_id.startswith('bundle/')
    stored = ui_store.load_ui_data()
    initial_ui = (ui_store.get_version_remark(stored, 'bundle', card_id, 'bundle/main.png')
                  if is_bundle else stored[card_id])
    api = PluginAPI(PluginManifest.load(write_plugin(tmp_path, 'note-side-effect')))
    called = []

    def write_note_from_plugin(payload):
        called.append(payload)
        if len(called) == 1:
            assert api.cards.write_note(card_id, 'note-written-by-sync-hook')

    api.on('card.updated', write_note_from_plugin)
    try:
        payload = {'id': card_id, 'source_revision': revision,
                   'ui_summary': 'user-note' if save_kind == 'note' else initial_ui['summary']}
        if is_bundle:
            payload.update(save_ui_to_bundle=True, bundle_dir='bundle', version_id=card_id)
        if save_kind == 'body':
            payload.update(description='before-hook', personality='submitted body', char_name='Hero')
        else:
            field = 'ui_summary' if save_kind == 'note' else 'resource_folder'
            payload.update(ui_only=True, ui_only_fields=[field])
            if save_kind == 'resource_folder':
                payload['resource_folder'] = 'changed-assets'
        with monkeypatch.context() as patch:
            forbidden = Mock(side_effect=AssertionError('UI reconciliation must not read or write card content'))
            if save_kind != 'body':
                for module in (cards, card_service):
                    for name in ('extract_card_info', 'write_card_metadata', 'calculate_token_count',
                                 'get_file_hash_and_size', 'update_card_cache'):
                        patch.setattr(module, name, forbidden)
                patch.setattr(cache, '_rebuild_global_tags_locked', forbidden)
            response = client.post('/api/update_card', json=payload).get_json()
            forbidden.assert_not_called()
        assert response['success'], response
        assert response['canonical_ui']['id'] == card_id
        assert response['canonical_ui']['ui_summary'] == 'note-written-by-sync-hook'
        assert not response['canonical_body']
        leader_note = 'note-written-by-sync-hook' if response['new_id'] == card_id else 'original'
        assert response['updated_card']['ui_summary'] == leader_note
        assert cache.id_map[response['new_id']]['ui_summary'] == leader_note
        if is_bundle:
            version = next(item for item in cache.id_map[response['new_id']]['versions'] if item['id'] == card_id)
            assert version['ui_summary'] == 'note-written-by-sync-hook'
        if save_kind != 'body':
            assert (path.read_bytes(), path.stat().st_mtime_ns) == before
            assert response['canonical_ui']['source_revision'] == revision
        captured = tmp_path / 'next_note_payload.json'
        initial = {'id': card_id, 'filename': path.name, 'char_name': 'Hero',
                   'description': 'before-hook', 'creator': 'before-author', 'tags': ['sample'],
                   'ui_summary': initial_ui['summary'], 'source_link': initial_ui['link'],
                   'resource_folder': initial_ui['resource_folder'], 'source_revision': revision}
        run_detail_modal_runtime_check('const initial = ' + json.dumps(initial) + ';\n'
            + 'const response = ' + json.dumps(response) + ';\n'
            + 'const payloadPath = ' + json.dumps(str(captured)) + ';\n'
            + 'const continuedInput = ' + json.dumps(continued_input) + ';\n'
            + 'const saveKind = ' + json.dumps(save_kind) + ';\n' + """
const {writeFileSync} = await import('node:fs');
const cleaner = await import('data:text/javascript,' + encodeURIComponent(readFileSync('static/js/utils/data.js', 'utf8')));
globalThis.__getCleanedV3Data = cleaner.getCleanedV3Data;
modal.$store = {global: {showToast() {}, setTagTaxonomy() {}}};
modal.activeCard = initial.id.startsWith('bundle/')
  ? {id: 'bundle/main.png', filename: 'main.png', is_bundle: true, bundle_dir: 'bundle'}
  : {id: initial.id, filename: initial.filename, is_bundle: false};
modal.editingData = modal._normalizeEditingDataShape(initial);
modal.originalDataJson = JSON.stringify(modal.editingData);
let refreshes = 0;
modal.refreshActiveCardDetail = () => { refreshes++; };
let persisted;
globalThis.__rebaseBaseline = (_data, fields, values) => { persisted = {fields, values}; };
let finish;
globalThis.__updateCard = () => new Promise(resolve => { finish = resolve; });
if (saveKind === 'note') modal.editingData.ui_summary = 'user-note';
else if (saveKind === 'body') modal.editingData.personality = 'submitted body';
else modal.editingData.resource_folder = 'changed-assets';
const saving = modal.saveChanges();
if (continuedInput) modal.editingData.ui_summary = 'newer note draft';
finish(response);
if (!(await saving)) throw new Error('save failed');
if (modal.editingData.ui_summary !== (continuedInput ? 'newer note draft' : 'note-written-by-sync-hook')) {
  throw new Error('final note was not absorbed or newer draft was lost');
}
if (!persisted.fields.includes('ui_summary') || persisted.values.ui_summary !== 'note-written-by-sync-hook') {
  throw new Error('snapshot baseline omitted the hook note');
}
if (continuedInput) {
  if (!modal.hasUnsavedChanges) throw new Error('newer input must stay dirty');
  modal.editingData.ui_summary = 'note-written-by-sync-hook';
}
if (modal.hasUnsavedChanges) throw new Error('reverting to final hook note must clear dirty state');
if (refreshes !== (saveKind === 'body' && !continuedInput ? 1 : 0)) throw new Error('unnecessary detail refresh');
modal.editingData.scenario = 'next body edit';
globalThis.__updateCard = async payload => { writeFileSync(payloadPath, JSON.stringify(payload)); return {success: false}; };
await modal.saveChanges();
""")
        next_payload = json.loads(captured.read_text())
        assert next_payload['ui_summary'] == 'note-written-by-sync-hook'
        saved = client.post('/api/update_card', json=next_payload)
        assert saved.status_code == 200 and saved.get_json()['success'], saved.get_json()
        assert api.cards.read_note(card_id) == 'note-written-by-sync-hook'
        assert extract_card_info(str(path))['data']['scenario'] == 'next body edit'
    finally:
        hooks.unregister('card.updated', write_note_from_plugin)


@pytest.mark.parametrize('editing_id,hook_id', [
    ('bundle/old.png', 'bundle/main.png'), ('bundle/main.png', 'bundle/old.png'),
    ('bundle/old.png', 'hero.png'),
])
@pytest.mark.parametrize('hook_note', ['', 'note-from-hook'])
def test_hook_notes_reconcile_only_their_bundle_versions(isolated_library, tmp_path, editing_id, hook_id, hook_note):
    client, root, _db, cache, _jobs, _cfg = isolated_library
    for card_id in {editing_id, hook_id}:
        write_png(root / card_id)
    api = PluginAPI(PluginManifest.load(write_plugin(tmp_path, 'cross-version-note')))

    def partial_hook(_payload):
        assert api.cards.write_note(hook_id, hook_note)
        raise RuntimeError('hook failed after persisting its note')

    api.on('card.updated', partial_hook)
    try:
        response = client.post('/api/update_card', json={
            'id': editing_id, 'ui_only': True, 'ui_summary': 'submitted-note',
            'ui_only_fields': ['ui_summary'],
        }).get_json()
        assert response['success'], response
        assert response['canonical_ui']['id'] == editing_id
        assert response['canonical_ui']['ui_summary'] == 'submitted-note'
        expected_leader = (hook_note if hook_id == 'bundle/main.png'
                           else 'submitted-note' if editing_id == 'bundle/main.png' else 'original')
        assert response['updated_card']['ui_summary'] == expected_leader
        cached = cache.id_map['bundle/main.png']
        assert cached['ui_summary'] == expected_leader
        version_notes = {item['id']: item['ui_summary'] for item in cached['versions']}
        assert version_notes[editing_id] == 'submitted-note'
        if hook_id.startswith('bundle/'):
            assert version_notes[hook_id] == hook_note
        assert api.cards.read_note(hook_id) == hook_note
        stored = ui_store.load_ui_data()
        assert stored['bundle']['_version_remarks']['bundle/old.png']['extension'] is True
        assert stored['hero.png']['unknown'] == [1]
    finally:
        hooks.unregister('card.updated', partial_hook)


@pytest.mark.parametrize('failure', ['read', 'degraded', 'stat'])
def test_hook_ui_read_failure_never_establishes_a_stale_save_baseline(
        isolated_library, monkeypatch, tmp_path, failure):
    client, root, _db, cache, _jobs, _cfg = isolated_library
    write_png(root / 'hero.png')
    api = PluginAPI(PluginManifest.load(write_plugin(tmp_path, 'unreadable-hook-note')))

    def fail(*_args, **_kwargs):
        raise ui_store.UiDataLoadError('injected post-hook UI read failure')

    def write_then_block_read(_payload):
        assert api.cards.write_note('hero.png', 'committed-hook-note')
        if failure == 'stat':
            monkeypatch.setattr(cards, 'get_ui_data_revision', Mock(side_effect=PermissionError('injected stat failure')))
        elif failure == 'read':
            monkeypatch.setattr(cards, 'load_ui_data', fail)
        else:
            # 新权威库不可读时不能退回迁移快照。
            from core.data import local_state_repository as state
            reader = state.Repository.get_many
            def deny_primary(self, keys=None, **kwargs):
                if self.component == 'ui':
                    raise state.LocalStateError('injected authoritative read failure')
                return reader(self, keys, **kwargs)
            monkeypatch.setattr(state.Repository, 'get_many', deny_primary)

    api.on('card.updated', write_then_block_read)
    try:
        response = client.post('/api/update_card', json={
            'id': 'hero.png', 'ui_only': True, 'ui_summary': 'user-note',
            'ui_only_fields': ['ui_summary'],
        }).get_json()
        assert not response['success'] and response['ui_data_saved'] and response['detail_reload_required']
        assert not response['file_modified']
        assert 'canonical_ui' not in response and 'updated_card' not in response
        assert cache.id_map['hero.png']['ui_summary'] == 'user-note'
        from core.data import local_state_repository as state
        with sqlite3.connect(state.DEFAULT_DB_PATH) as saved:
            assert json.loads(saved.execute("SELECT payload_json FROM ui_records WHERE key='hero.png'").fetchone()[0])['summary'] == 'committed-hook-note'
    finally:
        hooks.unregister('card.updated', write_then_block_read)
        ui_store._clear_ui_data_degraded()


def test_transient_pre_hook_stat_failure_revalidates_final_ui(isolated_library, monkeypatch, tmp_path):
    client, root, _db, _cache, _jobs, _cfg = isolated_library
    write_png(root / 'hero.png')
    api = PluginAPI(PluginManifest.load(write_plugin(tmp_path, 'transient-ui-stat')))
    revision = cards.get_ui_data_revision
    calls = []

    def stat_once_unavailable(*args):
        calls.append(True)
        if len(calls) == 1:
            raise PermissionError('transient stat failure')
        return revision(*args)

    monkeypatch.setattr(cards, 'get_ui_data_revision', stat_once_unavailable)

    def hook(_payload):
        assert api.cards.write_note('hero.png', '')

    api.on('card.updated', hook)
    try:
        response = client.post('/api/update_card', json={
            'id': 'hero.png', 'ui_only': True, 'ui_summary': 'user-note',
        }).get_json()
        assert response['success'], response
        assert response['canonical_ui']['ui_summary'] == response['updated_card']['ui_summary'] == ''
    finally:
        hooks.unregister('card.updated', hook)


@pytest.mark.parametrize('failure', ['ui', 'metadata', 'index'])
def test_body_save_failure_reports_committed_parts_and_preserves_actual_file(isolated_library, monkeypatch, failure):
    client, root, db, cache, jobs, cfg = isolated_library
    path = root / 'hero.png'
    write_png(path)
    if failure == 'ui':
        monkeypatch.setattr(cards, 'save_ui_data', lambda *_args, **_kwargs: False)
    elif failure == 'metadata':
        monkeypatch.setattr(cards, 'update_card_cache', lambda *_args, **_kwargs: {'cache_updated': False})
    else:
        def fail_index(*_args, **_kwargs):
            raise OSError('injected index commit failure')
        monkeypatch.setattr(cards, '_apply_card_index_increment_now', fail_index)
    result = client.post('/api/update_card', json={'id': 'hero.png', 'char_name': 'Hero',
        'description': 'actually committed body', 'ui_summary': 'submitted note',
        'source_revision': build_file_source_revision(str(path))}).get_json()
    assert not result['success'], result
    assert result['file_modified'] and result['index_sync_pending'] and result['retryable']
    assert result['ui_data_saved'] == (failure != 'ui')
    assert extract_card_info(str(path))['data']['description'] == 'actually committed body'
    if failure == 'ui':
        assert ui_store.load_ui_data()['hero.png']['summary'] == 'original'



def test_writer_failure_after_replacement_reports_actual_file_commit(isolated_library, monkeypatch):
    client, root, db, cache, jobs, cfg = isolated_library
    path = root / 'hero.png'
    write_png(path)
    def replaced_then_failed(target, info):
        assert write_card_metadata(target, info)
        return False  # e.g. post-replacement directory fsync failure
    monkeypatch.setattr(cards, 'write_card_metadata', replaced_then_failed)
    result = client.post('/api/update_card', json={'id': 'hero.png', 'char_name': 'Hero',
        'description': 'already replaced', 'source_revision': build_file_source_revision(str(path))}).get_json()
    assert not result['success'] and result['file_modified'] and result['index_sync_pending']
    assert not result['ui_data_saved']
    assert extract_card_info(str(path))['data']['description'] == 'already replaced'


@pytest.mark.parametrize('fault', ['repository', 'sqlite'])
def test_ui_commit_then_revision_read_failure_reports_saved(isolated_library, monkeypatch, fault):
    from core.data import local_state_repository as state
    client, root, db, cache, jobs, cfg = isolated_library
    def fail(*args, **kwargs):
        raise (state.LocalStateError('authority read failed') if fault == 'repository'
               else sqlite3.OperationalError('read failed'))
    monkeypatch.setattr(cards, 'get_ui_data_revision', fail)
    monkeypatch.setattr(cards, 'reconcile_card_ui_fields', fail)
    result = client.post('/api/update_card', json={'id': 'hero.png', 'ui_only': True,
        'ui_only_fields': ['ui_summary'], 'ui_summary': 'COMMITTED NOTE'}).get_json()
    assert state.Repository().get('hero.png')['summary'] == 'COMMITTED NOTE'
    assert result['success'] is False
    assert result['ui_data_saved'] is True
    assert result['retryable'] and result['detail_reload_required']


def test_cold_bundle_hook_uses_actual_ui_record_revision(isolated_library):
    client, root, db, cache, jobs, cfg = isolated_library
    for card_id in ['bundle/main.png', 'bundle/old.png']:
        write_png(root / card_id)
    cache.id_map.clear()
    cache.bundle_map.clear()
    def hook(_):
        data = ui_store.load_ui_data()
        ui_store.set_version_remark(data, 'bundle', 'bundle/old.png',
            {'summary': 'HOOK NOTE', 'link': 'keep', 'resource_folder': 'shared'}, 'bundle/main.png')
        assert ui_store.save_ui_data(data)
    hooks.register('card.updated', hook)
    try:
        result = client.post('/api/update_card', json={'id': 'bundle/old.png', 'ui_only': True,
            'ui_only_fields': ['ui_summary'], 'ui_summary': 'REQUEST NOTE', 'save_ui_to_bundle': True,
            'bundle_dir': 'bundle', 'version_id': 'bundle/old.png'}).get_json()
        assert result['success'], result
        assert result['canonical_ui']['ui_summary'] == 'HOOK NOTE'
    finally:
        hooks.unregister('card.updated', hook)



def test_ui_commit_then_cache_failure_keeps_committed_fact(isolated_library, monkeypatch):
    from core.data import local_state_repository as state
    client, root, db, cache, jobs, cfg = isolated_library
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError('post-commit cache failure')
    monkeypatch.setattr(cache, 'update_card_data', fail)
    result = client.post('/api/update_card', json={'id': 'hero.png', 'ui_only': True,
        'ui_only_fields': ['ui_summary'], 'ui_summary': 'COMMITTED BEFORE CACHE'}).get_json()
    assert state.Repository().get('hero.png')['summary'] == 'COMMITTED BEFORE CACHE'
    assert result['success'] is False and result['ui_data_saved'] is True
    assert result['retryable'] and result['detail_reload_required']


@pytest.mark.parametrize('include_note', [False, True])
def test_repeated_body_saves_commit_and_ack_only_owned_file_intents(isolated_library, monkeypatch, include_note):
    client, root, db, cache, jobs, cfg = isolated_library
    from core import config
    monkeypatch.setattr(config, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(index_job_worker, 'enqueue_index_job', REAL_ENQUEUE_INDEX_JOB)
    write_png(root/'hero.png')
    # A file intent from a separate operation must survive even a successful save.
    with closing(sqlite3.connect(db)) as conn:
        conn.execute('DELETE FROM index_jobs')
        prior_job = conn.execute(
            "INSERT INTO index_jobs(job_type,entity_id,source_path,payload_json) VALUES ('upsert_card',?,?,?)",
            ('hero.png', str(root/'hero.png'), json.dumps({'refresh_file': True, 'operation': 'prior', 'operation_kind': 'replace'})),
        ).lastrowid
        conn.commit()
    for index in range(3):
        payload = {'id': 'hero.png', 'char_name': f'Hero {index}', 'description': f'committed body {index}'}
        if include_note:
            payload['ui_summary'] = f'note {index}'
        result = client.post('/api/update_card', json=payload).get_json()
        assert result['success'] and not result.get('index_sync_pending'), result
        with closing(sqlite3.connect(db)) as conn:
            assert conn.execute("SELECT char_name,description FROM card_metadata WHERE id='hero.png'").fetchone() == (
                f'Hero {index}', f'committed body {index}')
            assert conn.execute("SELECT name FROM index_entities_v2 WHERE entity_id='card::hero.png'").fetchone()[0] == f'Hero {index}'
            assert conn.execute("SELECT id FROM index_jobs WHERE job_type='upsert_card' AND status!='done'").fetchall() == [(prior_job,)]


def test_later_hook_file_intent_is_not_acknowledged_by_earlier_save(isolated_library, monkeypatch):
    client, root, db, _cache, _jobs, _cfg = isolated_library
    from core import config
    monkeypatch.setattr(config, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(index_job_worker, 'enqueue_index_job', REAL_ENQUEUE_INDEX_JOB)
    write_png(root/'hero.png')
    with closing(sqlite3.connect(db)) as conn:
        conn.execute('DELETE FROM index_jobs')
        conn.commit()
    later_jobs = []
    def hook(_):
        later_jobs.append(index_job_worker.prepare_card_file_intent(str(root/'hero.png')))
    hooks.register('card.updated', hook)
    try:
        result = client.post('/api/update_card', json={
            'id': 'hero.png', 'char_name': 'saved before hook', 'description': 'new body',
        }).get_json()
        assert result['success'], result
        with closing(sqlite3.connect(db)) as conn:
            assert later_jobs
            assert conn.execute("SELECT id FROM index_jobs WHERE job_type='upsert_card' AND status!='done'").fetchall() == [(later_jobs[0],)]
    finally:
        hooks.unregister('card.updated', hook)


def test_worldbook_enqueue_failure_rolls_back_metadata_and_retains_file_recovery(isolated_library, monkeypatch):
    from core import config
    from core.services import cache_service, card_index_sync_service
    client, root, db, _cache, _jobs, _cfg = isolated_library
    monkeypatch.setattr(config, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(index_job_worker, 'enqueue_index_job', REAL_ENQUEUE_INDEX_JOB)
    monkeypatch.setattr(card_index_sync_service, 'enqueue_index_job', REAL_ENQUEUE_INDEX_JOB)
    write_png(root/'hero.png', 'OldBook')
    with client.application.app_context():
        assert cache_service.update_card_cache('hero.png', str(root/'hero.png'))
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='worldinfo'")
        conn.commit()
        index_build_service.apply_worldinfo_embedded_increment(conn, 'hero.png', str(root/'hero.png'))
        conn.execute('DELETE FROM index_jobs')
        conn.commit()
    enqueue = index_job_worker._enqueue_index_job_on_connection
    def fail_world(conn, job_type, *args):
        if job_type == 'upsert_world_embedded':
            raise sqlite3.OperationalError('derived intent insert failed')
        return enqueue(conn, job_type, *args)
    monkeypatch.setattr(index_job_worker, '_enqueue_index_job_on_connection', fail_world)
    result = client.post('/api/update_card', json={'id': 'hero.png', 'char_name': 'Hero',
        'character_book': {'name': 'NewBook', 'entries': [{'keys': ['new'], 'content': 'new content'}]},
    }).get_json()
    assert result['success'] is False and result['file_modified'] and result['index_sync_pending'], result
    assert extract_card_info(str(root/'hero.png'))['data']['character_book']['name'] == 'NewBook'
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        assert conn.execute("SELECT character_book_name FROM card_metadata WHERE id='hero.png'").fetchone()[0] == 'OldBook'
        assert conn.execute("SELECT name FROM index_entities_v2 WHERE entity_id='world::embedded::hero.png'").fetchone()[0] == 'OldBook'
        rows = conn.execute("SELECT * FROM index_jobs WHERE job_type='upsert_card' AND status!='done'").fetchall()
        assert any(json.loads(row['payload_json']).get('refresh_file') for row in rows)
    monkeypatch.setattr(index_job_worker, '_enqueue_index_job_on_connection', enqueue)
    for row in rows:
        index_job_worker.process_card_job(row, json.loads(row['payload_json']))
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM index_jobs WHERE job_type='upsert_world_embedded' AND status!='done'").fetchall()
        assert rows
        for row in rows:
            index_job_worker.process_worldinfo_job(conn, row)
        assert conn.execute("SELECT name FROM index_entities_v2 WHERE entity_id='world::embedded::hero.png'").fetchone()[0] == 'NewBook'
