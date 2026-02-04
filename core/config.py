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
    "cards_dir": "data/library/characters",
    "world_info_dir": "data/library/lorebooks",
    "presets_dir": "data/library/presets",
    "regex_dir": "data/library/extensions/regex",
    "scripts_dir": "data/library/extensions/tavern_helper",
    "quick_replies_dir": "data/library/extensions/quick-replies", 
    "default_sort": "date_desc",
    "theme_accent": "blue",
    "host": "127.0.0.1",
    "port": 5000,
    "resources_dir": "data/assets/card_assets",
    "st_url": "http://127.0.0.1:8000",
    "st_data_dir": "",  # SillyTavern 安装目录，留空则自动探测
    "st_auth_type": "basic",  # 'basic' or 'web'
    "st_username": "",
    "st_password": "",
    "st_proxy": "",
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

    # PNG 元数据是否使用确定性排序（默认关闭，避免改变外部工具的字节级行为）
    "png_deterministic_sort": False,

    # 允许访问的绝对资源目录白名单（仅影响资源文件列表接口）
    # 例: ["D:/SillyTavern/assets", "E:/resources"]
    "allowed_abs_resource_roots": [],

    # 世界书详情预览优化
    # preview_limit: 预览最大条目数（0 表示不限制）
    # preview_entry_max_chars: 单条内容最大字符数（0 表示不截断）
    "wi_preview_limit": 300,
    "wi_preview_entry_max_chars": 2000,

    # 外网访问身份验证（本地/局域网访问不受限制）
    # 仅当 auth_username 和 auth_password 都设置时才启用
    "auth_username": "",
    "auth_password": "",
    # IP 白名单：这些 IP 无需登录即可访问
    # 支持格式：单个 IP ("192.168.1.100")、CIDR ("192.168.1.0/24")、通配符 ("192.168.*.*")
    # 默认已包含 127.0.0.1 和 ::1 (本机)，无需手动添加
    "auth_trusted_ips": [],
    # 受信任代理列表：仅当请求来自这些代理时才信任 X-Forwarded-For / X-Real-IP
    # 建议仅包含反向代理/内网穿透服务的出口 IP
    # 默认包含本机 127.0.0.1 / ::1（本地反向代理常见）
    "auth_trusted_proxies": [],
    # 登录失败限流/锁定
    # max_attempts: 失败次数阈值
    # fail_window_seconds: 统计窗口（秒）
    # lockout_seconds: 锁定时长（秒）
    "auth_max_attempts": 5,
    "auth_fail_window_seconds": 600,
    "auth_lockout_seconds": 900,
    # 连续失败触发“锁定模式”（需要手动重启）
    # hard_lock_threshold: 连续失败次数阈值
    "auth_hard_lock_threshold": 50,

    # 导入文件时是否使用角色名自动重命名文件
    # 设为 False 则保留原始文件名（仅处理冲突时添加序号）
    "auto_rename_on_import": True,
}

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except:
            return DEFAULT_CONFIG
    return DEFAULT_CONFIG

class ConfigProxy:
    def _load(self):
        return load_config()

    def get(self, key, default=None):
        return self._load().get(key, default)

    def __getitem__(self, key):
        return self._load()[key]

    def __contains__(self, key):
        return key in self._load()

    def items(self):
        return self._load().items()

    def keys(self):
        return self._load().keys()

    def values(self):
        return self._load().values()

    def to_dict(self):
        return self._load()

def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except:
        return False

def _ensure_dir(path: str) -> str:
    try:
        if path and not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path

def _resolve_dir(cfg: dict, key: str, default: str) -> str:
    raw = cfg.get(key, default)
    if os.path.isabs(raw):
        return raw
    return os.path.join(BASE_DIR, raw)

def get_cards_folder() -> str:
    cfg = load_config()
    return _ensure_dir(_resolve_dir(cfg, 'cards_dir', 'data/library/characters'))

def get_world_info_folder() -> str:
    cfg = load_config()
    return _ensure_dir(_resolve_dir(cfg, 'world_info_dir', 'data/library/lorebooks'))

class DynamicPath:
    def __init__(self, getter):
        self._getter = getter

    def __fspath__(self):
        return self._getter()

    def __str__(self):
        return self._getter()

    def __repr__(self):
        return self._getter()

# 初始化全局变量 CARDS_FOLDER 和 WI_FOLDER（动态路径）
CARDS_FOLDER = DynamicPath(get_cards_folder)
WI_FOLDER = DynamicPath(get_world_info_folder)

# 兼容旧逻辑：提供动态读取的配置访问器
current_config = ConfigProxy()
