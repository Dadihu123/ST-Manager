"""触摸长按 → 合成 contextmenu 的行为测试。

用 Node 加载真实模块，stub 出 document/window/document 事件系统，
验证：长按触发合成事件、位移取消、排除标记、原生去重、桌面不挂钩子。
"""

import json
import subprocess
import textwrap
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LONG_PRESS = PROJECT_ROOT / 'static/js/utils/longPress.js'


def test_consumed_long_press_suppresses_release_click_only_on_its_target():
    out = run_node(_prelude() + """
        lp.installLongPressContextMenu();
        const node = makeElement();
        const touch = {clientX:50, clientY:80, screenX:50, screenY:80};
        fireDoc('touchstart', {target:node, touches:[touch]});
        await new Promise(r=>setTimeout(r, lp.LONG_PRESS_MS + 20));
        fireDoc('touchend', {});
        let prevented = 0, stopped = 0;
        const click = target => ({target, preventDefault(){prevented++;}, stopImmediatePropagation(){stopped++;}});
        fireDoc('click', click(makeElement()));
        results.push(prevented);
        fireDoc('click', click(node));
        fireDoc('click', click(node));
        results.push({prevented, stopped});
        lp.__resetForTests();
    """)
    assert out == [0, {'prevented': 1, 'stopped': 1}]


def test_implicit_image_drag_is_blocked_only_inside_business_targets():
    out = run_node(_prelude() + """
        lp.installLongPressContextMenu();
        const card = makeElement();
        const image = makeElement({});
        image.parentElement = card;
        let prevented = 0, stopped = 0;
        const drag = target => ({target, preventDefault(){prevented++;}, stopPropagation(){stopped++;}});
        fireDoc('dragstart', drag(makeElement({})));
        results.push(prevented);
        fireDoc('dragstart', drag(image));
        results.push({prevented,stopped});
        lp.__resetForTests();
    """)
    assert out == [0, {'prevented': 1, 'stopped': 1}]


def run_node(script_body, touch=True):
    """在 stub 出的 DOM 环境里跑一段 ESM 脚本。"""
    node_script = textwrap.dedent(
        f"""
        const results = [];
        const docListeners = {{}};
        const dispatched = [];

        function makeElement(attrs = {{'data-long-press-menu': ''}}) {{
          const el = {{
            nodeType: 1,
            parentElement: null,
            attributes: {{ ...attrs }},
            hasAttribute(name) {{ return Object.prototype.hasOwnProperty.call(this.attributes, name); }},
            dispatchEvent(event) {{
              dispatched.push({{ type: event.type, clientX: event.clientX, clientY: event.clientY }});
              // 模拟 Alpine 的 @contextmenu.prevent：调用 preventDefault。
              if (typeof event.preventDefault === 'function') event.preventDefault();
              return !event.defaultPrevented;
            }},
          }};
          return el;
        }}

        globalThis.MouseEvent = class MouseEvent {{
          constructor(type, init = {{}}) {{
            this.type = type;
            this.bubbles = !!init.bubbles;
            this.cancelable = !!init.cancelable;
            this.clientX = init.clientX || 0;
            this.clientY = init.clientY || 0;
            this.screenX = init.screenX || 0;
            this.screenY = init.screenY || 0;
            this.defaultPrevented = false;
          }}
          preventDefault() {{ this.defaultPrevented = true; }}
        }};

        // 触摸设备上 disableNativeDragForTouch 会扫 [draggable="true"]，
        // 这里提供一个可注入的假节点列表，让测试能断言「被摘掉了」。
        globalThis.__dragCandidates = [];
        globalThis.__observed = [];
        globalThis.__observerCallbacks = [];
        globalThis.MutationObserver = class MutationObserver {{
          constructor(cb) {{
            this._cb = cb;
            globalThis.__observerCallbacks.push(cb);
          }}
          observe(target, opts) {{ globalThis.__observed.push({{ target, opts }}); }}
          disconnect() {{ globalThis.__observed.push('disconnected'); }}
        }};

        globalThis.document = {{
          addEventListener(type, handler) {{
            (docListeners[type] = docListeners[type] || []).push(handler);
          }},
          removeEventListener(type, handler) {{
            const arr = docListeners[type] || [];
            const i = arr.indexOf(handler);
            if (i >= 0) arr.splice(i, 1);
          }},
          querySelectorAll(selector) {{
            if (selector === '[draggable="true"]') return globalThis.__dragCandidates;
            return [];
          }},
          documentElement: {{}},
        }};

        // Node 新版把 navigator 暴露成只读 getter，必须用 defineProperty 覆盖。
        Object.defineProperty(globalThis, 'navigator', {{
          value: {{ maxTouchPoints: {1 if touch else 0} }},
          configurable: true,
          writable: true,
        }});
        globalThis.window = {{
          ontouchstart: {'function(){}' if touch else 'undefined'},
          matchMedia: (q) => ({{ matches: {str(touch).lower()} }}),
        }};

        function fireDoc(type, payload) {{
          (docListeners[type] || []).forEach((fn) => fn(payload));
        }}

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
        const lp = await import({json.dumps(LONG_PRESS.as_uri())});
        const dispatchedBefore = () => dispatched.length;
        """
    )


def test_long_press_synthesizes_contextmenu_with_coordinates():
    """按住超过阈值后，应派发带真实坐标的 contextmenu。"""
    body = (
        _prelude()
        + textwrap.dedent(
            f"""
        lp.installLongPressContextMenu();
        const el = makeElement();
        fireDoc('touchstart', {{
          touches: [{{ clientX: 120, clientY: 240, screenX: 120, screenY: 240 }}],
          target: el,
        }});
        await new Promise((r) => setTimeout(r, lp.LONG_PRESS_MS + 120));

        results.push({{ dispatched }});
        """
        )
    )
    out = run_node(body)[0]
    assert len(out['dispatched']) == 1
    assert out['dispatched'][0]['type'] == 'contextmenu'
    assert out['dispatched'][0]['clientX'] == 120
    assert out['dispatched'][0]['clientY'] == 240


def test_short_tap_does_not_fire():
    """短按（未达阈值）不得触发右键菜单。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        lp.installLongPressContextMenu();
        const el = makeElement();
        fireDoc('touchstart', { touches: [{ clientX: 10, clientY: 10 }], target: el });
        await new Promise((r) => setTimeout(r, 100));
        fireDoc('touchend', {});
        await new Promise((r) => setTimeout(r, 400));

        results.push({ dispatched });
        """
        )
    )
    out = run_node(body)[0]
    assert out['dispatched'] == []


def test_moving_finger_cancels_long_press():
    """手指移动超过容忍值（视为滚动）应取消。"""
    body = (
        _prelude()
        + textwrap.dedent(
            f"""
        lp.installLongPressContextMenu();
        const el = makeElement();
        fireDoc('touchstart', {{ touches: [{{ clientX: 10, clientY: 10 }}], target: el }});
        fireDoc('touchmove', {{ touches: [{{ clientX: 60, clientY: 90 }}] }});
        await new Promise((r) => setTimeout(r, lp.LONG_PRESS_MS + 120));

        results.push({{ dispatched }});
        """
        )
    )
    out = run_node(body)[0]
    assert out['dispatched'] == []


def test_small_jitter_still_fires():
    """轻微抖动（未超容忍值）仍应触发。"""
    body = (
        _prelude()
        + textwrap.dedent(
            f"""
        lp.installLongPressContextMenu();
        const el = makeElement();
        fireDoc('touchstart', {{ touches: [{{ clientX: 10, clientY: 10 }}], target: el }});
        fireDoc('touchmove', {{ touches: [{{ clientX: 13, clientY: 12 }}] }});
        await new Promise((r) => setTimeout(r, lp.LONG_PRESS_MS + 120));

        results.push({{ dispatched }});
        """
        )
    )
    out = run_node(body)[0]
    assert len(out['dispatched']) == 1


def test_excluded_element_is_skipped():
    """带 data-no-long-press 的元素不参与长按合成。"""
    body = (
        _prelude()
        + textwrap.dedent(
            f"""
        lp.installLongPressContextMenu();
        const el = makeElement({{ 'data-no-long-press': '' }});
        fireDoc('touchstart', {{ touches: [{{ clientX: 10, clientY: 10 }}], target: el }});
        await new Promise((r) => setTimeout(r, lp.LONG_PRESS_MS + 120));

        results.push({{ dispatched }});
        """
        )
    )
    out = run_node(body)[0]
    assert out['dispatched'] == []


def test_ancestor_exclusion_applies_to_children():
    """父元素被排除时，子元素也不触发（事件冒泡链上的属性都检查）。"""
    body = (
        _prelude()
        + textwrap.dedent(
            f"""
        lp.installLongPressContextMenu();
        const parent = makeElement({{ 'data-no-long-press': '' }});
        const child = makeElement();
        child.parentElement = parent;
        fireDoc('touchstart', {{ touches: [{{ clientX: 10, clientY: 10 }}], target: child }});
        await new Promise((r) => setTimeout(r, lp.LONG_PRESS_MS + 120));

        results.push({{ dispatched }});
        """
        )
    )
    out = run_node(body)[0]
    assert out['dispatched'] == []


def test_native_contextmenu_is_taken_over_not_ignored():
    """原生 contextmenu 必须被接管（preventDefault + 按手指坐标重新合成）。

    这是真机测出来的关键行为：Android WebView 在长按约 500ms 时会**自己**派发
    contextmenu，坐标是系统的（页面角落/文字选区），不是手指位置。
    旧实现在收到它时取消自己的长按 → 合成事件永远发不出 → **长按没有任何菜单**。

    新语义：拦掉系统默认菜单，用我们记录的落点合成一个正确的事件。
    """
    body = (
        _prelude()
        + textwrap.dedent(
            f"""
        lp.installLongPressContextMenu();
        const el = makeElement();
        fireDoc('touchstart', {{ touches: [{{ clientX: 120, clientY: 240 }}], target: el }});

        // 模拟浏览器在长按期间派发自己的 contextmenu（坐标是错的 58,40）
        let prevented = false;
        const nativeEvt = {{
          type: 'contextmenu',
          clientX: 58,
          clientY: 40,
          defaultPrevented: false,
          preventDefault() {{ this.defaultPrevented = true; prevented = true; }},
          stopPropagation() {{}},
        }};
        fireDoc('contextmenu', nativeEvt);

        await new Promise((r) => setTimeout(r, lp.LONG_PRESS_MS + 150));

        results.push({{ prevented, dispatched }});
        """
        )
    )
    out = run_node(body)[0]

    assert out['prevented'] is True, '必须拦掉系统默认的 contextmenu'
    assert len(out['dispatched']) == 1, '应合成且仅合成一次'
    # 关键：用的是手指坐标，不是系统给的 58,40
    assert out['dispatched'][0]['clientX'] == 120
    assert out['dispatched'][0]['clientY'] == 240


def test_native_contextmenu_without_pending_is_ignored():
    """没有进行中的长按时，原生 contextmenu 不干预（可能是系统在别处触发）。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        lp.installLongPressContextMenu();
        let prevented = false;
        const nativeEvt = {
          type: 'contextmenu',
          clientX: 10,
          clientY: 10,
          preventDefault() { prevented = true; },
          stopPropagation() {},
        };
        fireDoc('contextmenu', nativeEvt);
        await new Promise((r) => setTimeout(r, 100));

        results.push({ prevented, dispatched });
        """
        )
    )
    out = run_node(body)[0]
    assert out['prevented'] is False
    assert out['dispatched'] == []


def test_desktop_does_not_install_touch_handlers():
    """桌面（fine pointer + 无触摸）不挂钩子，鼠标右键路径保持原样。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        const installed = lp.installLongPressContextMenu();
        const handlerCount = Object.values(docListeners).reduce((n, arr) => n + arr.length, 0);
        results.push({ installed, handlerCount, isTouch: lp.isTouchDevice() });
        """
        )
    )
    out = run_node(body, touch=False)[0]
    assert out['isTouch'] is False
    assert out['handlerCount'] == 0, '桌面环境不应注册任何触摸监听'


def test_two_finger_touch_never_fires():
    """双指（缩放）不触发长按菜单。"""
    body = (
        _prelude()
        + textwrap.dedent(
            f"""
        lp.installLongPressContextMenu();
        const el = makeElement();
        fireDoc('touchstart', {{ touches: [
          {{ clientX: 10, clientY: 10 }},
          {{ clientX: 80, clientY: 80 }},
        ], target: el }});
        await new Promise((r) => setTimeout(r, lp.LONG_PRESS_MS + 120));

        results.push({{ dispatched }});
        """
        )
    )
    out = run_node(body)[0]
    assert out['dispatched'] == []


# --- 静态契约 ---


def test_all_contextmenu_elements_are_marked():
    """所有 @contextmenu 元素都要带 data-long-press-menu，确保 tooltip 不抢长按。"""
    templates = PROJECT_ROOT / 'templates'
    total_context = 0
    total_marked = 0
    for path in templates.rglob('*.html'):
        text = path.read_text(encoding='utf-8')
        total_context += text.count('@contextmenu')
        total_marked += text.count('data-long-press-menu')

    assert total_context > 0
    assert total_marked == total_context, (
        f'@contextmenu 有 {total_context} 处，但标记只有 {total_marked} 处'
    )


def test_layout_installs_long_press():
    source = (PROJECT_ROOT / 'static/js/components/layout.js').read_text(encoding='utf-8')
    assert 'installLongPressContextMenu' in source


def test_tooltip_skips_elements_with_context_menu():
    """tooltip 的触摸长按必须跳过带右键菜单的元素。"""
    source = (PROJECT_ROOT / 'static/js/utils/tooltip.js').read_text(encoding='utf-8')
    assert 'data-long-press-menu' in source
    assert 'isTooltipEligibleForTouch' in source


def test_tooltip_has_touch_channel():
    source = (PROJECT_ROOT / 'static/js/utils/tooltip.js').read_text(encoding='utf-8')
    assert 'onTouchStart' in source
    assert 'TOUCH_LONG_PRESS_MS' in source


# ---------------------------------------------------------------------------
# 原生拖拽与长按菜单的冲突
#
# 真机上 `draggable="true"` 的元素（卡片、侧栏文件夹）长按时，浏览器会进入
# 原生拖拽并抢占这个时段，导致长按菜单「有时弹、有时不弹」。
# 触摸端本就没有可用的 HTML5 拖放，因此安装长按桥时把 draggable 摘掉。
# ---------------------------------------------------------------------------


def test_touch_install_strips_native_draggable():
    """触摸设备上安装长按桥时，必须把现有 draggable=true 摘成 false。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        const el = {
          nodeType: 1,
          attributes: { draggable: 'true' },
          getAttribute(n) { return this.attributes[n] ?? null; },
          setAttribute(n, v) { this.attributes[n] = v; },
        };
        globalThis.__dragCandidates.push(el);

        lp.installLongPressContextMenu();

        results.push({ draggable: el.getAttribute('draggable'), marked: el.getAttribute('data-drag-disabled') });
        """
        )
    )
    out = run_node(body)[0]

    assert out['draggable'] == 'false', (
        '触摸设备上必须摘掉原生 draggable，否则会与长按菜单抢时段'
    )
    assert out['marked'] == '1', '应记录 data-drag-disabled 便于排查'


def test_touch_install_observes_later_draggable():
    """Alpine 重新渲染后新出现的 draggable 也要被摘掉（靠 MutationObserver）。

    必须同时观察 `childList` 与 `attributes`：只配 attributes 时新插入的节点
    完全不在观察范围内，而 Alpine 的 x-for 渲染卡片正是 appendChild。
    这个漏配在真机上验证时才暴露（注入的 draggable 元素没被摘掉）。
    """
    body = (
        _prelude()
        + textwrap.dedent(
            """
        lp.installLongPressContextMenu();

        const calls = globalThis.__observed.filter((o) => typeof o === 'object');
        const opts = calls[0] ? calls[0].opts : {};
        results.push({
          observed: calls.length,
          filter: opts.attributeFilter,
          childList: opts.childList,
          subtree: opts.subtree,
        });
        """
        )
    )
    out = run_node(body)[0]

    assert out['observed'] >= 1, '应安装 MutationObserver 观察后续变化'
    assert out['filter'] == ['draggable'], '应只观察 draggable 属性，避免无谓开销'
    assert out['childList'] is True, (
        '必须观察 childList，否则新插入的卡片（Alpine x-for）不会被摘掉'
    )
    assert out['subtree'] is True, '需要 subtree 才能覆盖深层节点'


def test_observer_strips_newly_added_nodes():
    """新增的 draggable 节点（appendChild）必须被摘掉。

    真机验证发现的缺陷：只监听 attributes 时，动态插入的节点漏掉了。
    """
    body = (
        _prelude()
        + textwrap.dedent(
            """
        lp.installLongPressContextMenu();

        // 取出注册的回调，模拟一条 childList 记录
        const calls = globalThis.__observed.filter((o) => typeof o === 'object');
        const cb = globalThis.__observerCallbacks[0];

        const added = {
          nodeType: 1,
          attributes: { draggable: 'true' },
          getAttribute(n) { return this.attributes[n] ?? null; },
          setAttribute(n, v) { this.attributes[n] = v; },
          querySelectorAll() { return []; },
        };
        cb([{ type: 'childList', addedNodes: [added] }]);

        results.push({ draggable: added.getAttribute('draggable'), marked: added.getAttribute('data-drag-disabled') });
        """
        )
    )
    out = run_node(body)[0]

    assert out['draggable'] == 'false', (
        'childList 新增的 draggable 节点必须被摘掉'
    )
    assert out['marked'] == '1'


def test_desktop_install_does_not_touch_draggable():
    """桌面端必须保持原生拖放不变——鼠标拖放是主交互，不能动。"""
    body = (
        _prelude()
        + textwrap.dedent(
            """
        const el = {
          nodeType: 1,
          attributes: { draggable: 'true' },
          getAttribute(n) { return this.attributes[n] ?? null; },
          setAttribute(n, v) { this.attributes[n] = v; },
        };
        globalThis.__dragCandidates.push(el);

        lp.installLongPressContextMenu();

        results.push({ draggable: el.getAttribute('draggable') });
        """
        )
    )
    out = run_node(body, touch=False)[0]

    assert out['draggable'] == 'true', (
        '桌面端不得改动 draggable；本模块只在触摸设备生效'
    )


def test_drag_toggle_is_documented():
    """摘 draggable 是「损失能力」的决定，源码里必须写明为什么可接受。"""
    source = LONG_PRESS.read_text(encoding='utf-8')
    assert 'disableNativeDragForTouch' in source
    # 必须说明触摸端本就没有 HTML5 拖放、以及等价入口在哪
    assert 'touch' in source.lower()
    assert 'draggable' in source
