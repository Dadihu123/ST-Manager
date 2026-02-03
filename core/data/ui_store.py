import os
import json
import logging
from core.config import DB_FOLDER
from core.consts import RESERVED_RESOURCE_NAMES

# 定义存储文件路径
UI_DATA_FILE = os.path.join(DB_FOLDER, 'ui_data.json')

logger = logging.getLogger(__name__)

VERSION_REMARKS_KEY = '_version_remarks'

def load_ui_data():
    """
    加载 UI 辅助数据 (JSON 格式)。
    包含用户的卡片备注、来源链接、资源文件夹映射等信息。

    Returns:
        dict: UI 数据字典。如果文件不存在或解析失败，返回空字典。
    """
    if os.path.exists(UI_DATA_FILE):
        try:
            with open(UI_DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # === 脏数据清理逻辑 ===
            # 检查 resource_folder 是否使用了系统保留名称 (如 'cards', 'thumbnails' 等)
            dirty = False
            for key, info in data.items():
                rf = info.get('resource_folder', '')
                if rf:
                    # 兼容 Windows/Linux 分隔符，取第一层目录名检查
                    first_part = rf.replace('\\', '/').split('/')[0].lower()
                    if first_part in RESERVED_RESOURCE_NAMES:
                        logger.warning(f"检测到非法资源目录配置 '{rf}' (属于保留目录)，已自动移除关联。")
                        info['resource_folder'] = ""
                        dirty = True
            
            if dirty:
                # 如果有清理操作，立即回写文件以修正
                save_ui_data(data)
                
            return data
        except Exception as e:
            logger.error(f"加载 ui_data.json 失败: {e}")
            return {}
    return {}

def save_ui_data(data):
    """
    保存 UI 辅助数据到 JSON 文件。
    
    Args:
        data (dict): 要保存的数据字典。
    """
    try:
        # 确保父目录存在
        parent_dir = os.path.dirname(UI_DATA_FILE)
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir)
            
        with open(UI_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存 ui_data.json 失败: {e}")
        return False

def get_version_remark(ui_data, ui_key, version_id):
    """
    获取指定版本的备注信息。

    Args:
        ui_data: UI 数据字典
        ui_key: UI 键 (卡片 ID 或 bundle_dir)
        version_id: 版本 ID

    Returns:
        dict: 包含 summary, link, resource_folder 的字典，如果不存在返回空字典
    """
    if ui_key not in ui_data:
        return {}

    entry = ui_data[ui_key]

    if VERSION_REMARKS_KEY in entry and version_id in entry[VERSION_REMARKS_KEY]:
        return entry[VERSION_REMARKS_KEY][version_id]

    return {}

def set_version_remark(ui_data, ui_key, version_id, remark_data):
    """
    设置指定版本的备注信息。

    Args:
        ui_data: UI 数据字典 (会被直接修改)
        ui_key: UI 键 (卡片 ID 或 bundle_dir)
        version_id: 版本 ID
        remark_data: 包含 summary, link, resource_folder 的字典

    Returns:
        bool: 是否需要保存
    """
    if ui_key not in ui_data:
        ui_data[ui_key] = {}

    entry = ui_data[ui_key]

    if VERSION_REMARKS_KEY not in entry:
        entry[VERSION_REMARKS_KEY] = {}

    old_remark = entry[VERSION_REMARKS_KEY].get(version_id, {})
    if old_remark == remark_data:
        return False

    # 存储副本而不是引用，避免外部修改污染已存储的数据
    entry[VERSION_REMARKS_KEY][version_id] = remark_data.copy()
    return True

def migrate_version_remark_to_standalone(ui_data, bundle_dir, version_id):
    """
    将 bundle 下的版本备注迁移为独立卡片的备注。
    用于取消聚合或删除 bundle 时。

    Args:
        ui_data: UI 数据字典
        bundle_dir: bundle 目录路径
        version_id: 版本 ID (即独立后的卡片 ID)

    Returns:
        bool: 是否有数据迁移
    """
    if bundle_dir not in ui_data:
        return False

    entry = ui_data[bundle_dir]

    if VERSION_REMARKS_KEY not in entry:
        return False

    version_remark = entry[VERSION_REMARKS_KEY].get(version_id)
    if not version_remark:
        return False

    ui_data[version_id] = version_remark
    return True

def delete_version_remark(ui_data, bundle_dir, version_id):
    """
    删除 bundle 下指定版本的备注。
    用于删除版本时清理数据。

    Args:
        ui_data: UI 数据字典
        bundle_dir: bundle 目录路径
        version_id: 版本 ID

    Returns:
        bool: 是否有数据被删除
    """
    if bundle_dir not in ui_data:
        return False

    entry = ui_data[bundle_dir]

    if VERSION_REMARKS_KEY not in entry:
        return False

    if version_id not in entry[VERSION_REMARKS_KEY]:
        return False

    del entry[VERSION_REMARKS_KEY][version_id]

    if not entry[VERSION_REMARKS_KEY]:
        del entry[VERSION_REMARKS_KEY]

    return True

def cleanup_stale_version_remarks(ui_data, bundle_dir, valid_version_ids):
    """
    清理 bundle 下已失效版本的备注。
    用于扫描后发现某些版本已被删除时。

    Args:
        ui_data: UI 数据字典
        bundle_dir: bundle 目录路径
        valid_version_ids: 当前有效的版本 ID 列表

    Returns:
        int: 清理的备注数量
    """
    if bundle_dir not in ui_data:
        return 0

    entry = ui_data[bundle_dir]

    if VERSION_REMARKS_KEY not in entry:
        return 0

    removed_count = 0
    versions_to_remove = []

    for version_id in entry[VERSION_REMARKS_KEY]:
        if version_id not in valid_version_ids:
            versions_to_remove.append(version_id)

    for version_id in versions_to_remove:
        del entry[VERSION_REMARKS_KEY][version_id]
        removed_count += 1

    if not entry[VERSION_REMARKS_KEY]:
        del entry[VERSION_REMARKS_KEY]

    return removed_count

def migrate_bundle_remarks_to_versions(ui_data, bundle_dir):
    """
    将 bundle 的版本备注迁移为独立卡片的备注。
    用于 bundle 取消聚合时。

    Args:
        ui_data: UI 数据字典
        bundle_dir: bundle 目录路径

    Returns:
        int: 迁移的备注数量
    """
    if bundle_dir not in ui_data:
        return 0

    entry = ui_data[bundle_dir]
    migrated_count = 0

    if VERSION_REMARKS_KEY in entry:
        for version_id, remark in entry[VERSION_REMARKS_KEY].items():
            ui_data[version_id] = remark
            migrated_count += 1

    return migrated_count