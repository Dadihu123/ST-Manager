#!/usr/bin/env python3
"""Remove stale entries from ui_data.json by checking the configured files."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable


if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass


DEFAULT_CONFIG = {
    'cards_dir': 'data/library/characters',
    'world_info_dir': 'data/library/lorebooks',
    'presets_dir': 'data/library/presets',
    'beautify_dir': 'data/library/beautify',
    'resources_dir': 'data/assets/card_assets',
}

RESERVED_RESOURCE_NAMES = {'notes', 'backups', 'lorebooks', 'thumbnails', 'cards', 'trash'}
RESERVED_UI_KEYS = {
    '_beautify_library_v1',
    '_isolated_categories_v1',
    '_resource_item_categories_v1',
    '_shared_wallpaper_library_v1',
    '_tag_management_prefs_v1',
    '_tag_taxonomy_v1',
    '_version_remarks',
    '_worldinfo_notes_v1',
}


def _real_path(path: Path) -> Path:
    return Path(os.path.realpath(os.fspath(path)))


def _runtime_root() -> Path:
    if getattr(sys, 'frozen', False):
        return _real_path(Path(sys.executable).parent)
    return _real_path(Path(__file__).resolve().parent)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([os.fspath(_real_path(path)), os.fspath(_real_path(root))]) == os.fspath(
            _real_path(root)
        )
    except (OSError, ValueError):
        return False


def _configured_path(script_dir: Path, value: Any, fallback: str) -> Path:
    text = str(value or fallback).strip()
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = script_dir / candidate
    return _real_path(candidate)


def _normalized_path_text(value: Any) -> str:
    return str(value or '').strip().replace('\\', '/')


class UiDataCleaner:
    """Validate persisted UI references without deleting user files."""

    def __init__(self, script_dir: Path, config: dict[str, Any]):
        self.project_root = _real_path(script_dir)
        self.cards_root = _configured_path(
            self.project_root, config.get('cards_dir'), DEFAULT_CONFIG['cards_dir']
        )
        self.world_info_root = _configured_path(
            self.project_root,
            config.get('world_info_dir'),
            DEFAULT_CONFIG['world_info_dir'],
        )
        self.presets_root = _configured_path(
            self.project_root, config.get('presets_dir'), DEFAULT_CONFIG['presets_dir']
        )
        self.beautify_root = _configured_path(
            self.project_root, config.get('beautify_dir'), DEFAULT_CONFIG['beautify_dir']
        )
        self.resources_root = _configured_path(
            self.project_root, config.get('resources_dir'), DEFAULT_CONFIG['resources_dir']
        )
        self.stats: dict[str, Any] = {
            'removed_entries': 0,
            'removed_version_remarks': 0,
            'removed_worldinfo_notes': 0,
            'removed_resource_categories': 0,
            'removed_isolated_categories': 0,
            'removed_shared_wallpapers': 0,
            'removed_beautify_assets': 0,
            'removed_beautify_packages': 0,
            'cleared_fields': 0,
            'warnings': [],
        }
        self._warned_missing_roots: set[str] = set()

    def clean(self, ui_data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        self._clean_card_entries(ui_data)
        self._clean_isolated_categories(ui_data)
        self._clean_resource_item_categories(ui_data)
        self._clean_worldinfo_notes(ui_data)
        shared_ids = self._clean_shared_wallpapers(ui_data)
        self._clean_beautify_library(ui_data, shared_ids)
        self.stats['changed'] = self._has_changes()
        return ui_data, self.stats

    def _has_changes(self) -> bool:
        return any(
            self.stats[key] > 0
            for key in (
                'removed_entries',
                'removed_version_remarks',
                'removed_worldinfo_notes',
                'removed_resource_categories',
                'removed_isolated_categories',
                'removed_shared_wallpapers',
                'removed_beautify_assets',
                'removed_beautify_packages',
                'cleared_fields',
            )
        )

    def _warn_missing_root(self, label: str, root: Path) -> None:
        if label in self._warned_missing_roots:
            return
        if root.is_dir():
            return
        self._warned_missing_roots.add(label)
        self.stats['warnings'].append(f'{label} 目录不存在，跳过相关清理: {root}')

    def _resolve_file(
        self,
        value: Any,
        roots: Iterable[Path],
        *,
        allow_external_absolute: bool = False,
    ) -> Path | None:
        text = _normalized_path_text(value)
        if not text:
            return None

        raw_path = Path(text)
        candidates: list[tuple[Path, Path | None]] = []
        if raw_path.is_absolute():
            candidates.extend((raw_path, root) for root in roots)
            if allow_external_absolute:
                candidates.append((raw_path, None))
        else:
            for root in roots:
                candidates.append((root / raw_path, root))
            candidates.append((self.project_root / raw_path, self.project_root))

        for candidate, allowed_root in candidates:
            resolved = _real_path(candidate)
            if not resolved.is_file():
                continue
            if allowed_root is None and allow_external_absolute:
                return resolved
            if allowed_root is not None and _is_inside(resolved, allowed_root):
                return resolved
        return None

    def _resolve_directory(self, value: Any, root: Path) -> Path | None:
        text = _normalized_path_text(value)
        if not text:
            return None
        raw_path = Path(text)
        candidate = raw_path if raw_path.is_absolute() else root / raw_path
        resolved = _real_path(candidate)
        if resolved.is_dir() and _is_inside(resolved, root):
            return resolved
        return None

    def _card_path(self, value: Any) -> Path | None:
        text = _normalized_path_text(value)
        if not text or not self.cards_root.is_dir():
            return None
        return self._resolve_file(text, [self.cards_root])

    def _card_reference_exists(self, value: Any) -> bool:
        text = _normalized_path_text(value)
        if not text or not self.cards_root.is_dir():
            return False
        raw_path = Path(text)
        candidate = raw_path if raw_path.is_absolute() else self.cards_root / raw_path
        resolved = _real_path(candidate)
        if not _is_inside(resolved, self.cards_root):
            return False
        if resolved.is_file():
            return True
        return resolved.is_dir() and (resolved / '.bundle').is_file()

    def _clean_card_entries(self, ui_data: dict[str, Any]) -> None:
        if not self.cards_root.is_dir():
            self._warn_missing_root('角色卡', self.cards_root)
            return

        for raw_key in list(ui_data.keys()):
            if not isinstance(raw_key, str) or raw_key.startswith('_') or raw_key in RESERVED_UI_KEYS:
                continue
            if not self._card_reference_exists(raw_key):
                ui_data.pop(raw_key, None)
                self.stats['removed_entries'] += 1
                continue

            entry = ui_data.get(raw_key)
            if not isinstance(entry, dict):
                ui_data.pop(raw_key, None)
                self.stats['removed_entries'] += 1
                continue
            self._clean_card_entry(entry, raw_key)

    def _clean_card_entry(self, entry: dict[str, Any], card_key: str) -> None:
        resource_folder = _normalized_path_text(entry.get('resource_folder'))
        if resource_folder:
            first_part = resource_folder.split('/', 1)[0].lower()
            invalid_resource_folder = first_part in RESERVED_RESOURCE_NAMES
            if not invalid_resource_folder and self.resources_root.is_dir():
                invalid_resource_folder = self._resolve_directory(
                    resource_folder, self.resources_root
                ) is None
            if invalid_resource_folder:
                entry['resource_folder'] = ''
                self.stats['cleared_fields'] += 1
            elif not self.resources_root.is_dir():
                self._warn_missing_root('角色资源', self.resources_root)

        raw_remarks = entry.get('_version_remarks')
        if not isinstance(raw_remarks, dict):
            if '_version_remarks' in entry:
                entry.pop('_version_remarks', None)
                self.stats['cleared_fields'] += 1
            return

        for version_id in list(raw_remarks.keys()):
            version_exists = self._card_reference_exists(version_id)
            if not version_exists and '/' not in _normalized_path_text(version_id):
                version_exists = self._card_reference_exists(f'{card_key}/{version_id}')
            if not version_exists:
                raw_remarks.pop(version_id, None)
                self.stats['removed_version_remarks'] += 1
                continue
            version_remark = raw_remarks.get(version_id)
            if isinstance(version_remark, dict):
                self._clean_card_entry(version_remark, card_key)

        if not raw_remarks:
            entry.pop('_version_remarks', None)
            self.stats['cleared_fields'] += 1

    def _clean_isolated_categories(self, ui_data: dict[str, Any]) -> None:
        raw = ui_data.get('_isolated_categories_v1')
        if raw is None:
            return
        if not self.cards_root.is_dir():
            self._warn_missing_root('角色卡', self.cards_root)
            return
        if not isinstance(raw, dict):
            ui_data.pop('_isolated_categories_v1', None)
            self.stats['cleared_fields'] += 1
            return

        paths = raw.get('paths')
        if not isinstance(paths, list):
            raw['paths'] = []
            self.stats['cleared_fields'] += 1
            return

        valid_paths = []
        for path in paths:
            if self._resolve_directory(path, self.cards_root):
                valid_paths.append(path)
            else:
                self.stats['removed_isolated_categories'] += 1
        if valid_paths != paths:
            raw['paths'] = valid_paths

    def _clean_resource_item_categories(self, ui_data: dict[str, Any]) -> None:
        raw = ui_data.get('_resource_item_categories_v1')
        if raw is None:
            return
        if not isinstance(raw, dict):
            ui_data.pop('_resource_item_categories_v1', None)
            self.stats['cleared_fields'] += 1
            return

        mode_roots = {
            'worldinfo': [self.world_info_root, self.resources_root],
            'presets': [self.presets_root, self.resources_root],
        }
        for mode, roots in mode_roots.items():
            raw_items = raw.get(mode)
            if raw_items is None:
                continue
            if not isinstance(raw_items, dict):
                raw[mode] = {}
                self.stats['cleared_fields'] += 1
                continue
            if not any(root.is_dir() for root in roots):
                self._warn_missing_root(mode, roots[0])
                continue

            for file_path in list(raw_items.keys()):
                category_info = raw_items.get(file_path)
                is_valid = bool(
                    isinstance(category_info, dict)
                    and str(category_info.get('category') or '').strip()
                    and self._resolve_file(file_path, roots) is not None
                )
                if not is_valid:
                    raw_items.pop(file_path, None)
                    self.stats['removed_resource_categories'] += 1

    def _clean_worldinfo_notes(self, ui_data: dict[str, Any]) -> None:
        raw = ui_data.get('_worldinfo_notes_v1')
        if raw is None:
            return
        if not isinstance(raw, dict):
            ui_data.pop('_worldinfo_notes_v1', None)
            self.stats['cleared_fields'] += 1
            return

        for note_key in list(raw.keys()):
            note = raw.get(note_key)
            try:
                source_type, target = str(note_key).split('::', 1)
            except ValueError:
                source_type, target = '', ''
            target_exists = self._worldinfo_note_target_exists(source_type, target)
            valid_note = isinstance(note, dict) and str(note.get('summary') or '').strip()
            if not target_exists or not valid_note:
                raw.pop(note_key, None)
                self.stats['removed_worldinfo_notes'] += 1

    def _worldinfo_note_target_exists(self, source_type: str, target: str) -> bool:
        if source_type == 'embedded':
            if not self.cards_root.is_dir():
                self._warn_missing_root('角色卡', self.cards_root)
                return True
            return self._card_path(target) is not None
        if source_type == 'global':
            if not self.world_info_root.is_dir():
                self._warn_missing_root('全局世界书', self.world_info_root)
                return True
            return self._resolve_file(target, [self.world_info_root]) is not None
        if source_type == 'resource':
            if not self.resources_root.is_dir():
                self._warn_missing_root('角色资源', self.resources_root)
                return True
            return self._resolve_file(target, [self.resources_root]) is not None
        return False

    def _clean_shared_wallpapers(self, ui_data: dict[str, Any]) -> set[str]:
        raw = ui_data.get('_shared_wallpaper_library_v1')
        if raw is None:
            return set()
        if not isinstance(raw, dict):
            ui_data.pop('_shared_wallpaper_library_v1', None)
            self.stats['cleared_fields'] += 1
            return set()

        raw_items = raw.get('items')
        if not isinstance(raw_items, dict):
            raw['items'] = {}
            self.stats['cleared_fields'] += 1
            raw_items = raw['items']

        valid_ids: set[str] = set()
        for wallpaper_id in list(raw_items.keys()):
            item = raw_items.get(wallpaper_id)
            if not isinstance(item, dict):
                raw_items.pop(wallpaper_id, None)
                self.stats['removed_shared_wallpapers'] += 1
                continue
            source_type = str(item.get('source_type') or '').strip().lower()
            file_exists = self._resolve_file(
                item.get('file'),
                [self.project_root, self.beautify_root],
                allow_external_absolute=True,
            )
            if source_type == 'builtin' and self._builtin_wallpaper_exists(wallpaper_id):
                file_exists = True
            if file_exists is None:
                raw_items.pop(wallpaper_id, None)
                self.stats['removed_shared_wallpapers'] += 1
                continue
            valid_ids.add(str(wallpaper_id))

        for selection_key in ('manager_wallpaper_id', 'preview_wallpaper_id'):
            selected_id = str(raw.get(selection_key) or '').strip()
            if not selected_id:
                continue
            if selected_id.startswith('builtin:') and self._builtin_wallpaper_exists(selected_id):
                continue
            if selected_id not in valid_ids:
                raw[selection_key] = ''
                self.stats['cleared_fields'] += 1

        return valid_ids

    def _builtin_wallpaper_exists(self, wallpaper_id: str) -> bool:
        prefix = 'builtin:'
        if not wallpaper_id.startswith(prefix):
            return False
        relative_name = _normalized_path_text(wallpaper_id[len(prefix) :]).lstrip('/')
        if not relative_name or '..' in Path(relative_name).parts:
            return False
        builtin_root = self.project_root / 'static' / 'assets' / 'wallpapers' / 'builtin'
        candidate = _real_path(builtin_root / relative_name)
        return _is_inside(candidate, builtin_root) and candidate.is_file()

    def _clean_beautify_library(self, ui_data: dict[str, Any], shared_ids: set[str]) -> None:
        raw = ui_data.get('_beautify_library_v1')
        if raw is None:
            return
        if not self.beautify_root.is_dir():
            self._warn_missing_root('美化库', self.beautify_root)
            return
        if not isinstance(raw, dict):
            ui_data.pop('_beautify_library_v1', None)
            self.stats['cleared_fields'] += 1
            return

        global_settings = raw.get('global_settings')
        if isinstance(global_settings, dict):
            self._clean_asset(global_settings.get('wallpaper'))
            identities = global_settings.get('identities')
            self._clean_identities(identities)

        packages = raw.get('packages')
        if not isinstance(packages, dict):
            raw['packages'] = {}
            self.stats['cleared_fields'] += 1
            return

        packages_root = self.beautify_root / 'packages'
        for package_id in list(packages.keys()):
            package = packages.get(package_id)
            package_dir = _real_path(packages_root / str(package_id))
            if not isinstance(package, dict) or not _is_inside(package_dir, packages_root) or not package_dir.is_dir():
                packages.pop(package_id, None)
                self.stats['removed_beautify_packages'] += 1
                continue
            self._clean_beautify_package(package, shared_ids)

    def _clean_beautify_package(self, package: dict[str, Any], shared_ids: set[str]) -> None:
        variants = package.get('variants')
        if isinstance(variants, dict):
            for variant_id in list(variants.keys()):
                variant = variants.get(variant_id)
                if not isinstance(variant, dict) or not self._asset_file_exists(variant.get('theme_file')):
                    variants.pop(variant_id, None)
                    self.stats['removed_beautify_assets'] += 1
                    continue
                wallpaper_ids = variant.get('wallpaper_ids')
                if isinstance(wallpaper_ids, list):
                    valid_wallpaper_ids = [
                        wallpaper_id
                        for wallpaper_id in wallpaper_ids
                        if str(wallpaper_id) in shared_ids
                        or (
                            str(wallpaper_id).startswith('builtin:')
                            and self._builtin_wallpaper_exists(str(wallpaper_id))
                        )
                    ]
                    if valid_wallpaper_ids != wallpaper_ids:
                        variant['wallpaper_ids'] = valid_wallpaper_ids
                        self.stats['cleared_fields'] += 1
                    if variant.get('selected_wallpaper_id') not in valid_wallpaper_ids:
                        if variant.get('selected_wallpaper_id'):
                            variant['selected_wallpaper_id'] = ''
                            self.stats['cleared_fields'] += 1

        wallpapers = package.get('wallpapers')
        if isinstance(wallpapers, dict):
            self._clean_asset_collection(wallpapers)
        screenshots = package.get('screenshots')
        if isinstance(screenshots, dict):
            self._clean_asset_collection(screenshots)
        self._clean_identities(package.get('identity_overrides'))

        if package.get('cover_variant_id') not in (variants or {}):
            if package.get('cover_variant_id'):
                package['cover_variant_id'] = ''
                self.stats['cleared_fields'] += 1

    def _asset_file_exists(self, file_path: Any) -> bool:
        return (
            self._resolve_file(
                file_path,
                [self.project_root, self.beautify_root],
                allow_external_absolute=True,
            )
            is not None
        )

    def _clean_asset(self, asset: Any) -> None:
        if not isinstance(asset, dict) or not asset.get('file'):
            return
        if self._asset_file_exists(asset.get('file')):
            return
        asset['file'] = ''
        for key, empty_value in (('filename', ''), ('width', 0), ('height', 0), ('mtime', 0)):
            if key in asset:
                asset[key] = empty_value
        self.stats['removed_beautify_assets'] += 1

    def _clean_identities(self, identities: Any) -> None:
        if not isinstance(identities, dict):
            return
        for identity in identities.values():
            self._clean_identity(identity)

    def _clean_identity(self, identity: Any) -> None:
        if not isinstance(identity, dict) or not identity.get('avatar_file'):
            return
        if self._asset_file_exists(identity.get('avatar_file')):
            return
        identity['avatar_file'] = ''
        self.stats['removed_beautify_assets'] += 1

    def _clean_asset_collection(self, assets: dict[str, Any]) -> None:
        for asset_id in list(assets.keys()):
            asset = assets.get(asset_id)
            if not isinstance(asset, dict) or not self._asset_file_exists(asset.get('file')):
                assets.pop(asset_id, None)
                self.stats['removed_beautify_assets'] += 1


def _load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return dict(DEFAULT_CONFIG)
    with config_path.open('r', encoding='utf-8') as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError('config.json 根数据必须是对象')
    return config


def _load_ui_data(ui_data_path: Path) -> dict[str, Any]:
    with ui_data_path.open('r', encoding='utf-8') as handle:
        ui_data = json.load(handle)
    if not isinstance(ui_data, dict):
        raise ValueError('ui_data.json 根数据必须是对象')
    return ui_data


def _backup_ui_data(ui_data_path: Path) -> Path:
    backup_path = Path(f'{ui_data_path}.bak')
    shutil.copy2(ui_data_path, backup_path)
    return backup_path


def _write_ui_data_atomic(ui_data_path: Path, ui_data: dict[str, Any]) -> None:
    ui_data_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(
        prefix=f'.{ui_data_path.name}.', suffix='.tmp', dir=ui_data_path.parent
    )
    try:
        with os.fdopen(file_descriptor, 'w', encoding='utf-8') as handle:
            file_descriptor = -1
            json.dump(ui_data, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, ui_data_path)
        temp_name = ''
    finally:
        if file_descriptor >= 0:
            os.close(file_descriptor)
        if temp_name:
            try:
                os.remove(temp_name)
            except OSError:
                pass


def clean_ui_data_file(
    *,
    config_path: Path | None = None,
    ui_data_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    script_dir = _runtime_root()
    resolved_config_path = _real_path(config_path or script_dir / 'config.json')
    resolved_ui_data_path = _real_path(
        ui_data_path or script_dir / 'data' / 'system' / 'db' / 'ui_data.json'
    )
    config = _load_config(resolved_config_path)
    original = _load_ui_data(resolved_ui_data_path)
    cleaner = UiDataCleaner(script_dir, config)
    cleaned, stats = cleaner.clean(original)

    backup_path = None
    if not dry_run:
        backup_path = _backup_ui_data(resolved_ui_data_path)
        if stats['changed']:
            _write_ui_data_atomic(resolved_ui_data_path, cleaned)

    stats.update(
        {
            'dry_run': dry_run,
            'config_path': str(resolved_config_path),
            'ui_data_path': str(resolved_ui_data_path),
            'backup_path': str(backup_path) if backup_path else '',
        }
    )
    return stats


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='扫描磁盘并清理无效的 ui_data.json 引用')
    parser.add_argument('--config', type=Path, help='配置文件路径，默认使用脚本同级 config.json')
    parser.add_argument('--ui-data', type=Path, help='ui_data.json 路径，默认使用 data/system/db/ui_data.json')
    parser.add_argument('--dry-run', action='store_true', help='只扫描和报告，不备份、不写回')
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        stats = clean_ui_data_file(
            config_path=args.config,
            ui_data_path=args.ui_data,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f'清理失败: {exc}')
        return 1

    action = '扫描完成，未发现需要清理的内容' if not stats['changed'] else '清理完成'
    if stats['dry_run']:
        action += '（预览模式）'
    print(action)
    print(
        '删除条目: {removed_entries}, 版本备注: {removed_version_remarks}, '
        '世界书备注: {removed_worldinfo_notes}, 资源分类: {removed_resource_categories}, '
        '共享壁纸: {removed_shared_wallpapers}, 美化资源: {removed_beautify_assets}'.format(
            **stats
        )
    )
    if stats.get('backup_path'):
        print(f'备份文件: {stats["backup_path"]}')
    for warning in stats.get('warnings', []):
        print(f'警告: {warning}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
