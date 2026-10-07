"""插件安装器（设计文档 3.2–3.6）。

从网络解压归档是**最高风险**的操作，逐项防护（3.4）：
- zip-slip：逐个 entry 校验 realpath 边界，**不用** `extractall()`
- 绝对路径 / 盘符：拒绝
- 符号链接：拒绝（`external_attr >> 16` 的 `S_ISLNK` 位）
- zip 炸弹：累计解压体积 ≤ 200MB、压缩比 ≤ 100:1、entry 数 ≤ 5000
- 磁盘空间：下载与解压前检查可用空间
- 供应链：强制 `manifest.id == catalog.id`
"""

import hashlib
import logging
import os
import re
import shutil
import stat
import time
import uuid
import zipfile

import requests

from core.config import TEMP_DIR, TRASH_FOLDER
from core.data.ui_store import update_ui_data
from core.plugins import job_store, registry
from core.plugins import secrets as secrets_store
from core.plugins.errors import (
    PluginArchiveUnsafeError,
    PluginInstallError,
    PluginManifestError,
)
from core.plugins.manifest import MANIFEST_FILENAME, PluginManifest
from core.utils.paths import is_under_base

logger = logging.getLogger(__name__)

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_ARCHIVE_ENTRIES = 5000
DOWNLOAD_TIMEOUT = (10, 60)
MAX_REDIRECTS = 3
DISK_SPACE_FACTOR = 3

REPO_PATTERN = re.compile(r'^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$')
REF_PATTERN = re.compile(r'^[A-Za-z0-9._/-]{1,200}$')
SHA_PATTERN = re.compile(r'^[0-9a-f]{7,40}$')

FORBIDDEN_DIR_NAMES = frozenset({'__pycache__', '.git', 'node_modules', '.venv', 'venv', '.idea', '.vscode'})

GITHUB_CODELOAD = 'https://codeload.github.com'


# ------------------------------------------------------------------ 输入校验


def validate_repo(repo: str) -> str:
    """校验 `owner/repo` 形式（拒绝任意 URL，防 SSRF）。"""
    value = str(repo or '').strip()
    if not REPO_PATTERN.match(value) or '..' in value:
        raise PluginInstallError(f'非法的仓库标识（只接受 owner/repo）: {repo!r}')
    return value


def validate_ref(ref: str, *, default: str = 'main') -> str:
    value = str(ref or '').strip() or default
    if not REF_PATTERN.match(value) or '..' in value:
        raise PluginInstallError(f'非法的 ref: {ref!r}')
    return value


def validate_subdir(subdir: str) -> str:
    value = str(subdir or '').strip().replace('\\', '/').strip('/')
    if not value:
        return ''
    if '..' in value.split('/') or value.startswith('/'):
        raise PluginInstallError(f'非法的 subdir: {subdir!r}')
    return value


def build_archive_url(repo: str, ref: str) -> str:
    """构造 GitHub 源码归档地址（域名固定，不接受任意 URL）。"""
    repo = validate_repo(repo)
    ref = validate_ref(ref)
    if SHA_PATTERN.match(ref):
        return f'{GITHUB_CODELOAD}/{repo}/zip/{ref}'
    return f'{GITHUB_CODELOAD}/{repo}/zip/refs/heads/{ref}'


# ------------------------------------------------------------------ 下载


def download_archive(url: str, dest_path: str, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> int:
    """流式下载归档，限制体积、超时与重定向次数。"""
    _ensure_free_space(os.path.dirname(dest_path) or TEMP_DIR, max_bytes)

    session = requests.Session()
    session.max_redirects = MAX_REDIRECTS
    written = 0
    try:
        with session.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT, allow_redirects=True) as response:
            if response.status_code != 200:
                raise PluginInstallError(f'下载失败: HTTP {response.status_code}')

            with open(dest_path, 'wb') as handle:
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > max_bytes:
                        raise PluginInstallError(f'归档超过下载上限（{max_bytes} 字节）')
                    handle.write(chunk)
    except requests.RequestException as exc:
        raise PluginInstallError(f'下载失败: {exc}') from exc
    finally:
        session.close()

    if written == 0:
        raise PluginInstallError('下载内容为空')
    return written


def _ensure_free_space(path: str, required_bytes: int) -> None:
    try:
        usage = shutil.disk_usage(path if os.path.isdir(path) else os.path.dirname(path))
    except OSError:
        return
    needed = max(int(required_bytes), 1) * DISK_SPACE_FACTOR
    if usage.free < needed:
        raise PluginInstallError(
            f'磁盘可用空间不足：需要约 {needed // (1024 * 1024)}MB，'
            f'当前剩余 {usage.free // (1024 * 1024)}MB'
        )


def file_sha256(path: str) -> str:
    """计算文件 sha256（小写十六进制）。"""
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def verify_sha256(path: str, expected: str) -> None:
    """校验归档 sha256；不匹配时抛 `PluginInstallError`。"""
    expected = str(expected or '').strip().lower()
    if not expected:
        return

    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise PluginInstallError(f'catalog 中的 sha256 格式非法: {expected!r}')

    actual = file_sha256(path)
    if actual != expected:
        raise PluginInstallError(f'归档校验和不匹配：期望 {expected}，实际 {actual}')


# ------------------------------------------------------------------ 解压


def _validate_archive_entry(info: zipfile.ZipInfo) -> None:
    name = str(info.filename or '')
    if not name:
        raise PluginArchiveUnsafeError('归档中存在空文件名')

    normalized = name.replace('\\', '/')
    if normalized.startswith('/') or os.path.isabs(normalized):
        raise PluginArchiveUnsafeError(f'归档中存在绝对路径: {name}')
    drive, _ = os.path.splitdrive(normalized)
    if drive:
        raise PluginArchiveUnsafeError(f'归档中存在盘符路径: {name}')
    if '..' in [part for part in normalized.split('/') if part]:
        raise PluginArchiveUnsafeError(f'归档中存在上级目录引用: {name}')

    mode = info.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise PluginArchiveUnsafeError(f'归档中不允许符号链接: {name}')


def safe_extract_archive(archive_path: str, dest_dir: str) -> str:
    """安全解压 zip 归档，返回解压目录。"""
    dest_dir = os.path.abspath(dest_dir)
    os.makedirs(dest_dir, exist_ok=True)
    real_dest = os.path.realpath(dest_dir)

    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        raise PluginArchiveUnsafeError(f'归档不是合法的 zip 文件: {exc}') from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_ENTRIES:
            raise PluginArchiveUnsafeError(f'归档条目过多（{len(infos)} > {MAX_ARCHIVE_ENTRIES}）')

        total_size = 0
        for info in infos:
            _validate_archive_entry(info)
            total_size += int(info.file_size or 0)
            if info.compress_size and info.file_size:
                ratio = info.file_size / max(1, info.compress_size)
                if ratio > MAX_COMPRESSION_RATIO:
                    raise PluginArchiveUnsafeError(
                        f'归档压缩比异常（{ratio:.1f}:1）: {info.filename}'
                    )
        if total_size > MAX_UNCOMPRESSED_BYTES:
            raise PluginArchiveUnsafeError(
                f'归档解压后体积过大（{total_size // (1024 * 1024)}MB）'
            )

        _ensure_free_space(dest_dir, total_size)

        for info in infos:
            target = os.path.realpath(os.path.join(dest_dir, info.filename.replace('\\', '/')))
            if not is_under_base(target, real_dest, resolve_symlinks=True):
                raise PluginArchiveUnsafeError(f'归档条目越出解压目录: {info.filename}')

            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue

            parent = os.path.dirname(target)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with archive.open(info) as source, open(target, 'wb') as handle:
                shutil.copyfileobj(source, handle)

    return dest_dir


# ------------------------------------------------------------------ 安装


def strip_forbidden_dirs(root: str) -> list:
    """剥离 `__pycache__` / `.git` / `node_modules` 等目录（2.1）。"""
    removed = []
    for current_root, dirs, _files in os.walk(root, topdown=True):
        for name in list(dirs):
            if name not in FORBIDDEN_DIR_NAMES:
                continue
            target = os.path.join(current_root, name)
            try:
                shutil.rmtree(target)
                removed.append(target)
            except OSError as exc:
                logger.warning('清理插件目录 %s 失败: %s', target, exc)
            dirs.remove(name)
    return removed


def locate_plugin_root(extract_dir: str, subdir: str = '') -> str:
    """在解压结果中定位插件根（含 `manifest.json` 的目录）。"""
    base = os.path.join(extract_dir, subdir.replace('/', os.sep)) if subdir else extract_dir
    if not os.path.isdir(base):
        raise PluginInstallError(f'归档中不存在子目录: {subdir}')

    if os.path.isfile(os.path.join(base, MANIFEST_FILENAME)):
        return base

    candidates = []
    for name in sorted(os.listdir(base)):
        candidate = os.path.join(base, name)
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, MANIFEST_FILENAME)):
            candidates.append(candidate)

    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise PluginInstallError('归档中未找到 manifest.json')
    raise PluginInstallError(f'归档中存在多个插件目录，请指定 subdir: {[os.path.basename(c) for c in candidates]}')


def install_plugin_dir(
    source_dir: str, *, expected_id: str = '', source_label: str = 'local',
) -> dict:
    """把已解压的插件目录安装到 `data/plugins/<id>/`（原子替换 + 回收站）。

    解压出的目录名不可控（GitHub 归档顶层是 `repo-branch`），因此这里不校验
    目录名与 id 一致；安装完成后目录会被重命名为 id。
    """
    source_dir = os.path.abspath(source_dir)
    manifest = PluginManifest.load(source_dir, expected_id=expected_id, check_dir_name=False)

    strip_forbidden_dirs(source_dir)

    plugins_root = registry.plugins_dir()
    os.makedirs(plugins_root, exist_ok=True)
    target_dir = os.path.join(plugins_root, manifest.plugin_id)

    staging_dir = os.path.join(plugins_root, f'.install-{manifest.plugin_id}-{uuid.uuid4().hex[:8]}')
    try:
        shutil.move(source_dir, staging_dir)
    except OSError as exc:
        raise PluginInstallError(f'准备安装目录失败: {exc}') from exc

    existed = os.path.isdir(target_dir)
    trash_path = ''
    try:
        if existed:
            trash_path = move_plugin_to_trash(manifest.plugin_id, target_dir=target_dir)
        os.replace(staging_dir, target_dir)
    except OSError as exc:
        # 回滚：尽量把 staging 挪回去，避免留下半成品
        if not os.path.isdir(target_dir) and os.path.isdir(staging_dir):
            try:
                os.replace(staging_dir, target_dir)
            except OSError:
                logger.error('安装回滚失败，残留目录 %s', staging_dir)
        raise PluginInstallError(f'安装目录替换失败: {exc}') from exc
    finally:
        if os.path.isdir(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)

    try:
        os.makedirs(os.path.join(target_dir, 'data'), exist_ok=True)
    except OSError:
        pass

    style_errors = scan_style_scope(manifest)
    if style_errors:
        _persist_style_scope_errors(manifest.plugin_id, style_errors)

    _log_action(
        manifest.plugin_id,
        'update' if existed else 'install',
        version=manifest.version,
        source=source_label,
        detail={'trash': trash_path, 'style_scope_errors': style_errors},
    )

    return {
        'id': manifest.plugin_id,
        'name': manifest.name,
        'version': manifest.version,
        'path': target_dir,
        'action': 'update' if existed else 'install',
        'trash': trash_path,
        'style_scope_errors': style_errors,
    }


def move_plugin_to_trash(plugin_id: str, *, target_dir: str = '') -> str:
    """把插件目录移入回收站（不直接删除，对齐既有约定）。"""
    source = target_dir or os.path.join(registry.plugins_dir(), plugin_id)
    if not os.path.isdir(source):
        return ''

    os.makedirs(TRASH_FOLDER, exist_ok=True)
    stamp = time.strftime('%Y%m%d%H%M%S')
    destination = os.path.join(TRASH_FOLDER, f'plugin_{plugin_id}_{stamp}')
    suffix = 1
    while os.path.exists(destination):
        destination = os.path.join(TRASH_FOLDER, f'plugin_{plugin_id}_{stamp}_{suffix}')
        suffix += 1

    shutil.move(source, destination)
    return destination


def install_from_catalog(app, entry: dict, *, ref: str = '', subdir: str = '') -> dict:
    """从 catalog 条目安装：下载 → 解压 → 校验 → 原子替换。"""
    source = entry.get('source') if isinstance(entry, dict) else None
    if not isinstance(source, dict):
        raise PluginInstallError('catalog 条目缺少 source')
    if str(source.get('type') or 'github') != 'github':
        raise PluginInstallError(f'不支持的安装源类型: {source.get("type")}')

    repo = validate_repo(source.get('repo'))
    effective_ref = validate_ref(ref or source.get('ref') or 'main')
    effective_subdir = validate_subdir(subdir or source.get('subdir') or '')
    expected_id = str(entry.get('id') or '').strip()

    os.makedirs(TEMP_DIR, exist_ok=True)
    work_dir = os.path.join(TEMP_DIR, f'plugin_install_{uuid.uuid4().hex[:12]}')
    os.makedirs(work_dir, exist_ok=True)
    archive_path = os.path.join(work_dir, 'plugin.zip')

    try:
        url = build_archive_url(repo, effective_ref)
        logger.info('开始下载插件归档: %s', url)
        download_archive(url, archive_path)

        expected_sha = str(source.get('sha256') or '').strip()
        if expected_sha:
            verify_sha256(archive_path, expected_sha)

        extract_dir = os.path.join(work_dir, 'extracted')
        safe_extract_archive(archive_path, extract_dir)

        plugin_root = locate_plugin_root(extract_dir, effective_subdir)
        result = install_plugin_dir(
            plugin_root, expected_id=expected_id, source_label=f'catalog:{repo}',
        )
    except Exception as exc:
        _log_action(
            expected_id or repo, 'install', source=f'catalog:{repo}',
            detail={'error': str(exc)}, success=False,
        )
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    return result


def install_from_upload(file_storage, *, source_label: str = 'upload') -> dict:
    """手动上传 zip 安装（离线兜底）。"""
    os.makedirs(TEMP_DIR, exist_ok=True)
    work_dir = os.path.join(TEMP_DIR, f'plugin_upload_{uuid.uuid4().hex[:12]}')
    os.makedirs(work_dir, exist_ok=True)
    archive_path = os.path.join(work_dir, 'plugin.zip')

    try:
        file_storage.save(archive_path)
        size = os.path.getsize(archive_path)
        if size > MAX_DOWNLOAD_BYTES:
            raise PluginInstallError(f'上传归档超过大小上限（{size} 字节）')

        extract_dir = os.path.join(work_dir, 'extracted')
        safe_extract_archive(archive_path, extract_dir)

        plugin_root = locate_plugin_root(extract_dir)
        return install_plugin_dir(plugin_root, source_label=source_label)
    except Exception as exc:
        _log_action('unknown', 'install', source=source_label, detail={'error': str(exc)}, success=False)
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def uninstall_plugin(plugin_id: str, *, keep_data: bool = False) -> dict:
    """卸载插件：取消作业 → 目录入回收站 → 默认清理配置与密钥。"""
    plugin_id = str(plugin_id or '').strip()
    state = registry.get_state(plugin_id)
    target_dir = state.plugin_dir if state is not None else os.path.join(registry.plugins_dir(), plugin_id)
    if not target_dir or not os.path.isdir(target_dir):
        raise PluginInstallError(f'插件目录不存在: {plugin_id}')

    version = state.manifest.version if (state is not None and state.manifest) else ''

    cancelled = cancel_plugin_jobs(plugin_id)
    trash_path = move_plugin_to_trash(plugin_id, target_dir=target_dir)

    cleared = {'ui_data': False, 'secrets': False}
    if not keep_data:
        cleared['ui_data'] = _clear_ui_namespace(plugin_id)
        cleared['secrets'] = secrets_store.clear_plugin_secrets(plugin_id)

    registry.drop_state(plugin_id)

    _log_action(
        plugin_id, 'uninstall', version=version, source='local',
        detail={'keep_data': bool(keep_data), 'trash': trash_path, 'cleared': cleared},
    )

    return {
        'id': plugin_id,
        'version': version,
        'trash': trash_path,
        'cancelled_jobs': cancelled,
        'cleared': cleared,
        'keep_data': bool(keep_data),
    }


def cancel_plugin_jobs(plugin_id: str) -> int:
    """协作式取消某插件的排队/运行/暂停作业。"""
    conn = job_store.connect(ensure_schema=True)
    try:
        placeholders = ','.join('?' for _ in job_store.ACTIVE_STATUSES)
        cursor = conn.execute(
            f'''
            UPDATE plugin_jobs
            SET status = 'cancelled', finished_at = ?, claim_token = ''
            WHERE plugin_id = ? AND status IN ({placeholders})
            ''',
            (time.time(), str(plugin_id), *job_store.ACTIVE_STATUSES),
        )
        conn.commit()
        return int(cursor.rowcount or 0)
    finally:
        conn.close()


def _clear_ui_namespace(plugin_id: str) -> bool:
    """卸载时默认清理 `ui_data._plugins_v1.<id>`（D10）。"""
    def mutator(ui_data):
        namespace = ui_data.get('_plugins_v1')
        if isinstance(namespace, dict):
            namespace.pop(plugin_id, None)

    return bool(update_ui_data(mutator))


def _log_action(
    plugin_id: str, action: str, *, version: str = '', source: str = '',
    detail: dict | None = None, success: bool = True,
) -> None:
    try:
        conn = job_store.connect(ensure_schema=True)
        try:
            job_store.log_install_action(
                conn, plugin_id, action,
                version=version, source=source, detail=detail or {}, success=success,
            )
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - 审计写入失败不影响主流程
        logger.warning('写入插件安装日志失败: %s %s', plugin_id, action, exc_info=True)


# ------------------------------------------------------------------ CSS 作用域


def scan_css_scope(css_path: str, plugin_id: str) -> list:
    """F11 静态检查：找出 CSS 顶层的裸选择器（未以插件作用域开头）。

    作用域根：`.plugin-<id>` 或 `[data-plugin="<id>"]`。
    分组规则（`@media` / `@supports` / `@layer` / `@container`）内部的选择器、
    以及 `@keyframes` / `@font-face` 内部的声明不做检查。
    """
    plugin_id = str(plugin_id or '')
    filename = os.path.basename(str(css_path or '')) or 'style.css'
    try:
        with open(css_path, 'r', encoding='utf-8') as handle:
            source = handle.read()
    except OSError as exc:
        return [f'{filename}: 读取失败 ({exc})']

    if not plugin_id:
        return [f'{filename}: 缺少插件 id']

    scope_tokens = (
        f'.plugin-{plugin_id}', f'[data-plugin="{plugin_id}"]', f"[data-plugin='{plugin_id}']",
    )

    violations = []
    stack = []
    buffer = []
    skip_blocks = 0
    index = 0
    length = len(source)

    while index < length:
        char = source[index]

        if char == '/' and index + 1 < length and source[index + 1] == '*':
            end = source.find('*/', index + 2)
            index = length if end == -1 else end + 2
            continue

        if char == '{':
            selector = ''.join(buffer).strip()
            buffer = []
            head = selector.split(None, 1)[0].lower() if selector else ''

            if head.startswith('@'):
                if head in ('@media', '@supports', '@layer', '@container', '@keyframes', '@font-face'):
                    skip_blocks += 1
                stack.append(head)
            else:
                if skip_blocks == 0 and selector and not any(token in selector for token in scope_tokens):
                    if not _is_keyframe_selector(selector):
                        violations.append(selector)
                stack.append('')
            index += 1
            continue

        if char == '}':
            if stack:
                head = stack.pop()
                if head.startswith('@') and head in (
                    '@media', '@supports', '@layer', '@container', '@keyframes', '@font-face',
                ):
                    skip_blocks = max(0, skip_blocks - 1)
            buffer = []
            index += 1
            continue

        buffer.append(char)
        index += 1

    return violations


def _is_keyframe_selector(selector: str) -> bool:
    """`0%` / `from` / `to` 这类关键帧步骤选择器。"""
    first = selector.split(',', 1)[0].strip().lower()
    return first in ('from', 'to') or bool(re.match(r'^\d+(\.\d+)?%$', first))


def scan_style_scope(manifest: PluginManifest) -> dict:
    """扫描插件声明的全部样式文件，返回 `{相对路径: [违规选择器]}`。"""
    result = {}
    for absolute_path in manifest.frontend_styles or []:
        violations = scan_css_scope(absolute_path, manifest.plugin_id)
        if not violations:
            continue
        relative = os.path.relpath(absolute_path, manifest.plugin_dir).replace('\\', '/')
        result[relative] = violations
        logger.warning(
            '插件 %s 的样式 %s 未通过作用域检查，将拒绝加载: %s',
            manifest.plugin_id, relative, violations[:5],
        )
    return result


def _persist_style_scope_errors(plugin_id: str, errors: dict) -> None:
    def mutator(ui_data):
        namespace = ui_data.get('_plugins_v1')
        if not isinstance(namespace, dict):
            namespace = {}
            ui_data['_plugins_v1'] = namespace
        entry = namespace.get(plugin_id)
        if not isinstance(entry, dict):
            entry = {}
            namespace[plugin_id] = entry
        entry['style_scope_errors'] = errors

    update_ui_data(mutator)


def read_style_scope_errors(plugin_id: str) -> dict:
    """读取某个插件未通过作用域检查的样式（供 `/api/plugins/list` 使用）。"""
    from core.data.ui_store import load_ui_data_or_empty

    ui_data = load_ui_data_or_empty()
    namespace = ui_data.get('_plugins_v1')
    if not isinstance(namespace, dict):
        return {}
    entry = namespace.get(str(plugin_id or ''))
    if not isinstance(entry, dict):
        return {}
    errors = entry.get('style_scope_errors')
    return errors if isinstance(errors, dict) else {}
