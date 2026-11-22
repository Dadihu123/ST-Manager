from core.context import ctx
from core.data.ui_store import get_tag_management_prefs, get_tag_taxonomy, load_ui_data


def _normalize_tags(tags):
    if isinstance(tags, str):
        tags = [tags]
    elif not isinstance(tags, (list, tuple, set)):
        return []

    out = []
    seen = set()
    for item in tags:
        if item is None:
            continue
        tag = str(item).strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag)
    return out


def build_known_tag_set(ui_data=None, taxonomy=None):
    taxonomy_data = taxonomy if isinstance(taxonomy, dict) else get_tag_taxonomy(ui_data)
    known_tags = set(_normalize_tags(getattr(ctx.cache, 'global_tags', None)))

    tag_to_category = taxonomy_data.get('tag_to_category')
    if isinstance(tag_to_category, dict):
        for raw_tag in tag_to_category.keys():
            tag = str(raw_tag).strip()
            if tag:
                known_tags.add(tag)

    category_tag_order = taxonomy_data.get('category_tag_order')
    if isinstance(category_tag_order, dict):
        for raw_tags in category_tag_order.values():
            for tag in _normalize_tags(raw_tags):
                known_tags.add(tag)

    return known_tags


def filter_governed_tags(tags, ui_data=None, prefs=None, known_tags=None):
    normalized_tags = _normalize_tags(tags)
    prefs_data = prefs if isinstance(prefs, dict) else get_tag_management_prefs(ui_data)

    blacklist = set(_normalize_tags(prefs_data.get('tag_blacklist') or []))
    lock_tag_library = bool(prefs_data.get('lock_tag_library'))
    known_tag_set = known_tags if known_tags is not None else build_known_tag_set(ui_data=ui_data)

    accepted = []
    skipped_unknown = []
    skipped_blacklist = []

    for tag in normalized_tags:
        if tag in blacklist:
            skipped_blacklist.append(tag)
            continue
        if lock_tag_library and tag not in known_tag_set:
            skipped_unknown.append(tag)
            continue
        accepted.append(tag)

    return {
        'accepted': accepted,
        'skipped_unknown': skipped_unknown,
        'skipped_blacklist': skipped_blacklist,
    }


def build_governance_feedback(filtered):
    payload = filtered if isinstance(filtered, dict) else {}
    return {
        'skipped_unknown': list(payload.get('skipped_unknown') or []),
        'skipped_blacklist': list(payload.get('skipped_blacklist') or []),
    }


def card_tag_data(card_info):
    data = card_info.get('data')
    return data if isinstance(data, dict) else card_info


def card_tag_list(card_info):
    tags = card_tag_data(card_info).get('tags', card_info.get('tags'))
    return _normalize_tags(tags.split(',') if isinstance(tags, str) else tags)


def govern_card_tag_additions(card_info, *, previous_tags=(), merge=False, ui_data=None):
    """Filter incoming additions and keep existing tags on overwrite imports."""
    incoming = card_tag_list(card_info)
    if not incoming and not merge:
        return False
    if ui_data is None:
        ui_data = load_ui_data()
    prefs = get_tag_management_prefs(ui_data)
    if not merge and not (prefs['tag_blacklist'] or prefs['lock_tag_library']):
        return False
    previous = set(previous_tags)
    accepted = set(filter_governed_tags(
        [tag for tag in incoming if tag not in previous], ui_data=ui_data, prefs=prefs,
    )['accepted'])
    retained = [tag for tag in incoming if tag in previous or tag in accepted]
    result = list(dict.fromkeys([*previous_tags, *retained])) if merge else retained
    if result == incoming:
        return False
    data = card_tag_data(card_info)
    data['tags'] = result
    if data is not card_info and 'tags' in card_info:
        card_info['tags'] = result
    return True
