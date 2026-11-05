import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.config import build_default_config, normalize_config


def test_pagination_scrubber_defaults_to_enabled():
    """默认开启，保证老用户升级后行为不变。"""
    assert build_default_config()['show_pagination_scrubber'] is True
    assert normalize_config({})['show_pagination_scrubber'] is True


@pytest.mark.parametrize(
    'raw, expected',
    [
        (True, True),
        (False, False),
        (1, True),
        (0, False),
        ('true', True),
        ('1', True),
        ('yes', True),
        ('on', True),
        ('false', False),
        ('0', False),
        ('no', False),
        ('off', False),
        ('', False),
    ],
)
def test_pagination_scrubber_accepts_string_flags(raw, expected):
    """手改 config.json 写成字符串也不能反向生效（'false' 必须为假）。"""
    cfg = normalize_config({'show_pagination_scrubber': raw})
    assert cfg['show_pagination_scrubber'] is expected


def test_pagination_scrubber_falls_back_to_default_on_garbage():
    cfg = normalize_config({'show_pagination_scrubber': 'not-a-bool'})
    assert cfg['show_pagination_scrubber'] is True


def test_pagination_scrubber_survives_roundtrip(tmp_path, monkeypatch):
    """写过 config 再读回来仍是布尔值。"""
    from core import config as config_module

    path = tmp_path / 'config.json'
    config_module.write_config_file(
        str(path), {'show_pagination_scrubber': 'off'}
    )

    monkeypatch.setattr(config_module, 'CONFIG_FILE', str(path))
    loaded = config_module.load_config()
    assert loaded['show_pagination_scrubber'] is False
