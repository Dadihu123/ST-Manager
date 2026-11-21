import json
import logging
import os
import re
import tempfile
import threading


logger = logging.getLogger(__name__)

USER_INPUT_PATTERN = r'<本轮用户输入>\s*([\s\S]*?)\s*</本轮用户输入>'
RECALL_PATTERN = r'<recall>([\s\S]*?)</recall>'
THINKING_PATTERN = r'\[metacognition\]([\s\S]*?)(?=\n<content>|$)'
CONTENT_PATTERN = r'<content>([\s\S]*?)</content>'
SUMMARY_PATTERN = r'<details>\s*<summary>\s*小总结\s*</summary>([\s\S]*?)</details>'
CHOICE_PATTERN = r'<choice>([\s\S]*?)</choice>'
TIMEBAR_PATTERN = r'```([^`·]+·[^`]+)```'
RUNTIME_CANDIDATE_PATTERN = r'<!doctype html|<html|<head|<body|<iframe|<script|<style'
CHAT_INDEX_PREVIEW_LIMIT = 160

_CHAT_JSONL_INDEX_CACHE = {}
_CHAT_JSONL_INDEX_LOCK = threading.Lock()


def _looks_like_chat_metadata(payload):
    if not isinstance(payload, dict):
        return False
    if 'chat_metadata' in payload:
        return True
    return 'mes' not in payload and 'is_user' not in payload and 'name' not in payload


def _compile(pattern, flags=0):
    try:
        return re.compile(pattern, flags)
    except re.error:
        return None


def extract_content(message_text: str) -> str:
    if not isinstance(message_text, str) or not message_text:
        return ''

    content = message_text

    user_input_re = _compile(USER_INPUT_PATTERN, re.IGNORECASE)
    if user_input_re:
        match = user_input_re.search(content)
        if match and match.group(1):
            content = match.group(1)

    recall_re = _compile(RECALL_PATTERN, re.IGNORECASE | re.MULTILINE)
    if recall_re:
        content = recall_re.sub('', content)

    thinking_re = _compile(THINKING_PATTERN, re.IGNORECASE | re.MULTILINE)
    if thinking_re:
        content = thinking_re.sub('', content)

    content_re = _compile(CONTENT_PATTERN, re.IGNORECASE)
    if content_re:
        match = content_re.search(content)
        if match and match.group(1):
            content = match.group(1)

    content = re.sub(r'以下是用户的本轮输入[\s\S]*?</本轮用户输入>', '', content)
    return content.strip()


def parse_time_bar(message_text: str):
    if not isinstance(message_text, str) or not message_text:
        return None
    regex = _compile(TIMEBAR_PATTERN, re.IGNORECASE)
    if not regex:
        return None
    match = regex.search(message_text)
    return match.group(1).strip() if match and match.group(1) else None


def parse_summary(message_text: str):
    if not isinstance(message_text, str) or not message_text:
        return None
    regex = _compile(SUMMARY_PATTERN, re.IGNORECASE)
    if not regex:
        return None
    match = regex.search(message_text)
    return match.group(1).strip() if match and match.group(1) else None


def parse_thinking(message_text: str):
    if not isinstance(message_text, str) or not message_text:
        return None
    regex = _compile(THINKING_PATTERN, re.IGNORECASE)
    if not regex:
        return None
    match = regex.search(message_text)
    return match.group(1).strip() if match and match.group(1) else None


def parse_choices(message_text: str):
    if not isinstance(message_text, str) or not message_text:
        return []

    regex = _compile(CHOICE_PATTERN, re.IGNORECASE)
    if not regex:
        return []

    match = regex.search(message_text)
    if not match or not match.group(1):
        return []

    choices = []
    for line in match.group(1).strip().splitlines():
        item_match = re.match(r'^\s*(.+?)\s*-\s*(.+?)\s*$', line)
        if not item_match:
            continue
        choices.append({
            'text': item_match.group(1).strip(),
            'desc': item_match.group(2).strip(),
        })

    return choices


def parse_message(raw_message, floor):
    src = raw_message if isinstance(raw_message, dict) else {}
    message_text = src.get('mes', '') or ''

    return {
        'floor': int(floor),
        'name': src.get('name') or 'Unknown',
        'is_user': bool(src.get('is_user', False)),
        'is_system': bool(src.get('is_system', False)),
        'send_date': src.get('send_date') or '',
        'mes': message_text,
        'swipes': src.get('swipes') if isinstance(src.get('swipes'), list) else [],
        'extra': src.get('extra') if isinstance(src.get('extra'), dict) else {},
        'content': extract_content(message_text),
        'time_bar': parse_time_bar(message_text),
        'summary': parse_summary(message_text),
        'choices': parse_choices(message_text),
        'thinking': parse_thinking(message_text),
    }


def parse_messages(raw_messages):
    result = []
    source = raw_messages if isinstance(raw_messages, list) else []
    for index, item in enumerate(source, start=1):
        result.append(parse_message(item, index))
    return result


def _normalize_preview_text(text, limit=CHAT_INDEX_PREVIEW_LIMIT):
    source = re.sub(r'\s+', ' ', str(text or '')).strip()
    return source[:max(40, int(limit or CHAT_INDEX_PREVIEW_LIMIT))]


def _looks_like_runtime_candidate(message_text):
    if not isinstance(message_text, str) or not message_text:
        return False
    return re.search(RUNTIME_CANDIDATE_PATTERN, message_text, re.IGNORECASE) is not None


def _is_ignorable_tail_placeholder_message(raw_message):
    source = raw_message if isinstance(raw_message, dict) else {}
    if source.get('is_user') or source.get('is_system'):
        return False

    message_text = str(source.get('mes') or '').strip()
    if message_text:
        return False

    extra = source.get('extra') if isinstance(source.get('extra'), dict) else {}
    if str(extra.get('display_text') or '').strip():
        return False

    swipes = source.get('swipes') if isinstance(source.get('swipes'), list) else []
    if not swipes:
        return False

    return all(not str(item or '').strip() for item in swipes)


def _is_ignorable_tail_placeholder_index_item(index_item):
    source = index_item if isinstance(index_item, dict) else {}
    if source.get('is_user') or source.get('is_system'):
        return False

    if str(source.get('preview') or '').strip():
        return False

    return not bool(source.get('has_runtime_candidate'))


def _trim_trailing_items(items, predicate):
    source = list(items) if isinstance(items, list) else []
    while source and predicate(source[-1]):
        source.pop()
    return source


def _trim_trailing_raw_messages(raw_messages):
    return _trim_trailing_items(raw_messages, _is_ignorable_tail_placeholder_message)


def _trim_trailing_message_index(message_index):
    return _trim_trailing_items(message_index, _is_ignorable_tail_placeholder_index_item)


def build_chat_message_index_item(raw_message, floor):
    source = raw_message if isinstance(raw_message, dict) else {}
    message_text = source.get('mes', '') or ''
    preview = _normalize_preview_text(extract_content(message_text) or message_text)

    return {
        'floor': int(floor),
        'name': source.get('name') or 'Unknown',
        'is_user': bool(source.get('is_user', False)),
        'is_system': bool(source.get('is_system', False)),
        'send_date': source.get('send_date') or '',
        'preview': preview,
        'has_runtime_candidate': _looks_like_runtime_candidate(message_text),
    }


def _message_preview(parsed_messages):
    for item in parsed_messages:
        content = (item.get('content') or item.get('mes') or '').strip()
        if content:
            preview = re.sub(r'\s+', ' ', content)
            return preview[:220]
    return ''


def _guess_chat_name(file_path, metadata):
    base_name = os.path.splitext(os.path.basename(file_path or ''))[0]
    if isinstance(metadata, dict):
        chat_meta = metadata.get('chat_metadata') if isinstance(metadata.get('chat_metadata'), dict) else {}
        for key in ('chat_name', 'name', 'title', 'session_name'):
            value = chat_meta.get(key) or metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return base_name


def build_chat_stats(file_path, metadata, raw_messages, parsed_messages):
    source_messages = parsed_messages if isinstance(parsed_messages, list) else []
    trimmed_raw_messages = _trim_trailing_raw_messages(raw_messages if isinstance(raw_messages, list) else [])
    if len(trimmed_raw_messages) < len(source_messages):
        source_messages = source_messages[:len(trimmed_raw_messages)]
    created_at = ''
    if isinstance(metadata, dict):
        chat_meta = metadata.get('chat_metadata') if isinstance(metadata.get('chat_metadata'), dict) else {}
        for key in ('create_date', 'created_at', 'created', 'start_date'):
            value = chat_meta.get(key) or metadata.get(key)
            if isinstance(value, str) and value.strip():
                created_at = value.strip()
                break

    first_message_at = ''
    last_message_at = ''
    user_count = 0
    assistant_count = 0
    for item in source_messages:
        send_date = item.get('send_date') or ''
        if send_date and not first_message_at:
            first_message_at = send_date
        if send_date:
            last_message_at = send_date
        if item.get('is_user'):
            user_count += 1
        elif not item.get('is_system'):
            assistant_count += 1

    return {
        'chat_name': _guess_chat_name(file_path, metadata),
        'message_count': len(source_messages),
        'user_count': user_count,
        'assistant_count': assistant_count,
        'created_at': created_at,
        'first_message_at': first_message_at,
        'last_message_at': last_message_at,
        'preview': _message_preview(source_messages),
        'metadata': metadata if isinstance(metadata, dict) else {},
    }


def build_chat_stats_from_index(file_path, metadata, message_index):
    source_messages = _trim_trailing_message_index(message_index if isinstance(message_index, list) else [])
    created_at = ''
    if isinstance(metadata, dict):
        chat_meta = metadata.get('chat_metadata') if isinstance(metadata.get('chat_metadata'), dict) else {}
        for key in ('create_date', 'created_at', 'created', 'start_date'):
            value = chat_meta.get(key) or metadata.get(key)
            if isinstance(value, str) and value.strip():
                created_at = value.strip()
                break

    first_message_at = ''
    last_message_at = ''
    user_count = 0
    assistant_count = 0
    preview = ''

    for item in source_messages:
        send_date = item.get('send_date') or ''
        if send_date and not first_message_at:
            first_message_at = send_date
        if send_date:
            last_message_at = send_date

        if item.get('is_user'):
            user_count += 1
        elif not item.get('is_system'):
            assistant_count += 1

        if not preview:
            preview = _normalize_preview_text(item.get('preview') or '')

    return {
        'chat_name': _guess_chat_name(file_path, metadata),
        'message_count': len(source_messages),
        'user_count': user_count,
        'assistant_count': assistant_count,
        'created_at': created_at,
        'first_message_at': first_message_at,
        'last_message_at': last_message_at,
        'preview': preview,
        'metadata': metadata if isinstance(metadata, dict) else {},
    }


def invalidate_chat_jsonl_index(file_path):
    if not file_path:
        return

    abs_path = os.path.abspath(file_path)
    with _CHAT_JSONL_INDEX_LOCK:
        _CHAT_JSONL_INDEX_CACHE.pop(abs_path, None)


def get_chat_jsonl_index(file_path, *, catalog=False):
    abs_path = os.path.abspath(file_path)
    stat = os.stat(abs_path)
    file_mtime = float(stat.st_mtime)
    file_size = int(stat.st_size)

    with _CHAT_JSONL_INDEX_LOCK:
        cached = _CHAT_JSONL_INDEX_CACHE.get(abs_path)
        if (
            not catalog and isinstance(cached, dict)
            and float(cached.get('file_mtime') or 0) == file_mtime
            and int(cached.get('file_size') or 0) == file_size
        ):
            return cached

    metadata = None
    message_index = []
    offsets = []

    with open(abs_path, 'rb') as f:
        line_number = 0
        while True:
            offset = f.tell()
            line = f.readline()
            if not line:
                break

            line_number += 1
            if catalog:
                try:
                    text = line.decode('utf-8-sig' if line_number == 1 else 'utf-8').strip()
                except UnicodeDecodeError:
                    return None
                if line_number == 1:
                    from core.utils.format_validation import is_valid_chat_header
                    try:
                        if not is_valid_chat_header(json.loads(text)):
                            return None
                    except ValueError:
                        return None
            else:
                text = line.decode('utf-8', errors='ignore').strip()
            if not text:
                continue

            try:
                payload = json.loads(text)
            except json.JSONDecodeError as e:
                logger.warning(f'聊天记录索引解析失败 {abs_path}:{line_number}: {e}')
                continue

            if metadata is None and _looks_like_chat_metadata(payload):
                metadata = payload
                continue

            if not isinstance(payload, dict):
                continue

            floor = len(message_index) + 1
            message_index.append(build_chat_message_index_item(payload, floor))
            offsets.append(int(offset))

    if catalog and not line_number:
        return None
    message_index = _trim_trailing_message_index(message_index)
    offsets = offsets[:len(message_index)]

    result = {
        'file_mtime': file_mtime,
        'file_size': file_size,
        'metadata': metadata if isinstance(metadata, dict) else {},
        'message_index': message_index,
        'offsets': offsets,
    }

    if catalog:
        return result if line_number else None
    with _CHAT_JSONL_INDEX_LOCK:
        _CHAT_JSONL_INDEX_CACHE[abs_path] = result

    return result


def read_chat_jsonl(file_path):
    metadata = None
    messages = []

    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line_number, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError as e:
                logger.warning(f'聊天记录解析失败 {file_path}:{line_number}: {e}')
                continue

            if metadata is None and _looks_like_chat_metadata(payload):
                metadata = payload
                continue

            if isinstance(payload, dict):
                messages.append(payload)

    return metadata, messages


def read_chat_jsonl_range(file_path, start_floor=1, end_floor=None, index_data=None):
    index_info = index_data if isinstance(index_data, dict) else get_chat_jsonl_index(file_path)
    offsets = index_info.get('offsets') if isinstance(index_info.get('offsets'), list) else []
    total = len(offsets)
    if total <= 0:
        return index_info.get('metadata') if isinstance(index_info.get('metadata'), dict) else {}, [], []

    try:
        start_value = int(start_floor or 1)
    except (TypeError, ValueError):
        start_value = 1
    try:
        end_value = int(end_floor if end_floor is not None else total)
    except (TypeError, ValueError):
        end_value = total

    start_value = max(1, min(total, start_value))
    end_value = max(start_value, min(total, end_value))

    metadata = index_info.get('metadata') if isinstance(index_info.get('metadata'), dict) else {}
    raw_messages = []
    parsed_messages = []

    with open(file_path, 'rb') as f:
        for floor in range(start_value, end_value + 1):
            try:
                f.seek(offsets[floor - 1])
                line = f.readline().decode('utf-8', errors='ignore').strip()
                if not line:
                    continue
                payload = json.loads(line)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f'聊天记录范围读取失败 {file_path}#{floor}: {e}')
                continue

            if not isinstance(payload, dict):
                continue

            raw_messages.append(payload)
            parsed_messages.append(parse_message(payload, floor))

    return metadata, raw_messages, parsed_messages


def write_chat_jsonl(file_path, metadata, raw_messages):
    parent_dir = os.path.dirname(file_path)
    os.makedirs(parent_dir, exist_ok=True)

    fd, temp_path = tempfile.mkstemp(prefix='chat_', suffix='.tmp', dir=parent_dir)
    os.close(fd)

    try:
        with open(temp_path, 'w', encoding='utf-8', newline='\n') as f:
            if isinstance(metadata, dict) and metadata:
                f.write(json.dumps(metadata, ensure_ascii=False, separators=(',', ':')))
                f.write('\n')

            for item in raw_messages if isinstance(raw_messages, list) else []:
                if not isinstance(item, dict):
                    continue
                f.write(json.dumps(item, ensure_ascii=False, separators=(',', ':')))
                f.write('\n')

        os.replace(temp_path, file_path)
        return True
    except Exception as e:
        logger.error(f'写入聊天记录失败 {file_path}: {e}')
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        return False
