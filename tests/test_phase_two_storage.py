"""Phase two integration checks: real SQLite and files, never user paths."""
import json
import os
import sqlite3
import struct
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image

from core.data import local_state_repository as state, ui_store, chat_store
from core.data.index_runtime_store import (
    ensure_index_runtime_schema, repair_full_search_mapping, delete_full_search_rows,
    clear_generation_data,
)
from core.utils.image import write_card_metadata, extract_card_info, image_content_revision
from core.utils.png_metadata import read_png_text, rewrite_png_text, PngFormatError


@pytest.fixture
def store(tmp_path, monkeypatch):
    db = tmp_path / 'state.db'
    ui = tmp_path / 'ui.json'
    chat = tmp_path / 'chat.json'
    monkeypatch.setattr(state, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(ui_store, 'UI_DATA_FILE', str(ui))
    monkeypatch.setattr(chat_store, 'CHAT_DATA_FILE', str(chat))
    return db, ui, chat


def test_snapshot_merge_conflicts_unknown_values_and_bindings(store):
    db, ui, chat = store
    original = {'a.png': {'summary': 'old', 'link': 'url', 'chat_ids': ['c', 'd'],
                          'plugin': {'opaque': [1, None]}}, '_unknown': [False, 9]}
    ui.write_text(json.dumps(original))
    chat.write_text(json.dumps({'c': {'notes': 'note', 'last_view_floor': 7, 'future': [2]}}))
    repo = state.Repository()
    assert repo.export_snapshot() == original
    first, second = ui_store.load_ui_data(), ui_store.load_ui_data()
    first['a.png']['summary'] = 'one'
    second['a.png']['link'] = 'two'
    assert ui_store.save_ui_data(first) and ui_store.save_ui_data(second)
    stale = ui_store.load_ui_data()
    stale['a.png']['summary'] = 'conflict'
    repo.update_fields('a.png', {'summary': 'three'})
    assert ui_store.save_ui_data(stale) is False
    assert repo.get('a.png')['summary'] == 'three'
    assert repo.get('a.png')['link'] == 'two'
    assert repo.get('_unknown') == [False, 9]
    assert state.binding_keys(['c']) == [('a.png', 'c')]
    assert chat_store.load_chat_data()['c']['future'] == [2]
    assert json.loads(ui.read_text()) == original  # no dual writes
    with state.connect(db) as conn:
        assert conn.execute('PRAGMA synchronous').fetchone()[0] == 2


def test_composable_transaction_rolls_back_all_state(store):
    repo = state.Repository()
    repo.replace_snapshot({'a': {'summary': 'before'}})
    revision = repo.revision()
    with pytest.raises(RuntimeError):
        with repo.transaction() as conn:
            repo.update_fields('a', {'summary': 'after'}, conn=conn)
            repo.update_fields('b', {'chat_ids': ['c']}, conn=conn)
            raise RuntimeError('abort')
    assert repo.export_snapshot() == {'a': {'summary': 'before'}}
    assert repo.revision() == revision
    assert state.binding_keys() == []


def test_concurrent_record_writers(store):
    repo = state.Repository()
    repo.replace_snapshot({'a': {}})
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: repo.update_fields('a', {str(n): n}), range(20)))
    assert repo.get('a') == {str(n): n for n in range(20)}


@pytest.mark.parametrize('phase', ['preparing', 'imported'])
def test_migration_interruption_and_activation_retry(store, monkeypatch, phase):
    db, ui, _ = store
    ui.write_text(json.dumps({'a': {'summary': 'original'}, '_plugin': [None, 1]}))
    activate = state._activate
    def fail(conn):
        if phase == 'imported':
            raise OSError('activation interrupted')
        return activate(conn)
    if phase == 'preparing':
        original_encode = state.encode
        def fail_encode(value):
            if isinstance(value, dict) and value.get('summary') == 'original':
                raise OSError('staging interrupted')
            return original_encode(value)
        monkeypatch.setattr(state, 'encode', fail_encode)
    else:
        monkeypatch.setattr(state, '_activate', fail)
    with pytest.raises(state.LocalStateError):
        state.initialize()
    monkeypatch.setattr(state, '_activate', activate)
    if phase == 'preparing':
        monkeypatch.setattr(state, 'encode', original_encode)
    state.initialize()
    assert state.Repository().get('a')['summary'] == 'original'
    state.Repository().update_fields('a', {'summary': 'new authority'})
    state._ready.clear()
    ui.write_text('{}')
    state.initialize()
    assert state.Repository().get('a')['summary'] == 'new authority'


def test_migration_corrupt_and_unreachable_sources_never_activate(store, monkeypatch):
    db, ui, _ = store
    ui.write_text('{broken')
    with pytest.raises(state.LocalStateError):
        state.initialize()
    with sqlite3.connect(db) as conn:
        assert conn.execute('SELECT COUNT(*) FROM ui_records').fetchone()[0] == 0
    ui.write_text('{}')
    original = state._legacy
    def denied(path):
        if path == str(ui):
            raise PermissionError('unreachable')
        return original(path)
    monkeypatch.setattr(state, '_legacy', denied)
    with pytest.raises(state.LocalStateError):
        state.initialize()


def test_activated_missing_or_corrupt_database_never_reimports(store):
    db, ui, _ = store
    ui.write_text('{"a":{"summary":"old"}}')
    state.initialize()
    state.Repository().update_fields('a', {'summary': 'new'})
    state._ready.clear()
    db.unlink()
    with pytest.raises(state.LocalStateError):
        state.initialize()


def test_large_legacy_migration_and_unknown_payload(store):
    _, ui, _ = store
    payload = {'huge': {'summary': 'x' * (17 * 1024 ** 2)}, '_plugin': [False, None]}
    ui.write_text(json.dumps(payload))
    state.initialize()
    assert state.Repository().export_snapshot() == payload


def test_fts_mapping_repair_plan_rollback_and_generation(tmp_path):
    with sqlite3.connect(tmp_path / 'fts.db') as conn:
        ensure_index_runtime_schema(conn)
        conn.executemany('INSERT INTO index_search_full_v2 VALUES (?,?,?)',
                         [(1, f'card::{i}', f'word {i}') for i in range(10000)])
        conn.execute("INSERT INTO index_search_full_v2 VALUES (1,'card::1','latest')")
        repair_full_search_mapping(conn)
        assert conn.execute('SELECT COUNT(*) FROM index_full_rowids').fetchone()[0] == 10000
        conn.execute("DELETE FROM index_full_rowids WHERE entity_id='card::2'")
        conn.execute("UPDATE index_full_rowids SET fts_rowid=900000 WHERE entity_id='card::3'")
        repair_full_search_mapping(conn)
        conn.commit()
        plan = conn.execute('EXPLAIN QUERY PLAN SELECT fts_rowid FROM index_full_rowids '
                            'WHERE generation=? AND entity_id=?', (1, 'card::1')).fetchall()
        assert any('SEARCH' in row[3] and 'INDEX' in row[3] for row in plan)
        steps = [0]
        conn.set_progress_handler(lambda: steps.__setitem__(0, steps[0] + 1) or 0, 1)
        delete_full_search_rows(conn, 1, 'card::1')
        conn.set_progress_handler(None, 0)
        assert steps[0] < 2000  # a real VM instruction budget, independent of FTS row count
        conn.rollback()
        assert conn.execute("SELECT content FROM index_search_full_v2 WHERE rowid=(SELECT fts_rowid "
                            "FROM index_full_rowids WHERE generation=1 AND entity_id='card::1')").fetchone()[0] == 'latest'
        clear_generation_data(conn, 'cards', 1)
        assert conn.execute('SELECT COUNT(*) FROM index_full_rowids').fetchone()[0] == 0
        assert conn.execute('SELECT COUNT(*) FROM index_search_full_v2').fetchone()[0] == 0


def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)


@pytest.mark.parametrize('kind', [b'tEXt', b'zTXt', b'iTXt'])
@pytest.mark.parametrize('after', [True, False])
def test_chunk_read_write_preserves_image_and_ancillary(tmp_path, monkeypatch, kind, after):
    path = tmp_path / 'card.png'
    Image.new('P', (10, 10)).save(path, transparency=0)
    raw = path.read_bytes()
    value = b'{"spec":"chara_card_v2","spec_version":"2.0","data":{"name":"chunk card"}}'
    payload = (b'CHARA\0' + value if kind == b'tEXt' else
               b'CHARA\0\0' + zlib.compress(value) if kind == b'zTXt' else
               b'CHARA\0\1\0en\0translated\0' + zlib.compress(value))
    extra = chunk(kind, payload) + chunk(b'tEXt', b'Software\0kept')
    if after:
        raw = raw[:-12] + extra + raw[-12:]
    else:
        raw = raw[:33] + extra + raw[33:]
    path.write_bytes(raw)
    before = image_content_revision(str(path))
    def no_pixels(*args, **kwargs):
        raise AssertionError('metadata must not decode or encode pixels')
    monkeypatch.setattr(Image, 'open', no_pixels)
    assert extract_card_info(str(path))['data']['name'] == 'chunk card'
    assert write_card_metadata(str(path), {'name': 'new card'})
    assert image_content_revision(str(path)) == before
    assert read_png_text(path)['Software'] == 'kept'
    # Compare all non-character bytes exactly, including PLTE/tRNS and compressed IDAT.
    def chunks(data):
        result = []
        offset = 8
        while offset < len(data):
            size = struct.unpack('>I', data[offset:offset+4])[0]
            block = data[offset:offset+size+12]
            if block[4:8] not in (b'tEXt', b'zTXt', b'iTXt'):
                result.append(block)
            offset += size + 12
        return result
    assert chunks(raw) == chunks(path.read_bytes())


def test_corrupt_png_never_replaces_original(tmp_path):
    path = tmp_path / 'broken.png'
    Image.new('RGB', (2, 2)).save(path)
    raw = bytearray(path.read_bytes())
    raw[30] ^= 1
    path.write_bytes(raw)
    with pytest.raises(PngFormatError):
        rewrite_png_text(path, '{"name":"new"}')
    assert path.read_bytes() == raw
    assert not list(tmp_path.glob('.stm-png-*'))


def test_global_namespace_updates_only_accessed_member(store, monkeypatch):
    repo = state.Repository()
    payload = {'_worldinfo_notes_v1': {f'embedded::card-{i}.png': {'summary': 'note', 'opaque': i}
                                      for i in range(10000)}, '_plugins_v1': {'one': {'private': 7}}}
    repo.replace_snapshot(payload)
    first, second = ui_store.load_ui_data(), ui_store.load_ui_data()
    decoded = []
    original = state.json.loads
    def observe(raw, *args, **kwargs):
        decoded.append(len(raw))
        return original(raw, *args, **kwargs)
    monkeypatch.setattr(state.json, 'loads', observe)
    assert ui_store.set_worldinfo_note(first, 'embedded', 'new', card_id='card-500.png')
    assert ui_store.set_worldinfo_note(second, 'embedded', 'other', card_id='card-700.png')
    assert ui_store.save_ui_data(first) and ui_store.save_ui_data(second)
    assert len(decoded) < 30 and max(decoded) < 1000
    monkeypatch.setattr(state.json, 'loads', original)
    exported = repo.export_snapshot()
    assert len(exported['_worldinfo_notes_v1']) == 10000
    assert exported['_worldinfo_notes_v1']['embedded::card-500.png']['summary'] == 'new'
    assert exported['_worldinfo_notes_v1']['embedded::card-500.png']['opaque'] == 500
    assert exported['_worldinfo_notes_v1']['embedded::card-700.png']['summary'] == 'other'
    assert exported['_plugins_v1'] == payload['_plugins_v1']


def test_active_schema_corruption_blocks_restart(store):
    db, _, _ = store
    state.Repository().update_fields('a', {'summary': 'keep'})
    with sqlite3.connect(db) as conn:
        conn.execute('DROP TABLE ui_records')
    state._ready.clear()
    with pytest.raises(state.LocalStateError):
        state.initialize()
    with sqlite3.connect(db) as conn:
        assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='ui_records'").fetchone()


def test_file_intent_recovers_current_file_and_does_not_ack_newer_job(store, tmp_path, monkeypatch):
    from core import config
    from core.context import ctx
    from core.data.db_session import _initialize_database
    from core.services import index_job_worker as worker, index_build_service as build
    from core.data.cache import GlobalMetadataCache
    db, _, _ = store
    root = tmp_path / 'cards'
    root.mkdir()
    path = root / 'a.png'
    Image.new('RGB', (4, 4)).save(path)
    state.initialize()
    with sqlite3.connect(db) as conn:
        _initialize_database(conn, is_existing_db=True, schema_only=True)
        conn.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='cards'")
    monkeypatch.setattr(config, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(worker, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(build, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(ctx, 'cache', GlobalMetadataCache())
    # The real writer persists an intent before atomic file replacement.
    assert write_card_metadata(str(path), {'data': {'name': 'first'}})
    with worker._connect() as conn:
        row = conn.execute("SELECT * FROM index_jobs WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
    # A newer actual file survives; the old intent must reconcile it, never replay old content.
    assert write_card_metadata(str(path), {'data': {'name': 'newer', 'description': 'persisted'}})
    worker.process_card_job(row, json.loads(row['payload_json']))
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT char_name FROM card_metadata WHERE id='a.png'").fetchone()[0] == 'newer'
        assert conn.execute("SELECT name FROM index_entities_v2 WHERE entity_id='card::a.png'").fetchone()[0] == 'newer'
        jobs = conn.execute('SELECT id,status FROM index_jobs ORDER BY id').fetchall()
        assert jobs[0] == (row['id'], 'done')
        assert jobs[1][1] == 'pending'
    assert extract_card_info(str(path))['data']['description'] == 'persisted'


@pytest.mark.parametrize('broken', ['truncated', 'trailing', 'budget'])
def test_png_compressed_text_rejects_invalid_stream_without_replacement(tmp_path, monkeypatch, broken):
    from core.utils import png_metadata
    path = tmp_path / 'bad-text.png'
    Image.new('RGB', (2, 2)).save(path)
    raw = path.read_bytes()
    compressed = zlib.compress(b'x' * 500)
    if broken == 'truncated':
        compressed = compressed[:-2]
    elif broken == 'trailing':
        compressed += b'unexpected'
    else:
        monkeypatch.setattr(png_metadata, 'MAX_TEXT_BYTES', 100)
    raw = raw[:-12] + chunk(b'zTXt', b'chara\0\0' + compressed) + raw[-12:]
    path.write_bytes(raw)
    with pytest.raises(PngFormatError):
        rewrite_png_text(path, '{"name":"replacement"}')
    assert path.read_bytes() == raw


def test_apng_metadata_edit_preserves_animation_bytes(tmp_path):
    path = tmp_path / 'animated.png'
    images = [Image.new('RGBA', (4, 4), color) for color in ('red', 'blue')]
    images[0].save(path, save_all=True, append_images=images[1:], duration=100, loop=0)
    raw = path.read_bytes()
    before = image_content_revision(str(path))
    assert b'acTL' in raw and b'fdAT' in raw
    assert write_card_metadata(str(path), {'data': {'name': 'animated'}})
    assert image_content_revision(str(path)) == before
    with Image.open(path) as result:
        assert result.n_frames == 2
        result.seek(1)
        assert result.convert('RGB').getpixel((0, 0)) == (0, 0, 255)


def test_failed_intents_are_retained_and_retried_without_restart(store, monkeypatch):
    from core.services import index_job_worker as worker
    db, _, _ = store
    state.initialize()
    monkeypatch.setattr(worker, 'DEFAULT_DB_PATH', str(db))
    with worker._connect() as conn:
        conn.executemany("INSERT INTO index_jobs(job_type,entity_id,status,finished_at) VALUES ('upsert_card',?,'failed',1)",
                         [(str(i),) for i in range(80)])
        worker._prune_terminal_jobs(conn)
        assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE status='failed'").fetchone()[0] == 80
    rows, pending = worker._claim_pending_jobs(50)
    assert len(rows) == 50 and pending == 30


def test_prepared_ui_revision_cannot_overwrite_newer_projection(store, monkeypatch):
    from core.services import index_job_worker as worker
    db, _, _ = store
    repo = state.Repository()
    repo.update_fields('a.png', {'summary': 'old'})
    key, old, revision = worker._prepare_card_ui('a.png')
    repo.update_fields('a.png', {'summary': 'new'})
    with sqlite3.connect(db) as conn:
        with pytest.raises(state.StateConflict):
            worker._check_prepared_ui(conn, key, revision)
    assert repo.get('a.png')['summary'] == 'new'



def test_external_in_place_image_edit_with_preserved_mtime_invalidates_revision(tmp_path):
    import os
    path = tmp_path / 'external.png'
    Image.new('RGB', (16, 16), 'red').save(path)
    original = path.stat()
    revision = image_content_revision(str(path))
    # Keep the inode and exact byte count; only IDAT contents and Windows ChangeTime differ.
    raw = bytearray(path.read_bytes())
    offset = raw.index(b'IDAT') - 4
    size = struct.unpack('>I', raw[offset:offset + 4])[0]
    image_data = bytearray(zlib.decompress(raw[offset + 8:offset + 8 + size]))
    image_data[-1] ^= 1
    replacement = zlib.compress(bytes(image_data))
    if len(replacement) != size:
        # A same-length ancillary rendering chunk gives a deterministic in-place fixture.
        block = chunk(b'gAMA', struct.pack('>I', 45455))
        raw = raw[:33] + block + raw[33:]
        path.write_bytes(raw)
        revision = image_content_revision(str(path))
        original = path.stat()
        start = raw.index(b'gAMA') - 4
        raw[start:start + 16] = chunk(b'gAMA', struct.pack('>I', 50000))
    else:
        raw[offset:offset + size + 12] = chunk(b'IDAT', replacement)
    with path.open('r+b') as target:
        target.write(raw)
    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert path.stat().st_size == original.st_size
    assert path.stat().st_ino == original.st_ino
    assert image_content_revision(str(path)) != revision



def test_active_backup_reader_never_exports_stale_legacy_on_damaged_authority(store):
    db, ui, _ = store
    ui.write_text('{"a":{"summary":"stale JSON"}}')
    state.initialize()
    state.Repository().update_fields('a', {'summary': 'current SQLite'})
    with sqlite3.connect(db) as conn:
        conn.execute('DROP TABLE local_state_migrations')
    with pytest.raises(state.LocalStateError):
        state.read_snapshot_at(str(db), 'ui', str(ui))


def test_png_replacement_must_remain_readable_within_budget(tmp_path, monkeypatch):
    from core.utils import png_metadata
    path = tmp_path / 'small-budget.png'
    Image.new('RGB', (4, 4)).save(path)
    original = path.read_bytes()
    monkeypatch.setattr(png_metadata, 'MAX_TEXT_BYTES', 100)
    with pytest.raises(PngFormatError):
        rewrite_png_text(path, json.dumps({'data': {'name': 'x' * 100}}))
    assert path.read_bytes() == original



def test_empty_resource_normalization_does_not_schedule_worldbook_work(store):
    from core.data.db_session import _initialize_database
    db, _, _ = store
    state.initialize()
    with sqlite3.connect(db) as conn:
        _initialize_database(conn, is_existing_db=True, schema_only=True)
        conn.execute("INSERT INTO card_metadata(id,char_name) VALUES ('a.png','A')")
    repo = state.Repository()
    repo.update_fields('a.png', {'summary': 'before'})
    repo.update_fields('a.png', {'summary': 'after', 'resource_folder': ''})
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE job_type='upsert_world_owner'").fetchone()[0] == 0


@pytest.mark.parametrize('delete_namespace', [False, True])
def test_namespace_replacement_rejects_concurrent_members(store, delete_namespace):
    repo = state.Repository()
    repo.replace_snapshot({'_worldinfo_notes_v1': {'embedded::old.png': {'note': 'old'}}})
    first = ui_store.load_ui_data()
    if delete_namespace:
        del first['_worldinfo_notes_v1']
    else:
        ui_store.rename_embedded_worldinfo_note_card_prefix(first, 'old.png', 'new.png')
    repo.update_fields('_worldinfo_notes_v1', {'embedded::other.png': {'note': 'concurrent'}})
    with pytest.raises(state.StateConflict):
        repo.save(first)
    assert repo.export_snapshot()['_worldinfo_notes_v1']['embedded::other.png']['note'] == 'concurrent'


def test_outer_rollback_keeps_snapshot_retryable(store):
    repo = state.Repository()
    repo.replace_snapshot({'a': {'summary': 'old'}, '_notes': {'one': 'old'}})
    snapshot = ui_store.load_ui_data()
    snapshot['a']['summary'] = 'new'
    snapshot['_notes']['one'] = 'new'
    with pytest.raises(RuntimeError):
        with repo.transaction() as conn:
            repo.save(snapshot, conn=conn)
            raise RuntimeError('rollback owner')
    assert repo.export_snapshot() == {'a': {'summary': 'old'}, '_notes': {'one': 'old'}}
    assert repo.save(snapshot)
    assert repo.export_snapshot() == {'a': {'summary': 'new'}, '_notes': {'one': 'new'}}


def test_flask_savepoint_rollback_keeps_snapshot_retryable(store):
    from flask import Flask, g
    repo = state.Repository()
    repo.replace_snapshot({'a': {'summary': 'old'}})
    snapshot = ui_store.load_ui_data()
    snapshot['a']['summary'] = 'new'
    with Flask(__name__).app_context(), state.connect() as conn:
        g.db = conn
        conn.execute('BEGIN IMMEDIATE')
        assert repo.save(snapshot)
        conn.rollback()
        g.pop('db')
    assert repo.get('a')['summary'] == 'old'
    assert repo.save(snapshot)
    assert repo.get('a')['summary'] == 'new'


def test_migration_lock_open_failure_is_structured(store):
    db, _, _ = store
    Path(str(db) + '.migration.lock').mkdir()
    with pytest.raises(state.LocalStateError):
        state.initialize()
    from core import create_app
    app = create_app()
    assert app is not None
    assert 'system' in app.blueprints


def test_repeated_schema_initialization_does_not_scan_fts(tmp_path):
    with sqlite3.connect(tmp_path / 'fts.db') as conn:
        ensure_index_runtime_schema(conn)
        conn.executemany('INSERT INTO index_search_full_v2 VALUES (?,?,?)',
                         [(1, 'card::' + str(i), 'word') for i in range(1000)])
        repair_full_search_mapping(conn)
        conn.commit()
        steps = [0]
        conn.set_progress_handler(lambda: steps.__setitem__(0, steps[0] + 1) or 0, 1)
        ensure_index_runtime_schema(conn)
        conn.set_progress_handler(None, 0)
        assert steps[0] < 5000
        assert conn.execute('SELECT COUNT(*) FROM index_full_rowids').fetchone()[0] == 1000


def test_replacement_text_budget_includes_keywords(tmp_path, monkeypatch):
    from core.utils import png_metadata
    path = tmp_path / 'budget.png'
    Image.new('RGB', (2, 2)).save(path)
    original = path.read_bytes()
    payload = '{"data":{"name":"x"}}'
    replacements = png_metadata.encode_card_chunks(payload)
    limit = sum(len(value.encode('latin-1')) for _, value in replacements)
    monkeypatch.setattr(png_metadata, 'MAX_TEXT_BYTES', limit)
    with pytest.raises(PngFormatError):
        rewrite_png_text(path, payload)
    assert path.read_bytes() == original
    cost = sum(len(key.encode('latin-1')) + 1 + len(value.encode('latin-1')) for key, value in replacements)
    monkeypatch.setattr(png_metadata, 'MAX_TEXT_BYTES', cost)
    assert rewrite_png_text(path, payload)
    assert read_png_text(path)['chara']


def test_worldinfo_increment_removes_disappeared_zero_categories(store, tmp_path, monkeypatch):
    from core.data import db_session
    from core.services import index_build_service as build
    worlds = tmp_path / 'worlds'
    (worlds / 'old').mkdir(parents=True)
    (worlds / 'empty').mkdir()
    path = worlds / 'old' / 'book.json'
    path.write_text('{"name":"book","entries":{}}')
    monkeypatch.setattr(build, 'load_config', lambda: {'world_info_dir': str(worlds)})
    with state.connect(store[0]) as conn:
        db_session._initialize_database(conn, is_existing_db=True, schema_only=True)
        conn.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='worldinfo'")
        conn.commit()
        build.apply_worldinfo_path_increment(conn, str(path))
        path.unlink()
        path.parent.rmdir()
        build.apply_worldinfo_path_increment(conn, str(path))
        rows = conn.execute("SELECT category_path FROM index_category_stats_v2 WHERE scope='worldinfo'").fetchall()
        assert 'old' not in {row[0] for row in rows}
        assert 'empty' in {row[0] for row in rows}


@pytest.mark.parametrize('operation', [
    'upload', 'rename', 'change_image', 'convert', 'folder', 'folder_legacy',
    'upload_note_pending', 'upload_note_running', 'convert_before_plain', 'convert_before_valid',
    'change_image_early_worker', 'convert_early_worker',
    'folder_early_worker',
    'automation_early_worker',
    'convert_scan_first', 'world_ack',
    'rename_hook',
    'chain_api', 'chain_body', 'chain_automation', 'chain_move', 'chain_folder',
    'chain_deleted', 'chain_without_generation',
    'move_ack_world', 'move_ack_ui', 'move_ack_revision', 'move_ack_unrelated_receipt',
])
def test_real_process_exit_around_card_file_commit_recovers(tmp_path, operation):
    import subprocess
    import sys
    root = tmp_path / operation
    root.mkdir()
    helper = Path(__file__).with_name('phase_two_crash_helper.py')
    crash = subprocess.run([sys.executable, '-X', 'utf8', str(helper), str(root), operation, 'crash'],
                           capture_output=True, timeout=60)
    expected_exit = (0 if operation == 'rename_hook' or operation.startswith(('chain_', 'move_ack_')) else 75 if operation == 'world_ack' else 76 if operation.endswith('_scan_first')
                     else 74 if operation.startswith('convert_before') else 73)
    assert crash.returncode == expected_exit, (crash.stdout + crash.stderr).decode('utf-8', errors='replace')
    recovery = subprocess.run([sys.executable, '-X', 'utf8', str(helper), str(root), operation, 'recover'],
                              capture_output=True, timeout=60)
    assert recovery.returncode == 0, (recovery.stdout + recovery.stderr).decode('utf-8', errors='replace')


@pytest.mark.parametrize('operation,failure', [
    (operation, failure) for operation in ('convert', 'bundle')
    for failure in ('normal', 'cold', 'binding', 'note', 'sqlite', 'false')
] + [('image', 'false'), ('bundle', 'marker'), ('convert', 'cleanup'), ('convert', 'replace'),
     pytest.param('convert', 'readonly', marks=pytest.mark.skipif(os.name != 'nt', reason='Windows readonly deletion'))])
def test_conversion_ui_migration_and_recovery(tmp_path, operation, failure):
    import subprocess
    import sys
    helper = Path(__file__).with_name('phase_two_crash_helper.py')
    result = subprocess.run([sys.executable, '-X', 'utf8', str(helper), str(tmp_path),
                             'conversion_ui', operation + ':' + failure], capture_output=True, timeout=60)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')


@pytest.mark.parametrize('mode', ['main', 'middle', 'last', 'recovery_middle', 'normal',
                                  'changed', 'collision', 'missing', 'access', 'ack'])
def test_bundle_companions_real_process_recovery(tmp_path, mode):
    import subprocess
    import sys
    helper = Path(__file__).with_name('phase_two_crash_helper.py')
    crash = subprocess.run([sys.executable, '-X', 'utf8', str(helper), str(tmp_path), 'conversion_ui',
                            'bundle:sidecar_' + mode], capture_output=True, timeout=60)
    assert crash.returncode == (0 if mode == 'normal' else 73), (
        crash.stdout + crash.stderr).decode('utf-8', errors='replace')
    recovery = subprocess.run([sys.executable, '-X', 'utf8', str(helper), str(tmp_path),
                               'bundle_companions', mode], capture_output=True, timeout=60)
    if mode == 'recovery_middle':
        assert recovery.returncode == 74, (recovery.stdout + recovery.stderr).decode('utf-8', errors='replace')
        recovery = subprocess.run([sys.executable, '-X', 'utf8', str(helper), str(tmp_path),
                                   'bundle_companions', 'main'], capture_output=True, timeout=60)
    assert recovery.returncode == 0, (recovery.stdout + recovery.stderr).decode('utf-8', errors='replace')


@pytest.mark.parametrize('kind,operation', [(kind, operation) for kind in ('card', 'folder', 'bundle')
                                          for operation in ('api', 'update', 'delete', 'rollback', 'failure')]
                         + [('card', 'concurrent')])
def test_underscore_card_binding_and_projection(tmp_path, kind, operation):
    import subprocess
    import sys
    helper = Path(__file__).with_name('phase_two_crash_helper.py')
    result = subprocess.run([sys.executable, '-X', 'utf8', str(helper), str(tmp_path),
                             'underscore_binding', kind + ':' + operation], capture_output=True, timeout=60)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')


@pytest.mark.parametrize('operation', ['bind', 'unbind', 'rebind', 'repeat', 'failure'])
def test_chat_binding_response_matches_authoritative_commit(tmp_path, operation):
    import subprocess
    import sys
    helper = Path(__file__).with_name('phase_two_crash_helper.py')
    result = subprocess.run([sys.executable, '-X', 'utf8', str(helper), str(tmp_path),
                             'chat_binding_response', operation], capture_output=True, timeout=60)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', errors='replace')


def _world_job_runtime(store, tmp_path, monkeypatch):
    from core import config
    from core.context import ctx
    from core.data.cache import GlobalMetadataCache
    from core.data.db_session import _initialize_database
    from core.services import index_build_service as build, index_job_worker as worker
    roots = {name: tmp_path / name for name in ('cards', 'worlds', 'resources')}
    for root in roots.values():
        root.mkdir()
    monkeypatch.setattr(config, 'CARDS_FOLDER', str(roots['cards']))
    monkeypatch.setattr(build, 'CARDS_FOLDER', str(roots['cards']))
    monkeypatch.setattr(worker, 'DEFAULT_DB_PATH', str(store[0]))
    monkeypatch.setattr(build, 'load_config', lambda: {'world_info_dir': str(roots['worlds']),
                                                     'resources_dir': str(roots['resources'])})
    monkeypatch.setattr(ctx, 'cache', GlobalMetadataCache())
    state.initialize()
    with state.connect(store[0]) as conn:
        _initialize_database(conn, is_existing_db=True, schema_only=True)
        conn.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='worldinfo'")
    return roots, build, worker


def _run_world_worker_once(worker, monkeypatch):
    from core.context import ctx
    class StopWorker(Exception):
        pass
    calls = []
    def wait(_timeout):
        if calls:
            raise StopWorker()
        calls.append(True)
        return True
    monkeypatch.setattr(ctx, 'index_upgrade_active', False)
    monkeypatch.setattr(ctx.index_wakeup, 'wait', wait)
    with pytest.raises(StopWorker):
        worker.worker_loop()


@pytest.mark.parametrize('storage_state', ['root_offline', 'child_unreadable', 'file_deleted', 'folder_deleted'])
def test_card_recovery_requires_confirmed_deletion(store, tmp_path, monkeypatch, storage_state):
    from flask import Flask, g
    from core.services import cache_service

    roots, build, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    folder = roots['cards'] / 'nested'
    folder.mkdir()
    card = folder / 'hero.json'
    card.write_text(json.dumps({'spec': 'chara_card_v3', 'spec_version': '3.0',
                               'data': {'name': 'Hero', 'description': 'old body'}}))
    with state.connect(store[0]) as conn:
        conn.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='cards'")
        with Flask(__name__).app_context():
            g.db = conn
            assert cache_service.update_card_cache('nested/hero.json', str(card))['cache_updated']
            g.pop('db')
        conn.execute("UPDATE card_metadata SET is_favorite=1 WHERE id='nested/hero.json'")
        conn.commit()
        build.apply_card_increment(conn, 'nested/hero.json', str(card))
        identity = tuple(conn.execute('SELECT is_favorite,card_uid FROM card_metadata').fetchone())
        conn.execute('DELETE FROM index_jobs')
    job_id = worker.prepare_card_file_intent(str(card))
    card.write_text(json.dumps({'spec': 'chara_card_v3', 'spec_version': '3.0',
                               'data': {'name': 'Hero', 'description': 'NEW BODY'}}))

    offline = tmp_path / 'offline'
    if storage_state == 'root_offline':
        roots['cards'].rename(offline)
    else:
        card.unlink()
        if storage_state == 'folder_deleted':
            folder.rmdir()
    with monkeypatch.context() as unavailable:
        if storage_state == 'child_unreadable':
            walk = build.walk_directory_strict
            def denied(root):
                yield from walk(root)
                raise PermissionError('child cannot be enumerated')
            unavailable.setattr(build, 'walk_directory_strict', denied)
        _run_world_worker_once(worker, unavailable)
    with state.connect(store[0]) as conn:
        actual_identity = [tuple(row) for row in conn.execute('SELECT is_favorite,card_uid FROM card_metadata')]
        status, error = conn.execute('SELECT status,error_msg FROM index_jobs WHERE id=?', (job_id,)).fetchone()
        if storage_state in ('file_deleted', 'folder_deleted'):
            assert actual_identity == []
            assert status == 'done'
            assert conn.execute("SELECT COUNT(*) FROM index_entities_v2 WHERE entity_type='card'").fetchone()[0] == 0
            return
        assert actual_identity == [identity]
        assert status == 'failed' and error
        assert conn.execute("SELECT favorite FROM index_entities_v2 WHERE entity_id='card::nested/hero.json'").fetchone()[0] == 1
    if storage_state == 'root_offline':
        offline.rename(roots['cards'])
    else:
        card.write_text(json.dumps({'spec': 'chara_card_v3', 'spec_version': '3.0',
                                   'data': {'name': 'Hero', 'description': 'NEW BODY'}}))
    with state.connect(store[0]) as conn:
        conn.execute('UPDATE index_jobs SET finished_at=0 WHERE id=?', (job_id,))
    _run_world_worker_once(worker, monkeypatch)
    with state.connect(store[0]) as conn:
        assert tuple(conn.execute('SELECT is_favorite,card_uid FROM card_metadata').fetchone()) == identity
        assert conn.execute('SELECT description FROM card_metadata').fetchone()[0] == 'NEW BODY'
        assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (job_id,)).fetchone()[0] == 'done'


def test_group_lock_wait_releases_destination_before_waiting_for_source(monkeypatch):
    import threading
    from core.context import ctx
    from core.services import card_operation_lock as locks

    monkeypatch.setattr(ctx, 'card_locks', {})
    monkeypatch.setattr(ctx, 'card_locks_guard', threading.Lock())
    acquired, source = locks.try_acquire_card_lock('hero.png')
    assert acquired
    waiting = threading.Event()
    finished = threading.Event()
    acquire = locks.try_acquire_card_lock
    def observed(card_id, **kwargs):
        if card_id == 'hero.png' and kwargs.get('blocking'):
            waiting.set()
        return acquire(card_id, **kwargs)
    monkeypatch.setattr(locks, 'try_acquire_card_lock', observed)
    def recover():
        with locks.card_locks(['hero.png', '0hero.png']):
            finished.set()
    thread = threading.Thread(target=recover, daemon=True)
    thread.start()
    try:
        assert waiting.wait(5)
        # The source writer can synchronously write its conflict-resolved new ID.
        acquired, destination = acquire('0hero.png')
        assert acquired, 'worker retained destination lock while waiting for source'
        locks.release_card_lock(destination)
        assert not finished.is_set()
    finally:
        locks.release_card_lock(source)
        thread.join(5)
    assert not thread.is_alive() and finished.is_set()


def test_resolved_move_conflict_preserves_source_and_does_not_publish_intent(store, tmp_path, monkeypatch):
    import threading
    from core.context import ctx
    from core.services import card_operation_lock as locks

    roots, _, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    monkeypatch.setattr(ctx, 'card_locks', {})
    source, destination = roots['cards'] / 'hero.json', roots['cards'] / '0hero.json'
    source.write_text('{"name":"original"}')
    ready, release = threading.Event(), threading.Event()
    def other_writer():
        with locks.card_locks(['0hero.json']):
            ready.set()
            release.wait(10)
    thread = threading.Thread(target=other_writer, daemon=True)
    thread.start()
    try:
        assert ready.wait(5)
        with locks.card_locks(['hero.json']), locks.file_intent_scope():
            with pytest.raises(RuntimeError, match='正在使用'):
                worker.prepare_card_file_intent(str(destination), old_path=str(source), operation_kind='rename')
        assert source.read_text() == '{"name":"original"}' and not destination.exists()
        with state.connect(store[0]) as conn:
            assert conn.execute('SELECT COUNT(*) FROM index_jobs').fetchone()[0] == 0
    finally:
        release.set()
        thread.join(5)
    assert not thread.is_alive()


@pytest.mark.parametrize('payload,expected', [
    ({'id': 'z/hero.png', 'new_filename': '0hero.png'}, ['z/hero.png', 'z/0hero.png']),
    ({'old_path': 'z/pack', 'new_name': '0pack'}, ['z/pack/hero.png', 'z/0pack/hero.png']),
    ({'source_path': 'z/pack', 'target_parent_path': 'a'}, ['z/pack/hero.png', 'a/pack/hero.png']),
    ({'card_id': 'z/hero.png', 'bundle_name': '0pack'}, ['z/hero.png', 'z/0pack/hero.png']),
])
def test_request_holds_destination_locks_before_file_intent(monkeypatch, payload, expected):
    import threading
    from flask import Flask
    from types import SimpleNamespace
    from core.context import ctx
    from core.services import card_operation_lock as locks

    monkeypatch.setattr(ctx, 'card_locks', {})
    monkeypatch.setattr(ctx, 'card_locks_guard', threading.Lock())
    monkeypatch.setattr(ctx, 'cache', SimpleNamespace(id_map={'z/pack/hero.png': {}}, lock=threading.RLock()))
    app = Flask(__name__)
    @locks.request_card_locks
    def publish():
        for card_id in expected:
            assert ctx.card_locks[card_id]._is_owned(), card_id
        return True
    with app.test_request_context(json=payload):
        assert publish()
    assert all(not lock._is_owned() for lock in ctx.card_locks.values())


@pytest.mark.parametrize('owner_state', ['deleted', 'file_without_metadata', 'inaccessible'])
def test_obsolete_owner_and_access_failure_do_not_block_other_world_jobs(store, tmp_path, monkeypatch, owner_state):
    roots, build, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    card = roots['cards'] / 'hero.json'
    card.write_text(json.dumps({'spec': 'chara_card_v3', 'spec_version': '3.0',
        'data': {'name': 'Hero', 'description': 'body',
        'character_book': {'name': 'OwnerBook', 'entries': [{'content': 'owner'}]}}}))
    other = roots['worlds'] / 'other.json'
    other.write_text('{"name":"OldOtherBook","entries":{}}')
    with state.connect(store[0]) as conn:
        conn.execute("INSERT INTO card_metadata(id,char_name,has_character_book,character_book_name) "
                     "VALUES ('hero.json','Hero',1,'OwnerBook')")
        conn.commit()
        build.apply_worldinfo_embedded_increment(conn, 'hero.json', str(card))
        build.apply_worldinfo_path_increment(conn, str(other))
        assert conn.execute("SELECT name FROM index_entities_v2 WHERE entity_type='world_embedded'").fetchone()[0] == 'OwnerBook'
        conn.execute("DELETE FROM card_metadata WHERE id='hero.json'")
    if owner_state != 'file_without_metadata':
        card.unlink()
    if owner_state == 'inaccessible':
        walk = build.walk_directory_strict
        def denied(root):
            if str(root) == str(roots['cards']):
                raise PermissionError('card directory is inaccessible')
            yield from walk(root)
        monkeypatch.setattr(build, 'walk_directory_strict', denied)
    other.write_text('{"name":"NewOtherBook","entries":{}}')
    worker.enqueue_index_job('upsert_world_embedded', entity_id='hero.json', source_path=str(card))
    worker.enqueue_index_job('upsert_world_owner', entity_id='hero.json', source_path=str(card),
                             payload={'remove_owner_ids': ['hero.json']})
    worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(other))
    for _ in range(2):
        with state.connect(store[0]) as conn:
            conn.execute("UPDATE index_jobs SET finished_at=0 WHERE status='failed'")
        _run_world_worker_once(worker, monkeypatch)
        with state.connect(store[0]) as conn:
            names = [row[0] for row in conn.execute("SELECT name FROM index_entities_v2 ORDER BY name")]
            statuses = [row[0] for row in conn.execute('SELECT status FROM index_jobs ORDER BY id')]
        if owner_state == 'deleted':
            assert names == ['NewOtherBook']
            assert statuses == ['done', 'done', 'done']
        else:
            assert names == ['NewOtherBook', 'OwnerBook']
            assert statuses == ['failed', 'failed', 'done']


def test_split_retry_keeps_shared_resource_owners_atomic(store, tmp_path, monkeypatch):
    roots, build, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    shared = roots['resources'] / 'shared' / 'lorebooks' / 'book.json'
    shared.parent.mkdir(parents=True)
    shared.write_text('{"name":"OldShared","entries":{}}')
    other = roots['worlds'] / 'other.json'
    other.write_text('{"name":"OldOther","entries":{}}')
    for name in ('a.json', 'b.json'):
        (roots['cards'] / name).write_text(json.dumps({'spec': 'chara_card_v3', 'spec_version': '3.0',
            'data': {'name': name, 'description': 'body',
            'character_book': {'name': name, 'entries': [{'content': 'embedded'}]}}}))
    with state.connect(store[0]) as conn:
        conn.executemany('INSERT INTO card_metadata(id,char_name,has_character_book) VALUES (?,?,1)',
                         [('a.json', 'A'), ('b.json', 'B')])
    state.Repository().replace_snapshot({name: {'resource_folder': 'shared'} for name in ('a.json', 'b.json')})
    with state.connect(store[0]) as conn:
        for name in ('a.json', 'b.json'):
            build.apply_worldinfo_owner_increment(conn, name, str(roots['cards'] / name))
        build.apply_worldinfo_path_increment(conn, str(other))
        conn.execute('DELETE FROM index_jobs')
    shared.write_text('{"name":"NewShared","entries":{}}')
    other.write_text('{"name":"NewOther","entries":{}}')
    monkeypatch.setattr(worker, 'classify_worldinfo_path',
                        lambda path: {'kind': 'resource' if path == str(shared) else 'global'})
    monkeypatch.setattr(worker, 'resolve_resource_worldinfo_owner_card_ids', lambda _path, **_: ['a.json', 'b.json'])
    prepare = build._prepared_world_file
    def fail_second_owner(path, **kwargs):
        if str(path) == str(roots['cards'] / 'b.json'):
            raise PermissionError('second shared owner is inaccessible')
        return prepare(path, **kwargs)
    monkeypatch.setattr(build, '_prepared_world_file', fail_second_owner)
    worker.enqueue_index_job('upsert_world_owner', entity_id='a.json', source_path=str(shared))
    worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(other))
    _run_world_worker_once(worker, monkeypatch)
    with state.connect(store[0]) as conn:
        assert [row[0] for row in conn.execute("SELECT name FROM index_entities_v2 WHERE entity_type='world_resource'")] == ['OldShared', 'OldShared']
        assert conn.execute("SELECT name FROM index_entities_v2 WHERE entity_type='world_global'").fetchone()[0] == 'NewOther'
        assert [row[0] for row in conn.execute('SELECT status FROM index_jobs ORDER BY id')] == ['failed', 'done']
        conn.execute("UPDATE index_jobs SET finished_at=0 WHERE status='failed'")
    monkeypatch.setattr(build, '_prepared_world_file', prepare)
    _run_world_worker_once(worker, monkeypatch)
    with state.connect(store[0]) as conn:
        assert [row[0] for row in conn.execute("SELECT name FROM index_entities_v2 WHERE entity_type='world_resource'")] == ['NewShared', 'NewShared']
        assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE status!='done'").fetchone()[0] == 0


@pytest.mark.parametrize('window', [
    'identical_existing_target', 'invalid_committed_target', 'changed_target',
    'changed_source', 'cleanup_retry', 'legacy_without_evidence',
])
def test_conversion_recovery_preserves_source_until_valid_committed_target(store, tmp_path, monkeypatch, window):
    import os
    import shutil
    from flask import Flask
    from core import config
    from core.context import ctx
    from core.data.cache import GlobalMetadataCache
    from core.data.db_session import _initialize_database
    from core.services import index_job_worker as worker, index_build_service as build
    from core.services import cache_service
    from core.utils.data import normalize_card_v3

    db = store[0]
    root = tmp_path / 'cards'
    root.mkdir()
    old, target, staged = root / 'hero.json', root / 'hero.png', root / 'prepared.png.tmp'
    body = normalize_card_v3({'data': {'name': 'Hero', 'description': 'only original body'}})
    old.write_text(json.dumps(body), encoding='utf-8')
    original = old.read_bytes()
    Image.new('RGB', (8, 8), 'blue').save(target)
    Image.new('RGB', (8, 8), 'red').save(staged, 'PNG')
    if window != 'invalid_committed_target':
        assert write_card_metadata(str(staged), body, prepare_intent=False)
    if window == 'identical_existing_target':
        shutil.copyfile(staged, target)
        stamp = staged.stat()
        os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))

    monkeypatch.setattr(config, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(worker, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(build, 'CARDS_FOLDER', str(root))
    monkeypatch.setattr(ctx, 'cache', GlobalMetadataCache())
    state.initialize()
    with state.connect(db) as conn:
        _initialize_database(conn, is_existing_db=True, schema_only=True)
        conn.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='cards'")
    with Flask(__name__).app_context():
        from flask import g
        with state.connect(db) as conn:
            g.db = conn
            assert cache_service.update_card_cache('hero.json', str(old))['cache_updated']
            g.pop('db')
    state.Repository().update_fields('hero.json', {'summary': 'keep me', 'chat_ids': ['chat']})
    job_id = worker.prepare_card_file_intent(str(target), old_path=str(old), operation_kind='convert',
                                             prepared_path=str(staged))
    with worker._connect() as conn:
        row = conn.execute('SELECT * FROM index_jobs WHERE id=?', (job_id,)).fetchone()
    payload = json.loads(row['payload_json'])
    if window == 'identical_existing_target':
        assert payload['prepared_output']['sha256'] == payload['target_before']['sha256']
        assert payload['prepared_output']['inode'] != payload['target_before']['inode']
        worker.process_card_job(row, payload)
    elif window == 'changed_target':
        assert write_card_metadata(str(target), {'data': {'name': 'Other'}}, prepare_intent=False)
        with pytest.raises(RuntimeError, match='无法确认转换已提交'):
            worker.process_card_job(row, payload)
    elif window == 'legacy_without_evidence':
        payload.pop('prepared_output')
        with pytest.raises(RuntimeError, match='缺少输出身份凭据'):
            worker.process_card_job(row, payload)
    else:
        os.replace(staged, target)
        if window == 'changed_source':
            old.write_text(json.dumps({'name': 'concurrent edit'}), encoding='utf-8')
            original = old.read_bytes()
            with pytest.raises(RuntimeError, match='转换源文件已变化'):
                worker.process_card_job(row, payload)
        elif window == 'invalid_committed_target':
            with pytest.raises(ValueError, match='不是合法角色卡'):
                worker.process_card_job(row, payload)
        else:
            remove = os.remove
            with monkeypatch.context() as failure:
                def deny_source(path):
                    if str(path) == str(old):
                        raise PermissionError('source cleanup unavailable')
                    return remove(path)
                failure.setattr(os, 'remove', deny_source)
                with pytest.raises(PermissionError):
                    worker.process_card_job(row, payload)
            assert old.read_bytes() == original
            assert state.Repository().get('hero.png')['chat_ids'] == ['chat']
            with worker._connect() as conn:
                assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (job_id,)).fetchone()[0] == 'pending'
            worker.process_card_job(row, payload)
            assert not old.exists()
            assert extract_card_info(str(target))['data']['description'] == 'only original body'
            return

    assert old.read_bytes() == original
    assert state.Repository().get('hero.json')['chat_ids'] == ['chat']
    with worker._connect() as conn:
        assert conn.execute("SELECT description FROM card_metadata WHERE id='hero.json'").fetchone()[0] == 'only original body'



def test_namespace_rebase_keeps_transaction_revision_not_later_writer(store, monkeypatch):
    repo = state.Repository()
    repo.replace_snapshot({'_notes': {'one': 'old'}})
    snapshot = ui_store.load_ui_data()
    snapshot['_notes']['one'] = 'new'
    assert repo.save(snapshot)
    repo.update_fields('_notes', {'two': 'concurrent'})
    snapshot['_notes'] = {'one': 'replace'}
    with pytest.raises(state.StateConflict):
        repo.save(snapshot)
    assert repo.export_snapshot()['_notes']['two'] == 'concurrent'


@pytest.mark.parametrize('commit', [False, True])
def test_namespace_read_uses_outer_transaction_and_survives_connection_close(store, monkeypatch, commit):
    repo = state.Repository()
    repo.replace_snapshot({'_notes': {'summary': 'before', 'opaque': {'enabled': True}}})
    with state.connect(store[0]) as conn:
        conn.execute('BEGIN IMMEDIATE')
        repo.update_fields('_notes', {'summary': 'inside', 'new': ['value']}, conn=conn)
        def unexpected_connection(*args, **kwargs):
            raise AssertionError('namespace escaped its transaction')
        with monkeypatch.context() as patch:
            patch.setattr(state, 'connect', unexpected_connection)
            snapshot = repo.get('_notes', conn=conn)
            assert snapshot['summary'] == 'inside'
        revision = snapshot.root_revision
        assert revision == conn.execute("SELECT revision FROM ui_records WHERE key='_notes'").fetchone()[0]
        conn.commit() if commit else conn.rollback()
    repo.update_fields('_notes', {'late': 'newer transaction'})
    assert state.plain(snapshot.copy()) == {'summary': 'inside', 'opaque': {'enabled': True}, 'new': ['value']}
    assert 'late' not in snapshot and snapshot.get('late') is None
    assert repo.get('_notes')['summary'] == ('inside' if commit else 'before')


def test_frozen_namespace_retains_authoritative_decode_error(store):
    repo = state.Repository()
    repo.replace_snapshot({'_notes': {'summary': 'before'}})
    with state.connect(store[0]) as conn:
        conn.execute("UPDATE ui_namespace_records SET payload_json='broken' WHERE namespace='_notes'")
    snapshot = repo.get('_notes')
    with pytest.raises(state.LocalStateError, match='权威命名空间读取失败'):
        snapshot.get('summary')


@pytest.mark.parametrize('kind', ['card', 'folder', 'bundle'])
def test_namespace_crash_recovery_projects_committed_note_and_revision(tmp_path, kind):
    import subprocess
    import sys
    helper = Path(__file__).with_name('phase_two_crash_helper.py')
    crash = subprocess.run([sys.executable, '-X', 'utf8', str(helper), str(tmp_path), 'namespace_recovery',
                            kind + ':crash'], capture_output=True, timeout=60)
    assert crash.returncode == 73, crash.stdout + crash.stderr
    recovery = subprocess.run([sys.executable, '-X', 'utf8', str(helper), str(tmp_path), 'namespace_recovery',
                               kind + ':recover'], capture_output=True, timeout=60)
    assert recovery.returncode == 0, recovery.stdout + recovery.stderr


@pytest.mark.parametrize('operation', ['merge', 'conflict'])
def test_real_chat_requests_merge_progress_but_reject_conflicting_notes(tmp_path, operation):
    import subprocess
    import sys
    helper = Path(__file__).with_name('phase_two_crash_helper.py')
    result = subprocess.run([sys.executable, '-X', 'utf8', str(helper), str(tmp_path),
                             'chat_concurrent_save', operation], capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def test_chat_derived_timestamp_merge_does_not_weaken_nested_conflicts(store):
    repo = state.Repository('chat')
    repo.replace_snapshot({'chat': {'notes': 'original', 'last_view_floor': 0,
                                   'metadata': {'updated_at': 'business value'}, 'updated_at': 1}})
    first, second = chat_store.load_chat_data(), chat_store.load_chat_data()
    first['chat'].update(notes='note', updated_at=2)
    second['chat'].update(last_view_floor=9, updated_at=3)
    assert repo.save(second) and repo.save(first)
    stored = repo.get('chat')
    assert stored['notes'] == 'note' and stored['last_view_floor'] == 9 and stored['updated_at'] >= 3
    first, second = chat_store.load_chat_data(), chat_store.load_chat_data()
    first['chat']['metadata']['updated_at'] = 'first'
    second['chat']['metadata']['updated_at'] = 'second'
    assert repo.save(second)
    with pytest.raises(state.StateConflict):
        repo.save(first)
    assert repo.get('chat')['metadata']['updated_at'] == 'second'


@pytest.mark.parametrize('operation', ['list', 'detail', 'range', 'update_meta', 'bind', 'import', 'save', 'delete'])
def test_chat_routes_reject_actual_local_state_write_failure(store, tmp_path, monkeypatch, operation):
    import io
    from flask import Flask
    from core.api.v1 import chats
    root = tmp_path/'chats'
    path = root/'Hero/test.jsonl'
    path.parent.mkdir(parents=True)
    content = (json.dumps({'user_name': 'User', 'character_name': 'Hero'}) + '\n' +
               json.dumps({'name': 'Hero', 'is_user': False, 'mes': 'hello'}) + '\n')
    path.write_text(content, encoding='utf-8')
    monkeypatch.setattr(chats, 'CHATS_FOLDER', str(root))
    monkeypatch.setattr(chats, 'TRASH_FOLDER', str(tmp_path/'trash'))
    monkeypatch.setattr(chats, '_current_card_ui_identities', lambda: None)
    repo = state.Repository('chat')
    repo.replace_snapshot({'Hero/test.jsonl': {'notes': 'keep'}} if operation == 'delete' else {})
    with state.connect(store[0]) as conn:
        for event in ('INSERT', 'DELETE'):
            conn.execute(f"CREATE TRIGGER reject_chat_{event.lower()} BEFORE {event} ON chat_local_state "
                         "BEGIN SELECT RAISE(ABORT, 'local state unavailable'); END")
    calls = []
    def save(data):
        result = chat_store.save_chat_data(data)
        calls.append(result)
        return result
    monkeypatch.setattr(chats, 'save_chat_data', save)
    app = Flask(__name__)
    app.register_blueprint(chats.bp)
    client = app.test_client()
    if operation == 'list':
        reply = client.get('/api/chats/list').get_json()
    elif operation == 'import':
        reply = client.post('/api/chats/import', data={'files': (io.BytesIO(content.encode()), 'import.jsonl')}).get_json()
    else:
        reply = client.post('/api/chats/' + operation, json={'id': 'Hero/test.jsonl', 'notes': 'draft',
            'unbind': True, 'raw_messages': [{'name': 'Hero', 'is_user': False, 'mes': 'changed'}]}).get_json()
    assert calls == [False]
    assert reply['success'] is False and '未保存' in reply['msg'], reply
    assert repo.get('Hero/test.jsonl', {}).get('notes') == ('keep' if operation == 'delete' else None)


@pytest.mark.parametrize('targeted', [False, True])
@pytest.mark.parametrize('concurrent', ['before_save', 'after_save', 'none'])
def test_reused_namespace_snapshot_rename_never_loses_concurrent_note(store, targeted, concurrent):
    repo = state.Repository()
    key = ui_store.WORLDINFO_NOTES_KEY
    repo.replace_snapshot({key: {'embedded::hero.png': {'summary': 'original', 'opaque': 'preserve'}}})
    snapshot = ui_store.load_ui_data()
    if not targeted:
        snapshot[key]  # Explicit full compatibility snapshot.
    assert ui_store.set_worldinfo_note(snapshot, 'embedded', 'mine', card_id='hero.png')
    if concurrent == 'before_save':
        repo.update_fields(key, {'embedded::other.png': {'summary': 'concurrent'}})
    assert repo.save(snapshot)
    if concurrent == 'after_save':
        repo.update_fields(key, {'embedded::other.png': {'summary': 'concurrent'}})
    try:
        assert ui_store.rename_embedded_worldinfo_note_card_prefix(snapshot, 'hero.png', 'renamed.png')
        repo.save(snapshot)
    except state.StateConflict:
        snapshot = ui_store.load_ui_data()
        assert ui_store.rename_embedded_worldinfo_note_card_prefix(snapshot, 'hero.png', 'renamed.png')
        assert repo.save(snapshot)
    notes = repo.export_snapshot()[key]
    assert notes['embedded::renamed.png']['summary'] == 'mine'
    assert notes['embedded::renamed.png']['opaque'] == 'preserve'
    assert 'embedded::hero.png' not in notes
    assert notes.get('embedded::other.png') == (None if concurrent == 'none' else {'summary': 'concurrent'})


@pytest.mark.parametrize('commit', [False, True])
def test_targeted_namespace_commit_confirmation_and_expansion(store, commit):
    repo = state.Repository()
    repo.replace_snapshot({'_notes': {'one': {'a': 'original', 'b': 'original'}, 'unseen': 'before'}})
    snapshot = ui_store.load_ui_data()
    entry = snapshot.namespace_members('_notes', ['one', 'absent'])
    entry['one']['a'] = 'mine'
    # Merge another field of the observed member, plus an unobserved member.
    repo.update_fields('_notes', {'one': {'a': 'original', 'b': 'concurrent'}, 'unseen': 'concurrent'})
    with repo.transaction() as conn:
        assert repo.save(snapshot, conn=conn)
        if not commit:
            conn.rollback()
    if not commit:
        assert repo.get('_notes')['one']['a'] == 'original'
        assert repo.save(snapshot)
    else:
        snapshot.confirm_saved()
    # Confirmation uses the exact committing transaction, including merged fields.
    assert entry['one'] == {'a': 'mine', 'b': 'concurrent'}
    assert entry.get('absent') is None
    assert entry.copy()['unseen'] == 'concurrent'
    repo.update_fields('_notes', {'late': 'later transaction'})
    with pytest.raises(state.StateConflict):
        entry.get('late')


def test_targeted_namespace_reads_uncommitted_members_from_supplied_connection(store, monkeypatch):
    repo = state.Repository()
    repo.replace_snapshot({'_notes': {'one': 'before', 'two': 'unseen'}})
    with repo.transaction() as conn:
        repo.update_fields('_notes', {'one': 'inside'}, conn=conn)
        with monkeypatch.context() as patch:
            patch.setattr(state, 'connect', lambda *a, **kw: pytest.fail('escaped transaction'))
            entry = repo.get_namespace_members('_notes', ['one', 'missing'], conn=conn)
            assert entry['one'] == 'inside' and entry.get('missing') is None
        conn.rollback()
    assert entry['one'] == 'inside'  # Captured values survive rollback/connection close.
    with pytest.raises(state.StateConflict):
        entry['two']  # Expansion cannot mix the rolled-back root with a later view.


@pytest.mark.parametrize('initial', [None, ['opaque'], {'embedded::hero.png': {'summary': 'before'}}])
def test_targeted_note_preserves_unknown_root_types_and_missing_baselines(store, initial):
    repo = state.Repository()
    repo.replace_snapshot({ui_store.WORLDINFO_NOTES_KEY: initial})
    snapshot = ui_store.load_ui_data()
    assert ui_store.set_worldinfo_note(snapshot, 'embedded', 'after', card_id='hero.png')
    assert repo.save(snapshot)
    assert ui_store.get_worldinfo_note(ui_store.load_ui_data(), 'embedded', card_id='hero.png')['summary'] == 'after'


def _world_note_client(store, tmp_path, monkeypatch, source):
    from flask import Flask
    from core.api.v1 import world_info
    roots, build, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    cfg = {'world_info_dir': str(roots['worlds']), 'resources_dir': str(roots['resources'])}
    monkeypatch.setattr(world_info, 'load_config', lambda: cfg)
    monkeypatch.setattr(world_info, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(world_info, 'CARDS_FOLDER', str(roots['cards']))
    book = (roots['resources']/'assets/lorebooks/book.json' if source == 'resource'
            else roots['worlds']/'book.json')
    book.parent.mkdir(parents=True, exist_ok=True)
    book.write_text('{"name":"Book","entries":{}}', encoding='utf-8')
    app = Flask(__name__)
    app.register_blueprint(world_info.bp)
    target = {'source_type': source, **({'card_id': 'hero.png'} if source == 'embedded'
                                      else {'file_path': str(book)})}
    return app, world_info, worker, target


@pytest.mark.parametrize('concurrent', ['unrelated', 'source_edit', 'source_delete', 'target', 'storage_failure'])
def test_resource_folder_rename_keeps_disk_state_notes_and_search_consistent(
    store, tmp_path, monkeypatch, concurrent,
):
    from contextlib import closing
    from threading import Event

    from core.api.v1 import system
    from core.services import card_service, index_build_service as build, wi_entry_history_service as history
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    app.register_blueprint(system.bp)
    old_book = Path(target['file_path'])
    resources = old_book.parents[2]
    new_book = resources / 'glasshouse' / 'lorebooks' / old_book.name
    global_book = tmp_path / 'worlds' / 'other.json'
    global_book.write_text('{"name":"Other","entries":{}}', encoding='utf-8')
    cfg = {'world_info_dir': str(global_book.parent), 'resources_dir': str(resources)}
    card_id = 'Hero.json'
    card = tmp_path / 'cards' / card_id
    card.write_text('{"spec":"chara_card_v3","spec_version":"3.0","data":{"name":"Hero"}}', encoding='utf-8')
    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(card.parent))
    monkeypatch.setattr(card_service, 'DEFAULT_DB_PATH', str(store[0]))
    monkeypatch.setattr(card_service, 'load_config', lambda: cfg)
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *_args: None)
    monkeypatch.setattr(history, 'DEFAULT_DB_PATH', str(store[0]))
    monkeypatch.setattr(history, 'load_config', lambda: cfg)
    repo = state.Repository()
    repo.update_fields(card_id, {'resource_folder': 'assets'})
    with closing(state.connect(store[0])) as conn, conn:
        conn.execute('INSERT INTO card_metadata(id,char_name,category) VALUES (?,?,?)', (card_id, 'Hero', ''))
        assert build.build_worldinfo_generation(conn, 1) == 2

    def save_note(book, summary, source='resource'):
        return app.test_client().post('/api/world_info/note/save', json={
            'source_type': source, 'file_path': str(book), 'summary': summary,
        })

    def rename():
        return app.test_client().post('/api/rename_resource_folder', json={
            'card_id': card_id, 'new_name': 'glasshouse',
        })

    def matches(query):
        return [[Path(item['path']) for item in query_worldinfo_index({
            'db_path': str(store[0]), 'search': query, 'search_mode': mode,
        })['items']] for mode in ('fast', 'fulltext')]

    assert save_note(old_book, 'originalmarker').get_json()['success']
    _run_world_worker_once(worker, monkeypatch)
    assert matches('originalmarker') == [[old_book], [old_book]]
    assert history.append_entry_history_records('resource', '', str(old_book), [
        {'entry_uid': '1', 'snapshot': {'content': 'old entry'}},
    ]) == 1

    notes = state.NamespaceRepository(ui_store.WORLDINFO_NOTES_KEY)
    old_key = ui_store.build_worldinfo_note_key('resource', old_book)
    new_key = ui_store.build_worldinfo_note_key('resource', new_book)
    sibling_key = ui_store.build_worldinfo_note_key('resource', resources / 'assets-extra' / 'book.json')
    notes.update_fields(sibling_key, {'summary': 'neighbor', 'opaque': True})
    started, release = Event(), Event()
    save = card_service.save_ui_data

    def pause_save(*args, **kwargs):
        started.set()
        assert release.wait(10), 'resource rename was not released'
        return save(*args, **kwargs)

    monkeypatch.setattr(card_service, 'save_ui_data', pause_save)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(rename)
        try:
            assert started.wait(10), 'resource rename did not reach authoritative save'
            assert new_book.is_file() and not old_book.exists()
            if concurrent == 'unrelated':
                assert save_note(global_book, 'globalmarker', source='global').get_json()['success']
            elif concurrent == 'source_edit':
                notes.update_fields(old_key, {'summary': 'latestmarker', 'opaque': {'extension': True}})
            elif concurrent == 'source_delete':
                notes.delete(old_key)
            elif concurrent == 'target':
                result = save_note(new_book, 'occupiedmarker')
                assert result.status_code == 409 and result.get_json()['retryable']
                # Preserve a destination note even if it was introduced by a direct repository writer.
                notes.update_fields(new_key, {'summary': 'occupiedmarker'})
            elif concurrent == 'storage_failure':
                with closing(state.connect(store[0])) as conn, conn:
                    conn.execute(
                        "CREATE TRIGGER reject_resource_note_move BEFORE UPDATE OF key ON ui_namespace_records "
                        "BEGIN SELECT RAISE(ABORT, 'note storage unavailable'); END"
                    )
        finally:
            release.set()
        response = future.result(timeout=10)

    if concurrent in ('target', 'storage_failure'):
        assert response.status_code == 400 and not response.get_json()['success']
        assert old_book.is_file() and not new_book.exists()
        assert repo.get(card_id)['resource_folder'] == 'assets'
        assert notes.get(old_key)['summary'] == 'originalmarker'
        assert matches('originalmarker') == [[old_book], [old_book]]
        assert history.list_entry_history_records('resource', '', str(old_book), '1')
        assert not history.list_entry_history_records('resource', '', str(new_book), '1')
        with closing(state.connect(store[0])) as conn, conn:
            assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE job_type='upsert_world_owner'").fetchone()[0] == 0
            if concurrent == 'storage_failure':
                assert notes.get(new_key) is None
                conn.execute('DROP TRIGGER reject_resource_note_move')
        if concurrent == 'target':
            assert notes.get(new_key)['summary'] == 'occupiedmarker'
            notes.delete(new_key)
        response = rename()

    assert response.status_code == 200 and response.get_json()['success']
    assert new_book.is_file() and not old_book.exists()
    assert repo.get(card_id)['resource_folder'] == 'glasshouse'
    assert not history.list_entry_history_records('resource', '', str(old_book), '1')
    assert history.list_entry_history_records('resource', '', str(new_book), '1')
    assert notes.get(sibling_key) == {'summary': 'neighbor', 'opaque': True}
    assert notes.get(old_key) is None
    with closing(state.connect(store[0])) as conn:
        assert [tuple(row) for row in conn.execute(
            "SELECT entity_id,status FROM index_jobs WHERE job_type='upsert_world_owner'"
        )] == [(card_id, 'pending')]
    _run_world_worker_once(worker, monkeypatch)
    with closing(state.connect(store[0])) as conn:
        assert [Path(row[0]) for row in conn.execute(
            "SELECT source_path FROM index_entities_v2 WHERE generation=1 AND entity_type='world_resource'"
        )] == [new_book]
    if concurrent == 'source_delete':
        assert notes.get(new_key) is None
        assert matches('originalmarker') == [[], []]
    elif concurrent == 'source_edit':
        assert notes.get(new_key)['opaque'] == {'extension': True}
        assert matches('latestmarker') == [[new_book], [new_book]]
        assert matches('originalmarker') == [[], []]
    else:
        assert matches('originalmarker') == [[new_book], [new_book]]
    if concurrent == 'unrelated':
        assert matches('globalmarker') == [[global_book], [global_book]]


def test_resource_folder_rename_queues_refresh_before_card_has_metadata(store, tmp_path, monkeypatch):
    from contextlib import closing
    from threading import Event

    from core.api.v1 import system
    from core.services import card_service

    app, _, _, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    app.register_blueprint(system.bp)
    old_book = Path(target['file_path'])
    resources = old_book.parents[2]
    card_id = 'unscanned.json'
    card = tmp_path / 'cards' / card_id
    card.write_text('{}', encoding='utf-8')
    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(card.parent))
    monkeypatch.setattr(card_service, 'DEFAULT_DB_PATH', str(store[0]))
    monkeypatch.setattr(card_service, 'load_config', lambda: {'resources_dir': str(resources)})
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *_args: None)
    wakeup = Event()
    monkeypatch.setattr(card_service.ctx, 'index_wakeup', wakeup)
    repo = state.Repository()
    repo.update_fields(card_id, {'resource_folder': 'assets'})

    def rename():
        return app.test_client().post('/api/rename_resource_folder', json={
            'card_id': card_id, 'new_name': 'glasshouse',
        })

    with closing(state.connect(store[0])) as conn, conn:
        conn.execute(
            "CREATE TRIGGER reject_owner_job BEFORE INSERT ON index_jobs WHEN NEW.job_type='upsert_world_owner' "
            "BEGIN SELECT RAISE(ABORT, 'owner job unavailable'); END"
        )
    assert rename().status_code == 400
    assert old_book.is_file() and not wakeup.is_set()
    assert repo.get(card_id)['resource_folder'] == 'assets'
    with closing(state.connect(store[0])) as conn, conn:
        conn.execute('DROP TRIGGER reject_owner_job')

    assert rename().status_code == 200
    assert wakeup.is_set()
    with closing(state.connect(store[0])) as conn:
        assert [tuple(row) for row in conn.execute(
            "SELECT entity_id,source_path,status FROM index_jobs WHERE job_type='upsert_world_owner'"
        )] == [(card_id, str(card), 'pending')]


@pytest.mark.skipif(os.name != 'nt', reason='Windows per-directory case sensitivity and aliases')
@pytest.mark.parametrize('case', ['mixed', 'distinct', 'legacy', 'concurrent', 'destination_conflict'])
def test_resource_folder_rename_keeps_worldbook_category_keys(store, tmp_path, monkeypatch, case):
    import subprocess
    from contextlib import closing
    from threading import Event

    from core.api.v1 import system
    from core.services import card_service, index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index
    from core.utils.filesystem import filesystem_path_key

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    app.register_blueprint(system.bp)
    template = Path(target['file_path'])
    template.unlink()
    resources = template.parents[2]
    if case in ('mixed', 'distinct', 'concurrent'):
        for directory in (resources, template.parent):
            result = subprocess.run(['fsutil', 'file', 'SetCaseSensitiveInfo', str(directory), 'enable'],
                                    capture_output=True)
            if result.returncode != 0:
                pytest.skip('temporary filesystem does not allow enabling case sensitivity')
    card_id = 'Hero.json'
    card = tmp_path / 'cards' / card_id
    card.write_text('{"spec":"chara_card_v3","spec_version":"3.0","data":{"name":"Hero"}}', encoding='utf-8')
    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(card.parent))
    monkeypatch.setattr(card_service, 'DEFAULT_DB_PATH', str(store[0]))
    monkeypatch.setattr(card_service, 'load_config', lambda: {'resources_dir': str(resources)})
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *_args: None)
    repo = state.Repository()
    repo.update_fields(card_id, {'resource_folder': 'assets'})
    states = [(template.with_name('Book.json'), 'springmarker', 'spring')]
    if case == 'distinct':
        states.append((template.with_name('BOOK.json'), 'wintermarker', 'winter'))
    for book, marker, _ in states:
        book.write_text(json.dumps({'name': marker, 'entries': {}}), encoding='utf-8')
    other_book = resources / 'unrelated' / 'lorebooks' / 'Other.json'
    if case == 'concurrent':
        other_book.parent.mkdir(parents=True)
        other_book.write_text('{"name":"Other","entries":{}}', encoding='utf-8')
    if case == 'distinct':
        assert not states[0][0].samefile(states[1][0])
    old_book = states[0][0]
    new_book = resources / 'renamed' / 'lorebooks' / old_book.name
    with closing(state.connect(store[0])) as conn, conn:
        conn.execute('INSERT INTO card_metadata(id,char_name,category) VALUES (?,?,?)', (card_id, 'Hero', ''))
        assert build.build_worldinfo_generation(conn, 1) == len(states)

    def classify(book, category):
        response = app.test_client().post('/api/world_info/category/move', json={
            'file_path': str(book), 'source_type': 'resource', 'target_category': category,
        })
        assert response.get_json()['success'], response.get_json()

    def rename():
        return app.test_client().post('/api/rename_resource_folder', json={
            'card_id': card_id, 'new_name': 'renamed',
        })

    namespace = state.NamespaceRepository(ui_store.RESOURCE_ITEM_CATEGORIES_KEY)
    if case == 'legacy':
        namespace_root = {ui_store.RESOURCE_ITEM_CATEGORIES_KEY: {
            'worldinfo': {str(old_book).upper(): {'category': 'spring', 'opaque': True}},
        }}
        assert ui_store.save_ui_data(namespace_root)
    else:
        for book, _, category in states:
            classify(book, category)
        _run_world_worker_once(worker, monkeypatch)

    if case == 'concurrent':
        started, release = Event(), Event()
        name = 'rename_resource_item_category_path_prefix'
        original = getattr(card_service, name)

        def pause(*args, **kwargs):
            started.set()
            assert release.wait(10), 'resource rename was not released'
            return original(*args, **kwargs)

        monkeypatch.setattr(card_service, name, pause)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(rename)
            try:
                assert started.wait(10) and new_book.is_file()
                classify(other_book, 'outside')
            finally:
                release.set()
            response = future.result(timeout=10)
    else:
        if case == 'destination_conflict':
            # A genuine persisted destination override must still be preserved.
            alias = str(new_book.with_name('BOOK.JSON')).replace('\\', '/').lower()
            namespace.update_fields('worldinfo', {alias: {'category': 'outside'}})
        response = rename()

    stored = namespace.get('worldinfo')
    key = lambda book: filesystem_path_key(str(book)).replace('\\', '/')
    if case == 'destination_conflict':
        assert response.status_code == 400 and not response.get_json()['success']
        assert old_book.is_file() and not new_book.exists()
        assert stored[key(old_book)]['category'] == 'spring'
        assert stored[key(new_book)]['category'] == 'outside'
        return

    assert response.status_code == 200 and response.get_json()['success']
    _run_world_worker_once(worker, monkeypatch)
    for book, marker, category in states:
        moved = new_book.with_name(book.name)
        assert moved.is_file() and not book.exists()
        assert stored[key(moved)]['category'] == category
        for mode in ('fast', 'fulltext'):
            items = query_worldinfo_index({'db_path': str(store[0]), 'search': marker, 'search_mode': mode})['items']
            assert [(Path(item['path']), item['display_category']) for item in items] == [(moved, category)]
    if case == 'legacy':
        assert stored[key(new_book)]['opaque'] is True
    if case == 'concurrent':
        assert stored[key(other_book)]['category'] == 'outside'
    assert len(stored) == len(states) + (case == 'concurrent')


@pytest.mark.parametrize('mode', ['worldinfo', 'presets'])
@pytest.mark.parametrize('first', ['rename', 'classification', 'rename_before_validation'])
def test_resource_category_and_rename_ordering(store, tmp_path, monkeypatch, mode, first):
    from collections.abc import Mapping
    from contextlib import closing
    from threading import Event

    from core.api.v1 import presets, system
    from core.services import card_service, index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index
    from core.utils.filesystem import filesystem_path_key

    app, world_info, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    app.register_blueprint(system.bp)
    app.register_blueprint(presets.bp)
    book = Path(target['file_path'])
    book.write_text('{"name":"springmarker","entries":{}}', encoding='utf-8')
    resources = book.parents[2]
    card_id = 'Hero.json'
    card = tmp_path / 'cards' / card_id
    card.write_text('{"spec":"chara_card_v3","spec_version":"3.0","data":{"name":"Hero"}}', encoding='utf-8')
    config = {'resources_dir': str(resources), 'world_info_dir': str(tmp_path / 'worlds')}
    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(card.parent))
    monkeypatch.setattr(card_service, 'DEFAULT_DB_PATH', str(store[0]))
    monkeypatch.setattr(card_service, 'load_config', lambda: config)
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *_args: None)
    monkeypatch.setattr(presets, 'load_config', lambda: config)
    monkeypatch.setattr(presets, '_get_presets_path', lambda: str(tmp_path / 'presets'))
    state.Repository().update_fields(card_id, {'resource_folder': 'assets'})
    with closing(state.connect(store[0])) as conn, conn:
        conn.execute('INSERT INTO card_metadata(id,char_name,category) VALUES (?,?,?)', (card_id, 'Hero', ''))
        assert build.build_worldinfo_generation(conn, 1) == 1

    source = book
    module, endpoint = world_info, 'world_info'
    if mode == 'presets':
        module, endpoint = presets, 'presets'
        source = book.parents[1] / 'presets' / 'Style.json'
        source.parent.mkdir()
        source.write_text('{"name":"Style"}', encoding='utf-8')
    dest = resources / 'renamed' / source.parent.name / source.name

    def classify(path, category=None):
        action = 'move' if category is not None else 'reset'
        return app.test_client().post(f'/api/{endpoint}/category/{action}', json={
            'file_path': str(path), 'source_type': 'resource', 'target_category': category,
        })

    def rename():
        return app.test_client().post('/api/rename_resource_folder', json={
            'card_id': card_id, 'new_name': 'renamed',
        })

    def key(path):
        return filesystem_path_key(str(path)).replace('\\', '/')

    def categories():
        entries = state.NamespaceRepository(ui_store.RESOURCE_ITEM_CATEGORIES_KEY).get(mode, {})
        assert isinstance(entries, Mapping)
        return {path: info['category'] for path, info in entries.items()}

    source_alias = source.with_name(source.name.upper()) if os.name == 'nt' else source
    if first == 'rename':
        assert classify(source, 'spring').get_json()['success']
        _run_world_worker_once(worker, monkeypatch)

    started, release = Event(), Event()
    if first == 'rename':
        paused, name = card_service, 'save_ui_data'
    elif first == 'classification':
        paused, name = module, 'save_ui_data'
    else:
        paused, name = module, '_update_resource_category'
    original = getattr(paused, name)

    def pause(*args, **kwargs):
        if not started.is_set():
            started.set()
            assert release.wait(10), 'resource request was not released'
        return original(*args, **kwargs)

    monkeypatch.setattr(paused, name, pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(rename) if first == 'rename' else pool.submit(classify, source_alias, 'spring')
        try:
            assert started.wait(10), 'resource request did not reach the chosen stage'
            if first == 'rename':
                assert dest.is_file() and not source.exists()
                for reply in (classify(source_alias), classify(dest, 'replacement')):
                    assert reply.status_code == 409 and not reply.get_json()['success']
                    assert '重试' in reply.get_json()['msg']
            elif first == 'classification':
                reply = rename()
                assert not reply.get_json()['success'] and '重试' in reply.get_json()['msg']
                assert source.is_file() and not dest.exists()
            else:
                assert rename().get_json()['success'] and dest.is_file()
        finally:
            release.set()
        result = future.result(timeout=10).get_json()

    if first == 'rename_before_validation':
        assert not result['success'] and '重试' in result['msg']
        assert categories() == {}
        assert classify(dest, 'spring').get_json()['success']
    else:
        assert result['success']
    if first == 'classification':
        assert categories() == {key(source): 'spring'}
        assert rename().get_json()['success']
    assert categories() == {key(dest): 'spring'}
    assert classify(dest).get_json()['success']
    assert categories() == {}
    if mode == 'worldinfo':
        _run_world_worker_once(worker, monkeypatch)
        for search_mode in ('fast', 'fulltext'):
            items = query_worldinfo_index({
                'db_path': str(store[0]), 'search': 'springmarker', 'search_mode': search_mode,
            })['items']
            assert [(Path(item['path']), item['display_category']) for item in items] == [(dest, '')]


@pytest.mark.parametrize('case', ['first_note', 'unrelated_note', 'clear_note', 'rename_first', 'old_request', 'delete_first'])
def test_resource_note_and_rename_ordering(store, tmp_path, monkeypatch, case):
    from contextlib import closing
    from threading import Event

    from core.api.v1 import system
    from core.services import card_service, index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, world_info, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    app.register_blueprint(system.bp)
    source = Path(target['file_path'])
    resources = source.parents[2]
    dest = resources / 'renamed' / 'lorebooks' / source.name
    global_book = tmp_path / 'worlds' / 'other.json'
    global_book.write_text('{"name":"Other","entries":{}}', encoding='utf-8')
    card_id = 'Hero.json'
    card = tmp_path / 'cards' / card_id
    card.write_text('{"spec":"chara_card_v3","spec_version":"3.0","data":{"name":"Hero"}}', encoding='utf-8')
    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(card.parent))
    monkeypatch.setattr(card_service, 'DEFAULT_DB_PATH', str(store[0]))
    monkeypatch.setattr(card_service, 'load_config', lambda: {'resources_dir': str(resources)})
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *_args: None)
    monkeypatch.setattr(world_info, 'suppress_fs_events', lambda *_args: None)
    monkeypatch.setattr(world_info, 'TRASH_FOLDER', str(tmp_path / 'trash'))
    state.Repository().update_fields(card_id, {'resource_folder': 'assets'})
    with closing(state.connect(store[0])) as conn, conn:
        conn.execute('INSERT INTO card_metadata(id,char_name,category) VALUES (?,?,?)', (card_id, 'Hero', ''))
        assert build.build_worldinfo_generation(conn, 1) == 2

    def save_note(path, summary, source_type='resource'):
        return app.test_client().post('/api/world_info/note/save', json={
            'file_path': str(path), 'source_type': source_type, 'summary': summary,
        })

    def rename():
        return app.test_client().post('/api/rename_resource_folder', json={
            'card_id': card_id, 'new_name': 'renamed',
        })

    def delete(path):
        return app.test_client().post('/api/world_info/delete', json={
            'file_path': str(path), 'source_type': 'resource',
        })

    def matches(query):
        return [[Path(item['path']) for item in query_worldinfo_index({
            'db_path': str(store[0]), 'search': query, 'search_mode': mode,
        })['items']] for mode in ('fast', 'fulltext')]

    if case in ('clear_note', 'rename_first', 'delete_first'):
        assert save_note(source, 'oldnotemarker').get_json()['success']
        _run_world_worker_once(worker, monkeypatch)
    if case == 'unrelated_note':
        assert save_note(global_book, 'initialglobalmarker', 'global').get_json()['success']

    if case == 'rename_first':
        paused, name = card_service, 'save_ui_data'
    elif case == 'old_request':
        paused, name = world_info, '_save_file_world_info_note'
    elif case == 'delete_first':
        paused, name = world_info, 'purge_entry_history_scope'
    else:
        paused, name = world_info, 'save_ui_data'
    original = getattr(paused, name)
    started, release = Event(), Event()

    def pause(*args, **kwargs):
        if not started.is_set():
            started.set()
            assert release.wait(10), 'resource request was not released'
        return original(*args, **kwargs)

    monkeypatch.setattr(paused, name, pause)
    # Relative requests are resolved against the same application root as absolute requests.
    source_request = source.relative_to(tmp_path)
    summary = '' if case in ('clear_note', 'delete_first') else 'newnotemarker'
    with ThreadPoolExecutor(max_workers=1) as pool:
        if case == 'rename_first':
            future = pool.submit(rename)
        elif case == 'delete_first':
            future = pool.submit(delete, source_request)
        else:
            future = pool.submit(save_note, source_request, summary)
        try:
            assert started.wait(10), 'resource request did not reach the chosen stage'
            with closing(sqlite3.connect(store[0], timeout=0)) as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                state.Repository('chat').update_fields('unrelated-chat', {'last_view_floor': 7}, conn=conn)
            if case == 'rename_first':
                assert dest.is_file() and not source.exists()
                for reply in (save_note(source_request, ''), save_note(dest, summary)):
                    assert reply.status_code == 409 and reply.get_json()['retryable']
                    assert reply.get_json()['ui_data_saved'] is False
                reply = delete(dest)
                assert reply.status_code == 409 and reply.get_json()['retryable']
            elif case == 'old_request':
                assert rename().get_json()['success'] and dest.is_file()
            else:
                reply = rename()
                assert not reply.get_json()['success'] and '重试' in reply.get_json()['msg']
                assert source.is_file() == (case != 'delete_first') and not dest.exists()
                if case == 'delete_first':
                    assert save_note(source_request, 'newnotemarker').status_code == 409
            if case == 'unrelated_note':
                assert save_note(global_book, 'updatedglobalmarker', 'global').get_json()['success']
        finally:
            release.set()
        reply = future.result(timeout=10).get_json()

    notes = state.NamespaceRepository(ui_store.WORLDINFO_NOTES_KEY)
    source_key = ui_store.build_worldinfo_note_key('resource', source)
    dest_key = ui_store.build_worldinfo_note_key('resource', dest)
    if case == 'old_request':
        assert not reply['success'] and reply['retryable'] and reply['ui_data_saved'] is False
        assert notes.get(source_key) is None and notes.get(dest_key) is None
        assert save_note(dest, summary).get_json()['success']
    else:
        assert reply['success'], reply
    if case not in ('rename_first', 'old_request'):
        if case != 'delete_first':
            assert reply['ui_summary'] == summary
        assert rename().get_json()['success']
    if case == 'rename_first':
        assert notes.get(dest_key)['summary'] == 'oldnotemarker'
        assert save_note(dest, summary).get_json()['success']
    assert dest.is_file() == (case != 'delete_first') and not source.exists()
    assert notes.get(source_key) is None
    assert (notes.get(dest_key, {}) or {}).get('summary', '') == summary
    assert state.Repository('chat').get('unrelated-chat')['last_view_floor'] == 7
    _run_world_worker_once(worker, monkeypatch)
    assert matches('newnotemarker') == ([[dest], [dest]] if summary else [[], []])
    assert matches('oldnotemarker') == [[], []]
    if case == 'unrelated_note':
        assert matches('updatedglobalmarker') == [[global_book], [global_book]]


def _change_global_worldinfo_test_path(app, operation, source):
    client = app.test_client()
    if operation == 'folder':
        return client.post('/api/world_info/folders/rename', json={
            'category': 'OldGarden', 'new_name': 'NewGarden',
        })
    if operation == 'file':
        return client.post('/api/world_info/category/move', json={
            'source_type': 'global', 'file_path': str(source), 'target_category': 'NewGarden',
        })
    # Older callers send only the path; deletion still clears the actual note.
    return client.post('/api/world_info/delete', json={'file_path': str(source)})


@pytest.mark.parametrize('operation', ['folder', 'file', 'delete'])
@pytest.mark.parametrize('ordering', ['note_first', 'operation_first', 'stale_request', 'enqueue_failure'])
def test_global_worldinfo_note_and_path_operations(store, tmp_path, monkeypatch, operation, ordering):
    from contextlib import closing
    from threading import Event

    from core.services import index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, world_info, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    seed = Path(target['file_path'])
    source = seed.parent / 'OldGarden' / seed.name
    source.parent.mkdir()
    seed.rename(source)
    dest = seed.parent / 'NewGarden' / seed.name
    unrelated = seed.parent / 'Other.json'
    unrelated.write_text('{"name":"Other","entries":{}}', encoding='utf-8')
    monkeypatch.setattr(world_info, 'TRASH_FOLDER', str(tmp_path / 'trash'))
    monkeypatch.setattr(world_info, 'suppress_fs_events', lambda *_args: None)
    with closing(state.connect(store[0])) as conn, conn:
        assert build.build_worldinfo_generation(conn, 1) == 2

    def save_note(path, summary, source_type='global'):
        return app.test_client().post('/api/world_info/note/save', json={
            'source_type': source_type, 'file_path': str(path), 'summary': summary,
        })

    def change_path():
        return _change_global_worldinfo_test_path(app, operation, source)

    source_request = source.relative_to(tmp_path)
    saved_marker = 'testglobalnotemarker'
    if ordering in ('operation_first', 'enqueue_failure'):
        assert save_note(source_request, saved_marker).get_json()['success']
        _run_world_worker_once(worker, monkeypatch)
    if ordering == 'enqueue_failure':
        with closing(state.connect(store[0])) as conn, conn:
            conn.execute('''CREATE TRIGGER reject_move_job BEFORE INSERT ON index_jobs
                            WHEN NEW.job_type='upsert_worldinfo_path'
                            BEGIN SELECT RAISE(ABORT, 'injected enqueue failure'); END''')
        reply = change_path().get_json()
        assert not reply['success'] and '重试' in reply['msg']
        assert source.is_file() and not dest.exists()
        with closing(state.connect(store[0])) as conn, conn:
            conn.execute('DROP TRIGGER reject_move_job')
            assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE status='pending'").fetchone()[0] == 0
    else:
        callback = '_save_file_world_info_note' if ordering == 'stale_request' else 'save_ui_data'
        original = getattr(world_info, callback)
        ready, resume = Event(), Event()

        def pause(*args, **kwargs):
            if not ready.is_set():
                ready.set()
                assert resume.wait(10), 'path request was not released'
            return original(*args, **kwargs)

        monkeypatch.setattr(world_info, callback, pause)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = (pool.submit(change_path) if ordering == 'operation_first'
                      else pool.submit(save_note, source_request, saved_marker))
            try:
                assert ready.wait(10), 'path request did not reach the chosen stage'
                if ordering == 'operation_first':
                    assert not source.exists() and dest.is_file() == (operation != 'delete')
                    paths = [source_request] if operation == 'delete' else [source_request, dest]
                    for path in paths:
                        reply = save_note(path, 'rejectedmarker')
                        assert reply.status_code == 409 and reply.get_json()['retryable']
                        assert reply.get_json()['ui_data_saved'] is False
                elif ordering == 'stale_request':
                    assert change_path().get_json()['success']
                else:
                    reply = change_path()
                    assert reply.status_code == 409 and reply.get_json()['retryable']
                    assert source.is_file() and not dest.exists()
                assert not save_note(unrelated, 'wrongnamespace', 'resource').get_json()['success']
                assert save_note(unrelated, 'parallelnotemarker').get_json()['success']
            finally:
                resume.set()
            reply = future.result(timeout=10).get_json()
        if ordering == 'stale_request':
            assert not reply['success'] and reply['retryable'] and reply['ui_data_saved'] is False
            if operation != 'delete':
                assert save_note(dest, saved_marker).get_json()['success']
        else:
            assert reply['success'], reply
        if ordering == 'note_first':
            assert change_path().get_json()['success']

    note_path = source if ordering == 'enqueue_failure' else dest if operation != 'delete' else None
    notes = state.NamespaceRepository(ui_store.WORLDINFO_NOTES_KEY)
    for path in (source, dest):
        note = notes.get(ui_store.build_worldinfo_note_key('global', path))
        assert (note or {}).get('summary') == (saved_marker if path == note_path else None)
        assert path.is_file() == (path == note_path)
    _run_world_worker_once(worker, monkeypatch)
    for mode in ('fast', 'fulltext'):
        for query, matches in [(saved_marker, [note_path] if note_path else []), ('rejectedmarker', []),
                               ('parallelnotemarker', [] if ordering == 'enqueue_failure' else [unrelated])]:
            items = query_worldinfo_index({'db_path': str(store[0]), 'search': query, 'search_mode': mode})['items']
            assert [Path(item['path']) for item in items] == matches


@pytest.mark.parametrize('operation', ['folder', 'file', 'delete'])
@pytest.mark.parametrize('worker_first', [False, True])
def test_worldinfo_worker_uses_committed_global_paths(store, tmp_path, monkeypatch, operation, worker_first):
    from collections import deque
    from contextlib import closing
    from threading import Event
    from types import SimpleNamespace

    from core.services import index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, world_info, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    seed = Path(target['file_path'])
    source = seed.parent / 'OldGarden' / seed.name
    source.parent.mkdir()
    seed.rename(source)
    unrelated = seed.parent / 'Other.json'
    unrelated.write_text('{"name":"Other","entries":{}}', encoding='utf-8')
    monkeypatch.setattr(world_info, 'TRASH_FOLDER', str(tmp_path / 'trash'))
    monkeypatch.setattr(world_info, 'suppress_fs_events', lambda *_args: None)
    with closing(state.connect(store[0])) as conn, conn:
        assert build.build_worldinfo_generation(conn, 1) == 2

    def note(path, summary):
        response = app.test_client().post('/api/world_info/note/save', json={
            **target, 'file_path': str(path), 'summary': summary,
        })
        assert response.get_json()['success'], response.get_json()

    def check_search(term, paths):
        for mode in ('fast', 'fulltext'):
            reply = query_worldinfo_index({'db_path': str(store[0]), 'search': term, 'search_mode': mode})
            assert [Path(item['path']) for item in reply['items']] == paths

    def run_claim():
        rows, _ = worker._claim_pending_jobs(50)
        worker._process_claimed_jobs(rows, worker._WorldinfoBootstrap(), deque())
        return [row['id'] for row in rows]

    def change_path():
        return _change_global_worldinfo_test_path(app, operation, source)

    note(source, 'previousnotemarker')
    run_claim()
    note(source, 'replacementnotemarker')
    with closing(state.connect(store[0])) as conn, conn:
        pending_id = conn.execute("SELECT id FROM index_jobs WHERE status='pending'").fetchone()[0]
        if not worker_first:
            # Put unrelated work behind a full batch of paths covered by the rename.
            if operation == 'folder':
                from core.utils.filesystem import filesystem_path_bucket
                batch = [str(source.with_name(f'Book{i}.json')) for i in range(49)]
                conn.executemany("INSERT INTO index_jobs(job_type,source_path,path_key) "
                                 "VALUES ('upsert_worldinfo_path',?,?)",
                                 ((p, filesystem_path_bucket(p)) for p in batch))
            deferred_count = 50 if operation == 'folder' else 1
    if not worker_first:
        note(unrelated, 'unrelatednotemarker')
        with closing(state.connect(store[0])) as conn, conn:
            if operation == 'delete':
                conn.execute('''CREATE TRIGGER reject_note_delete BEFORE DELETE ON ui_namespace_records
                                BEGIN SELECT RAISE(ABORT, 'injected note transaction failure'); END''')
            else:
                conn.execute('''CREATE TRIGGER reject_move_job BEFORE INSERT ON index_jobs
                                WHEN NEW.job_type='upsert_worldinfo_path'
                                BEGIN SELECT RAISE(ABORT, 'injected enqueue failure'); END''')

    ready, resume = Event(), Event()
    module, function = (worker, 'process_worldinfo_job') if worker_first else (world_info, 'save_ui_data')
    original = getattr(module, function)

    def pause(*args, **kwargs):
        if not ready.is_set():
            ready.set()
            assert resume.wait(10), 'worldinfo operation was not released'
        return original(*args, **kwargs)

    clock = worker.time.time()
    monkeypatch.setattr(worker, 'time', SimpleNamespace(time=lambda: clock))
    monkeypatch.setattr(module, function, pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run_claim if worker_first else change_path)
        try:
            assert ready.wait(10), 'worldinfo operation did not reach the chosen stage'
            if worker_first:
                reply = change_path()
                assert reply.status_code == 409 and reply.get_json()['retryable']
                assert source.is_file()
                note(unrelated, 'unrelatednotemarker')
            else:
                assert not source.exists()
                claimed = run_claim()
                assert claimed[0] == pending_id
                if operation == 'folder':
                    assert len(claimed) == 50 and len(run_claim()) == 1
                check_search('unrelatednotemarker', [unrelated])
                assert len(run_claim()) == 1  # a separate physical-category refresh also waits
                assert not run_claim()
                with closing(state.connect(store[0])) as conn:
                    pending = conn.execute("SELECT COUNT(*) FROM index_jobs WHERE status='pending' "
                                           "AND job_type='upsert_worldinfo_path'").fetchone()[0]
                    assert pending == deferred_count
            check_search('previousnotemarker', [source])
        finally:
            resume.set()
        reply = future.result(timeout=10)
    if worker_first:
        assert reply == [pending_id]
    else:
        assert not reply.get_json()['success'] and source.is_file()
        clock += 1
    run_claim()
    check_search('previousnotemarker', [])
    check_search('replacementnotemarker', [source])
    check_search('unrelatednotemarker', [unrelated])


@pytest.mark.parametrize('worker_first', [False, True])
def test_worldinfo_owner_uses_lease_for_actual_resource_binding(store, tmp_path, monkeypatch, worker_first):
    from collections import deque
    from contextlib import closing
    from threading import Event
    from types import SimpleNamespace

    from core.api.v1 import system
    from core.services import card_service, index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    app.register_blueprint(system.bp)
    source = Path(target['file_path'])
    dest = source.parents[2] / 'renamed' / 'lorebooks' / source.name
    owner = tmp_path / 'cards' / 'Hero.json'
    owner.write_text('{"spec":"chara_card_v3","spec_version":"3.0","data":{"name":"Hero"}}', encoding='utf-8')
    monkeypatch.setattr(card_service, 'DEFAULT_DB_PATH', str(store[0]))
    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(owner.parent))
    monkeypatch.setattr(card_service, 'load_config', lambda: {'resources_dir': str(source.parents[2])})
    state.Repository().update_fields(owner.name, {'resource_folder': str(source.parents[1])})
    with closing(state.connect(store[0])) as conn, conn:
        conn.execute('INSERT INTO card_metadata(id,char_name,category) VALUES (?,?,?)', (owner.name, 'Hero', ''))
        assert build.build_worldinfo_generation(conn, 1) == 1

    def rename():
        return app.test_client().post('/api/rename_resource_folder', json={'card_id': owner.name, 'new_name': 'renamed'})

    def run_claim():
        rows, _ = worker._claim_pending_jobs()
        worker._process_claimed_jobs(rows, worker._WorldinfoBootstrap(), deque())
        return [row['id'] for row in rows]

    job = worker.enqueue_index_job('upsert_world_owner', entity_id=owner.name, source_path=str(owner))
    if not worker_first:
        with closing(state.connect(store[0])) as conn, conn:
            conn.execute('''CREATE TRIGGER reject_owner_binding BEFORE UPDATE ON ui_records
                            WHEN NEW.key='Hero.json'
                            BEGIN SELECT RAISE(ABORT, 'injected binding failure'); END''')
    ready, resume = Event(), Event()
    module, function = ((build, '_resource_lore_dir') if worker_first else (card_service, 'save_ui_data'))
    original = getattr(module, function)

    def pause(*args, **kwargs):
        ready.set()
        assert resume.wait(10), 'resource operation was not released'
        return original(*args, **kwargs)

    clock = worker.time.time()
    monkeypatch.setattr(worker, 'time', SimpleNamespace(time=lambda: clock))
    monkeypatch.setattr(module, function, pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        ongoing = pool.submit(run_claim if worker_first else rename)
        try:
            assert ready.wait(10)
            if worker_first:
                response = rename().get_json()
                assert not response['success'] and response['retryable'] and source.is_file()
            else:
                assert dest.is_file() and run_claim() == [job] and not run_claim()
                for mode in ('fast', 'fulltext'):
                    result = query_worldinfo_index({'db_path': str(store[0]), 'search': 'Book', 'search_mode': mode})
                    assert [Path(row['path']) for row in result['items']] == [source]
        finally:
            resume.set()
        result = ongoing.result(timeout=10)
    assert source.is_file()
    if worker_first:
        assert result == [job]
    else:
        assert not result.get_json()['success']
        clock += 1
        assert run_claim() == [job]
    with closing(state.connect(store[0])) as conn:
        assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (job,)).fetchone()[0] == 'done'


@pytest.mark.parametrize('route', ['queued', 'startup', 'bootstrap'])
def test_worldinfo_rebuild_retries_after_path_rollback(store, tmp_path, monkeypatch, route):
    from collections import deque
    from contextlib import closing
    from threading import Event
    from types import SimpleNamespace

    from core.data.index_runtime_store import get_search_content_format_version
    from core.services import index_build_service as build, index_upgrade_service as upgrade
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, world_info, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    seed = Path(target['file_path'])
    source = seed.parent / 'OldGarden' / seed.name
    source.parent.mkdir()
    seed.rename(source)
    new = seed.parent / 'NewGarden' / seed.name
    monkeypatch.setattr(upgrade, 'DEFAULT_DB_PATH', str(store[0]))
    monkeypatch.setattr(upgrade, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(worker.ctx, 'index_upgrade_active', route == 'startup')
    monkeypatch.setattr(worker.ctx, 'index_upgrade_done', Event())
    marker = 'rebuildstablemarker'
    result = app.test_client().post('/api/world_info/note/save', json={
        **target, 'file_path': str(source), 'summary': marker,
    })
    assert result.get_json()['success']
    active = int(route != 'bootstrap')
    with closing(state.connect(store[0])) as conn, conn:
        if active:
            assert build.build_worldinfo_generation(conn, 1) == 1
            conn.execute("UPDATE index_jobs SET status='done' WHERE status='pending'")
        else:
            conn.execute("UPDATE index_build_state SET active_generation=0 WHERE scope='worldinfo'")
        version = get_search_content_format_version(conn, 'worldinfo')
        conn.execute('''CREATE TRIGGER reject_move_job BEFORE INSERT ON index_jobs
                        WHEN NEW.job_type='upsert_worldinfo_path'
                        BEGIN SELECT RAISE(ABORT, 'injected enqueue failure'); END''')
    if route == 'queued':
        job_id = worker.enqueue_index_job('rebuild_scope', payload={'scope': 'worldinfo'})

    ready, resume = Event(), Event()
    original = world_info.save_ui_data

    def pause_save(*args, **kwargs):
        ready.set()
        assert resume.wait(10), 'path operation was not released'
        return original(*args, **kwargs)

    def run_claim():
        rows, _ = worker._claim_pending_jobs()
        worker._process_claimed_jobs(rows, worker._WorldinfoBootstrap(), deque())
        return [row['id'] for row in rows]

    clock = worker.time.time()
    monkeypatch.setattr(worker, 'time', SimpleNamespace(time=lambda: clock))
    monkeypatch.setattr(world_info, 'save_ui_data', pause_save)
    with ThreadPoolExecutor(max_workers=1) as pool:
        moved = pool.submit(_change_global_worldinfo_test_path, app, 'folder', source)
        try:
            assert ready.wait(10) and new.is_file()
            if route == 'startup':
                upgrade._background_upgrade_worker([{'scope': 'worldinfo', 'reason': 'bootstrap'}])
                assert not worker.ctx.index_upgrade_active and worker.ctx.index_upgrade_done.is_set()
            with closing(state.connect(store[0])) as conn:
                pending = conn.execute("SELECT id FROM index_jobs WHERE status='pending'").fetchone()[0]
                if route == 'queued':
                    assert pending == job_id
            assert run_claim() == [pending]
            assert not run_claim()
            with closing(state.connect(store[0])) as conn:
                current = conn.execute("SELECT active_generation,building_generation FROM index_build_state "
                                       "WHERE scope='worldinfo'").fetchone()
                assert tuple(current) == (active, 0)
                assert get_search_content_format_version(conn, 'worldinfo') == version
        finally:
            resume.set()
        assert not moved.result(timeout=10).get_json()['success'] and source.is_file()
    clock += 1
    assert run_claim() == [pending]
    for mode in ('fast', 'fulltext'):
        matches = query_worldinfo_index({'db_path': str(store[0]), 'search': marker, 'search_mode': mode})['items']
        assert [Path(item['path']) for item in matches] == [source]


def test_worldinfo_rebuild_discards_generation_changed_before_activation(store, tmp_path, monkeypatch):
    from collections import deque
    from contextlib import closing
    from types import SimpleNamespace

    from core.services import index_build_service as build, index_upgrade_service as upgrade

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    source = Path(target['file_path'])
    new = source.parent / 'NewGarden' / source.name
    monkeypatch.setattr(upgrade, 'DEFAULT_DB_PATH', str(store[0]))
    monkeypatch.setattr(upgrade, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    with closing(state.connect(store[0])) as conn, conn:
        assert build.build_worldinfo_generation(conn, 1) == 1
    rebuild = worker.enqueue_index_job('rebuild_scope', payload={'scope': 'worldinfo'})
    original = upgrade._ensure_worldinfo_projection_complete
    moved = False

    def move_after_build(*args):
        nonlocal moved
        original(*args)
        if not moved:
            moved = True
            assert _change_global_worldinfo_test_path(app, 'file', source).get_json()['success']
            assert new.is_file()

    def run_claim():
        rows, _ = worker._claim_pending_jobs()
        worker._process_claimed_jobs(rows, worker._WorldinfoBootstrap(), deque())

    clock = worker.time.time()
    monkeypatch.setattr(worker, 'time', SimpleNamespace(time=lambda: clock))
    monkeypatch.setattr(upgrade, '_ensure_worldinfo_projection_complete', move_after_build)
    run_claim()
    with closing(state.connect(store[0])) as conn:
        assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (rebuild,)).fetchone()[0] == 'pending'
        assert tuple(conn.execute("SELECT active_generation,building_generation FROM index_build_state "
                                  "WHERE scope='worldinfo'").fetchone()) == (1, 0)
        assert conn.execute("SELECT COUNT(*) FROM index_entities_v2 WHERE generation=2").fetchone()[0] == 0
    run_claim()  # The path jobs proceed while the rebuild is delayed.
    clock += 1
    run_claim()
    with closing(state.connect(store[0])) as conn:
        assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (rebuild,)).fetchone()[0] == 'done'
        row = conn.execute("SELECT source_path FROM index_entities_v2 WHERE generation=2").fetchone()
        assert Path(row[0]) == new


def test_worldinfo_category_refresh_retries_same_job_after_stale_scan(store, tmp_path, monkeypatch):
    from collections import deque
    from contextlib import closing
    from threading import Event, current_thread

    from core.services import index_build_service as build

    app, world_info, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    root = Path(target['file_path']).parent
    old, new = root / 'OldGarden', root / 'NewGarden'
    old.mkdir()
    with closing(state.connect(store[0])) as conn, conn:
        assert build.build_worldinfo_generation(conn, 1) == 1
    (old / 'Invalid.json').write_text('not JSON', encoding='utf-8')

    def categories():
        with closing(state.connect(store[0])) as conn:
            return list(conn.execute("SELECT category_path FROM index_category_stats_v2 "
                                     "WHERE entity_type='world_global' ORDER BY category_path"))

    note = app.test_client().post('/api/world_info/note/save', json={**target, 'summary': 'unrelatedmarker'})
    assert note.get_json()['success']
    with closing(state.connect(store[0])) as conn, conn:
        conn.execute('''CREATE TRIGGER reject_move_job BEFORE INSERT ON index_jobs
                        WHEN NEW.job_type='upsert_worldinfo_path'
                        BEGIN SELECT RAISE(ABORT, 'injected enqueue failure'); END''')
    ready, resume = Event(), Event()
    original = world_info.save_ui_data
    caller = current_thread()

    def pause_save(*args, **kwargs):
        if current_thread() is not caller:
            ready.set()
            assert resume.wait(10), 'path operation was not released'
        return original(*args, **kwargs)

    monkeypatch.setattr(world_info, 'save_ui_data', pause_save)
    with ThreadPoolExecutor(max_workers=1) as pool:
        moved = pool.submit(_change_global_worldinfo_test_path, app, 'folder', old / 'Invalid.json')
        try:
            assert ready.wait(10) and new.is_dir()
            rows, _ = worker._claim_pending_jobs()
            assert [row['job_type'] for row in rows] == ['upsert_worldinfo_path']
            worker._process_claimed_jobs(rows, worker._WorldinfoBootstrap(), deque())
            with closing(state.connect(store[0])) as conn:
                job_id = conn.execute("SELECT id FROM index_jobs WHERE job_type='refresh_worldinfo_categories'").fetchone()[0]
                assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (rows[0]['id'],)).fetchone()[0] == 'done'
            assert [tuple(row) for row in categories()] == [('OldGarden',)]
        finally:
            resume.set()
        assert not moved.result(timeout=10).get_json()['success']

    scan = build._read_worldinfo_physical_categories
    mutated = False

    def change_after_scan(path):
        nonlocal mutated
        physical = scan(path)
        if not mutated:
            mutated = True
            client = app.test_client()
            assert client.post('/api/world_info/folders/delete', json={'category': 'OldGarden'}).get_json()['success']
            assert client.post('/api/world_info/folders/create', json={'name': 'Later'}).get_json()['success']
        return physical

    (old / 'Invalid.json').unlink()
    monkeypatch.setattr(build, '_read_worldinfo_physical_categories', change_after_scan)
    attempts = []
    process = worker._process_claimed_jobs

    def record(rows, bootstrap, results):
        attempts.extend(row['id'] for row in rows)
        process(rows, bootstrap, results)

    wait = worker.ctx.index_wakeup.wait

    class StopWorker(Exception):
        pass

    def stop_when_done(timeout):
        with closing(state.connect(store[0])) as conn:
            status = conn.execute('SELECT status FROM index_jobs WHERE id=?', (job_id,)).fetchone()[0]
        if status == 'done':
            raise StopWorker
        return wait(min(timeout, 1))

    monkeypatch.setattr(worker, '_process_claimed_jobs', record)
    monkeypatch.setattr(worker.ctx.index_wakeup, 'wait', stop_when_done)
    monkeypatch.setattr(worker.ctx, 'index_upgrade_active', False)
    with pytest.raises(StopWorker):
        worker.worker_loop()
    assert attempts == [job_id, job_id]
    assert [tuple(row) for row in categories()] == [('Later',)]


@pytest.mark.skipif(os.name != 'nt', reason='Windows per-directory case sensitivity')
def test_worldinfo_folder_rename_preserves_notes_in_case_sensitive_directory(store, tmp_path, monkeypatch):
    import subprocess

    from core.services import index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, world_info, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    seed = Path(target['file_path'])
    seed.unlink()
    worlds = seed.parent
    result = subprocess.run(['fsutil', 'file', 'SetCaseSensitiveInfo', str(worlds), 'enable'], capture_output=True)
    if result.returncode != 0:
        pytest.skip('temporary filesystem does not allow enabling case sensitivity')
    original = worlds / 'OldFolder' / 'Nested' / 'Book.json'
    sibling = worlds / 'oldfolder' / 'Nested' / 'Book.json'
    destination = worlds / 'NewFolder' / 'Nested' / 'Book.json'
    for book, title in [(original, 'movedbookmarker'), (sibling, 'siblingbookmarker')]:
        book.parent.mkdir(parents=True)
        book.write_text(json.dumps({'name': title, 'entries': {}}), encoding='utf-8')
    assert not original.samefile(sibling)
    monkeypatch.setattr(world_info, 'DEFAULT_DB_PATH', str(store[0]))
    with state.connect(store[0]) as conn:
        assert build.build_worldinfo_generation(conn, 1) == 2
    client = app.test_client()
    for book, summary in [(original, 'movednotemarker'), (sibling, 'siblingnotemarker')]:
        reply = client.post('/api/world_info/note/save', json={
            **target, 'file_path': str(book), 'summary': summary,
        }).get_json()
        assert reply['success'], reply
    _run_world_worker_once(worker, monkeypatch)

    reply = client.post('/api/world_info/folders/rename', json={
        'category': 'OldFolder', 'new_name': 'NewFolder',
    }).get_json()
    assert reply['success'], reply
    assert not original.exists() and destination.exists() and sibling.exists()
    _run_world_worker_once(worker, monkeypatch)
    notes = ui_store.load_ui_data()
    for book, summary in [(destination, 'movednotemarker'), (sibling, 'siblingnotemarker')]:
        assert ui_store.get_worldinfo_note(notes, 'global', file_path=str(book))['summary'] == summary
        for mode in ('fast', 'fulltext'):
            reply = query_worldinfo_index({'db_path': str(store[0]), 'search': summary, 'search_mode': mode})
            assert [Path(item['path']) for item in reply['items']] == [book]
    assert not ui_store.get_worldinfo_note(notes, 'global', file_path=str(original))


@pytest.mark.skipif(os.name != 'nt', reason='Windows path aliases')
@pytest.mark.parametrize('pending_during_probe', ['keep', 'claim', 'replace', 'reject'])
def test_worldinfo_note_alias_preflight_does_not_hold_writer_lock(store, tmp_path, monkeypatch, pending_during_probe):
    from contextlib import closing
    from threading import Event

    from core.utils import filesystem

    app, world_info, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    book = Path(target['file_path'])
    alias = book.with_name('BOOK.JSON')
    third_path = book.with_name('Book.Json')
    assert alias.samefile(book) and third_path.samefile(book)
    original_id = worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(book))
    armed, entered, release = Event(), Event(), Event()
    real_set, real_case = world_info.set_worldinfo_note, filesystem._windows_case_sensitive

    def set_note(*args, **kwargs):
        changed = real_set(*args, **kwargs)
        armed.set()
        return changed

    def pause_case(parent, directory_cases):
        if (armed.is_set() and not entered.is_set()
                and os.path.normcase(parent) == os.path.normcase(str(book.parent))):
            entered.set()
            assert release.wait(10), 'directory case probe was not released'
        return real_case(parent, directory_cases)

    def save():
        return app.test_client().post('/api/world_info/note/save', json={
            **target, 'file_path': str(alias), 'summary': 'durable note',
        }).get_json()

    monkeypatch.setattr(world_info, 'set_worldinfo_note', set_note)
    monkeypatch.setattr(filesystem, '_windows_case_sensitive', pause_case)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(save)
        try:
            assert entered.wait(10), 'directory case probe did not run'
            with closing(sqlite3.connect(store[0], timeout=0)) as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                state.Repository('chat').update_fields('another-chat', {'last_view_floor': 9}, conn=conn)
                if pending_during_probe != 'keep':
                    conn.execute("UPDATE index_jobs SET status='running' WHERE id=?", (original_id,))
                if pending_during_probe == 'replace':
                    replacement_id = conn.execute(
                        "INSERT INTO index_jobs(job_type,source_path,path_key) VALUES ('upsert_worldinfo_path',?,?)",
                        (str(third_path), filesystem.filesystem_path_bucket(str(third_path))),
                    ).lastrowid
                if pending_during_probe == 'reject':
                    conn.execute("CREATE TRIGGER reject_alias_refresh BEFORE INSERT ON index_jobs "
                                 "BEGIN SELECT RAISE(ABORT, 'refresh unavailable'); END")
        finally:
            release.set()
        reply = future.result(timeout=10)
    assert state.Repository('chat').get('another-chat')['last_view_floor'] == 9
    with closing(state.connect(store[0])) as conn:
        jobs = [tuple(row) for row in conn.execute("SELECT id,source_path FROM index_jobs WHERE status='pending'")]
    if pending_during_probe == 'reject':
        assert reply['success'] is False and not jobs, reply
        assert not ui_store.get_worldinfo_note(ui_store.load_ui_data(), 'global', file_path=str(book))
        return
    assert reply['success'] and reply['ui_summary'] == 'durable note', reply
    assert len(jobs) == 1
    if pending_during_probe == 'keep':
        assert jobs == [(original_id, str(book))]
    elif pending_during_probe == 'claim':
        assert jobs[0][0] != original_id and jobs[0][1] == str(alias)
    else:
        assert jobs == [(replacement_id, str(third_path))]


@pytest.mark.skipif(os.name != 'nt', reason='Windows path aliases')
def test_standalone_worldinfo_enqueue_only_probes_when_pending_alias_exists(store, tmp_path, monkeypatch):
    from core.utils import filesystem

    _, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    path = Path(target['file_path'])
    probes = []
    actual = filesystem._windows_case_sensitive

    def observe(parent, cached):
        probes.append(parent)
        return actual(parent, cached)

    monkeypatch.setattr(filesystem, '_windows_case_sensitive', observe)
    original_id = worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(path))
    assert worker.enqueue_index_job('upsert_worldinfo_path', source_path=path.as_posix()) == original_id
    assert not probes
    assert worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(path.with_name('BOOK.json'))) == original_id
    assert os.path.normcase(str(path.parent)) in {os.path.normcase(parent) for parent in probes}


@pytest.mark.skipif(os.name != 'nt', reason='Windows path aliases')
@pytest.mark.parametrize('flask_writer', [False, True])
def test_worldinfo_note_enqueue_inside_outer_transaction_does_not_probe(store, tmp_path, monkeypatch, flask_writer):
    from contextlib import closing

    from flask import g

    from core.utils import filesystem

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    path = Path(target['file_path'])
    worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(path))
    alias = str(path.with_name('BOOK.json'))
    snapshot = ui_store.load_ui_data()
    assert ui_store.set_worldinfo_note(snapshot, 'global', 'draft', file_path=alias)

    def unexpected_probe(*args):
        pytest.fail('directory probe while outer write transaction was active')

    with monkeypatch.context() as patch, closing(state.connect(store[0])) as conn, app.app_context():
        conn.execute('BEGIN IMMEDIATE')
        if flask_writer:
            g.db = conn
        patch.setattr(filesystem, '_windows_case_sensitive', unexpected_probe)
        assert ui_store.save_ui_data(
            snapshot, conn=None if flask_writer else conn,
            worldinfo_jobs=[dict(job_type='upsert_worldinfo_path', source_path=alias)],
        )
        assert conn.execute('SELECT COUNT(*) FROM index_jobs').fetchone()[0] == 2
        conn.rollback()
        assert conn.execute('SELECT COUNT(*) FROM index_jobs').fetchone()[0] == 1
    assert not ui_store.get_worldinfo_note(ui_store.load_ui_data(), 'global', file_path=alias)


@pytest.mark.parametrize('source', ['global', 'resource', 'embedded'])
@pytest.mark.parametrize('failure', ['conflict', 'storage'])
def test_world_note_api_does_not_confirm_rejected_draft(store, tmp_path, monkeypatch, source, failure):
    import threading
    app, world_info, worker, target = _world_note_client(store, tmp_path, monkeypatch, source)
    client = app.test_client()
    assert client.post('/api/world_info/note/save', json={**target, 'summary': 'initial'}).get_json()['success']
    save = world_info.save_ui_data
    results, interleaved = [], []
    def save_after_other_request(snapshot, **kwargs):
        if failure == 'conflict' and not interleaved:
            interleaved.append(True)
            replies = []
            def other():
                replies.append(app.test_client().post('/api/world_info/note/save', json={
                    **target, 'summary': 'committed other note'}).get_json())
            thread = threading.Thread(target=other, daemon=True)
            thread.start()
            thread.join(10)
            assert not thread.is_alive() and replies[0]['success'], replies
        result = save(snapshot, **kwargs)
        results.append(result)
        return result
    monkeypatch.setattr(world_info, 'save_ui_data', save_after_other_request)
    with worker._connect() as conn:
        conn.execute('DELETE FROM index_jobs')
        if failure == 'storage':
            conn.execute("CREATE TRIGGER reject_note BEFORE INSERT ON ui_namespace_records "
                         "BEGIN SELECT RAISE(ABORT, 'state unavailable'); END")
    reply = client.post('/api/world_info/note/save', json={**target, 'summary': 'rejected draft'}).get_json()
    assert results == ([True, False] if failure == 'conflict' else [False])
    assert reply['success'] is False and reply['retryable'] and reply['ui_data_saved'] is False
    assert 'ui_summary' not in reply
    source_type = target['source_type']
    fields = {key: value for key, value in target.items() if key != 'source_type'}
    assert ui_store.get_worldinfo_note(ui_store.load_ui_data(), source_type, **fields)['summary'] == (
        'committed other note' if failure == 'conflict' else 'initial')
    with worker._connect() as conn:
        # Only the successful concurrent request may enqueue a note refresh.
        assert conn.execute('SELECT COUNT(*) FROM index_jobs').fetchone()[0] == (
            1 if failure == 'conflict' else 0)
        if failure == 'storage':
            conn.execute('DROP TRIGGER reject_note')
    retry = client.post('/api/world_info/note/save', json={**target, 'summary': 'rejected draft'}).get_json()
    assert retry['success'] and retry['ui_summary'] == 'rejected draft'


@pytest.mark.parametrize('size', [1000, 100000])
def test_single_world_note_api_reads_bounded_members_and_payload(store, tmp_path, monkeypatch, size):
    app, _, _, target = _world_note_client(store, tmp_path, monkeypatch, 'embedded')
    note_key = ui_store.build_worldinfo_note_key('embedded', card_id='hero.png')
    notes = {f'embedded::card-{i}.png': {'summary': 'opaque ' + 'x' * 180} for i in range(size - 1)}
    notes[note_key] = {'summary': 'before', 'opaque': 'keep'}
    state.Repository().replace_snapshot({ui_store.WORLDINFO_NOTES_KEY: notes})
    records, frozen = [], []
    read, decode = state.NamespaceRepository._read_records, state.Repository._decode_record
    def observe_read(self, *args, **kwargs):
        result = read(self, *args, **kwargs)
        records.extend(result.values())
        return result
    def observe_decode(self, *args, **kwargs):
        result = decode(self, *args, **kwargs)
        if isinstance(result, state.StateSnapshot) and result._records is not None:
            frozen.append(len(result._records))
        return result
    with monkeypatch.context() as patch:
        patch.setattr(state.NamespaceRepository, '_read_records', observe_read)
        patch.setattr(state.Repository, '_decode_record', observe_decode)
        reply = app.test_client().post('/api/world_info/note/save', json={**target, 'summary': 'actual note'}).get_json()
    assert reply['success'] and reply['ui_summary'] == 'actual note'
    assert len(records) <= 6 and sum(len(raw) for raw, _ in records) < 2048
    assert sum(frozen) == 0  # No uninstrumented compatibility full-root reads.
    with state.connect(store[0]) as conn:
        assert conn.execute('SELECT COUNT(*) FROM ui_namespace_records').fetchone()[0] == size
        assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE job_type='upsert_world_embedded'").fetchone()[0] == 1
    assert state.NamespaceRepository(ui_store.WORLDINFO_NOTES_KEY).get(note_key)['opaque'] == 'keep'


def test_worldinfo_list_batches_note_reads_and_keeps_concurrent_snapshot_complete(
        store, tmp_path, monkeypatch):
    from core.context import ctx
    app, world_info, _, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    root = tmp_path / 'worlds'
    notes = {}
    first_book = root / 'book.json'
    notes[ui_store.build_worldinfo_note_key('global', file_path=str(first_book))] = {
        'summary': 'initial note'}
    for index in range(999):
        book = root / f'book-{index:04}.json'
        book.write_text(json.dumps({'name': f'Book {index}', 'entries': {}}), encoding='utf-8')
        key = ui_store.build_worldinfo_note_key('global', file_path=str(book))
        notes[key] = {'summary': f'note {index}'}
    state.Repository().replace_snapshot({ui_store.WORLDINFO_NOTES_KEY: notes})

    original_connect = state.connect
    original_read = state.NamespaceRepository._read_records
    connections, rows_read, interleaved = [], [], []
    list_counts = []
    def observe_connect(*args, **kwargs):
        connections.append(True)
        return original_connect(*args, **kwargs)
    def observe_read(repository, keys=None, **kwargs):
        result = original_read(repository, keys, **kwargs)
        if repository.namespace == ui_store.WORLDINFO_NOTES_KEY:
            rows_read.extend(result)
        return result
    prefetch = world_info._prefetch_worldinfo_list_ui
    def save_during_list(snapshot, items, cfg):
        prefetch(snapshot, items, cfg)
        if not interleaved:
            interleaved.append(True)
            list_counts.append((len(connections), len(rows_read)))
            path = str(root / 'book-0500.json')
            result = app.test_client().post('/api/world_info/note/save', json={
                **target, 'file_path': path, 'summary': 'parallel committed note',
            }).get_json()
            assert result['success'], result

    ctx.wi_list_cache.clear()
    with monkeypatch.context() as patch:
        patch.setattr(state, 'connect', observe_connect)
        patch.setattr(state.NamespaceRepository, '_read_records', observe_read)
        patch.setattr(world_info, '_prefetch_worldinfo_list_ui', save_during_list)
        listing = app.test_client().get('/api/world_info/list?type=global&page_size=1000').get_json()

    assert listing['success'] and listing['total'] == 1000
    assert len(listing['items']) == 1000
    assert len(list_counts) == 1
    assert list_counts[0][1] == 1000 and list_counts[0][0] < 12
    assert all(item['ui_summary'] for item in listing['items'])
    followup = app.test_client().get('/api/world_info/list?type=global&search=parallel%20committed').get_json()
    assert followup['success'] and followup['total'] == 1
    assert followup['items'][0]['ui_summary'] == 'parallel committed note'


def test_worldinfo_note_schema_upgrade_rekeys_legacy_keys_without_losing_conflicts(
        store, tmp_path, monkeypatch):
    app, _, _, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    book = Path(target['file_path'])
    canonical = ui_store.build_worldinfo_note_key('global', file_path=str(book))
    legacy = 'global::' + str(book).replace('/', '\\')
    repo = state.Repository()
    repo.replace_snapshot({})
    with state.connect(store[0]) as conn:
        conn.execute('INSERT OR IGNORE INTO ui_namespace_roots(namespace) VALUES (?)',
                     (ui_store.WORLDINFO_NOTES_KEY,))
        conn.execute('INSERT OR REPLACE INTO ui_records(key,payload_json,revision) VALUES (?,?,1)',
                     (ui_store.WORLDINFO_NOTES_KEY, '{}'))
        conn.execute('INSERT INTO ui_namespace_records(namespace,key,payload_json) VALUES (?,?,?)',
                     (ui_store.WORLDINFO_NOTES_KEY, canonical,
                      state.encode({'summary': 'canonical note'})))
        conn.execute('INSERT INTO ui_namespace_records(namespace,key,payload_json) VALUES (?,?,?)',
                     (ui_store.WORLDINFO_NOTES_KEY, legacy,
                      state.encode({'summary': 'legacy note'})))
        conn.execute('UPDATE local_state_migrations SET version=1 WHERE id=1')
    state._ready.clear()
    state.initialize()

    note = ui_store.get_worldinfo_note(ui_store.load_ui_data(), 'global', file_path=str(book))
    assert note['summary'] == 'canonical note'
    with state.connect(store[0]) as conn:
        actual = {row[0]: json.loads(row[1]) for row in conn.execute(
            'SELECT key,payload_json FROM ui_namespace_records WHERE namespace=?',
            (ui_store.WORLDINFO_NOTES_KEY,))}
        assert canonical in actual and actual[canonical]['summary'] == 'canonical note'
        archived = [value for key, value in actual.items() if key.startswith('legacy-conflict::')]
        assert archived == [{'summary': 'legacy note'}]
        assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE job_type='rebuild_scope' "
                            "AND payload_json LIKE '%worldinfo%'").fetchone()[0] == 1
    detail = app.test_client().post('/api/world_info/detail', json=target).get_json()
    assert detail['success'] and detail['ui_summary'] == 'canonical note'


def _legacy_worldinfo_index(store, tmp_path, monkeypatch, filename, *, active=True, canonical_first=False):
    from core.data.db_session import _initialize_database
    from core.data.index_runtime_store import activate_generation, allocate_build_generation
    from core.data.sqlite_capabilities import supports_fts5
    from core.services import index_build_service as build, index_upgrade_service as upgrade, index_job_worker

    db, ui, _ = store
    book = tmp_path / 'OldWorlds' / filename
    book.parent.mkdir()
    book.write_text('{"name":"Book","entries":{"0":{"content":"bodymarker"}}}', encoding='utf-8')
    canonical = ui_store.build_worldinfo_note_key('global', file_path=str(book))
    alias = 'global::' + book.as_posix()
    if alias == canonical:  # Preserve the Windows fixture's distinct alias on case-sensitive hosts.
        alias = 'global::' + book.parent.as_posix() + '/./' + book.name
    notes = {}
    if filename != 'CanonicalOnly.json':
        notes[alias] = {'summary': 'cedarmarker' if filename == 'Conflict.json' else 'irismarker'}
    notes[canonical] = {'summary': 'irismarker'}
    if canonical_first:
        notes = dict(reversed(notes.items()))
    ui.write_text(json.dumps({ui_store.WORLDINFO_NOTES_KEY: notes}), encoding='utf-8')
    fixture = Path(__file__).with_name('fixtures') / 'worldinfo_notes_v120.json'
    old = json.loads(fixture.read_text(encoding='utf-8'))['books'][filename]
    with state.connect(db) as conn:
        _initialize_database(conn, is_existing_db=True, schema_only=True)
        assert allocate_build_generation(conn, 'worldinfo') == 1
        entity_id = 'world::global::' + filename
        conn.execute('INSERT INTO index_entities_v2(generation,entity_id,entity_type,source_path,name,filename,'
                     "summary_preview) VALUES (1,?,'world_global',?,'Book',?,?)",
                     (entity_id, str(book), filename, old['summary_preview']))
        conn.execute('INSERT INTO index_search_fast_v2 VALUES (1,?,?)', (entity_id, old['fast']))
        if supports_fts5():
            row = conn.execute('INSERT INTO index_search_full_v2 VALUES (1,?,?)', (entity_id, old['full']))
            conn.execute('INSERT INTO index_full_rowids VALUES (1,?,?)', (entity_id, row.lastrowid))
        if active:
            assert activate_generation(conn, 'worldinfo', 1, items_written=1)
    monkeypatch.setattr(build, 'load_config', lambda: {'world_info_dir': str(book.parent)})
    monkeypatch.setattr(upgrade, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db))
    return book, old


@pytest.mark.parametrize(('filename', 'canonical_first', 'active', 'needs_refresh'), [
    ('Conflict.json', False, True, True),
    ('Conflict.json', True, True, True),
    ('CanonicalOnly.json', False, True, True),
    ('Matching.json', False, True, False),
    ('Conflict.json', False, False, False),
])
def test_first_activation_checks_real_legacy_worldinfo_projection(
        store, tmp_path, monkeypatch, filename, canonical_first, active, needs_refresh):
    from flask import Flask
    from core.api.v1 import world_info
    from core.context import ctx
    from core.services import index_job_worker as worker, index_upgrade_service as upgrade
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    db, _, _ = store
    book, old = _legacy_worldinfo_index(store, tmp_path, monkeypatch, filename,
                                       active=active, canonical_first=canonical_first)
    if active:
        assert all(item['scope'] != 'worldinfo' for item in upgrade.plan_startup_upgrade())
    state.initialize()
    with state.connect(db) as conn:
        jobs = [(row[0], json.loads(row[1]), row[2]) for row in conn.execute(
            'SELECT job_type,payload_json,status FROM index_jobs')]
        expected = {'scope': 'worldinfo', 'note_migration_generation': 1}
        assert jobs == ([('rebuild_scope', expected, 'pending')] if needs_refresh else [])
    assert ui_store.get_worldinfo_note(ui_store.load_ui_data(), 'global', file_path=str(book))['summary'] == 'irismarker'
    if needs_refresh:
        def hits(word, mode):
            return query_worldinfo_index({'db_path': str(db), 'search': word, 'search_mode': mode})['total']

        app = Flask(__name__)
        app.register_blueprint(world_info.bp)
        monkeypatch.setattr(world_info, 'DEFAULT_DB_PATH', str(db))
        monkeypatch.setattr(world_info, 'load_config', lambda: {
            'world_info_dir': str(book.parent), 'worldinfo_list_use_index': True})
        monkeypatch.setattr(ctx.cache, 'initialized', True)
        client = app.test_client()

        def list_summaries(word, mode):
            result = client.get('/api/world_info/list', query_string={
                'search': word, 'search_mode': mode}).get_json()
            assert result['success']
            return [item['ui_summary'] for item in result['items']]

        for mode in ('fast', 'fulltext'):
            assert hits('cedarmarker', mode) == int(old['summary_preview'] == 'cedarmarker')
            assert hits('irismarker', mode) == 0
            if old['summary_preview'] == 'cedarmarker':
                assert list_summaries('cedarmarker', mode) == ['irismarker']
        _run_world_worker_once(worker, monkeypatch)
        with state.connect(db) as conn:
            assert conn.execute('SELECT status FROM index_jobs').fetchone()[0] == 'done'
        for mode in ('fast', 'fulltext'):
            assert hits('cedarmarker', mode) == 0
            assert hits('irismarker', mode) == 1
            assert list_summaries('cedarmarker', mode) == []
            assert list_summaries('irismarker', mode) == ['irismarker']


@pytest.mark.parametrize('stale_source', [None, 'embedded', 'resource'])
def test_activation_checks_resource_notes_and_embedded_card_override(store, tmp_path, monkeypatch, stale_source):
    db, ui, _ = store
    _legacy_worldinfo_index(store, tmp_path, monkeypatch, 'Matching.json')
    payload = json.loads(ui.read_text(encoding='utf-8'))
    card_id = '_Hero.png'
    resource_path = str(tmp_path / 'Resources' / 'Book.json')
    notes = payload[ui_store.WORLDINFO_NOTES_KEY]
    notes[ui_store.build_worldinfo_note_key('resource', file_path=resource_path)] = {'summary': 'resource note'}
    notes[ui_store.build_worldinfo_note_key('embedded', card_id=card_id)] = {'summary': 'fallback'}
    payload[card_id] = {'summary': 'card override'}
    ui.write_text(json.dumps(payload), encoding='utf-8')
    with state.connect(db) as conn:
        for source, target, path, summary in [
                ('embedded', card_id, str(tmp_path / card_id), 'card override'),
                ('resource', card_id + '::Book.json', resource_path, 'resource note')]:
            conn.execute('INSERT INTO index_entities_v2(generation,entity_id,entity_type,source_path,name,filename,'
                         "summary_preview) VALUES (1,?,?,?,'Book','Book.json',?)",
                         (f'world::{source}::{target}', 'world_' + source, path,
                          'stale' if source == stale_source else summary))
    state.initialize()
    with state.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE job_type='rebuild_scope'").fetchone()[0] == (
            0 if stale_source is None else 1)


@pytest.mark.parametrize('already_activated', [False, True])
def test_worldinfo_projection_reconciliation_rolls_back_and_retries(store, tmp_path, monkeypatch, already_activated):
    db, ui, _ = store
    _legacy_worldinfo_index(store, tmp_path, monkeypatch, 'Conflict.json')
    if already_activated:
        state.initialize()
        with state.connect(db) as conn:
            conn.execute('DELETE FROM index_jobs')
            conn.execute('UPDATE local_state_migrations SET version=2')
        state._ready.clear()
        ui.write_text('{}')  # Never re-import a retained file when repairing an activated database.
    with state.connect(db) as conn:
        conn.execute("CREATE TRIGGER reject_rebuild BEFORE INSERT ON index_jobs WHEN NEW.job_type='rebuild_scope' "
                     "BEGIN SELECT RAISE(ABORT,'queue unavailable'); END")
    with pytest.raises(state.LocalStateError):
        state.initialize()
    with state.connect(db) as conn:
        version, phase = conn.execute('SELECT version,state FROM local_state_migrations').fetchone()
        assert phase == ('activated' if already_activated else 'imported')
        if already_activated:
            assert version == 2
        else:
            assert conn.execute('SELECT COUNT(*) FROM ui_namespace_records').fetchone()[0] == 0
            assert conn.execute('SELECT COUNT(*) FROM local_state_staging').fetchone()[0] > 0
        assert conn.execute('SELECT COUNT(*) FROM index_jobs').fetchone()[0] == 0
        conn.execute('DROP TRIGGER reject_rebuild')
    state.initialize()
    state._ready.clear()
    state.initialize()
    with state.connect(db) as conn:
        assert tuple(conn.execute('SELECT version,state FROM local_state_migrations').fetchone()) == (
            state.SCHEMA_VERSION, 'activated')
        assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE job_type='rebuild_scope' "
                            "AND status='pending'").fetchone()[0] == 1


@pytest.mark.parametrize('startup', ['covered', 'inaccessible', 'newer_but_stale'])
def test_migration_job_after_startup_format_upgrade(store, tmp_path, monkeypatch, startup):
    from core.data.index_runtime_store import get_active_generation, set_search_content_format_version
    from core.services import index_build_service as build, index_job_worker as worker, index_upgrade_service as upgrade
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    db, _, _ = store
    _legacy_worldinfo_index(store, tmp_path, monkeypatch, 'Conflict.json')
    with state.connect(db) as conn:
        set_search_content_format_version(conn, 'worldinfo', 2)  # v1.2.0 wrote format 2.
    state.initialize()
    plan = next(item for item in upgrade.plan_startup_upgrade() if item['scope'] == 'worldinfo')
    assert plan['reason'] == 'search_content_format_upgrade'
    if startup == 'inaccessible':
        def deny(path):
            raise PermissionError(str(path))
        with monkeypatch.context() as patch:
            patch.setattr(build, 'walk_directory_strict', deny)
            with pytest.raises(PermissionError):
                upgrade.rebuild_scope_generation(**plan)
        with state.connect(db) as conn:
            assert get_active_generation(conn, 'worldinfo') == 1
            assert conn.execute('SELECT status FROM index_jobs').fetchone()[0] == 'pending'
    else:
        upgrade.rebuild_scope_generation(**plan)
        with state.connect(db) as conn:
            assert get_active_generation(conn, 'worldinfo') == 2
            if startup == 'newer_but_stale':
                conn.execute("UPDATE index_entities_v2 SET summary_preview='stale' WHERE entity_type='world_global'")
    _run_world_worker_once(worker, monkeypatch)
    with state.connect(db) as conn:
        assert get_active_generation(conn, 'worldinfo') == (3 if startup == 'newer_but_stale' else 2)
        assert conn.execute('SELECT status FROM index_jobs').fetchone()[0] == 'done'
    for mode in ('fast', 'fulltext'):
        for word, hits in [('irismarker', 1), ('cedarmarker', 0)]:
            assert query_worldinfo_index({'db_path': str(db), 'search': word, 'search_mode': mode})['total'] == hits


@pytest.mark.parametrize('repair', ['worker', 'same_note_retry', 'activation_retry', 'activation_rollback'])
def test_card_note_saved_before_activation_reaches_new_generation(store, tmp_path, monkeypatch, repair):
    from flask import Flask
    from core.api.v1 import cards
    from core.data.index_runtime_store import activate_generation, allocate_build_generation
    from core.services.card_index_query_service import query_indexed_cards

    roots, build, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    db = store[0]
    monkeypatch.setattr(cards, 'CARDS_FOLDER', str(roots['cards']))
    monkeypatch.setattr(cards, 'DEFAULT_DB_PATH', str(db))
    (roots['cards'] / 'hero.json').write_text('{"data":{"name":"Hero"}}', encoding='utf-8')
    state.Repository().update_fields('hero.json', {'summary': 'oldmarker'})
    app = Flask(__name__)
    app.register_blueprint(cards.bp)
    client = app.test_client()

    def save(word):
        result = client.post('/api/update_card', json={'id': 'hero.json', 'ui_only': True,
                             'ui_only_fields': ['ui_summary'], 'ui_summary': word}).get_json()
        assert result['success'], result

    def check_search(word, obsolete):
        for mode in ('fast', 'fulltext'):
            def search(term):
                return query_indexed_cards({'db_path': str(db), 'search': term, 'search_mode': mode})['cards']
            assert [(card['id'], card['ui_summary']) for card in search(word)] == [('hero.json', word)]
            assert not search(obsolete)

    with state.connect(db) as conn:
        conn.execute("INSERT INTO card_metadata(id,char_name) VALUES ('hero.json','Hero')")
        for gen in (1, 2):
            assert allocate_build_generation(conn, 'cards') == gen
            assert build.build_cards_generation(conn, gen) == 1
            if gen == 2:
                save('intermediatemarker')
                save('newmarker')
                _run_world_worker_once(worker, monkeypatch)
                check_search('newmarker', 'oldmarker')
                if repair.startswith('activation_'):
                    if repair == 'activation_retry':
                        conn.execute("CREATE TRIGGER reject_replay BEFORE INSERT ON index_jobs "
                                     "BEGIN SELECT RAISE(ABORT,'reject replay'); END")
                    else:
                        conn.execute("CREATE TRIGGER reject_replay BEFORE INSERT ON scan_runtime_state "
                                     "BEGIN SELECT RAISE(ROLLBACK,'reject replay'); END")
                    with pytest.raises(sqlite3.IntegrityError, match='reject replay'):
                        activate_generation(conn, 'cards', gen, items_written=1)
                    assert conn.execute("SELECT active_generation FROM index_build_state WHERE scope='cards'").fetchone()[0] == 1
                    check_search('newmarker', 'oldmarker')
                    conn.execute('DROP TRIGGER reject_replay')
            assert activate_generation(conn, 'cards', gen, items_written=1)
        assert conn.execute("SELECT count(*) FROM index_jobs WHERE status='pending' AND entity_id='hero.json'").fetchone()[0] == 1
    if repair == 'same_note_retry':
        save('newmarker')
    else:
        _run_world_worker_once(worker, monkeypatch)
    check_search('newmarker', 'oldmarker')
    with state.connect(db) as conn:
        assert not conn.execute("SELECT id FROM index_jobs WHERE status != 'done'").fetchall()
        receipt = conn.execute("SELECT generation FROM card_ui_projections WHERE card_id='hero.json'").fetchone()
        assert receipt[0] == 2


def test_one_wakeup_drains_card_note_replays_after_activation(store, tmp_path, monkeypatch):
    from flask import Flask
    from core.api.v1 import cards
    from core.data.index_runtime_store import activate_generation, allocate_build_generation
    from core.services.card_index_query_service import query_indexed_cards

    roots, build, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    db = store[0]
    ids = [f'card{i:03}.json' for i in range(101)]
    monkeypatch.setattr(cards, 'CARDS_FOLDER', str(roots['cards']))
    monkeypatch.setattr(cards, 'DEFAULT_DB_PATH', str(db))
    app = Flask(__name__)
    app.register_blueprint(cards.bp)
    client = app.test_client()
    state.Repository().replace_snapshot({key: {'summary': 'oldmarker'} for key in ids})
    for key in ids:
        (roots['cards'] / key).write_text('{"data":{"name":"Hero"}}', encoding='utf-8')
    with state.connect(db) as conn:
        conn.executemany('INSERT INTO card_metadata(id,char_name) VALUES (?,?)', [(key, key) for key in ids])
        for gen in (1, 2):
            assert allocate_build_generation(conn, 'cards') == gen
            assert build.build_cards_generation(conn, gen) == len(ids)
            if gen == 2:
                for key in ids:
                    result = client.post('/api/update_card', json={'id': key, 'ui_only': True,
                                         'ui_only_fields': ['ui_summary'], 'ui_summary': 'newmarker'}).get_json()
                    assert result['success'], result
            assert activate_generation(conn, 'cards', gen, items_written=len(ids))
        assert conn.execute("SELECT count(*) FROM index_jobs WHERE status='pending'").fetchone()[0] == len(ids)

    _run_world_worker_once(worker, monkeypatch)
    for mode in ('fast', 'fulltext'):
        for word, expected in [('oldmarker', 0), ('newmarker', len(ids))]:
            result = query_indexed_cards({'db_path': str(db), 'search': word, 'search_mode': mode})
            assert result['total_count'] == expected, (mode, word)


def test_due_worldinfo_failures_share_first_batch_with_new_work(store, tmp_path, monkeypatch):
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    roots, build, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    db = store[0]
    blocked = set()
    for i in range(50):
        path = roots['worlds'] / f'blocked{i}.json'
        path.write_text('{"name":"recoveredmarker","entries":{}}', encoding='utf-8')
        blocked.add(path)
        worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(path))
    prepare = build._prepared_world_file

    def fail_blocked(path, **kwargs):
        if Path(path) in blocked:
            raise PermissionError('unreadable worldbook')
        return prepare(path, **kwargs)

    monkeypatch.setattr(build, '_prepared_world_file', fail_blocked)
    _run_world_worker_once(worker, monkeypatch)
    with state.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM index_jobs WHERE status='failed'").fetchone()[0] == 50
        conn.execute("UPDATE index_jobs SET finished_at=0 WHERE status='failed'")
    healthy = roots['worlds'] / 'healthy.json'
    healthy.write_text('{"name":"healthymarker","entries":{}}', encoding='utf-8')
    job_id = worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(healthy))
    batches = []
    claim = worker._claim_pending_jobs

    def observe_claim(limit):
        rows, pending = claim(limit)
        if rows:
            batches.append([row['id'] for row in rows])
        return rows, pending

    monkeypatch.setattr(worker, '_claim_pending_jobs', observe_claim)
    _run_world_worker_once(worker, monkeypatch)
    assert job_id in batches[0] and len(batches[0]) == 50
    assert sorted(map(len, batches)) == [1, 50]
    with state.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM index_jobs WHERE status='failed' AND finished_at>0").fetchone()[0] == 50
        conn.execute("UPDATE index_jobs SET finished_at=0 WHERE status='failed'")
    for mode in ('fast', 'fulltext'):
        assert query_worldinfo_index({'db_path': str(db), 'search': 'healthymarker', 'search_mode': mode})['total'] == 1

    blocked.clear()
    _run_world_worker_once(worker, monkeypatch)
    with state.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM index_jobs WHERE status='done'").fetchone()[0] == 51
    for mode in ('fast', 'fulltext'):
        assert query_worldinfo_index({'db_path': str(db), 'search': 'recoveredmarker', 'search_mode': mode})['total'] == 50


@pytest.mark.parametrize('order', [('resource', 'global'), ('global', 'resource'), ('resource',)])
def test_unbound_note_does_not_suppress_worldinfo_bootstrap(store, tmp_path, monkeypatch, order):
    from core.data.index_runtime_store import get_active_generation
    from core.services import index_build_service as build, index_upgrade_service as upgrade
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, resource = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    db = store[0]
    monkeypatch.setattr(upgrade, 'DEFAULT_DB_PATH', str(db))
    book = tmp_path / 'worlds' / 'global.json'
    book.write_text('{"name":"Global","entries":{}}', encoding='utf-8')
    targets = {'resource': resource, 'global': {'source_type': 'global', 'file_path': str(book)}}
    with state.connect(db) as conn:
        conn.execute("UPDATE index_build_state SET active_generation=0 WHERE scope='worldinfo'")
    with monkeypatch.context() as patch:
        def deny(path):
            raise PermissionError(str(path))
        patch.setattr(build, 'walk_directory_strict', deny)
        with pytest.raises(PermissionError):
            upgrade.rebuild_scope_generation('worldinfo')
    client = app.test_client()
    for source in order:
        result = client.post('/api/world_info/note/save', json={**targets[source], 'summary': source+'marker'}).get_json()
        assert result['success'], result
    _run_world_worker_once(worker, monkeypatch)
    with state.connect(db) as conn:
        assert [row[0] for row in conn.execute('SELECT status FROM index_jobs')] == ['done'] * len(order)
        assert get_active_generation(conn, 'worldinfo') == int('global' in order)
    if 'global' in order:
        for mode in ('fast', 'fulltext'):
            assert query_worldinfo_index({'db_path': str(db), 'search': 'globalmarker', 'search_mode': mode})['total'] == 1


@pytest.mark.parametrize('lock_at', ['startup', 'claim', 'projection', 'finish', 'first_batch_ack'])
def test_index_worker_survives_sqlite_write_timeout(store, tmp_path, monkeypatch, lock_at):
    import threading
    from contextlib import closing
    from core.context import ctx
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    roots, _, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    book = roots['worlds'] / 'book.json'
    book.write_text('{"name":"lockmarker","entries":{}}', encoding='utf-8')
    job = worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(book))
    locks_ack = lock_at in ('finish', 'first_batch_ack')
    if locks_ack:
        later = roots['worlds'] / 'later.json'
        later.write_text('{"name":"later","entries":{}}', encoding='utf-8')
        last = worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(later))
    else:
        last = job
    locked_job = job if lock_at == 'first_batch_ack' else last
    connect = worker._connect
    tasks = []
    timeouts = []
    processed = []
    wakeup = threading.Event()
    class StopWorker(Exception):
        pass

    class CapturedThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            tasks.append(self.target)

    # Drive the actual daemon entry point synchronously. A second SQLite connection
    # holds the write lock; only the busy timeout and the worker's wait are shortened.
    with closing(connect()) as blocker:
        def lock_once(original):
            def wrapped(*args, **kwargs):
                if not timeouts and not blocker.in_transaction and (not locks_ack or args[0] == locked_job):
                    if locks_ack:
                        blocker.execute("INSERT INTO index_jobs(job_type,status,error_msg) "
                                        "VALUES ('rebuild_scope','running','claim:other')")
                        blocker.commit()
                    blocker.execute('BEGIN IMMEDIATE')
                return original(*args, **kwargs)
            return wrapped

        def observe_projection(conn, row):
            processed.append(row['id'])
            result = process_world_job(conn, row)
            if lock_at == 'projection' and not timeouts and not blocker.in_transaction:
                blocker.execute('BEGIN IMMEDIATE')
            return result

        def release_on_backoff(seconds):
            assert seconds > 0 and blocker.in_transaction
            timeouts.append(seconds)
            assert ctx.index_worker_started
            assert blocker.execute('SELECT status FROM index_jobs WHERE id=?', (last,)).fetchone()[0] == (
                'running' if locks_ack or lock_at == 'projection' else 'pending')
            if locks_ack:
                assert blocker.execute('SELECT status FROM index_jobs WHERE id=?', (job,)).fetchone()[0] == (
                    'done' if lock_at == 'finish' else 'running')
            if lock_at == 'projection' and hasattr(sqlite3, 'SQLITE_BUSY_SNAPSHOT'):
                assert processed == [job]  # ordinary writer lock must skip the per-job fallback
            blocker.rollback()

        def wait(_timeout):
            if blocker.execute('SELECT status FROM index_jobs WHERE id=?', (last,)).fetchone()[0] == 'done':
                raise StopWorker()
            assert wakeup.is_set(), 'recovery must not require a second enqueue or poll'
            return True

        monkeypatch.setattr(ctx, 'index_upgrade_active', False)
        monkeypatch.setattr(ctx, 'index_worker_started', False)
        monkeypatch.setattr(ctx, 'index_wakeup', wakeup)
        monkeypatch.setattr(wakeup, 'wait', wait)
        monkeypatch.setattr(worker, 'INDEX_DB_TIMEOUT_SECONDS', 0.005)
        monkeypatch.setattr(worker.threading, 'Thread', CapturedThread)
        monkeypatch.setattr(worker.time, 'sleep', release_on_backoff)
        process_world_job = worker.process_worldinfo_job
        monkeypatch.setattr(worker, 'process_worldinfo_job', observe_projection)
        if lock_at == 'startup':
            blocker.execute('BEGIN IMMEDIATE')
        elif lock_at != 'projection':
            method = '_claim_pending_jobs' if lock_at == 'claim' else '_mark_job_status'
            monkeypatch.setattr(worker, method, lock_once(getattr(worker, method)))
        worker.start_index_job_worker()
        worker.start_index_job_worker()
        assert len(tasks) == 1
        with pytest.raises(StopWorker):
            tasks[0]()
        assert len(timeouts) == 1 and not ctx.index_worker_started
        if locks_ack:
            assert processed == [job, last]
            assert blocker.execute("SELECT status FROM index_jobs WHERE error_msg='claim:other'").fetchone()[0] == 'running'
        worker.start_index_job_worker()
        assert len(tasks) == 2
    for mode in ('fast', 'fulltext'):
        assert query_worldinfo_index({'db_path': str(store[0]), 'search': 'lockmarker', 'search_mode': mode})['total'] == 1


def test_worldinfo_batch_publishes_during_continuous_chat_progress_writes(store, tmp_path, monkeypatch):
    from core.services import index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, _ = _world_note_client(store, tmp_path, monkeypatch, 'global')
    client = app.test_client()
    for i in range(12):
        book = tmp_path / 'worlds' / f'note{i}.json'
        book.write_text('{"name":"Book","entries":{}}', encoding='utf-8')
        reply = client.post('/api/world_info/note/save', json={
            'source_type': 'global', 'file_path': str(book), 'summary': 'snapshotmarker',
        }).get_json()
        assert reply['success'], reply

    walk = build.walk_directory_strict
    prepared = build._prepared_world_file
    chat = state.Repository('chat')
    progress_saved = []
    scans = []

    def save_progress():
        progress_saved.append(True)
        chat.update_fields('chat.jsonl', {'last_view_floor': len(progress_saved)})

    def walk_with_progress(path):
        scans.append(path)
        for row in walk(path):
            save_progress()
            yield row

    def prepare_with_progress(*args, **kwargs):
        result = prepared(*args, **kwargs)
        save_progress()
        return result

    monkeypatch.setattr(build, 'walk_directory_strict', walk_with_progress)
    monkeypatch.setattr(build, '_prepared_world_file', prepare_with_progress)
    _run_world_worker_once(worker, monkeypatch)
    assert len(scans) == 1
    assert chat.get('chat.jsonl')['last_view_floor'] == 13
    with state.connect(store[0]) as conn:
        assert dict(conn.execute('SELECT status,count(*) FROM index_jobs GROUP BY status')) == {'done': 12}
    for mode in ('fast', 'fulltext'):
        assert query_worldinfo_index({'db_path': str(store[0]), 'search': 'snapshotmarker', 'search_mode': mode})[
            'total'] == 12


@pytest.mark.parametrize('concurrent_change', ['note', 'generation'])
def test_worldinfo_rejects_projection_prepared_from_changed_inputs(store, tmp_path, monkeypatch, concurrent_change):
    from core.services import index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    client = app.test_client()
    assert client.post('/api/world_info/note/save', json={**target, 'summary': 'oldpreparedmarker'}).get_json()['success']
    process = worker.process_worldinfo_job
    changes = []

    def replace_after_prepare(conn, row):
        result = process(conn, row)
        if not changes:
            assert not conn.in_transaction
            if concurrent_change == 'note':
                assert client.post('/api/world_info/note/save',
                                   json={**target, 'summary': 'newcommittedmarker'}).get_json()['success']
            else:
                with state.connect(store[0]) as writer:
                    writer.execute("UPDATE index_build_state SET active_generation=2 WHERE scope='worldinfo'")
            changes.append(True)
        return result

    applied_generations = []
    apply = build._apply_worldinfo_plans

    def record_write(conn, generation, plans, physical):
        assert conn.in_transaction
        applied_generations.append(generation)
        return apply(conn, generation, plans, physical)

    monkeypatch.setattr(worker, 'process_worldinfo_job', replace_after_prepare)
    monkeypatch.setattr(build, '_apply_worldinfo_plans', record_write)
    _run_world_worker_once(worker, monkeypatch)
    assert applied_generations == ([1, 1] if concurrent_change == 'note' else [2])
    marker = 'newcommittedmarker' if concurrent_change == 'note' else 'oldpreparedmarker'
    for mode in ('fast', 'fulltext'):
        assert query_worldinfo_index({'db_path': str(store[0]), 'search': marker, 'search_mode': mode})['total'] == 1
        if concurrent_change == 'note':
            assert query_worldinfo_index({'db_path': str(store[0]), 'search': 'oldpreparedmarker',
                                          'search_mode': mode})['total'] == 0


def test_rebuild_activation_survives_process_exit_before_cleanup(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    helper = Path(__file__).with_name('phase_two_crash_helper.py')
    command = [sys.executable, str(helper), str(tmp_path), 'rebuild_activation_recovery']
    crash = subprocess.run([*command, 'crash'], capture_output=True, timeout=30)
    assert crash.returncode == 77, crash.stderr.decode(errors='replace')
    recovered = subprocess.run([*command, 'recover'], capture_output=True, timeout=30)
    assert recovered.returncode == 0, recovered.stderr.decode(errors='replace')


def test_index_worker_retries_rebuild_ack_without_rebuilding(store, tmp_path, monkeypatch):
    from contextlib import closing
    from core.data.index_runtime_store import get_active_generation
    from core.services import index_upgrade_service as upgrade
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    roots, build, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    db = store[0]
    monkeypatch.setattr(upgrade, 'DEFAULT_DB_PATH', str(db))
    for i in range(205):
        (roots['worlds'] / f'b{i:03}.json').write_text('{"name":"ackmarker","entries":{}}', encoding='utf-8')
    job_id = worker.enqueue_index_job('rebuild_scope', payload={'scope': 'worldinfo'})
    mark = worker._mark_job_status
    backoffs = []
    opened = []

    def count_open(path, *args, **kwargs):
        opened.append(path)
        return open(path, *args, **kwargs)

    with closing(worker._connect()) as blocker:
        def lock_ack(job, status, error):
            assert job == job_id and status == 'done'
            if len(backoffs) < 2:
                blocker.execute('BEGIN IMMEDIATE')
            return mark(job, status, error)

        def release_after_timeout(_seconds):
            assert blocker.in_transaction
            assert get_active_generation(blocker, 'worldinfo') == 2
            assert blocker.execute('SELECT status FROM index_jobs WHERE id=?', (job_id,)).fetchone()[0] == 'done'
            backoffs.append(True)
            blocker.rollback()

        monkeypatch.setattr(worker, 'INDEX_DB_TIMEOUT_SECONDS', 0.005)
        monkeypatch.setattr(worker.time, 'sleep', release_after_timeout)
        monkeypatch.setattr(worker, '_mark_job_status', lock_ack)
        monkeypatch.setattr(build, 'open', count_open, raising=False)
        _run_world_worker_once(worker, monkeypatch)

    assert len(backoffs) == 2
    assert len(opened) == 205
    with state.connect(db) as conn:
        assert get_active_generation(conn, 'worldinfo') == 2
        assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (job_id,)).fetchone()[0] == 'done'
    for mode in ('fast', 'fulltext'):
        assert query_worldinfo_index({'db_path': str(db), 'search': 'ackmarker', 'search_mode': mode})['total'] == 205


@pytest.mark.parametrize('failure', ['open', 'enumerate'])
def test_missing_worldinfo_generation_shares_failed_bootstrap_across_claims(store, tmp_path, monkeypatch, failure):
    import time
    from types import SimpleNamespace
    from core.context import ctx
    from core.services import index_build_service as build, index_upgrade_service as upgrade
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, resource = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    db = store[0]
    monkeypatch.setattr(upgrade, 'DEFAULT_DB_PATH', str(db))
    world_root = tmp_path / 'worlds'
    books = [(world_root / f'd{i:03}' / 'book.json') if failure == 'enumerate' else (world_root / f'b{i:03}.json')
             for i in range(205)]
    for book in books:
        book.parent.mkdir(exist_ok=True)
        book.write_text('{"name":"Book","entries":{}}', encoding='utf-8')
    with state.connect(db) as conn:
        conn.execute("UPDATE index_build_state SET active_generation=0 WHERE scope='worldinfo'")
    client = app.test_client()
    for book in books[:12]:
        assert client.post('/api/world_info/note/save', json={'source_type': 'global', 'file_path': str(book),
                           'summary': 'sharedbootstrapmarker'}).get_json()['success']
    assert client.post('/api/world_info/note/save', json={**resource, 'summary': 'unbound'}).get_json()['success']
    # Force several claims within one wakeup using the real fair queue.
    claim = worker._claim_pending_jobs
    monkeypatch.setattr(worker, '_claim_pending_jobs', lambda limit: claim(5))
    access_attempts = []
    clock_offset = 0
    attempts = []
    waits = 0
    rebuild = worker.rebuild_scope_generation
    scandir = os.scandir

    def count_rebuild(scope, reason):
        attempts.append(scope)
        return rebuild(scope, reason)

    def deny_last(path, *args, **kwargs):
        if not clock_offset:
            access_attempts.append(path)
            if len(access_attempts) % len(books) == 0:
                raise PermissionError('last worldbook unavailable')
        return open(path, *args, **kwargs)

    def deny_last_child(path):
        if not clock_offset and isinstance(path, (str, os.PathLike)) and Path(path).parent == world_root:
            access_attempts.append(path)
            if len(access_attempts) % len(books) == 0:
                raise PermissionError('last worldbook unavailable')
        return scandir(path)

    class StopWorker(Exception):
        pass

    def wait(_timeout):
        nonlocal clock_offset, waits
        waits += 1
        if waits == 1:
            return True  # initial wakeup
        if waits == 3:
            raise StopWorker()
        assert len(access_attempts) == len(books)
        assert attempts == ['worldinfo']
        with state.connect(db) as conn:
            assert conn.execute("SELECT active_generation FROM index_build_state WHERE scope='worldinfo'").fetchone()[0] == 0
            assert dict(conn.execute('SELECT status,count(*) FROM index_jobs GROUP BY status')) == {'failed': 12, 'done': 1}
            assert all('last worldbook unavailable' in row[0] for row in conn.execute(
                "SELECT error_msg FROM index_jobs WHERE status='failed'"))
        clock_offset = worker.INDEX_JOB_RETRY_SECONDS + 1  # reads recover before the next poll
        return False

    monkeypatch.setattr(ctx, 'index_upgrade_active', False)
    monkeypatch.setattr(ctx.index_wakeup, 'wait', wait)
    monkeypatch.setattr(worker, 'time', SimpleNamespace(time=lambda: time.time() + clock_offset))
    if failure == 'open':
        monkeypatch.setattr(build, 'open', deny_last, raising=False)
    else:
        monkeypatch.setattr(os, 'scandir', deny_last_child)
    monkeypatch.setattr(worker, 'rebuild_scope_generation', count_rebuild)
    with pytest.raises(StopWorker):
        worker.worker_loop()
    assert attempts == ['worldinfo', 'worldinfo']
    with state.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM index_jobs WHERE status='done'").fetchone()[0] == 13
    for mode in ('fast', 'fulltext'):
        result = query_worldinfo_index({'db_path': str(db), 'search': 'sharedbootstrapmarker', 'search_mode': mode})
        assert result['total'] == 12


def test_index_cleanup_write_timeout_retries_only_obsolete_generation(store, tmp_path, monkeypatch):
    import time
    from contextlib import closing
    from types import SimpleNamespace
    from core.context import ctx
    from core.data import index_runtime_store as runtime
    from core.services import index_upgrade_service as upgrade
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    roots, build, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    db = store[0]
    monkeypatch.setattr(upgrade, 'DEFAULT_DB_PATH', str(db))
    for i in range(205):
        (roots['worlds'] / f'b{i:03}.json').write_text('{"name":"oldcleanupmarker","entries":{}}', encoding='utf-8')
    upgrade.rebuild_scope_generation('worldinfo')
    for book in roots['worlds'].glob('*.json'):
        book.write_text('{"name":"newcleanupmarker","entries":{}}', encoding='utf-8')
    worker.enqueue_index_job('rebuild_scope', payload={'scope': 'worldinfo'})
    cleanup = runtime.cleanup_obsolete_generation
    attempts, opened = [], []
    offset = 0
    waits = 0

    def count_open(path, *args, **kwargs):
        opened.append(path)
        return open(path, *args, **kwargs)

    def cleanup_with_lock(conn, scope, generation, **kwargs):
        attempts.append(generation)
        assert runtime.get_active_generation(conn, scope) == 3
        if offset:
            return cleanup(conn, scope, generation, **kwargs)
        conn.execute('PRAGMA busy_timeout=5')
        with closing(worker._connect()) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            try:
                return cleanup(conn, scope, generation, **kwargs)
            finally:
                blocker.rollback()

    def assert_visible():
        assert len(opened) == 205
        for mode in ('fast', 'fulltext'):
            assert query_worldinfo_index({'db_path': str(db), 'search': 'newcleanupmarker',
                                          'search_mode': mode})['total'] == 205

    class StopWorker(Exception):
        pass

    def wait(_timeout):
        nonlocal offset, waits
        waits += 1
        if waits == 1:
            return True
        assert_visible()
        with state.connect(db) as conn:
            assert runtime.get_active_generation(conn, 'worldinfo') == 3
            jobs = dict(conn.execute('SELECT job_type,status FROM index_jobs'))
            old_rows = conn.execute(
                "SELECT count(*) FROM index_entities_v2 WHERE entity_type='world_global' AND generation=2"
            ).fetchone()[0]
        assert jobs['rebuild_scope'] == 'done'
        if waits == 2:
            assert jobs['cleanup_generation'] == 'failed' and old_rows == 205
            offset = worker.INDEX_JOB_RETRY_SECONDS + 1
            return False
        assert jobs['cleanup_generation'] == 'done' and old_rows == 0
        raise StopWorker()

    monkeypatch.setattr(build, 'open', count_open, raising=False)
    monkeypatch.setattr(runtime, 'cleanup_obsolete_generation', cleanup_with_lock)
    monkeypatch.setattr(worker, 'cleanup_obsolete_generation', cleanup_with_lock)
    monkeypatch.setattr(ctx, 'index_upgrade_active', False)
    monkeypatch.setattr(ctx.index_wakeup, 'wait', wait)
    monkeypatch.setattr(worker, 'time', SimpleNamespace(time=lambda: time.time() + offset))
    with pytest.raises(StopWorker):
        worker.worker_loop()
    assert attempts == [2, 2, 2]


def test_legacy_card_receipts_repair_only_stale_active_notes(store, tmp_path, monkeypatch):
    from core.data.index_runtime_store import activate_generation, allocate_build_generation
    from core.services.card_index_query_service import query_indexed_cards

    roots, build, worker = _world_job_runtime(store, tmp_path, monkeypatch)
    db = store[0]
    notes = {'stale.json': {'summary': 'newmarker'}, 'current.json': {'summary': 'goodmarker'}}
    state.Repository().replace_snapshot(notes)
    for card_id in notes:
        (roots['cards'] / card_id).write_text('{}', encoding='utf-8')
    with state.connect(db) as conn:
        conn.executemany('INSERT INTO card_metadata(id) VALUES (?)', [(key,) for key in notes])
        generation = allocate_build_generation(conn, 'cards')
        with monkeypatch.context() as patch:
            patch.setattr(build, 'load_ui_data', lambda: {**notes, 'stale.json': {'summary': 'oldmarker'}})
            assert build.build_cards_generation(conn, generation) == 2
        assert activate_generation(conn, 'cards', generation, items_written=2)
        conn.execute('DROP TABLE card_ui_projections')
        conn.execute('CREATE TABLE card_ui_projections(card_id TEXT PRIMARY KEY,ui_key TEXT NOT NULL,'
                     'ui_revision INTEGER NOT NULL,source_revision TEXT NOT NULL)')
        conn.execute('INSERT INTO card_ui_projections SELECT r.key,r.key,r.revision,e.source_revision '
                     "FROM ui_records r JOIN index_entities_v2 e ON e.entity_id='card::'||r.key")
        conn.execute("CREATE TRIGGER reject_repair BEFORE INSERT ON index_jobs BEGIN SELECT RAISE(ABORT,'repair'); END")
    state._ready.clear()
    with pytest.raises(state.LocalStateError):
        state.initialize()
    with state.connect(db) as conn:
        assert 'generation' not in {row[1] for row in conn.execute('PRAGMA table_info(card_ui_projections)')}
        conn.execute('DROP TRIGGER reject_repair')
    state.initialize()
    state._ready.clear()
    state.initialize()
    with state.connect(db) as conn:
        assert [tuple(row) for row in conn.execute('SELECT entity_id,status FROM index_jobs')] == [('stale.json', 'pending')]
        assert {row[0] for row in conn.execute('SELECT generation FROM card_ui_projections')} == {0}
    _run_world_worker_once(worker, monkeypatch)
    for mode in ('fast', 'fulltext'):
        for word, expected in [('newmarker', 1), ('oldmarker', 0), ('goodmarker', 1)]:
            assert query_indexed_cards({'db_path': str(db), 'search': word, 'search_mode': mode})['total_count'] == expected


def test_legacy_receipt_check_reads_large_cold_bundle_once(store, tmp_path, monkeypatch):
    from core.data.index_runtime_store import activate_generation, allocate_build_generation

    _, build, _ = _world_job_runtime(store, tmp_path, monkeypatch)
    ids = [f'bundle/v{i:04}.json' for i in range(501)]
    state.Repository().update_fields('bundle', {'summary': 'covermarker', '_version_remarks': {
        key: {'summary': 'versionmarker'} for key in ids[1::2]}})
    with state.connect(store[0]) as conn:
        conn.executemany('INSERT INTO card_metadata(id,last_modified) VALUES (?,1)', [(key,) for key in ids])
        generation = allocate_build_generation(conn, 'cards')
        assert build.build_cards_generation(conn, generation) == len(ids)
        assert activate_generation(conn, 'cards', generation, items_written=len(ids))
        covers = conn.execute("SELECT entity_id FROM index_entities_v2 WHERE summary_preview='covermarker'")
        assert [row[0] for row in covers] == ['card::' + ids[0]]
        conn.executemany("INSERT INTO card_ui_projections(card_id,ui_key,ui_revision,source_revision) "
                         "VALUES (?,'bundle',1,'')", [(key,) for key in ids])
        conn.execute("UPDATE index_entities_v2 SET summary_preview='stale' WHERE entity_id=?", ('card::'+ids[-1],))
        statements = []
        conn.set_trace_callback(statements.append)
        state._queue_stale_legacy_card_notes(conn)
        conn.set_trace_callback(None)
        assert [row[0] for row in conn.execute('SELECT entity_id FROM index_jobs')] == [ids[-1]]
    assert sum('ORDER BY last_modified DESC,id' in sql for sql in statements) == 1
    assert sum('FROM ui_records WHERE key IN' in sql for sql in statements) == 1


def test_shared_resource_category_changes_prepare_each_owner_once(store, tmp_path, monkeypatch):
    from core.services import index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    db = store[0]
    owners = [f'owner{i:02}.json' for i in range(60)]
    state.Repository().replace_snapshot({key: {'resource_folder': 'assets'} for key in owners})
    with state.connect(db) as conn:
        conn.executemany('INSERT INTO card_metadata(id,category) VALUES (?,?)',
                         [(key, 'inheritedmarker') for key in owners[:-1]])
    client = app.test_client()
    builds = []
    collect = build.collect_worldbook_fulltext

    def count(book):
        builds.append(1)
        return collect(book)

    monkeypatch.setattr(build, 'collect_worldbook_fulltext', count)
    with state.connect(db) as conn:
        conn.execute("CREATE TRIGGER reject_category_refresh BEFORE INSERT ON index_jobs "
                     "BEGIN SELECT RAISE(ABORT,'refresh unavailable'); END")
    reply = client.post('/api/world_info/category/move',
                        json={**target, 'target_category': 'overridemarker'}).get_json()
    assert not reply['success']
    assert not ui_store.get_resource_item_categories(ui_store.load_ui_data())['worldinfo']
    with state.connect(db) as conn:
        conn.execute('DROP TRIGGER reject_category_refresh')
    for endpoint, old, new in [('move', 'inheritedmarker', 'overridemarker'),
                                ('reset', 'overridemarker', 'inheritedmarker')]:
        reply = client.post('/api/world_info/category/' + endpoint,
                            json={**target, 'target_category': 'overridemarker'}).get_json()
        assert reply['success'], reply
        with state.connect(db) as conn:
            assert [tuple(row) for row in conn.execute(
                "SELECT job_type,source_path FROM index_jobs WHERE status='pending'",
            )] == [('upsert_worldinfo_path', target['file_path'])]
            if endpoint == 'move':
                conn.execute('INSERT INTO card_metadata(id,category) VALUES (?,?)',
                             (owners[-1], 'inheritedmarker'))
        builds.clear()
        _run_world_worker_once(worker, monkeypatch)
        assert len(builds) == 60
        for mode in ('fast', 'fulltext'):
            for marker, total in ((old, 0), (new, 60)):
                assert query_worldinfo_index({
                    'db_path': str(db), 'search': marker, 'search_mode': mode,
                })['total'] == total


@pytest.mark.parametrize('updates', [1, 20])
def test_resource_category_burst_prepares_only_changed_books(store, tmp_path, monkeypatch, updates):
    from core.services import index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    db = store[0]
    folder = Path(target['file_path']).parent
    paths = [Path(target['file_path']), *(folder / f'book{i:02}.json' for i in range(1, 20))]
    for path in paths:
        path.write_text('{"name":"siblingmarker","entries":{}}', encoding='utf-8')
    owners = [f'owner{i:02}.json' for i in range(60)]
    state.Repository().replace_snapshot({key: {'resource_folder': 'assets'} for key in owners})
    with state.connect(db) as conn:
        conn.executemany('INSERT INTO card_metadata(id) VALUES (?)', [(key,) for key in owners])
        with build.worldinfo_increment_batch(conn):
            for owner in owners:
                build.apply_worldinfo_owner_increment(conn, owner, commit=False)

    opens, scans, builds = [], [], []
    collect, listdir = build.collect_worldbook_fulltext, os.listdir

    def count_open(path, *args, **kwargs):
        opens.append(Path(path))
        return open(path, *args, **kwargs)

    def count_scan(path):
        if Path(path) == folder:
            scans.append(path)
        return listdir(path)

    def count_build(book):
        builds.append(True)
        return collect(book)

    client = app.test_client()
    for path in paths[:updates]:
        response = client.post('/api/world_info/category/move', json={
            **target, 'file_path': str(path), 'target_category': 'burstmarker',
        }).get_json()
        assert response['success'], response
    with monkeypatch.context() as patch:
        patch.setattr(build, 'open', count_open, raising=False)
        patch.setattr(os, 'listdir', count_scan)
        patch.setattr(build, 'collect_worldbook_fulltext', count_build)
        _run_world_worker_once(worker, patch)
    assert opens == paths[:updates]
    assert not scans
    assert len(builds) == len(owners) * updates
    with state.connect(db) as conn:
        assert [row[0] for row in conn.execute('SELECT status FROM index_jobs')] == ['done'] * updates
    for mode in ('fast', 'fulltext'):
        for marker, count in [('burstmarker', updates * 60), ('siblingmarker', 1200)]:
            assert query_worldinfo_index({
                'db_path': str(db), 'search': marker, 'search_mode': mode,
            })['total'] == count


@pytest.mark.skipif(os.name != 'nt', reason='Windows path aliases')
def test_resource_path_aliases_share_intent_and_remove_stale_projection(store, tmp_path, monkeypatch):
    from core.services import index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    db = store[0]
    source = Path(target['file_path'])
    alias = source.parent.parent.with_name('ASSETS') / 'LOREBOOKS' / 'BOOK.JSON'
    assert alias.samefile(source)
    state.Repository().replace_snapshot({'owner.json': {'resource_folder': 'assetS'}})
    with state.connect(db) as conn:
        conn.execute("INSERT INTO card_metadata(id,category) VALUES ('owner.json','oldcategorymarker')")
        build.apply_worldinfo_owner_increment(conn, 'owner.json')

    client = app.test_client()
    reply = client.post('/api/world_info/category/move', json={
        **target, 'file_path': alias.as_posix(), 'target_category': 'freshcategorymarker',
    }).get_json()
    assert reply['success'], reply
    reply = client.post('/api/world_info/note/save', json={**target, 'summary': 'newnotemarker'}).get_json()
    assert reply['success'], reply
    with state.connect(db) as conn:
        assert [tuple(row) for row in conn.execute('SELECT source_path,status FROM index_jobs')] == [
            (alias.as_posix(), 'pending'),
        ]
    _run_world_worker_once(worker, monkeypatch)

    def check(expected):
        for mode in ('fast', 'fulltext'):
            for marker, count in zip(('oldcategorymarker', 'freshcategorymarker', 'newnotemarker'), expected):
                assert query_worldinfo_index({
                    'db_path': str(db), 'search': marker, 'search_mode': mode,
                })['total'] == count

    check((0, 1, 1))
    with state.connect(db) as conn:
        assert [row[0] for row in conn.execute(
            "SELECT entity_id FROM index_entities_v2 WHERE entity_type='world_resource'",
        )] == ['world::resource::owner.json::book.json']
    state.Repository().replace_snapshot({})
    source.unlink()
    worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(alias))
    _run_world_worker_once(worker, monkeypatch)
    check((0, 0, 0))


@pytest.mark.skipif(os.name != 'nt', reason='Windows case-only path changes')
def test_watchdog_global_case_rename_then_delete_removes_all_search_results(store, tmp_path, monkeypatch):
    from threading import Event

    from watchdog import observers

    from core.context import ctx
    from core.services import index_build_service as build, scan_service

    app, world_info, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'global')
    old = Path(target['file_path'])
    renamed = old.with_name('BOOK.json')
    db = store[0]
    cfg = {**world_info.load_config(), 'worldinfo_list_use_index': True}
    monkeypatch.setattr(world_info, 'load_config', lambda: cfg)
    monkeypatch.setattr(world_info, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(scan_service, 'load_config', lambda: cfg)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db))
    monkeypatch.setattr(ctx, 'should_ignore_fs_event', lambda: False)
    ctx.cache.initialized = True
    with state.connect(db) as conn:
        build.build_worldinfo_generation(conn, 1)

    observer = observers.Observer()
    monkeypatch.setattr(observers, 'Observer', lambda: observer)
    notified = Event()

    def enqueue(job, **kwargs):
        worker.enqueue_index_job(job, **kwargs)
        if kwargs['source_path'] == str(renamed):
            notified.set()

    monkeypatch.setattr(scan_service, 'enqueue_index_job', enqueue)
    client = app.test_client()

    def assert_hits(ids):
        for mode in ('fast', 'fulltext'):
            reply = client.get('/api/world_info/list', query_string={
                'type': 'global', 'search': 'book', 'search_mode': mode,
            }).get_json()
            assert reply['success'], reply
            assert [item['id'] for item in reply['items']] == ids

    scan_service.start_fs_watcher()
    try:
        assert_hits(['global::book.json'])
        old.rename(renamed)
        assert notified.wait(8), 'Watchdog did not enqueue the rename'
        _run_world_worker_once(worker, monkeypatch)
        assert_hits(['global::BOOK.json'])

        # Simulate the previously released schema, which only keyed resource projections.
        with state.connect(db) as conn:
            conn.execute('DROP INDEX idx_world_global_path_key')
            conn.execute("UPDATE index_entities_v2 SET path_key=NULL WHERE entity_type='world_global'")
        worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(old))
        notified.clear()
        renamed.unlink()
        assert notified.wait(8), 'Watchdog did not enqueue the deletion'
        with state.connect(db) as conn:
            assert [row[0] for row in conn.execute(
                "SELECT source_path FROM index_jobs WHERE status='pending'",
            )] == [str(old)]
        _run_world_worker_once(worker, monkeypatch)
        assert_hits([])
        with state.connect(db) as conn:
            assert {row[0] for row in conn.execute('SELECT status FROM index_jobs')} == {'done'}
    finally:
        observer.stop()
        observer.join(timeout=8)


def test_resource_job_read_failure_keeps_successful_preparations_in_one_batch(store, tmp_path, monkeypatch):
    from core.services import index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    db = store[0]
    root = tmp_path / 'worlds'
    for i in range(200):
        (root / f'sub{i:03}').mkdir()
    books = [Path(target['file_path']).with_name(f'book{i:02}.json') for i in range(26)]
    state.Repository().replace_snapshot({'owner.json': {'resource_folder': 'assets'}})
    with state.connect(db) as conn:
        conn.execute("INSERT INTO card_metadata(id) VALUES ('owner.json')")

    client = app.test_client()
    for book in books:
        book.write_text('{"name":"Book","entries":{}}', encoding='utf-8')
        reply = client.post('/api/world_info/note/save', json={
            **target, 'file_path': str(book), 'summary': 'batchnotemarker',
        }).get_json()
        assert reply['success'], reply

    opens, scans = [], []
    walk = build.walk_directory_strict

    def open_with_one_failure(path, *args, **kwargs):
        opens.append(Path(path))
        if Path(path) == books[-1]:
            raise PermissionError('resource book access denied')
        return open(path, *args, **kwargs)

    def count_walk(path):
        scans.append(Path(path))
        yield from walk(path)

    def assert_search_total(total):
        for mode in ('fast', 'fulltext'):
            assert query_worldinfo_index({
                'db_path': str(db), 'search': 'batchnotemarker', 'search_mode': mode,
            })['total'] == total

    with monkeypatch.context() as fault:
        fault.setattr(build, 'open', open_with_one_failure, raising=False)
        fault.setattr(build, 'walk_directory_strict', count_walk)
        _run_world_worker_once(worker, fault)
    assert opens == books
    assert scans == [root]
    assert_search_total(25)
    with state.connect(db) as conn:
        assert [row[0] for row in conn.execute('SELECT status FROM index_jobs ORDER BY id')] == ['done'] * 25 + ['failed']
        conn.execute("UPDATE index_jobs SET finished_at=0 WHERE status='failed'")
    _run_world_worker_once(worker, monkeypatch)
    assert_search_total(26)


@pytest.mark.skipif(os.name != 'nt', reason='Windows per-directory case sensitivity')
@pytest.mark.parametrize('source', ['global', 'resource'])
def test_case_sensitive_worldinfo_paths_keep_independent_search_projections(store, tmp_path, monkeypatch, source):
    import subprocess

    from core.services import index_build_service as build

    app, world_info, worker, target = _world_note_client(store, tmp_path, monkeypatch, source)
    db = store[0]
    lower = Path(target['file_path'])
    lower.unlink()
    switched = subprocess.run(['fsutil', 'file', 'SetCaseSensitiveInfo', str(lower.parent), 'enable'], capture_output=True)
    if switched.returncode != 0:
        pytest.skip('temporary filesystem does not allow enabling case sensitivity')
    upper = lower.with_name('BOOK.json')
    lower.write_text('{"name":"lowerbookmarker","entries":{}}', encoding='utf-8')
    upper.write_text('{"name":"upperbookmarker","entries":{}}', encoding='utf-8')
    assert not lower.samefile(upper)
    if source == 'resource':
        (tmp_path / 'cards' / 'owner.json').write_text('{"name":"Owner"}', encoding='utf-8')
        state.Repository().replace_snapshot({'owner.json': {'resource_folder': 'assets'}})
        with state.connect(db) as conn:
            conn.execute("INSERT INTO card_metadata(id,char_name) VALUES ('owner.json','Owner')")
    with state.connect(db) as conn:
        assert build.build_worldinfo_generation(conn, 1) == 2

    cfg = {**world_info.load_config(), 'worldinfo_list_use_index': True}
    monkeypatch.setattr(world_info, 'load_config', lambda: cfg)
    monkeypatch.setattr(world_info, 'DEFAULT_DB_PATH', str(db))
    world_info.ctx.cache.initialized = True
    client = app.test_client()

    def search(marker, expected):
        for mode in ('fast', 'fulltext'):
            result = client.get('/api/world_info/list', query_string={
                'type': source, 'search': marker, 'search_mode': mode,
            }).get_json()
            assert result['success'], result
            assert [item['file_name'] for item in result['items']] == expected

    def save(path, marker):
        result = client.post('/api/world_info/note/save', json={
            **target, 'file_path': path.as_posix(), 'summary': marker,
        }).get_json()
        assert result['success'], result

    search('upperbookmarker', ['BOOK.json'])
    save(lower, 'lowernotemarker')
    _run_world_worker_once(worker, monkeypatch)
    search('upperbookmarker', ['BOOK.json'])
    search('lowernotemarker', ['book.json'])
    save(upper, 'uppernotemarker')
    save(lower, 'nextlowernotemarker')
    with state.connect(db) as conn:
        assert {Path(row[0]).name for row in conn.execute(
            "SELECT source_path FROM index_jobs WHERE status='pending'",
        )} == {'BOOK.json', 'book.json'}
    _run_world_worker_once(worker, monkeypatch)
    search('uppernotemarker', ['BOOK.json'])
    search('nextlowernotemarker', ['book.json'])
    lower.unlink()
    worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(lower))
    _run_world_worker_once(worker, monkeypatch)
    search('uppernotemarker', ['BOOK.json'])
    search('lowerbookmarker', [])


def test_worldinfo_category_scan_failure_retries_batch_without_rereading_books(store, tmp_path, monkeypatch):
    from core.services import index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    db = store[0]
    root = tmp_path / 'worlds'
    for i in range(200):
        (root / f'sub{i:03}').mkdir()
    books = [Path(target['file_path']).with_name(f'book{i:02}.json') for i in range(26)]
    for book in books:
        book.write_text('{"name":"oldbookmarker","entries":{}}', encoding='utf-8')
    Path(target['file_path']).unlink()
    (tmp_path / 'cards' / 'owner.json').write_text('{"name":"Owner"}', encoding='utf-8')
    state.Repository().replace_snapshot({'owner.json': {'resource_folder': 'assets'}})
    with state.connect(db) as conn:
        conn.execute("INSERT INTO card_metadata(id) VALUES ('owner.json')")
        assert build.build_worldinfo_generation(conn, 1) == 26
    client = app.test_client()
    for book in books:
        reply = client.post('/api/world_info/note/save', json={
            **target, 'file_path': str(book), 'summary': 'batchretrymarker',
        }).get_json()
        assert reply['success'], reply

    opens, scans = [], []
    walk = build.walk_directory_strict

    def count_open(path, *args, **kwargs):
        opens.append(Path(path))
        return open(path, *args, **kwargs)

    def failing_walk(path):
        scans.append(Path(path))
        for i, entry in enumerate(walk(path)):
            if i == 200:
                raise PermissionError('last directory unreadable')
            yield entry

    def search(marker, count):
        for mode in ('fast', 'fulltext'):
            assert query_worldinfo_index({
                'db_path': str(db), 'search': marker, 'search_mode': mode,
            })['total'] == count

    with monkeypatch.context() as fault:
        fault.setattr(build, 'open', count_open, raising=False)
        fault.setattr(build, 'walk_directory_strict', failing_walk)
        _run_world_worker_once(worker, fault)
    assert opens == books
    assert scans == [root]
    search('oldbookmarker', 26)
    search('batchretrymarker', 0)
    with state.connect(db) as conn:
        assert dict(conn.execute('SELECT status,count(*) FROM index_jobs GROUP BY status')) == {'failed': 26}
        conn.execute("UPDATE index_jobs SET finished_at=0 WHERE status='failed'")
    _run_world_worker_once(worker, monkeypatch)
    search('batchretrymarker', 26)


def test_path_key_upgrade_keeps_legacy_pending_job_and_active_projection(store, tmp_path, monkeypatch):
    from core.data.index_runtime_store import RUNTIME_SCHEMA_STATEMENTS
    from core.services import index_job_worker as worker
    from core.utils.filesystem import filesystem_path_bucket

    db = store[0]
    path = str(tmp_path / 'Assets' / 'lorebooks' / 'Book.json')
    old_path = Path(path).as_posix()
    entity = 'world::resource::owner.json::Book.json'
    monkeypatch.setattr(worker, 'DEFAULT_DB_PATH', str(db))
    with state.connect(db) as conn:
        for statement in RUNTIME_SCHEMA_STATEMENTS:
            conn.execute(statement)
        conn.execute('CREATE TABLE card_resource_bindings (card_ui_key TEXT PRIMARY KEY, resource_folder TEXT)')
        conn.execute("INSERT INTO card_resource_bindings VALUES ('owner.json','Assets')")
        job = conn.execute("INSERT INTO index_jobs(job_type, source_path, payload_json) "
                           "VALUES ('upsert_worldinfo_path', ?, ?)",
                           (old_path, '{"resource_note":true}')).lastrowid
        conn.execute('''INSERT INTO index_entities_v2 (
            generation,entity_id,entity_type,source_path,owner_entity_id,name,filename
        ) VALUES (2,?,'world_resource',?,'card::owner.json','Book','Book.json')''', (entity, old_path))
        state.ensure_schema(conn)
        ensure_index_runtime_schema(conn)
        conn.execute("UPDATE index_build_state SET active_generation=2 WHERE scope='worldinfo'")
        assert conn.execute("SELECT resource_folder,folder_key FROM card_resource_bindings").fetchone()[:] == (
            'Assets', filesystem_path_bucket('Assets'),
        )
        assert [tuple(row) for row in worker._indexed_resource_rows(conn, filesystem_path_bucket(path))] == [
            (entity, 'card::owner.json', old_path),
        ]
        assert conn.execute('SELECT source_path FROM index_entities_v2 WHERE entity_id=?', (entity,)).fetchone()[0] == old_path
    assert worker.enqueue_index_job('upsert_worldinfo_path', source_path=path) == job
    with state.connect(db) as conn:
        assert [tuple(row) for row in conn.execute('SELECT id,source_path,status FROM index_jobs')] == [
            (job, old_path, 'pending'),
        ]


@pytest.mark.parametrize('legacy_payload', [{}, {'resource_note': True}, {'unbound_resource_note': True}])
def test_unbound_resource_note_skips_unavailable_global_root(store, tmp_path, monkeypatch, legacy_payload):
    from core.services import index_build_service as build

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    calls = []

    def deny(path):
        calls.append(path)
        raise PermissionError(path)

    monkeypatch.setattr(build, 'walk_directory_strict', deny)
    reply = app.test_client().post('/api/world_info/note/save', json={**target, 'summary': 'saved'}).get_json()
    assert reply['success'], reply
    with state.connect(store[0]) as conn:
        if legacy_payload:
            conn.execute('UPDATE index_jobs SET payload_json=?', (json.dumps(legacy_payload),))
    _run_world_worker_once(worker, monkeypatch)
    assert not calls
    with state.connect(store[0]) as conn:
        assert [row[0] for row in conn.execute('SELECT status FROM index_jobs')] == ['done']
    assert ui_store.get_worldinfo_note(
        ui_store.load_ui_data(), 'resource', file_path=target['file_path'],
    )['summary'] == 'saved'


def test_shared_resource_note_expands_once_at_consumption_and_commits_atomically(store, tmp_path, monkeypatch):
    from core.services import index_build_service as build
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'resource')
    db = store[0]
    owners = [f'owner{i:02}.json' for i in range(60)]
    state.Repository().replace_snapshot({key: {'resource_folder': 'assets'} for key in owners})
    with state.connect(db) as conn:
        conn.executemany('INSERT INTO card_metadata(id) VALUES (?)', [(key,) for key in owners[:-1]])
    client = app.test_client()
    def save(summary):
        reply = client.post('/api/world_info/note/save', json={**target, 'summary': summary}).get_json()
        assert reply['success'], reply
    save('previousmarker')
    with state.connect(db) as conn:
        assert [tuple(row) for row in conn.execute('SELECT job_type,source_path FROM index_jobs')] == [
            ('upsert_worldinfo_path', target['file_path'])]
        # This owner becomes available after the API has committed the intent.
        conn.execute('INSERT INTO card_metadata(id) VALUES (?)', (owners[-1],))

    builds = 0
    collect = build.collect_worldbook_fulltext
    def count(book):
        nonlocal builds
        builds += 1
        return collect(book)
    monkeypatch.setattr(build, 'collect_worldbook_fulltext', count)
    _run_world_worker_once(worker, monkeypatch)
    assert builds == len(owners)
    def check_words(old, new):
        for mode in ('fast', 'fulltext'):
            for word, hits in [('previousmarker', old), ('currentmarker', new)]:
                assert query_worldinfo_index({'db_path': str(db), 'search': word, 'search_mode': mode})['total'] == hits
    check_words(60, 0)
    save('currentmarker')
    with state.connect(db) as conn:
        conn.execute("CREATE TRIGGER reject_last BEFORE INSERT ON index_entities_v2 "
                     "WHEN NEW.owner_entity_id='card::owner59.json' BEGIN SELECT RAISE(ABORT,'last owner'); END")
    _run_world_worker_once(worker, monkeypatch)
    check_words(60, 0)
    with state.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE status='failed'").fetchone()[0] == 1
        conn.execute('DROP TRIGGER reject_last')
        conn.execute("UPDATE index_jobs SET finished_at=0 WHERE status='failed'")
    builds = 0
    _run_world_worker_once(worker, monkeypatch)
    check_words(0, 60)
    assert builds == len(owners)


@pytest.mark.parametrize('size', [25, 5000])
def test_generation_ui_connections_do_not_grow_with_card_count(store, tmp_path, monkeypatch, size):
    _, build, _ = _world_job_runtime(store, tmp_path, monkeypatch)
    ids = [f'group{i % 5}/hero{i}.json' for i in range(size)]
    ui = {key: {'summary': 'cardmarker'} for key in ids[::2]}
    ui['group1'] = {'_version_remarks': {ids[1]: {'summary': 'versionmarker'}}}
    state.Repository().replace_snapshot(ui)
    books = {key: {'name': 'Book', 'entries': {}} for key in ids}
    connect = state.connect
    opened = 0
    batches = []
    get_many = state.Repository.get_many
    def record_batch(repo, keys=None, *, conn=None):
        assert keys is not None and conn is not None and conn.in_transaction
        batches.append(len(keys))
        return get_many(repo, keys, conn=conn)
    def count(*args, **kwargs):
        nonlocal opened
        opened += 1
        return connect(*args, **kwargs)
    with connect(store[0]) as conn:
        conn.executemany('INSERT INTO card_metadata(id,char_name) VALUES (?,?)', ((key,key) for key in ids))
        conn.commit()
        monkeypatch.setattr(state, 'connect', count)
        monkeypatch.setattr(state.Repository, 'get_many', record_batch)
        assert build.build_cards_generation(conn, 2) == size
        assert opened == 1
        opened = 0
        assert build.build_worldinfo_generation(conn, 3, inspected_books=books) == size
        assert opened == 1
        assert max(batches) <= build.BUILD_COMMIT_BATCH_SIZE + 6  # 5 parents and the library root
        for scope, key, expected in [('card', ids[0], 'cardmarker'), ('card', ids[1], 'versionmarker'),
                                     ('world::embedded', ids[0], 'cardmarker'), ('world::embedded', ids[3], '')]:
            row = conn.execute('SELECT summary_preview FROM index_entities_v2 WHERE entity_id=?',
                               (scope + '::' + key,)).fetchone()
            assert row[0] == expected


def test_worldinfo_note_refuses_to_overwrite_non_object_member(store, tmp_path, monkeypatch):
    app, _, _, target = _world_note_client(store, tmp_path, monkeypatch, 'embedded')
    note_key = ui_store.build_worldinfo_note_key('embedded', card_id=target['card_id'])
    state.Repository().replace_snapshot({ui_store.WORLDINFO_NOTES_KEY: {note_key: 'opaque legacy value'}})

    reply = app.test_client().post('/api/world_info/note/save', json={**target, 'summary': 'new note'}).get_json()

    assert reply['success'] is False
    assert '格式无效' in reply['msg']
    assert state.NamespaceRepository(ui_store.WORLDINFO_NOTES_KEY).get(note_key) == 'opaque legacy value'


def test_worldinfo_note_and_refresh_job_commit_or_roll_back_together(store, tmp_path, monkeypatch):
    app, _, worker, target = _world_note_client(store, tmp_path, monkeypatch, 'embedded')
    from core.services import index_build_service
    from core.utils.image import write_card_metadata
    from core.utils.png_metadata import build_card_pnginfo
    card = tmp_path / 'cards' / 'hero.png'
    card.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (8, 8), 'blue').save(
        card, pnginfo=build_card_pnginfo(json.dumps({'data': {'name': 'Hero', 'description': 'old'}})))
    data = extract_card_info(str(card))
    data['data']['character_book'] = {'name': 'Book', 'entries': [{'content': 'lore'}]}
    assert write_card_metadata(str(card), data, prepare_intent=False)
    state.Repository().update_fields('hero.png', {'summary': ''})
    from flask import Flask
    from core.services import cache_service
    from core.data import db_session
    monkeypatch.setattr(cache_service, 'CARDS_FOLDER', str(tmp_path / 'cards'))
    monkeypatch.setattr(cache_service, 'DEFAULT_DB_PATH', str(store[0]))
    monkeypatch.setattr(db_session, 'DEFAULT_DB_PATH', str(store[0]))
    with Flask(__name__).app_context():
        assert cache_service.update_card_cache('hero.png', str(card))['cache_updated']

    client = app.test_client()
    assert client.post('/api/world_info/note/save', json={**target, 'summary': 'before'}).get_json()['success']
    with worker._connect() as conn:
        index_build_service.apply_worldinfo_embedded_increment(conn, 'hero.png', str(card))
        conn.execute('DELETE FROM index_jobs')
        conn.execute("CREATE TRIGGER reject_note_refresh BEFORE INSERT ON index_jobs "
                     "WHEN NEW.job_type='upsert_world_embedded' "
                     "BEGIN SELECT RAISE(ABORT, 'job write failed'); END")
        conn.commit()

    rejected = client.post('/api/world_info/note/save', json={
        **target, 'summary': 'new committed note'}).get_json()
    assert rejected['success'] is False
    assert ui_store.get_worldinfo_note(ui_store.load_ui_data(), 'embedded',
                                       card_id='hero.png')['summary'] == 'before'
    with worker._connect() as conn:
        entity = conn.execute("SELECT summary_preview FROM index_entities_v2 WHERE "
                              "entity_id='world::embedded::hero.png'").fetchone()
        assert 'before' in entity[0]
        assert conn.execute('SELECT COUNT(*) FROM index_jobs').fetchone()[0] == 0
        conn.execute('DROP TRIGGER reject_note_refresh')
        conn.commit()

    retried = client.post('/api/world_info/note/save', json={
        **target, 'summary': 'new committed note'}).get_json()
    assert retried['success'] and retried['ui_summary'] == 'new committed note'
    rows, _ = worker._claim_pending_jobs(50)
    assert len(rows) == 1 and rows[0]['job_type'] == 'upsert_world_embedded'
    with worker._connect() as conn:
        with index_build_service.worldinfo_increment_batch(conn):
            worker.process_worldinfo_job(conn, rows[0])
        conn.commit()
    worker._mark_job_status(rows[0]['id'], 'done', '')
    with worker._connect() as conn:
        entity = conn.execute("SELECT summary_preview FROM index_entities_v2 WHERE "
                              "entity_id='world::embedded::hero.png'").fetchone()
        fast = conn.execute("SELECT content FROM index_search_fast_v2 WHERE "
                            "entity_id='world::embedded::hero.png'").fetchone()
        assert 'new committed note' in entity[0] and 'new committed note' in fast[0]


def test_plugin_private_single_member_avoids_reading_other_plugins(store, tmp_path, monkeypatch):
    from core.plugins.api import PluginAPI
    from core.plugins.manifest import PluginManifest
    from tests.plugins_test_support import write_plugin
    api = PluginAPI(PluginManifest.load(write_plugin(tmp_path, 'demo-plugin')))
    records = {f'plugin-{i}': {'opaque': 'x' * 200} for i in range(10000)}
    records['demo-plugin'] = {'value': 'before', 'unknown': [False, None]}
    state.Repository().replace_snapshot({'_plugins_v1': records})
    read = state.NamespaceRepository._read_records
    observed = []
    def observe(self, *args, **kwargs):
        result = read(self, *args, **kwargs)
        observed.extend(result)
        return result
    with monkeypatch.context() as patch:
        patch.setattr(state.NamespaceRepository, '_read_records', observe)
        assert api.private.read()['value'] == 'before'
        assert api.private.update(lambda entry: entry.update(value='after'))
        assert api.private.read() == {'value': 'after', 'unknown': [False, None]}
    assert observed and set(observed) == {'demo-plugin'} and len(observed) < 8
    assert state.NamespaceRepository('_plugins_v1').get('plugin-9999') == {'opaque': 'x' * 200}


@pytest.mark.parametrize('targeted', [False, True])
def test_namespace_confirmation_does_not_acknowledge_writer_after_commit(store, monkeypatch, targeted):
    repo = state.Repository()
    repo.replace_snapshot({'_notes': {'one': 'before'}})
    snapshot = ui_store.load_ui_data()
    entry = snapshot.namespace_members('_notes', ['one']) if targeted else snapshot['_notes']
    entry['one'] = 'mine'
    confirm = state.StateSnapshot.confirm_saved
    late = []
    def confirm_after_later_writer(current):
        if current.repository.component == 'namespace' and not late:
            late.append(True)
            repo.update_fields('_notes', {'later': 'concurrent after commit'})
        return confirm(current)
    with monkeypatch.context() as patch:
        patch.setattr(state.StateSnapshot, 'confirm_saved', confirm_after_later_writer)
        assert repo.save(snapshot)
    assert entry.root_revision < repo.revision('_notes')
    if targeted:
        with pytest.raises(state.StateConflict):
            list(entry)
    snapshot['_notes'] = {'one': 'replacement'}
    with pytest.raises(state.StateConflict):
        repo.save(snapshot)
    assert repo.get('_notes')['later'] == 'concurrent after commit'


@pytest.mark.parametrize('expansion', [False, True])
def test_targeted_namespace_root_and_members_share_read_transaction(store, monkeypatch, expansion):
    repo = state.Repository()
    repo.replace_snapshot({'_notes': {'one': 'before', 'two': 'before'}})
    entry = repo.get_namespace_members('_notes', ['one']) if expansion else None
    read = state.NamespaceRepository._read_records
    target = 'two' if expansion else 'one'
    writes = []
    def commit_between_root_and_member(self, *args, **kwargs):
        if not writes:
            writes.append(True)
            repo.update_fields('_notes', {target: 'concurrent'})
        return read(self, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(state.NamespaceRepository, '_read_records', commit_between_root_and_member)
        if expansion:
            assert entry[target] == 'before'
        else:
            entry = repo.get_namespace_members('_notes', ['one'])
            assert entry[target] == 'before'
    assert writes and repo.get('_notes')[target] == 'concurrent'
    assert entry.root_revision < repo.revision('_notes')
