"""Maintenance operations for generated and persisted manager data."""

import hashlib
import os

from core.consts import SIDECAR_EXTENSIONS


def _cache_name(source_name):
    normalized_name = str(source_name).replace('\\', '/')
    return hashlib.md5(normalized_name.encode('utf-8')).hexdigest() + '.webp'


def _sidecar_path(json_path):
    base_path = os.path.splitext(json_path)[0]
    for extension in SIDECAR_EXTENSIONS:
        candidate = base_path + extension
        if os.path.isfile(candidate):
            return candidate
    return None


def _valid_thumbnail_cache_names(cards_folder):
    cards_root = os.path.abspath(os.fspath(cards_folder))
    if not os.path.isdir(cards_root):
        raise FileNotFoundError(f'角色卡目录不存在: {cards_root}')

    valid_names = set()
    for current_root, _directory_names, file_names in os.walk(
        cards_root, followlinks=False
    ):
        for file_name in file_names:
            extension = os.path.splitext(file_name)[1].lower()
            if extension == '.json':
                source_path = os.path.join(current_root, file_name)
                sidecar_path = _sidecar_path(source_path)
                if not sidecar_path:
                    continue
                sidecar_rel_path = os.path.relpath(sidecar_path, cards_root).replace('\\', '/')
                valid_names.add(_cache_name(os.path.basename(sidecar_path)))
                valid_names.add(_cache_name(sidecar_rel_path))
            elif extension in SIDECAR_EXTENSIONS:
                rel_path = os.path.relpath(
                    os.path.join(current_root, file_name), cards_root
                ).replace('\\', '/')
                valid_names.add(_cache_name(rel_path))
                # Keep compatibility with caches created before nested paths were normalized.
                valid_names.add(_cache_name(file_name))
    return valid_names


def clean_orphaned_thumbnail_cache(cards_folder, thumb_folder):
    """Remove WebP thumbnails whose source image is no longer on disk."""
    valid_names = _valid_thumbnail_cache_names(cards_folder)
    thumbnail_root = os.path.abspath(os.fspath(thumb_folder))
    if not os.path.isdir(thumbnail_root):
        return {'scanned': 0, 'kept': 0, 'removed': 0, 'errors': []}

    scanned = 0
    kept = 0
    removed = 0
    errors = []
    for entry in os.scandir(thumbnail_root):
        if (
            not entry.name.lower().endswith('.webp')
            or not entry.is_file(follow_symlinks=False)
        ):
            continue
        scanned += 1
        if entry.name in valid_names:
            kept += 1
            continue
        try:
            os.unlink(entry.path)
            removed += 1
        except OSError as exc:
            errors.append(f'{entry.name}: {exc}')

    return {
        'scanned': scanned,
        'kept': kept,
        'removed': removed,
        'errors': errors,
    }
