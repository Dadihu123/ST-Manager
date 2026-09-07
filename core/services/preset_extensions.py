"""Compatibility helpers for preset-managed extension payloads."""

from copy import deepcopy


REGEX_EXTENSION_KEYS = frozenset(
    {
        'regex_scripts',
        'regexScripts',
        'regex',
        'regexes',
        'regular_expressions',
    }
)
REGEX_EXTENSION_KEY_ORDER = (
    'regex_scripts',
    'regexScripts',
    'regex',
    'regexes',
    'regular_expressions',
)

TAVERN_HELPER_EXTENSION_KEYS = frozenset(
    {
        'tavern_helper',
        'tavernHelper',
        'TavernHelper_scripts',
        'tavern_helper_scripts',
        'tavernHelper_scripts',
        'TavernHelper',
        'scripts',
    }
)

MANAGED_EXTENSION_KEYS = frozenset(
    {
        *REGEX_EXTENSION_KEYS,
        *TAVERN_HELPER_EXTENSION_KEYS,
        'SPreset',
        'RegexBinding',
    }
)


def is_managed_extension_key(key) -> bool:
    return str(key or '') in MANAGED_EXTENSION_KEYS


def _unwrap_script_item(item):
    if isinstance(item, dict) and isinstance(item.get('value'), dict):
        return item['value']
    return item


def _extract_tavern_script_list(value):
    if isinstance(value, dict):
        scripts = value.get('scripts')
        if isinstance(scripts, list):
            return scripts
        if isinstance(scripts, dict):
            return list(scripts.values())
        return []

    if not isinstance(value, list):
        return []

    for item in value:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and item[0] == 'scripts'
            and isinstance(item[1], list)
        ):
            return item[1]

    if all(isinstance(item, dict) for item in value):
        return value
    return []


def extract_tavern_helper_scripts(extensions) -> list:
    if not isinstance(extensions, dict):
        return []

    candidates = [
        extensions.get('tavern_helper'),
        extensions.get('tavernHelper'),
        extensions.get('TavernHelper_scripts'),
        extensions.get('tavern_helper_scripts'),
        extensions.get('tavernHelper_scripts'),
        extensions.get('TavernHelper'),
        extensions.get('scripts'),
    ]
    for candidate in candidates:
        scripts = _extract_tavern_script_list(candidate)
        if scripts:
            return [
                unwrapped
                for item in scripts
                for unwrapped in [_unwrap_script_item(item)]
                if isinstance(unwrapped, dict)
            ]
    return []


def _extract_regex_list(value):
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []

    for key in ('regex_scripts', 'regexScripts', 'regex', 'regexes', 'regular_expressions'):
        nested = value.get(key)
        if isinstance(nested, list):
            return nested

    if any(key in value for key in ('findRegex', 'pattern', 'expression', 'match')):
        return [value]
    return []


def extract_regex_script_items(extensions) -> list:
    if not isinstance(extensions, dict):
        return []

    candidates = [extensions.get(key) for key in REGEX_EXTENSION_KEY_ORDER]
    spreset = extensions.get('SPreset')
    if isinstance(spreset, dict):
        candidates.extend(
            [
                spreset.get('regex'),
                spreset.get('regexes'),
                spreset.get('regular_expressions'),
                spreset.get('RegexBinding'),
            ]
        )
    candidates.append(extensions.get('RegexBinding'))

    for candidate in candidates:
        items = _extract_regex_list(candidate)
        if items:
            return items
    return []


def _has_regex_source(extensions) -> bool:
    if not isinstance(extensions, dict):
        return False
    if any(key in extensions for key in REGEX_EXTENSION_KEYS):
        return True
    for container_key in ('SPreset', 'RegexBinding'):
        container = extensions.get(container_key)
        if isinstance(container, dict) and any(
            key in container
            for key in ('regex', 'regexes', 'regular_expressions', 'RegexBinding')
        ):
            return True
    return False


def _has_tavern_helper_source(extensions) -> bool:
    return isinstance(extensions, dict) and any(
        key in extensions for key in TAVERN_HELPER_EXTENSION_KEYS
    )


def _extract_helper_variables(helper):
    if isinstance(helper, dict) and isinstance(helper.get('variables'), dict):
        return helper['variables']
    if isinstance(helper, list):
        for item in helper:
            if (
                isinstance(item, list)
                and len(item) >= 2
                and item[0] == 'variables'
                and isinstance(item[1], dict)
            ):
                return item[1]
    return {}


def normalize_extensions_for_save(extensions):
    """Canonicalize managed extension data while preserving unrelated keys."""
    result = deepcopy(extensions) if isinstance(extensions, dict) else {}

    if _has_regex_source(result):
        result['regex_scripts'] = deepcopy(extract_regex_script_items(result))
        for key in REGEX_EXTENSION_KEYS - {'regex_scripts'}:
            result.pop(key, None)
        result.pop('RegexBinding', None)

    if _has_tavern_helper_source(result):
        scripts = deepcopy(extract_tavern_helper_scripts(result))
        variables = deepcopy(_extract_helper_variables(result.get('tavern_helper')))
        result['tavern_helper'] = {'scripts': scripts, 'variables': variables}
        for key in TAVERN_HELPER_EXTENSION_KEYS - {'tavern_helper'}:
            result.pop(key, None)

    return result
