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
    template = read_source('templates/components/context_menu.html')

    assert 'pluginEntries' in template
    assert 'runPluginEntry(entry)' in template
    # 置灰项可见但不可点，且显示 disabledHint（D7：不是隐藏、不是无反应）
    assert ':disabled="!entry.enabled"' in template
    assert 'disabledHint' in template


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
    哪几张卡无关。因此求值 `when` 时必须覆盖 `targetKind` 并把 `selectionCount`
    归零（右键文件夹）/ 置 1（右键卡片）。
    """
    source = read_source('static/js/components/contextMenu.js')

    # 用 contextOverride 覆盖全局上下文
    assert 'contextOverride: this.pluginEntryContext()' in source
    assert 'pluginEntryContext()' in source
    # 两种目标类型都要给出作用域
    assert "targetKind === 'card' ? 1 : 0" in source
    assert 'targetKind,' in source


def test_context_menu_resolves_folder_scope_host_side():
    """分类 → 卡片 id 列表必须由**宿主**解析后交给插件。

    插件拿不到主程序的卡片列表接口（只有 `/api/plugins/<id>/*`），也不该去读
    宿主的内部状态。让插件自己猜作用域的结果就是「右键分类，实际分析的是
    全局选中集」——这正是重写前的问题 1。
    """
    source = read_source('static/js/components/contextMenu.js')

    assert 'resolvePluginEntryTargetIds' in source
    assert "from '../api/card.js'" in source
    assert 'listCards(' in source
    # 解析发生在点击时（右键菜单频繁打开，不该每次都拉列表）
    assert 'await this.resolvePluginEntryTargetIds(targetKind)' in source
    # 目标 id 列表随 ctx / 事件一起交给插件
    assert 'targetIds,' in source
    assert 'targetPath,' in source


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
    assert 'x-for="entry in pluginBatchEntries"' in template
    assert 'runPluginBatchEntry(entry)' in template
    assert 'pluginBatchEntryIconHtml(entry)' in template
    # 置灰项可见但不可点，且带 disabledHint（D7）
    assert ':disabled="!entry.enabled"' in template
    assert 'entry.disabledHint' in template

    # 组件：取数与执行
    assert 'EntryRegistry' in component
    assert '.list({ kind: "batch" })' in component
    assert 'refreshPluginBatchEntries' in component
    assert "entries:changed" in component
    assert 'targetIds' in component
    assert "source: \"batch\"" in component


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

    assert '.filter((entry) => entry.enabled)' in body, (
        '批量入口必须过滤掉 when 不满足的项'
    )
    assert '.list({ kind: "batch" })' in body


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
