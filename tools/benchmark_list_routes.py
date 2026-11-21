"""Compare real Flask routes and SQLite on isolated data, including older checkouts."""

import argparse
import builtins
import hashlib
import io
import json
import os
import platform
import sqlite3
import sys
import threading
import tracemalloc
from collections import Counter
from contextlib import ExitStack, closing, redirect_stdout
from pathlib import Path
from statistics import median, quantiles
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import patch


def run(repo, count, chat_count, samples):
    sys.path.insert(0, str(repo))
    from flask import Flask
    from core.api.v1 import cards, chats
    from core.context import ctx
    from core.data import db_session, local_state_repository as state
    from core.data.cache import GlobalMetadataCache
    from core.services import index_upgrade_service
    try:
        from core.services import chat_catalog_service
    except ImportError:
        chat_catalog_service = None

    with TemporaryDirectory(prefix='stm-list-perf-') as tmp, ExitStack() as stack:
        root = Path(tmp)
        paths = {name: str(root / name) for name in ('cards', 'chats', 'worlds', 'resources', 'temp')}
        for value in paths.values():
            Path(value).mkdir()
        db = str(root / 'metadata.db')
        cfg = {'cards_dir': paths['cards'], 'chats_dir': paths['chats'],
               'world_info_dir': paths['worlds'], 'resources_dir': paths['resources'],
               'cards_list_use_index': False, 'fast_search_use_index': False}
        changes = dict(DEFAULT_DB_PATH=db, CARDS_FOLDER=paths['cards'], CHATS_FOLDER=paths['chats'],
                       TEMP_DIR=paths['temp'], CONFIG_FILE=str(root / 'config.json'),
                       UI_DATA_FILE=str(root / 'ui.json'), CHAT_DATA_FILE=str(root / 'chat.json'),
                       load_config=lambda: cfg)
        for module in list(sys.modules.values()):
            if getattr(module, '__name__', '').startswith('core'):
                for name, value in changes.items():
                    if hasattr(module, name):
                        stack.enter_context(patch.object(module, name, value))
        cache = GlobalMetadataCache()
        stack.enter_context(patch.object(ctx, 'cache', cache))
        state.initialize()
        with closing(sqlite3.connect(db)) as conn, conn, redirect_stdout(io.StringIO()):
            db_session._initialize_database(conn, is_existing_db=True, schema_only=True)
            rows = []
            for i in range(count):
                folder = f'Zone-{i % 20:02d}'
                if 10 <= i < 30:
                    folder = 'Zone-00/Bundle'
                cid = 'note.json' if i == 0 else f'{folder}/card-{i:06}.json'
                rows.append((cid, f'卡片 {i:06} 🐉', '["合成","sample"]', '' if i == 0 else folder,
                             'Author', 1700000000 + i, 100 + i % 50, i % 9 == 0))
            conn.executemany('INSERT INTO card_metadata '
                             '(id,char_name,tags,category,creator,last_modified,token_count,is_favorite) '
                             'VALUES (?,?,?,?,?,?,?,?)', rows)
        for i in range(20):
            (Path(paths['cards']) / f'Zone-{i:02d}').mkdir()
        bundle = Path(paths['cards']) / 'Zone-00' / 'Bundle'
        bundle.mkdir()
        (bundle / '.bundle').touch()
        (Path(paths['cards']) / 'Empty').mkdir()
        (Path(paths['cards']) / 'note.json').write_text('{"data":{"name":"Synthetic"}}', encoding='utf-8')
        for i in range(chat_count):
            folder = Path(paths['chats']) / f'Owner-{i % 20:02d}'
            folder.mkdir(exist_ok=True)
            body = '中文 preview ' + 'x' * (60000 if i % 50 == 0 else 40)
            chat_path = folder / f'chat-{i:04}.jsonl'
            chat_path.write_text(
                json.dumps({'user_name': 'User', 'character_name': 'AI', 'chat_metadata': {}}) + '\n' +
                json.dumps({'is_user': True, 'mes': body}, ensure_ascii=False) + '\n', encoding='utf-8')
            os.utime(chat_path, (1700000000 + i, 1700000000 + i))
        with closing(state.connect()) as conn, conn:
            repo = state.Repository('ui')
            uid = '3621d9a1-d989-43e4-b1d5-5cd583db8c93'
            conn.execute('UPDATE card_metadata SET card_uid=? WHERE id=?', (uid, 'note.json'))
            repo._put(conn, 'note.json', {'card_uid': uid,
                                         'chat_ids': [f'Owner-{i % 20:02d}/chat-{i:04}.jsonl'
                                                      for i in range(min(chat_count, 10))]})
        started = perf_counter()
        cache.reload_from_db(strict=True)
        cache_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        with redirect_stdout(io.StringIO()):
            index_upgrade_service.rebuild_scope_generation('cards', reason='benchmark')
        card_build_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        if chat_catalog_service:
            chat_catalog_service.reconcile(paths['chats'])
        chat_build_ms = (perf_counter() - started) * 1000 if chat_catalog_service else None
        app = Flask(__name__)
        app.register_blueprint(cards.bp)
        app.register_blueprint(chats.bp)
        app.teardown_appcontext(db_session.close_connection)
        client = app.test_client()
        sql = {'statements': 0, 'vm_blocks_1000': 0}
        original_connect = sqlite3.connect
        statements = []

        def increment(key):
            sql[key] += 1
            return 0

        def instrumented(*args, **kwargs):
            conn = original_connect(*args, **kwargs)
            def trace(statement):
                increment('statements')
                if any(part in statement for part in ('FROM card_list_items c', 'FROM chat_files f',
                                                       'FROM chat_card_bindings target', 'FROM card_list_facets')):
                    statements.append(statement)
            conn.set_trace_callback(trace)
            conn.set_progress_handler(lambda: increment('vm_blocks_1000'), 1000)
            return conn

        results = {}
        routes = {
            'cards': ('/api/list_cards', {'page': 2}),
            'cards_deep': ('/api/list_cards', {'page': max(1, count // 25)}),
            'cards_complex': ('/api/list_cards', {'category': 'Zone-00', 'search': '卡片', 'tags': '合成',
                                                 'token_min': 120, 'sort': 'token_asc'}),
            'chats': ('/api/chats/list', {'page_size': 12}),
            'chats_card': ('/api/chats/list', {'card_id': 'note.json'}),
        }
        for scenario in (*routes, 'note'):
            values = []

            def request(i):
                if scenario == 'note':
                    return client.post('/api/update_card', json={'id': 'note.json', 'ui_only': True,
                        'ui_only_fields': ['ui_summary'], 'ui_summary': f'合成备注 {i}'})
                url, params = routes[scenario]
                return client.get(url, query_string=params)

            result = None
            for i in range(samples + 1):
                started = perf_counter()
                response = request(i)
                elapsed = (perf_counter() - started) * 1000
                result = response.get_json()
                assert response.status_code == 200 and result.get('success', True), result
                values.append(elapsed)
            for key in sql:
                sql[key] = 0
            statements.clear()
            calls = Counter()
            original_open, original_stat = builtins.open, os.stat

            def measure_file(func, label):
                def counted(path, *args, **kwargs):
                    if isinstance(path, (str, Path)) and any(str(path).startswith(paths[name] + os.sep)
                                                             for name in ('cards', 'chats')):
                        calls[label] += 1
                    return func(path, *args, **kwargs)
                return counted

            def measure_call(func, label):
                def counted(*args, **kwargs):
                    calls[label] += 1
                    return func(*args, **kwargs)
                return counted

            tracemalloc.start()
            try:
                with ExitStack() as measures:
                    measures.enter_context(patch.object(sqlite3, 'connect', instrumented))
                    measures.enter_context(patch.object(builtins, 'open', measure_file(original_open, 'file_open')))
                    measures.enter_context(patch.object(os, 'stat', measure_file(original_stat, 'file_stat')))
                    for module, name, label in ((chats, 'get_chat_jsonl_index', 'chat_index_calls'),
                                                 (chat_catalog_service, 'get_chat_jsonl_index', 'chat_index_calls'),
                                                 (cards, 'extract_card_info', 'card_extract_calls'),
                                                 (cards, 'calculate_token_count', 'token_count_calls')):
                        if module and hasattr(module, name):
                            measures.enter_context(patch.object(module, name, measure_call(getattr(module, name), label)))
                    measured = request(samples + 1)
                    assert measured.status_code == 200
                _, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            plans = []
            count_ms = None
            with closing(original_connect(db)) as reader:
                reader.create_function('chat_lower', 1, lambda value: str(value or '').lower())
                reader.create_function('valid_chat_owner', 2, lambda *_: None)
                for statement in dict.fromkeys(statements):
                    plans.append([row[3] for row in reader.execute('EXPLAIN QUERY PLAN ' + statement.lstrip())])
                    if statement.startswith(('SELECT count(*) FROM card_list_items', 'SELECT coalesce(sum(count),0)')):
                        timings = []
                        for _ in range(samples):
                            started = perf_counter()
                            reader.execute(statement).fetchone()
                            timings.append((perf_counter() - started) * 1000)
                        count_ms = round(median(timings), 2)
            rows = result.get('cards', result.get('items', []))
            signature = {'ids': [row['id'] for row in rows],
                         'total': result.get('total_count', result.get('total')),
                         'stats': result.get('stats'), 'tags': sorted(result.get('sidebar_tags', [])),
                         'counts': result.get('category_counts'), 'folders': result.get('all_folders')}
            results[scenario] = dict(cold_ms=round(values[0], 2), p50_ms=round(median(values[1:]), 2),
                                     p95_ms=round(quantiles(values[1:], n=100, method='inclusive')[94], 2)
                                     if samples >= 20 else None, sql=dict(sql), plans=plans,
                                     traced_python_peak_kib=round(peak / 1024, 1), io=dict(calls), count_p50_ms=count_ms,
                                     total=signature['total'], stats=signature['stats'],
                                     first_id=signature['ids'][0] if signature['ids'] else None,
                                     signature=hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()[:12])
        errors = []

        def rebuild():
            try:
                index_upgrade_service.rebuild_scope_generation('cards', reason='benchmark_busy')
            except Exception as exc:
                errors.append(exc)

        busy = []
        with redirect_stdout(io.StringIO()):
            worker = threading.Thread(target=rebuild)
            worker.start()
            while worker.is_alive() and len(busy) < samples:
                started = perf_counter()
                response = client.get('/api/list_cards', query_string={'page': 2})
                assert response.status_code == 200
                busy.append((perf_counter() - started) * 1000)
            worker.join()
        if errors:
            raise errors[0]
        results['cards_busy'] = dict(samples=len(busy), p50_ms=round(median(busy), 2) if busy else None,
                                     p95_ms=round(quantiles(busy, n=100, method='inclusive')[94], 2)
                                     if len(busy) >= 20 else None)
        return dict(cards=count, chats=chat_count, samples=samples, platform=platform.platform(),
                    python=platform.python_version(), sqlite=sqlite3.sqlite_version,
                    cache_ms=round(cache_ms, 2), card_build_ms=round(card_build_ms, 2),
                    chat_build_ms=None if chat_build_ms is None else round(chat_build_ms, 2), results=results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--cards', type=int, required=True)
    parser.add_argument('--chats', type=int, required=True)
    parser.add_argument('--samples', type=int, default=20)
    options = parser.parse_args()
    print(json.dumps(run(options.repo.resolve(), options.cards, options.chats, options.samples),
                     ensure_ascii=False))
