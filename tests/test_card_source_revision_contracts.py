from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_detail_and_embedded_editors_send_source_revision():
    detail_source = read_project_file('static/js/components/detailModal.js')
    wi_editor_source = read_project_file('static/js/components/wiEditor.js')
    wi_popup_source = read_project_file('static/js/components/wiDetailPopup.js')

    # 详情页统一从 `incomingRevision` 吸收修订号（带陈旧响应保护，见资源绑定分析文档）
    assert 'const incomingRevision = String(safeCard.source_revision || \'\').trim();' in detail_source
    assert 'this.editingData.source_revision = incomingRevision;' in detail_source
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
    assert 'this.editingRevision = this.editingData.source_revision;' in detail_source
    assert 'source_revision: c.source_revision ?? "",' in detail_source
    assert 'res?.updated_card?.source_revision ||' in wi_editor_source
    assert 'this.editingData.source_revision ||' in wi_editor_source
    assert 'res?.updated_card?.source_revision ||' in wi_popup_source
    assert 'this.activeWiDetail.source_revision ||' in wi_popup_source


def test_detail_update_and_cover_paths_apply_immediate_source_revision():
    detail_source = read_project_file('static/js/components/detailModal.js')

    # 覆盖更新：响应里的修订号写回 updatedCard
    assert 'updatedCard.source_revision || res.source_revision || "";' in detail_source
    # 换图/换封统一走 _applyPersistedCardMutation 吸收新 ID 与修订号
    assert '_applyPersistedCardMutation(res, { refreshListEvent: \'refresh-card-list\' })' in detail_source
    assert 'res.source_revision || updatedCard?.source_revision || this.editingData.source_revision || \'\'' in detail_source


def test_detail_modal_rejects_stale_detail_responses():
    detail_source = read_project_file('static/js/components/detailModal.js')

    assert 'const staleResourceFolder = Boolean(' in detail_source
    assert 'if (!staleResourceFolder) {' in detail_source
    assert 'this.editingRevision = incomingRevision;' in detail_source


def test_detail_modal_absorbs_external_card_updates_and_conflicts():
    detail_source = read_project_file('static/js/components/detailModal.js')

    assert "window.addEventListener('card-updated'" in detail_source
    assert '_absorbExternalCardUpdate(' in detail_source
    assert 'async handleSaveConflict(res) {' in detail_source
    assert 'await this.reloadActiveCardFromDisk();' in detail_source
    assert "clear_ui_fields: this.editingData.resource_folder ? [] : ['resource_folder']," in detail_source


def test_wi_editor_hands_revision_back_on_close():
    wi_source = read_project_file('static/js/components/wiEditor.js')

    assert 'closeDetail.source_revision = this.editingData.source_revision;' in wi_source
    assert 'closeDetail.card_id = this.editingData.id;' in wi_source
    assert 'closeDetail.filename = this.editingData.filename;' in wi_source
    detail_source = read_project_file('static/js/components/detailModal.js')
    assert 'const closedRevision = String(detail.source_revision || \'\').trim();' in detail_source
    assert "this._syncPersistedBaseline(['source_revision']);" in detail_source
