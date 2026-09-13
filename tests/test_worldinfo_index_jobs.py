import json
import logging
import sqlite3
import sys
import types
from io import BytesIO
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.services import cache_service
from core.services import card_index_sync_service
from core.services import index_build_service
from core.services import scan_service
from core.services import index_job_worker


def test_worldinfo_watch_filter_accepts_global_and_resource_lorebooks(monkeypatch):
    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})

    assert scan_service._is_worldinfo_watch_path('D:/data/lorebooks/main/book.json') is True
    assert scan_service._is_worldinfo_watch_path('D:/data/resources/lucy/lorebooks/book.json') is True
    assert scan_service._is_worldinfo_watch_path('D:/data/resources/lucy/images/cover.png') is False


def test_classify_worldinfo_path_distinguishes_global_resource_and_invalid(monkeypatch):
    monkeypatch.setattr(
        index_build_service,
        'load_config',
        lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'},
    )

    assert index_build_service.classify_worldinfo_path('D:/data/lorebooks/main/book.json') == {
        'kind': 'global',
        'source_path': 'D:/data/lorebooks/main/book.json',
    }
    assert index_build_service.classify_worldinfo_path('D:/data/resources/hero-assets/lorebooks/book.json') == {
        'kind': 'resource',
        'source_path': 'D:/data/resources/hero-assets/lorebooks/book.json',
    }
    assert index_build_service.classify_worldinfo_path('D:/data/resources/hero-assets/images/cover.png') == {
        'kind': 'invalid',
        'source_path': 'D:/data/resources/hero-assets/images/cover.png',
    }


def test_resolve_resource_worldinfo_owner_card_ids_returns_all_matching_cards(monkeypatch):
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})
    monkeypatch.setattr(
        index_build_service,
        'load_ui_data',
        lambda: {
            'cards/zeta.png': {'resource_folder': 'shared-pack'},
            'cards/alpha.png': {'resource_folder': 'shared-pack'},
            'cards/other.png': {'resource_folder': 'other-pack'},
        },
    )

    assert index_build_service.resolve_resource_worldinfo_owner_card_ids('D:/data/resources/shared-pack/lorebooks/book.json') == [
        'cards/alpha.png',
        'cards/zeta.png',
    ]


def test_update_card_cache_returns_embedded_worldinfo_facts(monkeypatch):
    class _FakeConn:
        def cursor(self):
            return self

        def execute(self, *_args, **_kwargs):
            return self

        def fetchone(self):
            return {'is_favorite': 0, 'has_character_book': 0}

        def commit(self):
            return None

    monkeypatch.setattr(cache_service, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(cache_service, 'get_file_hash_and_size', lambda _path: ('h', 12))
    monkeypatch.setattr(cache_service, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': [], 'character_book': {'name': 'Book', 'entries': {}}}})
    monkeypatch.setattr(cache_service, 'calculate_token_count', lambda _payload: 111)
    monkeypatch.setattr(cache_service, 'get_wi_meta', lambda _payload: (True, 'Book'))

    result = cache_service.update_card_cache('cards/hero.png', 'D:/cards/hero.png', mtime=123.0)

    assert result == {
        'cache_updated': True,
        'has_embedded_wi': True,
        'previous_has_embedded_wi': False,
    }


def test_update_card_cache_ignores_cleanup_payload_and_returns_persistence_facts(monkeypatch):
    class _FakeConn:
        def cursor(self):
            return self

        def execute(self, *_args, **_kwargs):
            return self

        def fetchone(self):
            return {'is_favorite': 0, 'has_character_book': 0}

        def commit(self):
            return None

    monkeypatch.setattr(cache_service, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(cache_service, 'get_file_hash_and_size', lambda _path: ('h', 12))
    monkeypatch.setattr(cache_service, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': ['blue']}})
    monkeypatch.setattr(cache_service, 'calculate_token_count', lambda _payload: 111)
    monkeypatch.setattr(cache_service, 'get_wi_meta', lambda _payload: (False, ''))

    result = cache_service.update_card_cache(
        'cards/hero-renamed.png',
        'D:/cards/hero-renamed.png',
        mtime=123.0,
        remove_entity_ids=['cards/hero.json'],
    )

    assert result == {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    }


def test_update_card_cache_returns_previous_embedded_worldinfo_fact_when_removed(monkeypatch):
    class _FakeConn:
        def cursor(self):
            return self

        def execute(self, query, *_args, **_kwargs):
            self._last_query = query
            return self

        def fetchone(self):
            if 'SELECT is_favorite, has_character_book' in getattr(self, '_last_query', ''):
                return {'is_favorite': 0, 'has_character_book': 1}
            return {'is_favorite': 0}

        def commit(self):
            return None

    monkeypatch.setattr(cache_service, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(cache_service, 'get_file_hash_and_size', lambda _path: ('h', 12))
    monkeypatch.setattr(cache_service, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': []}})
    monkeypatch.setattr(cache_service, 'calculate_token_count', lambda _payload: 111)
    monkeypatch.setattr(cache_service, 'get_wi_meta', lambda _payload: (False, ''))

    result = cache_service.update_card_cache('cards/hero.png', 'D:/cards/hero.png', mtime=123.0)

    assert result == {
        'cache_updated': True,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': True,
    }


def test_worldinfo_watch_filter_rejects_sibling_prefix_paths(monkeypatch):
    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})

    assert scan_service._is_worldinfo_watch_path('D:/data/lorebooks2/x.json') is False


def test_worldinfo_watch_filter_is_case_tolerant_for_valid_paths(monkeypatch):
    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})

    assert scan_service._is_worldinfo_watch_path('d:/DATA/LOREBOOKS/main/book.JSON') is True
    assert scan_service._is_worldinfo_watch_path('d:/DATA/RESOURCES/lucy/LOREBOOKS/book.JSON') is True


def test_worldinfo_watcher_move_into_lorebook_path_enqueues_dest_path(monkeypatch):
    calls = []
    scheduled = {}

    class _FakeObserver:
        daemon = False

        def schedule(self, handler, watch_path, recursive=True):
            scheduled['handler'] = handler
            scheduled['watch_path'] = watch_path
            scheduled['recursive'] = recursive

        def start(self):
            scheduled['started'] = True

    class _FakeHandlerBase:
        pass

    monkeypatch.setattr(scan_service.ctx, 'should_ignore_fs_event', lambda: False)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', 'D:/cards')
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'request_scan', lambda **_kwargs: calls.append((('scan',), {})))

    watchdog_module = types.ModuleType('watchdog')
    observers_module = types.ModuleType('watchdog.observers')
    observers_module.Observer = _FakeObserver
    events_module = types.ModuleType('watchdog.events')
    events_module.FileSystemEventHandler = _FakeHandlerBase

    monkeypatch.setitem(sys.modules, 'watchdog', watchdog_module)
    monkeypatch.setitem(sys.modules, 'watchdog.observers', observers_module)
    monkeypatch.setitem(sys.modules, 'watchdog.events', events_module)

    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})

    scan_service.start_fs_watcher()

    event = types.SimpleNamespace(
        is_directory=False,
        event_type='moved',
        src_path='D:/tmp/book.json',
        dest_path='D:/data/lorebooks/main/book.json',
    )
    scheduled['handler'].on_any_event(event)

    assert calls == [(('upsert_worldinfo_path',), {'source_path': 'D:/data/lorebooks/main/book.json'})]


def test_worldinfo_watcher_routes_resource_lorebook_to_owner_refresh(monkeypatch):
    calls = []
    scheduled = {}

    class _FakeObserver:
        daemon = False

        def schedule(self, handler, watch_path, recursive=True):
            scheduled['handler'] = handler
            scheduled['watch_path'] = watch_path
            scheduled['recursive'] = recursive

        def start(self):
            scheduled['started'] = True

    class _FakeHandlerBase:
        pass

    monkeypatch.setattr(scan_service.ctx, 'should_ignore_fs_event', lambda: False)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', 'D:/cards')
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'request_scan', lambda **_kwargs: calls.append((('scan',), {})))

    watchdog_module = types.ModuleType('watchdog')
    observers_module = types.ModuleType('watchdog.observers')
    observers_module.Observer = _FakeObserver
    events_module = types.ModuleType('watchdog.events')
    events_module.FileSystemEventHandler = _FakeHandlerBase

    monkeypatch.setitem(sys.modules, 'watchdog', watchdog_module)
    monkeypatch.setitem(sys.modules, 'watchdog.observers', observers_module)
    monkeypatch.setitem(sys.modules, 'watchdog.events', events_module)

    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})
    monkeypatch.setattr(
        scan_service,
        'resolve_resource_worldinfo_owner_card_ids',
        lambda source_path: ['cards/alpha.png', 'cards/zeta.png'] if 'hero-assets' in source_path else [],
        raising=False,
    )

    scan_service.start_fs_watcher()

    event = types.SimpleNamespace(
        is_directory=False,
        event_type='modified',
        src_path='D:/data/resources/hero-assets/lorebooks/book.json',
        dest_path='',
    )
    scheduled['handler'].on_any_event(event)

    assert calls == [
        (('upsert_world_owner',), {'entity_id': 'cards/alpha.png', 'source_path': 'D:/data/resources/hero-assets/lorebooks/book.json'}),
        (('upsert_world_owner',), {'entity_id': 'cards/zeta.png', 'source_path': 'D:/data/resources/hero-assets/lorebooks/book.json'}),
    ]


def test_worldinfo_watcher_move_between_global_categories_refreshes_old_and_new_paths(monkeypatch):
    calls = []
    scheduled = {}

    class _FakeObserver:
        daemon = False

        def schedule(self, handler, watch_path, recursive=True):
            scheduled['handler'] = handler
            scheduled['watch_path'] = watch_path
            scheduled['recursive'] = recursive

        def start(self):
            scheduled['started'] = True

    class _FakeHandlerBase:
        pass

    monkeypatch.setattr(scan_service.ctx, 'should_ignore_fs_event', lambda: False)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', 'D:/cards')
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'request_scan', lambda **_kwargs: calls.append((('scan',), {})))

    watchdog_module = types.ModuleType('watchdog')
    observers_module = types.ModuleType('watchdog.observers')
    observers_module.Observer = _FakeObserver
    events_module = types.ModuleType('watchdog.events')
    events_module.FileSystemEventHandler = _FakeHandlerBase

    monkeypatch.setitem(sys.modules, 'watchdog', watchdog_module)
    monkeypatch.setitem(sys.modules, 'watchdog.observers', observers_module)
    monkeypatch.setitem(sys.modules, 'watchdog.events', events_module)

    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})

    scan_service.start_fs_watcher()

    event = types.SimpleNamespace(
        is_directory=False,
        event_type='moved',
        src_path='D:/data/lorebooks/旧分类/book.json',
        dest_path='D:/data/lorebooks/新分类/book.json',
    )
    scheduled['handler'].on_any_event(event)

    assert calls == [
        (('upsert_worldinfo_path',), {'source_path': 'D:/data/lorebooks/旧分类/book.json'}),
        (('upsert_worldinfo_path',), {'source_path': 'D:/data/lorebooks/新分类/book.json'}),
    ]


def test_worldinfo_watcher_move_between_resource_owners_refreshes_old_and_new_owners(monkeypatch):
    calls = []
    scheduled = {}

    class _FakeObserver:
        daemon = False

        def schedule(self, handler, watch_path, recursive=True):
            scheduled['handler'] = handler
            scheduled['watch_path'] = watch_path
            scheduled['recursive'] = recursive

        def start(self):
            scheduled['started'] = True

    class _FakeHandlerBase:
        pass

    monkeypatch.setattr(scan_service.ctx, 'should_ignore_fs_event', lambda: False)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', 'D:/cards')
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'request_scan', lambda **_kwargs: calls.append((('scan',), {})))

    watchdog_module = types.ModuleType('watchdog')
    observers_module = types.ModuleType('watchdog.observers')
    observers_module.Observer = _FakeObserver
    events_module = types.ModuleType('watchdog.events')
    events_module.FileSystemEventHandler = _FakeHandlerBase

    monkeypatch.setitem(sys.modules, 'watchdog', watchdog_module)
    monkeypatch.setitem(sys.modules, 'watchdog.observers', observers_module)
    monkeypatch.setitem(sys.modules, 'watchdog.events', events_module)

    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})
    monkeypatch.setattr(
        scan_service,
        'resolve_resource_worldinfo_owner_card_ids',
        lambda source_path: ['cards/old-owner.png'] if 'old-pack' in source_path else ['cards/new-owner.png'],
        raising=False,
    )

    scan_service.start_fs_watcher()

    event = types.SimpleNamespace(
        is_directory=False,
        event_type='moved',
        src_path='D:/data/resources/old-pack/lorebooks/book.json',
        dest_path='D:/data/resources/new-pack/lorebooks/book.json',
    )
    scheduled['handler'].on_any_event(event)

    assert calls == [
        (('upsert_world_owner',), {'entity_id': 'cards/old-owner.png', 'source_path': 'D:/data/resources/old-pack/lorebooks/book.json'}),
        (('upsert_world_owner',), {'entity_id': 'cards/new-owner.png', 'source_path': 'D:/data/resources/new-pack/lorebooks/book.json'}),
    ]


def test_card_watcher_routes_modify_to_targeted_card_task(monkeypatch):
    queued = []
    scheduled = {}

    class _FakeObserver:
        daemon = False

        def schedule(self, handler, watch_path, recursive=True):
            scheduled['handler'] = handler
            scheduled['watch_path'] = watch_path
            scheduled['recursive'] = recursive

        def start(self):
            scheduled['started'] = True

    class _FakeHandlerBase:
        pass

    monkeypatch.setattr(scan_service.ctx, 'should_ignore_fs_event', lambda: False)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', 'D:/cards')
    monkeypatch.setattr(scan_service.ctx.scan_queue, 'put', lambda task: queued.append(task))
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: queued.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'request_scan', lambda **kwargs: queued.append({'type': 'FULL_SCAN', **kwargs}))

    watchdog_module = types.ModuleType('watchdog')
    observers_module = types.ModuleType('watchdog.observers')
    observers_module.Observer = _FakeObserver
    events_module = types.ModuleType('watchdog.events')
    events_module.FileSystemEventHandler = _FakeHandlerBase

    monkeypatch.setitem(sys.modules, 'watchdog', watchdog_module)
    monkeypatch.setitem(sys.modules, 'watchdog.observers', observers_module)
    monkeypatch.setitem(sys.modules, 'watchdog.events', events_module)

    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})

    scan_service.start_fs_watcher()

    event = types.SimpleNamespace(
        is_directory=False,
        event_type='modified',
        src_path='D:/cards/hero.png',
        dest_path='',
    )
    scheduled['handler'].on_any_event(event)

    assert queued == [
        {'type': 'CARD_UPSERT', 'path': 'D:/cards/hero.png'}
    ]


def test_card_watcher_routes_move_to_targeted_card_task(monkeypatch):
    queued = []
    scheduled = {}

    class _FakeObserver:
        daemon = False

        def schedule(self, handler, watch_path, recursive=True):
            scheduled['handler'] = handler
            scheduled['watch_path'] = watch_path
            scheduled['recursive'] = recursive

        def start(self):
            scheduled['started'] = True

    class _FakeHandlerBase:
        pass

    monkeypatch.setattr(scan_service.ctx, 'should_ignore_fs_event', lambda: False)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', 'D:/cards')
    monkeypatch.setattr(scan_service.ctx.scan_queue, 'put', lambda task: queued.append(task))
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: queued.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'request_scan', lambda **kwargs: queued.append({'type': 'FULL_SCAN', **kwargs}))

    watchdog_module = types.ModuleType('watchdog')
    observers_module = types.ModuleType('watchdog.observers')
    observers_module.Observer = _FakeObserver
    events_module = types.ModuleType('watchdog.events')
    events_module.FileSystemEventHandler = _FakeHandlerBase

    monkeypatch.setitem(sys.modules, 'watchdog', watchdog_module)
    monkeypatch.setitem(sys.modules, 'watchdog.observers', observers_module)
    monkeypatch.setitem(sys.modules, 'watchdog.events', events_module)

    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})

    scan_service.start_fs_watcher()

    event = types.SimpleNamespace(
        is_directory=False,
        event_type='moved',
        src_path='D:/cards/old-name.png',
        dest_path='D:/cards/new-name.png',
    )
    scheduled['handler'].on_any_event(event)

    assert queued == [
        {'type': 'CARD_MOVE', 'src_path': 'D:/cards/old-name.png', 'dest_path': 'D:/cards/new-name.png'}
    ]


def test_card_watcher_routes_delete_to_targeted_card_task(monkeypatch):
    queued = []
    scheduled = {}

    class _FakeObserver:
        daemon = False

        def schedule(self, handler, watch_path, recursive=True):
            scheduled['handler'] = handler
            scheduled['watch_path'] = watch_path
            scheduled['recursive'] = recursive

        def start(self):
            scheduled['started'] = True

    class _FakeHandlerBase:
        pass

    monkeypatch.setattr(scan_service.ctx, 'should_ignore_fs_event', lambda: False)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', 'D:/cards')
    monkeypatch.setattr(scan_service.ctx.scan_queue, 'put', lambda task: queued.append(task))
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: queued.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'request_scan', lambda **kwargs: queued.append({'type': 'FULL_SCAN', **kwargs}))

    watchdog_module = types.ModuleType('watchdog')
    observers_module = types.ModuleType('watchdog.observers')
    observers_module.Observer = _FakeObserver
    events_module = types.ModuleType('watchdog.events')
    events_module.FileSystemEventHandler = _FakeHandlerBase

    monkeypatch.setitem(sys.modules, 'watchdog', watchdog_module)
    monkeypatch.setitem(sys.modules, 'watchdog.observers', observers_module)
    monkeypatch.setitem(sys.modules, 'watchdog.events', events_module)

    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})

    scan_service.start_fs_watcher()

    event = types.SimpleNamespace(
        is_directory=False,
        event_type='deleted',
        src_path='D:/cards/deleted.png',
        dest_path='',
    )
    scheduled['handler'].on_any_event(event)

    assert queued == [
        {'type': 'CARD_DELETE', 'path': 'D:/cards/deleted.png'}
    ]


def test_worldinfo_watcher_ignores_non_write_events(monkeypatch):
    calls = []
    scheduled = {}

    class _FakeObserver:
        daemon = False

        def schedule(self, handler, watch_path, recursive=True):
            scheduled['handler'] = handler
            scheduled['watch_path'] = watch_path
            scheduled['recursive'] = recursive

        def start(self):
            scheduled['started'] = True

    class _FakeHandlerBase:
        pass

    monkeypatch.setattr(scan_service.ctx, 'should_ignore_fs_event', lambda: False)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', 'D:/cards')
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'request_scan', lambda **_kwargs: calls.append((('scan',), {})))

    watchdog_module = types.ModuleType('watchdog')
    observers_module = types.ModuleType('watchdog.observers')
    observers_module.Observer = _FakeObserver
    events_module = types.ModuleType('watchdog.events')
    events_module.FileSystemEventHandler = _FakeHandlerBase

    monkeypatch.setitem(sys.modules, 'watchdog', watchdog_module)
    monkeypatch.setitem(sys.modules, 'watchdog.observers', observers_module)
    monkeypatch.setitem(sys.modules, 'watchdog.events', events_module)

    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})

    scan_service.start_fs_watcher()

    event = types.SimpleNamespace(
        is_directory=False,
        event_type='opened',
        src_path='D:/data/lorebooks/main/book.json',
        dest_path='',
    )
    scheduled['handler'].on_any_event(event)

    assert calls == []


def test_start_fs_watcher_skips_missing_watch_paths(monkeypatch, caplog, tmp_path):
    scheduled_paths = []
    started = []

    class _FakeObserver:
        daemon = False

        def schedule(self, _handler, watch_path, recursive=True):
            scheduled_paths.append((watch_path, recursive))
            if watch_path != str(cards_dir):
                raise FileNotFoundError(watch_path)

        def start(self):
            started.append(True)

    class _FakeHandlerBase:
        pass

    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()

    watchdog_module = types.ModuleType('watchdog')
    observers_module = types.ModuleType('watchdog.observers')
    observers_module.Observer = _FakeObserver
    events_module = types.ModuleType('watchdog.events')
    events_module.FileSystemEventHandler = _FakeHandlerBase

    monkeypatch.setitem(sys.modules, 'watchdog', watchdog_module)
    monkeypatch.setitem(sys.modules, 'watchdog.observers', observers_module)
    monkeypatch.setitem(sys.modules, 'watchdog.events', events_module)

    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(
        scan_service,
        'load_config',
        lambda: {
            'world_info_dir': str(tmp_path / 'missing-lorebooks'),
            'resources_dir': str(tmp_path / 'missing-resources'),
        },
    )

    with caplog.at_level(logging.WARNING):
        scan_service.start_fs_watcher()

    assert scheduled_paths == [
        (str(cards_dir), True),
        (str(tmp_path / 'missing-lorebooks'), True),
        (str(tmp_path / 'missing-resources'), True),
    ]
    assert started == [True]
    assert 'does not exist yet' in caplog.text


def test_update_card_cache_returns_false_when_cache_write_fails(monkeypatch):
    monkeypatch.setattr(cache_service, 'get_db', lambda: (_ for _ in ()).throw(RuntimeError('db down')))

    result = cache_service.update_card_cache('cards/hero.png', 'D:/cards/hero.png', mtime=123.0)

    assert result == {
        'cache_updated': False,
        'has_embedded_wi': False,
        'previous_has_embedded_wi': False,
    }
    assert bool(result) is False


def test_change_image_skips_file_driven_card_job_when_cache_write_fails(monkeypatch, tmp_path):
    from core.api.v1 import cards as cards_api

    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    card_path = cards_dir / 'hero.json'
    card_path.write_text(json.dumps({'data': {'name': 'Hero', 'tags': []}}, ensure_ascii=False), encoding='utf-8')

    db_path = tmp_path / 'cards_metadata.db'
    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE card_metadata (id TEXT PRIMARY KEY)')
        conn.execute('INSERT INTO card_metadata (id) VALUES (?)', ('hero.json',))
        conn.commit()

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': []}})
    monkeypatch.setattr(cards_api, 'resize_image_if_needed', lambda image: image)
    monkeypatch.setattr(cards_api, 'write_card_metadata', lambda *_args, **_kwargs: True)
    monkeypatch.setattr(cards_api, 'clean_sidecar_images', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'clean_thumbnail_cache', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cards_api,
        'update_card_cache',
        lambda *_args, **_kwargs: {
            'cache_updated': False,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
        },
    )
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload: None)
    monkeypatch.setattr(cards_api, 'ensure_import_time', lambda *_args, **_kwargs: (False, 0))
    monkeypatch.setattr(cards_api, 'calculate_token_count', lambda _data: 0)

    enqueue_calls = []
    monkeypatch.setattr(
        card_index_sync_service,
        'enqueue_index_job',
        lambda *args, **kwargs: enqueue_calls.append((args, kwargs)),
    )

    class _FakeCache:
        initialized = True
        category_counts = {}

        def __init__(self):
            self.id_map = {}
            self.cards = []
            self.bundle_map = {}

        def delete_card_update(self, card_id):
            assert card_id == 'hero.json'

        def add_card_update(self, payload):
            self.id_map[payload['id']] = payload
            return payload

        def update_card_data(self, _card_id, payload):
            return payload

    monkeypatch.setattr(cards_api.ctx, 'cache', _FakeCache())

    def _make_app():
        app = Flask(__name__)
        app.register_blueprint(cards_api.bp)
        return app

    image_bytes = BytesIO()
    from PIL import Image
    Image.new('RGBA', (1, 1), (255, 0, 0, 255)).save(image_bytes, format='PNG')
    image_bytes.seek(0)

    client = _make_app().test_client()
    res = client.post(
        '/api/change_image',
        data={'id': 'hero.json', 'image': (image_bytes, 'cover.png')},
        content_type='multipart/form-data',
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['new_id'] == 'hero.png'
    assert enqueue_calls == [
        (
            ('upsert_card',),
            {
                'entity_id': 'hero.png',
                'source_path': str(cards_dir / 'hero.png'),
                'payload': {'remove_entity_ids': ['hero.json']},
            },
        ),
        (
            ('upsert_world_owner',),
            {
                'entity_id': 'hero.png',
                'source_path': str(cards_dir / 'hero.png'),
                'payload': {'remove_owner_ids': ['hero.json']},
            },
        ),
    ]


def test_background_scanner_enqueues_targeted_card_reconcile_when_changes_detected(monkeypatch):
    calls = []

    class _FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, *_args, **_kwargs):
            return None

        def cursor(self):
            return self

        def fetchall(self):
            return [('gone.png', 10.0, 100, 0, 'hash', 0)]

        def commit(self):
            return None

    monkeypatch.setattr(scan_service.sqlite3, 'connect', lambda *_args, **_kwargs: _FakeConn())
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', 'D:/cards')
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'schedule_reload', lambda **_kwargs: None)
    monkeypatch.setattr(scan_service.os, 'walk', lambda _root: iter([('D:/cards', [], [])]))

    scan_service._perform_scan_logic()

    assert calls == [
        (('upsert_card',), {'entity_id': 'gone.png', 'source_path': 'D:\\cards\\gone.png'}),
        (('upsert_world_owner',), {'entity_id': 'gone.png', 'source_path': 'D:\\cards\\gone.png', 'payload': {'remove_owner_ids': ['gone.png']}}),
    ]


def test_process_card_upsert_task_updates_metadata_and_enqueues_targeted_jobs(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    card_path = cards_dir / 'nested' / 'hero.png'
    card_path.parent.mkdir(parents=True)
    card_path.write_bytes(b'hero')

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            CREATE TABLE card_metadata (
                id TEXT PRIMARY KEY,
                char_name TEXT,
                description TEXT,
                first_mes TEXT,
                mes_example TEXT,
                tags TEXT,
                category TEXT,
                creator TEXT,
                char_version TEXT,
                last_modified REAL,
                file_hash TEXT,
                file_size INTEGER,
                token_count INTEGER DEFAULT 0,
                has_character_book INTEGER DEFAULT 0,
                character_book_name TEXT DEFAULT '',
                is_favorite INTEGER DEFAULT 0
            )
            '''
        )
        conn.commit()

    calls = []
    reloads = []

    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(scan_service, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': ['blue'], 'description': 'desc'}})
    monkeypatch.setattr(scan_service, 'calculate_token_count', lambda _payload: 111)
    monkeypatch.setattr(scan_service, 'get_wi_meta', lambda _payload: (False, ''))
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'schedule_reload', lambda **kwargs: reloads.append(kwargs))

    assert scan_service._process_card_upsert_task(str(card_path)) is True

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT id, char_name, category, token_count FROM card_metadata ORDER BY id'
        ).fetchone()

    assert row == ('nested/hero.png', 'Hero', 'nested', 111)
    assert calls == [
        (('upsert_card',), {'entity_id': 'nested/hero.png', 'source_path': str(card_path)}),
        (('upsert_world_owner',), {'entity_id': 'nested/hero.png', 'source_path': str(card_path)}),
    ]
    assert reloads == [{'reason': 'watchdog_card_upsert'}]


def test_process_card_move_task_replaces_old_metadata_and_enqueues_targeted_cleanup(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'
    new_card_path = cards_dir / 'renamed' / 'new-name.png'
    new_card_path.parent.mkdir(parents=True)
    new_card_path.write_bytes(b'new')

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            CREATE TABLE card_metadata (
                id TEXT PRIMARY KEY,
                char_name TEXT,
                description TEXT,
                first_mes TEXT,
                mes_example TEXT,
                tags TEXT,
                category TEXT,
                creator TEXT,
                char_version TEXT,
                last_modified REAL,
                file_hash TEXT,
                file_size INTEGER,
                token_count INTEGER DEFAULT 0,
                has_character_book INTEGER DEFAULT 0,
                character_book_name TEXT DEFAULT '',
                is_favorite INTEGER DEFAULT 0
            )
            '''
        )
        conn.execute(
            'INSERT INTO card_metadata (id, char_name, category, last_modified, file_hash, file_size, token_count, has_character_book, character_book_name, is_favorite) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('old-name.png', 'Old Hero', 'legacy', 10.0, '', 3, 7, 0, '', 1),
        )
        conn.commit()

    calls = []
    reloads = []

    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(scan_service, 'extract_card_info', lambda _path: {'data': {'name': 'New Hero', 'tags': ['green']}})
    monkeypatch.setattr(scan_service, 'calculate_token_count', lambda _payload: 222)
    monkeypatch.setattr(scan_service, 'get_wi_meta', lambda _payload: (False, ''))
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'schedule_reload', lambda **kwargs: reloads.append(kwargs))

    assert scan_service._process_card_move_task('old-name.png', str(new_card_path)) is True

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute('SELECT id, char_name, category, token_count FROM card_metadata ORDER BY id').fetchall()

    assert rows == [('renamed/new-name.png', 'New Hero', 'renamed', 222)]
    assert calls == [
        (
            ('upsert_card',),
            {
                'entity_id': 'renamed/new-name.png',
                'source_path': str(new_card_path),
                'payload': {'remove_entity_ids': ['old-name.png']},
            },
        ),
        (
            ('upsert_world_owner',),
            {
                'entity_id': 'renamed/new-name.png',
                'source_path': str(new_card_path),
                'payload': {'remove_owner_ids': ['old-name.png']},
            },
        ),
    ]
    assert reloads == [{'reason': 'watchdog_card_move'}]


def test_process_card_delete_task_removes_metadata_and_enqueues_targeted_cleanup(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    cards_dir = tmp_path / 'cards'

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            '''
            CREATE TABLE card_metadata (
                id TEXT PRIMARY KEY,
                char_name TEXT,
                description TEXT,
                first_mes TEXT,
                mes_example TEXT,
                tags TEXT,
                category TEXT,
                creator TEXT,
                char_version TEXT,
                last_modified REAL,
                file_hash TEXT,
                file_size INTEGER,
                token_count INTEGER DEFAULT 0,
                has_character_book INTEGER DEFAULT 0,
                character_book_name TEXT DEFAULT '',
                is_favorite INTEGER DEFAULT 0
            )
            '''
        )
        conn.execute(
            'INSERT INTO card_metadata (id, char_name, category, last_modified, file_hash, file_size, token_count, has_character_book, character_book_name, is_favorite) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ('nested/deleted.png', 'Deleted Hero', 'nested', 10.0, '', 3, 7, 0, '', 0),
        )
        conn.commit()

    calls = []
    reloads = []

    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(scan_service, 'enqueue_index_job', lambda *args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr(scan_service, 'schedule_reload', lambda **kwargs: reloads.append(kwargs))

    assert scan_service._process_card_delete_task(str(cards_dir / 'nested' / 'deleted.png')) is True

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute('SELECT id FROM card_metadata ORDER BY id').fetchall()

    assert rows == []
    assert calls == [
        (
            ('upsert_card',),
            {
                'entity_id': 'nested/deleted.png',
                'source_path': str(cards_dir / 'nested' / 'deleted.png'),
                'payload': {'remove_entity_ids': ['nested/deleted.png']},
            },
        ),
        (
            ('upsert_world_owner',),
            {
                'entity_id': 'nested/deleted.png',
                'source_path': str(cards_dir / 'nested' / 'deleted.png'),
                'payload': {'remove_owner_ids': ['nested/deleted.png']},
            },
        ),
    ]
    assert reloads == [{'reason': 'watchdog_card_delete'}]


def test_process_card_delete_task_enqueues_entity_and_owner_cleanup(monkeypatch, tmp_path):
    calls = []
    reloads = []
    card_path = tmp_path / 'cards' / 'nested' / 'hero.png'
    db_path = tmp_path / 'cards_metadata.db'

    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_bytes(b'card')

    with sqlite3.connect(db_path) as conn:
        conn.execute('CREATE TABLE card_metadata (id TEXT PRIMARY KEY)')
        conn.execute('INSERT INTO card_metadata (id) VALUES (?)', ('nested/hero.png',))
        conn.commit()

    monkeypatch.setattr(scan_service, '_resolve_card_rel_path', lambda _path: 'nested/hero.png')
    monkeypatch.setattr(scan_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(
        scan_service,
        '_enqueue_card_reconcile_jobs',
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setattr(scan_service, 'schedule_reload', lambda **kwargs: reloads.append(kwargs))

    assert scan_service._process_card_delete_task(str(card_path)) is True
    assert calls == [
        (
            ('nested/hero.png', str(card_path)),
            {
                'remove_entity_ids': ['nested/hero.png'],
                'remove_owner_ids': ['nested/hero.png'],
            },
        )
    ]
    assert reloads == [{'reason': 'watchdog_card_delete'}]


def test_process_scan_task_falls_back_to_full_scan_when_card_task_fails(monkeypatch):
    queued = []

    monkeypatch.setattr(scan_service, '_process_card_upsert_task', lambda _path: False)
    monkeypatch.setattr(scan_service.ctx.scan_queue, 'put', lambda task: queued.append(task))

    assert scan_service._process_scan_task({'type': 'CARD_UPSERT', 'path': 'D:/cards/missing.png'}) is False

    assert queued == [
        {'type': 'FULL_SCAN', 'reason': 'card_upsert_failed'}
    ]


def test_enqueue_index_job_persists_pending_row(monkeypatch, tmp_path):
    import sqlite3

    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        from core.data.index_runtime_store import ensure_index_runtime_schema

        ensure_index_runtime_schema(conn)

    monkeypatch.setattr(index_job_worker, 'DEFAULT_DB_PATH', str(db_path))

    index_job_worker.enqueue_index_job('rebuild_scope', payload={'scope': 'worldinfo'})

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            'SELECT job_type, status, payload_json FROM index_jobs ORDER BY id DESC LIMIT 1'
        ).fetchone()

    assert row[0] == 'rebuild_scope'
    assert row[1] == 'pending'
    assert 'worldinfo' in row[2]


def test_update_card_cache_returns_persistence_facts_after_successful_commit(monkeypatch):
    calls = []

    class _FakeConn:
        def cursor(self):
            return self

        def execute(self, *_args, **_kwargs):
            return self

        def fetchone(self):
            return {'is_favorite': 0, 'has_character_book': 0}

        def commit(self):
            calls.append('commit')
            return None

    monkeypatch.setattr(cache_service, 'get_db', lambda: _FakeConn())
    monkeypatch.setattr(cache_service, 'get_file_hash_and_size', lambda _path: ('h', 12))
    monkeypatch.setattr(cache_service, 'extract_card_info', lambda _path: {'data': {'name': 'Hero', 'tags': [], 'character_book': {'name': 'Book', 'entries': {}}}})
    monkeypatch.setattr(cache_service, 'calculate_token_count', lambda _payload: 111)
    monkeypatch.setattr(cache_service, 'get_wi_meta', lambda _payload: (True, 'Book'))

    result = cache_service.update_card_cache('cards/hero.png', 'D:/cards/hero.png', mtime=123.0)

    assert result == {
        'cache_updated': True,
        'has_embedded_wi': True,
        'previous_has_embedded_wi': False,
    }
    assert bool(result) is True
    assert calls == ['commit']


def test_worldinfo_watch_filter_returns_false_for_cross_drive_path(monkeypatch):
    monkeypatch.setattr(scan_service, 'load_config', lambda: {'world_info_dir': 'D:/data/lorebooks', 'resources_dir': 'D:/data/resources'})

    assert scan_service._is_worldinfo_watch_path('E:/other/book.json') is False


def test_start_fs_watcher_schedules_cards_and_distinct_worldinfo_roots(monkeypatch):
    scheduled = []

    class _FakeObserver:
        daemon = False

        def schedule(self, handler, watch_path, recursive=True):
            scheduled.append((handler, watch_path, recursive))

        def start(self):
            return None

    class _FakeHandlerBase:
        pass

    watchdog_module = types.ModuleType('watchdog')
    observers_module = types.ModuleType('watchdog.observers')
    observers_module.Observer = _FakeObserver
    events_module = types.ModuleType('watchdog.events')
    events_module.FileSystemEventHandler = _FakeHandlerBase

    monkeypatch.setitem(sys.modules, 'watchdog', watchdog_module)
    monkeypatch.setitem(sys.modules, 'watchdog.observers', observers_module)
    monkeypatch.setitem(sys.modules, 'watchdog.events', events_module)
    monkeypatch.setattr(scan_service, 'CARDS_FOLDER', 'D:/cards')
    monkeypatch.setattr(scan_service, 'load_config', lambda: {
        'world_info_dir': 'D:/data/lorebooks',
        'resources_dir': 'D:/data/resources',
    })

    scan_service.start_fs_watcher()

    assert [item[1] for item in scheduled] == ['D:/cards', 'D:/data/lorebooks', 'D:/data/resources']
    assert all(item[2] is True for item in scheduled)


def test_classify_worldinfo_path_resolves_relative_dirs_from_base_dir(monkeypatch, tmp_path):
    base_dir = tmp_path / 'runtime'
    global_file = base_dir / 'data' / 'library' / 'lorebooks' / 'main' / 'book.json'
    resource_file = base_dir / 'data' / 'assets' / 'card_assets' / 'hero-assets' / 'lorebooks' / 'book.json'
    global_file.parent.mkdir(parents=True)
    resource_file.parent.mkdir(parents=True)
    global_file.write_text('{}', encoding='utf-8')
    resource_file.write_text('{}', encoding='utf-8')

    monkeypatch.setattr(index_build_service, 'BASE_DIR', str(base_dir))
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {
        'world_info_dir': 'data/library/lorebooks',
        'resources_dir': 'data/assets/card_assets',
    })

    assert index_build_service.classify_worldinfo_path(str(global_file)) == {
        'kind': 'global',
        'source_path': str(global_file).replace('\\', '/'),
    }
    assert index_build_service.classify_worldinfo_path(str(resource_file)) == {
        'kind': 'resource',
        'source_path': str(resource_file).replace('\\', '/'),
    }


def test_resolve_resource_worldinfo_owner_card_ids_supports_relative_resources_dir(monkeypatch, tmp_path):
    base_dir = tmp_path / 'runtime'
    resource_file = base_dir / 'data' / 'assets' / 'card_assets' / 'shared-pack' / 'lorebooks' / 'book.json'
    resource_file.parent.mkdir(parents=True)
    resource_file.write_text('{}', encoding='utf-8')

    monkeypatch.setattr(index_build_service, 'BASE_DIR', str(base_dir))
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {
        'world_info_dir': 'data/library/lorebooks',
        'resources_dir': 'data/assets/card_assets',
    })
    monkeypatch.setattr(
        index_build_service,
        'load_ui_data',
        lambda: {
            'cards/zeta.png': {'resource_folder': 'shared-pack'},
            'cards/alpha.png': {'resource_folder': 'shared-pack'},
            'cards/other.png': {'resource_folder': 'other-pack'},
        },
    )

    assert index_build_service.resolve_resource_worldinfo_owner_card_ids(str(resource_file)) == [
        'cards/alpha.png',
        'cards/zeta.png',
    ]


def test_apply_worldinfo_path_increment_uses_resolved_relative_global_dir(monkeypatch, tmp_path):
    from core.data.index_runtime_store import ensure_index_runtime_schema

    base_dir = tmp_path / 'runtime'
    global_file = base_dir / 'data' / 'library' / 'lorebooks' / 'main' / 'book.json'
    global_file.parent.mkdir(parents=True)
    global_file.write_text(json.dumps({'name': 'Global Book', 'entries': {}}), encoding='utf-8')

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    ensure_index_runtime_schema(conn)
    conn.execute('UPDATE index_build_state SET active_generation = 1 WHERE scope = ?', ('worldinfo',))
    conn.commit()

    monkeypatch.setattr(index_build_service, 'BASE_DIR', str(base_dir))
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {
        'world_info_dir': 'data/library/lorebooks',
        'resources_dir': 'data/assets/card_assets',
    })
    monkeypatch.setattr(index_build_service, 'load_ui_data', lambda: {})

    assert index_build_service.apply_worldinfo_path_increment(conn, str(global_file)) is True

    row = conn.execute(
        'SELECT entity_type, entity_id, source_path, display_category, name FROM index_entities_v2 WHERE generation = 1'
    ).fetchone()

    assert row['entity_type'] == 'world_global'
    assert row['entity_id'] == 'world::global::main/book.json'
    assert row['source_path'] == str(global_file)
    assert row['display_category'] == 'main'
    assert row['name'] == 'Global Book'


def test_build_worldinfo_generation_uses_resolved_relative_dirs(monkeypatch, tmp_path):
    from core.data.index_runtime_store import ensure_index_runtime_schema

    base_dir = tmp_path / 'runtime'
    global_file = base_dir / 'data' / 'library' / 'lorebooks' / 'main' / 'global-book.json'
    resource_file = base_dir / 'data' / 'assets' / 'card_assets' / 'shared-pack' / 'lorebooks' / 'resource-book.json'
    global_file.parent.mkdir(parents=True)
    resource_file.parent.mkdir(parents=True)
    global_file.write_text(json.dumps({'name': 'Global Book', 'entries': {}}), encoding='utf-8')
    resource_file.write_text(json.dumps({'name': 'Resource Book', 'entries': {}}), encoding='utf-8')

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    ensure_index_runtime_schema(conn)
    conn.execute(
        '''
        CREATE TABLE card_metadata (
            id TEXT PRIMARY KEY,
            char_name TEXT,
            category TEXT,
            character_book_name TEXT DEFAULT '',
            last_modified REAL,
            has_character_book INTEGER DEFAULT 0
        )
        '''
    )
    conn.execute(
        'INSERT INTO card_metadata(id, char_name, category, character_book_name, last_modified, has_character_book) VALUES (?, ?, ?, ?, ?, ?)',
        ('cards/hero.png', 'Hero', 'companions', '', 123.0, 0),
    )
    conn.commit()

    monkeypatch.setattr(index_build_service, 'BASE_DIR', str(base_dir))
    monkeypatch.setattr(index_build_service, 'CARDS_FOLDER', str(base_dir / 'cards'))
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {
        'world_info_dir': 'data/library/lorebooks',
        'resources_dir': 'data/assets/card_assets',
    })
    monkeypatch.setattr(
        index_build_service,
        'load_ui_data',
        lambda: {'cards/hero.png': {'resource_folder': 'shared-pack'}},
    )
    monkeypatch.setattr(index_build_service, 'extract_card_info', lambda _path: {})

    items_written = index_build_service.build_worldinfo_generation(conn, 7)

    rows = conn.execute(
        'SELECT entity_type, entity_id, source_path, name FROM index_entities_v2 WHERE generation = 7 ORDER BY entity_id'
    ).fetchall()

    assert items_written == 2
    assert [dict(row) for row in rows] == [
        {
            'entity_type': 'world_global',
            'entity_id': 'world::global::main/global-book.json',
            'source_path': str(global_file),
            'name': 'Global Book',
        },
        {
            'entity_type': 'world_resource',
            'entity_id': 'world::resource::cards/hero.png::resource-book.json',
            'source_path': str(resource_file),
            'name': 'Resource Book',
        },
    ]


def test_apply_worldinfo_owner_increment_uses_resolved_relative_runtime_dirs(monkeypatch, tmp_path):
    from core.data.index_runtime_store import ensure_index_runtime_schema

    base_dir = tmp_path / 'runtime'
    global_file = base_dir / 'data' / 'library' / 'lorebooks' / 'global' / 'book.json'
    resource_file = base_dir / 'data' / 'assets' / 'card_assets' / 'shared-pack' / 'lorebooks' / 'resource-book.json'
    global_file.parent.mkdir(parents=True)
    resource_file.parent.mkdir(parents=True)
    global_file.write_text(json.dumps({'name': 'Global Book', 'entries': {}}), encoding='utf-8')
    resource_file.write_text(json.dumps({'name': 'Resource Book', 'entries': {}}), encoding='utf-8')

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    ensure_index_runtime_schema(conn)
    conn.execute('UPDATE index_build_state SET active_generation = 1 WHERE scope = ?', ('worldinfo',))
    conn.execute(
        '''
        CREATE TABLE card_metadata (
            id TEXT PRIMARY KEY,
            char_name TEXT,
            category TEXT,
            character_book_name TEXT DEFAULT '',
            last_modified REAL,
            has_character_book INTEGER DEFAULT 0
        )
        '''
    )
    conn.execute(
        'INSERT INTO card_metadata(id, char_name, category, character_book_name, last_modified, has_character_book) VALUES (?, ?, ?, ?, ?, ?)',
        ('cards/hero.png', 'Hero', 'companions', 'Embedded Book', 123.0, 1),
    )
    conn.commit()

    monkeypatch.setattr(index_build_service, 'BASE_DIR', str(base_dir))
    monkeypatch.setattr(index_build_service, 'CARDS_FOLDER', str(base_dir / 'cards'))
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {
        'world_info_dir': 'data/library/lorebooks',
        'resources_dir': 'data/assets/card_assets',
    })
    monkeypatch.setattr(
        index_build_service,
        'load_ui_data',
        lambda: {
            'cards/hero.png': {'resource_folder': 'shared-pack'},
            '_resource_item_categories_v1': {
                'worldinfo': {
                    str(resource_file).replace('\\', '/').lower(): {'category': 'override-cat'}
                }
            },
        },
    )
    monkeypatch.setattr(
        index_build_service,
        'extract_card_info',
        lambda _path: {'data': {'character_book': {'name': 'Embedded Book'}}},
    )

    assert index_build_service.apply_worldinfo_owner_increment(conn, 'cards/hero.png') is True

    rows = conn.execute(
        'SELECT entity_type, entity_id, source_path, display_category, category_mode, name FROM index_entities_v2 WHERE generation = 1 ORDER BY entity_id'
    ).fetchall()
    stats = conn.execute(
        'SELECT entity_type, category_path, direct_count, subtree_count FROM index_category_stats_v2 WHERE generation = 1 AND scope = ? ORDER BY entity_type, category_path',
        ('worldinfo',),
    ).fetchall()

    assert [dict(row) for row in rows] == [
        {
            'entity_type': 'world_embedded',
            'entity_id': 'world::embedded::cards/hero.png',
            'source_path': str(base_dir / 'cards' / 'cards' / 'hero.png'),
            'display_category': 'companions',
            'category_mode': 'inherited',
            'name': 'Embedded Book',
        },
        {
            'entity_type': 'world_resource',
            'entity_id': 'world::resource::cards/hero.png::resource-book.json',
            'source_path': str(resource_file),
            'display_category': 'override-cat',
            'category_mode': 'override',
            'name': 'Resource Book',
        },
    ]
    assert ('world_global', 'global', 0, 0) in [tuple(row) for row in stats]


def test_apply_worldinfo_embedded_increment_uses_resolved_relative_global_dir(monkeypatch, tmp_path):
    from core.data.index_runtime_store import ensure_index_runtime_schema

    base_dir = tmp_path / 'runtime'
    global_file = base_dir / 'data' / 'library' / 'lorebooks' / 'global' / 'book.json'
    global_file.parent.mkdir(parents=True)
    global_file.write_text(json.dumps({'name': 'Global Book', 'entries': {}}), encoding='utf-8')

    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    ensure_index_runtime_schema(conn)
    conn.execute('UPDATE index_build_state SET active_generation = 1 WHERE scope = ?', ('worldinfo',))
    conn.execute(
        '''
        CREATE TABLE card_metadata (
            id TEXT PRIMARY KEY,
            char_name TEXT,
            category TEXT,
            character_book_name TEXT DEFAULT '',
            last_modified REAL,
            has_character_book INTEGER DEFAULT 0
        )
        '''
    )
    conn.execute(
        'INSERT INTO card_metadata(id, char_name, category, character_book_name, last_modified, has_character_book) VALUES (?, ?, ?, ?, ?, ?)',
        ('cards/hero.png', 'Hero', 'companions', 'Embedded Book', 123.0, 1),
    )
    conn.commit()

    monkeypatch.setattr(index_build_service, 'BASE_DIR', str(base_dir))
    monkeypatch.setattr(index_build_service, 'CARDS_FOLDER', str(base_dir / 'cards'))
    monkeypatch.setattr(index_build_service, 'load_config', lambda: {
        'world_info_dir': 'data/library/lorebooks',
        'resources_dir': 'data/assets/card_assets',
    })
    monkeypatch.setattr(index_build_service, 'load_ui_data', lambda: {})
    monkeypatch.setattr(
        index_build_service,
        'extract_card_info',
        lambda _path: {'data': {'character_book': {'name': 'Embedded Book'}}},
    )

    assert index_build_service.apply_worldinfo_embedded_increment(conn, 'cards/hero.png') is True

    row = conn.execute(
        'SELECT entity_type, entity_id, source_path, display_category, name FROM index_entities_v2 WHERE generation = 1'
    ).fetchone()
    stats = conn.execute(
        'SELECT entity_type, category_path, direct_count, subtree_count FROM index_category_stats_v2 WHERE generation = 1 AND scope = ? ORDER BY entity_type, category_path',
        ('worldinfo',),
    ).fetchall()

    assert dict(row) == {
        'entity_type': 'world_embedded',
        'entity_id': 'world::embedded::cards/hero.png',
        'source_path': str(base_dir / 'cards' / 'cards' / 'hero.png'),
        'display_category': 'companions',
        'name': 'Embedded Book',
    }
    assert ('world_global', 'global', 0, 0) in [tuple(stat) for stat in stats]
