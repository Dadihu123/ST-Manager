import os
from flask import Blueprint, render_template, send_from_directory

# === 基础设施 ===
from core.config import INTERNAL_DIR

# 定义蓝图
bp = Blueprint('views', __name__)

@bp.route('/')
def index():
    """
    渲染单页应用入口 (index.html)。
    Flask 会自动在 App 初始化时配置的 template_folder 中查找此文件。
    """
    return render_template('index.html')

@bp.route('/favicon.ico')
def favicon():
    """
    处理网站图标请求。
    显式指向内部资源目录，兼容 PyInstaller 打包后的临时路径 (sys._MEIPASS)。
    """
    # 确保路径分隔符在 Windows/Linux 下均正确
    static_brand_dir = os.path.join(INTERNAL_DIR, 'static', 'images', 'brand')
    
    return send_from_directory(
        static_brand_dir,
        'stm-mark.png',
        mimetype='image/png'
    )
