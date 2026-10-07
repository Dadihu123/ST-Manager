"""secrets.json 读写测试（设计文档第 7 部分 / 13.1）。"""

import json
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import secrets as secrets_module


@pytest.fixture
def secrets_file(tmp_path, monkeypatch):
    target = tmp_path / 'secrets.json'
    monkeypatch.setattr(secrets_module, 'SECRETS_FILE', str(target))
    secrets_module._clear_degraded()
    yield target
    secrets_module._clear_degraded()


def test_set_and_get_roundtrip(secrets_file):
    assert secrets_module.set_secret('demo', 'api_key', 'sk-abcd1234') is True
    assert secrets_module.get_secret('demo', 'api_key') == 'sk-abcd1234'


def test_written_file_is_utf8_json_with_schema_version(secrets_file):
    secrets_module.set_secret('demo', 'note', '中文密钥')

    payload = json.loads(secrets_file.read_text(encoding='utf-8'))

    assert payload['schema_version'] == 1
    assert payload['plugins']['demo']['note']['value'] == '中文密钥'
    assert payload['plugins']['demo']['note']['updated_at'] > 0


def test_secret_items_never_expose_plaintext(secrets_file):
    secrets_module.set_secret('demo', 'api_key', 'sk-1234567890abcd')

    described = secrets_module.describe_secrets(
        'demo', {'properties': {'api_key': {'type': 'string', 'secret': True}}},
    )

    entry = described['api_key']
    assert entry['set'] is True
    assert entry['hint'] == 'sk-…abcd'
    assert 'value' not in entry


def test_short_secret_hint_is_fully_masked():
    assert secrets_module.hint_for('short') == '•••••'
    assert secrets_module.hint_for('12345678') == '••••••••'
    assert secrets_module.hint_for('') == ''


def test_non_secret_item_returns_plaintext(secrets_file):
    secrets_module.set_secret('demo', 'base_url', 'https://api.example.com/v1')

    described = secrets_module.describe_secrets('demo', {'properties': {'base_url': {'type': 'string'}}})

    assert described['base_url']['value'] == 'https://api.example.com/v1'
    assert described['base_url']['set'] is True


def test_non_secret_default_is_reported_when_unset(secrets_file):
    described = secrets_module.describe_secrets(
        'demo', {'properties': {'base_url': {'type': 'string', 'default': 'https://example.com/v1'}}},
    )

    assert described['base_url']['value'] == 'https://example.com/v1'
    assert described['base_url']['set'] is False


def test_environment_variable_takes_priority(secrets_file, monkeypatch):
    secrets_module.set_secret('demo', 'api_key', 'from-file-value')
    monkeypatch.setenv('STM_PLUGIN_DEMO_API_KEY', 'from-env-values!')

    assert secrets_module.get_secret('demo', 'api_key') == 'from-env-values!'

    described = secrets_module.describe_secrets(
        'demo', {'properties': {'api_key': {'type': 'string', 'secret': True}}},
    )
    assert described['api_key']['source'] == 'env'
    assert described['api_key']['hint'] == 'fro…ues!'


def test_env_var_name_normalization():
    assert secrets_module.env_var_name('stm-ai-assistant', 'api-key') == 'STM_PLUGIN_STM_AI_ASSISTANT_API_KEY'
    assert secrets_module.env_var_name('demo', 'base.url') == 'STM_PLUGIN_DEMO_BASE_URL'


def test_delete_and_clear(secrets_file):
    secrets_module.set_secret('demo', 'a', '1')
    secrets_module.set_secret('demo', 'b', '2')
    secrets_module.set_secret('other', 'c', '3')

    assert secrets_module.delete_secret('demo', 'a') is True
    assert secrets_module.get_secret('demo', 'a') is None

    assert secrets_module.clear_plugin_secrets('demo') is True
    assert secrets_module.get_secret('demo', 'b') is None
    assert secrets_module.get_secret('other', 'c') == '3'


def test_empty_value_clears_secret(secrets_file):
    secrets_module.set_secret('demo', 'api_key', 'value')

    secrets_module.set_secret('demo', 'api_key', '')

    assert secrets_module.get_secret('demo', 'api_key') is None


def test_backup_rotation_keeps_previous_generation(secrets_file):
    secrets_module.set_secret('demo', 'api_key', 'v1')
    secrets_module.set_secret('demo', 'api_key', 'v2')

    backup_path = f'{secrets_file}.bak'
    assert os.path.exists(backup_path)

    payload = json.loads(open(backup_path, encoding='utf-8').read())
    assert payload['plugins']['demo']['api_key']['value'] == 'v1'


def test_corrupted_file_is_snapshotted_and_returns_empty(secrets_file):
    secrets_file.write_text('{not json', encoding='utf-8')

    data = secrets_module.load_secrets()

    assert data == {}
    assert secrets_module.is_degraded() is False
    corrupted = list(secrets_file.parent.glob('secrets.json.corrupted.*'))
    assert corrupted


def test_missing_file_returns_empty(secrets_file):
    assert secrets_module.load_secrets() == {}
    assert secrets_module.is_degraded() is False


def test_read_failure_blocks_write(secrets_file, monkeypatch):
    original = json.dumps({
        'schema_version': 1,
        'plugins': {'demo': {'api_key': {'value': 'x'}}},
        'app': {},
    })
    secrets_file.write_text(original, encoding='utf-8')

    def boom(path, attempts=secrets_module.READ_RETRY_ATTEMPTS):
        raise OSError('locked by another process')

    monkeypatch.setattr(secrets_module, '_read_json_with_retry', boom)

    assert secrets_module.load_secrets() == {}
    assert secrets_module.is_degraded() is True
    assert secrets_module.save_secrets({'plugins': {}, 'app': {}}) is False
    assert secrets_module.set_secret('demo', 'api_key', 'new') is False

    # 既有密钥文件不得被覆盖
    assert secrets_file.read_text(encoding='utf-8') == original


def test_redact_masks_known_values():
    assert secrets_module.redact('key=sk-secret-value', 'sk-secret-value') == 'key=***'
    assert secrets_module.redact('nothing to hide', 'ab') == 'nothing to hide'
