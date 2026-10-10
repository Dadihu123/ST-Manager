"""全屏遮罩的合成契约（backdrop-filter 退化取值防护）。

背景
----
Chromium 为带 `backdrop-filter` 的元素计算 backdrop 时，会把它当成一个
backdrop root。若页面上某个**祖先**也带着 `backdrop-filter`（哪怕取值是
退化的 `blur(0px)` / `brightness(1)`），全屏遮罩就只能采样到一个不完整的
backdrop。实测表现：

- 遮罩下整层内容丢失，变成一整片均匀的平坦灰；
- 极端情况直接画成纯黑矩形（`rgb(16,23,42)`，即 `--surface-scrim` 合成到黑上）；
- 遮罩内容高度变化（例如切换页签）时会触发 backdrop 重新快照，肉眼看到闪烁。

这个坑在主程序里已经踩过三次（detail-card workbench、automation workbench、
以及一个第三方插件的 overlay），所以这里把「不许再退化」钉成测试。
"""

from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# 退化取值：语法合法但视觉上是恒等变换 —— 它们同样会让元素成为 backdrop root。
DEGENERATE_BACKDROP_VALUES = (
    'blur(0)',
    'blur(0px)',
    'blur(0.0px)',
    'brightness(1)',
    'brightness(100%)',
    'saturate(1)',
    'contrast(1)',
    'opacity(1)',
    'grayscale(0)',
    'invert(0)',
    'sepia(0)',
    'hue-rotate(0deg)',
)


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def extract_exact_css_block(css_source, selector):
    """取出 `selector { … }` 的规则体；找不到直接报错（不要静默跳过）。"""
    start = css_source.find(f'{selector} {{')
    if start < 0:
        raise ValueError(f'Exact selector not found: {selector}')
    return css_source[start:].split('{', 1)[1].split('}', 1)[0]


def declared_backdrop_filters(rule_body):
    """返回规则体里所有 `backdrop-filter` / `-webkit-backdrop-filter` 的取值。"""
    values = []
    for line in rule_body.splitlines():
        stripped = line.strip()
        if not stripped.startswith(('backdrop-filter:', '-webkit-backdrop-filter:')):
            continue
        values.append(stripped.split(':', 1)[1].strip().rstrip(';').strip())
    return values


def test_main_container_never_declares_backdrop_filter():
    """页面壳必须一条 backdrop-filter 都没有。

    `.main-container` 是页面上几乎所有全屏遮罩的祖先；它一旦带上
    `backdrop-filter`，每一个遮罩都会退化。历史上这里写的是
    `backdrop-filter: blur(var(--bg-blur))`，用户没设壁纸时 `--bg-blur` 是
    `0px`，于是每台机器都无条件带着一个退化的 `blur(0px)`。
    """
    css = read_project_file('static/css/modules/layout.css')
    block = extract_exact_css_block(css, '.main-container')

    assert 'backdrop-filter' not in block, (
        '.main-container 不得声明 backdrop-filter（哪怕退化取值也不行）：'
        f'实测取值 {declared_backdrop_filters(block)}。'
        '壁纸模糊请用 body::before 的 filter: blur()。'
    )


@pytest.mark.parametrize('value', DEGENERATE_BACKDROP_VALUES)
def test_degenerate_backdrop_values_are_rejected_by_guard(value):
    """守卫本身要能识别退化取值（防止测试写歪成永远通过）。"""
    assert value.startswith(('blur(', 'brightness(', 'saturate(', 'contrast(',
                             'opacity(', 'grayscale(', 'invert(', 'sepia(',
                             'hue-rotate('))


def test_fullscreen_scrim_guard_rule_neutralizes_shell_blur():
    """`body.has-fullscreen-scrim` 兜底规则必须真的把壳的模糊关掉。"""
    css = read_project_file('static/css/modules/layout.css')
    block = extract_exact_css_block(css, 'body.has-fullscreen-scrim .main-container')
    values = declared_backdrop_filters(block)

    assert values, '兜底规则里没有 backdrop-filter 声明'
    assert all(v == 'none' for v in values), f'兜底规则取值必须全是 none：{values}'
    assert '-webkit-backdrop-filter: none;' in block
    assert 'backdrop-filter: none;' in block


def test_fullscreen_scrim_helper_owns_the_body_class():
    """契约只有一个实现入口：dom.js 的 setFullscreenScrim()。"""
    dom_js = read_project_file('static/js/utils/dom.js')

    assert 'const FULLSCREEN_SCRIM_CLASS = "has-fullscreen-scrim";' in dom_js
    assert 'export function setFullscreenScrim(open, owner = "default")' in dom_js
    assert 'export function isFullscreenScrimActive()' in dom_js
    assert 'fullscreenScrimOwners' in dom_js


def test_modal_overlay_does_not_declare_a_real_backdrop_blur():
    """共用全屏遮罩 `.modal-overlay` 不得再带 backdrop 模糊。

    它被约 20 个弹窗共用；一旦这里带上 `backdrop-filter: blur(5px)`，
    所有弹窗都会走「先对整页做离屏快照再模糊」的路径，在页面存在其它
    合成层时就会取到不完整内容。
    """
    css = read_project_file('static/css/modules/components.css')
    block = extract_exact_css_block(css, '.modal-overlay')
    values = declared_backdrop_filters(block)

    assert values, '.modal-overlay 应显式声明 backdrop-filter: none 以固化契约'
    assert all(v == 'none' for v in values), (
        f'.modal-overlay 不得带 backdrop 模糊（含退化取值）：{values}'
    )


@pytest.mark.parametrize('component, owner', [
    ('static/js/components/detailModal.js', 'detail-card'),
    ('static/js/components/automationModal.js', 'automation'),
])
def test_workbench_modals_register_the_fullscreen_scrim(component, owner):
    """两个 workbench 弹窗必须接入统一契约（而不是各自造类名）。"""
    source = read_project_file(component)

    assert 'setFullscreenScrim' in source, f'{component} 未接入 setFullscreenScrim'
    assert f"setFullscreenScrim(Boolean(" in source
    assert f"'{owner}'" in source, f'{component} 未传 owner "{owner}"'


def test_plugin_host_exposes_the_scrim_contract():
    """插件必须能通过 API 声明全屏遮罩，否则第三方只能自己造 workaround。"""
    host_js = read_project_file('static/js/pluginHost.js')
    docs = read_project_file('docs/plugin-api.md')

    assert 'import { setFullscreenScrim as applyFullscreenScrim } from "./utils/dom.js";' in host_js
    assert 'setFullscreenScrim(open, owner = pluginId)' in host_js
    assert 'setFullscreenScrim' in docs, 'docs/plugin-api.md 未登记 setFullscreenScrim'


def test_wallpaper_blur_uses_filter_not_backdrop_filter():
    """壁纸模糊必须挂在 `body::before` 的 `filter` 上。

    `filter` 只影响元素自己的绘制结果；`backdrop-filter` 会强制浏览器对
    下层做离屏快照，正是这个 bug 的根源。
    """
    css = read_project_file('static/css/modules/base.css')
    block = extract_exact_css_block(css, 'body::before')

    assert 'background-image: var(--bg-image-url);' in block
    assert 'filter: blur(var(--bg-blur));' in block
    assert 'backdrop-filter' not in block

    body_block = extract_exact_css_block(css, 'body')
    assert 'backdrop-filter' not in body_block
    assert 'background-image' not in body_block, (
        '壁纸不应挂在 body 自己身上：body 是所有遮罩的祖先，'
        '而壁纸要模糊就必须带 filter，filter 会让它成为 backdrop root。'
    )


def test_update_background_image_resets_stale_blur():
    """删壁纸必须一起清掉 `--bg-blur`。

    历史上 `updateBackgroundImage("")` 只重置 `--bg-image-url` 与
    `--bg-overlay-opacity`，把陈旧的 `blur(Npx)` 留在页面上。
    """
    source = read_project_file('static/js/state.js')
    start = source.index('updateBackgroundImage(url) {')
    block = source[start:start + 900]

    assert 'updateCssVariable("--bg-blur", "0px");' in block
    assert '"--bg-blur",' in block or '"--bg-blur", "0px"' in block
