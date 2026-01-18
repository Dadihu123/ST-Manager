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

# 确保核心系统目录存在
for d in [DATA_DIR, SYSTEM_DIR, DB_FOLDER, THUMB_FOLDER, TRASH_FOLDER]:
    if not os.path.exists(d):
        try: 
            os.makedirs(d)
        except: 
            pass

def ensure_config_dirs(cfg):
    """确保配置中指定的业务目录存在"""
    dirs_to_check = [
        cfg.get("cards_dir"),
        cfg.get("world_info_dir"),
        cfg.get("resources_dir")
    ]
    for d in dirs_to_check:
        if d:
            # 如果是相对路径，则相对于 BASE_DIR
            full_path = os.path.isabs(d) and d or os.path.join(BASE_DIR, d)
            if not os.path.exists(full_path):
                try:
                    os.makedirs(full_path, exist_ok=True)
                except Exception as e:
                    print(f"Failed to create directory {full_path}: {e}")

# 默认配置
DEFAULT_CONFIG = {
    "cards_dir": "data/library/characters",  # 默认为相对路径 'cards'
    "world_info_dir": "data/library/lorebooks",
    "default_sort": "date_desc",
    "theme_accent": "blue",
    "host": os.environ.get("HOST", "127.0.0.1"),
    "port": int(os.environ.get("PORT", 5000)),
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
    "auth_enabled": False,       # 是否启用登录认证
    "username": "admin",         # 认证用户名
    "password": "password",      # 认证密码
    "secret_key": "st-manager-secret-key" # 用于 Session 加密的密钥
}

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    cfg.update(data)
        except Exception as e:
            print(f"Error loading config.json: {e}")
    else:
        # 如果配置文件不存在，或者是一个文件夹 (Docker Windows 常见错误)，则尝试处理
        if os.path.isdir(CONFIG_FILE):
            print(f"⚠️ 警告: {CONFIG_FILE} 是一个目录而不是文件。")
            print("这通常是因为在 Docker 命令或 compose 中挂载了不存在的 config.json 文件，Docker 自动创建了同名文件夹。")
            print("请删除该文件夹并在宿主机创建一个空的 config.json 文件后再运行。")
        else:
            # 如果完全不存在，自动创建一个默认的
            save_config(cfg)
            
    # 环境变量优先级最高，确保 Docker 部署正常
    if os.environ.get("HOST"):
        cfg["host"] = os.environ.get("HOST")
    if os.environ.get("PORT"):
        try:
            cfg["port"] = int(os.environ.get("PORT"))
        except:
            pass
            
    # 确保业务目录存在
    ensure_config_dirs(cfg)
    
    return cfg

def save_config(cfg):
    global current_config
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        current_config = cfg
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