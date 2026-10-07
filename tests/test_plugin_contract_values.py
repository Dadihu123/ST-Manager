"""插件系统的数值契约测试：设计文档中的限值 ↔ 代码常量。

两侧同时断言：

1. 代码常量等于**期望值**（防止偷偷改动限值）；
2. 设计文档里出现对应的**人类可读描述**（防止改了代码不更新文档）。

任何一处漂移都会失败——这是「文档是唯一事实来源」在数值上的落地。
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import api as api_module
from core.plugins import catalog as catalog_module
from core.plugins import installer as installer_module
from core.plugins import job_store, jobs

DESIGN_DOC = os.path.join(PROJECT_ROOT, 'docs', '2026-09-22-plugin-system-design.md')


def _doc_text() -> str:
    with open(DESIGN_DOC, 'r', encoding='utf-8') as handle:
        return handle.read()


def _assert_documented(fragment: str) -> None:
    assert fragment in _doc_text(), f'设计文档缺少对应描述: {fragment!r}'


# ------------------------------------------------------------------ 安装器限值


def test_download_size_limit_matches_docs():
    assert installer_module.MAX_DOWNLOAD_BYTES == 50 * 1024 * 1024
    _assert_documented('max 50MB')


def test_uncompressed_size_limit_matches_docs():
    assert installer_module.MAX_UNCOMPRESSED_BYTES == 200 * 1024 * 1024
    _assert_documented('超过 200MB')


def test_compression_ratio_limit_matches_docs():
    assert installer_module.MAX_COMPRESSION_RATIO == 100
    _assert_documented('压缩比 > 100:1')


def test_archive_entry_limit_matches_docs():
    assert installer_module.MAX_ARCHIVE_ENTRIES == 5000
    _assert_documented('限制 entry 数量 ≤ 5000')


# ------------------------------------------------------------------ 作业限值


def test_jobs_per_plugin_limit_matches_docs():
    assert jobs.MAX_JOBS_PER_PLUGIN == 2
    _assert_documented('MAX_JOBS_PER_PLUGIN=2')


def test_items_per_run_limit_matches_docs():
    assert jobs.MAX_ITEMS_PER_RUN == 20000
    _assert_documented('MAX_ITEMS_PER_RUN=20000')


def test_item_payload_size_limit_matches_docs():
    assert job_store.MAX_ITEM_PAYLOAD_BYTES == 64 * 1024
    _assert_documented('单项参数')
    _assert_documented('≤ 64KB')


def test_item_result_size_limit_matches_docs():
    assert job_store.MAX_ITEM_RESULT_BYTES == 262144
    _assert_documented('262144')


def test_job_retention_matches_docs():
    assert job_store.PLUGIN_JOB_DONE_RETENTION == 100
    assert job_store.PLUGIN_JOB_FAILED_RETENTION == 50
    _assert_documented('completed 保留 100、failed 保留 50')


def test_worker_wakeup_interval_matches_docs():
    assert jobs.WAKEUP_INTERVAL_SECONDS == 30
    _assert_documented('30s')


# ------------------------------------------------------------------ SSE 限值


def test_sse_connection_limits_match_docs():
    assert jobs.SSE_MAX_CONNECTIONS_PER_RUN == 4
    assert jobs.SSE_MAX_CONNECTIONS_TOTAL == 32
    _assert_documented('每 run_id 最多 4 个并发 SSE')
    _assert_documented('全局最多 32 个')


def test_sse_heartbeat_interval_matches_docs():
    assert jobs.SSE_HEARTBEAT_INTERVAL_SECONDS == 15
    _assert_documented('15s 一次 `: heartbeat`')


# ------------------------------------------------------------------ 数据与目录


def test_ui_data_quota_matches_docs():
    assert api_module.PLUGIN_DATA_QUOTA_BYTES == 256 * 1024
    assert api_module.PLUGIN_DATA_QUOTA_WARN_BYTES == int(256 * 1024 * 0.8)
    _assert_documented('单插件命名空间上限 256KB')


def test_catalog_size_limit_matches_docs():
    assert catalog_module.MAX_CATALOG_BYTES == 512 * 1024
    _assert_documented('目录清单')


def test_catalog_cache_hours_default_matches_config():
    from core.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG['plugin_catalog_cache_hours'] == 6
    _assert_documented('| `plugin_catalog_cache_hours` | `6` |')


def test_catalog_url_default_matches_docs():
    from core.config import DEFAULT_CONFIG

    url = DEFAULT_CONFIG['plugin_catalog_url']
    assert url.startswith('https://raw.githubusercontent.com/')
    _assert_documented('raw.githubusercontent.com/Dadihu123/ST-Manager/main/static/plugins/catalog.json')


# ------------------------------------------------------------------ 密钥


def test_secret_backup_generations_matches_docs():
    from core.plugins import secrets as secrets_module

    assert secrets_module.BACKUP_GENERATIONS == 3
    _assert_documented('3 代')


def test_supported_api_versions_match_docs():
    from core.version import PLUGIN_API_VERSION, SUPPORTED_PLUGIN_API_VERSIONS

    assert PLUGIN_API_VERSION == 1
    assert SUPPORTED_PLUGIN_API_VERSIONS == (1,)
    _assert_documented('当前 `{1}`')
