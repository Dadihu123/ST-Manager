"""备份域测试（方案 §P1-3）。

重点覆盖「一键回滚」这条底线：AI 插件的写操作是批量且事后审批的，
能回滚才敢把破坏性写权限交给插件。
"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import api as api_module
from core.plugins.api import PluginAPI
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import clear_plugin_ui_namespace, write_card, write_plugin


@pytest.fixture(autouse=True)
def _clean_plugin_ui():
    clear_plugin_ui_namespace()
    yield
    clear_plugin_ui_namespace()


@pytest.fixture
def env(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    cards_root = tmp_path / 'cards'
    cards_root.mkdir()
    data_root = tmp_path / 'data'
    data_root.mkdir()

    monkeypatch.setattr(api_module, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(api_module, 'DATA_DIR', str(data_root))

    return {
        'api': PluginAPI(PluginManifest.load(plugin_dir)),
        'cards': cards_root,
    }


# ================================================================ 创建


def test_snapshot_card_copies_file(env):
    write_card(env['cards'], 'card.json')

    snapshot_path = env['api'].backups.snapshot_card('card.json', remark='unit-test')

    assert snapshot_path and os.path.isfile(snapshot_path)
    assert 'unit-test' in os.path.basename(snapshot_path)


def test_snapshot_rejects_unknown_card(env):
    assert env['api'].backups.snapshot_card('missing.json') is None


def test_snapshot_rejects_path_escape(env):
    assert env['api'].backups.snapshot_card('../../outside.json') is None


def test_snapshot_sanitizes_remark_for_filename(env):
    write_card(env['cards'], 'card.json')

    path = env['api'].backups.snapshot_card('card.json', remark='a/b:c*d?e')

    assert path and os.path.isfile(path)
    # 非法字符被替换，文件名保持可用
    assert '/' not in os.path.basename(path)
    assert ':' not in os.path.basename(path)


# ================================================================ 列举


def test_list_card_snapshots_returns_newest_first(env):
    api = env['api']
    write_card(env['cards'], 'card.json')

    api.backups.snapshot_card('card.json', remark='first')
    api.backups.snapshot_card('card.json', remark='second')

    snapshots = api.backups.list_card_snapshots('card.json')

    assert len(snapshots) >= 2
    assert snapshots[0]['remark'] == 'second'
    assert snapshots[1]['remark'] == 'first'


def test_list_card_snapshots_reports_metadata(env):
    api = env['api']
    write_card(env['cards'], 'card.json')
    api.backups.snapshot_card('card.json', remark='meta')

    entry = api.backups.list_card_snapshots('card.json')[0]

    for key in ('path', 'name', 'created_at', 'size', 'remark', 'is_auto'):
        assert key in entry, key
    assert entry['size'] > 0
    assert entry['is_auto'] is False


def test_list_card_snapshots_empty_for_unbacked_card(env):
    write_card(env['cards'], 'never-backup.json')

    assert env['api'].backups.list_card_snapshots('never-backup.json') == []


def test_list_card_snapshots_empty_for_unknown_card(env):
    assert env['api'].backups.list_card_snapshots('missing.json') == []


# ================================================================ 回滚


def test_restore_card_snapshot_brings_back_old_content(env):
    """方案 §P1-3 的核心验收：写坏了能一键回滚。"""
    api = env['api']
    write_card(env['cards'], 'card.json', description='原始描述')

    snapshot = api.backups.snapshot_card('card.json', remark='before-write')

    api.cards.write_fields('card.json', {'description': '被改坏了'})
    assert api.cards.read('card.json')['data']['description'] == '被改坏了'

    result = api.backups.restore_card_snapshot('card.json', snapshot)

    assert result['success'] is True
    assert api.cards.read('card.json')['data']['description'] == '原始描述'


def test_restore_takes_a_safety_snapshot_first(env):
    """恢复前自动再快照一次当前状态，因此「恢复」本身也可回滚。"""
    api = env['api']
    write_card(env['cards'], 'card.json', description='第一版')
    snapshot = api.backups.snapshot_card('card.json', remark='v1')

    api.cards.write_fields('card.json', {'description': '第二版'})
    result = api.backups.restore_card_snapshot('card.json', snapshot)

    assert result['safety_snapshot']
    assert os.path.isfile(result['safety_snapshot'])

    safety = json.loads(open(result['safety_snapshot'], encoding='utf-8').read())
    assert safety['data']['description'] == '第二版'


def test_restore_rejects_snapshot_from_another_card(env):
    """只允许恢复本卡片备份目录里的文件，防止借插件写任意路径。"""
    api = env['api']
    write_card(env['cards'], 'target.json')
    write_card(env['cards'], 'other.json')

    other_snapshot = api.backups.snapshot_card('other.json', remark='x')

    result = api.backups.restore_card_snapshot('target.json', other_snapshot)

    assert result['success'] is False
    assert result['error'] == 'snapshot_out_of_scope'


def test_restore_rejects_arbitrary_path(env):
    api = env['api']
    write_card(env['cards'], 'card.json')

    outside = env['cards'] / 'not-a-snapshot.json'
    outside.write_text('{}', encoding='utf-8')

    result = api.backups.restore_card_snapshot('card.json', str(outside))

    assert result['success'] is False
    assert result['error'] == 'snapshot_out_of_scope'


def test_restore_rejects_missing_snapshot(env):
    write_card(env['cards'], 'card.json')

    result = env['api'].backups.restore_card_snapshot('card.json', '/nonexistent/snap.json')

    assert result['success'] is False
    assert result['error'] == 'snapshot_not_found'


def test_restore_rejects_unknown_card(env):
    """卡片 id 非法/越界时给出 `card_not_found`（快照路径本身合法与否不重要）。"""
    result = env['api'].backups.restore_card_snapshot('../escape.json', '/tmp/x.json')

    assert result['success'] is False
    assert result['error'] == 'card_not_found'


def test_restore_can_rebuild_a_deleted_card(env):
    """卡片文件被删掉后，快照仍能把它还原回来。"""
    api = env['api']
    write_card(env['cards'], 'card.json', description='原始描述')
    snapshot = api.backups.snapshot_card('card.json', remark='keep')

    os.remove(str(env['cards'] / 'card.json'))
    assert api.cards.read('card.json') is None

    result = api.backups.restore_card_snapshot('card.json', snapshot)

    assert result['success'] is True
    assert api.cards.read('card.json')['data']['description'] == '原始描述'
