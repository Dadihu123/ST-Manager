import json
from pathlib import Path
import subprocess
import textwrap


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_presets_api_exposes_merge_and_import_helpers():
    source = read_project_file('static/js/api/presets.js')

    assert 'export async function mergePresetVersions(payload) {' in source
    assert 'fetch("/api/presets/version/merge", {' in source or "fetch('/api/presets/version/merge', {" in source
    assert 'export async function importPresetVersion(formData) {' in source
    assert 'fetch("/api/presets/version/import", {' in source or "fetch('/api/presets/version/import', {" in source
    assert 'body: formData' in source


def test_preset_merge_modal_template_renders_target_picker_family_name_and_preview():
    source = read_project_file('templates/modals/preset_version_merge.html')

    assert 'x-data="presetVersionMergeModal"' in source
    assert '{% call styled_select(' in source
    assert '"selectedTargetId",' in source
    assert 'x-for="item in flattenedItems"' in source
    assert 'x-for="item in items"' not in source
    assert 'x-model="familyName"' in source
    assert 'x-for="row in previewVersions"' in source
    assert '@click="confirmMerge()"' in source


def test_preset_merge_modal_runtime_builds_preview_and_posts_selected_target():
    source_path = PROJECT_ROOT / 'static/js/components/presetVersionMergeModal.js'
    node_script = textwrap.dedent(
        f"""
        import {{ readFileSync }} from 'node:fs';

        const sourcePath = {json.dumps(str(source_path))};
        let source = readFileSync(sourcePath, 'utf8');
        source = source.replace(/^import[\\s\\S]*?;\\r?\\n/gm, '');
        source = source.replace('export default function presetVersionMergeModal()', 'function presetVersionMergeModal()');
        const stubs = `
        let __mergeImpl = async () => ({{ success: true, preset: {{ id: 'global::alpha.json', family_info: {{ family_name: 'Merged Family' }}, available_versions: [] }} }});
        const mergePresetVersions = (...args) => __mergeImpl(...args);
        globalThis.__setMergePresetVersions = (fn) => {{ __mergeImpl = fn; }};
        globalThis.window = {{ dispatchEvent() {{ return true; }} }};
        globalThis.CustomEvent = class CustomEvent {{ constructor(name, options = {{}}) {{ this.type = name; this.detail = options.detail; }} }};
        `;
        const module = await import('data:text/javascript,' + encodeURIComponent(stubs + source + '\\nexport default presetVersionMergeModal;'));
        const modal = module.default();
        const calls = [];
        globalThis.__setMergePresetVersions(async (payload) => {{ calls.push(payload); return {{ success: true, preset: {{ id: payload.target_preset_id, family_info: {{ family_name: payload.family_name }}, available_versions: [] }} }}; }});

        modal.$store = {{ global: {{ showToast() {{}}, deviceType: 'desktop' }} }};
        modal.open({{
          items: [
            {{
              id: 'global::family',
              entry_type: 'family',
              name: 'Alpha Family',
              versions: [
                {{ id: 'global::alpha.json', name: 'Alpha', filename: 'alpha.json', preset_version: {{ version_label: 'alpha' }} }},
                {{ id: 'global::beta.json', name: 'Beta', filename: 'beta.json', preset_version: {{ version_label: 'beta' }} }},
              ],
            }},
            {{ id: 'global::gamma.json', entry_type: 'single', name: 'Gamma', filename: 'gamma.json', preset_kind: 'openai', root_scope_key: 'global' }},
          ],
        }});

        if (modal.previewVersions.length !== 3) throw new Error('expected three preview rows');
        if (modal.previewVersions[0].version_label !== 'alpha') throw new Error(`expected filename-derived label, got ${{modal.previewVersions[0].version_label}}`);
        if (modal.selectedTargetId !== 'global::alpha.json') throw new Error(`expected default target to be first concrete version, got ${{modal.selectedTargetId}}`);
        if (modal.familyName !== 'Alpha Family') throw new Error(`expected family-origin target to default to family name, got ${{modal.familyName}}`);
        modal.selectedTargetId = 'global::beta.json';
        if (modal.familyName !== 'Alpha Family') throw new Error(`expected same-family version switch to keep family name, got ${{modal.familyName}}`);
        modal.selectedTargetId = 'global::gamma.json';
        if (modal.familyName !== 'Gamma') throw new Error(`expected family name to update with selected target, got ${{modal.familyName}}`);
        modal.familyName = 'Merged Family';
        await modal.confirmMerge();
        if (calls.length !== 1) throw new Error(`expected one merge request, got ${{calls.length}}`);
        if (calls[0].target_preset_id !== 'global::gamma.json') throw new Error(`expected selected target id, got ${{calls[0].target_preset_id}}`);
        if (!Array.isArray(calls[0].source_preset_ids)) throw new Error('expected source_preset_ids array');
        if (calls[0].source_preset_ids.length !== 3) throw new Error(`expected three concrete source ids, got ${{calls[0].source_preset_ids.length}}`);
        if (calls[0].source_preset_ids[0] !== 'global::alpha.json') throw new Error(`expected first flattened source id, got ${{calls[0].source_preset_ids[0]}}`);
        if (calls[0].source_preset_ids[1] !== 'global::beta.json') throw new Error(`expected second flattened source id, got ${{calls[0].source_preset_ids[1]}}`);
        if (calls[0].source_preset_ids[2] !== 'global::gamma.json') throw new Error(`expected single item source id, got ${{calls[0].source_preset_ids[2]}}`);
        if (calls[0].family_name !== 'Merged Family') throw new Error(`expected submitted family name, got ${{calls[0].family_name}}`);
        """
    )
    result = subprocess.run(['node', '--input-type=module', '-e', node_script], cwd=PROJECT_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout
