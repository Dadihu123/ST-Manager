"""替换文本动作：在角色卡正文与内嵌世界书条目上执行查找/替换。

设计约束（来自需求讨论）：

- 默认按字面量匹配，可切换为正则；正则使用 Python ``re`` 语义。
- 默认不区分大小写、默认替换全部命中，都可单独关闭。
- 正则模式的替换串支持 ``\\1`` 和 ``$1`` 两种反向引用写法。
- 空查找串、无效正则、无效反向引用一律视为**配置错误**：整张卡跳过并报错，
  绝不静默降级成字面量、也绝不写回半成品。
- ``name`` 与世界书 ``keys``（触发词）默认不在目标里，但允许显式勾选：
  写进 ``keys`` 的 ``{{user}}`` 不会被 SillyTavern 展开，勾选后该条目会静默失效。
- 世界书条目的 ``entries`` 兼容数组和字典两种写法（同 ``core.utils.text``）。
"""

import copy
import re

from core.utils.text import iter_worldbook_entries

#: 默认目标：除 `name` 和世界书触发词以外的全部文本字段。
DEFAULT_TARGETS = (
    'description',
    'personality',
    'scenario',
    'first_mes',
    'mes_example',
    'creator_notes',
    'system_prompt',
    'post_history_instructions',
    'character_version',
    'alternate_greetings',
    'wi_content',
    'wi_comment',
)

#: 全部目标，顺序即执行顺序（与前端多选框顺序一致）。
ALL_TARGETS = ('name',) + DEFAULT_TARGETS + ('wi_keys',)

#: 正则标记白名单。前端只暴露 m/s（大小写由独立开关控制），
#: 但这里仍接受 i/x，兼容手改 JSON 或导入的规则集。
_ALLOWED_FLAGS = {'i', 'm', 's', 'x'}

#: 简单的字符串字段：直接读写 data_block[字段名]。
_PLAIN_FIELDS = {
    'description',
    'personality',
    'scenario',
    'first_mes',
    'mes_example',
    'creator_notes',
    'system_prompt',
    'post_history_instructions',
    'character_version',
}

_WI_TARGETS = {'wi_content', 'wi_comment', 'wi_keys'}

_USER_FLAG_PATTERN = re.compile(r'\$(\d+)')


class ReplaceConfigError(ValueError):
    """配置错误：该动作整条跳过，但同一张卡的其他动作/规则继续执行。"""


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if not text:
        return default
    return text in {'1', 'true', 'yes', 'on'}


def _normalize_targets(raw_targets):
    if raw_targets is None:
        return list(DEFAULT_TARGETS)
    if isinstance(raw_targets, str):
        raw_targets = [raw_targets]

    targets = []
    for item in raw_targets:
        target = str(item or '').strip()
        if target in ALL_TARGETS and target not in targets:
            targets.append(target)
    return targets


def normalize_config(raw_config):
    """把动作 value 规范成内部配置结构（不编译正则）。"""
    config = raw_config if isinstance(raw_config, dict) else {}
    find = config.get('find')
    if find is None:
        find = config.get('pattern')
    find = '' if find is None else str(find)

    replace = config.get('replace')
    if replace is None:
        replace = config.get('replacement')
    replace = '' if replace is None else str(replace)

    flags = config.get('flags')
    flags = '' if flags is None else str(flags)

    return {
        'find': find,
        'replace': replace,
        'regex': _as_bool(config.get('regex'), False),
        'case_sensitive': _as_bool(config.get('case_sensitive'), False),
        'first_only': _as_bool(config.get('first_only'), False),
        'flags': flags,
        'targets': _normalize_targets(config.get('targets')),
    }


def _build_flag_value(flags, case_sensitive):
    unknown = sorted(set(flags) - _ALLOWED_FLAGS)
    if unknown:
        raise ReplaceConfigError(f'不支持的正则标记: {", ".join(unknown)}')

    value = 0
    if 'i' in flags:
        value |= re.IGNORECASE
    if 'm' in flags:
        value |= re.MULTILINE
    if 's' in flags:
        value |= re.DOTALL
    if 'x' in flags:
        value |= re.VERBOSE
    if not case_sensitive:
        value |= re.IGNORECASE
    return value


def _translate_user_backrefs(replacement):
    """把 ``$1`` 归一成 Python 的 ``\\1``；``$$`` 视作字面 ``$``。"""
    return _USER_FLAG_PATTERN.sub(r'\\\1', replacement)


def compile_config(config):
    """编译成可执行的替换器；配置非法时抛 ``ReplaceConfigError``。

    返回 ``(pattern, replacement, is_regex, count)``：
    - 字面量模式返回一个**函数**替换串，避免替换内容里的反斜杠被当成反向引用；
    - 正则模式返回翻译过 ``$1`` 的模板串。
    """
    find = config['find']
    if not find:
        raise ReplaceConfigError('查找内容不能为空')

    flag_value = _build_flag_value(config['flags'], config['case_sensitive'])
    count = 1 if config['first_only'] else 0

    if not config['regex']:
        try:
            pattern = re.compile(re.escape(find), flag_value)
        except re.error as exc:  # pragma: no cover - re.escape 不会产生非法正则
            raise ReplaceConfigError(f'正则表达式无效: {exc}') from exc
        literal = config['replace']
        return pattern, (lambda _match: literal), False, count

    try:
        pattern = re.compile(find, flag_value)
    except re.error as exc:
        raise ReplaceConfigError(f'正则表达式无效: {exc}') from exc

    replacement = _translate_user_backrefs(config['replace'])
    # 反向引用写错（例如只有 2 个分组却写了 \3）只会在真正发生替换时报错，
    # 因此这里不做提前校验；实际替换由 _apply_one 统一把 re.error 转成
    # ReplaceConfigError，配合外层副本保证不会留下半改状态。
    return pattern, replacement, True, count


def _replace_in_string(value, pattern, replacement, count):
    if not isinstance(value, str) or not value:
        return value, 0
    new_value, hits = pattern.subn(replacement, value, count=count)
    return new_value, hits


def _replace_in_list(values, pattern, replacement, count):
    if not isinstance(values, list):
        return values, 0
    total = 0
    updated = []
    for item in values:
        new_item, hits = _replace_in_string(item, pattern, replacement, count)
        total += hits
        updated.append(new_item)
    return updated, total


def _replace_plain_field(data_block, field, pattern, replacement, count):
    new_value, hits = _replace_in_string(data_block.get(field), pattern, replacement, count)
    if hits:
        data_block[field] = new_value
    return hits


def _replace_greetings(data_block, pattern, replacement, count):
    new_value, hits = _replace_in_list(
        data_block.get('alternate_greetings'), pattern, replacement, count
    )
    if hits:
        data_block['alternate_greetings'] = new_value
    return hits


def _entry_comment_key(entry):
    """条目标题的落点：写回原本存在的那个字段，避免凭空造字段。"""
    for key in ('comment', 'title', 'name'):
        if key in entry:
            return key
    return 'comment'


def _replace_wi_content(entry, pattern, replacement, count):
    new_value, hits = _replace_in_string(entry.get('content'), pattern, replacement, count)
    if hits:
        entry['content'] = new_value
    return hits


def _replace_wi_comment(entry, pattern, replacement, count):
    key = _entry_comment_key(entry)
    new_value, hits = _replace_in_string(entry.get(key), pattern, replacement, count)
    if hits:
        entry[key] = new_value
    return hits


def _replace_wi_keys(entry, pattern, replacement, count):
    for key in ('keys', 'key'):
        if key not in entry:
            continue
        value = entry.get(key)
        if isinstance(value, list):
            new_value, hits = _replace_in_list(value, pattern, replacement, count)
        else:
            new_value, hits = _replace_in_string(value, pattern, replacement, count)
        if hits:
            entry[key] = new_value
        return hits
    return 0


_ENTRY_REPLACERS = {
    'wi_content': _replace_wi_content,
    'wi_comment': _replace_wi_comment,
    'wi_keys': _replace_wi_keys,
}


def _apply_one(working_info, config):
    pattern, replacement, _is_regex, count = compile_config(config)
    data_block = working_info.get('data')
    if not isinstance(data_block, dict):
        data_block = working_info

    per_target = {}
    try:
        for target in config['targets']:
            hits = 0
            if target in _PLAIN_FIELDS:
                hits = _replace_plain_field(data_block, target, pattern, replacement, count)
            elif target == 'name':
                hits = _replace_plain_field(data_block, 'name', pattern, replacement, count)
                if (
                    hits
                    and working_info is not data_block
                    and isinstance(working_info.get('name'), str)
                ):
                    # V2 兼容：root 层的 name 也同步，避免只改 data 导致旧软件读到旧名。
                    working_info['name'] = data_block['name']
            elif target == 'alternate_greetings':
                hits = _replace_greetings(data_block, pattern, replacement, count)
            elif target in _WI_TARGETS:
                replacer = _ENTRY_REPLACERS[target]
                for entry in iter_worldbook_entries(data_block):
                    hits += replacer(entry, pattern, replacement, count)
            if hits:
                per_target[target] = hits
    except re.error as exc:
        raise ReplaceConfigError(f'替换内容无效: {exc}') from exc

    return per_target


def apply_replace_text(card_info, action_values):
    """在卡片数据上执行一条或多条替换，返回结构化结果。

    Args:
        card_info: ``extract_card_info`` 返回的完整卡片字典（V3 根对象或 V2 扁平）。
        action_values: 规则里 ``replace_text`` 动作的 ``value`` 列表（按动作顺序）。

    Returns:
        dict: ``{'success', 'changed', 'total', 'per_target', 'per_action', 'errors'}``。
        只有 ``success`` 为真且 ``changed`` 为真时调用方才应写盘。
    """
    configs = []
    errors = []
    for index, raw in enumerate(action_values or []):
        try:
            config = normalize_config(raw)
            compile_config(config)
        except ReplaceConfigError as exc:
            errors.append({'index': index, 'error': str(exc)})
            continue
        configs.append(config)

    result = {
        'success': not errors,
        'changed': False,
        'total': 0,
        'per_target': {},
        'per_action': [],
        'errors': errors,
    }
    if errors or not configs:
        return result

    # 在副本上执行：任何一条中途失败都不会留下半改状态。
    working_info = copy.deepcopy(card_info)
    try:
        for index, config in enumerate(configs):
            per_target = _apply_one(working_info, config)
            action_total = sum(per_target.values())
            result['per_action'].append({
                'index': index,
                'total': action_total,
                'per_target': per_target,
            })
            result['total'] += action_total
            for target, hits in per_target.items():
                result['per_target'][target] = result['per_target'].get(target, 0) + hits
    except ReplaceConfigError as exc:
        result['success'] = False
        result['errors'].append({'index': None, 'error': str(exc)})
        return result
    except Exception as exc:  # noqa: BLE001 - 替换失败不应中断整条规则
        result['success'] = False
        result['errors'].append({'index': None, 'error': str(exc)})
        return result

    if result['total']:
        card_info.clear()
        card_info.update(working_info)
        result['changed'] = True

    return result


__all__ = [
    'ALL_TARGETS',
    'DEFAULT_TARGETS',
    'ReplaceConfigError',
    'apply_replace_text',
    'compile_config',
    'normalize_config',
]
