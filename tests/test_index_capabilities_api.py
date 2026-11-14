"""索引状态接口暴露平台能力（供前端隐藏不可用的搜索模式）。"""

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data import sqlite_capabilities


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    sqlite_capabilities.reset_cache_for_tests()
    yield
    sqlite_capabilities.reset_cache_for_tests()


def test_index_status_exposes_fts5_capability(monkeypatch):
    from core.services import index_service

    # 避免真的去读数据库：状态快照本身不依赖它
    monkeypatch.setattr(index_service, 'DEFAULT_DB_PATH', ':memory:')

    status = index_service.get_index_status()

    assert 'capabilities' in status
    assert isinstance(status['capabilities']['fts5'], bool)


def test_index_status_reports_fts5_false_when_unsupported(monkeypatch):
    from core.services import index_service

    monkeypatch.setattr(index_service, 'DEFAULT_DB_PATH', ':memory:')
    sqlite_capabilities.force_for_tests(False)

    status = index_service.get_index_status()

    assert status['capabilities']['fts5'] is False


def test_frontend_hides_fulltext_when_fts5_missing():
    """前端契约：header.js 的 canUseFulltextSearch 必须读取 capabilities.fts5。"""
    source = (ROOT / 'static' / 'js' / 'components' / 'header.js').read_text(encoding='utf-8')

    assert 'capabilities.fts5' in source
    assert 'capabilities.fts5 === false' in source
