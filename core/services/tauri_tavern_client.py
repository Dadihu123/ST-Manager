"""Client for the TauriTavern native integration API."""

import json
import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests


DEFAULT_TT_USER_HANDLE = 'default-user'
DEFAULT_TT_API_URL = 'http://127.0.0.1:19999'
TAURI_TAVERN_TARGET = 'tauritavern'


def is_tauri_tavern_target(config: Optional[Dict[str, Any]]) -> bool:
    return str((config or {}).get('st_target') or '').strip().lower() == TAURI_TAVERN_TARGET


def normalize_tt_user_handle(handle: Any) -> str:
    value = str(handle or '').strip()
    if not value or value in {'.', '..'} or '/' in value or '\\' in value:
        return DEFAULT_TT_USER_HANDLE
    return value


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
