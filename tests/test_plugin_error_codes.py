"""插件错误码契约测试：设计文档 10.4 表 ↔ `core/plugins/errors.py`。

设计文档是契约的唯一事实来源：新增错误码必须同时改文档与代码，任何一侧
漏改都会在这里失败（含 HTTP 状态码不一致）。
"""

import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import errors as errors_module

DESIGN_DOC = os.path.join(PROJECT_ROOT, 'docs', '2026-09-22-plugin-system-design.md')
TABLE_HEADER = '**统一错误码**'
ROW_PATTERN = re.compile(r'^\| `([a-z][a-z0-9_]*)` \| (\d{3}) \| (.+) \|$', re.MULTILINE)


def _documented_codes() -> dict:
    with open(DESIGN_DOC, 'r', encoding='utf-8') as handle:
        content = handle.read()

    start = content.index(TABLE_HEADER)
    end = content.find('\n## ', start)
    section = content[start:end if end > 0 else len(content)]

    return {
        match.group(1): int(match.group(2))
        for match in ROW_PATTERN.finditer(section)
    }


def _implemented_codes() -> dict:
    result = {}
    for name in dir(errors_module):
        candidate = getattr(errors_module, name)
        if not isinstance(candidate, type):
            continue
        if not issubclass(candidate, errors_module.PluginError):
            continue
        if candidate is errors_module.PluginError:
            continue
        result[candidate.code] = candidate.http_status
    return result


def test_documentation_table_is_parseable():
    documented = _documented_codes()

    assert len(documented) >= 16
    assert documented['plugin_not_found'] == 404


def test_every_implemented_code_is_documented():
    undocumented = sorted(set(_implemented_codes()) - set(_documented_codes()))

    assert undocumented == [], f'以下错误码未登记到设计文档 10.4: {undocumented}'


def test_every_documented_code_is_implemented():
    missing = sorted(set(_documented_codes()) - set(_implemented_codes()))

    assert missing == [], f'设计文档登记了但代码中不存在的错误码: {missing}'


def test_http_status_matches_documentation():
    documented = _documented_codes()
    implemented = _implemented_codes()

    mismatches = {
        code: {'documented': documented[code], 'implemented': implemented[code]}
        for code in documented
        if code in implemented and documented[code] != implemented[code]
    }

    assert mismatches == {}, f'HTTP 状态码不一致: {mismatches}'


def test_base_error_code_is_not_documented():
    assert errors_module.PluginError.code not in _documented_codes()


def test_error_codes_are_unique():
    codes = [
        getattr(errors_module, name).code
        for name in dir(errors_module)
        if isinstance(getattr(errors_module, name), type)
        and issubclass(getattr(errors_module, name), errors_module.PluginError)
        and getattr(errors_module, name) is not errors_module.PluginError
        and getattr(errors_module, name).__mro__[1] is errors_module.PluginError
    ]

    assert len(codes) == len(set(codes))


def test_to_dict_exposes_documented_code():
    payload = errors_module.PluginNotFoundError('插件不存在: demo').to_dict()

    assert payload == {
        'success': False,
        'msg': '插件不存在: demo',
        'error': 'plugin_not_found',
    }


def test_to_dict_includes_detail_when_present():
    payload = errors_module.PluginInstallError('安装失败', detail='zip-slip 被拦截').to_dict()

    assert payload['error'] == 'plugin_install_failed'
    assert payload['detail'] == 'zip-slip 被拦截'


def test_archive_error_inherits_install_error_but_has_own_code():
    error = errors_module.PluginArchiveUnsafeError('归档不安全')

    assert isinstance(error, errors_module.PluginInstallError)
    assert error.code == 'install_unsafe_archive'
    assert error.code != errors_module.PluginInstallError.code


def test_routes_use_error_http_status():
    """路由层必须用异常自带的 http_status，而不是硬编码 500。"""
    source_path = os.path.join(PROJECT_ROOT, 'core', 'plugins', 'routes.py')
    with open(source_path, 'r', encoding='utf-8') as handle:
        source = handle.read()

    assert 'http_status' in source
    assert 'error.to_dict()' in source or '.to_dict()' in source
