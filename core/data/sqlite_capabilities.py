"""本机 SQLite 的能力探测。

iOS 上 CPython 的 ``_sqlite3`` 是薄封装，链接的是系统 ``/usr/lib/libsqlite3.dylib``，
因此 **FTS5 是否存在由操作系统决定，不由 Python 打包方控制**。Android 上
Chaquopy 17.1 起自带 FTS5，桌面 CPython 也一直带 FTS5，但都不该被当作假设写死。

这里提供唯一的判定入口：真实建一张 ``temp`` 临时表做探测，结果在进程内缓存。
用 ``temp.`` 前缀是为了保证探测**不写主库**（临时表只存在于当前连接，且随连接消失）。

设计约束：
- 只吞 ``sqlite3.OperationalError``。其它异常（库损坏、磁盘只读等）必须照常抛出，
  否则会把「数据库坏了」误判成「没有 FTS5」，让后续降级掩盖真实故障。
- 探测是进程级缓存：同一进程连接多个库（含 ``:memory:``）时 SQLite 编译配置一致，
  重复探测没有意义。
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

_PROBE_TABLE = '__stm_fts5_probe'

#: 进程级探测结果缓存；``None`` 表示尚未探测。
_fts5_available = None


def _probe_fts5() -> bool:
    """真实建一次 fts5 临时表来判断可用性。"""
    conn = sqlite3.connect(':memory:')
    try:
        conn.execute(f'CREATE VIRTUAL TABLE temp.{_PROBE_TABLE} USING fts5(content)')
        conn.execute(f'DROP TABLE temp.{_PROBE_TABLE}')
        return True
    except sqlite3.OperationalError as exc:
        # 「no such module: fts5」走这里。其它 OperationalError（例如库损坏）
        # 也会到这里，但它们同样是「当前不可用」，降级是安全方向。
        logger.warning('本机 SQLite 不支持 FTS5，全文搜索将降级: %s', exc)
        return False
    finally:
        conn.close()


def supports_fts5() -> bool:
    """当前进程所用 SQLite 是否支持 FTS5（结果缓存）。"""
    global _fts5_available
    if _fts5_available is None:
        _fts5_available = _probe_fts5()
    return _fts5_available


def reset_cache_for_tests() -> None:
    """清空探测缓存（仅测试使用）。"""
    global _fts5_available
    _fts5_available = None


def force_for_tests(value: bool) -> None:
    """强制指定探测结果（仅测试使用）。

    多个模块都以 ``from ... import supports_fts5`` 的形式持有同一个函数对象，
    而该函数读取的是**本模块**的 ``_fts5_available``。因此模拟「无 FTS5 平台」
    必须改这里的缓存，而不是分别 patch 每个模块里的函数别名。
    """
    global _fts5_available
    _fts5_available = bool(value)
