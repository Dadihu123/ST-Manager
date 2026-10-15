"""全局悬浮提示（tooltip）契约测试。

背景：全仓 500+ 处提示都写成原生 `title` 属性，浏览器渲染的是系统默认白底方框。
`static/js/utils/tooltip.js` 在运行时把 `title` 迁移为 `data-tooltip`，再由
`static/css/modules/tooltip.css` 的 `.ui-tooltip` 浮层呈现。

这里锁死的是「浏览器不会报错、但会静默退化」的几类问题：

- 浮层样式没被 `style.css` 引入 → 提示完全不出现（或退化成无样式文本）；
- 浮层写死颜色 / 写死 z-index → 主题切换与层级约定脱节；
- 浮层没关掉 `pointer-events` → 它会挡住自己下面按钮的点击；
- 迁移后既有 `[title="…"]` 选择器失配 → 悬停瞬间按钮掉尺寸、掉危险色；
- 迁移把 `title` 从 `<iframe>` / 图标按钮上摘掉却不补可访问名。
"""

from pathlib import Path
import re

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TOOLTIP_CSS = 'static/css/modules/tooltip.css'
TOOLTIP_JS = 'static/js/utils/tooltip.js'
STYLE_ENTRY = 'static/css/style.css'
VARIABLES_CSS = 'static/css/modules/variables.css'


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def strip_css_comments(source):
    return re.sub(r'/\*.*?\*/', '', source, flags=re.S)


# --------------------------------------------------------------- 样式接入


def test_tooltip_stylesheet_is_registered_in_entry_css():
    assert 'modules/tooltip.css' in read_project_file(STYLE_ENTRY)


def test_tooltip_css_has_no_hardcoded_colors_or_z_index_literals():
    css = strip_css_comments(read_project_file(TOOLTIP_CSS))

    assert not re.search(r'#[0-9a-fA-F]{3,8}\b', css), '提示浮层不应写死十六进制颜色'
    assert not re.search(r'\brgba?\(', css), '提示浮层不应写死 rgb() 颜色'
    assert not re.search(r'z-index:\s*\d+', css), '提示浮层层级必须走 --z-* 令牌'
    assert 'z-index: var(--z-tooltip);' in css


def test_tooltip_css_uses_glass_surface_tokens():
    css = strip_css_comments(read_project_file(TOOLTIP_CSS))

    for token in (
        'var(--surface-overlay)',
        'var(--glass-border)',
        'var(--shadow-elevation)',
        'var(--ui-radius-sm)',
        'var(--content-primary)',
    ):
        assert token in css, token


def test_tooltip_css_is_passive_and_hidden_by_default():
    """浮层必须默认隐藏、且不参与命中测试，否则会挡住它下面的按钮。"""
    css = strip_css_comments(read_project_file(TOOLTIP_CSS))
    base_block = css.split('.ui-tooltip {', 1)[1].split('}', 1)[0]

    assert 'pointer-events: none;' in base_block
    assert 'visibility: hidden;' in base_block
    assert 'opacity: 0;' in base_block
    assert 'position: fixed;' in base_block

    visible_block = css.split('.ui-tooltip.is-visible {', 1)[1].split('}', 1)[0]
    assert 'visibility: visible;' in visible_block
    assert 'opacity: 1;' in visible_block


def test_tooltip_css_does_not_clip_its_own_arrow():
    """浮层本体一旦 `overflow: hidden`，伸到框外的箭头会被裁掉。"""
    css = strip_css_comments(read_project_file(TOOLTIP_CSS))
    base_block = css.split('.ui-tooltip {', 1)[1].split('}', 1)[0]

    assert 'overflow: hidden' not in base_block
    assert '.ui-tooltip__text {' in css
    assert 'overflow: hidden;' in css.split('.ui-tooltip__text {', 1)[1].split('}', 1)[0]


def test_tooltip_css_defines_arrow_for_every_placement():
    css = strip_css_comments(read_project_file(TOOLTIP_CSS))

    for placement in ('top', 'bottom', 'left', 'right'):
        assert f'.ui-tooltip[data-placement="{placement}"] .ui-tooltip__arrow' in css
        assert f'.ui-tooltip[data-placement="{placement}"] {{' in css


def test_tooltip_css_respects_reduced_motion():
    css = read_project_file(TOOLTIP_CSS)

    assert '@media (prefers-reduced-motion: reduce)' in css
    reduced_block = css.split('@media (prefers-reduced-motion: reduce) {', 1)[1]
    assert 'transition: none;' in reduced_block


# ------------------------------------------------------------------ 层级


def test_tooltip_z_index_token_sits_above_modals_and_avoids_plugin_band():
    variables = read_project_file(VARIABLES_CSS)
    match = re.search(r'--z-tooltip:\s*(\d+)', variables)
    assert match is not None, '缺少 --z-tooltip 令牌'
    value = int(match.group(1))

    def token_value(name):
        found = re.search(rf'{re.escape(name)}:\s*(\d+)', variables)
        assert found is not None, name
        return int(found.group(1))

    assert value > token_value('--z-modal-popover'), '提示必须盖得住模态弹出层'
    assert value > token_value('--z-chat-reader'), '提示必须盖得住聊天阅读器'
    assert not (800 <= value <= 2100), '不得落在插件硬编码层级区间'
    assert '.z-tooltip {' in variables


# ------------------------------------------------- 迁移不得破坏既有选择器


def test_title_based_css_selectors_also_match_migrated_attribute():
    """运行时 `title` 会变成 `data-tooltip`，按 title 写死的规则必须并列匹配。"""
    expectations = {
        'static/css/modules/modal-automation.css': (
            'button[title="关闭"]',
            'button[data-tooltip="关闭"]',
        ),
        'static/css/modules/detail-card-workbench.css': (
            "button[title^='删除']",
            "button[data-tooltip^='删除']",
        ),
        'static/css/modules/view-wi.css': (
            'button[title*="关闭"]',
            'button[data-tooltip*="关闭"]',
        ),
    }

    for relative_path, (title_selector, migrated_selector) in expectations.items():
        css = read_project_file(relative_path)
        assert title_selector in css, relative_path
        assert migrated_selector in css, relative_path


# --------------------------------------------------------------- 前端接入


def test_tooltip_module_is_wired_into_app_entry():
    app_source = read_project_file('static/js/app.js')

    assert 'import { initTooltipSystem } from "./utils/tooltip.js";' in app_source
    assert 'initTooltipSystem();' in app_source


def test_tooltip_module_is_idempotent_and_uses_capture_delegation():
    source = read_project_file(TOOLTIP_JS)

    # 幂等：重复初始化不得重复挂监听器
    assert '__stManagerTooltipSystemInstalled' in source
    assert 'if (window[INSTALL_FLAG]) return false;' in source

    for event_name in ('pointerover', 'pointerout', 'focusin', 'focusout', 'pointerdown', 'keydown'):
        assert f'"{event_name}"' in source, event_name
    assert source.count(', true);') >= 4, '委托监听器必须走捕获阶段'


def test_tooltip_module_never_injects_title_text_as_html():
    """`title` 文案来自模板与插件，任何情况下都不能被当作 HTML 解析。"""
    source = read_project_file(TOOLTIP_JS)

    assert 'textContent' in source
    assert 'innerHTML' not in source
    assert 'insertAdjacentHTML' not in source


def test_tooltip_module_skips_touch_pointers():
    source = read_project_file(TOOLTIP_JS)

    assert 'event.pointerType === "touch"' in source


def test_tooltip_module_preserves_accessible_name_for_nameless_elements():
    source = read_project_file(TOOLTIP_JS)

    assert 'needsAccessibleNameFallback' in source
    assert 'aria-label' in source
    # 表单控件靠 <label>/placeholder，补 aria-label 反而会覆盖正确的名字
    assert 'FORM_CONTROL_TAGS' in source
    assert 'aria-labelledby' in source


def test_tooltip_module_declares_its_public_attribute_contract():
    source = read_project_file(TOOLTIP_JS)

    for contract in (
        'data-tooltip',
        'data-tooltip-placement',
        'data-tooltip-disabled',
    ):
        assert contract in source, contract


def test_tooltip_module_keeps_placement_values_in_sync_with_css():
    source = read_project_file(TOOLTIP_JS)
    css = read_project_file(TOOLTIP_CSS)

    match = re.search(r'const PLACEMENTS = \[([^\]]+)\]', source)
    assert match is not None, '缺少 PLACEMENTS 常量'
    placements = re.findall(r'"([a-z]+)"', match.group(1))
    assert placements == ['top', 'bottom', 'left', 'right']

    for placement in placements:
        assert f'data-placement="{placement}"' in css, placement


@pytest.mark.parametrize('attribute', ['data-tooltip', 'data-tooltip-placement', 'data-tooltip-disabled'])
def test_tooltip_attributes_are_not_confiscated_by_plugin_manifest_rules(attribute):
    """`entries[]` 是严格白名单，但 tooltip 契约挂在普通 DOM 元素上，不应被误伤。"""
    manifest_source = read_project_file('core/plugins/manifest.py')

    assert attribute not in manifest_source
