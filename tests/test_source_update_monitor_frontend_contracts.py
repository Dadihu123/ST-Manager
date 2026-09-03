import json
import re
import subprocess
import textwrap

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def run_node_module_check(source_path, stub_source, script_body):
    export_name = (
        'sourceUpdateMonitor'
        if source_path.name == 'sourceUpdateMonitor.js'
        else 'tagFilterModal'
    )
    node_script = textwrap.dedent(
        f'''
        import {{ readFileSync }} from 'node:fs';

        let source = readFileSync({json.dumps(str(source_path))}, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace(
          'export default function sourceUpdateMonitor()',
          'function sourceUpdateMonitor()',
        );
        source = source.replace(
          'export default function tagFilterModal()',
          'function tagFilterModal()',
        );

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(
            {json.dumps(stub_source)} + source +
              {json.dumps(f'\nexport {{ {export_name} }};')}
          ),
        );

        {textwrap.dedent(script_body)}
        '''
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_monitor_settings_refresh_does_not_overwrite_saved_draft_after_race():
    source_path = PROJECT_ROOT / 'static/js/components/sourceUpdateMonitor.js'
    stub_source = '''
    globalThis.statusDeferred = {};
    globalThis.statusDeferred.promise = new Promise((resolve) => {
      globalThis.statusDeferred.resolve = resolve;
    });
    globalThis.entriesDeferred = {};
    globalThis.entriesDeferred.promise = new Promise((resolve) => {
      globalThis.entriesDeferred.resolve = resolve;
    });
    const getSourceUpdateMonitorStatus = () => globalThis.statusDeferred.promise;
    const getSourceUpdateMonitorEntries = () => globalThis.entriesDeferred.promise;
    const saveSourceUpdateMonitorSettings = async (payload) => {
      globalThis.savedPayload = { ...payload };
      return {
        success: true,
        enabled: true,
        schedule_mode: 'daily',
        daily_time: '12:34',
        timezone: 'Asia/Shanghai',
        next_run_at: 1234,
      };
    };
    const acknowledgeCardSourceUpdate = async () => ({ success: true });
    const addSourceUpdateMonitorEntries = async () => ({ success: true, results: [] });
    const cancelSourceUpdateMonitorRun = async () => ({ success: true });
    const completeSourceUpdateMonitorRun = async () => ({ success: true });
    const getSourceUpdateTargets = async () => ({ success: true, card_ids: [] });
    const reportSourceUpdateMonitorProgress = async () => ({ success: true });
    const removeSourceUpdateMonitorEntries = async () => ({ success: true });
    const setSourceUpdateMonitorEntryEnabled = async () => ({ success: true });
    const startSourceUpdateMonitorRun = async () => ({ success: true });
    const isBatchOperationRunning = () => false;
    const runSourceUpdateBatch = async () => ({ success: true });
    globalThis.window = {
      addEventListener() {},
      clearInterval() {},
      setInterval() { return 1; },
      dispatchEvent() {},
    };
    globalThis.CustomEvent = class CustomEvent {
      constructor(type, options = {}) {
        this.type = type;
        this.detail = options.detail;
      }
    };
    '''
    run_node_module_check(
        source_path,
        stub_source,
        '''
        const component = module.sourceUpdateMonitor();
        component.$store = { global: { showToast() {} } };
        component.status = {
          enabled: false,
          schedule_mode: 'manual',
          daily_time: '09:00',
          timezone: '',
        };

        const oldRefresh = component.refresh({ quiet: true });
        component.settingsDraft = {
          enabled: true,
          schedule_mode: 'daily',
          daily_time: '12:34',
          timezone: 'Asia/Shanghai',
        };
        component.markSettingsDraftDirty();
        await component.saveSettings();

        globalThis.statusDeferred.resolve({
          success: true,
          pool: {
            enabled: false,
            schedule_mode: 'manual',
            daily_time: '09:00',
            timezone: '',
          },
        });
        globalThis.entriesDeferred.resolve({ success: true, entries: [] });
        await oldRefresh;

        if (globalThis.savedPayload.schedule_mode !== 'daily') {
          throw new Error(`unexpected save payload: ${JSON.stringify(globalThis.savedPayload)}`);
        }
        if (
          component.settingsDraft.schedule_mode !== 'daily' ||
          component.settingsDraft.daily_time !== '12:34' ||
          component.settingsDraft.timezone !== 'Asia/Shanghai' ||
          component.settingsDraft.enabled !== true
        ) {
          throw new Error(`stale refresh overwrote settings: ${JSON.stringify(component.settingsDraft)}`);
        }
        if (component.status.schedule_mode !== 'daily' || component.status.enabled !== true) {
          throw new Error(`stale refresh overwrote status: ${JSON.stringify(component.status)}`);
        }
        ''',
    )


def test_tag_workspace_direct_close_exits_native_fullscreen():
    source_path = PROJECT_ROOT / 'static/js/components/tagFilterModal.js'
    stub_source = '''
    const deleteTags = async () => ({ success: true });
    const getTagManagementPrefs = async () => ({ success: true });
    const getTagOrder = async () => ({ success: true });
    const saveTagManagementPrefs = async () => ({ success: true });
    const saveTagOrder = async () => ({ success: true });
    const saveTagTaxonomy = async () => ({ success: true });
    const matchAnyTagSearchToken = () => true;
    const splitTagTokens = () => [];
    const DEFAULT_TAG_CATEGORY_COLOR = '#64748b';
    const DEFAULT_TAG_CATEGORY_OPACITY = 100;
    globalThis.shell = {};
    globalThis.exitCalls = 0;
    globalThis.document = {
      fullscreenElement: globalThis.shell,
      webkitFullscreenElement: null,
      exitFullscreen() {
        globalThis.exitCalls += 1;
        this.fullscreenElement = null;
        return Promise.resolve();
      },
      addEventListener() {},
    };
    globalThis.confirm = () => true;
    '''
    run_node_module_check(
        source_path,
        stub_source,
        '''
        const component = module.tagFilterModal();
        component.$root = { querySelector() { return globalThis.shell; } };
        component.$store = {
          global: {
            showTagFilterModal: true,
            isCardAdvancedFilterTagEditActive() { return false; },
            setCardAdvancedFilterTagEditSource() {},
          },
        };
        component.isDesktopWorkspaceFullscreen = true;

        component.requestCloseModal();
        await Promise.resolve();

        if (globalThis.exitCalls !== 1) {
          throw new Error(`expected one native fullscreen exit, got ${globalThis.exitCalls}`);
        }
        if (document.fullscreenElement !== null) {
          throw new Error('native fullscreen element was not cleared');
        }
        if (component.isDesktopWorkspaceFullscreen !== false) {
          throw new Error('workspace fullscreen state was not cleared');
        }
        if (component.$store.global.showTagFilterModal !== false) {
          throw new Error('modal state was not closed');
        }
        ''',
    )


def test_monitor_settings_template_marks_all_editable_controls_dirty():
    template = read_project_file('templates/modals/source_update_monitor.html')

    assert '@change="markSettingsDraftDirty()"' in template
    assert template.count('@input="markSettingsDraftDirty()"') == 2
    assert 'source_attrs=\'@change="markSettingsDraftDirty()"\'' in template


def test_monitor_member_icons_reuse_monitor_pool_glyph():
    template = read_project_file('templates/modals/source_update_monitor.html')

    assert '{% from "components/icon.html" import icon, loading_icon %}' in template
    assert template.count("icon('monitor-user', 'ui-icon--md')") == 1
    assert template.count("icon('monitor-user', 'ui-icon--xl')") == 1
    assert template.count("icon('monitor-user'") == 3


def test_fullscreen_and_favorite_card_css_keep_surfaces_and_icons_crisp():
    workspace_css = read_project_file('static/css/modules/modal-tools.css')
    card_css = read_project_file('static/css/modules/view-cards.css')
    components_css = read_project_file('static/css/modules/components.css')
    card_grid_source = read_project_file('static/js/components/cardGrid.js')
    card_grid_template = read_project_file('templates/components/grid_cards.html')
    layout_template = read_project_file('templates/layout.html')

    assert '.tag-filter-desktop-shell::backdrop {' in workspace_css
    assert 'background: var(--surface-page);' in workspace_css
    assert 'input[type="date"],\ninput[type="time"] {' in components_css
    assert 'color-scheme: dark;' in components_css
    assert 'html.light-mode input[type="date"],\nhtml.light-mode input[type="time"] {' in components_css
    assert '::-webkit-calendar-picker-indicator' in components_css
    assert '.st-card.is-favorite:hover {' in card_css
    favorite_hover = card_css.split('.st-card.is-favorite:hover {', 1)[1].split('}', 1)[0]
    assert 'scale(1.01)' not in favorite_hover
    assert '@keyframes favorite-card-flash' not in card_css
    assert '.st-card.is-favorite::before' not in card_css
    assert '.st-card.is-favorite::after' not in card_css
    assert '.st-card.is-favorite > .card-flip-inner' not in card_css
    assert 'holo-sheen' not in card_css

    assert '/static/lib/cards-css/holo-cards.css' in layout_template
    assert re.search(
        r'import\s*\{\s*attachHoloCard,\s*prepareHoloCard,\s*\}'
        r'\s*from\s*"../../lib/cards-css/index\.js";',
        card_grid_source,
    )
    assert 'regular: "cosmos"' in card_grid_source
    assert 'favorite: "glitter"' in card_grid_source
    assert 'textureSeed: cardEffectTextureSeed(card?.id)' in card_grid_source
    assert 'x-init="syncCardEffect($el, card)"' in card_grid_template
    assert 'class="card-effect-shell holo-card"' in card_grid_template
    assert 'class="holo-card__content"' in card_grid_template
    assert 'class="holo-card__shine"' in card_grid_template
    assert 'class="holo-card__glare"' in card_grid_template
    assert '.card-effect-shell .holo-card__content *' in card_css
    assert 'pointer-events: none;' in card_css.split(
        '.card-effect-shell .holo-card__shine', 1
    )[1]
