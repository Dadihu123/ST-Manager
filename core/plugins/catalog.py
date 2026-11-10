"""官方插件目录（设计文档 3.1–3.3，D11 方案 B）。

- 包内兜底清单：`static/plugins/catalog.json`（随包分发）。
- 远端拉取：用户打开「官方目录」页签时才拉，成功缓存 6 小时（可配置）。
- 拉取失败或关闭远端：回退包内清单并标记 `offline`。
- 安全约束：catalog 中的 `source.repo` 必须是 `owner/repo`，由应用拼成 GitHub
  官方域名，**不接受任意 URL**（防 SSRF）。
"""

import json
import logging
import os
import re
import time

import requests

from core.config import INTERNAL_DIR, SYSTEM_DIR, load_config
from core.plugins import changelog as changelog_module
from core.plugins import registry
from core.plugins.errors import PluginCatalogError
from core.plugins.manifest import compare_versions, parse_semver
from core.version import APP_VERSION

logger = logging.getLogger(__name__)

CATALOG_SCHEMA_VERSION = 3
CATALOG_RELATIVE_PATH = os.path.join('static', 'plugins', 'catalog.json')

# 归属分级（D5 / ADR-0008）：只披露信任级别，不再限制贡献类型。
# tier 只能由宿主仓库的 catalog 决定，插件 manifest 无权声明。
PLUGIN_TIERS = ('official', 'verified', 'community')
DEFAULT_PLUGIN_TIER = 'community'

CACHE_DIR = os.path.join(SYSTEM_DIR, 'plugins')
CACHE_FILE = os.path.join(CACHE_DIR, '_catalog_cache.json')

DEFAULT_CACHE_HOURS = 6
UPDATES_CACHE_HOURS = 24
REQUEST_TIMEOUT = (10, 30)
MAX_CATALOG_BYTES = 512 * 1024
# 远端 CHANGELOG 的体积上限：只用来切「本次更新说明」，不需要整本历史
MAX_CHANGELOG_BYTES = 256 * 1024
# 单条更新说明的体积上限（进缓存文件，也进接口响应）：按 UTF-8 字节算。
# 16KB 而不是 8KB：实测真实插件「上一版→这一版」的说明是 11.5KB（0.4.0→0.4.1，
# 最常见的升级路径），8KB 只能覆盖 71%，用户读到的就是半句话。缓存文件里只放
# 「已安装且目录里有更新」的插件（当前 2 个官方插件），16KB × 2 = 32KB，对
# `_catalog_cache.json` 完全可接受。
MAX_RELEASE_NOTES_BYTES = 16 * 1024

REPO_PATTERN = re.compile(r'^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$')
TAG_PATTERN = re.compile(r'^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?')


def normalize_tier(raw_tier) -> str:
    """把 catalog 的 `tier` 归一化为已知分级；未知值按 `community`（安全的一侧）。"""
    value = str(raw_tier or '').strip().lower()
    if value in PLUGIN_TIERS:
        return value
    if value:
        logger.warning('忽略未知的插件归属分级 %r（按 community 处理）', raw_tier)
    return DEFAULT_PLUGIN_TIER


def bundled_catalog_path() -> str:
    """包内兜底清单路径（兼容 PyInstaller 的 `sys._MEIPASS`）。"""
    return os.path.join(str(INTERNAL_DIR), CATALOG_RELATIVE_PATH)


def load_bundled_catalog() -> dict:
    """读取包内清单；缺失或损坏时返回空清单。"""
    path = bundled_catalog_path()
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning('读取包内插件目录失败 %s: %s', path, exc)
        return {'schema_version': CATALOG_SCHEMA_VERSION, 'plugins': []}
    return parse_catalog(payload)


def parse_catalog(payload) -> dict:
    """校验并规范化 catalog；非法条目被丢弃并记警告。"""
    if not isinstance(payload, dict):
        raise PluginCatalogError('catalog 顶层必须是对象')

    raw_plugins = payload.get('plugins')
    if not isinstance(raw_plugins, list):
        raw_plugins = []

    items = []
    seen = set()
    for raw in raw_plugins:
        entry = _normalize_entry(raw)
        if not entry:
            continue
        if entry['id'] in seen:
            logger.warning('catalog 中存在重复条目: %s', entry['id'])
            continue
        seen.add(entry['id'])
        items.append(entry)

    return {
        'schema_version': int(payload.get('schema_version') or CATALOG_SCHEMA_VERSION),
        'updated_at': str(payload.get('updated_at') or ''),
        'plugins': items,
    }


def _normalize_entry(raw) -> dict:
    if not isinstance(raw, dict):
        return {}

    plugin_id = str(raw.get('id') or '').strip()
    if not plugin_id:
        logger.warning('catalog 条目缺少 id，已忽略')
        return {}

    source = raw.get('source') if isinstance(raw.get('source'), dict) else {}
    repo = str(source.get('repo') or '').strip()
    if not REPO_PATTERN.match(repo) or '..' in repo:
        logger.warning('catalog 条目 %s 的 source.repo 非法（必须 owner/repo），已忽略', plugin_id)
        return {}

    return {
        'id': plugin_id,
        'name': str(raw.get('name') or plugin_id),
        'description': str(raw.get('description') or ''),
        'author': str(raw.get('author') or ''),
        'icon': str(raw.get('icon') or ''),
        'tags': [str(tag) for tag in (raw.get('tags') or []) if isinstance(tag, str)],
        # 归属分级（D5）：只做信任级别披露；manifest 无权声明
        'tier': normalize_tier(raw.get('tier')),
        'maintainer': str(raw.get('maintainer') or ''),
        'source': {
            'type': str(source.get('type') or 'github'),
            'repo': repo,
            'ref': str(source.get('ref') or 'main'),
            'subdir': str(source.get('subdir') or ''),
            'release_channel': str(source.get('release_channel') or 'stable'),
            # 可选：发布方提供归档 sha256 时，安装前做完整性校验（12.2 S5）
            'sha256': str(source.get('sha256') or '').strip().lower(),
        },
        'version': str(raw.get('version') or ''),
        # 目录里的 api_version / capabilities 是安装前披露：v3 契约只接受 3
        'api_version': raw.get('api_version'),
        'min_app_version': str(raw.get('min_app_version') or ''),
        # 能力披露（取代 v2 的 permissions）：仅用于安装前展示
        'capabilities': [
            str(item) for item in (raw.get('capabilities') or []) if isinstance(item, str)
        ],
        'homepage': str(raw.get('homepage') or ''),
    }


# ------------------------------------------------------------------ 缓存


def _read_cache() -> dict:
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_cache(payload: dict) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
    except OSError as exc:
        logger.warning('写入插件目录缓存失败: %s', exc)


def _cache_hours() -> float:
    try:
        value = float(load_config().get('plugin_catalog_cache_hours', DEFAULT_CACHE_HOURS))
    except (TypeError, ValueError):
        value = DEFAULT_CACHE_HOURS
    return max(0.0, value)


def _cache_is_fresh(entry: dict, *, max_age_hours: float) -> bool:
    if not isinstance(entry, dict):
        return False
    fetched_at = entry.get('fetched_at')
    try:
        fetched_at = float(fetched_at)
    except (TypeError, ValueError):
        return False
    if fetched_at <= 0:
        return False
    return (time.time() - fetched_at) < max_age_hours * 3600


# ------------------------------------------------------------------ 拉取


def fetch_remote_catalog(url: str) -> dict:
    """拉取远端 catalog（体积受限、超时受限）。"""
    if not str(url or '').strip():
        raise PluginCatalogError('未配置远端目录地址')

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
    except requests.RequestException as exc:
        raise PluginCatalogError(f'目录拉取失败: {exc}') from exc

    try:
        if response.status_code != 200:
            # 404 单独说明：远端目录是「主程序仓库里的一个文件」，404 几乎总是
            # 因为该文件还没被推送到远端默认分支（本地改了但没 push），而不是
            # 网络问题。把 URL 一并给出，用户能自己核对。
            if response.status_code == 404:
                raise PluginCatalogError(
                    f'远端目录不存在（HTTP 404）: {url}'
                    f'（该文件需位于主程序仓库的默认分支；若是本地改动尚未推送，'
                    f'push 后即可）'
                )
            raise PluginCatalogError(f'目录拉取失败: HTTP {response.status_code}')

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_CATALOG_BYTES:
                raise PluginCatalogError('目录文件超过大小上限')
            chunks.append(chunk)
    finally:
        response.close()

    body = b''.join(chunks)
    try:
        payload = json.loads(body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PluginCatalogError(f'目录内容不是合法 JSON: {exc}') from exc
    return parse_catalog(payload)


def get_catalog(*, refresh: bool = False) -> dict:
    """返回官方插件目录（远端优先，失败回退包内清单）。"""
    config = load_config()
    remote_enabled = bool(config.get('plugin_catalog_remote_enabled', True))
    remote_url = str(config.get('plugin_catalog_url') or '').strip()
    cache_hours = _cache_hours()

    cached = _read_cache().get('catalog') or {}
    if not refresh and remote_enabled and _cache_is_fresh(cached, max_age_hours=cache_hours):
        return {
            'success': True,
            'items': cached.get('plugins') or [],
            'source': 'cache',
            'offline': False,
            'updated_at': cached.get('updated_at', ''),
            'msg': '',
        }

    if remote_enabled and remote_url:
        try:
            payload = fetch_remote_catalog(remote_url)
        except PluginCatalogError as exc:
            logger.warning('远端插件目录不可用，回退包内清单: %s', exc)
            bundled = load_bundled_catalog()
            return {
                'success': True,
                'items': bundled.get('plugins') or [],
                'source': 'bundled',
                'offline': True,
                'updated_at': bundled.get('updated_at', ''),
                'msg': f'离线，显示内置目录（{exc}）',
            }

        cache_payload = _read_cache()
        cache_payload['catalog'] = {**payload, 'fetched_at': time.time()}
        _write_cache(cache_payload)
        return {
            'success': True,
            'items': payload.get('plugins') or [],
            'source': 'remote',
            'offline': False,
            'updated_at': payload.get('updated_at', ''),
            'msg': '',
        }

    bundled = load_bundled_catalog()
    return {
        'success': True,
        'items': bundled.get('plugins') or [],
        'source': 'bundled',
        'offline': False,
        'updated_at': bundled.get('updated_at', ''),
        'msg': '' if remote_enabled else '远端目录已关闭，显示内置目录',
    }


def find_catalog_entry(plugin_id: str) -> dict:
    """在目录（含缓存）中查找条目。"""
    plugin_id = str(plugin_id or '').strip()
    if not plugin_id:
        raise PluginCatalogError('缺少插件 id')

    for item in get_catalog().get('items') or []:
        if item.get('id') == plugin_id:
            return item
    raise PluginCatalogError(f'目录中不存在插件: {plugin_id}')


def plugin_tiers() -> dict:
    """本地解析 `plugin_id → tier` 映射（**不发起网络请求**）。

    归属分级（D5）由宿主仓库的 catalog 决定，而插件加载发生在应用启动阶段，
    不能为此等待远端。因此只读本地缓存与包内清单：两者都没有该插件时，
    调用方按 `community` 处理（这是安全的一侧）。
    """
    tiers = {}

    cached = _read_cache().get('catalog') or {}
    for item in cached.get('plugins') or []:
        if isinstance(item, dict) and item.get('id'):
            tiers[str(item['id'])] = normalize_tier(item.get('tier'))

    try:
        bundled = load_bundled_catalog()
    except Exception:  # noqa: BLE001 - 包内清单损坏不应影响插件加载
        logger.warning('读取包内插件目录失败，归属分级回退 community', exc_info=True)
        bundled = {}

    for item in bundled.get('plugins') or []:
        if isinstance(item, dict) and item.get('id'):
            tiers.setdefault(str(item['id']), normalize_tier(item.get('tier')))

    return tiers


def tier_for_plugin(plugin_id: str) -> str:
    """单个插件的归属分级；未知一律 `community`（D5）。"""
    return plugin_tiers().get(str(plugin_id or '').strip(), DEFAULT_PLUGIN_TIER)


# ------------------------------------------------------------------ 更新检查


def _github_headers() -> dict:
    headers = {'Accept': 'application/vnd.github+json'}
    token = _github_token()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    return headers


def _github_token() -> str:
    """GitHub Token 存 `secrets.json` 的 `app` 段（复用第 7 部分）。"""
    try:
        from core.plugins import secrets as secrets_store

        value = secrets_store.get_app_secret('github_token')
        if value:
            return str(value)
    except Exception:  # noqa: BLE001 - 读取失败按无 Token 处理
        logger.debug('读取 GitHub Token 失败', exc_info=True)
    return ''


def _truncate_notes(text) -> tuple:
    """把更新说明按 **UTF-8 字节**截断到 `MAX_RELEASE_NOTES_BYTES`，返回 `(text, truncated)`。

    按字节而不是字符数：这份正文会进接口响应与 24h 缓存文件，膨胀要按落盘体积控制；
    纯中文时字符数与字节数差 3 倍，只看字符数会放过 48KB 的正文。

    截断点退到**自然边界**：在预算内找最后一个 `\\n` 并从那里切开，结果总是完整的行。
    纯字节切会把句子、markdown 列表项乃至行内代码断在中间，而弹层的全部意义就是让用户
    读懂「这次改了什么」——读半句等于没读到。`\\n` 是 ASCII，绝不会落在多字节字符
    内部，所以在它上面切一定不切坏字符；只有整段就是一行超长文本（预算内没有换行）时
    才退回按字节切，并用 `errors='ignore'` 解掉可能被切掉一半的尾字符。

    已知边界：markdown 的硬换行（80 列折行）在源文件里也是 `\\n`，所以切点仍可能落在
    一个**逻辑段落**的中间——行是完整的，句子未必。实测插件仓库的 CHANGELOG 就是硬换行
    的（310 行里 158 行是续行），要再退到空行切会少留 190 字节（71% → 70%），换来的收益
    不值得多一层规则；真正的解法是 16KB 上限让常见升级路径（11.5KB）根本不触发截断。

    不在正文里拼「已截断」之类的提示：弹层有独立的截断提示行，后端拼会重复。
    """
    if not isinstance(text, str) or not text:
        return '', False

    encoded = text.encode('utf-8')
    if len(encoded) <= MAX_RELEASE_NOTES_BYTES:
        return text, False

    prefix = encoded[:MAX_RELEASE_NOTES_BYTES]
    last_newline = prefix.rfind(b'\n')
    if last_newline > 0:
        return prefix[:last_newline].decode('utf-8'), True

    return prefix.decode('utf-8', errors='ignore'), True


def _latest_release(repo: str) -> dict:
    """读取最新 Release：版本号 + 正文（正文即「本次更新说明」的候选来源之一）。

    错误文案是对外契约的一部分：`仓库没有 Release` 这条会被 `check_updates`
    捕获并触发「回退读远端 manifest」，改写会让 `stable` 渠道直接失去回退链。
    """
    url = f'https://api.github.com/repos/{repo}/releases/latest'
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT, headers=_github_headers())
    except requests.RequestException as exc:
        raise PluginCatalogError(f'更新检查失败: {exc}') from exc

    if response.status_code == 404:
        raise PluginCatalogError('仓库没有 Release')
    if response.status_code != 200:
        raise PluginCatalogError(f'更新检查失败: HTTP {response.status_code}')

    try:
        payload = response.json()
    except ValueError as exc:
        raise PluginCatalogError(f'Release 响应不是 JSON: {exc}') from exc

    tag = str(payload.get('tag_name') or '').strip()
    if not tag:
        raise PluginCatalogError('Release 缺少 tag_name')

    raw_body = payload.get('body')
    notes, notes_truncated = _truncate_notes(raw_body if isinstance(raw_body, str) else '')
    return {
        'version': tag.lstrip('v'),
        'notes': notes,
        'notes_truncated': notes_truncated,
    }


def _remote_manifest_payload(entry: dict) -> dict:
    """读取远端 `manifest.json` 的完整内容（版本 + 主程序门槛）。

    这是**权威版本源**：catalog 里的 `version` 字段只是发布方写的快照，
    可能与仓库实际内容不一致（改了 manifest 忘了改 catalog）。因此更新检查
    以远端 manifest 为准，catalog 的 `version` 只用于目录页展示。

    更新检查也不只看版本号：还要知道这版要求的**最低主程序版本**
    （`min_app_version`），否则旧主程序会先被告知「有更新」、点下去才装不上。

    参考 SillyTavern `src/endpoints/extensions.js`：它更进一步，直接读 git
    commit hash（`git rev-parse HEAD` + `git fetch` 比较），因为那里插件就是
    git 仓库工作副本。本项目的插件是**解压后的目录**（无 `.git`），所以用
    「远端 manifest 版本 + semver 比较」达到同样的目的，且不引入 git 依赖。
    """
    source = entry.get('source') or {}
    repo = str(source.get('repo') or '')
    ref = str(source.get('ref') or 'main')
    subdir = str(source.get('subdir') or '').strip('/')
    prefix = f'{subdir}/' if subdir else ''
    url = f'https://raw.githubusercontent.com/{repo}/{ref}/{prefix}manifest.json'

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as exc:
        raise PluginCatalogError(f'读取远端 manifest 失败: {exc}') from exc

    if response.status_code != 200:
        raise PluginCatalogError(f'读取远端 manifest 失败: HTTP {response.status_code}')

    try:
        payload = response.json()
    except ValueError as exc:
        raise PluginCatalogError(f'远端 manifest 不是 JSON: {exc}') from exc
    if not isinstance(payload, dict):
        raise PluginCatalogError('远端 manifest 不是对象')

    version = str(payload.get('version') or '').strip()
    if parse_semver(version) is None:
        raise PluginCatalogError(f'远端 manifest 版本号非法: {version!r}')
    return payload


def _close_quietly(response) -> None:
    """关闭响应，忽略关闭阶段的异常（释放连接失败不该影响已经拿到的正文）。"""
    try:
        response.close()
    except Exception:  # noqa: BLE001 - 关闭失败无可补救
        logger.debug('关闭 HTTP 响应失败', exc_info=True)


def _remote_changelog_text(entry: dict, *, available: str = '') -> str:
    """读取远端仓库根目录下的 `CHANGELOG.md` 原文。

    **绝不抛异常**：这是更新说明的次要来源，任何一环失败都只能降级为「无说明」，
    不能让「取说明」这一步把已经成功的更新检查拖成失败。

    ref 候选按「最可能命中」排序并去重保序：发布 tag `vX.Y.Z` → 裸版本号
    `X.Y.Z` → catalog 的 ref → `main`。发布方打 tag 的风格不统一（有的带 `v`
    有的不带），两种都试；最后一个 200 命中即停。
    """
    source = entry.get('source') or {}
    repo = str(source.get('repo') or '').strip()
    if not REPO_PATTERN.match(repo) or '..' in repo:
        return ''

    subdir = str(source.get('subdir') or '').strip('/')
    prefix = f'{subdir}/' if subdir else ''
    version = str(available or '').strip()

    candidates = []
    for raw in (f'v{version}' if version else '', version, source.get('ref'), 'main'):
        value = str(raw or '').strip()
        if value and value not in candidates:
            candidates.append(value)

    for ref in candidates:
        url = f'https://raw.githubusercontent.com/{repo}/{ref}/{prefix}CHANGELOG.md'
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        except requests.RequestException as exc:
            logger.debug('读取远端 CHANGELOG 失败 %s: %s', url, exc)
            continue

        if response.status_code != 200:
            logger.debug('读取远端 CHANGELOG 失败 %s: HTTP %s', url, response.status_code)
            _close_quietly(response)
            continue

        raw_body = None
        oversized = False
        try:
            chunks = []
            total = 0
            for chunk in response.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_CHANGELOG_BYTES:
                    oversized = True
                    break
                chunks.append(chunk)
            raw_body = b''.join(chunks)
        except Exception:  # noqa: BLE001 - 拿不到正文就换下一个 ref
            logger.debug('读取远端 CHANGELOG 正文失败 %s', url, exc_info=True)
        finally:
            _close_quietly(response)

        if oversized:
            logger.debug('远端 CHANGELOG 超过体积上限，忽略 %s', url)
            return ''
        if raw_body is None:
            continue

        try:
            return raw_body.decode('utf-8')
        except UnicodeDecodeError:
            logger.debug('远端 CHANGELOG 不是 UTF-8，忽略 %s', url)
            return ''

    return ''


def _release_notes_for(entry: dict, *, installed: str, available: str, release) -> tuple:
    """逐级回退取「本次更新说明」，返回 `(notes, source, truncated)`。

    ① 有 Release 正文就用它——发布方写的就是这次发布的说明，且不额外发请求；
    ② 否则读远端 CHANGELOG，按锚点切出 `(installed, available]` 区间
       （跨多个版本时全部带上，新的在前）；
    ③ 都没有就返回空说明，前端显示「本次更新没有提供说明」。
    """
    notes = ''
    source = ''

    if isinstance(release, dict) and str(release.get('notes') or '').strip():
        notes = str(release['notes']).strip()
        source = 'release'
    else:
        text = _remote_changelog_text(entry, available=available)
        if text:
            composed = changelog_module.compose_release_notes(
                text,
                from_version=installed,
                to_version=available,
            )
            if composed.strip():
                notes = composed.strip()
                source = 'changelog'

    if not source:
        return '', '', False

    truncated = bool(release.get('notes_truncated')) if source == 'release' else False
    notes, clipped = _truncate_notes(notes)
    return notes, source, truncated or clipped


def check_updates(*, force: bool = False) -> dict:
    """检查已安装插件是否有新版本。

    只报告，不自动安装——应用更新走 `POST /api/plugins/catalog/update`
    （内部复用 `installer.install_from_catalog`，原子替换 + 重启生效）。

    版本来源优先级（与 SillyTavern 的「远端优先」一致）：
    - `release_channel == 'stable'`：先问 GitHub Release（发布方打了 tag 才算发布），
      没有 Release 时回退读远端 `manifest.json`；
    - 其它 channel（如 `dev`）：直接读远端 `manifest.json`（跟随分支最新提交）。

    这样做的原因：`stable` 语义是「发布方显式发布」，而直接读 manifest 会让
    「改了 main 分支但还没发版」也算更新——SillyTavern 靠 git commit 区分
    「有提交」与「有发布」，这里用 Release/tag 达到同样的区分度。
    """
    cached = _read_cache().get('updates') or {}
    if not force and _cache_is_fresh(cached, max_age_hours=UPDATES_CACHE_HOURS):
        return {'success': True, 'updates': cached.get('updates') or [], 'source': 'cache', 'msg': ''}

    catalog_items = {item['id']: item for item in (get_catalog().get('items') or [])}
    updates = []
    errors = []

    for state in registry.list_states():
        if state.manifest is None:
            continue

        entry = catalog_items.get(state.plugin_id)
        if not entry:
            continue

        installed = state.manifest.version
        available = ''
        channel = entry['source'].get('release_channel', 'stable')
        remote_manifest = None
        release = None
        try:
            if channel == 'stable':
                try:
                    release = _latest_release(entry['source']['repo'])
                    available = release['version']
                except PluginCatalogError:
                    remote_manifest = _remote_manifest_payload(entry)
                    available = str(remote_manifest.get('version') or '').strip()
            else:
                remote_manifest = _remote_manifest_payload(entry)
                available = str(remote_manifest.get('version') or '').strip()
        except PluginCatalogError as exc:
            errors.append({'id': state.plugin_id, 'msg': str(exc)})
            continue

        if parse_semver(available) is None:
            continue

        # 主程序版本门槛：默认用 catalog 的声明（发布时与 ref/sha256 一起更新），
        # 远端 manifest 里给了就以远端为准——那才是发布方对「这版要哪个主程序」的声明。
        required_app = str(entry.get('min_app_version') or '').strip()
        if remote_manifest is not None:
            remote_required = str(remote_manifest.get('min_app_version') or '').strip()
            if remote_required:
                required_app = remote_required
        requires_app_update = bool(required_app) and compare_versions(APP_VERSION, required_app) < 0

        # 无论是否有更新都给出记录，前端才能显示「已是最新 vX.Y.Z」
        has_update = compare_versions(available, installed) > 0
        item = {
            'id': state.plugin_id,
            'name': state.manifest.name,
            'installed': installed,
            'available': available,
            'channel': channel,
            'repo': entry['source']['repo'],
            'has_update': has_update,
            # 装不上就别只说「有更新」：前端据此置灰按钮并提示先升级主程序。
            'min_app_version': required_app,
            'requires_app_update': requires_app_update,
            # 本次更新说明给前端更新确认弹层用；没有更新就不去取（省一次网络请求）。
            'release_notes': '',
            'release_notes_source': '',
            'release_notes_truncated': False,
        }
        if has_update:
            notes, notes_source, notes_truncated = _release_notes_for(
                entry,
                installed=installed,
                available=available,
                release=release,
            )
            item['release_notes'] = notes
            item['release_notes_source'] = notes_source
            item['release_notes_truncated'] = notes_truncated
            updates.append(item)

    cache_payload = _read_cache()
    cache_payload['updates'] = {'updates': updates, 'fetched_at': time.time()}
    _write_cache(cache_payload)

    return {'success': True, 'updates': updates, 'source': 'remote', 'errors': errors, 'msg': ''}


def reset_cache_for_tests() -> None:
    try:
        if os.path.exists(CACHE_FILE):
            os.remove(CACHE_FILE)
    except OSError:
        pass
