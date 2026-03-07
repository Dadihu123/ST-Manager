import json
import logging
import os
import re
import tempfile


logger = logging.getLogger(__name__)

USER_INPUT_PATTERN = r'<本轮用户输入>\s*([\s\S]*?)\s*</本轮用户输入>'
RECALL_PATTERN = r'<recall>([\s\S]*?)</recall>'
THINKING_PATTERN = r'\[metacognition\]([\s\S]*?)(?=\n<content>|$)'
CONTENT_PATTERN = r'<content>([\s\S]*?)</content>'
SUMMARY_PATTERN = r'<details>\s*<summary>\s*小总结\s*</summary>([\s\S]*?)</details>'
CHOICE_PATTERN = r'<choice>([\s\S]*?)</choice>'
TIMEBAR_PATTERN = r'```([^`·]+·[^`]+)```'


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
