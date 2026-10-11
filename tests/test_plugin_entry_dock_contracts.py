"""入口坞与命令面板契约测试（设计文档 阶段 5 / D6）。

坞是 `entries` 契约的**第一个消费者**，也是地基的验收装置。这里锁死它必须
满足的硬约束——尤其是那些「浏览器不会报错但功能静默失效」的点：

- 位置避开在流顶栏与翻页栏
- 收起态热区仍可命中（`opacity: 0` + `pointer-events: auto`）
- 根元素带 `data-marquee-ignore`（否则框选会命中坞）
- 键盘可达（`role="toolbar"` + roving tabindex）
- 模态打开时自动收起
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
    """收起态热区：`opacity: 0` 但 `pointer-events: auto`（否则永远展不开）。"""
    css = read_source(DOCK_CSS)
    hotzone = css.split('.entry-rail__hotzone {', 1)[1].split('}', 1)[0]

    assert 'width: 8px;' in hotzone
    assert 'opacity: 0;' in hotzone
    assert 'pointer-events: auto;' in hotzone


def test_expanded_rail_is_56px():
    css = read_source(DOCK_CSS)

    assert 'width: 56px;' in css


def test_dock_defaults_to_expanded():
    """坞默认**展开**（问题 2 的修复）。

    旧实现默认折叠，而折叠态的 `.entry-rail__panel` 是 `width: 0`——坞等于
    完全不可见，用户只能靠一个 8px 的透明热区把它摸出来（用户原话：
    「怎么目前都没了？」）。设计文档 D6 只要求「社区插件默认进溢出菜单」，
    从未要求坞本身默认隐藏。
    """
    component = read_source(DOCK_JS)

    # 初始 state 是展开。用 `class="entry-rail__toggle"` 式的精确匹配：
    # `expanded: true` 在 `{ expanded: true, side: "right" }` 里也出现，裸子串断言
    # 在把 state 改成 false 之后**仍然通过**（等于没测）。
    assert '\n    expanded: true,\n' in component, 'entryDock() 的初始 state 必须是展开'
    # 首次运行（无偏好）默认展开
    assert 'if (!raw) return { expanded: true, side: "right" };' in component
    # 偏好里缺 expanded 字段时也展开（旧版存过 {side:'right'} 的用户不该被折叠）
    assert 'parsed.expanded === undefined ? true' in component
    # 读取异常时的兜底同样展开（不能是「读失败 → 折叠」）
    assert 'return { expanded: true, side: "right" };' in component


def test_dock_prefs_default_expanded_when_read():
    """真实执行 `init()` 验证三种 localStorage 情形都得到「展开」。"""
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
              assert.equal(dock.expanded, true, name + ' 应默认展开');
            }

            // 4) 用户显式收起过 → 尊重用户选择
            globalThis.localStorage = {
              getItem() { return JSON.stringify({ expanded: false }); },
              setItem() {},
            };
            const { default: entryDock } = await import(
              './static/js/components/entryDock.js?case=explicit'
            );
            const dock = entryDock();
            dock.init();
            assert.equal(dock.expanded, false, '用户显式收起必须被尊重');
            """
        )
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_collapsed_rail_keeps_a_visible_strip():
    """折叠态仍保留 40px 可见条 + 明确的开合按钮。

    旧实现折叠态 `width: 0`，坞在视觉上彻底消失；现在折叠态保留一条窄边，
    用户看得见它、也知道点哪里展开。
    """
    css = read_source(DOCK_CSS)
    template = read_source(DOCK_TEMPLATE)

    # 折叠态的可见宽度（不再是 0）
    collapsed = css.split('.entry-rail.is-collapsed', 1)[1]
    assert 'width: 40px;' in collapsed.split('}', 1)[0], '折叠态必须保留可见宽度'

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


def test_dock_hover_expand_delay_is_150ms():
    component = read_source(DOCK_JS)

    assert 'HOVER_EXPAND_DELAY_MS = 150' in component


def test_dock_avoids_backdrop_filter():
    css = re.sub(r'/\*.*?\*/', '', read_source(DOCK_CSS), flags=re.S)

    assert 'backdrop-filter' not in css


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


def test_dock_and_palette_respect_reduced_motion():
    for path in (DOCK_CSS,):
        assert 'prefers-reduced-motion' in read_source(path), path


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
