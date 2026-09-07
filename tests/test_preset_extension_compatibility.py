import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import presets as presets_api
from core.services.preset_extensions import extract_regex_script_items
from core.services.preset_extensions import extract_tavern_helper_scripts
from core.services.preset_extensions import normalize_extensions_for_save


@pytest.mark.parametrize(
    ('extensions', 'expected_name'),
    [
        ({'tavern_helper': {'scripts': [{'name': 'object'}]}}, 'object'),
        (
            {'tavern_helper': [['scripts', [{'name': 'list'}]], ['variables', {'enabled': True}]]},
            'list',
        ),
        ({'TavernHelper_scripts': [{'type': 'script', 'value': {'name': 'legacy'}}]}, 'legacy'),
    ],
)
def test_preset_extension_helper_reads_all_tavern_helper_shapes(extensions, expected_name):
    scripts = extract_tavern_helper_scripts(extensions)

    assert [script['name'] for script in scripts] == [expected_name]


def test_preset_extension_helper_normalizes_legacy_shape_and_preserves_other_keys():
    normalized = normalize_extensions_for_save(
        {
            'TavernHelper_scripts': [
                {'type': 'script', 'value': {'name': 'legacy', 'content': 'run()'}},
            ],
            'memory': {'enabled': True},
        }
    )

    assert normalized['tavern_helper']['scripts'] == [
        {'name': 'legacy', 'content': 'run()'},
    ]
    assert normalized['tavern_helper']['variables'] == {}
    assert 'TavernHelper_scripts' not in normalized
    assert normalized['memory'] == {'enabled': True}


def test_preset_extension_helper_reads_regex_binding_shape():
    scripts = extract_regex_script_items(
        {'RegexBinding': {'regexes': [{'findRegex': 'foo'}]}}
    )

    assert len(scripts) == 1
    assert scripts[0]['findRegex'] == 'foo'


def test_preset_compatibility_utility_matches_backend_shape_matrix():
    utility_path = ROOT / 'static/js/utils/extensionCompatibility.js'
    node_script = textwrap.dedent(
        """
        import { readFileSync } from 'node:fs';
        const source = readFileSync(__SOURCE_PATH__, 'utf8');
        const module = await import(
          'data:text/javascript,' + encodeURIComponent(source),
        );

        const cases = [
          { tavern_helper: { scripts: [{ name: 'object' }] } },
          { tavern_helper: [['scripts', [{ name: 'list' }]], ['variables', { enabled: true }]] },
          { TavernHelper_scripts: [{ type: 'script', value: { name: 'legacy' } }] },
        ];

        for (const extensions of cases) {
          const summary = module.getPresetExtensionSummary(extensions);
          if (summary.script_count !== 1 || summary.other_count !== 0) {
            throw new Error(`unexpected summary: ${JSON.stringify(summary)}`);
          }

          const editor = module.normalizePresetExtensionsForEditor(extensions);
          if (module.extractPresetTavernScripts(editor).length !== 1) {
            throw new Error(`editor normalization lost scripts: ${JSON.stringify(editor)}`);
          }

          const saved = module.normalizePresetExtensionsForSave(extensions);
          if (saved.tavern_helper.scripts.length !== 1 || saved.TavernHelper_scripts) {
            throw new Error(`save normalization failed: ${JSON.stringify(saved)}`);
          }
        }
        """
    ).replace('__SOURCE_PATH__', json.dumps(str(utility_path)))

    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.parametrize(
    'helper_payload',
    [
        {'tavern_helper': {'scripts': [{'name': 'object'}]}},
        {'tavern_helper': [['scripts', [{'name': 'list'}]], ['variables', {}]]},
        {'TavernHelper_scripts': [{'type': 'script', 'value': {'name': 'legacy'}}]},
    ],
)
def test_preset_detail_and_list_share_extension_counts_and_hide_managed_items(
    monkeypatch, tmp_path, helper_payload
):
    presets_dir = tmp_path / 'presets'
    preset_path = presets_dir / 'compat.json'
    preset_path.parent.mkdir(parents=True, exist_ok=True)
    preset_path.write_text(
        json.dumps(
            {
                'name': 'Compat',
                'temperature': 0.8,
                'extensions': {
                    'regex_scripts': [{'findRegex': 'foo'}],
                    **helper_payload,
                    'memory': {'enabled': True},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {
            'presets_dir': str(presets_dir),
            'resources_dir': str(tmp_path / 'resources'),
        },
    )
    monkeypatch.setattr(presets_api, 'load_ui_data', lambda: {})

    app = Flask(__name__)
    app.register_blueprint(presets_api.bp)
    client = app.test_client()

    list_payload = client.get('/api/presets/list?filter_type=global').get_json()
    assert list_payload['items'][0]['regex_count'] == 1
    assert list_payload['items'][0]['script_count'] == 1

    detail = client.get('/api/presets/detail/global::compat.json').get_json()['preset']
    extension_items = [
        item for item in detail['reader_view']['items'] if item.get('group') == 'extensions'
    ]
    assert [item['title'] for item in extension_items] == ['memory']


def test_save_preset_extensions_canonicalizes_old_helper_and_keeps_unrelated_extension(
    monkeypatch, tmp_path
):
    presets_dir = tmp_path / 'presets'
    preset_path = presets_dir / 'compat.json'
    preset_path.parent.mkdir(parents=True, exist_ok=True)
    preset_path.write_text(
        json.dumps(
            {
                'name': 'Compat',
                'extensions': {
                    'TavernHelper_scripts': [
                        {'type': 'script', 'value': {'name': 'legacy'}},
                    ],
                    'memory': {'enabled': True},
                },
            },
            ensure_ascii=False,
        ),
        encoding='utf-8',
    )

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {
            'presets_dir': str(presets_dir),
            'resources_dir': str(tmp_path / 'resources'),
        },
    )

    app = Flask(__name__)
    app.register_blueprint(presets_api.bp)
    client = app.test_client()
    response = client.post(
        '/api/presets/save-extensions',
        json={
            'id': 'global::compat.json',
            'extensions': {
                'TavernHelper_scripts': [
                    {'type': 'script', 'value': {'name': 'legacy-updated'}},
                ],
                'memory': {'enabled': False},
            },
        },
    )

    assert response.status_code == 200
    saved = json.loads(preset_path.read_text(encoding='utf-8'))['extensions']
    assert saved['tavern_helper']['scripts'] == [{'name': 'legacy-updated'}]
    assert 'TavernHelper_scripts' not in saved
    assert saved['memory'] == {'enabled': False}
