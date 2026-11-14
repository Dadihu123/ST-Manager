import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('wheelhouse', ROOT / 'tools/build_android_wheelhouse.py')
wheelhouse = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wheelhouse)


def test_empty_wheelhouse_fails_even_when_host_package_is_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(wheelhouse, 'WHEELHOUSE', tmp_path)
    monkeypatch.setattr(wheelhouse, 'REQUIREMENTS', ['pip'])
    monkeypatch.setattr(wheelhouse, 'TARGET_ARGS', [])
    assert __import__('pip')
    assert wheelhouse.verify_offline() is False


def test_download_failure_aborts_build(monkeypatch, tmp_path):
    monkeypatch.setattr(wheelhouse, 'WHEELHOUSE', tmp_path)
    monkeypatch.setattr(wheelhouse, 'download', lambda *args: False)
    monkeypatch.setattr(wheelhouse, 'verify_offline', lambda: (_ for _ in ()).throw(AssertionError()))
    assert wheelhouse.main() == 1
