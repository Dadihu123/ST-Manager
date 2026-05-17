from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_detail_template_exposes_unknown_resource_bucket_and_delete_actions():
    source = (PROJECT_ROOT / 'templates/modals/detail_card.html').read_text(encoding='utf-8')

    assert 'resourceUnknown' in source
    assert "deleteResourceItem(file, '世界书')" in source
    assert "deleteResourceItem(file, '正则脚本')" in source
    assert "deleteResourceItem(file, '扩展脚本')" in source
    assert "deleteResourceItem(file, '快速回复')" in source
    assert "deleteResourceItem(file, '预设')" in source
    assert "deleteResourceItem(file, '未知资源')" in source
    assert source.index('预设 (Presets)') < source.index('其他资源 (Unknown)')


def test_detail_template_uses_directory_skin_items_in_filmstrip_and_resource_panel():
    source = (PROJECT_ROOT / 'templates/modals/detail_card.html').read_text(encoding='utf-8')

    assert source.count('currentSkinItems') >= 4
    assert 'enterSkinDirectory(item.path)' in source
    assert 'goToSkinParentDirectory()' in source
    assert 'selectSkinByPath(item.path)' in source
    assert 'isSkinPathSelected(item.path)' in source
    assert '@dblclick.stop="enterSkinDirectory(item.path)"' in source
    assert 'detail-thumb--nav' in source
    assert 'detail-thumb--folder' in source
