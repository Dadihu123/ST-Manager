"""F11 静态检查：插件样式作用域（设计文档 8.4 / 13.1）。"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins.installer import scan_css_scope, scan_style_scope
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import write_plugin


def _write_css(tmp_path, source):
    path = tmp_path / 'style.css'
    path.write_text(source, encoding='utf-8')
    return str(path)


def test_scoped_selector_passes(tmp_path):
    css = _write_css(tmp_path, '.plugin-demo-plugin .card { border: 1px solid red; }\n')

    assert scan_css_scope(css, 'demo-plugin') == []


def test_attribute_scope_passes(tmp_path):
    css = _write_css(tmp_path, '[data-plugin="demo-plugin"] .card { color: red; }\n')

    assert scan_css_scope(css, 'demo-plugin') == []


def test_bare_selector_is_reported(tmp_path):
    css = _write_css(tmp_path, '.card { border: 1px solid red; }\n')

    assert scan_css_scope(css, 'demo-plugin') == ['.card']


def test_element_and_body_selectors_are_reported(tmp_path):
    css = _write_css(tmp_path, 'div { color: red; }\nbody { margin: 0; }\n')

    violations = scan_css_scope(css, 'demo-plugin')

    assert 'div' in violations
    assert 'body' in violations


def test_media_block_inner_selectors_are_skipped(tmp_path):
    css = _write_css(
        tmp_path,
        '@media (max-width: 600px) {\n  .card { display: none; }\n}\n',
    )

    assert scan_css_scope(css, 'demo-plugin') == []


def test_keyframes_inner_selectors_are_skipped(tmp_path):
    css = _write_css(
        tmp_path,
        '@keyframes spin {\n  from { transform: rotate(0deg); }\n  100% { transform: rotate(360deg); }\n}\n',
    )

    assert scan_css_scope(css, 'demo-plugin') == []


def test_font_face_is_skipped(tmp_path):
    css = _write_css(tmp_path, '@font-face {\n  font-family: demo;\n  src: url(demo.woff2);\n}\n')

    assert scan_css_scope(css, 'demo-plugin') == []


def test_comments_do_not_leak_into_selector(tmp_path):
    css = _write_css(
        tmp_path,
        '/* .card is fine inside comments */\n.plugin-demo-plugin { color: red; }\n',
    )

    assert scan_css_scope(css, 'demo-plugin') == []


def test_media_with_bare_selector_then_top_level_bare_selector(tmp_path):
    css = _write_css(
        tmp_path,
        '@media print {\n  body { color: #000; }\n}\n.card { color: red; }\n',
    )

    assert scan_css_scope(css, 'demo-plugin') == ['.card']


def test_missing_file_reports_error(tmp_path):
    violations = scan_css_scope(str(tmp_path / 'missing.css'), 'demo-plugin')

    assert violations and '读取失败' in violations[0]


def test_scan_style_scope_reports_relative_path(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin', css='.card { border: 1px solid red; }\n')
    manifest = PluginManifest.load(plugin_dir)

    errors = scan_style_scope(manifest)

    assert 'frontend/plugin.css' in errors
    assert '.card' in errors['frontend/plugin.css']


def test_scan_style_scope_passes_scoped_css(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    manifest = PluginManifest.load(plugin_dir)

    assert scan_style_scope(manifest) == {}
