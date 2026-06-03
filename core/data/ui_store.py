import os
import json
import logging
import shutil
import tempfile
import threading
import time
from core.config import DB_FOLDER
from core.consts import RESERVED_RESOURCE_NAMES

# 定义存储文件路径
UI_DATA_FILE = os.path.join(DB_FOLDER, 'ui_data.json')

logger = logging.getLogger(__name__)

_UI_DATA_LOCK = threading.RLock()

VERSION_REMARKS_KEY = '_version_remarks'
IMPORT_TIME_KEY = 'import_time'
LAST_SENT_TO_ST_KEY = 'last_sent_to_st'
TAG_TAXONOMY_KEY = '_tag_taxonomy_v1'
TAG_MANAGEMENT_PREFS_KEY = '_tag_management_prefs_v1'
ISOLATED_CATEGORIES_KEY = '_isolated_categories_v1'
RESOURCE_ITEM_CATEGORIES_KEY = '_resource_item_categories_v1'
WORLDINFO_NOTES_KEY = '_worldinfo_notes_v1'
BEAUTIFY_LIBRARY_KEY = '_beautify_library_v1'
SHARED_WALLPAPER_LIBRARY_KEY = '_shared_wallpaper_library_v1'

DEFAULT_TAG_CATEGORY = '未分类'
DEFAULT_TAG_CATEGORY_COLOR = '#64748b'
DEFAULT_TAG_CATEGORY_OPACITY = 16


def _normalize_timestamp(value):
    """将时间戳规范为正浮点数，非法值返回 None。"""
    if isinstance(value, bool):
        return None

    try:
        ts = float(value)
    except (TypeError, ValueError):
        return None

    if ts <= 0:
        return None
    return ts


def _normalize_hex_color(value, fallback=DEFAULT_TAG_CATEGORY_COLOR):
    """规范化 16 进制颜色值，非法值回退到 fallback。"""
    fallback_color = fallback if isinstance(fallback, str) and fallback else DEFAULT_TAG_CATEGORY_COLOR

    if not isinstance(value, str):
        return fallback_color

    color = value.strip()
    if not color:
        return fallback_color

    if not color.startswith('#'):
        color = f'#{color}'

    short_hex = color[1:]
    if len(short_hex) == 3 and all(ch in '0123456789abcdefABCDEF' for ch in short_hex):
        return '#' + ''.join(ch * 2 for ch in short_hex).lower()

    if len(short_hex) == 6 and all(ch in '0123456789abcdefABCDEF' for ch in short_hex):
        return color.lower()

    return fallback_color


def _normalize_opacity(value, fallback=DEFAULT_TAG_CATEGORY_OPACITY):
    """规范化透明度百分比，范围 0~100。"""
    fallback_value = fallback
    try:
        fallback_value = int(float(fallback))
    except (TypeError, ValueError):
        fallback_value = DEFAULT_TAG_CATEGORY_OPACITY

    fallback_value = max(0, min(100, fallback_value))

    if isinstance(value, bool):
        return fallback_value

    try:
        normalized = int(float(value))
    except (TypeError, ValueError):
        return fallback_value

    return max(0, min(100, normalized))


def _normalize_category_name(value):
    if value is None:
        return ''
    return str(value).strip()


def _normalize_tag_name(value):
    if value is None:
        return ''
    return str(value).strip()


def _normalize_isolated_category_path(value):
    path = _normalize_category_name(value).replace('\\', '/').strip('/')
    if not path:
        return ''

    parts = [part.strip() for part in path.split('/') if str(part).strip()]
    if not parts:
        return ''

    return '/'.join(parts)


def _normalize_isolated_categories(raw):
    source = raw
    if isinstance(raw, list):
        source = {'paths': raw}
    elif not isinstance(raw, dict):
        source = {}

    raw_paths = source.get('paths')
    if not isinstance(raw_paths, list):
        raw_paths = []

    normalized_paths = []
    for raw_path in raw_paths:
        path = _normalize_isolated_category_path(raw_path)
        if not path:
            continue
        normalized_paths.append(path)

    normalized_paths.sort(key=lambda item: (item.count('/'), item.lower()))

    collapsed_paths = []
    for path in normalized_paths:
        if any(path == existing or path.startswith(existing + '/') for existing in collapsed_paths):
            continue
        collapsed_paths.append(path)

    updated_at = 0
    try:
        updated_at = int(source.get('updated_at') or 0)
    except (TypeError, ValueError):
        updated_at = 0

    if updated_at < 0:
        updated_at = 0

    return {
        'paths': collapsed_paths,
        'updated_at': updated_at,
    }


def _normalize_resource_item_category_path(value):
    if value is None:
        return ''

    path = os.path.normcase(os.path.normpath(str(value).strip()))
    if not path or path == '.':
        return ''
    return path.replace('\\', '/')


def _normalize_resource_item_categories(raw):
    source = raw if isinstance(raw, dict) else {}
    result = {
        'worldinfo': {},
        'presets': {},
        'updated_at': 0,
    }

    for mode in ('worldinfo', 'presets'):
        raw_items = source.get(mode)
        if not isinstance(raw_items, dict):
            continue

        normalized_items = {}
        for raw_path, raw_cfg in raw_items.items():
            path_key = _normalize_resource_item_category_path(raw_path)
            if not path_key:
                continue

            cfg = raw_cfg if isinstance(raw_cfg, dict) else {}
            category = _normalize_isolated_category_path(cfg.get('category'))
            if not category:
                continue

            updated_at = 0
            try:
                updated_at = int(cfg.get('updated_at') or 0)
            except (TypeError, ValueError):
                updated_at = 0

            normalized_items[path_key] = {
                'category': category,
                'updated_at': max(0, updated_at),
            }

        result[mode] = dict(sorted(normalized_items.items(), key=lambda item: item[0]))

    try:
        result['updated_at'] = max(0, int(source.get('updated_at') or 0))
    except (TypeError, ValueError):
        result['updated_at'] = 0

    return result


def _normalize_worldinfo_note_path(value):
    if value is None:
        return ''

    path = os.path.normcase(os.path.normpath(str(value).strip()))
    if not path or path == '.':
        return ''
    return path.replace('\\', '/')


def _normalize_worldinfo_note_card_id(value):
    if value is None:
        return ''

    card_id = str(value).replace('\\', '/').strip().strip('/')
    if not card_id:
        return ''
    return card_id


def build_worldinfo_note_key(source_type, file_path='', card_id=''):
    normalized_source = str(source_type or '').strip().lower()
    if normalized_source in ('global', 'resource'):
        path_key = _normalize_worldinfo_note_path(file_path)
        if not path_key:
            return ''
        return f'{normalized_source}::{path_key}'

    if normalized_source == 'embedded':
        normalized_card_id = _normalize_worldinfo_note_card_id(card_id)
        if not normalized_card_id:
            return ''
        return f'embedded::{normalized_card_id}'

    return ''


def _normalize_worldinfo_notes(raw):
    source = raw if isinstance(raw, dict) else {}
    normalized = {}

    for raw_key, raw_value in source.items():
        if not isinstance(raw_key, str):
            continue

        try:
            raw_source, raw_target = raw_key.split('::', 1)
        except ValueError:
            continue

        if raw_source in ('global', 'resource'):
            key = build_worldinfo_note_key(raw_source, file_path=raw_target)
        elif raw_source == 'embedded':
            key = build_worldinfo_note_key(raw_source, card_id=raw_target)
        else:
            key = ''

        if not key:
            continue

        note_info = raw_value if isinstance(raw_value, dict) else {}
        summary = note_info.get('summary', '')
        if not isinstance(summary, str):
            summary = str(summary or '')
        if not summary.strip():
            continue

        try:
            updated_at = max(0, int(note_info.get('updated_at') or 0))
        except (TypeError, ValueError):
            updated_at = 0

        normalized[key] = {
            'summary': summary,
            'updated_at': updated_at,
        }

    return dict(sorted(normalized.items(), key=lambda item: item[0]))


def _is_resource_item_categories_equal(left, right):
    left_norm = _normalize_resource_item_categories(left)
    right_norm = _normalize_resource_item_categories(right)
    return (
        left_norm.get('worldinfo') == right_norm.get('worldinfo')
        and left_norm.get('presets') == right_norm.get('presets')
    )


def _is_isolated_categories_equal(left, right):
    left_norm = _normalize_isolated_categories(left)
    right_norm = _normalize_isolated_categories(right)
    return left_norm.get('paths') == right_norm.get('paths')


def _normalize_tag_taxonomy(raw):
    """规范化标签分类配置结构。"""
    source = raw if isinstance(raw, dict) else {}

    default_category = _normalize_category_name(source.get('default_category')) or DEFAULT_TAG_CATEGORY

    categories = {}
    raw_categories = source.get('categories')
    if isinstance(raw_categories, dict):
        for raw_name, raw_cfg in raw_categories.items():
            category_name = _normalize_category_name(raw_name)
            if not category_name:
                continue

            color = DEFAULT_TAG_CATEGORY_COLOR
            opacity = DEFAULT_TAG_CATEGORY_OPACITY
            if isinstance(raw_cfg, dict):
                color = _normalize_hex_color(raw_cfg.get('color'), DEFAULT_TAG_CATEGORY_COLOR)
                opacity = _normalize_opacity(raw_cfg.get('opacity'), DEFAULT_TAG_CATEGORY_OPACITY)
            elif isinstance(raw_cfg, str):
                color = _normalize_hex_color(raw_cfg, DEFAULT_TAG_CATEGORY_COLOR)

            categories[category_name] = {
                'color': color,
                'opacity': opacity,
            }

    if default_category not in categories:
        categories[default_category] = {
            'color': DEFAULT_TAG_CATEGORY_COLOR,
            'opacity': DEFAULT_TAG_CATEGORY_OPACITY,
        }

    category_order = []
    seen_categories = set()
    raw_order = source.get('category_order')
    if isinstance(raw_order, list):
        for item in raw_order:
            category_name = _normalize_category_name(item)
            if not category_name or category_name in seen_categories:
                continue
            if category_name not in categories:
                continue
            seen_categories.add(category_name)
            category_order.append(category_name)

    if default_category not in seen_categories:
        category_order.insert(0, default_category)
        seen_categories.add(default_category)

    for category_name in sorted(categories.keys(), key=lambda x: x.lower()):
        if category_name in seen_categories:
            continue
        category_order.append(category_name)
        seen_categories.add(category_name)

    tag_to_category = {}
    raw_tag_to_category = source.get('tag_to_category')
    if isinstance(raw_tag_to_category, dict):
        for raw_tag, raw_category in raw_tag_to_category.items():
            tag = str(raw_tag).strip()
            if not tag:
                continue

            category_name = _normalize_category_name(raw_category)
            if category_name not in categories:
                category_name = default_category
            tag_to_category[tag] = category_name

    category_tag_order = {}
    raw_category_tag_order = source.get('category_tag_order')
    if isinstance(raw_category_tag_order, dict):
        for raw_category, raw_tags in raw_category_tag_order.items():
            category_name = _normalize_category_name(raw_category)
            if not isinstance(raw_tags, list):
                continue

            for raw_tag in raw_tags:
                tag = _normalize_tag_name(raw_tag)
                if not tag:
                    continue

                target_category = tag_to_category.get(tag)
                if target_category not in categories:
                    continue

                if target_category != category_name:
                    continue

                normalized_tags = category_tag_order.setdefault(target_category, [])
                if tag in normalized_tags:
                    continue
                normalized_tags.append(tag)

        category_tag_order = {
            category_name: ordered_tags
            for category_name, ordered_tags in category_tag_order.items()
            if category_name in categories and ordered_tags
        }

    updated_at = 0
    try:
        updated_at = int(source.get('updated_at') or 0)
    except (TypeError, ValueError):
        updated_at = 0

    if updated_at < 0:
        updated_at = 0

    return {
        'default_category': default_category,
        'category_order': category_order,
        'categories': categories,
        'tag_to_category': tag_to_category,
        'category_tag_order': category_tag_order,
        'updated_at': updated_at,
    }


def _is_tag_taxonomy_equal(left, right):
    """比较标签分类配置是否一致（忽略 updated_at）。"""
    left_norm = _normalize_tag_taxonomy(left)
    right_norm = _normalize_tag_taxonomy(right)

    return (
        left_norm.get('default_category') == right_norm.get('default_category')
        and left_norm.get('category_order') == right_norm.get('category_order')
        and left_norm.get('categories') == right_norm.get('categories')
        and left_norm.get('tag_to_category') == right_norm.get('tag_to_category')
        and left_norm.get('category_tag_order') == right_norm.get('category_tag_order')
    )


def _normalize_tag_management_prefs(raw):
    """规范化标签管理偏好配置。"""
    source = raw if isinstance(raw, dict) else {}

    raw_blacklist = source.get('tag_blacklist')
    tag_blacklist = []
    seen_tags = set()
    if isinstance(raw_blacklist, list):
        for raw_tag in raw_blacklist:
            if raw_tag is None:
                continue
            tag = str(raw_tag).strip()
            if not tag or tag in seen_tags:
                continue
            seen_tags.add(tag)
            tag_blacklist.append(tag)

    updated_at = 0
    try:
        updated_at = int(source.get('updated_at') or 0)
    except (TypeError, ValueError):
        updated_at = 0

    if updated_at < 0:
        updated_at = 0

    return {
        'lock_tag_library': bool(source.get('lock_tag_library')),
        'tag_blacklist': tag_blacklist,
        'updated_at': updated_at,
    }


def _is_tag_management_prefs_equal(left, right):
    left_norm = _normalize_tag_management_prefs(left)
    right_norm = _normalize_tag_management_prefs(right)
    return (
        left_norm.get('lock_tag_library') == right_norm.get('lock_tag_library')
        and left_norm.get('tag_blacklist') == right_norm.get('tag_blacklist')
    )


def _normalize_beautify_string(value):
    if value is None:
        return ''
    return str(value).strip()


def _normalize_beautify_path(value):
    path = _normalize_beautify_string(value).replace('\\', '/')
    return path.strip('/') if path else ''


def _normalize_shared_wallpaper_source_type(value):
    source_type = _normalize_beautify_string(value).lower()
    if source_type in ('builtin', 'imported', 'package_embedded'):
        return source_type
    return 'imported'


def _normalize_shared_wallpaper_item(raw_item, wallpaper_id):
    source = raw_item if isinstance(raw_item, dict) else {}

    def _to_int(value):
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    return {
        'id': wallpaper_id,
        'source_type': _normalize_shared_wallpaper_source_type(source.get('source_type')),
        'file': _normalize_beautify_path(source.get('file')),
        'filename': _normalize_beautify_string(source.get('filename')),
        'width': _to_int(source.get('width')),
        'height': _to_int(source.get('height')),
        'mtime': _to_int(source.get('mtime')),
        'created_at': _to_int(source.get('created_at')),
        'origin_package_id': _normalize_beautify_string(source.get('origin_package_id')),
        'origin_variant_id': _normalize_beautify_string(source.get('origin_variant_id')),
    }


def _normalize_shared_wallpaper_library(raw):
    source = raw if isinstance(raw, dict) else {}
    items = {}
    raw_items = source.get('items')
    if isinstance(raw_items, dict):
        for raw_wallpaper_id, raw_item in raw_items.items():
            wallpaper_id = _normalize_beautify_string(raw_wallpaper_id)
            if not wallpaper_id:
                continue
            items[wallpaper_id] = _normalize_shared_wallpaper_item(raw_item, wallpaper_id)

    manager_wallpaper_id = _normalize_beautify_string(source.get('manager_wallpaper_id'))
    if manager_wallpaper_id and not manager_wallpaper_id.startswith('builtin:') and manager_wallpaper_id not in items:
        manager_wallpaper_id = ''

    preview_wallpaper_id = _normalize_beautify_string(source.get('preview_wallpaper_id'))
    if preview_wallpaper_id and not preview_wallpaper_id.startswith('builtin:') and preview_wallpaper_id not in items:
        preview_wallpaper_id = ''

    try:
        updated_at = max(0, int(source.get('updated_at') or 0))
    except (TypeError, ValueError):
        updated_at = 0

    return {
        'items': dict(sorted(items.items(), key=lambda item: item[0])),
        'manager_wallpaper_id': manager_wallpaper_id,
        'preview_wallpaper_id': preview_wallpaper_id,
        'updated_at': updated_at,
    }


def _is_shared_wallpaper_library_equal(left, right):
    left_norm = _normalize_shared_wallpaper_library(left)
    right_norm = _normalize_shared_wallpaper_library(right)
    return (
        left_norm.get('items') == right_norm.get('items')
        and left_norm.get('manager_wallpaper_id') == right_norm.get('manager_wallpaper_id')
        and left_norm.get('preview_wallpaper_id') == right_norm.get('preview_wallpaper_id')
    )


def _normalize_beautify_platform(value):
    platform = _normalize_beautify_string(value).lower()
    if platform in ('pc', 'mobile', 'dual'):
        return platform
    return 'dual'


def _normalize_beautify_preview_hint(raw, platform='dual'):
    source = raw if isinstance(raw, dict) else {}
    accuracy = _normalize_beautify_string(source.get('preview_accuracy')).lower()
    if accuracy not in ('base', 'approx'):
        accuracy = 'approx' if platform in ('pc', 'mobile') else 'base'

    return {
        'needs_platform_review': bool(source.get('needs_platform_review')),
        'preview_accuracy': accuracy,
    }


def _normalize_beautify_wallpaper_ids(raw):
    if not isinstance(raw, list):
        return []

    result = []
    seen = set()
    for item in raw:
        wallpaper_id = _normalize_beautify_string(item)
        if not wallpaper_id or ':' not in wallpaper_id or wallpaper_id in seen:
            continue
        seen.add(wallpaper_id)
        result.append(wallpaper_id)
    return result


def _normalize_beautify_selected_wallpaper_id(raw):
    return _normalize_beautify_string(raw)


def _normalize_beautify_variant(raw_variant, variant_id):
    source = raw_variant if isinstance(raw_variant, dict) else {}
    platform = _normalize_beautify_platform(source.get('platform'))
    return {
        'id': variant_id,
        'name': _normalize_beautify_string(source.get('name')),
        'platform': platform,
        'theme_name': _normalize_beautify_string(source.get('theme_name')),
        'theme_file': _normalize_beautify_path(source.get('theme_file')),
        'wallpaper_ids': _normalize_beautify_wallpaper_ids(source.get('wallpaper_ids')),
        'selected_wallpaper_id': _normalize_beautify_selected_wallpaper_id(source.get('selected_wallpaper_id')),
        'preview_hint': _normalize_beautify_preview_hint(source.get('preview_hint'), platform),
    }


def _normalize_beautify_wallpaper(raw_wallpaper, wallpaper_id):
    source = raw_wallpaper if isinstance(raw_wallpaper, dict) else {}

    def _to_int(value):
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    return {
        'id': wallpaper_id,
        'variant_id': _normalize_beautify_string(source.get('variant_id')),
        'file': _normalize_beautify_path(source.get('file')),
        'filename': _normalize_beautify_string(source.get('filename')),
        'width': _to_int(source.get('width')),
        'height': _to_int(source.get('height')),
        'mtime': _to_int(source.get('mtime')),
    }


def _normalize_beautify_asset(raw_asset):
    source = raw_asset if isinstance(raw_asset, dict) else {}

    def _to_int(value):
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    return {
        'file': _normalize_beautify_path(source.get('file')),
        'filename': _normalize_beautify_string(source.get('filename')),
        'width': _to_int(source.get('width')),
        'height': _to_int(source.get('height')),
        'mtime': _to_int(source.get('mtime')),
    }


def _normalize_beautify_identity(raw_identity):
    source = raw_identity if isinstance(raw_identity, dict) else {}
    return {
        'name': _normalize_beautify_string(source.get('name')),
        'avatar_file': _normalize_beautify_path(source.get('avatar_file')),
    }


def _normalize_beautify_identities(raw):
    source = raw if isinstance(raw, dict) else {}
    return {
        'character': _normalize_beautify_identity(source.get('character')),
        'user': _normalize_beautify_identity(source.get('user')),
    }


def _normalize_beautify_screenshots(raw):
    if not isinstance(raw, dict):
        return {}

    screenshots = {}
    for raw_screenshot_id, raw_screenshot in raw.items():
        screenshot_id = _normalize_beautify_string(raw_screenshot_id)
        if not screenshot_id:
            continue

        screenshot = _normalize_beautify_asset(raw_screenshot)
        screenshots[screenshot_id] = {
            'id': screenshot_id,
            'file': screenshot['file'],
            'filename': screenshot['filename'],
            'width': screenshot['width'],
            'height': screenshot['height'],
            'mtime': screenshot['mtime'],
        }

    return dict(sorted(screenshots.items(), key=lambda item: item[0]))


def _normalize_beautify_global_settings(raw):
    source = raw if isinstance(raw, dict) else {}
    return {
        'wallpaper': _normalize_beautify_asset(source.get('wallpaper')),
        'identities': _normalize_beautify_identities(source.get('identities')),
    }


def _normalize_beautify_package(raw_package, package_id):
    source = raw_package if isinstance(raw_package, dict) else {}

    def _to_int(value):
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    variants = {}
    raw_variants = source.get('variants')
    if isinstance(raw_variants, dict):
        for raw_variant_id, raw_variant in raw_variants.items():
            variant_id = _normalize_beautify_string(raw_variant_id)
            if not variant_id:
                continue
            variants[variant_id] = _normalize_beautify_variant(raw_variant, variant_id)

    wallpapers = {}
    raw_wallpapers = source.get('wallpapers')
    if isinstance(raw_wallpapers, dict):
        for raw_wallpaper_id, raw_wallpaper in raw_wallpapers.items():
            wallpaper_id = _normalize_beautify_string(raw_wallpaper_id)
            if not wallpaper_id:
                continue
            wallpapers[wallpaper_id] = _normalize_beautify_wallpaper(raw_wallpaper, wallpaper_id)

    for variant in variants.values():
        variant['wallpaper_ids'] = [
            wallpaper_id
            for wallpaper_id in variant.get('wallpaper_ids', [])
            if (
                wallpaper_id.startswith('builtin:')
                or ':' in wallpaper_id
                or (wallpaper_id in wallpapers and wallpapers[wallpaper_id].get('variant_id') == variant['id'])
            )
        ]
        if variant.get('selected_wallpaper_id') not in variant['wallpaper_ids']:
            variant['selected_wallpaper_id'] = ''

    return {
        'id': package_id,
        'name': _normalize_beautify_string(source.get('name')),
        'author': _normalize_beautify_string(source.get('author')),
        'tags': [str(tag).strip() for tag in source.get('tags', []) if str(tag).strip()] if isinstance(source.get('tags'), list) else [],
        'notes': _normalize_beautify_string(source.get('notes')),
        'cover_variant_id': _normalize_beautify_string(source.get('cover_variant_id')),
        'created_at': _to_int(source.get('created_at')),
        'updated_at': _to_int(source.get('updated_at')),
        'screenshots': _normalize_beautify_screenshots(source.get('screenshots')),
        'identity_overrides': _normalize_beautify_identities(source.get('identity_overrides')),
        'variants': dict(sorted(variants.items(), key=lambda item: item[0])),
        'wallpapers': dict(sorted(wallpapers.items(), key=lambda item: item[0])),
    }


def _normalize_beautify_library(raw):
    source = raw if isinstance(raw, dict) else {}
    packages = {}
    raw_packages = source.get('packages')
    if isinstance(raw_packages, dict):
        for raw_package_id, raw_package in raw_packages.items():
            package_id = _normalize_beautify_string(raw_package_id)
            if not package_id:
                continue
            packages[package_id] = _normalize_beautify_package(raw_package, package_id)

    try:
        updated_at = max(0, int(source.get('updated_at') or 0))
    except (TypeError, ValueError):
        updated_at = 0

    return {
        'global_settings': _normalize_beautify_global_settings(source.get('global_settings')),
        'packages': dict(sorted(packages.items(), key=lambda item: item[0])),
        'updated_at': updated_at,
    }


def _is_beautify_library_equal(left, right):
    left_norm = _normalize_beautify_library(left)
    right_norm = _normalize_beautify_library(right)
    return (
        left_norm.get('global_settings') == right_norm.get('global_settings')
        and left_norm.get('packages') == right_norm.get('packages')
    )


def get_isolated_categories(ui_data):
    if not isinstance(ui_data, dict):
        return _normalize_isolated_categories({})
    return _normalize_isolated_categories(ui_data.get(ISOLATED_CATEGORIES_KEY))


def get_beautify_library(ui_data):
    if not isinstance(ui_data, dict):
        return _normalize_beautify_library({})
    return _normalize_beautify_library(ui_data.get(BEAUTIFY_LIBRARY_KEY))


def get_shared_wallpaper_library(ui_data):
    if not isinstance(ui_data, dict):
        return _normalize_shared_wallpaper_library({})
    return _normalize_shared_wallpaper_library(ui_data.get(SHARED_WALLPAPER_LIBRARY_KEY))


def set_beautify_library(ui_data, payload):
    if not isinstance(ui_data, dict):
        return False

    previous_raw = ui_data.get(BEAUTIFY_LIBRARY_KEY)
    previous_norm = _normalize_beautify_library(previous_raw)
    next_norm = _normalize_beautify_library(payload)

    if _is_beautify_library_equal(previous_norm, next_norm) and isinstance(previous_raw, dict):
        return False

    next_norm['updated_at'] = int(time.time())
    ui_data[BEAUTIFY_LIBRARY_KEY] = next_norm
    return True


def set_shared_wallpaper_library(ui_data, payload):
    if not isinstance(ui_data, dict):
        return False

    previous_raw = ui_data.get(SHARED_WALLPAPER_LIBRARY_KEY)
    previous_norm = _normalize_shared_wallpaper_library(previous_raw)
    next_norm = _normalize_shared_wallpaper_library(payload)

    if _is_shared_wallpaper_library_equal(previous_norm, next_norm) and isinstance(previous_raw, dict):
        return False

    next_norm['updated_at'] = int(time.time())
    ui_data[SHARED_WALLPAPER_LIBRARY_KEY] = next_norm
    return True


def get_resource_item_categories(ui_data):
    if not isinstance(ui_data, dict):
        return _normalize_resource_item_categories({})
    return _normalize_resource_item_categories(ui_data.get(RESOURCE_ITEM_CATEGORIES_KEY))


def get_worldinfo_notes(ui_data):
    if not isinstance(ui_data, dict):
        return _normalize_worldinfo_notes({})
    return _normalize_worldinfo_notes(ui_data.get(WORLDINFO_NOTES_KEY))


def get_worldinfo_note(ui_data, source_type, file_path='', card_id=''):
    note_key = build_worldinfo_note_key(source_type, file_path=file_path, card_id=card_id)
    if not note_key:
        return {}
    return get_worldinfo_notes(ui_data).get(note_key, {})


def set_worldinfo_note(ui_data, source_type, summary, file_path='', card_id=''):
    if not isinstance(ui_data, dict):
        return False

    note_key = build_worldinfo_note_key(source_type, file_path=file_path, card_id=card_id)
    if not note_key:
        return False

    normalized = get_worldinfo_notes(ui_data)
    summary_text = summary if isinstance(summary, str) else str(summary or '')

    if not summary_text.strip():
        if note_key not in normalized:
            return False
        del normalized[note_key]
        if normalized:
            ui_data[WORLDINFO_NOTES_KEY] = normalized
        else:
            ui_data.pop(WORLDINFO_NOTES_KEY, None)
        return True

    current_summary = normalized.get(note_key, {}).get('summary', '')
    if current_summary == summary_text:
        return False

    normalized[note_key] = {
        'summary': summary_text,
        'updated_at': int(time.time()),
    }
    ui_data[WORLDINFO_NOTES_KEY] = normalized
    return True


def delete_worldinfo_note(ui_data, source_type, file_path='', card_id=''):
    return set_worldinfo_note(ui_data, source_type, '', file_path=file_path, card_id=card_id)


def delete_worldinfo_notes_for_card_prefix(ui_data, card_prefix):
    if not isinstance(ui_data, dict):
        return False

    normalized_prefix = _normalize_worldinfo_note_card_id(card_prefix)
    if not normalized_prefix:
        return False

    notes = get_worldinfo_notes(ui_data)
    changed = False
    exact_key = build_worldinfo_note_key('embedded', card_id=normalized_prefix)
    nested_prefix = f'embedded::{normalized_prefix}/'

    for note_key in list(notes.keys()):
        if note_key == exact_key or note_key.startswith(nested_prefix):
            del notes[note_key]
            changed = True

    if not changed:
        return False

    if notes:
        ui_data[WORLDINFO_NOTES_KEY] = notes
    else:
        ui_data.pop(WORLDINFO_NOTES_KEY, None)
    return True


def rename_embedded_worldinfo_note_card_prefix(ui_data, old_card_prefix, new_card_prefix):
    if not isinstance(ui_data, dict):
        return False

    normalized_old = _normalize_worldinfo_note_card_id(old_card_prefix)
    normalized_new = _normalize_worldinfo_note_card_id(new_card_prefix)
    if not normalized_old or not normalized_new or normalized_old == normalized_new:
        return False

    raw_notes = ui_data.get(WORLDINFO_NOTES_KEY)
    if not isinstance(raw_notes, dict):
        return False

    changed = False
    remapped = {}
    exact_old_key = build_worldinfo_note_key('embedded', card_id=normalized_old)
    nested_old_prefix = f'embedded::{normalized_old}/'

    for note_key, note_value in raw_notes.items():
        if note_key == exact_old_key:
            remapped[build_worldinfo_note_key('embedded', card_id=normalized_new)] = note_value
            changed = True
            continue
        if note_key.startswith(nested_old_prefix):
            suffix = note_key[len(exact_old_key):]
            remapped[f'embedded::{normalized_new}{suffix}'] = note_value
            changed = True
            continue
        remapped[note_key] = note_value

    if not changed:
        return False

    ui_data[WORLDINFO_NOTES_KEY] = remapped
    return True


def rename_global_worldinfo_note_path_prefix(ui_data, old_path_prefix, new_path_prefix):
    if not isinstance(ui_data, dict):
        return False

    normalized_old = _normalize_worldinfo_note_path(old_path_prefix)
    normalized_new = _normalize_worldinfo_note_path(new_path_prefix)
    if not normalized_old or not normalized_new or normalized_old == normalized_new:
        return False

    raw_notes = ui_data.get(WORLDINFO_NOTES_KEY)
    if not isinstance(raw_notes, dict):
        return False

    changed = False
    remapped = {}
    exact_old_key = build_worldinfo_note_key('global', file_path=normalized_old)
    nested_old_prefix = f'global::{normalized_old}/'

    for note_key, note_value in raw_notes.items():
        if note_key == exact_old_key:
            remapped[build_worldinfo_note_key('global', file_path=normalized_new)] = note_value
            changed = True
            continue
        if note_key.startswith(nested_old_prefix):
            suffix = note_key[len(exact_old_key):]
            remapped[f'global::{normalized_new}{suffix}'] = note_value
            changed = True
            continue
        remapped[note_key] = note_value

    if not changed:
        return False

    ui_data[WORLDINFO_NOTES_KEY] = remapped
    return True


def set_resource_item_categories(ui_data, payload):
    if not isinstance(ui_data, dict):
        return False

    previous_raw = ui_data.get(RESOURCE_ITEM_CATEGORIES_KEY)
    previous_norm = _normalize_resource_item_categories(previous_raw)
    next_norm = _normalize_resource_item_categories(payload)

    if _is_resource_item_categories_equal(previous_norm, next_norm) and isinstance(previous_raw, dict):
        return False

    next_norm['updated_at'] = int(time.time())
    ui_data[RESOURCE_ITEM_CATEGORIES_KEY] = next_norm
    return True


def set_isolated_categories(ui_data, payload):
    if not isinstance(ui_data, dict):
        return False

    previous_raw = ui_data.get(ISOLATED_CATEGORIES_KEY)
    previous_norm = _normalize_isolated_categories(previous_raw)
    next_norm = _normalize_isolated_categories(payload)

    if _is_isolated_categories_equal(previous_norm, next_norm) and isinstance(previous_raw, dict):
        return False

    next_norm['updated_at'] = int(time.time())
    ui_data[ISOLATED_CATEGORIES_KEY] = next_norm
    return True


def get_tag_taxonomy(ui_data):
    """获取标签分类配置（自动回退默认值）。"""
    if not isinstance(ui_data, dict):
        return _normalize_tag_taxonomy({})
    return _normalize_tag_taxonomy(ui_data.get(TAG_TAXONOMY_KEY))


def set_tag_taxonomy(ui_data, taxonomy_payload):
    """保存标签分类配置。"""
    if not isinstance(ui_data, dict):
        return False

    previous_raw = ui_data.get(TAG_TAXONOMY_KEY)
    previous_norm = _normalize_tag_taxonomy(previous_raw)
    next_norm = _normalize_tag_taxonomy(taxonomy_payload)

    if _is_tag_taxonomy_equal(previous_norm, next_norm) and isinstance(previous_raw, dict):
        return False

    next_norm['updated_at'] = int(time.time())
    ui_data[TAG_TAXONOMY_KEY] = next_norm
    return True


def get_tag_management_prefs(ui_data):
    """获取标签管理偏好配置。"""
    if not isinstance(ui_data, dict):
        return _normalize_tag_management_prefs({})
    return _normalize_tag_management_prefs(ui_data.get(TAG_MANAGEMENT_PREFS_KEY))


def set_tag_management_prefs(ui_data, prefs_payload):
    """保存标签管理偏好配置。"""
    if not isinstance(ui_data, dict):
        return False

    previous_raw = ui_data.get(TAG_MANAGEMENT_PREFS_KEY)
    previous_norm = _normalize_tag_management_prefs(previous_raw)
    next_norm = _normalize_tag_management_prefs(prefs_payload)

    if _is_tag_management_prefs_equal(previous_norm, next_norm) and isinstance(previous_raw, dict):
        return False

    next_norm['updated_at'] = int(time.time())
    ui_data[TAG_MANAGEMENT_PREFS_KEY] = next_norm
    return True


def remove_tags_from_tag_taxonomy(ui_data, tags):
    """从标签分类映射中移除指定标签。"""
    if not isinstance(ui_data, dict):
        return False

    if not isinstance(tags, (list, tuple, set)):
        return False

    taxonomy = get_tag_taxonomy(ui_data)
    current_map = taxonomy.get('tag_to_category', {})
    if not isinstance(current_map, dict):
        current_map = {}

    next_map = dict(current_map)
    changed = False

    for raw_tag in tags:
        tag = str(raw_tag).strip()
        if not tag:
            continue
        if tag in next_map:
            del next_map[tag]
            changed = True

    if not changed:
        return False

    taxonomy['tag_to_category'] = next_map
    return set_tag_taxonomy(ui_data, taxonomy)


def get_import_time(ui_data, ui_key, fallback=None):
    """
    获取导入时间（秒级时间戳，浮点）。

    Args:
        ui_data: UI 数据字典
        ui_key: 卡片/Bundle 对应的 UI Key
        fallback: 兜底时间（通常传 last_modified）

    Returns:
        float: 导入时间；若不存在则回退 fallback；再无则返回 0
    """
    fallback_ts = _normalize_timestamp(fallback)

    if not isinstance(ui_data, dict):
        return fallback_ts if fallback_ts is not None else 0.0

    entry = ui_data.get(ui_key)
    if not isinstance(entry, dict):
        return fallback_ts if fallback_ts is not None else 0.0

    import_ts = _normalize_timestamp(entry.get(IMPORT_TIME_KEY))
    if import_ts is not None:
        return import_ts

    return fallback_ts if fallback_ts is not None else 0.0


def ensure_import_time(ui_data, ui_key, fallback=None):
    """
    确保指定 UI Key 拥有导入时间字段（只在缺失时写入）。

    Args:
        ui_data: UI 数据字典（会被原地修改）
        ui_key: 卡片/Bundle 对应的 UI Key
        fallback: 缺失时使用的时间戳（通常传导入完成时间）

    Returns:
        tuple[bool, float]: (是否发生修改, 最终导入时间)
    """
    fallback_ts = _normalize_timestamp(fallback)
    if fallback_ts is None:
        fallback_ts = time.time()

    if not isinstance(ui_data, dict) or not ui_key:
        return False, fallback_ts

    changed = False
    entry = ui_data.get(ui_key)
    if not isinstance(entry, dict):
        entry = {}
        ui_data[ui_key] = entry
        changed = True

    current_ts = _normalize_timestamp(entry.get(IMPORT_TIME_KEY))
    if current_ts is not None:
        return changed, current_ts

    entry[IMPORT_TIME_KEY] = fallback_ts
    changed = True
    return changed, fallback_ts


def get_last_sent_to_st(ui_data, ui_key):
    """获取上次发送到 ST 的时间戳；不存在则返回 0。"""
    if not isinstance(ui_data, dict):
        return 0.0

    entry = ui_data.get(ui_key)
    if not isinstance(entry, dict):
        return 0.0

    sent_ts = _normalize_timestamp(entry.get(LAST_SENT_TO_ST_KEY))
    return sent_ts if sent_ts is not None else 0.0


def set_last_sent_to_st(ui_data, ui_key, timestamp=None):
    """设置上次发送到 ST 的时间戳。"""
    sent_ts = _normalize_timestamp(timestamp)
    if sent_ts is None:
        sent_ts = time.time()

    if not isinstance(ui_data, dict) or not ui_key:
        return False, sent_ts

    changed = False
    entry = ui_data.get(ui_key)
    if not isinstance(entry, dict):
        entry = {}
        ui_data[ui_key] = entry
        changed = True

    current_ts = _normalize_timestamp(entry.get(LAST_SENT_TO_ST_KEY))
    if current_ts != sent_ts:
        entry[LAST_SENT_TO_ST_KEY] = sent_ts
        changed = True

    return changed, sent_ts


def _backup_ui_data_file_path():
    return f'{UI_DATA_FILE}.bak'


def _corrupted_ui_data_file_path():
    timestamp = time.strftime('%Y%m%d%H%M%S')
    return f'{UI_DATA_FILE}.corrupted.{timestamp}.{os.getpid()}'


def _read_json_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _copy_current_primary_to_backup_if_valid():
    if not os.path.exists(UI_DATA_FILE):
        return

    try:
        _read_json_file(UI_DATA_FILE)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"当前 ui_data.json 无法作为备份源，跳过预写备份: {exc}")
        return

    shutil.copy2(UI_DATA_FILE, _backup_ui_data_file_path())


def _copy_primary_to_backup():
    if os.path.exists(UI_DATA_FILE):
        shutil.copy2(UI_DATA_FILE, _backup_ui_data_file_path())


def _snapshot_corrupted_ui_data():
    if not os.path.exists(UI_DATA_FILE):
        return ''

    corrupted_path = _corrupted_ui_data_file_path()
    shutil.copy2(UI_DATA_FILE, corrupted_path)
    return corrupted_path


def _write_ui_data_file_atomic(data):
    parent_dir = os.path.dirname(UI_DATA_FILE)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    fd = None
    temp_path = ''
    try:
        fd, temp_path = tempfile.mkstemp(
            prefix=f'.{os.path.basename(UI_DATA_FILE)}.',
            suffix='.tmp',
            dir=parent_dir or None,
        )
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            fd = None
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, UI_DATA_FILE)
        temp_path = ''
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                logger.warning(f"清理 ui_data.json 临时文件失败: {temp_path}", exc_info=True)


def _load_backup_ui_data():
    backup_path = _backup_ui_data_file_path()
    if not os.path.exists(backup_path):
        return None

    try:
        data = _read_json_file(backup_path)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error(f"加载 ui_data.json 备份失败: {exc}")
        return None

    if not isinstance(data, dict):
        logger.error("ui_data.json 备份内容不是对象，无法恢复。")
        return None

    return data


def _recover_corrupted_ui_data(error):
    logger.error(f"ui_data.json 损坏: {error}")

    try:
        corrupted_path = _snapshot_corrupted_ui_data()
        if corrupted_path:
            logger.error(f"已备份损坏的 ui_data.json: {corrupted_path}")
    except Exception as snapshot_error:
        logger.error(f"备份损坏的 ui_data.json 失败: {snapshot_error}")

    backup_data = _load_backup_ui_data()
    if backup_data is None:
        return {}

    if save_ui_data(backup_data):
        logger.warning("已从 ui_data.json.bak 恢复 ui_data.json。")
    else:
        logger.error("从 ui_data.json.bak 恢复 ui_data.json 失败，已返回备份数据。")

    return backup_data


def load_ui_data():
    """
    加载 UI 辅助数据 (JSON 格式)。
    包含用户的卡片备注、来源链接、资源文件夹映射等信息。

    Returns:
        dict: UI 数据字典。如果文件不存在或解析失败，返回空字典。
    """
    with _UI_DATA_LOCK:
        if os.path.exists(UI_DATA_FILE):
            try:
                data = _read_json_file(UI_DATA_FILE)
            except json.JSONDecodeError as e:
                return _recover_corrupted_ui_data(e)
            except Exception as e:
                logger.error(f"加载 ui_data.json 失败: {e}")
                return {}

            if not isinstance(data, dict):
                logger.error("加载 ui_data.json 失败: 根数据不是对象")
                return {}

            # === 脏数据清理逻辑 ===
            # 检查 resource_folder 是否使用了系统保留名称 (如 'cards', 'thumbnails' 等)
            dirty = False
            for key, info in data.items():
                if not isinstance(info, dict):
                    continue

                rf = info.get('resource_folder', '')
                if rf:
                    # 兼容 Windows/Linux 分隔符，取第一层目录名检查
                    first_part = rf.replace('\\', '/').split('/')[0].lower()
                    if first_part in RESERVED_RESOURCE_NAMES:
                        logger.warning(f"检测到非法资源目录配置 '{rf}' (属于保留目录)，已自动移除关联。")
                        info['resource_folder'] = ""
                        dirty = True

                # 规范化 import_time，兼容历史字符串/非法值
                if IMPORT_TIME_KEY in info:
                    normalized_ts = _normalize_timestamp(info.get(IMPORT_TIME_KEY))
                    if normalized_ts is None:
                        del info[IMPORT_TIME_KEY]
                        dirty = True
                    elif info.get(IMPORT_TIME_KEY) != normalized_ts:
                        info[IMPORT_TIME_KEY] = normalized_ts
                        dirty = True

                if LAST_SENT_TO_ST_KEY in info:
                    normalized_sent_ts = _normalize_timestamp(info.get(LAST_SENT_TO_ST_KEY))
                    if normalized_sent_ts is None:
                        del info[LAST_SENT_TO_ST_KEY]
                        dirty = True
                    elif info.get(LAST_SENT_TO_ST_KEY) != normalized_sent_ts:
                        info[LAST_SENT_TO_ST_KEY] = normalized_sent_ts
                        dirty = True

            if dirty:
                # 如果有清理操作，立即回写文件以修正
                save_ui_data(data)

            return data
        return {}


def save_ui_data(data):
    """
    保存 UI 辅助数据到 JSON 文件。
    
    Args:
        data (dict): 要保存的数据字典。
    """
    with _UI_DATA_LOCK:
        try:
            parent_dir = os.path.dirname(UI_DATA_FILE)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            _copy_current_primary_to_backup_if_valid()
            _write_ui_data_file_atomic(data)
            _copy_primary_to_backup()
            return True
        except Exception as e:
            logger.error(f"保存 ui_data.json 失败: {e}")
            return False


def get_version_remark(ui_data, ui_key, version_id, cover_id=None):
    """
    获取指定版本的备注信息（仅 summary 是版本独立的）。
    link 和 resource_folder 从 bundle 全局获取。
    
    向后兼容：如果没有 _version_remarks 且根上有 summary，
    当请求的 version_id 是封面（cover_id）时，返回根上的 summary。

    Args:
        ui_data: UI 数据字典
        ui_key: UI 键 (卡片 ID 或 bundle_dir)
        version_id: 版本 ID
        cover_id: 封面版本 ID（可选），用于向后兼容旧格式

    Returns:
        dict: 包含 summary, link, resource_folder 的字典，如果不存在返回空字典
    """
    if ui_key not in ui_data:
        return {}

    entry = ui_data[ui_key]
    result = {}

    # 1. 从版本级别获取 summary（版本独立）
    has_version_remark = False
    if VERSION_REMARKS_KEY in entry and version_id in entry[VERSION_REMARKS_KEY]:
        version_data = entry[VERSION_REMARKS_KEY][version_id]
        result['summary'] = version_data.get('summary', '')
        has_version_remark = True
    
    # 向后兼容：如果没有版本级别的备注，且这是封面版本，使用根上的 summary
    if not has_version_remark and cover_id and version_id == cover_id:
        if 'summary' in entry:
            result['summary'] = entry['summary']

    # 2. 从 bundle 全局获取 link 和 resource_folder（共享）
    result['link'] = entry.get('link', '')
    result['resource_folder'] = entry.get('resource_folder', '')

    return result

def set_version_remark(ui_data, ui_key, version_id, remark_data, cover_id=None):
    """
    设置指定版本的备注信息（仅 summary 是版本独立的）。
    link 和 resource_folder 存储在 bundle 全局级别。
    
    向后兼容：如果根上有 summary 且这是封面版本，自动迁移到 _version_remarks。

    Args:
        ui_data: UI 数据字典 (会被直接修改)
        ui_key: UI 键 (卡片 ID 或 bundle_dir)
        version_id: 版本 ID
        remark_data: 包含 summary, link, resource_folder 的字典
        cover_id: 封面版本 ID（可选），用于向后兼容旧格式

    Returns:
        bool: 是否需要保存
    """
    if ui_key not in ui_data:
        ui_data[ui_key] = {}

    entry = ui_data[ui_key]
    changed = False

    # 向后兼容：如果根上有 summary 且这是封面版本，自动迁移
    if 'summary' in entry and cover_id and version_id == cover_id:
        if VERSION_REMARKS_KEY not in entry:
            entry[VERSION_REMARKS_KEY] = {}
        # 只有当封面版本还没有备注时，才迁移根上的 summary
        if cover_id not in entry[VERSION_REMARKS_KEY]:
            entry[VERSION_REMARKS_KEY][cover_id] = {'summary': entry['summary']}
            changed = True
        # 删除根上的 summary（已迁移到新格式）
        del entry['summary']

    # 1. 处理版本级别的 summary
    if VERSION_REMARKS_KEY not in entry:
        entry[VERSION_REMARKS_KEY] = {}

    old_remark = entry[VERSION_REMARKS_KEY].get(version_id, {})
    new_summary = remark_data.get('summary', '')

    if old_remark.get('summary', '') != new_summary:
        entry[VERSION_REMARKS_KEY][version_id] = {'summary': new_summary}
        changed = True

    # 2. 处理 bundle 全局的 link 和 resource_folder
    new_link = remark_data.get('link', '')
    new_resource_folder = remark_data.get('resource_folder', '')

    if entry.get('link', '') != new_link:
        entry['link'] = new_link
        changed = True

    if entry.get('resource_folder', '') != new_resource_folder:
        entry['resource_folder'] = new_resource_folder
        changed = True

    return changed

def migrate_version_remark_to_standalone(ui_data, bundle_dir, version_id):
    """
    将 bundle 下的版本备注迁移为独立卡片的备注。
    用于取消聚合或删除 bundle 时。
    注意：summary 从版本级别获取，link 和 resource_folder 从 bundle 全局获取。

    Args:
        ui_data: UI 数据字典
        bundle_dir: bundle 目录路径
        version_id: 版本 ID (即独立后的卡片 ID)

    Returns:
        bool: 是否有数据迁移
    """
    if bundle_dir not in ui_data:
        return False

    entry = ui_data[bundle_dir]
    migrated_data = {}
    has_data = False

    # 1. 从版本级别获取 summary
    if VERSION_REMARKS_KEY in entry and version_id in entry[VERSION_REMARKS_KEY]:
        version_data = entry[VERSION_REMARKS_KEY][version_id]
        if version_data.get('summary'):
            migrated_data['summary'] = version_data['summary']
            has_data = True

    # 2. 从 bundle 全局获取 link 和 resource_folder
    if entry.get('link'):
        migrated_data['link'] = entry['link']
        has_data = True

    if entry.get('resource_folder'):
        migrated_data['resource_folder'] = entry['resource_folder']
        has_data = True

    # 3. 复制导入时间（如果有）
    import_ts = _normalize_timestamp(entry.get(IMPORT_TIME_KEY))
    if import_ts is not None:
        migrated_data[IMPORT_TIME_KEY] = import_ts
        has_data = True

    if has_data:
        ui_data[version_id] = migrated_data
        return True

    return False

def delete_version_remark(ui_data, bundle_dir, version_id):
    """
    删除 bundle 下指定版本的备注。
    用于删除版本时清理数据。

    Args:
        ui_data: UI 数据字典
        bundle_dir: bundle 目录路径
        version_id: 版本 ID

    Returns:
        bool: 是否有数据被删除
    """
    if bundle_dir not in ui_data:
        return False

    entry = ui_data[bundle_dir]

    if VERSION_REMARKS_KEY not in entry:
        return False

    if version_id not in entry[VERSION_REMARKS_KEY]:
        return False

    del entry[VERSION_REMARKS_KEY][version_id]

    if not entry[VERSION_REMARKS_KEY]:
        del entry[VERSION_REMARKS_KEY]

    return True

def cleanup_stale_version_remarks(ui_data, bundle_dir, valid_version_ids):
    """
    清理 bundle 下已失效版本的备注。
    用于扫描后发现某些版本已被删除时。

    Args:
        ui_data: UI 数据字典
        bundle_dir: bundle 目录路径
        valid_version_ids: 当前有效的版本 ID 列表

    Returns:
        int: 清理的备注数量
    """
    if bundle_dir not in ui_data:
        return 0

    entry = ui_data[bundle_dir]

    if VERSION_REMARKS_KEY not in entry:
        return 0

    removed_count = 0
    versions_to_remove = []

    for version_id in entry[VERSION_REMARKS_KEY]:
        if version_id not in valid_version_ids:
            versions_to_remove.append(version_id)

    for version_id in versions_to_remove:
        del entry[VERSION_REMARKS_KEY][version_id]
        removed_count += 1

    if not entry[VERSION_REMARKS_KEY]:
        del entry[VERSION_REMARKS_KEY]

    return removed_count

def migrate_bundle_remarks_to_versions(ui_data, bundle_dir, version_ids=None):
    """
    将 bundle 的版本备注迁移为独立卡片的备注。
    用于 bundle 取消聚合时。
    注意：summary 从版本级别获取，link 和 resource_folder 从 bundle 全局复制到每个版本。

    Args:
        ui_data: UI 数据字典
        bundle_dir: bundle 目录路径
        version_ids: 可选，指定要迁移的版本 ID 列表，如果为 None 则迁移所有有备注的版本

    Returns:
        int: 迁移的备注数量
    """
    if bundle_dir not in ui_data:
        return 0

    entry = ui_data[bundle_dir]
    migrated_count = 0

    # 获取 bundle 全局的 link 和 resource_folder
    global_link = entry.get('link', '')
    global_resource_folder = entry.get('resource_folder', '')
    global_import_time = _normalize_timestamp(entry.get(IMPORT_TIME_KEY))

    # 确定要处理的版本列表
    versions_to_process = []
    if version_ids is not None:
        versions_to_process = version_ids
    elif VERSION_REMARKS_KEY in entry:
        versions_to_process = list(entry[VERSION_REMARKS_KEY].keys())

    for version_id in versions_to_process:
        migrated_data = {}
        has_data = False

        # 1. 从版本级别获取 summary
        if VERSION_REMARKS_KEY in entry and version_id in entry[VERSION_REMARKS_KEY]:
            version_data = entry[VERSION_REMARKS_KEY][version_id]
            if version_data.get('summary'):
                migrated_data['summary'] = version_data['summary']
                has_data = True

        # 2. 复制 bundle 全局的 link 和 resource_folder 到每个版本
        if global_link:
            migrated_data['link'] = global_link
            has_data = True

        if global_resource_folder:
            migrated_data['resource_folder'] = global_resource_folder
            has_data = True

        if global_import_time is not None:
            migrated_data[IMPORT_TIME_KEY] = global_import_time
            has_data = True

        if has_data:
            ui_data[version_id] = migrated_data
            migrated_count += 1

    return migrated_count
