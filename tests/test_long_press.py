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

        globalThis.document = {{
          addEventListener(type, handler) {{
            (docListeners[type] = docListeners[type] || []).push(handler);
          }},
          removeEventListener(type, handler) {{
            const arr = docListeners[type] || [];
            const i = arr.indexOf(handler);
            if (i >= 0) arr.splice(i, 1);
          }},
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
