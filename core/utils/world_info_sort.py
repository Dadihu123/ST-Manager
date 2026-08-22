"""SillyTavern-compatible ordering helpers for world-info previews."""

from functools import cmp_to_key


WI_SORT_MODES = {
    'priority',
    'custom',
    'title_asc',
    'title_desc',
    'tokens_asc',
    'tokens_desc',
    'depth_asc',
    'depth_desc',
    'order_asc',
    'order_desc',
    'uid_asc',
    'uid_desc',
    'probability_asc',
    'probability_desc',
}


def normalize_world_info_sort_mode(value):
    mode = str(value or '').strip()
    return mode if mode in WI_SORT_MODES else 'priority'


def _number(value, fallback=0.0):
    try:
        number = float(value)
        return number if number == number else fallback
    except (TypeError, ValueError):
        return fallback


def _order(entry):
    value = entry.get('insertion_order')
    if value is None:
        value = entry.get('order', 0)
    return _number(value, 0)


def _uid(entry, fallback_index):
    value = entry.get('uid')
    if value is None or value == '':
        value = entry.get('st_source_id')
    if value is None or value == '':
        value = entry.get('id', fallback_index)
    return value


def _uid_compare(left, right):
    left_num = _number(left, None)
    right_num = _number(right, None)
    if left_num is not None and right_num is not None:
        return (left_num > right_num) - (left_num < right_num)
    left_text = str(left).casefold()
    right_text = str(right).casefold()
    return (left_text > right_text) - (left_text < right_text)


def _text(entry):
    return str(entry.get('comment', entry.get('title', '')) or '').casefold()


def _priority(entry):
    if entry.get('disable') is True or entry.get('enabled') is False:
        return 2
    if entry.get('constant') is True:
        return 0
    return 1


def _primary_compare(left, right, left_index, right_index, mode):
    if mode == 'priority':
        return _priority(left) - _priority(right)
    if mode == 'custom':
        left_extensions = left.get('extensions') if isinstance(left.get('extensions'), dict) else {}
        right_extensions = right.get('extensions') if isinstance(right.get('extensions'), dict) else {}
        left_display = left.get('displayIndex', left_extensions.get('display_index'))
        right_display = right.get('displayIndex', right_extensions.get('display_index'))
        left_uid = _uid(left, left_index)
        right_uid = _uid(right, right_index)
        left_value = _number(left_display, _number(left_uid, left_index))
        right_value = _number(right_display, _number(right_uid, right_index))
        return (left_value > right_value) - (left_value < right_value)
    if mode in {'title_asc', 'title_desc'}:
        result = ( _text(left) > _text(right)) - (_text(left) < _text(right))
        return result if mode.endswith('_asc') else -result
    if mode in {'tokens_asc', 'tokens_desc'}:
        left_value = len(str(left.get('content') or ''))
        right_value = len(str(right.get('content') or ''))
        result = (left_value > right_value) - (left_value < right_value)
        return result if mode.endswith('_asc') else -result
    if mode in {'depth_asc', 'depth_desc'}:
        result = (_number(left.get('depth')) > _number(right.get('depth'))) - (
            _number(left.get('depth')) < _number(right.get('depth'))
        )
        return result if mode.endswith('_asc') else -result
    if mode in {'order_asc', 'order_desc'}:
        result = (_order(left) > _order(right)) - (_order(left) < _order(right))
        return result if mode.endswith('_asc') else -result
    if mode in {'uid_asc', 'uid_desc'}:
        result = _uid_compare(_uid(left, left_index), _uid(right, right_index))
        return result if mode.endswith('_asc') else -result
    if mode in {'probability_asc', 'probability_desc'}:
        result = (_number(left.get('probability'), 100) > _number(right.get('probability'), 100)) - (
            _number(left.get('probability'), 100) < _number(right.get('probability'), 100)
        )
        return result if mode.endswith('_asc') else -result
    return 0


def compare_world_info_entries(left_item, right_item, mode='priority'):
    left, left_index = left_item
    right, right_index = right_item
    normalized_mode = normalize_world_info_sort_mode(mode)
    primary = _primary_compare(left, right, left_index, right_index, normalized_mode)
    if primary:
        return primary

    secondary = (_order(right) > _order(left)) - (_order(right) < _order(left))
    if secondary:
        return secondary
    return _uid_compare(_uid(left, left_index), _uid(right, right_index))


def sort_world_info_entries(entries, mode='priority'):
    decorated = [(entry, index) for index, entry in enumerate(entries or []) if isinstance(entry, dict)]
    decorated.sort(key=cmp_to_key(lambda left, right: compare_world_info_entries(left, right, mode)))
    return [entry for entry, _index in decorated]


def sort_world_info_mapping(entries, mode='priority'):
    decorated = [((key, value), index) for index, (key, value) in enumerate((entries or {}).items()) if isinstance(value, dict)]

    def comparable(item):
        key, value = item[0]
        entry = value
        if (
            entry.get('uid') in (None, '')
            and entry.get('st_source_id') in (None, '')
            and entry.get('id') in (None, '')
        ):
            entry = {**entry, 'uid': key}
        return entry, item[1]

    decorated.sort(key=cmp_to_key(lambda left, right: compare_world_info_entries(comparable(left), comparable(right), mode)))
    return [item for item, _index in decorated]
