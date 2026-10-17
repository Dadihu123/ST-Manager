"""插件 API 文档同步测试（设计文档阶段 3「API 文档自动生成」）。

核心断言：`docs/plugin-api.md` 必须与 `PluginAPI` / `pluginHost.js` 的当前实现一致。
新增或删除 API 后忘记重跑 `python tools/gen_plugin_api_docs.py`，这里会直接失败。
"""

import inspect
import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from tools.gen_plugin_api_docs import (
    BACKEND_ATTRIBUTES,
    BACKEND_DOMAINS,
    BACKEND_GROUPS,
    BACKEND_INTERNAL,
    DOC_PATH,
    FRONTEND_MEMBERS,
    check_document,
    collect_backend_api,
    collect_frontend_members,
    collect_source_defined_methods,
    main,
    render,
)


def test_document_exists():
    assert os.path.isfile(DOC_PATH)


def test_document_is_in_sync_with_code():
    with open(DOC_PATH, 'r', encoding='utf-8') as handle:
        on_disk = handle.read()

    assert on_disk == render(), (
        'docs/plugin-api.md 与当前代码不一致；'
        '请运行 python tools/gen_plugin_api_docs.py 重新生成'
    )


def test_check_mode_passes(capsys):
    assert check_document() is True
    assert main(['--check']) == 0


def test_every_public_method_is_grouped():
    backend = collect_backend_api()

    ungrouped = [name for name in backend['public'] if name not in backend['declared']]

    assert ungrouped == [], f'以下公开方法未在生成器的分组表中登记: {ungrouped}'


def test_grouped_methods_actually_exist():
    from core.plugins.api import PluginAPI

    for _title, _stability, methods in BACKEND_GROUPS:
        for entry in methods:
            name = entry[0] if isinstance(entry, tuple) else entry
            assert hasattr(PluginAPI, name), f'分组表引用了不存在的方法: {name}'

    for name in BACKEND_INTERNAL:
        assert hasattr(PluginAPI, name), f'内部方法表引用了不存在的方法: {name}'


def test_grouped_domain_methods_actually_exist():
    """域方法必须真实存在于**域类**上。"""
    from core.plugins.domains import DOMAIN_CLASSES

    for domain, _summary, _stability, methods in BACKEND_DOMAINS:
        domain_cls = DOMAIN_CLASSES.get(domain)
        assert domain_cls is not None, f'域类未在 DOMAIN_CLASSES 登记: {domain}'
        for name in methods:
            assert hasattr(domain_cls, name), f'{domain} 域不存在方法: {name}'


def test_domain_methods_are_not_flat_members_of_plugin_api():
    """域方法不应同时是 `PluginAPI` 的类成员（否则 AST 与反射会漂移）。"""
    from core.plugins.api import PluginAPI

    flat = {
        name for name, member in inspect.getmembers(PluginAPI, predicate=inspect.isfunction)
    }
    for domain, _summary, _stability, methods in BACKEND_DOMAINS:
        conflicts = sorted(set(methods) & flat)
        assert conflicts == [], f'{domain} 域的方法与 PluginAPI 类成员重名: {conflicts}'


def test_domain_attributes_are_instance_attributes_not_properties():
    """域必须是 `__init__` 里的实例属性：`@property` 会让 AST 与反射不一致（方案 §3.5）。"""
    from core.plugins.api import PluginAPI

    for domain, _summary, _stability, _methods in BACKEND_DOMAINS:
        assert not hasattr(PluginAPI, domain), (
            f'{domain} 出现在 PluginAPI 类上；域必须是 __init__ 里的实例属性，'
            '否则 test_ast_and_introspection_agree_on_public_methods 会失败'
        )

    # 实例上确实存在，且是**同一个**实例（方案 §3.4 的硬约束）
    manifest = _demo_manifest()
    api = PluginAPI(manifest)
    for domain, _summary, _stability, _methods in BACKEND_DOMAINS:
        assert getattr(api, domain) is getattr(api, domain)


def test_domain_classes_match_backend_domains_registry():
    """生成器登记的域与 `DOMAIN_CLASSES` 必须一一对应（防止漏登记新域）。"""
    from core.plugins.domains import DOMAIN_CLASSES

    declared = {domain for domain, _summary, _s, _m in BACKEND_DOMAINS}

    assert declared == set(DOMAIN_CLASSES), (
        f'只在 DOMAIN_CLASSES 里的域: {sorted(set(DOMAIN_CLASSES) - declared)}；'
        f'只在 BACKEND_DOMAINS 里的域: {sorted(declared - set(DOMAIN_CLASSES))}'
    )


def _demo_manifest():
    """构造一个最小 manifest（域实例化不需要真实插件目录）。"""
    from core.plugins.manifest import PluginManifest

    class _Stub:
        plugin_id = 'docs-demo'
        plugin_dir = '.'
        config_schema = {}
        secret_schema = {}
        backend_jobs = []
        warnings = []

        def to_dict(self):
            return {'id': self.plugin_id}

    return _Stub()


def test_declared_domains_are_all_registered_as_attributes():
    declared_names = {name for name, _type, _stability, _doc in BACKEND_ATTRIBUTES}
    for domain, _summary, _stability, _methods in BACKEND_DOMAINS:
        assert domain in declared_names, f'域 {domain} 未登记进 BACKEND_ATTRIBUTES'


def test_ast_and_introspection_agree_on_public_methods():
    """静态解析与 import 后的反射结果必须一致（防止条件定义造成文档漂移）。"""
    assert collect_source_defined_methods() == collect_backend_api()['public']


def test_frontend_keys_are_all_declared():
    declared = set()
    for keys, _display, _stability, _doc in FRONTEND_MEMBERS:
        declared.update(keys)

    undeclared = [key for key in collect_frontend_members() if key not in declared]

    assert undeclared == [], f'pluginHost.js 暴露但未登记的成员: {undeclared}'


def test_frontend_declared_members_are_exposed_by_host():
    exposed = set(collect_frontend_members())
    declared = set()
    for keys, _display, _stability, _doc in FRONTEND_MEMBERS:
        declared.update(keys)

    # 允许声明但暂未实现（例如保留位），但必须显式说明；此处只检查常见漏写
    missing = sorted(declared - exposed)
    assert missing == [], f'文档声明了 pluginHost.js 未暴露的成员: {missing}'


def test_rendered_document_contains_key_sections():
    content = render()

    assert content.startswith('<!-- generated by tools/gen_plugin_api_docs.py')
    assert '请勿手工编辑' in content

    for title, _stability, _methods in BACKEND_GROUPS:
        assert f'### {title}' in content, title

    for domain, _summary, _stability, _methods in BACKEND_DOMAINS:
        assert f'### `api.{domain}.*`' in content, domain

    assert '## 后端 `PluginAPI`' in content
    assert '## 前端 `activate(api)`' in content
    assert '## 相关文档' in content


def test_rendered_document_avoids_self_parameter():
    content = render()

    assert 'set(self' not in content
    assert 'apply_tags(self' not in content
    assert '`api.cards.apply_tags()' in content


def test_signatures_are_complete_for_documented_methods():
    content = render()

    # 抽查几个契约上最关键的签名形态（域方法带 `api.<域>.` 前缀）
    assert 'apply_tags(card_ids, *, add=(), remove=(), replace: bool = False)' in content
    assert 'submit(job_type: str, *, items, payload=None) -> str' in content
    assert 'write(source: dict, data: dict, *, expected_revision: str = \'\') -> dict' in content
    assert 'move(card_ids, target_category: str) -> dict' in content


def test_domains_section_is_documented():
    content = render()

    for domain, _summary, _stability, methods in BACKEND_DOMAINS:
        assert f'`api.{domain}.*`' in content, domain
        for method in methods:
            assert f'`api.{domain}.{method}()`' in content, f'{domain}.{method}'


def test_previously_flat_members_are_gone():
    """方案 §3.2：这些成员不是改名，是**删除**，不应再出现在文档里。"""
    content = render()

    assert 'api.db()' not in content
    assert 'api.notify(' not in content
    assert '`suppress_fs_events()`' not in content


def test_attributes_section_is_documented():
    content = render()

    for name, type_hint, stability, _doc in BACKEND_ATTRIBUTES:
        assert f'| `{name}` | {type_hint} | {stability} |' in content


def test_generator_write_is_idempotent(tmp_path, monkeypatch):
    """无变化时不应重写文件（避免污染 mtime / 触发构建）。"""
    target = tmp_path / 'plugin-api.md'
    monkeypatch.setattr('tools.gen_plugin_api_docs.DOC_PATH', str(target))

    from tools import gen_plugin_api_docs as module

    assert module.write_document() is True
    first_stat = target.stat().st_mtime_ns

    assert module.write_document() is False
    assert target.stat().st_mtime_ns == first_stat


def test_missing_document_fails_check(tmp_path, monkeypatch):
    monkeypatch.setattr('tools.gen_plugin_api_docs.DOC_PATH', str(tmp_path / 'missing.md'))

    from tools import gen_plugin_api_docs as module

    assert module.check_document() is False


@pytest.mark.parametrize('fragment', [
    'subscribeJob',
    'plugin_<id>_',
    '`store`',
    'api.private.query',
    'api.cards.read_note',
    'api.backups.restore_card_snapshot',
])
def test_document_mentions_critical_contracts(fragment):
    assert fragment in render()
