import copy
import hashlib
import json
import logging
import os
import shutil
import time
from typing import Callable, Dict, Optional

from PIL import Image
from PIL import UnidentifiedImageError

from core.config import get_beautify_folder
from core.data.ui_store import (
    get_beautify_library,
    get_last_sent_to_st,
    load_ui_data,
    save_ui_data,
    set_beautify_library,
    set_shared_wallpaper_library,
)
from core.services.shared_wallpaper_service import SharedWallpaperService


logger = logging.getLogger(__name__)

PACKAGE_DIRECTORY_DELETE_DELAYS = (0, 0.05, 0.15)


class BeautifyService:
    def __init__(
        self,
        library_root: Optional[str] = None,
        ui_data_loader: Optional[Callable[[], Dict]] = None,
        ui_data_saver: Optional[Callable[[Dict], bool]] = None,
    ):
        self.library_root = os.path.abspath(library_root or get_beautify_folder())
        self._ui_data_loader = ui_data_loader or load_ui_data
        self._ui_data_saver = ui_data_saver or save_ui_data
        os.makedirs(self.library_root, exist_ok=True)

    def _project_root_for_library(self):
        normalized = self.library_root.replace('\\', '/').rstrip('/')
        suffix = '/data/library/beautify'
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
        return os.path.dirname(os.path.dirname(os.path.dirname(self.library_root)))

    def _load_ui_data(self):
        data = self._ui_data_loader() or {}
        if not isinstance(data, dict):
            return {}
        return data

    def _save_library(self, ui_data: Dict, library_payload: Dict):
        changed = set_beautify_library(ui_data, library_payload)
        if changed:
            self._ui_data_saver(copy.deepcopy(ui_data))
        return changed

    def _load_library_state(self, ui_data: Optional[Dict] = None):
        state = ui_data if isinstance(ui_data, dict) else self._load_ui_data()
        legacy_selected_wallpaper_ids = self._snapshot_legacy_selected_wallpaper_ids(state)
        library = get_beautify_library(state)
        if self._should_recover_library_from_disk(state, library):
            library = self._recover_library_from_disk(library)

        library = self._recover_variant_wallpaper_bindings(
            state,
            library,
            persist=False,
            legacy_selected_wallpaper_ids=legacy_selected_wallpaper_ids,
        )
        reconciled_library = self._reconcile_variant_wallpaper_references(state, library, persist=False)
        if self._save_library(state, reconciled_library):
            return get_beautify_library(state)
        return reconciled_library

    def _snapshot_legacy_selected_wallpaper_ids(self, ui_data: Dict):
        raw_library = ui_data.get('_beautify_library_v1') if isinstance(ui_data, dict) else {}
        if not isinstance(raw_library, dict):
            return {}

        selections = {}
        for package_id, package_info in (raw_library.get('packages') or {}).items():
            if not isinstance(package_info, dict):
                continue
            for variant_id, variant in ((package_info.get('variants') or {}).items()):
                if not isinstance(variant, dict):
                    continue
                selected_wallpaper_id = str(variant.get('selected_wallpaper_id') or '').strip()
                if not selected_wallpaper_id:
                    continue
                selections[(str(package_id).strip(), str(variant_id).strip())] = selected_wallpaper_id
        return selections

    def _should_recover_library_from_disk(self, ui_data: Dict, library: Dict):
        return not bool(library.get('packages'))

    def load_library(self):
        return self._load_library_state()

    def _load_shared_wallpaper_library(self, ui_data: Dict):
        return SharedWallpaperService(
            project_root=self._project_root_for_library(),
            ui_data_loader=lambda: ui_data,
            ui_data_saver=lambda data: True,
        ).load_library()

    def _reconcile_variant_wallpaper_references(self, ui_data: Dict, library: Dict, persist: bool = True):
        shared_items = (self._load_shared_wallpaper_library(ui_data).get('items') or {})
        packages = copy.deepcopy(library.get('packages') or {})
        changed = False

        for package_id, package_info in packages.items():
            variants = copy.deepcopy(package_info.get('variants') or {})
            for variant_id, variant in variants.items():
                wallpaper_ids = [
                    wallpaper_id
                    for wallpaper_id in list(variant.get('wallpaper_ids', []))
                    if wallpaper_id in shared_items
                ]
                selected_wallpaper_id = str(variant.get('selected_wallpaper_id') or '').strip()
                if selected_wallpaper_id not in wallpaper_ids:
                    selected_wallpaper_id = ''

                if wallpaper_ids != list(variant.get('wallpaper_ids', [])) or selected_wallpaper_id != str(variant.get('selected_wallpaper_id') or '').strip():
                    changed = True
                    variant['wallpaper_ids'] = wallpaper_ids
                    variant['selected_wallpaper_id'] = selected_wallpaper_id
                variants[variant_id] = variant

            package_info['variants'] = variants
            packages[package_id] = package_info

        reconciled_library = copy.deepcopy(library)
        reconciled_library['packages'] = packages
        if persist and changed and self._save_library(ui_data, reconciled_library):
            return get_beautify_library(ui_data)
        return reconciled_library

    def _recover_variant_wallpaper_bindings(
        self,
        ui_data: Dict,
        library: Dict,
        persist: bool = True,
        legacy_selected_wallpaper_ids: Optional[Dict] = None,
    ):
        shared_service = SharedWallpaperService(
            project_root=self._project_root_for_library(),
            ui_data_loader=lambda: ui_data,
            ui_data_saver=self._ui_data_saver,
        )
        packages = copy.deepcopy(library.get('packages') or {})
        changed = False
        legacy_selected_wallpaper_ids = legacy_selected_wallpaper_ids or {}

        for package_id, package_info in packages.items():
            variants = copy.deepcopy(package_info.get('variants') or {})
            legacy_wallpapers = copy.deepcopy(package_info.get('wallpapers') or {})
            if not variants or not legacy_wallpapers:
                package_info['variants'] = variants
                packages[package_id] = package_info
                continue

            single_variant_id = next(iter(variants.keys())) if len(variants) == 1 else ''
            legacy_wallpapers_by_variant = {variant_id: [] for variant_id in variants}
            for legacy_wallpaper in legacy_wallpapers.values():
                target_variant_id = str(legacy_wallpaper.get('variant_id') or '').strip()
                if target_variant_id and target_variant_id not in variants:
                    continue
                if not target_variant_id:
                    if not single_variant_id:
                        continue
                    target_variant_id = single_variant_id
                legacy_wallpapers_by_variant.setdefault(target_variant_id, []).append(copy.deepcopy(legacy_wallpaper))

            for variant_id, variant in list(variants.items()):
                variant = copy.deepcopy(variant)
                wallpaper_ids = list(variant.get('wallpaper_ids') or [])
                selected_wallpaper_id = str(variant.get('selected_wallpaper_id') or '').strip()
                legacy_selected_wallpaper_id = str(
                    legacy_selected_wallpaper_ids.get((str(package_id).strip(), str(variant_id).strip())) or ''
                ).strip()

                for legacy_wallpaper in legacy_wallpapers_by_variant.get(variant_id, []):
                    source_path = self._resolve_project_relative_path(legacy_wallpaper.get('file', ''))
                    if not source_path or not os.path.isfile(source_path):
                        continue

                    recovered = shared_service.ensure_package_embedded_wallpaper(
                        source_path,
                        package_id=package_id,
                        variant_id=variant_id,
                        source_name=legacy_wallpaper.get('filename') or os.path.basename(source_path),
                    )
                    recovered_id = str((recovered or {}).get('id') or '').strip()
                    if not recovered_id:
                        continue
                    if recovered_id not in wallpaper_ids:
                        wallpaper_ids.append(recovered_id)
                    if legacy_selected_wallpaper_id == str(legacy_wallpaper.get('id') or '').strip():
                        selected_wallpaper_id = recovered_id

                if wallpaper_ids != list(variant.get('wallpaper_ids') or []) or selected_wallpaper_id != str(variant.get('selected_wallpaper_id') or '').strip():
                    changed = True
                    variant['wallpaper_ids'] = wallpaper_ids
                    variant['selected_wallpaper_id'] = selected_wallpaper_id
                variants[variant_id] = variant

            package_info['variants'] = variants
            packages[package_id] = package_info

        recovered_library = copy.deepcopy(library)
        recovered_library['packages'] = packages
        if persist and changed and self._save_library(ui_data, recovered_library):
            return get_beautify_library(ui_data)
        return recovered_library

    def get_global_settings(self):
        ui_data = self._load_ui_data()
        settings = copy.deepcopy(self._load_library_state(ui_data).get('global_settings', {}))
        shared_wallpaper_library = SharedWallpaperService(
            project_root=self._project_root_for_library(),
            ui_data_loader=lambda: ui_data,
            ui_data_saver=lambda data: True,
        ).load_library()
        preview_wallpaper_id = str(shared_wallpaper_library.get('preview_wallpaper_id') or '').strip()
        settings['preview_wallpaper_id'] = preview_wallpaper_id

        if preview_wallpaper_id:
            preview_wallpaper = (shared_wallpaper_library.get('items') or {}).get(preview_wallpaper_id)
            if preview_wallpaper:
                settings['wallpaper'] = copy.deepcopy(preview_wallpaper)

        return settings

    def list_packages(self):
        library = self.load_library()
        shared_items = (self._load_shared_wallpaper_library(self._load_ui_data()).get('items') or {})
        packages = []
        for package_info in library.get('packages', {}).values():
            variants = list(package_info.get('variants', {}).values())
            screenshots = list(package_info.get('screenshots', {}).values())
            active_wallpapers = []
            seen_wallpaper_ids = set()
            for variant in variants:
                for wallpaper_id in variant.get('wallpaper_ids', []):
                    if wallpaper_id in seen_wallpaper_ids:
                        continue
                    wallpaper = shared_items.get(wallpaper_id)
                    if not wallpaper:
                        continue
                    seen_wallpaper_ids.add(wallpaper_id)
                    active_wallpapers.append(wallpaper)
            packages.append(
                {
                    'id': package_info['id'],
                    'name': package_info.get('name') or package_info['id'],
                    'author': package_info.get('author', ''),
                    'variant_count': len(variants),
                    'wallpaper_count': len(active_wallpapers),
                    'screenshot_count': len(screenshots),
                    'platforms': sorted({variant.get('platform', 'dual') for variant in variants}),
                    'updated_at': package_info.get('updated_at', 0),
                    'wallpaper_previews': [wallpaper.get('file', '') for wallpaper in active_wallpapers[:3]],
                }
            )
        return sorted(packages, key=lambda item: (-(item.get('updated_at') or 0), item['name'].lower()))

    def get_package(self, package_id: str):
        ui_data = self._load_ui_data()
        library = self._load_library_state(ui_data)
        resolved_package_id = str(package_id or '').strip()
        package = library.get('packages', {}).get(resolved_package_id)
        if not package:
            return None

        result = copy.deepcopy(package)
        shared_items = (self._load_shared_wallpaper_library(ui_data).get('items') or {})
        wallpapers = {}
        for variant_id, variant in result.get('variants', {}).items():
            variant['theme_data'] = self._load_theme_data(variant.get('theme_file', ''))
            variant['last_sent_to_st'] = get_last_sent_to_st(
                ui_data,
                self.get_variant_send_state_key(resolved_package_id, variant_id),
            )
            for wallpaper_id in list(variant.get('wallpaper_ids', [])):
                wallpaper = shared_items.get(wallpaper_id)
                if wallpaper:
                    wallpapers[wallpaper_id] = copy.deepcopy(wallpaper)
            result['variants'][variant_id] = variant
        result['wallpapers'] = wallpapers
        return result

    def get_variant_send_state_key(self, package_id: str, variant_id: str):
        resolved_package_id = str(package_id or '').strip()
        resolved_variant_id = str(variant_id or '').strip()
        return f'beautify::package::{resolved_package_id}::variant::{resolved_variant_id}'

    def build_sendable_theme_bundle(self, package_id: str, variant_id: str):
        package_detail = self.get_package(package_id)
        if not package_detail:
            raise LookupError('美化包不存在')

        resolved_variant_id = str(variant_id or '').strip()
        variant = copy.deepcopy((package_detail.get('variants') or {}).get(resolved_variant_id))
        if not variant:
            raise LookupError('变体不存在')

        theme_data = copy.deepcopy(variant.get('theme_data') or {})
        if not theme_data:
            raise ValueError('当前变体缺少可发送的主题数据')

        theme_name = str(theme_data.get('name') or '').strip()
        if not theme_name:
            raise ValueError('当前变体主题缺少 name，无法发送到 ST')

        theme_data['name'] = theme_name
        return {
            'package': copy.deepcopy(package_detail),
            'variant': variant,
            'theme_data': theme_data,
        }

    def import_theme(self, source_path: str, package_id: Optional[str] = None, platform: Optional[str] = None, source_name: Optional[str] = None):
        if not source_path or not os.path.isfile(source_path):
            raise ValueError('主题文件不存在')

        theme_payload = self._load_theme_payload(source_path)
        source_hint = source_name or source_path
        guessed_platform, needs_review = self.guess_platform(source_hint, theme_payload.get('name', ''), package_name='')
        resolved_platform = self._normalize_platform(platform) or guessed_platform
        if platform:
            needs_review = False

        ui_data = self._load_ui_data()
        library = self._load_library_state(ui_data)
        packages = dict(library.get('packages', {}))

        package_name = str(theme_payload.get('name') or '').strip() or PathLike.basename_without_ext(source_hint) or '未命名主题'
        resolved_package_id = str(package_id or '').strip() or self._build_package_id(package_name, packages)
        package_info = copy.deepcopy(packages.get(resolved_package_id) or self._build_empty_package(resolved_package_id, package_name))
        package_info['name'] = package_info.get('name') or package_name
        target_existing_package = bool(str(package_id or '').strip())

        themes_dir = os.path.join(self.library_root, 'packages', resolved_package_id, 'themes')
        os.makedirs(themes_dir, exist_ok=True)

        if target_existing_package:
            variant_id = self._build_variant_id(resolved_platform, source_hint, package_info)
            target_file = os.path.join(themes_dir, f'{variant_id}.json')
            variant_name = self._build_variant_name(theme_payload)
            wallpaper_ids = []
            selected_wallpaper_id = ''
        else:
            existing_variant = self._find_variant_by_platform(package_info, resolved_platform)
            target_file = os.path.join(themes_dir, f'{resolved_platform}.json')
            relative_theme_file = os.path.relpath(target_file, self._project_root_for_library()).replace('\\', '/')
            variant_id = existing_variant['id'] if existing_variant else f'var_{resolved_platform}_{self._short_hash(relative_theme_file)}'
            variant_name = (existing_variant or {}).get('name') or self._build_variant_name(theme_payload)
            wallpaper_ids = list((existing_variant or {}).get('wallpaper_ids', []))
            selected_wallpaper_id = str((existing_variant or {}).get('selected_wallpaper_id') or '').strip()

        with open(target_file, 'w', encoding='utf-8') as f:
            json.dump(theme_payload, f, ensure_ascii=False, indent=2)

        preview_accuracy = 'approx' if self._theme_has_custom_css(theme_payload) else ('approx' if resolved_platform in ('pc', 'mobile') else 'base')
        relative_theme_file = os.path.relpath(target_file, self._project_root_for_library()).replace('\\', '/')
        package_info['variants'][variant_id] = {
            'id': variant_id,
            'name': variant_name,
            'platform': resolved_platform,
            'theme_name': str(theme_payload.get('name') or package_info['name']).strip(),
            'theme_file': relative_theme_file,
            'wallpaper_ids': wallpaper_ids,
            'selected_wallpaper_id': selected_wallpaper_id,
            'preview_hint': {
                'needs_platform_review': needs_review,
                'preview_accuracy': preview_accuracy,
            },
        }
        package_info['cover_variant_id'] = package_info.get('cover_variant_id') or variant_id
        now = int(time.time())
        package_info['updated_at'] = now
        if not package_info.get('created_at'):
            package_info['created_at'] = now
        packages[resolved_package_id] = package_info
        library['packages'] = packages
        self._save_library(ui_data, library)

        return {
            'package': copy.deepcopy(package_info),
            'variant': copy.deepcopy(package_info['variants'][variant_id]),
            'theme': theme_payload,
        }

    def update_variant(self, package_id: str, variant_id: str, platform: Optional[str] = None, selected_wallpaper_id: str = ''):
        resolved_platform = self._normalize_platform(platform) if platform is not None else ''
        if platform is not None and not resolved_platform:
            raise ValueError('无效的端类型')

        ui_data = self._load_ui_data()
        library, package_info, variant = self._load_package_variant(ui_data, package_id, variant_id)
        if resolved_platform and variant.get('platform') != resolved_platform:
            old_theme_path = self._resolve_project_relative_path(variant.get('theme_file', ''))
            theme_payload = self._load_theme_data(variant.get('theme_file', '')) or {}
            variant_basename = os.path.basename(str(variant.get('theme_file') or '').replace('\\', '/'))
            if variant_basename.startswith('var_'):
                theme_filename = variant_basename
            else:
                theme_filename = f'{resolved_platform}.json'
                for sibling_id, sibling in (package_info.get('variants') or {}).items():
                    if sibling_id == variant_id:
                        continue
                    sibling_theme_file = str((sibling or {}).get('theme_file') or '').replace('\\', '/').strip()
                    if sibling_theme_file.endswith(f'/themes/{theme_filename}'):
                        theme_filename = f'{variant_id}.json'
                        break
            new_theme_path = os.path.join(self.library_root, 'packages', package_info['id'], 'themes', theme_filename)
            os.makedirs(os.path.dirname(new_theme_path), exist_ok=True)
            if old_theme_path and os.path.exists(old_theme_path) and os.path.abspath(old_theme_path) != os.path.abspath(new_theme_path):
                if os.path.exists(new_theme_path):
                    os.remove(new_theme_path)
                shutil.move(old_theme_path, new_theme_path)
            if theme_payload:
                theme_payload['platform'] = resolved_platform
                with open(new_theme_path, 'w', encoding='utf-8') as f:
                    json.dump(theme_payload, f, ensure_ascii=False, indent=2)
            variant['platform'] = resolved_platform
            variant['theme_file'] = os.path.relpath(new_theme_path, self._project_root_for_library()).replace('\\', '/')

        normalized_wallpaper_id = str(selected_wallpaper_id or '').strip()
        if normalized_wallpaper_id and normalized_wallpaper_id not in list(variant.get('wallpaper_ids', [])):
            raise ValueError('壁纸不存在或未绑定到当前变体')
        variant['selected_wallpaper_id'] = normalized_wallpaper_id

        preview_hint = copy.deepcopy(variant.get('preview_hint') or {})
        preview_hint['needs_platform_review'] = False
        variant['preview_hint'] = preview_hint

        package_info['variants'][variant_id] = variant
        package_info['updated_at'] = int(time.time())
        library['packages'][package_info['id']] = package_info
        self._save_library(ui_data, library)
        return copy.deepcopy(variant)

    def import_wallpaper(self, package_id: str, variant_id: str, source_path: str, source_name: Optional[str] = None):
        if not source_path or not os.path.isfile(source_path):
            raise ValueError('壁纸文件不存在')

        ui_data = self._load_ui_data()
        library, package_info, variant = self._load_package_variant(ui_data, package_id, variant_id)
        try:
            wallpaper = SharedWallpaperService(
                project_root=self._project_root_for_library(),
                ui_data_loader=lambda: ui_data,
                ui_data_saver=lambda data: True,
            ).import_wallpaper(
                source_path,
                source_name=source_name,
                package_id=package_info['id'],
                variant_id=variant_id,
            )
        except ValueError as exc:
            raise ValueError('壁纸文件无效') from exc
        if not wallpaper:
            raise ValueError('壁纸文件无效')

        wallpaper_ids = list(variant.get('wallpaper_ids', []))
        wallpaper_id = wallpaper.get('id', '')
        if wallpaper_id and wallpaper_id not in wallpaper_ids:
            wallpaper_ids.append(wallpaper_id)
        variant['wallpaper_ids'] = wallpaper_ids
        variant['selected_wallpaper_id'] = wallpaper_id
        package_info['variants'][variant_id] = variant
        package_info['updated_at'] = int(time.time())
        library['packages'][package_info['id']] = package_info
        self._save_library(ui_data, library)

        return {
            'package': copy.deepcopy(package_info),
            'variant': copy.deepcopy(variant),
            'wallpaper': copy.deepcopy(wallpaper),
        }

    def update_global_settings(self, payload: Optional[Dict] = None):
        ui_data = self._load_ui_data()
        library = self._load_library_state(ui_data)
        global_settings = copy.deepcopy(library.get('global_settings') or {})
        identities = copy.deepcopy(global_settings.get('identities') or {})
        source = payload if isinstance(payload, dict) else {}

        if source.get('clear_wallpaper') is True:
            self._remove_asset_file((global_settings.get('wallpaper') or {}).get('file', ''))
            global_settings['wallpaper'] = {}
            shared_service = SharedWallpaperService(
                project_root=self._project_root_for_library(),
                ui_data_loader=lambda: ui_data,
                ui_data_saver=lambda data: True,
            )
            shared_library = shared_service.load_library()
            next_shared_payload = {
                'items': dict(shared_library.get('items') or {}),
                'manager_wallpaper_id': shared_library.get('manager_wallpaper_id', ''),
                'preview_wallpaper_id': '',
            }
            set_shared_wallpaper_library(ui_data, next_shared_payload)

        for key in ('character', 'user'):
            current_identity = copy.deepcopy(identities.get(key) or {})
            name_key = f'{key}_name'
            if name_key in source:
                current_identity['name'] = str(source.get(name_key) or '').strip()

            if source.get(f'clear_{key}_avatar') is True:
                self._remove_asset_file(current_identity.get('avatar_file', ''))
                current_identity['avatar_file'] = ''

            identities[key] = current_identity

        global_settings['identities'] = identities
        library['global_settings'] = global_settings
        self._save_library(ui_data, library)
        return self.get_global_settings()

    def import_global_wallpaper(self, source_path: str, source_name: Optional[str] = None):
        if not source_path or not os.path.isfile(source_path):
            raise ValueError('壁纸文件不存在')

        ui_data = self._load_ui_data()
        library = self._load_library_state(ui_data)
        global_settings = copy.deepcopy(library.get('global_settings') or {})
        wallpapers_dir = os.path.join(self.library_root, 'global', 'wallpapers')
        try:
            wallpaper = self._copy_asset_to_slot(wallpapers_dir, 'wallpaper', source_path, source_name=source_name)
        except ValueError as exc:
            raise ValueError('壁纸文件无效') from exc

        global_settings['wallpaper'] = wallpaper
        library['global_settings'] = global_settings
        self._save_library(ui_data, library)
        return {'wallpaper': copy.deepcopy(wallpaper)}

    def import_global_avatar(self, target: str, source_path: str, source_name: Optional[str] = None):
        return {'identity': self._import_identity_avatar(None, target, source_path, source_name=source_name)}

    def import_screenshot(self, package_id: str, source_path: str, source_name: Optional[str] = None):
        if not source_path or not os.path.isfile(source_path):
            raise ValueError('截图文件不存在')

        ui_data = self._load_ui_data()
        library, package_info = self._load_package(ui_data, package_id)
        screenshots_dir = os.path.join(self.library_root, 'packages', package_info['id'], 'screenshots')
        try:
            screenshot = self._copy_asset_file(screenshots_dir, source_path, source_name=source_name)
        except ValueError as exc:
            raise ValueError('截图文件无效') from exc
        screenshot_id = f'shot_{self._short_hash(screenshot["file"] + str(time.time()))}'
        screenshot['id'] = screenshot_id

        screenshots = copy.deepcopy(package_info.get('screenshots') or {})
        screenshots[screenshot_id] = screenshot
        package_info['screenshots'] = screenshots
        package_info['updated_at'] = int(time.time())
        library['packages'][package_info['id']] = package_info
        self._save_library(ui_data, library)
        return {'package': copy.deepcopy(package_info), 'screenshot': copy.deepcopy(screenshot)}

    def update_package_identities(self, package_id: str, identities_payload: Optional[Dict] = None):
        ui_data = self._load_ui_data()
        library, package_info = self._load_package(ui_data, package_id)
        identity_overrides = copy.deepcopy(package_info.get('identity_overrides') or {})
        source = identities_payload if isinstance(identities_payload, dict) else {}

        for key in ('character', 'user'):
            current_identity = copy.deepcopy(identity_overrides.get(key) or {})
            name_key = f'{key}_name'
            if name_key in source:
                current_identity['name'] = str(source.get(name_key) or '').strip()

            if source.get(f'clear_{key}_avatar') is True:
                self._remove_asset_file(current_identity.get('avatar_file', ''))
                current_identity['avatar_file'] = ''

            identity_overrides[key] = current_identity

        package_info['identity_overrides'] = identity_overrides
        package_info['updated_at'] = int(time.time())
        library['packages'][package_info['id']] = package_info
        self._save_library(ui_data, library)
        return copy.deepcopy(package_info)

    def import_package_avatar(self, package_id: str, target: str, source_path: str, source_name: Optional[str] = None):
        return {
            'identity': self._import_identity_avatar(package_id, target, source_path, source_name=source_name)
        }

    def delete_package(self, package_id: str):
        ui_data = self._load_ui_data()
        library = self._load_library_state(ui_data)
        resolved_package_id = str(package_id or '').strip()
        packages = dict(library.get('packages', {}))
        package_info = packages.get(resolved_package_id)
        if not package_info:
            return False

        shared_library = self._load_shared_wallpaper_library(ui_data)
        shared_items = dict(shared_library.get('items') or {})
        removed_wallpaper_ids = set()
        for variant in (package_info.get('variants') or {}).values():
            for wallpaper_id in list(variant.get('wallpaper_ids') or []):
                wallpaper = shared_items.get(wallpaper_id)
                if not wallpaper:
                    continue
                if wallpaper.get('source_type') != 'package_embedded':
                    continue
                if str(wallpaper.get('origin_package_id') or '').strip() != resolved_package_id:
                    continue
                removed_wallpaper_ids.add(wallpaper_id)
                self._remove_shared_wallpaper_file(wallpaper.get('file', ''))
                shared_items.pop(wallpaper_id, None)

        if removed_wallpaper_ids:
            next_shared_payload = {
                'items': shared_items,
                'manager_wallpaper_id': ''
                if shared_library.get('manager_wallpaper_id') in removed_wallpaper_ids
                else shared_library.get('manager_wallpaper_id', ''),
                'preview_wallpaper_id': ''
                if shared_library.get('preview_wallpaper_id') in removed_wallpaper_ids
                else shared_library.get('preview_wallpaper_id', ''),
            }
            set_shared_wallpaper_library(ui_data, next_shared_payload)

        del packages[resolved_package_id]
        library['packages'] = packages

        package_dir = os.path.join(self.library_root, 'packages', resolved_package_id)
        self._remove_package_directory(package_dir)

        self._save_library(ui_data, library)
        return True

    def _remove_package_directory(self, package_dir: str):
        last_error = None
        for delay in PACKAGE_DIRECTORY_DELETE_DELAYS:
            if delay:
                time.sleep(delay)
            try:
                if not os.path.isdir(package_dir):
                    return
                shutil.rmtree(package_dir)
                return
            except FileNotFoundError:
                return
            except OSError as exc:
                last_error = exc
                logger.warning('删除美化包目录失败，将重试: %s', package_dir)

        if os.path.isdir(package_dir) and last_error is not None:
            raise last_error

    def _remove_shared_wallpaper_file(self, file_path: str):
        normalized = str(file_path or '').replace('\\', '/').strip().lstrip('/')
        if not normalized:
            return

        if not normalized.startswith('data/library/wallpapers/package_embedded/'):
            return

        project_root = self._project_root_for_library()
        target_path = os.path.abspath(os.path.join(project_root, normalized.replace('/', os.sep)))
        allowed_root = os.path.abspath(
            os.path.join(project_root, 'data', 'library', 'wallpapers', 'package_embedded')
        )
        try:
            if os.path.commonpath([target_path, allowed_root]) != allowed_root:
                return
        except ValueError:
            return

        if os.path.isfile(target_path):
            try:
                os.remove(target_path)
            except OSError:
                logger.warning('无法删除共享壁纸文件: %s', target_path)

        current_dir = os.path.dirname(target_path)
        while current_dir and current_dir != allowed_root:
            try:
                os.rmdir(current_dir)
            except OSError:
                break
            current_dir = os.path.dirname(current_dir)

    def get_preview_asset_path(self, subpath: str):
        normalized = str(subpath or '').replace('\\', '/').strip().lstrip('/')
        if not normalized or '..' in normalized.split('/'):
            return None

        project_root = self._project_root_for_library()
        candidates = [
            (self.library_root, normalized),
        ]
        if normalized.startswith('static/') or normalized.startswith('data/library/wallpapers/'):
            candidates.append((project_root, normalized))

        for root, relative_path in candidates:
            abs_root = os.path.abspath(root)
            candidate = os.path.abspath(os.path.join(abs_root, relative_path.replace('/', os.sep)))
            if os.path.commonpath([candidate, abs_root]) != abs_root:
                continue
            if os.path.exists(candidate) and os.path.isfile(candidate):
                return candidate
        return None

    def guess_platform(self, source_path: str, theme_name: str = '', package_name: str = ''):
        tokens = ' '.join(
            [
                os.path.basename(source_path or ''),
                str(theme_name or ''),
                str(package_name or ''),
            ]
        ).lower()
        if any(keyword in tokens for keyword in ('mobile', '移动', '手机')):
            return 'mobile', False
        if any(keyword in tokens for keyword in ('pc', '电脑', '桌面')):
            return 'pc', False
        if any(keyword in tokens for keyword in ('dual', '双端', '通用')):
            return 'dual', False
        return 'dual', True

    def _load_theme_payload(self, source_path: str):
        try:
            with open(source_path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError('主题 JSON 无法解析') from exc

        if not isinstance(payload, dict):
            raise ValueError('主题 JSON 格式无效')

        if not payload.get('name'):
            raise ValueError('主题缺少 name 字段')

        if not any(key in payload for key in ('main_text_color', 'chat_tint_color', 'custom_css', 'font_scale')):
            raise ValueError('文件不是有效的 ST theme JSON')

        return payload

    def _normalize_platform(self, platform: Optional[str]):
        value = str(platform or '').strip().lower()
        if value in ('pc', 'mobile', 'dual'):
            return value
        return ''

    def _build_empty_package(self, package_id: str, package_name: str):
        return {
            'id': package_id,
            'name': package_name,
            'author': '',
            'tags': [],
            'notes': '',
            'cover_variant_id': '',
            'created_at': int(time.time()),
            'updated_at': int(time.time()),
            'screenshots': {},
            'identity_overrides': {},
            'variants': {},
            'wallpapers': {},
        }

    def _recover_library_from_disk(self, library: Optional[Dict] = None):
        recovered_library = copy.deepcopy(library if isinstance(library, dict) else {})
        existing_packages = copy.deepcopy(recovered_library.get('packages') or {})
        packages = {}
        packages_root = os.path.join(self.library_root, 'packages')
        if not os.path.isdir(packages_root):
            recovered_library['packages'] = packages
            return recovered_library

        try:
            package_ids = sorted(
                entry
                for entry in os.listdir(packages_root)
                if os.path.isdir(os.path.join(packages_root, entry))
            )
        except OSError:
            recovered_library['packages'] = packages
            return recovered_library

        for package_id in package_ids:
            recovered_package = self._recover_package_from_disk(package_id, existing_packages.get(package_id))
            if recovered_package:
                packages[package_id] = recovered_package

        recovered_library['packages'] = packages
        return recovered_library

    def _recover_package_from_disk(self, package_id: str, package_info: Optional[Dict] = None):
        package_dir = os.path.join(self.library_root, 'packages', package_id)
        if not os.path.isdir(package_dir):
            return None

        existing_package = copy.deepcopy(package_info) if isinstance(package_info, dict) else {}
        existing_name = str(existing_package.get('name') or '').strip()
        package_name = existing_name or self._display_package_name(package_id)
        recovered_package = self._build_empty_package(package_id, package_name)
        for key in ('author', 'tags', 'notes', 'cover_variant_id', 'created_at', 'updated_at'):
            if key in existing_package:
                recovered_package[key] = copy.deepcopy(existing_package.get(key))

        theme_variants = self._recover_theme_variants(package_id, recovered_package, existing_package.get('variants'))
        if theme_variants:
            recovered_package['variants'] = theme_variants
            first_variant = next(iter(theme_variants.values()))
            if not existing_name and len(theme_variants) == 1:
                recovered_package['name'] = first_variant.get('theme_name') or package_name
            if not recovered_package.get('cover_variant_id') or recovered_package['cover_variant_id'] not in theme_variants:
                recovered_package['cover_variant_id'] = first_variant['id']
        elif not recovered_package.get('variants'):
            return None

        recovered_package['wallpapers'] = self._recover_assets_from_dir(package_id, 'wallpapers', 'wp')

        screenshots = self._recover_assets_from_dir(package_id, 'screenshots', 'shot')
        if not screenshots:
            screenshots = self._recover_assets_from_dir(package_id, 'screens', 'shot')
        recovered_package['screenshots'] = screenshots

        recovered_package['identity_overrides'] = self._recover_identity_overrides(package_id, existing_package.get('identity_overrides'))

        updated_candidates = [int(recovered_package.get('updated_at') or 0)]
        created_candidates = [int(recovered_package.get('created_at') or 0)]
        for variant in recovered_package.get('variants', {}).values():
            theme_path = self._resolve_project_relative_path(variant.get('theme_file', ''))
            timestamp = self._safe_mtime(theme_path)
            if timestamp:
                updated_candidates.append(timestamp)
                created_candidates.append(timestamp)
        for collection_name in ('wallpapers', 'screenshots'):
            for asset in recovered_package.get(collection_name, {}).values():
                timestamp = int(asset.get('mtime') or 0)
                if timestamp:
                    updated_candidates.append(timestamp)
                    created_candidates.append(timestamp)

        created_at = min((value for value in created_candidates if value > 0), default=0)
        updated_at = max((value for value in updated_candidates if value > 0), default=created_at)
        if created_at:
            recovered_package['created_at'] = created_at
        if updated_at:
            recovered_package['updated_at'] = updated_at
        return recovered_package

    def _recover_theme_variants(self, package_id: str, package_info: Dict, existing_variants: Optional[Dict] = None):
        themes_dir = os.path.join(self.library_root, 'packages', package_id, 'themes')
        if not os.path.isdir(themes_dir):
            return {}

        variants = {}
        existing_variants = copy.deepcopy(existing_variants) if isinstance(existing_variants, dict) else {}
        try:
            filenames = sorted(entry for entry in os.listdir(themes_dir) if entry.lower().endswith('.json'))
        except OSError:
            return {}

        for filename in filenames:
            theme_path = os.path.join(themes_dir, filename)
            theme_payload = self._read_recoverable_theme_payload(theme_path)
            if not theme_payload:
                continue
            theme_name = str(theme_payload.get('name') or '').strip()
            platform_name = os.path.splitext(filename)[0]
            platform = self._normalize_platform(theme_payload.get('platform')) or self._normalize_platform(platform_name)
            needs_platform_review = False
            if not platform_name:
                platform, needs_platform_review = self.guess_platform(filename, theme_name=theme_name, package_name=package_info.get('name', ''))
            else:
                platform = platform or platform_name.lower()
            if platform not in ('pc', 'mobile', 'dual'):
                platform, needs_platform_review = self.guess_platform(filename, theme_name=theme_name, package_name=package_info.get('name', ''))
            relative_theme_file = os.path.relpath(theme_path, self._project_root_for_library()).replace('\\', '/')
            variant_id, existing_variant = self._match_existing_variant(existing_variants, platform, relative_theme_file)
            if not variant_id:
                variant_id = f'var_{platform}_{self._short_hash(relative_theme_file)}'

            preview_hint = copy.deepcopy((existing_variant or {}).get('preview_hint') or {})
            preview_hint['needs_platform_review'] = bool(preview_hint.get('needs_platform_review')) or needs_platform_review
            preview_hint['preview_accuracy'] = 'approx' if self._theme_has_custom_css(theme_payload) else ('approx' if platform in ('pc', 'mobile') else 'base')
            variants[variant_id] = {
                'id': variant_id,
                'name': (existing_variant or {}).get('name') or theme_name or '未命名变体',
                'platform': platform,
                'theme_name': theme_name or (existing_variant or {}).get('theme_name') or package_info.get('name') or self._display_package_name(package_id),
                'theme_file': relative_theme_file,
                'wallpaper_ids': list((existing_variant or {}).get('wallpaper_ids', [])),
                'selected_wallpaper_id': str((existing_variant or {}).get('selected_wallpaper_id') or '').strip(),
                'preview_hint': preview_hint,
            }

        return variants

    def _match_existing_variant(self, existing_variants: Dict, platform: str, theme_file: str):
        for variant_id, variant in (existing_variants or {}).items():
            if str((variant or {}).get('theme_file') or '').strip() == theme_file:
                return variant_id, copy.deepcopy(variant)
        return '', None

    def _recover_assets_from_dir(self, package_id: str, folder_name: str, asset_prefix: str):
        assets_dir = os.path.join(self.library_root, 'packages', package_id, folder_name)
        if not os.path.isdir(assets_dir):
            return {}

        assets = {}
        try:
            filenames = sorted(
                entry
                for entry in os.listdir(assets_dir)
                if os.path.isfile(os.path.join(assets_dir, entry))
            )
        except OSError:
            return {}

        for filename in filenames:
            asset_path = os.path.join(assets_dir, filename)
            asset = self._read_image_asset(asset_path)
            if not asset:
                continue
            asset_id = f'{asset_prefix}_{self._short_hash(asset["file"])}'
            asset['id'] = asset_id
            if asset_prefix == 'wp':
                asset['variant_id'] = ''
            assets[asset_id] = asset
        return assets

    def _recover_identity_overrides(self, package_id: str, existing_identities: Optional[Dict] = None):
        avatars_dir = os.path.join(self.library_root, 'packages', package_id, 'avatars')
        existing = copy.deepcopy(existing_identities) if isinstance(existing_identities, dict) else {}
        identities = {
            'character': {'name': str((existing.get('character') or {}).get('name') or '').strip(), 'avatar_file': ''},
            'user': {'name': str((existing.get('user') or {}).get('name') or '').strip(), 'avatar_file': ''},
        }
        if not os.path.isdir(avatars_dir):
            return identities

        for target in ('character', 'user'):
            avatar = self._find_slot_asset(avatars_dir, target)
            if avatar:
                identities[target]['avatar_file'] = avatar['file']
        return identities

    def _find_slot_asset(self, target_dir: str, slot_name: str):
        if not os.path.isdir(target_dir):
            return {}
        prefix = f'{slot_name}.'
        try:
            filenames = sorted(entry for entry in os.listdir(target_dir) if entry.lower().startswith(prefix))
        except OSError:
            return {}
        for filename in filenames:
            asset = self._read_image_asset(os.path.join(target_dir, filename))
            if asset:
                return asset
        return {}

    def _read_image_asset(self, path: str):
        if not path or not os.path.isfile(path):
            return {}
        try:
            with Image.open(path) as image:
                width, height = image.size
        except (UnidentifiedImageError, OSError, ValueError):
            logger.warning('Skipping invalid beautify asset during recovery: %s', path, exc_info=True)
            return {}

        return {
            'file': os.path.relpath(path, self._project_root_for_library()).replace('\\', '/'),
            'filename': os.path.basename(path),
            'width': width,
            'height': height,
            'mtime': self._safe_mtime(path),
        }

    def _read_json_file(self, path: str):
        if not path or not os.path.isfile(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                payload = json.load(f)
            return payload if isinstance(payload, dict) else {}
        except (OSError, json.JSONDecodeError):
            logger.warning('Skipping invalid beautify theme during recovery: %s', path, exc_info=True)
            return {}

    def _read_recoverable_theme_payload(self, path: str):
        try:
            return self._load_theme_payload(path)
        except ValueError:
            logger.warning('Skipping invalid beautify theme during recovery: %s', path, exc_info=True)
            return {}

    def _safe_mtime(self, path: str):
        if not path or not os.path.exists(path):
            return 0
        try:
            return int(os.path.getmtime(path))
        except OSError:
            return 0

    def _display_package_name(self, package_id: str):
        normalized = str(package_id or '').strip()
        if normalized.startswith('pkg_'):
            normalized = normalized[4:]
        return normalized.replace('_', ' ').strip() or str(package_id or '').strip()

    def _build_package_id(self, package_name: str, existing_packages: Dict):
        base = self._slugify(package_name) or 'theme'
        candidate = f'pkg_{base}'
        if candidate not in existing_packages:
            return candidate
        suffix = self._short_hash(package_name + str(time.time()))
        return f'{candidate}_{suffix}'

    def _build_variant_id(self, platform: str, source_hint: str, package_info: Dict):
        seed = f'{platform}:{source_hint}:{time.time()}'
        variant_id = f'var_{platform}_{self._short_hash(seed)}'
        while variant_id in (package_info.get('variants') or {}):
            seed = f'{seed}:dup'
            variant_id = f'var_{platform}_{self._short_hash(seed)}'
        return variant_id

    def _build_variant_name(self, theme_payload: Dict):
        return str(theme_payload.get('name') or '').strip() or '未命名变体'

    def _slugify(self, value: str):
        normalized = []
        for char in str(value or '').strip().lower():
            if char.isascii() and char.isalnum():
                normalized.append(char)
            elif char in (' ', '-', '_'):
                normalized.append('_')
        slug = ''.join(normalized).strip('_')
        while '__' in slug:
            slug = slug.replace('__', '_')
        return slug

    def _short_hash(self, value: str):
        return hashlib.md5(value.encode('utf-8')).hexdigest()[:8]

    def _theme_has_custom_css(self, payload: Dict):
        return bool(str(payload.get('custom_css') or '').strip())

    def _resolve_project_relative_path(self, relative_path: str):
        if not relative_path:
            return ''
        return os.path.join(self._project_root_for_library(), relative_path.replace('/', os.sep))

    def _load_package_variant(self, ui_data: Dict, package_id: str, variant_id: str):
        library, package_info = self._load_package(ui_data, package_id)
        resolved_variant_id = str(variant_id or '').strip()

        variant = copy.deepcopy(package_info.get('variants', {}).get(resolved_variant_id))
        if not variant:
            raise ValueError('变体不存在')

        return library, package_info, variant

    def _load_package(self, ui_data: Dict, package_id: str):
        library = self._load_library_state(ui_data)
        resolved_package_id = str(package_id or '').strip()
        package_info = copy.deepcopy(library.get('packages', {}).get(resolved_package_id))
        if not package_info:
            raise ValueError('美化包不存在')
        return library, package_info

    def _build_unique_filename(self, target_dir: str, filename: str):
        sanitized_name = os.path.basename(str(filename or '').replace('\\', '/'))
        base_name, ext = os.path.splitext(sanitized_name)
        safe_base = base_name.strip() or 'wallpaper'
        safe_ext = ext or '.png'
        candidate = f'{safe_base}{safe_ext}'
        if not os.path.exists(os.path.join(target_dir, candidate)):
            return candidate

        index = 1
        while True:
            candidate = f'{safe_base}-{index}{safe_ext}'
            if not os.path.exists(os.path.join(target_dir, candidate)):
                return candidate
            index += 1

    def _find_variant_by_platform(self, package_info: Dict, platform: str):
        for variant in (package_info.get('variants') or {}).values():
            if variant.get('platform') == platform:
                return copy.deepcopy(variant)
        return None

    def _normalize_identity_target(self, target: str):
        resolved_target = str(target or '').strip().lower()
        if resolved_target not in ('character', 'user'):
            raise ValueError('无效的身份类型')
        return resolved_target

    def _copy_asset_to_slot(self, target_dir: str, slot_name: str, source_path: str, source_name: Optional[str] = None):
        original_name = source_name or os.path.basename(source_path)
        _, ext = os.path.splitext(original_name or '')
        slot_filename = f'{slot_name}{ext or ".png"}'
        os.makedirs(target_dir, exist_ok=True)
        target_file = os.path.join(target_dir, slot_filename)
        temp_file = os.path.join(target_dir, f'__incoming__{slot_filename}')
        try:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        except OSError:
            pass
        shutil.copy2(source_path, temp_file)

        try:
            with Image.open(temp_file) as image:
                width, height = image.size
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            self._remove_asset_file(os.path.relpath(temp_file, self._project_root_for_library()).replace('\\', '/'))
            raise ValueError('图片文件无效') from exc

        self._remove_slot_files(target_dir, slot_name, keep_filename=slot_filename)
        try:
            os.replace(temp_file, target_file)
        except OSError as exc:
            self._remove_asset_file(os.path.relpath(temp_file, self._project_root_for_library()).replace('\\', '/'))
            raise ValueError('图片文件无效') from exc

        return {
            'file': os.path.relpath(target_file, self._project_root_for_library()).replace('\\', '/'),
            'filename': slot_filename,
            'width': width,
            'height': height,
            'mtime': int(os.path.getmtime(target_file)),
        }

    def _remove_slot_files(self, target_dir: str, slot_name: str, keep_filename: str = ''):
        if not os.path.isdir(target_dir):
            return

        prefix = f'{slot_name}.'
        keep_name = str(keep_filename or '').strip().lower()
        for entry in os.listdir(target_dir):
            normalized = entry.lower()
            if not normalized.startswith(prefix):
                continue
            if keep_name and normalized == keep_name:
                continue
            try:
                os.remove(os.path.join(target_dir, entry))
            except OSError:
                continue

    def _remove_asset_file(self, relative_path: str):
        path = self._resolve_project_relative_path(relative_path)
        if not path or not os.path.isfile(path):
            return
        try:
            if os.path.commonpath([os.path.abspath(path), self.library_root]) != self.library_root:
                return
        except ValueError:
            return
        try:
            os.remove(path)
        except OSError:
            return

    def _copy_asset_file(self, target_dir: str, source_path: str, source_name: Optional[str] = None):
        os.makedirs(target_dir, exist_ok=True)
        original_name = source_name or os.path.basename(source_path)
        target_name = self._build_unique_filename(target_dir, original_name)
        target_file = os.path.join(target_dir, target_name)
        shutil.copy2(source_path, target_file)

        try:
            with Image.open(target_file) as image:
                width, height = image.size
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            self._remove_asset_file(os.path.relpath(target_file, self._project_root_for_library()).replace('\\', '/'))
            raise ValueError('图片文件无效') from exc

        return {
            'file': os.path.relpath(target_file, self._project_root_for_library()).replace('\\', '/'),
            'filename': target_name,
            'width': width,
            'height': height,
            'mtime': int(os.path.getmtime(target_file)),
        }

    def _import_identity_avatar(self, package_id: Optional[str], target: str, source_path: str, source_name: Optional[str] = None):
        if not source_path or not os.path.isfile(source_path):
            raise ValueError('头像文件不存在')

        resolved_target = self._normalize_identity_target(target)
        ui_data = self._load_ui_data()
        library = self._load_library_state(ui_data)

        if package_id is None:
            global_settings = copy.deepcopy(library.get('global_settings') or {})
            identities = copy.deepcopy(global_settings.get('identities') or {})
            identity = copy.deepcopy(identities.get(resolved_target) or {})
            avatars_dir = os.path.join(self.library_root, 'global', 'avatars')
            try:
                identity['avatar_file'] = self._copy_asset_to_slot(
                    avatars_dir,
                    resolved_target,
                    source_path,
                    source_name=source_name,
                )['file']
            except ValueError as exc:
                raise ValueError('头像文件无效') from exc
            identities[resolved_target] = identity
            global_settings['identities'] = identities
            library['global_settings'] = global_settings
        else:
            library, package_info = self._load_package(ui_data, package_id)
            identity_overrides = copy.deepcopy(package_info.get('identity_overrides') or {})
            identity = copy.deepcopy(identity_overrides.get(resolved_target) or {})
            avatars_dir = os.path.join(self.library_root, 'packages', package_info['id'], 'avatars')
            try:
                identity['avatar_file'] = self._copy_asset_to_slot(
                    avatars_dir,
                    resolved_target,
                    source_path,
                    source_name=source_name,
                )['file']
            except ValueError as exc:
                raise ValueError('头像文件无效') from exc
            identity_overrides[resolved_target] = identity
            package_info['identity_overrides'] = identity_overrides
            package_info['updated_at'] = int(time.time())
            library['packages'][package_info['id']] = package_info

        self._save_library(ui_data, library)
        if package_id is None:
            return copy.deepcopy(self._load_library_state(ui_data).get('global_settings', {}).get('identities', {}).get(resolved_target, {}))
        return copy.deepcopy(self._load_library_state(ui_data).get('packages', {}).get(str(package_id).strip(), {}).get('identity_overrides', {}).get(resolved_target, {}))

    def _load_theme_data(self, theme_file: str):
        path = self._resolve_project_relative_path(theme_file)
        if not path or not os.path.exists(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f'读取美化主题失败: {e}')
            return {}


class PathLike:
    @staticmethod
    def basename_without_ext(path: str):
        return os.path.splitext(os.path.basename(path or ''))[0].strip()
