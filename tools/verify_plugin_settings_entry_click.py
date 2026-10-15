"""端到端验证：从设置页「插件设置入口」点击后，插件面板确实可见。

对应原始问题：点击插件注册的面板后，面板被设置页盖住看不到。

跑法（需应用运行在 http://127.0.0.1:5000）：
    python tools/verify_plugin_settings_entry_click.py
"""

import argparse
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - 开发工具的可选依赖
    print(
        '需要 Playwright 才能运行本工具（不属于运行时依赖）：\n'
        '    pip install playwright && playwright install chromium'
    )
    raise SystemExit(2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:5000')
    args = parser.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.goto(args.base_url, wait_until='domcontentloaded')
        page.wait_for_function(
            "() => Boolean(window.Alpine && window.Alpine.store"
            " && window.Alpine.store('global'))",
            timeout=15000,
        )
        page.wait_for_timeout(600)
        page.evaluate("() => { const g = window.Alpine.store('global'); g.isDarkMode = true; g.applyDarkMode(); }")

        page.evaluate(
            "() => window.dispatchEvent(new CustomEvent('open-settings-section',"
            " { detail: { section: 'plugins' } }))"
        )
        page.wait_for_selector('.settings-modal-overlay', state='visible', timeout=8000)
        page.wait_for_timeout(1500)

        buttons = page.query_selector_all('.plugin-settings-entry')
        print(f'发现 {len(buttons)} 个插件设置入口')
        if not buttons:
            print('FAIL  没有渲染出任何插件设置入口')
            browser.close()
            return 1

        failures = []
        for index, button in enumerate(buttons):
            label = (button.inner_text() or '').replace('\n', ' / ').strip()
            button.click()
            page.wait_for_timeout(1200)

            # 只看**对话框型** surface：`--ambient` 是常驻图层（如桌面宠物），
            # 全屏透明且 pointer-events: none，与本次回归无关。
            state = page.evaluate(
                """() => {
                  const shell = document.querySelector(
                    '#plugin-surface-root .plugin-surface:not(.plugin-surface--ambient)'
                  );
                  const overlay = document.querySelector('.settings-modal-overlay');
                  if (!shell) return { opened: false };
                  const cs = getComputedStyle(shell);
                  const rect = shell.getBoundingClientRect();
                  // 取容器中心点，看命中的是最上层元素还是设置页
                  const cx = rect.left + rect.width / 2;
                  const cy = rect.top + rect.height / 2;
                  const top = document.elementFromPoint(cx, cy);
                  return {
                    opened: true,
                    cls: shell.className,
                    zIndex: cs.zIndex,
                    visible: cs.display !== 'none' && cs.visibility !== 'hidden',
                    w: Math.round(rect.width), h: Math.round(rect.height),
                    coveredBySettings: Boolean(overlay) && overlay.contains(top),
                    hitIsInsideShell: Boolean(shell.contains(top)),
                    settingsStillOpen: Boolean(overlay)
                      && getComputedStyle(overlay).display !== 'none',
                  };
                }"""
            )

            if not state.get('opened'):
                failures.append(f'{label}: 点击后没有 surface 挂载')
                print(f'  [{index}] {label}\n        FAIL 没有 surface')
                continue

            print(f"  [{index}] {label}")
            print(f"        class={state['cls']}")
            print(f"        z-index={state['zIndex']}  size={state['w']}x{state['h']}")
            print(f"        visible={state['visible']}  hit-in-shell={state['hitIsInsideShell']}"
                  f"  covered-by-settings={state['coveredBySettings']}")
            print(f"        设置页仍打开={state['settingsStillOpen']}")

            if not state['visible']:
                failures.append(f'{label}: surface 不可见')
            if state['coveredBySettings']:
                failures.append(f'{label}: 面板被设置页盖住（核心回归）')
            if not state['hitIsInsideShell']:
                failures.append(f'{label}: 面板中心点命中的不是面板本身')

            # 关闭该 surface，继续测下一个
            page.evaluate(
                """() => {
                  const shell = document.querySelector(
                    '#plugin-surface-root .plugin-surface:not(.plugin-surface--ambient)'
                  );
                  const close = shell && shell.querySelector('.plugin-surface__close');
                  if (close) close.click();
                }"""
            )
            page.wait_for_timeout(800)

        browser.close()

    print()
    if failures:
        for item in failures:
            print(f'FAIL  {item}')
        return 1
    print('PASS  所有插件设置入口点开后都可见，且未被设置页遮挡')
    return 0


if __name__ == '__main__':
    sys.exit(main())
