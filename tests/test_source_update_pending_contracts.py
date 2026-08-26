import json
import subprocess
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_detail_management_gates_source_controls_and_exposes_acknowledge_action():
    template = read_project_file('templates/modals/detail_card.html')
    script = read_project_file('static/js/components/detailModal.js')

    assert 'class="detail-source-title-sync-options"' in template
    assert 'x-show="canCheckSourceUpdate()"' in template
    assert 'x-model="syncSourceTitleOnUpdate"' in template
    assert 'x-show="hasPendingSourceUpdate()"' in template
    assert '@click="acknowledgeSourceUpdate()"' in template
    assert '确认无需更新' in template
    assert ':class="getSourceUpdateStateClass()"' in template
    assert 'acknowledgeCardSourceUpdate' in script
    assert "this.editingData?.source_link ?? this.activeCard?.source_link ?? ''" in script
    assert 'hasPendingSourceUpdate() {' in script
    assert 'async acknowledgeSourceUpdate() {' in script


def test_selected_card_source_update_actions_use_accessible_dropdowns_on_both_layouts():
    template = read_project_file('templates/components/header.html')
    script = read_project_file('static/js/components/header.js')
    batch_script = read_project_file('static/js/utils/batchOperations.js')

    assert template.count('x-data="{ showSourceUpdateMenu: false }"') == 2
    assert template.count('aria-haspopup="menu"') == 2
    assert template.count(':aria-expanded="showSourceUpdateMenu.toString()"') == 2
    assert template.count('role="menuitem"') == 6
    assert template.count('class="w-full block') == 6
    assert template.count('acknowledgeSelectedSourceUpdates()') == 2
    assert 'async acknowledgeSelectedSourceUpdates() {' in script
    assert 'runSourceUpdateAcknowledgeBatch' in script
    assert 'pending_only: true' in batch_script
    assert 'emptyMessage: "选中的角色卡没有待处理更新"' in batch_script


def test_source_update_dropdowns_match_automation_alignment_and_arrow_position():
    template = read_project_file('templates/components/header.html')

    assert "<span aria-hidden=\"true\">{{ icon('chevron-down', 'ui-icon--xs') }}</span> 来源更新" in template
    assert "<span aria-hidden=\"true\">{{ icon('chevron-down', 'ui-icon--xs') }}</span> 更新" in template
    assert (
        'class="absolute top-full left-0 mt-2 w-56 '
        'bg-[var(--bg-panel)] border border-[var(--border-light)] '
        'rounded-lg shadow-2xl py-1 overflow-hidden"'
    ) in template


def test_card_grid_prioritizes_persistent_pending_state_over_last_check_result():
    script = read_project_file('static/js/components/cardGrid.js')

    assert 'hasPendingSourceUpdate(card) {' in script
    assert 'if (this.hasPendingSourceUpdate(card)) return \'is-updated\';' in script
    assert '有尚未处理的来源更新；上次检查失败' in script
    assert '有尚未处理的来源更新；来源暂无后续变化' in script


def test_batch_acknowledge_resolves_and_processes_pending_targets_only():
    source_path = PROJECT_ROOT / 'static/js/utils/batchOperations.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        let source = readFileSync({json.dumps(str(source_path))}, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace(/\\bexport\\s+/g, '');

        const capturedTargets = [];
        const executeRules = async () => ({{ success: true }});
        const getAutomationTargets = async () => ({{ success: true, card_ids: [] }});
        const checkCardSourceUpdate = async () => ({{ success: true, supported: true }});
        const getSourceUpdateTargets = async (payload) => {{
          capturedTargets.push(payload);
          return {{ success: true, card_ids: payload.pending_only ? ['pending.png'] : [] }};
        }};
        const acknowledgeCardSourceUpdate = async (cardId) => ({{
          success: true,
          acknowledged: true,
          card_id: cardId,
          source_update: {{ pending_update: false }},
        }});

        const events = [];
        const store = {{
          batchProgress: {{ status: 'idle' }},
          showToast() {{}},
          startBatchProgress(_title, total) {{
            this.batchProgress = {{ status: 'running', total, cancelRequested: false }};
          }},
          updateBatchProgress(patch) {{ Object.assign(this.batchProgress, patch); }},
          finishBatchProgress(result) {{ this.result = result; }},
        }};
        globalThis.window = {{
          Alpine: {{ store: () => store }},
          dispatchEvent(event) {{ events.push(event); }},
        }};
        globalThis.CustomEvent = class CustomEvent {{
          constructor(type, options = {{}}) {{
            this.type = type;
            this.detail = options.detail;
          }}
        }};

        const module = new Function(
          'executeRules',
          'getAutomationTargets',
          'checkCardSourceUpdate',
          'getSourceUpdateTargets',
          'acknowledgeCardSourceUpdate',
          'window',
          'CustomEvent',
          `${{source}}\\nreturn {{ runSourceUpdateAcknowledgeBatch }};`,
        )(
          executeRules,
          getAutomationTargets,
          checkCardSourceUpdate,
          getSourceUpdateTargets,
          acknowledgeCardSourceUpdate,
          globalThis.window,
          globalThis.CustomEvent,
        );
        const result = await module.runSourceUpdateAcknowledgeBatch({{
          targetPayload: {{ card_ids: ['pending.png', 'clean.png'] }},
        }});

        if (capturedTargets.length !== 1 || capturedTargets[0].pending_only !== true) {{
          throw new Error(`expected pending-only target resolution, got ${{JSON.stringify(capturedTargets)}}`);
        }}
        if (result.selected !== 1 || result.acknowledged !== 1 || result.failed !== 0) {{
          throw new Error(`unexpected acknowledge summary: ${{JSON.stringify(result)}}`);
        }}
        if (events.length !== 1 || events[0].detail.result.source_update.pending_update !== false) {{
          throw new Error(`expected acknowledged item event, got ${{JSON.stringify(events)}}`);
        }}
        """
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
