import logging

logger = logging.getLogger(__name__)

def _coerce_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ('true', '1', 'yes', 'on', 'enabled'):
            return True
        if lowered in ('false', '0', 'no', 'off', 'disabled', ''):
            return False
        return True
    return bool(value)

def _normalize_regex_item(item, name_hint: str = None):
    """
    将各种格式的正则条目标准化为统一结构。
    返回 None 表示无有效 pattern。
    """
    if item is None:
        return None

    # 字符串格式
    if isinstance(item, str):
        pattern = item.strip()
        if not pattern:
            return None
        return {
            'name': name_hint or 'regex',
            'description': '',
            'pattern': pattern,
            'replace': '',
            'flags': '',
            'enabled': True,
            'scope': [],
        }

    if not isinstance(item, dict):
        return None

    pattern = (
        item.get('pattern') or
        item.get('regex') or
        item.get('expression') or
        item.get('match') or
        item.get('findRegex') or
        item.get('find') or
        item.get('regexPattern') or
        ''
    )
    if not pattern:
        return None

    name = item.get('name') or item.get('label') or item.get('scriptName') or name_hint or 'regex'
    flags = item.get('flags') or item.get('modifiers') or ''
    replace = (
        item.get('replace') or
        item.get('replacement') or
        item.get('replaceString') or
        ''
    )
    description = item.get('description') or item.get('comment') or ''
    if 'enabled' in item:
        enabled_value = item.get('enabled')
        if isinstance(enabled_value, str) and enabled_value.strip() == '':
            enabled = True
        else:
            enabled = _coerce_bool(enabled_value)
    elif 'disabled' in item:
        enabled = not _coerce_bool(item.get('disabled'))
    else:
        enabled = True
    scope = item.get('placement') or item.get('scope') or []

    return {
        'name': name,
        'description': description,
        'pattern': pattern,
        'replace': replace,
        'flags': flags,
        'enabled': enabled,
        'scope': scope if isinstance(scope, list) else [],
    }

def _extract_from_block(block):
    results = []
    if not block:
        return results

    # 列表格式
    if isinstance(block, list):
        for item in block:
            normalized = _normalize_regex_item(item)
            if normalized:
                results.append(normalized)
        return results

    # 字符串格式
    if isinstance(block, str):
        normalized = _normalize_regex_item(block)
        if normalized:
            results.append(normalized)
        return results

    if not isinstance(block, dict):
        return results

    # 若本身就是规则对象
    normalized = _normalize_regex_item(block)
    if normalized:
        results.append(normalized)
        return results

    # RegexBinding / 扩展格式：{ regexes: [...] }
    if isinstance(block.get('regexes'), list):
        for idx, item in enumerate(block.get('regexes') or []):
            name_hint = block.get('name') or f"regex_{idx}"
            normalized = _normalize_regex_item(item, name_hint=name_hint)
            if normalized:
                results.append(normalized)
        return results

    # 普通字典：遍历各 key
    for key, value in block.items():
        if value is None:
            continue
        if isinstance(value, str):
            normalized = _normalize_regex_item(value, name_hint=str(key))
            if normalized:
                results.append(normalized)
            continue
        if isinstance(value, dict):
            # RegexBinding 格式
            if isinstance(value.get('regexes'), list):
                for idx, item in enumerate(value.get('regexes') or []):
                    name_hint = value.get('name') or f"{key}_{idx}"
                    normalized = _normalize_regex_item(item, name_hint=name_hint)
                    if normalized:
                        results.append(normalized)
                continue

            normalized = _normalize_regex_item(value, name_hint=str(key))
            if normalized:
                results.append(normalized)
                continue

            # 其他脚本格式
            if value.get('script'):
                pattern = value.get('find') or value.get('pattern') or ''
                if pattern:
                    results.append({
                        'name': str(key),
                        'description': (value.get('script') or '')[:100] or 'Script based regex',
                        'pattern': pattern,
                        'replace': value.get('replace') or '',
                        'flags': '',
                        'enabled': not _coerce_bool(value.get('disabled')),
                        'scope': [],
                    })
            continue

        if isinstance(value, list):
            # 嵌套列表
            for item in value:
                normalized = _normalize_regex_item(item, name_hint=str(key))
                if normalized:
                    results.append(normalized)

    return results

def extract_regex_from_blocks(blocks):
    merged = []
    seen = set()

    for block in blocks:
        for item in _extract_from_block(block):
            key = f"{item.get('pattern','')}__{item.get('flags','')}__{item.get('replace','')}"
            if not item.get('pattern'):
                continue
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

    return merged

def extract_regex_from_preset_data(raw):
    if not isinstance(raw, dict):
        return []

    candidates = [
        raw.get('regex'),
        raw.get('regexes'),
        raw.get('regular_expressions'),
        raw.get('extensions', {}).get('regex'),
        raw.get('extensions', {}).get('regexes'),
        raw.get('extensions', {}).get('regular_expressions'),
        raw.get('extension_settings', {}).get('regex'),
        raw.get('extension_settings', {}).get('regexes'),
        raw.get('extension_settings', {}).get('regular_expressions'),
        raw.get('extensions', {}).get('regex_scripts'),
        raw.get('extension_settings', {}).get('regex_scripts'),
        raw.get('extensions', {}).get('scripts'),
        raw.get('extension_settings', {}).get('scripts'),
        raw.get('extensions', {}).get('SPreset', {}).get('regex'),
        raw.get('extensions', {}).get('SPreset', {}).get('regexes'),
        raw.get('extension_settings', {}).get('SPreset', {}).get('regex'),
        raw.get('extension_settings', {}).get('SPreset', {}).get('regexes'),
        raw.get('extensions', {}).get('SPreset', {}).get('RegexBinding', {}).get('regexes'),
        raw.get('extension_settings', {}).get('SPreset', {}).get('RegexBinding', {}).get('regexes'),
        raw.get('regex_scripts'),
        raw.get('regexScripts'),
    ]

    # prompts 中嵌入的 regex
    prompts = raw.get('prompts')
    if isinstance(prompts, list):
        for prompt in prompts:
            if isinstance(prompt, dict) and 'regex' in prompt:
                candidates.append(prompt.get('regex'))

    return extract_regex_from_blocks(candidates)

def extract_global_regex_from_settings(raw):
    if not isinstance(raw, dict):
        return []

    merged = []
    seen = set()

    def merge(items):
        for item in items or []:
            key = f"{item.get('pattern','')}__{item.get('flags','')}__{item.get('replace','')}"
            if not item.get('pattern'):
                continue
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

    # 先按 st-external-bridge 的思路，从可疑对象中抽取
    base_blocks = [
        raw,
        raw.get('extensions'),
        raw.get('extension_settings'),
        raw.get('client_settings'),
        raw.get('clientSettings'),
        raw.get('frontend'),
    ]
    for block in base_blocks:
        if isinstance(block, dict):
            merge(extract_regex_from_preset_data(block))

    # 再补充 find/replace / regex_scripts 等常见全局来源
    extra_blocks = [
        raw.get('regex_scripts'),
        raw.get('regexScripts'),
        raw.get('find_replace'),
        raw.get('findReplace'),
        raw.get('find_and_replace'),
        raw.get('findAndReplace'),
        raw.get('global_regex'),
        raw.get('globalRegex'),
        (raw.get('frontend') or {}).get('regex_scripts'),
        (raw.get('frontend') or {}).get('find_replace'),
        (raw.get('frontend') or {}).get('find_and_replace'),
        (raw.get('client_settings') or {}).get('regex_scripts'),
        (raw.get('client_settings') or {}).get('find_replace'),
        (raw.get('client_settings') or {}).get('find_and_replace'),
        (raw.get('clientSettings') or {}).get('regex_scripts'),
        (raw.get('clientSettings') or {}).get('find_replace'),
        (raw.get('clientSettings') or {}).get('find_and_replace'),
        (raw.get('extension_settings') or {}).get('regex_scripts'),
        (raw.get('extension_settings') or {}).get('find_replace'),
        (raw.get('extension_settings') or {}).get('find_and_replace'),
        (raw.get('extension_settings') or {}).get('regex'),
        (raw.get('extension_settings') or {}).get('regexes'),
        (raw.get('extensions') or {}).get('regex'),
        (raw.get('extensions') or {}).get('regexes'),
    ]
    for block in extra_blocks:
        if block is None:
            continue
        merge(extract_regex_from_blocks([block]))

    return merged
