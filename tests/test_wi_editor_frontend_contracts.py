from pathlib import Path
import re
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding='utf-8')


def extract_js_function_block(source: str, signature: str) -> str:
    start = source.index(signature)
    brace_start = source.index('{', start)
    depth = 1
    index = brace_start + 1
    while depth > 0:
        char = source[index]
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        index += 1
    return source[start:index]


def run_js(script: str) -> None:
    subprocess.run(
        ['node', '-e', script],
        cwd=ROOT,
        check=True,
        text=True,
    )


def test_wi_editor_runtime_maps_position_and_role_to_unique_select_values():
    source = read_project_file('static/js/components/wiEditor.js')
    get_block = extract_js_function_block(source, 'getEditorPositionSelectValue(entry) {')
    update_block = extract_js_function_block(source, 'updateEditorPositionFromSelect(entry, rawValue) {')

    script = textwrap.dedent(
        f'''
        const component = {{
          {get_block}
          ,
          {update_block}
        }};

        if (component.getEditorPositionSelectValue({{ position: 4, role: 0 }}) !== '4:0') {{
          throw new Error('expected system at-depth select value');
        }}
        if (component.getEditorPositionSelectValue({{ position: 4, role: 1 }}) !== '4:1') {{
          throw new Error('expected user at-depth select value');
        }}
        if (component.getEditorPositionSelectValue({{ position: 4, role: 2 }}) !== '4:2') {{
          throw new Error('expected assistant at-depth select value');
        }}
        if (component.getEditorPositionSelectValue({{ position: 4, role: 99 }}) !== '4:0') {{
          throw new Error('expected invalid role to fall back to system');
        }}

        const depthEntry = {{ position: 1, role: null }};
        component.updateEditorPositionFromSelect(depthEntry, '4:2');
        if (depthEntry.position !== 4 || depthEntry.role !== 2) {{
          throw new Error('expected at-depth assistant writeback');
        }}

        component.updateEditorPositionFromSelect(depthEntry, '3');
        if (depthEntry.position !== 3 || depthEntry.role !== null) {{
          throw new Error('expected non-depth selection to clear role');
        }}
        '''
    )

    run_js(script)


def test_wi_editor_runtime_preserves_non_depth_positions_and_defaults_invalid_position():
    source = read_project_file('static/js/components/wiEditor.js')
    get_block = extract_js_function_block(source, 'getEditorPositionSelectValue(entry) {')
    update_block = extract_js_function_block(source, 'updateEditorPositionFromSelect(entry, rawValue) {')

    script = textwrap.dedent(
        f'''
        const component = {{
          {get_block},
          {update_block}
        }};

        if (component.getEditorPositionSelectValue({{ position: 6, role: 2 }}) !== '6') {{
          throw new Error('expected non-depth position passthrough');
        }}

        const entry = {{ position: 4, role: 2 }};
        component.updateEditorPositionFromSelect(entry, 'bad-value');
        if (entry.position !== 0 || entry.role !== null) {{
          throw new Error('expected invalid select value to fall back to ST position 0 and clear role');
        }}
        '''
    )

    run_js(script)


def test_wi_editor_logic_select_matches_sillytavern_value_semantics():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')
    match = re.search(
        r'<select[^>]*x-model\.number="activeEditorEntry\.selectiveLogic"[^>]*>(.*?)</select>',
        template,
        re.S,
    )

    assert match, 'logic select should exist in fullscreen editor template'

    options = [
        (value, label.strip())
        for value, label in re.findall(r'<option\s+value="([^"]+)">(.*?)</option>', match.group(1), re.S)
    ]

    assert [value for value, _ in options] == ['0', '3', '1', '2']

    labels = {value: label for value, label in options}
    assert 'AND ANY' in labels['0']
    assert 'AND ALL' in labels['3']
    assert 'NOT ALL' in labels['1']
    assert 'NOT ANY' in labels['2']


def test_normalize_wi_entry_preserves_delay_until_recursion_boolean_and_numeric_semantics():
    source = read_project_file('static/js/utils/data.js')
    normalize_block = extract_js_function_block(
        source,
        'export function normalizeWiEntry(entry, index = 0) {',
    ).replace('export ', '', 1)

    script = textwrap.dedent(
        f'''
        {normalize_block}

        const asTrue = normalizeWiEntry({{ delayUntilRecursion: true }}, 0);
        if (asTrue.delayUntilRecursion !== true) {{
          throw new Error(`expected boolean true, got ${{String(asTrue.delayUntilRecursion)}}`);
        }}

        const asFalse = normalizeWiEntry({{ delayUntilRecursion: false }}, 0);
        if (asFalse.delayUntilRecursion !== false) {{
          throw new Error(`expected boolean false, got ${{String(asFalse.delayUntilRecursion)}}`);
        }}

        const asNumber = normalizeWiEntry({{ delayUntilRecursion: 3 }}, 0);
        if (asNumber.delayUntilRecursion !== 3) {{
          throw new Error(`expected numeric level 3, got ${{String(asNumber.delayUntilRecursion)}}`);
        }}
        '''
    )

    run_js(script)


def test_wi_editor_template_uses_delay_until_recursion_helpers_instead_of_numeric_x_model():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    assert 'x-model.number="activeEditorEntry.delayUntilRecursion"' not in template
    assert 'getDelayUntilRecursionEnabled(activeEditorEntry)' in template
    assert 'setDelayUntilRecursionEnabled(activeEditorEntry, $event.target.checked)' in template
    assert 'getDelayUntilRecursionLevel(activeEditorEntry)' in template
    assert 'setDelayUntilRecursionLevel(activeEditorEntry, $event.target.value)' in template


def test_wi_editor_runtime_delay_until_recursion_helpers_follow_st_semantics():
    source = read_project_file('static/js/components/wiEditor.js')
    get_enabled_block = extract_js_function_block(
        source,
        'getDelayUntilRecursionEnabled(entry) {',
    )
    get_level_block = extract_js_function_block(
        source,
        'getDelayUntilRecursionLevel(entry) {',
    )
    set_enabled_block = extract_js_function_block(
        source,
        'setDelayUntilRecursionEnabled(entry, enabled) {',
    )
    set_level_block = extract_js_function_block(
        source,
        'setDelayUntilRecursionLevel(entry, rawValue) {',
    )

    script = textwrap.dedent(
        f'''
        const component = {{
          {get_enabled_block},
          {get_level_block},
          {set_enabled_block},
          {set_level_block}
        }};

        const enabledOnly = {{ delayUntilRecursion: false }};
        if (component.getDelayUntilRecursionEnabled(enabledOnly) !== false) {{
          throw new Error('expected disabled state to read as false');
        }}

        component.setDelayUntilRecursionEnabled(enabledOnly, true);
        if (enabledOnly.delayUntilRecursion !== true) {{
          throw new Error(`expected enabling without level to produce boolean true, got ${{String(enabledOnly.delayUntilRecursion)}}`);
        }}
        if (component.getDelayUntilRecursionLevel(enabledOnly) !== '') {{
          throw new Error('expected boolean-only recursion delay to show blank level');
        }}

        component.setDelayUntilRecursionLevel(enabledOnly, '3');
        if (enabledOnly.delayUntilRecursion !== 3) {{
          throw new Error(`expected typed level to produce number 3, got ${{String(enabledOnly.delayUntilRecursion)}}`);
        }}
        if (component.getDelayUntilRecursionLevel(enabledOnly) !== 3) {{
          throw new Error('expected numeric recursion delay level to round-trip');
        }}

        const preLeveled = {{ delayUntilRecursion: 2 }};
        component.setDelayUntilRecursionEnabled(preLeveled, true);
        if (preLeveled.delayUntilRecursion !== 2) {{
          throw new Error('expected enabling to preserve an existing numeric level');
        }}

        component.setDelayUntilRecursionLevel(enabledOnly, '');
        if (enabledOnly.delayUntilRecursion !== true) {{
          throw new Error(`expected blank level to fall back to boolean true, got ${{String(enabledOnly.delayUntilRecursion)}}`);
        }}

        component.setDelayUntilRecursionEnabled(enabledOnly, false);
        if (enabledOnly.delayUntilRecursion !== false) {{
          throw new Error(`expected disabling to produce boolean false, got ${{String(enabledOnly.delayUntilRecursion)}}`);
        }}
      '''
    )

    run_js(script)


def test_wi_editor_template_exposes_selective_scan_depth_and_outlet_name_controls():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    assert 'x-model="activeEditorEntry.selective"' in template
    assert 'x-model.number="activeEditorEntry.scanDepth"' in template
    assert 'x-model="activeEditorEntry.outletName"' in template
    assert ':disabled="!activeEditorEntry.selective"' in template


def test_wi_editor_template_shows_outlet_name_only_for_outlet_position():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')
    assert 'x-if="activeEditorEntry.position === 7"' in template


def test_normalize_wi_entry_preserves_scan_depth_and_outlet_name_and_defaults_selective_true():
    source = read_project_file('static/js/utils/data.js')
    normalize_block = extract_js_function_block(
        source,
        'export function normalizeWiEntry(entry, index = 0) {',
    ).replace('export ', '', 1)

    script = textwrap.dedent(
        f'''
        {normalize_block}

        const entry = normalizeWiEntry({{
          scanDepth: 6,
          outletName: 'memory',
          selective: false,
        }}, 0);
        if (entry.scanDepth !== 6) {{
          throw new Error(`expected scanDepth 6, got ${{String(entry.scanDepth)}}`);
        }}
        if (entry.outletName !== 'memory') {{
          throw new Error(`expected outletName memory, got ${{String(entry.outletName)}}`);
        }}
        if (entry.selective !== false) {{
          throw new Error(`expected selective false, got ${{String(entry.selective)}}`);
        }}

        const defaultEntry = normalizeWiEntry({{}}, 0);
        if (defaultEntry.selective !== true) {{
          throw new Error(`expected selective default true, got ${{String(defaultEntry.selective)}}`);
        }}
        '''
    )

    run_js(script)


def test_new_entries_default_selective_true_without_scan_depth_or_outlet_name():
    helpers_source = read_project_file('static/js/utils/wiHelpers.js')
    add_block = extract_js_function_block(helpers_source, 'addWiEntry() {')

    script = textwrap.dedent(
        f'''
        const helper = {{
          entryUidField: 'st_manager_uid',
          currentWiIndex: -1,
          isEditingClipboard: false,
          $nextTick(fn) {{ fn(); }},
          _generateEntryUid() {{ return 'wi-test'; }},
          getWIArrayRef() {{
            if (!this._entries) this._entries = [];
            return this._entries;
          }},
          {add_block}
        }};

        globalThis.document = {{
          querySelector() {{ return null; }},
        }};

        helper.addWiEntry();
        const created = helper.getWIArrayRef()[0];
        if (!created) {{
          throw new Error('expected helper to create one entry');
        }}
        if (created.selective !== true) {{
          throw new Error(`expected new entry selective true, got ${{String(created.selective)}}`);
        }}
        if (Object.prototype.hasOwnProperty.call(created, 'scanDepth')) {{
          throw new Error('expected new entry to omit scanDepth until user sets it');
        }}
        if (Object.prototype.hasOwnProperty.call(created, 'outletName')) {{
          throw new Error('expected new entry to omit outletName until user sets it');
        }}
        '''
    )

    run_js(script)


def test_wi_editor_template_uses_tri_state_selects_for_case_sensitive_and_whole_words():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    assert 'x-model="activeEditorEntry.matchWholeWords"' not in template
    assert 'x-model="activeEditorEntry.caseSensitive"' not in template
    assert 'x-model="activeEditorEntry.matchWholeWordsState"' in template
    assert 'x-model="activeEditorEntry.caseSensitiveState"' in template
    assert template.count('<option value="null">跟随全局</option>') >= 2
    assert template.count('<option value="true">是</option>') >= 2
    assert template.count('<option value="false">否</option>') >= 2


def test_wi_editor_runtime_tri_state_helpers_round_trip_st_boolean_semantics():
    source = read_project_file('static/js/components/wiEditor.js')
    to_state_block = extract_js_function_block(
        source,
        'getTriStateSelectValue(value) {',
    )
    from_state_block = extract_js_function_block(
        source,
        'setTriStateValue(entry, key, rawValue) {',
    )

    script = textwrap.dedent(
        f'''
        const component = {{
          {to_state_block},
          {from_state_block}
        }};

        if (component.getTriStateSelectValue(null) !== 'null') {{
          throw new Error('expected null to render as string null');
        }}
        if (component.getTriStateSelectValue(true) !== 'true') {{
          throw new Error('expected true to render as string true');
        }}
        if (component.getTriStateSelectValue(false) !== 'false') {{
          throw new Error('expected false to render as string false');
        }}
        if (component.getTriStateSelectValue(undefined) !== 'null') {{
          throw new Error('expected undefined to render as global/null');
        }}

        const entry = {{}};
        component.setTriStateValue(entry, 'caseSensitive', 'true');
        if (entry.caseSensitive !== true) {{
          throw new Error(`expected true writeback, got ${{String(entry.caseSensitive)}}`);
        }}
        component.setTriStateValue(entry, 'caseSensitive', 'false');
        if (entry.caseSensitive !== false) {{
          throw new Error(`expected false writeback, got ${{String(entry.caseSensitive)}}`);
        }}
        component.setTriStateValue(entry, 'caseSensitive', 'null');
        if (entry.caseSensitive !== null) {{
          throw new Error(`expected null writeback, got ${{String(entry.caseSensitive)}}`);
        }}
        '''
    )

    run_js(script)


def test_normalize_wi_entry_preserves_tri_state_case_sensitive_and_match_whole_words():
    source = read_project_file('static/js/utils/data.js')
    normalize_block = extract_js_function_block(
        source,
        'export function normalizeWiEntry(entry, index = 0) {',
    ).replace('export ', '', 1)

    script = textwrap.dedent(
        f'''
        {normalize_block}

        const nullEntry = normalizeWiEntry({{
          caseSensitive: null,
          matchWholeWords: null,
        }}, 0);
        if (nullEntry.caseSensitive !== null) {{
          throw new Error(`expected caseSensitive null, got ${{String(nullEntry.caseSensitive)}}`);
        }}
        if (nullEntry.matchWholeWords !== null) {{
          throw new Error(`expected matchWholeWords null, got ${{String(nullEntry.matchWholeWords)}}`);
        }}

        const boolEntry = normalizeWiEntry({{
          caseSensitive: true,
          matchWholeWords: false,
        }}, 0);
        if (boolEntry.caseSensitive !== true) {{
          throw new Error(`expected caseSensitive true, got ${{String(boolEntry.caseSensitive)}}`);
        }}
        if (boolEntry.matchWholeWords !== false) {{
          throw new Error(`expected matchWholeWords false, got ${{String(boolEntry.matchWholeWords)}}`);
        }}
        '''
    )

    run_js(script)


def test_wi_editor_template_exposes_all_persisted_scan_source_toggles():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    expected_fields = [
        'matchCharacterDescription',
        'matchCharacterPersonality',
        'matchScenario',
        'matchPersonaDescription',
        'matchCharacterDepthPrompt',
        'matchCreatorNotes',
    ]

    for field in expected_fields:
        assert f'x-model="activeEditorEntry.{field}"' in template


def test_new_entries_default_all_scan_source_toggles_to_false():
    helpers_source = read_project_file('static/js/utils/wiHelpers.js')
    add_block = extract_js_function_block(helpers_source, 'addWiEntry() {')

    script = textwrap.dedent(
        f'''
        const helper = {{
          entryUidField: 'st_manager_uid',
          currentWiIndex: -1,
          isEditingClipboard: false,
          $nextTick(fn) {{ fn(); }},
          _generateEntryUid() {{ return 'wi-test'; }},
          getWIArrayRef() {{
            if (!this._entries) this._entries = [];
            return this._entries;
          }},
          {add_block}
        }};

        globalThis.document = {{
          querySelector() {{ return null; }},
        }};

        helper.addWiEntry();
        const created = helper.getWIArrayRef()[0];
        if (!created) {{
          throw new Error('expected helper to create one entry');
        }}

        const expectedFalseKeys = [
          'matchCharacterDescription',
          'matchCharacterPersonality',
          'matchScenario',
          'matchPersonaDescription',
          'matchCharacterDepthPrompt',
          'matchCreatorNotes',
        ];

        for (const key of expectedFalseKeys) {{
          if (created[key] !== false) {{
            throw new Error(`expected ${{key}} false by default, got ${{String(created[key])}}`);
          }}
        }}
        '''
    )

    run_js(script)


def test_wi_editor_template_exposes_timed_effect_fields_with_optional_number_helpers():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    for field in ['sticky', 'cooldown', 'delay']:
        assert f'getOptionalNumberInputValue(activeEditorEntry.{field})' in template
        assert f"setOptionalNumberField(activeEditorEntry, '{field}', $event.target.value)" in template


def test_wi_editor_runtime_optional_number_helper_preserves_null_and_numbers():
    source = read_project_file('static/js/components/wiEditor.js')
    get_block = extract_js_function_block(
        source,
        'getOptionalNumberInputValue(value) {',
    )
    set_block = extract_js_function_block(
        source,
        'setOptionalNumberField(entry, key, rawValue) {',
    )

    script = textwrap.dedent(
        f'''
        const component = {{
          {get_block},
          {set_block}
        }};

        if (component.getOptionalNumberInputValue(null) !== '') {{
          throw new Error('expected null to render as blank string');
        }}
        if (component.getOptionalNumberInputValue(undefined) !== '') {{
          throw new Error('expected undefined to render as blank string');
        }}
        if (component.getOptionalNumberInputValue(7) !== 7) {{
          throw new Error('expected numeric value to round-trip unchanged');
        }}

        const entry = {{}};
        component.setOptionalNumberField(entry, 'sticky', '12');
        if (entry.sticky !== 12) {{
          throw new Error(`expected sticky 12, got ${{String(entry.sticky)}}`);
        }}

        component.setOptionalNumberField(entry, 'sticky', '');
        if (entry.sticky !== null) {{
          throw new Error(`expected sticky null on blank input, got ${{String(entry.sticky)}}`);
        }}
        '''
    )

    run_js(script)


def test_new_entries_default_timed_effect_fields_to_null():
    helpers_source = read_project_file('static/js/utils/wiHelpers.js')
    add_block = extract_js_function_block(helpers_source, 'addWiEntry() {')

    script = textwrap.dedent(
        f'''
        const helper = {{
          entryUidField: 'st_manager_uid',
          currentWiIndex: -1,
          isEditingClipboard: false,
          $nextTick(fn) {{ fn(); }},
          _generateEntryUid() {{ return 'wi-test'; }},
          getWIArrayRef() {{
            if (!this._entries) this._entries = [];
            return this._entries;
          }},
          {add_block}
        }};

        globalThis.document = {{
          querySelector() {{ return null; }},
        }};

        helper.addWiEntry();
        const created = helper.getWIArrayRef()[0];
        if (!created) {{
          throw new Error('expected helper to create one entry');
        }}

        for (const key of ['sticky', 'cooldown', 'delay']) {{
          if (created[key] !== null) {{
            throw new Error(`expected ${{key}} null by default, got ${{String(created[key])}}`);
          }}
        }}
        '''
    )

    run_js(script)


def test_wi_editor_timed_effect_inputs_use_smaller_placeholder_text():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    for field in ['sticky', 'cooldown', 'delay']:
        assert f"setOptionalNumberField(activeEditorEntry, '{field}', $event.target.value)" in template

    assert template.count('placeholder:text-[10px]') >= 3


def test_wi_editor_template_exposes_group_phase6a_fields():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    assert 'x-model="activeEditorEntry.group"' in template
    assert 'x-model="activeEditorEntry.groupOverride"' in template
    assert 'x-model.number="activeEditorEntry.groupWeight"' in template
    assert 'x-model="activeEditorEntry.automationId"' in template


def test_new_entries_default_group_phase6a_fields_to_st_values():
    helpers_source = read_project_file('static/js/utils/wiHelpers.js')
    add_block = extract_js_function_block(helpers_source, 'addWiEntry() {')

    script = textwrap.dedent(
        f'''
        const helper = {{
          entryUidField: 'st_manager_uid',
          currentWiIndex: -1,
          isEditingClipboard: false,
          $nextTick(fn) {{ fn(); }},
          _generateEntryUid() {{ return 'wi-test'; }},
          getWIArrayRef() {{
            if (!this._entries) this._entries = [];
            return this._entries;
          }},
          {add_block}
        }};

        globalThis.document = {{
          querySelector() {{ return null; }},
        }};

        helper.addWiEntry();
        const created = helper.getWIArrayRef()[0];
        if (!created) {{
          throw new Error('expected helper to create one entry');
        }}

        if (created.group !== '') {{
          throw new Error(`expected group default '', got ${{String(created.group)}}`);
        }}
        if (created.groupOverride !== false) {{
          throw new Error(`expected groupOverride false, got ${{String(created.groupOverride)}}`);
        }}
        if (created.groupWeight !== 100) {{
          throw new Error(`expected groupWeight 100, got ${{String(created.groupWeight)}}`);
        }}
        if (created.automationId !== '') {{
          throw new Error(`expected automationId default '', got ${{String(created.automationId)}}`);
        }}
        '''
    )

    run_js(script)


def test_wi_editor_template_exposes_use_group_scoring_as_tri_state_select():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    assert 'x-model="activeEditorEntry.useGroupScoringState"' in template
    assert "setTriStateValue(activeEditorEntry, 'useGroupScoring', activeEditorEntry.useGroupScoringState)" in template
    assert 'getTriStateSelectValue(activeEditorEntry.useGroupScoring)' in template


def test_new_entries_default_use_group_scoring_to_null():
    helpers_source = read_project_file('static/js/utils/wiHelpers.js')
    add_block = extract_js_function_block(helpers_source, 'addWiEntry() {')

    script = textwrap.dedent(
        f'''
        const helper = {{
          entryUidField: 'st_manager_uid',
          currentWiIndex: -1,
          isEditingClipboard: false,
          $nextTick(fn) {{ fn(); }},
          _generateEntryUid() {{ return 'wi-test'; }},
          getWIArrayRef() {{
            if (!this._entries) this._entries = [];
            return this._entries;
          }},
          {add_block}
        }};

        globalThis.document = {{
          querySelector() {{ return null; }},
        }};

        helper.addWiEntry();
        const created = helper.getWIArrayRef()[0];
        if (!created) {{
          throw new Error('expected helper to create one entry');
        }}

        if (created.useGroupScoring !== null) {{
          throw new Error(`expected useGroupScoring null, got ${{String(created.useGroupScoring)}}`);
        }}
        '''
    )

    run_js(script)


def test_wi_editor_template_exposes_triggers_multi_select():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    assert '<select' in template and 'multiple' in template
    assert 'setMultiSelectField(activeEditorEntry, \'triggers\', $event.target)' in template
    for value in ['normal', 'continue', 'impersonate', 'swipe', 'regenerate', 'quiet']:
        assert f'value="{value}"' in template


def test_wi_editor_runtime_multi_select_helper_collects_selected_values():
    source = read_project_file('static/js/components/wiEditor.js')
    set_block = extract_js_function_block(
        source,
        'setMultiSelectField(entry, key, selectEl) {',
    )

    script = textwrap.dedent(
        f'''
        const component = {{
          {set_block}
        }};

        const entry = {{}};
        component.setMultiSelectField(entry, 'triggers', {{
          selectedOptions: [
            {{ value: 'normal' }},
            {{ value: 'quiet' }},
          ],
        }});

        if (!Array.isArray(entry.triggers) || entry.triggers.length !== 2) {{
          throw new Error('expected triggers to become a two-item array');
        }}
        if (entry.triggers[0] !== 'normal' || entry.triggers[1] !== 'quiet') {{
          throw new Error(`unexpected triggers order/value: ${{JSON.stringify(entry.triggers)}}`);
        }}
        '''
    )

    run_js(script)


def test_new_entries_default_triggers_to_empty_array():
    helpers_source = read_project_file('static/js/utils/wiHelpers.js')
    add_block = extract_js_function_block(helpers_source, 'addWiEntry() {')

    script = textwrap.dedent(
        f'''
        const helper = {{
          entryUidField: 'st_manager_uid',
          currentWiIndex: -1,
          isEditingClipboard: false,
          $nextTick(fn) {{ fn(); }},
          _generateEntryUid() {{ return 'wi-test'; }},
          getWIArrayRef() {{
            if (!this._entries) this._entries = [];
            return this._entries;
          }},
          {add_block}
        }};

        globalThis.document = {{
          querySelector() {{ return null; }},
        }};

        helper.addWiEntry();
        const created = helper.getWIArrayRef()[0];
        if (!created) {{
          throw new Error('expected helper to create one entry');
        }}

        if (!Array.isArray(created.triggers) || created.triggers.length !== 0) {{
          throw new Error(`expected triggers default [], got ${{JSON.stringify(created.triggers)}}`);
        }}
        '''
    )

    run_js(script)


def test_wi_editor_template_exposes_character_filter_controls():
    template = read_project_file('templates/modals/detail_wi_fullscreen.html')

    assert 'toggleCharacterFilterExclude(activeEditorEntry, $event.target.checked)' in template
    assert "setCharacterFilterCsv(activeEditorEntry, 'names', $event.target.value)" in template
    assert "setCharacterFilterCsv(activeEditorEntry, 'tags', $event.target.value)" in template


def test_wi_editor_runtime_character_filter_helpers_preserve_st_object_semantics():
    source = read_project_file('static/js/components/wiEditor.js')
    ensure_block = extract_js_function_block(
        source,
        'ensureCharacterFilterShape(entry) {',
    )
    toggle_block = extract_js_function_block(
        source,
        'toggleCharacterFilterExclude(entry, checked) {',
    )
    get_csv_block = extract_js_function_block(
        source,
        'getCharacterFilterCsv(entry, key) {',
    )
    set_csv_block = extract_js_function_block(
        source,
        'setCharacterFilterCsv(entry, key, rawValue) {',
    )

    script = textwrap.dedent(
        f'''
        const component = {{
          {ensure_block},
          {toggle_block},
          {get_csv_block},
          {set_csv_block}
        }};

        const entry = {{}};
        component.toggleCharacterFilterExclude(entry, true);
        if (!entry.characterFilter || entry.characterFilter.isExclude !== true) {{
          throw new Error('expected exclude toggle to create characterFilter object');
        }}
        if (JSON.stringify(entry.characterFilter.names) !== '[]' || JSON.stringify(entry.characterFilter.tags) !== '[]') {{
          throw new Error('expected empty names/tags arrays on creation');
        }}

        component.setCharacterFilterCsv(entry, 'names', 'Alice, Bob');
        if (JSON.stringify(entry.characterFilter.names) !== JSON.stringify(['Alice', 'Bob'])) {{
          throw new Error(`unexpected names: ${{JSON.stringify(entry.characterFilter.names)}}`);
        }}
        if (component.getCharacterFilterCsv(entry, 'names') !== 'Alice, Bob') {{
          throw new Error('expected names CSV to round-trip');
        }}

        component.setCharacterFilterCsv(entry, 'tags', 'tag-a, tag-b');
        if (JSON.stringify(entry.characterFilter.tags) !== JSON.stringify(['tag-a', 'tag-b'])) {{
          throw new Error(`unexpected tags: ${{JSON.stringify(entry.characterFilter.tags)}}`);
        }}

        component.setCharacterFilterCsv(entry, 'names', '');
        component.setCharacterFilterCsv(entry, 'tags', '');
        component.toggleCharacterFilterExclude(entry, false);
        if (Object.prototype.hasOwnProperty.call(entry, 'characterFilter')) {{
          throw new Error('expected empty non-exclude characterFilter to be removed');
        }}
        '''
    )

    run_js(script)


def test_new_entries_do_not_force_character_filter_object_by_default():
    helpers_source = read_project_file('static/js/utils/wiHelpers.js')
    add_block = extract_js_function_block(helpers_source, 'addWiEntry() {')

    script = textwrap.dedent(
        f'''
        const helper = {{
          entryUidField: 'st_manager_uid',
          currentWiIndex: -1,
          isEditingClipboard: false,
          $nextTick(fn) {{ fn(); }},
          _generateEntryUid() {{ return 'wi-test'; }},
          getWIArrayRef() {{
            if (!this._entries) this._entries = [];
            return this._entries;
          }},
          {add_block}
        }};

        globalThis.document = {{
          querySelector() {{ return null; }},
        }};

        helper.addWiEntry();
        const created = helper.getWIArrayRef()[0];
        if (!created) {{
          throw new Error('expected helper to create one entry');
        }}

        if (Object.prototype.hasOwnProperty.call(created, 'characterFilter')) {{
          throw new Error('expected new entry to omit characterFilter until user edits it');
        }}
        '''
    )

    run_js(script)


def test_normalize_wi_entry_maps_sillytavern_character_book_extensions():
    source = read_project_file('static/js/utils/data.js')
    normalize_block = extract_js_function_block(
        source,
        'export function normalizeWiEntry(entry, index = 0) {',
    ).replace('export ', '', 1)

    script = textwrap.dedent(
        f'''
        {normalize_block}

        const entry = normalizeWiEntry({{
          id: 42,
          keys: ['primary'],
          secondary_keys: ['secondary'],
          enabled: true,
          insertion_order: 7,
          position: 'after_char',
          selective: true,
          extensions: {{
            position: 4,
            role: 2,
            depth: 9,
            display_index: 12,
            exclude_recursion: true,
            prevent_recursion: true,
            delay_until_recursion: 3,
            ignore_budget: true,
            vectorized: true,
            probability: 35,
            useProbability: false,
            selectiveLogic: 3,
            outlet_name: 'memory',
            scan_depth: 6,
            case_sensitive: false,
            match_whole_words: true,
            group: 'lore-group',
            group_override: true,
            group_weight: 77,
            use_group_scoring: false,
            automation_id: 'auto-1',
            sticky: 2,
            cooldown: 5,
            delay: 8,
            triggers: ['normal', 'quiet'],
            match_persona_description: true,
            match_character_description: true,
            match_character_personality: true,
            match_character_depth_prompt: true,
            match_scenario: true,
            match_creator_notes: true,
          }},
        }}, 0);

        const expected = {{
          st_source_id: 42,
          keys: ['primary'],
          secondary_keys: ['secondary'],
          enabled: true,
          insertion_order: 7,
          position: 4,
          role: 2,
          depth: 9,
          displayIndex: 12,
          excludeRecursion: true,
          preventRecursion: true,
          delayUntilRecursion: 3,
          ignoreBudget: true,
          vectorized: true,
          probability: 35,
          useProbability: false,
          selectiveLogic: 3,
          outletName: 'memory',
          scanDepth: 6,
          caseSensitive: false,
          matchWholeWords: true,
          group: 'lore-group',
          groupOverride: true,
          groupWeight: 77,
          useGroupScoring: false,
          automationId: 'auto-1',
          sticky: 2,
          cooldown: 5,
          delay: 8,
          triggers: ['normal', 'quiet'],
          matchPersonaDescription: true,
          matchCharacterDescription: true,
          matchCharacterPersonality: true,
          matchCharacterDepthPrompt: true,
          matchScenario: true,
          matchCreatorNotes: true,
        }};

        for (const [key, value] of Object.entries(expected)) {{
          if (JSON.stringify(entry[key]) !== JSON.stringify(value)) {{
            throw new Error(`expected ${{key}}=${{JSON.stringify(value)}}, got ${{JSON.stringify(entry[key])}}`);
          }}
        }}
        '''
    )

    run_js(script)


def test_get_cleaned_v3_data_serializes_embedded_worldbook_fields_to_sillytavern_extensions():
    source = read_project_file('static/js/utils/data.js').replace('export ', '')

    script = textwrap.dedent(
        f'''
        {source}

        const cleaned = getCleanedV3Data({{
          char_name: 'Hero',
          description: '',
          first_mes: '',
          mes_example: '',
          personality: '',
          scenario: '',
          creator_notes: '',
          system_prompt: '',
          post_history_instructions: '',
          tags: [],
          creator: '',
          character_version: '',
          alternate_greetings: [],
          extensions: {{}},
          character_book: {{
            name: 'Embedded Book',
            entries: [{{
              id: 0,
              st_source_id: 42,
              comment: 'Entry',
              content: 'Content',
              keys: ['primary'],
              secondary_keys: ['secondary'],
              enabled: true,
              constant: true,
              selective: true,
              insertion_order: 7,
              position: 4,
              role: 2,
              depth: 9,
              displayIndex: 12,
              excludeRecursion: true,
              preventRecursion: true,
              delayUntilRecursion: 3,
              ignoreBudget: true,
              vectorized: true,
              probability: 35,
              useProbability: false,
              selectiveLogic: 3,
              outletName: 'memory',
              scanDepth: 6,
              caseSensitive: false,
              matchWholeWords: true,
              group: 'lore-group',
              groupOverride: true,
              groupWeight: 77,
              useGroupScoring: false,
              automationId: 'auto-1',
              sticky: 2,
              cooldown: 5,
              delay: 8,
              triggers: ['normal', 'quiet'],
              matchPersonaDescription: true,
              matchCharacterDescription: true,
              matchCharacterPersonality: true,
              matchCharacterDepthPrompt: true,
              matchScenario: true,
              matchCreatorNotes: true,
              use_regex: true,
            }}],
          }},
        }});

        const entry = cleaned.character_book.entries[0];
        const ext = entry.extensions;

        if (entry.id !== 42) throw new Error(`expected preserved character-book id 42, got ${{entry.id}}`);
        if (entry.position !== 'after_char') throw new Error(`expected after_char position, got ${{entry.position}}`);
        if (JSON.stringify(entry.keys) !== JSON.stringify(['primary'])) throw new Error('expected keys field');
        if (JSON.stringify(entry.secondary_keys) !== JSON.stringify(['secondary'])) throw new Error('expected secondary_keys field');
        if (entry.enabled !== true || entry.constant !== true || entry.selective !== true) {{
          throw new Error('expected top-level character-book booleans to persist');
        }}
        if (entry.insertion_order !== 7) throw new Error(`expected insertion_order 7, got ${{entry.insertion_order}}`);
        if (Object.prototype.hasOwnProperty.call(entry, 'excludeRecursion')) {{
          throw new Error('expected internal camelCase recursion field to be removed');
        }}
        if (Object.prototype.hasOwnProperty.call(entry, 'use_regex')) {{
          throw new Error('expected manager-only use_regex field to be removed');
        }}

        const expectedExt = {{
          position: 4,
          role: 2,
          depth: 9,
          display_index: 12,
          exclude_recursion: true,
          prevent_recursion: true,
          delay_until_recursion: 3,
          ignore_budget: true,
          vectorized: true,
          probability: 35,
          useProbability: false,
          selectiveLogic: 3,
          outlet_name: 'memory',
          scan_depth: 6,
          case_sensitive: false,
          match_whole_words: true,
          group: 'lore-group',
          group_override: true,
          group_weight: 77,
          use_group_scoring: false,
          automation_id: 'auto-1',
          sticky: 2,
          cooldown: 5,
          delay: 8,
          triggers: ['normal', 'quiet'],
          match_persona_description: true,
          match_character_description: true,
          match_character_personality: true,
          match_character_depth_prompt: true,
          match_scenario: true,
          match_creator_notes: true,
        }};

        for (const [key, value] of Object.entries(expectedExt)) {{
          if (JSON.stringify(ext[key]) !== JSON.stringify(value)) {{
            throw new Error(`expected extension ${{key}}=${{JSON.stringify(value)}}, got ${{JSON.stringify(ext[key])}}`);
          }}
        }}
        '''
    )

    run_js(script)


def test_sillytavern_worldbook_defaults_and_explicit_tri_state_false_persist():
    source = read_project_file('static/js/utils/data.js').replace('export ', '')
    helpers_source = read_project_file('static/js/utils/wiHelpers.js')
    add_block = extract_js_function_block(helpers_source, 'addWiEntry() {')

    script = textwrap.dedent(
        f'''
        {source}

        const defaultEntry = normalizeWiEntry({{}}, 0);
        if (defaultEntry.position !== 0) {{
          throw new Error(`expected ST default position 0, got ${{String(defaultEntry.position)}}`);
        }}
        if (defaultEntry.depth !== 4) {{
          throw new Error(`expected ST default depth 4, got ${{String(defaultEntry.depth)}}`);
        }}
        if (defaultEntry.role !== 0) {{
          throw new Error(`expected ST default role 0, got ${{String(defaultEntry.role)}}`);
        }}

        const exported = toStV3Worldbook({{
          name: 'Book',
          entries: [{{
            uid: 99,
            st_source_id: 88,
            displayIndex: 12,
            keys: ['primary'],
            enabled: true,
            caseSensitive: false,
            matchWholeWords: false,
            useGroupScoring: false,
          }}],
        }}, 'Book');
        const exportedEntry = exported.entries['99'];
        if (!exportedEntry) throw new Error('expected export to keep uid as entry key');
        if (exportedEntry.uid !== 99 || exportedEntry.displayIndex !== 12) {{
          throw new Error(`expected uid/displayIndex preservation, got ${{JSON.stringify(exportedEntry)}}`);
        }}
        if (Object.prototype.hasOwnProperty.call(exportedEntry, 'st_source_id')) {{
          throw new Error('expected internal st_source_id to be removed from ST worldbook export');
        }}
        for (const key of ['caseSensitive', 'matchWholeWords', 'useGroupScoring']) {{
          if (exportedEntry[key] !== false) {{
            throw new Error(`expected explicit ${{key}} false to persist, got ${{String(exportedEntry[key])}}`);
          }}
        }}
        '''
    )

    run_js(script)

    script_new_entry = textwrap.dedent(
        f'''
        const helper = {{
          entryUidField: 'st_manager_uid',
          currentWiIndex: -1,
          isEditingClipboard: false,
          $nextTick(fn) {{ fn(); }},
          _generateEntryUid() {{ return 'wi-test'; }},
          getWIArrayRef() {{
            if (!this._entries) this._entries = [];
            return this._entries;
          }},
          {add_block}
        }};

        globalThis.document = {{
          querySelector() {{ return null; }},
        }};

        helper.addWiEntry();
        const created = helper.getWIArrayRef()[0];
        if (created.position !== 0) {{
          throw new Error(`expected new entry ST position 0, got ${{String(created.position)}}`);
        }}
        if (created.role !== 0) {{
          throw new Error(`expected new entry ST role 0, got ${{String(created.role)}}`);
        }}
        if (created.depth !== 4) {{
          throw new Error(`expected new entry ST depth 4, got ${{String(created.depth)}}`);
        }}
        '''
    )

    run_js(script_new_entry)


def test_get_cleaned_v3_data_preserves_raw_sillytavern_character_book_extensions():
    source = read_project_file('static/js/utils/data.js').replace('export ', '')

    script = textwrap.dedent(
        f'''
        {source}

        const cleaned = getCleanedV3Data({{
          char_name: 'Hero',
          extensions: {{}},
          character_book: {{
            name: 'Raw Embedded Book',
            entries: [{{
              id: 5,
              keys: ['primary'],
              secondary_keys: ['secondary'],
              enabled: true,
              insertion_order: 9,
              position: 'after_char',
              extensions: {{
                position: 4,
                role: 2,
                depth: 7,
                exclude_recursion: true,
                prevent_recursion: true,
                case_sensitive: false,
                match_whole_words: true,
                use_group_scoring: false,
              }},
            }}],
          }},
        }});

        const entry = cleaned.character_book.entries[0];
        if (entry.id !== 5) throw new Error(`expected raw id 5, got ${{entry.id}}`);
        if (entry.position !== 'after_char') throw new Error(`expected raw position after_char, got ${{entry.position}}`);
        const ext = entry.extensions;
        const expected = {{
          position: 4,
          role: 2,
          depth: 7,
          exclude_recursion: true,
          prevent_recursion: true,
          case_sensitive: false,
          match_whole_words: true,
          use_group_scoring: false,
        }};
        for (const [key, value] of Object.entries(expected)) {{
          if (JSON.stringify(ext[key]) !== JSON.stringify(value)) {{
            throw new Error(`expected preserved extension ${{key}}=${{JSON.stringify(value)}}, got ${{JSON.stringify(ext[key])}}`);
          }}
        }}
        '''
    )

    run_js(script)
