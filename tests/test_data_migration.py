import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import zipfile

import pytest

from core import config
from core.services.data_migration_service import DataMigrationService
from core.utils.backup_recovery import activate_pending, durable_json, confirm_pending, seal_restore


def seed(base, external=None):
    cfg = config.build_default_config()
    for key, relative in config.RUNTIME_DIR_DEFAULTS.items():
        root = base / relative
        root.mkdir(parents=True, exist_ok=True)
        (root / (key + '.txt')).write_text('原始业务内容 ' + key, encoding='utf-8')
    if external:
        external.mkdir()
        cfg['resources_dir'] = str(external)
    cfg['auth_password'] = 'source-password'
    cfg['discord_bot_token'] = 'source-token'
    durable_json(str(base / 'config.json'), cfg)
    dbroot = base / 'data/system/db'
    dbroot.mkdir(parents=True)
    resources = external or base / cfg['resources_dir']
    (resources / 'bound').mkdir()
    (resources / 'bound/attachment.txt').write_text('attachment')
    (resources / 'empty-user-folder').mkdir()
    (base / cfg['world_info_dir'] / 'book.json').write_text('{"entries":{}}')
    ui = {'a.png': {'summary': '备注', 'tags': ['标签'],
                    'resource_folder': str(resources / 'bound')},
          '_plugins_v1': {'pet': {'enabled': True, 'config': {'secret': 'opaque-secret'}}}}
    durable_json(str(dbroot / 'ui_data.json'), ui)
    conn = sqlite3.connect(dbroot / 'cards_metadata.db')
    conn.execute('PRAGMA journal_mode=WAL')
    from core.data.db_session import _initialize_database
    _initialize_database(conn, is_existing_db=True, schema_only=True)
    conn.execute('CREATE TABLE plugin_pet_private(secret TEXT)')
    conn.execute('INSERT INTO card_metadata (id,is_favorite,card_uid) VALUES (?,1,?)', ('a.png', '11111111-1111-4111-8111-111111111111'))
    conn.execute('INSERT INTO ui_data_cache (card_id,resource_folder) VALUES (?,?)', ('a.png', str(resources / 'bound')))
    scope = hashlib.sha1('global|world_info_dir:book.json'.encode()).hexdigest()
    conn.execute("INSERT INTO wi_entry_history (scope_key,entry_uid,snapshot_json,snapshot_hash,created_at) VALUES (?,?,?,'hash',1)", (scope, 'entry-uid', '{"content":"历史"}'))
    conn.execute('INSERT INTO wi_clipboard (id,content_json) VALUES (1,?)', ('{"content":"剪贴板"}',))
    conn.execute('INSERT INTO source_update_monitor_entries (card_id,pool_id) VALUES (?,?)', ('a.png', 'pool'))
    conn.execute('INSERT INTO plugin_pet_private VALUES (?)', ('opaque-db-secret',))
    conn.execute("INSERT INTO index_jobs (job_type,source_path,status,created_at) VALUES ('upsert_card',?,'pending',1)", ('stale-path',))
    conn.commit()  # 保持连接开启，数据仍在真实 WAL 中。
    plugin = base / 'data/plugins/pet'
    (plugin / 'data').mkdir(parents=True)
    (plugin / 'main.py').write_text('# plugin program')
    (plugin / 'data/private.txt').write_text('private-secret')
    durable_json(str(base / 'data/system/secrets.json'), {'key': 'target-local-secret'})
    return conn


def exported(tmp_path, external=False):
    base = tmp_path / 'source'
    base.mkdir()
    conn = seed(base, tmp_path / 'external' if external else None)
    service = DataMigrationService(str(base))
    job = service.new_job('export')
    service.export(job)
    return service, job, conn


def import_zip(service, data):
    job = service.new_job('import')
    service.receive(job, io.BytesIO(data))
    service.validate(job)
    return job


@pytest.mark.parametrize('unclean', [False, True])
@pytest.mark.parametrize('filename', ['archive.db', 'records.bin'])
def test_sqlite_attachment_committed_wal_and_suffix_files_roundtrip(tmp_path, unclean, filename):
    import subprocess
    import sys
    from contextlib import closing

    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    attachments = base / config.RUNTIME_DIR_DEFAULTS['resources_dir'] / 'bound'
    originals = {'report-wal': b'ordinary WAL suffix attachment', 'drawing-shm': b'ordinary SHM suffix attachment',
                 'program.pyc': b'opaque bytecode attachment', 'memo-journal': b'ordinary journal attachment'}
    for name, data in originals.items():
        (attachments / name).write_bytes(data)
    database = attachments / filename
    connection = None
    if unclean:
        code = '''
import os,sqlite3,sys
connection=sqlite3.connect(sys.argv[1])
connection.execute('PRAGMA journal_mode=WAL')
connection.execute('CREATE TABLE user_records (value TEXT)')
connection.execute("INSERT INTO user_records VALUES ('已提交数据')")
connection.commit()
os._exit(0)
'''
        subprocess.run([sys.executable, '-X', 'utf8', '-c', code, str(database)], check=True)
    else:
        connection = sqlite3.connect(database)
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('CREATE TABLE user_records (value TEXT)')
        connection.execute("INSERT INTO user_records VALUES ('已提交数据')")
        connection.commit()
    wal = str(database) + '-wal'
    assert os.path.getsize(wal) > 32
    original_db, original_wal = database.read_bytes(), open(wal, 'rb').read()
    # 主文件单独复制确实没有 WAL 中的表，避免只测试已 checkpoint 的数据库。
    raw_main = tmp_path / 'raw-main.db'
    raw_main.write_bytes(original_db)
    with closing(sqlite3.connect(raw_main)) as db:
        with pytest.raises(sqlite3.OperationalError, match='no such table'):
            db.execute('SELECT value FROM user_records').fetchall()
    try:
        source = DataMigrationService(str(base))
        job = source.new_job('export')
        source.export(job)
        assert database.read_bytes() == original_db and open(wal, 'rb').read() == original_wal
        with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
            name = 'resources_dir/bound/' + filename
            manifest = json.loads(archive.read('manifest.json'))
            assert next(entry for entry in manifest['files'] if entry['path'] == name)['storage'] == 'sqlite_snapshot'
            assert name + '-wal' not in archive.namelist() and name + '-shm' not in archive.namelist()
            for suffix, data in originals.items():
                assert archive.read('resources_dir/bound/' + suffix) == data
        target = tmp_path / 'target'
        restore_export(source, job, target)
        confirm_pending(str(target))
        ui = json.loads((target / 'data/system/db/ui_data.json').read_text(encoding='utf-8'))
        restored_root = ui['a.png']['resource_folder']
        for name, data in originals.items():
            assert open(os.path.join(restored_root, name), 'rb').read() == data
        with closing(sqlite3.connect(os.path.join(restored_root, filename))) as db:
            assert db.execute('SELECT value FROM user_records').fetchall() == [('已提交数据',)]
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        if connection is not None:
            connection.close()


def test_sqlite_attachment_wal_change_aborts_export(tmp_path, monkeypatch):
    from core.services import data_migration_service as migration
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    attachment = base / config.RUNTIME_DIR_DEFAULTS['resources_dir'] / 'bound/archive.db'
    connection = sqlite3.connect(attachment)
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('CREATE TABLE user_records(value TEXT)')
    connection.execute("INSERT INTO user_records VALUES ('before')")
    connection.commit()
    original_snapshot = migration.sqlite_snapshot
    changed = False
    def snapshot(source, target):
        nonlocal changed
        original_snapshot(source, target)
        if os.path.samefile(source, attachment) and not changed:
            connection.execute("INSERT INTO user_records VALUES ('after')")
            connection.commit()
            changed = True
    monkeypatch.setattr(migration, 'sqlite_snapshot', snapshot)
    try:
        service = DataMigrationService(str(base))
        job = service.new_job('export')
        with pytest.raises(ValueError, match='变更'):
            service.export(job)
        assert changed
        assert service.status(job)['state'] != 'ready'
        assert not os.path.exists(service.path(job, 'backup.zip'))
        assert connection.execute('SELECT COUNT(*) FROM user_records').fetchone()[0] == 2
    finally:
        connection.close()


def test_invalid_sqlite_attachment_aborts_without_raw_copy_fallback(tmp_path):
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    attachment = base / config.RUNTIME_DIR_DEFAULTS['resources_dir'] / 'bound/broken.db'
    attachment.write_bytes(b'SQLite format 3\x00' + b'\x00' * 256)
    service = DataMigrationService(str(base))
    job = service.new_job('export')
    with pytest.raises(sqlite3.DatabaseError):
        service.export(job)
    assert service.status(job)['state'] != 'ready'
    assert not os.path.exists(service.path(job, 'backup.zip'))


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_ambiguous_sqlite_companion_is_not_silently_excluded(tmp_path, suffix):
    from contextlib import closing
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    attachment = base / config.RUNTIME_DIR_DEFAULTS['resources_dir'] / 'bound/archive.db'
    with closing(sqlite3.connect(attachment)) as connection:
        connection.execute('CREATE TABLE user_records(value TEXT)')
        connection.commit()
    companion = str(attachment) + suffix
    content = b'ordinary attachment masquerading as SQLite companion'
    with open(companion, 'wb') as handle:
        handle.write(content)
    service = DataMigrationService(str(base))
    job = service.new_job('export')
    with pytest.raises(ValueError, match='格式不明确'):
        service.export(job)
    assert service.status(job)['state'] != 'ready'
    assert not os.path.exists(service.path(job, 'backup.zip'))
    assert open(companion, 'rb').read() == content


def test_corrupt_sqlite_attachment_with_valid_zip_hash_is_rejected(tmp_path):
    from contextlib import closing
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    attachment = base / config.RUNTIME_DIR_DEFAULTS['resources_dir'] / 'bound/archive.db'
    with closing(sqlite3.connect(attachment)) as connection:
        connection.execute('CREATE TABLE user_records(value TEXT)')
        connection.commit()
    source = DataMigrationService(str(base))
    exported_job = source.new_job('export')
    source.export(exported_job)
    with zipfile.ZipFile(source.path(exported_job, 'backup.zip')) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    name = 'resources_dir/bound/archive.db'
    corrupt = b'corrupt attachment with recalculated checksum'
    manifest = json.loads(entries['manifest.json'])
    for entry in manifest['files']:
        if entry['path'].endswith('/bound/archive.db'):
            entries[entry['path']] = corrupt
            entry.update(size=len(corrupt), sha256=hashlib.sha256(corrupt).hexdigest())
    entries['manifest.json'] = json.dumps(manifest).encode()
    original = attachment.read_bytes()
    job = source.new_job('import')
    source.receive(job, io.BytesIO(zip_bytes(entries.items())))
    with pytest.raises(ValueError, match='SQLite 附件快照损坏'):
        source.validate(job)
    assert source.status(job)['state'] != 'preview'
    assert attachment.read_bytes() == original
    assert not (base / 'data/migration/pending.json').exists()


@pytest.mark.parametrize('binding,expected', [('BOUND', 'bound'), (r'bound\Sub', 'bound/Sub')])
def test_windows_relative_bindings_follow_actual_names_in_real_zip(tmp_path, monkeypatch, binding, expected):
    import posixpath
    from contextlib import closing
    from core.services import data_migration_service as migration
    from core.services.migration_paths import MigrationPaths
    from core.services.card_resource_binding_service import resource_folder_abs_path

    base = tmp_path / 'source'
    base.mkdir()
    connection = seed(base)
    seed_valid_card(connection, base)
    resources = base / config.RUNTIME_DIR_DEFAULTS['resources_dir']
    (resources / 'bound/Sub').mkdir()
    (resources / 'bound/Sub/attachment.txt').write_text('nested attachment')
    connection.execute('UPDATE ui_data_cache SET resource_folder=?', (binding,))
    connection.commit()
    connection.close()
    ui_path = base / 'data/system/db/ui_data.json'
    ui = json.loads(ui_path.read_text(encoding='utf-8'))
    ui['a.png']['resource_folder'] = binding
    durable_json(str(ui_path), ui)
    # 持久值来自 Windows。只给路径编解码器指定 Windows 比较规则，不改变文件系统 API。
    monkeypatch.setattr(migration, 'MigrationPaths',
                        lambda *args, **kwargs: MigrationPaths(*args, **{**kwargs, 'casefold': True}))
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
        portable = json.loads(archive.read('db/ui_data.json'))
        token = portable['a.png']['resource_folder']
        logical = token.removeprefix('stm://')
        assert logical.endswith('/' + expected) and '\\' not in token
        assert archive.read(logical + '/attachment.txt')
        roots = {root: '/data/user/0/pkg/files/' + root for root in json.loads(archive.read('manifest.json'))['roots']}
        android = MigrationPaths('/data/user/0/pkg/files', roots).ui(portable)
        folder = android['a.png']['resource_folder']
        assert folder.endswith('/' + expected)
        assert posixpath.basename(folder) == expected.rsplit('/', 1)[-1]
        # POSIX 名称匹配与真实 ZIP 清单精确对应，未声称真机验证。
        assert folder == roots[logical.split('/', 1)[0]] + '/' + logical.split('/', 1)[1]
    target = tmp_path / 'target'
    restore_export(source, job, target)
    confirm_pending(str(target))
    ui = json.loads((target / 'data/system/db/ui_data.json').read_text(encoding='utf-8'))
    folder = resource_folder_abs_path(ui['a.png']['resource_folder'])
    assert os.path.isfile(os.path.join(folder, 'attachment.txt'))
    with closing(sqlite3.connect(target / 'data/system/db/cards_metadata.db')) as db:
        assert db.execute('SELECT resource_folder FROM ui_data_cache').fetchone()[0] == ui['a.png']['resource_folder']


def test_relative_binding_outside_resource_root_is_collected(tmp_path):
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    resources = base / config.RUNTIME_DIR_DEFAULTS['resources_dir']
    outside = base / 'outside-relative'
    outside.mkdir()
    (outside / 'attachment.txt').write_bytes(b'outside relative binding')
    ui_path = base / 'data/system/db/ui_data.json'
    ui = json.loads(ui_path.read_text(encoding='utf-8'))
    ui['a.png']['resource_folder'] = os.path.relpath(outside, resources).replace('\\', '/')
    durable_json(str(ui_path), ui)
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    target = tmp_path / 'target'
    prepare_export(source, job, target)
    base.rename(tmp_path / 'source-away')
    activate_pending(str(target))
    confirm_pending(str(target))
    ui = json.loads((target / 'data/system/db/ui_data.json').read_text(encoding='utf-8'))
    with open(os.path.join(ui['a.png']['resource_folder'], 'attachment.txt'), 'rb') as handle:
        assert handle.read() == b'outside relative binding'


@pytest.mark.parametrize('data_name', ['data', 'Data', 'DATA', 'dAtA'])
def test_plugin_private_directory_alias_never_enters_zip(tmp_path, data_name):
    from pathlib import Path
    from core.plugins.api import PluginAPI
    from core.plugins.manifest import PluginManifest
    from tests.plugins_test_support import base_manifest

    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    plugin = base / 'data/plugins/pet'
    private = plugin / data_name
    if data_name != 'data':
        (plugin / 'data').rename(private)
        if not (plugin / 'data').exists():
            pytest.skip('源文件系统不将此大小写变体视作私有 data 目录')
    (plugin / 'frontend/data').mkdir(parents=True)
    program = b'export function activate(api) { return null; }'
    (plugin / 'frontend/data/main.js').write_bytes(program)
    durable_json(str(plugin / 'manifest.json'), base_manifest(
        'pet', backend=None, frontend={'entry': 'frontend/data/main.js'}))
    api = PluginAPI(PluginManifest.load(str(plugin)))
    private_api = Path(api.private.dir())
    assert os.path.samefile(private_api, private)
    secret = b'synthetic-private-credential-do-not-export'
    (private_api / 'credential.json').write_bytes(secret)
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    assert source.status(job)['state'] == 'ready'
    with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert not any(name == 'plugins/pet/' + data_name or
                       name.startswith('plugins/pet/' + data_name + '/')
                       for name in archive.namelist() + manifest['directories'])
        assert not any(secret in archive.read(name) for name in archive.namelist())
        assert archive.read('plugins/pet/frontend/data/main.js') == program
    target = tmp_path / 'target'
    restore_export(source, job, target)
    confirm_pending(str(target))
    loaded = PluginManifest.load(str(target / 'data/plugins/pet'))
    assert Path(loaded.frontend_entry).read_bytes() == program
    assert not (target / 'data/plugins/pet' / data_name).exists()


@pytest.mark.parametrize('filename', ['ui_data.json', 'chat_data.json', 'cards_metadata.db'])
def test_database_filename_alias_roundtrip_and_real_startup(tmp_path, filename):
    from core.data.chat_store import normalize_chat_entry

    base = tmp_path / 'source'
    base.mkdir()
    connection = seed(base)
    seed_valid_card(connection, base)
    connection.close()
    dbroot = base / 'data/system/db'
    chat = {'session.jsonl': normalize_chat_entry({'favorite': True, 'notes': '聊天备注'})}
    durable_json(str(dbroot / 'chat_data.json'), chat)
    (dbroot / filename).rename(dbroot / filename.upper())
    if not (dbroot / filename).exists():
        pytest.skip('源文件系统不将此大小写变体视作内置数据库文件')
    assert filename.upper() in os.listdir(dbroot)
    isolated_python(base, '''
from flask import Flask
from core.data.ui_store import load_ui_data
from core.data.chat_store import load_chat_data
from core.data.db_session import get_db
assert load_ui_data()['a.png']['summary']=='备注'
assert load_chat_data()['session.jsonl']['notes']=='聊天备注'
with Flask(__name__).app_context():
    db=get_db()
    assert db.execute("SELECT is_favorite FROM card_metadata WHERE id='a.png'").fetchone()[0]==1
    db.close()
''')
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    # 保持真实 WAL 连接开启，名称规范化不能绕过一致快照。
    wal = sqlite3.connect(dbroot / 'cards_metadata.db')
    try:
        wal.execute('PRAGMA journal_mode=WAL')
        wal.execute("UPDATE card_metadata SET char_name='WAL 中已提交的名称' WHERE id='a.png'")
        wal.commit()
        assert os.path.getsize(str(dbroot / 'cards_metadata.db') + '-wal') > 32
        source.export(job)
        with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
            snapshot = tmp_path / 'snapshot.db'
            snapshot.write_bytes(archive.read('db/cards_metadata.db'))
        check = sqlite3.connect(snapshot)
        try:
            assert check.execute("SELECT char_name FROM card_metadata WHERE id='a.png'").fetchone()[0] == 'WAL 中已提交的名称'
        finally:
            check.close()
    finally:
        wal.close()
    with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
        assert json.loads(archive.read('db/ui_data.json'))['a.png']['summary'] == '备注'
        assert json.loads(archive.read('db/chat_data.json')) == chat
        assert 'db/cards_metadata.db' in archive.namelist()
        assert 'db/' + filename.upper() not in archive.namelist()
        for entry in json.loads(archive.read('manifest.json'))['files']:
            raw = archive.read(entry['path'])
            assert len(raw) == entry['size']
            assert hashlib.sha256(raw).hexdigest() == entry['sha256']
    target = tmp_path / 'target'
    restored, imported = prepare_export(source, job, target)
    base.rename(tmp_path / 'source-away')
    isolated_startup(target, '''
from core.data.chat_store import load_chat_data
assert ui['a.png']['summary']=='备注'
assert ui['a.png']['tags']==['标签']
assert load_chat_data()['session.jsonl']['notes']=='聊天备注'
assert load_chat_data()['session.jsonl']['favorite'] is True
assert ctx.cache.id_map['a.png']['is_favorite']
assert ctx.cache.id_map['a.png']['ui_summary']=='备注'
assert os.path.isfile(os.path.join(ctx.cache.id_map['a.png']['resource_folder'],'attachment.txt'))
''')
    assert restored.status(imported)['state'] == 'complete'
    assert set(os.listdir(target / 'data/system/db')) >= {
        'ui_data.json', 'chat_data.json', 'cards_metadata.db'}


@pytest.mark.parametrize('slot', ['plugins', 'db'])
def test_source_name_lookup_access_error_aborts_export(tmp_path, monkeypatch, slot):
    from core.services import data_migration_service as migration

    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    canonical = (base / 'data/plugins/pet/data' if slot == 'plugins'
                 else base / 'data/system/db/ui_data.json')
    alias = canonical.with_name(canonical.name.upper())
    canonical.rename(alias)
    if not canonical.exists():
        pytest.skip('源文件系统不支持此大小写别名')
    service = DataMigrationService(str(base))
    job = service.new_job('export')
    original_stat = os.stat

    def denied(path, *args, **kwargs):
        if os.path.normpath(os.fspath(path)) == str(canonical):
            raise PermissionError('合成的名称查询访问失败')
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(migration.os, 'stat', denied)
    with pytest.raises(PermissionError, match='名称查询访问失败'):
        service.export(job)
    assert service.status(job)['state'] != 'ready'
    assert not os.path.exists(service.path(job, 'backup.zip'))


@pytest.mark.parametrize('data_name', ['data', 'Data'])
def test_plugin_nested_data_program_survives_manifest_loading(tmp_path, data_name):
    from core.plugins.manifest import PluginManifest
    from tests.plugins_test_support import base_manifest
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    plugin = base / 'data/plugins/nested-program'
    program_dir = plugin / 'frontend' / data_name
    program_dir.mkdir(parents=True)
    program = b'export function activate(api) { return null; }'
    (program_dir / 'main.js').write_bytes(program)
    (program_dir / 'support.pyc').write_bytes(b'opaque compiled program')
    (plugin / 'data').mkdir()
    (plugin / 'data/private.json').write_text('{"secret":"private-value"}')
    (plugin / 'frontend/__pycache__').mkdir()
    (plugin / 'frontend/__pycache__/runtime.pyc').write_bytes(b'rebuildable')
    entry = 'frontend/' + data_name + '/main.js'
    manifest = base_manifest('nested-program', backend=None, frontend={'entry': entry})
    durable_json(str(plugin / 'manifest.json'), manifest)
    parsed = PluginManifest.load(str(plugin))
    assert parsed.frontend_entry_rel == entry
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
        assert archive.read('plugins/nested-program/' + entry) == program
        assert archive.read('plugins/nested-program/frontend/' + data_name + '/support.pyc') == b'opaque compiled program'
        assert not any('plugins/nested-program/data/' in name or '__pycache__' in name for name in archive.namelist())
    target = tmp_path / 'target'
    restore_export(source, job, target)
    confirm_pending(str(target))
    loaded = PluginManifest.load(str(target / 'data/plugins/nested-program'))
    assert open(loaded.frontend_entry, 'rb').read() == program
    assert loaded.frontend_entry_rel == parsed.frontend_entry_rel


def zip_bytes(entries):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return data.getvalue()


def test_real_zip_wal_roundtrip_external_associations(tmp_path):
    source, job, conn = exported(tmp_path, external=True)
    path = source.path(job, 'backup.zip')
    with zipfile.ZipFile(path) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['version'] == 3 and manifest['complete']
        assert archive.read('resources_dir/bound/attachment.txt') == b'attachment'
        assert 'plugins/pet/main.py' in archive.namelist()
        assert not any('private.txt' in n or '-wal' in n for n in archive.namelist())
        for item in manifest['files']:
            raw = archive.read(item['path'])
            assert len(raw) == item['size']
            assert hashlib.sha256(raw).hexdigest() == item['sha256']
        assert b'source-password' not in archive.read('settings.json')
        assert b'source-token' not in archive.read('settings.json')
        assert b'opaque-secret' not in archive.read('db/ui_data.json')
        assert b'opaque-db-secret' not in archive.read('db/cards_metadata.db')
        assert str(tmp_path).replace('\\', '/').encode() not in archive.read('db/ui_data.json')
    conn.close()
    target = tmp_path / 'target'
    target.mkdir()
    target_conn = seed(target)
    target_conn.close()
    cfg = json.loads((target / 'config.json').read_text(encoding='utf-8'))
    cfg['auth_password'] = 'target-password'
    durable_json(str(target / 'config.json'), cfg)
    restored = DataMigrationService(str(target))
    imported = import_zip(restored, open(path, 'rb').read())
    assert restored.status(imported)['state'] == 'preview'
    old_cfg = (target / 'config.json').read_bytes()
    restored.update(imported, state='restoring')
    restored.prepare_restore(imported)
    assert (target / 'config.json').read_bytes() == old_cfg
    activate_pending(str(target))
    confirm_pending(str(target))
    cfg = json.loads((target / 'config.json').read_text(encoding='utf-8'))
    assert cfg['auth_password'] == 'target-password'
    assert str(tmp_path / 'external') not in cfg['resources_dir']
    ui = json.loads((target / 'data/system/db/ui_data.json').read_text(encoding='utf-8'))
    assert ui['a.png']['summary'] == '备注'
    assert ui['a.png']['tags'] == ['标签']
    assert os.path.isfile(os.path.join(ui['a.png']['resource_folder'], 'attachment.txt'))
    assert os.path.isdir(os.path.join(cfg['resources_dir'], 'empty-user-folder'))
    assert ui['_plugins_v1']['pet']['enabled'] is False
    with sqlite3.connect(target / 'data/system/db/cards_metadata.db') as db:
        assert db.execute('SELECT id,is_favorite,card_uid FROM card_metadata').fetchone() == ('a.png', 1, '11111111-1111-4111-8111-111111111111')
        assert db.execute('SELECT card_id FROM source_update_monitor_entries').fetchone()[0] == 'a.png'
        assert db.execute('SELECT content_json FROM wi_clipboard').fetchone()[0] == '{"content":"剪贴板"}'
        scope = hashlib.sha1('global|world_info_dir:book.json'.encode()).hexdigest()
        assert db.execute('SELECT scope_key FROM wi_entry_history').fetchone()[0] == scope
        assert db.execute('SELECT resource_folder FROM ui_data_cache').fetchone()[0] == ui['a.png']['resource_folder']
        assert db.execute('SELECT COUNT(*) FROM index_jobs').fetchone()[0] == 0
    assert json.loads((target / 'data/system/secrets.json').read_text())['key'] == 'target-local-secret'
    assert os.path.isfile(restored.path(imported, 'protection/config.json'))


@pytest.mark.parametrize('name', ['../evil', '/abs', 'C:/abs', 'x\\y', 'a/../b', 'CON.txt', 'a./b'])
def test_malicious_paths_do_not_touch_current_library(tmp_path, name):
    service = DataMigrationService(str(tmp_path))
    job = service.new_job('import')
    service.receive(job, io.BytesIO(zip_bytes([(name, 'evil')])))
    with pytest.raises(ValueError):
        service.validate(job)
    assert not (tmp_path / 'config.json').exists()
    assert not (tmp_path / 'evil').exists()


@pytest.mark.parametrize('kind', ['file', 'directory'])
def test_overlong_utf8_component_real_zip_rejected_before_extract(tmp_path, kind):
    # ZIP 可以描述 Windows 可用但 Android NAME_MAX=255 无法创建的名字。
    name = '汉' * 90 + ('.txt' if kind == 'file' else '/item.txt')
    service = DataMigrationService(str(tmp_path))
    job = service.new_job('import')
    service.receive(job, io.BytesIO(zip_bytes([('resources_dir/' + name, b'attachment')])))
    with pytest.raises(ValueError, match='255.*UTF-8'):
        service.validate(job)
    assert not os.path.exists(os.path.join(service.path(job, 'restore'), 'resources_dir'))
    assert service.status(job)['state'] != 'preview'


@pytest.mark.skipif(os.name != 'nt', reason='需 Windows 创建超过 Android NAME_MAX 的真实文件名')
@pytest.mark.parametrize('kind', ['file', 'empty-directory'])
def test_windows_overlong_utf8_component_fails_real_export(tmp_path, kind):
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    root = base / config.RUNTIME_DIR_DEFAULTS['resources_dir']
    path = root / ('汉' * 90 + ('.txt' if kind == 'file' else ''))
    if kind == 'file':
        path.write_bytes(b'attachment')
    else:
        path.mkdir()
    service = DataMigrationService(str(base))
    job = service.new_job('export')
    with pytest.raises(ValueError, match='255.*UTF-8'):
        service.export(job)
    assert not os.path.exists(service.path(job, 'backup.zip'))
    assert service.status(job)['state'] != 'ready'


def test_utf8_component_at_255_byte_boundary_roundtrip(tmp_path):
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    filename = '汉' * 83 + 'ab.txt'
    assert len(filename.encode('utf-8')) == 255
    original = b'boundary attachment'
    (base / config.RUNTIME_DIR_DEFAULTS['resources_dir'] / filename).write_bytes(original)
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    restored, imported = restore_export(source, job, tmp_path / 'target')
    confirm_pending(restored.base)
    cfg = restored._config()
    assert open(os.path.join(cfg['resources_dir'], filename), 'rb').read() == original


@pytest.mark.parametrize('kind', ['file', 'directory'])
def test_long_full_utf8_path_rejected_before_extract(tmp_path, kind):
    relative = '/'.join(['汉' * 80] * 18)
    name = 'resources_dir/' + relative + ('/item.txt' if kind == 'file' else '')
    assert len(name.encode('utf-8')) > 4095
    service = DataMigrationService(str(tmp_path))
    imported = service.new_job('import')
    service.receive(imported, io.BytesIO(zip_bytes([(name, b'attachment')])))
    with pytest.raises(ValueError, match='完整相对路径.*3072'):
        service.validate(imported)
    assert not os.path.exists(service.path(imported, 'restore/resources_dir'))


@pytest.mark.skipif(os.name != 'nt', reason='需 Windows 创建 Android 无法落盘的真实完整路径')
@pytest.mark.parametrize('empty', [False, True])
def test_windows_long_full_path_fails_real_export(tmp_path, empty):
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    folder = base / config.RUNTIME_DIR_DEFAULTS['resources_dir']
    for _ in range(18):
        folder /= '汉' * 80
    folder.mkdir(parents=True)
    if not empty:
        (folder / 'item.txt').write_bytes(b'attachment')
    service = DataMigrationService(str(base))
    job = service.new_job('export')
    with pytest.raises(ValueError, match='完整相对路径.*3072'):
        service.export(job)
    assert not os.path.exists(service.path(job, 'backup.zip'))
    assert service.status(job)['state'] != 'ready'


def test_portable_path_boundary_real_zip_roundtrip(tmp_path):
    from core.services import data_migration_service as migration
    source, _, connection = exported(tmp_path, external=True)
    connection.close()
    parts = ['汉' * 80] * 12
    prefix = 'resources_dir/' + '/'.join(parts) + '/'
    leaf = 'x' * (migration.MAX_ARCHIVE_PATH_BYTES - len(prefix.encode('utf-8')) - 4) + '.txt'
    assert len((prefix + leaf).encode('utf-8')) == migration.MAX_ARCHIVE_PATH_BYTES
    folder = os.path.join(source.base, source._config()['resources_dir'], *parts)
    os.makedirs(folder)
    with open(os.path.join(folder, leaf), 'wb') as handle:
        handle.write(b'portable boundary')
    job = source.new_job('export')
    source.export(job)
    long_target = tmp_path / 'long-target'
    for _ in range(5):
        long_target /= '根' * 80
    long_target.mkdir(parents=True)
    rejected = DataMigrationService(str(long_target))
    rejected_job = rejected.new_job('import')
    rejected.receive(rejected_job, io.BytesIO(open(source.path(job, 'backup.zip'), 'rb').read()))
    with pytest.raises(ValueError, match='目标完整路径'):
        rejected.validate(rejected_job)
    assert os.listdir(rejected.path(rejected_job, 'restore')) == []
    restored, imported = restore_export(source, job, tmp_path / 'target')
    confirm_pending(restored.base)
    path = os.path.join(restored._config()['resources_dir'], *parts, leaf)
    assert open(path, 'rb').read() == b'portable boundary'


def test_actual_target_prefix_length_is_checked_before_extract(tmp_path, monkeypatch):
    from core.services import data_migration_service as migration
    source, job, connection = exported(tmp_path)
    connection.close()
    data = open(source.path(job, 'backup.zip'), 'rb').read()
    target = tmp_path / 'target'
    target.mkdir()
    restored = DataMigrationService(str(target))
    imported = restored.new_job('import')
    # 缩小实际绝对路径预算，验证目标前缀确实参与检查，而非只检查 ZIP 相对路径。
    root_size = len(restored.path(imported, 'restore').encode('utf-8'))
    monkeypatch.setattr(migration, 'MAX_ABSOLUTE_PATH_BYTES', root_size + 12)
    restored.receive(imported, io.BytesIO(data))
    with pytest.raises(ValueError, match='目标完整路径'):
        restored.validate(imported)
    assert os.listdir(restored.path(imported, 'restore')) == []
    assert not os.path.exists(target / 'config.json')


@pytest.mark.parametrize('change', [
    'book', 'same-size-book', 'config', 'database', 'extra-file', 'missing-file',
    'extra-directory', 'missing-directory', 'seal', 'missing-seal', 'legacy-pending', 'moves', 'directory-link',
])
def test_final_pending_content_is_verified_before_any_activation_move(tmp_path, change):
    source, exported_job, connection = exported(tmp_path)
    connection.close()
    target = tmp_path / 'target'
    target.mkdir()
    seed(target).close()
    restored = DataMigrationService(str(target))
    imported = import_zip(restored, open(source.path(exported_job, 'backup.zip'), 'rb').read())
    restored.update(imported, state='restoring')
    restored.prepare_restore(imported)
    journal = target / 'data/migration/pending.json'
    plan = json.loads(journal.read_text(encoding='utf-8'))
    assert plan['seal_sha256']
    book = restored.path(imported, 'library/world_info_dir/book.json')
    before = {name: (target / name).read_bytes() for name in (
        'config.json', 'data/system/db/cards_metadata.db', 'data/system/db/ui_data.json')}
    if change == 'book':
        durable_json(book, {'entries': {}, 'changed': True})
    elif change == 'same-size-book':
        info = os.stat(book)
        raw = open(book, 'rb').read()
        with open(book, 'wb') as handle:
            handle.write(raw.replace(b'entries', b'CHANGED'))
        os.utime(book, ns=(info.st_atime_ns, info.st_mtime_ns))
    elif change == 'config':
        durable_json(restored.path(imported, 'restore/config.json'), {'changed': True})
    elif change == 'database':
        from contextlib import closing
        with closing(sqlite3.connect(restored.path(imported, 'restore/db/cards_metadata.db'))) as db:
            db.execute('UPDATE card_metadata SET is_favorite=0')
            db.commit()
    elif change == 'extra-file':
        durable_json(restored.path(imported, 'restore/plugins/injected.json'), {'changed': True})
    elif change == 'missing-file':
        os.remove(book)
    elif change == 'extra-directory':
        os.mkdir(restored.path(imported, 'library/world_info_dir/injected'))
    elif change == 'missing-directory':
        os.rmdir(restored.path(imported, 'restore/resources_dir/empty-user-folder'))
    elif change == 'seal':
        durable_json(os.path.join(target, plan['seal']), {'changed': True})
    elif change == 'missing-seal':
        os.remove(os.path.join(target, plan['seal']))
    elif change == 'legacy-pending':
        plan.pop('seal')
        plan.pop('seal_sha256')
        durable_json(str(journal), plan)
    elif change == 'moves':
        plan['moves'] = plan['moves'][1:]
        durable_json(str(journal), plan)
    elif change == 'directory-link':
        directory_link(restored.path(imported, 'library/world_info_dir/linked'), tmp_path / 'source')
    activate_pending(str(target))
    assert not journal.exists()
    state = json.loads((target / 'data/migration/last-restore.json').read_text(encoding='utf-8'))
    assert state['state'] == 'rolled_back'
    assert '启动前校验失败' in state['error']
    assert restored.status(imported)['state'] == 'rolled_back'
    assert not os.path.exists(restored.path(imported, 'protection'))
    for name, raw in before.items():
        assert (target / name).read_bytes() == raw


@pytest.mark.parametrize('area', ['restore/world_info_dir/book.json', 'library/world_info_dir/book.json'])
def test_legacy_snapshot_restore_cannot_write_migration_data(tmp_path, monkeypatch, area):
    from flask import Flask
    from core.api.v1 import system
    source, exported_job, connection = exported(tmp_path)
    connection.close()
    target = tmp_path / 'target'
    target.mkdir()
    restored = DataMigrationService(str(target))
    imported = import_zip(restored, open(source.path(exported_job, 'backup.zip'), 'rb').read())
    if area.startswith('library'):
        restored.update(imported, state='restoring')
        restored.prepare_restore(imported)
    destination = restored.path(imported, area)
    before = open(destination, 'rb').read()
    snapshot = tmp_path / 'snapshot.json'
    durable_json(str(snapshot), {'entries': {}, 'injected': True})
    monkeypatch.setattr(system, 'BASE_DIR', str(target))
    monkeypatch.setattr(system, 'load_config', restored._config)
    app = Flask(__name__)
    app.register_blueprint(system.bp)
    result = app.test_client().post('/api/restore_backup', json={
        'backup_path': str(snapshot), 'type': 'lorebook', 'target_id': 'global::book',
        'target_file_path': destination})
    assert result.get_json()['success'] is False
    assert '迁移' in result.get_json()['msg']
    assert open(destination, 'rb').read() == before


def test_confirmed_restore_blocks_business_requests_at_shared_entry(tmp_path, monkeypatch):
    import core
    from core.api.v1 import migration
    from flask import jsonify
    source, job, connection = exported(tmp_path)
    connection.close()
    target = tmp_path / 'target'
    restored, imported = prepare_export(source, job, target)
    monkeypatch.setattr(core, 'BASE_DIR', str(target))
    monkeypatch.setattr(core.plugin_registry, 'load_all', lambda app: None)
    monkeypatch.setattr(core, 'init_auth', lambda app: None)
    monkeypatch.setattr(migration, '_service', restored)
    app = core.create_app()
    touched = []
    @app.post('/plugins/test/write')
    def plugin_write():
        touched.append('write')
        return jsonify(success=True)
    client = app.test_client()
    for path in ('/api/restore_backup', '/api/scripts/save', '/api/save_settings', '/plugins/test/write'):
        result = client.post(path, json={})
        assert result.status_code == 409, (path, result.get_json())
        assert result.get_json()['error'] == 'restore_pending'
    assert not touched
    assert client.get(f'/api/migration/jobs/{imported}').get_json()['state'] == 'restart_required'
    assert client.post('/api/migration/legacy-ui', json={}).status_code == 400
    # 验证事务结束后统一门禁释放。
    activate_pending(str(target))
    confirm_pending(str(target))
    assert client.post('/plugins/test/write', json={}).get_json()['success'] is True
    assert touched == ['write']


def test_real_startup_rejects_modified_pending_library_and_uses_original_library(tmp_path):
    base = tmp_path / 'source'
    base.mkdir()
    connection = seed(base)
    seed_valid_card(connection, base)
    connection.close()
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    target = tmp_path / 'target'
    target.mkdir()
    connection = seed(target)
    seed_valid_card(connection, target)
    connection.close()
    restored = DataMigrationService(str(target))
    imported = import_zip(restored, open(source.path(job, 'backup.zip'), 'rb').read())
    restored.update(imported, state='restoring')
    restored.prepare_restore(imported)
    durable_json(restored.path(imported, 'library/world_info_dir/book.json'), {'entries': {}, 'changed': True})
    old_config = (target / 'config.json').read_bytes()
    base.rename(tmp_path / 'source-away')
    isolated_python(target, '''
import json,os,core
from core.context import ctx
from core.config import load_config
for name in ('start_background_index_upgrade','start_background_scanner',
             'start_index_job_worker','start_monitor_scheduler'):
    setattr(core,name,lambda *args,**kwargs: None)
core.plugin_jobs.start_plugin_job_worker=lambda: None
from core.plugins import hooks
hooks.emit=lambda *args,**kwargs: None
core.init_services()
assert ctx.init_status['status']=='ready',ctx.init_status
base=os.environ['STM_DATA_ROOT']
state=json.load(open(os.path.join(base,'data/migration/last-restore.json'),encoding='utf-8'))
assert state['state']=='rolled_back',state
assert '启动前校验失败' in state['error']
cfg=load_config()
book=os.path.join(base,cfg['world_info_dir'],'book.json')
assert json.load(open(book,encoding='utf-8'))=={'entries':{}}
assert ctx.cache.id_map['a.png']['is_favorite']
assert ctx.cache.id_map['a.png']['ui_summary']=='备注'
assert ctx.cache.id_map['a.png']['tags']==['标签']
''')
    assert (target / 'config.json').read_bytes() == old_config


@pytest.mark.parametrize('change', [
    'content', 'same-size-content', 'missing-file', 'extra-file', 'missing-directory',
    'extra-directory', 'settings', 'database', 'manifest', 'manifest-and-content',
])
def test_modified_preview_staging_aborts_before_any_restore_write(tmp_path, change):
    source, exported_job, connection = exported(tmp_path)
    connection.close()
    target = tmp_path / 'target'
    target.mkdir()
    seed(target).close()
    restored = DataMigrationService(str(target))
    imported = import_zip(restored, open(source.path(exported_job, 'backup.zip'), 'rb').read())
    stage = restored.path(imported, 'restore')
    book = os.path.join(stage, 'world_info_dir', 'book.json')
    before = {name: (target / name).read_bytes() for name in (
        'config.json', 'data/system/db/cards_metadata.db', 'data/system/db/ui_data.json')}
    if change in ('content', 'manifest-and-content'):
        durable_json(book, {'entries': {}, 'changed': True})
    elif change == 'same-size-content':
        info = os.stat(book)
        with open(book, 'rb') as handle:
            raw = handle.read()
        with open(book, 'wb') as handle:
            handle.write(raw.replace(b'entries', b'CHANGED'))
        os.utime(book, ns=(info.st_atime_ns, info.st_mtime_ns))
    elif change == 'missing-file':
        os.remove(book)
    elif change == 'extra-file':
        durable_json(os.path.join(stage, 'world_info_dir', 'injected.json'), {'entries': {}})
    elif change == 'missing-directory':
        os.rmdir(os.path.join(stage, 'resources_dir', 'empty-user-folder'))
    elif change == 'extra-directory':
        os.mkdir(os.path.join(stage, 'world_info_dir', 'injected'))
    elif change == 'settings':
        durable_json(os.path.join(stage, 'settings.json'), {'theme': 'changed'})
    elif change == 'database':
        from contextlib import closing
        with closing(sqlite3.connect(os.path.join(stage, 'db', 'cards_metadata.db'))) as db:
            db.execute('UPDATE card_metadata SET is_favorite=0')
            db.commit()
    if change in ('manifest', 'manifest-and-content'):
        path = restored.path(imported, 'manifest.json')
        with open(path, encoding='utf-8') as handle:
            manifest = json.load(handle)
        manifest['created_at'] = 'modified after preview'
        if change == 'manifest-and-content':
            raw = open(book, 'rb').read()
            for entry in manifest['files']:
                if entry['path'] == 'world_info_dir/book.json':
                    entry.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        durable_json(path, manifest)
    restored.update(imported, state='restoring')
    with pytest.raises(ValueError, match='重新选择备份并预览'):
        restored.prepare_restore(imported)
    assert restored.status(imported)['state'] == 'failed'
    assert not os.path.exists(os.path.join(restored.root, 'pending.json'))
    assert not os.path.exists(restored.path(imported, 'library'))
    assert not os.path.exists(restored.path(imported, 'protection'))
    for name, raw in before.items():
        assert (target / name).read_bytes() == raw


def directory_link(link, target):
    if os.name == 'nt':
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


@pytest.mark.parametrize('name_bytes', [253, 254, 255])
def test_restored_long_script_name_can_be_edited_through_real_api(tmp_path, name_bytes):
    base = tmp_path / 'source'
    base.mkdir()
    connection = seed(base)
    seed_valid_card(connection, base)
    connection.close()
    stem_bytes = name_bytes - len('.json')
    filename = '脚' * (stem_bytes // 3) + 'a' * (stem_bytes % 3) + '.json'
    assert len(filename.encode('utf-8')) == name_bytes
    # 源端使用实际脚本保存接口创建，导出恢复继续使用真实 ZIP 和启动流程。
    isolated_python(base, '''
import json,os,sys
from flask import Flask
from core.config import load_config,BASE_DIR
from core.api.v1 import resources
app=Flask(__name__)
app.register_blueprint(resources.bp)
path=os.path.join(BASE_DIR,load_config()['scripts_dir'],sys.argv[1])
payload={'type':'script','name':'迁移前脚本','content':'console.log("source");'}
result=app.test_client().post('/api/scripts/save',json={'file_path':path,'content':payload}).get_json()
assert result['success'],result
assert json.load(open(path,encoding='utf-8'))==payload
''', filename)
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
        raw = archive.read('scripts_dir/' + filename)
        assert json.loads(raw)['name'] == '迁移前脚本'
        entry = next(row for row in json.loads(archive.read('manifest.json'))['files']
                     if row['path'] == 'scripts_dir/' + filename)
        assert entry['sha256'] == hashlib.sha256(raw).hexdigest()
    target = tmp_path / 'target'
    restored, imported = prepare_export(source, job, target)
    base.rename(tmp_path / 'source-away')
    isolated_startup(target, '''
import builtins,errno
from flask import Flask
from core.api.v1 import resources
path=os.path.join(cfg['scripts_dir'],FILENAME)
assert json.load(open(path,encoding='utf-8'))['name']=='迁移前脚本'
# Windows 隔离测试在真实 open/os.open 上施加 Android 名称限制，不声称为真机测试。
original_open=builtins.open
original_os_open=os.open
temporary_names=[]
def check(path):
    if not isinstance(path,int) and len(os.path.basename(os.fsdecode(path)).encode('utf-8'))>255:
        raise OSError(errno.ENAMETOOLONG,'File name too long',os.fspath(path))
def checked_open(path,*args,**kwargs):
    check(path)
    return original_open(path,*args,**kwargs)
def checked_os_open(path,*args,**kwargs):
    check(path)
    if os.fspath(path).endswith('.tmp'):
        temporary_names.append(os.path.abspath(path))
    return original_os_open(path,*args,**kwargs)
builtins.open=checked_open
os.open=checked_os_open
try:
    app=Flask(__name__)
    app.register_blueprint(resources.bp)
    payload={'type':'script','name':'恢复后编辑','content':'console.log("edited");'}
    result=app.test_client().post('/api/scripts/save',json={'file_path':path,'content':payload}).get_json()
    assert result['success'],result
    assert json.load(open(path,encoding='utf-8'))==payload
    assert temporary_names
    assert all(os.path.samefile(os.path.dirname(name),os.path.dirname(path)) for name in temporary_names)
    assert not any(os.path.exists(name) for name in temporary_names)
finally:
    builtins.open=original_open
    os.open=original_os_open
assert ctx.cache.id_map['a.png']['is_favorite']
assert ctx.cache.id_map['a.png']['ui_summary']=='备注'
assert ctx.cache.id_map['a.png']['tags']==['标签']
'''.replace('FILENAME', repr(filename)))
    assert restored.status(imported)['state'] == 'complete'


def test_cold_start_restored_library_is_writable_through_data_root_alias(tmp_path):
    base = tmp_path / 'source'
    base.mkdir()
    connection = seed(base, tmp_path / 'external-resources')
    seed_valid_card(connection, base)
    connection.close()
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    native = tmp_path / 'data-data-files'
    native.mkdir()
    alias = tmp_path / 'data-user-0-files'
    directory_link(alias, native)
    restored = DataMigrationService(str(alias))
    imported = import_zip(restored, open(source.path(job, 'backup.zip'), 'rb').read())
    restored.update(imported, state='restoring')
    restored.prepare_restore(imported)
    base.rename(tmp_path / 'source-away')
    isolated_startup(alias, '''
import io
from flask import Flask
from core.api.v1 import resources
from core.utils.paths import require_business_write_path
app=Flask(__name__)
app.register_blueprint(resources.bp)
client=app.test_client()
assert not os.path.exists(os.path.join(root,'data/migration/pending.json'))
assert os.path.normpath(os.path.realpath(cfg['scripts_dir']))!=os.path.normpath(cfg['scripts_dir'])
for dirname,filename,payload in (
    ('scripts_dir','short.json',{'type':'script','name':'短脚本','content':'console.log(1);'}),
    ('scripts_dir','脚'*83+'a.json',{'type':'script','name':'长脚本','content':'console.log(2);'}),
    ('regex_dir','regex.json',{'findRegex':'/edited/'})):
    path=os.path.join(cfg[dirname],filename)
    result=client.post('/api/scripts/save',json={'file_path':path,'content':payload}).get_json()
    assert result['success'],result
    assert json.load(open(path,encoding='utf-8'))==payload
    require_business_write_path(os.path.realpath(path),root,cfg)
folder=ui['a.png']['resource_folder']
assert '/library/' in folder.replace(chr(92),'/'),folder
uploaded=client.post('/api/upload_card_resource',data={
    'card_id':'a.png','file':(io.BytesIO(b'alias-upload'),'new-attachment.txt')}).get_json()
assert uploaded['success'],uploaded
assert open(os.path.join(folder,'new-attachment.txt'),'rb').read()==b'alias-upload'
assert open(os.path.join(folder,'attachment.txt'),'rb').read()==b'attachment'
job=JOB
for area in ('restore','protection','snapshot'):
    path=os.path.join(root,'data/migration',job,area,'forbidden.json')
    os.makedirs(os.path.dirname(path),exist_ok=True)
    with open(path,'w',encoding='utf-8') as handle:
        handle.write('{}')
    denied=client.post('/api/scripts/save',json={'file_path':path,'content':{'changed':True}}).get_json()
    assert denied['success'] is False,denied
    assert '迁移' in denied['msg'],denied
    assert open(path,encoding='utf-8').read()=='{}'
assert ctx.cache.id_map['a.png']['is_favorite']
assert ctx.cache.id_map['a.png']['ui_summary']=='备注'
assert ctx.cache.id_map['a.png']['tags']==['标签']
'''.replace('JOB', repr(imported)))
    assert restored.status(imported)['state'] == 'complete'


@pytest.mark.parametrize('area', ['restore', 'restore/world_info_dir'])
def test_preview_directory_replaced_with_link_aborts_restore(tmp_path, area):
    source, exported_job, connection = exported(tmp_path)
    connection.close()
    imported = import_zip(source, open(source.path(exported_job, 'backup.zip'), 'rb').read())
    path = source.path(imported, area)
    relocated = tmp_path / 'relocated'
    os.rename(path, relocated)
    directory_link(path, relocated)
    before = open(os.path.join(source.base, 'config.json'), 'rb').read()
    source.update(imported, state='restoring')
    with pytest.raises(ValueError, match='重新选择备份并预览'):
        source.prepare_restore(imported)
    assert source.status(imported)['state'] == 'failed'
    assert not os.path.exists(os.path.join(source.root, 'pending.json'))
    assert open(os.path.join(source.base, 'config.json'), 'rb').read() == before


@pytest.mark.parametrize('library_alias', [False, True])
def test_script_api_rejects_directory_links_into_restore(tmp_path, monkeypatch, library_alias):
    from flask import Flask
    from core.api.v1 import resources
    source, exported_job, connection = exported(tmp_path)
    connection.close()
    imported = import_zip(source, open(source.path(exported_job, 'backup.zip'), 'rb').read())
    if library_alias:
        alias = source.path(imported, 'library/world_info_dir')
    else:
        alias = os.path.join(source.base, 'business-link')
    os.makedirs(os.path.dirname(alias), exist_ok=True)
    directory_link(alias, source.path(imported, 'restore/world_info_dir'))
    cfg = source._config()
    cfg['world_info_dir'] = alias
    monkeypatch.setattr(resources, 'BASE_DIR', source.base)
    monkeypatch.setattr(resources, 'load_config', lambda: cfg)
    app = Flask(__name__)
    app.register_blueprint(resources.bp)
    path = os.path.join(alias, 'book.json')
    before = open(path, 'rb').read()
    result = app.test_client().post('/api/scripts/save', json={
        'file_path': path, 'content': {'entries': {}, 'changed': True}})
    assert result.get_json()['success'] is False
    assert '迁移' in result.get_json()['msg']
    assert open(path, 'rb').read() == before


@pytest.mark.parametrize('relative', [False, True])
def test_script_api_cannot_modify_preview_or_pending_library(tmp_path, monkeypatch, relative):
    from flask import Flask
    from core.api.v1 import resources
    source, exported_job, connection = exported(tmp_path)
    seed_valid_card(connection, tmp_path / 'source')
    connection.close()
    exported_job = source.new_job('export')
    source.export(exported_job)
    target = tmp_path / 'target'
    target.mkdir()
    seed(target).close()
    restored = DataMigrationService(str(target))
    imported = import_zip(restored, open(source.path(exported_job, 'backup.zip'), 'rb').read())
    monkeypatch.setattr(resources, 'BASE_DIR', str(target))
    monkeypatch.setattr(resources, 'load_config', restored._config)
    app = Flask(__name__)
    app.register_blueprint(resources.bp)
    client = app.test_client()
    book = restored.path(imported, 'restore/world_info_dir/book.json')
    for path in (book, restored.path(imported, 'manifest.json'), restored.path(imported, 'status.json')):
        raw = open(path, 'rb').read()
        value = os.path.relpath(path, target) if relative else path
        result = client.post('/api/scripts/save', json={'file_path': value, 'content': {'entries': {}}})
        assert result.get_json()['success'] is False
        assert '迁移' in result.get_json()['msg']
        assert open(path, 'rb').read() == raw
    restored.update(imported, state='restoring')
    restored.prepare_restore(imported)
    pending_book = restored.path(imported, 'library/world_info_dir/book.json')
    assert os.path.isfile(pending_book)
    result = client.post('/api/scripts/save', json={
        'file_path': pending_book, 'content': {'entries': {}, 'changed': True}})
    assert result.get_json()['success'] is False
    os.rename(source.base, str(tmp_path / 'source-away'))
    isolated_startup(target, '''
book=os.path.join(cfg['world_info_dir'],'book.json')
assert json.load(open(book,encoding='utf-8'))=={'entries':{}}
''', before_init='''
from flask import Flask
from core.api.v1 import resources
app=Flask(__name__)
app.register_blueprint(resources.bp)
book=os.path.join(load_config()['world_info_dir'],'book.json')
result=app.test_client().post('/api/scripts/save',json={
    'file_path':book,'content':{'entries':{},'changed':True}})
assert result.get_json()['success'] is False,result.get_json()
assert '迁移' in result.get_json()['msg']
''')
    # 已通过真实启动的正式业务库仍可编辑，不因位于 migration/library 下被误封。
    result = client.post('/api/scripts/save', json={
        'file_path': pending_book, 'content': {'entries': {}, 'changed': True}})
    assert result.get_json()['success'] is True
    assert json.load(open(pending_book, encoding='utf-8'))['changed'] is True


@pytest.mark.parametrize('entries', [[('x','a'),('X','b')], [('x','a'),('x/y','b')]])
def test_duplicate_and_conflicting_entries(tmp_path, entries):
    service = DataMigrationService(str(tmp_path))
    job = service.new_job('import')
    service.receive(job, io.BytesIO(zip_bytes(entries)))
    with pytest.raises(ValueError):
        service.validate(job)


def test_symlink_archive_rejected(tmp_path):
    data = io.BytesIO()
    with zipfile.ZipFile(data, 'w') as archive:
        info = zipfile.ZipInfo('linked')
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(info, '/etc/passwd')
    service = DataMigrationService(str(tmp_path))
    job = service.new_job('import')
    service.receive(job, io.BytesIO(data.getvalue()))
    with pytest.raises(ValueError):
        service.validate(job)


def test_corrupt_hash_and_space_fail_before_overwrite(tmp_path, monkeypatch):
    service, job, conn = exported(tmp_path)
    conn.close()
    with zipfile.ZipFile(service.path(job, 'backup.zip')) as archive:
        entries = [(name, archive.read(name)) for name in archive.namelist()]
    damaged = [(name, b'ATTACHMENT' if name == 'resources_dir/bound/attachment.txt' else raw) for name,raw in entries]
    with pytest.raises(ValueError):
        import_zip(service, zip_bytes(damaged))
    cfg = open(os.path.join(service.base, 'config.json'), 'rb').read()
    monkeypatch.setattr(shutil, 'disk_usage', lambda _: type('Space', (), {'free': 1})())
    with pytest.raises(ValueError, match='空间'):
        import_zip(service, zip_bytes(entries))
    assert open(os.path.join(service.base, 'config.json'), 'rb').read() == cfg


def test_inaccessible_directory_aborts_export(tmp_path, monkeypatch):
    base = tmp_path / 'base'
    base.mkdir()
    conn = seed(base)
    conn.close()
    service = DataMigrationService(str(base))
    from core.services import data_migration_service as module
    original = module.walk_directory_strict
    def broken(root):
        if str(root).endswith('characters'):
            raise PermissionError('目录不可访问')
        yield from original(root)
    monkeypatch.setattr(module, 'walk_directory_strict', broken)
    job = service.new_job('export')
    with pytest.raises(PermissionError):
        service.export(job)
    assert not os.path.exists(service.path(job, 'backup.zip'))


def test_system_directory_cannot_be_exported_through_resource_configuration(tmp_path):
    base = tmp_path / 'base'
    base.mkdir()
    conn = seed(base)
    conn.close()
    path = base / 'config.json'
    cfg = json.loads(path.read_text(encoding='utf-8'))
    cfg['resources_dir'] = str(base / 'data/system').lower() if os.name == 'nt' else str(base / 'data/system')
    durable_json(str(path), cfg)
    service = DataMigrationService(str(base))
    job = service.new_job('export')
    with pytest.raises(ValueError, match='系统'):
        service.export(job)
    assert not os.path.exists(service.path(job, 'backup.zip'))


def test_cross_platform_path_tokens():
    from core.services.migration_paths import MigrationPaths
    assert MigrationPaths('D:/Library', {}, exporting=True).path('D:/Library') == 'stm://base'
    assert MigrationPaths('/data/user/0/pkg/files', {}).path('stm://base') == '/data/user/0/pkg/files'
    windows = {'resource_folder': r'd:\LIBRARY\assets\bound',
               'summary': 'my cards are here', 'html': '<img src="D:/Library/assets/bound/image.png">'}
    portable = MigrationPaths('D:/Library', {'resources_dir':'D:/Library/assets'}, exporting=True, casefold=True).ui({'cards/a.png': windows})
    android = MigrationPaths('/data/user/0/pkg/files', {'resources_dir':'/data/user/0/pkg/files/data/library/assets'}).ui(portable)
    assert android['cards/a.png']['resource_folder'] == '/data/user/0/pkg/files/data/library/assets/bound'
    assert android['cards/a.png']['html'] == windows['html']
    assert android['cards/a.png']['summary'] == windows['summary']
    back = MigrationPaths('/data/user/0/pkg/files', {
        'resources_dir': '/data/user/0/pkg/files/data/library/assets'}, exporting=True).ui(android)
    desktop = MigrationPaths('E:/Restored', {'resources_dir': 'E:/Restored/resources'}).ui(back)
    assert desktop['cards/a.png']['resource_folder'] == 'E:/Restored/resources/bound'
    assert desktop['cards/a.png']['summary'] == windows['summary']


@pytest.mark.parametrize('filename', ['book.json', 'History.JSON'])
def test_absolute_external_binding_and_legacy_history_remain_linked(tmp_path, monkeypatch, filename):
    source, _, conn = exported(tmp_path)
    external = tmp_path / 'bound-outside-config'
    external.mkdir()
    (external / filename).write_text('{"entries":{}}')
    ui_path = os.path.join(source.base, 'data/system/db/ui_data.json')
    with open(ui_path, encoding='utf-8') as handle:
        ui = json.load(handle)
    ui['a.png']['resource_folder'] = str(external)
    durable_json(ui_path, ui)
    old_scope = hashlib.sha1(('resource|' + str(external / filename).replace('\\', '/')).encode()).hexdigest()
    conn.execute("INSERT INTO wi_entry_history (scope_key,entry_uid,snapshot_json,snapshot_hash,created_at) VALUES (?,?,?,'hash',1)", (old_scope, 'outside-entry', '{}'))
    conn.commit()
    job = source.new_job('export')
    source.export(job)
    conn.close()
    target = tmp_path / 'other-device'
    target.mkdir()
    restored = DataMigrationService(str(target))
    imported = import_zip(restored, open(source.path(job, 'backup.zip'), 'rb').read())
    restored.update(imported, state='restoring')
    restored.prepare_restore(imported)
    activate_pending(str(target))
    confirm_pending(str(target))
    ui = json.loads((target / 'data/system/db/ui_data.json').read_text(encoding='utf-8'))
    book = os.path.join(ui['a.png']['resource_folder'], filename)
    assert os.path.isfile(book)
    cfg = json.loads((target / 'config.json').read_text(encoding='utf-8'))
    from core.services import wi_entry_history_service as history
    monkeypatch.setattr(history, '_history_roots', lambda: {
        'base': str(target), 'world_info_dir': cfg['world_info_dir'], 'resources_dir': cfg['resources_dir']})
    from contextlib import closing
    with closing(sqlite3.connect(target / 'data/system/db/cards_metadata.db')) as db:
        scope = db.execute("SELECT scope_key FROM wi_entry_history WHERE entry_uid='outside-entry'").fetchone()[0]
    assert scope == history.build_scope_key('resource', file_path=book)


def restore_export(source, job, target):
    restored, imported = prepare_export(source, job, target)
    activate_pending(str(target))
    return restored, imported


def prepare_export(source, job, target):
    target.mkdir()
    restored = DataMigrationService(str(target))
    imported = import_zip(restored, open(source.path(job, 'backup.zip'), 'rb').read())
    restored.update(imported, state='restoring')
    restored.prepare_restore(imported)
    return restored, imported


def isolated_python(base, code, *args):
    import subprocess
    import sys
    from pathlib import Path
    env = {**os.environ, 'STM_ANDROID_SHELL': '1', 'STM_DATA_ROOT': str(base),
           'STM_INTERNAL_ROOT': str(Path(__file__).resolve().parents[1])}
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, *map(str, args)], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr


def isolated_startup(base, assertions, before_init=''):
    isolated_python(base, '''
import json,os
import core
from core.context import ctx
from core.config import load_config
from core.services import wi_entry_history_service as history
from core.data.ui_store import get_worldinfo_note,load_ui_data
for name in ('start_background_index_upgrade','start_background_scanner',
             'start_index_job_worker','start_monitor_scheduler'):
    setattr(core,name,lambda *a,**kw: None)
core.plugin_jobs.start_plugin_job_worker=lambda: None
from core.plugins import hooks
hooks.emit=lambda *a,**kw: None
''' + before_init + '''
core.init_services()
assert ctx.init_status['status']=='ready',ctx.init_status
root=os.environ['STM_DATA_ROOT']
assert json.load(open(os.path.join(root,'data/migration/last-restore.json'),encoding='utf-8'))['state']=='complete'
cfg=load_config()
ui=load_ui_data()
''' + assertions)


def seed_valid_card(conn, base, card_id='a.png'):
    import base64
    from PIL import Image, PngImagePlugin
    path = base / config.RUNTIME_DIR_DEFAULTS['cards_dir'] / card_id
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = PngImagePlugin.PngInfo()
    payload = json.dumps({'spec': 'chara_card_v2', 'spec_version': '2.0',
                          'data': {'name': 'A', 'description': '', 'tags': ['标签']}}).encode()
    metadata.add_text('chara', base64.b64encode(payload).decode())
    Image.new('RGB', (16, 16), '#224466').save(path, pnginfo=metadata)
    conn.execute("UPDATE card_metadata SET id=?,char_name='A',tags='[\"标签\"]',category='',creator='',"
                 "char_version='',last_modified=1", (card_id,))
    conn.execute('UPDATE ui_data_cache SET card_id=?', (card_id,))
    conn.execute('UPDATE source_update_monitor_entries SET card_id=?', (card_id,))
    conn.commit()


@pytest.mark.parametrize('source_state', ['enabled', 'disabled', 'legacy-missing'])
@pytest.mark.parametrize('existing_target', [False, True])
def test_global_automation_selection_survives_zip_and_real_startup(tmp_path, source_state, existing_target):
    base = tmp_path / 'source'
    base.mkdir()
    connection = seed(base)
    seed_valid_card(connection, base)
    connection.close()
    # 使用真实规则保存和全局启用接口，配置和规则文件均由业务代码落盘。
    setup = '''
import sys
from flask import Flask
from core.api.v1 import automation
from core.services import automation_service
app=Flask(__name__)
app.register_blueprint(automation.bp)
client=app.test_client()
ruleset=client.post('/api/automation/rulesets',json={
    'meta':{'name':'迁移规则_甲'},
    'rules':[{'name':'迁移标签','enabled':True,'trigger_contexts':['auto_import'],
              'groups':[{'logic':'AND','conditions':[{'field':'char_name','operator':'eq','value':'A'}]}],
              'actions':[{'type':'add_tag','value':'自动迁移标签'}]}]
}).get_json()
assert ruleset['success'],ruleset
active=ruleset['id'] if sys.argv[1]!='disabled' else None
assert client.post('/api/automation/global_setting',json={'ruleset_id':active}).get_json()['success']
assert client.get('/api/automation/global_setting').get_json()['ruleset_id']==active
runtime=automation_service._build_runtime_from_active_ruleset()
assert (runtime is not None)==(active is not None)
'''
    isolated_python(base, setup, source_state)
    source = DataMigrationService(str(base))
    exported_job = source.new_job('export')
    source.export(exported_job)
    expected = '迁移规则_甲' if source_state == 'enabled' else None
    with zipfile.ZipFile(source.path(exported_job, 'backup.zip')) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    settings = json.loads(entries['settings.json'])
    assert settings['active_automation_ruleset'] == (None if source_state == 'disabled' else '迁移规则_甲')
    assert json.loads(entries['automation/迁移规则_甲.json'])['id'] == '迁移规则_甲'
    if source_state == 'legacy-missing':
        settings.pop('active_automation_ruleset')
        raw = json.dumps(settings, ensure_ascii=False).encode('utf-8')
        entries['settings.json'] = raw
        manifest = json.loads(entries['manifest.json'])
        for entry in manifest['files']:
            if entry['path'] == 'settings.json':
                entry.update(size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        entries['manifest.json'] = json.dumps(manifest, ensure_ascii=False).encode('utf-8')
    target = tmp_path / 'target'
    target.mkdir()
    if existing_target:
        seed(target).close()
        # 目标已有不同的启用规则，恢复关闭状态时必须覆盖该选择。
        isolated_python(target, setup.replace('迁移规则_甲', '目标原规则'), 'enabled')
    restored = DataMigrationService(str(target))
    imported = import_zip(restored, zip_bytes(entries.items()))
    warnings = restored.status(imported)['preview']['warnings']
    assert any('未包含全局自动化启用设置' in warning for warning in warnings) == (source_state == 'legacy-missing')
    restored.update(imported, state='restoring')
    restored.prepare_restore(imported)
    base.rename(tmp_path / 'source-away')
    isolated_startup(target, '''
from flask import Flask
from core.api.v1 import automation
from core.services import automation_service
app=Flask(__name__)
app.register_blueprint(automation.bp)
client=app.test_client()
expected=EXPECTED
assert cfg['active_automation_ruleset']==expected,cfg
assert client.get('/api/automation/global_setting').get_json()['ruleset_id']==expected
rules=client.get('/api/automation/rulesets/迁移规则_甲').get_json()
assert rules['success'],rules
assert rules['data']['rules'][0]['actions']==[{'type':'add_tag','value':'自动迁移标签'}]
runtime=automation_service._build_runtime_from_active_ruleset()
assert automation_service.has_global_automation_action('add_tag')==(expected is not None)
if expected is None:
    assert runtime is None,runtime
else:
    assert runtime['ruleset_id']==expected,runtime
    plan=automation_service.engine.evaluate({'char_name':'A'},runtime['ruleset'],match_if_no_conditions=True)
    assert plan['actions']==[{'type':'add_tag','value':'自动迁移标签'}],plan
assert ctx.cache.id_map['a.png']['is_favorite']
assert ctx.cache.id_map['a.png']['ui_summary']=='备注'
assert ctx.cache.id_map['a.png']['tags']==['标签']
assert os.path.isfile(os.path.join(ctx.cache.id_map['a.png']['resource_folder'],'attachment.txt'))
'''.replace('EXPECTED', repr(expected)))


def test_underscore_card_bindings_survive_real_startup_without_source(tmp_path):
    base = tmp_path / 'source'
    base.mkdir()
    external = tmp_path / 'external'
    conn = seed(base, external)
    seed_valid_card(conn, base, '_a.png')
    conn.close()
    ui_path = base / 'data/system/db/ui_data.json'
    ui = json.loads(ui_path.read_text(encoding='utf-8'))
    ui['_a.png'] = ui.pop('a.png')
    durable_json(str(ui_path), ui)
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    target = tmp_path / 'target'
    prepare_export(source, job, target)
    base.rename(tmp_path / 'source-away')
    external.rename(tmp_path / 'external-away')
    isolated_startup(target, '''
card=ctx.cache.id_map['_a.png']
assert card['is_favorite'] and card['ui_summary']=='备注' and card['tags']==['标签']
assert open(os.path.join(card['resource_folder'],'attachment.txt')).read()=='attachment'
assert ui['_a.png']['resource_folder']==card['resource_folder']
''')


@pytest.mark.parametrize('child_first', [True, False])
def test_nested_external_roots_keep_one_copy_and_real_history(tmp_path, child_first):
    from core.data.ui_store import set_worldinfo_note
    base = tmp_path / 'source'
    base.mkdir()
    conn = seed(base)
    seed_valid_card(conn, base)
    conn.close()
    parent = tmp_path / 'outside'
    child = parent / 'nested'
    book = child / 'lorebooks/History.JSON'
    book.parent.mkdir(parents=True)
    book.write_text('{"entries":{}}')
    cfg = json.loads((base / 'config.json').read_text(encoding='utf-8'))
    cfg['allowed_abs_resource_roots'] = [str(parent), str(child)]
    durable_json(str(base / 'config.json'), cfg)
    ui_path = base / 'data/system/db/ui_data.json'
    ui = json.loads(ui_path.read_text(encoding='utf-8'))
    ui['a.png']['resource_folder'] = str(child)
    second = {'resource_folder': str(parent)}
    ui = {'a.png': ui['a.png'], 'parent.png': second} if child_first else {'parent.png': second, 'a.png': ui['a.png']}
    set_worldinfo_note(ui, 'resource', '嵌套备注', file_path=str(book))
    durable_json(str(ui_path), ui)
    isolated_python(base, '''
import sys
from core.services import wi_entry_history_service as h
for kind in ('resource','lorebook'):
    assert h.append_entry_history_records(kind,'',sys.argv[1],[{'entry_uid':kind,'snapshot':{'content':'saved'}}])==1
    assert len(h.list_entry_history_records(kind,'',sys.argv[1],kind))==1
''', book)
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert any(link['relative'] == 'nested' for link in manifest['root_links'].values())
    target = tmp_path / 'target'
    prepare_export(source, job, target)
    base.rename(tmp_path / 'source-away')
    parent.rename(tmp_path / 'outside-away')
    isolated_startup(target, '''
folder=ctx.cache.id_map['a.png']['resource_folder']
parent=ui['parent.png']['resource_folder']
book=os.path.join(folder,'lorebooks','History.JSON')
other=os.path.join(parent,'nested','lorebooks','History.JSON')
assert os.path.samefile(book,other)
history.purge_orphaned_entry_history(cards_root=cfg['cards_dir'],world_info_root=cfg['world_info_dir'],
                                    resources_root=cfg['resources_dir'],
                                    external_resource_roots=cfg['allowed_abs_resource_roots'])
assert get_worldinfo_note(ui,'resource',file_path=book)['summary']=='嵌套备注'
for kind in ('resource','lorebook'):
    assert len(history.list_entry_history_records(kind,'',book,kind))==1
    assert len(history.list_entry_history_records(kind,'',other,kind))==1
''')


def test_shared_worldbook_resource_root_keeps_notes_and_real_history(tmp_path):
    from core.data.ui_store import set_worldinfo_note
    base = tmp_path / 'source'
    base.mkdir()
    conn = seed(base)
    seed_valid_card(conn, base)
    conn.close()
    cfg = json.loads((base / 'config.json').read_text(encoding='utf-8'))
    cfg['resources_dir'] = cfg['world_info_dir']
    durable_json(str(base / 'config.json'), cfg)
    shared = base / cfg['world_info_dir']
    book = shared / 'book.json'
    ui_path = base / 'data/system/db/ui_data.json'
    ui = json.loads(ui_path.read_text(encoding='utf-8'))
    ui['a.png']['resource_folder'] = str(shared)
    for kind in ('global', 'resource'):
        set_worldinfo_note(ui, kind, kind + '备注', file_path=str(book))
    durable_json(str(ui_path), ui)
    isolated_python(base, '''
import sys
from core.services import wi_entry_history_service as h
for kind in ('global','resource','lorebook'):
    assert h.append_entry_history_records(kind,'',sys.argv[1],[{'entry_uid':kind,'snapshot':{'content':'saved'}}])==1
    assert len(h.list_entry_history_records(kind,'',sys.argv[1],kind))==1
''', book)
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    target = tmp_path / 'target'
    prepare_export(source, job, target)
    base.rename(tmp_path / 'source-away')
    isolated_startup(target, '''
assert os.path.samefile(cfg['world_info_dir'],cfg['resources_dir'])
folder=ctx.cache.id_map['a.png']['resource_folder']
assert os.path.samefile(folder,cfg['resources_dir'])
book=os.path.join(folder,'book.json')
history.purge_orphaned_entry_history(cards_root=cfg['cards_dir'],world_info_root=cfg['world_info_dir'],
                                    resources_root=cfg['resources_dir'])
for kind in ('global','resource'):
    assert get_worldinfo_note(ui,kind,file_path=book)['summary']==kind+'备注'
for kind in ('global','resource','lorebook'):
    assert len(history.list_entry_history_records(kind,'',book,kind))==1
''')


@pytest.mark.parametrize('anchor,relative', [
    ('beautify_dir', ''), ('beautify_dir', 'Books'),
    ('assets', ''), ('assets', 'Books'),
    ('wallpapers', ''), ('wallpapers', 'Books'),
])
def test_worldbook_fixed_root_alias_survives_startup_and_cleanup(tmp_path, anchor, relative):
    from core.data.ui_store import set_worldinfo_note
    from core.services.data_migration_service import FIXED
    base = tmp_path / 'source'
    base.mkdir()
    connection = seed(base)
    seed_valid_card(connection, base)
    connection.close()
    cfg = json.loads((base / 'config.json').read_text(encoding='utf-8'))
    anchor_path = base / (cfg['beautify_dir'] if anchor == 'beautify_dir' else FIXED[anchor])
    folder = anchor_path / relative if relative else anchor_path
    folder.mkdir(parents=True, exist_ok=True)
    book = folder / 'MixedCase.JSON'
    book.write_text('{"entries":{}}')
    cfg['world_info_dir'] = str(folder)
    durable_json(str(base / 'config.json'), cfg)
    ui_path = base / 'data/system/db/ui_data.json'
    ui = json.loads(ui_path.read_text(encoding='utf-8'))
    set_worldinfo_note(ui, 'global', '固定根共享备注', file_path=str(book))
    durable_json(str(ui_path), ui)
    isolated_python(base, '''
import sys
from core.services import wi_entry_history_service as h
assert h.append_entry_history_records('global','',sys.argv[1],[
    {'entry_uid':'shared-fixed','snapshot':{'content':'shared history'}}])==1
assert len(h.list_entry_history_records('global','',sys.argv[1],'shared-fixed'))==1
''', book)
    service = DataMigrationService(str(base))
    job = service.new_job('export')
    service.export(job)
    with zipfile.ZipFile(service.path(job, 'backup.zip')) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['root_links']['world_info_dir'] == {'root': anchor, 'relative': relative}
    target = tmp_path / 'target'
    prepare_export(service, job, target)
    base.rename(tmp_path / 'source-away')
    target_anchor = cfg['beautify_dir'] if anchor == 'beautify_dir' else FIXED[anchor]
    # 默认美化根也固定在此目录；测试配置并未改变它。
    expected = os.path.join(str(target), target_anchor, relative)
    assertions = '''
book=os.path.join(cfg['world_info_dir'],'MixedCase.JSON')
assert os.path.samefile(cfg['world_info_dir'],EXPECTED)
assert get_worldinfo_note(ui,'global',file_path=book)['summary']=='固定根共享备注'
assert len(history.list_entry_history_records('global','',book,'shared-fixed'))==1
history.purge_orphaned_entry_history(cards_root=cfg['cards_dir'],world_info_root=cfg['world_info_dir'],
                                    resources_root=cfg['resources_dir'])
assert len(history.list_entry_history_records('global','',book,'shared-fixed'))==1
'''.replace('EXPECTED', repr(expected))
    isolated_startup(target, assertions)


@pytest.mark.parametrize('layout', ['fixed-inside-business', 'fixed-inside-fixed'])
def test_unsupported_fixed_root_overlap_fails_before_export(tmp_path, layout):
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    cfg = json.loads((base / 'config.json').read_text(encoding='utf-8'))
    if layout == 'fixed-inside-business':
        outer = tmp_path / 'outer'
        cfg['world_info_dir'] = str(outer)
        cfg['beautify_dir'] = str(outer / 'beautify')
    else:
        cfg['beautify_dir'] = str(base / 'data/assets/beautify')
    os.makedirs(os.path.join(base, cfg['beautify_dir']), exist_ok=True)
    durable_json(str(base / 'config.json'), cfg)
    before = (base / 'data/system/db/cards_metadata.db').read_bytes()
    service = DataMigrationService(str(base))
    job = service.new_job('export')
    with pytest.raises(ValueError, match='暂不支持.*固定目录'):
        service.export(job)
    assert service.status(job)['state'] != 'ready'
    assert not os.path.exists(service.path(job, 'backup.zip'))
    assert not os.path.exists(service.path(job, 'backup.zip.part'))
    assert (base / 'data/system/db/cards_metadata.db').read_bytes() == before


@pytest.mark.parametrize('name,constant', [
    ('manifest.json', 'MAX_MANIFEST_BYTES'), ('settings.json', 'MAX_SETTINGS_BYTES'),
])
def test_real_zip_export_and_import_share_utf8_metadata_limits(tmp_path, monkeypatch, name, constant):
    from core.services import data_migration_service as migration
    service, baseline, connection = exported(tmp_path)
    connection.close()
    base = tmp_path / 'source'
    cfg = service._config()
    cfg['bg_url'] = '背景/壁纸.png'
    durable_json(str(base / 'config.json'), cfg)
    reference = service.new_job('export')
    service.export(reference)
    with zipfile.ZipFile(service.path(reference, 'backup.zip')) as archive:
        raw = archive.read(name)
        assert len(raw) > len(raw.decode('utf-8'))
        zip_data = open(service.path(reference, 'backup.zip'), 'rb').read()
    before = (base / 'data/system/db/cards_metadata.db').read_bytes()
    monkeypatch.setattr(migration, constant, len(raw) - 1)
    failed = service.new_job('export')
    with pytest.raises(ValueError, match='过大'):
        service.export(failed)
    assert service.status(failed)['state'] != 'ready'
    assert not os.path.exists(service.path(failed, 'backup.zip'))
    imported = service.new_job('import')
    service.receive(imported, io.BytesIO(zip_data))
    with pytest.raises(ValueError, match='过大'):
        service.validate(imported)
    assert service.status(imported)['state'] != 'preview'
    assert (base / 'data/system/db/cards_metadata.db').read_bytes() == before
    # 相同字节上限允许生成的真实 ZIP 也必须允许预览（未伪造 ZIP 或文件清单）。
    monkeypatch.setattr(migration, constant, len(raw))
    accepted = service.new_job('export')
    service.export(accepted)
    with zipfile.ZipFile(service.path(accepted, 'backup.zip')) as archive:
        assert len(archive.read(name)) == len(raw)
    restored = import_zip(service, open(service.path(accepted, 'backup.zip'), 'rb').read())
    assert service.status(restored)['state'] == 'preview'


def test_export_entry_limit_includes_generated_metadata(tmp_path, monkeypatch):
    from core.services import data_migration_service as migration
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    (base / 'data/system/db/ui_data.json').unlink()
    service = DataMigrationService(str(base))
    rows = service.snapshot_inventory(service.roots(service._config()))[0]
    monkeypatch.setattr(migration, 'MAX_FILES', len(rows))
    job = service.new_job('export')
    with pytest.raises(ValueError, match='ZIP 文件数过多'):
        service.export(job)
    assert service.status(job)['state'] != 'ready'
    assert not os.path.exists(service.path(job, 'backup.zip'))


@pytest.mark.parametrize('contents', ['different-files', 'empty', 'file-directory'])
def test_unicode_directory_conflict_aborts_real_export(tmp_path, contents):
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    root = base / config.RUNTIME_DIR_DEFAULTS['cards_dir']
    first, second = root / 'Café', root / 'Cafe\u0301'
    first.mkdir()
    try:
        if contents == 'file-directory':
            second.write_bytes(b'file conflicting with directory')
        else:
            second.mkdir()
    except FileExistsError:
        pytest.skip('当前文件系统自动合并 Unicode 规范化名称')
    if contents == 'different-files':
        (first / 'a.png').write_bytes(b'a')
        (second / 'b.png').write_bytes(b'b')
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    with pytest.raises(ValueError, match='冲突'):
        source.export(job)
    assert source.status(job)['state'] != 'ready'
    assert not os.path.exists(source.path(job, 'backup.zip'))


def test_archive_implicit_ancestor_conflict_rejected(tmp_path):
    service = DataMigrationService(str(tmp_path))
    raw = zip_bytes([('cards_dir/Café/a.png', b'a'), ('cards_dir/Cafe\u0301/b.png', b'b')])
    job = service.new_job('import')
    service.receive(job, io.BytesIO(raw))
    with pytest.raises(ValueError, match='冲突'):
        service.validate(job)


@pytest.mark.parametrize('links', [
    None,
    {'world_info_dir': {'root': 'resources_dir', 'relative': '../escape'}},
    {'world_info_dir': {'root': 'db', 'relative': ''}},
    {'world_info_dir': {'root': 'resources_dir', 'relative': ''},
     'resources_dir': {'root': 'world_info_dir', 'relative': ''}},
    {'world_info_dir': {'root': 'resources_dir', 'relative': ''}},
    {'world_info_dir': {'root': 'resources_dir', 'relative': 'missing-directory'}},
    {'world_info_dir': {'root': [], 'relative': ''}},
])
def test_invalid_root_links_rejected_before_preview(tmp_path, links):
    source, exported_job, conn = exported(tmp_path)
    conn.close()
    with zipfile.ZipFile(source.path(exported_job, 'backup.zip')) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    manifest = json.loads(entries['manifest.json'])
    manifest['root_links'] = links
    entries['manifest.json'] = json.dumps(manifest).encode()
    original = (tmp_path / 'source/data/system/db/cards_metadata.db').read_bytes()
    job = source.new_job('import')
    source.receive(job, io.BytesIO(zip_bytes(entries.items())))
    with pytest.raises(ValueError):
        source.validate(job)
    assert source.status(job)['state'] != 'preview'
    assert (tmp_path / 'source/data/system/db/cards_metadata.db').read_bytes() == original
    assert not (tmp_path / 'source/data/migration/pending.json').exists()


def test_short_relative_root_keeps_ids_notes_tags_and_favorites(tmp_path):
    source, _, conn = exported(tmp_path)
    base = tmp_path / 'source'
    cfg = json.loads((base / 'config.json').read_text(encoding='utf-8'))
    cfg['cards_dir'] = 'cards'
    durable_json(str(base / 'config.json'), cfg)
    (base / 'cards/cards').mkdir(parents=True)
    (base / 'cards/cards/a.png').write_bytes(b'original card bytes')
    ui_path = base / 'data/system/db/ui_data.json'
    ui = json.loads(ui_path.read_text(encoding='utf-8'))
    ui['cards/a.png'] = ui.pop('a.png')
    ui['cards/a.png']['summary'] = 'my cards are here'
    ui['cards/a.png']['version_remarks'] = {'cards/a.png': {'summary': 'cards unchanged'}}
    durable_json(str(ui_path), ui)
    conn.execute("UPDATE card_metadata SET id='cards/a.png'")
    conn.execute("UPDATE ui_data_cache SET card_id='cards/a.png', summary='my cards are here'")
    conn.execute("UPDATE source_update_monitor_entries SET card_id='cards/a.png'")
    conn.commit()
    job = source.new_job('export')
    source.export(job)
    conn.close()
    target = tmp_path / 'target'
    _, imported = restore_export(source, job, target)
    confirm_pending(str(target))
    cfg = json.loads((target / 'config.json').read_text(encoding='utf-8'))
    assert open(os.path.join(cfg['cards_dir'], 'cards/a.png'), 'rb').read() == b'original card bytes'
    ui = json.loads((target / 'data/system/db/ui_data.json').read_text(encoding='utf-8'))
    assert ui['cards/a.png']['summary'] == 'my cards are here'
    assert ui['cards/a.png']['tags'] == ['标签']
    assert ui['cards/a.png']['version_remarks']['cards/a.png']['summary'] == 'cards unchanged'
    from contextlib import closing
    with closing(sqlite3.connect(target / 'data/system/db/cards_metadata.db')) as db:
        assert db.execute('SELECT id,is_favorite FROM card_metadata').fetchone() == ('cards/a.png', 1)
        assert db.execute('SELECT card_id,summary FROM ui_data_cache').fetchone() == ('cards/a.png', 'my cards are here')
        assert db.execute('SELECT card_id FROM source_update_monitor_entries').fetchone()[0] == 'cards/a.png'


@pytest.mark.parametrize('external_beautify', [False, True])
def test_real_beautify_zip_keeps_posix_relative_asset_paths(tmp_path, external_beautify):
    import posixpath
    from PIL import Image
    from core.data.ui_store import get_beautify_library
    from core.services.beautify_service import BeautifyService
    from core.services.migration_paths import MigrationPaths

    source, _, conn = exported(tmp_path)
    base = tmp_path / 'source'
    cfg = json.loads((base / 'config.json').read_text(encoding='utf-8'))
    if external_beautify:
        cfg['beautify_dir'] = str(tmp_path / 'custom/library/beautify')
        durable_json(str(base / 'config.json'), cfg)
    ui_path = base / 'data/system/db/ui_data.json'
    loader = lambda: json.loads(ui_path.read_text(encoding='utf-8'))
    service = BeautifyService(library_root=os.path.join(base, cfg['beautify_dir']),
                             internal_root=str(base), ui_data_loader=loader,
                             ui_data_saver=lambda data: durable_json(str(ui_path), data))
    theme = tmp_path / 'theme_pc.json'
    theme.write_text('{"name":"Migration Theme","main_text_color":"#fff"}')
    image = tmp_path / 'image.png'
    Image.new('RGB', (64, 64), '#224466').save(image)
    imported_theme = service.import_theme(str(theme), platform='pc')
    package_id = imported_theme['package']['id']
    variant_id = imported_theme['variant']['id']
    shot = service.import_screenshot(package_id, str(image))['screenshot']
    avatar = service.import_package_avatar(package_id, 'user', str(image))['identity']
    job = source.new_job('export')
    source.export(job)
    conn.close()
    with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
        portable = json.loads(archive.read('db/ui_data.json'))
        android_base = '/data/user/0/com.stmanager.pro/files'
        roots = {slot: android_base + '/data/' + slot for slot in json.loads(archive.read('manifest.json'))['roots']}
        roots['beautify_dir'] = android_base + '/data/library/beautify'
        android = MigrationPaths(android_base, roots).ui(portable)
        package = get_beautify_library(android)['packages'][package_id]
        files = [package['variants'][variant_id]['theme_file'], package['screenshots'][shot['id']]['file'],
                 package['identity_overrides']['user']['avatar_file']]
        for relative in files:
            assert relative.startswith('data/library/beautify/') and not posixpath.isabs(relative)
            logical = 'beautify_dir/' + relative.removeprefix('data/library/beautify/')
            assert archive.read(logical)
            assert posixpath.join(android_base, relative).startswith(android_base + '/data/library/beautify/')
    target = tmp_path / 'target'
    restore_export(source, job, target)
    confirm_pending(str(target))
    target_ui = target / 'data/system/db/ui_data.json'
    restored = BeautifyService(library_root=str(target / 'data/library/beautify'), internal_root=str(target),
                              ui_data_loader=lambda: json.loads(target_ui.read_text(encoding='utf-8')),
                              ui_data_saver=lambda data: durable_json(str(target_ui), data))
    package = restored.get_package(package_id)
    assert package['variants'][variant_id]['theme_data']['name'] == 'Migration Theme'
    assert package['identity_overrides']['user']['avatar_file'].endswith('/avatars/user.png')
    for relative in [package['screenshots'][shot['id']]['file'],
                     package['identity_overrides']['user']['avatar_file']]:
        path = restored.get_preview_asset_path(relative.removeprefix('data/library/beautify/'))
        assert path and open(path, 'rb').read() == image.read_bytes()


def test_windows_worldbook_note_uses_actual_case_on_posix(tmp_path, monkeypatch):
    import inspect
    import posixpath
    import types
    from core.data import ui_store
    from core.services.migration_paths import MigrationPaths

    source, _, conn = exported(tmp_path)
    base = tmp_path / 'source'
    cfg = source._config()
    book = base / cfg['world_info_dir'] / 'UpperDir/MixedCase.JSON'
    book.parent.mkdir()
    book.write_text('{"entries":{}}')
    ui_path = base / 'data/system/db/ui_data.json'
    ui = json.loads(ui_path.read_text(encoding='utf-8'))
    folder = base / cfg['resources_dir'] / 'EmptyFolder'
    folder.mkdir()
    ui['a.png']['resource_folder'] = str(folder).replace('\\', '/').lower()
    # Windows 的历史键已丢失大小写，即使此测试在 POSIX 上运行也模拟同样的持久值。
    ui['_worldinfo_notes_v1'] = {'global::' + str(book).replace('\\', '/').lower(): {'summary': '大小写备注'}}
    durable_json(str(ui_path), ui)
    job = source.new_job('export')
    # 使用 Windows 路径比较规则收集真实 ZIP；不改变文件系统 API 的实现。
    from core.services import data_migration_service as migration
    original = migration.MigrationPaths
    monkeypatch.setattr(migration, 'MigrationPaths', lambda *a, **kw: original(*a, **{**kw, 'casefold': True}))
    source.export(job)
    conn.close()
    with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
        portable = json.loads(archive.read('db/ui_data.json'))
        roots = {slot: '/data/' + slot for slot in json.loads(archive.read('manifest.json'))['roots']}
    key = next(iter(portable['_worldinfo_notes_v1']))
    assert key.endswith('/UpperDir/MixedCase.JSON')
    # 执行真实规范化函数，只替换其 os.path 为 POSIX 规则；不声称是 Android 真机。
    from core.utils import filesystem
    namespace = {'os': types.SimpleNamespace(name='posix', path=posixpath)}
    for normalize in (filesystem.filesystem_path_bucket, filesystem.filesystem_path_key):
        exec(inspect.getsource(normalize), namespace)
    monkeypatch.setattr(ui_store, 'filesystem_path_key', namespace['filesystem_path_key'])
    root = '/data/user/0/com.stmanager.pro/files/data/worldbooks'
    android = MigrationPaths('/data/user/0/com.stmanager.pro/files', {**roots, 'world_info_dir': root}).ui(portable)
    note = ui_store.get_worldinfo_note(android, 'global', file_path=root + '/UpperDir/MixedCase.JSON')
    assert note['summary'] == '大小写备注'
    assert android['a.png']['resource_folder'].endswith('/EmptyFolder')


@pytest.mark.parametrize('sql,compatible', [
    ('ALTER TABLE wi_history_roots DROP COLUMN roots_json', False),
    ('ALTER TABLE card_metadata DROP COLUMN is_favorite', True),
])
def test_real_zip_validates_business_schema_and_supported_upgrades(tmp_path, sql, compatible):
    from contextlib import closing
    source, job, conn = exported(tmp_path)
    conn.close()
    dbpath = tmp_path / 'mutated.db'
    with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    dbpath.write_bytes(entries['db/cards_metadata.db'])
    with closing(sqlite3.connect(dbpath)) as db:
        db.execute(sql)
        db.commit()
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    entries['db/cards_metadata.db'] = dbpath.read_bytes()
    manifest = json.loads(entries['manifest.json'])
    for entry in manifest['files']:
        if entry['path'] == 'db/cards_metadata.db':
            entry.update(size=len(entries[entry['path']]), sha256=hashlib.sha256(entries[entry['path']]).hexdigest())
    entries['manifest.json'] = json.dumps(manifest).encode()
    target = tmp_path / 'target'
    target.mkdir()
    seed(target).close()
    before = (target / 'data/system/db/cards_metadata.db').read_bytes()
    restored = DataMigrationService(str(target))
    imported = restored.new_job('import')
    restored.receive(imported, io.BytesIO(zip_bytes(entries.items())))
    if compatible:
        restored.validate(imported)
        assert restored.status(imported)['state'] == 'preview'
        stage_db = restored.path(imported, 'restore/db/cards_metadata.db')
        assert open(stage_db, 'rb').read() == entries['db/cards_metadata.db']
        restored.update(imported, state='restoring')
        restored.prepare_restore(imported)
        with closing(sqlite3.connect(stage_db)) as upgraded:
            assert 'is_favorite' in {row[1] for row in upgraded.execute('PRAGMA table_info(card_metadata)')}
    else:
        with pytest.raises(ValueError, match='结构'):
            restored.validate(imported)
        assert restored.status(imported)['state'] != 'preview'
    assert (target / 'data/migration/pending.json').exists() is compatible
    assert (target / 'data/system/db/cards_metadata.db').read_bytes() == before


@pytest.mark.parametrize('failure', ['database', 'cache', 'interrupted'])
def test_restore_waits_for_startup_and_rolls_back_on_failure(tmp_path, monkeypatch, failure):
    import core
    from core.data import db_session
    source, job, conn = exported(tmp_path)
    conn.close()
    target = tmp_path / 'target'
    target.mkdir()
    seed(target).close()
    db = target / 'data/system/db/cards_metadata.db'
    old_db = db.read_bytes()
    old_config = (target / 'config.json').read_bytes()
    restored = DataMigrationService(str(target))
    imported = import_zip(restored, open(source.path(job, 'backup.zip'), 'rb').read())
    restored.update(imported, state='restoring')
    restored.prepare_restore(imported)
    activate_pending(str(target))
    journal = target / 'data/migration/pending.json'
    assert json.loads(journal.read_text(encoding='utf-8'))['state'] == 'awaiting_startup'
    assert restored.status(imported)['state'] == 'restart_required'
    if failure == 'interrupted':
        activate_pending(str(target))
    else:
        monkeypatch.setattr(core, 'BASE_DIR', str(target))
        monkeypatch.setattr(config, 'CONFIG_FILE', str(target / 'config.json'))
        monkeypatch.setattr(db_session, 'DEFAULT_DB_PATH', str(db))
        monkeypatch.setattr(core, 'cleanup_temp_files', lambda: None)
        monkeypatch.setattr(core, 'plan_startup_upgrade', lambda **_: [])
        monkeypatch.setattr(core.ctx, 'init_status', dict(core.ctx.init_status))
        def fail(*args, **kwargs):
            raise RuntimeError('injected startup failure')
        if failure == 'database':
            monkeypatch.setattr(core, 'init_database', fail)
        else:
            monkeypatch.setattr(core, 'init_database', lambda: None)
            from types import SimpleNamespace
            monkeypatch.setattr(core.ctx, 'cache', SimpleNamespace(reload_from_db=fail))
        core.init_services()
        assert core.ctx.init_status['status'] == 'error'
        assert '已自动回滚' in core.ctx.init_status['message']
    assert (target / 'config.json').read_bytes() == old_config
    assert db.read_bytes() == old_db
    assert not journal.exists()
    assert json.loads((target / 'data/migration/last-restore.json').read_text(encoding='utf-8'))['state'] == 'rolled_back'


@pytest.mark.parametrize('valid_cache', [True, False])
def test_restore_real_startup_database_and_cache_in_isolated_process(tmp_path, valid_cache):
    import subprocess
    import sys
    from pathlib import Path
    from PIL import Image

    base = tmp_path / 'source'
    base.mkdir()
    conn = seed(base)
    Image.new('RGB', (16, 16), '#224466').save(base / config.RUNTIME_DIR_DEFAULTS['cards_dir'] / 'a.png')
    conn.execute("UPDATE card_metadata SET char_name='A',tags='[\"标签\"]',category=?,creator='',"
                 "char_version='',last_modified=1", ('' if valid_cache else None,))
    conn.commit()
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    conn.close()
    target = tmp_path / 'isolated-target'
    target.mkdir()
    seed(target).close()
    old_db = (target / 'data/system/db/cards_metadata.db').read_bytes()
    restored = DataMigrationService(str(target))
    imported = import_zip(restored, open(source.path(job, 'backup.zip'), 'rb').read())
    restored.update(imported, state='restoring')
    restored.prepare_restore(imported)
    code = '''
import json,os
import core
from core.context import ctx
for name in ('start_background_index_upgrade','start_background_scanner',
             'start_index_job_worker','start_monitor_scheduler'):
    setattr(core,name,lambda *a,**kw: None)
core.plugin_jobs.start_plugin_job_worker=lambda: None
from core.plugins import hooks
hooks.emit=lambda *a,**kw: None
core.init_services()
root=os.environ['STM_DATA_ROOT']
assert not os.path.exists(os.path.join(root,'data/migration/pending.json'))
state=json.load(open(os.path.join(root,'data/migration/last-restore.json'),encoding='utf-8'))['state']
if os.environ['STM_EXPECT_VALID']=='1':
    assert ctx.init_status['status']=='ready', ctx.init_status
    assert state=='complete', state
    assert ctx.cache.id_map['a.png']['is_favorite']
    assert ctx.cache.id_map['a.png']['ui_summary']=='备注'
    assert ctx.cache.id_map['a.png']['tags']==['标签']
    assert os.path.isfile(os.path.join(ctx.cache.id_map['a.png']['resource_folder'],'attachment.txt'))
else:
    assert state=='rolled_back', state
    assert ctx.init_status['status']=='error', ctx.init_status
    assert '已自动回滚' in ctx.init_status['message']
'''
    env = {**os.environ, 'STM_ANDROID_SHELL': '1', 'STM_DATA_ROOT': str(target),
           'STM_INTERNAL_ROOT': str(Path(__file__).resolve().parents[1]),
           'STM_EXPECT_VALID': '1' if valid_cache else '0'}
    result = subprocess.run([sys.executable, '-X', 'utf8', '-c', code], env=env,
                            capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    if not valid_cache:
        assert (target / 'data/system/db/cards_metadata.db').read_bytes() == old_db


@pytest.mark.parametrize('interrupted', [False, True])
def test_failed_or_interrupted_activation_rolls_back(tmp_path, monkeypatch, interrupted):
    base = tmp_path
    root = base / 'data/migration'
    job = '0' * 32
    stage = root / job / 'restore'
    stage.mkdir(parents=True)
    (base / 'config.json').write_text('old')
    (stage / 'config.json').write_text('new')
    moves = [{'source': f'data/migration/{job}/restore/config.json', 'target':'config.json',
              'old':f'data/migration/{job}/protection/config.json', 'existed':True, 'started':True}]
    seal = seal_restore(str(base), job, moves)
    durable_json(str(root / 'pending.json'), {'state':'applying' if interrupted else 'pending',
                                            'job': job, 'moves':moves, **seal})
    if interrupted:
        (root / job / 'protection').mkdir()
        os.replace(base / 'config.json', root / job / 'protection/config.json')
        os.replace(stage / 'config.json', base / 'config.json')
        activate_pending(str(base))
    else:
        original = os.replace
        def fail(src,dst):
            if str(src).endswith('restore/config.json'):
                raise OSError('空间不足')
            return original(src,dst)
        monkeypatch.setattr(os, 'replace', fail)
        with pytest.raises(OSError):
            activate_pending(str(base))
    assert (base / 'config.json').read_text() == 'old'
    assert json.loads((root / 'last-restore.json').read_text())['state'] == 'rolled_back'


def test_incomplete_rollback_keeps_journal_and_retries_next_startup(tmp_path, monkeypatch):
    root = tmp_path / 'data/migration'
    job = '0' * 32
    stage = root / job / 'restore'
    stage.mkdir(parents=True)
    (stage / 'config.json').write_text('new')
    (tmp_path / 'config.json').write_text('old')
    moves = [{
        'source': f'data/migration/{job}/restore/config.json', 'target': 'config.json',
        'old': f'data/migration/{job}/protection/config.json'}]
    seal = seal_restore(str(tmp_path), job, moves)
    durable_json(str(root / 'pending.json'), {'state': 'pending', 'job': job, **seal, 'moves': moves})
    activate_pending(str(tmp_path))
    from core.utils.backup_recovery import rollback_pending
    original = os.replace
    def denied(src, dst):
        if str(src).endswith('protection/config.json'):
            raise PermissionError('temporarily denied')
        return original(src, dst)
    with monkeypatch.context() as failure:
        failure.setattr(os, 'replace', denied)
        with pytest.raises(PermissionError):
            rollback_pending(str(tmp_path), 'startup validation failed')
    assert json.loads((root / 'pending.json').read_text(encoding='utf-8'))['state'] == 'rolling_back'
    assert not (root / 'last-restore.json').exists()
    activate_pending(str(tmp_path))
    assert (tmp_path / 'config.json').read_text() == 'old'
    assert not (root / 'pending.json').exists()
    assert json.loads((root / 'last-restore.json').read_text(encoding='utf-8'))['state'] == 'rolled_back'


def test_nonempty_fts_snapshot_remains_valid(tmp_path):
    service, job, conn = exported(tmp_path)
    try:
        conn.execute('CREATE VIRTUAL TABLE IF NOT EXISTS index_search_full_v2 USING fts5(content)')
    except sqlite3.OperationalError:
        conn.close()
        pytest.skip('SQLite 无 FTS5')
    conn.execute('INSERT INTO index_search_full_v2 (content) VALUES (?)', ('重建的索引',))
    conn.commit()
    job = service.new_job('export')
    service.export(job)
    conn.close()
    imported = import_zip(service, open(service.path(job, 'backup.zip'), 'rb').read())
    assert service.status(imported)['state'] == 'preview'


def test_export_recovers_unclean_wal_without_changing_source(tmp_path):
    import subprocess
    import sys
    base = tmp_path / 'base'
    base.mkdir()
    conn = seed(base)
    conn.close()
    path = base / 'data/system/db/cards_metadata.db'
    code = """import sqlite3,sys,os
conn=sqlite3.connect(sys.argv[1])
conn.execute('PRAGMA journal_mode=WAL')
conn.execute("INSERT INTO card_metadata (id,is_favorite,card_uid) VALUES ('wal.png',1,'wal-uid')")
conn.commit()
os._exit(0)
"""
    subprocess.run([sys.executable, '-c', code, str(path)], check=True)
    assert os.path.isfile(str(path) + '-wal')
    before = path.stat().st_mtime_ns
    service = DataMigrationService(str(base))
    job = service.new_job('export')
    service.export(job)
    assert path.stat().st_mtime_ns == before
    with zipfile.ZipFile(service.path(job, 'backup.zip')) as archive:
        db = tmp_path / 'snapshot.db'
        db.write_bytes(archive.read('db/cards_metadata.db'))
    from contextlib import closing
    with closing(sqlite3.connect(db)) as snapshot:
        assert snapshot.execute("SELECT is_favorite FROM card_metadata WHERE id='wal.png'").fetchone()[0] == 1


@pytest.mark.parametrize('changed', [{'version': 1}, {'version': 2}, {'version': 99},
                                     {'complete': False}, {'app_version': '999.0.0'}])
def test_incompatible_or_incomplete_manifest_rejected(tmp_path, changed):
    service, job, conn = exported(tmp_path)
    conn.close()
    with zipfile.ZipFile(service.path(job, 'backup.zip')) as archive:
        entries = []
        for name in archive.namelist():
            raw = archive.read(name)
            if name == 'manifest.json':
                manifest = json.loads(raw)
                manifest.update(changed)
                raw = json.dumps(manifest).encode()
            entries.append((name, raw))
    with pytest.raises(ValueError):
        import_zip(service, zip_bytes(entries))
    assert not os.path.exists(os.path.join(service.root, 'pending.json'))


def test_maintenance_window_waits_for_active_writer_and_blocks_new_work():
    import threading
    from core.services.maintenance_gate import MaintenanceGate
    barrier = MaintenanceGate()
    existing = threading.Event()
    release = threading.Event()
    snapshot = threading.Event()
    finish = threading.Event()
    new_work = threading.Event()
    def writer():
        with barrier.activity():
            with barrier.activity():  # 嵌套调用可重入。
                existing.set()
                assert release.wait(5)
    def backup():
        with barrier.exclusive():
            snapshot.set()
            assert finish.wait(5)
    def late_writer():
        with barrier.activity():
            new_work.set()
    threads = [threading.Thread(target=writer), threading.Thread(target=backup)]
    threads[0].start()
    assert existing.wait(2)
    threads[1].start()
    assert not snapshot.wait(.05)
    release.set()
    assert snapshot.wait(2)
    third = threading.Thread(target=late_writer)
    third.start()
    assert not new_work.wait(.05)
    finish.set()
    for thread in threads + [third]:
        thread.join(2)
        assert not thread.is_alive()
    assert new_work.is_set()


def test_http_upload_preview_requires_explicit_confirmation(tmp_path, monkeypatch):
    import time
    from flask import Flask
    from core.api.v1 import migration
    service, exported_job, conn = exported(tmp_path)
    conn.close()
    monkeypatch.setattr(migration, '_service', service)
    app = Flask(__name__)
    app.register_blueprint(migration.bp)
    client = app.test_client()
    job = client.post('/api/migration/import').get_json()['id']
    with open(service.path(exported_job, 'backup.zip'), 'rb') as handle:
        result = client.put(f'/api/migration/jobs/{job}/upload', data=handle,
                            content_type='application/zip')
    assert result.status_code == 200
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get(f'/api/migration/jobs/{job}').get_json()
        if result['state'] == 'preview':
            break
        time.sleep(.02)
    assert result['state'] == 'preview'
    assert client.post(f'/api/migration/jobs/{job}/restore', json={}).status_code == 400
    assert not os.path.exists(os.path.join(service.root, 'pending.json'))
    assert client.post(f'/api/migration/jobs/{job}/restore', json={'confirm': True}).status_code == 200
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = client.get(f'/api/migration/jobs/{job}').get_json()
        if result['state'] == 'restart_required':
            break
        time.sleep(.02)
    assert result['state'] == 'restart_required'
    assert client.post(f'/api/migration/jobs/{job}/restore', json={'confirm': True}).status_code == 400


def test_http_restore_refuses_modified_preview_and_requires_new_import(tmp_path, monkeypatch):
    import time
    from flask import Flask
    from core.api.v1 import migration
    service, exported_job, connection = exported(tmp_path)
    connection.close()
    zip_data = open(service.path(exported_job, 'backup.zip'), 'rb').read()
    imported = import_zip(service, zip_data)
    monkeypatch.setattr(migration, '_service', service)
    app = Flask(__name__)
    app.register_blueprint(migration.bp)
    client = app.test_client()
    book = service.path(imported, 'restore/world_info_dir/book.json')
    durable_json(book, {'entries': {}, 'modified_after_preview': True})
    before = open(os.path.join(service.base, 'config.json'), 'rb').read()
    response = client.post(f'/api/migration/jobs/{imported}/restore', json={'confirm': True})
    assert response.status_code == 200
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        state = client.get(f'/api/migration/jobs/{imported}').get_json()
        if state['state'] == 'failed':
            break
        time.sleep(.02)
    assert state['state'] == 'failed'
    assert '重新选择备份并预览' in state['error']
    assert not os.path.exists(os.path.join(service.root, 'pending.json'))
    assert open(os.path.join(service.base, 'config.json'), 'rb').read() == before
    assert client.post(f'/api/migration/jobs/{imported}/restore', json={'confirm': True}).status_code == 400
    # 损坏任务不可重复确认，重新选择原 ZIP 可重新校验并预览。
    replacement = import_zip(service, zip_data)
    assert service.status(replacement)['state'] == 'preview'


@pytest.mark.parametrize('missing_legacy', [False, True])
def test_active_authority_archive_roundtrip_ignores_stale_json(tmp_path, missing_legacy):
    from core.data.local_state_repository import activate_snapshots_at, read_snapshot_at
    base = tmp_path / 'source'
    base.mkdir()
    seed(base).close()
    db = base / 'data/system/db/cards_metadata.db'
    ui = json.loads((db.parent / 'ui_data.json').read_text(encoding='utf-8'))
    ui['a.png']['summary'] = 'SQLite authority'
    ui['a.png']['chat_ids'] = ['one.jsonl', 'two.jsonl']
    ui['_future'] = [None, 'unknown', {'opaque': 1}]
    chat = {'one.jsonl': {'summary': 'local note', 'bookmarks': [3, 8], 'reader_state': {'message_index': 9}}}
    activate_snapshots_at(str(db), ui, chat)
    if missing_legacy:
        (db.parent / 'ui_data.json').unlink()
    source = DataMigrationService(str(base))
    job = source.new_job('export')
    source.export(job)
    with zipfile.ZipFile(source.path(job, 'backup.zip')) as archive:
        exported_ui = json.loads(archive.read('db/ui_data.json'))
        assert exported_ui['a.png']['summary'] == 'SQLite authority'
        assert exported_ui['_future'] == ui['_future']
        assert '_plugins_v1' not in exported_ui
    target = tmp_path / 'target'
    restore_export(source, job, target)
    confirm_pending(str(target))
    restored_db = target / 'data/system/db/cards_metadata.db'
    restored = read_snapshot_at(str(restored_db), 'ui', str(restored_db.parent / 'ui_data.json'))
    assert restored['a.png']['summary'] == 'SQLite authority'
    assert restored['_future'] == ui['_future']
    assert restored['a.png']['chat_ids'] == ['one.jsonl', 'two.jsonl']
    assert str(base) not in restored['a.png']['resource_folder']
    with sqlite3.connect(restored_db) as conn:
        assert conn.execute('SELECT chat_id FROM chat_card_bindings ORDER BY chat_id').fetchall() == [('one.jsonl',), ('two.jsonl',)]
        assert conn.execute('SELECT state FROM local_state_migrations').fetchone()[0] == 'activated'
    assert read_snapshot_at(str(restored_db), 'chat', '')['one.jsonl']['summary'] == 'local note'


@pytest.mark.parametrize('damage', ['missing_table', 'missing_database', 'corrupt_database'])
def test_valid_archive_recovers_damaged_target_authority(tmp_path, damage):
    from core.data.local_state_repository import activate_snapshots_at
    source, export_job, source_conn = exported(tmp_path)
    source_conn.close()
    archive = Path(source.path(export_job, 'backup.zip')).read_bytes()
    target = tmp_path / 'target'
    target.mkdir()
    seed(target).close()
    db = target / 'data/system/db/cards_metadata.db'
    from core.data.local_state_repository import initialize
    initialize(str(db), str(db.parent / 'ui_data.json'), str(db.parent / 'chat_data.json'))
    activate_snapshots_at(str(db), {'_plugins_v1': {'local': {'config': {'secret': 'keep'}}}}, {})
    if damage == 'missing_table':
        with sqlite3.connect(db) as conn:
            conn.execute('DROP TABLE ui_records')
    elif damage == 'missing_database':
        db.unlink()
    else:
        db.write_bytes(b'damaged authority')
    service = DataMigrationService(str(target))
    job = import_zip(service, archive)
    service.update(job, state='restoring')
    service.prepare_restore(job)
    assert (target / 'data/migration/pending.json').is_file()
    assert any('插件' in warning for warning in service.status(job).get('warnings', []))
    restored = json.loads(Path(service.path(job, 'restore/db/ui_data.json')).read_text(encoding='utf-8'))
    assert restored['a.png']['summary'] == '备注'
    assert restored['_plugins_v1']['pet']['enabled'] is False
