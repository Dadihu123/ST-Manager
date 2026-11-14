"""SQLite 能力探测：FTS5 可用性与缓存语义。"""

import sqlite3
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data import sqlite_capabilities


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    """每个用例前后都清空缓存，避免探测结果在用例之间串味。"""
    sqlite_capabilities.reset_cache_for_tests()
    yield
    sqlite_capabilities.reset_cache_for_tests()


def test_supports_fts5_matches_real_capability():
    """探测结论必须与「真的能不能建 fts5 表」一致。"""
    conn = sqlite3.connect(':memory:')
    try:
        conn.execute('CREATE VIRTUAL TABLE t USING fts5(content)')
        real = True
    except sqlite3.OperationalError:
        real = False
    finally:
        conn.close()

    assert sqlite_capabilities.supports_fts5() is real


def test_probe_does_not_pollute_main_schema():
    """探测必须只建 temp 表，不得在主库里留下任何对象。"""
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE sentinel(x)')
    before = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()

    sqlite_capabilities.supports_fts5()

    after = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
    ).fetchall()
    conn.close()

    assert before == after


def test_result_is_cached_across_calls(monkeypatch):
    """第二次调用不得重新探测。"""
    sqlite_capabilities.reset_cache_for_tests()
    calls = []

    real_connect = sqlite_capabilities.sqlite3.connect

    def counting_connect(*args, **kwargs):
        calls.append(args)
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite_capabilities.sqlite3, 'connect', counting_connect)

    first = sqlite_capabilities.supports_fts5()
    second = sqlite_capabilities.supports_fts5()

    assert first is second
    assert len(calls) == 1


def test_missing_fts5_module_is_reported_as_unsupported(monkeypatch):
    """模拟无 FTS5 的 SQLite：应判定为不支持，而不是抛异常。"""
    sqlite_capabilities.reset_cache_for_tests()

    real_connect = sqlite_capabilities.sqlite3.connect

    class _NoFts5Connection:
        def __init__(self, inner):
            self._inner = inner

        def execute(self, sql, *args):
            if 'fts5' in sql.lower():
                raise sqlite3.OperationalError('no such module: fts5')
            return self._inner.execute(sql, *args)

        def close(self):
            self._inner.close()

    monkeypatch.setattr(
        sqlite_capabilities.sqlite3,
        'connect',
        lambda *a, **k: _NoFts5Connection(real_connect(*a, **k)),
    )

    assert sqlite_capabilities.supports_fts5() is False


def test_non_operational_error_propagates(monkeypatch):
    """非 OperationalError 必须照常抛出，避免把真实故障误判成「没有 FTS5」。"""
    sqlite_capabilities.reset_cache_for_tests()

    def boom(*args, **kwargs):
        raise RuntimeError('disk on fire')

    monkeypatch.setattr(sqlite_capabilities.sqlite3, 'connect', boom)

    with pytest.raises(RuntimeError):
        sqlite_capabilities.supports_fts5()
