"""持久化 Discord 论坛标签 ID 到名称的映射。"""

import logging
import sqlite3
import time
from typing import Any

from core.config import DEFAULT_DB_PATH

logger = logging.getLogger(__name__)

DISCORD_TAG_MAPPING_TABLE = 'discord_tag_mapping'


def ensure_discord_tag_mapping_schema(conn: sqlite3.Connection) -> None:
    """确保 Discord 标签映射表存在。"""
    conn.execute(
        f'''
        CREATE TABLE IF NOT EXISTS {DISCORD_TAG_MAPPING_TABLE} (
            parent_id TEXT NOT NULL,
            guild_id TEXT NOT NULL DEFAULT '',
            tag_id TEXT NOT NULL,
            tag_name TEXT NOT NULL,
            updated_at REAL NOT NULL,
            PRIMARY KEY (parent_id, tag_id)
        )
        '''
    )
    conn.execute(
        f'''
        CREATE INDEX IF NOT EXISTS idx_{DISCORD_TAG_MAPPING_TABLE}_guild
        ON {DISCORD_TAG_MAPPING_TABLE} (guild_id, parent_id)
        '''
    )


def get_discord_tag_name_map(
    parent_id: str,
    tag_ids: list[str],
    *,
    guild_id: str = '',
) -> dict[str, str]:
    """读取已知标签名称；只返回非空名称。"""
    normalized_parent_id = str(parent_id or '').strip()
    normalized_ids = [str(tag_id).strip() for tag_id in tag_ids if str(tag_id).strip()]
    if not normalized_parent_id or not normalized_ids:
        return {}

    placeholders = ','.join('?' for _ in normalized_ids)
    query = (
        f'SELECT tag_id, tag_name FROM {DISCORD_TAG_MAPPING_TABLE} '
        f'WHERE parent_id = ? AND tag_id IN ({placeholders}) AND tag_name <> ?'
    )
    try:
        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            rows = conn.execute(
                query,
                [normalized_parent_id, *normalized_ids, ''],
            ).fetchall()
    except sqlite3.OperationalError as exc:
        # Older/isolated test databases may not have run init_database yet.
        logger.warning('读取 Discord 标签映射失败: %s', exc)
        return {}
    except (OSError, sqlite3.DatabaseError) as exc:
        logger.warning('读取 Discord 标签映射数据库失败: %s', exc)
        return {}

    return {str(tag_id): str(tag_name) for tag_id, tag_name in rows}


def save_discord_tag_mappings(
    parent_id: str,
    tags: list[dict[str, Any]],
    *,
    guild_id: str = '',
) -> int:
    """保存父论坛返回的标签定义，返回实际写入的数量。"""
    normalized_parent_id = str(parent_id or '').strip()
    if not normalized_parent_id:
        return 0

    rows = []
    timestamp = time.time()
    normalized_guild_id = str(guild_id or '').strip()
    for tag in tags if isinstance(tags, list) else []:
        if not isinstance(tag, dict):
            continue
        tag_id = str(tag.get('id') or '').strip()
        tag_name = str(tag.get('name') or '').strip()
        if tag_id and tag_name:
            rows.append((normalized_parent_id, normalized_guild_id, tag_id, tag_name, timestamp))

    if not rows:
        return 0

    try:
        with sqlite3.connect(DEFAULT_DB_PATH, timeout=30) as conn:
            ensure_discord_tag_mapping_schema(conn)
            conn.executemany(
                f'''
                INSERT INTO {DISCORD_TAG_MAPPING_TABLE}
                    (parent_id, guild_id, tag_id, tag_name, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(parent_id, tag_id) DO UPDATE SET
                    guild_id = excluded.guild_id,
                    tag_name = excluded.tag_name,
                    updated_at = excluded.updated_at
                ''',
                rows,
            )
            return len(rows)
    except (OSError, sqlite3.DatabaseError) as exc:
        logger.warning('保存 Discord 标签映射失败: %s', exc)
        return 0
