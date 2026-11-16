"""可移植 ZIP：原始业务文件 + 脱敏设置 + SQLite backup API 快照。

恢复先写隔离代，再在下次启动、打开任何数据库之前切换固定目录。
"""
import hashlib
import json
import logging
import ntpath
import os
import re
import shutil
import sqlite3
import stat
import threading
import time
import unicodedata
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from core import config
from core.services.maintenance_gate import gate
from core.services.migration_paths import MigrationPaths
from core.utils.backup_recovery import durable_json, seal_restore
from core.utils.filesystem import walk_directory_strict
from core.version import APP_VERSION

FORMAT = 'st-manager-backup'
VERSION = 3
CHUNK = 1024 * 1024
MAX_BYTES = 100 * 1024 ** 3
MAX_FILES = 200000
MAX_MANIFEST_BYTES = 32 * CHUNK
MAX_SETTINGS_BYTES = 16 * CHUNK
MAX_COMPONENT_BYTES = 255
MAX_ARCHIVE_PATH_BYTES = 3072
MAX_ABSOLUTE_PATH_BYTES = 4095
PROCESS = uuid.uuid4().hex
logger = logging.getLogger(__name__)
FIXED = {'assets': 'data/assets', 'wallpapers': 'data/library/wallpapers',
         'db': 'data/system/db', 'automation': 'data/system/automation',
         'snapshots': 'data/system/backups', 'plugins': 'data/plugins'}
RESTORE_FIXED = {**FIXED, 'beautify_dir': 'data/library/beautify'}
LINKABLE_FIXED = frozenset({'assets', 'wallpapers', 'beautify_dir'})
DB_FILES = ('cards_metadata.db', 'ui_data.json', 'chat_data.json')
EXCLUDED = [
    '登录密码、Cookie、API Token、system/secrets.json（保留目标设备凭据）',
    '插件配置、私有命名空间、私有目录和私有表（可能含密钥；插件程序包含，恢复后禁用）',
    '回收站、缩略图、临时文件、运行锁、索引队列和可重建索引',
    'SillyTavern / TauriTavern 安装目录及其凭据、浏览器本地存储、未绑定的外部文件',
]
LOCAL_KEYS = {'host', 'port', 'st_url', 'st_data_dir', 'tt_data_dir', 'tt_api_url',
              'st_proxy', 'allowed_abs_resource_roots'}
SENSITIVE = re.compile(r'password|cookie|token|secret|api.?key|username|auth_', re.I)


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(CHUNK), b''):
            h.update(block)
    return h.hexdigest()


def safe_name(name):
    if not isinstance(name, str) or not name or '\\' in name or ntpath.splitdrive(name)[0]:
        raise ValueError('备份含非法路径')
    if len(name.encode('utf-8')) > MAX_ARCHIVE_PATH_BYTES:
        raise ValueError('完整相对路径超过跨平台限制（最多 3072 个 UTF-8 字节，另预留目标目录前缀）: ' + name)
    parts = name.split('/')
    for part in parts:
        if len(part.encode('utf-8')) > MAX_COMPONENT_BYTES:
            raise ValueError('文件或目录名超过跨平台限制（每段最多 255 个 UTF-8 字节）: ' + name)
        if (part in ('', '.', '..') or part[-1:] in (' ', '.') or
                re.search(r'[<>:"|?*\x00-\x1f]', part) or
                re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I)):
            raise ValueError('备份含不安全或跨平台不兼容路径: ' + name)
    return name


def validate_absolute_path(path):
    # 为原子写入的 .new / .tmp 后缀留出空间；也考虑 Android 路径别名的实际前缀。
    if max(len(os.path.abspath(path).encode('utf-8')),
           len(os.path.realpath(path).encode('utf-8'))) + 8 > MAX_ABSOLUTE_PATH_BYTES:
        raise ValueError('目标完整路径超过跨平台限制（4095 个 UTF-8 字节），请缩短数据根或目录层级: ' + path)


def validate_archive_paths(files, directories=()):
    """文件、显式目录和隐式祖先共用一个跨平台名称空间。"""
    nodes = {}
    explicit = set()
    for entries, kind in ((files, 'file'), (directories, 'directory')):
        for name in entries:
            safe_name(name)
            if name in explicit:
                raise ValueError('文件或目录清单重复: ' + name)
            explicit.add(name)
            parts = name.split('/')
            for depth in range(1, len(parts) + 1):
                original = '/'.join(parts[:depth])
                key = unicodedata.normalize('NFC', original).casefold()
                node_kind = kind if depth == len(parts) else 'directory'
                previous = nodes.get(key)
                if previous is not None and previous != (original, node_kind):
                    raise ValueError('文件、目录或祖先路径存在跨平台名称冲突: ' + original)
                nodes[key] = (original, node_kind)


def validate_archive_limits(infos):
    """生成与读取 ZIP 采用相同的条目数、元数据字节数和解压总量限制。"""
    if len(infos) > MAX_FILES + 2:
        raise ValueError('ZIP 文件数过多')
    for info in infos:
        if info.filename == 'manifest.json' and info.file_size > MAX_MANIFEST_BYTES:
            raise ValueError('清单过大（上限 32 MiB）')
        if info.filename == 'settings.json' and info.file_size > MAX_SETTINGS_BYTES:
            raise ValueError('设置过大（上限 16 MiB）')
    total = sum(info.file_size for info in infos)
    if total > MAX_BYTES:
        raise ValueError('解压大小超限')
    return total


def write_archive_json(archive, name, value, limit, *, indent=None):
    """逐块编码并按 UTF-8 实际字节限流，失败的半成品不会发布。"""
    size = 0
    buffer = bytearray()
    encoder = json.JSONEncoder(ensure_ascii=False, indent=indent)
    with archive.open(name, 'w', force_zip64=True) as output:
        for part in encoder.iterencode(value):
            block = part.encode('utf-8')
            size += len(block)
            if size > limit:
                raise ValueError(('清单' if name == 'manifest.json' else '设置') + '过大，无法生成可恢复的备份')
            buffer.extend(block)
            if len(buffer) >= 64 * 1024:
                output.write(buffer)
                buffer.clear()
        if buffer:
            output.write(buffer)


def source_entry_name(directory, name, canonical_names):
    """按实际文件身份识别内置名称，遵守源目录的大小写语义；读取失败不能视作缺失。"""
    if name in canonical_names:
        return name
    info = os.stat(os.path.join(directory, name))
    for canonical in canonical_names:
        try:
            expected = os.stat(os.path.join(directory, canonical))
        except FileNotFoundError:
            continue
        if os.path.samestat(info, expected):
            return canonical
    return None


def prune_plugin_directories(root, directory, dirs):
    """data 仅在 plugins/<id>/data 是私有目录；程序内部同名目录属于程序。"""
    relative = os.path.relpath(directory, root)
    plugin_root = relative != '.' and len(relative.replace('\\', '/').split('/')) == 1
    excluded = ('__pycache__', 'data', '.git', '.venv') if plugin_root else ('__pycache__',)
    dirs[:] = [name for name in dirs if source_entry_name(directory, name, excluded) is None]


def sqlite_snapshot(source, target):
    """只读源连接生成独立 SQLite 快照，包含已提交 WAL；失败不降级成裸文件复制。"""
    stalled_since = time.monotonic()
    def progress(status, remaining, total):
        nonlocal stalled_since
        if status not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            stalled_since = time.monotonic()
        if time.monotonic() - stalled_since > 60:
            raise ValueError('SQLite 快照超时，请停止外部写入后重试: ' + source)
        if shutil.disk_usage(os.path.dirname(target)).free < 32 * CHUNK:
            raise ValueError('SQLite 快照空间不足')

    with closing(sqlite3.connect(Path(source).as_uri() + '?mode=ro', uri=True)) as src:
        estimate = src.execute('PRAGMA page_count').fetchone()[0] * src.execute('PRAGMA page_size').fetchone()[0]
        if estimate > MAX_BYTES or shutil.disk_usage(os.path.dirname(target)).free < estimate + 32 * CHUNK:
            raise ValueError('SQLite 快照超过限制或空间不足: ' + source)
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst, pages=256, progress=progress, sleep=0.05)
            if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite 快照完整性检查失败: ' + source)



def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _within(path, root):
    try:
        return os.path.normcase(os.path.commonpath([path, root])) == os.path.normcase(root)
    except ValueError:
        return False


class DataMigrationService:
    def __init__(self, base=None):
        self.base = os.path.abspath(base or config.BASE_DIR)
        self.root = os.path.join(self.base, 'data', 'migration')
        self.lock = threading.RLock()
        os.makedirs(self.root, exist_ok=True)

    def path(self, job_id, filename='status.json'):
        if not re.fullmatch(r'[0-9a-f]{32}', job_id):
            raise ValueError('无效任务')
        return os.path.join(self.root, job_id, filename)

    def status(self, job_id):
        with self.lock:
            return self._read_status(job_id)

    def _read_status(self, job_id):
        with open(self.path(job_id), encoding='utf-8') as handle:
            result = json.load(handle)
        if result['state'] == 'restart_required':
            last = os.path.join(self.root, 'last-restore.json')
            if os.path.exists(last):
                with open(last, encoding='utf-8') as handle:
                    recovery = json.load(handle)
                if recovery.get('job') == job_id:
                    result.update(state=recovery['state'], phase=(
                        '恢复已完成，配置、数据库与缓存已通过启动验证；索引将在后台重建'
                        if recovery['state'] == 'complete'
                        else '恢复未通过验证或被中断，已自动回滚，现有数据已保留'))
                    if recovery.get('error'):
                        result['error'] = recovery['error']
            pending = os.path.join(self.root, 'pending.json')
            if os.path.exists(pending):
                with open(pending, encoding='utf-8') as handle:
                    plan = json.load(handle)
                if plan.get('job') == job_id and plan['state'] == 'awaiting_startup':
                    result.update(state='restart_required', phase='目录已切换，正在验证配置、数据库与缓存；尚未确认恢复成功')
        if result['state'] in ('queued', 'working', 'uploading', 'restoring', 'saving') and result.get('process') != PROCESS:
            result.update(state='failed', error='上次操作因进程退出而中断，请重新选择文件或重新导出')
        return result

    def update(self, job_id, **values):
        with self.lock:
            path = self.path(job_id)
            current = self.status(job_id) if os.path.exists(path) else {'id': job_id}
            current.update(values)
            durable_json(path, current)
            return current

    def new_job(self, kind):
        if os.path.exists(os.path.join(self.root, 'pending.json')):
            raise ValueError('已有待执行恢复，请先完全退出并重启应用')
        job = uuid.uuid4().hex
        self.update(job, kind=kind, state='queued', process=PROCESS, phase='等待处理', done=0, total=0)
        return job

    def run(self, job, operation):
        def worker():
            try:
                operation(job)
            except Exception as exc:
                logger.warning('数据迁移作业失败 %s: %s', job, exc)
                self.update(job, state='failed', phase='操作失败，当前资源库未改动', error=str(exc))
        threading.Thread(target=worker, daemon=True).start()

    def _config(self):
        path = os.path.join(self.base, 'config.json')
        try:
            with open(path, encoding='utf-8') as handle:
                return config.normalize_config(json.load(handle))
        except FileNotFoundError:
            return config.build_default_config()

    def roots(self, cfg):
        roots = {k: os.path.abspath(os.path.join(self.base, cfg[k]))
                 for k in config.RUNTIME_DIR_DEFAULTS}
        if cfg.get('st_openai_preset_dir'):
            roots['st_openai_preset_dir'] = os.path.abspath(os.path.join(self.base, cfg['st_openai_preset_dir']))
        roots.update({k: os.path.join(self.base, v) for k, v in FIXED.items()})
        # 绝对绑定可以在 resources_dir 白名单之外；按实际关联补入逻辑目录。
        ui = os.path.join(roots['db'], 'ui_data.json')
        if os.path.exists(ui):
            with open(ui, encoding='utf-8') as handle:
                data = json.load(handle)
            def collect(obj):
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        if key == 'resource_folder' and isinstance(value, str) and value.strip():
                            raw = value.strip().replace('\\', '/')
                            path = os.path.abspath(os.path.join(roots['resources_dir'], raw))
                            if not any(_within(path, r) for r in roots.values()):
                                roots['external_' + hashlib.sha256(path.encode()).hexdigest()[:12]] = path
                        elif key != '_plugins_v1':
                            collect(value)
                elif isinstance(obj, list):
                    for item in obj:
                        collect(item)
            collect(data)
        for path in cfg.get('allowed_abs_resource_roots', []):
            full = os.path.abspath(os.path.join(self.base, path))
            if not any(os.path.normcase(full) == os.path.normcase(r) for r in roots.values()):
                roots.setdefault('external_' + hashlib.sha256(full.encode()).hexdigest()[:12], full)
        return roots

    def root_links(self, roots, directories):
        """业务根可共享固定资源根，但固定根必须能够独立切换及回滚。"""
        movable = {slot: root for slot, root in roots.items() if slot not in RESTORE_FIXED}
        fixed = {slot: root for slot, root in roots.items() if slot in RESTORE_FIXED}
        for slot, path in fixed.items():
            for other, root in fixed.items():
                if slot != other and _within(path, root):
                    raise ValueError(f'暂不支持固定目录重叠: {slot} / {other}，请先分离目录')
        spellings = {(slot, os.path.normcase(relative)): relative
                     for slot, relative in (directory.split('/', 1) for directory in directories)}
        links = {}
        for slot, path in movable.items():
            for anchor, root in fixed.items():
                if ((_within(root, path) and not _within(path, root)) or
                        (_within(path, root) and anchor not in LINKABLE_FIXED)):
                    raise ValueError(f'暂不支持业务目录包含或覆盖固定目录（含系统目录）: {slot} / {anchor}，请先分离目录')
            parent = min((key for key, root in roots.items() if _within(path, root)),
                         key=lambda key: (len(roots[key]), key not in RESTORE_FIXED, key))
            if parent != slot:
                relative = os.path.relpath(path, roots[parent]).replace('\\', '/')
                relative = '' if relative == '.' else spellings.get((parent, os.path.normcase(relative)), relative)
                links[slot] = {'root': parent, 'relative': relative}
        return links

    def validate_root_links(self, manifest):
        """共享根必须与父目录的真实文件、空目录清单完全一致，不能藏掉冲突副本。"""
        links = manifest.get('root_links')
        if not isinstance(links, dict):
            raise ValueError('无效目录关联')
        roots = manifest['roots']
        files = {entry['path']: (entry['size'], entry['sha256']) for entry in manifest['files']}
        directories = manifest.get('directories', [])
        for slot, link in links.items():
            if not isinstance(link, dict) or set(link) != {'root', 'relative'}:
                raise ValueError('无效目录关联')
            parent, relative = link['root'], link['relative']
            if (not isinstance(parent, str) or slot not in roots or slot in RESTORE_FIXED or parent not in roots or
                    (parent in RESTORE_FIXED and parent not in LINKABLE_FIXED) or
                    parent == slot or parent in links or not isinstance(relative, str)):
                raise ValueError('无效目录关联目标')
            if relative:
                safe_name(relative)
                if parent + '/' + relative not in directories:
                    raise ValueError('共享目录在父目录清单中不存在')
            prefix = parent + '/' + (relative + '/' if relative else '')
            own = slot + '/'
            if ({name[len(own):]: value for name, value in files.items() if name.startswith(own)} !=
                    {name[len(prefix):]: value for name, value in files.items() if name.startswith(prefix)} or
                    {name[len(own):] for name in directories if name.startswith(own)} !=
                    {name[len(prefix):] for name in directories if name.startswith(prefix)}):
                raise ValueError('共享目录与父目录的备份内容不一致')
        return links

    def request_restore(self, job):
        with self.lock:
            state = self.status(job)
            if state['state'] != 'preview':
                raise ValueError('请先校验并预览')
            state.update(state='restoring', phase='准备恢复与自动保护')
            durable_json(self.path(job), state)
        self.run(job, self.prepare_restore)

    def required_source_authorizations(self):
        """只为当前无法读取的外部根复用 Android 按需授权，不为默认备份申请权限。"""
        required = []
        for root in self.roots(self._config()).values():
            if _within(root, self.base):
                continue
            try:
                with os.scandir(root) as entries:
                    next(entries, None)
            except PermissionError:
                required.append(root)
        return sorted(set(required))

    def inventory(self, roots):
        result = []
        for slot, root in roots.items():
            # 已配置业务根必须存在；固定的可选目录允许尚未创建。
            try:
                info = os.lstat(root)
            except FileNotFoundError:
                if slot in FIXED:
                    continue
                raise
            if not stat.S_ISDIR(info.st_mode) or getattr(os.path, 'isjunction', lambda _: False)(root):
                raise ValueError('目录不存在: ' + root)
            if slot not in FIXED:
                recursive = _within(self.root, root)
                private = any(_within(root, reserved) for reserved in (
                    os.path.join(self.base, 'data', 'system'),
                    os.path.join(self.base, 'data', 'plugins'),
                ))
                if _within(root, self.root):
                    relative = os.path.relpath(root, self.root).replace('\\', '/')
                    private = private or not re.match(r'^[0-9a-f]{32}/library/[^/]+(?:/|$)', relative)
                if recursive or private:
                    raise ValueError('业务目录覆盖应用系统/备份目录，请先配置独立的资源目录: ' + root)
            for directory, dirs, files in walk_directory_strict(root):
                dirs.sort()
                for name in list(dirs):
                    path = os.path.join(directory, name)
                    if os.path.islink(path) or getattr(os.path, 'isjunction', lambda _: False)(path):
                        raise ValueError('不支持符号链接/目录联接: ' + path)
                if slot == 'plugins':
                    prune_plugin_directories(root, directory, dirs)
                for name in sorted(files):
                    path = os.path.join(directory, name)
                    rel = os.path.relpath(path, root).replace('\\', '/')
                    if slot == 'db':
                        rel = source_entry_name(root, rel, DB_FILES)
                        if rel is None:
                            continue
                    if slot == 'snapshots' and rel.startswith('user_db/'):
                        continue
                    if not stat.S_ISREG(os.lstat(path).st_mode):
                        raise ValueError('不支持特殊文件: ' + path)
                    info = os.stat(path)
                    safe_name(slot + '/' + rel)
                    result.append((slot, rel, path, info.st_size, info.st_mtime_ns))
        if len(result) > MAX_FILES or sum(row[3] for row in result) > MAX_BYTES:
            raise ValueError('超出备份限制（20 万文件 / 100 GiB）')
        validate_archive_paths([row[0] + '/' + row[1] for row in result])
        return result

    def directories(self, roots):
        result = []
        for slot, root in roots.items():
            if slot in FIXED and not os.path.exists(root):
                continue
            for directory, dirs, _ in walk_directory_strict(root):
                if slot == 'plugins':
                    prune_plugin_directories(root, directory, dirs)
                dirs.sort()
                for name in dirs:
                    result.append(safe_name(slot + '/' + os.path.relpath(os.path.join(directory, name), root).replace('\\', '/')))
        if len(result) > MAX_FILES:
            raise ValueError('目录数超过限制')
        validate_archive_paths((), result)
        return result

    def snapshot_inventory(self, roots):
        """按 SQLite 文件头识别主文件，只排除其配套日志；其他同后缀附件全部保留。"""
        rows = self.inventory(roots)
        databases = set()
        for _, _, path, *_ in rows:
            key = os.path.normcase(os.path.abspath(path))
            if key not in databases:
                with open(path, 'rb') as handle:
                    if handle.read(16) == b'SQLite format 3\x00':
                        databases.add(key)
        runtime = set()
        # SHM 仅为锁/读标记，快照的只读连接可能创建或更新它；WAL/journal 才承载事务数据。
        journals = {}
        for database in sorted(databases):
            for suffix in ('-wal', '-shm', '-journal'):
                path = database + suffix
                try:
                    info = os.lstat(path)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError('SQLite 日志不是普通文件: ' + path)
                with open(path, 'rb') as handle:
                    header = handle.read(8)
                if suffix == '-wal':
                    recognized = not info.st_size or (info.st_size >= 32 and
                                                       header[:4] in (b'7\x7f\x06\x82', b'7\x7f\x06\x83'))
                elif suffix == '-shm':
                    recognized = not info.st_size or (info.st_size >= 96 and header[:4] in (
                        (3007000).to_bytes(4, 'little'), (3007000).to_bytes(4, 'big')))
                else:
                    recognized = not info.st_size or header in (b'\x00' * 8, b'\xd9\xd5\x05\xf9\x20\xa1\x63\xd7')
                if not recognized:
                    raise ValueError('SQLite 配套文件格式不明确，不能安全替代或遗漏: ' + path)
                runtime.add(path)
                # 空日志或只有 WAL 头没有提交帧，不影响逻辑快照。
                if suffix != '-shm' and info.st_size > (32 if suffix == '-wal' else 0):
                    journals[path] = (info.st_size, info.st_mtime_ns)
        files = [row for row in rows if os.path.normcase(os.path.abspath(row[2])) not in runtime]
        return files, databases, journals

    def _rewrite_db(self, path, paths, history=None):
        with closing(sqlite3.connect(path)) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('数据库校验失败')
            # FTS shadow 表不可直接 DELETE（会破坏 FTS 内部结构）。先删除虚拟表，
            # SQLite 自动移除 shadow 表，启动初始化会重新建立可重建索引。
            virtuals = list(conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE 'CREATE VIRTUAL TABLE%'").fetchall())
            for (table,) in virtuals:
                if table.startswith(('index_', 'plugin_')):
                    conn.execute('DROP TABLE ' + _quote(table))
            tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for table in tables:
                if table.startswith('sqlite_'):
                    continue
                if table.startswith(('index_', 'plugin_')) or table == 'scan_runtime_state':
                    conn.execute('DELETE FROM ' + _quote(table))
                    continue
                columns = [r[1] for r in conn.execute('PRAGMA table_info(' + _quote(table) + ')')]
                # rowid 保留所有表主键和业务关联；仅修改 TEXT 内容。
                rows = conn.execute('SELECT rowid, * FROM ' + _quote(table))
                for row in rows:
                    values = []
                    for column, value in zip(columns, row[1:]):
                        if column == 'scope_key' and history:
                            value = history.get(value, value)
                        elif table == 'ui_data_cache' and column == 'resource_folder':
                            value = paths.binding(value)
                        elif table == 'wi_history_roots' and column == 'roots_json':
                            roots = json.loads(value)
                            value = json.dumps({key: paths.path(root) for key, root in roots.items()}, ensure_ascii=False)
                        values.append(value)
                    if tuple(values) != tuple(row[1:]):
                        conn.execute('UPDATE ' + _quote(table) + ' SET ' +
                                     ','.join(_quote(c) + '=?' for c in columns) + ' WHERE rowid=?',
                                     values + [row[0]])
            conn.commit()
            # 删除页中的凭据/插件数据也不能随快照泄漏。
            conn.execute('VACUUM')

    def _history_map(self, rows, roots, to_portable=True, *, paths=None, previous_roots=None):
        from core.services.wi_entry_history_service import _scope_path

        contexts = [{'base': self.base, **roots}]
        if previous_roots:
            contexts.append({**contexts[0], **previous_roots})
        contexts = [{key: os.path.abspath(value) for key, value in context.items()} for context in contexts]
        result = {}
        for slot, rel, *_ in rows:
            if (not rel.lower().endswith('.json') or
                    (to_portable and slot not in ('world_info_dir', 'resources_dir') and not slot.startswith('external_'))):
                continue
            full = os.path.join(roots[slot], rel)
            for stype in ('global', 'resource', 'lorebook'):
                if to_portable:
                    # 与绑定和备注使用同一个选择器；不能让后遍历的父根改写子根。
                    token = f'stm-history:{stype}:' + paths.path(full)[len('stm://'):]
                    for context in contexts:
                        previous = os.path.join(context[slot], rel)
                        for path in (_scope_path(previous, context),
                                     os.path.normpath(previous).replace('\\', '/')):
                            key = hashlib.sha1(f'{stype}|{path}'.encode()).hexdigest()
                            if key in result and result[key] != token:
                                raise ValueError('历史定位键存在歧义，请先完成旧历史路径转换后重试')
                            result[key] = token
                else:
                    token = f'stm-history:{stype}:{slot}/{rel}'
                    scope_path = _scope_path(full, contexts[0])
                    result[token] = hashlib.sha1(f'{stype}|{scope_path}'.encode()).hexdigest()
        return result

    def export(self, job):
        self.update(job, state='working', phase='等待资源写入、扫描及插件作业完成')
        with gate.exclusive():
            cfg = self._config()
            roots = self.roots(cfg)
            self.root_links(roots, ())  # 在资源读取和快照之前拒绝不能原子切换的重叠组合。
            rows, sqlite_sources, journals = self.snapshot_inventory(roots)
            directories = self.directories(roots)
            validate_archive_paths([row[0] + '/' + row[1] for row in rows], directories)
            if not any(r[0] == 'db' and r[1] == 'cards_metadata.db' for r in rows):
                raise ValueError('数据库尚未创建，请等待应用初始化完成')
            total = sum(r[3] for r in rows) + sum(size for size, _ in journals.values())
            if shutil.disk_usage(self.root).free < total * 2 + 64 * CHUNK:
                raise ValueError('空间不足：备份暂存至少需要原数据两倍可用空间')
            paths = MigrationPaths(self.base, roots, rows, directories=directories,
                                   exporting=True, casefold=os.name == 'nt')
            history = self._history_map(rows, roots, paths=paths)
            manifest = {'format': FORMAT, 'version': VERSION, 'app_version': APP_VERSION,
                        'created_at': datetime.now(timezone.utc).isoformat(), 'complete': True,
                        'excluded': EXCLUDED, 'roots': list(roots), 'root_links': self.root_links(roots, directories),
                        'files': [], 'directories': directories}
            settings = {k: v for k, v in cfg.items() if k in config.DEFAULT_CONFIG and
                        k not in roots and k not in LOCAL_KEYS and not SENSITIVE.search(k)}
            stage = self.path(job, 'snapshot')
            os.makedirs(stage, exist_ok=True)
            done = 0
            packed_size = 0
            with zipfile.ZipFile(self.path(job, 'backup.zip.part'), 'w', zipfile.ZIP_DEFLATED,
                                 allowZip64=True) as archive:
                for slot, rel, source, size, mtime in rows:
                    name = f'{slot}/{rel}'
                    target = os.path.join(stage, 'file')
                    self.update(job, phase='收集与校验原文件', done=done, total=total)
                    is_sqlite = os.path.normcase(os.path.abspath(source)) in sqlite_sources
                    if name == 'db/cards_metadata.db' or is_sqlite:
                        # 只读源连接也避免「最后一个可写连接关闭」触发 WAL checkpoint，
                        # 改变源主文件并被外部变更检测误判。
                        sqlite_snapshot(source, target)
                    if name == 'db/cards_metadata.db':
                        # 兼容尚未完成旧绝对路径历史转换的库；只修改快照。
                        with closing(sqlite3.connect(target)) as db:
                            if db.execute("SELECT 1 FROM sqlite_master WHERE name='wi_history_roots'").fetchone():
                                previous = db.execute('SELECT roots_json FROM wi_history_roots WHERE id=1').fetchone()
                                if previous:
                                    old_roots = json.loads(previous[0])
                                    history = self._history_map(rows, roots, paths=paths, previous_roots=old_roots)
                        self._rewrite_db(target, paths, history)
                    elif name in ('db/ui_data.json', 'db/chat_data.json'):
                        with open(source, encoding='utf-8') as handle:
                            value = json.load(handle)
                        if name == 'db/ui_data.json':
                            # 未知插件数据不能安全脱敏；保留目标设备的配置/私有数据。
                            value.pop('_plugins_v1', None)
                        durable_json(target, paths.ui(value) if name == 'db/ui_data.json' else value)
                    elif not is_sqlite:
                        shutil.copyfile(source, target)
                    if os.stat(source).st_size != size or os.stat(source).st_mtime_ns != mtime:
                        raise ValueError('备份期间文件发生变更，请停止外部编辑后重试: ' + source)
                    packed_size += os.path.getsize(target)
                    if packed_size > MAX_BYTES:
                        raise ValueError('快照解压总大小超过 100 GiB 限制')
                    entry = {'path': name, 'type': slot, 'size': os.path.getsize(target), 'sha256': digest(target)}
                    if is_sqlite:
                        entry['storage'] = 'sqlite_snapshot'
                    manifest['files'].append(entry)
                    archive.write(target, name)
                    os.remove(target)
                    done += size
                if (rows, sqlite_sources, journals) != self.snapshot_inventory(roots) or directories != self.directories(roots):
                    raise ValueError('备份期间目录发生变更，请重试')
                if not any(e['path'] == 'db/ui_data.json' for e in manifest['files']):
                    raw = b'{}'
                    archive.writestr('db/ui_data.json', raw)
                    manifest['files'].append({'path': 'db/ui_data.json', 'type': 'db', 'size': 2,
                                              'sha256': hashlib.sha256(raw).hexdigest()})
                write_archive_json(archive, 'settings.json', paths.settings(settings), MAX_SETTINGS_BYTES)
                # settings 也必须纳入校验清单。
                raw = archive.read('settings.json')
                manifest['files'].append({'path': 'settings.json', 'type': 'settings',
                                          'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
                self.validate_root_links(manifest)
                write_archive_json(archive, 'manifest.json', manifest, MAX_MANIFEST_BYTES, indent=2)
                validate_archive_limits(archive.infolist())
            if os.path.getsize(self.path(job, 'backup.zip.part')) > MAX_BYTES:
                raise ValueError('ZIP 大小超过传输限制，无法生成可恢复的备份')
            os.replace(self.path(job, 'backup.zip.part'), self.path(job, 'backup.zip'))
            self.update(job, state='ready', phase='备份已生成，请选择保存位置', done=total, total=total,
                        filename='ST-Manager-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip')

    def receive(self, job, stream):
        self.update(job, state='uploading', phase='接收备份文件')
        target = self.path(job, 'upload.zip.part')
        count = 0
        with open(target, 'xb') as handle:
            for block in iter(lambda: stream.read(CHUNK), b''):
                count += len(block)
                if count > MAX_BYTES or shutil.disk_usage(self.root).free < len(block) + 32 * CHUNK:
                    raise ValueError('备份超过限制或暂存空间不足')
                handle.write(block)
        os.replace(target, self.path(job, 'upload.zip'))

    def validate(self, job):
        self.update(job, state='working', phase='校验 ZIP 与文件清单')
        stage = self.path(job, 'restore')
        validate_absolute_path(stage)
        os.makedirs(stage, exist_ok=False)
        with zipfile.ZipFile(self.path(job, 'upload.zip')) as archive:
            infos = archive.infolist()
            total = validate_archive_limits(infos)
            validate_archive_paths([info.filename for info in infos])
            names = set()
            for info in infos:
                safe_name(info.orig_filename)
                safe_name(info.filename)
                key = unicodedata.normalize('NFC', info.filename).casefold()
                mode = info.external_attr >> 16
                if (key in names or info.is_dir() or info.flag_bits & 1 or
                        stat.S_IFMT(mode) not in (0, stat.S_IFREG)):
                    raise ValueError('ZIP 含重复、链接、加密或特殊条目')
                names.add(key)
            for key in names:
                if any('/'.join(key.split('/')[:i]) in names for i in range(1, len(key.split('/')))):
                    raise ValueError('ZIP 文件与目录冲突')
            if shutil.disk_usage(self.root).free < total * 2 + 64 * CHUNK:
                raise ValueError('解压大小超限或空间不足')
            if 'manifest.json' not in archive.namelist() or 'settings.json' not in archive.namelist():
                raise ValueError('缺少备份清单或设置')
            manifest = json.loads(archive.read('manifest.json'))
            if (manifest.get('format') != FORMAT or manifest.get('version') != VERSION or
                    manifest.get('complete') is not True):
                raise ValueError('不支持的版本或不完整备份')
            def version_tuple(value):
                match = re.match(r'^(\d+)\.(\d+)(?:\.(\d+))?', str(value))
                if not match:
                    raise ValueError('备份应用版本无效')
                return tuple(int(v or 0) for v in match.groups())
            if version_tuple(manifest.get('app_version')) > version_tuple(APP_VERSION):
                raise ValueError('备份来自更新的应用版本，请先升级目标设备应用')
            roots = manifest['roots']
            allowed = set(config.RUNTIME_DIR_DEFAULTS) | set(FIXED) | {'st_openai_preset_dir'}
            if (not isinstance(roots, list) or len(roots) != len(set(roots)) or
                    any(r not in allowed and not re.fullmatch(r'external_[0-9a-f]{12}', r) for r in roots)):
                raise ValueError('未知逻辑目录')
            if not (set(config.RUNTIME_DIR_DEFAULTS) | set(FIXED)).issubset(roots):
                raise ValueError('备份缺少核心逻辑目录')
            expected = {}
            for entry in manifest['files']:
                name = safe_name(entry['path'])
                if name in expected or (name != 'settings.json' and name.split('/')[0] not in roots):
                    raise ValueError('无效文件清单')
                if name.startswith('db/') and name not in (
                        'db/cards_metadata.db', 'db/ui_data.json', 'db/chat_data.json'):
                    raise ValueError('备份包含非契约数据库文件')
                if name == 'settings.json' and entry.get('type') != 'settings':
                    raise ValueError('无效设置清单')
                expected[name] = entry
            if set(expected) | {'manifest.json'} != {i.filename for i in infos}:
                raise ValueError('ZIP 与清单不一致')
            directories = manifest.get('directories', [])
            if not isinstance(directories, list) or len(directories) > MAX_FILES:
                raise ValueError('目录清单超限')
            validate_archive_paths([info.filename for info in infos], directories)
            root_links = self.validate_root_links(manifest)
            self.validate_destination_paths(job, manifest, root_links)
            seen = set(names)
            for directory in directories:
                safe_name(directory)
                key = unicodedata.normalize('NFC', directory).casefold()
                if directory.split('/')[0] not in roots or key in seen:
                    raise ValueError('目录清单重复或与文件冲突')
                if any('/'.join(key.split('/')[:i]) in names for i in range(1, len(key.split('/')))):
                    raise ValueError('目录清单与文件冲突')
                seen.add(key)
                os.makedirs(os.path.join(stage, *directory.split('/')), exist_ok=True)
            done = 0
            for name, entry in expected.items():
                info = archive.getinfo(name)
                if info.file_size != entry['size']:
                    raise ValueError('文件大小校验失败')
                target = os.path.join(stage, *name.split('/'))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                h = hashlib.sha256()
                with archive.open(info) as src, open(target, 'xb') as dst:
                    for block in iter(lambda: src.read(CHUNK), b''):
                        h.update(block)
                        dst.write(block)
                        done += len(block)
                if h.hexdigest() != entry['sha256']:
                    raise ValueError('SHA-256 校验失败: ' + name)
                if entry.get('storage') == 'sqlite_snapshot':
                    try:
                        uri = Path(target).as_uri() + '?mode=ro&immutable=1'
                        with closing(sqlite3.connect(uri, uri=True)) as snapshot:
                            if snapshot.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                                raise ValueError('SQLite 附件快照完整性检查失败: ' + name)
                    except sqlite3.DatabaseError as exc:
                        raise ValueError('SQLite 附件快照损坏: ' + name) from exc
                self.update(job, phase='校验并暂存原文件', done=done, total=total)
        durable_json(self.path(job, 'manifest.json'), manifest)
        for slot in roots:
            os.makedirs(os.path.join(stage, slot), exist_ok=True)
        db = os.path.join(stage, 'db', 'cards_metadata.db')
        if not os.path.isfile(db) or not os.path.isfile(os.path.join(stage, 'db', 'ui_data.json')):
            raise ValueError('备份缺少数据库或备注数据')
        # 升级检查会写库，预览使用副本，待恢复文件保持 ZIP 中的原始校验值。
        schema_check = self.path(job, 'schema-check.db')
        try:
            shutil.copyfile(db, schema_check)
            with closing(sqlite3.connect(schema_check)) as conn:
                from core.data.db_session import validate_migration_database
                validate_migration_database(conn)
        finally:
            for suffix in ('', '-wal', '-shm', '-journal'):
                if os.path.exists(schema_check + suffix):
                    os.remove(schema_check + suffix)
        with open(os.path.join(stage, 'settings.json'), encoding='utf-8') as handle:
            settings = json.load(handle)
        if not isinstance(settings, dict):
            raise ValueError('备份设置必须是 JSON 对象')
        warnings = ['插件依赖可能不兼容目标平台，恢复后请检查并按需重新安装；插件配置与私有数据需另行迁移']
        if 'active_automation_ruleset' not in settings:
            warnings.append('此备份未包含全局自动化启用设置，恢复后默认关闭；请重新选择规则，或在源设备重新导出')
        self.update(job, state='preview', phase='校验通过，请确认恢复',
                    manifest_sha256=digest(self.path(job, 'manifest.json')), preview={
            'created_at': manifest['created_at'], 'app_version': manifest['app_version'],
            'files': len(expected), 'bytes': total, 'excluded': EXCLUDED,
            'targets': self.targets(job, roots, root_links),
            'warnings': warnings,
            'overwrite': '重启后替换应用设置、用户数据库、壁纸、自动化规则、快照和插件程序；业务原文件写入隔离代。旧数据保留在自动保护目录。插件恢复后禁用。',
        })

    def verify_restore_stage(self, job):
        """在维护锁内复核预览清单及完整暂存树，任何变化都不能进入目录切换。"""
        message = '待恢复数据已变化或无法读取，请重新选择备份并预览'
        try:
            stage = self.path(job, 'restore')
            manifest_path = self.path(job, 'manifest.json')
            for path in (self.root, self.path(job, ''), stage, manifest_path):
                info = os.lstat(path)
                if stat.S_ISLNK(info.st_mode) or getattr(os.path, 'isjunction', lambda _: False)(path):
                    raise ValueError('暂存路径包含链接')
            expected_hash = self.status(job).get('manifest_sha256')
            if not expected_hash or digest(manifest_path) != expected_hash:
                raise ValueError('预览清单已变化')
            with open(manifest_path, encoding='utf-8') as handle:
                manifest = json.load(handle)
            expected = {entry['path']: entry for entry in manifest['files']}
            directories = set(manifest['directories']) | set(manifest['roots'])
            for name in expected:
                parts = name.split('/')
                directories.update('/'.join(parts[:i]) for i in range(1, len(parts)))
            found_files, found_dirs = set(), set()
            for directory, dirs, files in walk_directory_strict(stage):
                for name in dirs + files:
                    path = os.path.join(directory, name)
                    relative = os.path.relpath(path, stage).replace('\\', '/')
                    info = os.lstat(path)
                    if getattr(os.path, 'isjunction', lambda _: False)(path):
                        raise ValueError('暂存目录包含链接')
                    if stat.S_ISDIR(info.st_mode):
                        found_dirs.add(relative)
                    elif stat.S_ISREG(info.st_mode):
                        found_files.add(relative)
                    else:
                        raise ValueError('暂存区包含链接或特殊文件')
            if found_files != set(expected) or found_dirs != directories:
                raise ValueError('暂存文件或目录清单已变化')
            total = sum(entry['size'] for entry in expected.values())
            done = 0
            for name, entry in expected.items():
                path = os.path.join(stage, *name.split('/'))
                before = os.stat(path)
                if before.st_size != entry['size'] or digest(path) != entry['sha256']:
                    raise ValueError('暂存文件校验失败: ' + name)
                after = os.stat(path)
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('复核期间文件发生变化: ' + name)
                done += entry['size']
                self.update(job, phase='确认恢复：重新校验暂存文件', done=done, total=total)
            if digest(manifest_path) != expected_hash:
                raise ValueError('复核期间清单发生变化')
            return manifest
        except (OSError, ValueError, KeyError, TypeError) as exc:
            error = message + ': ' + str(exc)
            self.update(job, state='failed', phase='恢复已停止，当前资源库未改动', error=error)
            raise ValueError(error) from exc

    def targets(self, job, roots, root_links=None):
        targets = {slot: os.path.join(self.base, RESTORE_FIXED[slot]) if slot in RESTORE_FIXED else
                   self.path(job, 'library/' + slot) for slot in roots}
        for slot, link in (root_links or {}).items():
            targets[slot] = os.path.join(targets[link['root']], *link['relative'].split('/'))
        return targets

    def validate_destination_paths(self, job, manifest, root_links):
        targets = self.targets(job, manifest['roots'], root_links)
        names = set(manifest['directories']) | {entry['path'] for entry in manifest['files']}
        names.update(manifest['roots'])
        for name in names:
            validate_absolute_path(self.path(job, 'restore/' + name))
            slot, _, relative = name.partition('/')
            if slot in targets:
                validate_absolute_path(os.path.join(targets[slot], relative))
                if slot in RESTORE_FIXED:
                    validate_absolute_path(self.path(job, 'protection/' + name))

    def import_legacy_ui(self, data):
        """旧附加信息 JSON 做合并，不导入插件执行开关或覆盖原文件。"""
        from core.data.ui_store import update_ui_data, UI_DATA_FILE
        from core.services.cache_service import schedule_reload
        if not isinstance(data, dict) or len(json.dumps(data, ensure_ascii=False)) > 16 * CHUNK:
            raise ValueError('请提供有效的 ui_data.json（不超过 16 MiB）')
        if 'format' in data or 'version' in data or any(
                not k.startswith('_') and not isinstance(v, dict) for k, v in data.items()):
            raise ValueError('此文件不是旧备注与标签数据，请使用对应的导入入口')
        clean = {k: v for k, v in data.items() if k != '_plugins_v1'}
        with gate.activity():
            if os.path.exists(UI_DATA_FILE):
                shutil.copyfile(UI_DATA_FILE, UI_DATA_FILE + '.before-legacy-import')
            def merge(current):
                for key, value in clean.items():
                    if isinstance(value, dict) and isinstance(current.get(key), dict):
                        current[key].update(value)
                    else:
                        current[key] = value
                return current
            if not update_ui_data(merge):
                raise ValueError('附加信息保存失败，原数据已保留')
            schedule_reload(reason='legacy_ui_import')
        return len(clean)

    def prepare_restore(self, job):
        with gate.exclusive():
            if self.status(job)['state'] != 'restoring':
                raise ValueError('请先校验并预览备份')
            journal = os.path.join(self.root, 'pending.json')
            if os.path.exists(journal):
                raise ValueError('已有待执行恢复，请先重启')
            manifest = self.verify_restore_stage(job)
            stage = self.path(job, 'restore')
            root_links = self.validate_root_links(manifest)
            self.validate_destination_paths(job, manifest, root_links)
            targets = self.targets(job, manifest['roots'], root_links)
            paths = MigrationPaths(self.base, targets)
            with open(os.path.join(stage, 'settings.json'), encoding='utf-8') as handle:
                imported = json.load(handle)
            # 旧 ZIP 没有此字段，不能沿用即将被替换的目标规则集选择。
            imported.setdefault('active_automation_ruleset', config.DEFAULT_CONFIG['active_automation_ruleset'])
            cfg = self._config()
            for key, value in imported.items():
                if key in config.DEFAULT_CONFIG and key not in LOCAL_KEYS and not SENSITIVE.search(key):
                    cfg[key] = paths.settings({key: value})[key]
            for key in config.RUNTIME_DIR_DEFAULTS:
                cfg[key] = targets[key].replace('\\', '/')
            cfg['st_openai_preset_dir'] = targets.get('st_openai_preset_dir', '')
            cfg['allowed_abs_resource_roots'] = [v for k, v in targets.items() if k.startswith('external_')]
            for name in ('ui_data.json', 'chat_data.json'):
                path = os.path.join(stage, 'db', name)
                if not os.path.exists(path):
                    continue
                with open(path, encoding='utf-8') as handle:
                    value = json.load(handle)
                if name == 'ui_data.json':
                    value = paths.ui(value)
                if name == 'ui_data.json':
                    # 保留本机插件凭据，但禁用全部插件，显式由用户重新启用。
                    value.pop('_plugins_v1', None)
                    current = os.path.join(self.base, FIXED['db'], name)
                    if os.path.exists(current):
                        with open(current, encoding='utf-8') as handle:
                            plugins = json.load(handle).get('_plugins_v1', {})
                        value['_plugins_v1'] = plugins
                        for directory in os.listdir(os.path.join(stage, 'plugins')):
                            plugins.setdefault(directory, {})
                        for item in plugins.values():
                            if isinstance(item, dict):
                                item['enabled'] = False
                if name == 'ui_data.json':
                    plugins = value.setdefault('_plugins_v1', {})
                    for directory in os.listdir(os.path.join(stage, 'plugins')):
                        plugins.setdefault(directory, {})['enabled'] = False
                durable_json(path, value)
            rows = [(e['path'].split('/', 1)[0], e['path'].split('/', 1)[1])
                    for e in manifest['files'] if '/' in e['path']]
            with closing(sqlite3.connect(os.path.join(stage, 'db', 'cards_metadata.db'))) as conn:
                from core.data.db_session import validate_migration_database
                validate_migration_database(conn)
            self._rewrite_db(os.path.join(stage, 'db', 'cards_metadata.db'), paths,
                             self._history_map(rows, targets, to_portable=False))
            durable_json(os.path.join(stage, 'config.json'), cfg)
            moves = []
            for slot, target in targets.items():
                source = os.path.join(stage, slot)
                if slot in root_links:
                    continue  # 文件已随完整父根切换，保留暂存副本供检查。
                if slot not in RESTORE_FIXED:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    os.replace(source, target)
                    continue
                moves.append({'source': os.path.relpath(source, self.base).replace('\\', '/'),
                              'target': RESTORE_FIXED[slot], 'old': os.path.relpath(self.path(job, 'protection/' + slot), self.base).replace('\\', '/')})
            moves.append({'source': os.path.relpath(os.path.join(stage, 'config.json'), self.base).replace('\\', '/'),
                          'target': 'config.json', 'old': os.path.relpath(self.path(job, 'protection/config.json'), self.base).replace('\\', '/')})
            self.update(job, phase='生成转换后数据的启动校验清单')
            seal = seal_restore(self.base, job, moves)
            durable_json(journal, {'state': 'pending', 'job': job, 'moves': moves, **seal})
            self.update(job, state='restart_required', phase='恢复已暂存，请完全退出并重新启动应用',
                        protection=self.path(job, 'protection'))
