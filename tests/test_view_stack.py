"""视图栈与返回手势契约测试。

用 Node 直接加载 `static/js/utils/viewStack.js`（纯 ESM，无浏览器依赖），
在 stub 出来的 window 上验证「按 LIFO 关闭 + 工作区回退 + 交还系统」三条语义。
"""

import json
import subprocess
import textwrap
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
VIEW_STACK = PROJECT_ROOT / 'static/js/utils/viewStack.js'
HOST_BRIDGE = PROJECT_ROOT / 'static/js/utils/hostBridge.js'


def run_node(script_body):
    """跑一段 Node ESM 脚本，返回解析后的 JSON 结果。"""
    node_script = textwrap.dedent(
        f"""
        const results = [];
        const listeners = {{}};

        globalThis.CustomEvent = class CustomEvent {{
          constructor(type, options) {{ this.type = type; this.detail = (options || {{}}).detail; }}
        }};

        function makeWindow() {{
          const historyStack = [{{ state: null }}];
          let cursor = 0;
          return {{
            addEventListener(type, handler) {{
              (listeners[type] = listeners[type] || []).push(handler);
            }},
            removeEventListener(type, handler) {{
              const arr = listeners[type] || [];
              const i = arr.indexOf(handler);
              if (i >= 0) arr.splice(i, 1);
            }},
            dispatchEvent(event) {{
              (listeners[event.type] || []).forEach((fn) => fn(event));
              return true;
            }},
            history: {{
              pushState(state) {{ historyStack.splice(++cursor); historyStack.push({{ state }}); }},
              back() {{ setTimeout(() => {{
                if (cursor > 0) {{ cursor--; window.dispatchEvent({{type:'popstate',state:this.state}}); }}
              }}, 0); }},
              get state() {{ return historyStack[cursor].state; }},
              get length() {{ return historyStack.length; }},
            }},
          }};
        }}

        globalThis.window = makeWindow();

        {script_body}

        console.log('@@RESULT@@' + JSON.stringify(results));
        """
    )

    proc = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=90,
    )
    if proc.returncode != 0:
        pytest.fail(f'Node 执行失败:\nstdout={proc.stdout}\nstderr={proc.stderr}')

    for line in proc.stdout.splitlines():
        if line.startswith('@@RESULT@@'):
            return json.loads(line[len('@@RESULT@@'):])
    pytest.fail(f'未拿到结果:\nstdout={proc.stdout}\nstderr={proc.stderr}')


def _prelude():
    return textwrap.dedent(
        f"""
        const vs = await import({json.dumps(VIEW_STACK.as_uri())});
        """
    )


def test_component_lookup_reuses_index_and_tracks_dynamic_scopes():
    out = run_node(_prelude() + """
        let invalidate, scans = 0;
        globalThis.MutationObserver = class {
          constructor(callback) { invalidate = callback; }
          observe() {}
          disconnect() {}
        };
        const element = attrs => ({ getAttribute: key => attrs[key] || null });
        const first = element({'x-data': 'detailModal()'});
        const nested = element({'data-back-scope': 'header-batch-actions'});
        let elements = [first, nested];
        const lookup = vs.createComponentLookup({
          querySelectorAll() { scans++; return elements; },
        });
        results.push(lookup('detailModal') === first);
        results.push(lookup('header-batch-actions') === nested);
        for (let i = 0; i < 100; i++) lookup('not-mounted');
        results.push(scans);
        const replacement = element({'x-data': 'detailModal'});
        elements = [replacement];
        invalidate();
        results.push(lookup('detailModal') === replacement);
        results.push(lookup('header-batch-actions') === null);
        results.push(scans);
        lookup.disconnect();
    """)
    assert out == [True, True, 1, True, True, 2]


def test_unchanged_depth_does_not_repeat_host_notifications():
    out = run_node(_prelude() + """
        const notifications = [];
        window.addEventListener(vs.VIEW_STACK_EVENT, e => notifications.push(e.detail.depth));
        let open = false;
        vs.register({key:'overlay', isActive:()=>open, close:()=>{open=false;}});
        for (let i = 0; i < 100; i++) vs.sync();
        open = true;
        vs.sync();
        vs.sync();
        vs.closeTop();
        results.push(notifications);
    """)
    assert out == [[0, 1, 0]]


def test_close_top_is_lifo():
    """后注册的层先被关闭（LIFO）。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        const order = [];
        let a = true, b = true;
        vs.register({ key: 'a', isActive: () => a, close: () => { order.push('a'); a = false; } });
        vs.register({ key: 'b', isActive: () => b, close: () => { order.push('b'); b = false; } });

        vs.closeTop();
        vs.closeTop();
        const noMore = vs.closeTop();

        results.push({ order, noMore, depth: vs.depth() });
        """
        )
    )
    out = run_node(body)[0]
    assert out['order'] == ['b', 'a'], '应按注册逆序关闭'
    assert out['noMore'] is False, '层关完后 closeTop 应返回 false'
    assert out['depth'] == 0


def test_inactive_layer_is_skipped():
    """isActive 为 false 的层不参与返回，也不被关闭。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        const order = [];
        vs.register({ key: 'off', isActive: () => false, close: () => order.push('off') });
        let on = true;
        vs.register({ key: 'on', isActive: () => on, close: () => { order.push('on'); on = false; } });

        vs.closeTop();
        const second = vs.closeTop();

        results.push({ order, second, depth: vs.depth() });
        """
        )
    )
    out = run_node(body)[0]
    assert out['order'] == ['on']
    assert out['second'] is False


def test_throwing_isActive_does_not_break_stack():
    """组件销毁后 getter 抛错，不得打断返回流程。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        const order = [];
        vs.register({ key: 'boom', isActive: () => { throw new Error('destroyed'); }, close: () => order.push('boom') });
        let ok = true;
        vs.register({ key: 'ok', isActive: () => ok, close: () => { order.push('ok'); ok = false; } });

        vs.closeTop();
        results.push({ order, depth: vs.depth() });
        """
        )
    )
    out = run_node(body)[0]
    assert out['order'] == ['ok']


def test_handle_back_falls_through_to_workspace_then_system():
    """栈空 → 工作区回默认模式 → 再返回才交还系统。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        let mode = 'worldinfo';
        const workspace = {
          getMode: () => mode,
          getHomeMode: () => 'cards',
          setMode: (m) => { mode = m; },
        };

        const first = vs.handleBack(workspace);   // 栈空 → 回默认工作区
        const modeAfter = mode;
        const second = vs.handleBack(workspace);  // 已在默认工作区 → 交还系统

        results.push({ first, modeAfter, second });
        """
        )
    )
    out = run_node(body)[0]
    assert out['first'] is True
    assert out['modeAfter'] == 'cards'
    assert out['second'] is False, '已在默认工作区时应交还系统（Android 才真正退出）'


def test_layer_wins_over_workspace():
    """有活动层时，返回只关层，不动工作区。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        let mode = 'worldinfo';
        let modal = true;
        vs.register({ key: 'm', isActive: () => modal, close: () => { modal = false; } });
        const workspace = {
          getMode: () => mode,
          getHomeMode: () => 'cards',
          setMode: (m) => { mode = m; },
        };

        vs.handleBack(workspace);
        results.push({ modal, mode });
        """
        )
    )
    out = run_node(body)[0]
    assert out['modal'] is False
    assert out['mode'] == 'worldinfo', '关弹窗时不得同时切换工作区'


def test_history_sentinel_pushed_and_popped():
    """有活动层时压入哨兵项（让 WebView 的 canGoBack() 为真），关完后退掉。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        const before = window.history.length;
        vs.install();
        let active = true;
        vs.register({ key: 'x', isActive: () => active, close: () => { active = false; } });
        const during = window.history.length;
        const stateDuring = window.history.state;

        active = false;
        vs.sync();
        await new Promise(resolve => setTimeout(resolve, 10));
        const after = window.history.length;

        results.push({ before, during, after, cleared: !window.history.state?.__viewStack,
          hasSentinel: !!(stateDuring && stateDuring.__viewStack) });
        """
        )
    )
    out = run_node(body)[0]
    assert out['during'] == out['before'] + 1, '进入有层状态应压入哨兵'
    assert out['hasSentinel'] is True
    assert out['after'] == out['during'], 'history.length 包含前进历史，回退不减少 length'
    assert out['cleared'] is True


def test_no_history_churn_when_depth_unchanged():
    """层数在非零之间变化时，不应反复 push/back。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        const before = window.history.length;
        let a = true, b = false;
        vs.register({ key: 'a', isActive: () => a, close: () => { a = false; } });
        vs.register({ key: 'b', isActive: () => b, close: () => { b = false; } });
        const afterOne = window.history.length;

        b = true;   // 深度 1 → 2
        vs.sync();
        const afterTwo = window.history.length;

        results.push({ before, afterOne, afterTwo });
        """
        )
    )
    out = run_node(body)[0]
    assert out['afterOne'] == out['before'] + 1
    assert out['afterTwo'] == out['afterOne'], '深度 1→2 不应再压哨兵'


def test_register_rejects_malformed_layer():
    body = (
        _prelude()
        + textwrap.dedent(
            """
        let err = '';
        try { vs.register({ key: 'bad' }); } catch (e) { err = e.constructor.name; }
        results.push({ err });
        """
        )
    )
    out = run_node(body)[0]
    assert out['err'] == 'TypeError'


# --- 静态契约：接入点必须存在且不破坏既有 Escape ---


def test_layout_registers_layers_and_installs_bridge():
    source = (PROJECT_ROOT / 'static/js/components/layout.js').read_text(encoding='utf-8')
    assert 'registerViewLayer' in source
    assert 'installHostBridge' in source
    assert '_installBackGestureSupport' in source


def test_layout_keeps_existing_escape_handler():
    """既有 Escape 取消拖拽的行为必须保留（返回手势是新增通道，不是替换）。"""
    source = (PROJECT_ROOT / 'static/js/components/layout.js').read_text(encoding='utf-8')
    assert 'e.key === "Escape"' in source
    assert 'handleGlobalDragEnd' in source


def test_host_bridge_exposes_back_hook_for_native_shell():
    source = HOST_BRIDGE.read_text(encoding='utf-8')
    assert '__stmHostBack' in source, 'Android 壳需要一个可调用的返回钩子'
    assert 'handleBack' in source


def test_layout_registers_context_menu_layer():
    """右键/长按菜单必须注册到视图栈，否则返回键关不掉它。

    真机实测发现：菜单打开时按返回键毫无反应，因为 contextMenu 组件
    不在 layout 的 x-data 作用域内，我最初只注册了设置弹窗与标签筛选。
    该组件通过全局事件 `hide-context-menu` 收口。
    """
    source = (PROJECT_ROOT / 'static/js/components/layout.js').read_text(encoding='utf-8')
    assert 'context-menu' in source, '应注册 context-menu 层'
    assert 'hide-context-menu' in source, '应通过既有事件关闭菜单'
    assert 'Alpine.$data' in source, '需要读组件状态判断菜单是否可见'


def test_layout_registers_mobile_navigation_layers():
    """移动端导航（左侧抽屉、右侧入口坞）必须参与返回。

    用户反馈：打开左侧视图导航栏或右侧入口/设置导航后，按返回键直接
    退回桌面退出应用——因为它们从没注册成视图层。
    """
    source = (PROJECT_ROOT / 'static/js/components/layout.js').read_text(encoding='utf-8')
    assert 'visibleSidebar' in source, '左侧导航栏应参与返回'
    assert 'entryDock' in source, '右侧入口坞应参与返回'
    assert 'entry-dock:collapse' in source, '应有收起入口坞的兜底通道'


def test_navigation_layers_are_gated_by_floating_not_device():
    """「是否参与返回」的判据是**浮层性**，不是设备类型本身。

    规则（真机与用户在 392 / 1098 CSS 两档下共同确认）：
      - mobile（<900px）：侧栏是带遮罩的滑入抽屉 → 参与返回
      - tablet / desktop：侧栏常驻占位 → **不参与返回**

    这是真机抓到的顺序 bug：`entry-dock` 无条件 active=true 且移动端默认展开，
    返回键把坞关掉而不是关用户想关的那一层；一次返回被"吃掉"却什么也没关。
    """
    source = (PROJECT_ROOT / 'static/js/components/layout.js').read_text(encoding='utf-8')

    # sidebar 层：必须带 deviceType === "mobile" 条件
    sidebar_block = source.split('key: "sidebar"', 1)[1].split('},', 1)[0]
    assert 'deviceType' in sidebar_block and 'mobile' in sidebar_block, (
        'sidebar 层必须限定 mobile：宽屏下侧栏常驻，不该消费返回键'
    )

    # entry-dock 层：同样必须限定 mobile（桌面竖排坞常驻）
    dock_block = source.split('key: "entry-dock"', 1)[1].split('},', 1)[0]
    assert 'deviceType' in dock_block and 'mobile' in dock_block, (
        'entry-dock 层必须限定 mobile'
    )
    # 且必须显式比较 expanded === true，不能只看真值
    assert 'expanded' in dock_block


def test_view_stack_exposes_diagnostics():
    """必须提供 describe() 诊断快照。

    真机上「返回键直接退出」时，无法从外部区分三种原因：
    层没注册 / isActive 恒 false / DOM 观察没装上。快照能一眼分辨。
    """
    source = (PROJECT_ROOT / 'static/js/utils/viewStack.js').read_text(encoding='utf-8')
    assert 'export function describe' in source

    bridge = (PROJECT_ROOT / 'static/js/utils/hostBridge.js').read_text(encoding='utf-8')
    assert '__stmViewStack' in bridge, '诊断快照应挂到 window 便于 adb/CDP 读取'
    assert 'describeStack' in bridge


def test_context_menu_component_honors_hide_event():
    """contextMenu 组件本身必须监听 hide-context-menu（注册层依赖它）。"""
    source = (PROJECT_ROOT / 'static/js/components/contextMenu.js').read_text(encoding='utf-8')
    assert 'hide-context-menu' in source
    assert 'hideContextMenu' in source
