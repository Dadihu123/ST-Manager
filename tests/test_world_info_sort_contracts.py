from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]


def run_node_module(script: str) -> None:
    subprocess.run(
        ['node', '--input-type=module', '-e', textwrap.dedent(script)],
        cwd=ROOT,
        check=True,
        text=True,
    )


def test_world_info_sort_matches_sillytavern_priority_and_tie_breakers():
    run_node_module(
        '''
        import { sortWiEntries } from './static/js/utils/wiSort.js';

        const entries = [
          { st_source_id: 9, enabled: true, insertion_order: 10 },
          { st_source_id: 1, constant: true, enabled: true, insertion_order: 1 },
          { st_source_id: 2, enabled: false, insertion_order: 100 },
          { st_source_id: 3, enabled: true, insertion_order: 10 },
        ];
        const result = sortWiEntries(entries, 'priority').map((entry) => entry.st_source_id);
        if (JSON.stringify(result) !== JSON.stringify([1, 3, 9, 2])) {
          throw new Error(`unexpected priority order: ${JSON.stringify(result)}`);
        }
        if (entries[0].st_source_id !== 9) throw new Error('sort must not mutate source array');
        '''
    )


def test_world_info_sort_supports_custom_display_index_and_all_modes():
    run_node_module(
        '''
        import { WI_SORT_OPTIONS, sortWiEntries } from './static/js/utils/wiSort.js';

        const entries = [
          { st_source_id: 9, displayIndex: 2, comment: 'Zulu', content: '12345', depth: 4, probability: 40 },
          { st_source_id: 1, displayIndex: 0, comment: 'Alpha', content: '1', depth: 1, probability: 90 },
          { st_source_id: 2, displayIndex: 1, comment: 'Beta', content: '123', depth: 2, probability: 10 },
        ];
        const custom = sortWiEntries(entries, 'custom').map((entry) => entry.st_source_id);
        if (JSON.stringify(custom) !== JSON.stringify([1, 2, 9])) throw new Error('custom order mismatch');
        for (const option of WI_SORT_OPTIONS) {
          const sorted = sortWiEntries(entries, option.value);
          if (sorted.length !== entries.length) throw new Error(`mode failed: ${option.value}`);
        }
        '''
    )


def test_custom_clipboard_paste_uses_visible_order_and_keeps_source_uids_unique():
    run_node_module(
        '''
        import wiEditor from './static/js/components/wiEditor.js';

        globalThis.window = { localStorage: { getItem: () => null, setItem() {} } };
        globalThis.document = { querySelectorAll: () => [] };

        const component = wiEditor();
        component.editingData = { character_book: { entries: [
          { st_manager_uid: 'a', st_source_id: 1, displayIndex: 20 },
          { st_manager_uid: 'b', st_source_id: 2, displayIndex: 10 },
          { st_manager_uid: 'c', st_source_id: 3, displayIndex: 30 },
        ] } };
        component.wiSortMode = 'custom';
        component.currentWiEntryKey = 'manager:b';
        component.currentWiIndex = 1;
        component._generateEntryUid = () => 'new';
        component.$nextTick = (fn) => fn();

        component.addWiEntryFromClipboard({ comment: 'new', content: '' });

        const ordered = component.getSortedWIEntries().map((entry) => entry.st_manager_uid);
        if (JSON.stringify(ordered) !== JSON.stringify(['b', 'new', 'a', 'c'])) {
          throw new Error(`unexpected custom paste order: ${JSON.stringify(ordered)}`);
        }
        const entries = component.getWIArrayRef();
        if (new Set(entries.map((entry) => entry.st_source_id)).size !== entries.length) {
          throw new Error('custom paste reused a source UID');
        }
        if (entries.find((entry) => entry.st_manager_uid === 'new').displayIndex !== 11) {
          throw new Error('custom paste did not persist the visible insertion index');
        }
        '''
    )


def test_world_info_export_preserves_uid_and_display_index_contract():
    source = (ROOT / 'core/api/v1/world_info.py').read_text(encoding='utf-8')
    assert "uid = entry.get('uid')" in source
    assert "display_index = entry.get('displayIndex')" in source
    assert "export_entries[str(uid)] = final_entry" in source


def test_world_info_templates_keep_sort_controls_out_of_fixed_card_detail_view():
    fullscreen = (ROOT / 'templates/modals/detail_wi_fullscreen.html').read_text(encoding='utf-8')
    popup = (ROOT / 'templates/modals/detail_wi_popup.html').read_text(encoding='utf-8')
    card = (ROOT / 'templates/modals/detail_card.html').read_text(encoding='utf-8')
    css = (ROOT / 'static/css/modules/view-wi.css').read_text(encoding='utf-8')

    for template in (fullscreen, popup):
        assert 'wiSortMode' in template
        assert 'setWiSortMode($event.target.value)' in template or 'setWiSortMode(option.value)' in template
    assert 'wi-sort-menu' in fullscreen
    assert 'wi-sort-menu' in popup
    assert 'getSortedWIEntries()' in fullscreen
    assert 'getDefaultSortedWIEntries()' in card
    assert 'wiSortMode' not in card
    assert '.wi-sort-menu' in css
    assert '.wi-sort-control select option' in css
    assert 'background-color: var(--bg-body)' in css
    assert 'background-color: var(--bg-panel)' in css
    assert 'color: var(--text-main)' in css
