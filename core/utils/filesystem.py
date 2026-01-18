import os
import json
import shutil
import time
import uuid
import base64
import logging
from PIL import Image, PngImagePlugin
from core.consts import SIDECAR_EXTENSIONS
from core.utils.data import deterministic_sort, normalize_card_v3

logger = logging.getLogger(__name__)

def save_json_atomic(path, data):
    """原子化保存 JSON，确保格式统一"""
    try:
        # 1. 标准化排序
        sorted_data = deterministic_sort(data)
        
        # 2. 写入临时文件
        temp_path = path + ".tmp"
        with open(temp_path, 'w', encoding='utf-8') as f:
            # ensure_ascii=False 显示中文, indent=4 美化, separators 去除行尾多余空格
            json.dump(sorted_data, f, ensure_ascii=False, indent=4, separators=(',', ': '))
            
        # 3. 替换原文件 (原子操作)
        if os.path.exists(path):
            os.replace(temp_path, path)
        else:
            os.rename(temp_path, path)
        return True
    except Exception as e:
        logger.error(f"Save JSON error: {e}")
        return False

# 判断是否是卡片文件
def is_card_file(filename):
    return filename.lower().endswith(('.png', '.json'))

def safe_move_to_trash(src_path, trash_folder_path):
    """
    将文件或文件夹安全移动到回收站。
    策略：
    1. 保持原文件名主体。
    2. 追加 _时间戳_随机码 防止冲突。
    3. 如果是 JSON 卡片，尝试同时移动同名图片，并保持后缀一致以便恢复。
    """
    if not os.path.exists(src_path):
        return False

    try:
        # 确保回收站目录存在
        if not os.path.exists(trash_folder_path):
            os.makedirs(trash_folder_path)

        basename = os.path.basename(src_path)
        name_part, ext_part = os.path.splitext(basename)
        
        # 生成唯一后缀 (时间戳_4位随机Hex)
        unique_suffix = f"_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        
        # 目标主文件名
        target_name = f"{name_part}{unique_suffix}{ext_part}"
        target_path = os.path.join(trash_folder_path, target_name)
        
        # 执行移动
        shutil.move(src_path, target_path)
        print(f"Moved to trash: {src_path} -> {target_path}")

        # === 特殊处理：如果是 JSON 卡片，尝试移动所有伴生图片 ===
        if ext_part.lower() == '.json':
            # 查找同名图片 (去掉 break，遍历所有可能的后缀)
            for img_ext in ['.png', '.webp', '.jpg', '.jpeg']:
                sidecar_src = os.path.join(os.path.dirname(src_path), name_part + img_ext)
                if os.path.exists(sidecar_src):
                    # 使用相同的 unique_suffix
                    sidecar_target_name = f"{name_part}{unique_suffix}{img_ext}"
                    sidecar_target_path = os.path.join(trash_folder_path, sidecar_target_name)
                    try:
                        shutil.move(sidecar_src, sidecar_target_path)
                        print(f"Moved sidecar to trash: {sidecar_src} -> {sidecar_target_path}")
                    except Exception as e:
                        print(f"Error moving sidecar {sidecar_src}: {e}")

        return True
    except Exception as e:
        logger.error(f"Failed to move {src_path} to trash: {e}")
        return False

def safe_delete_card_file(file_path):
    """安全删除文件 (如果需要回收站功能，需引入 send2trash，这里使用 os.remove)"""
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
            print(f"Deleted: {file_path}")
        except Exception as e:
            print(f"Error deleting {file_path}: {e}")

# 清理旧快照
def cleanup_old_snapshots(target_dir, max_limit, prefix_filter=None):
    """
    清理目标目录下过期的快照文件。
    :param target_dir: 备份目录
    :param max_limit: 最大保留数量
    :param prefix_filter: 如果提供，只清理包含此前缀的文件 (用于区分 AUTO 和 普通备份)
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
        
        # 按时间倒序排列 (新的在前)
        all_files.sort(key=lambda x: x[1], reverse=True)
        
        # 如果超过限制，删除旧的
        if len(all_files) > max_limit:
            for f_path, _ in all_files[max_limit:]:
                try:
                    os.remove(f_path)
                    print(f"Deleted old snapshot: {f_path}")
                    # 尝试清理同名伴生图
                    base_path = os.path.splitext(f_path)[0]
                    for ext in ['.png', '.json', '.webp']:
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
            # 1. 打开源图片
            with Image.open(src_path) as img:
                # 2. 准备 Metadata
                meta = PngImagePlugin.PngInfo()
                # 保留非 Chara 的其他元数据 (如软件信息等)
                for k, v in img.info.items():
                    if k not in ['chara', 'ccv3'] and isinstance(v, str):
                        meta.add_text(k, v)
                
                # 3. 注入新的 Chara 数据 (Base64编码)
                # 确保是 JSON 字符串
                if compact:
                    json_str = json.dumps(normalized_data, ensure_ascii=False, separators=(',', ':'))
                else:
                    json_str = json.dumps(normalized_data, ensure_ascii=False)
                new_chara_str = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
                meta.add_text('chara', new_chara_str)

                # 4. 保存到【备份路径】 (不修改原图)
                save_kwargs = {"pnginfo": meta, "optimize": True}
                if img.info.get('icc_profile'):
                    save_kwargs["icc_profile"] = img.info.get('icc_profile')
                
                img.save(dst_path, "PNG", **save_kwargs)
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