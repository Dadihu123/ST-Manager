import hashlib
import logging
import os
import shutil
import time

from PIL import Image, UnidentifiedImageError

from core.config import BASE_DIR, INTERNAL_DIR
from core.data.ui_store import (
    get_shared_wallpaper_library,
    load_ui_data,
    save_ui_data,
    set_shared_wallpaper_library,
)


logger = logging.getLogger(__name__)


class SharedWallpaperService:
    def __init__(self, project_root=None, ui_data_loader=None, ui_data_saver=None, internal_root=None):
        # 用户数据根（data/ 下）→ BASE_DIR；随包只读资源 → INTERNAL_DIR。
        self.project_root = os.path.abspath(project_root or BASE_DIR)
        # 内置壁纸是随包资源，打包态必须从 INTERNAL_DIR 读：frozen 下 BASE_DIR 是
        # exe/.app 所在目录，其中并没有 static/，用 BASE_DIR 会静默读到空目录。
        self.internal_root = os.path.abspath(internal_root or INTERNAL_DIR)
        self.ui_data_loader = ui_data_loader or load_ui_data
        self.ui_data_saver = ui_data_saver or save_ui_data

    def load_library(self):
        ui_data = self.ui_data_loader()
        persisted = get_shared_wallpaper_library(ui_data)
        raw_persisted = ui_data.get('_shared_wallpaper_library_v1') if isinstance(ui_data, dict) else {}
        items = dict(persisted.get('items') or {})
        items.update(self._load_package_embedded_items())
        builtin_items = self._load_builtin_items()
        items.update(builtin_items)

        manager_wallpaper_id = self._normalize_selection_id(
            raw_persisted.get('manager_wallpaper_id') if isinstance(raw_persisted, dict) else ''
        ) or persisted.get('manager_wallpaper_id', '')
        if manager_wallpaper_id not in items:
            manager_wallpaper_id = ''

        preview_wallpaper_id = self._normalize_selection_id(
            raw_persisted.get('preview_wallpaper_id') if isinstance(raw_persisted, dict) else ''
        ) or persisted.get('preview_wallpaper_id', '')
        if preview_wallpaper_id not in items:
            preview_wallpaper_id = ''

        return {
            'items': dict(sorted(items.items(), key=lambda item: item[0])),
            'manager_wallpaper_id': manager_wallpaper_id,
            'preview_wallpaper_id': preview_wallpaper_id,
            'updated_at': persisted.get('updated_at', 0),
        }

    def import_wallpaper(
        self,
        source_path,
        selection_target='',
        source_name=None,
        package_id='',
        variant_id='',
    ):
        source_type = 'package_embedded' if package_id or variant_id else 'imported'
        target_dir = self._target_dir_for_source(source_type, package_id=package_id, variant_id=variant_id)
        os.makedirs(target_dir, exist_ok=True)

        filename = self._build_filename(source_path, source_name=source_name)
        target_path = self._resolve_unique_target_path(target_dir, filename)
        shutil.copy2(source_path, target_path)

        item = self._build_item(
            target_path,
            source_type=source_type,
            wallpaper_id=self._wallpaper_id_for_path(target_path, prefix=source_type),
            package_id=package_id,
            variant_id=variant_id,
            created_at=int(time.time()),
        )
        if not item:
            self._safe_remove_file(target_path)
            return {}
        self._upsert_item(item, selection_target=selection_target)
        return item

    def ensure_package_embedded_wallpaper(self, source_path, package_id, variant_id, source_name=None):
        if not source_path or not os.path.isfile(source_path):
            return {}

        resolved_package_id = str(package_id or '').strip()
        resolved_variant_id = str(variant_id or '').strip()
        if not resolved_package_id or not resolved_variant_id:
            return {}

        library = self.load_library()
        for item in (library.get('items') or {}).values():
            if item.get('source_type') != 'package_embedded':
                continue
            if str(item.get('origin_package_id') or '').strip() != resolved_package_id:
                continue
            if str(item.get('origin_variant_id') or '').strip() != resolved_variant_id:
                continue

            existing_path = os.path.join(
                self.project_root,
                str(item.get('file') or '').replace('/', os.sep),
            )
            if self._files_match(existing_path, source_path):
                return item

        return self.import_wallpaper(
            source_path,
            source_name=source_name,
            package_id=resolved_package_id,
            variant_id=resolved_variant_id,
        )

    def select_wallpaper(self, wallpaper_id, selection_target):
        selection_target = str(selection_target or '').strip()
        if selection_target not in ('manager', 'preview'):
            raise ValueError('无效的 selection_target')

        wallpaper_id = self._normalize_selection_id(wallpaper_id)
        library = self.load_library()
        items = dict(library.get('items') or {})
        if wallpaper_id not in items:
            raise ValueError('壁纸不存在')

        ui_data = self.ui_data_loader()
        payload = get_shared_wallpaper_library(ui_data)
        raw_persisted = ui_data.get('_shared_wallpaper_library_v1') if isinstance(ui_data, dict) else {}
        next_payload = {
            'items': dict(payload.get('items') or {}),
            'manager_wallpaper_id': self._normalize_selection_id(
                raw_persisted.get('manager_wallpaper_id') if isinstance(raw_persisted, dict) else ''
            ) or payload.get('manager_wallpaper_id', ''),
            'preview_wallpaper_id': self._normalize_selection_id(
                raw_persisted.get('preview_wallpaper_id') if isinstance(raw_persisted, dict) else ''
            ) or payload.get('preview_wallpaper_id', ''),
        }
        next_payload[f'{selection_target}_wallpaper_id'] = wallpaper_id

        changed = set_shared_wallpaper_library(ui_data, next_payload)
        stored_payload = ui_data.get('_shared_wallpaper_library_v1') if isinstance(ui_data, dict) else None
        if isinstance(stored_payload, dict):
            if (
                next_payload['manager_wallpaper_id'].startswith('builtin:')
                and next_payload['manager_wallpaper_id'] in items
            ):
                stored_payload['manager_wallpaper_id'] = next_payload['manager_wallpaper_id']
            if (
                next_payload['preview_wallpaper_id'].startswith('builtin:')
                and next_payload['preview_wallpaper_id'] in items
            ):
                stored_payload['preview_wallpaper_id'] = next_payload['preview_wallpaper_id']
        if changed:
            self.ui_data_saver(ui_data)

        return {
            'selected': True,
            'selection_target': selection_target,
            'wallpaper_id': wallpaper_id,
            'wallpaper': items[wallpaper_id],
        }

    def migrate_legacy_backgrounds(self, ui_data=None):
        payload = ui_data if isinstance(ui_data, dict) else self.ui_data_loader()
        bg_url = str(payload.get('bg_url') or '').strip()
        if not bg_url and isinstance(payload.get('settings'), dict):
            bg_url = str(payload['settings'].get('bg_url') or '').strip()
        prefix = '/assets/backgrounds/'
        if not bg_url.startswith(prefix):
            return self.load_library()

        filename = bg_url[len(prefix):].strip().replace('\\', '/')
        if not filename or '/' in filename:
            return self.load_library()

        legacy_path = os.path.join(self.project_root, 'data', 'assets', 'backgrounds', filename)
        if not os.path.isfile(legacy_path):
            return self.load_library()

        library = self.load_library()
        manager_wallpaper_id = library.get('manager_wallpaper_id', '')
        manager_item = (library.get('items') or {}).get(manager_wallpaper_id) or {}
        if manager_item:
            return library

        if manager_item.get('source_type') == 'imported':
            manager_file = os.path.join(self.project_root, str(manager_item.get('file') or '').replace('/', os.sep))
            if self._files_match(manager_file, legacy_path):
                return library

        self.import_wallpaper(
            legacy_path,
            selection_target='manager',
            source_name=filename,
        )
        return self.load_library()

    def _load_builtin_items(self):
        # 内置壁纸随包分发，走 internal_root（frozen 下 = sys._MEIPASS），
        # 不能用 project_root（frozen 下是 exe 同级，没有 static/）。
        builtin_root = os.path.join(self.internal_root, 'static', 'assets', 'wallpapers', 'builtin')
        if not os.path.isdir(builtin_root):
            return {}

        items = {}
        for current_root, _, filenames in os.walk(builtin_root):
            for filename in sorted(filenames):
                path = os.path.join(current_root, filename)
                rel_path = os.path.relpath(path, builtin_root).replace('\\', '/')
                wallpaper_id = f'builtin:{rel_path}'
                item = self._build_item(path, source_type='builtin', wallpaper_id=wallpaper_id)
                if item:
                    items[wallpaper_id] = item
        return items

    def _load_package_embedded_items(self):
        embedded_root = os.path.join(self.project_root, 'data', 'library', 'wallpapers', 'package_embedded')
        if not os.path.isdir(embedded_root):
            return {}

        items = {}
        for current_root, _, filenames in os.walk(embedded_root):
            for filename in sorted(filenames):
                path = os.path.join(current_root, filename)
                rel_dir = os.path.relpath(current_root, embedded_root).replace('\\', '/')
                path_parts = [part for part in rel_dir.split('/') if part and part != '.']
                if len(path_parts) < 2:
                    continue
                package_id, variant_id = path_parts[0], path_parts[1]
                wallpaper_id = self._wallpaper_id_for_path(path, prefix='package_embedded')
                item = self._build_item(
                    path,
                    source_type='package_embedded',
                    wallpaper_id=wallpaper_id,
                    package_id=package_id,
                    variant_id=variant_id,
                )
                if item:
                    items[wallpaper_id] = item
        return items

    def _upsert_item(self, item, selection_target=''):
        if not item:
            return False
        ui_data = self.ui_data_loader()
        payload = get_shared_wallpaper_library(ui_data)
        raw_persisted = ui_data.get('_shared_wallpaper_library_v1') if isinstance(ui_data, dict) else {}
        items = dict(payload.get('items') or {})
        items[item['id']] = item

        merged_items = dict(items)
        merged_items.update(self._load_builtin_items())

        manager_wallpaper_id = self._normalize_selection_id(
            raw_persisted.get('manager_wallpaper_id') if isinstance(raw_persisted, dict) else ''
        ) or payload.get('manager_wallpaper_id', '')
        if manager_wallpaper_id not in merged_items:
            manager_wallpaper_id = ''

        preview_wallpaper_id = self._normalize_selection_id(
            raw_persisted.get('preview_wallpaper_id') if isinstance(raw_persisted, dict) else ''
        ) or payload.get('preview_wallpaper_id', '')
        if preview_wallpaper_id not in merged_items:
            preview_wallpaper_id = ''

        next_payload = {
            'items': items,
            'manager_wallpaper_id': manager_wallpaper_id,
            'preview_wallpaper_id': preview_wallpaper_id,
        }
        if selection_target == 'manager':
            next_payload['manager_wallpaper_id'] = item['id']
        elif selection_target == 'preview':
            next_payload['preview_wallpaper_id'] = item['id']

        changed = set_shared_wallpaper_library(ui_data, next_payload)
        stored_payload = ui_data.get('_shared_wallpaper_library_v1') if isinstance(ui_data, dict) else None
        if isinstance(stored_payload, dict):
            if (
                selection_target != 'manager'
                and manager_wallpaper_id.startswith('builtin:')
                and manager_wallpaper_id in merged_items
            ):
                stored_payload['manager_wallpaper_id'] = manager_wallpaper_id
            if (
                selection_target != 'preview'
                and preview_wallpaper_id.startswith('builtin:')
                and preview_wallpaper_id in merged_items
            ):
                stored_payload['preview_wallpaper_id'] = preview_wallpaper_id
        if changed:
            self.ui_data_saver(ui_data)
        return changed

    def _build_item(self, path, source_type, wallpaper_id, package_id='', variant_id='', created_at=None):
        metadata = self._read_image_metadata(path, created_at=created_at)
        if not metadata:
            return {}
        return {
            'id': wallpaper_id,
            'source_type': source_type,
            'file': (os.path.relpath(path, self.internal_root).replace('\\', '/')
                     if source_type == 'builtin' else self._relative_path(path)),
            'filename': os.path.basename(path),
            'width': metadata['width'],
            'height': metadata['height'],
            'mtime': metadata['mtime'],
            'created_at': metadata['created_at'],
            'origin_package_id': str(package_id or '').strip(),
            'origin_variant_id': str(variant_id or '').strip(),
        }

    def _read_image_metadata(self, path, created_at=None):
        if not path or not os.path.isfile(path):
            return {}
        try:
            with Image.open(path) as image:
                width, height = image.size
        except (UnidentifiedImageError, OSError, ValueError):
            logger.warning('Skipping invalid wallpaper asset: %s', path, exc_info=True)
            return {}

        mtime = self._safe_timestamp(path)
        return {
            'width': width,
            'height': height,
            'mtime': mtime,
            'created_at': max(0, int(created_at if created_at is not None else mtime)),
        }

    def _safe_timestamp(self, path):
        try:
            return max(0, int(os.path.getmtime(path)))
        except OSError:
            return 0

    def _relative_path(self, path):
        return os.path.relpath(path, self.project_root).replace('\\', '/')

    def _target_dir_for_source(self, source_type, package_id='', variant_id=''):
        if source_type == 'package_embedded':
            return os.path.join(
                self.project_root,
                'data',
                'library',
                'wallpapers',
                'package_embedded',
                self._safe_path_component(package_id),
                self._safe_path_component(variant_id),
            )
        return os.path.join(self.project_root, 'data', 'library', 'wallpapers', 'imported')

    def _build_filename(self, source_path, source_name=None):
        candidate = str(source_name or os.path.basename(source_path) or 'wallpaper').strip()
        stem, ext = os.path.splitext(candidate)
        safe_stem = self._safe_filename(stem or 'wallpaper')
        safe_ext = ''.join(ch for ch in ext if ch.isascii() and (ch.isalnum() or ch == '.')) or '.png'
        return f'{safe_stem}{safe_ext.lower()}'

    def _resolve_unique_target_path(self, target_dir, filename):
        stem, ext = os.path.splitext(filename)
        candidate = os.path.join(target_dir, filename)
        index = 2
        while os.path.exists(candidate):
            candidate = os.path.join(target_dir, f'{stem}_{index}{ext}')
            index += 1
        return candidate

    def _wallpaper_id_for_path(self, path, prefix='imported'):
        rel_path = self._relative_path(path)
        digest = hashlib.sha1(rel_path.encode('utf-8')).hexdigest()[:12]
        return f'{prefix}:{digest}'

    def _safe_filename(self, value):
        normalized = []
        for char in str(value or '').strip():
            if char.isascii() and (char.isalnum() or char in ('-', '_')):
                normalized.append(char)
            elif char in (' ', '.'):
                normalized.append('_')
        result = ''.join(normalized).strip('._-')
        return result or f'wallpaper_{int(time.time())}'

    def _safe_path_component(self, value):
        normalized = []
        for char in str(value or '').strip():
            if char.isascii() and (char.isalnum() or char in ('-', '_')):
                normalized.append(char)
        return ''.join(normalized) or 'default'

    def _normalize_selection_id(self, value):
        return str(value or '').strip()

    def _safe_remove_file(self, path):
        try:
            if path and os.path.isfile(path):
                os.remove(path)
        except OSError:
            logger.warning('Failed to remove invalid imported wallpaper: %s', path, exc_info=True)

    def _files_match(self, left_path, right_path):
        if not left_path or not right_path:
            return False
        if not os.path.isfile(left_path) or not os.path.isfile(right_path):
            return False
        if os.path.getsize(left_path) != os.path.getsize(right_path):
            return False
        return self._file_digest(left_path) == self._file_digest(right_path)

    def _file_digest(self, path):
        digest = hashlib.sha1()
        with open(path, 'rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
        return digest.hexdigest()
