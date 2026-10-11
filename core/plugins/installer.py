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
import threading
import time
import uuid
import zipfile

import requests

from core.config import INTERNAL_DIR, TEMP_DIR, TRASH_FOLDER
from core.data.ui_store import ENTRY_LAYOUT_KEY, update_ui_data
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
# 注：不再需要单独的 commit-sha 正则——裸 `zip/<ref>` 同时支持分支 / tag / sha

FORBIDDEN_DIR_NAMES = frozenset({'__pycache__', '.git', 'node_modules', '.venv', 'venv', '.idea', '.vscode'})

#: 插件私有数据目录名（`PluginAPI.data_dir()` 承诺的位置，更新时必须保留，D4）
PLUGIN_DATA_DIRNAME = 'data'

#: 新包携带的同名文件与用户数据冲突时的改名备份后缀（D4.2）
PLUGIN_DEFAULT_SUFFIX = '.plugin-default'

GITHUB_CODELOAD = 'https://codeload.github.com'


# ------------------------------------------------------------------ 输入校验


def validate_repo(repo: str) -> str:
    """校验 `owner/repo` 形式（拒绝任意 URL，防 SSRF）。"""
    value = str(repo or '').strip()
    if not REPO_PATTERN.match(value) or '..' in value:
        raise PluginInstallError(f'非法的仓库标识（只接受 owner/repo）: {repo!r}')
    return value


def validate_ref(ref: str, *, default: str = 'main') -> str:
    """校验分支 / tag / commit sha 名。

    `ref` 会被拼进 codeload URL，因此除了正则白名单还要挡住：
    - 前导 `/`（会拼出 `zip//etc/passwd` 这样的双斜杠路径）
    - `..` 路径穿越
    - 空段（`a//b`）
    """
    value = str(ref or '').strip() or default
    if not REF_PATTERN.match(value) or '..' in value:
        raise PluginInstallError(f'非法的 ref: {ref!r}')
    if value.startswith('/') or value.endswith('/') or '//' in value:
        raise PluginInstallError(f'非法的 ref（路径形状）: {ref!r}')
    return value


def validate_subdir(subdir: str) -> str:
    value = str(subdir or '').strip().replace('\\', '/').strip('/')
    if not value:
        return ''
    if '..' in value.split('/') or value.startswith('/'):
        raise PluginInstallError(f'非法的 subdir: {subdir!r}')
    return value


def build_archive_url(repo: str, ref: str) -> str:
    """构造 GitHub 源码归档地址（域名固定，不接受任意 URL）。

    **不依赖 git**：走 GitHub 的 codeload 归档接口拿源码 zip，因此无需
    `git clone`，也不需要 GitHub API（不消耗 API 配额、不受限流影响）。

    三种 URL 形式的实测结果（HEAD 探测，见下表）决定了这里的写法：

    | ref 类型            | `zip/refs/heads/<ref>` | `zip/refs/tags/<ref>` | `zip/<ref>` |
    |---------------------|------------------------|-----------------------|-------------|
    | 分支 `main`         | 200                    | 404                   | **200**     |
    | tag `v2.31.0`       | **404**                | 200                   | **200**     |
    | commit sha          | —                      | —                     | **200**     |

    `refs/heads/` 只解析分支，`refs/tags/` 只解析 tag，**只有裸 `zip/<ref>`
    两者都能解析**。此前只用 `refs/heads/<ref>`，导致传 tag 必然 404
    （`stable` 渠道按 Release tag 更新时会踩到）。
    """
    repo = validate_repo(repo)
    ref = validate_ref(ref)
    return f'{GITHUB_CODELOAD}/{repo}/zip/{ref}'


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

    **更新保留 `data/`（D4）**：更新在本项目里就是重新安装，旧目录会整体进回收站。
    插件私有数据目录（`api.data_dir()` 承诺的 `data/plugins/<id>/data/`）因此在
    `os.replace` **之前**移出、替换后**合并**回来，否则「更新一次丢一次用户数据」。
    合并规则见 `_merge_preserved_data()`：**用户数据优先**，冲突项备份为新包那份的
    `<name>.plugin-default`。迁移失败只 warning，**绝不阻断安装**。
    """
    source_dir = os.path.abspath(source_dir)
    manifest = PluginManifest.load(source_dir, expected_id=expected_id, check_dir_name=False)

    strip_forbidden_dirs(source_dir)

    # 必须在 `shutil.move` **之前**扫描：manifest 里的样式路径指向源目录，目录一旦被
    # 移走，扫描就只剩「读取失败」，而那条假违规会被持久化，导致前端拒绝注入该插件的
    # 整份 CSS（pluginHost.js:150-158）。
    style_errors = scan_style_scope(manifest)

    # 声明层检查（F13 / F15）：只 warning，不阻止安装，因此单独一个命名空间键
    style_warnings = scan_style_declarations(manifest)

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
    preserved = {'preserved': 0, 'conflicts': []}
    preserved_dir = ''
    try:
        if existed:
            # 先把用户数据移出待替换的旧目录（D4.2）。必须在 `move_plugin_to_trash`
            # 之前，否则旧 `data/` 会随旧目录一起进回收站。
            preserved_dir = _preserve_plugin_data(staging_dir, target_dir)
            trash_path = move_plugin_to_trash(manifest.plugin_id, target_dir=target_dir)
        os.replace(staging_dir, target_dir)
    except OSError as exc:
        # 回滚：尽量把 staging 挪回去，避免留下半成品
        if not os.path.isdir(target_dir) and os.path.isdir(staging_dir):
            try:
                os.replace(staging_dir, target_dir)
            except OSError:
                logger.error('安装回滚失败，残留目录 %s', staging_dir)
        if preserved_dir:
            # 回滚同理优先保数据。只在目录确实回滚成功时合并，避免凭空造出一个
            # 没有 manifest 的插件目录；否则把临时目录路径留在日志里供手工找回。
            if os.path.isdir(target_dir):
                logger.warning('安装失败，尝试把已移出的用户数据合并回 %s', target_dir)
                _merge_preserved_data(preserved_dir, target_dir)
            else:
                logger.error(
                    '安装失败且目录未回滚，用户数据仍在 %s', preserved_dir,
                )
        raise PluginInstallError(f'安装目录替换失败: {exc}') from exc
    finally:
        if os.path.isdir(staging_dir):
            shutil.rmtree(staging_dir, ignore_errors=True)

    try:
        os.makedirs(os.path.join(target_dir, PLUGIN_DATA_DIRNAME), exist_ok=True)
    except OSError:
        pass

    if preserved_dir:
        preserved = _merge_preserved_data(preserved_dir, target_dir)

    if style_errors:
        _persist_style_scope_errors(manifest.plugin_id, style_errors)

    _persist_style_declaration_warnings(manifest.plugin_id, style_warnings)

    # 关键：把磁盘上的新 manifest 同步进内存状态。
    # 否则 `state.manifest.version` 会停在进程启动时读的旧值，`check_updates()`
    # 就会拿陈旧版本比远端版本，导致「刚更新完仍报有更新」的死循环。
    # 这里不重载代码（模块已在 sys.modules，热重载有类身份/蓝图重复注册的陷阱），
    # 只刷新声明层并置 `restart_required`，让 UI 如实提示需重启。
    registry.refresh_manifest(manifest.plugin_id, target_dir)

    _log_action(
        manifest.plugin_id,
        'update' if existed else 'install',
        version=manifest.version,
        source=source_label,
        detail={
            'trash': trash_path,
            'preserved_data': preserved['preserved'],
            'preserved_data_conflicts': preserved['conflicts'],
            'style_scope_errors': style_errors,
            'style_declaration_warnings': style_warnings,
        },
    )

    return {
        'id': manifest.plugin_id,
        'name': manifest.name,
        'version': manifest.version,
        'path': target_dir,
        'action': 'update' if existed else 'install',
        'trash': trash_path,
        'preserved_data': preserved['preserved'],
        'preserved_data_conflicts': preserved['conflicts'],
        'style_scope_errors': style_errors,
        'style_declaration_warnings': style_warnings,
    }


def _preserve_plugin_data(staging_dir: str, target_dir: str) -> str:
    """把旧插件目录的 `data/` 移到 staging 同级临时位置，返回该路径。

    与 staging 同级（同一插件根内）可保证同卷，`os.replace` 不受跨卷限制。
    旧目录没有 `data/` 时返回 `''`。

    失败（跨卷 / 权限 / 占用）时只记 warning 并返回 `''`——**数据迁移失败不得
    阻断安装**，最坏情况退化成改动前的行为（用户数据随旧目录进回收站，仍可手工找回）。
    """
    source = os.path.join(target_dir, PLUGIN_DATA_DIRNAME)
    if not os.path.isdir(source):
        return ''

    preserved_dir = os.path.join(
        os.path.dirname(staging_dir) or '.',
        f'.preserved-{os.path.basename(target_dir)}-{uuid.uuid4().hex[:8]}',
    )
    try:
        shutil.move(source, preserved_dir)
    except OSError as exc:
        logger.warning('保留插件 %s 的 data 目录失败（继续安装）: %s', target_dir, exc)
        return ''
    return preserved_dir


def _merge_preserved_data(preserved_dir: str, target_dir: str) -> dict:
    """把保留的用户数据合并回新插件目录的 `data/`。

    返回 `{'preserved': int, 'conflicts': list}`。

    合并规则（D4.2，**核心是「新包不得静默覆盖用户数据」**）：
    - 目标不存在同名项 → 用户那份直接移入（计入 `preserved`）。
    - 两边都是目录 → 递归合并，逐项套用同样的规则。
    - 目标已存在同名项（文件，或「用户是文件 / 包内是目录」这类形状冲突）→
      **用户数据优先**：把**包内那份**改名备份为 `<name>.plugin-default`
      （同名备份已存在时追加数字后缀），再把用户那份放到原名，并记入 `conflicts`。

    迁移失败只记日志，**绝不阻断安装**；此时保留临时目录（里面是尚未搬回的用户
    数据）并把路径写进日志供手工找回，而不是在失败路径上删除用户数据。

    `conflicts` 里存的是备份项的**相对 `data/` 的名称**（用 `/` 归一），只用于日志。
    """
    result = {'preserved': 0, 'conflicts': []}
    if not os.path.isdir(preserved_dir):
        return result

    destination = os.path.join(target_dir, PLUGIN_DATA_DIRNAME)
    try:
        os.makedirs(destination, exist_ok=True)
    except OSError as exc:
        logger.error(
            '插件 %s 的 data 目录不可用，%s 中的用户数据未迁移: %s',
            os.path.basename(target_dir), preserved_dir, exc,
        )
        return result

    try:
        merged_preserved, merged_conflicts = _merge_tree(preserved_dir, destination)
        result['preserved'] = merged_preserved
        result['conflicts'] = merged_conflicts

        if merged_conflicts:
            logger.warning(
                '插件 %s 更新时有 %s 个同名项与包内文件冲突，已保留用户数据并把包内那份备份为 %s',
                os.path.basename(target_dir), len(merged_conflicts), PLUGIN_DEFAULT_SUFFIX,
            )
    except OSError as exc:
        # 迁移中断：**保留**临时目录（里面是尚未搬回的用户数据），只记路径供手工找回，
        # 绝不在失败路径上删除用户数据。
        logger.error(
            '插件 %s 的用户数据迁移未完成，剩余数据仍在 %s: %s',
            os.path.basename(target_dir), preserved_dir, exc,
        )
        return result

    shutil.rmtree(preserved_dir, ignore_errors=True)
    return result


def _merge_tree(source_dir: str, target_dir: str) -> tuple:
    """递归合并 `source_dir`（用户数据）到 `target_dir`（新装插件）。

    返回 `(移入的文件数, 冲突备份列表)`；冲突时始终**用户数据留在原名**。
    """
    preserved = 0
    conflicts = []

    for name in sorted(os.listdir(source_dir)):
        source = os.path.join(source_dir, name)
        target = os.path.join(target_dir, name)
        # `lexists`：目标位置有个断链符号链接时也算被占用，避免覆盖式写入
        occupied = os.path.lexists(target)

        if not occupied:
            preserved += _move_entry(source, target)
            continue

        if os.path.isdir(source) and not os.path.islink(source) and os.path.isdir(target):
            nested_preserved, nested_conflicts = _merge_tree(source, target)
            preserved += nested_preserved
            conflicts.extend(nested_conflicts)
            continue

        # 冲突：先把包内那份备份走，再把用户那份放回原名。
        # 备份成功但用户那份移动失败时，目标位置会留下缺口——把备份移回去补上，
        # 避免为了保数据反而弄坏插件目录。
        backup = _backup_plugin_default(target)
        conflicts.append(os.path.basename(backup).replace('\\', '/'))
        try:
            preserved += _move_entry(source, target)
        except OSError:
            _restore_plugin_default(backup, target)
            raise

    return preserved, conflicts


def _restore_plugin_default(backup: str, target: str) -> None:
    """把已备份的包内文件移回 `target`（用户数据迁移失败时的回补）。"""
    try:
        if os.path.exists(target) or not os.path.exists(backup):
            return
        shutil.move(backup, target)
        logger.warning('用户数据迁移失败，已把包内文件还原到 %s', target)
    except OSError as exc:
        logger.error('还原包内文件 %s 失败，副本仍在 %s: %s', target, backup, exc)


def _move_entry(source: str, target: str) -> int:
    """移动一个条目（文件或整棵子树），返回其中的文件数（空目录计 1）。"""
    if os.path.isdir(source) and not os.path.islink(source):
        count = sum(len(files) for _root, _dirs, files in os.walk(source))
    else:
        count = 1

    shutil.move(source, target)
    return max(1, count)


def _backup_plugin_default(target: str) -> str:
    """把新包携带的冲突项改名备份为 `<target>.plugin-default`，返回备份的完整路径。

    备份名已被占用时追加 `.2` / `.3`…，**任何同名文件都不覆盖**——已经躺在那里的
    备份同样是磁盘上的数据。

    命名以**原始文件名**为基准（`providers.json.plugin-default` → 下一个是
    `providers.json.plugin-default.2`），避免连续更新时套娃成
    `.plugin-default.plugin-default`。
    """
    prefix = re.sub(r'(\.plugin-default)(\.\d+)?$', '', str(target))
    backup = f'{prefix}{PLUGIN_DEFAULT_SUFFIX}'
    if os.path.lexists(backup):
        suffix = 2
        while os.path.lexists(f'{prefix}{PLUGIN_DEFAULT_SUFFIX}.{suffix}'):
            suffix += 1
        backup = f'{prefix}{PLUGIN_DEFAULT_SUFFIX}.{suffix}'

    shutil.move(target, backup)
    return backup


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


def install_from_upload(
    file_storage, *, source_label: str = 'upload', expected_id: str = '',
) -> dict:
    """手动上传 zip 安装（离线兜底）。

    `expected_id` 由上传界面可选填写：填了就校验归档里的 `manifest.id` 是否一致，
    不一致时按 `PluginManifest.load(expected_id=...)` 的语义**拒绝**（与 catalog 路径
    对齐，见 `install_from_catalog`）；留空则完全以归档内的 id 为准。
    """
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
        return install_plugin_dir(
            plugin_root,
            expected_id=str(expected_id or '').strip(),
            source_label=source_label,
        )
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
    """卸载时默认清理 `ui_data._plugins_v1.<id>`（D10）。

    同时剪除入口布局偏好（`ui_data._entry_layout_v1`）中属于该插件的键：
    禁用只让入口消失、偏好保留；卸载才真正丢弃，避免 `_entry_layout_v1`
    被已卸载插件的条目永久占位（D6）。
    """
    prefix = f'{plugin_id}:'

    def mutator(ui_data):
        namespace = ui_data.get('_plugins_v1')
        if isinstance(namespace, dict):
            namespace.pop(plugin_id, None)

        layout = ui_data.get(ENTRY_LAYOUT_KEY)
        if not isinstance(layout, dict):
            return

        for key in ('order', 'pinned', 'hidden'):
            values = layout.get(key)
            if isinstance(values, list):
                layout[key] = [
                    item for item in values
                    if not (isinstance(item, str) and item.startswith(prefix))
                ]

        shortcuts = layout.get('shortcuts')
        if isinstance(shortcuts, dict):
            layout['shortcuts'] = {
                combo: target for combo, target in shortcuts.items()
                if not (isinstance(target, str) and target.startswith(prefix))
            }

        groups = layout.get('groups')
        if isinstance(groups, dict):
            layout['groups'] = {
                name: [item for item in members if not (isinstance(item, str) and item.startswith(prefix))]
                if isinstance(members, list) else members
                for name, members in groups.items()
            }

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


# --------------------------------------------------------- CSS 声明层静态检查


#: 声明层检查的分类（与设计文档 F13 / F15 一一对应；`read_error` 用于读取失败）
STYLE_DECLARATION_CATEGORIES = (
    'position_fixed', 'unknown_tokens', 'important', 'hardcoded_sprite', 'read_error',
)

#: 分组 at-rule：内部选择器**仍需检查**（与 `scan_css_scope` 的 skip_blocks 相反）
_GROUPING_AT_RULES = ('@media', '@supports', '@layer', '@container')

#: 内部不是选择器的 at-rule：整棵子树跳过
_OPAQUE_AT_RULES = ('@keyframes', '@font-face')

_VAR_REFERENCE_PATTERN = re.compile(r'var\(')

#: 宿主 sprite 引用（F15）：插件不得硬编码 `url('/static/icons/ui.svg#icon-x')`
_SPRITE_REFERENCE_PATTERN = re.compile(
    r'/static/icons/|(?<![\w/-])icons/(?:ui|detail|sidebar|preset)\.svg'
)

_VARIABLES_PATH = os.path.join('static', 'css', 'modules', 'variables.css')

_known_tokens_cache = None
_known_tokens_lock = threading.RLock()


def _parse_css_blocks(source: str) -> dict:
    """把 CSS 源码解析成嵌套块树（注释已剔除）。

    每个节点形如 `{'prelude': str, 'at': str, 'children': list, 'decls': list}`；
    `decls` 是直接位于该块内的 `prop: value` 文本。
    """
    root = {'prelude': '', 'at': '', 'children': [], 'decls': []}
    stack = [root]
    buffer = []
    index = 0
    length = len(source)

    while index < length:
        char = source[index]

        if char == '/' and index + 1 < length and source[index + 1] == '*':
            end = source.find('*/', index + 2)
            index = length if end == -1 else end + 2
            continue

        if char == '{':
            prelude = ''.join(buffer).strip()
            buffer = []
            head = prelude.split(None, 1)[0].lower() if prelude else ''
            node = {
                'prelude': prelude,
                'at': head if head.startswith('@') else '',
                'children': [],
                'decls': [],
            }
            stack[-1]['children'].append(node)
            stack.append(node)
            index += 1
            continue

        if char in '};':
            text = ''.join(buffer).strip()
            if text:
                stack[-1]['decls'].append(text)
            buffer = []
            if char == '}' and len(stack) > 1:
                stack.pop()
            index += 1
            continue

        buffer.append(char)
        index += 1

    tail = ''.join(buffer).strip()
    if tail:
        stack[-1]['decls'].append(tail)
    return root


def _selector_is_scoped(selector: str, plugin_id: str) -> bool:
    """选择器是否以插件作用域开头（`.plugin-<id>` 或 `[data-plugin="<id>"]`）。"""
    tokens = (
        f'.plugin-{plugin_id}', f'[data-plugin="{plugin_id}"]', f"[data-plugin='{plugin_id}']",
    )
    return any(token in selector for token in tokens)


def _iter_var_references(value: str):
    """产出 `var(--x)` 引用：`(名字, 是否有回退值)`。"""
    text = str(value or '')
    index = 0

    while True:
        start = text.find('var(', index)
        if start == -1:
            return

        position = start + 4
        depth = 0
        has_fallback = False
        name_chars = []
        while position < len(text):
            char = text[position]
            if char == '(':
                depth += 1
            elif char == ')':
                if depth == 0:
                    break
                depth -= 1
            elif char == ',' and depth == 0:
                has_fallback = True
            elif depth == 0 and not has_fallback:
                name_chars.append(char)
            position += 1

        name = ''.join(name_chars).strip()
        if name.startswith('--'):
            yield name, has_fallback
        index = max(position + 1, start + 4)


def resolve_known_tokens() -> frozenset:
    """宿主 CSS 令牌清单（从 `variables.css` 解析，进程内缓存）。

    PyInstaller 打包态 `static/` 只读，因此从 `INTERNAL_DIR` 读取。
    """
    global _known_tokens_cache
    with _known_tokens_lock:
        if _known_tokens_cache is not None:
            return _known_tokens_cache

        path = os.path.join(str(INTERNAL_DIR), _VARIABLES_PATH)
        tokens = set()
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                source = handle.read()
        except OSError as exc:
            logger.warning('读取宿主 CSS 令牌失败 %s: %s', path, exc)
            _known_tokens_cache = frozenset()
            return _known_tokens_cache

        def walk(node):
            for decl in node['decls']:
                name = decl.split(':', 1)[0].strip()
                if name.startswith('--'):
                    tokens.add(name)
            for child in node['children']:
                walk(child)

        walk(_parse_css_blocks(source))
        _known_tokens_cache = frozenset(tokens)
        return _known_tokens_cache


def reset_known_tokens_for_tests() -> None:
    """清空令牌缓存（仅测试使用）。"""
    global _known_tokens_cache
    with _known_tokens_lock:
        _known_tokens_cache = None


def scan_css_declarations(css_path: str, plugin_id: str, *, known_tokens=None) -> dict:
    """F13 / F15 静态检查：找出声明层的四类问题（**不拒绝加载**，只 warning）。

    与 `scan_css_scope` 的关键差异：本函数**必须进入** `@media` / `@supports` /
    `@layer` / `@container` 内部的选择器（移动端与主题分支里的 `position: fixed`
    同样是浮层，漏掉就等于没检查）；只跳过 `@keyframes` / `@font-face` 内部。

    Returns:
        `{分类: [人类可读消息]}`，只包含命中的分类；全部合规时返回 `{}`。
    """
    plugin_id = str(plugin_id or '')
    filename = os.path.basename(str(css_path or '')) or 'style.css'
    try:
        with open(css_path, 'r', encoding='utf-8') as handle:
            source = handle.read()
    except OSError as exc:
        return {'read_error': [f'{filename}: 读取失败 ({exc})']}

    if not plugin_id:
        return {'read_error': [f'{filename}: 缺少插件 id']}

    if known_tokens is None:
        known_tokens = resolve_known_tokens()

    findings = {category: [] for category in STYLE_DECLARATION_CATEGORIES}
    root = _parse_css_blocks(source)

    def walk(node, selector: str):
        for decl in node['decls']:
            prop, _, raw_value = decl.partition(':')
            prop = prop.strip().lower()
            value = raw_value.strip()
            if not prop or not value:
                continue

            if prop == 'position' and value.split(None, 1)[0].lower() == 'fixed':
                findings['position_fixed'].append(
                    f'{selector or "顶层"} 使用 position: fixed，应改用宿主提供的 surface 容器'
                )

            if '!important' in value.lower() and not _selector_is_scoped(selector, plugin_id):
                findings['important'].append(
                    f'{selector or "顶层"} 在非作用域选择器上使用 !important'
                )

            if _SPRITE_REFERENCE_PATTERN.search(value):
                findings['hardcoded_sprite'].append(
                    f'{selector or "顶层"} 硬编码了宿主图标 sprite 路径：{value}'
                )

            for name, has_fallback in _iter_var_references(value):
                if has_fallback or name in known_tokens:
                    continue
                findings['unknown_tokens'].append(
                    f'{selector or "顶层"} 引用了未知令牌 {name} 且没有回退值'
                )

        for child in node['children']:
            head = child['at']
            if head in _OPAQUE_AT_RULES:
                continue
            if head:
                # 分组 at-rule：条件不是选择器，继承外层选择器继续下探
                walk(child, selector)
            else:
                walk(child, child['prelude'])

    for child in root['children']:
        if child['at'] in _OPAQUE_AT_RULES:
            continue
        if child['at']:
            walk(child, '')
        else:
            walk(child, child['prelude'])

    return {category: items for category, items in findings.items() if items}


def scan_style_declarations(manifest: PluginManifest, *, known_tokens=None) -> dict:
    """扫描插件声明的全部样式，返回 `{相对路径: {分类: [消息]}}`。"""
    result = {}
    for absolute_path in manifest.frontend_styles or []:
        findings = scan_css_declarations(
            absolute_path, manifest.plugin_id, known_tokens=known_tokens,
        )
        if not findings:
            continue
        relative = os.path.relpath(absolute_path, manifest.plugin_dir).replace('\\', '/')
        result[relative] = findings
        logger.warning(
            '插件 %s 的样式 %s 存在声明层问题（不阻止加载）: %s',
            manifest.plugin_id, relative,
            {category: len(items) for category, items in findings.items()},
        )
    return result


def _persist_style_declaration_warnings(plugin_id: str, warnings: dict) -> None:
    def mutator(ui_data):
        namespace = ui_data.get('_plugins_v1')
        if not isinstance(namespace, dict):
            namespace = {}
            ui_data['_plugins_v1'] = namespace
        entry = namespace.get(plugin_id)
        if not isinstance(entry, dict):
            entry = {}
            namespace[plugin_id] = entry
        entry['style_declaration_warnings'] = warnings

    update_ui_data(mutator)


def read_style_declaration_warnings(plugin_id: str) -> dict:
    """读取某个插件的声明层检查结果（供 `/api/plugins/list` 使用）。"""
    from core.data.ui_store import load_ui_data_or_empty

    ui_data = load_ui_data_or_empty()
    namespace = ui_data.get('_plugins_v1')
    if not isinstance(namespace, dict):
        return {}
    entry = namespace.get(str(plugin_id or ''))
    if not isinstance(entry, dict):
        return {}
    warnings = entry.get('style_declaration_warnings')
    return warnings if isinstance(warnings, dict) else {}
