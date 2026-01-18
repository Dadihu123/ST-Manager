import os
from flask import Blueprint, render_template, send_from_directory, request, session, redirect, url_for

# === 基础设施 ===
from core.config import INTERNAL_DIR, load_config

# 定义蓝图
bp = Blueprint('views', __name__)

@bp.route('/')
def index():
    """
    渲染单页应用入口 (index.html)。
    Flask 会自动在 App 初始化时配置的 template_folder 中查找此文件。
    """
    return render_template('index.html')

@bp.route('/login', methods=['GET', 'POST'])
def login():
    """
    身份验证页面
    """
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        cfg = load_config()
        if username == cfg.get('username') and password == cfg.get('password'):
            session['logged_in'] = True
            return redirect(url_for('views.index'))
        
        return render_template('login.html', error='用户名或密码错误')
        
    return render_template('login.html')

@bp.route('/logout')
def logout():
    """
    注销登录
    """
    session.pop('logged_in', None)
    return redirect(url_for('views.login'))

@bp.route('/favicon.ico')
def favicon():
    """
    处理网站图标请求。
    显式指向内部资源目录，兼容 PyInstaller 打包后的临时路径 (sys._MEIPASS)。
    """
    # 确保路径分隔符在 Windows/Linux 下均正确
    static_images_dir = os.path.join(INTERNAL_DIR, 'static', 'images')
    
    return send_from_directory(
        static_images_dir, 
        'STM.ico', 
        mimetype='image/vnd.microsoft.icon'
    )