"""Discord 类脑帖子来源标题与首帖编辑时间检查。"""

import base64
from functools import wraps
import json
import logging
import os
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from core.config import CARDS_FOLDER, load_config
from core.context import ctx
from core.data.ui_store import (
    SOURCE_UPDATE_PENDING_STATUSES,
    get_source_update_state,
    load_ui_data,
    reset_source_update_state,
    save_source_title_state,
    save_ui_data,
    set_source_update_state,
)
from core.services.card_service import resolve_ui_key
from core.services.card_operation_lock import (
    card_busy_result,
    release_card_lock,
    try_acquire_card_lock,
)
from core.utils.discord_url import extract_discord_thread_id

logger = logging.getLogger(__name__)

DISCORD_API_ROOT = 'https://discord.com/api/v10'
DEFAULT_TIMEOUT = 30


def _source_operation_locked(func):
    """让来源状态读写遵循统一的卡片级非阻塞锁。"""
    @wraps(func)
    def wrapped(card_id, *args, **kwargs):
        acquired, lock = try_acquire_card_lock(card_id, blocking=False)
        if not acquired:
            result = card_busy_result(card_id)
            try:
                data = load_ui_data()
                ui_key = resolve_ui_key(card_id)
                result['source_update'] = get_source_update_state(data, ui_key)
            except (AttributeError, KeyError, TypeError):
                pass
            return result

        try:
            return func(card_id, *args, **kwargs)
        finally:
            release_card_lock(lock)

    return wrapped


def _parse_timestamp(value):
    """将 Discord ISO 8601 时间转换为 UTC 秒级时间戳。"""
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def _format_timestamp(value):
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat().replace('+00:00', 'Z')
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _parse_discord_parts(url):
    """解析 Discord URL 的 guild/channel/thread 三个 ID。"""
    thread_id = extract_discord_thread_id(url)
    if not thread_id:
        return None

    try:
        parsed = urlparse(str(url).strip())
        parts = [part for part in parsed.path.strip('/').split('/') if part]
        if len(parts) < 3 or parts[0] != 'channels':
            return None

        guild_id = parts[1]
        if len(parts) >= 5 and parts[3] == 'threads':
            channel_id = parts[2]
        elif len(parts) == 3 or (len(parts) >= 4 and parts[3].isdigit()):
            channel_id = thread_id
        else:
            channel_id = parts[2]

        if not guild_id.isdigit() or not channel_id.isdigit() or not thread_id.isdigit():
            return None
        return guild_id, channel_id, thread_id
    except (TypeError, ValueError, IndexError):
        return None


def _build_headers(guild_id, channel_id, config=None):
    """按现有论坛标签抓取器的认证方式构造请求头。"""
    cfg = config if isinstance(config, dict) else load_config()
    user_agent = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    headers = {
        'User-Agent': user_agent,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }

    auth_type = str(cfg.get('discord_auth_type', 'token') or 'token').lower()
    token = str(cfg.get('discord_bot_token', '') or '').strip()
    cookie = str(cfg.get('discord_user_cookie', '') or '').strip()
    if auth_type == 'cookie' and cookie:
        cleaned_cookie = cookie.replace('\n', ' ').replace('\r', ' ')
        headers.update({
            'Cookie': cleaned_cookie,
            'Referer': f'https://discord.com/channels/{guild_id}/{channel_id}',
            'X-Discord-Locale': 'zh-CN',
            'X-Debug-Options': 'bugReporterEnabled',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        })
        super_properties = {
            'os': 'Windows',
            'browser': 'Chrome',
            'device': '',
            'system_locale': 'zh-CN',
            'browser_user_agent': user_agent,
            'browser_version': '120',
            'os_version': '10',
            'referrer': '',
            'referring_domain': '',
            'referrer_current': '',
            'referring_domain_current': '',
            'release_channel': 'stable',
            'client_build_number': 9999,
            'client_event_source': None,
        }
        headers['X-Super-Properties'] = base64.b64encode(
            json.dumps(super_properties, separators=(',', ':')).encode('utf-8')
        ).decode('ascii')
    elif token:
        token = token.removeprefix('Bearer ').strip()
        headers['Authorization'] = token

    return headers


def _response_json(response):
    try:
        payload = response.json()
    except (TypeError, ValueError, requests.RequestException):
        payload = None
    return payload if isinstance(payload, (dict, list)) else None


def _describe_starter_message_error(status_code, payload):
    """将首帖消息接口的 HTTP/Discord 错误转换为可操作的提示。"""
    api_code = payload.get('code') if isinstance(payload, dict) else None
    api_message = str(payload.get('message') or '').strip() if isinstance(payload, dict) else ''

    if status_code == 403 and api_code == 20002:
        detail = (
            '当前 Discord 认证身份不能调用单条消息接口（仅 Bot 可使用此接口），'
            '消息列表接口也未取得首帖，无法读取首帖编辑时间'
        )
    elif status_code == 404 or api_code == 10008:
        detail = '首帖消息不存在或已被删除'
    elif status_code == 403:
        detail = 'Discord 拒绝读取首帖消息，请检查 Bot 的查看频道和读取消息历史权限'
    elif api_message:
        detail = f'首帖消息 API 返回 HTTP {status_code}: {api_message}'
    else:
        detail = f'首帖消息 API 返回 HTTP {status_code}'

    return detail, api_code, api_message


def _find_message_by_id(payload, message_id):
    """从消息列表响应中找到指定 ID 的消息。"""
    if not isinstance(payload, list):
        return None
    expected_id = str(message_id or '').strip()
    for item in payload:
        if isinstance(item, dict) and str(item.get('id') or '').strip() == expected_id:
            return item
    return None


def fetch_discord_source(url, *, timeout=DEFAULT_TIMEOUT, http_get=None, config=None,
                         include_first_message=True):
    """抓取来源标题及可选的首帖消息时间，不访问父论坛频道。"""
    parts = _parse_discord_parts(url)
    if not parts:
        return {
            'success': False,
            'supported': False,
            'status': 'unsupported',
            'error': '仅支持 Discord 类脑帖子链接',
        }

    guild_id, channel_id, thread_id = parts
    getter = http_get or requests.get
    headers = _build_headers(guild_id, channel_id, config)
    thread_url = f'{DISCORD_API_ROOT}/channels/{thread_id}'
    try:
        thread_response = getter(thread_url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        logger.warning('Discord thread request failed: %s', exc)
        return {
            'success': False,
            'supported': True,
            'status': 'error',
            'error': f'Discord 帖子请求失败: {exc}',
        }

    thread_payload = _response_json(thread_response)
    if getattr(thread_response, 'status_code', 0) != 200 or not isinstance(thread_payload, dict):
        status_code = getattr(thread_response, 'status_code', 0)
        error_map = {
            401: 'Discord 认证失败，请检查 Token/Cookie',
            403: 'Discord 拒绝访问，请检查权限',
            404: 'Discord 帖子不存在或已被删除',
        }
        return {
            'success': False,
            'supported': True,
            'status': 'error',
            'http_status': status_code,
            'error': error_map.get(status_code, f'Discord API 返回 HTTP {status_code}'),
        }

    source_title = str(thread_payload.get('name') or '').strip()
    applied_tags = thread_payload.get('applied_tags')
    if not isinstance(applied_tags, list):
        applied_tags = []
    source = {
        'title': source_title,
        'thread_id': thread_id,
        'guild_id': guild_id,
        'channel_id': channel_id,
        # 标签抓取可直接复用这些字段，避免再次请求帖子详情。
        'applied_tag_ids': [
            str(tag_id) for tag_id in applied_tags
            if tag_id is not None
        ],
        'parent_id': str(thread_payload.get('parent_id') or channel_id),
        'thread_created_at': thread_payload.get('thread_metadata', {}).get('create_timestamp')
        if isinstance(thread_payload.get('thread_metadata'), dict) else None,
        'first_message_available': False,
        'first_message_timestamp': None,
        'first_message_edited_at': None,
        'first_message_revision_at': None,
    }

    if not include_first_message:
        return {'success': True, 'supported': True, 'status': 'ok', 'source': source}

    # Discord 论坛帖的首帖消息 ID 与 thread ID 相同；last_pin_timestamp 不是编辑时间。
    # 用户身份不能调用单条消息接口时，先用官方消息列表接口按首帖 ID 定位。
    around_url = f'{DISCORD_API_ROOT}/channels/{thread_id}/messages?around={thread_id}&limit=1'
    around_status = None
    around_payload = None
    try:
        around_response = getter(around_url, headers=headers, timeout=timeout)
        around_status = getattr(around_response, 'status_code', 0)
        around_payload = _response_json(around_response)
    except requests.RequestException as exc:
        source['edit_fallback_error'] = f'消息列表请求失败: {exc}'

    message_payload = _find_message_by_id(around_payload, thread_id)
    if message_payload is not None:
        source['first_message_fetch_method'] = 'messages_around'
    else:
        # 保留单消息接口作为 Bot 身份或旧 Discord 行为下的兼容路径。
        message_url = f'{DISCORD_API_ROOT}/channels/{thread_id}/messages/{thread_id}'
        try:
            message_response = getter(message_url, headers=headers, timeout=timeout)
        except requests.RequestException as exc:
            source['edit_error'] = f'首帖消息请求失败: {exc}'
            return {'success': True, 'supported': True, 'status': 'first_message_unavailable', 'source': source}

        message_payload = _response_json(message_response)
        if getattr(message_response, 'status_code', 0) == 200 and isinstance(message_payload, dict):
            source['first_message_fetch_method'] = 'single_message'
        else:
            status_code = getattr(message_response, 'status_code', 0)
            source['edit_http_status'] = status_code
            if around_status is not None:
                source['edit_fallback_http_status'] = around_status
            edit_error, api_code, api_message = _describe_starter_message_error(
                status_code,
                message_payload,
            )
            source['edit_error'] = edit_error
            if api_code is not None:
                source['edit_api_code'] = api_code
            if api_message:
                source['edit_api_message'] = api_message
            return {'success': True, 'supported': True, 'status': 'first_message_unavailable', 'source': source}

    if not isinstance(message_payload, dict):
        source['edit_http_status'] = around_status
        source['edit_error'] = '消息列表未返回与首帖 ID 匹配的消息'
        return {'success': True, 'supported': True, 'status': 'first_message_unavailable', 'source': source}

    if around_status is not None and source.get('first_message_fetch_method') != 'messages_around':
        source['edit_fallback_http_status'] = around_status

    message_timestamp = message_payload.get('timestamp')
    edited_timestamp = message_payload.get('edited_timestamp')
    created_at = _parse_timestamp(message_timestamp)
    edited_at = _parse_timestamp(edited_timestamp)
    revision_at = edited_at if edited_at is not None else created_at
    source.update({
        'first_message_available': True,
        'first_message_id': str(message_payload.get('id') or thread_id),
        'first_message_timestamp': message_timestamp,
        'first_message_edited_at': edited_timestamp,
        'first_message_revision_at': _format_timestamp(revision_at),
        'first_message_timestamp_epoch': created_at,
        'first_message_edited_at_epoch': edited_at,
        'first_message_revision_at_epoch': revision_at,
    })
    return {'success': True, 'supported': True, 'status': 'ok', 'source': source}


def _resolve_card_and_source(card_id, source_link=None, ui_data=None):
    if not card_id:
        return None, '', '', ui_data if isinstance(ui_data, dict) else load_ui_data()

    cache = getattr(ctx, 'cache', None)
    id_map = getattr(cache, 'id_map', None)
    card = id_map.get(card_id) if isinstance(id_map, dict) else None
    data = ui_data if isinstance(ui_data, dict) else load_ui_data()
    try:
        ui_key = resolve_ui_key(card_id)
    except (AttributeError, KeyError, TypeError):
        ui_key = card_id
    link = str(source_link or '').strip()
    if not link and ui_key and isinstance(data.get(ui_key), dict):
        link = str(data[ui_key].get('link') or '').strip()
    return card, ui_key, link, data


def resolve_card_source(card_id, source_link=None, *, ui_data=None):
    """返回当前角色卡、UI key 和来源链接，不发起网络请求。"""
    return _resolve_card_and_source(card_id, source_link, ui_data)


def is_supported_source_url(source_url):
    """复用现有 Discord 来源解析规则判断链接是否可检查。"""
    return bool(_parse_discord_parts(str(source_url or '').strip()))


def _local_last_modified(card_id, card):
    if isinstance(card, dict):
        try:
            value = float(card.get('last_modified') or 0)
            if value > 0:
                return value
        except (TypeError, ValueError):
            pass

    if card_id:
        try:
            path = os.path.join(CARDS_FOLDER, str(card_id).replace('/', os.sep))
            return float(os.path.getmtime(path))
        except (OSError, TypeError, ValueError):
            pass
    return 0.0


def _state_for_card(ui_data, ui_key):
    return get_source_update_state(ui_data, ui_key)


def _reset_state_if_source_changed(data, ui_key, source_url, status, error=''):
    current = _state_for_card(data, ui_key)
    normalized_url = str(source_url or '').strip()
    if current.get('source_url') == normalized_url:
        return current

    changed, state = reset_source_update_state(
        data,
        ui_key,
        source_url=normalized_url,
        status=status,
        error=error,
    )
    if changed:
        save_ui_data(data)
    return state


@_source_operation_locked
def prepare_source_link_for_card(card_id, source_link=None, *, ui_data=None):
    """记录链接变更并清空旧来源基线，不发起 Discord 请求。"""
    _card, ui_key, link, data = _resolve_card_and_source(card_id, source_link, ui_data)
    if not ui_key:
        return {
            'success': False,
            'status': 'error',
            'error': '无法定位卡片 UI 数据',
            'card_id': card_id,
        }

    if not link:
        status = 'no_source'
    elif not _parse_discord_parts(link):
        status = 'unsupported'
    else:
        status = 'never_checked'

    state = _reset_state_if_source_changed(data, ui_key, link, status)
    return {
        'success': True,
        'supported': bool(link and _parse_discord_parts(link)),
        'status': state.get('last_status', status),
        'card_id': card_id,
        'source_update': state,
    }


def _status_message(status, detail=''):
    message = {
        'no_source': '未配置来源链接',
        'unsupported': '仅支持 Discord 类脑帖子链接',
        'never_checked': '尚未检查来源',
        'baseline_established': '已建立基线，下一次才能判断',
        'title_synced': '来源标题已同步，尚未建立检查基线',
        'baseline_refreshed': '角色卡更新后，已刷新来源标题和首帖时间基线',
        'first_check_updated': '首次检查发现来源首帖晚于本地角色卡，已标记为待处理更新',
        'updated': '检测到来源帖子已更新',
        'title_changed': '检测到来源标题已变化',
        'title_and_content_updated': '检测到来源标题和首帖编辑时间都已变化',
        'unchanged': '来源标题和首帖编辑时间均未变化',
        'first_message_unavailable': '无法取得首帖编辑时间，只能检查标题',
        'acknowledged': '已确认当前来源更新无需处理',
        'not_pending': '当前没有待处理的来源更新',
        'error': '检查来源失败',
    }.get(status, status)
    if status == 'first_message_unavailable' and detail:
        return f'{message}：{detail}'
    return message


@_source_operation_locked
def save_source_title_for_card(card_id, title, source_link=None, *, ui_data=None, reset_baseline=False):
    """保存来源贴标题，不改变角色卡名称或文件名。"""
    card, ui_key, link, data = _resolve_card_and_source(card_id, source_link, ui_data)
    if not ui_key:
        return {'success': False, 'status': 'error', 'error': '无法定位卡片 UI 数据'}
    if not _parse_discord_parts(link):
        return {'success': False, 'supported': False, 'status': 'unsupported', 'error': '仅支持 Discord 类脑帖子链接'}

    changed, state = save_source_title_state(
        data,
        ui_key,
        title,
        source_url=link,
        reset_baseline=reset_baseline,
    )
    if changed and not save_ui_data(data):
        return {'success': False, 'status': 'error', 'error': '保存来源标题失败'}

    if isinstance(card, dict):
        card['source_title'] = state['source_title']
        card['source_update'] = state
    return {
        'success': True,
        'supported': True,
        'status': 'title_synced',
        'source_title': state['source_title'],
        'source_update': state,
    }


@_source_operation_locked
def sync_source_title_for_card(card_id, source_link=None, *, title_hint=None, ui_data=None,
                               timeout=DEFAULT_TIMEOUT, http_get=None):
    """同步标题；优先复用标签抓取已经取得的 title，避免重复请求。"""
    card, ui_key, link, data = _resolve_card_and_source(card_id, source_link, ui_data)
    if not link:
        state = _reset_state_if_source_changed(data, ui_key, '', 'no_source')
        return {
            'success': False,
            'status': 'no_source',
            'error': '未配置来源链接',
            'source_update': state,
        }
    if not _parse_discord_parts(link):
        state = _reset_state_if_source_changed(data, ui_key, link, 'unsupported')
        return {
            'success': False,
            'supported': False,
            'status': 'unsupported',
            'error': '仅支持 Discord 类脑帖子链接',
            'source_update': state,
        }

    if title_hint is not None:
        return save_source_title_for_card(
            card_id,
            title_hint,
            link,
            ui_data=data,
        )

    fetched = fetch_discord_source(
        link,
        timeout=timeout,
        http_get=http_get,
        include_first_message=False,
    )
    if not fetched.get('success') or not fetched.get('source'):
        state = _reset_state_if_source_changed(
            data,
            ui_key,
            link,
            fetched.get('status', 'error'),
            fetched.get('error') or '无法取得来源标题',
        )
        return {
            'success': False,
            'supported': True,
            'status': fetched.get('status', 'error'),
            'error': fetched.get('error') or '无法取得来源标题',
            'source_update': state,
        }
    return save_source_title_for_card(
        card_id,
        fetched['source'].get('title', ''),
        link,
        ui_data=data,
    )


@_source_operation_locked
def check_card_source_update(card_id, source_link=None, *, ui_data=None, timeout=DEFAULT_TIMEOUT,
                             http_get=None, now=None):
    """检查单张卡片来源是否更新，结果可直接供未来检查池复用。"""
    card, ui_key, link, data = _resolve_card_and_source(card_id, source_link, ui_data)
    checked_at = float(now if now is not None else time.time())
    if not card:
        return {'success': False, 'status': 'error', 'error': '找不到角色卡', 'card_id': card_id}
    if not link:
        state = _reset_state_if_source_changed(data, ui_key, '', 'no_source')
        return {
            'success': True,
            'supported': False,
            'status': 'no_source',
            'message': _status_message('no_source'),
            'card_id': card_id,
            'source_update': state,
        }
    if not _parse_discord_parts(link):
        state = _reset_state_if_source_changed(data, ui_key, link, 'unsupported')
        return {
            'success': True,
            'supported': False,
            'status': 'unsupported',
            'message': _status_message('unsupported'),
            'card_id': card_id,
            'source_update': state,
        }

    fetched = fetch_discord_source(
        link,
        timeout=timeout,
        http_get=http_get,
    )
    if not fetched.get('success'):
        state = _state_for_card(data, ui_key)
        if state.get('source_url') != link:
            state = _reset_state_if_source_changed(data, ui_key, link, 'error')
        state['source_url'] = link
        state['last_checked_at'] = checked_at
        state['last_status'] = 'error'
        state['last_error'] = fetched.get('error', '')
        changed, state = set_source_update_state(data, ui_key, state)
        if changed:
            save_ui_data(data)
        return {
            'success': False,
            'supported': True,
            'status': 'error',
            'error': fetched.get('error') or '检查来源失败',
            'card_id': card_id,
            'source_update': state,
        }

    source = fetched.get('source') or {}
    current_title = str(source.get('title') or '').strip()
    current_revision = source.get('first_message_revision_at_epoch')
    first_message_available = bool(source.get('first_message_available')) and current_revision is not None
    state = _state_for_card(data, ui_key)
    source_changed = bool(
        state.get('source_url') != link
        and (state.get('source_url') or link)
    )
    if source_changed:
        # 新来源不能继承旧来源的待处理标记；后续检查从新来源重新建立基线。
        changed, state = reset_source_update_state(
            data,
            ui_key,
            source_url=link,
            status='never_checked',
        )
        if changed:
            save_ui_data(data)
    first_check = not state.get('baseline_established') or state.get('source_url') != link
    previous_title = state.get('source_title', '')
    previous_revision = state.get('first_message_revision_at')
    title_changed = bool(
        not first_check
        and previous_title != current_title
        and (previous_title or current_title)
    )
    content_changed = False
    remote_newer_than_local = False
    warnings = []

    if first_message_available:
        local_mtime = _local_last_modified(card_id, card)
        remote_newer_than_local = first_check and current_revision > local_mtime + 0.001
        if not first_check and previous_revision is not None:
            try:
                content_changed = current_revision > float(previous_revision) + 0.001
            except (TypeError, ValueError):
                warnings.append('历史首帖时间基线无效')
        elif not first_check and previous_revision is None:
            warnings.append('历史首帖时间基线缺失，暂不判断内容变化')

        if first_check:
            status = 'first_check_updated' if remote_newer_than_local else 'baseline_established'
        elif title_changed and content_changed:
            status = 'title_and_content_updated'
        elif content_changed:
            status = 'updated'
        elif title_changed:
            status = 'title_changed'
        else:
            status = 'unchanged'

        next_state = {
            'source_url': link,
            'source_title': current_title,
            'first_message_edited_at': source.get('first_message_edited_at_epoch'),
            'first_message_timestamp': source.get('first_message_timestamp_epoch'),
            'first_message_revision_at': current_revision,
            'baseline_established': True,
            'last_checked_at': checked_at,
            'last_status': status,
            'last_error': '',
        }
    else:
        # 没有首帖消息时只保存标题和链接，不把检查标记为完整基线。
        status = 'first_message_unavailable'
        if not first_check and title_changed:
            status = 'title_changed'
        next_state = dict(state)
        next_state.update({
            'source_url': link,
            'source_title': current_title,
            'baseline_established': bool(state.get('baseline_established')) and not first_check,
            'last_checked_at': checked_at,
            'last_status': status,
            'last_error': source.get('edit_error') or '无法取得首帖编辑时间',
        })
        warnings.append(next_state['last_error'])

    detected_change = bool(remote_newer_than_local or title_changed or content_changed)
    was_pending = bool(state.get('pending_update'))
    next_state['pending_update'] = bool(was_pending or detected_change)
    if detected_change:
        next_state['pending_status'] = (
            status if status in SOURCE_UPDATE_PENDING_STATUSES else state.get('pending_status', '')
        )
        next_state['pending_since'] = state.get('pending_since') if was_pending else checked_at
    elif was_pending:
        next_state['pending_status'] = state.get('pending_status', '')
        next_state['pending_since'] = state.get('pending_since')
    else:
        next_state['pending_status'] = ''
        next_state['pending_since'] = None

    changed, normalized_state = set_source_update_state(data, ui_key, next_state)
    if changed:
        save_ui_data(data)
    if isinstance(card, dict):
        card['source_title'] = normalized_state['source_title']
        card['source_update'] = normalized_state

    message = _status_message(status, warnings[0] if warnings else '')
    if normalized_state['pending_update'] and not detected_change:
        if status == 'unchanged':
            message = '来源暂无后续变化，仍有待处理更新'
        elif status == 'first_message_unavailable':
            message = f'{message}；原有待处理更新已保留'

    return {
        'success': True,
        'supported': True,
        'status': status,
        'message': message,
        'card_id': card_id,
        'changed': detected_change,
        'first_check': first_check,
        'baseline_established': normalized_state['baseline_established'],
        'title_changed': title_changed,
        'first_message_changed': content_changed,
        'remote_newer_than_local': remote_newer_than_local,
        'local_last_modified': _local_last_modified(card_id, card),
        'source': source,
        'source_update': normalized_state,
        'warnings': warnings,
        'checked_at': checked_at,
    }


@_source_operation_locked
def acknowledge_card_source_update(card_id, *, ui_data=None):
    """确认当前已检测到的来源版本无需处理，并保留它作为后续检查基线。"""
    card, ui_key, link, data = _resolve_card_and_source(card_id, ui_data=ui_data)
    if not card:
        return {'success': False, 'status': 'error', 'error': '找不到角色卡', 'card_id': card_id}
    if not ui_key:
        return {'success': False, 'status': 'error', 'error': '无法定位卡片 UI 数据', 'card_id': card_id}

    state = _state_for_card(data, ui_key)
    if not state.get('pending_update'):
        return {
            'success': True,
            'supported': bool(link and _parse_discord_parts(link)),
            'status': 'not_pending',
            'acknowledged': False,
            'message': _status_message('not_pending'),
            'card_id': card_id,
            'source_update': state,
        }

    next_state = dict(state)
    next_state.update({
        'pending_update': False,
        'pending_status': '',
        'pending_since': None,
        'last_status': 'acknowledged',
        'last_error': '',
    })
    changed, normalized_state = set_source_update_state(data, ui_key, next_state)
    if changed and not save_ui_data(data):
        return {
            'success': False,
            'status': 'error',
            'error': '保存来源更新状态失败',
            'card_id': card_id,
            'source_update': state,
        }

    if isinstance(card, dict):
        card['source_update'] = normalized_state
        card['source_title'] = normalized_state['source_title']

    return {
        'success': True,
        'supported': bool(link and _parse_discord_parts(link)),
        'status': 'acknowledged',
        'acknowledged': True,
        'message': _status_message('acknowledged'),
        'card_id': card_id,
        'source_update': normalized_state,
    }


@_source_operation_locked
def refresh_card_source_baseline(card_id, source_link=None, *, ui_data=None,
                                 timeout=DEFAULT_TIMEOUT, http_get=None, now=None,
                                 fetched=None):
    """在角色卡实际更新成功后，重新抓取标题和首帖时间并接受为新基线。"""
    card, ui_key, link, data = _resolve_card_and_source(card_id, source_link, ui_data)
    refreshed_at = float(now if now is not None else time.time())
    if not card:
        return {'success': False, 'status': 'error', 'error': '找不到角色卡', 'card_id': card_id}
    if not link:
        state = _reset_state_if_source_changed(data, ui_key, '', 'no_source')
        return {
            'success': True,
            'supported': False,
            'status': 'no_source',
            'message': _status_message('no_source'),
            'card_id': card_id,
            'source_update': state,
        }
    if not _parse_discord_parts(link):
        state = _reset_state_if_source_changed(data, ui_key, link, 'unsupported')
        return {
            'success': True,
            'supported': False,
            'status': 'unsupported',
            'message': _status_message('unsupported'),
            'card_id': card_id,
            'source_update': state,
        }

    if fetched is None:
        fetched = fetch_discord_source(
            link,
            timeout=timeout,
            http_get=http_get,
        )
    if not fetched.get('success'):
        state = _state_for_card(data, ui_key)
        if state.get('source_url') != link:
            state = _reset_state_if_source_changed(data, ui_key, link, 'error')
        state['source_url'] = link
        state['last_checked_at'] = refreshed_at
        state['last_status'] = 'error'
        state['last_error'] = fetched.get('error', '')
        changed, state = set_source_update_state(data, ui_key, state)
        if changed:
            save_ui_data(data)
        return {
            'success': False,
            'supported': True,
            'status': 'error',
            'error': fetched.get('error') or '刷新来源基线失败',
            'card_id': card_id,
            'source_update': state,
        }

    source = fetched.get('source') or {}
    current_title = str(source.get('title') or '').strip()
    current_revision = source.get('first_message_revision_at_epoch')
    first_message_available = bool(source.get('first_message_available')) and current_revision is not None
    if not first_message_available:
        state = _state_for_card(data, ui_key)
        state.update({
            'source_url': link,
            'source_title': current_title,
            'last_checked_at': refreshed_at,
            'last_status': 'first_message_unavailable',
            'last_error': source.get('edit_error') or '无法取得首帖编辑时间',
        })
        changed, state = set_source_update_state(data, ui_key, state)
        if changed:
            save_ui_data(data)
        if isinstance(card, dict):
            card['source_title'] = state['source_title']
            card['source_update'] = state
        return {
            'success': True,
            'supported': True,
            'status': 'first_message_unavailable',
            'message': _status_message('first_message_unavailable', state['last_error']),
            'card_id': card_id,
            'baseline_established': state['baseline_established'],
            'source': source,
            'source_update': state,
            'warnings': [state['last_error']],
            'refreshed_after_card_update': True,
        }

    next_state = {
        'source_url': link,
        'source_title': current_title,
        'first_message_edited_at': source.get('first_message_edited_at_epoch'),
        'first_message_timestamp': source.get('first_message_timestamp_epoch'),
        'first_message_revision_at': current_revision,
        'baseline_established': True,
        'pending_update': False,
        'pending_status': '',
        'pending_since': None,
        'last_checked_at': refreshed_at,
        'last_status': 'baseline_refreshed',
        'last_error': '',
    }
    changed, normalized_state = set_source_update_state(data, ui_key, next_state)
    if changed:
        save_ui_data(data)
    if isinstance(card, dict):
        card['source_title'] = normalized_state['source_title']
        card['source_update'] = normalized_state

    return {
        'success': True,
        'supported': True,
        'status': 'baseline_refreshed',
        'message': _status_message('baseline_refreshed'),
        'card_id': card_id,
        'baseline_established': True,
        'source': source,
        'source_update': normalized_state,
        'refreshed_after_card_update': True,
        'checked_at': refreshed_at,
    }
