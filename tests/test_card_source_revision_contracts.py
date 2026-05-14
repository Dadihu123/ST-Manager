from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_detail_and_embedded_editors_send_source_revision():
    detail_source = read_project_file('static/js/components/detailModal.js')
    wi_editor_source = read_project_file('static/js/components/wiEditor.js')
    wi_popup_source = read_project_file('static/js/components/wiDetailPopup.js')

    assert 'this.editingData.source_revision = safeCard.source_revision || "";' in detail_source
    assert 'source_revision: this.editingData.source_revision || "",' in detail_source
    assert 'source_revision: this.editingData.source_revision || "",' in wi_editor_source
    assert (
        'source_revision: this.activeWiDetail.source_revision || "",' in wi_popup_source
        or 'source_revision: this.activeWiDetail?.source_revision || "",' in wi_popup_source
    )


def test_detail_and_embedded_editors_refresh_source_revision_after_save():
    detail_source = read_project_file('static/js/components/detailModal.js')
    wi_editor_source = read_project_file('static/js/components/wiEditor.js')
    wi_popup_source = read_project_file('static/js/components/wiDetailPopup.js')

    assert 'this.editingData.source_revision = res.updated_card?.source_revision || this.editingData.source_revision || "";' in detail_source
    assert 'this.editingData.source_revision = c.source_revision || this.editingData.source_revision || "";' in detail_source
    assert 'res?.updated_card?.source_revision ||' in wi_editor_source
    assert 'this.editingData.source_revision ||' in wi_editor_source
    assert 'res?.updated_card?.source_revision ||' in wi_popup_source
    assert 'this.activeWiDetail.source_revision ||' in wi_popup_source


def test_detail_update_and_cover_paths_apply_immediate_source_revision():
    detail_source = read_project_file('static/js/components/detailModal.js')

    assert 'updatedCard.source_revision || res.source_revision || "";' in detail_source
    assert 'res.updated_card?.source_revision || res.source_revision || "";' in detail_source
    assert 'this.editingData.source_revision = refreshedRevision || this.editingData.source_revision || "";' in detail_source
