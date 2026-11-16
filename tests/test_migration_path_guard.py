import json
import os

import pytest

from core.utils.paths import is_protected_migration_path, require_business_write_path


def directory_link(link, target):
    if os.name == 'nt':
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


@pytest.fixture
def android_aliases(tmp_path):
    native = tmp_path / 'data/data/com.stmanager.test/files'
    alias = tmp_path / 'data/user/0/com.stmanager.test/files'
    native.mkdir(parents=True)
    alias.parent.mkdir(parents=True)
    directory_link(alias, native)
    assert os.path.samefile(alias, native)
    assert os.path.normpath(os.path.realpath(alias)) != str(alias)
    return native, alias


@pytest.mark.parametrize('base_alias', [0, 1])
@pytest.mark.parametrize('root_alias', [0, 1])
@pytest.mark.parametrize('path_alias', [0, 1])
def test_active_library_accepts_android_root_aliases(android_aliases, base_alias, root_alias, path_alias):
    suffix = 'data/migration/' + 'a' * 32 + '/library/scripts_dir'
    root = android_aliases[root_alias] / suffix
    root.mkdir(parents=True)
    path = android_aliases[path_alias] / suffix / 'new.json'
    cfg = {'scripts_dir': str(root)}
    assert not is_protected_migration_path(str(path), str(android_aliases[base_alias]), [str(root)])
    require_business_write_path(str(path), str(android_aliases[base_alias]), cfg)


@pytest.mark.parametrize('alias', [0, 1])
@pytest.mark.parametrize('area', ['restore', 'snapshot', 'protection', 'library/not-configured'])
def test_alias_does_not_release_staging_or_protection(android_aliases, alias, area):
    base = android_aliases[1 - alias]
    active = base / ('data/migration/' + 'a' * 32 + '/library/scripts_dir')
    active.mkdir(parents=True)
    path = android_aliases[alias] / ('data/migration/' + 'a' * 32) / area / 'book.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{}', encoding='utf-8')
    assert is_protected_migration_path(str(path), str(base), [str(active)])
    with pytest.raises(ValueError, match='迁移暂存'):
        require_business_write_path(str(path), str(base), {'scripts_dir': str(active)})
    # 即使配置错误地指向受保护目录，也不能借配置放行。
    if not area.startswith('library/'):
        assert is_protected_migration_path(str(path), str(base), [str(path.parent)])


@pytest.mark.parametrize('alias', [0, 1])
@pytest.mark.parametrize('journal', ['pending', 'invalid'])
def test_pending_or_unreadable_journal_still_blocks_aliases(android_aliases, alias, journal):
    base = android_aliases[1 - alias]
    suffix = 'data/migration/' + 'a' * 32 + '/library/scripts_dir'
    root = base / suffix
    root.mkdir(parents=True)
    pending = base / 'data/migration/pending.json'
    pending.write_text(json.dumps({'job': 'a' * 32}) if journal == 'pending' else '{', encoding='utf-8')
    path = android_aliases[alias] / suffix / 'book.json'
    with pytest.raises(ValueError, match='迁移暂存'):
        require_business_write_path(str(path), str(base), {'scripts_dir': str(root)})


@pytest.mark.parametrize('alias', [0, 1])
@pytest.mark.parametrize('whole_slot', [False, True])
def test_library_link_into_protection_is_never_active(android_aliases, alias, whole_slot):
    base = android_aliases[1 - alias]
    workspace = base / ('data/migration/' + 'a' * 32)
    protected = workspace / 'protection/scripts'
    protected.mkdir(parents=True)
    (protected / 'book.json').write_text('original', encoding='utf-8')
    slot = workspace / 'library/scripts_dir'
    slot.parent.mkdir(parents=True)
    if whole_slot:
        directory_link(slot, protected)
        root = slot
    else:
        slot.mkdir()
        root = slot / 'linked'
        directory_link(root, protected)
    path = android_aliases[alias] / os.path.relpath(root, base) / 'book.json'
    with pytest.raises(ValueError, match='迁移暂存'):
        require_business_write_path(str(path), str(base), {'scripts_dir': str(root)})
    assert (protected / 'book.json').read_text(encoding='utf-8') == 'original'
