"""Isolated daily-operation benchmark: python tools/benchmark_daily_operations.py.

Synthetic content only; no app startup, scanners, or user paths are accessed.
Times include real persistence and indexing (FULL durability); fixture setup is excluded.
"""
import argparse
import gc
from collections import Counter
from contextlib import ExitStack, closing
import json
import io
import os
from pathlib import Path
import sqlite3
from statistics import median
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask
from PIL import Image

from core.api.v1 import chats, cards
from core.context import ctx
from core.data import ui_store, db_session
from core.data.cache import GlobalMetadataCache
from core.services import card_service, index_build_service, card_index_sync_service
from core.utils.image import write_card_metadata


def benchmark(card_count, chat_count, *, scenario=None):
    with tempfile.TemporaryDirectory(prefix='stm_daily_perf_') as root, ExitStack() as stack:
        counts = Counter()
        timings = Counter()
        synthetic_config = {'cards_dir': str(Path(root) / 'fixture-inactive'), 'world_info_dir': str(Path(root) / 'worlds'),
            'resources_dir': str(Path(root) / 'resources'), 'chats_dir': str(Path(root) / 'chats'),
            'presets_dir': str(Path(root) / 'presets')}
        for name in ('worlds', 'resources', 'chats', 'presets'):
            (Path(root) / name).mkdir(exist_ok=True)
        # Redirect every already-bound default before any persistence or history access.
        for module in list(sys.modules.values()):
            if not getattr(module, '__name__', '').startswith('core'):
                continue
            for attribute, value in (('DEFAULT_DB_PATH', str(Path(root) / 'metadata.db')),
                                     ('CONFIG_FILE', str(Path(root) / 'config.json')),
                                     ('UI_DATA_FILE', str(Path(root) / 'ui.json')),
                                     ('CHAT_DATA_FILE', str(Path(root) / 'chat.json'))):
                if hasattr(module, attribute):
                    stack.enter_context(patch.object(module, attribute, value))
            if hasattr(module, 'load_config'):
                stack.enter_context(patch.object(module, 'load_config', lambda: dict(synthetic_config)))

        def instrument(module, name, label):
            original = getattr(module, name)

            def measured(*args, **kwargs):
                counts[label] += 1
                start = perf_counter()
                try:
                    return original(*args, **kwargs)
                finally:
                    timings[label] += (perf_counter() - start) * 1000

            stack.enter_context(patch.object(module, name, measured))

        stack.enter_context(patch.object(ui_store, 'UI_DATA_FILE', str(Path(root) / 'ui.json')))
        from core.data import chat_store
        try:
            from core.data import local_state_repository
        except ImportError:
            local_state_repository = None
        if local_state_repository is not None:
            stack.enter_context(patch.object(local_state_repository, 'DEFAULT_DB_PATH', str(Path(root) / 'metadata.db')))
            local_state_repository._ready.clear()
        stack.enter_context(patch.object(chat_store, 'CHAT_DATA_FILE', str(Path(root) / 'chat.json')))
        cache = GlobalMetadataCache()
        stack.enter_context(patch.object(ctx, 'cache', cache))
        payload = {f'card-{i}.png': {'summary': 'synthetic note', 'chat_ids': [f'chat-{i % chat_count}.jsonl']}
                   for i in range(card_count)}
        cache.id_map = {key: {'id': key, 'char_name': key, 'tags': ['sample'],
                             'source_update': {'last_status': 'unchecked'}} for key in payload}
        card_path = Path(root) / 'card-0.png'
        if scenario and 'large-png' in scenario:
            Image.effect_noise((2048, 2048), 64).convert('RGB').save(card_path)
        else:
            Image.new('RGB', (64, 64)).save(card_path)
        write_card_metadata(str(card_path), {'data': {'name': 'Synthetic', 'tags': ['sample'],
            'character_book': {'entries': [{'keys': ['synthetic'], 'content': 'x' * 128}
                                            for _ in range(5000 if scenario and 'large-book' in scenario else 5)]}}})
        db_path = str(Path(root) / 'metadata.db')
        with sqlite3.connect(db_path) as conn, redirect_stdout(io.StringIO()):
            db_session._initialize_database(conn, is_existing_db=True, schema_only=True)
            conn.execute('INSERT INTO card_metadata(id, char_name, tags, category, last_modified) VALUES (?, ?, ?, ?, ?)',
                         ('card-0.png', 'Synthetic', '["sample"]', '', card_path.stat().st_mtime))
            conn.executemany('INSERT INTO index_entities_v2 '
                             '(generation,entity_id,entity_type,source_path,name,filename) VALUES (1,?,?,?,?,?)',
                             [(f'card::card-{i}.png', 'card', str(Path(root) / f'card-{i}.png'),
                               'Synthetic', f'card-{i}.png') for i in range(card_count)])
            conn.executemany('INSERT INTO index_search_fast_v2 VALUES (1,?,?)',
                             [(f'card::card-{i}.png', 'synthetic text') for i in range(card_count)])
            conn.executemany('INSERT INTO index_search_full_v2 VALUES (1,?,?)',
                             [(f'card::card-{i}.png', 'synthetic text') for i in range(card_count)])
            from core.data import index_runtime_store
            if hasattr(index_runtime_store, 'repair_full_search_mapping'):
                index_runtime_store.repair_full_search_mapping(conn)
            from core.utils.source_revision import build_file_source_revision
            conn.execute("UPDATE index_entities_v2 SET source_revision=? WHERE entity_id='card::card-0.png'",
                         (build_file_source_revision(str(card_path)),))
            conn.execute("UPDATE index_build_state SET active_generation = 1 WHERE scope = 'cards'")
            conn.commit()
        conn.close()
        synthetic_config['cards_dir'] = root
        for module in (cards, card_service, index_build_service, db_session):
            for attribute, value in (('CARDS_FOLDER', root), ('DEFAULT_DB_PATH', db_path)):
                stack.enter_context(patch.object(module, attribute, value))
        stack.enter_context(patch.object(cards, 'suppress_fs_events', lambda *args: None))
        from core.services import index_job_worker
        stack.enter_context(patch.object(index_job_worker, 'DEFAULT_DB_PATH', db_path))
        stack.enter_context(patch.object(index_job_worker, 'CARDS_FOLDER', root, create=True))
        start = perf_counter()
        if local_state_repository is not None:
            (Path(root) / 'ui.json').write_text(json.dumps(payload), encoding='utf-8')
            local_state_repository.initialize()
        else:
            assert ui_store.save_ui_data(payload)
        migration_ms = (perf_counter() - start) * 1000
        from core import config
        stack.enter_context(patch.object(config, 'CARDS_FOLDER', root))
        global_dir = Path(root) / 'worlds'
        resource_dir = Path(root) / 'resources'
        global_dir.mkdir(exist_ok=True)
        resource_dir.mkdir(exist_ok=True)
        stack.enter_context(patch.object(index_build_service, 'load_config', lambda: {
            'world_info_dir': str(global_dir), 'resources_dir': str(resource_dir)}))
        if local_state_repository is not None:
            instrument(local_state_repository.Repository, '_put', 'record_write')
        instrument(index_build_service, 'apply_card_increment', 'index_increment')
        # Every connection is real; tracing observes persisted SQL rather than replacing it.
        sql_counts = Counter()
        original_connect = sqlite3.connect
        def traced_connect(*args, **kwargs):
            connection = original_connect(*args, **kwargs)
            def trace(sql):
                statement = sql.lstrip().upper()
                for label, prefix in [('ui_sql_write', 'INSERT INTO UI_RECORDS'),
                                      ('fts_insert', 'INSERT INTO INDEX_SEARCH_FULL_V2'),
                                      ('entity_insert', 'INSERT OR REPLACE INTO INDEX_ENTITIES_V2'),
                                      ('job_insert', 'INSERT INTO INDEX_JOBS')]:
                    if statement.startswith(prefix):
                        sql_counts[label] += 1
            connection.set_trace_callback(trace)
            return connection
        stack.enter_context(patch.object(sqlite3, 'connect', traced_connect))
        for name, label in (('_read_json_file', 'ui_parse'), ('_write_ui_data_file_atomic', 'ui_save')):
            if hasattr(ui_store, name):
                instrument(ui_store, name, label)
        instrument(cache, '_rebuild_global_tags_locked', 'tag_rebuild')
        instrument(chats, '_build_binding_info', 'binding_scan')
        if hasattr(chats, '_build_binding_table'):
            instrument(chats, '_build_binding_table', 'binding_table')
        start = perf_counter()
        data = ui_store.load_ui_data()
        data['card-0.png']['summary'] = 'updated synthetic note'
        ui_store.save_ui_data(data)
        ui_store.load_ui_data()  # synchronous index's UI read
        cache.update_card_data('card-0.png', {'tags': ['sample']})
        note_ms = (perf_counter() - start) * 1000
        start = perf_counter()
        table = chats._build_binding_table(data) if hasattr(chats, '_build_binding_table') else data
        for i in range(chat_count):
            chats._build_chat_item(f'chat-{i}.jsonl', {}, table)
        list_ms = (perf_counter() - start) * 1000
        for module in (cards, card_service):
            for name, label in (('extract_card_info', 'card_parse'), ('write_card_metadata', 'png_write'),
                                ('calculate_token_count', 'token'), ('get_file_hash_and_size', 'card_hash')):
                if hasattr(module, name):
                    instrument(module, name, label)
        before_counts = counts.copy()
        sql_counts.clear()
        app = Flask(__name__)
        app.register_blueprint(cards.bp)
        app.teardown_appcontext(db_session.close_connection)
        before_sql_bytes = Path(db_path).stat().st_size + sum(p.stat().st_size for p in Path(root).glob('metadata.db-wal'))
        start = perf_counter()
        response = app.test_client().post('/api/update_card', json={
            'id': 'card-0.png', 'ui_only': True, 'ui_only_fields': ['ui_summary'],
            'ui_summary': 'route synthetic note',
        }).get_json()
        route_ms = (perf_counter() - start) * 1000
        after_sql_bytes = Path(db_path).stat().st_size + sum(p.stat().st_size for p in Path(root).glob('metadata.db-wal'))
        assert response['success'], response
        route_counts = {key: counts[key] - before_counts[key] for key in
                        ('ui_parse', 'ui_save', 'record_write', 'index_increment', 'card_parse', 'png_write', 'token', 'card_hash', 'tag_rebuild')}
        route_sql_counts = dict(sql_counts)
        route_io = {'logical_ui_json_written_bytes': route_counts['ui_save'] * (Path(root) / 'ui.json').stat().st_size,
                    'card_file_read_bytes': 0, 'card_file_written_bytes': 0}
        with closing(sqlite3.connect(db_path)) as reader:
            ui_payload_bytes = (reader.execute("SELECT length(CAST(payload_json AS BLOB)) FROM ui_records "
                                               "WHERE key='card-0.png'").fetchone()[0]
                                if local_state_repository is not None else 0)
        scenario_result = {}
        if scenario:
            scenario_result = benchmark_body_scenario(stack, root, card_path, db_path, cache, app,
                counts, sql_counts, instrument, scenario, local_state_repository)
        gc.collect()  # Older implementations leave SQLite context-manager cycles for GC.
        return {'scenario': scenario or 'note', 'migration_ms': round(migration_ms, 2), **scenario_result, 'cards': card_count, 'real_fts_entities': card_count, 'chats': chat_count,
                'sql_file_growth_bytes': after_sql_bytes - before_sql_bytes, 'sql_counts': route_sql_counts,
                'note_logical_io': route_io, 'note_ui_payload_bytes': ui_payload_bytes,
                'legacy_ui_bytes': (Path(root) / 'ui.json').stat().st_size if (Path(root) / 'ui.json').exists() else 0, 'ui_save_cycle_ms': round(note_ms, 2),
                'binding_items_ms': round(list_ms, 2), 'note_route_ms': round(route_ms, 2),
                'note_route_counts': route_counts, 'counts': dict(counts),
                'segments_ms': {k: round(v, 2) for k, v in timings.items()}}


def benchmark_body_scenario(stack, root, card_path, db_path, cache, app, counts, sql_counts,
                            instrument, scenario, repository):
    from core.services import cache_service, index_job_worker
    from core.utils import png_metadata
    from core import config
    for module in (cache_service,):
        stack.enter_context(patch.object(module, 'CARDS_FOLDER', root))
        stack.enter_context(patch.object(module, 'DEFAULT_DB_PATH', db_path))
    instrument(cache_service, 'extract_card_info', 'card_parse')
    instrument(cache_service, 'calculate_token_count', 'token')
    instrument(cache_service, 'get_file_hash_and_size', 'card_hash')
    from core.utils import image as image_module
    if hasattr(image_module, 'read_png_text'):
        instrument(image_module, 'read_png_text', 'chunk_read')
    instrument(Image.Image, 'save', 'pixel_encode')
    # Bundle cover and non-cover target share a root record, with separate notes.
    target_id = 'card-0.png'
    if 'bundle' in scenario:
        bundle = Path(root) / 'bundle'
        bundle.mkdir()
        (bundle / '.bundle').write_text('1')
        import shutil
        shutil.copyfile(card_path, bundle / 'main.png')
        shutil.copyfile(card_path, bundle / 'old.png')
        target_id = 'bundle/old.png'
        for name in ('main.png', 'old.png'):
            with app.app_context():
                assert cache_service.update_card_cache('bundle/' + name, str(bundle / name))['cache_updated']
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            for name in ('main.png', 'old.png'):
                index_build_service.apply_card_increment(conn, 'bundle/' + name, str(bundle / name))
        cache.id_map['bundle/main.png'] = {'id': 'bundle/main.png', 'is_bundle': True,
            'bundle_dir': 'bundle', 'versions': [{'id': 'bundle/main.png'}, {'id': target_id}],
            'tags': ['sample'], 'source_update': {'last_status': 'unchecked'}}
        cache.bundle_map['bundle'] = 'bundle/main.png'
    target = Path(root) / target_id
    from core.utils.image import extract_card_info
    saved_body = extract_card_info(str(target))['data']
    times, operations = [], []
    for index in range(3):
        if index == 0:
            from core.utils import image
            if hasattr(image, '_IMAGE_REVISIONS'):
                image._IMAGE_REVISIONS.clear()
        counts.clear()
        sql_counts.clear()
        started = perf_counter()
        response = app.test_client().post('/api/update_card', json={**saved_body, 'char_name': saved_body.get('name'), 'id': target_id,
            'description': f'synthetic body {index}', 'ui_summary': f'combined note {index}'}).get_json()
        times.append(round((perf_counter() - started) * 1000, 2))
        assert response['success'], response
        with closing(sqlite3.connect(db_path)) as reader:
            pending = reader.execute("SELECT COUNT(*) FROM index_jobs WHERE job_type='upsert_card' AND status='pending'").fetchone()[0]
        operations.append({'counts': dict(counts), 'sql': dict(sql_counts),
                           'pending_card_jobs': pending,
                           'png_output_bytes': target.stat().st_size})
    # A file commit with an unprocessed durable intent models process death before cache/index.
    recovery_ms = None
    recovered = 0
    if repository is not None:
        counts.clear()
        sql_counts.clear()
        from core.utils.image import extract_card_info, write_card_metadata
        info = extract_card_info(str(target))
        info['data']['description'] = 'crash recovery latest file'
        assert write_card_metadata(str(target), info)
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            pending = conn.execute("SELECT * FROM index_jobs WHERE job_type='upsert_card' AND status='pending'").fetchall()
        started = perf_counter()
        for row in pending:
            index_job_worker.process_card_job(row, json.loads(row['payload_json']))
            recovered += 1
        recovery_ms = round((perf_counter() - started) * 1000, 2)
        with sqlite3.connect(db_path) as conn:
            assert conn.execute('SELECT description FROM card_metadata WHERE id=?', (target_id,)).fetchone()[0] == 'crash recovery latest file'
    return {'body_cold_ms': times[0], 'body_hot_median_ms': median(times[1:]),
            'body_samples_ms': times, 'body_operations': operations,
            'png_bytes': target.stat().st_size, 'recovery_ms': recovery_ms,
            'recovered_card_jobs': recovered}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sizes', nargs='+', type=int, default=[1000, 10000])
    parser.add_argument('--chats', nargs='+', type=int, default=[10, 100])
    parser.add_argument('--scenarios', action='store_true', help='also measure body/bundle/PNG/recovery')
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    if args.scenarios:
        for size in args.sizes:
            for scenario in ('ordinary-small', 'ordinary-large-book', 'bundle-small', 'bundle-large-png-large-book'):
                print(json.dumps(benchmark(size, args.chats[0], scenario=scenario), ensure_ascii=False), flush=True)
        sys.exit(0)
    for size in args.sizes:
        for count in args.chats:
            samples = [benchmark(size, count) for _ in range(max(1, args.repeat))]
            result = samples[0]
            result['timing_samples_ms'] = {key: [sample[key] for sample in samples]
                                          for key in ('ui_save_cycle_ms', 'binding_items_ms', 'note_route_ms', 'migration_ms')}
            for key in ('ui_save_cycle_ms', 'binding_items_ms', 'note_route_ms', 'migration_ms'):
                result[key] = round(median(sample[key] for sample in samples), 2)
            result['segments_ms'] = {key: round(median(sample['segments_ms'].get(key, 0)
                                                      for sample in samples), 2)
                                     for key in result['segments_ms']}
            result['samples'] = len(samples)
            print(json.dumps(result, ensure_ascii=False))
