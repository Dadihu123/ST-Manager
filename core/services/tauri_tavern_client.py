"""Clients for sending resources to TauriTavern.

TauriTavern 提供两种接收外部资源的方式：

- ``TauriTavernLocalClient``（默认，``tt_mode = 'local'``）
  直接写入 TauriTavern 的数据目录。它的用户数据布局与 SillyTavern 完全一致
  （``characters`` / ``worlds`` / ``OpenAI Settings`` / ``themes``），且各仓储
  每次读取都会重新扫描目录并按文件签名校验缓存，因此外部写入的文件会被识别。
- ``TauriTavernClient``（``tt_mode = 'api'``）
  调用 TauriTavern 的原生集成 API（``127.0.0.1:19999``）。该接口目前只存在于
  TauriTavern 尚未发布的开发分支，官方发行版不包含，默认不启用。
"""

import json
import os
import shutil
import tempfile
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from core.utils.filesystem import sanitize_filename


DEFAULT_TT_USER_HANDLE = 'default-user'
DEFAULT_TT_API_URL = 'http://127.0.0.1:19999'
TAURI_TAVERN_TARGET = 'tauritavern'
TT_MODE_LOCAL = 'local'
TT_MODE_API = 'api'

# TauriTavern 用户目录内的资源子目录，与 SillyTavern 保持一致。
TT_RESOURCE_DIRECTORIES = {
    'characters': 'characters',
    'worlds': 'worlds',
    'presets': 'OpenAI Settings',
    'themes': 'themes',
}


def is_tauri_tavern_target(config: Optional[Dict[str, Any]]) -> bool:
    return str((config or {}).get('st_target') or '').strip().lower() == TAURI_TAVERN_TARGET


def normalize_tt_mode(mode: Any) -> str:
    value = str(mode or '').strip().lower()
    return value if value in {TT_MODE_LOCAL, TT_MODE_API} else TT_MODE_LOCAL


def normalize_tt_user_handle(handle: Any) -> str:
    value = str(handle or '').strip()
    if not value or value in {'.', '..'} or '/' in value or '\\' in value:
        return DEFAULT_TT_USER_HANDLE
    return value


def normalize_tauri_data_root(data_root: Any) -> str:
    """把用户选择的路径规范化为「包含用户目录的数据根目录」。

    允许直接选择 ``<root>/default-user``，此时自动回退到其父目录。
    """
    value = str(data_root or '').strip().strip('"').strip("'")
    if not value:
        return ''
    normalized = os.path.abspath(os.path.normpath(os.path.expanduser(value)))
    if os.path.basename(normalized).lower() == DEFAULT_TT_USER_HANDLE:
        return os.path.dirname(normalized)
    return normalized


def normalize_tt_api_url(api_url: Any) -> str:
    value = str(api_url or '').strip().strip('"').strip("'")
    if not value:
        return ''
    parsed = urlparse(value)
    if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
        raise ValueError('TauriTavern 集成 API 地址必须是 http:// 或 https:// 地址')
    if parsed.username or parsed.password:
        raise ValueError('TauriTavern 集成 API 地址不能包含用户名或密码')
    return value.rstrip('/')


class TauriTavernLocalClient:
    """Write SillyTavern-compatible resources into a TauriTavern data directory."""

    def __init__(
        self,
        data_root: Any = '',
        user_handle: Any = DEFAULT_TT_USER_HANDLE,
    ):
        raw_handle = str(user_handle or '').strip()
        if raw_handle and normalize_tt_user_handle(raw_handle) != raw_handle:
            raise ValueError('TauriTavern 用户目录名不合法')
        self.user_handle = normalize_tt_user_handle(user_handle)
        self.data_root = normalize_tauri_data_root(data_root)

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        return cls(
            data_root=cfg.get('tt_data_dir') or '',
            user_handle=cfg.get('tt_user_handle', DEFAULT_TT_USER_HANDLE),
        )

    @property
    def user_dir(self) -> str:
        if not self.data_root:
            return ''
        return os.path.join(self.data_root, self.user_handle)

    def resource_dir(self, resource_type: str) -> str:
        directory_name = TT_RESOURCE_DIRECTORIES.get(resource_type)
        if not directory_name or not self.user_dir:
            return ''
        return os.path.join(self.user_dir, directory_name)

    def validate(self) -> Dict[str, Any]:
        """校验数据目录是否可用，供「测试连接」使用。"""
        root_exists = bool(self.data_root and os.path.isdir(self.data_root))
        user_dir_exists = bool(self.user_dir and os.path.isdir(self.user_dir))
        valid = root_exists and user_dir_exists
        if valid:
            message = 'TauriTavern 数据目录有效'
        elif not root_exists:
            message = '数据根目录不存在，请选择其下包含用户目录的 TauriTavern 数据目录'
        else:
            message = f'未找到用户目录: {self.user_handle}'

        resources = {}
        for resource_type in TT_RESOURCE_DIRECTORIES:
            directory = self.resource_dir(resource_type)
            resources[resource_type] = {
                'path': directory,
                'exists': bool(directory and os.path.isdir(directory)),
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
        if not directory:
            raise ValueError(f'不支持的资源类型: {resource_type}')
        os.makedirs(directory, exist_ok=True)

        safe_name = sanitize_filename(os.path.basename(str(filename or '')))
        if not safe_name or safe_name in {'.', '..'}:
            raise ValueError('目标文件名不合法')

        target = os.path.abspath(os.path.join(directory, safe_name))
        try:
            inside = os.path.commonpath([target, os.path.abspath(directory)])
        except ValueError as error:
            raise ValueError('目标文件路径不合法') from error
        if inside != os.path.abspath(directory):
            raise ValueError('目标文件路径不合法')
        return target

    @staticmethod
    def _require_source(source_path: str):
        if not source_path or not os.path.isfile(source_path):
            raise ValueError('源文件不存在')

    @staticmethod
    def _write_bytes_atomic(target: str, payload: bytes):
        fd, temp_path = tempfile.mkstemp(
            prefix='.st-manager-',
            suffix='.tmp',
            dir=os.path.dirname(target),
        )
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(payload)
            os.replace(temp_path, target)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def _write_json_atomic(self, target: str, payload: Dict[str, Any]):
        self._write_bytes_atomic(
            target,
            (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8'),
        )

    def send_character(self, source_path: str) -> Dict[str, str]:
        extension = os.path.splitext(source_path)[1].lower()
        if extension not in {'.png', '.json'}:
            raise ValueError('TauriTavern 仅支持 PNG 或 JSON 角色卡')

        self._require_source(source_path)
        target = self._target_path('characters', os.path.basename(source_path))
        shutil.copy2(source_path, target)
        return {'path': target, 'filename': os.path.basename(target)}

    def send_world_info(self, source_path: str, payload_bytes: bytes) -> Dict[str, str]:
        self._require_source(source_path)
        if not isinstance(payload_bytes, (bytes, bytearray)):
            raise ValueError('世界书内容无效')

        filename = os.path.splitext(os.path.basename(source_path))[0] + '.json'
        target = self._target_path('worlds', filename)
        self._write_bytes_atomic(target, bytes(payload_bytes))
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
        settings: Dict[str, Any] = {}
        if os.path.isfile(settings_path):
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
        filename_stem = preset_name or os.path.splitext(os.path.basename(source_path))[0]
        target = self._target_path('presets', f'{filename_stem}.json')
        self._write_json_atomic(target, preset_data)
        return {'path': target, 'filename': os.path.basename(target)}


def build_tauri_tavern_client(config: Optional[Dict[str, Any]] = None):
    """按配置返回本地目录客户端或原生 API 客户端。"""
    cfg = config or {}
    if normalize_tt_mode(cfg.get('tt_mode')) == TT_MODE_API:
        return TauriTavernClient.from_config(cfg)
    return TauriTavernLocalClient.from_config(cfg)


class TauriTavernClient:
    """Send compatible resources through TauriTavern's native integration API."""

    def __init__(
        self,
        api_url: Any = DEFAULT_TT_API_URL,
        user_handle: Any = DEFAULT_TT_USER_HANDLE,
        timeout: float = 15,
    ):
        raw_handle = str(user_handle or '').strip()
        if raw_handle and normalize_tt_user_handle(raw_handle) != raw_handle:
            raise ValueError('TauriTavern 用户 handle 不合法')
        self.user_handle = normalize_tt_user_handle(user_handle)
        self.api_url = normalize_tt_api_url(api_url)
        self.timeout = max(float(timeout), 1.0)

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        return cls(
            api_url=cfg.get('tt_api_url') or DEFAULT_TT_API_URL,
            user_handle=cfg.get('tt_user_handle', DEFAULT_TT_USER_HANDLE),
        )

    def _api_request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        if not self.api_url:
            raise ValueError('未配置 TauriTavern 集成 API 地址')

        url = f'{self.api_url}/{path.lstrip("/")}'
        request_kwargs = dict(kwargs)
        request_kwargs.setdefault('timeout', self.timeout)
        request_kwargs.setdefault('headers', {})
        request_kwargs['headers'] = {
            'Accept': 'application/json',
            **request_kwargs['headers'],
        }

        session = requests.Session()
        session.trust_env = False
        try:
            response = session.request(method.upper(), url, **request_kwargs)
        except requests.RequestException as error:
            raise ValueError(f'无法连接 TauriTavern 集成 API: {error}') from error

        payload: Any = None
        try:
            payload = response.json()
        except (ValueError, TypeError):
            payload = {}

        if response.status_code >= 400:
            message = payload.get('error') if isinstance(payload, dict) else None
            if isinstance(payload, dict):
                message = message or payload.get('message')
            message = message or response.text or f'HTTP {response.status_code}'
            raise ValueError(f'TauriTavern 集成 API 请求失败: {message}')
        if not isinstance(payload, dict):
            raise ValueError('TauriTavern 集成 API 返回格式无效')
        if payload.get('success') is False:
            raise ValueError(str(payload.get('error') or payload.get('message') or 'TauriTavern 导入失败'))
        return payload

    def check_connection(self) -> Dict[str, Any]:
        """Check the API and the configured TauriTavern user directory."""
        return self._api_request(
            'GET',
            '/api/st-manager/v1/status',
            params={'user_handle': self.user_handle},
        )

    @staticmethod
    def _require_source(source_path: str):
        if not source_path or not os.path.isfile(source_path):
            raise ValueError('源文件不存在')

    def send_character(self, source_path: str) -> Dict[str, str]:
        extension = os.path.splitext(source_path)[1].lower()
        if extension not in {'.png', '.json'}:
            raise ValueError('TauriTavern 仅支持 PNG 或 JSON 角色卡')

        self._require_source(source_path)
        mime = 'image/png' if extension == '.png' else 'application/json'
        with open(source_path, 'rb') as handle:
            result = self._api_request(
                'POST',
                '/api/st-manager/v1/characters/import',
                files={'file': (os.path.basename(source_path), handle, mime)},
                data={
                    'user_handle': self.user_handle,
                    'preserve_file_name': (
                        os.path.basename(source_path) if extension == '.png' else ''
                    ),
                },
            )
        return {
            'path': str(result.get('path') or ''),
            'filename': str(result.get('filename') or os.path.basename(source_path)),
        }

    def send_world_info(self, source_path: str, payload_bytes: bytes) -> Dict[str, str]:
        self._require_source(source_path)
        if not isinstance(payload_bytes, (bytes, bytearray)):
            raise ValueError('世界书内容无效')

        try:
            payload = json.loads(bytes(payload_bytes).decode('utf-8'))
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError(f'世界书内容不是有效 JSON: {error}') from error
        if not isinstance(payload, dict):
            raise ValueError('世界书内容必须是 JSON 对象')

        name = os.path.splitext(os.path.basename(source_path))[0]
        result = self._api_request(
            'POST',
            '/api/st-manager/v1/worlds/import',
            json={'user_handle': self.user_handle, 'name': name, 'data': payload},
        )
        return {
            'path': str(result.get('path') or ''),
            'filename': str(result.get('filename') or f'{name}.json'),
        }

    def send_theme(self, theme_data: Dict[str, Any]) -> Dict[str, str]:
        if not isinstance(theme_data, dict):
            raise ValueError('主题内容无效')
        theme_name = str(theme_data.get('name') or '').strip()
        if not theme_name:
            raise ValueError('主题缺少 name 字段')

        result = self._api_request(
            'POST',
            '/api/st-manager/v1/themes/import',
            json={
                'user_handle': self.user_handle,
                'name': theme_name,
                'data': dict(theme_data),
            },
        )
        return {
            'path': str(result.get('path') or ''),
            'settings_path': str(result.get('settings_path') or ''),
            'filename': str(result.get('filename') or f'{theme_name}.json'),
        }

    def send_preset(self, source_path: str, preset_data: Dict[str, Any]) -> Dict[str, str]:
        self._require_source(source_path)
        if not isinstance(preset_data, dict):
            raise ValueError('预设内容无效')

        preset_name = str(preset_data.get('name') or preset_data.get('title') or '').strip()
        filename_stem = preset_name or os.path.splitext(os.path.basename(source_path))[0]
        result = self._api_request(
            'POST',
            '/api/st-manager/v1/presets/import',
            json={
                'user_handle': self.user_handle,
                'api_id': 'openai',
                'name': filename_stem,
                'preset': preset_data,
            },
        )
        return {
            'path': str(result.get('path') or ''),
            'filename': str(result.get('filename') or f'{filename_stem}.json'),
        }
