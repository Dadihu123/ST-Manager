"""Collect comparable, credential-free snapshots for Discord and Shimmerday.

The probe intentionally mirrors the two existing code paths used by ST-Manager:

* ``ForumTagFetcher``: Discord thread metadata, followed by the parent forum
  channel when applied tags are present.  The probe additionally requests the
  starter message so its real ``edited_timestamp`` can be inspected.
* ``fetch_thread_preview``: one request to the Shimmerday thread search API.

Credentials are read from environment variables or hidden prompts and are never
written to the output.  The output is intended for local diagnosis, not as a
replacement for either production service.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import platform
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

import requests


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.automation.forum_tag_fetcher import ForumTagFetcher
from core.utils.discord_url import extract_discord_thread_id


DEFAULT_OUTPUT_DIR = REPO_ROOT / 'artifacts' / 'forum_update_probe'
DISCORD_API_ROOT = 'https://discord.com/api/v10'
SHIMMERDAY_THREAD_API = 'https://forum.shimmerday.top/v1/search/thread/{thread_id}'
DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)

_SENSITIVE_KEY_PATTERN = re.compile(
    r'(authorization|cookie|token|secret|password|passwd|session|api[_-]?key)',
    re.IGNORECASE,
)
_SENSITIVE_HEADER_NAMES = {
    'authorization',
    'cookie',
    'proxy-authorization',
    'set-cookie',
    'x-auth-token',
}
_CANDIDATE_KEYS = {
    'title',
    'name',
    'updated_at',
    'updatedat',
    'last_active_at',
    'lastactiveat',
    'last_edited_at',
    'lasteditedat',
    'last_message_at',
    'lastmessageat',
    'last_message_id',
    'lastmessageid',
    'edit_timestamp',
    'edittimestamp',
    'edited_timestamp',
    'editedtimestamp',
    'timestamp',
    'archive_timestamp',
    'archivetimestamp',
    'created_at',
    'createdat',
}


def _redact_payload(value: Any) -> Any:
    """Redact sensitive-looking mapping fields before writing a response."""
    if isinstance(value, dict):
        return {
            str(key): '<redacted>'
            if _SENSITIVE_KEY_PATTERN.search(str(key))
            else _redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(text: str) -> str:
    """Remove common credential-bearing header lines from non-JSON bodies."""
    lines = []
    for line in str(text or '').splitlines():
        if ':' in line:
            header_name = line.split(':', 1)[0].strip().lower()
            if header_name in _SENSITIVE_HEADER_NAMES:
                lines.append(f'{line.split(":", 1)[0]}: <redacted>')
                continue
        lines.append(line)
    cleaned = '\n'.join(lines)
    # Also cover cookie-like values embedded in otherwise non-JSON text.
    cleaned = re.sub(
        r'''(?i)\b(?:session|sessionid|token|auth|authorization|secret|password)\s*=\s*[^;\s&,"']+''',
        lambda match: f'{match.group(0).split("=", 1)[0]}=<redacted>',
        cleaned,
    )
    cleaned = re.sub(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+', 'Bearer <redacted>', cleaned)
    return cleaned


def _safe_url(url: str) -> str:
    """Keep the navigable path while dropping potentially sensitive query data."""
    try:
        parsed = urlsplit(str(url or ''))
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))
    except ValueError:
        return '<invalid-url>'


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + '.tmp')
    temp_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False),
        encoding='utf-8',
    )
    temp_path.replace(path)


def _safe_slug(value: str, fallback: str = 'target') -> str:
    slug = re.sub(r'[^A-Za-z0-9._-]+', '_', str(value or '')).strip('._-')
    return (slug[:80] or fallback)


def _selected_response_headers(response: requests.Response) -> dict[str, str]:
    """Keep cache/size diagnostics without persisting request or auth headers."""
    allowed = {
        'cache-control',
        'content-encoding',
        'content-length',
        'content-type',
        'date',
        'etag',
        'last-modified',
        'server',
        'age',
        'vary',
        'x-cache',
        'cf-cache-status',
    }
    return {
        key: str(value)
        for key, value in response.headers.items()
        if key.lower() in allowed
    }


def _save_response_body(
    response: requests.Response,
    path_prefix: Path,
) -> tuple[str, Any | None, bool]:
    """Save a response body and return ``(filename, parsed_payload, truncated)``."""
    raw_body = response.content
    max_bytes = 20 * 1024 * 1024
    truncated = len(raw_body) > max_bytes
    body = raw_body[:max_bytes]

    payload: Any | None = None
    try:
        payload = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        payload = None

    if payload is not None and not truncated:
        output_path = path_prefix.with_suffix('.json')
        _write_json(output_path, _redact_payload(payload))
    else:
        output_path = path_prefix.with_suffix('.txt')
        text = body.decode(response.encoding or 'utf-8', errors='replace')
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_redact_text(text), encoding='utf-8')

    return output_path.name, payload, truncated


def _capture_get(
    request_get: Callable[..., requests.Response],
    *,
    name: str,
    url: str,
    headers: dict[str, str],
    timeout: float,
    output_prefix: Path,
) -> tuple[dict[str, Any], Any | None]:
    """Perform one GET and persist only safe response diagnostics."""
    started = time.perf_counter()
    try:
        # Production currently calls requests.get for each request, which uses
        # a fresh Session. Keep that behavior so timing comparisons are fair.
        response = request_get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return (
            {
                'name': name,
                'url': _safe_url(url),
                'ok': False,
                'status_code': None,
                'elapsed_ms': elapsed_ms,
                'error_type': type(exc).__name__,
                'error': _redact_text(str(exc)),
            },
            None,
        )

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    body_file, payload, truncated = _save_response_body(response, output_prefix)
    raw_size = len(response.content)
    record = {
        'name': name,
        'url': _safe_url(url),
        'ok': 200 <= response.status_code < 300,
        'status_code': response.status_code,
        'elapsed_ms': elapsed_ms,
        'response_elapsed_ms': round(response.elapsed.total_seconds() * 1000, 2),
        'response_bytes': raw_size,
        'body_sha256': hashlib.sha256(response.content).hexdigest(),
        'body_truncated': truncated,
        'body_file': body_file,
        'content_headers': _selected_response_headers(response),
    }
    return record, payload


def _candidate_fields(value: Any, *, max_items: int = 100) -> dict[str, Any]:
    """Collect likely title/timestamp fields while preserving the raw body too."""
    found: dict[str, Any] = {}

    def visit(node: Any, path: str, depth: int) -> None:
        if len(found) >= max_items or depth > 8:
            return
        if isinstance(node, dict):
            for key, child in node.items():
                key_text = str(key)
                normalized = re.sub(r'[^a-z0-9]', '', key_text.lower())
                child_path = f'{path}.{key_text}' if path else key_text
                if key_text.lower() in _CANDIDATE_KEYS or normalized in _CANDIDATE_KEYS:
                    if isinstance(child, (str, int, float, bool)) or child is None:
                        found[child_path] = _redact_payload(child)
                visit(child, child_path, depth + 1)
        elif isinstance(node, list):
            for index, child in enumerate(node[:100]):
                visit(child, f'{path}[{index}]', depth + 1)

    visit(value, '', 0)
    return found


def _discord_headers(auth_type: str, credential: str, guild_id: str, channel_id: str) -> dict[str, str]:
    headers = {
        'User-Agent': DEFAULT_USER_AGENT,
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    }
    if auth_type == 'token':
        token = str(credential or '').strip()
        if token.startswith('Bearer '):
            token = token.replace('Bearer ', '', 1).strip()
        headers['Authorization'] = token
        return headers

    cleaned_cookie = str(credential or '').strip().replace('\n', ' ').replace('\r', ' ')
    headers.update(
        {
            'Cookie': cleaned_cookie,
            'Referer': f'https://discord.com/channels/{guild_id}/{channel_id}',
            'X-Discord-Locale': 'zh-CN',
            'X-Debug-Options': 'bugReporterEnabled',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        }
    )
    super_properties = {
        'os': 'Windows',
        'browser': 'Chrome',
        'device': '',
        'system_locale': 'zh-CN',
        'browser_user_agent': DEFAULT_USER_AGENT,
        'browser_version': '120.0.0.0',
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
    return headers


def _parse_discord_parts(url: str, timeout: float) -> tuple[str | None, str | None, str | None]:
    # Use the same parser as the production tag fetcher.  It is intentionally
    # private there because this probe is diagnostic, but keeping the call here
    # prevents the two tools from silently accepting different URL formats.
    if not extract_discord_thread_id(url):
        return None, None, None
    return ForumTagFetcher(timeout=timeout)._parse_discord_thread_url(url)


def _probe_discord(
    request_get: Callable[..., requests.Response],
    *,
    url: str,
    credential: str,
    auth_type: str,
    timeout: float,
    output_dir: Path,
    prefix: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        'method': 'discord_tag_fetch',
        'source_url': _safe_url(url),
        'auth_type': auth_type,
        'requests': [],
        'extracted': {},
    }
    guild_id, channel_id, thread_id = _parse_discord_parts(url, timeout)
    if not all((guild_id, channel_id, thread_id)):
        result.update({'success': False, 'error': 'unsupported_discord_url'})
        return result

    result['thread_id'] = thread_id
    headers = _discord_headers(auth_type, credential, guild_id, channel_id)
    thread_url = f'{DISCORD_API_ROOT}/channels/{thread_id}'
    thread_record, thread_payload = _capture_get(
        request_get,
        name='thread',
        url=thread_url,
        headers=headers,
        timeout=timeout,
        output_prefix=output_dir / f'{prefix}_discord_thread',
    )
    result['requests'].append(thread_record)
    result['extracted']['thread_candidates'] = _candidate_fields(thread_payload)

    if not isinstance(thread_payload, dict):
        result.update({'success': False, 'error': 'thread_response_not_json_object'})
        return result

    applied_tags = thread_payload.get('applied_tags') or []
    parent_id = thread_payload.get('parent_id') or channel_id
    result['extracted'].update(
        {
            'title': thread_payload.get('name', ''),
            'applied_tag_ids': applied_tags,
            'parent_id': parent_id,
        }
    )

    # This conditional mirrors ForumTagFetcher exactly: no parent request is
    # made when the thread has no applied tags.
    if not applied_tags:
        result['extracted']['parent_request'] = 'skipped_no_applied_tags'
    else:
        parent_url = f'{DISCORD_API_ROOT}/channels/{parent_id}'
        parent_record, parent_payload = _capture_get(
            request_get,
            name='parent_forum',
            url=parent_url,
            headers=headers,
            timeout=timeout,
            output_prefix=output_dir / f'{prefix}_discord_parent',
        )
        result['requests'].append(parent_record)
        result['extracted']['parent_candidates'] = _candidate_fields(parent_payload)

        available_tags = []
        if isinstance(parent_payload, dict):
            available_tags = parent_payload.get('available_tags') or []
        tag_map = {
            str(item.get('id')): item.get('name', '')
            for item in available_tags
            if isinstance(item, dict) and item.get('id') is not None
        }
        result['extracted']['available_tags'] = _redact_payload(available_tags)
        result['extracted']['resolved_tag_names'] = [
            tag_map.get(str(tag_id), f'未知标签_{tag_id}') for tag_id in applied_tags
        ]

    # The tag fetcher does not need this request.  It is intentionally added
    # only by the probe so the actual first-message ``edited_timestamp`` can
    # be inspected without confusing it with ``last_pin_timestamp`` or other
    # thread activity fields.
    starter_url = f'{DISCORD_API_ROOT}/channels/{thread_id}/messages/{thread_id}'
    starter_record, starter_payload = _capture_get(
        request_get,
        name='starter_message',
        url=starter_url,
        headers=headers,
        timeout=timeout,
        output_prefix=output_dir / f'{prefix}_discord_starter_message',
    )
    result['requests'].append(starter_record)
    result['extracted']['starter_message_candidates'] = _candidate_fields(starter_payload)
    if isinstance(starter_payload, dict):
        timestamp = starter_payload.get('timestamp')
        edited_timestamp = starter_payload.get('edited_timestamp')
        result['extracted'].update(
            {
                'first_message_id': starter_payload.get('id') or thread_id,
                'first_message_timestamp': timestamp,
                'first_message_edited_timestamp': edited_timestamp,
                'first_message_revision_timestamp': edited_timestamp or timestamp,
                'first_message_available': bool(timestamp),
            }
        )
    else:
        result['extracted']['first_message_available'] = False

    tag_fetch_success = bool(
        thread_record.get('ok') and (not applied_tags or parent_record.get('ok'))
    )
    result['extracted']['tag_fetch_success'] = tag_fetch_success
    result['extracted']['starter_message_success'] = bool(starter_record.get('ok'))
    # Preserve the historical method status: the Discord tag path is healthy
    # when its thread/parent requests succeed.  Starter-message availability
    # is reported separately because it is an additional diagnostic request.
    result['success'] = tag_fetch_success
    return result


def _probe_shimmerday(
    request_get: Callable[..., requests.Response],
    *,
    url: str,
    credential: str,
    timeout: float,
    output_dir: Path,
    prefix: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        'method': 'shimmerday_search',
        'source_url': _safe_url(url),
        'requests': [],
        'extracted': {},
    }
    thread_id = extract_discord_thread_id(url)
    if not thread_id:
        result.update({'success': False, 'error': 'unsupported_discord_url'})
        return result

    result['thread_id'] = thread_id
    headers = {
        'Accept': 'application/json',
        'User-Agent': DEFAULT_USER_AGENT,
        'Cookie': str(credential or '').strip().replace('\n', ' ').replace('\r', ' '),
    }
    api_url = SHIMMERDAY_THREAD_API.format(thread_id=thread_id)
    record, payload = _capture_get(
        request_get,
        name='thread_search',
        url=api_url,
        headers=headers,
        timeout=timeout,
        output_prefix=output_dir / f'{prefix}_shimmerday_thread',
    )
    result['requests'].append(record)
    result['extracted']['candidates'] = _candidate_fields(payload)
    if isinstance(payload, dict):
        result['extracted']['top_level_keys'] = list(payload.keys())
    result['success'] = bool(record.get('ok') and payload is not None)
    return result


def _read_urls(args: argparse.Namespace) -> list[str]:
    urls = list(args.url or [])
    if args.url_file:
        path = Path(args.url_file)
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except OSError as exc:
            raise ValueError(f'无法读取 --url-file: {exc}') from exc
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                urls.append(line)

    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = str(url).strip()
        if normalized and normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def _credential(
    *,
    label: str,
    env_name: str,
    no_prompt: bool,
) -> tuple[str, str]:
    value = os.environ.get(env_name, '')
    if value:
        return value, f'env:{env_name}'
    if no_prompt:
        return '', 'missing'
    try:
        value = getpass.getpass(f'{label}（不会写入文件）: ').strip()
    except (EOFError, KeyboardInterrupt):
        print(f'\n未读取 {label}，跳过对应请求。', file=sys.stderr)
        return '', 'missing'
    return value, 'prompt' if value else 'missing'


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='采集 Discord 标签抓取与类脑搜索的可比响应快照（不会保存 Cookie/Token）。'
    )
    parser.add_argument('--url', action='append', help='Discord 类脑帖子链接，可重复传入。')
    parser.add_argument('--url-file', help='每行一个 Discord 链接的文本文件。')
    parser.add_argument(
        '--method',
        choices=('all', 'discord', 'shimmerday'),
        default='all',
        help='采集方式，默认 all。',
    )
    parser.add_argument(
        '--discord-auth',
        choices=('token', 'cookie'),
        default='cookie',
        help='Discord 标签抓取认证方式，默认 cookie。',
    )
    parser.add_argument('--discord-token-env', default='ST_PROBE_DISCORD_TOKEN')
    parser.add_argument('--discord-cookie-env', default='ST_PROBE_DISCORD_COOKIE')
    parser.add_argument('--shimmerday-cookie-env', default='ST_PROBE_SHIMMERDAY_COOKIE')
    parser.add_argument(
        '--output-dir',
        default=str(DEFAULT_OUTPUT_DIR),
        help=f'输出根目录，默认 {DEFAULT_OUTPUT_DIR}',
    )
    parser.add_argument('--timeout', type=float, default=30.0, help='单个请求超时秒数。')
    parser.add_argument(
        '--no-prompt',
        action='store_true',
        help='只使用环境变量；缺少认证时跳过请求，不弹出隐藏输入。',
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        urls = _read_urls(args)
    except ValueError as exc:
        parser.error(str(exc))
    if not urls:
        parser.error('至少需要一个 --url 或 --url-file。')
    if args.timeout <= 0:
        parser.error('--timeout 必须大于 0。')

    output_root = Path(args.output_dir).expanduser().resolve()
    run_name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8]
    output_dir = output_root / run_name
    output_dir.mkdir(parents=True, exist_ok=True)

    discord_credential = ''
    discord_source = 'not_requested'
    shimmerday_credential = ''
    shimmerday_source = 'not_requested'
    if args.method in ('all', 'discord'):
        env_name = args.discord_token_env if args.discord_auth == 'token' else args.discord_cookie_env
        label = 'Discord Token' if args.discord_auth == 'token' else 'Discord Cookie'
        discord_credential, discord_source = _credential(
            label=label,
            env_name=env_name,
            no_prompt=args.no_prompt,
        )
    if args.method in ('all', 'shimmerday'):
        shimmerday_credential, shimmerday_source = _credential(
            label='类脑搜索 Cookie',
            env_name=args.shimmerday_cookie_env,
            no_prompt=args.no_prompt,
        )

    started = time.perf_counter()
    targets: list[dict[str, Any]] = []
    for index, url in enumerate(urls, start=1):
        prefix = f'{index:03d}_{_safe_slug(extract_discord_thread_id(url) or url)}'
        target: dict[str, Any] = {'source_url': _safe_url(url), 'methods': {}}
        if args.method in ('all', 'discord'):
            if discord_credential:
                target['methods']['discord_tag_fetch'] = _probe_discord(
                    requests.get,
                    url=url,
                    credential=discord_credential,
                    auth_type=args.discord_auth,
                    timeout=args.timeout,
                    output_dir=output_dir,
                    prefix=prefix,
                )
            else:
                target['methods']['discord_tag_fetch'] = {
                    'success': False,
                    'skipped': True,
                    'error': 'missing_discord_credential',
                }
        if args.method in ('all', 'shimmerday'):
            if shimmerday_credential:
                target['methods']['shimmerday_search'] = _probe_shimmerday(
                    requests.get,
                    url=url,
                    credential=shimmerday_credential,
                    timeout=args.timeout,
                    output_dir=output_dir,
                    prefix=prefix,
                )
            else:
                target['methods']['shimmerday_search'] = {
                    'success': False,
                    'skipped': True,
                    'error': 'missing_shimmerday_credential',
                }
        targets.append(target)

    manifest = {
        'schema_version': 1,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(),
        'platform': platform.platform(),
        'timeout_seconds': args.timeout,
        'connection_reuse': False,
        'method_requested': args.method,
        'discord_auth_type': args.discord_auth if args.method in ('all', 'discord') else None,
        'credential_sources': {
            'discord': discord_source,
            'shimmerday': shimmerday_source,
        },
        'privacy': {
            'request_auth_headers_saved': False,
            'response_headers_filtered': True,
            'response_sensitive_fields_redacted': True,
            'credentials_saved': False,
        },
        'total_elapsed_ms': round((time.perf_counter() - started) * 1000, 2),
        'targets': targets,
    }
    _write_json(output_dir / 'manifest.json', manifest)
    (output_dir / 'README.txt').write_text(
        '此目录由 tools/forum_update_probe.py 生成。\n'
        'manifest.json 包含请求顺序、耗时、响应大小和候选标题/时间字段。\n'
        'Discord 额外的 starter_message 响应用于确认首帖 timestamp/edited_timestamp；生产标签抓取不发起该请求。\n'
        '响应文件已过滤请求认证头，并对敏感字段做了脱敏。\n',
        encoding='utf-8',
    )

    print(f'采集完成：{output_dir}')
    print('请将该目录中的全部文件保留在工作区，下一步可直接分析。')
    for target in targets:
        statuses = []
        for method, value in target['methods'].items():
            if value.get('skipped'):
                statuses.append(f'{method}=skipped')
                continue
            elapsed = sum(item.get('elapsed_ms', 0) for item in value.get('requests', []))
            status_text = f'{method}={"ok" if value.get("success") else "failed"}/{elapsed:.0f}ms'
            extracted = value.get('extracted') or {}
            if method == 'discord_tag_fetch' and 'starter_message_success' in extracted:
                status_text += f', starter_message={"ok" if extracted.get("starter_message_success") else "failed"}'
            statuses.append(status_text)
        print(f'- {target["source_url"]}: {", ".join(statuses)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
