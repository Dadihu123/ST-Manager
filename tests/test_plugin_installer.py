"""插件安装器测试（设计文档 3.2–3.6 / 13.1）。

重点是解压安全：zip-slip、绝对路径、盘符、符号链接、zip 炸弹、体积上限、
供应链 id 校验，以及安装/卸载的回收站与数据清理语义。
"""

import hashlib
import json
import os
import stat
import sys
import zipfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import installer as installer_module
from core.plugins import job_store, registry
from core.plugins import secrets as secrets_module
from core.plugins.errors import (
    PluginArchiveUnsafeError,
    PluginInstallError,
    PluginManifestError,
)
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import clear_plugin_ui_namespace, write_plugin


@pytest.fixture
def install_env(tmp_path, monkeypatch):
    plugins_root = tmp_path / 'plugins'
    plugins_root.mkdir()
    trash_root = tmp_path / 'trash'
    temp_root = tmp_path / 'temp'
    temp_root.mkdir()

    monkeypatch.setattr(registry, 'plugins_dir', lambda: str(plugins_root))
    monkeypatch.setattr(installer_module, 'TRASH_FOLDER', str(trash_root))
    monkeypatch.setattr(installer_module, 'TEMP_DIR', str(temp_root))
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'jobs.db'))
    monkeypatch.setattr(secrets_module, 'SECRETS_FILE', str(tmp_path / 'secrets.json'))
    # 清空注册表内存状态：`install_plugin_dir()` 现在会登记 state（plugin_dir 指向
    # 本用例的 plugins_root），不清理的话下个用例的 `uninstall_plugin()` 会从陈旧
    # state 里读到上一个用例的 tmp_path。其它插件测试文件也都这么做。
    registry.reset_for_tests()
    clear_plugin_ui_namespace()
    secrets_module._clear_degraded()

    yield {
        'plugins_root': plugins_root,
        'trash_root': trash_root,
        'temp_root': temp_root,
        'tmp_path': tmp_path,
    }

    registry.reset_for_tests()
    clear_plugin_ui_namespace()
    secrets_module._clear_degraded()


def _write_plugin_zip(path, entries, *, plugin_id='zip-plugin'):
    """构造插件 zip；entries 为 `{相对路径: 内容}` 或 `(ZipInfo, content)` 列表。"""
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archived = False
        for name, content in entries.items():
            if isinstance(name, str) and name == 'manifest.json':
                archived = True
            archive.writestr(name, content)
        if not archived and 'manifest.json' not in entries:
            archive.writestr('manifest.json', json.dumps({
                'id': plugin_id,
                'name': plugin_id,
                'version': '0.1.0',
                'api_version': 1,
                'backend': {'entry': 'backend', 'register': 'register'},
            }))
            archive.writestr('backend/__init__.py', 'def register(api):\n    return None\n')
    return path


def _symlink_entry(name, target='../../outside'):
    info = zipfile.ZipInfo(name)
    info.create_system = 3  # Unix
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info, target


# ------------------------------------------------------------------ 输入校验


def test_validate_repo_accepts_owner_slash_repo():
    assert installer_module.validate_repo('owner/repo') == 'owner/repo'
    assert installer_module.validate_repo('Owner.Name/repo_name-1') == 'Owner.Name/repo_name-1'


@pytest.mark.parametrize('repo', [
    'https://evil.example/x.zip',
    'owner',
    'owner/repo/extra',
    '../owner/repo',
    'owner/..',
    '',
])
def test_validate_repo_rejects_arbitrary_urls(repo):
    with pytest.raises(PluginInstallError):
        installer_module.validate_repo(repo)


@pytest.mark.parametrize('ref', ['../main', 'main/../../x', 'main;rm -rf /', ''])
def test_validate_ref_rejects_unsafe_values(ref):
    if ref == '':
        assert installer_module.validate_ref(ref) == 'main'
        return
    with pytest.raises(PluginInstallError):
        installer_module.validate_ref(ref)


def test_validate_subdir_rejects_traversal():
    assert installer_module.validate_subdir('packages/plugin-a') == 'packages/plugin-a'
    assert installer_module.validate_subdir('') == ''
    with pytest.raises(PluginInstallError):
        installer_module.validate_subdir('../outside')


def test_build_archive_url_uses_codeload_only():
    """域名固定为 codeload.github.com（防 SSRF），且用**裸 ref** 形式。

    裸 `zip/<ref>` 是唯一能同时解析分支与 tag 的写法：
    - `zip/refs/heads/<ref>` 只解析分支（tag 会 404）
    - `zip/refs/tags/<ref>` 只解析 tag（分支会 404）
    实测见 `build_archive_url` 的 docstring。
    """
    assert installer_module.build_archive_url('owner/repo', 'main') == (
        'https://codeload.github.com/owner/repo/zip/main'
    )
    assert installer_module.build_archive_url('owner/repo', 'abc1234') == (
        'https://codeload.github.com/owner/repo/zip/abc1234'
    )


def test_build_archive_url_resolves_tags_not_only_branches():
    """回归：tag 必须可用（`stable` 渠道按 Release tag 更新时会传 tag）。

    旧实现无条件拼 `refs/heads/<ref>`，导致传 tag 得到 404——
    「检查更新说 v0.3.0 可用，点更新却下载失败」。
    """
    for ref in ('v0.2.0', '0.2.0', 'release-2026-10'):
        url = installer_module.build_archive_url('owner/repo', ref)

        assert url == f'https://codeload.github.com/owner/repo/zip/{ref}'
        assert 'refs/heads' not in url
        assert 'refs/tags' not in url


def test_build_archive_url_rejects_unsafe_refs():
    """`ref` 会拼进 URL，必须挡住路径穿越、前导斜杠与命令注入形状。"""
    for bad in (
        '../main',
        'main;rm -rf /',
        '/etc/passwd',        # 前导斜杠会拼出 `zip//etc/passwd`
        'main/',              # 尾随斜杠
        'a//b',               # 空段
        'main?x=1',           # 查询串
        'main#frag',          # 片段
        'a' * 201,            # 超长
    ):
        with pytest.raises(PluginInstallError):
            installer_module.build_archive_url('owner/repo', bad)


# ------------------------------------------------------------------ 解压安全


def test_safe_extract_accepts_wellformed_archive(tmp_path, install_env):
    archive_path = _write_plugin_zip(tmp_path / 'ok.zip', {'extra.txt': 'hello'})

    dest = installer_module.safe_extract_archive(str(archive_path), str(tmp_path / 'out'))

    assert os.path.isfile(os.path.join(dest, 'manifest.json'))
    assert os.path.isfile(os.path.join(dest, 'backend', '__init__.py'))
    assert open(os.path.join(dest, 'extra.txt'), encoding='utf-8').read() == 'hello'


@pytest.mark.parametrize('name', [
    '../escape.py',
    '../../escape.py',
    'nested/../../escape.py',
])
def test_safe_extract_rejects_zip_slip(tmp_path, install_env, name):
    archive_path = _write_plugin_zip(tmp_path / 'slip.zip', {name: 'pwned'})

    with pytest.raises(PluginArchiveUnsafeError, match='上级目录'):
        installer_module.safe_extract_archive(str(archive_path), str(tmp_path / 'out'))

    assert not (tmp_path / 'escape.py').exists()


def test_safe_extract_rejects_absolute_path(tmp_path, install_env):
    entries = {}
    info = zipfile.ZipInfo('/tmp/evil.py')
    entries[info] = 'pwned'
    archive_path = tmp_path / 'abs.zip'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        for info, content in entries.items():
            archive.writestr(info, content)

    with pytest.raises(PluginArchiveUnsafeError, match='绝对路径'):
        installer_module.safe_extract_archive(str(archive_path), str(tmp_path / 'out'))


def test_safe_extract_rejects_drive_letter(tmp_path, install_env):
    info = zipfile.ZipInfo('C:/windows/evil.py')
    archive_path = tmp_path / 'drive.zip'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr(info, 'pwned')

    # Windows 上 'C:/...' 同时命中绝对路径判定，两者都属拒绝理由
    with pytest.raises(PluginArchiveUnsafeError, match='绝对路径|盘符'):
        installer_module.safe_extract_archive(str(archive_path), str(tmp_path / 'out'))


def test_safe_extract_rejects_symlink(tmp_path, install_env):
    info, target = _symlink_entry('link')
    archive_path = tmp_path / 'symlink.zip'
    with zipfile.ZipFile(archive_path, 'w') as archive:
        archive.writestr(info, target)

    with pytest.raises(PluginArchiveUnsafeError, match='符号链接'):
        installer_module.safe_extract_archive(str(archive_path), str(tmp_path / 'out'))


def test_safe_extract_rejects_high_compression_ratio(tmp_path, install_env):
    archive_path = tmp_path / 'bomb.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('big.bin', b'\0' * (4 * 1024 * 1024))
        archive.writestr('manifest.json', '{}')

    with pytest.raises(PluginArchiveUnsafeError, match='压缩比'):
        installer_module.safe_extract_archive(str(archive_path), str(tmp_path / 'out'))


def test_safe_extract_rejects_total_size_limit(tmp_path, install_env, monkeypatch):
    monkeypatch.setattr(installer_module, 'MAX_UNCOMPRESSED_BYTES', 1024)
    # 用不可压缩数据，确保先命中「体积上限」而不是「压缩比」
    archive_path = _write_plugin_zip(tmp_path / 'big.zip', {'payload.bin': os.urandom(4096)})

    with pytest.raises(PluginArchiveUnsafeError, match='体积过大'):
        installer_module.safe_extract_archive(str(archive_path), str(tmp_path / 'out'))


def test_safe_extract_rejects_too_many_entries(tmp_path, install_env, monkeypatch):
    monkeypatch.setattr(installer_module, 'MAX_ARCHIVE_ENTRIES', 3)
    entries = {f'file-{index}.txt': 'x' for index in range(6)}
    archive_path = _write_plugin_zip(tmp_path / 'many.zip', entries)

    with pytest.raises(PluginArchiveUnsafeError, match='条目过多'):
        installer_module.safe_extract_archive(str(archive_path), str(tmp_path / 'out'))


def test_safe_extract_rejects_non_zip(tmp_path, install_env):
    broken = tmp_path / 'broken.zip'
    broken.write_text('not a zip', encoding='utf-8')

    with pytest.raises(PluginArchiveUnsafeError, match='zip'):
        installer_module.safe_extract_archive(str(broken), str(tmp_path / 'out'))


def test_safe_extract_rejects_when_disk_space_is_low(tmp_path, install_env, monkeypatch):
    archive_path = _write_plugin_zip(tmp_path / 'disk.zip', {'payload.bin': b'x' * 1024})

    class _Usage:
        free = 1

    monkeypatch.setattr(installer_module.shutil, 'disk_usage', lambda path: _Usage())

    with pytest.raises(PluginInstallError, match='磁盘可用空间不足'):
        installer_module.safe_extract_archive(str(archive_path), str(tmp_path / 'out'))


# ------------------------------------------------------------------ 定位与安装


def test_locate_plugin_root_finds_single_nested_dir(tmp_path, install_env):
    archive_path = _write_plugin_zip(tmp_path / 'nested.zip', {'README.md': 'hello'}, plugin_id='nested-plugin')
    dest = installer_module.safe_extract_archive(str(archive_path), str(tmp_path / 'out'))

    # 解压结果已经是插件根（manifest 在顶层）
    assert installer_module.locate_plugin_root(dest) == dest

    wrapped = tmp_path / 'wrapped'
    os.makedirs(wrapped)
    # GitHub 归档的形态：解压后多一层 `repo-branch/`，插件根在其中
    write_plugin(wrapped, 'repo-main')

    assert installer_module.locate_plugin_root(str(wrapped)) == os.path.join(str(wrapped), 'repo-main')


def test_locate_plugin_root_rejects_ambiguous_archives(tmp_path, install_env):
    root = tmp_path / 'ambiguous'
    write_plugin(root, 'plugin-a')
    write_plugin(root, 'plugin-b')

    with pytest.raises(PluginInstallError, match='多个插件目录'):
        installer_module.locate_plugin_root(str(root))


def test_locate_plugin_root_rejects_missing_manifest(tmp_path, install_env):
    empty = tmp_path / 'empty'
    os.makedirs(empty)

    with pytest.raises(PluginInstallError, match='manifest'):
        installer_module.locate_plugin_root(str(empty))


def test_install_plugin_dir_moves_source_and_strips_forbidden_dirs(tmp_path, install_env):
    source = write_plugin(tmp_path / 'stage', 'zip-plugin')
    os.makedirs(os.path.join(source, '__pycache__'))
    os.makedirs(os.path.join(source, 'node_modules'))
    with open(os.path.join(source, '__pycache__', 'x.pyc'), 'wb') as handle:
        handle.write(b'x')

    result = installer_module.install_plugin_dir(source)

    target = install_env['plugins_root'] / 'zip-plugin'
    assert result['action'] == 'install'
    assert target.is_dir()
    assert (target / 'manifest.json').is_file()
    assert (target / 'data').is_dir()
    assert not (target / '__pycache__').exists()
    assert not (target / 'node_modules').exists()
    assert not os.path.isdir(source)


def test_install_plugin_dir_replaces_existing_into_trash(tmp_path, install_env):
    target = install_env['plugins_root'] / 'zip-plugin'
    target.mkdir(parents=True)
    (target / 'old.txt').write_text('old', encoding='utf-8')

    source = write_plugin(tmp_path / 'stage', 'zip-plugin')
    result = installer_module.install_plugin_dir(source)

    assert result['action'] == 'update'
    assert result['trash']
    assert not (target / 'old.txt').exists()
    trashed = list(install_env['trash_root'].glob('plugin_zip-plugin_*'))
    assert trashed and (trashed[0] / 'old.txt').is_file()


def test_install_plugin_dir_enforces_expected_id(tmp_path, install_env):
    source = write_plugin(tmp_path / 'stage', 'zip-plugin')

    with pytest.raises(PluginManifestError, match='预期'):
        installer_module.install_plugin_dir(source, expected_id='another-plugin')


# ------------------------------------------- 安装/更新后同步内存 manifest（回归）


def _stage_versioned(tmp_path, version, name='stage'):
    """生成一个指定版本的插件目录，返回其路径。"""
    from tests.plugins_test_support import base_manifest

    payload = base_manifest('zip-plugin')
    payload['version'] = version
    return write_plugin(tmp_path / name, 'zip-plugin', manifest=payload)


def _cached_state(install_env, *, loaded=False):
    """模拟「进程启动时加载过该插件」——注册表缓存了当时的 manifest。"""
    state = registry.PluginState('zip-plugin', str(install_env['plugins_root'] / 'zip-plugin'))
    state.manifest = PluginManifest.load(state.plugin_dir, check_dir_name=False)
    state.loaded = loaded
    registry._states['zip-plugin'] = state
    return state


def test_install_refreshes_in_memory_manifest_version(tmp_path, install_env):
    """回归：更新后内存里的 `state.manifest.version` 必须跟着磁盘走。

    此前 `install_plugin_dir()` 只用 `os.replace` 换了目录，**从不刷新**
    `registry._states` 里的状态。于是 `catalog.check_updates()` 拿进程启动时
    读的旧版本去比远端版本，导致「刚更新完仍报有更新」的死循环——用户点更新、
    再检查又说有更新，其实磁盘早就是新版了。
    """

    installer_module.install_plugin_dir(_stage_versioned(tmp_path, '0.1.0', 'v1'))
    state = _cached_state(install_env)
    assert state.manifest.version == '0.1.0'

    result = installer_module.install_plugin_dir(_stage_versioned(tmp_path, '0.2.0', 'v2'))

    assert result['version'] == '0.2.0'
    assert result['action'] == 'update'
    assert state.manifest.version == '0.2.0', '内存 manifest 未随磁盘刷新'
    assert registry.get_state('zip-plugin').manifest.version == '0.2.0'


def test_install_marks_restart_required_and_does_not_reload_code(tmp_path, install_env):
    """刷新只覆盖「声明层」：置 `restart_required`，但不假装代码已热重载。

    设计文档 3.2 明确不进程内热重载（`importlib.reload` 的类身份变化、
    装饰器重复注册、蓝图路由冲突）。所以 `loaded` 不能被这次刷新改动。
    """

    installer_module.install_plugin_dir(_stage_versioned(tmp_path, '0.1.0', 'r1'))
    _cached_state(install_env, loaded=True)

    installer_module.install_plugin_dir(_stage_versioned(tmp_path, '0.2.0', 'r2'))

    refreshed = registry.get_state('zip-plugin')
    assert refreshed.restart_required is True, '更新后必须提示需重启'
    assert refreshed.loaded is True, '刷新不应改动 loaded（代码仍是旧的）'


def test_first_install_registers_state_for_restart(tmp_path, install_env):
    """首次安装（进程内无该插件）也要登记状态，UI 才能显示「需重启加载」。"""

    installer_module.install_plugin_dir(_stage_versioned(tmp_path, '0.3.0', 'fresh'))

    state = registry.get_state('zip-plugin')
    assert state is not None
    assert state.manifest.version == '0.3.0'
    assert state.restart_required is True


def test_refresh_manifest_survives_unreadable_directory(tmp_path, install_env):
    """刷新失败不应影响安装结果（目录被外力删掉时只警告，不抛错）。"""

    installer_module.install_plugin_dir(_stage_versioned(tmp_path, '0.1.0', 'x1'))

    assert registry.refresh_manifest('zip-plugin', str(tmp_path / 'does-not-exist')) is None
    assert registry.get_state('zip-plugin').manifest.version == '0.1.0'

def test_install_plugin_dir_records_audit_log(tmp_path, install_env):
    source = write_plugin(tmp_path / 'stage', 'zip-plugin')

    installer_module.install_plugin_dir(source, source_label='catalog:owner/repo')

    conn = job_store.connect(ensure_schema=True)
    try:
        rows = job_store.list_install_log(conn, 'zip-plugin')
    finally:
        conn.close()

    assert rows and rows[0]['action'] == 'install'
    assert rows[0]['source'] == 'catalog:owner/repo'
    assert rows[0]['success'] is True


def test_install_plugin_dir_persists_style_scope_errors(tmp_path, install_env):
    source = write_plugin(tmp_path / 'stage', 'zip-plugin', css='.card { border: 1px solid red; }\n')

    result = installer_module.install_plugin_dir(source)

    assert 'frontend/plugin.css' in result['style_scope_errors']
    assert 'frontend/plugin.css' in installer_module.read_style_scope_errors('zip-plugin')


def test_install_plugin_dir_persists_style_declaration_warnings(tmp_path, install_env):
    """F13：`position: fixed` 只记警告，**不拒绝安装**。"""
    source = write_plugin(
        tmp_path / 'stage', 'zip-plugin',
        css='.plugin-zip-plugin-launcher { position: fixed; }\n',
    )

    result = installer_module.install_plugin_dir(source)

    assert result['style_scope_errors'] == {}
    warnings = result['style_declaration_warnings']
    assert warnings['frontend/plugin.css']['position_fixed']
    assert installer_module.read_style_declaration_warnings('zip-plugin') == warnings
    # 与作用域错误是两个独立键，不能互相污染
    assert installer_module.read_style_scope_errors('zip-plugin') == {}


def test_install_plugin_dir_records_clean_declaration_warnings(tmp_path, install_env):
    source = write_plugin(tmp_path / 'stage', 'zip-plugin')

    result = installer_module.install_plugin_dir(source)

    assert result['style_declaration_warnings'] == {}
    assert installer_module.read_style_declaration_warnings('zip-plugin') == {}


def test_install_plugin_dir_scans_declarations_before_moving_source(tmp_path, install_env):
    """回归：声明层扫描同样必须在 `shutil.move` 之前完成，否则只会读到「读取失败」。"""
    css = '.plugin-zip-plugin-launcher { position: fixed; }\n'
    source = write_plugin(tmp_path / 'stage', 'zip-plugin', css=css)

    result = installer_module.install_plugin_dir(source)

    warnings = result['style_declaration_warnings']
    assert 'read_error' not in warnings.get('frontend/plugin.css', {})


def test_install_plugin_dir_scans_css_before_moving_source(tmp_path, install_env):
    """回归：作用域扫描必须在 `shutil.move` 之前做完。

    安装流程会把源目录整体移动/替换掉（`install_plugin_dir` 里的 `shutil.move`）。
    如果扫描发生在移动之后，manifest 上记的绝对路径已经失效，扫描只会返回
    `plugin.css: 读取失败 (...)`；那条假违规会被写进 ui_data，而前端
    `pluginHost.js:150-158` 会据此拒绝注入该插件的整份 CSS —— 一个完全合规的
    插件也会因此完全丢失样式。
    """
    scoped_css = '.plugin-zip-plugin-overlay { background: var(--surface-scrim); }\n'
    source = write_plugin(tmp_path / 'stage', 'zip-plugin', css=scoped_css)

    result = installer_module.install_plugin_dir(source)

    assert result['style_scope_errors'] == {}, result['style_scope_errors']
    assert installer_module.read_style_scope_errors('zip-plugin') == {}

    installed_css = os.path.join(result['path'], 'frontend', 'plugin.css')
    assert os.path.isfile(installed_css)
    with open(installed_css, 'r', encoding='utf-8') as handle:
        assert handle.read() == scoped_css


# ------------------------------------------------------------------ 上传与目录安装


class _FakeUpload:
    def __init__(self, source_path):
        self.filename = os.path.basename(source_path)
        self._source = source_path

    def save(self, destination):
        import shutil as _shutil

        _shutil.copy2(self._source, destination)


def test_install_from_upload_installs_plugin(tmp_path, install_env):
    archive_path = _write_plugin_zip(tmp_path / 'upload.zip', {'extra.txt': 'x'}, plugin_id='upload-plugin')

    result = installer_module.install_from_upload(_FakeUpload(str(archive_path)))

    assert result['id'] == 'upload-plugin'
    assert (install_env['plugins_root'] / 'upload-plugin' / 'manifest.json').is_file()


def test_install_from_upload_enforces_expected_id(tmp_path, install_env):
    """D9.3：上传路径此前不绑定 `expected_id`，与 catalog 路径不一致。"""
    archive_path = _write_plugin_zip(tmp_path / 'upload.zip', {'extra.txt': 'x'}, plugin_id='upload-plugin')

    with pytest.raises(PluginManifestError, match='预期'):
        installer_module.install_from_upload(
            _FakeUpload(str(archive_path)), expected_id='another-plugin',
        )

    assert not (install_env['plugins_root'] / 'upload-plugin').exists()


def test_install_from_upload_accepts_matching_expected_id(tmp_path, install_env):
    archive_path = _write_plugin_zip(tmp_path / 'upload.zip', {'extra.txt': 'x'}, plugin_id='upload-plugin')

    result = installer_module.install_from_upload(
        _FakeUpload(str(archive_path)), expected_id='upload-plugin',
    )

    assert result['id'] == 'upload-plugin'


def test_install_from_upload_ignores_blank_expected_id(tmp_path, install_env):
    archive_path = _write_plugin_zip(tmp_path / 'upload.zip', {'extra.txt': 'x'}, plugin_id='upload-plugin')

    result = installer_module.install_from_upload(
        _FakeUpload(str(archive_path)), expected_id='   ',
    )

    assert result['id'] == 'upload-plugin'


def test_install_from_upload_rejects_unsafe_archive(tmp_path, install_env):
    archive_path = _write_plugin_zip(tmp_path / 'evil.zip', {'../../evil.py': 'pwned'})

    with pytest.raises(PluginArchiveUnsafeError):
        installer_module.install_from_upload(_FakeUpload(str(archive_path)))

    assert not (tmp_path / 'evil.py').exists()


def test_install_from_upload_logs_failure(tmp_path, install_env):
    archive_path = _write_plugin_zip(tmp_path / 'evil.zip', {'../../evil.py': 'pwned'})

    with pytest.raises(PluginArchiveUnsafeError):
        installer_module.install_from_upload(_FakeUpload(str(archive_path)))

    conn = job_store.connect(ensure_schema=True)
    try:
        rows = job_store.list_install_log(conn, 'unknown')
    finally:
        conn.close()

    assert rows and rows[0]['success'] is False


def _stub_download(archive_path, monkeypatch, calls=None):
    def fake_download(url, dest_path, *, max_bytes=installer_module.MAX_DOWNLOAD_BYTES):
        import shutil as _shutil

        _shutil.copy2(archive_path, dest_path)
        if calls is not None:
            calls.append(url)
        return os.path.getsize(dest_path)

    monkeypatch.setattr(installer_module, 'download_archive', fake_download)


def test_install_from_catalog_downloads_extracts_and_installs(tmp_path, install_env, monkeypatch):
    archive_path = _write_plugin_zip(tmp_path / 'catalog.zip', {'extra.txt': 'x'}, plugin_id='catalog-plugin')
    calls = []
    _stub_download(archive_path, monkeypatch, calls)

    result = installer_module.install_from_catalog(None, {
        'id': 'catalog-plugin',
        'source': {'type': 'github', 'repo': 'owner/repo', 'ref': 'main'},
    })

    assert result['id'] == 'catalog-plugin'
    assert calls == ['https://codeload.github.com/owner/repo/zip/main']
    assert (install_env['plugins_root'] / 'catalog-plugin' / 'manifest.json').is_file()


def test_install_from_catalog_verifies_sha256(tmp_path, install_env, monkeypatch):
    archive_path = _write_plugin_zip(tmp_path / 'catalog.zip', {'extra.txt': 'x'}, plugin_id='catalog-plugin')
    _stub_download(archive_path, monkeypatch)
    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()

    result = installer_module.install_from_catalog(None, {
        'id': 'catalog-plugin',
        'source': {'type': 'github', 'repo': 'owner/repo', 'sha256': digest},
    })

    assert result['id'] == 'catalog-plugin'


def test_install_from_catalog_rejects_bad_sha256(tmp_path, install_env, monkeypatch):
    archive_path = _write_plugin_zip(tmp_path / 'catalog.zip', {'extra.txt': 'x'}, plugin_id='catalog-plugin')
    _stub_download(archive_path, monkeypatch)

    with pytest.raises(PluginInstallError, match='校验和不匹配'):
        installer_module.install_from_catalog(None, {
            'id': 'catalog-plugin',
            'source': {'type': 'github', 'repo': 'owner/repo', 'sha256': 'f' * 64},
        })

    assert not (install_env['plugins_root'] / 'catalog-plugin').exists()


def test_install_from_catalog_rejects_id_mismatch(tmp_path, install_env, monkeypatch):
    archive_path = _write_plugin_zip(tmp_path / 'catalog.zip', {'extra.txt': 'x'}, plugin_id='real-plugin')
    _stub_download(archive_path, monkeypatch)

    with pytest.raises(PluginManifestError, match='预期'):
        installer_module.install_from_catalog(None, {
            'id': 'claimed-plugin',
            'source': {'type': 'github', 'repo': 'owner/repo'},
        })


def test_install_from_catalog_rejects_unsupported_source_type(tmp_path, install_env):
    with pytest.raises(PluginInstallError, match='不支持的安装源'):
        installer_module.install_from_catalog(None, {
            'id': 'x',
            'source': {'type': 'ftp', 'repo': 'owner/repo'},
        })


def test_install_from_catalog_uses_subdir(tmp_path, install_env, monkeypatch):
    stage = tmp_path / 'stage'
    write_plugin(os.path.join(stage, 'packages', 'pack-a'), 'pack-a')

    archive_path = tmp_path / 'monorepo.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for current_root, _dirs, files in os.walk(stage):
            for name in files:
                full = os.path.join(current_root, name)
                archive.write(full, os.path.relpath(full, stage))

    _stub_download(archive_path, monkeypatch)

    result = installer_module.install_from_catalog(None, {
        'id': 'pack-a',
        'source': {'type': 'github', 'repo': 'owner/mono', 'subdir': 'packages/pack-a'},
    })

    assert result['id'] == 'pack-a'


# ------------------------------------------------------------------ 卸载


def test_uninstall_moves_to_trash_and_clears_data(tmp_path, install_env, monkeypatch):
    target = install_env['plugins_root'] / 'zip-plugin'
    write_plugin(install_env['plugins_root'], 'zip-plugin')

    # 写入配置与密钥，验证默认清理行为
    from core.data.ui_store import update_ui_data

    def mutator(ui_data):
        namespace = ui_data.setdefault('_plugins_v1', {})
        namespace.setdefault('zip-plugin', {})['config'] = {'greeting': 'x'}

    update_ui_data(mutator)
    secrets_module.set_secret('zip-plugin', 'api_key', 'sk-1234')

    result = installer_module.uninstall_plugin('zip-plugin')

    assert result['id'] == 'zip-plugin'
    assert not target.exists()
    assert os.path.isdir(result['trash'])
    assert registry.read_ui_entry('zip-plugin') == {}
    assert secrets_module.get_secret('zip-plugin', 'api_key') is None


def test_uninstall_keep_data_preserves_config_and_secrets(tmp_path, install_env):
    write_plugin(install_env['plugins_root'], 'zip-plugin')

    from core.data.ui_store import update_ui_data

    def mutator(ui_data):
        namespace = ui_data.setdefault('_plugins_v1', {})
        namespace.setdefault('zip-plugin', {})['config'] = {'greeting': 'keep'}

    update_ui_data(mutator)
    secrets_module.set_secret('zip-plugin', 'api_key', 'sk-keep')

    installer_module.uninstall_plugin('zip-plugin', keep_data=True)

    assert registry.read_ui_entry('zip-plugin').get('config') == {'greeting': 'keep'}
    assert secrets_module.get_secret('zip-plugin', 'api_key') == 'sk-keep'


def test_uninstall_cancels_active_jobs(tmp_path, install_env):
    from core.plugins import jobs

    write_plugin(install_env['plugins_root'], 'zip-plugin')

    conn = job_store.connect(ensure_schema=True)
    try:
        run_id = job_store.create_job(conn, 'zip-plugin', 'demo.run', ['a'])
        job_store.update_job(conn, run_id, status='running')
    finally:
        conn.close()

    result = installer_module.uninstall_plugin('zip-plugin')

    assert result['cancelled_jobs'] == 1
    conn = job_store.connect(ensure_schema=True)
    try:
        assert job_store.get_job(conn, run_id)['status'] == 'cancelled'
    finally:
        conn.close()
    jobs.reset_for_tests()


def test_uninstall_rejects_missing_plugin(tmp_path, install_env):
    with pytest.raises(PluginInstallError, match='插件目录不存在'):
        installer_module.uninstall_plugin('missing-plugin')


def test_uninstall_logs_action(tmp_path, install_env):
    write_plugin(install_env['plugins_root'], 'zip-plugin')

    installer_module.uninstall_plugin('zip-plugin')

    conn = job_store.connect(ensure_schema=True)
    try:
        rows = job_store.list_install_log(conn, 'zip-plugin')
    finally:
        conn.close()

    assert rows and rows[0]['action'] == 'uninstall'
