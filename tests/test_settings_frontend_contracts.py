import json
import subprocess
import textwrap
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def run_state_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/state.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');

        const stubs = `
        const getServerStatus = async () => ({{}});
        const getSettings = async () => ({{}});
        const saveSettings = async (...args) => {{
          const fn = globalThis.__saveSettingsStub;
          return typeof fn === 'function' ? fn(...args) : {{ success: true }};
        }};
        const performSystemAction = async () => ({{ success: true }});
        const triggerScan = async () => ({{ success: true }});
        const updateCssVariable = () => {{}};
        const applyFont = () => {{}};
        const getIsolatedCategories = async () => ({{ isolated_categories: {{ paths: [] }} }});
        const saveIsolatedCategoriesRequest = async () => ({{ success: true, isolated_categories: {{ paths: [] }} }});
        globalThis.window = {{
          innerWidth: 1280,
          innerHeight: 720,
          addEventListener() {{}},
          removeEventListener() {{}},
          dispatchEvent() {{}},
          visualViewport: null,
        }};
        globalThis.document = {{
          documentElement: {{
            classList: {{ add() {{}}, remove() {{}} }},
          }},
        }};
        globalThis.localStorage = {{
          getItem() {{ return null; }},
          setItem() {{}},
          removeItem() {{}},
        }};
        globalThis.CustomEvent = class CustomEvent {{
          constructor(type, options = {{}}) {{
            this.type = type;
            this.detail = options.detail;
          }}
        }};
        globalThis.alert = () => {{}};
        globalThis.confirm = () => true;
        globalThis.Alpine = {{
          _stores: new Map(),
          store(name, value) {{
            if (arguments.length === 1) return this._stores.get(name);
            this._stores.set(name, value);
            return value;
          }},
        }};
        `;

        const module = await import(
          'data:text/javascript,' + encodeURIComponent(stubs + source),
        );
        module.initState();
        const store = globalThis.Alpine.store('global');

        {textwrap.dedent(script_body)}
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


def run_settings_modal_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/components/settingsModal.js'
    stub_source = textwrap.dedent(
        """
        const uploadBackground = (...args) => {
          const fn = globalThis.__uploadBackgroundStub;
          return typeof fn === 'function' ? fn(...args) : Promise.resolve({ success: true, url: '/uploaded/default.png' });
        };
        const openTrash = async () => ({ success: true });
        const emptyTrash = async () => ({ success: true });
        const evaluateSettingsPathSafety = (...args) => {
          const fn = globalThis.__evaluateSettingsPathSafetyStub;
          return typeof fn === 'function'
            ? fn(...args)
            : Promise.resolve({ success: true, risk_level: 'safe', risk_summary: '', blocked_actions: [], conflicts: [] });
        };
        const performSystemAction = async () => ({ success: true });
        const triggerScan = async () => ({ success: true });
        const exportUserDbBackup = (...args) => {
          const fn = globalThis.__exportUserDbBackupStub;
          return typeof fn === 'function' ? fn(...args) : Promise.resolve({ success: true, file_name: 'user-db-backup.json' });
        };
        const importUserDbBackup = (...args) => {
          const fn = globalThis.__importUserDbBackupStub;
          return typeof fn === 'function' ? fn(...args) : Promise.resolve({
            success: true,
            stats: {
              favorites: { imported: 0 },
              wi_clipboard: { imported: 0 },
              wi_entry_history: { imported: 0 },
            },
          });
        };
        const updateCssVariable = () => {};
        const applyFontDom = () => {};
        globalThis.alert = () => {};
        globalThis.confirm = () => true;
        globalThis.FormData = class FormData {
          constructor() {
            this.entries = [];
          }
          append(key, value) {
            this.entries.push([key, value]);
          }
            };
        """
    )
    module_suffix = '\nexport default settingsModal;'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function settingsModal()', 'function settingsModal()');

        const uploadResults = globalThis.__uploadResults = [];
        const backgroundUpdates = globalThis.__backgroundUpdates = [];

        const module = await import(
          'data:text/javascript,' + encodeURIComponent({json.dumps(stub_source)} + source + {json.dumps(module_suffix)}),
        );
        const component = module.default();

        {textwrap.dedent(script_body)}
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


def run_shared_wallpaper_picker_runtime_check(script_body):
    source_path = PROJECT_ROOT / 'static/js/components/sharedWallpaperPicker.js'
    stub_source = textwrap.dedent(
        """
        const importSharedWallpaper = (...args) => {
          const fn = globalThis.__importSharedWallpaperStub;
          const formData = args[0];
          const selectionTarget = args.length > 1 ? args[1] : 'manager';
          if (selectionTarget && formData && typeof formData.append === 'function') {
            formData.append('selection_target', selectionTarget);
          }
          return typeof fn === 'function' ? fn(formData, selectionTarget) : Promise.resolve({ success: true, item: null, items: [] });
        };
        const selectSharedWallpaper = (...args) => {
          const fn = globalThis.__selectSharedWallpaperStub;
          return typeof fn === 'function' ? fn(...args) : Promise.resolve({ success: true, selected_id: args[0]?.wallpaper_id || '' });
        };
        globalThis.alert = () => {};
        globalThis.FormData = class FormData {
          constructor() {
            this.entries = [];
          }
          append(key, value) {
            this.entries.push([key, value]);
          }
        };
        """
    )
    module_suffix = '\nexport default sharedWallpaperPicker;'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function sharedWallpaperPicker(options = {{}})', 'function sharedWallpaperPicker(options = {{}})');

        const module = await import(
          'data:text/javascript,' + encodeURIComponent({json.dumps(stub_source)} + source + {json.dumps(module_suffix)}),
        );
        const component = module.default();

        {textwrap.dedent(script_body)}
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


def test_state_settings_form_only_includes_openai_preset_directory():
    source = read_project_file('static/js/state.js')

    assert 'st_openai_preset_dir:' in source
    assert 'st_textgen_preset_dir:' not in source
    assert 'st_instruct_preset_dir:' not in source
    assert 'st_context_preset_dir:' not in source
    assert 'st_sysprompt_dir:' not in source
    assert 'st_reasoning_dir:' not in source


def test_settings_template_only_exposes_openai_preset_directory_input():
    source = read_project_file('templates/modals/settings.html')

    assert 'x-model="settingsForm.st_openai_preset_dir"' in source
    assert 'x-model="settingsForm.st_textgen_preset_dir"' not in source
    assert 'x-model="settingsForm.st_instruct_preset_dir"' not in source
    assert 'x-model="settingsForm.st_context_preset_dir"' not in source
    assert 'x-model="settingsForm.st_sysprompt_dir"' not in source
    assert 'x-model="settingsForm.st_reasoning_dir"' not in source


def test_settings_template_exposes_path_safety_warning_and_sync_blocking_bindings():
    source = read_project_file('templates/modals/settings.html')

    assert 'x-show="pathSafety.risk_level && pathSafety.risk_level !== \'safe\'"' in source
    assert 'x-text="pathSafety.risk_summary || \'检测到路径重叠风险，请先处理后再继续。\'"' in source
    assert 'x-text="getPathConflictMessage(\'cards_dir\')"' in source
    assert 'x-text="getPathConflictMessage(\'resources_dir\')"' in source
    assert 'x-text="getPathConflictMessage(\'st_openai_preset_dir\')"' in source
    assert 'x-text="syncSafetySummary"' in source
    assert ':disabled="isSyncActionBlocked(\'sync_characters\') || syncing"' in source
    assert ':disabled="isSyncActionBlocked(\'sync_all\') || syncing"' in source


def test_settings_template_keeps_background_controls_visible_for_selected_manager_wallpaper():
    source = read_project_file('templates/modals/settings.html')

    assert 'x-show="settingsForm.bg_url || settingsForm.manager_wallpaper_id"' in source


def test_settings_template_exposes_shared_wallpaper_picker_ui():
    source = read_project_file('templates/modals/settings.html')

    assert 'x-data="sharedWallpaperPicker({' in source
    assert "sourceFilter: 'all'" in source
    assert "selectionTarget: 'manager'" in source
    assert 'persistSelection: false' in source
    assert '@shared-wallpaper-selected.window="applySharedWallpaperSelection($event.detail)"' in source
    assert "setSourceFilter('builtin')" in source
    assert "setSourceFilter('imported')" in source
    assert "setSourceFilter('beautify')" in source
    assert 'sharedWallpaperPreviewUrl(item.file)' in source
    assert 'background-image:url(' in source
    assert "x-text=\"item.source_type || 'imported'\"" in source


def test_settings_template_exposes_user_db_backup_controls():
    source = read_project_file('templates/modals/settings.html')

    assert '用户 DB 数据' in source
    assert '@click="exportUserDbData()"' in source
    assert '@click="triggerUserDbImport()"' in source
    assert 'x-ref="userDbImportInput"' in source
    assert 'accept=".json,application/json"' in source
    assert '@change="handleUserDbImport($event)"' in source


def test_resource_api_exposes_shared_wallpaper_import_and_select_helpers():
    source = read_project_file('static/js/api/resource.js')

    assert 'export async function importSharedWallpaper(' in source
    assert 'selectionTarget = "manager"' in source or "selectionTarget = 'manager'" in source
    assert 'fetch("/api/shared-wallpapers/import"' in source or "fetch('/api/shared-wallpapers/import'" in source
    assert 'if (selectionTarget)' in source
    assert 'formData.append("selection_target", selectionTarget)' in source or "formData.append('selection_target', selectionTarget)" in source
    assert 'export async function selectSharedWallpaper(payload)' in source
    assert 'fetch("/api/shared-wallpapers/select"' in source or "fetch('/api/shared-wallpapers/select'" in source
    assert 'selection_target: payload.selection_target || "manager"' in source or "selection_target: payload.selection_target || 'manager'" in source


def test_system_api_exposes_settings_path_safety_and_nested_save_helpers():
    source = read_project_file('static/js/api/system.js')

    assert 'export async function evaluateSettingsPathSafety(config)' in source
    assert "fetch('/api/settings_path_safety'" in source
    assert 'body: JSON.stringify({ config }),' in source
    assert 'export async function saveSettings(config, options = {})' in source
    assert 'body: JSON.stringify({' in source
    assert 'config,' in source
    assert 'confirm_risky_paths: !!options.confirm_risky_paths,' in source


def test_store_save_settings_wraps_config_and_confirm_risky_paths_option():
    run_state_runtime_check(
        """
        const calls = [];
        globalThis.__saveSettingsStub = (config, options) => {
          calls.push({ config: { ...config }, options: { ...options } });
          return Promise.resolve({ success: true });
        };

        store.settingsForm = {
          api_key: 'secret',
          items_per_page: '24',
          items_per_page_wi: '12',
          theme_accent: 'blue',
        };
        store.updateItemsPerPage = () => {};
        const events = [];
        globalThis.window.dispatchEvent = (event) => events.push({ type: event.type, detail: event.detail });

        const res = await store.saveSettings(false, { confirm_risky_paths: true });

        if (!res.success) {
          throw new Error(`expected save success, got: ${JSON.stringify(res)}`);
        }
        if (calls.length !== 1) {
          throw new Error(`expected one save call, got: ${JSON.stringify(calls)}`);
        }
        if (calls[0].config.api_key !== 'secret') {
          throw new Error(`expected config forwarded intact, got: ${JSON.stringify(calls)}`);
        }
        if (calls[0].options.confirm_risky_paths !== true) {
          throw new Error(`expected confirm_risky_paths option forwarded, got: ${JSON.stringify(calls)}`);
        }
        if (events.length !== 0) {
          throw new Error(`expected closeModal=false to avoid dispatch, got: ${JSON.stringify(events)}`);
        }
        """
    )


def test_store_save_settings_returns_requires_confirmation_without_alert():
    run_state_runtime_check(
        """
        const alerts = [];
        globalThis.alert = (message) => alerts.push(message);
        globalThis.__saveSettingsStub = () => Promise.resolve({
          success: false,
          requires_confirmation: true,
          path_safety: {
            risk_level: 'warning',
            conflicts: [{ field: 'cards_dir' }],
          },
        });

        store.settingsForm = {
          items_per_page: '24',
          items_per_page_wi: '12',
          theme_accent: 'blue',
        };
        store.updateItemsPerPage = () => {};

        const res = await store.saveSettings(true, { confirm_risky_paths: false });

        if (!res.requires_confirmation) {
          throw new Error(`expected requires_confirmation response, got: ${JSON.stringify(res)}`);
        }
        if (alerts.length !== 0) {
          throw new Error(`requires_confirmation should not trigger alert, got: ${JSON.stringify(alerts)}`);
        }
        """
    )


def test_system_api_exposes_user_db_backup_helpers():
    source = read_project_file('static/js/api/system.js')

    assert 'export async function exportUserDbBackup()' in source
    assert 'fetch("/api/user-db-backup/export", {' in source
    assert 'export async function importUserDbBackup(formData)' in source
    assert 'fetch("/api/user-db-backup/import", {' in source


def test_resolve_manager_background_url_prefers_selected_shared_wallpaper():
    run_state_runtime_check(
        """
        store.settingsForm.bg_url = '/legacy/background.png';
        store.settingsForm.manager_wallpaper_id = 'builtin:space/stars.png';
        store.sharedWallpapers = [
          {
            id: 'builtin:space/stars.png',
            file: 'static/assets/wallpapers/builtin/space/stars.png',
          },
        ];

        const resolved = store.resolveManagerBackgroundUrl();
        if (resolved !== '/api/beautify/preview-asset/static/assets/wallpapers/builtin/space/stars.png') {
          throw new Error(`expected shared wallpaper url, got: ${resolved}`);
        }
        """
    )


def test_resolve_manager_background_url_uses_servable_route_for_imported_shared_wallpaper():
    run_state_runtime_check(
        """
        store.settingsForm.bg_url = '/legacy/background.png';
        store.settingsForm.manager_wallpaper_id = 'imported:demo';
        store.sharedWallpapers = [
          {
            id: 'imported:demo',
            file: 'data/library/wallpapers/imported/demo.png',
          },
        ];

        const resolved = store.resolveManagerBackgroundUrl();
        if (resolved !== '/api/beautify/preview-asset/data/library/wallpapers/imported/demo.png') {
          throw new Error(`expected servable shared wallpaper route, got: ${resolved}`);
        }
        """
    )


def test_resolve_manager_background_url_falls_back_to_legacy_bg_url_when_selected_item_missing():
    run_state_runtime_check(
        """
        store.settingsForm.bg_url = '/legacy/background.png';
        store.settingsForm.manager_wallpaper_id = 'missing-id';
        store.sharedWallpapers = [
          {
            id: 'builtin:space/stars.png',
            file: 'static/assets/wallpapers/builtin/space/stars.png',
          },
        ];

        const resolved = store.resolveManagerBackgroundUrl();
        if (resolved !== '/legacy/background.png') {
          throw new Error(`expected legacy background fallback, got: ${resolved}`);
        }
        """
    )


def test_settings_modal_legacy_background_input_clears_manager_wallpaper_selection():
    run_settings_modal_runtime_check(
        """
        component.$store = {
          global: {
            settingsForm: {
              manager_wallpaper_id: 'builtin:space/stars.png',
              bg_url: '/legacy/background.png',
            },
            resolveManagerBackgroundUrl() {
              return this.settingsForm.bg_url || '';
            },
            updateBackgroundImage(url) {
              backgroundUpdates.push(url);
            },
          },
        };

        component.applyBackgroundUrlInput();

        if (component.$store.global.settingsForm.manager_wallpaper_id !== '') {
          throw new Error('expected applyBackgroundUrlInput() to clear manager_wallpaper_id');
        }
        if (backgroundUpdates.length !== 1 || backgroundUpdates[0] !== '/legacy/background.png') {
          throw new Error(`unexpected background updates: ${JSON.stringify(backgroundUpdates)}`);
        }
        """
    )


def test_settings_modal_upload_flow_clears_manager_wallpaper_selection():
    run_settings_modal_runtime_check(
        """
        globalThis.__uploadBackgroundStub = async () => ({ success: true, url: '/uploaded/new-background.png' });

        component.$store = {
          global: {
            settingsForm: {
              manager_wallpaper_id: 'builtin:space/stars.png',
              bg_url: '',
            },
            resolveManagerBackgroundUrl() {
              return this.settingsForm.bg_url || '';
            },
            updateBackgroundImage(url) {
              backgroundUpdates.push(url);
            },
          },
        };

        const button = { innerText: 'Upload' };
        const event = {
          target: {
            files: [{ size: 1024, name: 'wallpaper.png' }],
            previousElementSibling: button,
            value: 'filled',
          },
        };

        await component.handleBackgroundUpload(event);

        if (component.$store.global.settingsForm.manager_wallpaper_id !== '') {
          throw new Error('expected handleBackgroundUpload() to clear manager_wallpaper_id');
        }
        if (component.$store.global.settingsForm.bg_url !== '/uploaded/new-background.png') {
          throw new Error(`unexpected uploaded bg_url: ${component.$store.global.settingsForm.bg_url}`);
        }
        if (backgroundUpdates.length !== 1 || backgroundUpdates[0] !== '/uploaded/new-background.png') {
          throw new Error(`unexpected background updates: ${JSON.stringify(backgroundUpdates)}`);
        }
        if (event.target.value !== '') {
          throw new Error('expected upload input value to reset after upload');
        }
        if (button.innerText !== 'Upload') {
          throw new Error(`expected button text restore, got: ${button.innerText}`);
        }
        """
    )


def test_settings_modal_export_user_db_data_alerts_success_with_filename():
    run_settings_modal_runtime_check(
        """
        const alerts = [];
        globalThis.alert = (message) => alerts.push(message);
        globalThis.__exportUserDbBackupStub = async () => ({
          success: true,
          file_name: 'user-db-backup-20260426.json',
        });

        await component.exportUserDbData();

        if (alerts.length !== 1) {
          throw new Error(`expected one alert, got: ${JSON.stringify(alerts)}`);
        }
        if (!String(alerts[0]).includes('user-db-backup-20260426.json')) {
          throw new Error(`expected success alert with filename, got: ${alerts[0]}`);
        }
        """
    )


def test_settings_modal_user_db_import_triggers_upload_resets_input_and_alerts_summary():
    run_settings_modal_runtime_check(
        """
        const alerts = [];
        const confirms = [];
        const importCalls = [];
        globalThis.alert = (message) => alerts.push(message);
        globalThis.confirm = (message) => {
          confirms.push(message);
          return true;
        };
        globalThis.__importUserDbBackupStub = async (formData) => {
          importCalls.push(formData.entries);
          return {
            success: true,
            stats: {
              favorites: { imported: 2 },
              wi_clipboard: { imported: 1 },
              wi_entry_history: { imported: 3 },
            },
          };
        };

        let clickCount = 0;
        component.$refs = {
          userDbImportInput: {
            click() {
              clickCount += 1;
            },
          },
        };

        component.triggerUserDbImport();

        if (clickCount !== 1) {
          throw new Error(`expected triggerUserDbImport() to click once, got: ${clickCount}`);
        }

        const file = { name: 'user-db-backup.json' };
        const event = {
          target: {
            files: [file],
            value: 'filled',
          },
        };

        await component.handleUserDbImport(event);

        if (confirms.length !== 1 || !String(confirms[0]).includes('ui_data.json')) {
          throw new Error(`expected confirm warning about ui_data.json, got: ${JSON.stringify(confirms)}`);
        }
        if (importCalls.length !== 1) {
          throw new Error(`expected one import call, got: ${JSON.stringify(importCalls)}`);
        }
        if (!importCalls[0].some(([key, value]) => key === 'file' && value === file)) {
          throw new Error(`expected FormData file append, got: ${JSON.stringify(importCalls[0])}`);
        }
        if (event.target.value !== '') {
          throw new Error('expected import input reset after upload');
        }
        if (alerts.length !== 1) {
          throw new Error(`expected one import success alert, got: ${JSON.stringify(alerts)}`);
        }
        if (!String(alerts[0]).includes('收藏: 导入 2')) {
          throw new Error(`expected favorites import summary in alert, got: ${alerts[0]}`);
        }
        if (!String(alerts[0]).includes('剪贴板: 导入 1')) {
          throw new Error(`expected clipboard import summary in alert, got: ${alerts[0]}`);
        }
        if (!String(alerts[0]).includes('历史记录: 导入 3')) {
          throw new Error(`expected history import summary in alert, got: ${alerts[0]}`);
        }
        """
    )


def test_shared_wallpaper_picker_groups_sources_for_settings_usage():
    run_shared_wallpaper_picker_runtime_check(
        """
        component.$store = {
          global: {
            sharedWallpapers: [
              { id: 'builtin:a', source_type: 'builtin' },
              { id: 'imported:b', source_type: 'imported' },
              { id: 'beautify:c', source_type: 'package_embedded' },
            ],
          },
        };

        const grouped = component.groupedWallpapers;
        if (grouped.builtin.length !== 1 || grouped.imported.length !== 1 || grouped.beautify.length !== 1) {
          throw new Error(`unexpected grouped wallpapers: ${JSON.stringify(grouped)}`);
        }

        component.setSourceFilter('beautify');
        const filtered = component.filteredWallpapers;
        if (filtered.length !== 1 || filtered[0].id !== 'beautify:c') {
          throw new Error(`unexpected filtered wallpapers: ${JSON.stringify(filtered)}`);
        }
        """
    )


def test_shared_wallpaper_picker_exposes_preview_asset_url_helper():
    run_shared_wallpaper_picker_runtime_check(
        """
        const resolvedBuiltin = component.sharedWallpaperPreviewUrl('static/assets/wallpapers/builtin/space/stars.png');
        if (resolvedBuiltin !== '/api/beautify/preview-asset/static/assets/wallpapers/builtin/space/stars.png') {
          throw new Error(`unexpected builtin preview url: ${resolvedBuiltin}`);
        }

        const resolvedImported = component.sharedWallpaperPreviewUrl('data/library/wallpapers/imported/demo.png');
        if (resolvedImported !== '/api/beautify/preview-asset/data/library/wallpapers/imported/demo.png') {
          throw new Error(`unexpected imported preview url: ${resolvedImported}`);
        }
      """
    )


def test_shared_wallpaper_picker_selection_updates_manager_wallpaper_context():
    run_shared_wallpaper_picker_runtime_check(
        """
        const selectCalls = [];
        const dispatched = [];
        globalThis.window = {
          dispatchEvent(event) {
            dispatched.push(event);
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, options = {}) {
            this.type = type;
            this.detail = options.detail;
          }
        };
        const managerComponent = module.default({
          selectionTarget: 'manager',
          persistSelection: false,
        });

        managerComponent.$store = {
          global: {
            settingsForm: {
              manager_wallpaper_id: '',
              bg_url: '/legacy/background.png',
            },
            sharedWallpapers: [],
            resolveManagerBackgroundUrl() {
              const item = this.sharedWallpapers.find((entry) => entry.id === this.settingsForm.manager_wallpaper_id);
              return item ? `/${item.file}` : this.settingsForm.bg_url || '';
            },
            updateBackgroundImage(url) {
              globalThis.__selectedBackgroundUrl = url;
            },
          },
        };

        await managerComponent.selectWallpaper({
          id: 'builtin:space/stars.png',
          file: 'static/assets/wallpapers/builtin/space/stars.png',
          source_type: 'builtin',
        });

        if (selectCalls.length !== 0) {
          throw new Error(`manager draft selection should not call select api: ${JSON.stringify(selectCalls)}`);
        }

        if (managerComponent.$store.global.settingsForm.manager_wallpaper_id !== 'builtin:space/stars.png') {
          throw new Error(`unexpected selected wallpaper id: ${managerComponent.$store.global.settingsForm.manager_wallpaper_id}`);
        }
        if (managerComponent.$store.global.settingsForm.bg_url !== '') {
          throw new Error(`expected bg_url cleared, got: ${managerComponent.$store.global.settingsForm.bg_url}`);
        }
        if (globalThis.__selectedBackgroundUrl !== '/static/assets/wallpapers/builtin/space/stars.png') {
          throw new Error(`unexpected background url: ${globalThis.__selectedBackgroundUrl}`);
        }
        if (!dispatched.some((event) => event.type === 'shared-wallpaper-selected' && event.detail?.wallpaper?.id === 'builtin:space/stars.png' && event.detail?.selectionTarget === 'manager')) {
          throw new Error(`expected shared-wallpaper-selected event, got: ${JSON.stringify(dispatched)}`);
        }
        """
    )


def test_shared_wallpaper_picker_import_merges_single_item_into_existing_list():
    run_shared_wallpaper_picker_runtime_check(
        """
        const importCalls = [];
        const dispatched = [];
        globalThis.window = {
          dispatchEvent(event) {
            dispatched.push(event);
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, options = {}) {
            this.type = type;
            this.detail = options.detail;
          }
        };
        globalThis.__importSharedWallpaperStub = async (formData, selectionTarget) => {
          importCalls.push({ entries: formData.entries, selectionTarget });
          return {
            success: true,
            item: {
              id: 'imported:new-wallpaper.png',
              file: 'data/library/wallpapers/imported/new-wallpaper.png',
              source_type: 'imported',
            },
          };
        };

        const managerComponent = module.default({
          selectionTarget: 'manager',
          persistSelection: false,
        });

        managerComponent.$store = {
          global: {
            settingsForm: {
              manager_wallpaper_id: '',
              bg_url: '/legacy/background.png',
            },
            sharedWallpapers: [
              {
                id: 'builtin:space/stars.png',
                file: 'static/assets/wallpapers/builtin/space/stars.png',
                source_type: 'builtin',
              },
            ],
            resolveManagerBackgroundUrl() {
              const item = this.sharedWallpapers.find((entry) => entry.id === this.settingsForm.manager_wallpaper_id);
              return item ? `/${item.file}` : this.settingsForm.bg_url || '';
            },
            updateBackgroundImage(url) {
              globalThis.__importedBackgroundUrl = url;
            },
          },
        };

        await managerComponent.handleImport({
          target: {
            files: [{ name: 'new-wallpaper.png' }],
            value: 'filled',
          },
        });

        if (importCalls.length !== 1) {
          throw new Error(`expected one import call, got: ${JSON.stringify(importCalls)}`);
        }
        if (importCalls[0].selectionTarget !== '') {
          throw new Error(`manager draft import should omit immediate selection target, got: ${JSON.stringify(importCalls)}`);
        }
        const entries = importCalls[0].entries;
        if (entries.some(([key]) => key === 'selection_target')) {
          throw new Error(`draft manager import should not append selection_target, got: ${JSON.stringify(entries)}`);
        }
        const ids = managerComponent.$store.global.sharedWallpapers.map((item) => item.id).sort();
        if (ids.length !== 2 || ids[0] !== 'builtin:space/stars.png' || ids[1] !== 'imported:new-wallpaper.png') {
          throw new Error(`unexpected merged wallpaper ids: ${JSON.stringify(ids)}`);
        }
        if (managerComponent.$store.global.settingsForm.manager_wallpaper_id !== 'imported:new-wallpaper.png') {
          throw new Error(`expected imported wallpaper selected locally, got: ${managerComponent.$store.global.settingsForm.manager_wallpaper_id}`);
        }
        if (managerComponent.$store.global.settingsForm.bg_url !== '') {
          throw new Error(`expected bg_url cleared after import, got: ${managerComponent.$store.global.settingsForm.bg_url}`);
        }
        if (globalThis.__importedBackgroundUrl !== '/data/library/wallpapers/imported/new-wallpaper.png') {
          throw new Error(`unexpected imported background url: ${globalThis.__importedBackgroundUrl}`);
        }
        if (!dispatched.some((event) => event.type === 'shared-wallpaper-selected' && event.detail?.wallpaper?.id === 'imported:new-wallpaper.png' && event.detail?.selectionTarget === 'manager')) {
          throw new Error(`expected import to dispatch shared-wallpaper-selected, got: ${JSON.stringify(dispatched)}`);
        }
        """
    )


def test_shared_wallpaper_picker_selection_updates_preview_wallpaper_context():
    run_shared_wallpaper_picker_runtime_check(
        """
        const selectCalls = [];
        globalThis.__selectSharedWallpaperStub = async (payload) => {
          selectCalls.push(payload);
          return ({
            success: true,
            wallpaper: {
              id: payload.wallpaper_id,
              file: 'data/library/wallpapers/imported/preview.png',
              source_type: 'imported',
            },
          });
        };

        const previewComponent = module.default({ selectionTarget: 'preview' });
        previewComponent.$store = {
          global: {
            beautifyGlobalSettings: {
              preview_wallpaper_id: '',
              wallpaper: null,
            },
            sharedWallpapers: [],
          },
        };

        await previewComponent.selectWallpaper({ id: 'imported:preview' });

        if (selectCalls.length !== 1 || selectCalls[0].selection_target !== 'preview') {
          throw new Error(`unexpected preview select payloads: ${JSON.stringify(selectCalls)}`);
        }
        if (previewComponent.$store.global.beautifyGlobalSettings.preview_wallpaper_id !== 'imported:preview') {
          throw new Error(`expected preview wallpaper id update, got: ${previewComponent.$store.global.beautifyGlobalSettings.preview_wallpaper_id}`);
        }
        if (previewComponent.$store.global.beautifyGlobalSettings.wallpaper?.id !== 'imported:preview') {
          throw new Error(`expected preview wallpaper object update, got: ${JSON.stringify(previewComponent.$store.global.beautifyGlobalSettings.wallpaper)}`);
        }
      """
    )


def test_settings_modal_applies_shared_wallpaper_selection_detail():
    run_settings_modal_runtime_check(
        """
        component.$store = {
          global: {
            settingsForm: {
              manager_wallpaper_id: '',
              bg_url: '/legacy/background.png',
            },
            sharedWallpapers: [
              {
                id: 'builtin:space/stars.png',
                file: 'static/assets/wallpapers/builtin/space/stars.png',
                source: 'builtin',
              },
            ],
            resolveManagerBackgroundUrl() {
              const item = this.sharedWallpapers.find((entry) => entry.id === this.settingsForm.manager_wallpaper_id);
              return item ? `/${item.file}` : this.settingsForm.bg_url || '';
            },
            updateBackgroundImage(url) {
              backgroundUpdates.push(url);
            },
          },
        };

        component.applySharedWallpaperSelection({
          selectionTarget: 'manager',
          wallpaper: {
            id: 'builtin:space/stars.png',
            file: 'static/assets/wallpapers/builtin/space/stars.png',
            source: 'builtin',
          },
        });

        if (component.$store.global.settingsForm.manager_wallpaper_id !== 'builtin:space/stars.png') {
          throw new Error('expected applySharedWallpaperSelection() to store selected id');
        }
        if (component.$store.global.settingsForm.bg_url !== '') {
          throw new Error(`expected legacy bg_url cleared, got: ${component.$store.global.settingsForm.bg_url}`);
        }
        if (backgroundUpdates.length !== 1 || backgroundUpdates[0] !== '/static/assets/wallpapers/builtin/space/stars.png') {
          throw new Error(`unexpected background updates: ${JSON.stringify(backgroundUpdates)}`);
        }
        """
    )


def test_settings_modal_ignores_preview_shared_wallpaper_selection_detail():
    run_settings_modal_runtime_check(
        """
        component.$store = {
          global: {
            settingsForm: {
              manager_wallpaper_id: '',
              bg_url: '/legacy/background.png',
            },
            sharedWallpapers: [
              {
                id: 'builtin:space/stars.png',
                file: 'static/assets/wallpapers/builtin/space/stars.png',
                source: 'builtin',
              },
            ],
            resolveManagerBackgroundUrl() {
              const item = this.sharedWallpapers.find((entry) => entry.id === this.settingsForm.manager_wallpaper_id);
              return item ? `/${item.file}` : this.settingsForm.bg_url || '';
            },
            updateBackgroundImage(url) {
              backgroundUpdates.push(url);
            },
          },
        };

        component.applySharedWallpaperSelection({
          selectionTarget: 'preview',
          wallpaper: {
            id: 'builtin:space/stars.png',
            file: 'static/assets/wallpapers/builtin/space/stars.png',
            source: 'builtin',
          },
        });

        if (component.$store.global.settingsForm.manager_wallpaper_id !== '') {
          throw new Error('preview selection detail should not set manager_wallpaper_id');
        }
        if (component.$store.global.settingsForm.bg_url !== '/legacy/background.png') {
          throw new Error('preview selection detail should preserve legacy bg_url');
        }
        if (backgroundUpdates.length !== 0) {
          throw new Error(`preview selection detail should not trigger background updates: ${JSON.stringify(backgroundUpdates)}`);
        }
        """
    )


def test_settings_modal_ignores_stale_shared_wallpaper_selection_detail_without_clearing_legacy_background():
    run_settings_modal_runtime_check(
        """
        component.$store = {
          global: {
            settingsForm: {
              manager_wallpaper_id: '',
              bg_url: '/legacy/background.png',
            },
            sharedWallpapers: [],
            resolveManagerBackgroundUrl() {
              return this.settingsForm.bg_url || '';
            },
            updateBackgroundImage(url) {
              backgroundUpdates.push(url);
            },
          },
        };

        component.applySharedWallpaperSelection({
          selectionTarget: 'manager',
          wallpaper: {
            id: '',
            file: 'static/assets/wallpapers/builtin/space/stars.png',
          },
        });

        if (component.$store.global.settingsForm.manager_wallpaper_id !== '') {
          throw new Error('stale selection detail should not set manager_wallpaper_id');
        }
        if (component.$store.global.settingsForm.bg_url !== '/legacy/background.png') {
          throw new Error('stale selection detail should preserve legacy bg_url');
        }
        if (backgroundUpdates.length !== 0) {
          throw new Error(`stale selection detail should not trigger background updates: ${JSON.stringify(backgroundUpdates)}`);
        }
        """
    )


def test_settings_modal_tracks_path_safety_conflicts_confirmation_and_blocked_sync_actions():
    run_settings_modal_runtime_check(
        """
        const confirmMessages = [];
        const saveCalls = [];
        globalThis.confirm = (message) => {
          confirmMessages.push(message);
          return true;
        };
        const evaluateCalls = [];
        globalThis.__evaluateSettingsPathSafetyStub = async (config) => {
          evaluateCalls.push({ ...config });
          return {
            success: true,
            risk_level: 'warning',
            risk_summary: '检测到 1 个路径与 SillyTavern 目录重叠。',
            blocked_actions: ['sync_all', 'sync_characters'],
            conflicts: [
              {
                field: 'cards_dir',
                message: '角色卡路径与 ST characters 目录重叠。',
                severity: 'warning',
              },
            ],
          };
        };

        component.$store = {
          global: {
            settingsForm: {
              cards_dir: 'cards',
              resources_dir: 'resources',
              st_data_dir: 'D:/SillyTavern',
              allowed_abs_resource_roots: [],
            },
            saveSettings(closeModal, options = {}) {
              saveCalls.push({ closeModal, options: { ...options } });
              if (saveCalls.length === 1) {
                return Promise.resolve({
                  success: false,
                  requires_confirmation: true,
                  path_safety: {
                    risk_level: 'warning',
                    risk_summary: '检测到 1 个路径与 SillyTavern 目录重叠。',
                    blocked_actions: ['sync_all', 'sync_characters'],
                    conflicts: [
                      {
                        field: 'cards_dir',
                        message: '角色卡路径与 ST characters 目录重叠。',
                        severity: 'warning',
                      },
                    ],
                  },
                });
              }
              return Promise.resolve({
                success: true,
                path_safety: {
                  risk_level: 'warning',
                  risk_summary: '检测到 1 个路径与 SillyTavern 目录重叠。',
                  blocked_actions: ['sync_all', 'sync_characters'],
                  conflicts: [
                    {
                      field: 'cards_dir',
                      message: '角色卡路径与 ST characters 目录重叠。',
                      severity: 'warning',
                    },
                  ],
                },
              });
            },
          },
        };

        await component.saveSettings(false);

        if (saveCalls.length !== 2) {
          throw new Error(`expected confirmation retry save, got: ${JSON.stringify(saveCalls)}`);
        }
        if (saveCalls[0].options.confirm_risky_paths !== undefined) {
          throw new Error(`expected first save to omit confirm_risky_paths, got: ${JSON.stringify(saveCalls)}`);
        }
        if (saveCalls[1].options.confirm_risky_paths !== true) {
          throw new Error(`expected retry save to confirm risky paths, got: ${JSON.stringify(saveCalls)}`);
        }
        if (confirmMessages.length !== 1 || !confirmMessages[0].includes('角色卡路径与 ST characters 目录重叠。')) {
          throw new Error(`expected confirmation prompt with conflict message, got: ${JSON.stringify(confirmMessages)}`);
        }
        if (!component.pathSafety || component.pathSafety.risk_level !== 'warning') {
          throw new Error(`expected warning pathSafety retained after confirmed save, got: ${JSON.stringify(component.pathSafety)}`);
        }
        if (component.getPathConflictMessage('cards_dir') !== '角色卡路径与 ST characters 目录重叠。') {
          throw new Error(`unexpected field conflict message: ${component.getPathConflictMessage('cards_dir')}`);
        }
        if (component.getPathConflictMessage('resources_dir') !== '') {
          throw new Error(`expected empty conflict message for unrelated field, got: ${component.getPathConflictMessage('resources_dir')}`);
        }
        if (!component.isSyncActionBlocked('sync_characters') || !component.isSyncActionBlocked('sync_all')) {
          throw new Error(`expected sync actions blocked, got: ${JSON.stringify(component.pathSafety)}`);
        }
        if (component.syncSafetySummary !== '部分同步操作因路径风险已被禁用。') {
          throw new Error(`unexpected sync safety summary: ${component.syncSafetySummary}`);
        }

        await component.schedulePathSafetyEvaluation();
        if (evaluateCalls.length !== 1 || evaluateCalls[0].st_data_dir !== 'D:/SillyTavern') {
          throw new Error(`expected path safety evaluation call, got: ${JSON.stringify(evaluateCalls)}`);
        }
        """
    )


def test_settings_modal_refreshes_path_safety_after_st_path_validation_and_blocks_sync_requests():
    run_settings_modal_runtime_check(
        """
        const fetchCalls = [];
        const evaluateCalls = [];
        globalThis.fetch = async (url, options = {}) => {
          fetchCalls.push({ url, options });
          if (url === '/api/st/validate_path') {
            return {
              async json() {
                return {
                  success: true,
                  valid: true,
                  normalized_path: 'D:/SillyTavern',
                  resources: {
                    characters: { count: 1 },
                  },
                };
              },
            };
          }
          throw new Error(`unexpected fetch url: ${url}`);
        };
        globalThis.__evaluateSettingsPathSafetyStub = async (config) => {
          evaluateCalls.push({ ...config });
          return {
            success: true,
            risk_level: 'danger',
            risk_summary: '检测到 1 个路径与 SillyTavern 目录重叠。',
            blocked_actions: ['sync_chats', 'sync_all'],
            conflicts: [
              {
                field: 'chats_dir',
                message: '聊天路径与 ST chats 目录重叠。',
                severity: 'danger',
              },
            ],
          };
        };

        const dispatched = [];
        globalThis.window = {
          setTimeout,
          clearTimeout,
          dispatchEvent(event) {
            dispatched.push(event.type);
          },
        };
        globalThis.CustomEvent = class CustomEvent {
          constructor(type, options = {}) {
            this.type = type;
            this.detail = options.detail;
          }
        };

        component.$store = {
          global: {
            settingsForm: {
              st_data_dir: 'D:/SillyTavern/data/default-user',
              chats_dir: 'data/library/chats',
              allowed_abs_resource_roots: [],
            },
          },
        };

        await component.validateSTPath();

        if (!component.stPathValid) {
          throw new Error(`expected valid ST path, got: ${component.stPathStatus}`);
        }
        if (component.$store.global.settingsForm.st_data_dir !== 'D:/SillyTavern') {
          throw new Error(`expected normalized st path stored, got: ${component.$store.global.settingsForm.st_data_dir}`);
        }
        if (fetchCalls.length !== 1 || evaluateCalls.length !== 1 || evaluateCalls[0].st_data_dir !== 'D:/SillyTavern') {
          throw new Error(`expected validation plus safety refresh, got: ${JSON.stringify({ fetchCalls, evaluateCalls })}`);
        }
        if (!component.isSyncActionBlocked('sync_chats') || !component.isSyncActionBlocked('sync_all')) {
          throw new Error(`expected blocked sync actions after validation, got: ${JSON.stringify(component.pathSafety)}`);
        }

        component.syncing = false;
        component.syncStatus = '';
        await component.syncFromST('chats');
        if (!component.syncStatus.includes('已被禁用')) {
          throw new Error(`expected blocked sync status, got: ${component.syncStatus}`);
        }
        if (fetchCalls.length !== 1) {
          throw new Error(`blocked single sync should not hit backend, got: ${JSON.stringify(fetchCalls)}`);
        }

        await component.syncAllFromST();
        if (!component.syncStatus.includes('已被禁用')) {
          throw new Error(`expected blocked sync-all status, got: ${component.syncStatus}`);
        }
        if (fetchCalls.length !== 1) {
          throw new Error(`blocked sync-all should not hit backend, got: ${JSON.stringify(fetchCalls)}`);
        }
        if (dispatched.length !== 0) {
          throw new Error(`blocked sync should not dispatch refresh events, got: ${JSON.stringify(dispatched)}`);
        }
        """
    )


def test_settings_modal_watches_st_compatibility_fields_for_live_path_safety_refresh():
    run_settings_modal_runtime_check(
        """
        const evaluateCalls = [];
        globalThis.__evaluateSettingsPathSafetyStub = async (config) => {
          evaluateCalls.push({ ...config });
          return {
            success: true,
            risk_level: 'warning',
            risk_summary: '检测到 1 个路径与 SillyTavern 目录重叠。',
            blocked_actions: [],
            conflicts: [
              {
                field: 'st_openai_preset_dir',
                message: 'OpenAI 兼容目录与 ST 预设目录重叠。',
                severity: 'warning',
              },
            ],
          };
        };

        const watchers = new Map();
        globalThis.setTimeout = (callback) => {
          callback();
          return 1;
        };
        globalThis.clearTimeout = () => {};
        component.$watch = (expression, callback) => {
          watchers.set(expression, callback);
        };
        component.$store = {
          global: {
            showSettingsModal: true,
            settingsForm: {
              st_data_dir: 'D:/SillyTavern',
              st_openai_preset_dir: 'D:/SillyTavern/data/default-user/openai',
              allowed_abs_resource_roots: [],
            },
          },
        };

        component.init();

        const compatibilityFields = [
          'settingsForm.st_openai_preset_dir',
        ];

        for (const expression of compatibilityFields) {
          if (!watchers.has(expression)) {
            throw new Error(`missing watcher for compatibility field: ${expression}`);
          }
        }

        watchers.get('settingsForm.st_openai_preset_dir')();
        await Promise.resolve();
        await Promise.resolve();

        if (evaluateCalls.length !== 1 || evaluateCalls[0].st_openai_preset_dir !== 'D:/SillyTavern/data/default-user/openai') {
          throw new Error(`expected compatibility field edit to refresh path safety, got: ${JSON.stringify(evaluateCalls)}`);
        }
        if (component.getPathConflictMessage('st_openai_preset_dir') !== 'OpenAI 兼容目录与 ST 预设目录重叠。') {
          throw new Error(`expected compatibility conflict retained, got: ${component.getPathConflictMessage('st_openai_preset_dir')}`);
        }
        """
    )


def test_settings_modal_clearing_st_path_invalidates_inflight_path_safety_refresh():
    run_settings_modal_runtime_check(
        """
        const evaluateCalls = [];
        let resolveEvaluation;
        const evaluationPromise = new Promise((resolve) => {
          resolveEvaluation = resolve;
        });
        globalThis.__evaluateSettingsPathSafetyStub = (config) => {
          evaluateCalls.push({ ...config });
          return evaluationPromise;
        };

        let nextTimerId = 1;
        const timers = new Map();
        globalThis.setTimeout = (callback) => {
          const timerId = nextTimerId++;
          timers.set(timerId, callback);
          return timerId;
        };
        globalThis.clearTimeout = (timerId) => {
          timers.delete(timerId);
        };

        component.$store = {
          global: {
            settingsForm: {
              cards_dir: 'cards',
              st_data_dir: 'D:/SillyTavern',
              allowed_abs_resource_roots: [],
            },
          },
        };

        const pendingEvaluation = component.schedulePathSafetyEvaluation();
        const scheduledRefresh = timers.get(component.pathSafetyDebounceTimer);
        if (typeof scheduledRefresh !== 'function') {
          throw new Error(`expected debounced refresh callback, got: ${component.pathSafetyDebounceTimer}`);
        }

        scheduledRefresh();
        await Promise.resolve();

        component.$store.global.settingsForm.st_data_dir = '';
        const clearedState = await component.schedulePathSafetyEvaluation();
        if (clearedState.risk_level !== 'safe') {
          throw new Error(`expected immediate safe state after clearing ST path, got: ${JSON.stringify(clearedState)}`);
        }

        resolveEvaluation({
          success: true,
          risk_level: 'danger',
          risk_summary: 'Detected overlapping path.',
          blocked_actions: ['sync_all'],
          conflicts: [
            {
              field: 'cards_dir',
              message: 'cards_dir overlaps ST characters.',
              severity: 'danger',
            },
          ],
        });

        await pendingEvaluation;
        await Promise.resolve();

        if (evaluateCalls.length !== 1 || evaluateCalls[0].st_data_dir !== 'D:/SillyTavern') {
          throw new Error(`expected one in-flight evaluation for old ST path, got: ${JSON.stringify(evaluateCalls)}`);
        }
        if (component.pathSafety.risk_level !== 'safe') {
          throw new Error(`stale evaluation should not repopulate path safety after clearing ST path: ${JSON.stringify(component.pathSafety)}`);
        }
        if (component.getPathConflictMessage('cards_dir') !== '') {
          throw new Error(`stale evaluation should not restore field conflict after clearing ST path: ${component.getPathConflictMessage('cards_dir')}`);
        }
        if ((component.pathSafety.blocked_actions || []).length !== 0) {
          throw new Error(`stale evaluation should not restore blocked sync actions: ${JSON.stringify(component.pathSafety)}`);
        }
        """
    )


def test_settings_modal_number_stepper_clamps_and_increments_values():
    run_settings_modal_runtime_check(
        """
        component.$store = {
          global: {
            settingsForm: {
              snapshot_limit_manual: 200,
              snapshot_limit_auto: 1,
              wi_preview_limit: null,
            },
          },
        };

        component.adjustNumberSetting('snapshot_limit_manual', 1, 1, 200);
        if (component.$store.global.settingsForm.snapshot_limit_manual !== 200) {
          throw new Error('expected manual snapshot limit to clamp at its maximum');
        }

        component.adjustNumberSetting('snapshot_limit_auto', -1, 1, 50);
        if (component.$store.global.settingsForm.snapshot_limit_auto !== 1) {
          throw new Error('expected automatic snapshot limit to clamp at its minimum');
        }

        component.adjustNumberSetting('wi_preview_limit', 1, 0);
        if (component.$store.global.settingsForm.wi_preview_limit !== 1) {
          throw new Error('expected an empty preview limit to start from its minimum');
        }
        """
    )
