"""全局测试隔离：确保测试永远不会写入真实的用户数据目录。

背景：`core/data/ui_store.py` 的 `UI_DATA_FILE` 在 import 时就绑定到
`data/system/db/ui_data.json`。部分测试直接调用真实 `save_ui_data()`（只替换
了上层 API 的引用），于是会把测试数据写进开发机上真实的用户数据里 —— 实测
`test_beautify_api.py` / `test_card_source_revision.py` /
`test_folder_rename_move_sync.py` 都会污染真实 ui_data.json 及其轮转备份。

这里在测试会话开始前把 ui_store / chat_store 的落盘路径重定向到临时目录，
让所有测试天然与真实数据隔离，无需每个用例各自 monkeypatch。

另外统一测试期的文本编码（见下方 `_force_utf8_text_io`）。
"""

import atexit
import shutil
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _force_utf8_text_io():
    """让 `Path.read_text()` / `write_text()` 的默认编码固定为 UTF-8。

    为什么需要：项目里大量测试用不带参数的 `read_text()` 读写中文世界书与
    卡片数据。本机 Python 的 locale 默认编码是 cp936(GBK)，一遇到中文字节
    就抛 `UnicodeDecodeError`，看起来像业务 bug，实际是环境差异。

    实测：同一批测试在 `PYTHONUTF8=1` 下 3812 passed / 1 failed，
    在默认 GBK 下 3804 passed / 9 failed —— 差的 8 个全是编码假阳性。

    `io.text_encoding()` 读的是解释器启动时缓存的 locale，运行期改
    `locale.getpreferredencoding` 不生效，所以这里直接包装 Path 的两个方法。
    """
    _orig_read_text = Path.read_text
    _orig_write_text = Path.write_text

    def read_text(self, encoding=None, errors=None):
        return _orig_read_text(self, encoding=encoding or 'utf-8', errors=errors)

    def write_text(self, data, encoding=None, errors=None, newline=None):
        return _orig_write_text(
            self, data, encoding=encoding or 'utf-8', errors=errors, newline=newline
        )

    Path.read_text = read_text
    Path.write_text = write_text


_force_utf8_text_io()


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


def pytest_configure(config):
    """注册自定义 marker，避免 `PytestUnknownMarkWarning`。

    `slow`：需要跑完整 Gradle 构建或访问真实 SDK 的用例。
    默认跳过，用 `pytest -m slow` 或 `STM_RUN_SLOW=1 pytest` 显式开启
    —— 它们单次可能几分钟，不该拖慢日常回归。
    """
    config.addinivalue_line(
        'markers',
        'slow: 需要真实 Gradle 构建 / Android SDK，默认跳过（-m slow 或 STM_RUN_SLOW=1 开启）',
    )


def pytest_collection_modifyitems(config, items):
    """默认跳过 `slow` 用例，除非显式要求。

    为什么不用 `skipif` 表达式：那样会和 `-m slow` 打架——用户已经用 `-m`
    明确点名要跑，再被 skipif 拦掉就永远跑不起来了。
    这里只在「用户没提 slow」时补 skip，`-m slow` / `STM_RUN_SLOW=1`
    两种显式意图都能正常放行。
    """
    import os

    explicitly_requested = (
        'slow' in (config.getoption('-m') or '')
        or os.environ.get('STM_RUN_SLOW') == '1'
    )
    if explicitly_requested:
        return

    skip_slow = pytest.mark.skip(
        reason='slow 用例默认跳过；用 -m slow 或 STM_RUN_SLOW=1 开启'
    )
    for item in items:
        if 'slow' in item.keywords:
            item.add_marker(skip_slow)
