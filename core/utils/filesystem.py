import os
import json
import shutil
import time
import uuid
import logging
import re
import stat
import tempfile
from contextvars import ContextVar
from functools import cache, partial, wraps
from core.consts import SIDECAR_EXTENSIONS
from core.utils.data import deterministic_sort, normalize_card_v3

logger = logging.getLogger(__name__)
_directory_case_cache = ContextVar('directory_case_cache', default=None)


def filesystem_path_bucket(path: str) -> str:
    """只用于定位候选项，允许数据库在目录离线时建表和回填。"""
    return os.path.normcase(os.path.normpath(path)) if path else ''


@cache
def _windows_directory_queries():
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    kernel.GetFileInformationByHandleEx.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    return kernel


def _windows_case_sensitive(parent, directory_cases):
    if parent not in directory_cases:
        import ctypes
        from ctypes import wintypes

        kernel = _windows_directory_queries()
        # FILE_READ_ATTRIBUTES, share read/write/delete, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS.
        handle = kernel.CreateFileW(parent, 0x80, 7, None, 3, 0x02000000, None)
        sensitive = None
        if handle != wintypes.HANDLE(-1).value:
            try:
                flags = wintypes.DWORD()
                # FileCaseSensitiveInfo, FILE_CS_FLAG_CASE_SENSITIVE_DIR.
                if kernel.GetFileInformationByHandleEx(handle, 23, ctypes.byref(flags), ctypes.sizeof(flags)):
                    sensitive = bool(flags.value & 1)
                elif ctypes.get_last_error() in (1, 50, 87):
                    sensitive = False  # Windows or a volume that does not support the flag.
            finally:
                kernel.CloseHandle(handle)
        directory_cases[parent] = sensitive
    return directory_cases[parent]


def filesystem_paths_match(left: str, right: str, *, directory_cases=None, probe=True) -> bool:
    """仅在对应名称所在的目录明确不区分大小写时合并别名。"""
    left, right = os.path.normpath(left), os.path.normpath(right)
    if left == right:
        return True
    if os.name != 'nt' or os.path.normcase(left) != os.path.normcase(right):
        return False
    if directory_cases is None:
        directory_cases = {}
    drive, left_path = os.path.splitdrive(os.path.abspath(left))
    _, right_path = os.path.splitdrive(os.path.abspath(right))
    parent = drive + os.sep
    for left_part, right_part in zip(left_path.strip(os.sep).split(os.sep), right_path.strip(os.sep).split(os.sep)):
        if left_part != right_part:
            sensitive = _windows_case_sensitive(parent, directory_cases) if probe else directory_cases.get(parent)
            if sensitive is not False:
                return False
        parent = os.path.join(parent, left_part)
    return True


def prepare_filesystem_path_match(path: str, *, probe=True):
    """采集请求路径各级名称的大小写规则，返回无目录探测的比较函数。"""
    cases = {}
    if os.name == 'nt' and path:
        drive, rest = os.path.splitdrive(os.path.abspath(path))
        literal_parent = drive + os.sep
        normalized_parent = os.path.normcase(literal_parent)
        cached = _directory_case_cache.get()
        if cached is None:
            cached = {}
        for part in rest.strip(os.sep).split(os.sep):
            sensitive = (_windows_case_sensitive(normalized_parent, cached) if probe
                         else cached.get(normalized_parent))
            cases[literal_parent] = sensitive
            literal_parent = os.path.join(literal_parent, part)
            normalized_parent = os.path.join(normalized_parent, os.path.normcase(part) if sensitive is False else part)
    return partial(filesystem_paths_match, path, directory_cases=cases, probe=False)


def filesystem_path_key(path: str, *, directory_cases=None, preserve_unknown=False) -> str:
    """世界书备注与分类的规范路径，保留区分大小写的各级名称。"""
    if not path or os.name != 'nt' or not os.path.isabs(path):
        return filesystem_path_bucket(path)
    if directory_cases is None:
        directory_cases = _directory_case_cache.get()
        if directory_cases is None:
            directory_cases = {}
    drive, rest = os.path.splitdrive(os.path.normpath(path))
    parent = drive + os.sep
    key = os.path.normcase(parent)
    for part in rest.strip(os.sep).split(os.sep):
        sensitive = _windows_case_sensitive(parent, directory_cases)
        # 兼容旧备注键；已保存的分类在目录暂时不可用时保留原有大小写。
        keep_case = sensitive is True or (sensitive is None and preserve_unknown)
        key = os.path.join(key, part if keep_case else os.path.normcase(part))
        parent = key if sensitive is not None else os.path.join(parent, part)
    return key


def cache_directory_case_checks(operation):
    """复用同一请求或构建中的目录属性查询。"""
    @wraps(operation)
    def wrapped(*args, **kwargs):
        if os.name != 'nt' or _directory_case_cache.get() is not None:
            return operation(*args, **kwargs)
        token = _directory_case_cache.set({})
        try:
            return operation(*args, **kwargs)
        finally:
            _directory_case_cache.reset(token)
    return wrapped


def walk_directory_strict(root):
    """枚举失败必须中止，不能把未读到的目录内容当成空目录。"""
    def onerror(error):
        raise error

    yield from os.walk(root, onerror=onerror)


def sanitize_filename(filename: str, replacement: str = '_') -> str:
    """
    清理文件名，移除不安全字符
    模拟 sanitize-filename 库的行为
    """
    # Windows 和 Unix 系统的非法文件名字符
    illegal_chars = r'[<>:"/\\|?*\x00-\x1f]'
    
    # 替换非法字符
    sanitized = re.sub(illegal_chars, replacement, filename)
    
    # 移除文件名开头和结尾的空格和点
    sanitized = sanitized.strip('. ')
    
    # Windows 保留名称
    reserved_names = {
        'CON', 'PRN', 'AUX', 'NUL',
        'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
        'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
    }
    
    name_upper = sanitized.upper()
    if name_upper in reserved_names or name_upper.split('.')[0] in reserved_names:
        sanitized = f"{replacement}{sanitized}"
    
    # 限制长度（255字节）
    if len(sanitized.encode('utf-8')) > 255:
        sanitized = sanitized[:200]  # 保守处理
    
    return sanitized or 'undefined'

def save_json_atomic(path, data):
    """原子化保存 JSON，确保格式统一"""
    temp_path = None
    try:
        path = os.path.abspath(path)
        # 1. 标准化排序
        sorted_data = deterministic_sort(data)
        
        # 独立短名称避免给已达 NAME_MAX 的文件名追加后缀；同目录保证原子替换。
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=os.path.dirname(path),
                                         prefix='.stm-json-', suffix='.tmp', delete=False) as f:
            temp_path = f.name
            # ensure_ascii=False 显示中文, indent=4 美化, separators 去除行尾多余空格
            json.dump(sorted_data, f, ensure_ascii=False, indent=4, separators=(',', ': '))
            f.flush()
            os.fsync(f.fileno())

        # 3. 替换原文件 (原子操作)
        # Windows 的只读属性会令失败后的临时文件也无法删除；只在 POSIX 复制权限位。
        if os.name != 'nt' and os.path.exists(path):
            os.chmod(temp_path, stat.S_IMODE(os.stat(path).st_mode))
        os.replace(temp_path, path)
        temp_path = None
        return True
    except Exception as e:
        logger.error(f"Save JSON error: {e}")
        return False
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning('清理 JSON 临时文件失败: %s', exc)

# 判断是否是卡片文件
def is_card_file(filename):
    return filename.lower().endswith(('.png', '.json'))

def safe_move_to_trash(src_path, trash_folder_path, *, on_moved=None):
    """
    将文件或文件夹安全移动到回收站。
    策略：
    1. 保持原文件名主体。
    2. 追加 _时间戳_随机码 防止冲突。
    3. 如果是 JSON 卡片，尝试同时移动同名图片，并保持后缀一致以便恢复。
    on_moved 在移动后提交关联状态。回调失败时尝试恢复原文件并传播错误。
    """
    if not os.path.exists(src_path):
        return False

    moved = []
    try:
        # 确保回收站目录存在
        os.makedirs(trash_folder_path, exist_ok=True)

        basename = os.path.basename(src_path)
        name_part, ext_part = os.path.splitext(basename)
        
        # 生成唯一后缀 (时间戳_4位随机Hex)
        unique_suffix = f"_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        
        # 目标主文件名
        target_name = f"{name_part}{unique_suffix}{ext_part}"
        target_path = os.path.join(trash_folder_path, target_name)
        
        # 执行移动
        shutil.move(src_path, target_path)
        moved.append((src_path, target_path))
        print(f"Moved to trash: {src_path} -> {target_path}")

        # === 特殊处理：如果是 JSON 卡片，尝试移动所有伴生图片 ===
        if ext_part.lower() == '.json':
            # 查找同名图片 (去掉 break，遍历所有可能的后缀)
            for img_ext in SIDECAR_EXTENSIONS:
                sidecar_src = os.path.join(os.path.dirname(src_path), name_part + img_ext)
                if os.path.exists(sidecar_src):
                    # 使用相同的 unique_suffix
                    sidecar_target_name = f"{name_part}{unique_suffix}{img_ext}"
                    sidecar_target_path = os.path.join(trash_folder_path, sidecar_target_name)
                    try:
                        shutil.move(sidecar_src, sidecar_target_path)
                        moved.append((sidecar_src, sidecar_target_path))
                        print(f"Moved sidecar to trash: {sidecar_src} -> {sidecar_target_path}")
                    except Exception as e:
                        print(f"Error moving sidecar {sidecar_src}: {e}")

    except Exception as e:
        logger.error(f"Failed to move {src_path} to trash: {e}")
        return False

    if on_moved is not None:
        try:
            on_moved()
        except Exception:
            for original, trashed in reversed(moved):
                try:
                    if os.path.lexists(original):
                        raise FileExistsError(original)
                    shutil.move(trashed, original)
                except OSError as exc:
                    logger.error('Restore from trash failed (%s -> %s): %s', trashed, original, exc)
            raise
    return True

def safe_delete_card_file(file_path):
    """安全删除文件 (如果需要回收站功能，需引入 send2trash，这里使用 os.remove)"""
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            print(f"Deleted: {file_path}")
        except Exception as e:
            print(f"Error deleting {file_path}: {e}")

# 清理旧快照
def cleanup_old_snapshots(target_dir, max_limit, prefix_filter=None, *, protected_path=None):
    """
    清理目标目录下过期的快照文件。
    :param target_dir: 备份目录
    :param max_limit: 最大保留数量
    :param prefix_filter: 如果提供，只清理包含此前缀的文件 (用于区分 AUTO 和 普通备份)
    :param protected_path: 优先保留本次刚创建的快照，避免时钟变化导致其被删除
    """
    if not os.path.exists(target_dir): return
    
    try:
        all_files = []
        for f in os.listdir(target_dir):
            if f.lower().endswith(('.json', '.png')):
                # 如果指定了过滤器（例如只清理 __AUTO__），则跳过不包含该标记的文件
                if prefix_filter and prefix_filter not in f:
                    continue
                # 如果没有指定过滤器（清理普通备份），且文件包含 __AUTO__，则跳过（避免误删自动备份）
                if not prefix_filter and "__AUTO__" in f:
                    continue
                    
                full_path = os.path.join(target_dir, f)
                all_files.append((full_path, os.path.getmtime(full_path)))
        
        # 优先保留受保护快照，其他按时间倒序排列。
        all_files.sort(key=lambda x: (x[0] == protected_path, x[1]), reverse=True)
        
        # 如果超过限制，删除旧的
        if len(all_files) > max_limit:
            for f_path, _ in all_files[max_limit:]:
                try:
                    os.remove(f_path)
                    print(f"Deleted old snapshot: {f_path}")
                    # 尝试清理同名伴生图
                    base_path = os.path.splitext(f_path)[0]
                    for ext in ['.json', *SIDECAR_EXTENSIONS]:
                        sidecar = base_path + ext
                        if os.path.exists(sidecar) and sidecar != f_path:
                            os.remove(sidecar)
                except Exception as e:
                    print(f"Error deleting old snapshot {f_path}: {e}")
    except Exception as e:
        print(f"Cleanup failed: {e}")

# 将数据写入快照文件 (PNG 或 JSON)
def write_snapshot_file(src_path, dst_path, data, is_png, compact=False):
    """
    基于源文件(src_path)创建快照(dst_path)，并注入新数据(data)。
    如果不传 data，则退化为直接复制文件。
    """
    try:
        # 如果没有新数据，直接复制物理文件
        if not data:
            shutil.copy2(src_path, dst_path)
            return True

        # 标准化数据 (如果是卡片快照，也建议标准化一下，保持一致性)
        # 但如果是 WI，不需要 normalize_card_v3
        if data and ('spec' in data or 'data' in data):
             data = normalize_card_v3(data)
             
        normalized_data = deterministic_sort(data)

        if is_png:
            from core.utils.png_metadata import rewrite_png_text
            json_str = json.dumps(normalized_data, ensure_ascii=False,
                                  separators=(',', ':') if compact else None)
            rewrite_png_text(src_path, json_str, destination=dst_path)
        else:
            # JSON 格式直接写入备份路径
            with open(dst_path, 'w', encoding='utf-8') as f:
                if compact:
                    # 压缩模式：去空格，一行
                    json.dump(normalized_data, f, ensure_ascii=False, separators=(',', ':'))
                else:
                    # 美化模式
                    json.dump(normalized_data, f, ensure_ascii=False, indent=4, separators=(',', ': '))
        
        return True
    except Exception as e:
        logger.error(f"Snapshot write error: {e}")
        # 如果写入失败，尝试回退到直接复制
        try:
            shutil.copy2(src_path, dst_path)
        except:
            pass
        return False
