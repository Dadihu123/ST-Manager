"""类脑搜索站（shimmerday）帖子预览转发服务。"""

import logging

import requests

from core.config import load_config
from core.utils.discord_url import extract_discord_thread_id

logger = logging.getLogger(__name__)

SHIMMERDAY_THREAD_API = 'https://forum.shimmerday.top/v1/search/thread/{thread_id}'
DEFAULT_TIMEOUT = 20


def fetch_thread_preview(source_link=None, card_id=None, timeout=DEFAULT_TIMEOUT):
    """解析来源链接并转发请求类脑搜索站帖子详情。

    Args:
        source_link: Discord channels URL
        card_id: 可选；未传 source_link 时从来源卡读取
        timeout: 上游请求超时秒数

    Returns:
        dict: {success, data?, msg?, thread_id?}
    """
    link = _resolve_source_link(source_link=source_link, card_id=card_id)
    if not link:
        return {'success': False, 'msg': '未提供来源链接'}

    thread_id = extract_discord_thread_id(link)
    if not thread_id:
        return {'success': False, 'msg': '无法从来源链接解析类脑帖子 ID'}

    cookie = str(load_config().get('shimmerday_forum_cookie') or '').strip()
    if not cookie:
        return {
            'success': False,
            'msg': '未配置类脑 Cookie（设置 → shimmerday_forum_cookie）',
        }

    api_url = SHIMMERDAY_THREAD_API.format(thread_id=thread_id)
    headers = {
        'Accept': 'application/json',
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        # 类脑搜索站会话 Cookie
        'Cookie': cookie.replace('\n', ' ').replace('\r', ' '),
    }

    try:
        resp = requests.get(api_url, headers=headers, timeout=timeout)
    except requests.Timeout:
        logger.warning('类脑搜索站预览超时: %s', thread_id)
        return {'success': False, 'msg': '类脑搜索站接口请求超时', 'thread_id': thread_id}
    except requests.RequestException as exc:
        logger.error('类脑搜索站预览请求失败: %s', exc)
        return {
            'success': False,
            'msg': f'类脑搜索站接口请求失败: {exc}',
            'thread_id': thread_id,
        }

    if resp.status_code == 401 or resp.status_code == 403:
        return {
            'success': False,
            'msg': '类脑 Cookie 无效或已过期，请重新配置',
            'thread_id': thread_id,
        }

    if resp.status_code == 404:
        return {'success': False, 'msg': '未找到对应帖子', 'thread_id': thread_id}

    if resp.status_code >= 400:
        return {
            'success': False,
            'msg': f'类脑搜索站接口错误 ({resp.status_code})',
            'thread_id': thread_id,
        }

    try:
        payload = resp.json()
    except ValueError:
        return {
            'success': False,
            'msg': '类脑搜索站接口返回非 JSON',
            'thread_id': thread_id,
        }

    if not isinstance(payload, dict):
        return {
            'success': False,
            'msg': '类脑搜索站接口返回格式异常',
            'thread_id': thread_id,
        }

    return {'success': True, 'thread_id': thread_id, 'data': payload}


def _resolve_source_link(source_link=None, card_id=None):
    """优先用显式链接，否则从缓存 / ui_data 读取。

    Bundle 的 link 保存在 bundle 目录键下，而不是每个版本的卡片 ID
    下；因此按 card_id 回查时需要先解析对应的 UI key。
    """
    link = str(source_link or '').strip()
    if link:
        return link

    cid = str(card_id or '').strip()
    if not cid:
        return ''

    try:
        from core.context import ctx
        from core.services.card_service import resolve_ui_key

        card = ctx.cache.id_map.get(cid) if ctx.cache else None
        if isinstance(card, dict):
            cached_link = str(card.get('source_link') or '').strip()
            if cached_link:
                return cached_link

        # Bundle 聚合卡和 Bundle 版本分别使用不同的 card_id，统一解析到
        # bundle 目录键后再读取全局 link。
        resolved_ui_key = resolve_ui_key(cid)
    except Exception as exc:
        logger.warning('读取卡片缓存来源链接失败: %s', exc)
        resolved_ui_key = ''

    try:
        from core.data.ui_store import load_ui_data

        ui_data = load_ui_data()
        if not isinstance(ui_data, dict):
            return ''

        # 保留 cid 作为回退，兼容普通卡片和历史数据。
        candidate_keys = []
        if resolved_ui_key:
            candidate_keys.append(resolved_ui_key)
        if cid not in candidate_keys:
            candidate_keys.append(cid)

        for key in candidate_keys:
            entry = ui_data.get(key)
            if isinstance(entry, dict):
                link = str(entry.get('link') or '').strip()
                if link:
                    return link
    except Exception as exc:
        logger.warning('读取 ui_data 来源链接失败: %s', exc)

    return ''
