"""F11 静态检查：插件样式作用域（设计文档 8.4 / 13.1）。

另含 F13 / F15 的声明层检查（`scan_css_declarations`）。
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins.installer import (
    resolve_known_tokens,
    scan_css_declarations,
    scan_css_scope,
    scan_style_declarations,
    scan_style_scope,
)
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


# ---------------------------------------------------------------------------
# F13 / F15 声明层检查（`scan_css_declarations`）
#
# 与作用域检查的关键差异：**必须进入 `@media` 内部**。移动端分支里的
# `position: fixed` 同样是插件自绘浮层，漏掉就等于没检查。
# ---------------------------------------------------------------------------


def _known_tokens():
    return resolve_known_tokens()


def test_declaration_scan_passes_clean_scoped_css(tmp_path):
    css = _write_css(
        tmp_path,
        '.plugin-demo-plugin .card {\n'
        '  color: var(--content-primary);\n'
        '  z-index: var(--z-modal);\n'
        '}\n',
    )

    assert scan_css_declarations(css, 'demo-plugin', known_tokens=_known_tokens()) == {}


def test_position_fixed_is_reported(tmp_path):
    css = _write_css(tmp_path, '.plugin-demo-plugin .launcher { position: fixed; }\n')

    result = scan_css_declarations(css, 'demo-plugin', known_tokens=_known_tokens())

    assert len(result['position_fixed']) == 1
    assert 'position: fixed' in result['position_fixed'][0]


def test_position_fixed_inside_media_is_reported(tmp_path):
    """核心用例：`@media` 内的 `position: fixed` 必须被抓到。"""
    css = _write_css(
        tmp_path,
        '@media (max-width: 600px) {\n'
        '  .plugin-demo-plugin .sheet { position: fixed; inset: 0; }\n'
        '}\n',
    )

    result = scan_css_declarations(css, 'demo-plugin', known_tokens=_known_tokens())

    assert len(result['position_fixed']) == 1
    assert '.plugin-demo-plugin .sheet' in result['position_fixed'][0]


def test_position_fixed_inside_supports_and_layer_is_reported(tmp_path):
    css = _write_css(
        tmp_path,
        '@supports (display: grid) {\n'
        '  .plugin-demo-plugin .a { position: fixed; }\n'
        '}\n'
        '@layer base {\n'
        '  .plugin-demo-plugin .b { position: fixed; }\n'
        '}\n'
        '@container (min-width: 400px) {\n'
        '  .plugin-demo-plugin .c { position: fixed; }\n'
        '}\n',
    )

    result = scan_css_declarations(css, 'demo-plugin', known_tokens=_known_tokens())

    assert len(result['position_fixed']) == 3


def test_keyframes_and_font_face_are_skipped(tmp_path):
    css = _write_css(
        tmp_path,
        '@keyframes spin {\n'
        '  from { position: fixed; }\n'
        '  to { position: fixed; }\n'
        '}\n'
        "@font-face {\n  font-family: demo;\n  src: url('/static/icons/ui.svg#icon-wand');\n}\n",
    )

    assert scan_css_declarations(css, 'demo-plugin', known_tokens=_known_tokens()) == {}


def test_relative_position_is_not_reported(tmp_path):
    css = _write_css(tmp_path, '.plugin-demo-plugin .card { position: relative; }\n')

    assert 'position_fixed' not in scan_css_declarations(
        css, 'demo-plugin', known_tokens=_known_tokens(),
    )


def test_unknown_token_without_fallback_is_reported(tmp_path):
    css = _write_css(tmp_path, '.plugin-demo-plugin .card { color: var(--nope-not-real); }\n')

    result = scan_css_declarations(css, 'demo-plugin', known_tokens=_known_tokens())

    assert len(result['unknown_tokens']) == 1
    assert '--nope-not-real' in result['unknown_tokens'][0]


def test_unknown_token_with_fallback_is_allowed(tmp_path):
    css = _write_css(tmp_path, '.plugin-demo-plugin .card { color: var(--nope, red); }\n')

    assert 'unknown_tokens' not in scan_css_declarations(
        css, 'demo-plugin', known_tokens=_known_tokens(),
    )


def test_known_token_is_allowed(tmp_path):
    css = _write_css(tmp_path, '.plugin-demo-plugin .card { color: var(--content-primary); }\n')

    assert 'unknown_tokens' not in scan_css_declarations(
        css, 'demo-plugin', known_tokens=_known_tokens(),
    )


def test_unknown_token_inside_media_is_reported(tmp_path):
    css = _write_css(
        tmp_path,
        '@media print {\n  .plugin-demo-plugin .x { color: var(--nope-here); }\n}\n',
    )

    result = scan_css_declarations(css, 'demo-plugin', known_tokens=_known_tokens())

    assert len(result['unknown_tokens']) == 1


def test_important_on_scoped_selector_is_allowed(tmp_path):
    css = _write_css(tmp_path, '.plugin-demo-plugin .card { color: red !important; }\n')

    assert 'important' not in scan_css_declarations(
        css, 'demo-plugin', known_tokens=_known_tokens(),
    )


def test_important_on_bare_selector_is_reported(tmp_path):
    css = _write_css(tmp_path, '.card { color: red !important; }\n')

    result = scan_css_declarations(css, 'demo-plugin', known_tokens=_known_tokens())

    assert len(result['important']) == 1
    assert '.card' in result['important'][0]


def test_hardcoded_sprite_path_is_reported(tmp_path):
    css = _write_css(
        tmp_path,
        ".plugin-demo-plugin .i { background: url('/static/icons/ui.svg#icon-bolt'); }\n",
    )

    result = scan_css_declarations(css, 'demo-plugin', known_tokens=_known_tokens())

    assert len(result['hardcoded_sprite']) == 1
    assert 'hardcoded_sprite' in result


def test_relative_sprite_path_is_reported(tmp_path):
    css = _write_css(
        tmp_path,
        '.plugin-demo-plugin .i { mask: url(icons/detail.svg#icon-info); }\n',
    )

    result = scan_css_declarations(css, 'demo-plugin', known_tokens=_known_tokens())

    assert len(result['hardcoded_sprite']) == 1


def test_plugin_own_asset_url_is_allowed(tmp_path):
    css = _write_css(
        tmp_path,
        ".plugin-demo-plugin .i { background: url('assets/logo.svg'); }\n",
    )

    assert 'hardcoded_sprite' not in scan_css_declarations(
        css, 'demo-plugin', known_tokens=_known_tokens(),
    )


def test_missing_file_reports_read_error(tmp_path):
    result = scan_css_declarations(str(tmp_path / 'missing.css'), 'demo-plugin')

    assert 'read_error' in result
    assert '读取失败' in result['read_error'][0]


def test_comments_do_not_produce_findings(tmp_path):
    css = _write_css(
        tmp_path,
        '/* .bare { position: fixed; color: var(--nope) !important; } */\n'
        '.plugin-demo-plugin { color: red; }\n',
    )

    assert scan_css_declarations(css, 'demo-plugin', known_tokens=_known_tokens()) == {}


def test_scan_style_declarations_reports_relative_path(tmp_path):
    plugin_dir = write_plugin(
        tmp_path, 'demo-plugin',
        css='.plugin-demo-plugin .launcher { position: fixed; }\n',
    )
    manifest = PluginManifest.load(plugin_dir)

    warnings = scan_style_declarations(manifest, known_tokens=_known_tokens())

    assert 'frontend/plugin.css' in warnings
    assert warnings['frontend/plugin.css']['position_fixed']


def test_scan_style_declarations_passes_clean_css(tmp_path):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    manifest = PluginManifest.load(plugin_dir)

    assert scan_style_declarations(manifest, known_tokens=_known_tokens()) == {}


def test_resolve_known_tokens_reads_host_variables():
    tokens = resolve_known_tokens()

    assert '--content-primary' in tokens
    assert '--z-modal' in tokens
    assert '--accent-main' in tokens
