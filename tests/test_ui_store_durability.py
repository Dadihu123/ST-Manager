"""权威状态耐久性：真实 SQLite/WAL，旧 JSON 只用于迁移和显式导出。"""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from core.data import local_state_repository as state, ui_store, chat_store


@pytest.fixture
def store(monkeypatch, tmp_path):
    ui = tmp_path / 'ui_data.json'
    chat = tmp_path / 'chat_data.json'
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(ui))
    monkeypatch.setattr(chat_store, 'CHAT_DATA_FILE', str(chat))
    ui_store._clear_ui_data_degraded()
    yield state.Repository(), ui
    ui_store._clear_ui_data_degraded()


def test_migration_preserves_primary_and_all_backup_generations(store):
    repo, ui = store
    original = {'hero.png': {'summary': 'old', 'unknown': [1, None]}}
    ui.write_text(json.dumps(original))
    for suffix in ('.bak', '.bak.1', '.bak.2'):
        ui.with_name(ui.name + suffix).write_text(json.dumps({'generation': suffix}))
    assert repo.export_snapshot() == original
    repo.update_fields('hero.png', {'summary': 'new'})
    assert json.loads(ui.read_text()) == original
    assert json.loads(ui.with_name(ui.name + '.before-local-state').read_text()) == original
    for suffix in ('.bak', '.bak.1', '.bak.2'):
        assert json.loads(ui.with_name(ui.name + suffix).read_text()) == {'generation': suffix}
    with sqlite3.connect(repo.path or state.DEFAULT_DB_PATH) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_valid_backup_recovers_confirmed_corrupt_legacy_source(store):
    repo, ui = store
    ui.write_text('{broken')
    ui.with_name(ui.name + '.bak').write_text('{bad backup')
    ui.with_name(ui.name + '.bak.1').write_text('{"hero":{"summary":"recovered"}}')
    assert repo.get('hero') == {'summary': 'recovered'}
    assert ui.read_text() == '{broken'  # evidence is preserved, never replaced in place


def test_corrupt_source_without_valid_backup_blocks_migration_and_writes(store):
    repo, ui = store
    ui.write_text('{broken')
    with pytest.raises(ui_store.UiDataLoadError):
        ui_store.load_ui_data()
    assert ui_store.is_ui_data_degraded()
    assert not ui_store.save_ui_data({'hero': {'summary': 'new'}})
    assert ui.read_text() == '{broken'


def test_migration_access_failure_never_uses_stale_backup(store, monkeypatch):
    repo, ui = store
    ui.write_text('{"hero":{"summary":"current"}}')
    ui.with_name(ui.name + '.bak').write_text('{"hero":{"summary":"old"}}')
    original = state._legacy
    def denied(path):
        if path == str(ui):
            raise PermissionError('unreachable')
        return original(path)
    monkeypatch.setattr(state, '_legacy', denied)
    with pytest.raises(ui_store.UiDataLoadError):
        ui_store.load_ui_data()
    assert not ui_store.save_ui_data({'new': {}})
    assert json.loads(ui.read_text())['hero']['summary'] == 'current'


def test_normalization_is_atomic_and_preserves_original_snapshot(store):
    repo, ui = store
    original = {'hero': {'summary': 'keep', 'resource_folder': 'cards/bad',
                          'import_time': '1700000000.5', 'future': [None]}}
    ui.write_text(json.dumps(original))
    assert repo.get('hero') == {'summary': 'keep', 'resource_folder': '',
                                'import_time': 1700000000.5, 'future': [None]}
    assert json.loads(ui.read_text()) == original


def test_failed_serialization_preserves_committed_record(store):
    repo, _ = store
    repo.update_fields('hero', {'summary': 'before'})
    draft = ui_store.load_ui_data()
    draft['hero']['summary'] = object()
    assert not ui_store.save_ui_data(draft)
    assert repo.get('hero') == {'summary': 'before'}


def test_failed_sql_commit_rolls_back_records_bindings_and_revision(store):
    repo, _ = store
    repo.update_fields('hero', {'summary': 'before', 'chat_ids': ['old']})
    revision = repo.revision()
    with pytest.raises(sqlite3.DatabaseError):
        with repo.transaction() as conn:
            repo.update_fields('hero', {'summary': 'after', 'chat_ids': ['new']}, conn=conn)
            conn.set_authorizer(lambda op, arg, *rest: sqlite3.SQLITE_DENY
                                if op == sqlite3.SQLITE_TRANSACTION and arg == 'COMMIT'
                                else sqlite3.SQLITE_OK)
    assert repo.get('hero') == {'summary': 'before', 'chat_ids': ['old']}
    assert state.binding_keys() == [('hero', 'old')]
    assert repo.revision() == revision


def test_no_baseline_cannot_replace_or_delete_existing_rows(store):
    repo, _ = store
    original = {str(i): {'summary': 'keep'} for i in range(400)}
    repo.replace_snapshot(original)
    assert not ui_store.save_ui_data({'0': {'summary': 'overwrite'}})
    assert ui_store.save_ui_data({})  # empty changes are not a destructive replacement
    assert repo.export_snapshot() == original


def test_explicit_snapshot_import_can_shrink(store):
    repo, _ = store
    repo.replace_snapshot({str(i): {'summary': 'keep'} for i in range(400)})
    repo.replace_snapshot({'new': {'summary': 'explicit'}})
    assert repo.export_snapshot() == {'new': {'summary': 'explicit'}}


def test_snapshot_deletion_has_baseline_conflict_protection(store):
    repo, _ = store
    repo.update_fields('a', {'summary': 'before'})
    old = ui_store.load_ui_data()
    del old['a']
    repo.update_fields('a', {'summary': 'newer'})
    assert not ui_store.save_ui_data(old)
    assert repo.get('a') == {'summary': 'newer'}


def test_update_ui_data_serializes_concurrent_writers(store):
    repo, _ = store
    repo.update_fields('base', {'summary': 'base'})
    def writer(i):
        return ui_store.update_ui_data(lambda data: data.__setitem__(str(i), {'summary': str(i)}))
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(pool.map(writer, range(20)))
    assert repo.export_snapshot() == {'base': {'summary': 'base'},
                                     **{str(i): {'summary': str(i)} for i in range(20)}}


def test_activated_database_failure_never_falls_back_to_json(store):
    repo, ui = store
    ui.write_text('{"hero":{"summary":"old"}}')
    repo.update_fields('hero', {'summary': 'new'})
    with sqlite3.connect(state.DEFAULT_DB_PATH) as conn:
        conn.execute('DROP TABLE ui_records')
    with pytest.raises(state.LocalStateError):
        repo.get('hero')
    assert not ui_store.save_ui_data({'other': {}})
    assert json.loads(ui.read_text()) == {'hero': {'summary': 'old'}}


def test_explicit_legacy_export_reads_authority(store, tmp_path):
    repo, ui = store
    ui.write_text('{"hero":{"summary":"old"}}')
    repo.update_fields('hero', {'summary': 'new'})
    target = tmp_path / 'export.json'
    assert ui_store.export_legacy_ui_data(str(target))
    assert json.loads(target.read_text()) == {'hero': {'summary': 'new'}}
    assert json.loads(ui.read_text()) == {'hero': {'summary': 'old'}}
