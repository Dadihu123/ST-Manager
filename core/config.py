import sys
import os
import json

# --- 智能判断根目录 (兼容 PyInstaller) ---
if getattr(sys, 'frozen', False):
    # PyInstaller 打包后的环境
    BASE_DIR = os.path.dirname(sys.executable)
    INTERNAL_DIR = sys._MEIPASS
else:
    # 如果是正常的 Python 脚本运行环境
    _current_dir = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = os.path.dirname(_current_dir)
    INTERNAL_DIR = BASE_DIR

CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')

# === v2.0 目录结构定义 ===
DATA_DIR = os.path.join(BASE_DIR, 'data')

# 系统数据目录 (DB, Thumbnails, Trash)
SYSTEM_DIR = os.path.join(DATA_DIR, 'system')
DB_FOLDER = os.path.join(SYSTEM_DIR, 'db')
DEFAULT_DB_PATH = os.path.join(DB_FOLDER, 'cards_metadata.db')
THUMB_FOLDER = os.path.join(SYSTEM_DIR, 'thumbnails')
TRASH_FOLDER = os.path.join(SYSTEM_DIR, 'trash')
TEMP_DIR = os.path.join(DATA_DIR, 'temp')

# 确保核心系统目录存在
for d in [DATA_DIR, SYSTEM_DIR, DB_FOLDER, THUMB_FOLDER, TRASH_FOLDER, TEMP_DIR]:
    if not os.path.exists(d):
        try: os.makedirs(d)
        except: pass

# 默认配置
DEFAULT_CONFIG = {
    "cards_dir": "data/library/characters",  # 默认为相对路径 'cards'
    "world_info_dir": "data/library/lorebooks",
    "default_sort": "date_desc",
    "theme_accent": "blue",
    "host": "127.0.0.1",
    "port": 5000,
    "resources_dir": "data/assets/card_assets",
    "st_url": "http://127.0.0.1:8000",
    "st_auth_type": "basic",  # 'basic' or 'web'
    "st_username": "",
    "st_password": "",
    "items_per_page": 0,
    "items_per_page_wi": 0,
    "dark_mode": True,
    "font_style": "sans",      # 字体: sans, serif, mono
    "card_width": 220,         # 卡片宽度
    "bg_url": "/assets/backgrounds/default_background.jpeg",  # 默认背景图路径
    "bg_opacity": 0.45,        # 默认遮罩浓度
    "bg_blur": 2,               # 默认模糊度
    "auto_save_enabled": False, # 是否自动保存
    "auto_save_interval": 3,   # 默认 3 分钟
    "snapshot_limit_manual": 50, # 手动快照保留数量上限
    "snapshot_limit_auto": 5,    # 自动快照保留数量上限

    # 是否启用自动文件系统监听（watchdog）以触发扫描
    # 设为 False 时，仅保留后台扫描线程，手动触发的扫描任务仍然有效
    "enable_auto_scan": True,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except:
        return False

# 初始化全局变量 CARDS_FOLDER 和 WI_FOLDER
current_config = load_config()

# 1. 角色卡目录
raw_cards_dir = current_config.get('cards_dir', 'data/library/characters')
if os.path.isabs(raw_cards_dir):
    CARDS_FOLDER = raw_cards_dir
else:
    CARDS_FOLDER = os.path.join(BASE_DIR, raw_cards_dir)

if not os.path.exists(CARDS_FOLDER):
    try: os.makedirs(CARDS_FOLDER)
    except: print(f"Warning: Could not create folder {CARDS_FOLDER}")

# 2. 世界书目录
raw_wi_dir = current_config.get('world_info_dir', 'data/library/lorebooks')
if os.path.isabs(raw_wi_dir):
    WI_FOLDER = raw_wi_dir
else:
    WI_FOLDER = os.path.join(BASE_DIR, raw_wi_dir)

if not os.path.exists(WI_FOLDER):
    try: os.makedirs(WI_FOLDER)
    except: pass