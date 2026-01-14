import os
import time
import sqlite3
import json
import logging
from flask import g

# === 基础设施 ===
from core.config import CARDS_FOLDER, DEFAULT_DB_PATH

# === 工具函数 (用于数据迁移) ===
from core.utils.image import extract_card_info
from core.utils.data import get_wi_meta, sanitize_for_utf8
from core.utils.text import calculate_token_count
from core.utils.hash import get_file_hash_and_size
from core.utils.filesystem import is_card_file

logger = logging.getLogger(__name__)

def get_db():
    """
    获取当前请求上下文中的数据库连接 (Flask g对象)。
    如果连接不存在则创建。
    """
    if 'db' not in g:
        # 连接数据库，设置超时防止锁死
        g.db = sqlite3.connect(DEFAULT_DB_PATH, timeout=30)
        # 设置行工厂，使得查询结果可以通过列名访问 (row['column'])
        g.db.row_factory = sqlite3.Row
        
        # 开启 WAL (Write-Ahead Logging) 模式，提高并发读写性能
        try:
            g.db.execute("PRAGMA journal_mode=WAL;")
            g.db.execute("PRAGMA synchronous=NORMAL;")
        except Exception as e:
            logger.warning(f"Failed to enable WAL mode: {e}")
            
    return g.db

def close_connection(exception):
    """
    关闭数据库连接，注册到 Flask 的 teardown_appcontext。
    """
    db = g.pop('db', None)
    if db is not None:
        db.close()

def execute_with_retry(func, max_retries=5, delay=0.1):
    """
    数据库操作重试包装器。
    解决 SQLite database is locked 问题。
    """
    for i in range(max_retries):
        try:
            return func()
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower():
                if i < max_retries - 1:
                    time.sleep(delay * (i + 1)) # 递增退避策略
                    continue
            raise e
        except Exception as e:
            raise e

def init_database():
    """
    初始化数据库。
    1. 如果数据库文件不存在，创建表结构并执行全量数据迁移。
    2. 如果存在，检查表结构是否需要升级（Migration）。
    """
    # 内部引用，避免循环引用
    from core.context import ctx
    db_path = DEFAULT_DB_PATH
    
    # 检查数据库是否已存在，用于后续判断是否需要扫描文件系统
    is_existing_db = os.path.exists(db_path)
    
    # 更新全局状态
    ctx.set_status(status="initializing", message="正在检查数据库结构...")
    
    # 创建临时连接进行初始化 (不使用 Flask g，因为此时可能不在请求上下文中)
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
    except:
        pass
    
    cursor = conn.cursor()
    
    # === 1. 创建表结构 ===
    
    # 核心角色卡元数据表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS card_metadata (
            id TEXT PRIMARY KEY,
            char_name TEXT,
            description TEXT,
            first_mes TEXT,
            mes_example TEXT,
            tags TEXT,
            category TEXT,
            creator TEXT,
            char_version TEXT,
            last_modified REAL,
            file_hash TEXT,
            file_size INTEGER,
            token_count INTEGER DEFAULT 0,
            has_character_book INTEGER DEFAULT 0,
            character_book_name TEXT DEFAULT ''
        )
    ''')
    
    # 文件夹结构缓存表 (可选，目前主要用于加速目录树构建)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS folder_structure (
            path TEXT PRIMARY KEY,
            name TEXT,
            parent_path TEXT,
            last_scanned REAL
        )
    ''')
    
    # UI 数据缓存表 (用于加速 UI 数据关联查询)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ui_data_cache (
            card_id TEXT PRIMARY KEY,
            summary TEXT,
            link TEXT,
            resource_folder TEXT,
            last_updated REAL
        )
    ''')

    # 世界书剪切板表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wi_clipboard (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content_json TEXT,
            sort_order INTEGER,
            created_at REAL
        )
    ''')
    
    conn.commit()
    
    # === 2. 数据库结构升级 (Migrations) ===
    # 检查列是否存在，如果不存在则添加
    cursor.execute("PRAGMA table_info(card_metadata)")
    columns = [info[1] for info in cursor.fetchall()]
    
    if 'token_count' not in columns:
        print("正在升级数据库: 添加 token_count 列...")
        try:
            cursor.execute("ALTER TABLE card_metadata ADD COLUMN token_count INTEGER DEFAULT 0")
            conn.commit()
        except Exception as e:
            logger.error(f"数据库升级失败 (token_count): {e}")
    
    if 'is_favorite' not in columns:
        print("正在升级数据库: 添加 is_favorite 列...")
        try:
            cursor.execute("ALTER TABLE card_metadata ADD COLUMN is_favorite INTEGER DEFAULT 0")
            conn.commit()
        except Exception as e:
            logger.error(f"数据库升级失败 (is_favorite): {e}")

    if 'has_character_book' not in columns:
        print("正在升级数据库: 添加 has_character_book 列...")
        try:
            cursor.execute("ALTER TABLE card_metadata ADD COLUMN has_character_book INTEGER DEFAULT 0")
            cursor.execute("ALTER TABLE card_metadata ADD COLUMN character_book_name TEXT DEFAULT ''")
            conn.commit()
        except Exception as e:
            logger.error(f"数据库升级失败 (WI columns): {e}")

    # === 3. 数据迁移逻辑 ===
    if not is_existing_db:
        # 全新数据库：执行全量文件扫描导入
        _migrate_existing_data(conn)
    else:
        # 已有数据库：标记为就绪
        ctx.set_status(status="ready", message="启动完成", progress=100)

    conn.close()
    
    ctx.set_status(status="ready")
    print("数据库初始化和表结构检查完成")

def _migrate_existing_data(conn):
    """
    [内部函数] 将现有文件系统中的数据全量迁移到数据库。
    """
    # 内部引用，避免循环引用
    from core.context import ctx
    ctx.set_status(status="processing", message="正在扫描文件系统...")
    
    file_list = []
    skipped_files = []
    
    print("正在扫描文件列表...")
    for root, dirs, files in os.walk(CARDS_FOLDER):
        for f in files:
            if is_card_file(f):
                file_list.append(os.path.join(root, f))
    
    total_files = len(file_list)
    ctx.set_status(total=total_files)

    if total_files == 0:
        print("未发现角色卡，跳过导入。")
        ctx.set_status(status="ready", message="未发现文件，准备就绪", progress=0)
        return

    ctx.set_status(status="processing", message=f"发现 {total_files} 张卡片，开始导入...")
    print(f"开始导入 {total_files} 张卡片...")
    
    cursor = conn.cursor()
    card_count = 0
    error_count = 0
    
    for full_path in file_list:
        clean_path = sanitize_for_utf8(full_path)
        try:
            # 计算相对路径 ID (统一使用 / 作为分隔符)
            rel_path = os.path.relpath(full_path, CARDS_FOLDER)
            file_id_path = rel_path.replace('\\', '/')
            
            # 计算分类
            if '/' in file_id_path:
                category = file_id_path.rsplit('/', 1)[0]
            else:
                category = ""
            
            # 提取基础信息
            try:
                file_hash, file_size = get_file_hash_and_size(full_path)
            except Exception as e:
                # 即使哈希失败也继续，只是哈希为空
                file_hash, file_size = "", 0
                print(f"File access error: {clean_path} - {e}")
            
            # 解析卡片内容
            info = extract_card_info(full_path)
            
            if not info:
                # 无法解析为卡片，跳过
                continue
            
            # 提取数据块 (兼容 V2/V3)
            data_block = info.get('data', {}) if 'data' in info else info
            
            # 处理标签
            tags = data_block.get('tags', [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(',') if t.strip()]
            elif tags is None:
                tags = []
            tags = list(dict.fromkeys([str(t).strip() for t in tags if str(t).strip()])) # 去重
            
            # 处理名称
            char_name = info.get('name') or data_block.get('name') or os.path.splitext(os.path.basename(clean_path))[0]
            
            # 获取修改时间
            try:
                mtime = os.path.getmtime(full_path)
            except:
                mtime = 0
            
            # 计算 Token
            calc_data = data_block.copy()
            if 'name' not in calc_data:
                calc_data['name'] = char_name
            token_count = calculate_token_count(calc_data)
            
            # 检查是否包含世界书
            has_wi, wi_name = get_wi_meta(data_block)
            
            # 插入数据库
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO card_metadata
                    (id, char_name, description, first_mes, mes_example, tags, category, creator, char_version, last_modified, file_hash, file_size, token_count, has_character_book, character_book_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    file_id_path, char_name, data_block.get('description', ''),
                    data_block.get('first_mes', ''), data_block.get('mes_example', ''),
                    json.dumps(tags), category, data_block.get('creator', ''),
                    data_block.get('character_version', ''), mtime, file_hash, file_size,
                    token_count, has_wi, wi_name
                ))
                card_count += 1
            except Exception as db_e:
                print(f"❌ 数据库插入失败: {file_id_path} - {db_e}")
                skipped_files.append((file_id_path, str(db_e)))
                error_count += 1
                continue
            
            # 批量提交并更新状态
            if card_count % 50 == 0:
                try:
                    conn.commit()
                    ctx.set_status(progress=card_count, message=f"正在导入: {card_count}/{total_files}")
                except Exception:
                    conn.rollback()
                    
        except Exception as outer_e:
            print(f"❌ 处理文件异常: {clean_path} - {outer_e}")
            error_count += 1
            continue
    
    # 最终提交
    try:
        conn.commit()
    except Exception as final_e:
        print(f"❌ 最终提交失败: {final_e}")
        conn.rollback()
    
    # 打印简报
    print(f"✅ 数据库迁移完成: 成功 {card_count} / 失败 {error_count}")
    
    ctx.set_status(status="processing", message="迁移完成，正在加载缓存...", progress=total_files)

def backfill_wi_metadata():
    """
    后台任务：检查数据库中尚未标记 WI 的卡片，补充 has_character_book 字段。
    用于解决旧版本数据库升级后，旧卡片不显示在世界书列表的问题。
    """
    # 稍作等待，确保主初始化流程先释放资源
    time.sleep(3)
    print("正在后台检查角色卡世界书索引...")
    
    db_path = DEFAULT_DB_PATH
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            cursor = conn.cursor()
            # 查找尚未检查过 WI 的记录 (has_character_book = 0)
            cursor.execute("SELECT id FROM card_metadata WHERE has_character_book = 0")
            rows = cursor.fetchall()
            
            updates = []
            for row in rows:
                card_id = row[0]
                full_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
                
                if os.path.exists(full_path):
                    info = extract_card_info(full_path)
                    if info:
                        data = info.get('data', {}) if 'data' in info else info
                        has_wi, wi_name = get_wi_meta(data)
                        if has_wi:
                            updates.append((1, wi_name, card_id))
            
            if updates:
                print(f"发现 {len(updates)} 张旧卡片包含世界书，正在更新索引...")
                cursor.executemany("UPDATE card_metadata SET has_character_book = ?, character_book_name = ? WHERE id = ?", updates)
                conn.commit()
                print("世界书索引更新完成。")
    except Exception as e:
        logger.error(f"Backfill WI metadata error: {e}")