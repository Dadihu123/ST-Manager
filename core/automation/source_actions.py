"""来源链接自动化动作的纯数据处理 helpers。"""

import re


DEFAULT_SOURCE_TITLE_PATTERN = r'(?:【|\[)([^】\]]+)(?:】|\])'
DEFAULT_SOURCE_TITLE_CAPTURE_GROUPS = [1]
DEFAULT_SOURCE_TITLE_SPLIT_PATTERN = r'[/|]'
DEFAULT_CREATOR_FORMAT = '{{author}}'

_ALLOWED_FLAG_MAP = {
    'i': re.IGNORECASE,
    'm': re.MULTILINE,
    's': re.DOTALL,
    'x': re.VERBOSE,
}
_PLACEHOLDER_PATTERN = re.compile(r'\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}')
_MAX_PATTERN_LENGTH = 4096


def _compile_pattern(pattern, flags=''):
    pattern_text = str(pattern or '')
    if not pattern_text:
        raise ValueError('未配置正则表达式')
    if len(pattern_text) > _MAX_PATTERN_LENGTH:
        raise ValueError(f'正则表达式过长，最多支持 {_MAX_PATTERN_LENGTH} 个字符')

    flag_value = 0
    if isinstance(flags, str):
        unknown_flags = sorted(set(flags) - set(_ALLOWED_FLAG_MAP))
        if unknown_flags:
            raise ValueError(f'不支持的正则标记: {", ".join(unknown_flags)}')
        for flag in flags:
            flag_value |= _ALLOWED_FLAG_MAP[flag]

    try:
        return re.compile(pattern_text, flag_value)
    except re.error as exc:
        raise ValueError(f'正则表达式无效: {exc}') from exc


def _normalize_capture_groups(value, default_groups=None):
    if value is None:
        return list(default_groups or [0])

    raw_groups = value if isinstance(value, (list, tuple)) else [value]
    groups = []
    for item in raw_groups:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            groups.append(item)
            continue

        text = str(item or '').strip()
        if not text:
            continue
        if text.isdigit():
            groups.append(int(text))
        else:
            groups.append(text)

    return groups or list(default_groups or [0])


def _split_extracted_value(value, split_pattern, flags=''):
    text = str(value or '').strip()
    if not text:
        return []
    if not str(split_pattern or '').strip():
        return [text]

    splitter = _compile_pattern(split_pattern, flags=flags)
    return [part.strip() for part in splitter.split(text) if part and part.strip()]


def extract_source_title_tags(title, config=None):
    """使用用户自定义正则从来源标题中提取标签。"""
    cfg = config if isinstance(config, dict) else {}
    title_text = str(title or '').strip()
    pattern_text = str(cfg.get('pattern') or DEFAULT_SOURCE_TITLE_PATTERN).strip()
    flags = str(cfg.get('flags') or '')
    capture_groups = _normalize_capture_groups(
        cfg.get('capture_groups', cfg.get('capture_group')),
        default_groups=DEFAULT_SOURCE_TITLE_CAPTURE_GROUPS,
    )
    split_pattern = cfg.get('split_pattern')
    if split_pattern is None:
        split_pattern = DEFAULT_SOURCE_TITLE_SPLIT_PATTERN

    result = {
        'success': False,
        'title': title_text,
        'pattern': pattern_text,
        'capture_groups': capture_groups,
        'split_pattern': str(split_pattern or ''),
        'matched_values': [],
        'extracted_tags': [],
        'match_count': 0,
    }

    try:
        compiled = _compile_pattern(pattern_text, flags=flags)
        # 编译分隔正则提前完成，避免在有匹配结果时才暴露配置错误。
        if str(split_pattern or '').strip():
            _compile_pattern(split_pattern, flags=flags)
    except ValueError as exc:
        result['error'] = str(exc)
        return result

    if not title_text:
        result['success'] = True
        return result

    tags = []
    try:
        for match in compiled.finditer(title_text):
            result['match_count'] += 1
            for group in capture_groups:
                try:
                    value = match.group(group)
                except (IndexError, KeyError):
                    result['error'] = f'捕获组不存在: {group}'
                    return result

                if value is None:
                    continue
                value_text = str(value).strip()
                if not value_text:
                    continue
                result['matched_values'].append(value_text)
                for tag in _split_extracted_value(value_text, split_pattern, flags=flags):
                    if tag not in tags:
                        tags.append(tag)
    except ValueError as exc:
        result['error'] = str(exc)
        return result

    result['success'] = True
    result['extracted_tags'] = tags
    return result


def normalize_source_author(author):
    """将 Discord/类脑的作者对象统一为自动化动作使用的字段。"""
    if isinstance(author, str):
        author = {'username': author}
    if not isinstance(author, dict):
        return None

    author_id = str(author.get('id') or '').strip()
    username = str(author.get('username') or author.get('name') or '').strip()
    display_name = str(
        author.get('display_name')
        or author.get('global_name')
        or username
        or ''
    ).strip()
    global_name = str(author.get('global_name') or display_name or username or '').strip()

    if not any((author_id, username, display_name, global_name)):
        return None

    return {
        'id': author_id,
        'username': username,
        'name': username,
        'display_name': display_name,
        'global_name': global_name,
    }


def _creator_context(source, author, author_field):
    normalized_author = normalize_source_author(author) or {}
    field_name = str(author_field or 'username').strip().lower()
    if field_name in {'id', 'author_id'}:
        selected_author = normalized_author.get('id', '')
    elif field_name in {'display', 'display_name'}:
        selected_author = normalized_author.get('display_name', '')
    elif field_name == 'global_name':
        selected_author = normalized_author.get('global_name', '')
    else:
        selected_author = (
            normalized_author.get('username')
            or normalized_author.get('name')
            or normalized_author.get('display_name')
            or ''
        )

    return {
        'author': selected_author,
        'username': normalized_author.get('username', ''),
        'name': normalized_author.get('name', ''),
        'display_name': normalized_author.get('display_name', ''),
        'global_name': normalized_author.get('global_name', ''),
        'author_id': normalized_author.get('id', ''),
        'title': str((source or {}).get('title') or '').strip(),
        'source_url': str((source or {}).get('source_url') or '').strip(),
    }


def render_source_creator(template, source=None, author=None, author_field='username'):
    """将来源作者和标题字段渲染为创作者文本。"""
    raw_template = str(template if template is not None else DEFAULT_CREATOR_FORMAT)
    context = _creator_context(source or {}, author, author_field)

    def replace_placeholder(match):
        return str(context.get(match.group(1), '') or '')

    return _PLACEHOLDER_PATTERN.sub(replace_placeholder, raw_template).strip()


__all__ = [
    'DEFAULT_CREATOR_FORMAT',
    'DEFAULT_SOURCE_TITLE_CAPTURE_GROUPS',
    'DEFAULT_SOURCE_TITLE_PATTERN',
    'DEFAULT_SOURCE_TITLE_SPLIT_PATTERN',
    'extract_source_title_tags',
    'normalize_source_author',
    'render_source_creator',
]
