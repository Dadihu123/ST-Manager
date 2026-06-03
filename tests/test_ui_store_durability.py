import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data import ui_store as ui_store_module


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _patch_ui_path(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    return ui_path


def test_save_ui_data_keeps_existing_file_when_json_dump_fails(monkeypatch, tmp_path):
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    original = {'hero.png': {'summary': 'keep me'}}
    _write_json(ui_path, original)

    def failing_dump(_payload, handle, *args, **kwargs):
        handle.write('{"partial":')
        raise RuntimeError('forced json dump failure')

    monkeypatch.setattr(ui_store_module.json, 'dump', failing_dump)

    assert ui_store_module.save_ui_data({'hero.png': {'summary': 'new'}}) is False
    assert _read_json(ui_path) == original
    assert not list(tmp_path.glob('*.tmp'))


def test_save_ui_data_writes_primary_and_last_good_backup(monkeypatch, tmp_path):
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    payload = {'hero.png': {'summary': 'fresh'}}

    assert ui_store_module.save_ui_data(payload) is True

    assert _read_json(ui_path) == payload
    assert _read_json(tmp_path / 'ui_data.json.bak') == payload
    assert not list(tmp_path.glob('*.tmp'))


def test_load_ui_data_restores_valid_backup_when_primary_is_corrupt(monkeypatch, tmp_path):
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    backup_payload = {'hero.png': {'summary': 'from backup'}}
    ui_path.write_text('{"broken":', encoding='utf-8')
    _write_json(tmp_path / 'ui_data.json.bak', backup_payload)

    loaded = ui_store_module.load_ui_data()

    assert loaded == backup_payload
    assert _read_json(ui_path) == backup_payload
    assert _read_json(tmp_path / 'ui_data.json.bak') == backup_payload
    corrupted_files = list(tmp_path.glob('ui_data.json.corrupted.*'))
    assert len(corrupted_files) == 1
    assert corrupted_files[0].read_text(encoding='utf-8') == '{"broken":'


def test_load_ui_data_returns_empty_and_preserves_corrupt_file_without_backup(monkeypatch, tmp_path):
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    ui_path.write_text('{"broken":', encoding='utf-8')

    assert ui_store_module.load_ui_data() == {}

    corrupted_files = list(tmp_path.glob('ui_data.json.corrupted.*'))
    assert len(corrupted_files) == 1
    assert corrupted_files[0].read_text(encoding='utf-8') == '{"broken":'
    assert ui_path.read_text(encoding='utf-8') == '{"broken":'


def test_load_ui_data_dirty_cleanup_uses_atomic_save(monkeypatch, tmp_path):
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    payload = {
        'hero.png': {
            'summary': 'note',
            'resource_folder': 'cards/bad',
            ui_store_module.IMPORT_TIME_KEY: '1700000000.5',
        }
    }
    _write_json(ui_path, payload)

    loaded = ui_store_module.load_ui_data()

    expected = {
        'hero.png': {
            'summary': 'note',
            'resource_folder': '',
            ui_store_module.IMPORT_TIME_KEY: 1700000000.5,
        }
    }
    assert loaded == expected
    assert _read_json(ui_path) == expected
    assert _read_json(tmp_path / 'ui_data.json.bak') == expected
    assert not list(tmp_path.glob('*.tmp'))
