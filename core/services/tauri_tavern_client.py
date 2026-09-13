"""TauriTavern local data-directory integration.

TauriTavern's SillyTavern-compatible routes are intercepted inside its own
WebView, so an external manager cannot call them over HTTP.  This adapter
writes the compatible user-data files directly instead.
"""

import json
import os
import shutil
import tempfile
from typing import Any, Dict, Optional

from core.utils.filesystem import sanitize_filename


DEFAULT_TT_USER_HANDLE = 'default-user'
TAURI_TAVERN_TARGET = 'tauritavern'
SUPPORTED_TAURI_RESOURCE_TYPES = {'characters', 'worlds', 'presets', 'themes'}


def is_tauri_tavern_target(config: Optional[Dict[str, Any]]) -> bool:
    return str((config or {}).get('st_target') or '').strip().lower() == TAURI_TAVERN_TARGET


def normalize_tt_user_handle(handle: Any) -> str:
    value = str(handle or '').strip()
    if not value or value in {'.', '..'} or '/' in value or '\\' in value:
        return DEFAULT_TT_USER_HANDLE
    return value


def normalize_tauri_data_root(data_root: Any) -> str:
    value = str(data_root or '').strip().strip('"').strip("'")
    if not value:
        return ''
    normalized = os.path.abspath(os.path.normpath(os.path.expanduser(value)))
    if os.path.basename(normalized).lower() == DEFAULT_TT_USER_HANDLE:
        return os.path.dirname(normalized)
    return normalized


class TauriTavernClient:
    """Copy SillyTavern-compatible resources into a TauriTavern user dir."""

    def __init__(self, data_root: Any = '', user_handle: Any = DEFAULT_TT_USER_HANDLE):
        self.data_root = normalize_tauri_data_root(data_root)
        raw_handle = str(user_handle or '').strip()
        if raw_handle and normalize_tt_user_handle(raw_handle) != raw_handle:
            raise ValueError('TauriTavern 用户目录名不合法')
        self.user_handle = normalize_tt_user_handle(user_handle)

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        return cls(cfg.get('tt_data_dir', ''), cfg.get('tt_user_handle', DEFAULT_TT_USER_HANDLE))

    @property
    def user_dir(self) -> str:
        if not self.data_root:
            return ''
        return os.path.join(self.data_root, self.user_handle)

    def resource_dir(self, resource_type: str) -> str:
        directories = {
            'characters': 'characters',
            'worlds': 'worlds',
            'presets': 'OpenAI Settings',
            'themes': 'themes',
        }
        directory_name = directories.get(resource_type)
        if not directory_name or not self.user_dir:
            return ''
        return os.path.join(self.user_dir, directory_name)

    def validate(self) -> Dict[str, Any]:
        root_exists = bool(self.data_root and os.path.isdir(self.data_root))
        user_dir_exists = bool(self.user_dir and os.path.isdir(self.user_dir))
        valid = root_exists and user_dir_exists
        if valid:
            message = 'TauriTavern 数据目录有效'
        elif not root_exists:
            message = '数据根目录不存在，请选择包含用户目录的 TauriTavern 数据目录'
        else:
            message = f'未找到用户目录: {self.user_handle}'

        resources = {
            resource_type: {
                'path': self.resource_dir(resource_type),
                'exists': os.path.isdir(self.resource_dir(resource_type)),
            }
            for resource_type in ('characters', 'worlds', 'presets', 'themes')
        }
        return {
            'valid': valid,
            'message': message,
            'normalized_path': self.data_root,
            'user_handle': self.user_handle,
            'user_dir': self.user_dir,
            'resources': resources,
        }

    def _require_layout(self):
        result = self.validate()
        if not result['valid']:
            raise ValueError(result['message'])

    def _target_path(self, resource_type: str, filename: str) -> str:
        self._require_layout()
        directory = self.resource_dir(resource_type)
        os.makedirs(directory, exist_ok=True)
        safe_name = sanitize_filename(os.path.basename(str(filename or '')))
        if not safe_name or safe_name in {'.', '..'}:
            raise ValueError('目标文件名不合法')
        target = os.path.abspath(os.path.join(directory, safe_name))
        try:
            if os.path.commonpath([target, os.path.abspath(directory)]) != os.path.abspath(directory):
                raise ValueError('目标文件路径不合法')
        except ValueError:
            raise ValueError('目标文件路径不合法')
        return target

    @staticmethod
    def _require_source(source_path: str):
        if not source_path or not os.path.isfile(source_path):
            raise ValueError('源文件不存在')

    def _copy_file(self, source_path: str, resource_type: str, filename: str = '') -> str:
        self._require_source(source_path)
        target = self._target_path(resource_type, filename or os.path.basename(source_path))
        shutil.copy2(source_path, target)
        return target

    def send_character(self, source_path: str) -> Dict[str, str]:
        extension = os.path.splitext(source_path)[1].lower()
        if extension not in {'.png', '.json'}:
            raise ValueError('TauriTavern 仅支持 PNG 或 JSON 角色卡')
        target = self._copy_file(source_path, 'characters')
        return {'path': target, 'filename': os.path.basename(target)}

    def send_world_info(self, source_path: str, payload_bytes: bytes) -> Dict[str, str]:
        self._require_source(source_path)
        if not isinstance(payload_bytes, (bytes, bytearray)):
            raise ValueError('世界书内容无效')
        filename = os.path.splitext(os.path.basename(source_path))[0] + '.json'
        target = self._target_path('worlds', filename)
        fd, temp_path = tempfile.mkstemp(prefix='.st-manager-', suffix='.json', dir=os.path.dirname(target))
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(bytes(payload_bytes))
            os.replace(temp_path, target)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        return {'path': target, 'filename': os.path.basename(target)}

    def send_theme(self, theme_data: Dict[str, Any]) -> Dict[str, str]:
        if not isinstance(theme_data, dict):
            raise ValueError('主题内容无效')
        theme_name = str(theme_data.get('name') or '').strip()
        if not theme_name:
            raise ValueError('主题缺少 name 字段')

        target = self._target_path('themes', f'{theme_name}.json')
        payload = dict(theme_data)
        payload['name'] = theme_name
        self._write_json_atomic(target, payload)

        settings_path = os.path.join(self.user_dir, 'settings.json')
        settings = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as handle:
                    settings = json.load(handle)
            except (OSError, ValueError) as error:
                raise ValueError(f'TauriTavern 用户设置无法读取: {error}') from error
            if not isinstance(settings, dict):
                raise ValueError('TauriTavern 用户设置格式无效')

        power_user = settings.get('power_user')
        if not isinstance(power_user, dict):
            power_user = {}
        power_user['theme'] = theme_name
        settings['power_user'] = power_user
        self._write_json_atomic(settings_path, settings)
        return {
            'path': target,
            'settings_path': settings_path,
            'filename': os.path.basename(target),
        }

    def send_preset(self, source_path: str, preset_data: Dict[str, Any]) -> Dict[str, str]:
        self._require_source(source_path)
        if not isinstance(preset_data, dict):
            raise ValueError('预设内容无效')
        preset_name = str(preset_data.get('name') or preset_data.get('title') or '').strip()
        filename = (preset_name or os.path.splitext(os.path.basename(source_path))[0]) + '.json'
        target = self._target_path('presets', filename)
        fd, temp_path = tempfile.mkstemp(prefix='.st-manager-', suffix='.json', dir=os.path.dirname(target))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(preset_data, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
            os.replace(temp_path, target)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        return {'path': target, 'filename': os.path.basename(target)}

    @staticmethod
    def _write_json_atomic(target: str, payload: Dict[str, Any]):
        fd, temp_path = tempfile.mkstemp(
            prefix='.st-manager-',
            suffix='.json',
            dir=os.path.dirname(target),
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
            os.replace(temp_path, target)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
