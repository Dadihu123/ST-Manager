"""插件系统的数值契约测试：设计文档中的限值 ↔ 代码常量。

两侧同时断言：

1. 代码常量等于**期望值**（防止偷偷改动限值）；
2. 设计文档里出现对应的**人类可读描述**（防止改了代码不更新文档）。

任何一处漂移都会失败——这是「文档是唯一事实来源」在数值上的落地。
v2 时代的限值（安装器/作业/SSE/密钥）仍以旧设计文档为事实源；
v3 新增的契约版本与贡献容量以 `docs/2026-10-21-plugin-contract-v3-design.md` 为准。
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import api as api_module
from core.plugins import catalog as catalog_module
from core.plugins import contract as contract_module
from core.plugins import installer as installer_module
from core.plugins import job_store, jobs

DESIGN_DOC = os.path.join(PROJECT_ROOT, 'docs', '2026-09-22-plugin-system-design.md')
DESIGN_DOC_V3 = os.path.join(PROJECT_ROOT, 'docs', '2026-10-21-plugin-contract-v3-design.md')


def _doc_text() -> str:
    with open(DESIGN_DOC, 'r', encoding='utf-8') as handle:
        return handle.read()


def _doc_text_v3() -> str:
    with open(DESIGN_DOC_V3, 'r', encoding='utf-8') as handle:
        return handle.read()


def _assert_documented(fragment: str) -> None:
    assert fragment in _doc_text(), f'设计文档缺少对应描述: {fragment!r}'


def _assert_v3_documented(fragment: str) -> None:
    assert fragment in _doc_text_v3(), f'v3 设计文档缺少对应描述: {fragment!r}'


# ------------------------------------------------------------------ 契约版本（S1）


def test_plugin_api_version_is_three():
    from core.version import PLUGIN_API_VERSION, SUPPORTED_PLUGIN_API_VERSIONS

    assert PLUGIN_API_VERSION == 3
    assert SUPPORTED_PLUGIN_API_VERSIONS == (3,)
    _assert_v3_documented('| `api_version` | `3` |')
    _assert_v3_documented('`manifest_version` / `api_version` 不在 `(3,)`')


def test_manifest_api_versions_agree_with_core_version():
    """S1：`core/version.py` 与 `contract.py` 的版本常量必须一致（两处不能漂移）。"""
    from core.version import (
        PLUGIN_API_VERSION,
        SUPPORTED_PLUGIN_API_VERSIONS,
    )
    from core.plugins import contract as contract

    assert contract.API_VERSION == PLUGIN_API_VERSION
    assert contract.SUPPORTED_API_VERSIONS == SUPPORTED_PLUGIN_API_VERSIONS
    assert contract.MANIFEST_VERSION == 3
    assert contract.SUPPORTED_MANIFEST_VERSIONS == (3,)


def test_supported_manifest_versions_match_docs():
    from core.plugins.manifest import (
        DEFAULT_MANIFEST_VERSION,
        SUPPORTED_MANIFEST_VERSIONS,
    )

    assert DEFAULT_MANIFEST_VERSION == 3
    assert SUPPORTED_MANIFEST_VERSIONS == (3,)
    _assert_v3_documented('| `manifest_version` | `3` |')


# ------------------------------------------------------------------ 贡献容量 / 落点


def test_contribution_limits_match_docs():
    assert contract_module.MAX_MENU_NODES_PER_PLUGIN == 64
    assert contract_module.MAX_MENU_DEPTH == 3
    assert contract_module.MAX_COMMANDS_PER_PLUGIN == 32
    assert contract_module.MAX_SLOTS_PER_PLUGIN == 16
    assert contract_module.MAX_DOCK_SLOTS == 8
    assert contract_module.MAX_DOCK_PER_PLUGIN == 2
    _assert_v3_documented('单插件菜单节点上限 **64**（含子节点）')
    _assert_v3_documented('菜单树最大深度 **3**')
    _assert_v3_documented('全局 8 个槽位，单插件最多 2 个')
    _assert_v3_documented('64 节点、深度 3、dock 2/8、命令 32、插槽 16')


def test_menu_placements_match_docs():
    expected = (
        'context.folder',
        'context.card',
        'context.footer',
        'batch.actions',
        'commandPalette',
        'dock',
        'settings.nav',
    )

    assert contract_module.MENU_PLACEMENTS == expected
    for placement in expected:
        _assert_v3_documented(f'| `{placement}` |')


def test_slots_match_docs():
    expected = (
        'settings.section',
        'header.actions',
        'card.detail.tabs',
        'page.cards.toolbar',
        'page.worldinfo.toolbar',
    )

    assert contract_module.SLOT_NAMES == expected
    for slot in expected:
        _assert_v3_documented(f'| `{slot}` |')
    _assert_v3_documented('`empty.<mode>`')


def test_capability_bits_match_docs():
    assert contract_module.CAPABILITY_UI_CUSTOM == 'ui.custom'
    assert contract_module.CAPABILITY_UI_GLOBAL_STYLES == 'ui.global_styles'
    assert 'ui.custom' in contract_module.KNOWN_CAPABILITIES
    assert 'ui.global_styles' in contract_module.KNOWN_CAPABILITIES
    _assert_v3_documented('`ui.custom` `ui.global_styles`')


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


# ------------------------------------------------------------------ 归档 URL 形式


def test_archive_url_uses_bare_ref_form_documented():
    """归档 URL 必须用裸 `zip/<ref>`（分支与 tag 都能解析）。

    旧实现无条件拼 `refs/heads/<ref>`，导致按 Release tag 更新时 404。
    设计文档 3.3 记录了三种形式的实测对照表。
    """
    assert installer_module.build_archive_url('owner/repo', 'main') == (
        'https://codeload.github.com/owner/repo/zip/main'
    )
    _assert_documented('| 分支 `main` | 200 | 404 | **200** |')
    _assert_documented('| tag `v2.31.0` | **404** | 200 | **200** |')


def test_catalog_update_endpoint_is_documented():
    """更新端点是 3.6 生命周期四操作之一，文档必须列出。"""
    _assert_documented('POST /api/plugins/catalog/update')
    _assert_documented('| `POST` | `/api/plugins/catalog/update` |')
