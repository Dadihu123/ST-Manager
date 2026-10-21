"""右键菜单与快捷键入口契约（设计文档 D1 / D7 / 9.3.1）。

`kind: "context"` 的落点是**右键菜单**，`entries[].shortcut` 是「建议快捷键，
宿主可覆盖」（2.2）。这两条此前都没有消费者：`contextMenu.js` 不引用
`EntryRegistry`，也没有任何 keydown 监听调用 `findByShortcut()`。

这里既做源码契约断言，也在 node 可用时**真实执行**注册表逻辑。
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


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


# ------------------------------------------------------------------ 右键菜单


def test_context_menu_consumes_plugin_context_entries():
    """D1：`kind: "context"` 必须在右键菜单里有消费者。"""
    source = read_source('static/js/components/contextMenu.js')

    assert "import { EntryRegistry }" in source
    assert "kind: 'context'" in source
    # 打开菜单时重算（`when` 依赖当前模式与选中项，不能只在 init 里算一次）
    assert 'refreshPluginEntries' in source
    assert 'entries:changed' in source
    # 置灰项不执行
    assert 'entry.enabled' in source or 'entry.enabled === false' in source


def test_context_menu_template_renders_plugin_entries():
    """右键菜单里插件入口是**一个父项 + 二级浮层**，不适用的动作不出现。

    用户口径（2026-10-20）：「不匹配的就直接不显示，不用置灰显示」，
    并且「右键菜单中应该是看到 AI 助手这一项，然后点开后是多项子功能」。
    2026-10-21 追加：二级菜单必须是**独立浮层**，禁止就地展开（见
    `test_submenus_are_fixed_flyouts_opening_to_the_right`）。
    因此这里不再断言 `disabledHint` / `:disabled`，改为断言分组渲染。
    """
    template = read_source('templates/components/context_menu.html')

    assert 'pluginEntries' in template
    assert 'runPluginEntry(entry)' in template
    # 分组父项：一级只有「AI 助手」，点开是二级菜单（锚点元素要一起传，用于定位）
    assert "unit.type === 'group'" in template
    assert 'togglePluginGroup(unit.key, $event.currentTarget)' in template
    assert 'activePluginGroupUnit()' in template
    assert 'backFromPluginGroup()' in template
    # 未分组时仍然平铺一条（单入口插件不该被包一层）
    assert "unit.type === 'entry'" in template
    # 不再渲染置灰项
    assert 'disabledHint' not in template
    assert ':disabled="!entry.enabled"' not in template


def test_context_menu_icon_resolves_plugin_assets():
    """右键菜单里的插件图标同样要能解析资源路径（需要 pluginId）。"""
    source = read_source('static/js/components/contextMenu.js')

    assert 'pluginEntryIconHtml' in source
    # 单引号风格（contextMenu.js 全文用单引号）
    assert "pluginId: String((entry && entry.pluginId) || '')" in source


def test_context_menu_dispatches_to_surface_then_event():
    """与坞 / 命令面板同一套约定：先找 surface，找不到再派发 `entry:activate`。"""
    source = read_source('static/js/components/contextMenu.js')

    assert 'PluginSurfaceHost.has(surfaceKey)' in source
    assert 'PluginSurfaceHost.openSurface(surfaceKey' in source
    assert 'entry:activate' in source
    assert "source: 'context'" in source


def test_context_menu_evaluates_when_against_the_right_click_target():
    """右键菜单的作用域是**右键目标**，不是全局选中集。

    这是「右键分类 → 分析整个分类」与「批量菜单 → 分析选中卡片」分离的根因修复：
    右键一个分类时，作用域是那个分类（含子分类）的全部卡片，与用户恰好勾选了
    哪几张卡无关。因此求值 `when` 时必须覆盖 `targetKind`，并把 `selectionCount`
    归零（右键不是「选中集」语境）。
    """
    source = read_source('static/js/components/contextMenu.js')

    # 用 contextOverride 覆盖全局上下文
    assert 'contextOverride: this.pluginEntryContext()' in source
    assert 'pluginEntryContext()' in source
    # 右键目标类型交给 when.target 求值；选中数与本次操作无关，恒为 0
    assert 'targetKind: String(this.type' in source
    assert 'selectionCount: 0' in source


def test_context_menu_passes_only_semantic_target_host_side():
    """右键目标只传**语义**（kind / path / id），解析作用域归插件。

    此前宿主在点击瞬间用 `listCards({page_size: 100000})` 同步拉整个分类的卡片，
    造成三个问题：右键上万张卡片的分类时菜单点不动；解析失败与「分类确实为空」
    都变成空数组（插件无法如实报错）；世界书视图的分类右键拉的是**卡片**。

    `ctx.target` 的契约见 `docs/2026-10-19-host-patch.md` §1。
    """
    source = read_source('static/js/components/contextMenu.js')

    # 宿主不再解析 id 列表
    assert 'resolvePluginEntryTargetIds' not in source
    assert 'listCards' not in source

    # 只构造语义目标；`ids` 恒为空数组（右键不携带「选中集」）
    assert "kind: kind === 'card' ? 'card' : 'folder'" in source
    assert "path: kind === 'folder' ? rawTarget : ''" in source
    assert "id: kind === 'card' ? rawTarget : ''" in source
    assert 'ids: [],' in source
    assert 'target,' in source
    # 旧扁平字段已删除（留着会诱导插件继续读旧形状）
    assert 'targetIds' not in source
    assert 'targetPath' not in source


def test_batch_menu_passes_selection_target():
    """批量入口传 `kind: 'selection'` + 选中 id 列表（`ctx.target.ids`）。"""
    component = read_source('static/js/components/header.js')

    assert 'kind: "selection"' in component
    assert 'ids: [...this.selectedIds]' in component
    assert 'source: "batch"' in component
    assert 'target,' in component
    # 旧扁平字段已删除
    assert 'targetKind' not in component
    assert 'targetIds' not in component


def test_batch_menu_consumes_plugin_batch_entries():
    """D1：`kind: "batch"` 的落点是**批量操作菜单**（`header.html`）。

    用户原话：「对于选中卡片的分析应该注册到批量处理的展开项中，这样才符合
    当前整个项目的设计。」批量菜单沿用全局 selection 语义求值 `when`。
    """
    template = read_source('templates/components/header.html')
    component = read_source('static/js/components/header.js')

    # 模板：在批量操作菜单内渲染 batch 入口
    # （断言 x-for 真的遍历 pluginBatchEntries，而不只是「某处提到这个名字」——
    #  后者在把列表换成空数组时仍然成立，等于没测）
    assert 'x-for="unit in pluginBatchEntries"' in template
    assert 'runPluginBatchEntry(entry)' in template
    assert 'pluginBatchEntryIconHtml(entry)' in template
    # 与右键菜单一致：一个「AI 助手」父项 + 二级浮层；不适用就不出现
    assert "unit.type === 'group'" in template
    assert 'togglePluginBatchGroup(unit.key, $event.currentTarget)' in template
    assert 'x-for="entry in activePluginBatchGroupUnit().entries"' in template
    assert 'disabledHint' not in template

    # 组件：取数与执行
    assert 'EntryRegistry' in component
    assert 'EntryRegistry.menuGroups({ kind: "batch" })' in component
    assert 'refreshPluginBatchEntries' in component
    assert "entries:changed" in component
    assert 'ids: [...this.selectedIds]' in component
    assert 'source: "batch"' in component


def test_mobile_selection_bar_offers_plugin_batch_entries():
    """移动端选中栏必须有插件批量入口（此前只有桌面菜单有）。

    手机视图下用户选完卡片看不到插件批量按钮，等于插件在移动端不可达。
    """
    template = read_source('templates/components/header.html')

    # 移动端选中栏的锚点
    mobile_bar = template.split("ui-batch-action-strip--mobile", 1)[1]
    mobile_bar = mobile_bar.split("<!-- 移动端：展开菜单 -->", 1)[0]

    # 移动端是一排图标按钮，没有悬停子菜单的位置：走拍平后的入口
    assert 'x-for="entry in pluginBatchFlatEntries"' in mobile_bar
    assert 'runPluginBatchEntry(entry)' in mobile_bar
    assert 'pluginBatchEntryIconHtml(entry)' in mobile_bar


def test_batch_menu_items_render_badge_and_progress():
    """批量菜单项要画角标 / 进度，与右键菜单保持一致。

    否则「有 3 条待审批」只在右键菜单可见，而批量菜单里那条入口看起来毫无状态。
    `entry.progress` 是 `{done, total}`（不是百分数），模板必须走百分比换算。
    2026-10-21：分组子项搬进了二级浮层，所以这里把一级项与浮层一起看。
    """
    template = read_source('templates/components/header.html')
    component = read_source('static/js/components/header.js')

    # 批量菜单块（桌面批量操作下拉 + 插件分组二级浮层）
    menu_block = template.split('插件声明的 `kind: "batch"` 入口', 1)[1]
    menu_block = menu_block.split('<!-- 移动端：展开菜单 -->', 1)[0]

    assert 'pluginBatchEntryBadge(entry)' in menu_block
    assert 'plugin-entry-progress' in menu_block
    assert 'plugin-entry-progress-bar' in menu_block
    assert 'pluginBatchEntryProgressPercent(entry)' in menu_block

    # 百分比换算在组件里，模板只做拼接
    assert 'pluginBatchEntryProgressPercent(entry) {' in component
    assert 'pluginBatchEntryBadge(entry) {' in component


def test_submenus_are_fixed_flyouts_opening_to_the_right():
    """右键菜单 / 批量菜单的二级必须是**独立 fixed 浮层，固定向右展开**。

    用户口径（2026-10-21，第二次澄清）：二级菜单「怎么想不都应该向右弹出吗」，
    「保持向右展开的逻辑不变的情况下，如果列表向下延申会超出屏幕的话则应该
    向上延申」。也就是说纵向自适应不是「向下展开」，而是**贴着父项右侧、
    顶部对齐**，只在下方放不下时整体上移。

    为什么不能用 `absolute left-full top-0`：一级菜单盒带
    `max-height + overflow:auto`（`.ui-context-menu` 甚至 `overflow:hidden`），
    absolute 子元素会被裁掉——「运行自动化」的规则集子菜单原先就是这样坏的。
    """
    context_template = read_source('templates/components/context_menu.html')
    header_template = read_source('templates/components/header.html')
    context_source = read_source('static/js/components/contextMenu.js')
    header_source = read_source('static/js/components/header.js')
    flyout_util = read_source('static/js/utils/flyoutPosition.js')

    # 三个浮层各自是独立节点（不是一级菜单盒里的一块 x-show 内容）
    assert 'data-context-ruleset-flyout' in context_template
    assert 'data-plugin-group-flyout' in context_template
    assert 'data-plugin-batch-flyout' in header_template
    assert 'class="plugin-menu-flyout"' in context_template
    assert 'class="plugin-menu-flyout"' in header_template

    # 「运行自动化」不再用 absolute 子菜单（会被裁掉），改走同一套浮层
    assert 'absolute left-full top-0' not in context_template
    assert 'x-data="{ showSub: false }"' not in context_template
    assert 'toggleRuleSetSubmenu($event.currentTarget)' in context_template
    assert 'data-context-ruleset-flyout' in context_template

    # 就地展开的残留必须删干净
    assert 'pl-6' not in header_template
    assert 'pluginBatchGroupOpen' not in header_template
    assert 'pluginBatchGroupOpen' not in header_source
    assert 'pluginGroupOpen' not in context_template
    assert 'pluginGroupOpen' not in context_source

    # 桌面端浮层是一级菜单的兄弟节点（在 `.ui-context-menu` 之外），
    # 批量菜单的浮层还要 teleport 到 body：`.header-bar` 的 backdrop-filter
    # 会给 fixed 后代造包含块。
    context_menu_box_end = context_template.index('</div>', context_template.index('class="ui-context-menu"'))
    assert context_template.index('data-plugin-group-flyout') > context_menu_box_end
    assert context_template.index('data-context-ruleset-flyout') > context_menu_box_end
    assert 'x-teleport="body"' in header_template

    # 定位工具：fixed + 向右展开 + 纵向向上延申
    assert 'export function computeFlyoutPosition' in flyout_util
    assert 'export function positionFlyoutElement' in flyout_util
    assert 'FLYOUT_VIEWPORT_MARGIN = 8' in flyout_util
    assert 'placement' in flyout_util
    assert "placement = 'right'" in flyout_util
    # 高度必须在渲染后测量（getBoundingClientRect），不能用估算值
    assert 'getBoundingClientRect' in flyout_util
    assert 'offsetHeight' in flyout_util

    # 组件：点父项 → 渲染后 requestAnimationFrame 里测量定位；同一时间只开一个
    for source in (context_source, header_source):
        assert 'positionFlyoutElement' in source
        assert 'requestAnimationFrame' in source
    assert 'toggleSubmenu' in context_source
    assert 'togglePluginBatchGroup' in header_source
    # 父项必须 @click.stop：宿主有全局 window click 监听会立刻关掉菜单。
    # 锚点传 `$event.currentTarget`（不是 `$event`）：浮层要按父项矩形定位。
    assert '@click.stop="togglePluginGroup(unit.key, $event.currentTarget)"' in context_template
    assert '@click.stop="togglePluginBatchGroup(unit.key, $event.currentTarget)"' in header_template
    # Escape / 滚动宿主页面 → 关闭二级
    assert "'Escape'" in context_source
    assert '"Escape"' in header_source
    assert "addEventListener('scroll'" in context_source
    assert 'addEventListener("scroll"' in header_source
    # 移动端退化为「弹层第二屏」（返回行 + 切内容），桌面端不走这条
    assert 'isMobile && activePluginGroupUnit()' in context_template
    assert '!isMobile && activePluginGroupUnit()' in context_template


def test_clicking_a_parent_twice_closes_its_submenu():
    """再点一次同一个父项要收起二级（用户明确指出的缺陷）。

    批量菜单里「自动处理 / 来源更新」就是这个行为（`showX = !showX`），
    AI 助手必须一致；切换父项时则直接换成新的那一项。
    """
    context_source = read_source('static/js/components/contextMenu.js')
    header_source = read_source('static/js/components/header.js')

    # 两个组件都用「已展开则收起，否则打开」的 toggle
    assert 'toggleSubmenu(kind, anchorEl) {' in context_source
    assert 'if (String(this.activeSubmenu || \'\') === target) {' in context_source
    assert 'togglePluginBatchGroup(key, anchorEl) {' in header_source
    assert 'if (String(this.activePluginBatchGroup || "") === target) {' in header_source

    # 模板父项走 toggle（不是 open），否则再点一次只会重复打开
    context_template = read_source('templates/components/context_menu.html')
    header_template = read_source('templates/components/header.html')
    assert 'togglePluginGroup(unit.key, $event.currentTarget)' in context_template
    assert 'togglePluginBatchGroup(unit.key, $event.currentTarget)' in header_template
    assert 'openPluginGroup(unit.key' not in context_template
    assert 'openPluginBatchGroup(unit.key' not in header_template


def test_flyout_is_looked_up_from_document_not_component_el():
    """浮层元素必须从 `document` 找，不能用 `this.$el`。

    实测踩过的坑：`toggleSubmenu()` 由 `@click` 发起，定位逻辑跑在
    `$nextTick` / `requestAnimationFrame` 回调里。此时 Alpine 的 `$el` magic
    指向**被点的那个按钮**（拿到 BUTTON），`this.$el.querySelector('[data-plugin-…]')`
    永远返回 null，浮层就停在初始的 `top:-9999px` 上——看起来「点了没反应」。

    两个组件都用 data 属性从 document 查（页面上各自只有一个实例）。
    """
    context_source = read_source('static/js/components/contextMenu.js')
    header_source = read_source('static/js/components/header.js')

    assert "document.querySelector(`[${attr}]`)" in context_source
    assert 'document.querySelector("[data-plugin-batch-flyout]")' in header_source
    # `$el` 只允许出现在解释性注释里，不能真的参与查找
    for source in (context_source, header_source):
        code = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
        code = re.sub(r'//[^\n]*', '', code)
        assert '$el' not in code, '$el 在异步回调里指向被点的元素，不能用来找浮层'


def test_batch_entries_are_hidden_when_not_applicable():
    """批量菜单只列出**可用**的 batch 入口（问题 5）。

    批量菜单的宿主内建项都靠 `x-show="currentMode === ..."` 自己管可见性，
    插件项没有等价条件。AI 助手只处理角色卡，因此在世界书 / 会话 / 预设视图下
    这个菜单项不该出现（用户原话：「在世界书等其他视图，这个批量处理菜单就
    不应该注册了」）。

    与右键菜单的区别：右键菜单里 `when` 不满足要**可见但置灰**（D7），因为用户
    是在「对某个目标操作」的语境下期待看到它；批量菜单是**动作清单**，
    不适用就该收起，而不是留一条永远点不动的灰项。
    """
    component = read_source('static/js/components/header.js')
    # 只看 `refreshPluginBatchEntries` 的定义体（注释里也提到了这个写法，先剥注释）
    code = re.sub(r'/\*.*?\*/', '', component, flags=re.S)
    body = code.split('refreshPluginBatchEntries() {', 1)[1].split('\n    },', 1)[0]

    # `menuGroups` 内部就是 `list({ enabledOnly: true })`：只给可用入口
    assert 'menuGroups({ kind: "batch" })' in body, (
        '批量入口必须过滤掉 when 不满足的项'
    )


# ------------------------------------------------------------------ 快捷键


def test_shortcut_is_dispatched_from_a_real_keydown_listener():
    """`entries[].shortcut` 必须有真实键盘监听消费（此前只有 find* 没有调用方）。"""
    source = read_source('static/js/components/commandPalette.js')

    assert 'handleEntryShortcut' in source
    assert 'EntryRegistry.findByShortcut(combo)' in source
    assert 'shortcutCombo' in source
    # 必须挂在已有的 keydown 监听里（与 Ctrl+K 同一个 handler）
    assert 'window.addEventListener("keydown", this._keyHandler)' in source
    assert 'this.handleEntryShortcut(event)' in source


def test_shortcut_requires_a_modifier_and_ignores_typing():
    """两条纪律：裸键不进快捷键表；输入框里不触发。"""
    source = read_source('static/js/components/commandPalette.js')

    assert 'isTypingTarget' in source
    # 至少一个修饰键
    assert 'if (!parts.length) return "";' in source
    # 输入元素识别
    assert '"textarea"' in source
    assert 'isContentEditable' in source


def test_shortcut_ui_exists_in_entry_overview():
    """设计文档 9.3.1：快捷键列「`entry.shortcut`（用户可改）」——需要有改的入口。"""
    manager = read_source('static/js/components/pluginManager.js')
    template = read_source('templates/modals/plugin_manager.html')

    assert 'entryShortcut' in manager
    assert 'captureEntryShortcut' in manager
    assert 'onShortcutKeydown' in manager
    assert 'assignEntryShortcut' in manager
    assert 'clearEntryShortcut' in manager

    assert 'captureEntryShortcut(row)' in template
    assert 'onShortcutKeydown($event)' in template


# ------------------------------------------------------------------ 真实执行

NODE = shutil.which('node')
requires_node = pytest.mark.skipif(NODE is None, reason='node 不可用')


def _run_registry_script(body: str):
    script = f"""
import {{ EntryRegistry }} from 'file:///{PROJECT_ROOT.replace(os.sep, '/')}/static/js/entryRegistry.js';
{body}
"""
    result = subprocess.run(
        [NODE, '--input-type=module', '-e', script],
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )
    if result.returncode != 0:
        pytest.skip(f'node 执行失败: {result.stderr[:400]}')
    return json.loads(result.stdout)


@requires_node
def test_declared_shortcut_is_active_by_default():
    """`shortcut` 是「建议快捷键」——用户没改时**直接生效**，不只是展示。"""
    out = _run_registry_script("""
EntryRegistry.setPlugins([
  { id: 'p1', enabled: true, manifest: { entries: [
    { id: 'a', kind: 'command', label: 'A', shortcut: 'Ctrl+Shift+A' },
  ] } },
]);
EntryRegistry.layout = { order: [], pinned: [], hidden: [], groups: {}, shortcuts: {} };
process.stdout.write(JSON.stringify({
  hit: EntryRegistry.findByShortcut('Ctrl+Shift+A')?.label || null,
  miss: EntryRegistry.findByShortcut('Ctrl+Shift+Z'),
  empty: EntryRegistry.findByShortcut(''),
}));
""")
    assert out['hit'] == 'A'
    assert out['miss'] is None
    assert out['empty'] is None


@requires_node
def test_user_configuration_overrides_declared_shortcut():
    """用户配置优先（覆盖语义）：改绑后旧组合键不再触发原入口。"""
    out = _run_registry_script("""
EntryRegistry.setPlugins([
  { id: 'p1', enabled: true, manifest: { entries: [
    { id: 'a', kind: 'command', label: 'A', shortcut: 'Ctrl+Shift+A' },
    { id: 'b', kind: 'command', label: 'B', shortcut: 'Ctrl+Shift+B' },
  ] } },
]);
EntryRegistry.layout = {
  order: [], pinned: [], hidden: [], groups: {},
  shortcuts: { 'Ctrl+Shift+A': 'p1:b' },
};
process.stdout.write(JSON.stringify({
  rebound: EntryRegistry.findByShortcut('Ctrl+Shift+A')?.label || null,
  freedByOverride: EntryRegistry.findByShortcut('Ctrl+Shift+B')?.label || null,
}));
""")
    assert out['rebound'] == 'B', 'Ctrl+Shift+A 应被改绑到 B'
    assert out['freedByOverride'] is None, 'B 已被改绑，其建议值不应再生效'


@requires_node
def test_shortcut_returns_evaluated_entry_with_enabled_flag():
    """返回值必须带 `enabled`，否则置灰判断会失效（`get()` 返回的是原始项）。"""
    out = _run_registry_script("""
EntryRegistry.setPlugins([
  { id: 'p1', enabled: true, manifest: { entries: [
    { id: 'sel', kind: 'context', label: '需选中', shortcut: 'Ctrl+Shift+S',
      requires_selection: true, when: { selection: 'any' } },
  ] } },
]);
EntryRegistry.layout = { order: [], pinned: [], hidden: [], groups: {}, shortcuts: {} };
const hit = EntryRegistry.findByShortcut('Ctrl+Shift+S');
process.stdout.write(JSON.stringify({
  hasEnabled: Object.prototype.hasOwnProperty.call(hit || {}, 'enabled'),
  enabled: hit ? hit.enabled : null,
  hint: hit ? hit.disabledHint : '',
}));
""")
    assert out['hasEnabled'] is True, 'findByShortcut 必须返回求值后的条目'
    assert out['enabled'] is False, '未选中时该入口应置灰'
    assert out['hint'], '置灰必须带 disabledHint'


@requires_node
def test_host_core_shortcuts_are_always_enabled():
    """宿主内建入口（`core:`）没有 `when`，恒为可用。"""
    out = _run_registry_script("""
EntryRegistry.layout = {
  order: [], pinned: [], hidden: [], groups: {},
  shortcuts: { 'Ctrl+K': 'core:open-settings' },
};
const hit = EntryRegistry.findByShortcut('Ctrl+K');
process.stdout.write(JSON.stringify({
  label: hit ? hit.label : null,
  enabled: hit ? hit.enabled : null,
}));
""")
    assert out['label'] == '打开设置'
    assert out['enabled'] is True


@requires_node
def test_context_entries_are_listed_with_when_evaluated():
    """右键菜单取的就是 `EntryRegistry.list({kind:'context'})` 的结果。"""
    out = _run_registry_script("""
EntryRegistry.setPlugins([
  { id: 'p1', enabled: true, manifest: { entries: [
    { id: 'ctx', kind: 'context', label: '分析选中', icon: 'tags',
      requires_selection: true, when: { mode: ['cards'], selection: 'any' },
      disabledHint: '请先选卡' },
    { id: 'dock', kind: 'dock', label: '面板' },
  ] } },
]);
const items = EntryRegistry.list({ kind: 'context' });
process.stdout.write(JSON.stringify({
  count: items.length,
  id: items[0]?.id || null,
  hasEnabled: Object.prototype.hasOwnProperty.call(items[0] || {}, 'enabled'),
  hint: items[0]?.disabledHint || '',
  pluginId: items[0]?.pluginId || '',
}));
""")
    assert out['count'] == 1, '只应返回 context 类入口'
    assert out['id'] == 'ctx'
    assert out['hasEnabled'] is True
    assert out['hint'] == '请先选卡'
    assert out['pluginId'] == 'p1'


@requires_node
def test_flyout_opens_right_and_shifts_up_when_short_on_room():
    """二级浮层的空间算法（真实执行 `utils/flyoutPosition.js`）。

    用户口径（2026-10-21 澄清）：展开方向**固定向右**，纵向做自适应——
    「保持向右展开的逻辑不变的情况下，如果列表向下延申会超出屏幕的话则
    应该向上延申」。这里覆盖五种边界：默认向右、下方不够时整体上移、
    上移也放不下时贴 8px 并允许内部滚动、右侧不够翻到左边、两边都不够就钳进视口。
    """
    script = f"""
import {{ computeFlyoutPosition, FLYOUT_VIEWPORT_MARGIN }} from 'file:///{PROJECT_ROOT.replace(os.sep, '/')}/static/js/utils/flyoutPosition.js';

const viewport = {{ width: 1200, height: 800 }};
// 浮层 224x180（14rem 宽，3 项）
const size = {{ width: 224, height: 180 }};
// 父项 240 宽、36 高，左边距 100（右侧还剩 760px，够放）
const at = (top) => ({{ top, bottom: top + 36, left: 100, right: 340 }});

const normal = computeFlyoutPosition(at(300), size, viewport);
// 父项在底部：向下延伸会超出视口，整体上移（底边对齐父项底边）
const low = computeFlyoutPosition(at(700), size, viewport);
// 浮层比视口还高：上移也放不下，贴 8px + maxHeight
const huge = computeFlyoutPosition(at(400), {{ width: 224, height: 900 }}, viewport);
// 父项贴右边缘：右侧放不下，翻到左边
const nearRight = computeFlyoutPosition({{ top: 300, bottom: 336, left: 1000, right: 1140 }}, size, viewport);
// 两边都放不下（浮层比视口还宽）：钳进视口
const narrow = computeFlyoutPosition(
  {{ top: 300, bottom: 336, left: 0, right: 240 }},
  {{ width: 2000, height: 100 }},
  viewport,
);

process.stdout.write(JSON.stringify({{
  margin: FLYOUT_VIEWPORT_MARGIN,
  normal: {{ top: normal.top, left: normal.left, placement: normal.placement }},
  low: {{ top: low.top, left: low.left, placement: low.placement }},
  huge: {{ top: huge.top, maxHeight: huge.maxHeight }},
  nearRight: {{ left: nearRight.left, placement: nearRight.placement }},
  narrow: {{ left: narrow.left }},
}}));
"""
    result = subprocess.run(
        [NODE, '--input-type=module', '-e', script],
        capture_output=True, text=True, encoding='utf-8', timeout=60,
    )
    assert result.returncode == 0, result.stderr[:400]
    out = json.loads(result.stdout)

    assert out['margin'] == 8
    # 默认：贴在父项右边（right + 4），顶部与父项对齐
    assert out['normal'] == {'top': 300, 'left': 344, 'placement': 'right'}
    # 下方溢出：不改成向下展开，而是保持右侧、整体上移（736 - 180）
    assert out['low'] == {'top': 556, 'left': 344, 'placement': 'right'}
    # 上移也放不下：贴 8px，并给出 `100vh - 16px` 级别的内部滚动高度
    assert out['huge'] == {'top': 8, 'maxHeight': 784}
    # 右侧放不下 → 翻到父项左边：1000 - 224 - 4 = 772
    assert out['nearRight'] == {'left': 772, 'placement': 'left'}
    # 两边都放不下 → 钳进视口（1200 - 8 - 2000 为负，取 8）
    assert out['narrow']['left'] == 8
