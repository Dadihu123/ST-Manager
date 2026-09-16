from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_worldinfo_send_to_st_api_helper_contract():
    source = read_project_file('static/js/api/wi.js')

    assert 'export async function sendWorldInfoToSillyTavern(payload) {' in source
    assert 'fetch("/api/world_info/send_to_st", {' in source
    assert 'method: "POST"' in source
    assert 'body: JSON.stringify(payload || {})' in source
    assert 'return res.json()' in source


def test_worldinfo_grid_js_send_to_st_contracts():
    source = read_project_file('static/js/components/wiGrid.js')

    assert 'canSendWorldInfoToST(item) {' in source
    assert 'sourceType === "global"' in source
    assert 'sourceType === "resource"' in source
    assert 'isSendingWorldInfoToST(itemId) {' in source
    assert 'getWorldInfoSendToSTTitle(item) {' in source
    assert 'applyWorldInfoSentState(detail) {' in source
    assert 'getWorldInfoSentFieldName() {' in source
    assert 'getLastSentFieldName?.() || "last_sent_to_st"' in source
    assert 'window.addEventListener("wi-sent-to-st"' in source
    assert 'detail.id' in source
    assert 'detail[sentField]' in source
    assert 'this.applyWorldInfoSentState(detail);' in source


def test_worldinfo_grid_template_send_to_st_contracts():
    source = read_project_file('templates/components/grid_wi.html')

    assert '@click.stop="sendWorldInfoToST(item)"' in source
    assert ':title="getWorldInfoSendToSTTitle(item)"' in source
    assert 'x-show="canSendWorldInfoToST(item)"' in source
    assert 'class="card-send-st-btn"' in source


def test_worldinfo_detail_popup_js_send_to_st_contracts():
    source = read_project_file('static/js/components/wiDetailPopup.js')

    assert 'sendWorldInfoToSillyTavern,' in source
    assert 'isSendingWorldInfoToST: false,' in source
    assert 'canSendActiveWorldInfoToST() {' in source
    assert 'getActiveWorldInfoSendToSTTitle() {' in source
    assert 'async sendActiveWorldInfoToST() {' in source
    assert 'window.dispatchEvent(new CustomEvent("wi-sent-to-st", {' in source
    assert 'id:' in source
    assert 'last_sent_to_st:' in source
    assert 'if (this.activeWiDetail && this.activeWiDetail.id === detail.id) {' in source


def test_worldinfo_detail_popup_template_send_to_st_contracts():
    source = read_project_file('templates/modals/detail_wi_popup.html')

    assert '@click="sendActiveWorldInfoToST()"' in source
    assert 'x-show="canSendActiveWorldInfoToST()"' in source
    assert '发送到 ST' in source
    assert "'send-target-tint': true" in source
    assert "'has-sent': getActiveWorldInfoSentAt() > 0" in source
    assert "'is-sending': isSendingWorldInfoToST" in source
