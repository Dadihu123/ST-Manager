"""全局测试隔离：确保测试永远不会写入真实的用户数据目录。

背景：`core/data/ui_store.py` 的 `UI_DATA_FILE` 在 import 时就绑定到
`data/system/db/ui_data.json`。部分测试直接调用真实 `save_ui_data()`（只替换
了上层 API 的引用），于是会把测试数据写进开发机上真实的用户数据里 —— 实测
`test_beautify_api.py` / `test_card_source_revision.py` /
`test_folder_rename_move_sync.py` 都会污染真实 ui_data.json 及其轮转备份。

这里在测试会话开始前把 ui_store / chat_store 的落盘路径重定向到临时目录，
让所有测试天然与真实数据隔离，无需每个用例各自 monkeypatch。
"""

import atexit
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_ISOLATION_DIR = Path(tempfile.mkdtemp(prefix='stm_pytest_isolation_'))
_DB_DIR = _ISOLATION_DIR / 'system' / 'db'
_DB_DIR.mkdir(parents=True, exist_ok=True)

_ORIGINAL_PATHS = {}


def _redirect(module, attribute, target_path):
    """把模块级路径常量指向隔离目录。"""
    if module is None or not hasattr(module, attribute):
        return
    _ORIGINAL_PATHS[(module.__name__, attribute)] = getattr(module, attribute)
    setattr(module, attribute, str(target_path))


def _install_isolation():
    """把 ui_data / chat_data 的落盘位置改到临时目录。"""
    from core.data import chat_store as chat_store_module
    from core.data import ui_store as ui_store_module

    _redirect(ui_store_module, 'UI_DATA_FILE', _DB_DIR / 'ui_data.json')
    _redirect(chat_store_module, 'CHAT_DATA_FILE', _DB_DIR / 'chat_data.json')


_install_isolation()


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001 - pytest hook signature
    """会话结束后清理隔离目录。"""
    shutil.rmtree(_ISOLATION_DIR, ignore_errors=True)


@atexit.register
def _cleanup_isolation_dir():
    shutil.rmtree(_ISOLATION_DIR, ignore_errors=True)
