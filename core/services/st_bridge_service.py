"""SillyTavern「待定」桥接服务。

设计要点（与 ST-Manager 其它模块一致的分层）：

- 库目录（``cards_dir``）只读，桥接永远不会删改库里的卡；想写回必须显式 ``commit``。
- 装载 = 把库卡复制进酒馆角色目录；酒馆看到的是一份独立副本，随便改。
- 提交 = 把副本原子写回原卡，写之前备份、写之前比对装载时的哈希（防覆盖别人的改动）。
- 丢弃 = 只删酒馆那一侧的副本与登记项。

所有路径都经过 :func:`_safe_join` 归一化，拒绝 ``..``、绝对路径与盘符。
"""

import hashlib
import logging
import os
import shutil
import time

from core.config import SYSTEM_DIR, get_cards_folder
from core.data import st_bridge_store
from core.services.card_operation_lock import card_lock

logger = logging.getLogger(__name__)

# 酒馆能识别的角色卡扩展名
CARD_EXTENSIONS = ('.png', '.json', '.jpg', '.jpeg', '.webp', '.yaml', '.yml', '.charx', '.byaf')

BACKUP_DIRNAME = 'st_bridge'
NAME_ATTEMPT_LIMIT = 500
HASH_CHUNK_SIZE = 1024 * 1024


class StBridgeError(Exception):
    """桥接业务的可预期错误，携带 HTTP 状态码与额外字段。"""

    def __init__(self, message, status_code=400, **extra):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.extra = extra


# ---------------------------------------------------------------- 目录解析


def get_characters_dir():
    """酒馆角色目录（本地模式）。未配置、不存在或走的是 HTTP 模式时返回 None。"""
    try:
        from core.services.st_client import get_st_client
    except ImportError as exc:  # pragma: no cover - 依赖缺失时不影响其它功能
        logger.warning('SillyTavern 客户端不可用: %s', exc)
        return None

    try:
        client = get_st_client()
        path = client.get_st_subdir('characters')
    except Exception as exc:  # noqa: BLE001 - 客户端初始化失败不该抛给调用方
        logger.warning('解析 SillyTavern 角色目录失败: %s', exc)
        return None

    if path and os.path.isdir(path):
        return path
    return None


def get_cards_dir():
    return get_cards_folder()


def _backup_dir():
    path = os.path.join(SYSTEM_DIR, 'backups', BACKUP_DIRNAME)
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------- 路径与哈希


def _safe_join(root, relative):
    """把相对路径拼到 root 之下；越界或非法时返回 None。"""
    if not root:
        return None
    text = str(relative or '').replace('\\', '/').strip()
    if not text or text.startswith('/') or text.startswith('~'):
        return None
    head = text.split('/', 1)[0]
    if os.path.isabs(text) or ':' in head:
        return None

    root_real = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root_real, text.replace('/', os.sep)))
    try:
        if os.path.commonpath([candidate, root_real]) != root_real:
            return None
    except ValueError:
        return None
    return candidate


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _is_card_file(path):
    return str(path).lower().endswith(CARD_EXTENSIONS)


def _staged_stat(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return stat.st_size, stat.st_mtime


# ---------------------------------------------------------------- 登记项查询


def _find_staged_by_source(source_id):
    """同一张库卡重复装载时复用已有副本，返回 staged_name 或 None。"""
    best_name = None
    best_time = -1.0
    for staged_name, entry in st_bridge_store.load_all().items():
        if entry.get('source_id') != source_id:
            continue
        staged_time = float(entry.get('staged_at') or 0)
        if staged_time >= best_time:
            best_name, best_time = staged_name, staged_time
    return best_name


def _unique_staged_name(dest_root, filename):
    """在酒馆角色目录里找一个不冲突的文件名。"""
    stem, ext = os.path.splitext(filename)
    candidate = filename
    index = 1
    while index <= NAME_ATTEMPT_LIMIT:
        if not os.path.exists(os.path.join(dest_root, candidate)):
            return candidate
        candidate = f'{stem}__{index}{ext}'
        index += 1
    raise StBridgeError('同名文件过多，无法生成待定副本', 409)


# ---------------------------------------------------------------- 装载 / 提交 / 丢弃


def checkout(card_id, *, cards_dir=None, characters_dir=None):
    """把库卡复制进酒馆角色目录并登记。重复装载同一张卡会复用已有副本。"""
    cards_root = cards_dir or get_cards_dir()
    dest_root = characters_dir or get_characters_dir()
    if not dest_root:
        raise StBridgeError('未找到 SillyTavern 角色目录，请先在设置里配置 SillyTavern 数据目录', 400)

    source_path = _safe_join(cards_root, card_id)
    if not source_path or not os.path.isfile(source_path):
        raise StBridgeError('卡片不存在', 404)
    if not _is_card_file(source_path):
        raise StBridgeError('不支持的文件类型', 400)

    source_id = os.path.relpath(source_path, os.path.realpath(cards_root)).replace(os.sep, '/')

    existing_name = _find_staged_by_source(source_id)
    if existing_name:
        existing_path = _safe_join(dest_root, existing_name)
        if existing_path and os.path.isfile(existing_path):
            return {
                'success': True,
                'staged_name': existing_name,
                'source_id': source_id,
                'reused': True,
            }

    staged_name = _unique_staged_name(dest_root, os.path.basename(source_path))
    target_path = _safe_join(dest_root, staged_name)
    if not target_path:
        raise StBridgeError('待定副本路径非法', 400)

    try:
        os.makedirs(os.path.dirname(target_path) or dest_root, exist_ok=True)
        shutil.copy2(source_path, target_path)
    except OSError as exc:
        logger.error('复制卡片到酒馆目录失败: %s', exc)
        raise StBridgeError('复制卡片失败，请检查磁盘空间与权限', 500)

    source_stat = os.stat(source_path)
    staged_stat = _staged_stat(target_path) or (source_stat.st_size, time.time())
    entry = {
        'source_id': source_id,
        'source_hash': _sha256(source_path),
        'size': source_stat.st_size,
        'staged_at': time.time(),
        'staged_size': staged_stat[0],
        'staged_mtime': staged_stat[1],
        'origin': 'library',
    }
    st_bridge_store.put(staged_name, entry)

    _request_scan('st_bridge_checkout')
    logger.info('已装载卡片到待定: %s -> %s', source_id, staged_name)
    return {
        'success': True,
        'staged_name': staged_name,
        'source_id': source_id,
        'size': source_stat.st_size,
        'reused': False,
    }


def commit(staged_name, *, force=False, cards_dir=None, characters_dir=None):
    """把待定副本写回原卡：先校验哈希、先备份、再原子替换。"""
    entry = st_bridge_store.get(staged_name)
    if not entry:
        raise StBridgeError('这张待定卡没有登记记录', 404)

    cards_root = cards_dir or get_cards_dir()
    dest_root = characters_dir or get_characters_dir()
    source_id = str(entry.get('source_id') or '')
    source_path = _safe_join(cards_root, source_id)
    staged_path = _safe_join(dest_root, staged_name)

    if not source_path or not os.path.isfile(source_path):
        raise StBridgeError('原卡已不存在，无法覆盖', 404)
    if not staged_path or not os.path.isfile(staged_path):
        raise StBridgeError('待定副本已不存在', 404)

    with card_lock(source_id, context='st_bridge') as acquired:
        if not acquired:
            raise StBridgeError('角色卡正在被其他操作使用，请稍后重试', 409, card_busy=True)

        expected_hash = str(entry.get('source_hash') or '')
        current_hash = _sha256(source_path)
        if expected_hash and current_hash != expected_hash and not force:
            raise StBridgeError(
                '原卡在装载之后被修改过，直接提交会覆盖这些改动',
                409,
                conflict=True,
                source_hash=expected_hash,
                current_hash=current_hash,
            )

        backup_path = _backup_source(source_path)
        _atomic_replace(staged_path, source_path)

        new_hash = _sha256(source_path)
        staged_stat = _staged_stat(staged_path)
        st_bridge_store.update(
            staged_name,
            source_hash=new_hash,
            committed_at=time.time(),
            staged_size=staged_stat[0] if staged_stat else None,
            staged_mtime=staged_stat[1] if staged_stat else None,
        )

    _request_scan('st_bridge_commit')
    logger.info('已把待定卡写回原卡: %s (备份 %s)', source_id, backup_path)
    return {
        'success': True,
        'source_id': source_id,
        'staged_name': staged_name,
        'source_hash': new_hash,
        'backup': backup_path,
    }


def discard(staged_name, *, characters_dir=None):
    """丢弃一张待定卡：删副本 + 删登记项，原卡不动。"""
    entry = st_bridge_store.get(staged_name)
    if not entry:
        raise StBridgeError('这张待定卡没有登记记录', 404)

    dest_root = characters_dir or get_characters_dir()
    staged_path = _safe_join(dest_root, staged_name)
    removed = False
    if staged_path and os.path.isfile(staged_path):
        try:
            os.remove(staged_path)
            removed = True
        except OSError as exc:
            logger.error('删除待定副本失败: %s', exc)
            raise StBridgeError('删除待定副本失败，请检查文件是否被占用', 500)

    st_bridge_store.remove(staged_name)
    _request_scan('st_bridge_discard')
    return {'success': True, 'staged_name': staged_name, 'removed': removed}


# ---------------------------------------------------------------- 状态与目录树


def status(*, verify=False, cards_dir=None, characters_dir=None):
    """待定清单概览。

    列出酒馆角色目录里的全部卡片文件：登记过的标 ``origin='library'``，
    酒馆自己导入的标 ``origin='st_import'``——这样「待定」面板既能看到桥接装载的卡，
    也能看到直接在酒馆里新建/导入的卡。

    ``verify`` 为真时逐张比对原卡哈希（慢），默认只比大小/mtime，供页面轮询用。
    """
    cards_root = cards_dir or get_cards_dir()
    dest_root = characters_dir or get_characters_dir()
    entries = st_bridge_store.load_all()

    files = []
    if dest_root and os.path.isdir(dest_root):
        try:
            names = sorted(os.listdir(dest_root))
        except OSError as exc:
            logger.warning('读取酒馆角色目录失败: %s', exc)
            names = []
        files = [
            name for name in names
            if not name.startswith('.')
            and _is_card_file(name)
            and os.path.isfile(os.path.join(dest_root, name))
        ]

    items = []
    staged_count = 0
    edited_count = 0
    conflict_count = 0

    for name in files:
        staged_path = os.path.join(dest_root, name)
        stat = _staged_stat(staged_path)
        entry = entries.get(name)

        if not entry:
            items.append({
                'filename': name,
                'staged_id': name,
                'source_id': '',
                'origin': 'st_import',
                'size': stat[0] if stat else None,
                'staged_at': None,
                'edited': False,
                'conflict': False,
                'missing_source': False,
            })
            continue

        staged_count += 1
        source_id = str(entry.get('source_id') or '')
        source_path = _safe_join(cards_root, source_id)
        missing_source = not (source_path and os.path.isfile(source_path))

        edited = False
        if stat and entry.get('staged_size') is not None:
            edited = stat[0] != entry['staged_size']
        if not edited and stat and entry.get('staged_mtime'):
            edited = abs(stat[1] - float(entry['staged_mtime'])) > 1.0

        conflict = False
        if verify and not missing_source and entry.get('source_hash'):
            conflict = _sha256(source_path) != entry['source_hash']

        if edited:
            edited_count += 1
        if conflict:
            conflict_count += 1

        items.append({
            'filename': name,
            'staged_id': name,
            'source_id': source_id,
            'origin': entry.get('origin') or 'library',
            'size': stat[0] if stat else None,
            'staged_at': entry.get('staged_at'),
            'edited': edited,
            'conflict': conflict,
            'missing_source': missing_source,
        })

    # 登记过但文件已不在（用户手动删了副本）：也列出来，方便 UI 清理
    for name, entry in entries.items():
        if name in files:
            continue
        staged_count += 1
        items.append({
            'filename': name,
            'staged_id': name,
            'source_id': str(entry.get('source_id') or ''),
            'origin': entry.get('origin') or 'library',
            'size': None,
            'staged_at': entry.get('staged_at'),
            'edited': False,
            'conflict': False,
            'missing_source': False,
            'staged_missing': True,
        })

    items.sort(key=lambda item: item['filename'].lower())
    return {
        'success': True,
        'total': len(items),
        'staged': staged_count,
        'edited': edited_count,
        'conflict': conflict_count,
        'items': items,
        'pending_dir': dest_root or '',
        'cards_dir': cards_root or '',
    }


def public_tree(*, cards_dir=None, characters_dir=None, max_entries=20000):
    """库目录树 + 每个文件夹直接包含的卡片数，供酒馆侧的分类栏使用。"""
    cards_root = cards_dir or get_cards_dir()
    if not cards_root or not os.path.isdir(cards_root):
        raise StBridgeError('未找到角色卡库目录', 400)

    folders = {}
    root_name = os.path.realpath(cards_root)
    for dirpath, dirnames, filenames in os.walk(cards_root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith('.'))
        relative = os.path.relpath(dirpath, root_name).replace(os.sep, '/')
        if relative == '.':
            relative = ''
        count = sum(1 for name in filenames if name.lower().endswith(CARD_EXTENSIONS))
        if relative or count:
            folders[relative] = count
        if len(folders) >= max_entries:
            logger.warning('库目录数量超过 %s，目录树已截断', max_entries)
            break

    return {
        'success': True,
        'folders': folders,
        'total': sum(folders.values()),
        'pending_dir': characters_dir or get_characters_dir() or '',
    }


# ---------------------------------------------------------------- 内部工具


def _backup_source(source_path):
    """把原卡复制到备份目录，返回备份文件路径。"""
    stamp = time.strftime('%Y%m%d_%H%M%S')
    name = os.path.basename(source_path)
    backup_path = os.path.join(_backup_dir(), f'{stamp}_{name}')
    index = 1
    while os.path.exists(backup_path):
        backup_path = os.path.join(_backup_dir(), f'{stamp}_{index}_{name}')
        index += 1
    shutil.copy2(source_path, backup_path)
    return backup_path


def _atomic_replace(staged_path, source_path):
    """先写到原卡同目录的临时文件，再 os.replace 原子替换，避免半截文件。"""
    temp_path = source_path + '.st_bridge.tmp'
    try:
        shutil.copy2(staged_path, temp_path)
        os.replace(temp_path, source_path)
    except OSError as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        logger.error('写回原卡失败: %s', exc)
        raise StBridgeError('写回原卡失败，请检查文件是否被占用', 500)


def _request_scan(reason):
    """通知扫描服务刷新索引；扫描模块不可用时静默跳过。"""
    try:
        from core.services.scan_service import request_scan
    except ImportError:  # pragma: no cover
        return
    try:
        request_scan(reason)
    except Exception as exc:  # noqa: BLE001
        logger.warning('触发扫描失败（不影响桥接结果）: %s', exc)
