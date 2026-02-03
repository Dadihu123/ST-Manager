import os
import shutil
import logging
import threading
import traceback
import mimetypes
from flask import Flask

# === 基础设施 ===
from core.config import INTERNAL_DIR, BASE_DIR, TEMP_DIR
from core.context import ctx
from core.auth import init_auth

# === 数据与服务 ===
from core.data.db_session import init_database, close_connection, backfill_wi_metadata
from core.services.scan_service import start_background_scanner

# === API 蓝图 ===
from core.api.v1 import cards, world_info, system, resources, automation, extensions, presets, st_sync
from core.api import views

logger = logging.getLogger(__name__)

def create_app():
    """
    Flask 应用工厂函数。
    负责初始化 Flask 实例、注册蓝图、配置数据库钩子。
    """
    # 配置日志
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 强制 MIME 类型映射，防止注册表异常
    mimetypes.add_type('application/javascript', '.js')
    mimetypes.add_type('text/css', '.css') 
    app = Flask(__name__, 
                static_folder=os.path.join(INTERNAL_DIR, 'static'),
                template_folder=os.path.join(INTERNAL_DIR, 'templates'))
    
    # 注册数据库连接关闭钩子 (在请求结束时自动调用)
    app.teardown_appcontext(close_connection)
    
    # === 注册蓝图 (Blueprints) ===
    
    # 1. 核心业务 API (V1)
    app.register_blueprint(cards.bp)       # 角色卡管理
    app.register_blueprint(world_info.bp)  # 世界书管理
    app.register_blueprint(system.bp)      # 系统设置与操作
    app.register_blueprint(resources.bp)   # 静态资源服务 (图片/缩略图)
    app.register_blueprint(automation.bp)  # 自动化任务管理
    app.register_blueprint(extensions.bp)  # 扩展脚本管理
    app.register_blueprint(presets.bp)     # 预设管理
    app.register_blueprint(st_sync.bp)     # SillyTavern 资源同步
    
    # 2. 页面视图
    app.register_blueprint(views.bp)       # 前端页面入口
    
    # 3. 初始化外网访问认证
    init_auth(app)
    
    return app

def cleanup_temp_files():
    """
    启动时清空临时目录 (data/temp)
    """
    try:
        if not os.path.exists(TEMP_DIR):
            return

        count = 0
        for filename in os.listdir(TEMP_DIR):
            full_path = os.path.join(TEMP_DIR, filename)
            try:
                if os.path.isfile(full_path) or os.path.islink(full_path):
                    os.remove(full_path)
                    count += 1
                elif os.path.isdir(full_path):
                    shutil.rmtree(full_path)
                    count += 1
            except Exception as e:
                logger.warning(f"Failed to delete temp item {filename}: {e}")
        
        if count > 0:
            logger.info(f"Cleaned up {count} items in temporary directory.")
    except Exception as e:
        logger.warning(f"Error during temp directory cleanup: {e}")

def init_services():
    """
    后台服务初始化函数。
    通常在 app.py 的独立线程中运行，避免阻塞 Web 服务启动。
    """
    print("正在启动后台服务...")
    ctx.set_status(status="initializing", message="正在初始化数据库...")
    
    # 0. 清理残留临时文件
    cleanup_temp_files()
    
    try:
        # 1. 数据库初始化 (建表、迁移)
        init_database()

        # 2. 缓存加载
        # 数据库就绪后，将数据全量加载到内存缓存中，加速后续查询
        print("正在加载缓存...")
        ctx.set_status(status="initializing", message="正在加载缓存...")
        
        if ctx.cache:
            ctx.cache.reload_from_db()
        else:
            logger.error("Cache component not initialized in Context!")
        
        # 3. 数据修正 (后台任务)
        # 检查并修复旧版数据的索引 (如 WI 关联)
        threading.Thread(target=backfill_wi_metadata, daemon=True).start()
        
        # 4. 启动文件系统扫描器
        # 负责监听文件变动并同步到数据库
        start_background_scanner()
        
        # 初始化完成
        ctx.set_status(status="ready", message="服务已就绪")
        print("✅ 后台服务启动完成")
        
    except Exception as e:
        logger.error(f"Service initialization failed: {e}")
        traceback.print_exc() 
        ctx.set_status(status="error", message=f"启动失败: {e}")