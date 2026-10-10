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
from core.plugins import registry
from core.plugins.entries import DEFAULT_ENTRY_TIER, normalize_tier
from core.plugins.errors import PluginCatalogError
from core.plugins.manifest import compare_versions, parse_semver

logger = logging.getLogger(__name__)

CATALOG_SCHEMA_VERSION = 2
CATALOG_RELATIVE_PATH = os.path.join('static', 'plugins', 'catalog.json')

CACHE_DIR = os.path.join(SYSTEM_DIR, 'plugins')
CACHE_FILE = os.path.join(CACHE_DIR, '_catalog_cache.json')

DEFAULT_CACHE_HOURS = 6
UPDATES_CACHE_HOURS = 24
REQUEST_TIMEOUT = (10, 30)
MAX_CATALOG_BYTES = 512 * 1024

REPO_PATTERN = re.compile(r'^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$')
TAG_PATTERN = re.compile(r'^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?')


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
        # 归属分级（D5）：决定该插件的入口能用哪些 kind；manifest 无权声明
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
        'api_version': raw.get('api_version'),
        'min_app_version': str(raw.get('min_app_version') or ''),
        'permissions': [str(item) for item in (raw.get('permissions') or []) if isinstance(item, str)],
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
    return plugin_tiers().get(str(plugin_id or '').strip(), DEFAULT_ENTRY_TIER)


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


def _latest_release_version(repo: str) -> str:
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
    return tag.lstrip('v')


def _remote_manifest_version(entry: dict) -> str:
    """读取远端 `manifest.json` 的版本号。

    这是**权威版本源**：catalog 里的 `version` 字段只是发布方写的快照，
    可能与仓库实际内容不一致（改了 manifest 忘了改 catalog）。因此更新检查
    以远端 manifest 为准，catalog 的 `version` 只用于目录页展示。

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

    version = str(payload.get('version') or '').strip()
    if parse_semver(version) is None:
        raise PluginCatalogError(f'远端 manifest 版本号非法: {version!r}')
    return version


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
        try:
            if channel == 'stable':
                try:
                    available = _latest_release_version(entry['source']['repo'])
                except PluginCatalogError:
                    available = _remote_manifest_version(entry)
            else:
                available = _remote_manifest_version(entry)
        except PluginCatalogError as exc:
            errors.append({'id': state.plugin_id, 'msg': str(exc)})
            continue

        if parse_semver(available) is None:
            continue

        # 无论是否有更新都给出记录，前端才能显示「已是最新 vX.Y.Z」
        item = {
            'id': state.plugin_id,
            'name': state.manifest.name,
            'installed': installed,
            'available': available,
            'channel': channel,
            'repo': entry['source']['repo'],
            'has_update': compare_versions(available, installed) > 0,
        }
        if item['has_update']:
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
