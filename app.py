import argparse
import sys
import os

# 显示将当前工作目录添加到系统路径中
base_path = os.path.dirname(os.path.abspath(__file__))
if base_path not in sys.path:
    sys.path.insert(0, base_path)

import threading
import webbrowser
import platform

# 设置 UTF-8 输出编码，支持 emoji 显示（兼容 Windows）
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# 确保在 PyInstaller 打包环境下也能正确找到资源
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

# 导入核心工厂和初始化函数
# create_app: 创建 Flask 应用实例
# init_services: 初始化数据库、缓存和后台扫描线程
from core import create_app, init_services
from core.config import ensure_config_file, ensure_runtime_dirs, load_config
from core.utils.net import is_port_available


def is_running_in_docker():
    if os.path.exists('/.dockerenv'):
        return True

    cgroup_path = '/proc/1/cgroup'
    if not os.path.exists(cgroup_path):
        return False

    try:
        with open(cgroup_path, 'r', encoding='utf-8') as f:
            cgroup_content = f.read()
            return 'docker' in cgroup_content or 'containerd' in cgroup_content
    except OSError:
        return False


def parse_cli_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Start ST-Manager. Command-line host/port overrides affect only the current run.'
    )
    parser.add_argument('--debug', action='store_true', help='Enable debug mode and auto reload for the current run')
    parser.add_argument('--host', help='Override the server host for the current run only')
    parser.add_argument('--port', type=int, help='Override the server port for the current run only')
    return parser.parse_args(argv)


def get_default_config_overrides(in_docker):
    return {'host': '0.0.0.0'} if in_docker else None


def ensure_startup_config(in_docker):
    ensure_config_file(default_overrides=get_default_config_overrides(in_docker))
    cfg = load_config()
    ensure_runtime_dirs(cfg)
    return cfg


def resolve_server_settings(cfg, cli_args):
    host = cli_args.host if cli_args.host is not None else cfg.get('host', '127.0.0.1')
    port = cli_args.port if cli_args.port is not None else cfg.get('port', 5000)
    debug = cli_args.debug or os.environ.get('FLASK_DEBUG') == '1'
    return host, port, debug

if __name__ == '__main__':
    cli_args = parse_cli_args()
    in_docker = is_running_in_docker()

    try:
        cfg = ensure_startup_config(in_docker)
    except Exception as exc:
        print(f'❌ 配置文件生成失败: {exc}')
        if platform.system() == 'Windows':
            os.system('pause')
        sys.exit(1)

    # 1. 加载配置
    server_host, server_port, debug_mode = resolve_server_settings(cfg, cli_args)

    # 2. 端口占用检测
    # 如果端口被占用，给出友好提示并暂停（防止窗口闪退）
    # 注意：在 Flask Debug 模式(Reload)下，子进程启动时端口可能已被保留，因此仅在主进程检测
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        if not is_port_available(server_port, server_host):
            print(f"\n{'='*60}")
            print(f"❌ 启动失败：地址 {server_host}:{server_port} 已被占用！")
            print(f"{'='*60}")
            print(f"可能的原因：")
            print(f"1. 另一个 ST Manager 实例已经在运行中。")
            print(f"2. 其他程序（如 SillyTavern）占用了此端口。")
            print(f"\n请尝试：")
            print(f" - 关闭已运行的窗口。")
            print(f" - 修改 config.json 中的 'port' 或 'host' 设置。")
            print(f"{'='*60}\n")
            
            if platform.system() == "Windows":
                os.system("pause")
            sys.exit(1)

    # 3. 启动后台服务 
    # (数据库初始化 -> 加载缓存 -> 启动扫描器)
    # daemon=True 保证主程序退出时线程自动结束，防止僵尸进程

    # 3.0 数据目录独占锁：防止两个进程共用同一份 data/ 互相覆盖 ui_data.json。
    # 在 Debug 模式下，仅在真正的工作进程 (WERKZEUG_RUN_MAIN="true") 中加锁，
    # 避免 Watcher 进程与工作进程互相冲突。
    if not debug_mode or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        from core.config import DATA_DIR
        from core.data.data_dir_lock import acquire_data_directory_lock

        if not acquire_data_directory_lock(DATA_DIR):
            print(f"\n{'='*60}")
            print("❌ 启动失败：数据目录已被另一个 ST Manager 实例占用！")
            print(f"{'='*60}")
            print(f"数据目录: {DATA_DIR}")
            print("同时运行多个实例会互相覆盖本地备注、链接与标签分类等数据。")
            print("\n请尝试：")
            print(" - 关闭已运行的其他 ST Manager 窗口/进程。")
            print(" - 若确认没有实例在运行，可删除数据目录下的 st_manager.lock 后重试。")
            print(f"{'='*60}\n")
            if platform.system() == "Windows":
                os.system("pause")
            sys.exit(1)

    # 在 Debug 模式下，仅在 Reload 子进程 (WERKZEUG_RUN_MAIN="true") 中启动后台服务
    # 避免在 Watcher 进程中重复启动
    if not debug_mode or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        threading.Thread(target=init_services, daemon=True).start()

    # 4. 自动打开浏览器
    # 仅在非 Reload 模式下执行，防止开发时每次保存代码都弹窗
    # WERKZEUG_RUN_MAIN 是 Flask debug 模式下的环境变量
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        try:
            # 如果绑定的是 0.0.0.0，浏览器打开 127.0.0.1
            open_host = '127.0.0.1' if server_host == '0.0.0.0' else server_host
            threading.Timer(0.5, lambda: webbrowser.open(f"http://{open_host}:{server_port}")).start()
        except: 
            pass

    # 5. 创建并运行 Flask 应用
    print(f"🚀 服务器已启动: http://{server_host}:{server_port}")
    if debug_mode:
        print(f"🔧 Debug 模式: 开启 (Hot Reload enabled)")
    
    app = create_app()
    
    try:
        # use_reloader=False: 在生产或打包环境建议关闭，避免双进程导致 Context 初始化两次
        # debug=False: 生产环境关闭
        app.run(debug=debug_mode, host=server_host, port=server_port, use_reloader=debug_mode)
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"❌ 端口 {server_port} 被占用。")
        else:
            print(f"❌ 服务器异常退出: {e}")
        
        if platform.system() == "Windows":
            os.system("pause")
