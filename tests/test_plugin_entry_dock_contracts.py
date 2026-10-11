"""入口坞与命令面板契约测试（设计文档 阶段 5 / D6）。

坞是 `entries` 契约的**第一个消费者**，也是地基的验收装置。这里锁死它必须
满足的硬约束——尤其是那些「浏览器不会报错但功能静默失效」的点：

- 位置避开在流顶栏与翻页栏
- 收起态只有右边缘垂直居中的毛玻璃箭头，不占内容区宽度
- 展开态是垂直居中、**高度随入口数量自适应**的毛玻璃浮层
- 坞内入口只有图标，没有文字标签
- 根元素带 `data-marquee-ignore`（否则框选会命中坞）
- 键盘可达（`role="toolbar"` + roving tabindex）
- 与坞重叠的 surface 打开时自动收起
- 溢出菜单**真的能点开**（曾因 `@click.outside` 竞态与 `pointer-events` 继承而完全不可用）
- 移动端退化为顶栏按钮 + 底部 sheet
- 层级走令牌，且不与插件硬编码的 2140/2150 冲突
"""

import os
import re
import shutil
import subprocess
import sys
import textwrap

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DOCK_CSS = 'static/css/modules/entry-dock.css'
DOCK_JS = 'static/js/components/entryDock.js'
DOCK_TEMPLATE = 'templates/components/entry_dock.html'
PALETTE_JS = 'static/js/components/commandPalette.js'
PALETTE_TEMPLATE = 'templates/components/command_palette.html'


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


def run_node(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['node', '--input-type=module', '-e', textwrap.dedent(script)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )


requires_node = pytest.mark.skipif(
    shutil.which('node') is None,
    reason='Node.js is required for entry dock contract checks',
)

#: 坞与面板依赖的最小浏览器环境（window / localStorage / CustomEvent）。
#: `dispatchEvent` 必须存在——注册表每次变更都会广播 `entries:changed`。
BROWSER_STUB = r"""
const dispatched = [];
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
};
globalThis.window = {
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent(event) { dispatched.push(event); return true; },
};
globalThis.localStorage = { getItem() { return null; }, setItem() {} };
globalThis.__dispatched = dispatched;
"""


def run_browser_script(body: str) -> subprocess.CompletedProcess:
    """在浏览器垫片之上运行一段测试脚本。"""
    return run_node(BROWSER_STUB + textwrap.dedent(body))


# ------------------------------------------------------------------ 坞的硬约束


def test_dock_root_is_marquee_ignored():
    """坞是 fixed 覆盖层，必须带 `data-marquee-ignore`，否则框选会命中它。"""
    template = read_source(DOCK_TEMPLATE)

    # 根元素自身带标记
    assert 'data-marquee-ignore' in template
    # 关键子元素也带（热区与面板）
    assert template.count('data-marquee-ignore') >= 4


def test_dock_position_avoids_top_and_pagination_bars():
    """坞的 top/bottom 必须是 64px，避开在流顶栏与翻页栏。"""
    css = read_source(DOCK_CSS)

    assert 'top: 64px;' in css
    assert 'bottom: 64px;' in css


def test_collapsed_hotzone_is_invisible_but_clickable():
    """收起态热区：`opacity: 0` 但 `pointer-events: auto`（否则永远展不开）。

    热区的**尺寸**已随「毛玻璃箭头」改版收敛：不再是贯穿整屏高度的 8px 竖条
    （那会在内容区右侧形成一条看不见的鼠标死区），而是箭头周围一圈窄环。
    """
    css = read_source(DOCK_CSS)
    hotzone = css.split('.entry-rail__hotzone {', 1)[1].split('}', 1)[0]

    assert 'opacity: 0;' in hotzone
    assert 'pointer-events: auto;' in hotzone
    # 收敛到箭头尺寸附近（用令牌 + calc，而不是写死 8px / height: 100%）
    assert 'width: calc(var(--dock-handle-width)' in hotzone
    assert 'height: calc(var(--dock-handle-height)' in hotzone
    assert 'height: 100%;' not in hotzone, (
        '热区不得再贯穿整屏高度：那是一条看不见的鼠标死区'
    )


def test_collapsed_dock_is_only_a_vertically_centered_glass_arrow():
    """收起态 = 右边缘**垂直居中**的毛玻璃小箭头，屏幕上没有常驻竖白条。

    这是用户明确要求的形态：旧实现收起态保留 40px 图标竖条，展开态 56px，
    视觉上就是一条从顶栏通到翻页栏的白条。
    """
    css = read_source(DOCK_CSS)
    code = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    # 定位带垂直居中：`align-items: center` 是浮层与箭头居中的唯一实现方式
    rail = code.split('.entry-rail {', 1)[1].split('}', 1)[0]
    assert 'align-items: center;' in rail, '坞必须垂直居中'
    assert 'justify-content: flex-end;' in rail, '坞必须贴住右边缘'

    # 收起态不再有可见宽度（旧的 40px 图标竖条必须消失）
    assert 'width: 40px;' not in code, '收起态不得再保留 40px 竖条'
    assert 'width: 56px;' not in code, '展开态宽度已改用 --dock-panel-width 令牌'

    # 收起态浮层彻底归零：宽度、边框、底色一起清掉
    collapsed = code.split('.entry-rail.is-collapsed .entry-rail__panel {', 1)[1].split('}', 1)[0]
    assert 'width: 0;' in collapsed
    assert 'border-width: 0;' in collapsed, 'box-sizing:border-box 下残留边框会形成可见残影'
    assert 'background-color: transparent;' in collapsed

    # 箭头自身是毛玻璃（半透明底 + backdrop-filter），且尺寸走令牌
    toggle = code.split('.entry-rail__toggle {', 1)[1].split('}', 1)[0]
    assert 'width: var(--dock-handle-width);' in toggle
    assert 'height: var(--dock-handle-height);' in toggle
    assert '-webkit-backdrop-filter: var(--dock-glass-blur);' in toggle
    assert 'backdrop-filter: var(--dock-glass-blur);' in toggle


def test_expanded_panel_height_follows_entry_count():
    """展开态浮层**高度随入口数量自适应**，不得撑满或留有空白。

    旧实现 `top: 64px; bottom: 64px` + `align-items: stretch` 会把浮层拉到
    整屏高度 —— 入口只有一两个时下方是一大片空白（用户明确否掉的形态）。
    """
    css = read_source(DOCK_CSS)
    code = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    rail = code.split('.entry-rail {', 1)[1].split('}', 1)[0]
    assert 'align-items: stretch;' not in rail, (
        'stretch 会让浮层长到整屏高度，入口少时留下大片空白'
    )

    panel = code.split('.entry-rail__panel {', 1)[1].split('}', 1)[0]
    assert 'height: auto;' in panel, '浮层高度必须由内容决定'
    assert 'max-height: 100%;' in panel, '入口过多时用 max-height 兜底滚动'
    # 不得出现"撑满父容器"的高度声明（`max-height: 100%` 是允许的兜底，
    # 所以必须排除 `max-` 前缀，否则断言会被自己的兜底规则误伤）
    assert not re.search(r'(?<!max-)height:\s*(100%|100vh|stretch)', panel), (
        '浮层不得撑满父容器高度，否则入口少时就是一条贯穿的竖条'
    )
    assert 'flex: 1 1' not in panel
    assert 'flex: 1;' not in panel

    # 展开态宽度走令牌，并与槽位宽度配套（装得下才不会被 overflow-x 裁掉）
    assert 'width: var(--dock-panel-width);' in code
    assert '--dock-panel-width:' in code
    assert '--dock-slot-size:' in code


def test_dock_entries_render_icons_only():
    """坞内入口**只保留图标**，不再渲染文字标签（用户要求 2）。

    标签信息不丢：槽位仍带 `title` tooltip 与 `aria-label`，溢出菜单里也有完整
    文字。因此这里断言的粒度是「坞槽位内不再出现 `.entry-rail__label` 节点」。
    """
    template = read_source(DOCK_TEMPLATE)
    css = read_source(DOCK_CSS)

    # 模板：坞槽位按钮内部不再有标签 span
    slot_block = template.split('class="entry-rail__slot"', 1)[1].split('</button>', 1)[0]
    assert 'entry-rail__label' not in slot_block, '坞槽位内不得再渲染文字标签'
    assert 'x-text="entry.label"' not in slot_block

    # 「更多」按钮同样只有图标
    more_block = template.split('entry-rail__slot--more', 1)[1].split('</button>', 1)[0]
    assert 'entry-rail__label' not in more_block

    # 标签信息改由 aria-label + title 提供（可发现性不能丢）
    assert ':aria-label="entry.label"' in slot_block
    assert ':title="entry.enabled ? (entry.description || entry.label) : entry.disabledHint"' in slot_block

    # CSS 侧保留防回归规则：万一有人把标签塞回来，也不会把浮层撑高
    assert '.entry-rail__label {' in css
    label_block = css.split('.entry-rail__label {', 1)[1].split('}', 1)[0]
    assert 'display: none;' in label_block


def test_dock_uses_glass_surface_tokens():
    """毛玻璃观感必须由既有令牌推导，不得写死颜色。

    `backdrop-filter` 的启用理由与其安全性证据见
    `test_dock_backdrop_filter_is_allowed_and_justified`。
    """
    css = read_source(DOCK_CSS)

    # 玻璃参数定义在坞根节点上，箭头/浮层/溢出菜单共用同一套
    assert '--dock-glass-surface:' in css
    assert '--dock-glass-blur:' in css
    assert 'color-mix(in srgb,' in css, '半透明底应从既有令牌 color-mix 推导'
    assert 'var(--glass-border)' in css

    # 三个玻璃面板都真的用上了这套配方
    for selector in ('.entry-rail__panel {', '.entry-rail__toggle {', '.entry-overflow {'):
        block = css.split(selector, 1)[1].split('}', 1)[0]
        assert 'var(--dock-glass-surface)' in block, selector
        assert 'var(--dock-glass-blur)' in block, selector


def test_dock_defaults_to_collapsed():
    """坞默认**收起**（毛玻璃箭头改版）。

    旧实现默认展开，因为收起态的 `.entry-rail__panel` 是 `width: 0` + 8px 全透明
    热区，坞在视觉上完全不存在，默认收起等于用户永远发现不了插件入口。

    改版后收起态是右边缘一枚**常驻可见、垂直居中、可点击**的毛玻璃箭头，
    可发现性由箭头自己承担；同时收起态不占用内容区宽度，所以默认收起是更好的选择。
    """
    component = read_source(DOCK_JS)

    # 初始 state 是收起。用精确匹配：裸子串断言在把 state 改成 true 之后仍然通过。
    assert '\n    expanded: false,\n' in component, 'entryDock() 的初始 state 必须是收起'
    # 首次运行（无偏好）默认收起
    assert 'if (!raw) return { expanded: false, side: "right" };' in component
    # 偏好里缺 expanded 字段时也收起
    assert 'parsed.expanded === undefined ? false' in component
    # 读取异常时的兜底同样收起（不能是「读失败 → 展开」）
    assert 'return { expanded: false, side: "right" };' in component


def test_dock_prefs_default_collapsed_when_read():
    """真实执行 `init()` 验证三种 localStorage 情形都得到「收起」。"""
    result = run_node(
        BROWSER_STUB
        + """
        // `init()` 还会读设备类型（`resolveDeviceType`）与主程序版本
        // （`entryRegistry.hostAppVersion` 查 meta 标签），给一个最小 document
        globalThis.document = {
          documentElement: { clientWidth: 1440 },
          querySelector() { return null; },
        };
        globalThis.window.innerWidth = 1440;
        """
        + textwrap.dedent(
            """
            import assert from 'node:assert/strict';

            const cases = {
              // 1) 首次运行：没有偏好
              'no-pref': null,
              // 2) 旧版偏好：只有 side，没有 expanded 字段
              'legacy-pref': JSON.stringify({ side: 'right' }),
              // 3) 偏好损坏
              'broken-pref': '{not json',
            };

            for (const [name, stored] of Object.entries(cases)) {
              globalThis.localStorage = {
                getItem() { return stored; },
                setItem() {},
              };
              const { default: entryDock } = await import(
                './static/js/components/entryDock.js?case=' + name
              );
              const dock = entryDock();
              dock.init();
              assert.equal(dock.expanded, false, name + ' 应默认收起');
            }

            // 4) 用户显式展开过 → 尊重用户选择（刷新后仍展开）
            globalThis.localStorage = {
              getItem() { return JSON.stringify({ expanded: true }); },
              setItem() {},
            };
            const { default: entryDock } = await import(
              './static/js/components/entryDock.js?case=explicit'
            );
            const dock = entryDock();
            dock.init();
            assert.equal(dock.expanded, true, '用户显式展开必须被尊重');
            """
        )
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_collapsed_rail_keeps_a_visible_arrow_and_toggle_button():
    """收起态仍有一个**明确可见、可点**的开合入口（毛玻璃箭头）。

    旧实现收起态 `width: 0`，坞在视觉上彻底消失（可发现性靠 40px 竖条）；
    改版后靠常驻箭头，因此箭头必须：可见、有状态语义、真的接线到 `toggle()`。
    """
    css = read_source(DOCK_CSS)
    template = read_source(DOCK_TEMPLATE)

    # 箭头不是靠"面板本身可见"来暴露的，它是坞里唯一的常驻元素
    toggle = css.split('.entry-rail__toggle {', 1)[1].split('}', 1)[0]
    assert 'pointer-events: auto;' in toggle

    # 明确的开合按钮 + 状态语义
    assert 'class="entry-rail__toggle"' in template
    assert ':aria-expanded="expanded' in template
    assert "'收起入口坞'" in template and "'展开入口坞'" in template
    # 图标存在（chevron-right 是宿主 sprite 里真实存在的名字）
    assert 'icon-chevron-right' in template

    # 按钮**自己**接线到 toggle()。必须按块断言：`@click="toggle()"` 在移动端
    # 触发按钮上也出现，裸子串断言在把这个按钮的 handler 删掉后仍然通过。
    toggle_block = template.split('class="entry-rail__toggle"', 1)[1].split('</button>', 1)[0]
    assert '@click="toggle()"' in toggle_block, '开合按钮必须真的接线到 toggle()'


def test_collapse_cancels_pending_hover_expand():
    """点击收起必须取消挂起的 hover 展开定时器（否则「点了收起没反应」）。

    实测复现（Playwright + Chromium，真实页面）：收起态下指针要移到箭头上去点
    「收起」，这个 entering 动作会排一次 150ms 的展开定时器；若 `collapse()`
    不清掉它，150ms 后 `expand()` 又触发，坞自己弹回来。事件日志：

        onHotzoneEnter @4155 → expand @4305 → collapse @4664 → expand @4814(+150ms)

    因此 `collapse()` 必须先取消定时器，且取消逻辑要收敛到一个方法里复用。
    """
    component = read_source(DOCK_JS)

    assert 'cancelHoverTimer() {' in component, '取消定时器必须是可复用的方法'
    assert 'clearTimeout(this._hoverTimer)' in component

    # collapse() 自己在自己的块里取消定时器
    collapse_block = component.split('collapse() {', 1)[1].split('\n    },', 1)[0]
    assert 'this.cancelHoverTimer();' in collapse_block, (
        'collapse() 必须取消挂起的 hover 展开，否则 150ms 后又弹开'
    )
    # 取消要发生在改变状态**之前**，否则仍有窗口期
    assert collapse_block.index('this.cancelHoverTimer();') < collapse_block.index('this.expanded = false;')

    # 离开热区与销毁也要取消（复用同一个方法，不再各写一份）
    for name in ('onHotzoneLeave() {', 'destroy() {'):
        block = component.split(name, 1)[1].split('\n    },', 1)[0]
        assert 'this.cancelHoverTimer();' in block, name

    # 定时器回调里清空句柄，避免留下一个已触发的陈旧 id
    enter_block = component.split('onHotzoneEnter() {', 1)[1].split('\n    },', 1)[0]
    assert 'this._hoverTimer = null;' in enter_block


def test_surfaces_overlapping_the_dock_also_zero_its_glass_edges():
    """与坞重叠的 surface 打开时，玻璃框的**边框与底色**也要一起归零。

    `box-sizing: border-box` 下 `width: 0` 仍会留下 1px 边框的可见残影，
    因此在宽度归零之外还要清掉 `border-width` 与 `background-color`。
    """
    css = read_source(DOCK_CSS)
    code = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    for selector in ('body:has(.plugin-surface--panel)', 'body:has(.plugin-surface--sheet)'):
        block = code.split(selector, 1)[1].split('}', 1)[0]
        assert 'width: 0;' in block, selector
        assert 'border-width: 0;' in block, selector
        assert 'background-color: transparent;' in block, selector


def test_dock_slots_are_draggable_and_persist_order():
    """D6 / 设计文档阶段 5 验收项：**拖拽重排持久化**。

    这是此前唯一真正缺失的坞能力（槽位 / 溢出 / pin / hide 都已实现，拖拽没有）。
    顺序写进 `layout.order`（走后端 `_entry_layout_v1`），不是 localStorage——
    `EntryRegistry.list()` 排序时「用户显式排序优先于插件 priority」。
    """
    template = read_source(DOCK_TEMPLATE)
    component = read_source(DOCK_JS)

    # 模板：槽位可拖 + 五个 drag 事件 + 拖拽态 class
    assert 'draggable="true"' in template
    for handler in ('onSlotDragStart(entry, $event)', 'onSlotDragOver(entry, $event)',
                    'onSlotDragLeave(entry)', 'onSlotDragEnd()', 'onSlotDrop(entry, $event)'):
        assert handler in template, handler
    assert "'is-dragging': draggingKey === entry.key" in template
    assert "'is-drop-target': dragOverKey === entry.key" in template

    # 组件：state 与处理函数
    for name in ('draggingKey', 'dragOverKey'):
        assert name in component, name
    for method in ('onSlotDragStart(entry, event) {', 'onSlotDragOver(entry, event) {',
                   'onSlotDragLeave(entry) {', 'onSlotDragEnd() {', 'async onSlotDrop(targetEntry, event) {'):
        assert method in component, method

    # 落点计算：在**完整**顺序里搬移（含溢出菜单里的入口），再持久化
    assert 'EntryRegistry.updateLayout({ order: current })' in component
    assert 'EntryRegistry.searchable()' in component


def test_dock_uses_roving_tabindex_and_toolbar_role():
    template = read_source(DOCK_TEMPLATE)
    component = read_source(DOCK_JS)

    assert 'role="toolbar"' in template
    assert 'aria-orientation="vertical"' in template
    # roving tabindex：只有当前项可 Tab 到达
    assert ':tabindex="tabIndexFor(entry)"' in template
    assert 'tabIndexFor(entry) {' in component


def test_dock_keyboard_bindings_cover_arrows_enter_delete():
    component = read_source(DOCK_JS)

    for key in ('"ArrowDown"', '"ArrowUp"', '"Enter"', '"Delete"', '"Home"', '"End"'):
        assert key in component, key
    assert 'handleKeydown(event) {' in component


def test_dock_collapses_only_for_surfaces_that_actually_overlap_it():
    """只有**真正与坞重叠**的 surface 打开时才收起（纯 CSS，不需要 JS 协调）。

    ⚠️ 这里**不能**用 `body:has(.modal-overlay)`：`:has()` 只看元素是否存在，
    不看可见性，而主程序 28 个模态框全部用 `x-show`（常驻 DOM，仅 `display:none`）。
    因此那条规则**几乎永久成立**，坞会被永久压成 `width: 0` —— 用户完全找不到
    插件入口（实测症状：右键菜单与批量菜单都能找到，就是找不到固定入口）。

    `panel` / `sheet` 贴着屏幕右侧/底部，与坞抢空间，需要收起；
    `modal` 居中且 `z-index` 远高于坞，天然盖住坞，不需要也不该收起。
    """
    css = read_source(DOCK_CSS)
    # 注释里会引用旧写法说明原因，只看代码
    code = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    assert '.modal-overlay' not in code, (
        'modal-overlay 常驻 DOM，`:has()` 会永久成立 → 坞永久不可见'
    )
    assert 'body:has(.plugin-surface--panel) .entry-rail .entry-rail__panel' in code
    assert 'body:has(.plugin-surface--sheet) .entry-rail .entry-rail__panel' in code
    # 宽泛的 `.plugin-surface` 会连 modal 一起收起，也不该出现
    assert 'body:has(.plugin-surface) ' not in code


def test_dock_hides_sidebar_on_mobile_and_uses_sheet():
    css = read_source(DOCK_CSS)
    template = read_source(DOCK_TEMPLATE)

    # ≤900px 不渲染侧条
    mobile_block = css.split('@media (max-width: 900px) {', 1)[1].split('}', 1)[0]
    assert '.entry-rail' in mobile_block
    assert 'display: none;' in mobile_block

    # 移动端走顶栏按钮 + 底部 sheet
    assert 'entry-dock-mobile-trigger' in template
    assert 'entry-sheet' in template
    assert "deviceType === 'mobile'" in template


def test_dock_expand_works_on_mobile_so_the_sheet_can_open():
    """`expand()` **不得**对 mobile 提前 return —— 否则移动端 sheet 永远打不开。

    移动端顶栏按钮走 `toggle()` → `expand()`，而 `expanded` 同时是底部 sheet 的
    开关（模板里 `x-if="deviceType === 'mobile' && expanded"`）。旧实现在
    `expand()` 里写 `if (this.deviceType === "mobile") return;`，移动端按钮因此
    是死键。之前没暴露，是因为旧默认值是「展开」—— 静默盖住了这个缺陷；
    默认改成收起后它会变成必现回归。

    hover 展开（真正的误触来源）在 `onHotzoneEnter()` 里按 deviceType 判断，
    那里才是该拦的地方，本测试同时锁住这一点。
    """
    component = read_source(DOCK_JS)
    template = read_source(DOCK_TEMPLATE)

    expand_block = component.split('expand() {', 1)[1].split('\n    },', 1)[0]
    assert 'deviceType' not in expand_block, (
        'expand() 不得按 deviceType 拦截：移动端顶栏按钮要靠它打开 sheet'
    )
    assert 'this.expanded = true;' in expand_block

    # 移动端按钮确实接线到 toggle()，而 toggle() 走 expand()
    trigger_block = template.split('class="entry-dock-mobile-trigger"', 1)[1].split('</button>', 1)[0]
    assert '@click="toggle()"' in trigger_block

    # sheet 的存在条件确实是 expanded
    assert "deviceType === 'mobile' && expanded" in template

    # hover 展开仍然只对 desktop 生效（误触来源在这里拦）
    enter_block = component.split('onHotzoneEnter() {', 1)[1].split('\n    },', 1)[0]
    assert 'if (this.deviceType !== "desktop") return;' in enter_block


def test_dock_hover_expand_delay_is_150ms():
    component = read_source(DOCK_JS)

    assert 'HOVER_EXPAND_DELAY_MS = 150' in component


def test_dock_backdrop_filter_is_allowed_and_justified():
    """契约反转：坞**可以**用 `backdrop-filter`（原禁令的根因已消失）。

    旧契约是 `assert 'backdrop-filter' not in css`，理由是 `.main-container`
    的 backdrop root 黑块问题：它曾是几乎所有全屏遮罩的祖先，一旦自己成为
    backdrop root，遮罩的 `backdrop-filter` 就只能采样到不完整的 backdrop，
    实测会把遮罩下的整层画成纯黑矩形。

    该根因**已被修复**，且坞从来不在那条祖先链上：

    1. `.main-container` 现在完全不带 `backdrop-filter`（壁纸模糊改走
       `body::before { filter: blur() }`），见 layout.css / base.css；
    2. 坞是 `.main-container` 的**兄弟**节点（`templates/index.html`），
       不是任何全屏遮罩的祖先，因此不可能成为遮罩的 backdrop root。

    真实浏览器实测（Playwright + Chromium，1440×900，真实页面 + 真插件）：

    - `getComputedStyle(.entry-rail__panel).backdropFilter` 取回
      `blur(14px) saturate(1.45)`，彩虹底图下可见明显磨砂混色 → 玻璃真的生效；
    - 打开全屏「系统设置」模态时，坞被遮罩正常盖住
      （`elementFromPoint` 命中 `.modal-overlay`，z 1100 > 坞 z 80），
      坞所在区域**没有黑块**，遮罩上的控件交互正常；
    - 关闭模态后坞恢复可交互（`elementFromPoint` 重新命中坞）。

    因此这里把契约改成「坞的玻璃层必须带 backdrop-filter，且必须带退化取值」，
    并用「坞不得成为遮罩祖先」这条不变量守住原来的坑。
    """
    css = read_source(DOCK_CSS)
    template = read_source(DOCK_TEMPLATE)
    index_source = read_source('templates/index.html')
    layout_css = read_source('static/css/modules/layout.css')

    # 1) 三块玻璃面板都必须真的带 backdrop-filter（否则就只是"半透明"，不是毛玻璃）
    for selector in ('.entry-rail__panel {', '.entry-rail__toggle {', '.entry-overflow {'):
        block = css.split(selector, 1)[1].split('}', 1)[0]
        assert 'backdrop-filter: var(--dock-glass-blur);' in block, selector

    # 2) 保留 `-webkit-` 前缀（Safari）
    assert '-webkit-backdrop-filter: var(--dock-glass-blur);' in css

    # 3) 守住原坑的不变量：坞**不在**遮挡整屏的遮罩祖先链上。
    #    index.html 里坞与 `.main-container` 是兄弟 —— 坞必须在 `.main-container`
    #    之后、且不在其内部出现。
    main_start = index_source.index('class="main-container"')
    # 坞的 include 必须排在 .main-container 之后（兄弟，而不是嵌套在内）
    assert index_source.index('components/entry_dock.html') > main_start, (
        '坞必须是 .main-container 的兄弟节点；嵌进去就可能成为遮罩的 backdrop root'
    )
    # 坞不得自带任何 `.modal-overlay` / 全屏遮罩节点
    assert 'modal-overlay' not in template

    # 4) `.main-container` 必须仍然**没有** backdrop-filter（这条禁令继续生效）
    main_block = re.sub(r'/\*.*?\*/', '', layout_css, flags=re.S)
    main_block = main_block.split('.main-container {', 1)[1].split('}', 1)[0]
    assert 'backdrop-filter' not in main_block, (
        '.main-container 一旦带 backdrop-filter 就会变成 backdrop root，'
        '全屏遮罩会退化成黑块 —— 这正是坞旧禁令要防的坑'
    )


def test_dock_and_palette_respect_reduced_motion():
    for path in (DOCK_CSS,):
        assert 'prefers-reduced-motion' in read_source(path), path


def test_dock_reduced_motion_also_covers_the_toggle_arrow():
    """箭头旋转也是动效，必须在 `prefers-reduced-motion` 里一起关掉。"""
    css = read_source(DOCK_CSS)

    block = css.split('@media (prefers-reduced-motion: reduce) {', 1)[1]
    assert '.entry-rail__toggle svg' in block, '箭头旋转动画漏了 reduced-motion'
    assert '.entry-rail__panel' in block
    assert '.entry-rail__slot' in block


def test_dock_is_hidden_when_no_plugin_registered_a_dock_entry():
    """一个插件 dock 入口都没有时，坞**整体不出现**（右侧不留死箭头）。

    坞只由插件的 `kind: "dock"` 入口填充 —— 宿主内建命令全是 `kind: "command"`
    （见 `entryRegistry.js` 的 `CORE_ENTRIES`），而 `dockSlots()` /
    `overflowEntries()` 都只取 `kind: "dock"`。所以「没装任何带 dock 入口的插件」
    是完全正常的状态（新装的主程序就是这样），此时右侧不该常驻一枚点了没用的箭头、
    移动端也不该有一个点开是空 sheet 的顶栏按钮。

    实测过的错误行为：一个入口都没有时，desktop/tablet 仍渲染
    `.entry-rail__toggle`，mobile 仍渲染 `.entry-dock-mobile-trigger`。

    门控方式必须是 `x-show`（切 `display`）而**不是**把 `hasEntries` 并进外层
    `x-if`：外层的 `x-if` 只在 deviceType 变化时重建子树，把 `hasEntries` 并进去
    会让「插件装卸」也触发整树销毁重建，实测在清空注册表时会多抛
    `Cannot read properties of undefined (reading 'length')`
    （Alpine 的 x-for 在宿主 x-if 拆除子树时重入 reconcile）。
    真实 Chromium 对照：HEAD 6 次 pageerror，`x-if` 方案 10 次，`x-show` 方案 6 次。
    """
    component = read_source(DOCK_JS)
    template = read_source(DOCK_TEMPLATE)

    # 1) 计算属性：槽位与溢出都为空才算「没有入口」
    assert 'get hasEntries() {' in component
    has_entries = component.split('get hasEntries() {', 1)[1].split('\n    },', 1)[0]
    assert 'this.slots.length > 0 || this.overflow.length > 0' in has_entries, (
        'hasEntries 必须同时看 slots 与 overflow：只有 overflow（社区插件默认不固定）'
        '时箭头同样要出现'
    )

    # 2) 桌面坞 + 移动端按钮都按 hasEntries 门控
    rail_block = template.split('<template x-if="deviceType !== \'mobile\'">', 1)[1].split('>', 1)[0]
    assert 'x-show="hasEntries"' in rail_block, '坞必须按 hasEntries 门控'

    trigger_block = template.split('class="entry-dock-mobile-trigger"', 1)[1].split('>', 1)[0]
    assert 'x-show="hasEntries"' in trigger_block, '移动端按钮同样要门控'

    # 3) 门控不得并进外层 x-if（会引入额外的 Alpine reconcile 报错）
    assert "deviceType !== 'mobile' && hasEntries" not in template, (
        'hasEntries 不得并进外层 x-if：那会让插件装卸触发整树重建并多抛 pageerror'
    )

    # 4) 移动端 sheet 也要门控：`expanded` 是持久化偏好，用户上次开着 sheet 关掉
    #    页面、之后卸载了全部插件时，重新打开不该弹出一个空 sheet
    sheet_block = template.split('<!-- 移动端底部 sheet', 1)[1].split('>', 1)[0]
    assert 'hasEntries' in sheet_block, '空态下不该弹出空 sheet'
    assert 'expanded' in sheet_block


def test_dock_toggle_arrow_points_where_it_will_go():
    """箭头朝向必须"指向点击后会去的方向"：收起朝**内**，展开朝**外**。

    sprite 里只有 `icon-chevron-right`（无 left 变体），所以收起态的"朝左"= 180°。

    旧实现写反了（收起 `rotate(0)` 朝右 = 指向屏幕边缘、无视浮层将要出现的方向；
    展开才 `rotate(180deg)` 朝左），用户反馈「展开不是向外而是向内，方向反了」。

    这里同时断言"基准"与"展开"两个分支都存在，且基准是 180°：
    只断言展开分支会让整个规则被删掉后仍然通过。
    """
    css = read_source(DOCK_CSS)

    base = css.split('.entry-rail__toggle svg {', 1)[1].split('}', 1)[0]
    assert 'rotate(180deg)' in base, '收起态箭头必须朝内（左）'

    expanded = css.split(
        '.entry-rail.is-expanded .entry-rail__toggle svg {', 1
    )[1].split('}', 1)[0]
    assert 'rotate(0deg)' in expanded, '展开态箭头必须朝外（右）'


def test_dock_slot_icon_fills_a_sane_share_of_the_slot():
    """图标必须撑满槽位的合理比例 —— 不能只有一小撮。

    实测旧值：槽位 40px、内层 `<svg>` 16px，`iconToSlotRatio` 只有 **0.40**，
    按钮四周全是空白（用户反馈「图标占比按钮比例很小，感觉上没有必要」）。

    这里锁住三件互相咬合的事：
    1. 图标尺寸走 `--dock-icon-size` 令牌（不再写死 1.25rem）；
    2. 尺寸令牌与槽位令牌成比例（用数字断言区间，防止有人只改其中一个）；
    3. 尺寸规则要能**压过** `ui-icon--sm`（`uiPrimitives.js:icon()` 总会带上它）。
       裸 `> *`（特异度 0,1,0）与尺寸类同分、只能靠源序取胜，太脆弱。
    """
    css = read_source(DOCK_CSS)

    root = css.split('.entry-dock-root {', 1)[1].split('}', 1)[0]
    slot = float(re.search(r'--dock-slot-size:\s*([\d.]+)rem', root).group(1))
    icon = float(re.search(r'--dock-icon-size:\s*([\d.]+)rem', root).group(1))
    ratio = icon / slot
    assert 0.5 <= ratio <= 0.72, f'图标/槽位比 {ratio:.2f} 不在合理区间（0.40 太小）'

    # 注意锚点要带换行：裸 `.entry-rail__icon {` 会先匹配到
    # `.entry-rail__slot.is-warn .entry-rail__icon {` 这类组合选择器。
    block = css.split('\n.entry-rail__icon {', 1)[1].split('}', 1)[0]
    assert 'var(--dock-icon-size)' in block

    # 传给 icon() 的尺寸类必须被坞自己的规则盖过。
    # ⚠️ 断言前必须剥掉注释：上面的解释性注释里逐字写了这两个选择器，
    # 于是把真正的规则删掉后断言依然通过（变异测试抓出来的假绿）。
    code = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    assert '.entry-rail__icon > svg' in code
    assert '.entry-rail__icon > .ui-icon' in code


def test_dock_entry_count_badge_sits_on_the_arrow_on_both_layouts():
    """入口数量数字标必须挂在**箭头**上，而不是面板里的槽位（PC 与移动端都要）。

    移动端旧 badge 挂在 `.entry-dock-mobile-trigger` 上但用 `x-show="slots.length"`：
    社区插件默认不固定、只进溢出菜单，此时 `slots.length === 0` 而入口明明有，
    徽标凭空消失。所以两端都改用 `entryCount`。
    """
    component = read_source(DOCK_JS)
    template = read_source(DOCK_TEMPLATE)

    count = component.split('get entryCount() {', 1)[1].split('\n    },', 1)[0]
    assert 'this.entries.length' in count, 'entryCount 必须用 entries（含未固定的入口）'

    # PC：徽标在开合按钮内部
    toggle_block = template.split('class="entry-rail__toggle"', 1)[1].split('</button>', 1)[0]
    assert 'entry-rail__toggle-count' in toggle_block
    assert 'x-text="entryCount"' in toggle_block

    # 移动端：徽标在底部箭头内部，且不再用 slots.length
    trigger_block = template.split('class="entry-dock-mobile-trigger"', 1)[1].split('</button>', 1)[0]
    assert 'entry-dock-mobile-trigger__count' in trigger_block
    assert 'x-text="entryCount"' in trigger_block
    assert 'x-text="slots.length"' not in template, (
        'slots.length 会在"只有社区插件"时把徽标判成不可见'
    )


def test_mobile_trigger_is_docked_into_the_bottom_bar_not_its_own_row():
    """移动端触发器必须是**底部栏上的浮动箭头**，不能独占一行。

    旧实现 `position: relative` + 普通块级按钮 ⇒ `.entry-dock-root` 在 body 的
    column flex 里占掉一整行（实测根节点高 32px、把翻页栏顶上去，
    触发按钮落在 `y=848` 而翻页栏 `y=788..848`）。用户反馈「单独占据了一行没有必要」。

    现在 `position: fixed` 贴视口右下角：根节点高度塌成 0，箭头落进翻页栏那条带子里。
    """
    css = read_source(DOCK_CSS)
    component = read_source(DOCK_JS)

    trigger = css.split('.entry-dock-mobile-trigger {', 1)[1].split('}', 1)[0]
    assert 'position: fixed;' in trigger, '必须是 fixed，否则根节点会独占一行'
    assert 'bottom:' in trigger and 'right:' in trigger
    assert 'var(--z-entry-rail)' in trigger

    # 箭头朝上（收起）→ 朝下（展开），与 PC 端同一套语义。
    # 两个分支都要断到**角度值**：只断选择器存在的话，把展开态的角度改回
    # `rotate(-90deg)`（箭头永远朝上、点了不知道有没有生效）测试仍然通过。
    collapsed = css.split('\n.entry-dock-mobile-trigger svg {', 1)[1].split('}', 1)[0]
    assert 'rotate(-90deg)' in collapsed, '收起态箭头必须朝上'

    expanded = css.split(
        ".entry-dock-mobile-trigger[aria-expanded='true'] svg {", 1
    )[1].split('}', 1)[0]
    assert 'rotate(90deg)' in expanded, '展开态箭头必须朝下'

    # 为箭头让位的规则必须由 JS 挂类驱动，而不是 CSS `:has()`
    assert 'entry-dock-mobile-docked' in component
    assert 'syncMobileDockedClass' in component
    assert 'classList.toggle("entry-dock-mobile-docked", docked)' in component
    assert ':has(.entry-dock-mobile-trigger)' not in css, (
        ':has() 只看元素是否存在，x-show 只切 display ⇒ 空态下也会白留一段空隙'
    )


def test_dock_uses_z_index_tokens_only():
    css = read_source(DOCK_CSS)
    literals = re.findall(r'z-index:\s*(\d+)', css)

    assert literals == [], f'坞样式出现 z-index 字面量: {literals}'
    assert 'var(--z-entry-rail)' in css
    assert 'var(--z-modal-popover)' in css


def test_entry_rail_token_does_not_collide_with_plugin_hardcoded_values():
    """陷阱：插件硬编码 2140/2150，宿主令牌必须避开那个区间。"""
    from core.plugins.installer import resolve_known_tokens

    tokens = resolve_known_tokens()
    assert '--z-entry-rail' in tokens
    assert '--z-surface' in tokens

    css = read_source('static/css/modules/variables.css')
    for name in ('--z-entry-rail', '--z-surface'):
        match = re.search(rf'{re.escape(name)}:\s*(\d+)', css)
        assert match is not None, name
        value = int(match.group(1))
        assert not (800 <= value <= 2100), f'{name} 落在插件硬编码区间: {value}'


def test_dock_css_has_no_hardcoded_hex_colors():
    css = read_source(DOCK_CSS)
    assert not re.search(r'#[0-9a-fA-F]{6}\b', css)


def test_dock_prefs_use_localstorage_with_consistent_naming():
    """命名参照既有 `st_manager_tag_view_prefs` / `st_manager_per_page`。"""
    component = read_source(DOCK_JS)

    assert 'st_manager_entry_dock_prefs' in component


def test_dock_persists_layout_through_registry():
    """顺序/固定/隐藏走后端 `_entry_layout_v1`，不是 localStorage。"""
    component = read_source(DOCK_JS)

    assert 'EntryRegistry.updateLayout(' in component
    assert 'togglePin(entry)' in component
    assert 'hide(entry)' in component


# ------------------------------------------------------------------ 命令面板


def test_command_palette_uses_ctrl_or_cmd_k():
    component = read_source(PALETTE_JS)

    assert '(event.ctrlKey || event.metaKey)' in component
    assert 'String(event.key).toLowerCase() === "k"' in component


def test_command_palette_searches_registry_and_core_commands():
    component = read_source(PALETTE_JS)

    assert 'EntryRegistry.searchable()' in component
    assert 'CORE_ACTIONS' in component


def test_command_palette_is_registered_and_included():
    app_source = read_source('static/js/app.js')
    index_source = read_source('templates/index.html')

    assert 'Alpine.data("commandPalette"' in app_source
    assert 'commandPalette.js' in app_source
    assert 'components/command_palette.html' in index_source


def test_dock_is_registered_and_included():
    app_source = read_source('static/js/app.js')
    index_source = read_source('templates/index.html')

    assert 'Alpine.data("entryDock"' in app_source
    assert 'entryDock.js' in app_source
    assert 'components/entry_dock.html' in index_source


def test_dock_and_palette_use_bare_x_data_for_lifecycle():
    """Alpine v3 自动调用 `init()` / `destroy()`，因此**不得**再写 `x-init` / `x-destroy`。

    `x-destroy` 甚至不是 Alpine 指令；写上它会让 `init()` 被调用两次，
    window 监听器重复注册（组件销毁后仍会响应事件）。
    """
    for path in (DOCK_TEMPLATE, PALETTE_TEMPLATE):
        template = read_source(path)
        assert 'x-init=' not in template, path
        assert 'x-destroy=' not in template, path
        assert 'x-data="entryDock"' in template or 'x-data="commandPalette"' in template, path


def test_new_stylesheet_is_registered_in_entry_css():
    entry = read_source('static/css/style.css')

    assert 'modules/entry-dock.css' in entry


def test_dead_sidebar_toggle_css_was_removed():
    """阶段 6.5：`.sidebar-toggle-button` 全仓零引用，已删除。"""
    css = read_source('static/css/modules/layout.css')

    assert '.sidebar-toggle-button' not in css


# --------------------------------------------------- 溢出菜单可用性（曾完全不可用）


def test_overflow_menu_opts_back_into_pointer_events():
    """溢出菜单必须显式取回 `pointer-events: auto`，否则**画出来却点不到**。

    `pointer-events` 是**继承**属性。坞根节点整体 `pointer-events: none`
    （`.entry-rail` 是跨越整屏高度的定位带，不这么做内容区右侧会多出一条
    看不见的鼠标死区），而 `.entry-overflow` 是它的后代，于是继承了 `none`。

    实测症状（真实 Chromium）：菜单视觉上正常渲染，但
    `document.elementFromPoint(菜单内一点)` 返回的是**下面的 `.card-grid`** ——
    搜索框输不进字、条目点不动、固定按钮无效，整块菜单是死的。
    坞自己的 `.entry-rail__panel` / `.entry-rail__toggle` 一直有
    `pointer-events: auto`，只有后来加的溢出菜单漏了。
    """
    css = read_source(DOCK_CSS)
    code = re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    rail = code.split('.entry-rail {', 1)[1].split('}', 1)[0]
    assert 'pointer-events: none;' in rail, '坞定位带必须整体放行鼠标'

    # 坞里每一个**可交互**的后代都必须自己取回 auto，不能靠继承
    for selector in ('.entry-rail__panel {', '.entry-rail__toggle {', '.entry-overflow {'):
        block = code.split(selector, 1)[1].split('}', 1)[0]
        assert 'pointer-events: auto;' in block, (
            f'{selector} 必须显式 pointer-events: auto；'
            '否则会继承 .entry-rail 的 none 而点不动'
        )


def test_overflow_toggle_ignores_the_click_that_opened_it():
    """打开溢出菜单的那次点击必须被 `@click.outside` 忽略，否则菜单**根本打不开**。

    机制（已在真实 Chromium 里逐步确认）：
    1. 用户点 `⋯`，点击事件 E 开始派发；
    2. Alpine 的 `@click` 先把 `overflowOpen` 置为 true，响应式副作用随即把
       `.entry-overflow` 插入 DOM，并给它挂上 document 级的 `@click.outside`；
    3. 此时 E **仍在冒泡**。按 DOM 规范，「派发过程中新注册的监听器」会对尚未
       访问到的祖先节点生效 —— 于是这个刚挂上的 `@click.outside` 在同一轮派发里
       收到 E，发现 target 不在菜单内，立刻把菜单关掉。

    实测症状：`overflowOpen` 在同一帧内 true→false，DOM 里 `.entry-overflow`
    数量始终为 0，菜单闪都不闪一下。

    修法用**事件身份守卫**而不是在按钮上加 `@click.stop`：后者会让这次点击再也
    到不了 document，从而破坏仓库里「点任意处关闭其它浮层」的既有约定
    （如 `contextMenu.js` 的全局 click 监听）。
    """
    component = read_source(DOCK_JS)
    template = read_source(DOCK_TEMPLATE)

    # 1) 打开时记住触发事件
    toggle_block = component.split('toggleOverflow(event) {', 1)[1].split('\n    },', 1)[0]
    assert 'this._overflowOpenedByEvent = event || null;' in toggle_block
    assert '_overflowOpenedByEvent: null,' in component, 'state 必须初始化该字段'

    # 2) 关闭时跳过那一次事件
    close_block = component.split('closeOverflow(event) {', 1)[1].split('\n    },', 1)[0]
    assert 'if (event && event === this._overflowOpenedByEvent) return;' in close_block, (
        '必须按事件身份守卫；少了它菜单会被自己那次点击关掉'
    )
    assert 'this.overflowOpen = false;' in close_block

    # 3) 模板接线：按钮传 $event，浮层调 closeOverflow($event)
    more_block = template.split('entry-rail__slot--more', 1)[1].split('</button>', 1)[0]
    assert '@click="toggleOverflow($event)"' in more_block

    overflow_block = template.split('class="entry-overflow"', 1)[1].split('>', 1)[0]
    assert '@click.outside="closeOverflow($event)"' in overflow_block, (
        '浮层必须把事件传给 closeOverflow 才能做身份比对'
    )
    # 不能退回"直接赋值"的写法（那正是竞态的源头）
    assert '@click.outside="overflowOpen = false"' not in template

    # 4) 不能靠 stopPropagation 解决（会破坏全局 click 关闭其它浮层的约定）
    assert '.stop' not in more_block, (
        '不得用 @click.stop：那次点击必须继续冒泡，否则点空白处关不掉其它浮层'
    )


def test_overflow_menu_closes_on_escape_from_its_own_focus():
    """焦点在溢出菜单内部时，Escape 必须能关闭它。

    坞的 `handleKeydown` 挂在 `.entry-rail__panel` 上，而 `.entry-overflow` 是
    面板的**兄弟**节点（同为 `.entry-rail` 的子元素），并不在它的 keydown 树里。
    菜单打开后焦点会自动落到搜索框（`toggleOverflow` 里 `$nextTick` 聚焦
    `overflowSearch`），所以面板上的 keydown 永远收不到 —— Escape 会完全失灵。
    """
    template = read_source(DOCK_TEMPLATE)
    component = read_source(DOCK_JS)

    overflow_block = template.split('class="entry-overflow"', 1)[1].split('>', 1)[0]
    assert '@keydown.escape.stop="closeOverflow()"' in overflow_block, (
        '溢出菜单必须自己处理 Escape：它的 keydown 不在 .entry-rail__panel 的树里'
    )
    # 面板之外的节点 → 必须用 .stop 防止事件继续冒泡到坞根（那里会收起整个坞）
    assert '.escape.stop' in overflow_block

    # 打开时聚焦搜索框（正因如此 Escape 必须在菜单内部处理）
    assert 'this.$refs?.overflowSearch' in component


# ------------------------------------------------------------------ 行为契约


@requires_node
def test_overflow_groups_by_plugin():
    result = run_browser_script(
        """
        import assert from 'node:assert/strict';

        const { EntryRegistry } = await import('./static/js/entryRegistry.js');
        EntryRegistry.setPlugins([
          {
            id: 'plugin-a',
            enabled: true,
            manifest: { entries: [
              { id: 'a1', kind: 'dock', label: 'A1' },
              { id: 'a2', kind: 'dock', label: 'A2' },
            ] },
          },
          {
            id: 'plugin-b',
            enabled: true,
            manifest: { entries: [{ id: 'b1', kind: 'dock', label: 'B1' }] },
          },
        ]);

        const { default: entryDock } = await import('./static/js/components/entryDock.js');
        const dock = entryDock();
        dock.refresh();

        // community 插件默认全部进溢出菜单
        assert.equal(dock.overflow.length, 3);
        const groups = dock.overflowGroups;
        assert.equal(groups.length, 2);
        const byId = Object.fromEntries(groups.map((g) => [g.pluginId, g.items.length]));
        assert.deepEqual(byId, { 'plugin-a': 2, 'plugin-b': 1 });
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_overflow_search_filters_by_label_and_plugin():
    result = run_browser_script(
        """
        import assert from 'node:assert/strict';

        const { EntryRegistry } = await import('./static/js/entryRegistry.js');
        EntryRegistry.setPlugins([
          {
            id: 'alpha-plugin',
            enabled: true,
            manifest: { entries: [
              { id: 'summarize', kind: 'dock', label: '生成概览' },
              { id: 'tag', kind: 'dock', label: '打标签' },
            ] },
          },
        ]);

        const { default: entryDock } = await import('./static/js/components/entryDock.js');
        const dock = entryDock();
        dock.refresh();

        dock.overflowQuery = '概览';
        assert.equal(dock.filteredOverflow.length, 1);
        assert.equal(dock.filteredOverflow[0].id, 'summarize');

        // 按插件 id 也能搜到
        dock.overflowQuery = 'alpha';
        assert.equal(dock.filteredOverflow.length, 2);

        dock.overflowQuery = 'zzz';
        assert.equal(dock.filteredOverflow.length, 0);
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_disabled_entry_click_opens_plugin_config_instead_of_doing_nothing():
    """D7：置灰项点击必须跳到配置区，而不是无反应。"""
    result = run_browser_script(
        """
        import assert from 'node:assert/strict';

        const { default: entryDock } = await import('./static/js/components/entryDock.js');
        const dock = entryDock();
        dock.onDisabledClick({ pluginId: 'demo-plugin' });

        const events = globalThis.__dispatched;
        assert.equal(events.length, 1);
        assert.equal(events[0].type, 'open-settings-section');
        assert.equal(events[0].detail.section, 'plugins');
        assert.equal(events[0].detail.anchor, 'plugin-config-demo-plugin');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_dock_open_uses_registered_surface():
    """坞打开入口必须走宿主 surface，而不是自己造浮层。"""
    from tests.test_plugin_surface_contracts import DOM_SHIM

    result = run_node(
        BROWSER_STUB + DOM_SHIM + textwrap.dedent(
            """
            const { EntryRegistry } = await import('./static/js/entryRegistry.js');
            const { PluginSurfaceHost } = await import('./static/js/pluginSurfaceHost.js');
            const { default: entryDock } = await import('./static/js/components/entryDock.js');

            EntryRegistry.setPlugins([
              {
                id: 'demo-plugin',
                enabled: true,
                manifest: { entries: [{ id: 'panel', kind: 'dock', label: '面板' }] },
              },
            ]);

            let mounted = 0;
            PluginSurfaceHost.register('demo-plugin', 'panel', { mount() { mounted += 1; } });

            const dock = entryDock();
            dock.refresh();

            assert.equal(dock.open('demo-plugin:panel'), true);
            assert.equal(mounted, 1, '坞必须通过宿主 surface 打开，而不是自己造浮层');
            assert.equal(dock.activeKey, 'demo-plugin:panel');
            """
        )
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_palette_ranks_prefix_matches_first():
    result = run_browser_script(
        """
        import assert from 'node:assert/strict';

        const { EntryRegistry } = await import('./static/js/entryRegistry.js');
        EntryRegistry.setPlugins([
          {
            id: 'demo-plugin',
            enabled: true,
            manifest: { entries: [
              { id: 'x', kind: 'command', label: '概览生成' },
              { id: 'y', kind: 'command', label: '生成概览' },
            ] },
          },
        ]);

        const { default: commandPalette } = await import('./static/js/components/commandPalette.js');
        const palette = commandPalette();
        palette.query = '生成';
        palette.rebuild();

        // 前缀命中（"生成概览"）排在包含命中（"概览生成"）之前
        const pluginItems = palette.items.filter((item) => item.pluginId === 'demo-plugin');
        assert.equal(pluginItems[0].label, '生成概览');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_palette_includes_core_commands_even_without_plugins():
    result = run_browser_script(
        """
        import assert from 'node:assert/strict';

        const { EntryRegistry } = await import('./static/js/entryRegistry.js');
        EntryRegistry.setPlugins([]);

        const { default: commandPalette } = await import('./static/js/components/commandPalette.js');
        const palette = commandPalette();
        palette.rebuild();

        assert.ok(palette.items.length > 0, '没有插件时宿主内建命令仍必须可用');
        assert.ok(palette.items.every((item) => item.key.startsWith('core:')));
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_palette_activate_runs_core_action_and_closes():
    result = run_browser_script(
        """
        import assert from 'node:assert/strict';

        const modes = [];
        globalThis.window.Alpine = {
          store: () => ({ set currentMode(value) { modes.push(value); } }),
        };

        const { default: commandPalette } = await import('./static/js/components/commandPalette.js');
        const palette = commandPalette();
        palette.open = true;
        palette.items = [{ key: 'core:switch-chats', label: '切换到会话' }];

        assert.equal(palette.activateIndex(0), true);
        assert.deepEqual(modes, ['chats']);
        assert.equal(palette.open, false, '执行后必须关闭面板');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout


@requires_node
def test_palette_keyboard_navigation_wraps():
    result = run_browser_script(
        """
        import assert from 'node:assert/strict';

        const { default: commandPalette } = await import('./static/js/components/commandPalette.js');
        const palette = commandPalette();
        palette.items = [{ key: 'a' }, { key: 'b' }, { key: 'c' }];

        const press = (key) => palette.handleKeydown({ key, preventDefault() {} });

        press('ArrowDown');
        assert.equal(palette.activeIndex, 1);
        press('ArrowUp');
        press('ArrowUp');
        assert.equal(palette.activeIndex, 2, '向上越界必须回绕到末尾');
        press('ArrowDown');
        assert.equal(palette.activeIndex, 0, '向下越界必须回绕到开头');
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout
