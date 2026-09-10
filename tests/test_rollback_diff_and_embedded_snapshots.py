import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _make_system_app():
    from core.api.v1 import system as system_api

    app = Flask(__name__)
    app.register_blueprint(system_api.bp)
    return app, system_api


def _configure_system_paths(monkeypatch, system_api, tmp_path):
    cards_root = tmp_path / 'cards'
    cards_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(system_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(system_api, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(system_api, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(
        system_api,
        'load_config',
        lambda: {
            'resources_dir': str(tmp_path / 'resources'),
            'presets_dir': str(tmp_path / 'presets'),
            'world_info_dir': str(tmp_path / 'lorebooks'),
            'chats_dir': str(tmp_path / 'chats'),
        },
    )
    monkeypatch.setattr(system_api, 'schedule_reload', lambda **_: None)
    monkeypatch.setattr(system_api, 'update_card_cache', lambda *args, **kwargs: None)
    return cards_root


def test_embedded_snapshot_keeps_host_card_and_restores_worldbook(monkeypatch, tmp_path):
    app, system_api = _make_system_app()
    cards_root = _configure_system_paths(monkeypatch, system_api, tmp_path)
    card_path = cards_root / 'hero.json'
    card_path.write_text(
        json.dumps(
            {
                'spec': 'chara_card_v3',
                'spec_version': '3.0',
                'data': {
                    'name': 'Hero',
                    'description': 'Host card stays intact',
                    'character_book': {'name': 'Hero WI', 'entries': []},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    book = {
        'name': 'Hero WI',
        'entries': [
            {
                'uid': 'entry-1',
                'key': ['hello'],
                'keysecondary': [],
                'comment': 'Greeting',
                'content': 'Hello from the saved worldbook',
                'disable': False,
                'order': 100,
            }
        ],
    }

    client = app.test_client()
    create_res = client.post(
        '/api/create_snapshot',
        json={
            'id': 'hero.json',
            'type': 'card',
            'content': book,
            'is_embedded_wi_only': True,
            'label': 'embedded-wi',
        },
    )

    assert create_res.status_code == 200
    create_payload = create_res.get_json()
    assert create_payload['success'] is True
    backup_path = Path(create_payload['path'])
    assert backup_path.exists()

    saved = json.loads(backup_path.read_text(encoding='utf-8'))
    assert saved['data']['name'] == 'Hero'
    assert saved['data']['description'] == 'Host card stays intact'
    assert saved['data']['character_book']['entries'][0]['content'] == (
        'Hello from the saved worldbook'
    )

    list_res = client.post(
        '/api/list_backups',
        json={'id': 'hero.json', 'type': 'card'},
    )
    assert list_res.get_json()['success'] is True
    assert len(list_res.get_json()['backups']) == 1

    card_path.write_text(
        json.dumps(
            {
                'spec': 'chara_card_v3',
                'spec_version': '3.0',
                'data': {
                    'name': 'Hero',
                    'description': 'Changed after snapshot',
                    'character_book': {'name': 'Hero WI', 'entries': []},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    legacy_backup = tmp_path / 'legacy-worldbook.json'
    legacy_backup.write_text(json.dumps(book, ensure_ascii=False), encoding='utf-8')
    legacy_restore_res = client.post(
        '/api/restore_backup',
        json={
            'backup_path': str(legacy_backup),
            'target_id': 'hero.json',
            'type': 'card',
            'is_embedded_wi_only': True,
        },
    )
    assert legacy_restore_res.get_json()['success'] is True
    legacy_restored = json.loads(card_path.read_text(encoding='utf-8'))
    assert legacy_restored['data']['description'] == 'Changed after snapshot'
    assert legacy_restored['data']['character_book']['entries'][0]['uid'] == 'entry-1'

    restore_res = client.post(
        '/api/restore_backup',
        json={
            'backup_path': str(backup_path),
            'target_id': 'hero.json',
            'type': 'card',
        },
    )
    assert restore_res.get_json()['success'] is True
    restored = json.loads(card_path.read_text(encoding='utf-8'))
    assert restored['data']['description'] == 'Host card stays intact'
    assert restored['data']['character_book']['entries'][0]['uid'] == 'entry-1'


def test_standalone_worldbook_snapshot_roundtrip_uses_lorebook_backups(monkeypatch, tmp_path):
    app, system_api = _make_system_app()
    _configure_system_paths(monkeypatch, system_api, tmp_path)
    lorebooks_root = tmp_path / 'lorebooks'
    lorebooks_root.mkdir(parents=True, exist_ok=True)
    lorebook_path = lorebooks_root / 'shared.json'
    lorebook_path.write_text(
        json.dumps({'name': 'Shared', 'entries': []}, ensure_ascii=False),
        encoding='utf-8',
    )
    book = {
        'name': 'Shared',
        'entries': [
            {
                'uid': 'shared-1',
                'keys': ['shared'],
                'comment': 'Shared entry',
                'content': 'Shared content',
            }
        ],
    }

    client = app.test_client()
    create_res = client.post(
        '/api/create_snapshot',
        json={
            'id': 'global::shared.json',
            'type': 'lorebook',
            'file_path': str(lorebook_path),
            'content': book,
        },
    )
    assert create_res.get_json()['success'] is True
    backup_path = Path(create_res.get_json()['path'])
    assert backup_path.parent.parent.name == 'lorebooks'

    list_res = client.post(
        '/api/list_backups',
        json={
            'id': 'global::shared.json',
            'type': 'lorebook',
            'file_path': str(lorebook_path),
        },
    )
    assert len(list_res.get_json()['backups']) == 1

    lorebook_path.write_text(
        json.dumps({'name': 'Shared', 'entries': []}, ensure_ascii=False),
        encoding='utf-8',
    )
    restore_res = client.post(
        '/api/restore_backup',
        json={
            'backup_path': str(backup_path),
            'target_id': 'global::shared.json',
            'type': 'lorebook',
            'target_file_path': str(lorebook_path),
        },
    )
    assert restore_res.get_json()['success'] is True
    restored = json.loads(lorebook_path.read_text(encoding='utf-8'))
    assert restored['entries'][0]['content'] == 'Shared content'


def _extract_js_function_block(source, signature):
    start = source.index(signature)
    brace_start = source.index('{', start)
    depth = 1
    index = brace_start + 1
    while depth > 0:
        if source[index] == '{':
            depth += 1
        elif source[index] == '}':
            depth -= 1
        index += 1
    return source[start:index]


def _run_rollback_runtime_check(script_body):
    rollback_source = (ROOT / 'static/js/components/rollbackModal.js').read_text(
        encoding='utf-8'
    )
    rollback_source = re.sub(
        r'import\s+[\s\S]*?from\s+"[^"]+";\s*',
        '',
        rollback_source,
    ).replace(
        'export default function rollbackModal()',
        'function rollbackModal()',
    )
    data_source = (ROOT / 'static/js/utils/data.js').read_text(encoding='utf-8')
    normalize_block = _extract_js_function_block(
        data_source,
        'export function normalizeWiEntry(entry, index = 0)',
    ).replace('export function normalizeWiEntry', 'function normalizeWiEntry', 1)
    node_script = textwrap.dedent(
        f'''
        const normalizeWiEntry = new Function(
          {json.dumps(normalize_block)} + '\\nreturn normalizeWiEntry;'
        )();
        const rollbackFactory = new Function(
          'listBackups', 'restoreBackup', 'readFileContent', 'normalizeCardData',
          'openPath', 'getCardMetadata', 'generateSideBySideDiff',
          'getCleanedV3Data', 'normalizeWiEntry', 'toStV3Worldbook',
          {json.dumps(rollback_source)} + '\\nreturn rollbackModal;'
        );
        const rollbackModal = rollbackFactory(
          () => Promise.resolve({{}}),
          () => Promise.resolve({{}}),
          () => Promise.resolve({{}}),
          () => Promise.resolve({{ success: true, data: {{}} }}),
          () => Promise.resolve({{}}),
          () => Promise.resolve({{ success: true, data: {{}} }}),
          () => ({{ left: '', right: '' }}),
          (value) => value,
          normalizeWiEntry,
          (value) => value,
        );
        const component = rollbackModal();
        {script_body}
        '''
    )
    subprocess.run(
        ['node', '--input-type=module', '-'],
        cwd=ROOT,
        input=node_script,
        check=True,
        text=True,
    )


def test_worldbook_diff_ignores_alias_defaults_but_counts_blank_entry():
    _run_rollback_runtime_check(
        '''
        const oldEntries = [{
          uid: 'entry-1',
          key: ['hero'],
          keysecondary: [],
          comment: 'Greeting',
          content: 'Hello',
          disable: false,
          order: 100,
        }];
        const currentEntries = [{
          st_manager_uid: 'entry-1',
          keys: ['hero'],
          secondary_keys: [],
          comment: 'Greeting',
          content: 'Hello',
          enabled: true,
          insertion_order: 100,
        }, {
          st_manager_uid: 'entry-new',
          keys: [],
          secondary_keys: [],
          comment: '',
          content: '',
          enabled: true,
          insertion_order: 101,
        }];
        const pairs = component._buildLorebookPairs(oldEntries, currentEntries);
        const statuses = pairs.map((pair) => component._getPairMeta(pair).status);
        if (statuses.filter((status) => status === 'same').length !== 1) {
          throw new Error('legacy/editor aliases should match as unchanged');
        }
        if (statuses.filter((status) => status === 'added').length !== 1) {
          throw new Error('one blank entry should count as one addition');
        }
        if (statuses.includes('changed')) {
          throw new Error('adding a blank entry must not change existing entries');
        }
        if (component._extractLorebookEntries({ entries: currentEntries }).length !== 2) {
          throw new Error('book-only snapshots should expose their entries');
        }
        '''
    )


def test_card_diff_defaults_to_fields_and_keeps_raw_mode_available():
    _run_rollback_runtime_check(
        '''
        const left = {
          spec: 'chara_card_v3',
          data: {
            name: 'Hero',
            description: 'Old description',
            tags: ['one'],
            character_book: { name: 'WI', entries: [] },
          },
        };
        const right = {
          spec: 'chara_card_v3',
          data: {
            name: 'Hero',
            description: 'New description',
            tags: ['one'],
            character_book: { name: 'WI', entries: [] },
          },
        };
        const summary = component._summarizeCardDiff(left, right);
        if (summary.changed !== 1 || summary.categories[0].key !== 'description') {
          throw new Error('card diff should isolate the changed business field');
        }
        const rendered = component._renderCardFieldDiff(left, right);
        if (!rendered.html.includes('preset-rollback-field-value-pane') ||
            !rendered.html.includes('description')) {
          throw new Error('card field diff should render labeled old/new values');
        }
        component.rollbackTargetType = 'card';
        component.rollbackTargetId = 'hero.json';
        component.diffRenderMode = 'fields';
        if (!component.diffModeLabel || component.diffModeLabel === 'raw') {
          throw new Error('card rollback should default to field comparison');
        }
        component.setDiffRenderMode('raw');
        if (component.diffRenderMode !== 'raw' || !component.diffModeLabel.includes('JSON')) {
          throw new Error('raw JSON mode should remain available');
        }
        '''
    )


def test_rollback_card_diff_uses_symmetric_direction_icon_and_structured_value_rows():
    template = (ROOT / 'templates' / 'modals' / 'rollback.html').read_text(encoding='utf-8')
    js_source = (ROOT / 'static' / 'js' / 'components' / 'rollbackModal.js').read_text(
        encoding='utf-8'
    )
    css_source = (ROOT / 'static' / 'css' / 'modules' / 'preset-rollback.css').read_text(
        encoding='utf-8'
    )

    assert "icon('arrow-left', 'ui-icon--xs rotate-180')" in template
    assert 'preset-rollback-line-diff-row' in js_source
    assert '.preset-rollback-field-value .preset-rollback-line-diff-row' in css_source
    assert 'align-items: start;' in css_source
    assert 'text-align: left;' in css_source
