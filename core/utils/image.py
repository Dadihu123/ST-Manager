import os
import json
import base64
import hashlib
import logging
import threading
from PIL import Image
from core.consts import SIDECAR_EXTENSIONS
from core.config import INTERNAL_DIR, load_config
from core.utils.data import normalize_card_v3, deterministic_sort, sanitize_for_utf8
from core.utils.format_validation import is_valid_character_card_data
from core.utils.filesystem import save_json_atomic
from core.utils.png_metadata import (
    iter_card_payloads,
    read_png_text, rewrite_png_text,
)

logger = logging.getLogger(__name__)

# 获取默认图片路径
def get_default_card_image_path():
    return os.path.join(INTERNAL_DIR, 'static', 'images', 'default_card.png')

def _should_deterministic_png():
    """是否启用 PNG 元数据确定性排序（默认关闭）"""
    try:
        cfg = load_config()
        return bool(cfg.get('png_deterministic_sort', False))
    except Exception:
        return False

CARD_INFO_OK = 'ok'
CARD_INFO_NOT_A_CARD = 'not_a_card'
CARD_INFO_UNREADABLE = 'unreadable'


def _decode_card_payload(raw):
    """把单个 PNG 文本块的载荷解析成 JSON 对象，失败返回 ``None``。

    依次尝试三种策略：明文 JSON、标准 Base64、以及兼容缺省 Padding 与
    URL-Safe 变体的增强 Base64。
    """
    if not raw:
        return None

    # === 策略 A: 尝试直接解析为 JSON (针对某些 V3 卡片直接存明文的情况) ===
    try:
        # 某些特殊情况下 raw 可能是 bytes，先尝试转 str 判断是否以 { 开头
        raw_str = raw
        if isinstance(raw_str, bytes):
            raw_str = raw_str.decode('utf-8', errors='ignore')
        raw_str = str(raw_str).strip()

        if raw_str.startswith('{') or raw_str.startswith('['):
            return json.loads(raw_str)
    except Exception:
        pass

    # === 策略 B: 标准 Base64 解码 (最稳健的旧版逻辑) ===
    try:
        decoded = base64.b64decode(raw).decode('utf-8')
        return json.loads(decoded)
    except Exception:
        pass

    # === 策略 C: 增强型 Base64 解码 (处理 Padding 缺失等边缘情况) ===
    try:
        payload = raw
        if isinstance(payload, bytes):
            payload = payload.decode('utf-8', errors='ignore')
        payload = str(payload).strip()
        padded = payload + ('=' * (-len(payload) % 4))

        # 尝试 URL-Safe 解码 (部分 Web 工具生成的卡片)
        try:
            decoded = base64.urlsafe_b64decode(padded).decode('utf-8', errors='ignore')
            return json.loads(decoded)
        except Exception:
            # 尝试标准解码 + Padding
            decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
            return json.loads(decoded)
    except Exception:
        pass

    return None


def _pick_card_payload(metadata):
    """按 ``ccv3`` > ``chara`` 的优先级挑出角色卡载荷。

    与 SillyTavern 的 ``character-card-parser.js`` ``read()`` 一致：``ccv3``
    优先。同一张卡片可能同时携带两个块，而 ``chara`` 那份未必合规
    （例如 V2 的 ``character_book`` 缺 ``extensions``），优先读 ``chara``
    会把合法卡片误判为「非有效卡片」。

    在此基础上多留一层容错：优先返回第一个「能解析且通过校验」的块；
    若所有块都通不过校验，则退回第一个「能解析」的块，交由调用方按原有
    逻辑判定为 ``not_a_card``。这样既修正了优先级，又不会让任何原本
    可读的卡片变成读不出来。

    返回 ``(cleaned_data, dirty_flags)``；没有任何可解析块时返回 ``(None, [])``。
    """
    fallback = None
    for _key, raw in iter_card_payloads(metadata):
        decoded = _decode_card_payload(raw)
        if not decoded:
            continue

        dirty_flags = []
        cleaned = sanitize_for_utf8(decoded, dirty_tracker=dirty_flags)
        if is_valid_character_card_data(cleaned):
            return cleaned, dirty_flags

        if fallback is None:
            fallback = (cleaned, dirty_flags)

    if fallback is None:
        return None, []
    return fallback


def extract_card_info_with_status(filepath, *, raise_access_errors=False):
    """解析卡片元数据，并区分「确认不是卡片」与「暂时读不了」。

    返回值 ``(info, status)``：

    - ``(dict, CARD_INFO_OK)``         成功解析出角色卡
    - ``(None, CARD_INFO_NOT_A_CARD)`` 文件可正常打开，但内容不是角色卡
      （例如误放进卡目录的世界书、无关 JSON）。这类文件可以从索引中安全剔除。
    - ``(None, CARD_INFO_UNREADABLE)`` 文件无法读取（IO 错误、损坏图片、
      权限问题、正在被写入等）。调用方不应据此删除既有数据库记录，
      否则一次偶发读取失败就会丢掉用户的收藏与元数据。

    ``raise_access_errors`` 供完整索引重建使用：保留 OSError，让调用方终止新 generation。
    """
    try:
        data = None
        dirty_flags = []
        # 1. 处理 JSON 文件
        if filepath.lower().endswith('.json'):
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
        else:
            metadata = read_png_text(filepath)
            data, dirty_flags = _pick_card_payload(metadata)

        if data:
            if not isinstance(data, dict):
                return None, CARD_INFO_NOT_A_CARD

            if not dirty_flags:
                dirty_flags = []
                data = sanitize_for_utf8(data, dirty_tracker=dirty_flags)

            if dirty_flags:
                # 打印醒目的日志
                msg = f"⚠️ [自动修复] 检测到元数据编码异常 (Unicode Error)，已过滤非法字符: {filepath}"
                print(msg)
                logger.warning(msg)

            if not is_valid_character_card_data(data):
                return None, CARD_INFO_NOT_A_CARD

            return data, CARD_INFO_OK

        return None, CARD_INFO_NOT_A_CARD

    except Exception as e:
        if raise_access_errors and isinstance(e, OSError):
            raise
        logger.warning('读取角色卡失败，保留已有索引记录: %s (%s)', filepath, e)
        return None, CARD_INFO_UNREADABLE


def extract_card_info(filepath):
    """兼容旧调用方：解析失败一律返回 ``None``。"""
    info, _status = extract_card_info_with_status(filepath)
    return info

def extract_card_info_strict(filepath):
    """索引重建使用：文件访问失败必须中止，不能伪装成没有内嵌世界书。"""
    info, _status = extract_card_info_with_status(filepath, raise_access_errors=True)
    return info


def write_card_metadata(filepath, json_data):
    try:
        # === 应用 V3 标准化 ===
        # 只有当看起来像角色卡（有name或data）时才处理，避免误伤其他JSON
        if 'name' in json_data or 'data' in json_data:
            json_data = normalize_card_v3(json_data)

        # === 强制清洗 alternate_greetings，防止存入 [""] ===
        # 递归检查 root 和 data 层
        targets = [json_data]
        if 'data' in json_data and isinstance(json_data['data'], dict):
            targets.append(json_data['data'])
            
        for t in targets:
            if 'alternate_greetings' in t and isinstance(t['alternate_greetings'], list):
                # 过滤掉空字符串和仅包含空格的字符串
                t['alternate_greetings'] = [
                    s for s in t['alternate_greetings'] 
                    if isinstance(s, str) and s.strip()
                ]

        # === 数据排序 (Deterministic) ===
        normalized_data = deterministic_sort(json_data)

        # 支持 JSON 文件直接写入
        if filepath.lower().endswith('.json'):
            return save_json_atomic(filepath, normalized_data)

        # PNG 格式文件写入
        # 1. 准备数据
        use_deterministic = _should_deterministic_png()
        png_payload = normalized_data if use_deterministic else json_data
        if use_deterministic:
            json_str = json.dumps(png_payload, ensure_ascii=False, separators=(',', ':'))
        else:
            json_str = json.dumps(png_payload)
        return rewrite_png_text(filepath, json_str)

    except Exception as e:
        logger.error(f"Metadata write error: {e}")
        return False

def resize_image_if_needed(img):
    """如果图片大于2k，等比缩小"""
    max_dimension = 2048
    width, height = img.size
    if width > max_dimension or height > max_dimension:
        if width > height:
            new_width = max_dimension
            new_height = int(height * (max_dimension / width))
        else:
            new_height = max_dimension
            new_width = int(width * (max_dimension / height))
        return img.resize((new_width, new_height), Image.Resampling.LANCZOS)
    return img

def find_sidecar_image(json_path):
    """
    根据 JSON 文件的路径，查找是否存在同名的图片文件。
    返回找到的第一个图片文件的完整路径，如果没有则返回 None。
    """
    base_path = os.path.splitext(json_path)[0]
    for ext in SIDECAR_EXTENSIONS:
        img_path = base_path + ext
        if os.path.exists(img_path):
            return img_path
    return None

def clean_sidecar_images(json_path, exclude_ext=None):
    """
    删除 JSON 文件对应的所有伴生图片。
    exclude_ext: 保留某种后缀的图片（例如刚上传了png，就不要删掉它），传入如 '.png'
    """
    base_path = os.path.splitext(json_path)[0]
    for ext in SIDECAR_EXTENSIONS:
        if exclude_ext and ext == exclude_ext:
            continue
        img_path = base_path + ext
        if os.path.exists(img_path):
            try:
                os.remove(img_path)
                print(f"Deleted old sidecar: {img_path}")
            except Exception as e:
                print(f"Failed to delete sidecar {img_path}: {e}")

def clean_thumbnail_cache(rel_path, thumb_folder):
    """
    主动删除指定卡片 ID 对应的 WebP/JPEG 缩略图缓存。
    确保下次请求时，服务器会重新从原图生成最新的缩略图。
    """
    try:
        # 逻辑必须与 serve_thumbnail 中的 hash 逻辑一致
        rel_path = rel_path.replace('\\', '/')
        filename = os.path.basename(rel_path)
        
        # 如果是 JSON 卡片，serve_thumbnail 是根据同名图片生成的 hash
        # 而 api_update_card_file 中我们通常已经把它转成了 .png 或本身就是 .png
        # 简单起见，尝试清理 .png 后缀对应的缓存
        base_name = os.path.splitext(filename)[0]
        potential_names = {rel_path, filename, base_name + '.png', os.path.splitext(rel_path)[0] + '.png'}
        
        for name in potential_names:
            thumb_hash = hashlib.md5(name.encode('utf-8')).hexdigest()
            for extension in ('.webp', '.jpg'):
                thumb_path = os.path.join(thumb_folder, thumb_hash + extension)
                for target in (thumb_path, thumb_path + '.revision'):
                    if os.path.exists(target):
                        os.remove(target)
    except Exception as e:
        print(f"清理缩略图失败: {e}")


_IMAGE_REVISIONS = {}
_IMAGE_REVISION_LOCK = threading.RLock()
_WINDOWS_FILE_INFO_API = None
_WINDOWS_FILE_INFO_API_LOCK = threading.Lock()
THUMBNAIL_ALGORITHM_VERSION = '2'


def _get_windows_file_info_api():
    global _WINDOWS_FILE_INFO_API
    if _WINDOWS_FILE_INFO_API is None:
        with _WINDOWS_FILE_INFO_API_LOCK:
            if _WINDOWS_FILE_INFO_API is None:
                import ctypes
                from ctypes import wintypes

                class FileBasicInfo(ctypes.Structure):
                    _fields_ = [(name, ctypes.c_longlong) for name in (
                        'creation', 'access', 'write', 'change'
                    )] + [('attributes', wintypes.DWORD)]

                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.CreateFileW.argtypes = [
                    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                    wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
                ]
                kernel.CreateFileW.restype = wintypes.HANDLE
                kernel.GetFileInformationByHandleEx.argtypes = [
                    wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
                ]
                kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel.CloseHandle.restype = wintypes.BOOL
                _WINDOWS_FILE_INFO_API = (ctypes, wintypes, FileBasicInfo, kernel)
    return _WINDOWS_FILE_INFO_API


def _image_file_version(path):
    stat = os.stat(path)
    change_time = stat.st_ctime_ns
    if os.name == 'nt':
        # Windows 的 st_ctime 是创建时间；外部原地改图并还原 mtime 仍须失效。
        ctypes, wintypes, FileBasicInfo, kernel = _get_windows_file_info_api()
        handle = kernel.CreateFileW(path, 0x80, 7, None, 3, 0, None)
        if handle == wintypes.HANDLE(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            info = FileBasicInfo()
            if not kernel.GetFileInformationByHandleEx(handle, 0, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            change_time = info.change
        finally:
            kernel.CloseHandle(handle)
    return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, change_time, stat.st_size)


def card_image_file_version(path, *, include_change_time=False):
    """Return a filesystem version for a card image, resolving JSON sidecars."""
    path = os.fspath(path) if path else path
    if str(path).lower().endswith('.json'):
        path = find_sidecar_image(path)
    if not path:
        return None
    try:
        if include_change_time or os.name != 'nt':
            return _image_file_version(path)
        stat = os.stat(path)
        return ('stat', stat.st_dev, stat.st_ino, stat.st_mtime_ns,
                stat.st_ctime_ns, stat.st_size)
    except OSError:
        return None


def image_content_revision(path):
    """图片内容版本与文件冲突版本独立；外部替换后重新验证全部渲染 chunk。"""
    from core.utils.png_metadata import png_image_revision
    absolute = os.path.abspath(path)
    version = _image_file_version(absolute)
    with _IMAGE_REVISION_LOCK:
        cached = _IMAGE_REVISIONS.get(absolute)
        if cached and cached[0] == version:
            return cached[1]
    if absolute.lower().endswith('.png'):
        revision = png_image_revision(absolute)
    else:
        digest = hashlib.sha256()
        with open(absolute, 'rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        revision = digest.hexdigest()
    if _image_file_version(absolute) != version:
        raise OSError('图片在读取时发生变化，请重试')
    with _IMAGE_REVISION_LOCK:
        if len(_IMAGE_REVISIONS) >= 512:
            _IMAGE_REVISIONS.pop(next(iter(_IMAGE_REVISIONS)))
        _IMAGE_REVISIONS[absolute] = (version, revision)
    return revision


def card_image_revision(path):
    """供图片 URL 使用；JSON 的伴生图与缩略图共享同一内容版本。"""
    from core.utils.source_revision import build_file_source_revision
    original = path
    if str(path).lower().endswith('.json'):
        path = find_sidecar_image(path)
        if not path:
            return 'no-image'
    try:
        return image_content_revision(path)
    except (OSError, ValueError):
        # 无法验证的图片不复用已验证版本；缩略图入口仍明确报告读取错误。
        return 'unverified-' + build_file_source_revision(path or original)


def card_image_urls(card_id, path):
    from urllib.parse import quote
    revision = card_image_revision(path)
    encoded_id = quote(card_id)
    return {'image_revision': revision, 'image_url': f'/cards_file/{encoded_id}?v={revision}',
            'thumb_url': f'/api/thumbnail/{encoded_id}?v={THUMBNAIL_ALGORITHM_VERSION}-{revision}'}
