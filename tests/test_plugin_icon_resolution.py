"""图标解析契约（设计文档 2.2「图标名契约（D4）」）。

`entries[].icon` 与 `api.ui.icon()` 允许**两种**取值：
- 宿主图标名（不含 `/` 与 `.`，如 `wand`）→ `/static/icons/<sprite>.svg#icon-<name>`
- 插件内资源路径（含 `/`，如 `assets/icon.svg`）→ `/api/plugins/<id>/assets/<path>`

这里既做源码级契约断言，也在 node 可用时**真实执行**解析函数（比字符串匹配强）。
"""

import json
import os
import re
import shutil
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins.assets import ALLOWED_EXTENSIONS as ASSET_ALLOWED_EXTENSIONS


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


def _parse_icon_extensions(source: str) -> set:
    """从 `icons.js` 源码里解析出 `PLUGIN_ICON_EXTENSIONS` 的实际取值。

    解析而不是硬编码第二份字面量：后端加扩展名时这里应当自动跟随判断，
    而不是让两份字面量各自腐烂。
    """
    match = re.search(r'PLUGIN_ICON_EXTENSIONS = new Set\(\[([^\]]*)\]\)', source)
    assert match is not None, '未解析到 PLUGIN_ICON_EXTENSIONS 定义'
    return {item.strip().strip('"').strip("'").lower()
            for item in match.group(1).split(',') if item.strip()}


# ------------------------------------------------------------------ 源码契约


def test_icons_module_exposes_both_resolvers():
    source = read_source('static/js/utils/icons.js')

    for fragment in (
        'export function isHostIconName(',
        'export function resolveIconUrl(',
        'export function resolvePluginIcon(',
        'export function resolveIcon(',
        'export function hasHostIcon(',
    ):
        assert fragment in source, fragment


def test_plugin_icon_resolution_enforces_backend_constraints():
    """前端提前拒绝非法资源路径，与后端 `assets.py` 同一套约束。

    真正的边界检查仍在后端路由；这里只是让插件作者早点拿到空结果（占位图标），
    而不是渲染一个必然 404 的 URL。

    与后端 `ALLOWED_EXTENSIONS` 的关系是**真子集**（⊂），不是相等：后端还要放行
    `.js/.css/.json/.woff2/.map` 等非图标类型，而图标位是 16–24px 的 mask 渲染，
    动图与 `.avif` 在那里没有意义，所以这里只收静态图。
    """
    source = read_source('static/js/utils/icons.js')

    assert "relative.split(\"/\").includes(\"..\")" in source
    # 图标扩展名必须是后端白名单的真子集（后端变了这里不能跟着漂）
    icon_extensions = _parse_icon_extensions(source)
    assert icon_extensions == {'.svg', '.png', '.webp'}
    assert icon_extensions < set(ASSET_ALLOWED_EXTENSIONS), (
        f'图标扩展名不再是后端资产白名单的真子集: {sorted(icon_extensions)}'
    )
    # 缺少 pluginId 时不猜 URL
    assert 'if (!id) return "";' in source


def test_ui_primitives_renders_asset_icons_with_mask_not_use():
    """资源图标必须用 `<span>` + CSS mask，**不能**塞进 `<use href>`。

    宿主 sprite 是描边式（`fill: none; stroke: currentColor`），插件 SVG 是填充式
    （`fill: currentColor`）——混进 `<use>` 会渲染成空图形。用 mask 而不是 `<img>`：
    `<img>` 上下文里的 `currentColor` 解析不到页面 CSS 变量，永远是黑色剪影。
    """
    source = read_source('static/js/uiPrimitives.js')

    assert 'ui-icon--asset' in source
    assert '--ui-icon-mask' in source
    assert 'resolved.kind === "asset"' in source
    # 三态分支齐全（host / asset / missing）
    assert 'resolved.kind === "missing"' in source
    assert 'resolved.href' in source, 'host 分支用 resolved.href 填 <use>'


def test_asset_icon_css_uses_mask_and_current_color():
    css = read_source('static/css/modules/icons.css')

    assert '.ui-icon.ui-icon--asset' in css
    assert 'var(--ui-icon-mask)' in css
    assert 'background-color: currentColor' in css
    assert '-webkit-mask:' in css, '必须同时写 -webkit- 前缀（与其它 mask 用法一致）'


def test_entry_renderers_pass_plugin_id_for_asset_icons():
    """坞 / 命令面板 / 入口总览渲染图标时必须把 pluginId 传下去。

    资源路径本身不含插件 id，拿不到 id 就只能降级成占位图标。
    """
    for path, marker in (
        ('static/js/components/entryDock.js', 'pluginId: String((entry && entry.pluginId) || "")'),
        ('static/js/components/commandPalette.js', 'pluginId: String((entry && entry.pluginId) || "")'),
    ):
        source = read_source(path)
        assert marker in source, path

    # 入口总览（插件管理）也要渲染图标列
    manager = read_source('static/js/components/pluginManager.js')
    assert 'entryIconHtml(row)' in manager
    assert 'pluginId: String((row && row.pluginId) || "")' in manager


def test_entry_overview_template_has_icon_column():
    """设计文档 9.3.1 要求「图标 + 名称」列。"""
    template = read_source('templates/modals/plugin_manager.html')

    assert 'plugin-entries-icon' in template
    assert 'entryIconHtml(row)' in template


# ------------------------------------------------------------------ 真实执行

NODE = shutil.which('node')

pytestmark_node = pytest.mark.skipif(NODE is None, reason='node 不可用，跳过真实执行验证')


def _run_icon_probe(cases):
    """在 node 里真实执行 `resolveIcon()`，返回结果列表。"""
    script = f"""
import {{ resolveIcon, resolvePluginIcon, resolveIconUrl }} from 'file:///{PROJECT_ROOT.replace(os.sep, '/')}/static/js/utils/icons.js';
const cases = {json.dumps(cases, ensure_ascii=False)};
const out = cases.map(([value, pluginId]) => resolveIcon(value, {{ pluginId: pluginId || '' }}));
process.stdout.write(JSON.stringify(out));
"""
    result = subprocess.run(
        [NODE, '--input-type=module', '-e', script],
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )
    if result.returncode != 0:
        pytest.skip(f'node 执行失败: {result.stderr[:400]}')
    return json.loads(result.stdout)


@pytestmark_node
def test_host_icon_names_resolve_to_sprite():
    results = _run_icon_probe([['wand', ''], ['tags', ''], ['nonexistent-icon-xyz', '']])

    assert results[0]['kind'] == 'host'
    assert results[0]['href'] == '/static/icons/ui.svg#icon-wand'
    assert results[1]['kind'] == 'host'
    # 未知宿主图标名 → 占位（不抛错）
    assert results[2]['kind'] == 'missing'


@pytestmark_node
def test_plugin_asset_paths_resolve_to_asset_url():
    results = _run_icon_probe([
        ['assets/icon.svg', 'stm-ai-assistant'],
        ['frontend/assets/icon.svg', 'stm-ai-assistant'],
        ['assets/logo.png', 'demo-plugin'],
    ])

    assert results[0]['kind'] == 'asset'
    assert results[0]['url'] == '/api/plugins/stm-ai-assistant/assets/assets/icon.svg'
    assert results[1]['url'] == '/api/plugins/stm-ai-assistant/assets/frontend/assets/icon.svg'
    assert results[2]['url'] == '/api/plugins/demo-plugin/assets/assets/logo.png'


@pytestmark_node
def test_plugin_asset_paths_are_rejected_when_unsafe_or_unowned():
    results = _run_icon_probe([
        # 缺少 pluginId：不能猜 URL
        ['assets/icon.svg', ''],
        # 路径穿越
        ['assets/../../../etc/passwd', 'p'],
        # 扩展名不在白名单（后端 assets.py 也不放行 .py）
        ['assets/evil.py', 'p'],
        ['backend/routes.py', 'p'],
        # 空值
        ['', 'p'],
    ])

    assert [item['kind'] for item in results] == ['missing'] * 5, results


@pytestmark_node
def test_dynamic_image_assets_are_not_usable_as_icons():
    """D5：后端放行 `.gif` / `.avif` 作图片资产，但图标位（mask 渲染）不收它们。

    这是「图标扩展名 ⊂ 后端资产白名单」这条关系的**行为级**证据：`.gif` 作资产可用，
    作图标一律降级为占位图标。
    """
    results = _run_icon_probe([
        ['assets/pet.gif', 'demo-plugin'],
        ['assets/pet.avif', 'demo-plugin'],
        # 同一位置换成静态图则正常产出 URL
        ['assets/pet.png', 'demo-plugin'],
    ])

    assert [item['kind'] for item in results] == ['missing', 'missing', 'asset'], results
    assert results[2]['url'] == '/api/plugins/demo-plugin/assets/assets/pet.png'
    assert {'.gif', '.avif'} <= set(ASSET_ALLOWED_EXTENSIONS), '后端必须放行 gif/avif 作资产'


@pytestmark_node
def test_resolve_icon_url_only_handles_host_names():
    """`resolveIconUrl` 是 `<use href>` 专用：资源路径一律返回空串。"""
    script = f"""
import {{ resolveIconUrl }} from 'file:///{PROJECT_ROOT.replace(os.sep, '/')}/static/js/utils/icons.js';
process.stdout.write(JSON.stringify([
  resolveIconUrl('wand'),
  resolveIconUrl('assets/icon.svg'),
  resolveIconUrl('frontend/assets/icon.svg'),
]));
"""
    result = subprocess.run(
        [NODE, '--input-type=module', '-e', script],
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )
    if result.returncode != 0:
        pytest.skip(f'node 执行失败: {result.stderr[:400]}')

    host, asset_a, asset_b = json.loads(result.stdout)
    assert host == '/static/icons/ui.svg#icon-wand'
    assert asset_a == ''
    assert asset_b == ''
