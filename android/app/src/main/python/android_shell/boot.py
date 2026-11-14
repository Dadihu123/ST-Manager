"""Android 壳入口：先声明路径，再导入 core；绑定成功后才向宿主报告就绪。"""

import logging
import os
import threading

logger = logging.getLogger(__name__)
_server = None
_lock = threading.Lock()
_services_started = False


def _prepare_runtime(internal_dir: str = '', data_root: str = '') -> dict:
    os.environ['STM_ANDROID_SHELL'] = '1'
    os.environ['STM_DATA_ROOT'] = os.path.abspath(data_root or os.environ['HOME'])
    if internal_dir:
        os.environ['STM_INTERNAL_ROOT'] = os.path.abspath(internal_dir)

    from core.config import BASE_DIR, INTERNAL_DIR, ensure_config_file, ensure_runtime_dirs, load_config

    # 禁止运行中改根：模块级路径常量必须在首次 import 前确定。
    if BASE_DIR != os.environ['STM_DATA_ROOT']:
        raise RuntimeError('数据根已初始化，切换目录需要重启应用')
    if internal_dir and INTERNAL_DIR != os.environ['STM_INTERNAL_ROOT']:
        raise RuntimeError('资源根已初始化，更新资源需要重启应用')
    ensure_config_file(default_overrides={'enable_auto_scan': False})
    cfg = load_config()
    cfg['enable_auto_scan'] = False
    ensure_runtime_dirs(cfg)
    return {'base_dir': BASE_DIR, 'internal_dir': INTERNAL_DIR, 'enable_auto_scan': False}


def start_server(port: int = 17863, internal_dir: str = '', data_root: str = '') -> int:
    """幂等启动。make_server 持有绑定的 socket，返回后监听者必为本次后端。"""
    global _server, _services_started
    with _lock:
        if _server is not None:
            return _server.server_port
        runtime = _prepare_runtime(internal_dir, data_root)
        from core import create_app, init_services
        from werkzeug.serving import make_server

        app = create_app()
        server = make_server('127.0.0.1', int(port), app, threaded=True)
        threading.Thread(target=server.serve_forever, name='stm-flask', daemon=True).start()
        _server = server
        if not _services_started:
            threading.Thread(target=init_services, daemon=True).start()
            _services_started = True
        logger.info('Android 运行时: %s', runtime)
        return server.server_port
