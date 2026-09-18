import json
import sys
from pathlib import Path
from types import SimpleNamespace

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import cards as cards_api


def _make_app():
    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)
    return app


def test_sync_folder_prefix_after_fs_move_updates_db_ui_cache_and_index(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    moved_file = cards_root / 'dst' / 'pack' / 'sub' / 'hero.json'
    moved_file.parent.mkdir(parents=True, exist_ok=True)
    moved_file.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    saved_ui_payloads = []
    update_calls = []
    sync_calls = []
    events = []

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self._rows = []
            self.commit_calls = 0

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            normalized_sql = ' '.join(str(sql).split())
            if normalized_sql.startswith("SELECT id FROM card_metadata WHERE id LIKE ? || '/%' ESCAPE '\\'"):
                self._rows = [('src/pack/sub/hero.json',)]
            return self

        def fetchall(self):
            return list(self._rows)

        def commit(self):
            self.commit_calls += 1
            events.append('commit')
            return None

    class _FakeCache:
        def __init__(self):
            self.id_map = {
                'src/pack/sub/hero.json': {
                    'id': 'src/pack/sub/hero.json',
                    'category': 'src/pack/sub',
                    'is_bundle': False,
                    'last_modified': 1,
                }
            }
            self.bundle_map = {}
            self.visible_folders = []

        def move_folder_update(self, old_path_prefix, new_path_prefix):
            moved_items = []
            for card_id in list(self.id_map.keys()):
                if not card_id.startswith(old_path_prefix + '/'):
                    continue
                moved_items.append((card_id, self.id_map.pop(card_id)))

            for old_id, card in moved_items:
                suffix = old_id[len(old_path_prefix):]
                new_id = new_path_prefix + suffix
                old_category = card.get('category', '')
                if old_category == old_path_prefix:
                    new_category = new_path_prefix
                elif old_category.startswith(old_path_prefix + '/'):
                    new_category = new_path_prefix + old_category[len(old_path_prefix):]
                else:
                    new_category = new_id.rsplit('/', 1)[0] if '/' in new_id else ''

                card = dict(card)
                card['id'] = new_id
                card['category'] = new_category
                self.id_map[new_id] = card

    fake_conn = _FakeConn()
    fake_cache = _FakeCache()
    ui_data = {
        'src/pack': {'summary': 'folder note'},
        'src/pack/sub/hero.json': {
            'summary': 'nested note',
            card_service.VERSION_REMARKS_KEY: {
                'src/pack/sub/hero.json': {'label': 'old remark'},
            },
        },
        '_worldinfo_notes_v1': {
            'embedded::src/pack/sub/hero.json': {'summary': 'embedded note'},
            'resource::book.json': {'summary': 'keep resource note'},
            'global::lorebook.json': {'summary': 'keep global note', 'updated_at': 99},
        },
    }

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'save_ui_data',
        lambda payload, **_kwargs: ((
            events.append('save_ui_data'),
            saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
        ), None)[1],
    )
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda card_id, full_path, **kwargs: ((
            events.append('update_card_cache'),
            update_calls.append({'card_id': card_id, 'full_path': full_path, 'kwargs': kwargs}),
            {
                'cache_updated': True,
                'has_embedded_wi': False,
                'previous_has_embedded_wi': False,
            },
        ))[2],
    )
    monkeypatch.setattr(
        card_service,
        'sync_card_index_jobs',
        lambda **kwargs: ((events.append('sync_card_index_jobs'), sync_calls.append(kwargs)), {})[1],
    )
    monkeypatch.setattr(card_service.ctx, 'cache', fake_cache, raising=False)

    card_service.sync_folder_prefix_after_fs_move(
        conn=fake_conn,
        ui_data=ui_data,
        old_path='src/pack',
        new_path='dst/pack',
    )

    assert saved_ui_payloads[-1] == {
        'dst/pack': {'summary': 'folder note'},
        'dst/pack/sub/hero.json': {
            'summary': 'nested note',
            card_service.VERSION_REMARKS_KEY: {
                'dst/pack/sub/hero.json': {'label': 'old remark'},
            },
        },
        '_worldinfo_notes_v1': {
            'embedded::dst/pack/sub/hero.json': {'summary': 'embedded note'},
            'resource::book.json': {'summary': 'keep resource note'},
            'global::lorebook.json': {'summary': 'keep global note', 'updated_at': 99},
        },
    }
    assert fake_conn.executed == [
        ("SELECT id FROM card_metadata WHERE id LIKE ? || '/%' ESCAPE '\\'", ('src/pack',)),
        (
            """
            UPDATE card_metadata 
            SET id = ?, category = REPLACE(category, ?, ?) 
            WHERE id = ?
        """,
            ('dst/pack/sub/hero.json', 'src/pack', 'dst/pack', 'src/pack/sub/hero.json'),
        ),
    ]
    assert fake_conn.commit_calls == 1
    assert events == ['commit', 'save_ui_data', 'update_card_cache', 'sync_card_index_jobs']
    assert update_calls == [
        {
            'card_id': 'dst/pack/sub/hero.json',
            'full_path': str(cards_root / 'dst' / 'pack' / 'sub' / 'hero.json'),
            'kwargs': {'remove_entity_ids': ['src/pack/sub/hero.json']},
        }
    ]
    assert sync_calls == [
        {
            'card_id': 'dst/pack/sub/hero.json',
            'source_path': str(cards_root / 'dst' / 'pack' / 'sub' / 'hero.json'),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['src/pack/sub/hero.json'],
            'remove_owner_ids': ['src/pack/sub/hero.json'],
        }
    ]
    assert fake_cache.id_map == {
        'dst/pack/sub/hero.json': {
            'id': 'dst/pack/sub/hero.json',
            'category': 'dst/pack/sub',
            'is_bundle': False,
            'last_modified': 1,
        }
    }


def test_sync_exact_card_after_fs_move_updates_db_ui_cache_and_index(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    moved_file = cards_root / 'dst' / 'hero.json'
    moved_file.parent.mkdir(parents=True, exist_ok=True)
    moved_file.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    saved_ui_payloads = []
    update_calls = []
    sync_calls = []
    move_card_calls = []
    events = []

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self.commit_calls = 0

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            return self

        def commit(self):
            self.commit_calls += 1
            events.append('commit')
            return None

    fake_conn = _FakeConn()
    ui_data = {
        'src/hero.json': {
            'summary': 'card note',
            card_service.VERSION_REMARKS_KEY: {
                'src/hero.json': {'summary': 'version note'},
            },
        },
        '_worldinfo_notes_v1': {
            'embedded::src/hero.json': {'summary': 'embedded note'},
            'embedded::src/other.json': {'summary': 'keep other note'},
            'resource::book.json': {'summary': 'keep resource note'},
        },
    }

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'save_ui_data',
        lambda payload, **_kwargs: ((
            events.append('save_ui_data'),
            saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
        ), None)[1],
    )
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda card_id, full_path, **kwargs: ((
            events.append('update_card_cache'),
            update_calls.append({'card_id': card_id, 'full_path': full_path, 'kwargs': kwargs}),
            {
                'cache_updated': True,
                'has_embedded_wi': False,
                'previous_has_embedded_wi': False,
            },
        ))[2],
    )
    monkeypatch.setattr(
        card_service,
        'sync_card_index_jobs',
        lambda **kwargs: ((events.append('sync_card_index_jobs'), sync_calls.append(kwargs)), {})[1],
    )
    monkeypatch.setattr(
        card_service.ctx,
        'cache',
        SimpleNamespace(
            move_card_update=lambda *args: (events.append('move_card_update'), move_card_calls.append(args))[-1],
        ),
        raising=False,
    )

    card_service.sync_exact_card_after_fs_move(
        conn=fake_conn,
        ui_data=ui_data,
        old_card_id='src/hero.json',
        new_card_id='dst/hero.json',
        dst_full_path=str(moved_file),
        final_name='hero.json',
        old_category='src',
    )

    assert fake_conn.executed == [
        ('UPDATE card_metadata SET id = ?, category = ? WHERE id = ?', ('dst/hero.json', 'dst', 'src/hero.json')),
    ]
    assert fake_conn.commit_calls == 1
    assert saved_ui_payloads[-1] == {
        'dst/hero.json': {
            'summary': 'card note',
            card_service.VERSION_REMARKS_KEY: {
                'dst/hero.json': {'summary': 'version note'},
            },
        },
        '_worldinfo_notes_v1': {
            'embedded::dst/hero.json': {'summary': 'embedded note'},
            'embedded::src/other.json': {'summary': 'keep other note'},
            'resource::book.json': {'summary': 'keep resource note'},
        },
    }
    assert events == ['save_ui_data', 'commit', 'move_card_update', 'update_card_cache', 'sync_card_index_jobs']
    assert move_card_calls == [
        ('src/hero.json', 'dst/hero.json', 'src', 'dst', 'hero.json', str(moved_file)),
    ]
    assert update_calls == [
        {
            'card_id': 'dst/hero.json',
            'full_path': str(moved_file),
            'kwargs': {'remove_entity_ids': ['src/hero.json']},
        }
    ]
    assert sync_calls == [
        {
            'card_id': 'dst/hero.json',
            'source_path': str(moved_file),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['src/hero.json'],
            'remove_owner_ids': ['src/hero.json'],
        }
    ]


def test_sync_exact_card_after_fs_move_updates_db_ui_cache_and_index_for_png_rename(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    moved_file = cards_root / 'dst' / 'hero_1.png'
    moved_file.parent.mkdir(parents=True, exist_ok=True)
    moved_file.write_bytes(b'hero-image')

    saved_ui_payloads = []
    update_calls = []
    sync_calls = []
    move_card_calls = []
    events = []

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self.commit_calls = 0

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            return self

        def commit(self):
            self.commit_calls += 1
            events.append('commit')
            return None

    fake_conn = _FakeConn()
    ui_data = {
        'src/hero.png': {
            'summary': 'card note',
            card_service.VERSION_REMARKS_KEY: {
                'src/hero.png': {'summary': 'version note'},
            },
        },
        '_worldinfo_notes_v1': {
            'embedded::src/hero.png': {'summary': 'embedded note'},
            'embedded::src/other.png': {'summary': 'keep other note'},
            'resource::book.json': {'summary': 'keep resource note'},
        },
    }

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'save_ui_data',
        lambda payload, **_kwargs: ((
            events.append('save_ui_data'),
            saved_ui_payloads.append(json.loads(json.dumps(payload, ensure_ascii=False))),
        ), None)[1],
    )
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda card_id, full_path, **kwargs: ((
            events.append('update_card_cache'),
            update_calls.append({'card_id': card_id, 'full_path': full_path, 'kwargs': kwargs}),
            {
                'cache_updated': True,
                'has_embedded_wi': False,
                'previous_has_embedded_wi': False,
            },
        ))[2],
    )
    monkeypatch.setattr(
        card_service,
        'sync_card_index_jobs',
        lambda **kwargs: ((events.append('sync_card_index_jobs'), sync_calls.append(kwargs)), {})[1],
    )
    monkeypatch.setattr(
        card_service.ctx,
        'cache',
        SimpleNamespace(
            move_card_update=lambda *args: (events.append('move_card_update'), move_card_calls.append(args))[-1],
        ),
        raising=False,
    )

    card_service.sync_exact_card_after_fs_move(
        conn=fake_conn,
        ui_data=ui_data,
        old_card_id='src/hero.png',
        new_card_id='dst/hero_1.png',
        dst_full_path=str(moved_file),
        final_name='hero_1.png',
        old_category='src',
    )

    assert fake_conn.executed == [
        ('UPDATE card_metadata SET id = ?, category = ? WHERE id = ?', ('dst/hero_1.png', 'dst', 'src/hero.png')),
    ]
    assert fake_conn.commit_calls == 1
    assert saved_ui_payloads[-1] == {
        'dst/hero_1.png': {
            'summary': 'card note',
            card_service.VERSION_REMARKS_KEY: {
                'dst/hero_1.png': {'summary': 'version note'},
            },
        },
        '_worldinfo_notes_v1': {
            'embedded::dst/hero_1.png': {'summary': 'embedded note'},
            'embedded::src/other.png': {'summary': 'keep other note'},
            'resource::book.json': {'summary': 'keep resource note'},
        },
    }
    assert events == ['save_ui_data', 'commit', 'move_card_update', 'update_card_cache', 'sync_card_index_jobs']
    assert move_card_calls == [
        ('src/hero.png', 'dst/hero_1.png', 'src', 'dst', 'hero_1.png', str(moved_file)),
    ]
    assert update_calls == [
        {
            'card_id': 'dst/hero_1.png',
            'full_path': str(moved_file),
            'kwargs': {'remove_entity_ids': ['src/hero.png']},
        }
    ]
    assert sync_calls == [
        {
            'card_id': 'dst/hero_1.png',
            'source_path': str(moved_file),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['src/hero.png'],
            'remove_owner_ids': ['src/hero.png'],
        }
    ]


def test_sync_exact_card_after_fs_move_cache_failure_stops_after_commit_before_cache_refresh(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    moved_file = cards_root / 'dst' / 'hero.json'
    moved_file.parent.mkdir(parents=True, exist_ok=True)
    moved_file.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    update_calls = []
    sync_calls = []

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self.commit_calls = 0

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            return self

        def commit(self):
            self.commit_calls += 1
            return None

    fake_conn = _FakeConn()

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(card_service, 'save_ui_data', lambda payload, **_kwargs: None)
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda *args, **kwargs: update_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(card_service, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(
        card_service.ctx,
        'cache',
        SimpleNamespace(move_card_update=lambda *args: (_ for _ in ()).throw(RuntimeError('cache move failed'))),
        raising=False,
    )

    try:
        card_service.sync_exact_card_after_fs_move(
            conn=fake_conn,
            ui_data={},
            old_card_id='src/hero.json',
            new_card_id='dst/hero.json',
            dst_full_path=str(moved_file),
            final_name='hero.json',
            old_category='src',
        )
        raise AssertionError('expected cache move failure')
    except RuntimeError as exc:
        assert str(exc) == 'cache move failed'

    assert fake_conn.executed == [
        ('UPDATE card_metadata SET id = ?, category = ? WHERE id = ?', ('dst/hero.json', 'dst', 'src/hero.json')),
    ]
    assert fake_conn.commit_calls == 1
    assert update_calls == []
    assert sync_calls == []


def test_sync_exact_card_after_fs_move_save_ui_failure_skips_commit_and_cache_refresh(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    moved_file = cards_root / 'dst' / 'hero.json'
    moved_file.parent.mkdir(parents=True, exist_ok=True)
    moved_file.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    update_calls = []
    sync_calls = []
    move_card_calls = []

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self.commit_calls = 0

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            return self

        def commit(self):
            self.commit_calls += 1
            return None

    fake_conn = _FakeConn()
    ui_data = {'src/hero.json': {'summary': 'card note'}}

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'save_ui_data',
        lambda payload, **_kwargs: (_ for _ in ()).throw(RuntimeError('ui save failed')),
    )
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda *args, **kwargs: update_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(card_service, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})
    monkeypatch.setattr(
        card_service.ctx,
        'cache',
        SimpleNamespace(move_card_update=lambda *args: move_card_calls.append(args)),
        raising=False,
    )

    try:
        card_service.sync_exact_card_after_fs_move(
            conn=fake_conn,
            ui_data=ui_data,
            old_card_id='src/hero.json',
            new_card_id='dst/hero.json',
            dst_full_path=str(moved_file),
            final_name='hero.json',
            old_category='src',
        )
        raise AssertionError('expected ui save failure')
    except RuntimeError as exc:
        assert str(exc) == 'ui save failed'

    assert fake_conn.executed == [
        ('UPDATE card_metadata SET id = ?, category = ? WHERE id = ?', ('dst/hero.json', 'dst', 'src/hero.json')),
    ]
    assert fake_conn.commit_calls == 0
    assert move_card_calls == []
    assert update_calls == []
    assert sync_calls == []


def test_sync_exact_card_after_fs_move_updates_bundle_version_projection_for_nested_rename(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    moved_file = cards_root / 'dst' / 'bundle' / 'alt_1.json'
    moved_file.parent.mkdir(parents=True, exist_ok=True)
    moved_file.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    update_calls = []
    sync_calls = []
    events = []

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self.commit_calls = 0

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            return self

        def commit(self):
            self.commit_calls += 1
            events.append('commit')
            return None

    fake_conn = _FakeConn()

    class _GuardedCache:
        def __init__(self):
            self._id_map = {
                'src/bundle/alt.json': {
                    'id': 'src/bundle/alt.json',
                    'category': 'src/bundle',
                    'filename': 'alt.json',
                },
                'dst/bundle/cover.json': {
                    'id': 'dst/bundle/cover.json',
                    'category': 'dst/bundle',
                    'filename': 'cover.json',
                    'is_bundle': True,
                    'bundle_dir': 'dst/bundle',
                    'versions': [
                        {
                            'id': 'src/bundle/alt.json',
                            'filename': 'alt.json',
                        }
                    ],
                },
            }

        def move_card_update(self, old_id, new_id, old_category, new_category, new_filename, full_path):
            events.append('move_card_update')
            self._id_map.setdefault(new_id, dict(self._id_map.pop(old_id)))
            self._id_map[new_id].update(
                {
                    'id': new_id,
                    'category': new_category,
                    'filename': new_filename,
                }
            )
            self._id_map['dst/bundle/cover.json']['versions'] = [
                {
                    'id': new_id,
                    'filename': new_filename,
                }
            ]

        def update_bundle_version_projection_after_move(self, *args, **kwargs):
            raise AssertionError('sync_exact_card_after_fs_move should not require a second cache call')

        @property
        def id_map(self):
            raise AssertionError('sync_exact_card_after_fs_move should not mutate bundle versions via unlocked id_map access')

        @property
        def bundle_map(self):
            raise AssertionError('sync_exact_card_after_fs_move should not inspect bundle_map directly outside the cache lock')

    fake_cache = _GuardedCache()

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(
        card_service,
        'save_ui_data',
        lambda payload, **_kwargs: None,
    )
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda card_id, full_path, **kwargs: ((
            events.append('update_card_cache'),
            update_calls.append({'card_id': card_id, 'full_path': full_path, 'kwargs': kwargs}),
            {
                'cache_updated': True,
                'has_embedded_wi': False,
                'previous_has_embedded_wi': False,
            },
        ))[2],
    )
    monkeypatch.setattr(
        card_service,
        'sync_card_index_jobs',
        lambda **kwargs: ((events.append('sync_card_index_jobs'), sync_calls.append(kwargs)), {})[1],
    )
    monkeypatch.setattr(card_service.ctx, 'cache', fake_cache, raising=False)

    card_service.sync_exact_card_after_fs_move(
        conn=fake_conn,
        ui_data={},
        old_card_id='src/bundle/alt.json',
        new_card_id='dst/bundle/alt_1.json',
        dst_full_path=str(moved_file),
        final_name='alt_1.json',
        old_category='src/bundle',
    )

    assert fake_conn.executed == [
        ('UPDATE card_metadata SET id = ?, category = ? WHERE id = ?', ('dst/bundle/alt_1.json', 'dst/bundle', 'src/bundle/alt.json')),
    ]
    assert fake_conn.commit_calls == 1
    assert fake_cache._id_map['dst/bundle/cover.json']['versions'] == [
        {
            'id': 'dst/bundle/alt_1.json',
            'filename': 'alt_1.json',
        }
    ]
    assert events == ['commit', 'move_card_update', 'update_card_cache', 'sync_card_index_jobs']
    assert update_calls == [
        {
            'card_id': 'dst/bundle/alt_1.json',
            'full_path': str(moved_file),
            'kwargs': {'remove_entity_ids': ['src/bundle/alt.json']},
        }
    ]
    assert sync_calls == [
        {
            'card_id': 'dst/bundle/alt_1.json',
            'source_path': str(moved_file),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['src/bundle/alt.json'],
            'remove_owner_ids': ['src/bundle/alt.json'],
        }
    ]


def test_sync_exact_card_after_fs_move_reprojects_versions_across_bundles(monkeypatch, tmp_path):
    from core.services import card_service

    cards_root = tmp_path / 'cards'
    moved_file = cards_root / 'dst' / 'bundle' / 'alt.json'
    moved_file.parent.mkdir(parents=True, exist_ok=True)
    moved_file.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    update_calls = []
    sync_calls = []
    events = []

    class _FakeConn:
        def __init__(self):
            self.executed = []
            self.commit_calls = 0

        def execute(self, sql, params=()):
            self.executed.append((sql, params))
            return self

        def commit(self):
            self.commit_calls += 1
            events.append('commit')
            return None

    class _FakeCache:
        def __init__(self):
            self.bundle_map = {
                'src/bundle': 'src/bundle/cover.json',
                'dst/bundle': 'dst/bundle/cover.json',
            }
            self.id_map = {
                'src/bundle/alt.json': {
                    'id': 'src/bundle/alt.json',
                    'category': 'src/bundle',
                    'filename': 'alt.json',
                },
                'src/bundle/cover.json': {
                    'id': 'src/bundle/cover.json',
                    'category': 'src/bundle',
                    'filename': 'cover.json',
                    'is_bundle': True,
                    'bundle_dir': 'src/bundle',
                    'versions': [
                        {
                            'id': 'src/bundle/alt.json',
                            'filename': 'alt.json',
                        },
                        {
                            'id': 'src/bundle/cover.json',
                            'filename': 'cover.json',
                        },
                    ],
                },
                'dst/bundle/cover.json': {
                    'id': 'dst/bundle/cover.json',
                    'category': 'dst/bundle',
                    'filename': 'cover.json',
                    'is_bundle': True,
                    'bundle_dir': 'dst/bundle',
                    'versions': [
                        {
                            'id': 'dst/bundle/cover.json',
                            'filename': 'cover.json',
                        },
                    ],
                },
            }

        def move_card_update(self, old_id, new_id, old_category, new_category, new_filename, full_path):
            events.append('move_card_update')
            self.id_map.setdefault(new_id, dict(self.id_map.pop(old_id)))
            self.id_map[new_id].update(
                {
                    'id': new_id,
                    'category': new_category,
                    'filename': new_filename,
                }
            )
            self.id_map['src/bundle/cover.json']['versions'] = [
                version
                for version in self.id_map['src/bundle/cover.json']['versions']
                if version.get('id') != old_id
            ]
            self.id_map['dst/bundle/cover.json']['versions'].append(
                {
                    'id': new_id,
                    'filename': new_filename,
                }
            )

        def update_bundle_version_projection_after_move(self, *args, **kwargs):
            raise AssertionError('sync_exact_card_after_fs_move should not require a second cache call')

    fake_conn = _FakeConn()
    fake_cache = _FakeCache()

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root), raising=False)
    monkeypatch.setattr(card_service, 'save_ui_data', lambda payload, **_kwargs: None)
    monkeypatch.setattr(
        card_service,
        'update_card_cache',
        lambda card_id, full_path, **kwargs: ((
            events.append('update_card_cache'),
            update_calls.append({'card_id': card_id, 'full_path': full_path, 'kwargs': kwargs}),
            {
                'cache_updated': True,
                'has_embedded_wi': False,
                'previous_has_embedded_wi': False,
            },
        ))[2],
    )
    monkeypatch.setattr(
        card_service,
        'sync_card_index_jobs',
        lambda **kwargs: ((events.append('sync_card_index_jobs'), sync_calls.append(kwargs)), {})[1],
    )
    monkeypatch.setattr(card_service.ctx, 'cache', fake_cache, raising=False)

    card_service.sync_exact_card_after_fs_move(
        conn=fake_conn,
        ui_data={},
        old_card_id='src/bundle/alt.json',
        new_card_id='dst/bundle/alt.json',
        dst_full_path=str(moved_file),
        final_name='alt.json',
        old_category='src/bundle',
    )

    assert fake_conn.executed == [
        ('UPDATE card_metadata SET id = ?, category = ? WHERE id = ?', ('dst/bundle/alt.json', 'dst/bundle', 'src/bundle/alt.json')),
    ]
    assert fake_conn.commit_calls == 1
    assert fake_cache.id_map['src/bundle/cover.json']['versions'] == [
        {
            'id': 'src/bundle/cover.json',
            'filename': 'cover.json',
        }
    ]
    assert fake_cache.id_map['dst/bundle/cover.json']['versions'] == [
        {
            'id': 'dst/bundle/cover.json',
            'filename': 'cover.json',
        },
        {
            'id': 'dst/bundle/alt.json',
            'filename': 'alt.json',
        },
    ]
    assert events == ['commit', 'move_card_update', 'update_card_cache', 'sync_card_index_jobs']
    assert update_calls == [
        {
            'card_id': 'dst/bundle/alt.json',
            'full_path': str(moved_file),
            'kwargs': {'remove_entity_ids': ['src/bundle/alt.json']},
        }
    ]
    assert sync_calls == [
        {
            'card_id': 'dst/bundle/alt.json',
            'source_path': str(moved_file),
            'file_content_changed': False,
            'rename_changed': True,
            'cache_updated': True,
            'has_embedded_wi': False,
            'previous_has_embedded_wi': False,
            'remove_entity_ids': ['src/bundle/alt.json'],
            'remove_owner_ids': ['src/bundle/alt.json'],
        }
    ]


def test_global_metadata_cache_move_card_update_updates_bundle_projection_for_same_bundle(tmp_path):
    from core.data.cache import GlobalMetadataCache

    moved_file = tmp_path / 'bundle' / 'alt_1.json'
    moved_file.parent.mkdir(parents=True, exist_ok=True)
    moved_file.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    cache = GlobalMetadataCache()
    cache.bundle_map = {'bundle': 'bundle/cover.json'}
    cache.id_map = {
        'bundle/alt.json': {
            'id': 'bundle/alt.json',
            'category': 'bundle',
            'filename': 'alt.json',
            'last_modified': 1,
        },
        'bundle/cover.json': {
            'id': 'bundle/cover.json',
            'category': 'bundle',
            'filename': 'cover.json',
            'is_bundle': True,
            'bundle_dir': 'bundle',
            'versions': [
                {
                    'id': 'bundle/alt.json',
                    'filename': 'alt.json',
                }
            ],
        },
    }

    cache.move_card_update(
        'bundle/alt.json',
        'bundle/alt_1.json',
        'bundle',
        'bundle',
        'alt_1.json',
        str(moved_file),
    )

    assert cache.id_map['bundle/cover.json']['versions'] == [
        {
            'id': 'bundle/alt_1.json',
            'filename': 'alt_1.json',
        }
    ]


def test_global_metadata_cache_move_card_update_reprojects_versions_across_bundles(tmp_path):
    from core.data.cache import GlobalMetadataCache

    moved_file = tmp_path / 'dst' / 'bundle' / 'alt.json'
    moved_file.parent.mkdir(parents=True, exist_ok=True)
    moved_file.write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    cache = GlobalMetadataCache()
    cache.bundle_map = {
        'src/bundle': 'src/bundle/cover.json',
        'dst/bundle': 'dst/bundle/cover.json',
    }
    cache.id_map = {
        'src/bundle/alt.json': {
            'id': 'src/bundle/alt.json',
            'category': 'src/bundle',
            'filename': 'alt.json',
            'last_modified': 1,
        },
        'src/bundle/cover.json': {
            'id': 'src/bundle/cover.json',
            'category': 'src/bundle',
            'filename': 'cover.json',
            'is_bundle': True,
            'bundle_dir': 'src/bundle',
            'versions': [
                {
                    'id': 'src/bundle/alt.json',
                    'filename': 'alt.json',
                },
                {
                    'id': 'src/bundle/cover.json',
                    'filename': 'cover.json',
                },
            ],
        },
        'dst/bundle/cover.json': {
            'id': 'dst/bundle/cover.json',
            'category': 'dst/bundle',
            'filename': 'cover.json',
            'is_bundle': True,
            'bundle_dir': 'dst/bundle',
            'versions': [
                {
                    'id': 'dst/bundle/cover.json',
                    'filename': 'cover.json',
                },
            ],
        },
    }

    cache.move_card_update(
        'src/bundle/alt.json',
        'dst/bundle/alt.json',
        'src/bundle',
        'dst/bundle',
        'alt.json',
        str(moved_file),
    )

    assert cache.id_map['src/bundle/cover.json']['versions'] == [
        {
            'id': 'src/bundle/cover.json',
            'filename': 'cover.json',
        }
    ]
    assert cache.id_map['dst/bundle/cover.json']['versions'] == [
        {
            'id': 'dst/bundle/cover.json',
            'filename': 'cover.json',
        },
        {
            'id': 'dst/bundle/alt.json',
            'filename': 'alt.json',
        },
    ]


def test_cleanup_deleted_cards_after_fs_delete_dispatches_cleanup_only_jobs(monkeypatch):
    from core.services import card_service

    sync_calls = []

    monkeypatch.setattr(card_service, 'sync_card_index_jobs', lambda **kwargs: sync_calls.append(kwargs) or {})

    card_service.cleanup_deleted_cards_after_fs_delete(
        deleted_card_ids=['src/a.json', 'src/b.json'],
        source_paths_by_card_id={
            'src/a.json': 'D:/cards/src/a.json',
            'src/b.json': 'D:/cards/src/b.json',
        },
    )

    assert sync_calls == [
        {
            'card_id': 'src/a.json',
            'source_path': 'D:/cards/src/a.json',
            'remove_entity_ids': ['src/a.json'],
            'remove_owner_ids': ['src/a.json'],
        },
        {
            'card_id': 'src/b.json',
            'source_path': 'D:/cards/src/b.json',
            'remove_entity_ids': ['src/b.json'],
            'remove_owner_ids': ['src/b.json'],
        },
    ]


def test_api_rename_folder_uses_shared_folder_sync_helper(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'src' / 'pack'
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    sync_calls = []

    class _UnusedSqliteConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return self

        def execute(self, _sql, _params=()):
            return self

        def fetchall(self):
            return []

        def commit(self):
            return None

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'DEFAULT_DB_PATH', str(tmp_path / 'db.sqlite3'))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _value: True)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'src/pack': {'summary': 'folder note'}})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload, **_kwargs: None)
    monkeypatch.setattr(
        cards_api,
        'sqlite3',
        SimpleNamespace(connect=lambda *_args, **_kwargs: _UnusedSqliteConnection()),
    )
    monkeypatch.setattr(
        cards_api.ctx,
        'cache',
        SimpleNamespace(
            rename_folder_update=lambda *_args, **_kwargs: None,
            category_counts={'src': 1},
        ),
        raising=False,
    )
    def _record_sync(**kwargs):
        sync_calls.append(kwargs)

    monkeypatch.setattr(cards_api, 'sync_folder_prefix_after_fs_move', _record_sync, raising=False)

    client = _make_app().test_client()
    res = client.post('/api/rename_folder', json={'old_path': 'src/pack', 'new_name': 'renamed'})

    assert res.status_code == 200
    assert res.get_json() == {'success': True, 'new_path': 'src/renamed'}
    assert sync_calls == [
        {
            'conn': sync_calls[0]['conn'],
            'ui_data': {'src/pack': {'summary': 'folder note'}},
            'old_path': 'src/pack',
            'new_path': 'src/renamed',
        }
    ]
    assert (cards_dir / 'src' / 'pack').exists() is False
    assert (cards_dir / 'src' / 'renamed' / 'hero.json').exists() is True


def test_api_rename_folder_returns_warning_when_shared_sync_fails(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'src' / 'pack'
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    schedule_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, '_is_safe_filename', lambda _value: True)
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError('sync failed')),
        raising=False,
    )
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **kwargs: schedule_calls.append(kwargs))

    client = _make_app().test_client()
    res = client.post('/api/rename_folder', json={'old_path': 'src/pack', 'new_name': 'renamed'})

    assert res.status_code == 200
    assert res.get_json() == {
        'success': True,
        'new_path': 'src/renamed',
        'warning': '文件夹已重命名，但数据库索引更新遇到问题，系统将自动修复。',
    }
    assert schedule_calls == [{'reason': 'rename_folder:fallback'}]
    assert (cards_dir / 'src' / 'pack').exists() is False
    assert (cards_dir / 'src' / 'renamed' / 'hero.json').exists() is True


def test_api_move_folder_direct_uses_shared_folder_sync_helper(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'src' / 'pack'
    target_parent_dir = cards_dir / 'dst'
    source_dir.mkdir(parents=True, exist_ok=True)
    target_parent_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    sync_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'src/pack': {'summary': 'folder note'}})
    monkeypatch.setattr(cards_api, 'save_ui_data', lambda _payload, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'rename_folder_in_db', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, 'rename_folder_in_ui', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cards_api.ctx,
        'cache',
        SimpleNamespace(
            move_folder_update=lambda *_args, **_kwargs: None,
            category_counts={'dst': 1},
        ),
        raising=False,
    )
    def _record_sync(**kwargs):
        sync_calls.append(kwargs)

    monkeypatch.setattr(cards_api, 'sync_folder_prefix_after_fs_move', _record_sync, raising=False)

    client = _make_app().test_client()
    res = client.post('/api/move_folder', json={'source_path': 'src/pack', 'target_parent_path': 'dst'})

    assert res.status_code == 200
    assert res.get_json() == {
        'success': True,
        'new_path': 'dst/pack',
        'mode': 'move',
        'category_counts': {'dst': 1},
    }
    assert sync_calls == [
        {
            'conn': sync_calls[0]['conn'],
            'ui_data': {'src/pack': {'summary': 'folder note'}},
            'old_path': 'src/pack',
            'new_path': 'dst/pack',
        }
    ]
    assert (cards_dir / 'src' / 'pack').exists() is False
    assert (cards_dir / 'dst' / 'pack' / 'hero.json').exists() is True


def test_api_move_folder_direct_returns_warning_when_shared_sync_fails(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'src' / 'pack'
    target_parent_dir = cards_dir / 'dst'
    source_dir.mkdir(parents=True, exist_ok=True)
    target_parent_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    schedule_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'src/pack': {'summary': 'folder note'}})
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError('sync failed')),
        raising=False,
    )
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **kwargs: schedule_calls.append(kwargs))
    monkeypatch.setattr(
        cards_api.ctx,
        'cache',
        SimpleNamespace(category_counts={'dst': 1}),
        raising=False,
    )

    client = _make_app().test_client()
    res = client.post('/api/move_folder', json={'source_path': 'src/pack', 'target_parent_path': 'dst'})

    assert res.status_code == 200
    assert res.get_json() == {
        'success': True,
        'new_path': 'dst/pack',
        'mode': 'move',
        'warning': '文件夹已移动，但数据库索引更新遇到问题，系统将自动修复。',
        'category_counts': {'dst': 1},
    }
    assert schedule_calls == [{'reason': 'move_folder:fallback'}]
    assert (cards_dir / 'src' / 'pack').exists() is False
    assert (cards_dir / 'dst' / 'pack' / 'hero.json').exists() is True


def test_api_move_folder_merge_plans_success_actions_without_force_reload(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'src' / 'pack'
    target_dir = cards_dir / 'dst' / 'pack'
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    (source_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')
    (source_dir / 'ally.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')
    subfree_dir = source_dir / 'subfree'
    subfree_dir.mkdir(parents=True, exist_ok=True)
    (subfree_dir / 'ally.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')
    (target_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    folder_sync_calls = []
    exact_sync_calls = []
    force_reload_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'get_db', lambda: object())
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'src/pack': {'summary': 'folder note'}})
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **kwargs: folder_sync_calls.append(kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        cards_api,
        'sync_exact_card_after_fs_move',
        lambda **kwargs: exact_sync_calls.append(kwargs),
        raising=False,
    )

    client = _make_app().test_client()
    res = client.post(
        '/api/move_folder',
        json={
            'source_path': 'src/pack',
            'target_parent_path': 'dst',
            'merge_if_exists': True,
        },
    )

    assert res.status_code == 200
    assert res.get_json() == {'success': True, 'new_path': 'dst/pack', 'mode': 'merge'}
    assert folder_sync_calls == [
        {
            'conn': folder_sync_calls[0]['conn'],
            'ui_data': {'src/pack': {'summary': 'folder note'}},
            'old_path': 'src/pack/subfree',
            'new_path': 'dst/pack/subfree',
        }
    ]
    assert len(exact_sync_calls) == 2
    assert {
        (
            call['old_card_id'],
            call['new_card_id'],
            call['dst_full_path'],
            call['final_name'],
            call['old_category'],
        )
        for call in exact_sync_calls
    } == {
        (
            'src/pack/hero.json',
            'dst/pack/hero_1.json',
            str(target_dir / 'hero_1.json'),
            'hero_1.json',
            'src/pack',
        ),
        (
            'src/pack/ally.json',
            'dst/pack/ally.json',
            str(target_dir / 'ally.json'),
            'ally.json',
            'src/pack',
        ),
    }
    assert {id(call['conn']) for call in exact_sync_calls} == {id(exact_sync_calls[0]['conn'])}
    assert {id(call['ui_data']) for call in exact_sync_calls} == {id(exact_sync_calls[0]['ui_data'])}
    assert force_reload_calls == []
    assert (cards_dir / 'dst' / 'pack' / 'hero_1.json').exists() is True
    assert (cards_dir / 'dst' / 'pack' / 'ally.json').exists() is True
    assert (cards_dir / 'dst' / 'pack' / 'subfree' / 'ally.json').exists() is True
    assert (cards_dir / 'src' / 'pack').exists() is False


def test_api_move_folder_merge_syncs_standalone_png_without_conflict(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'src' / 'pack'
    target_dir = cards_dir / 'dst' / 'pack'
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    (source_dir / 'hero.png').write_bytes(b'hero-image')

    folder_sync_calls = []
    exact_sync_calls = []
    force_reload_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'get_db', lambda: object())
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'src/pack': {'summary': 'folder note'}})
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **kwargs: folder_sync_calls.append(kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        cards_api,
        'sync_exact_card_after_fs_move',
        lambda **kwargs: exact_sync_calls.append(kwargs),
        raising=False,
    )

    client = _make_app().test_client()
    res = client.post(
        '/api/move_folder',
        json={
            'source_path': 'src/pack',
            'target_parent_path': 'dst',
            'merge_if_exists': True,
        },
    )

    assert res.status_code == 200
    assert res.get_json() == {'success': True, 'new_path': 'dst/pack', 'mode': 'merge'}
    assert folder_sync_calls == []
    assert len(exact_sync_calls) == 1
    assert exact_sync_calls[0]['old_card_id'] == 'src/pack/hero.png'
    assert exact_sync_calls[0]['new_card_id'] == 'dst/pack/hero.png'
    assert exact_sync_calls[0]['dst_full_path'] == str(target_dir / 'hero.png')
    assert exact_sync_calls[0]['final_name'] == 'hero.png'
    assert exact_sync_calls[0]['old_category'] == 'src/pack'
    assert force_reload_calls == []
    assert (cards_dir / 'dst' / 'pack' / 'hero.png').exists() is True
    assert (cards_dir / 'src' / 'pack').exists() is False


def test_api_move_folder_merge_syncs_standalone_png_when_conflict_renames(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'src' / 'pack'
    target_dir = cards_dir / 'dst' / 'pack'
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    (source_dir / 'hero.png').write_bytes(b'source-hero-image')
    (target_dir / 'hero.png').write_bytes(b'existing-hero-image')

    folder_sync_calls = []
    exact_sync_calls = []
    force_reload_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'get_db', lambda: object())
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'src/pack': {'summary': 'folder note'}})
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **kwargs: folder_sync_calls.append(kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        cards_api,
        'sync_exact_card_after_fs_move',
        lambda **kwargs: exact_sync_calls.append(kwargs),
        raising=False,
    )

    client = _make_app().test_client()
    res = client.post(
        '/api/move_folder',
        json={
            'source_path': 'src/pack',
            'target_parent_path': 'dst',
            'merge_if_exists': True,
        },
    )

    assert res.status_code == 200
    assert res.get_json() == {'success': True, 'new_path': 'dst/pack', 'mode': 'merge'}
    assert folder_sync_calls == []
    assert len(exact_sync_calls) == 1
    assert exact_sync_calls[0]['old_card_id'] == 'src/pack/hero.png'
    assert exact_sync_calls[0]['new_card_id'] == 'dst/pack/hero_1.png'
    assert exact_sync_calls[0]['dst_full_path'] == str(target_dir / 'hero_1.png')
    assert exact_sync_calls[0]['final_name'] == 'hero_1.png'
    assert exact_sync_calls[0]['old_category'] == 'src/pack'
    assert force_reload_calls == []
    assert (cards_dir / 'dst' / 'pack' / 'hero.png').read_bytes() == b'existing-hero-image'
    assert (cards_dir / 'dst' / 'pack' / 'hero_1.png').read_bytes() == b'source-hero-image'
    assert (cards_dir / 'src' / 'pack').exists() is False


def test_api_move_folder_merge_returns_warning_when_shared_sync_fails_after_fs_started(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'src' / 'pack'
    target_dir = cards_dir / 'dst' / 'pack'
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    (source_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')
    (target_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    schedule_calls = []
    force_reload_calls = []
    exact_sync_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'get_db', lambda: object())
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'src/pack': {'summary': 'folder note'}})
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **kwargs: schedule_calls.append(kwargs))
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))
    monkeypatch.setattr(
        cards_api,
        'sync_exact_card_after_fs_move',
        lambda **kwargs: (exact_sync_calls.append(kwargs), (_ for _ in ()).throw(RuntimeError('sync failed')))[1],
        raising=False,
    )
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **_kwargs: None,
        raising=False,
    )

    client = _make_app().test_client()
    res = client.post(
        '/api/move_folder',
        json={
            'source_path': 'src/pack',
            'target_parent_path': 'dst',
            'merge_if_exists': True,
        },
    )

    assert res.status_code == 200
    assert res.get_json() == {
        'success': True,
        'new_path': 'dst/pack',
        'mode': 'merge',
        'warning': '文件夹已合并，但数据库索引更新遇到问题，系统将自动修复。',
    }
    assert schedule_calls == [{'reason': 'move_folder:merge_fallback'}]
    assert force_reload_calls == []
    assert len(exact_sync_calls) == 1
    assert exact_sync_calls[0]['old_card_id'] == 'src/pack/hero.json'
    assert exact_sync_calls[0]['new_card_id'] == 'dst/pack/hero_1.json'
    assert (cards_dir / 'dst' / 'pack' / 'hero_1.json').exists() is True
    assert (cards_dir / 'src' / 'pack' / 'hero.json').exists() is False


def test_api_move_folder_merge_sync_failure_before_remaining_actions_returns_error(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'src' / 'pack'
    target_dir = cards_dir / 'dst' / 'pack'
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    (source_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')
    (source_dir / 'ally.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')
    (target_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    schedule_calls = []
    force_reload_calls = []
    exact_sync_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'get_db', lambda: object())
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'src/pack': {'summary': 'folder note'}})
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **kwargs: schedule_calls.append(kwargs))
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))
    monkeypatch.setattr(
        cards_api,
        'sync_exact_card_after_fs_move',
        lambda **kwargs: (exact_sync_calls.append(kwargs), (_ for _ in ()).throw(RuntimeError('sync failed')))[1],
        raising=False,
    )
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **_kwargs: None,
        raising=False,
    )

    client = _make_app().test_client()
    res = client.post(
        '/api/move_folder',
        json={
            'source_path': 'src/pack',
            'target_parent_path': 'dst',
            'merge_if_exists': True,
        },
    )

    assert res.status_code == 200
    assert res.get_json() == {
        'success': True,
        'new_path': 'dst/pack',
        'mode': 'merge',
        'warning': '文件夹已合并，但数据库索引更新遇到问题，系统将自动修复。',
    }
    assert schedule_calls == [{'reason': 'move_folder:merge_fallback'}]
    assert force_reload_calls == []
    assert len(exact_sync_calls) == 1
    moved_old_id = exact_sync_calls[0]['old_card_id']
    moved_new_id = exact_sync_calls[0]['new_card_id']
    assert {moved_old_id, moved_new_id} in [
        {'src/pack/hero.json', 'dst/pack/hero_1.json'},
        {'src/pack/ally.json', 'dst/pack/ally.json'},
    ]
    if moved_old_id == 'src/pack/hero.json':
        assert (cards_dir / 'dst' / 'pack' / 'hero_1.json').exists() is True
        assert (cards_dir / 'src' / 'pack' / 'hero.json').exists() is False
        assert (cards_dir / 'dst' / 'pack' / 'ally.json').exists() is False
        assert (cards_dir / 'src' / 'pack' / 'ally.json').exists() is True
    else:
        assert (cards_dir / 'dst' / 'pack' / 'ally.json').exists() is True
        assert (cards_dir / 'src' / 'pack' / 'ally.json').exists() is False
        assert (cards_dir / 'dst' / 'pack' / 'hero_1.json').exists() is False
        assert (cards_dir / 'src' / 'pack' / 'hero.json').exists() is True


def test_api_move_folder_merge_returns_warning_for_post_mutation_failure_before_remaining_actions(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'src' / 'pack'
    target_dir = cards_dir / 'dst' / 'pack'
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    (source_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')
    (source_dir / 'ally.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')
    (target_dir / 'hero.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    schedule_calls = []
    force_reload_calls = []
    exact_sync_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'get_db', lambda: object())
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'src/pack': {'summary': 'folder note'}})
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **kwargs: schedule_calls.append(kwargs))
    monkeypatch.setattr(cards_api, 'force_reload', lambda **kwargs: force_reload_calls.append(kwargs))
    monkeypatch.setattr(
        cards_api,
        'sync_exact_card_after_fs_move',
        lambda **kwargs: (exact_sync_calls.append(kwargs), (_ for _ in ()).throw(RuntimeError('sync failed')))[1],
        raising=False,
    )
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **_kwargs: None,
        raising=False,
    )

    client = _make_app().test_client()
    res = client.post(
        '/api/move_folder',
        json={
            'source_path': 'src/pack',
            'target_parent_path': 'dst',
            'merge_if_exists': True,
        },
    )

    assert res.status_code == 200
    assert res.get_json() == {
        'success': True,
        'new_path': 'dst/pack',
        'mode': 'merge',
        'warning': '文件夹已合并，但数据库索引更新遇到问题，系统将自动修复。',
    }
    assert schedule_calls == [{'reason': 'move_folder:merge_fallback'}]
    assert force_reload_calls == []
    assert len(exact_sync_calls) == 1
    moved_old_id = exact_sync_calls[0]['old_card_id']
    moved_new_id = exact_sync_calls[0]['new_card_id']
    assert {moved_old_id, moved_new_id} in [
        {'src/pack/hero.json', 'dst/pack/hero_1.json'},
        {'src/pack/ally.json', 'dst/pack/ally.json'},
    ]
    if moved_old_id == 'src/pack/hero.json':
        assert (cards_dir / 'dst' / 'pack' / 'hero_1.json').exists() is True
        assert (cards_dir / 'src' / 'pack' / 'hero.json').exists() is False
        assert (cards_dir / 'dst' / 'pack' / 'ally.json').exists() is False
        assert (cards_dir / 'src' / 'pack' / 'ally.json').exists() is True
    else:
        assert (cards_dir / 'dst' / 'pack' / 'ally.json').exists() is True
        assert (cards_dir / 'src' / 'pack' / 'ally.json').exists() is False
        assert (cards_dir / 'dst' / 'pack' / 'hero_1.json').exists() is False
        assert (cards_dir / 'src' / 'pack' / 'hero.json').exists() is True


def test_api_move_folder_merge_returns_warning_when_folder_sync_fails_after_folder_move(monkeypatch, tmp_path):
    cards_dir = tmp_path / 'cards'
    source_dir = cards_dir / 'src' / 'pack'
    target_dir = cards_dir / 'dst' / 'pack'
    source_dir.mkdir(parents=True, exist_ok=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    (source_dir / 'subfree').mkdir(parents=True, exist_ok=True)
    (source_dir / 'subfree' / 'ally.json').write_text('{"spec":"chara_card_v2"}', encoding='utf-8')

    schedule_calls = []
    exact_sync_calls = []

    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(cards_api, 'suppress_fs_events', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cards_api, '_is_safe_rel_path', lambda _value, allow_empty=False: True)
    monkeypatch.setattr(cards_api, 'get_db', lambda: object())
    monkeypatch.setattr(cards_api, 'load_ui_data', lambda: {'src/pack': {'summary': 'folder note'}})
    monkeypatch.setattr(cards_api, 'schedule_reload', lambda **kwargs: schedule_calls.append(kwargs))
    monkeypatch.setattr(
        cards_api,
        'sync_exact_card_after_fs_move',
        lambda **kwargs: exact_sync_calls.append(kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        cards_api,
        'sync_folder_prefix_after_fs_move',
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError('sync failed')),
        raising=False,
    )

    client = _make_app().test_client()
    res = client.post(
        '/api/move_folder',
        json={
            'source_path': 'src/pack',
            'target_parent_path': 'dst',
            'merge_if_exists': True,
        },
    )

    assert res.status_code == 200
    assert res.get_json() == {
        'success': True,
        'new_path': 'dst/pack',
        'mode': 'merge',
        'warning': '文件夹已合并，但数据库索引更新遇到问题，系统将自动修复。',
    }
    assert schedule_calls == [{'reason': 'move_folder:merge_fallback'}]
    assert exact_sync_calls == []
    assert (cards_dir / 'dst' / 'pack' / 'subfree' / 'ally.json').exists() is True
    assert (cards_dir / 'src' / 'pack' / 'subfree').exists() is False
