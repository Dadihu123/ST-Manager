"""Generation-scoped logical cards and their rebuildable facet counts."""

import json
import os
import stat
from urllib.parse import quote
from uuid import uuid4

from core.data.sqlite_capabilities import supports_fts5
from core.utils.filesystem import walk_directory_strict
from core.utils.search_text import split_cjk_for_index

VERSION = 2
SORT_COLUMNS = ('mtime', 'import_sort', 'name_key', 'tokens')
_CARD_COLUMNS = ('id,char_name,tags,category,creator,char_version,last_modified,'
                 'file_hash,token_count,is_favorite,card_uid')


def ensure_schema(conn):
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE name IN ('card_metadata','ui_records')")}
    if tables != {'card_metadata', 'ui_records'}:
        return
    conn.execute('''CREATE TABLE IF NOT EXISTS card_list_state (
        generation INTEGER PRIMARY KEY, root TEXT NOT NULL, format INTEGER NOT NULL,
        stats_key TEXT NOT NULL, stats_revision INTEGER NOT NULL DEFAULT 0
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS card_list_dirty (
        generation INTEGER NOT NULL, key TEXT NOT NULL, PRIMARY KEY(generation,key)
    ) WITHOUT ROWID''')
    conn.execute('''CREATE TABLE IF NOT EXISTS card_list_folders (
        generation INTEGER NOT NULL, folder TEXT NOT NULL, bundle INTEGER NOT NULL,
        PRIMARY KEY(generation,folder)
    ) WITHOUT ROWID''')
    conn.execute('''CREATE TABLE IF NOT EXISTS card_list_items (
        rowid INTEGER PRIMARY KEY, generation INTEGER NOT NULL, key TEXT NOT NULL, card_id TEXT NOT NULL,
        category TEXT NOT NULL, category_key TEXT NOT NULL, isolated_key TEXT NOT NULL,
        mtime REAL NOT NULL, imported REAL NOT NULL, import_sort REAL NOT NULL, name_key TEXT NOT NULL,
        filename_key TEXT NOT NULL, creator_key TEXT NOT NULL, note_key TEXT NOT NULL,
        tokens INTEGER NOT NULL, favorite INTEGER NOT NULL, payload TEXT NOT NULL,
        UNIQUE(generation,key), UNIQUE(generation,card_id)
    )''')
    for column in SORT_COLUMNS:
        # Reversing an index also reverses the tie breaker, which is part of the public page order.
        conn.execute(f'CREATE INDEX IF NOT EXISTS card_list_sort_{column} '
                     f'ON card_list_items(generation,{column},key)')
        conn.execute(f'CREATE INDEX IF NOT EXISTS card_list_folder_sort_{column} '
                     f'ON card_list_items(generation,category_key,{column},key)')
    conn.execute('CREATE INDEX IF NOT EXISTS card_list_favorite ON card_list_items(generation,favorite,mtime,key)')
    conn.execute('''CREATE TABLE IF NOT EXISTS card_list_tags (
        generation INTEGER NOT NULL, key TEXT NOT NULL, tag TEXT NOT NULL, tag_key TEXT NOT NULL,
        PRIMARY KEY(generation,key,tag)
    ) WITHOUT ROWID''')
    conn.execute('CREATE INDEX IF NOT EXISTS card_list_by_tag ON card_list_tags(generation,tag,key)')
    conn.execute('''CREATE TABLE IF NOT EXISTS card_list_facets (
        generation INTEGER NOT NULL, category TEXT NOT NULL, category_key TEXT NOT NULL,
        isolated_key TEXT NOT NULL, kind INTEGER NOT NULL, tag TEXT NOT NULL, count INTEGER NOT NULL,
        PRIMARY KEY(generation,category,kind,tag)
    ) WITHOUT ROWID''')
    if supports_fts5():
        conn.execute('CREATE VIRTUAL TABLE IF NOT EXISTS card_list_fts USING fts5(mix,name,filename,tags,creator)')
    for table in ('card_list_facets', 'card_list_folders'):
        for action, ref in (('INSERT', 'NEW'), ('UPDATE', 'NEW'), ('DELETE', 'OLD')):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_stats_{action} AFTER {action} ON {table}
                BEGIN UPDATE card_list_state SET stats_revision=stats_revision+1
                WHERE generation={ref}.generation; END''')
    for table, field in (('card_metadata', 'id'), ('ui_records', 'key')):
        for action, refs in (('INSERT', ('NEW',)), ('UPDATE', ('OLD', 'NEW')), ('DELETE', ('OLD',))):
            def predicate(ref):
                if table == 'card_metadata':
                    return '1'
                return (f"substr({ref}.{field},1,1) != '_' "
                        f'OR EXISTS (SELECT 1 FROM card_metadata WHERE id={ref}.{field}) '
                        f'OR EXISTS (SELECT 1 FROM card_list_items WHERE generation=card_list_state.generation '
                        f'AND key={ref}.{field})')

            statements = ' '.join(
                f'INSERT INTO card_list_dirty SELECT generation,{ref}.{field} FROM card_list_state '
                f'WHERE {predicate(ref)} ON CONFLICT DO NOTHING;'
                for ref in refs)
            # OR REPLACE on the outer SQL can override conflict clauses in trigger statements.
            conn.execute(f'CREATE TRIGGER IF NOT EXISTS card_list_{table}_{action} AFTER {action} ON {table} '
                         f'BEGIN {statements} END')


def installed(conn):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name='card_list_state'").fetchone() is not None


def root_key(root):
    return os.path.normcase(os.path.abspath(root))


def eligible(conn, generation, root):
    return installed(conn) and conn.execute(
        'SELECT 1 FROM card_list_state WHERE generation=? AND root=? AND format=?',
        (generation, root_key(root), VERSION)).fetchone() is not None


def root_changed(conn, generation, root):
    return installed(conn) and conn.execute(
        'SELECT 1 FROM card_list_state WHERE generation=? AND root!=?',
        (generation, root_key(root))).fetchone() is not None


def metadata_matches(conn, root):
    scanned_root = metadata_root(conn)
    return not scanned_root or scanned_root == root_key(root)


def metadata_root(conn):
    from core.data.index_runtime_store import SCAN_STATE_CARD_ROOT, get_scan_state

    return get_scan_state(conn, SCAN_STATE_CARD_ROOT, '')


def category_key(path):
    return '/'.join(part.strip() for part in str(path or '').replace('\\', '/').strip('/').split('/') if part.strip())


def _tag(value):
    return str(value).strip()


def _existing(conn, generation, key):
    row = conn.execute('SELECT rowid,category,payload FROM card_list_items WHERE generation=? AND key=?',
                       (generation, key)).fetchone()
    return (row[0], row[1], json.loads(row[2]).get('tags', [])) if row else None


def _facets(conn, generation, category, tags, increment):
    values = [(0, ''), *((1, tag) for tag in set(tags))]
    conn.executemany('''INSERT INTO card_list_facets VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(generation,category,kind,tag) DO UPDATE SET count=count+excluded.count''',
                     ((generation, category, category.lower(), category_key(category), kind, tag, increment)
                      for kind, tag in values))
    if increment < 0:
        conn.execute('DELETE FROM card_list_facets WHERE generation=? AND category=? AND count=0',
                     (generation, category))


def _remove(conn, generation, key):
    old = _existing(conn, generation, key)
    if old:
        rowid, category, tags = old
        if supports_fts5():
            conn.execute('DELETE FROM card_list_fts WHERE rowid=?', (rowid,))
        conn.execute('DELETE FROM card_list_items WHERE rowid=?', (rowid,))
        conn.execute('DELETE FROM card_list_tags WHERE generation=? AND key=?', (generation, key))
        _facets(conn, generation, category, tags, -1)


def _encode(card):
    return json.dumps(card, ensure_ascii=False, separators=(',', ':'))


def _put(conn, generation, key, card):
    old = _existing(conn, generation, key)
    category, tags = card['category'], card['tags']
    same_facets = old and old[1] == category and set(old[2]) == set(tags)
    if old and not same_facets:
        _facets(conn, generation, old[1], old[2], -1)
    if not same_facets:
        _facets(conn, generation, category, tags, 1)
        conn.execute('DELETE FROM card_list_tags WHERE generation=? AND key=?', (generation, key))
        conn.executemany('INSERT INTO card_list_tags VALUES (?,?,?,?)',
                         ((generation, key, tag, tag.lower()) for tag in set(tags)))
    name, filename, creator, note = (str(card[field] or '') for field in
                                    ('char_name', 'filename', 'creator', 'ui_summary'))
    cursor = conn.execute('''INSERT INTO card_list_items
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(generation,key) DO UPDATE SET
        card_id=excluded.card_id,category=excluded.category,category_key=excluded.category_key,
        isolated_key=excluded.isolated_key,mtime=excluded.mtime,imported=excluded.imported,
        import_sort=excluded.import_sort,name_key=excluded.name_key,filename_key=excluded.filename_key,
        creator_key=excluded.creator_key,note_key=excluded.note_key,tokens=excluded.tokens,
        favorite=excluded.favorite,payload=excluded.payload''',
        (old[0] if old else None, generation, key, card['id'], category, category.lower(), category_key(category),
         card['last_modified'], card['import_time'], card['import_time'] or card['last_modified'],
         name.lower(), filename.lower(), creator.lower(), note.lower(), int(card['token_count'] or 0),
         int(card['is_favorite']), _encode(card)))
    if supports_fts5():
        rowid = old[0] if old else cursor.lastrowid
        if old:
            conn.execute('DELETE FROM card_list_fts WHERE rowid=?', (rowid,))
        tag_text = ' '.join(tags)
        conn.execute('INSERT INTO card_list_fts(rowid,mix,name,filename,tags,creator) VALUES (?,?,?,?,?,?)',
                     (rowid, *(split_cjk_for_index(value) for value in (
                         ' '.join((name, filename, category, note, tag_text)), name, filename, tag_text, creator))))


def read_ui(conn, keys):
    values = {}
    for key in set(keys):
        record = conn.execute('SELECT payload_json FROM ui_records WHERE key=?', (key,)).fetchone()
        if record:
            value = json.loads(record[0])
            if isinstance(value, dict):
                values[key] = value
    return values


def _card(conn, members, bundle=''):
    from core.data.ui_store import (get_import_time, get_last_sent_to_st, get_last_sent_to_tt,
                                    get_source_update_state, get_version_remark)
    from core.utils.image import THUMBNAIL_ALGORITHM_VERSION
    from core.utils.card_identity import normalize_card_uid

    cover = members[0]
    cid, name, raw_tags, category, creator, version, mtime, file_hash, tokens, favorite, uid = cover
    ui_key = bundle or cid
    ui = read_ui(conn, (ui_key, *(r[0] for r in members)))
    record = ui.get(ui_key, {})
    note = get_version_remark(ui, bundle, cid, cid) or record if bundle else record
    category = bundle.rpartition('/')[0] if bundle else str(category or '').replace('\\', '/')
    mtime = float(mtime or 0)
    try:
        raw_tags = json.loads(raw_tags or '[]')
    except (TypeError, ValueError):
        raw_tags = []
    if isinstance(raw_tags, str):
        raw_tags = raw_tags.split(',')
    tags = [t for v in raw_tags if (t := _tag(v))] if isinstance(raw_tags, list) else []
    source = get_source_update_state(ui, ui_key)
    versions = []
    if bundle:
        for vid, _, _, _, _, vversion, vmtime, *_ in members:
            entry = dict(id=vid, filename=vid.rsplit('/', 1)[-1], last_modified=vmtime,
                         import_time=get_import_time(ui, vid, vmtime), char_version=vversion)
            remark = get_version_remark(ui, bundle, vid, cid)
            if remark:
                entry.update(ui_summary=remark.get('summary', ''), source_link=remark.get('link', ''),
                             resource_folder=remark.get('resource_folder', ''))
            versions.append(entry)
    card = dict(id=cid, filename=cid.rsplit('/', 1)[-1], char_name=name, tags=tags, category=category,
                creator=creator, char_version=version, last_modified=mtime, file_hash=file_hash,
                token_count=tokens, dir_path=cid.rpartition('/')[0], is_bundle=bool(bundle),
                versions=versions, is_favorite=bool(favorite), card_uid=normalize_card_uid(
                    (record.get('card_uid') or uid) if bundle else uid),
                ui_summary=note.get('summary', ''), source_link=note.get('link', ''),
                resource_folder=note.get('resource_folder', ''), import_time=get_import_time(ui, ui_key, mtime),
                last_sent_to_st=get_last_sent_to_st(ui, ui_key), last_sent_to_tt=get_last_sent_to_tt(ui, ui_key),
                source_update=source, source_title=source.get('source_title', ''),
                image_url=f'/cards_file/{quote(cid)}?v={mtime}',
                thumb_url=f'/api/thumbnail/{quote(cid)}?v={THUMBNAIL_ALGORITHM_VERSION}-{mtime}')
    if bundle:
        card['bundle_dir'] = bundle
    return card


def _members(conn, folder):
    prefix = folder + '/'
    return [row for row in conn.execute(
        f'SELECT {_CARD_COLUMNS} FROM card_metadata WHERE id>=? AND id<? ORDER BY last_modified DESC,id',
        (prefix, folder + '0')) if row[0].rpartition('/')[0] == folder]


def _is_bundle(root, folder):
    if not folder:
        return False
    path = os.path.join(root, folder.replace('/', os.sep), '.bundle')
    try:
        return stat.S_ISREG(os.stat(path).st_mode)
    except FileNotFoundError:
        # An inaccessible ancestor must not be treated as a removed marker.
        return False


def _update_key(conn, generation, root, key, checked_folders, processed_bundles, folders=None):
    if not key:
        return
    folder = key.rpartition('/')[0]
    for possible in (folder, key):
        if not possible or possible in checked_folders:
            continue
        checked_folders.add(possible)
        old = conn.execute('SELECT bundle FROM card_list_folders WHERE generation=? AND folder=?',
                           (generation, possible)).fetchone()
        # Card file keys are not directories. Only probe them if they are a recorded folder.
        if possible == key and not old:
            continue
        is_bundle = bool(folders.get(possible)) if folders is not None else _is_bundle(root, possible)
        if bool(old and old[0]) != is_bundle:
            conn.execute('INSERT OR REPLACE INTO card_list_folders VALUES (?,?,?)',
                         (generation, possible, int(is_bundle)))
            members = _members(conn, possible)
            _remove(conn, generation, possible)
            if is_bundle:
                for member in members:
                    _remove(conn, generation, member[0])
            else:
                for member in members:
                    _put(conn, generation, member[0], _card(conn, [member]))
    for possible in (key, folder):
        if possible and conn.execute('SELECT 1 FROM card_list_folders WHERE generation=? AND folder=? AND bundle=1',
                                     (generation, possible)).fetchone():
            if possible in processed_bundles:
                return
            processed_bundles.add(possible)
            members = _members(conn, possible)
            if members:
                _put(conn, generation, possible, _card(conn, members, possible))
            else:
                _remove(conn, generation, possible)
            return
    row = conn.execute(f'SELECT {_CARD_COLUMNS} FROM card_metadata WHERE id=?', (key,)).fetchone()
    if row:
        _put(conn, generation, key, _card(conn, [row]))
    else:
        _remove(conn, generation, key)


def drain(conn, generation, root, keys=None, *, folders=None):
    checked_folders, processed_bundles = set(), set()
    if keys is None:
        keys = [row[0] for row in conn.execute(
            'SELECT key FROM card_list_dirty WHERE generation=? ORDER BY key', (generation,))]
    for key in sorted({key for key in keys if key}):
        _update_key(conn, generation, root, key, checked_folders, processed_bundles, folders)
        conn.execute('DELETE FROM card_list_dirty WHERE generation=? AND key=?', (generation, key))


def read_folders(root):
    folders = {}
    for path, children, names in walk_directory_strict(root):
        children[:] = [name for name in children if not name.startswith('.')]
        rel = os.path.relpath(path, root).replace('\\', '/')
        if rel != '.':
            folders[rel] = int('.bundle' in names)
    return folders


def refresh_folders(conn, generation, folders):
    previous = dict(conn.execute('SELECT folder,bundle FROM card_list_folders WHERE generation=?', (generation,)))
    changed = {key for key in folders.keys() | previous.keys() if folders.get(key) != previous.get(key)}
    # Let drain observe the old bundle bit so it can convert between versions and the logical card.
    for key in changed:
        if folders.get(key) or previous.get(key):
            conn.execute('INSERT INTO card_list_dirty VALUES (?,?) ON CONFLICT DO NOTHING', (generation, key))
            if key not in previous:
                conn.execute('INSERT INTO card_list_folders VALUES (?,?,0)', (generation, key))
        elif key in folders:
            conn.execute('INSERT INTO card_list_folders VALUES (?,?,0) ON CONFLICT DO NOTHING', (generation, key))
        else:
            conn.execute('DELETE FROM card_list_folders WHERE generation=? AND folder=?', (generation, key))


def refresh_active_folders(db_path, root, folders=None):
    """Publish a complete folder read alongside the active generation's other facets."""
    from contextlib import closing

    from core.data.index_runtime_store import get_active_generation
    from core.data.local_state_repository import connect

    with closing(connect(db_path)) as conn, conn:
        if not installed(conn):
            return
        if folders is None:
            folders = read_folders(root)
        conn.execute('BEGIN IMMEDIATE')
        generation = get_active_generation(conn, 'cards')
        if eligible(conn, generation, root) and metadata_matches(conn, root):
            reconcile_folders(conn, generation, root, folders)


def reconcile_folders(conn, generation, root, folders):
    refresh_folders(conn, generation, folders)
    drain(conn, generation, root, folders=folders)
    conn.executemany('DELETE FROM card_list_folders WHERE generation=? AND folder=?',
                     ((generation, row[0]) for row in conn.execute(
                         'SELECT folder FROM card_list_folders WHERE generation=?', (generation,)).fetchall()
                      if row[0] not in folders))


def publish_folder_change(db_path, root, *, old='', new=''):
    """Publish a confirmed application mkdir, rename, or removal without a tree walk."""
    from contextlib import closing

    from core.data.index_runtime_store import get_active_generation
    from core.data.local_state_repository import connect

    if not os.path.isfile(db_path):
        return
    with closing(connect(db_path)) as conn, conn:
        generation = get_active_generation(conn, 'cards')
        if not eligible(conn, generation, root) or not metadata_matches(conn, root):
            return
        affected = conn.execute('''SELECT folder FROM card_list_folders WHERE generation=?
            AND (folder=? OR (folder>=? AND folder<?))''',
            (generation, old, old + '/', old + '0')).fetchall() if old else []
        destinations = {new + row[0][len(old):] for row in affected} | {new} if new else set()
        observed = {folder: _is_bundle(root, folder) for folder in destinations}
        conn.execute('BEGIN IMMEDIATE')
        generation = get_active_generation(conn, 'cards')
        if not eligible(conn, generation, root) or not metadata_matches(conn, root):
            return
        if old:
            for (folder,) in affected:
                conn.execute('DELETE FROM card_list_folders WHERE generation=? AND folder=?', (generation, folder))
                _remove(conn, generation, folder)
        for folder in observed:
            conn.execute('INSERT OR IGNORE INTO card_list_folders VALUES (?,?,0)', (generation, folder))
        drain(conn, generation, root, observed, folders=observed)
        while new:
            conn.execute('INSERT OR IGNORE INTO card_list_folders VALUES (?,?,0)', (generation, new))
            new = new.rpartition('/')[0]


def build(conn, generation, root):
    conn.execute('INSERT INTO card_list_state VALUES (?,?,0,?,0)', (generation, root_key(root), uuid4().hex))
    conn.commit()
    folders = read_folders(root)
    conn.executemany('INSERT INTO card_list_folders VALUES (?,?,?)',
                     ((generation, folder, bundle) for folder, bundle in folders.items()))
    conn.execute('''INSERT INTO card_list_dirty SELECT ?,id FROM card_metadata WHERE 1
                 ON CONFLICT DO NOTHING''', (generation,))
    conn.commit()
    # Re-read each key under the writer transaction; later writes re-add it until activation.
    while True:
        conn.execute('BEGIN IMMEDIATE')
        rows = conn.execute('SELECT key FROM card_list_dirty WHERE generation=? ORDER BY key LIMIT 500',
                            (generation,)).fetchall()
        checked_folders, processed_bundles = set(), set()
        for row in rows:
            _update_key(conn, generation, root, row[0], checked_folders, processed_bundles, folders)
        conn.executemany('DELETE FROM card_list_dirty WHERE generation=? AND key=?',
                         ((generation, row[0]) for row in rows))
        conn.commit()
        if not rows:
            break
    conn.execute('UPDATE card_list_state SET format=? WHERE generation=?', (VERSION, generation))
    conn.commit()


def drain_active_batch(db_path, root, *, limit=100):
    """Refresh pending keys within one short, root-checked writer transaction."""
    from contextlib import closing

    from core.data.index_runtime_store import get_active_generation
    from core.data.local_state_repository import connect
    from core.services.path_operation import observe_path_changes

    with closing(connect(db_path)) as conn, conn:
        generation = get_active_generation(conn, 'cards')
        if not eligible(conn, generation, root) or not metadata_matches(conn, root):
            return False
        keys = tuple(row[0] for row in conn.execute(
            'SELECT key FROM card_list_dirty WHERE generation=? ORDER BY key LIMIT ?', (generation, limit)))
        if not keys:
            return False
        folders = {key.rpartition('/')[0] for key in keys}
        folders.update(row[0] for row in conn.execute(
            f"SELECT folder FROM card_list_folders WHERE generation=? AND folder IN ({','.join('?' for _ in keys)})",
            (generation, *keys)))
        with observe_path_changes(*(os.path.join(root, folder) for folder in folders)) as observed:
            values = {folder: _is_bundle(root, folder) for folder in folders}
            conn.execute('BEGIN IMMEDIATE')
            with observed.pin() as stable:
                if (not stable or generation != get_active_generation(conn, 'cards')
                        or not metadata_matches(conn, root)):
                    return False
                drain(conn, generation, root, keys, folders=values)
                conn.commit()
        return len(keys) == limit


def clear(conn, generation):
    if not installed(conn):
        return
    if supports_fts5():
        conn.execute('DELETE FROM card_list_fts WHERE rowid IN (SELECT rowid FROM card_list_items WHERE generation=?)',
                     (generation,))
    for table in ('items', 'tags', 'facets', 'dirty', 'folders', 'state'):
        conn.execute(f'DELETE FROM card_list_{table} WHERE generation=?', (generation,))
