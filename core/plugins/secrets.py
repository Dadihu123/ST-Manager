"""插件密钥存储（设计文档第 7 部分）。

- 落盘位置：`data/system/secrets.json`（**不迁移** `config.json` 里的既有密钥，D2）。
- 原子写：同目录 `mkstemp` → `fsync` → `os.replace`，写前轮转 3 代 `.bak`。
- 内容损坏：备份为 `.corrupted.<ts>` 后返回 `{}`（密钥丢失不该阻塞启动）。
- 读取 IO 失败：标记降级并**拒绝写入**，避免把仅存的有效密钥覆盖掉。
- `secret: true` 的项永不返回明文，只返回 `{set, hint}`。
- 环境变量 `STM_PLUGIN_<ID>_<KEY>` 优先级最高（Docker/CI 场景不落盘）。
"""

import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time

from core.config import SYSTEM_DIR

logger = logging.getLogger(__name__)

SECRETS_FILE = os.path.join(SYSTEM_DIR, 'secrets.json')

SCHEMA_VERSION = 1
BACKUP_GENERATIONS = 3
READ_RETRY_ATTEMPTS = 4
READ_RETRY_DELAY_SECONDS = 0.05
HINT_PREFIX_LEN = 3
HINT_SUFFIX_LEN = 4
MIN_HINTABLE_LENGTH = 8

ENV_PREFIX = 'STM_PLUGIN_'

_ENV_SANITIZE_PATTERN = re.compile(r'[^A-Za-z0-9]+')

_secrets_lock = threading.RLock()

# 读取失败降级状态：一旦某次读取因 IO 错误失败，在下次成功读取前禁止写入。
_degraded_reason = ''


def _mark_degraded(reason: str) -> None:
    global _degraded_reason
    with _secrets_lock:
        _degraded_reason = str(reason or 'unknown')


def _clear_degraded() -> None:
    global _degraded_reason
    with _secrets_lock:
        _degraded_reason = ''


def is_degraded() -> bool:
    """当前是否处于「读取失败、禁止写入」状态。"""
    with _secrets_lock:
        return bool(_degraded_reason)


def degraded_reason() -> str:
    with _secrets_lock:
        return _degraded_reason


def env_var_name(plugin_id: str, key: str) -> str:
    """环境变量名：`STM_PLUGIN_<PLUGIN_ID>_<KEY>`（大写、非字母数字转下划线）。"""
    normalized_id = _ENV_SANITIZE_PATTERN.sub('_', str(plugin_id or '').strip().lower()).upper()
    normalized_key = _ENV_SANITIZE_PATTERN.sub('_', str(key or '').strip().lower()).upper()
    return f'{ENV_PREFIX}{normalized_id}_{normalized_key}'


def hint_for(value: str) -> str:
    """生成掩码提示：前 3 + 后 4；过短的值全部掩码。"""
    text = str(value or '')
    if not text:
        return ''
    if len(text) <= MIN_HINTABLE_LENGTH:
        return '•' * len(text)
    return f'{text[:HINT_PREFIX_LEN]}…{text[-HINT_SUFFIX_LEN:]}'


def redact(text, *values) -> str:
    """把文本中出现过的密钥值替换为掩码。用于日志与错误信息。"""
    result = str(text or '')
    for value in values:
        secret = str(value or '')
        if len(secret) < 4:
            continue
        result = result.replace(secret, '***')
    return result


def _backup_paths() -> list:
    base = f'{SECRETS_FILE}.bak'
    return [base] + [f'{base}.{index}' for index in range(1, BACKUP_GENERATIONS)]


def _corrupted_path() -> str:
    timestamp = time.strftime('%Y%m%d%H%M%S')
    return f'{SECRETS_FILE}.corrupted.{timestamp}.{os.getpid()}'


def _is_retriable_read_error(exc: Exception) -> bool:
    if isinstance(exc, json.JSONDecodeError):
        return False
    if isinstance(exc, UnicodeDecodeError):
        return True
    return isinstance(exc, OSError)


def _read_json_with_retry(path: str, attempts: int = READ_RETRY_ATTEMPTS) -> dict:
    """带重试地读取 JSON；用于区分「瞬时占用」与「内容损坏」。"""
    last_error = None
    total = max(1, int(attempts))
    for attempt in range(total):
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise json.JSONDecodeError('top level is not object', '', 0)
            return payload
        except Exception as exc:  # noqa: BLE001 - 需要区分瞬时/永久错误
            last_error = exc
            if not _is_retriable_read_error(exc) or attempt == total - 1:
                raise
            time.sleep(READ_RETRY_DELAY_SECONDS * (attempt + 1))

    raise last_error if last_error is not None else OSError(f'无法读取 {path}')


def _rotate_backups() -> None:
    paths = _backup_paths()
    oldest = paths[-1]
    if os.path.exists(oldest):
        try:
            os.remove(oldest)
        except OSError as exc:
            logger.warning('清理旧密钥备份失败 %s: %s', oldest, exc)

    for source, target in zip(reversed(paths[:-1]), reversed(paths[1:])):
        if not os.path.exists(source):
            continue
        try:
            os.replace(source, target)
        except OSError as exc:
            logger.warning('轮转密钥备份失败 %s -> %s: %s', source, target, exc)


def _preserve_current_as_backup() -> None:
    """写入前把当前主文件轮转为备份（仅当它可解析为对象）。"""
    if not os.path.exists(SECRETS_FILE):
        return
    try:
        _read_json_with_retry(SECRETS_FILE)
    except Exception as exc:  # noqa: BLE001 - 不可解析时不覆盖既有备份世代
        logger.warning('当前 secrets.json 无法解析，跳过备份: %s', exc)
        return

    try:
        _rotate_backups()
        shutil.copy2(SECRETS_FILE, _backup_paths()[0])
    except OSError as exc:
        logger.warning('备份 secrets.json 失败: %s', exc)


def _snapshot_corrupted() -> str:
    if not os.path.exists(SECRETS_FILE):
        return ''
    try:
        target = _corrupted_path()
        shutil.copy2(SECRETS_FILE, target)
        return target
    except OSError as exc:
        logger.error('备份损坏的 secrets.json 失败: %s', exc)
        return ''


def _apply_restrictive_permissions(path: str) -> None:
    """POSIX 下把密钥文件收紧到 0600；Windows 上 chmod 语义有限，忽略失败。"""
    if os.name != 'posix':
        return
    try:
        os.chmod(path, 0o600)
    except OSError as exc:
        logger.warning('设置 secrets.json 权限失败: %s', exc)


def _write_atomic(data: dict) -> None:
    parent_dir = os.path.dirname(SECRETS_FILE)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
        if os.name == 'posix':
            try:
                os.chmod(parent_dir, 0o700)
            except OSError:
                pass

    fd = None
    temp_path = ''
    try:
        fd, temp_path = tempfile.mkstemp(
            prefix=f'.{os.path.basename(SECRETS_FILE)}.',
            suffix='.tmp',
            dir=parent_dir or None,
        )
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            fd = None
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, SECRETS_FILE)
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
                logger.warning('清理 secrets.json 临时文件失败: %s', temp_path, exc_info=True)

    _apply_restrictive_permissions(SECRETS_FILE)


def load_secrets() -> dict:
    """读取密钥文件；文件缺失或内容损坏时返回 `{}`，读取 IO 失败则标记降级。"""
    if not os.path.exists(SECRETS_FILE):
        _clear_degraded()
        return {}

    try:
        payload = _read_json_with_retry(SECRETS_FILE)
    except json.JSONDecodeError as exc:
        corrupted = _snapshot_corrupted()
        logger.error('secrets.json 内容损坏，已备份为 %s: %s', corrupted or '(备份失败)', exc)
        _clear_degraded()
        return {}
    except Exception as exc:  # noqa: BLE001 - 读失败必须阻止后续覆盖写
        _mark_degraded(f'{type(exc).__name__}: {exc}')
        logger.error('secrets.json 读取失败，已禁止写入以避免覆盖: %s', exc)
        return {}

    _clear_degraded()
    payload.setdefault('schema_version', SCHEMA_VERSION)
    plugins = payload.get('plugins')
    if not isinstance(plugins, dict):
        payload['plugins'] = {}
    app_section = payload.get('app')
    if not isinstance(app_section, dict):
        payload['app'] = {}
    return payload


def save_secrets(data: dict) -> bool:
    """原子保存密钥文件；处于降级状态或数据非法时拒绝写入。"""
    if not isinstance(data, dict):
        logger.error('保存 secrets.json 失败: 数据不是字典')
        return False

    with _secrets_lock:
        if _degraded_reason:
            logger.error(
                '拒绝写入 secrets.json: 当前处于读取失败降级状态 (%s)。请先成功读取一次。',
                _degraded_reason,
            )
            return False

        try:
            payload = dict(data)
            payload['schema_version'] = SCHEMA_VERSION
            if not isinstance(payload.get('plugins'), dict):
                payload['plugins'] = {}
            if not isinstance(payload.get('app'), dict):
                payload['app'] = {}

            _preserve_current_as_backup()
            _write_atomic(payload)
            return True
        except Exception as exc:  # noqa: BLE001 - 写盘失败必须记录且不抛出
            logger.error('保存 secrets.json 失败: %s', exc)
            return False


def _plugin_bucket(data: dict, plugin_id: str, *, create: bool = False) -> dict:
    plugins = data.setdefault('plugins', {}) if create else (data.get('plugins') or {})
    if not isinstance(plugins, dict):
        plugins = {}
        if create:
            data['plugins'] = plugins
    bucket = plugins.get(str(plugin_id))
    if not isinstance(bucket, dict):
        bucket = {}
        if create:
            plugins[str(plugin_id)] = bucket
    return bucket


def get_secret(plugin_id: str, key: str, *, default=None):
    """读取单个密钥值：环境变量 > secrets.json > default。"""
    value = _env_value(plugin_id, key)
    if value is not None:
        return value

    data = load_secrets()
    entry = _plugin_bucket(data, plugin_id).get(str(key))
    if isinstance(entry, dict) and entry.get('value') not in (None, ''):
        return str(entry.get('value'))
    if isinstance(entry, str) and entry:
        return entry
    return default


def secret_updated_at(plugin_id: str, key: str) -> float:
    """密钥最后一次写入时间；来自环境变量时返回 0。"""
    data = load_secrets()
    entry = _plugin_bucket(data, plugin_id).get(str(key))
    if isinstance(entry, dict):
        try:
            return float(entry.get('updated_at') or 0)
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _env_value(plugin_id: str, key: str):
    name = env_var_name(plugin_id, key)
    if not name:
        return None
    value = os.environ.get(name)
    if value is None or value == '':
        return None
    return value


def set_secret(plugin_id: str, key: str, value) -> bool:
    """写入（或清除）单个密钥。`value` 为 None / 空串表示清除该项。"""
    plugin_id = str(plugin_id or '').strip()
    key = str(key or '').strip()
    if not plugin_id or not key:
        return False

    data = load_secrets()
    if is_degraded():
        return False

    bucket = _plugin_bucket(data, plugin_id, create=True)
    if value is None or str(value) == '':
        bucket.pop(key, None)
    else:
        bucket[key] = {'value': str(value), 'updated_at': time.time()}

    if not bucket:
        plugins = data.get('plugins') or {}
        plugins.pop(plugin_id, None)

    return save_secrets(data)


def delete_secret(plugin_id: str, key: str) -> bool:
    """清除单个密钥项。"""
    return set_secret(plugin_id, key, None)


def app_env_var_name(key: str) -> str:
    """主程序自身密钥的环境变量名：`STM_APP_<KEY>`。"""
    normalized = _ENV_SANITIZE_PATTERN.sub('_', str(key or '').strip().lower()).upper()
    return f'STM_APP_{normalized}'


def get_app_secret(key: str, *, default=None):
    """读取 `app` 段的主程序自身密钥（如 `github_token`）。

    环境变量 `STM_APP_<KEY>` 优先级最高，其余读取 `secrets.json` 的 `app` 段。
    """
    env_name = app_env_var_name(key)
    env_value = os.environ.get(env_name) if env_name else None
    if env_value:
        return env_value

    data = load_secrets()
    section = data.get('app') if isinstance(data.get('app'), dict) else {}
    entry = section.get(str(key))
    if isinstance(entry, dict) and entry.get('value') not in (None, ''):
        return str(entry.get('value'))
    if isinstance(entry, str) and entry:
        return entry
    return default


def set_app_secret(key: str, value) -> bool:
    """写入（或清除）`app` 段的密钥；`None` / 空串表示清除。"""
    key = str(key or '').strip()
    if not key:
        return False

    data = load_secrets()
    if is_degraded():
        return False

    section = data.get('app')
    if not isinstance(section, dict):
        section = {}
        data['app'] = section

    if value is None or str(value) == '':
        section.pop(key, None)
    else:
        section[key] = {'value': str(value), 'updated_at': time.time()}

    return save_secrets(data)


def clear_plugin_secrets(plugin_id: str) -> bool:
    """清除某个插件的全部密钥（卸载时默认调用）。"""
    plugin_id = str(plugin_id or '').strip()
    if not plugin_id:
        return False

    data = load_secrets()
    if is_degraded():
        return False

    plugins = data.get('plugins') or {}
    if plugin_id not in plugins:
        return True
    plugins.pop(plugin_id, None)
    return save_secrets(data)


def describe_secrets(plugin_id: str, secret_schema: dict | None = None) -> dict:
    """渲染密钥表单所需的元数据。

    `secret: true` 的项只返回 `{set, hint, updated_at, source}`；
    非 secret 项返回明文 `value`。schema 未声明的额外项按 secret 处理。
    """
    schema = secret_schema if isinstance(secret_schema, dict) else {}
    properties = schema.get('properties') if isinstance(schema.get('properties'), dict) else {}

    data = load_secrets()
    bucket = _plugin_bucket(data, plugin_id)

    result = {}
    reported_keys = set()
    for key, spec in properties.items():
        spec = spec if isinstance(spec, dict) else {}
        reported_keys.add(key)
        result[key] = _describe_one(plugin_id, key, spec, bucket)

    for key, entry in bucket.items():
        if key in reported_keys:
            continue
        if not isinstance(entry, dict):
            continue
        result[str(key)] = _describe_one(plugin_id, str(key), {'type': 'string', 'secret': True}, bucket)

    return result


def _describe_one(plugin_id: str, key: str, spec: dict, bucket: dict) -> dict:
    env_value = _env_value(plugin_id, key)
    entry = bucket.get(key) if isinstance(bucket.get(key), dict) else {}
    file_value = entry.get('value')
    stored = '' if file_value in (None, '') else str(file_value)
    effective = env_value if env_value is not None else stored

    # 非 secret 项在没有保存值时回退 schema 默认值，与 get_secret 的语义保持一致；
    # 但默认值不算「已设置」，避免 UI 误报为已配置。
    if not effective and not spec.get('secret') and 'default' in spec:
        default_value = spec.get('default')
        effective = '' if default_value is None else str(default_value)

    try:
        updated_at = float(entry.get('updated_at') or 0)
    except (TypeError, ValueError):
        updated_at = 0.0

    is_set = bool(env_value is not None or stored)
    source = 'env' if env_value is not None else ('file' if stored else '')

    if spec.get('secret'):
        return {
            'set': is_set,
            'hint': hint_for(effective) if is_set else '',
            'updated_at': updated_at,
            'source': source,
        }

    return {
        'set': is_set,
        'value': effective,
        'updated_at': updated_at,
        'source': source,
    }
