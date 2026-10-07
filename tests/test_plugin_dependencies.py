"""插件间依赖声明与加载顺序测试（设计文档阶段 3 + 2.2）。"""

import os
import sys

import pytest
from flask import Flask

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import registry as registry_module
from core.plugins.manifest import (
    PluginManifest,
    parse_requirement,
    satisfies_requirement,
)
from tests.plugins_test_support import (
    base_manifest,
    clear_plugin_ui_namespace,
    default_css,
    write_plugin,
)

PROBE_MODULE = '_st_plugin_load_probe'

BACKEND_RECORDING_LOAD = '''\
import sys


def register(api):
    probe = sys.modules.get('{probe}')
    if probe is not None:
        probe.append(api.plugin_id)
'''.format(probe=PROBE_MODULE)


@pytest.fixture(autouse=True)
def _isolate_registry():
    registry_module.reset_for_tests()
    clear_plugin_ui_namespace()
    load_order = []
    sys.modules[PROBE_MODULE] = load_order
    yield load_order
    sys.modules.pop(PROBE_MODULE, None)
    registry_module.reset_for_tests()
    clear_plugin_ui_namespace()
    for name in list(sys.modules):
        if name.startswith(registry_module.MODULE_PREFIX):
            sys.modules.pop(name, None)


def _make_plugin(tmp_path, plugin_id, *, version='1.0.0', requires=None, **manifest_overrides):
    manifest = base_manifest(plugin_id, version=version, **manifest_overrides)
    if requires is not None:
        manifest['requires'] = requires
    return write_plugin(
        tmp_path, plugin_id,
        manifest=manifest,
        backend=BACKEND_RECORDING_LOAD,
    )


# ------------------------------------------------------------------ 约束解析


@pytest.mark.parametrize('constraint,expected', [
    ('1.2.3', ('==', '1.2.3')),
    ('==1.2.3', ('==', '1.2.3')),
    ('=1.2.3', ('=', '1.2.3')),
    ('>=1.2.3', ('>=', '1.2.3')),
    ('>1.2.3', ('>', '1.2.3')),
    ('<=1.2.3', ('<=', '1.2.3')),
    ('<1.2.3', ('<', '1.2.3')),
    ('*', ('==', '*')),
    ('>= 1.2.3', ('>=', '1.2.3')),
])
def test_parse_requirement_accepts_supported_syntax(constraint, expected):
    assert parse_requirement(constraint) == expected


@pytest.mark.parametrize('constraint', ['', 'latest', '^1.2.3', '~1.2.3', '>=abc', '1.2'])
def test_parse_requirement_rejects_unsupported_syntax(constraint):
    assert parse_requirement(constraint) is None


@pytest.mark.parametrize('version,constraint,expected', [
    ('1.2.3', '>=1.2.3', True),
    ('1.2.4', '>=1.2.3', True),
    ('1.2.2', '>=1.2.3', False),
    ('1.2.3', '>1.2.3', False),
    ('1.2.3', '<=1.2.3', True),
    ('1.2.3', '<1.2.3', False),
    ('1.2.3', '1.2.3', True),
    ('1.2.3', '1.2.4', False),
    ('1.2.3', '*', True),
    ('2.0.0', '>=1.10.0', True),
    ('1.9.9', '>=1.10.0', False),
])
def test_satisfies_requirement(version, constraint, expected):
    assert satisfies_requirement(version, constraint) is expected


# ------------------------------------------------------------------ manifest 解析


def test_manifest_parses_valid_requires(tmp_path):
    plugin_dir = _make_plugin(tmp_path, 'child-plugin', requires={'base-plugin': '>=1.0.0'})

    manifest = PluginManifest.load(plugin_dir)

    assert manifest.requires == {'base-plugin': '>=1.0.0'}
    assert manifest.to_dict()['requires'] == {'base-plugin': '>=1.0.0'}


def test_manifest_ignores_invalid_requires_entries(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'child-plugin',
        manifest=base_manifest('child-plugin', requires={
            'Bad_Id': '>=1.0.0',
            'ok-plugin': 'latest',
            'child-plugin': '>=1.0.0',
            'good-plugin': '>=2.0.0',
        }),
    )

    manifest = PluginManifest.load(plugin_dir)

    assert manifest.requires == {'good-plugin': '>=2.0.0'}
    assert len(manifest.warnings) == 3


def test_manifest_warns_when_requires_is_not_object(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'child-plugin',
        manifest=base_manifest('child-plugin', requires=['base-plugin']),
    )

    manifest = PluginManifest.load(plugin_dir)

    assert manifest.requires == {}
    assert any('requires' in warning for warning in manifest.warnings)


# ------------------------------------------------------------------ 加载顺序


def test_dependencies_load_before_dependents(tmp_path, monkeypatch, _isolate_registry):
    _make_plugin(tmp_path, 'base-plugin')
    _make_plugin(tmp_path, 'child-plugin', requires={'base-plugin': '>=1.0.0'})
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))

    summary = registry_module.load_all(Flask('deps-test'))

    assert sorted(summary['loaded']) == ['base-plugin', 'child-plugin']
    assert _isolate_registry == ['base-plugin', 'child-plugin']


def test_transitive_dependencies_are_ordered(tmp_path, monkeypatch, _isolate_registry):
    _make_plugin(tmp_path, 'a-plugin')
    _make_plugin(tmp_path, 'b-plugin', requires={'a-plugin': '>=1.0.0'})
    _make_plugin(tmp_path, 'c-plugin', requires={'b-plugin': '>=1.0.0'})
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))

    summary = registry_module.load_all(Flask('deps-test'))

    assert sorted(summary['loaded']) == ['a-plugin', 'b-plugin', 'c-plugin']
    assert _isolate_registry == ['a-plugin', 'b-plugin', 'c-plugin']


def test_missing_dependency_marks_load_error(tmp_path, monkeypatch):
    _make_plugin(tmp_path, 'child-plugin', requires={'ghost-plugin': '>=1.0.0'})
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))

    summary = registry_module.load_all(Flask('deps-test'))

    assert summary['loaded'] == []
    assert summary['failed'] == ['child-plugin']
    state = registry_module.get_state('child-plugin')
    assert '缺少依赖插件' in state.load_error
    assert 'ghost-plugin' in state.load_error
    assert registry_module.read_ui_entry('child-plugin')['load_error'].startswith('缺少依赖插件')


def test_version_mismatch_marks_load_error(tmp_path, monkeypatch):
    _make_plugin(tmp_path, 'base-plugin', version='1.0.0')
    _make_plugin(tmp_path, 'child-plugin', requires={'base-plugin': '>=2.0.0'})
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))

    summary = registry_module.load_all(Flask('deps-test'))

    assert summary['loaded'] == ['base-plugin']
    assert summary['failed'] == ['child-plugin']
    assert '依赖版本不满足' in registry_module.get_state('child-plugin').load_error


def test_dependency_on_disabled_plugin_fails(tmp_path, monkeypatch):
    _make_plugin(tmp_path, 'base-plugin')
    _make_plugin(tmp_path, 'child-plugin', requires={'base-plugin': '*'})
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))
    registry_module.set_enabled('base-plugin', False)

    summary = registry_module.load_all(Flask('deps-test'))

    assert summary['disabled'] == ['base-plugin']
    assert summary['failed'] == ['child-plugin']
    assert '依赖插件已被禁用' in registry_module.get_state('child-plugin').load_error


def test_cycle_is_detected_and_both_fail(tmp_path, monkeypatch):
    _make_plugin(tmp_path, 'a-plugin', requires={'b-plugin': '*'})
    _make_plugin(tmp_path, 'b-plugin', requires={'a-plugin': '*'})
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))

    summary = registry_module.load_all(Flask('deps-test'))

    assert summary['loaded'] == []
    assert sorted(summary['failed']) == ['a-plugin', 'b-plugin']
    assert '循环依赖' in registry_module.get_state('a-plugin').load_error
    assert '循环依赖' in registry_module.get_state('b-plugin').load_error


def test_dependent_of_broken_plugin_fails_with_dependency_chain_message(tmp_path, monkeypatch):
    _make_plugin(tmp_path, 'middle-plugin', requires={'broken-plugin': '*'})
    _make_plugin(tmp_path, 'top-plugin', requires={'middle-plugin': '*'})
    write_plugin(tmp_path, 'broken-plugin', backend='raise RuntimeError("boom")\n')
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))

    summary = registry_module.load_all(Flask('deps-test'))

    assert summary['failed'] == ['broken-plugin', 'middle-plugin', 'top-plugin']
    assert registry_module.get_state('middle-plugin').load_error == '依赖链中存在无法加载的插件'
    assert registry_module.get_state('top-plugin').load_error == '依赖链中存在无法加载的插件'


def test_plugins_without_requires_load_normally(tmp_path, monkeypatch, _isolate_registry):
    _make_plugin(tmp_path, 'solo-plugin')
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))

    summary = registry_module.load_all(Flask('deps-test'))

    assert summary['loaded'] == ['solo-plugin']
    assert _isolate_registry == ['solo-plugin']


def test_resolve_dependencies_returns_topological_order(tmp_path):
    candidates = {}
    for plugin_id, requires in (
        ('c-plugin', {'b-plugin': '>=0.1.0'}),
        ('b-plugin', {'a-plugin': '>=0.1.0'}),
        ('a-plugin', {}),
    ):
        manifest = base_manifest(plugin_id, requires=requires) if requires else base_manifest(plugin_id)
        plugin_dir = write_plugin(tmp_path, plugin_id, manifest=manifest)
        candidates[plugin_id] = {
            'dir': plugin_dir,
            'manifest': PluginManifest.load(plugin_dir),
            'enabled': True,
        }

    order, errors = registry_module.resolve_dependencies(candidates)

    assert errors == {}
    assert order == ['a-plugin', 'b-plugin', 'c-plugin']


def test_frontend_only_plugin_can_be_a_dependency(tmp_path, monkeypatch, _isolate_registry):
    write_plugin(
        tmp_path, 'theme-plugin',
        manifest=base_manifest('theme-plugin', backend={}),
        backend=None,
        css=default_css('theme-plugin'),
    )
    _make_plugin(tmp_path, 'child-plugin', requires={'theme-plugin': '>=0.1.0'})
    monkeypatch.setattr(registry_module, 'plugins_dir', lambda: str(tmp_path))

    summary = registry_module.load_all(Flask('deps-test'))

    assert sorted(summary['loaded']) == ['child-plugin', 'theme-plugin']
    assert summary['failed'] == []
