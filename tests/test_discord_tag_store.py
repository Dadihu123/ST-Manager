"""Discord 标签 ID 映射持久化测试。"""

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.data import discord_tag_store as store


def test_discord_tag_mapping_round_trip_and_parent_isolation(tmp_path, monkeypatch):
    db_path = tmp_path / 'mapping.sqlite3'
    monkeypatch.setattr(store, 'DEFAULT_DB_PATH', str(db_path))

    assert store.save_discord_tag_mappings(
        'parent-a',
        [{'id': 'tag-1', 'name': '角色'}, {'id': 'tag-2', 'name': '工具'}],
        guild_id='guild-a',
    ) == 2
    assert store.get_discord_tag_name_map(
        'parent-a',
        ['tag-1', 'tag-2', 'tag-3'],
        guild_id='guild-a',
    ) == {'tag-1': '角色', 'tag-2': '工具'}
    assert store.get_discord_tag_name_map('parent-b', ['tag-1'], guild_id='guild-a') == {}

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            'SELECT parent_id, guild_id, tag_id, tag_name FROM discord_tag_mapping'
        ).fetchall()
    assert rows == [
        ('parent-a', 'guild-a', 'tag-1', '角色'),
        ('parent-a', 'guild-a', 'tag-2', '工具'),
    ]
