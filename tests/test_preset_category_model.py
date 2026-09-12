import json
import sys
from io import BytesIO
from pathlib import Path

from flask import Flask


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import presets as presets_api
from core.data import ui_store as ui_store_module


def _make_test_app():
    app = Flask(__name__)
    app.register_blueprint(presets_api.bp)
    return app


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _write_versioned_global_family(presets_dir: Path, family_id: str, versions: list[dict]):
    for version in versions:
        meta = {
            'preset_family_id': family_id,
            'preset_family_name': version.get('family_name') or 'Companion Family',
            'preset_version_label': version['label'],
            'preset_version_order': version['order'],
            'preset_is_default_version': bool(version.get('is_default', False)),
        }
        _write_json(
            presets_dir / version['category'] / version['filename'],
            {
                'name': version['name'],
                'description': version.get('description', ''),
                'x_st_manager': meta,
                **(version.get('content') or {}),
            },
        )


class _FakeCache:
    def __init__(self, cards):
        self.cards = list(cards)


def _make_card(card_id, category, *, char_name='Lucy'):
    return {
        'id': card_id,
        'category': category,
        'char_name': char_name,
        'filename': card_id.split('/')[-1],
    }


def _setup_preset_env(monkeypatch, tmp_path, *, cards=None, ui_payload=None):
    presets_dir = tmp_path / 'presets'
    resources_dir = tmp_path / 'resources'
    ui_path = tmp_path / 'ui_data.json'
    ui_path.write_text(json.dumps(ui_payload or {}, ensure_ascii=False), encoding='utf-8')

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(resources_dir)},
    )
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    monkeypatch.setattr(presets_api, 'load_ui_data', lambda: ui_payload or {}, raising=False)
    monkeypatch.setattr(presets_api, 'get_resource_item_categories', ui_store_module.get_resource_item_categories, raising=False)
    monkeypatch.setattr(
        presets_api,
        '_get_cards_by_resource_folder',
        lambda: {
            str((ui_payload or {}).get(card.get('id'), {}).get('resource_folder') or ''): card
            for card in (cards or [])
            if (ui_payload or {}).get(card.get('id'), {}).get('resource_folder')
        },
        raising=False,
    )

    return presets_dir, resources_dir


def test_list_presets_returns_relative_path_ids_for_global_nested_files(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    _write_json(
        presets_dir / '写作' / '长文' / 'companion.json',
        {'name': 'Companion', 'description': 'Long-form writing helper'},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=global')

    assert res.status_code == 200
    payload = res.get_json()
    assert len(payload['items']) == 1
    item = payload['items'][0]
    assert item['id'] == 'global::写作/长文/companion.json'
    assert item['display_category'] == '写作/长文'
    assert item['category_mode'] == 'physical'


def test_list_presets_paginates_filtered_items(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    for index in range(3):
        _write_json(
            presets_dir / f'item-{index}.json',
            {'name': f'Item {index}', 'description': 'needle'},
        )

    client = _make_test_app().test_client()
    res = client.get(
        '/api/presets/list?filter_type=global&search=needle&page=2&page_size=2'
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['total'] == 3
    assert payload['count'] == 3
    assert payload['page'] == 2
    assert payload['page_size'] == 2
    assert payload['total_pages'] == 2
    assert len(payload['items']) == 1


def test_list_presets_returns_display_category_for_global_and_resource_items(monkeypatch, tmp_path):
    presets_dir, resources_dir = _setup_preset_env(
        monkeypatch,
        tmp_path,
        cards=[_make_card('cards/lucy.png', '角色分类')],
        ui_payload={'cards/lucy.png': {'resource_folder': 'lucy'}},
    )
    _write_json(presets_dir / '写作' / '长文' / 'companion.json', {'name': 'Companion'})
    _write_json(resources_dir / 'lucy' / 'presets' / 'scene.json', {'name': 'Scene Preset'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=all')

    assert res.status_code == 200
    payload = res.get_json()
    items = {item['type']: item for item in payload['items']}
    assert items['global']['display_category'] == '写作/长文'
    assert items['global']['category_mode'] == 'physical'
    assert items['resource']['display_category'] == '角色分类'
    assert items['resource']['category_mode'] == 'inherited'


def test_list_presets_applies_resource_override_category(monkeypatch, tmp_path):
    resource_file = tmp_path / 'resources' / 'lucy' / 'presets' / 'companion.json'
    path_key = ui_store_module._normalize_resource_item_category_path(str(resource_file).replace('\\', '/'))
    _, resources_dir = _setup_preset_env(
        monkeypatch,
        tmp_path,
        cards=[_make_card('cards/lucy.png', '原始分类')],
        ui_payload={
            'cards/lucy.png': {'resource_folder': 'lucy'},
            '_resource_item_categories_v1': {
                'presets': {
                    path_key: {
                        'category': '角色专属',
                        'updated_at': 100,
                    }
                }
            },
        },
    )
    _write_json(resource_file, {'name': 'Companion'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=resource')

    assert res.status_code == 200
    payload = res.get_json()
    assert len(payload['items']) == 1
    resource_item = payload['items'][0]
    assert resource_item['display_category'] == '角色专属'
    assert resource_item['category_mode'] == 'override'


def test_list_presets_applies_resource_override_category_with_path_case_mismatch(monkeypatch, tmp_path):
    resource_file = tmp_path / 'resources' / 'lucy' / 'presets' / 'companion.json'
    mixed_case_key = ui_store_module._normalize_resource_item_category_path(
        str(resource_file).replace('resources', 'RESOURCES').replace('lucy', 'LUCY').replace('\\', '/')
    )
    _, _resources_dir = _setup_preset_env(
        monkeypatch,
        tmp_path,
        cards=[_make_card('cards/lucy.png', '原始分类')],
        ui_payload={
            'cards/lucy.png': {'resource_folder': 'lucy'},
            '_resource_item_categories_v1': {
                'presets': {
                    mixed_case_key: {
                        'category': '角色专属',
                        'updated_at': 100,
                    }
                }
            },
        },
    )
    _write_json(resource_file, {'name': 'Companion'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=resource')

    assert res.status_code == 200
    payload = res.get_json()
    assert len(payload['items']) == 1
    resource_item = payload['items'][0]
    assert resource_item['display_category'] == '角色专属'
    assert resource_item['category_mode'] == 'override'


def test_list_presets_filters_by_display_category(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    _write_json(presets_dir / '写作' / '长文' / 'companion.json', {'name': 'Companion'})
    _write_json(presets_dir / '工具' / 'quick.json', {'name': 'Quick Tool'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=global&category=写作')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['name'] for item in payload['items']] == ['Companion']


def test_preset_override_category_stays_pinned_when_owner_card_category_changes(monkeypatch, tmp_path):
    resource_file = tmp_path / 'resources' / 'lucy' / 'presets' / 'companion.json'
    path_key = ui_store_module._normalize_resource_item_category_path(str(resource_file).replace('\\', '/'))
    _, resources_dir = _setup_preset_env(
        monkeypatch,
        tmp_path,
        cards=[_make_card('cards/lucy.png', '迁移后分类')],
        ui_payload={
            'cards/lucy.png': {'resource_folder': 'lucy'},
            '_resource_item_categories_v1': {
                'presets': {
                    path_key: {
                        'category': '角色专属',
                        'updated_at': 100,
                    }
                }
            },
        },
    )
    _write_json(resource_file, {'name': 'Companion'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=resource')

    assert res.status_code == 200
    payload = res.get_json()
    assert len(payload['items']) == 1
    resource_item = payload['items'][0]
    assert resource_item['display_category'] == '角色专属'
    assert resource_item['category_mode'] == 'override'


def test_preset_same_name_different_global_folders_do_not_conflict(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    _write_json(presets_dir / '写作' / 'companion.json', {'name': 'Companion A'})
    _write_json(presets_dir / '战斗' / 'companion.json', {'name': 'Companion B'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=global')

    assert res.status_code == 200
    payload = res.get_json()
    items = payload['items']
    assert len(items) == 2
    assert {item['id'] for item in items} == {
        'global::写作/companion.json',
        'global::战斗/companion.json',
    }


def test_list_presets_includes_openai_alternate_root_files_in_global_results(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    openai_dir = tmp_path / 'st-openai-presets'
    presets_dir.mkdir(parents=True, exist_ok=True)
    openai_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {
            'presets_dir': str(presets_dir),
            'resources_dir': str(tmp_path / 'resources'),
            'st_openai_preset_dir': str(openai_dir),
        },
    )
    monkeypatch.setattr(presets_api, 'load_ui_data', lambda: {}, raising=False)
    monkeypatch.setattr(presets_api, 'get_resource_item_categories', ui_store_module.get_resource_item_categories, raising=False)
    monkeypatch.setattr(presets_api, '_get_cards_by_resource_folder', lambda: {}, raising=False)

    _write_json(openai_dir / 'OpenAI' / 'chat.json', {'name': 'Chat Preset', 'openai_model': 'gpt-4.1'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=global')

    assert res.status_code == 200
    payload = res.get_json()
    assert len(payload['items']) == 1
    item = payload['items'][0]
    assert item['id'] == 'global-alt::st_openai_preset_dir::OpenAI/chat.json'
    assert item['type'] == 'global'
    assert item['source_type'] == 'global'
    assert item['source_folder'] == 'st_openai_preset_dir'
    assert item['display_category'] == 'OpenAI'
    assert item['physical_category'] == 'OpenAI'


def test_list_presets_deduplicates_overlapping_openai_alternate_root_files(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    openai_dir = presets_dir / 'OpenAI'
    openai_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(
        presets_api,
        'load_config',
        lambda: {
            'presets_dir': str(presets_dir),
            'resources_dir': str(tmp_path / 'resources'),
            'st_openai_preset_dir': str(openai_dir),
        },
    )
    monkeypatch.setattr(presets_api, 'load_ui_data', lambda: {}, raising=False)
    monkeypatch.setattr(presets_api, 'get_resource_item_categories', ui_store_module.get_resource_item_categories, raising=False)
    monkeypatch.setattr(presets_api, '_get_cards_by_resource_folder', lambda: {}, raising=False)

    _write_json(openai_dir / 'chat.json', {'name': 'Chat Preset', 'openai_model': 'gpt-4.1'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=global')

    assert res.status_code == 200
    payload = res.get_json()
    assert len(payload['items']) == 1
    assert payload['items'][0]['id'] == 'global::OpenAI/chat.json'


def test_list_presets_returns_folder_capabilities(monkeypatch, tmp_path):
    presets_dir, resources_dir = _setup_preset_env(
        monkeypatch,
        tmp_path,
        cards=[_make_card('cards/lucy.png', '写作')],
        ui_payload={'cards/lucy.png': {'resource_folder': 'lucy'}},
    )
    _write_json(presets_dir / '写作' / '长文' / 'companion.json', {'name': 'Companion'})
    _write_json(resources_dir / 'lucy' / 'presets' / 'scene.json', {'name': 'Scene Preset'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=all')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['folder_capabilities']['写作']['has_physical_folder'] is True
    assert payload['folder_capabilities']['写作']['has_virtual_items'] is True


def test_list_presets_folder_metadata_ignores_category_filter_narrowing(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    _write_json(presets_dir / '写作' / '长文' / 'companion.json', {'name': 'Companion'})
    _write_json(presets_dir / '工具' / 'quick.json', {'name': 'Quick Tool'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=global&category=写作')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['name'] for item in payload['items']] == ['Companion']
    assert payload['all_folders'] == ['写作', '写作/长文', '工具']
    assert payload['category_counts']['写作'] == 1
    assert payload['category_counts']['工具'] == 1
    assert payload['folder_capabilities']['工具']['has_physical_folder'] is True


def test_list_presets_folder_metadata_ignores_search_narrowing(monkeypatch, tmp_path):
    presets_dir, resources_dir = _setup_preset_env(
        monkeypatch,
        tmp_path,
        cards=[_make_card('cards/lucy.png', '角色分类')],
        ui_payload={'cards/lucy.png': {'resource_folder': 'lucy'}},
    )
    _write_json(presets_dir / '写作' / '长文' / 'companion.json', {'name': 'Companion'})
    _write_json(resources_dir / 'lucy' / 'presets' / 'search-hit.json', {'name': 'Needle Preset'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=all&search=needle')

    assert res.status_code == 200
    payload = res.get_json()
    assert [item['name'] for item in payload['items']] == ['Needle Preset']
    assert payload['all_folders'] == ['写作', '写作/长文', '角色分类']
    assert payload['category_counts']['写作'] == 1
    assert payload['category_counts']['角色分类'] == 1
    assert payload['folder_capabilities']['写作']['has_physical_folder'] is True
    assert payload['folder_capabilities']['角色分类']['has_virtual_items'] is True


def test_list_presets_groups_versioned_global_files_into_family_entry(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    family_meta = {
        'x_st_manager': {
            'preset_family_id': 'family-alpha',
            'preset_family_name': 'Companion Family',
            'preset_version_order': 10,
        }
    }
    _write_json(
        presets_dir / '写作' / 'companion-v1.json',
        {
            'name': 'Companion V1',
            'description': 'Legacy baseline',
            **family_meta,
            'x_st_manager': {
                **family_meta['x_st_manager'],
                'preset_version_label': 'v1',
                'preset_is_default_version': True,
            },
        },
    )
    _write_json(
        presets_dir / '写作' / 'companion-v2.json',
        {
            'name': 'Companion V2',
            'description': 'Upgraded variant',
            **family_meta,
            'x_st_manager': {
                **family_meta['x_st_manager'],
                'preset_version_label': 'v2',
                'preset_version_order': 20,
            },
        },
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=global&search=v2')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['count'] == 1
    assert payload['all_folders'] == ['写作']

    item = payload['items'][0]
    assert item['entry_type'] == 'family'
    assert item['id'] == 'global::global::family-alpha'
    assert item['family_id'] == 'family-alpha'
    assert item['family_name'] == 'Companion Family'
    assert item['name'] == 'Companion Family'
    assert item['default_version_id'] == 'global::写作/companion-v1.json'
    assert item['default_version_label'] == 'v1'
    assert item['version_count'] == 2
    assert [version['preset_version']['version_label'] for version in item['versions']] == ['v1', 'v2']
    assert {version['id'] for version in item['versions']} == {
        'global::写作/companion-v1.json',
        'global::写作/companion-v2.json',
    }


def test_list_presets_does_not_group_same_family_id_across_global_and_resource_sources(monkeypatch, tmp_path):
    presets_dir, resources_dir = _setup_preset_env(
        monkeypatch,
        tmp_path,
        cards=[_make_card('cards/lucy.png', '角色分类')],
        ui_payload={'cards/lucy.png': {'resource_folder': 'lucy'}},
    )
    version_meta = {
        'x_st_manager': {
            'preset_family_id': 'shared-family',
            'preset_family_name': 'Shared Family',
            'preset_version_label': 'v1',
            'preset_version_order': 10,
            'preset_is_default_version': True,
        }
    }
    _write_json(presets_dir / '写作' / 'companion.json', {'name': 'Global Companion', **version_meta})
    _write_json(
        resources_dir / 'lucy' / 'presets' / 'companion.json',
        {'name': 'Resource Companion', **version_meta},
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=all&search=shared')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['count'] == 2
    family_ids = {item['id'] for item in payload['items']}
    assert family_ids == {
        'global::global::shared-family',
        'resource::resource::lucy::shared-family',
    }
    assert {item['entry_type'] for item in payload['items']} == {'family'}


def test_list_presets_keeps_versioned_family_visible_under_category_filter(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    family_meta = {
        'x_st_manager': {
            'preset_family_id': 'family-category',
            'preset_family_name': 'Writing Family',
            'preset_version_label': 'v1',
            'preset_version_order': 10,
            'preset_is_default_version': True,
        }
    }
    _write_json(presets_dir / '写作' / 'family-v1.json', {'name': 'Writing V1', **family_meta})
    _write_json(
        presets_dir / '写作' / 'family-v2.json',
        {
            'name': 'Writing V2',
            'x_st_manager': {
                **family_meta['x_st_manager'],
                'preset_version_label': 'v2',
                'preset_version_order': 20,
                'preset_is_default_version': False,
            },
        },
    )

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=global&category=写作')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['count'] == 1
    assert payload['items'][0]['entry_type'] == 'family'
    assert payload['items'][0]['id'] == 'global::global::family-category'
    assert payload['items'][0]['display_category'] == '写作'


def test_list_presets_keeps_mixed_category_family_visible_under_each_category_filter(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    family_meta = {
        'x_st_manager': {
            'preset_family_id': 'family-mixed-category',
            'preset_family_name': 'Mixed Category Family',
            'preset_version_label': 'v1',
            'preset_version_order': 10,
            'preset_is_default_version': True,
        }
    }
    _write_json(presets_dir / '写作' / 'family-v1.json', {'name': 'Writing V1', **family_meta})
    _write_json(
        presets_dir / '工具' / 'family-v2.json',
        {
            'name': 'Tooling V2',
            'x_st_manager': {
                **family_meta['x_st_manager'],
                'preset_version_label': 'v2',
                'preset_version_order': 20,
                'preset_is_default_version': False,
            },
        },
    )

    client = _make_test_app().test_client()
    writing_res = client.get('/api/presets/list?filter_type=global&category=写作')
    tooling_res = client.get('/api/presets/list?filter_type=global&category=工具')

    assert writing_res.status_code == 200
    assert tooling_res.status_code == 200

    writing_payload = writing_res.get_json()
    tooling_payload = tooling_res.get_json()

    assert writing_payload['count'] == 1
    assert tooling_payload['count'] == 1
    assert writing_payload['items'][0]['id'] == 'global::global::family-mixed-category'
    assert tooling_payload['items'][0]['id'] == 'global::global::family-mixed-category'


def test_preset_detail_accepts_relative_path_global_id(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    _write_json(presets_dir / '写作' / '长文' / 'companion.json', {'name': 'Companion'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/global::写作/长文/companion.json')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['preset']['id'] == 'global::写作/长文/companion.json'
    assert payload['preset']['name'] == 'Companion'


def test_preset_detail_returns_source_aware_resource_id(monkeypatch, tmp_path):
    _presets_dir, resources_dir = _setup_preset_env(monkeypatch, tmp_path)
    _write_json(resources_dir / 'lucy' / 'presets' / 'companion.json', {'name': 'Companion'})

    client = _make_test_app().test_client()
    res = client.get('/api/presets/detail/resource::lucy::companion')

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert payload['preset']['id'] == 'resource::lucy::companion'


def test_export_preset_returns_attachment_for_global_id(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    _write_json(
        presets_dir / '写作' / '长文' / 'companion.json',
        {'name': 'Companion', 'temperature': 0.7},
    )

    client = _make_test_app().test_client()
    res = client.post('/api/presets/export', json={'id': 'global::写作/长文/companion.json'})

    assert res.status_code == 200
    assert 'application/json' in res.headers['Content-Type']
    assert 'attachment' in res.headers['Content-Disposition']
    assert 'companion.json' in res.headers['Content-Disposition']

    payload = json.loads(res.data.decode('utf-8'))
    assert payload['name'] == 'Companion'
    assert payload['temperature'] == 0.7


def test_export_preset_returns_attachment_for_resource_id(monkeypatch, tmp_path):
    _, resources_dir = _setup_preset_env(
        monkeypatch,
        tmp_path,
        cards=[_make_card('cards/lucy.png', '角色分类')],
        ui_payload={'cards/lucy.png': {'resource_folder': 'lucy'}},
    )
    _write_json(resources_dir / 'lucy' / 'presets' / 'scene.json', {'name': 'Scene Preset', 'top_p': 0.9})

    client = _make_test_app().test_client()
    res = client.post('/api/presets/export', json={'id': 'resource::lucy::scene'})

    assert res.status_code == 200
    assert 'application/json' in res.headers['Content-Type']
    assert 'attachment' in res.headers['Content-Disposition']
    assert 'scene.json' in res.headers['Content-Disposition']

    payload = json.loads(res.data.decode('utf-8'))
    assert payload['name'] == 'Scene Preset'
    assert payload['top_p'] == 0.9


def test_export_preset_supports_grouped_family_item_via_concrete_version_id(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    _write_versioned_global_family(
        presets_dir,
        'family-export',
        [
            {
                'category': '写作',
                'filename': 'companion-v1.json',
                'name': 'Companion V1',
                'label': 'v1',
                'order': 10,
                'is_default': True,
                'content': {'temperature': 0.7},
            },
            {
                'category': '写作',
                'filename': 'companion-v2.json',
                'name': 'Companion V2',
                'label': 'v2',
                'order': 20,
                'content': {'temperature': 0.9},
            },
        ],
    )

    client = _make_test_app().test_client()
    list_res = client.get('/api/presets/list?filter_type=global')

    assert list_res.status_code == 200
    payload = list_res.get_json()
    assert payload['count'] == 1
    family_item = payload['items'][0]
    assert family_item['entry_type'] == 'family'
    assert family_item['id'] == 'global::global::family-export'

    export_res = client.post('/api/presets/export', json={'id': family_item['default_version_id']})

    assert export_res.status_code == 200
    assert 'application/json' in export_res.headers['Content-Type']
    assert 'attachment' in export_res.headers['Content-Disposition']
    assert 'companion-v1.json' in export_res.headers['Content-Disposition']

    payload = json.loads(export_res.data.decode('utf-8'))
    assert payload['name'] == 'Companion V1'
    assert payload['temperature'] == 0.7
    assert payload['x_st_manager']['preset_family_id'] == 'family-export'


def test_export_preset_rejects_invalid_id(monkeypatch, tmp_path):
    _setup_preset_env(monkeypatch, tmp_path)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/export', json={'id': 'bad::format'})

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['msg'] == 'Invalid preset ID'


def test_delete_preset_uses_relative_path_global_id(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    preset_path = presets_dir / '写作' / '长文' / 'companion.json'
    _write_json(preset_path, {'name': 'Companion'})

    client = _make_test_app().test_client()
    res = client.post('/api/presets/delete', json={'id': 'global::写作/长文/companion.json'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert preset_path.exists() is False


def test_delete_preset_supports_grouped_family_item_via_legacy_route_and_promotes_next_default(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    default_path = presets_dir / '写作' / 'companion-v1.json'
    sibling_path = presets_dir / '写作' / 'companion-v2.json'
    _write_versioned_global_family(
        presets_dir,
        'family-delete',
        [
            {
                'category': '写作',
                'filename': default_path.name,
                'name': 'Companion V1',
                'label': 'v1',
                'order': 10,
                'is_default': True,
            },
            {
                'category': '写作',
                'filename': sibling_path.name,
                'name': 'Companion V2',
                'label': 'v2',
                'order': 20,
            },
        ],
    )

    client = _make_test_app().test_client()
    list_res = client.get('/api/presets/list?filter_type=global')

    assert list_res.status_code == 200
    payload = list_res.get_json()
    assert payload['count'] == 1
    family_item = payload['items'][0]
    assert family_item['entry_type'] == 'family'
    assert family_item['default_version_id'] == 'global::写作/companion-v1.json'

    delete_res = client.post('/api/presets/delete', json={'id': family_item['default_version_id']})

    assert delete_res.status_code == 200
    assert delete_res.get_json()['success'] is True
    assert default_path.exists() is False
    assert sibling_path.exists() is True

    sibling_payload = json.loads(sibling_path.read_text(encoding='utf-8'))
    assert sibling_payload['x_st_manager']['preset_is_default_version'] is True

    refreshed_list_res = client.get('/api/presets/list?filter_type=global')

    assert refreshed_list_res.status_code == 200
    refreshed_payload = refreshed_list_res.get_json()
    assert refreshed_payload['count'] == 1
    refreshed_family = refreshed_payload['items'][0]
    assert refreshed_family['default_version_id'] == 'global::写作/companion-v2.json'
    assert refreshed_family['version_count'] == 1


def test_save_preset_uses_relative_path_global_id(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    preset_path = presets_dir / '写作' / '长文' / 'companion.json'
    _write_json(preset_path, {'name': 'Old Name'})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/save',
        json={
            'id': 'global::写作/长文/companion.json',
            'content': {'name': 'New Name'},
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert json.loads(preset_path.read_text(encoding='utf-8'))['name'] == 'New Name'


def test_save_preset_rejects_invalid_json_string_content(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    preset_path = presets_dir / '写作' / '长文' / 'companion.json'
    _write_json(preset_path, {'name': 'Old Name'})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/save',
        json={
            'id': 'global::写作/长文/companion.json',
            'content': '{bad json',
        },
    )

    assert res.status_code == 400
    payload = res.get_json()
    assert payload['success'] is False
    assert json.loads(preset_path.read_text(encoding='utf-8'))['name'] == 'Old Name'


def test_save_preset_allows_falsey_but_present_content(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    preset_path = presets_dir / '写作' / '长文' / 'companion.json'
    _write_json(preset_path, {'name': 'Old Name'})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/save',
        json={
            'id': 'global::写作/长文/companion.json',
            'content': {},
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert json.loads(preset_path.read_text(encoding='utf-8')) == {}


def test_save_preset_extensions_uses_relative_path_global_id(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    preset_path = presets_dir / '写作' / '长文' / 'companion.json'
    _write_json(preset_path, {'name': 'Companion', 'extensions': {}})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/save-extensions',
        json={
            'id': 'global::写作/长文/companion.json',
            'extensions': {'regex_scripts': ['one']},
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    saved = json.loads(preset_path.read_text(encoding='utf-8'))
    assert saved['extensions']['regex_scripts'] == ['one']


def test_move_preset_global_item_moves_file_to_target_category(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    source_path = presets_dir / '写作' / 'companion.json'
    _write_json(source_path, {'name': 'Companion'})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/category/move',
        json={
            'id': 'global::写作/companion.json',
            'source_type': 'global',
            'target_category': '写作/长文',
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert source_path.exists() is False
    assert (presets_dir / '写作' / '长文' / 'companion.json').exists()


def test_move_preset_supports_grouped_family_item_via_concrete_version_target(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    source_path = presets_dir / '写作' / 'companion-v2.json'
    target_path = presets_dir / '归档' / 'companion-v2.json'
    _write_versioned_global_family(
        presets_dir,
        'family-move',
        [
            {
                'category': '写作',
                'filename': 'companion-v1.json',
                'name': 'Companion V1',
                'label': 'v1',
                'order': 10,
                'is_default': True,
            },
            {
                'category': '写作',
                'filename': source_path.name,
                'name': 'Companion V2',
                'label': 'v2',
                'order': 20,
            },
        ],
    )

    client = _make_test_app().test_client()
    list_res = client.get('/api/presets/list?filter_type=global')

    assert list_res.status_code == 200
    payload = list_res.get_json()
    assert payload['count'] == 1
    family_item = payload['items'][0]
    target_version = next(version for version in family_item['versions'] if version['id'].endswith('companion-v2.json'))

    move_res = client.post(
        '/api/presets/category/move',
        json={
            'id': target_version['id'],
            'source_type': family_item['source_type'],
            'target_category': '归档',
        },
    )

    assert move_res.status_code == 200
    payload = move_res.get_json()
    assert payload['success'] is True
    assert source_path.exists() is False
    assert target_path.exists() is True


def test_move_preset_resource_item_sets_override_without_moving_file(monkeypatch, tmp_path):
    resource_file = tmp_path / 'resources' / 'lucy' / 'presets' / 'companion.json'
    path_key = ui_store_module._normalize_resource_item_category_path(str(resource_file))
    _, _resources_dir = _setup_preset_env(
        monkeypatch,
        tmp_path,
        cards=[_make_card('cards/lucy.png', '原始分类')],
        ui_payload={'cards/lucy.png': {'resource_folder': 'lucy'}},
    )
    _write_json(resource_file, {'name': 'Companion'})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/category/move',
        json={
            'id': 'resource::lucy::companion',
            'source_type': 'resource',
            'file_path': str(resource_file),
            'target_category': '角色专属',
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert resource_file.exists() is True
    saved_payload = ui_store_module.get_resource_item_categories(ui_store_module.load_ui_data())
    assert saved_payload['presets'][path_key]['category'] == '角色专属'


def test_reset_preset_resource_category_override_restores_inherited_category(monkeypatch, tmp_path):
    resource_file = tmp_path / 'resources' / 'lucy' / 'presets' / 'companion.json'
    path_key = ui_store_module._normalize_resource_item_category_path(str(resource_file))
    _, _resources_dir = _setup_preset_env(
        monkeypatch,
        tmp_path,
        cards=[_make_card('cards/lucy.png', '角色分类')],
        ui_payload={
            'cards/lucy.png': {'resource_folder': 'lucy'},
            '_resource_item_categories_v1': {
                'presets': {
                    path_key: {'category': '角色专属', 'updated_at': 100},
                }
            },
        },
    )
    _write_json(resource_file, {'name': 'Companion'})

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/category/reset',
        json={
            'id': 'resource::lucy::companion',
            'source_type': 'resource',
            'file_path': str(resource_file),
        },
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    saved_payload = ui_store_module.get_resource_item_categories(ui_store_module.load_ui_data())
    assert path_key not in saved_payload['presets']


def test_create_preset_folder_creates_real_subdirectory(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/folders/create', json={'parent_category': '写作', 'name': '长文'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert (presets_dir / '写作' / '长文').is_dir()
    assert '写作' in payload['all_folders']
    assert '写作/长文' in payload['all_folders']
    assert payload['folder_capabilities']['写作']['has_physical_folder'] is True
    assert payload['folder_capabilities']['写作/长文']['can_delete_physical_folder'] is True


def test_rename_preset_folder_renames_real_subdirectory(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    (presets_dir / '写作' / '旧分类').mkdir(parents=True, exist_ok=True)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/folders/rename', json={'category': '写作/旧分类', 'new_name': '长文'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert (presets_dir / '写作' / '旧分类').exists() is False
    assert (presets_dir / '写作' / '长文').is_dir()


def test_delete_empty_preset_folder_removes_directory(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    target_dir = presets_dir / '写作' / '待删除'
    target_dir.mkdir(parents=True, exist_ok=True)

    client = _make_test_app().test_client()
    res = client.post('/api/presets/folders/delete', json={'category': '写作/待删除'})

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert target_dir.exists() is False


def test_upload_preset_uses_target_category_subfolder(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/upload',
        data={
            'target_category': '写作/长文',
            'files': (BytesIO(json.dumps({'temperature': 0.8}).encode('utf-8')), 'companion.json'),
        },
        content_type='multipart/form-data',
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is True
    assert (presets_dir / '写作' / '长文' / 'companion.json').exists()


def test_upload_preset_from_non_global_context_requires_explicit_fallback_confirmation_contract(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)

    client = _make_test_app().test_client()
    res = client.post(
        '/api/presets/upload',
        data={
            'source_context': 'resource',
            'files': (BytesIO(json.dumps({'temperature': 0.8}).encode('utf-8')), 'companion.json'),
        },
        content_type='multipart/form-data',
    )

    assert res.status_code == 200
    payload = res.get_json()
    assert payload['success'] is False
    assert payload['requires_global_fallback_confirmation'] is True
    assert not any(presets_dir.rglob('companion.json'))


def test_move_preset_category_reset_rejects_non_resource_item(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    source_path = presets_dir / '写作' / 'companion.json'
    _write_json(source_path, {'name': 'Companion'})

    client = _make_test_app().test_client()

    move_res = client.post(
        '/api/presets/category/move',
        json={
            'id': 'global::写作/companion.json',
            'source_type': 'global',
            'file_path': str(source_path),
            'target_category': '角色专属',
            'mode': 'resource_only',
        },
    )
    assert move_res.status_code == 200
    move_payload = move_res.get_json()
    assert move_payload['success'] is False
    assert 'resource' in move_payload['msg'].lower() or '资源' in move_payload['msg']

    reset_res = client.post(
        '/api/presets/category/reset',
        json={
            'id': 'global::写作/companion.json',
            'source_type': 'global',
            'file_path': str(source_path),
        },
    )
    assert reset_res.status_code == 200
    reset_payload = reset_res.get_json()
    assert reset_payload['success'] is False
    assert 'resource' in reset_payload['msg'].lower() or '资源' in reset_payload['msg']


def test_list_presets_includes_empty_physical_folders_in_metadata(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    empty_dir = presets_dir / '写作' / '空目录'
    empty_dir.mkdir(parents=True, exist_ok=True)

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=global')

    assert res.status_code == 200
    payload = res.get_json()
    assert '写作' in payload['all_folders']
    assert '写作/空目录' in payload['all_folders']
    assert payload['folder_capabilities']['写作']['has_physical_folder'] is True
    assert payload['folder_capabilities']['写作/空目录']['can_delete_physical_folder'] is True


def test_preset_root_folder_capabilities_allow_create_subcategory(monkeypatch, tmp_path):
    presets_dir = tmp_path / 'presets'
    presets_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(presets_api, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(presets_api, 'load_config', lambda: {'presets_dir': str(presets_dir), 'resources_dir': str(tmp_path / 'resources')})
    monkeypatch.setattr(presets_api.ctx, 'cache', _FakeCache([]))

    client = _make_test_app().test_client()
    res = client.get('/api/presets/list?filter_type=global')

    assert res.status_code == 200
    payload = res.get_json()
    root_caps = payload['folder_capabilities'].get('', {})
    assert root_caps.get('has_physical_folder') is True
    assert root_caps.get('can_create_child_folder') is True


def test_preset_resource_override_rejects_non_resource_path_even_with_resource_source_type(monkeypatch, tmp_path):
    presets_dir, _ = _setup_preset_env(monkeypatch, tmp_path)
    global_file = presets_dir / '写作' / 'companion.json'
    _write_json(global_file, {'name': 'Companion'})

    client = _make_test_app().test_client()

    move_res = client.post(
        '/api/presets/category/move',
        json={
            'id': 'resource::fake::companion',
            'source_type': 'resource',
            'file_path': str(global_file),
            'target_category': '角色专属',
        },
    )
    assert move_res.status_code == 200
    move_payload = move_res.get_json()
    assert move_payload['success'] is False
    assert '不存在' in move_payload['msg'] or '资源' in move_payload['msg'] or '非法路径' in move_payload['msg']

    reset_res = client.post(
        '/api/presets/category/reset',
        json={
            'id': 'resource::fake::companion',
            'source_type': 'resource',
            'file_path': str(global_file),
        },
    )
    assert reset_res.status_code == 200
    reset_payload = reset_res.get_json()
    assert reset_payload['success'] is False
    assert '不存在' in reset_payload['msg'] or '资源' in reset_payload['msg'] or '非法路径' in reset_payload['msg']
