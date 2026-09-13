import os
import json
import base64
import hashlib
import shutil
import logging
from PIL import Image, PngImagePlugin
from core.consts import SIDECAR_EXTENSIONS
from core.config import INTERNAL_DIR, load_config
from core.utils.data import normalize_card_v3, deterministic_sort, sanitize_for_utf8
from core.utils.format_validation import is_valid_character_card_data
from core.utils.filesystem import save_json_atomic

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

def extract_card_info(filepath):
    try:
        data = None
        # 1. 处理 JSON 文件
        if filepath.lower().endswith('.json'):
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                data = json.load(f)
        else:
            # 2. 处理 PNG 文件
            with Image.open(filepath) as img:
                # === 强制加载图片数据，确保读取到完整元数据 ===
                img.load()
                
                metadata = img.info or {}
                raw = metadata.get('chara') or metadata.get('ccv3')
                
                if not raw:
                    return None

                result = None

                # === 策略 A: 尝试直接解析为 JSON (针对某些 V3 卡片直接存明文的情况) ===
                try:
                    # 某些特殊情况下 raw 可能是 bytes，先尝试转 str 判断是否以 { 开头
                    raw_str = raw
                    if isinstance(raw_str, bytes):
                        raw_str = raw_str.decode('utf-8', errors='ignore')
                    raw_str = str(raw_str).strip()
                    
                    if raw_str.startswith('{') or raw_str.startswith('['):
                        result = json.loads(raw_str)
                except:
                    pass

                # === 策略 B: 你的旧版逻辑 (最稳健的标准 Base64 解码) ===
                if result is None:
                    try:
                        # 直接交给 b64decode，它能很好地处理 bytes，不需要我们可以转 string
                        decoded = base64.b64decode(raw).decode('utf-8')
                        result = json.loads(decoded)
                    except:
                        pass

                # === 策略 C: 增强型 Base64 解码 (处理 Padding 缺失等边缘情况) ===
                if result is None:
                    try:
                        if isinstance(raw, bytes):
                            raw = raw.decode('utf-8', errors='ignore')
                        raw = str(raw).strip()
                        padded = raw + ('=' * (-len(raw) % 4))
                        
                        # 尝试 URL-Safe 解码 (部分 Web 工具生成的卡片)
                        try:
                            decoded = base64.urlsafe_b64decode(padded).decode('utf-8', errors='ignore')
                            result = json.loads(decoded)
                        except:
                            # 尝试标准解码 + Padding
                            decoded = base64.b64decode(padded).decode('utf-8', errors='ignore')
                            result = json.loads(decoded)
                    except:
                        pass

                data = result
        if data:
            dirty_flags = []
            cleaned_data = sanitize_for_utf8(data, dirty_tracker=dirty_flags)
            
            if dirty_flags:
                # 打印醒目的日志
                msg = f"⚠️ [自动修复] 检测到元数据编码异常 (Unicode Error)，已过滤非法字符: {filepath}"
                print(msg) 
                logger.warning(msg)
                
            if not is_valid_character_card_data(cleaned_data):
                return None

            return cleaned_data

        return None

    except Exception as e:
        # print(f"Error parsing {filepath}: {e}") # 调试用
        return None

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
        new_chara_str = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        # 2. 打开图片 (此时图片像素已经是新的了)
        img = Image.open(filepath)

        # 尝试获取原图的 ICC 颜色配置文件，防止颜色偏差
        icc_profile = img.info.get('icc_profile')

        # 3. 准备 Metadata
        meta = PngImagePlugin.PngInfo()
        # 保留原图非角色数据的其他元数据
        for k, v in img.info.items():
            if k not in ['chara', 'ccv3'] and isinstance(v, str):
                meta.add_text(k, v)
        # 4. 写入核心数据
        meta.add_text('chara', new_chara_str)

        # 保存参数设置
        save_kwargs = {"pnginfo": meta}
        save_kwargs["optimize"] = True
        if icc_profile:
            save_kwargs["icc_profile"] = icc_profile

        # 5. 保存
        img.save(filepath, "PNG", **save_kwargs)
        return True
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
    主动删除指定卡片 ID 对应的 WebP 缩略图缓存。
    确保下次请求时，服务器会重新从原图生成最新的缩略图。
    """
    try:
        # 逻辑必须与 serve_thumbnail 中的 hash 逻辑一致
        filename = os.path.basename(rel_path)
        
        # 如果是 JSON 卡片，serve_thumbnail 是根据同名图片生成的 hash
        # 而 api_update_card_file 中我们通常已经把它转成了 .png 或本身就是 .png
        # 简单起见，尝试清理 .png 后缀对应的缓存
        base_name = os.path.splitext(filename)[0]
        potential_names = [filename, base_name + ".png"]
        
        for name in potential_names:
            thumb_hash_name = hashlib.md5(name.encode('utf-8')).hexdigest() + ".webp"
            thumb_path = os.path.join(thumb_folder, thumb_hash_name)
            if os.path.exists(thumb_path):
                os.remove(thumb_path)
                # print(f"DEBUG: 已清理缩略图缓存 {thumb_path}")    
    except Exception as e:
        print(f"清理缩略图失败: {e}")
