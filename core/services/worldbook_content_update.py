"""Whole-file worldbook updates with a verified rollback snapshot."""
import hashlib
import json
import os
import re
import stat
import tempfile
import threading
import time
from datetime import datetime
from urllib.parse import urljoin, urlsplit

import requests

from core.utils.filesystem import cleanup_old_snapshots

MAX_SOURCE_BYTES = 10 * 1024 * 1024
# Bounded lock storage; unrelated targets can occasionally serialize harmlessly.
_TARGET_LOCKS = [threading.RLock() for _ in range(64)]


class WorldbookUpdateError(ValueError):
    def __init__(self, message, code='invalid_source', status=400):
        super().__init__(message)
        self.code = code
        self.status = status


def worldbook_target_lock(path):
    identity = os.path.normcase(os.path.realpath(path or '.'))
    index = int(hashlib.sha256(os.fsencode(identity)).hexdigest()[:8], 16) % len(_TARGET_LOCKS)
    return _TARGET_LOCKS[index]


def _under(path, root):
    try:
        path, root = os.path.normcase(path), os.path.normcase(root)
        return os.path.commonpath([path, root]) == root
    except ValueError:
        return False


def resolve_update_target(path, source_type, cfg, base_dir, cards_dir):
    if source_type not in ('global', 'resource'):
        raise WorldbookUpdateError('仅独立世界书支持更新内容', 'unsupported_target')
    if not isinstance(path, str) or not path or '\x00' in path:
        raise WorldbookUpdateError('世界书路径无效', 'invalid_target')
    absolute = os.path.abspath(path if os.path.isabs(path) else os.path.join(base_dir, path))
    real_path = os.path.realpath(absolute)
    raw_root = cfg.get('world_info_dir', 'lorebooks') if source_type == 'global' else cfg.get('resources_dir', 'resources')
    absolute_root = os.path.abspath(raw_root if os.path.isabs(raw_root) else os.path.join(base_dir, raw_root))
    root = os.path.realpath(absolute_root)
    if (_under(real_path, os.path.realpath(str(cards_dir)))
            or not _under(absolute, absolute_root) or not _under(real_path, root)
            or not real_path.lower().endswith('.json')):
        raise WorldbookUpdateError('世界书路径不在允许的独立书目录中', 'invalid_target')
    if source_type == 'resource' and '/lorebooks/' not in '/' + os.path.relpath(real_path, root).replace('\\', '/') + '/':
        raise WorldbookUpdateError('资源世界书路径无效', 'invalid_target')
    # Do not replace a symlink itself or silently redirect the selected file.
    if os.path.islink(absolute):
        raise WorldbookUpdateError('请选取实际世界书文件，不能更新符号链接', 'invalid_target')
    if not os.path.isfile(real_path):
        raise WorldbookUpdateError('世界书已移走或删除，请刷新列表', 'target_missing', 404)
    return absolute


def _bounded_read(handle):
    raw = handle.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise WorldbookUpdateError('世界书文件不能超过 10 MiB', 'source_too_large', 413)
    return raw


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise WorldbookUpdateError('JSON 包含重复字段，无法安全比较')
        result[key] = value
    return result


def parse_worldbook(raw):
    if isinstance(raw, str):
        try:
            raw = raw.encode('utf-8')
        except UnicodeError as exc:
            raise WorldbookUpdateError('世界书必须为 UTF-8 JSON') from exc
    if len(raw) > MAX_SOURCE_BYTES:
        raise WorldbookUpdateError('世界书文件不能超过 10 MiB', 'source_too_large', 413)
    try:
        text = raw.decode('utf-8-sig')
        content = json.loads(text, object_pairs_hook=_unique_pairs,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise WorldbookUpdateError('无法读取有效的 UTF-8 JSON 世界书') from exc
    if not isinstance(content, dict) or not isinstance(content.get('entries'), (dict, list)):
        raise WorldbookUpdateError('世界书必须包含 entries 对象或数组')
    entries = content['entries'].values() if isinstance(content['entries'], dict) else content['entries']
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('content'), str):
            raise WorldbookUpdateError('每个世界书条目必须为对象，并包含文字 content')
        for key in ('key', 'keysecondary', 'keys', 'secondary_keys'):
            if key in entry and (not isinstance(entry[key], list) or not all(isinstance(item, str) for item in entry[key])):
                raise WorldbookUpdateError('世界书关键词必须为文字数组')
    # Unknown fields and arbitrary-precision integers stay untouched.
    return text, content


def preserve_target_name(text, content, current):
    if 'name' in current:
        if content.get('name') == current['name'] and 'name' in content:
            return text, content
        content['name'] = current['name']
    elif 'name' in content:
        del content['name']
    else:
        return text, content
    return json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False), content


def read_target(path):
    try:
        with open(path, 'rb') as handle:
            raw = _bounded_read(handle)
    except FileNotFoundError as exc:
        raise WorldbookUpdateError('世界书已移走或删除，请刷新列表', 'target_missing', 404) from exc
    text, content = parse_worldbook(raw)
    return raw, text, content, hashlib.sha256(raw).hexdigest()


def _validate_url(url):
    if not isinstance(url, str):
        raise WorldbookUpdateError('请输入 http 或 https 世界书链接', 'invalid_url')
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in ('http', 'https') or not parts.hostname or parts.username is not None or parts.password is not None:
            raise ValueError('invalid URL')
        parts.port
    except ValueError as exc:
        raise WorldbookUpdateError('请输入不含账号密码的 http 或 https 世界书链接', 'invalid_url') from exc
    return url


def fetch_source(url):
    current = _validate_url(url)
    # shortcut: chunk checkpoints give a best-effort overall budget; a slow drip
    # can exceed it. Use a transport with total deadlines if hostile sources matter.
    deadline = time.monotonic() + 30
    try:
        with requests.Session() as session:
            for _ in range(6):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise WorldbookUpdateError('获取世界书超时，请重试', 'source_fetch_failed', 502)
                with session.get(current, stream=True, allow_redirects=False,
                                 timeout=(min(5, remaining), min(10, remaining))) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get('Location')
                        if not location:
                            raise WorldbookUpdateError('下载链接的跳转地址为空', 'source_fetch_failed', 502)
                        current = _validate_url(urljoin(current, location))
                        continue
                    response.raise_for_status()
                    chunks = []
                    size = 0
                    for chunk in response.iter_content(chunk_size=65536):
                        if time.monotonic() > deadline:
                            raise WorldbookUpdateError('获取世界书超时，请重试', 'source_fetch_failed', 502)
                        size += len(chunk)
                        if size > MAX_SOURCE_BYTES:
                            raise WorldbookUpdateError('世界书文件不能超过 10 MiB', 'source_too_large', 413)
                        chunks.append(chunk)
                    return b''.join(chunks)
            raise WorldbookUpdateError('下载链接跳转次数过多', 'source_fetch_failed', 502)
    except requests.RequestException as exc:
        # Exception text can include credentials/query secrets from remote URLs.
        raise WorldbookUpdateError('无法获取世界书，请检查链接或稍后重试', 'source_fetch_failed', 502) from exc


def atomic_write_bytes(path, raw, expected_revision=None):
    # Ordinary save/restore historically follows file symlinks; retain the link.
    if os.path.islink(path):
        if expected_revision is not None:
            raise WorldbookUpdateError('世界书文件已变为符号链接，请刷新列表', 'invalid_target')
        path = os.path.realpath(path)
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(prefix='.' + os.path.basename(path) + '-', suffix='.tmp', dir=os.path.dirname(path))
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if os.path.exists(path):
            os.chmod(temp_path, stat.S_IMODE(os.stat(path).st_mode))
        if expected_revision is not None:
            if read_target(path)[3] != expected_revision:
                raise WorldbookUpdateError('世界书在预览后有改动，请重新比较', 'source_changed', 409)
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


def write_update_backup(path, raw, data_dir):
    name = os.path.splitext(os.path.basename(path))[0]
    safe_name = re.sub(r'[\\/:*?"<>|]', '_', name).strip() or 'unnamed_backup'
    folder = os.path.join(data_dir, 'system', 'backups', 'lorebooks', safe_name)
    os.makedirs(folder, exist_ok=True)
    filename = f'{name}_{datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")}__KEY__更新前.json'
    backup_path = os.path.join(folder, filename)
    atomic_write_bytes(backup_path, raw)
    with open(backup_path, 'rb') as handle:
        if handle.read() != raw:
            raise OSError('更新前备份校验失败')
    return backup_path


def commit_update(path, source_text, expected_revision, data_dir, cfg):
    if not isinstance(source_text, str):
        raise WorldbookUpdateError('更新来源为空，请重新选择来源')
    text, content = parse_worldbook(source_text)
    if not isinstance(expected_revision, str) or not expected_revision:
        raise WorldbookUpdateError('请先预览当前差异', 'source_changed', 409)
    with worldbook_target_lock(path):
        raw, _, current, revision = read_target(path)
        if revision != expected_revision:
            raise WorldbookUpdateError('世界书在预览后有改动，请重新比较', 'source_changed', 409)
        text, content = preserve_target_name(text, content, current)
        try:
            limit = max(1, min(int(cfg.get('snapshot_limit_manual', 50)), 200))
        except (ValueError, TypeError):
            limit = 50
        try:
            backup_path = write_update_backup(path, raw, data_dir)
        except OSError as exc:
            raise WorldbookUpdateError('更新前备份失败，未替换世界书', 'backup_failed', 500) from exc
        # External editors do not share this process lock; recheck after backup.
        if read_target(path)[3] != expected_revision:
            raise WorldbookUpdateError('世界书在预览后有改动，请重新比较', 'source_changed', 409)
        incoming = text.encode('utf-8')
        atomic_write_bytes(path, incoming, expected_revision=expected_revision)
        with open(path, 'rb') as handle:
            if handle.read() != incoming:
                raise OSError('世界书写入校验失败，请从更新前备份恢复')
        cleanup_old_snapshots(os.path.dirname(backup_path), limit)
        return content, backup_path
