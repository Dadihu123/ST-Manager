import json
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.services import index_service
from core.services.worldinfo_index_query_service import query_worldinfo_index
from core.data.index_runtime_store import ensure_index_runtime_schema


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _activate_worldinfo_generation(conn, generation=1):
    ensure_index_runtime_schema(conn)
    conn.execute(
        "UPDATE index_build_state SET active_generation = ?, state = 'ready', phase = 'ready' WHERE scope = 'worldinfo'",
        (generation,),
    )


def test_rebuild_worldinfo_index_writes_global_resource_and_embedded_rows(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    lore_dir = tmp_path / 'lorebooks'
    res_dir = tmp_path / 'resources'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()

    _write_json(lore_dir / '科幻' / 'dragon.json', {'name': 'Dragon Lore', 'entries': {}})
    _write_json(res_dir / 'lucy' / 'lorebooks' / 'companion.json', {'name': 'Companion Lore', 'entries': {}})

    monkeypatch.setattr(index_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_service, 'load_config', lambda: {'world_info_dir': str(lore_dir), 'resources_dir': str(res_dir)})
    monkeypatch.setattr(index_service, 'load_ui_data', lambda: {
        'cards/lucy.png': {'resource_folder': 'lucy'},
        '_resource_item_categories_v1': {'worldinfo': {}},
    })
    monkeypatch.setattr(index_service, 'extract_card_info', lambda _path: {'data': {'character_book': {'name': 'Embedded Book', 'entries': {'0': {'content': 'hello'}}}}})

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, category TEXT, has_character_book INTEGER, character_book_name TEXT, last_modified REAL, wi_metadata_scanned INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO card_metadata (id, char_name, category, has_character_book, character_book_name, last_modified, wi_metadata_scanned) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('cards/lucy.png', 'Lucy', '科幻', 1, 'Embedded Book', 100.0, 0),
        )
        conn.commit()

    index_service.rebuild_worldinfo_index()

    with sqlite3.connect(db_path) as conn:
        generation = conn.execute(
            "SELECT active_generation FROM index_build_state WHERE scope = 'worldinfo'"
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT entity_type, name, display_category, category_mode, owner_entity_id FROM index_entities_v2 WHERE generation = ? AND entity_type LIKE 'world_%' ORDER BY entity_type",
            (generation,),
        ).fetchall()

    assert rows == [
        ('world_embedded', 'Embedded Book', '科幻', 'inherited', 'card::cards/lucy.png'),
        ('world_global', 'Dragon Lore', '科幻', 'physical', ''),
        ('world_resource', 'Companion Lore', '科幻', 'inherited', 'card::cards/lucy.png'),
    ]


def test_rebuild_worldinfo_index_preserves_resource_override_category(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    res_dir = tmp_path / 'resources'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()
    from PIL import Image
    (cards_dir / 'cards').mkdir()
    Image.new('RGB', (1, 1)).save(cards_dir / 'cards' / 'lucy.png')
    (tmp_path / 'lorebooks').mkdir()
    target = res_dir / 'lucy' / 'lorebooks' / 'companion.json'
    _write_json(target, {'name': 'Companion Lore', 'entries': {}})

    monkeypatch.setattr(index_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_service, 'load_config', lambda: {'world_info_dir': str(tmp_path / 'lorebooks'), 'resources_dir': str(res_dir)})
    monkeypatch.setattr(index_service, 'load_ui_data', lambda: {
        'cards/lucy.png': {'resource_folder': 'lucy'},
        '_resource_item_categories_v1': {
            'worldinfo': {
                str(target).replace('\\', '/').lower(): {'category': '自定义分类', 'updated_at': 1}
            }
        },
    })

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, category TEXT, has_character_book INTEGER, character_book_name TEXT, last_modified REAL, wi_metadata_scanned INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO card_metadata (id, char_name, category, has_character_book, character_book_name, last_modified, wi_metadata_scanned) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('cards/lucy.png', 'Lucy', '原始分类', 0, '', 100.0, 0),
        )
        conn.commit()

    index_service.rebuild_worldinfo_index()

    with sqlite3.connect(db_path) as conn:
        generation = conn.execute(
            "SELECT active_generation FROM index_build_state WHERE scope = 'worldinfo'"
        ).fetchone()[0]
        row = conn.execute(
            "SELECT display_category, category_mode FROM index_entities_v2 WHERE generation = ? AND entity_type = 'world_resource'",
            (generation,),
        ).fetchone()

    assert row == ('自定义分类', 'override')


def test_rebuild_worldinfo_index_skips_bad_files_without_erasing_valid_rows(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    lore_dir = tmp_path / 'lorebooks'
    cards_dir = tmp_path / 'cards'
    cards_dir.mkdir()

    _write_json(lore_dir / '科幻' / 'dragon.json', {'name': 'Dragon Lore', 'entries': {}})
    bad_path = lore_dir / '科幻' / 'broken.json'
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text('{bad json', encoding='utf-8')

    monkeypatch.setattr(index_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_service, 'CARDS_FOLDER', str(cards_dir))
    monkeypatch.setattr(index_service, 'load_config', lambda: {'world_info_dir': str(lore_dir), 'resources_dir': str(tmp_path / 'resources')})
    monkeypatch.setattr(index_service, 'load_ui_data', lambda: {'_resource_item_categories_v1': {'worldinfo': {}}})

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, category TEXT, has_character_book INTEGER, character_book_name TEXT, last_modified REAL, wi_metadata_scanned INTEGER DEFAULT 0)"
        )
        conn.commit()

    index_service.rebuild_worldinfo_index()

    with sqlite3.connect(db_path) as conn:
        generation = conn.execute(
            "SELECT active_generation FROM index_build_state WHERE scope = 'worldinfo'"
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT entity_type, name FROM index_entities_v2 WHERE generation = ? AND entity_type LIKE 'world_%' ORDER BY entity_type, name",
            (generation,),
        ).fetchall()

    assert rows == [('world_global', 'Dragon Lore')]


def test_rebuild_worldinfo_index_uses_configured_cards_dir_for_embedded_books(monkeypatch, tmp_path):
    db_path = tmp_path / 'cards_metadata.db'
    (tmp_path / 'lorebooks').mkdir()
    configured_cards_dir = tmp_path / 'configured-cards'
    configured_cards_dir.mkdir()
    fallback_cards_dir = tmp_path / 'fallback-cards'
    fallback_cards_dir.mkdir()

    seen_paths = []

    def _fake_extract(path):
        seen_paths.append(path)
        if path == str(configured_cards_dir / 'cards' / 'lucy.png'):
            return {'data': {'character_book': {'name': 'Embedded Book', 'entries': {'0': {'content': 'hello'}}}}}
        return None

    monkeypatch.setattr(index_service, 'DEFAULT_DB_PATH', str(db_path))
    monkeypatch.setattr(index_service, 'CARDS_FOLDER', str(fallback_cards_dir))
    monkeypatch.setattr(
        index_service,
        'load_config',
        lambda: {
            'world_info_dir': str(tmp_path / 'lorebooks'),
            'resources_dir': str(tmp_path / 'resources'),
            'cards_dir': str(configured_cards_dir),
        },
    )
    monkeypatch.setattr(index_service, 'load_ui_data', lambda: {'_resource_item_categories_v1': {'worldinfo': {}}})
    monkeypatch.setattr(index_service, 'extract_card_info', _fake_extract)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE card_metadata (id TEXT PRIMARY KEY, char_name TEXT, category TEXT, has_character_book INTEGER, character_book_name TEXT, last_modified REAL, wi_metadata_scanned INTEGER DEFAULT 0)"
        )
        conn.execute(
            "INSERT INTO card_metadata (id, char_name, category, has_character_book, character_book_name, last_modified, wi_metadata_scanned) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ('cards/lucy.png', 'Lucy', '科幻', 1, 'Embedded Book', 100.0, 0),
        )
        conn.commit()

    index_service.rebuild_worldinfo_index()

    with sqlite3.connect(db_path) as conn:
        generation = conn.execute(
            "SELECT active_generation FROM index_build_state WHERE scope = 'worldinfo'"
        ).fetchone()[0]
        row = conn.execute(
            "SELECT entity_type, name, source_path FROM index_entities_v2 WHERE generation = ? AND entity_type = 'world_embedded'",
            (generation,),
        ).fetchone()

    assert seen_paths == [str(configured_cards_dir / 'cards' / 'lucy.png')]
    assert row == ('world_embedded', 'Embedded Book', str(configured_cards_dir / 'cards' / 'lucy.png'))


def test_query_worldinfo_index_returns_filtered_page_and_folder_metadata_from_projection(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        _activate_worldinfo_generation(conn, 1)
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'world::global::科幻/dragon.json', 'world_global', 'D:/lorebooks/科幻/dragon.json', '', 'Dragon Lore', 'dragon.json', '科幻', '科幻', 'physical', 0, '', 300.0, 0.0, 0, 'dragon lore', 300.0, '', '300:1'),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'world::global::科幻/alpha.json', 'world_global', 'D:/lorebooks/科幻/alpha.json', '', 'Alpha Lore', 'alpha.json', '科幻', '科幻', 'physical', 0, '', 200.0, 0.0, 0, 'alpha lore', 200.0, '', '200:1'),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'world::global::奇幻/forest.json', 'world_global', 'D:/lorebooks/奇幻/forest.json', '', 'Forest Lore', 'forest.json', '奇幻', '奇幻', 'physical', 0, '', 100.0, 0.0, 0, 'forest lore', 100.0, '', '100:1'),
        )
        conn.execute("INSERT OR REPLACE INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)", (1, 'world::global::科幻/dragon.json', 'Dragon Lore'))
        conn.execute("INSERT OR REPLACE INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)", (1, 'world::global::科幻/alpha.json', 'Alpha Lore'))
        conn.execute("INSERT OR REPLACE INTO index_search_fast_v2(generation, entity_id, content) VALUES (?, ?, ?)", (1, 'world::global::奇幻/forest.json', 'Forest Lore'))
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_global', '科幻', 2, 2),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_global', '奇幻', 1, 1),
        )
        conn.commit()

    result = query_worldinfo_index({
        'type': 'global',
        'category': '科幻',
        'search': 'dragon',
        'page': 1,
        'page_size': 1,
        'paginate': True,
        'db_path': str(db_path),
    })

    assert [item['id'] for item in result['items']] == ['world::global::科幻/dragon.json']
    assert result['total'] == 1
    assert result['all_folders'] == ['奇幻', '科幻']
    assert result['category_counts'] == {'奇幻': 1, '科幻': 2}
    assert result['folder_capabilities']['']['can_create_child_folder'] is True
    assert result['folder_capabilities']['科幻']['has_physical_folder'] is True
    assert result['folder_capabilities']['奇幻']['can_rename_physical_folder'] is True


def test_query_worldinfo_index_uses_subtree_counts_for_ancestor_folder_badges(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        _activate_worldinfo_generation(conn, 1)
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'world::global::科幻/赛博朋克/dragon.json', 'world_global', 'D:/lorebooks/科幻/赛博朋克/dragon.json', '', 'Dragon Lore', 'dragon.json', '科幻/赛博朋克', '科幻/赛博朋克', 'physical', 0, '', 300.0, 0.0, 0, 'dragon lore', 300.0, '', '300:1'),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_global', '科幻', 0, 1),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_global', '科幻/赛博朋克', 1, 1),
        )
        conn.commit()

    result = query_worldinfo_index({
        'type': 'global',
        'page': 1,
        'page_size': 20,
        'paginate': True,
        'db_path': str(db_path),
    })

    assert result['category_counts']['科幻'] == 1
    assert result['category_counts']['科幻/赛博朋克'] == 1


def test_query_worldinfo_index_marks_virtual_resource_folders_without_physical_folder_capabilities(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        _activate_worldinfo_generation(conn, 1)
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'world::resource::cards/lucy.png::companion.json', 'world_resource', 'D:/resources/lucy/lorebooks/companion.json', 'card::cards/lucy.png', 'Companion Lore', 'companion.json', '科幻/伙伴', '', 'inherited', 0, '', 300.0, 0.0, 0, 'companion lore', 300.0, '', '300:1'),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_resource', '科幻', 0, 1),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_resource', '科幻/伙伴', 1, 1),
        )
        conn.commit()

    result = query_worldinfo_index({
        'type': 'resource',
        'page': 1,
        'page_size': 20,
        'paginate': True,
        'db_path': str(db_path),
    })

    assert result['folder_capabilities']['科幻']['has_physical_folder'] is False
    assert result['folder_capabilities']['科幻']['has_virtual_items'] is True
    assert result['folder_capabilities']['科幻']['can_create_child_folder'] is False
    assert result['folder_capabilities']['科幻']['can_rename_physical_folder'] is False
    assert result['folder_capabilities']['科幻/伙伴']['has_physical_folder'] is False
    assert result['folder_capabilities']['科幻/伙伴']['has_virtual_items'] is True


def test_query_worldinfo_index_type_all_preserves_empty_physical_folder_capabilities(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        _activate_worldinfo_generation(conn, 1)
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_all', '科幻', 0, 0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_global', '科幻', 0, 0),
        )
        conn.commit()

    result = query_worldinfo_index({
        'type': 'all',
        'page': 1,
        'page_size': 20,
        'paginate': True,
        'db_path': str(db_path),
    })

    assert result['folder_capabilities']['科幻']['has_physical_folder'] is True
    assert result['folder_capabilities']['科幻']['can_create_child_folder'] is True
    assert result['folder_capabilities']['科幻']['can_rename_physical_folder'] is True


def test_query_worldinfo_index_marks_empty_physical_folders_deletable(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        _activate_worldinfo_generation(conn, 1)
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_global', '科幻', 0, 0),
        )
        conn.commit()

    result = query_worldinfo_index({
        'type': 'global',
        'page': 1,
        'page_size': 20,
        'paginate': True,
        'db_path': str(db_path),
    })

    assert result['folder_capabilities']['科幻']['has_physical_folder'] is True
    assert result['folder_capabilities']['科幻']['can_delete_physical_folder'] is True


def test_query_worldinfo_index_does_not_mark_parent_with_child_folder_deletable(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        _activate_worldinfo_generation(conn, 1)
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_global', '科幻', 0, 0),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_global', '科幻/空目录', 0, 0),
        )
        conn.commit()

    result = query_worldinfo_index({
        'type': 'global',
        'page': 1,
        'page_size': 20,
        'paginate': True,
        'db_path': str(db_path),
    })

    assert result['folder_capabilities']['科幻']['has_physical_folder'] is True
    assert result['folder_capabilities']['科幻']['can_delete_physical_folder'] is False
    assert result['folder_capabilities']['科幻/空目录']['can_delete_physical_folder'] is True


def test_query_worldinfo_index_malformed_search_falls_back_to_literal_name_substring(tmp_path):
    db_path = tmp_path / 'cards_metadata.db'

    with sqlite3.connect(db_path) as conn:
        _activate_worldinfo_generation(conn, 1)
        conn.execute(
            "INSERT OR REPLACE INTO index_entities_v2(generation, entity_id, entity_type, source_path, owner_entity_id, name, filename, display_category, physical_category, category_mode, favorite, summary_preview, updated_at, import_time, token_count, sort_name, sort_mtime, thumb_url, source_revision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 'world::global::科幻/broken[query].json', 'world_global', 'D:/lorebooks/科幻/broken[query].json', '', 'broken[query] lore', 'broken[query].json', '科幻', '科幻', 'physical', 0, '', 300.0, 0.0, 0, 'broken[query] lore', 300.0, '', '300:1'),
        )
        conn.execute(
            "INSERT OR REPLACE INTO index_category_stats_v2(generation, scope, entity_type, category_path, direct_count, subtree_count) VALUES (?, ?, ?, ?, ?, ?)",
            (1, 'worldinfo', 'world_global', '科幻', 1, 1),
        )
        conn.commit()

    result = query_worldinfo_index({
        'type': 'global',
        'search': 'broken[query',
        'page': 1,
        'page_size': 20,
        'paginate': True,
        'db_path': str(db_path),
    })

    assert [item['name'] for item in result['items']] == ['broken[query] lore']
    assert result['total'] == 1
