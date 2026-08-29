"""
core/auth.py
外网访问身份验证模块

功能:
- 使用白名单机制（IP/域名）控制免登录访问
- 默认仅允许 127.0.0.1 (本机) 免登录
- 用户可自定义添加信任的 IP、IP 段或域名到白名单
- 不在白名单内的访问需要账号密码验证
"""

import os
import secrets
import hashlib
import logging
import ipaddress
import time
import threading
import socket
from functools import wraps
from flask import request, session, redirect, url_for, render_template_string, jsonify

from core.config import load_config

logger = logging.getLogger(__name__)

# 默认白名单（仅本机）
DEFAULT_TRUSTED_IPS = ['127.0.0.1', '::1']
# 默认受信任代理（仅本机）
DEFAULT_TRUSTED_PROXIES = ['127.0.0.1', '::1']

# 域名解析缓存（用于白名单域名匹配）
_DOMAIN_CACHE_LOCK = threading.Lock()
_DOMAIN_IP_CACHE = {}

# 登录失败限流（内存态）
_RATE_LIMIT_LOCK = threading.Lock()
_FAILED_LOGINS = {}
_LOCKED_UNTIL = {}
_HARD_LOCKED = False
_HARD_LOCKED_AT = 0.0
_GLOBAL_FAIL_COUNT = 0
_GLOBAL_FAIL_LAST_TS = 0.0


def _strip_port(ip):
    """
    去除 IP 中可能包含的端口信息
    支持格式:
    - "1.2.3.4:5678"
    - "[::1]:5678"
    """
    if not ip:
        return ''

    ip = ip.strip()

    # IPv6 with brackets: [::1]:1234
    if ip.startswith('[') and ']' in ip:
        return ip[1:ip.index(']')].strip()

    # IPv4 with port: 1.2.3.4:5678
    if ':' in ip and ip.count(':') == 1 and '.' in ip:
        return ip.split(':', 1)[0].strip()

    return ip


def _normalize_host(host):
    """
    规范化 Host（去端口/去 IPv6 方括号）
    """
    if not host:
        return ''

    host = host.strip()

    # IPv6 with brackets: [::1]:1234
    if host.startswith('[') and ']' in host:
        host = host[1:host.index(']')].strip()
    else:
        # IPv4/hostname with port
        if ':' in host:
            host = host.split(':', 1)[0].strip()

    return host.lower()


def _is_local_host(host):
    """
    判断 Host 是否为本机访问
    """
    normalized = _normalize_host(host)
    return normalized in ('localhost', '127.0.0.1', '::1')




def get_trusted_proxies():
    """
    获取受信任代理列表
    仅当请求来自这些代理时，才会信任 X-Forwarded-For / X-Real-IP
    """
    cfg = load_config()
    user_proxies = cfg.get('auth_trusted_proxies', [])
    return DEFAULT_TRUSTED_PROXIES + list(user_proxies)


def _get_rate_limit_config():
    cfg = load_config()
    try:
        max_attempts = int(cfg.get('auth_max_attempts', 5))
    except Exception:
        max_attempts = 5
    try:
        window = int(cfg.get('auth_fail_window_seconds', 600))
    except Exception:
        window = 600
    try:
        lockout = int(cfg.get('auth_lockout_seconds', 900))
    except Exception:
        lockout = 900

    # 合理范围限制
    max_attempts = max(3, min(max_attempts, 20))
    window = max(60, min(window, 3600))
    lockout = max(60, min(lockout, 7200))

    return max_attempts, window, lockout


def _get_hard_lock_threshold():
    cfg = load_config()
    try:
        threshold = int(cfg.get('auth_hard_lock_threshold', 50))
    except Exception:
        threshold = 50
    # 20 ~ 500
    threshold = max(20, min(threshold, 500))
    return threshold


def _get_rate_limit_key():
    ip = get_real_ip() or request.remote_addr or ''
    ip = _strip_port(ip)
    if ip == 'localhost':
        ip = '127.0.0.1'
    return ip if ip else 'unknown'


def _cleanup_rate_limit_state(now_ts, window_seconds):
    # 清理过期记录，避免内存增长
    stale_keys = []
    for key, data in _FAILED_LOGINS.items():
        if now_ts - data.get('last_ts', now_ts) > window_seconds:
            stale_keys.append(key)
    for key in stale_keys:
        _FAILED_LOGINS.pop(key, None)

    expired_locks = [k for k, v in _LOCKED_UNTIL.items() if v <= now_ts]
    for key in expired_locks:
        _LOCKED_UNTIL.pop(key, None)


def _check_lockout(key, now_ts):
    locked_until = _LOCKED_UNTIL.get(key)
    if locked_until and locked_until > now_ts:
        return True, max(1, int(locked_until - now_ts))
    if locked_until and locked_until <= now_ts:
        _LOCKED_UNTIL.pop(key, None)
    return False, 0


def _record_failed_login(key, now_ts, max_attempts, window_seconds, lockout_seconds):
    data = _FAILED_LOGINS.get(key)
    if not data or now_ts - data.get('first_ts', now_ts) > window_seconds:
        data = {'count': 1, 'first_ts': now_ts, 'last_ts': now_ts}
    else:
        data['count'] = data.get('count', 0) + 1
        data['last_ts'] = now_ts
    _FAILED_LOGINS[key] = data

    if data['count'] >= max_attempts:
        _LOCKED_UNTIL[key] = now_ts + lockout_seconds
        return True
    return False


def _reset_failed_logins(key):
    _FAILED_LOGINS.pop(key, None)
    _LOCKED_UNTIL.pop(key, None)


def _reset_global_failures():
    global _GLOBAL_FAIL_COUNT, _GLOBAL_FAIL_LAST_TS
    _GLOBAL_FAIL_COUNT = 0
    _GLOBAL_FAIL_LAST_TS = 0.0


def _is_hard_locked():
    return _HARD_LOCKED


def _parse_x_forwarded_for(xff_value):
    """
    解析 X-Forwarded-For，返回合法 IP 列表（按顺序）
    """
    if not xff_value:
        return []

    parts = [p.strip() for p in xff_value.split(',') if p.strip()]
    ips = []
    for part in parts:
        ip = _strip_port(part)
        if ip == 'localhost':
            ip = '127.0.0.1'
        try:
            ipaddress.ip_address(ip)
            ips.append(ip)
        except ValueError:
            continue
    return ips


def _get_client_ip_from_xff(xff_value, trusted_proxies, remote_addr):
    """
    从 X-Forwarded-For 链中提取真实客户端 IP
    逻辑:
    - 解析 XFF 为列表
    - 追加 remote_addr 作为最后一跳（如未包含）
    - 从右向左跳过受信任代理，取第一个非代理 IP
    """
    xff_ips = _parse_x_forwarded_for(xff_value)

    if remote_addr:
        try:
            ipaddress.ip_address(remote_addr)
            if not xff_ips or xff_ips[-1] != remote_addr:
                xff_ips.append(remote_addr)
        except ValueError:
            pass

    # 从右向左跳过受信任代理
    for ip in reversed(xff_ips):
        if not is_ip_in_whitelist(ip, trusted_proxies):
            return ip

    # 全部都是代理，兜底返回最左边或 remote_addr
    if xff_ips:
        return xff_ips[0]
    return remote_addr or ''


def get_real_ip():
    """
    获取真实客户端 IP，考虑反向代理情况
    仅当请求来自受信任代理时才信任 X-Forwarded-For / X-Real-IP
    """
    remote_addr = _strip_port(request.remote_addr or '')
    if remote_addr == 'localhost':
        remote_addr = '127.0.0.1'

    trusted_proxies = get_trusted_proxies()
    is_proxy = bool(remote_addr and is_ip_in_whitelist(remote_addr, trusted_proxies))
    has_forwarded = bool(request.headers.get('X-Forwarded-For') or request.headers.get('X-Real-IP'))
    local_host = _is_local_host(request.host)

    if is_proxy:
        # 仅在受信任代理下使用转发头
        forwarded_for = request.headers.get('X-Forwarded-For')
        if forwarded_for:
            client_ip = _get_client_ip_from_xff(forwarded_for, trusted_proxies, remote_addr)
            if client_ip:
                # 反向代理场景下不信任 loopback 作为真实客户端（避免外网穿透绕过）
                if is_ip_in_whitelist(client_ip, DEFAULT_TRUSTED_IPS):
                    return ''
                return client_ip

        real_ip = request.headers.get('X-Real-IP')
        if real_ip:
            real_ip = _strip_port(real_ip.strip())
            if real_ip:
                if is_ip_in_whitelist(real_ip, DEFAULT_TRUSTED_IPS):
                    return ''
                return real_ip

        # 代理请求但未携带转发头：
        # - 若 Host 非本机，则视为外网，不允许回退到本机 IP
        # - 若 Host 为本机，允许回退（本机访问）
        if (has_forwarded or not is_ip_in_whitelist(remote_addr, DEFAULT_TRUSTED_IPS)) or not local_host:
            return ''

    return remote_addr or ''


def get_trusted_ips():
    """
    获取信任的白名单列表（IP/CIDR/通配符/域名）
    格式支持：
    - 单个 IP: "192.168.1.100"
    - IP 段 (CIDR): "192.168.1.0/24"
    - 通配符: "192.168.1.*" (会转换为 CIDR)
    - 域名: "your-ddns.example.com"
    """
    cfg = load_config()
    user_whitelist = cfg.get('auth_trusted_ips', [])

    # 合并默认白名单和用户白名单
    return DEFAULT_TRUSTED_IPS + list(user_whitelist)


def normalize_ip_pattern(pattern):
    """
    标准化 IP 模式，将通配符格式转换为 CIDR
    例如: "192.168.1.*" -> "192.168.1.0/24"
         "192.168.*.*" -> "192.168.0.0/16"
    """
    pattern = pattern.strip()

    # 处理通配符格式
    if '*' in pattern:
        parts = pattern.split('.')
        cidr_bits = 0
        normalized_parts = []

        for part in parts:
            if part == '*':
                normalized_parts.append('0')
            else:
                normalized_parts.append(part)
                cidr_bits += 8

        if len(normalized_parts) == 4:
            return f"{'.'.join(normalized_parts)}/{cidr_bits}"

    return pattern


def _get_domain_cache_ttl_seconds():
    """
    获取域名解析缓存时间（秒）
    """
    cfg = load_config()
    try:
        ttl = int(cfg.get('auth_domain_cache_seconds', 60))
    except Exception:
        ttl = 60
    return max(10, min(ttl, 3600))


def _normalize_domain_pattern(pattern):
    """
    标准化白名单中的域名配置。
    支持:
    - domain.tld
    - domain.tld:port
    - http(s)://domain.tld[:port]/path
    """
    if not pattern or not isinstance(pattern, str):
        return ''

    candidate = pattern.strip()
    if not candidate:
        return ''

    # 去掉 URL 的 scheme/path/query/fragment
    if '://' in candidate:
        candidate = candidate.split('://', 1)[1]
    candidate = candidate.split('/', 1)[0].split('?', 1)[0].split('#', 1)[0]
    candidate = _normalize_host(candidate).rstrip('.')
    if not candidate:
        return ''

    # 本机别名，走既有逻辑
    if candidate == 'localhost':
        return 'localhost'

    # 不支持域名通配符，避免歧义
    if '*' in candidate:
        return ''

    # 排除纯数字/点（通常是 IP），域名必须包含至少一个字母
    if '.' not in candidate or not any(ch.isalpha() for ch in candidate):
        return ''

    # 基础合法性检查（兼容 punycode）
    allowed_chars = set('abcdefghijklmnopqrstuvwxyz0123456789-.')
    if any(ch not in allowed_chars for ch in candidate):
        return ''

    labels = candidate.split('.')
    if any(not label for label in labels):
        return ''
    if any(label.startswith('-') or label.endswith('-') for label in labels):
        return ''

    return candidate


def _resolve_domain_ips(domain):
    """
    解析域名并返回 IP 集合（支持 IPv4/IPv6）。
    结果会按 TTL 缓存，避免每次请求都进行 DNS 查询。
    """
    now_ts = time.time()
    ttl_seconds = _get_domain_cache_ttl_seconds()

    with _DOMAIN_CACHE_LOCK:
        cached = _DOMAIN_IP_CACHE.get(domain)
        if cached and cached.get('expires_at', 0) > now_ts:
            return set(cached.get('ips', []))

    resolved_ips = set()
    try:
        infos = socket.getaddrinfo(domain, None)
        for info in infos:
            sockaddr = info[4] if len(info) > 4 else None
            if not sockaddr:
                continue

            ip = str(sockaddr[0]).strip()
            ip = _strip_port(ip)
            if ip == 'localhost':
                ip = '127.0.0.1'

            try:
                resolved_ips.add(str(ipaddress.ip_address(ip)))
            except ValueError:
                continue
    except (socket.gaierror, OSError) as e:
        logger.warning(f"白名单域名解析失败: {domain} ({e})")

    with _DOMAIN_CACHE_LOCK:
        _DOMAIN_IP_CACHE[domain] = {
            'ips': resolved_ips,
            'expires_at': now_ts + ttl_seconds
        }
        # 顺便清理过期缓存，避免常驻增长
        stale_domains = [k for k, v in _DOMAIN_IP_CACHE.items() if v.get('expires_at', 0) <= now_ts]
        for stale in stale_domains:
            _DOMAIN_IP_CACHE.pop(stale, None)

    return resolved_ips


def is_ip_in_whitelist(ip, whitelist):
    """
    检查 IP 是否在白名单中
    """
    if not ip:
        return False

    # 处理 localhost 别名
    if ip == 'localhost':
        ip = '127.0.0.1'

    try:
        client_ip = ipaddress.ip_address(ip)
    except ValueError:
        # 无法解析的 IP，不在白名单中
        return False

    for pattern in whitelist:
        if not isinstance(pattern, str):
            continue

        pattern = pattern.strip()
        if not pattern:
            continue

        # 先按 IP/CIDR/通配符匹配（兼容旧行为）
        normalized_ip_pattern = normalize_ip_pattern(pattern)

        try:
            # 尝试作为单个 IP 匹配
            if '/' not in normalized_ip_pattern:
                if client_ip == ipaddress.ip_address(normalized_ip_pattern):
                    return True
            else:
                # 作为网络段匹配
                network = ipaddress.ip_network(normalized_ip_pattern, strict=False)
                if client_ip in network:
                    return True
        except ValueError:
            # 非 IP/CIDR 格式，继续尝试按域名匹配
            pass

        # 域名匹配：将域名解析为 IP 列表后对比
        domain = _normalize_domain_pattern(pattern)
        if not domain:
            continue

        if domain == 'localhost':
            domain_ips = set(str(ipaddress.ip_address(v)) for v in DEFAULT_TRUSTED_IPS)
        else:
            domain_ips = _resolve_domain_ips(domain)

        if str(client_ip) in domain_ips:
            return True

    return False


def is_trusted_request():
    """
    判断是否为受信任的请求（在白名单中）
    """
    ip = get_real_ip()
    whitelist = get_trusted_ips()
    return is_ip_in_whitelist(ip, whitelist)


def get_auth_credentials():
    """
    获取认证凭据，优先级：环境变量 > 配置文件
    返回 (username, password) 元组
    """
    # 优先从环境变量读取
    env_username = os.environ.get('STM_AUTH_USER', '').strip()
    env_password = os.environ.get('STM_AUTH_PASS', '').strip()

    if env_username and env_password:
        return env_username, env_password

    # 从配置文件读取
    cfg = load_config()
    cfg_username = cfg.get('auth_username', '').strip()
    cfg_password = cfg.get('auth_password', '').strip()

    return cfg_username, cfg_password


def is_auth_enabled():
    """
    检查是否启用了外网认证（配置了用户名和密码）
    支持环境变量: STM_AUTH_USER, STM_AUTH_PASS
    """
    username, password = get_auth_credentials()
    return bool(username and password)


def verify_credentials(username, password):
    """
    验证用户名和密码
    """
    stored_username, stored_password = get_auth_credentials()

    if not stored_username or not stored_password:
        return False

    return username == stored_username and password == stored_password


def is_authenticated():
    """
    检查当前会话是否已认证
    """
    return session.get('authenticated', False)


def login_user():
    """
    标记当前会话为已认证
    """
    session['authenticated'] = True
    session.permanent = True  # 使用持久会话


def logout_user():
    """
    登出当前会话
    """
    session.pop('authenticated', None)


def check_auth():
    """
    检查是否需要认证，返回 True 表示通过（无需认证或已认证）
    """
    # 白名单内的请求直接放行
    if is_trusted_request():
        return True

    # 未启用认证，直接放行
    if not is_auth_enabled():
        return True

    # 检查是否已登录
    return is_authenticated()


# === 登录页面 HTML ===
LOGIN_PAGE_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ST Manager - 登录</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-container {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 40px;
            width: 100%;
            max-width: 400px;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
        }
        .login-header {
            text-align: center;
            margin-bottom: 30px;
        }
        .login-header h1 {
            color: #fff;
            font-size: 28px;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        .login-icon {
            width: 1.25em;
            height: 1.25em;
            color: currentColor;
            flex: 0 0 auto;
        }
        .security-note-icon {
            width: 1.2em;
            height: 1.2em;
            margin-right: 4px;
            vertical-align: -0.25em;
            color: #93c5fd;
        }
        .login-header p {
            color: rgba(255, 255, 255, 0.6);
            font-size: 14px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        .form-group label {
            display: block;
            color: rgba(255, 255, 255, 0.8);
            margin-bottom: 8px;
            font-size: 14px;
        }
        .form-group input {
            width: 100%;
            padding: 12px 16px;
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.2);
            border-radius: 8px;
            color: #fff;
            font-size: 16px;
            transition: all 0.3s ease;
        }
        .form-group input:focus {
            outline: none;
            border-color: #3b82f6;
            background: rgba(255, 255, 255, 0.15);
        }
        .form-group input::placeholder {
            color: rgba(255, 255, 255, 0.4);
        }
        .login-btn {
            width: 100%;
            padding: 14px;
            background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
            border: none;
            border-radius: 8px;
            color: #fff;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .login-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px -10px rgba(59, 130, 246, 0.5);
        }
        .login-btn:active {
            transform: translateY(0);
        }
        .error-msg {
            background: rgba(239, 68, 68, 0.2);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: #fca5a5;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
            text-align: center;
        }
        .security-note {
            margin-top: 20px;
            padding: 12px;
            background: rgba(59, 130, 246, 0.1);
            border-radius: 8px;
            color: rgba(255, 255, 255, 0.6);
            font-size: 12px;
            text-align: center;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="login-header">
            <h1>
                <svg class="login-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                    <use href="/static/icons/ui.svg#icon-lock"></use>
                </svg>
                <span>ST Manager</span>
            </h1>
            <p>外网访问需要身份验证</p>
        </div>
        
        {% if error %}
        <div class="error-msg">{{ error }}</div>
        {% endif %}
        
        <form method="POST" action="/auth/login">
            <div class="form-group">
                <label for="username">用户名</label>
                <input type="text" id="username" name="username" placeholder="请输入用户名" required autofocus>
            </div>
            <div class="form-group">
                <label for="password">密码</label>
                <input type="password" id="password" name="password" placeholder="请输入密码" required>
            </div>
            <button type="submit" class="login-btn">登 录</button>
        </form>

        <div class="security-note">
            <svg class="security-note-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <use href="/static/icons/ui.svg#icon-shield"></use>
            </svg>
            您的 IP: {{ client_ip }}<br>
            <span style="font-size: 11px; opacity: 0.7;">如需免登录访问，请在设置中将此 IP 添加到白名单</span>
        </div>
    </div>
</body>
</html>
'''


def init_auth(app):
    """
    初始化认证模块，注册相关路由和钩子
    """
    # 设置 Secret Key（用于 Session 加密）
    if not app.secret_key:
        # 尝试从环境变量获取，否则生成一个持久的密钥
        secret_key = os.environ.get('STM_SECRET_KEY')
        if not secret_key:
            # 生成随机密钥并存储到配置目录
            from core.config import DATA_DIR
            key_file = os.path.join(DATA_DIR, '.secret_key')
            if os.path.exists(key_file):
                with open(key_file, 'r') as f:
                    secret_key = f.read().strip()
            else:
                secret_key = secrets.token_hex(32)
                try:
                    with open(key_file, 'w') as f:
                        f.write(secret_key)
                except:
                    pass
        app.secret_key = secret_key
    
    # 配置 Session
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7 天

    # === 登录页面路由 ===
    @app.route('/auth/login', methods=['GET', 'POST'])
    def auth_login():
        global _HARD_LOCKED, _HARD_LOCKED_AT, _GLOBAL_FAIL_COUNT, _GLOBAL_FAIL_LAST_TS
        client_ip = get_real_ip()

        # 锁定模式：需要手动重启
        if _is_hard_locked():
            error = "系统已进入锁定模式，需要后台手动重启"
            return render_template_string(LOGIN_PAGE_TEMPLATE, error=error, client_ip=client_ip)

        # 白名单内直接重定向到首页
        if is_trusted_request():
            return redirect('/')

        # 未启用认证也重定向
        if not is_auth_enabled():
            return redirect('/')

        error = None
        if request.method == 'POST':
            # 登录失败限流/锁定
            now_ts = time.time()
            key = _get_rate_limit_key()
            with _RATE_LIMIT_LOCK:
                max_attempts, window_seconds, lockout_seconds = _get_rate_limit_config()
                hard_lock_threshold = _get_hard_lock_threshold()
                _cleanup_rate_limit_state(now_ts, window_seconds)
                locked, remaining = _check_lockout(key, now_ts)
            if locked:
                minutes = max(1, int((remaining + 59) / 60))
                error = f"登录失败次数过多，请在 {minutes} 分钟后再试"
                logger.warning(f"登录被锁定: {key} 剩余 {remaining}s")
                return render_template_string(LOGIN_PAGE_TEMPLATE, error=error, client_ip=client_ip)

            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')

            if verify_credentials(username, password):
                login_user()
                with _RATE_LIMIT_LOCK:
                    _reset_failed_logins(key)
                    _reset_global_failures()
                logger.info(f"用户 '{username}' 从 {client_ip} 登录成功")
                # 重定向到原始请求页面或首页
                next_url = request.args.get('next', '/')
                return redirect(next_url)
            else:
                with _RATE_LIMIT_LOCK:
                    is_locked = _record_failed_login(
                        key, now_ts, max_attempts, window_seconds, lockout_seconds
                    )
                    # 全局连续失败计数（不区分 IP）
                    _GLOBAL_FAIL_COUNT += 1
                    _GLOBAL_FAIL_LAST_TS = now_ts
                    if _GLOBAL_FAIL_COUNT >= hard_lock_threshold and not _HARD_LOCKED:
                        _HARD_LOCKED = True
                        _HARD_LOCKED_AT = now_ts
                        logger.error(f"触发锁定模式: 全局连续失败 {_GLOBAL_FAIL_COUNT} 次")
                        error = "系统已进入锁定模式，需要后台手动重启"
                        return render_template_string(LOGIN_PAGE_TEMPLATE, error=error, client_ip=client_ip)
                    locked, remaining = _check_lockout(key, now_ts)
                if is_locked or locked:
                    minutes = max(1, int((remaining + 59) / 60))
                    error = f"登录失败次数过多，请在 {minutes} 分钟后再试"
                    logger.warning(f"登录被锁定: {key} 剩余 {remaining}s")
                else:
                    error = "用户名或密码错误"
                    logger.warning(f"登录失败: 用户 '{username}' 从 {client_ip}")

        return render_template_string(LOGIN_PAGE_TEMPLATE, error=error, client_ip=client_ip)

    # === 登出路由 ===
    @app.route('/auth/logout')
    def auth_logout():
        logout_user()
        return redirect('/auth/login')

    # === 全局认证检查 ===
    @app.before_request
    def check_authentication():
        # 排除静态资源和认证相关路由
        excluded_paths = (
            '/static/',
            '/auth/',
            '/favicon.ico',
        )
        
        path = request.path
        for excluded in excluded_paths:
            if path.startswith(excluded):
                return None

        # 锁定模式：需要手动重启
        if _is_hard_locked():
            if path.startswith('/api/'):
                return jsonify({
                    'success': False,
                    'error': 'Locked',
                    'message': '系统已进入锁定模式，需要后台手动重启'
                }), 503
            return redirect('/auth/login')
        
        # 检查认证
        if not check_auth():
            # API 请求返回 401
            if path.startswith('/api/'):
                return jsonify({
                    'success': False,
                    'error': 'Unauthorized',
                    'message': '需要登录才能访问此接口'
                }), 401
            
            # 页面请求重定向到登录页
            return redirect(f'/auth/login?next={request.path}')
        
        return None

    logger.info("认证模块已初始化")


# === 命令行工具 ===
def cli_set_auth(username, password):
    """
    通过命令行设置认证账号密码
    """
    from core.config import load_config, save_config

    cfg = load_config()
    cfg['auth_username'] = username
    cfg['auth_password'] = password

    if save_config(cfg):
        print(f"✅ 认证设置成功！")
        print(f"   用户名: {username}")
        print(f"   密码: {'*' * len(password)}")
        return True
    else:
        print("❌ 保存配置失败")
        return False


def cli_add_trusted_ip(ip):
    """
    通过命令行添加信任地址（IP/网段/域名）
    """
    from core.config import load_config, save_config

    cfg = load_config()
    trusted_ips = cfg.get('auth_trusted_ips', [])

    if ip in trusted_ips:
        print(f"⚠️ 地址 {ip} 已在白名单中")
        return False

    trusted_ips.append(ip)
    cfg['auth_trusted_ips'] = trusted_ips

    if save_config(cfg):
        print(f"✅ 已添加信任地址: {ip}")
        return True
    else:
        print("❌ 保存配置失败")
        return False


def cli_show_status():
    """
    显示当前认证状态
    """
    username, password = get_auth_credentials()
    from core.config import load_config
    cfg = load_config()
    trusted_ips = cfg.get('auth_trusted_ips', [])
    trusted_proxies = cfg.get('auth_trusted_proxies', [])

    print("\n🔐 ST Manager 认证状态")
    print("=" * 40)

    if username and password:
        # 检查来源
        env_user = os.environ.get('STM_AUTH_USER', '').strip()
        source = "环境变量" if env_user else "配置文件"
        print(f"✅ 认证已启用 (来源: {source})")
        print(f"   用户名: {username}")
        print(f"   密码: {'*' * len(password)}")
    else:
        print("❌ 认证未启用")
        print("   (未设置用户名和密码)")

    print(f"\n📋 白名单（IP/域名）:")
    print(f"   固定: 127.0.0.1, ::1 (本机)")
    if trusted_ips:
        for ip in trusted_ips:
            print(f"   自定义: {ip}")
    else:
        print(f"   自定义: (无)")

    print(f"\n🧭 受信任代理:")
    print(f"   固定: 127.0.0.1, ::1 (本机)")
    if trusted_proxies:
        for ip in trusted_proxies:
            print(f"   自定义: {ip}")
    else:
        print(f"   自定义: (无)")

    print("\n💡 使用提示:")
    print("   设置账号: python -m core.auth --set-auth <用户名> <密码>")
    print("   添加白名单: python -m core.auth --add-ip <IP/网段/域名>")
    print("   环境变量: STM_AUTH_USER, STM_AUTH_PASS")
    print()


def main():
    """
    命令行入口
    用法:
        python -m core.auth                          # 显示状态
        python -m core.auth --set-auth <用户名> <密码>  # 设置账号密码
        python -m core.auth --add-ip <地址>           # 添加白名单（IP/网段/域名）
    """
    import sys

    args = sys.argv[1:]

    if not args:
        cli_show_status()
        return

    if args[0] == '--set-auth' and len(args) >= 3:
        cli_set_auth(args[1], args[2])
    elif args[0] == '--add-ip' and len(args) >= 2:
        cli_add_trusted_ip(args[1])
    elif args[0] in ('-h', '--help'):
        print(main.__doc__)
    else:
        print("❌ 无效的参数")
        print(main.__doc__)
        sys.exit(1)


if __name__ == '__main__':
    main()
