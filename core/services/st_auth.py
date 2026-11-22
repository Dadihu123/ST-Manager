import logging
from urllib.parse import urljoin

import requests
from requests.auth import HTTPBasicAuth

from core.config import load_config, normalize_config

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/120.0.0.0 Safari/537.36'
)


class STAuthError(Exception):
    """Structured SillyTavern auth/connection error."""

    def __init__(self, stage, message, status_code=None, response_text=''):
        super().__init__(message)
        self.stage = stage
        self.message = message
        self.status_code = status_code
        self.response_text = response_text or ''


class STHTTPClient:
    def __init__(self, config=None, st_url=None, timeout=30):
        self.config = normalize_config(config or load_config())
        self.base_url = (st_url or self.config.get('st_url', 'http://127.0.0.1:8000')).rstrip('/')
        self.timeout = timeout
        self.auth_type = self.config.get('st_auth_type', 'basic')
        self.proxy = (self.config.get('st_proxy', '') or '').strip()
        self.proxies = {
            'http': self.proxy or None,
            'https': self.proxy or None,
        }
        self.basic_username = self.config.get('st_basic_username', '') or ''
        self.basic_password = self.config.get('st_basic_password', '') or ''
        self.web_username = self.config.get('st_web_username', '') or ''
        self.web_password = self.config.get('st_web_password', '') or ''
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': DEFAULT_USER_AGENT})
        if self.uses_basic_auth and (self.basic_username or self.basic_password):
            self.session.auth = HTTPBasicAuth(self.basic_username, self.basic_password)
        self._authenticated = False

    @property
    def uses_basic_auth(self):
        return self.auth_type in ('basic', 'auth_web')

    @property
    def uses_web_login(self):
        return self.auth_type in ('web', 'auth_web')

    def _resolve_url(self, path):
        if path.startswith('http://') or path.startswith('https://'):
            return path
        return urljoin(f'{self.base_url}/', path.lstrip('/'))

    def _sync_csrf_header(self):
        csrf_token = self.session.cookies.get('XSRF-TOKEN')
        if csrf_token:
            self.session.headers.update({'X-XSRF-TOKEN': csrf_token})
        else:
            self.session.headers.pop('X-XSRF-TOKEN', None)

    def _request(self, method, path, timeout=None, **kwargs):
        url = self._resolve_url(path)
        kwargs.setdefault('proxies', self.proxies)
        kwargs.setdefault('timeout', timeout or self.timeout)
        try:
            response = self.session.request(method, url, **kwargs)
        except requests.exceptions.ConnectionError as exc:
            raise STAuthError('connection', '无法连接到 SillyTavern，请确认它已启动。') from exc
        except requests.exceptions.Timeout as exc:
            raise STAuthError('connection', '连接 SillyTavern 超时，请检查地址、代理或服务状态。') from exc

        self._sync_csrf_header()
        return response

    def _warm_up_basic_auth(self):
        response = self._request('GET', self.base_url, timeout=5)
        if response.status_code == 401:
            raise STAuthError(
                'basic_auth',
                'Basic/Auth 认证失败，请检查 Basic/Auth 用户名和密码。',
                status_code=response.status_code,
                response_text=response.text,
            )
        return response

    def _prepare_csrf(self):
        response = self._request('GET', '/csrf-token', timeout=5)
        if response.status_code in (404, 405):
            # Older servers may only provide the XSRF-TOKEN cookie.
            return
        if response.status_code == 200:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            token = payload.get('token') if isinstance(payload, dict) else None
            if isinstance(token, str) and token:
                self.session.headers['X-CSRF-Token'] = token
                return
        raise STAuthError(
            'csrf',
            '无法获取 SillyTavern 的 CSRF 令牌，请检查连接地址、认证设置或 ST 日志。',
            status_code=response.status_code,
        )

    def _perform_web_login(self):
        response = self._request(
            'POST',
            '/api/users/login',
            json={'handle': self.web_username, 'password': self.web_password},
            timeout=5,
        )
        if response.status_code != 200:
            raise STAuthError(
                'web_login',
                'Web 登录失败，请检查 Web 用户名和密码。',
                status_code=response.status_code,
                response_text=response.text,
            )
        return response

    def ensure_authenticated(self):
        if self._authenticated:
            return self

        if self.uses_basic_auth:
            self._warm_up_basic_auth()

        self._prepare_csrf()

        if self.uses_web_login:
            self._perform_web_login()

        self._sync_csrf_header()
        self._authenticated = True
        return self

    def request(self, method, path, authenticate=True, timeout=None, **kwargs):
        if authenticate:
            self.ensure_authenticated()
        return self._request(method, path, timeout=timeout, **kwargs)

    def get(self, path, authenticate=True, timeout=None, **kwargs):
        return self.request('GET', path, authenticate=authenticate, timeout=timeout, **kwargs)

    def post(self, path, authenticate=True, timeout=None, **kwargs):
        return self.request('POST', path, authenticate=authenticate, timeout=timeout, **kwargs)


def build_st_http_client(config=None, st_url=None, timeout=30):
    return STHTTPClient(config=config, st_url=st_url, timeout=timeout)

