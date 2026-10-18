"""在真实浏览器里验证宿主 UI 原语对话框（`api.ui.confirm`）的层级与 ESC 归属。

回归目标：原语遮罩带 `.modal-overlay` 的缺省层级 `--z-modal-std`(1100)，
而插件 surface 的 modal / panel / sheet 在 `--z-modal-popover`(3400)。
于是 `api.ui.confirm()` 从插件面板里弹出时会画在面板**下面**：看得见、点不到，
用户只会觉得「按钮坏了」。实测现场就是本插件的「出站内容提示」：

    AI 分析会把卡片内容发送到你配置的 provider 地址。确认已知晓？

这个脚本把那条链路原样跑一遍（不碰真实数据：用路由拦截把
`outbound_acknowledged` 改成 false），断言三件用户可感的事：

1. 遮罩层级高于插件 surface；
2. 点「确定」按钮正中央时命中测试落在按钮上，且确实发出 `/outbound/ack`；
3. 按 ESC 只关闭对话框，不连带关掉弹它的插件面板
   （`pluginSurfaceHost.js` 在 document 上也有 ESC 监听）。

跑法：
    python tools/verify_primitive_dialog_layering.py
需要应用已在 http://127.0.0.1:5000 运行（或传 --base-url）。
"""

import argparse
import json
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - 开发工具的可选依赖
    print(
        '需要 Playwright 才能运行本工具（不属于运行时依赖）：\n'
        '    pip install playwright && playwright install chromium'
    )
    raise SystemExit(2)


STATUS_ROUTE = '**/api/plugins/stm-ai-assistant/status*'

OPEN_WORKBENCH = """
() => {
  const slot = document.querySelector('[data-entry-key="stm-ai-assistant:workbench"]');
  if (!slot) return false;
  slot.click();
  return true;
}
"""

OPEN_SETTINGS_TAB = """
() => {
  const tab = Array.from(document.querySelectorAll('.plugin-stm-ai-assistant-tab'))
    .find((node) => node.textContent.trim() === '设置');
  if (!tab) return false;
  tab.click();
  return true;
}
"""

PROBE = """
() => {
  const overlay = document.querySelector('.ui-primitive-overlay');
  const surface = document.querySelector('.plugin-surface--modal');
  if (!overlay || !surface) return { ok: false, reason: 'overlay/surface 缺失' };

  const confirmButton = Array.from(overlay.querySelectorAll('button'))
    .find((node) => node.textContent.trim() === '确定');
  if (!confirmButton) return { ok: false, reason: '找不到确定按钮' };

  const rect = confirmButton.getBoundingClientRect();
  const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);

  return {
    ok: true,
    title: (overlay.querySelector('.ui-primitive-dialog__title') || {}).textContent || '',
    overlayZ: getComputedStyle(overlay).zIndex,
    surfaceZ: getComputedStyle(surface).zIndex,
    hitOnConfirmButton: Boolean(hit && confirmButton.contains(hit)),
    hitTag: hit ? String(hit.tagName) : '',
  };
}
"""

SURFACE_STILL_OPEN = """
() => {
  const surface = document.querySelector('.plugin-surface--modal');
  if (!surface) return false;
  const style = getComputedStyle(surface);
  return style.display !== 'none' && style.visibility !== 'hidden';
}
"""


def force_unacknowledged(route):
    """把出站提示的确认状态改成 false，复现「首次打开设置页弹提示」。"""
    response = route.fetch()
    payload = json.loads(response.text())
    payload['outbound_acknowledged'] = False
    route.fulfill(
        status=response.status,
        headers={**response.headers, 'content-type': 'application/json; charset=utf-8'},
        body=json.dumps(payload, ensure_ascii=False),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:5000')
    args = parser.parse_args()

    failures = []
    ack_requests = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.route(STATUS_ROUTE, force_unacknowledged)
        page.on(
            'request',
            lambda request: ack_requests.append(request.url)
            if request.method == 'POST' and '/outbound/ack' in request.url
            else None,
        )

        # 应用有一条常驻 SSE 流，`networkidle` 永远不会触发；等 DOM + 语义令牌即可。
        page.goto(args.base_url, wait_until='domcontentloaded')
        page.wait_for_function(
            "() => getComputedStyle(document.documentElement)"
            ".getPropertyValue('--z-modal-alert').trim() !== ''",
            timeout=15000,
        )

        token = page.evaluate(
            "() => parseInt(getComputedStyle(document.documentElement)"
            ".getPropertyValue('--z-modal-alert').trim(), 10)"
        )
        popover = page.evaluate(
            "() => parseInt(getComputedStyle(document.documentElement)"
            ".getPropertyValue('--z-modal-popover').trim(), 10)"
        )
        print(f'令牌：--z-modal-popover={popover} / --z-modal-alert={token}')
        if not token > popover:
            failures.append(f'--z-modal-alert({token}) 必须高于 --z-modal-popover({popover})')

        # 入口坞由注册表异步渲染（插件 manifest 到达后才出现），先等它建好再点
        try:
            page.wait_for_selector(
                '[data-entry-key="stm-ai-assistant:workbench"]', state='visible', timeout=15000
            )
        except Exception:
            print('FAIL  坞里没有 stm-ai-assistant:workbench 入口（插件未安装？）')
            browser.close()
            return 1

        page.evaluate(OPEN_WORKBENCH)
        page.wait_for_selector('.plugin-surface--modal', state='visible', timeout=8000)

        if not page.evaluate(OPEN_SETTINGS_TAB):
            failures.append('找不到插件面板的「设置」页签')
        page.wait_for_selector('.ui-primitive-overlay', state='visible', timeout=8000)

        probe = page.evaluate(PROBE)
        if not probe.get('ok'):
            failures.append(f"probe 失败：{probe.get('reason')}")
        else:
            print(
                f"场景：{probe['title']} · surface.z={probe['surfaceZ']} / "
                f"overlay.z={probe['overlayZ']} · 命中 {probe['hitTag']} · "
                f"落在确定按钮={probe['hitOnConfirmButton']}"
            )
            if not probe['hitOnConfirmButton']:
                failures.append('确认框被插件面板盖住：点「确定」命中的是面板，不是按钮')
            if int(probe['overlayZ'] or 0) <= int(probe['surfaceZ'] or 0):
                failures.append('原语遮罩层级未高于插件 surface')

        # 场景 A：ESC 只关对话框，插件面板必须还在
        page.keyboard.press('Escape')
        page.wait_for_selector('.ui-primitive-overlay', state='detached', timeout=4000)
        surface_open_after_esc = page.evaluate(SURFACE_STILL_OPEN)
        print(f'ESC 后插件面板仍在：{surface_open_after_esc}')
        if not surface_open_after_esc:
            failures.append('按 ESC 关掉对话框的同时，把插件面板也关掉了（ESC 未被隔离）')
            browser.close()
            print()
            for item in failures:
                print(f'FAIL  {item}')
            return 1

        # 场景 B：真实鼠标点「确定」——这条链路会发 POST /outbound/ack
        # 切走再切回设置页：`showTab` 会 refresh 视图，load() 重新判定未确认状态
        page.evaluate("""() => {
          const tab = Array.from(document.querySelectorAll('.plugin-stm-ai-assistant-tab'))
            .find((node) => node.textContent.trim() === '工作台');
          if (tab) tab.click();
        }""")
        page.evaluate(OPEN_SETTINGS_TAB)
        page.wait_for_selector('.ui-primitive-overlay', state='visible', timeout=8000)

        box = page.evaluate("""() => {
          const overlay = document.querySelector('.ui-primitive-overlay');
          const confirmButton = Array.from(overlay.querySelectorAll('button'))
            .find((node) => node.textContent.trim() === '确定');
          const rect = confirmButton.getBoundingClientRect();
          return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
        }""")
        page.mouse.click(box['x'], box['y'])
        page.wait_for_selector('.ui-primitive-overlay', state='detached', timeout=4000)
        page.wait_for_timeout(600)
        if not ack_requests:
            failures.append('点击「确定」没有发出 POST /outbound/ack（按钮没吃到点击）')
        if not page.evaluate(SURFACE_STILL_OPEN):
            failures.append('点「确定」后插件面板被关掉了（不应如此）')

        browser.close()

    print()
    if failures:
        for item in failures:
            print(f'FAIL  {item}')
        return 1

    print('PASS  出站提示弹在插件 surface 之上；点得到（并真的确认）；ESC 只关自己那一层')
    return 0


if __name__ == '__main__':
    sys.exit(main())
