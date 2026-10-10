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
    clear_plugin_ui_namespace()
    secrets_module._clear_degraded()

    yield {
        'plugins_root': plugins_root,
        'trash_root': trash_root,
        'temp_root': temp_root,
        'tmp_path': tmp_path,
    }

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
    assert installer_module.build_archive_url('owner/repo', 'main') == (
        'https://codeload.github.com/owner/repo/zip/refs/heads/main'
    )
    assert installer_module.build_archive_url('owner/repo', 'abc1234') == (
        'https://codeload.github.com/owner/repo/zip/abc1234'
    )


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
    assert calls == ['https://codeload.github.com/owner/repo/zip/refs/heads/main']
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
