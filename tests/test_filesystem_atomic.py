import builtins
import errno
import json
import os
import stat

import pytest

from core.utils import filesystem


@pytest.fixture
def portable_name_limit(monkeypatch):
    """在真实文件 I/O 上施加 Android 的 NAME_MAX，Windows 也运行同一行为测试。"""
    original_open = builtins.open
    original_os_open = os.open

    def check(path):
        if not isinstance(path, int) and len(os.path.basename(os.fsdecode(path)).encode('utf-8')) > 255:
            raise OSError(errno.ENAMETOOLONG, 'File name too long', os.fspath(path))

    def checked_open(path, *args, **kwargs):
        check(path)
        return original_open(path, *args, **kwargs)

    def checked_os_open(path, *args, **kwargs):
        check(path)
        return original_os_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, 'open', checked_open)
    monkeypatch.setattr(os, 'open', checked_os_open)


@pytest.mark.parametrize('name_bytes', [253, 254, 255])
@pytest.mark.parametrize('existing', [False, True])
def test_atomic_json_long_name_is_editable(tmp_path, portable_name_limit, name_bytes, existing):
    stem_bytes = name_bytes - len('.json')
    name = '长' * (stem_bytes // 3) + 'a' * (stem_bytes % 3) + '.json'
    assert len(name.encode('utf-8')) == name_bytes
    target = tmp_path / name
    if existing:
        target.write_text('{"original":true}', encoding='utf-8')
    original_replace = os.replace
    replacements = []

    def record_replace(source, destination):
        temporary = os.path.abspath(source)
        assert os.path.dirname(temporary) == str(tmp_path)
        assert len(os.path.basename(temporary).encode('utf-8')) <= 255
        replacements.append(temporary)
        original_replace(source, destination)

    # 记录真实替换，以验证临时文件位于同一文件系统。
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(filesystem.os, 'replace', record_replace)
        assert filesystem.save_json_atomic(str(target), {'notes': '编辑后的内容', 'enabled': True})
    assert len(replacements) == 1
    assert json.loads(target.read_text(encoding='utf-8')) == {'notes': '编辑后的内容', 'enabled': True}
    assert '编辑后的内容' in target.read_text(encoding='utf-8')
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize('failure', ['serialize', 'fsync', 'replace', 'create'])
@pytest.mark.parametrize('existing', [False, True])
def test_atomic_json_failure_keeps_original_and_cleans_temporary(tmp_path, monkeypatch, failure, existing):
    target = tmp_path / 'script.json'
    original = b'{"original":"unchanged"}'
    if existing:
        target.write_bytes(original)
    data = {'value': 'new'}

    def denied(*args, **kwargs):
        raise OSError('synthetic write failure')

    if failure == 'serialize':
        data = {'value': object()}
    elif failure == 'create':
        monkeypatch.setattr(filesystem.tempfile, 'NamedTemporaryFile', denied)
    else:
        monkeypatch.setattr(filesystem.os, failure, denied)
    assert filesystem.save_json_atomic(str(target), data) is False
    if existing:
        assert target.read_bytes() == original
    else:
        assert not target.exists()
    assert set(tmp_path.iterdir()) == ({target} if existing else set())


def test_atomic_json_does_not_touch_unrelated_tmp_and_accepts_relative_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    unrelated = tmp_path / 'script.json.tmp'
    unrelated.write_bytes(b'not this saves temporary file')
    assert filesystem.save_json_atomic('script.json', {'notes': '备注'})
    assert unrelated.read_bytes() == b'not this saves temporary file'
    assert json.loads((tmp_path / 'script.json').read_text(encoding='utf-8')) == {'notes': '备注'}
    assert {path.name for path in tmp_path.iterdir()} == {'script.json', 'script.json.tmp'}


@pytest.mark.skipif(os.name == 'nt', reason='POSIX mode semantics')
def test_atomic_json_preserves_existing_permissions(tmp_path):
    target = tmp_path / 'script.json'
    target.write_text('{}', encoding='utf-8')
    target.chmod(0o640)
    assert filesystem.save_json_atomic(str(target), {'notes': '修改'})
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


@pytest.mark.skipif(os.name != 'nt', reason='Windows read-only attribute semantics')
def test_atomic_json_readonly_target_failure_cleans_temporary(tmp_path):
    target = tmp_path / 'readonly.json'
    original = b'{"original":true}'
    target.write_bytes(original)
    target.chmod(stat.S_IREAD)
    try:
        assert filesystem.save_json_atomic(str(target), {'edited': True}) is False
        assert target.read_bytes() == original
        assert list(tmp_path.iterdir()) == [target]
    finally:
        target.chmod(stat.S_IREAD | stat.S_IWRITE)
