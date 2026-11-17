"""Isolated phase-one baseline: python tools/benchmark_daily_operations.py.

Synthetic content only; no app startup, scanners, or user paths are accessed.
Times include synchronous JSON durability and backup rotation, but exclude fixture setup.
"""
import argparse
import gc
from collections import Counter
from contextlib import ExitStack
import json
import io
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


def benchmark(card_count, chat_count):
    with tempfile.TemporaryDirectory(prefix='stm_daily_perf_') as root, ExitStack() as stack:
        counts = Counter()
        timings = Counter()

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
        cache = GlobalMetadataCache()
        stack.enter_context(patch.object(ctx, 'cache', cache))
        payload = {f'card-{i}.png': {'summary': 'synthetic note', 'chat_ids': [f'chat-{i % chat_count}.jsonl']}
                   for i in range(card_count)}
        cache.id_map = {key: {'id': key, 'char_name': key, 'tags': ['sample'],
                             'source_update': {'last_status': 'unchecked'}} for key in payload}
        card_path = Path(root) / 'card-0.png'
        Image.new('RGB', (1, 1)).save(card_path)
        write_card_metadata(str(card_path), {'data': {'name': 'Synthetic', 'tags': ['sample'],
            'character_book': {'entries': [{'keys': ['synthetic'], 'content': 'x' * 128}
                                            for _ in range(500)]}}})
        db_path = str(Path(root) / 'metadata.db')
        with sqlite3.connect(db_path) as conn, redirect_stdout(io.StringIO()):
            db_session._initialize_database(conn, is_existing_db=True, schema_only=True)
            conn.execute('INSERT INTO card_metadata(id, char_name, tags, category, last_modified) VALUES (?, ?, ?, ?, ?)',
                         ('card-0.png', 'Synthetic', '["sample"]', '', card_path.stat().st_mtime))
            conn.execute("UPDATE index_build_state SET active_generation = 1 WHERE scope = 'cards'")
            conn.commit()
        conn.close()
        for module in (cards, card_service, index_build_service, db_session):
            for attribute, value in (('CARDS_FOLDER', root), ('DEFAULT_DB_PATH', db_path)):
                stack.enter_context(patch.object(module, attribute, value))
        stack.enter_context(patch.object(cards, 'suppress_fs_events', lambda *args: None))
        stack.enter_context(patch.object(card_index_sync_service, 'enqueue_index_job', lambda *args, **kw: None))
        ui_store.save_ui_data(payload)
        instrument(ui_store, '_read_json_file', 'ui_parse')
        instrument(ui_store, '_write_ui_data_file_atomic', 'ui_save')
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
        app = Flask(__name__)
        app.register_blueprint(cards.bp)
        app.teardown_appcontext(db_session.close_connection)
        start = perf_counter()
        response = app.test_client().post('/api/update_card', json={
            'id': 'card-0.png', 'ui_only': True, 'ui_only_fields': ['ui_summary'],
            'ui_summary': 'route synthetic note',
        }).get_json()
        route_ms = (perf_counter() - start) * 1000
        assert response['success'], response
        route_counts = {key: counts[key] - before_counts[key] for key in
                        ('ui_parse', 'ui_save', 'card_parse', 'png_write', 'token', 'card_hash', 'tag_rebuild')}
        gc.collect()  # Older implementations leave SQLite context-manager cycles for GC.
        return {'cards': card_count, 'chats': chat_count, 'ui_save_cycle_ms': round(note_ms, 2),
                'binding_items_ms': round(list_ms, 2), 'note_route_ms': round(route_ms, 2),
                'note_route_counts': route_counts, 'counts': dict(counts),
                'segments_ms': {k: round(v, 2) for k, v in timings.items()}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sizes', nargs='+', type=int, default=[1000, 10000])
    parser.add_argument('--chats', nargs='+', type=int, default=[10, 100])
    parser.add_argument('--repeat', type=int, default=3)
    args = parser.parse_args()
    for size in args.sizes:
        for count in args.chats:
            samples = [benchmark(size, count) for _ in range(max(1, args.repeat))]
            result = samples[0]
            for key in ('ui_save_cycle_ms', 'binding_items_ms', 'note_route_ms'):
                result[key] = round(median(sample[key] for sample in samples), 2)
            result['segments_ms'] = {key: round(median(sample['segments_ms'].get(key, 0)
                                                      for sample in samples), 2)
                                     for key in result['segments_ms']}
            result['samples'] = len(samples)
            print(json.dumps(result, ensure_ascii=False))
