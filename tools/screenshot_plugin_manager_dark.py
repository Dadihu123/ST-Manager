"""在真实浏览器里截取插件管理页的两个修复点，用于人工核对深色模式观感。

跑法（需应用运行在 http://127.0.0.1:5000）：
    python tools/screenshot_plugin_manager_dark.py
产物落在 data/tmp/ 下，不进版本库。
"""

import argparse
import os

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - 开发工具的可选依赖
    print(
        '需要 Playwright 才能运行本工具（不属于运行时依赖）：\n'
        '    pip install playwright && playwright install chromium'
    )
    raise SystemExit(2)

OUT_DIR = os.path.join('data', 'tmp')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:5000')
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        page.goto(args.base_url, wait_until='domcontentloaded')
        page.wait_for_function(
            "() => getComputedStyle(document.documentElement)"
            ".getPropertyValue('--z-modal-std').trim() !== ''",
            timeout=15000,
        )

        # 等 Alpine 与全局 store 就绪（CSS 变量就绪 ≠ store 就绪）
        page.wait_for_function(
            "() => Boolean(window.Alpine && window.Alpine.store && window.Alpine.store('global'))",
            timeout=15000,
        )
        page.wait_for_timeout(800)

        # 强制深色模式：直接走应用的 store，等同用户点「深色模式」开关
        page.evaluate(
            """() => {
              const g = window.Alpine.store('global');
              g.isDarkMode = true;
              g.applyDarkMode();
            }"""
        )
        page.wait_for_timeout(300)
        mode = page.evaluate(
            "() => document.documentElement.classList.contains('light-mode') ? 'light' : 'dark'"
        )
        print(f'当前主题模式: {mode}')
        if mode != 'dark':
            print('警告：未能切到深色模式，截图不代表深色观感')

        page.evaluate(
            "() => window.dispatchEvent(new CustomEvent('open-settings-section',"
            " { detail: { section: 'plugins' } }))"
        )
        page.wait_for_selector('.settings-modal-overlay', state='visible', timeout=8000)
        page.wait_for_timeout(1500)
        page.wait_for_timeout(1200)

        shots = []

        # ① 已安装页：插件设置入口区块
        def shot_installed():
            node = page.query_selector('.plugin-settings-entries')
            if node and node.is_visible():
                node.screenshot(path=os.path.join(OUT_DIR, 'pm-dark-settings-entries.png'))
                return 'pm-dark-settings-entries.png'
            # 没有插件声明 settings 入口时，截已安装页卡片本身作为对照
            body = page.query_selector('#plugin-panel-installed')
            body.screenshot(path=os.path.join(OUT_DIR, 'pm-dark-settings-entries.png'))
            return 'pm-dark-settings-entries.png (无 settings 入口，退化为已安装页)'

        shots.append(shot_installed())

        # ② 官方目录页：已安装胶囊
        page.evaluate(
            "() => { const el = document.querySelector('#plugin-tab-catalog'); el && el.click(); }"
        )
        page.wait_for_timeout(900)
        panel = page.query_selector('#plugin-panel-catalog')
        if panel:
            panel.screenshot(path=os.path.join(OUT_DIR, 'pm-dark-catalog-installed.png'))
            shots.append('pm-dark-catalog-installed.png')

        # ③ 入口总览页：筛选输入框
        page.evaluate(
            "() => { const el = document.querySelector('#plugin-tab-entries'); el && el.click(); }"
        )
        page.wait_for_timeout(900)
        rows = page.query_selector('.plugin-entries-table-wrapper')
        search = page.query_selector('.plugin-entries-search')
        if rows:
            rows.screenshot(path=os.path.join(OUT_DIR, 'pm-dark-entries-search.png'))
            shots.append('pm-dark-entries-search.png')
        if search:
            box = search.bounding_box()
            if box:
                page.screenshot(
                    path=os.path.join(OUT_DIR, 'pm-dark-entries-search-crop.png'),
                    clip={
                        'x': max(0, box['x'] - 24),
                        'y': max(0, box['y'] - 24),
                        'width': min(1440, box['width'] + 48),
                        'height': box['height'] + 48,
                    },
                )
                shots.append('pm-dark-entries-search-crop.png')

        # 数值化核对：搜索框的底色/文字色不再来自 --surface-control
        probe = page.evaluate(
            """() => {
              const el = document.querySelector('.plugin-entries-search');
              if (!el) return null;
              const cs = getComputedStyle(el);
              return { background: cs.backgroundColor, color: cs.color,
                       borderColor: cs.borderTopColor };
            }"""
        )

        browser.close()

    print('深色模式截图：')
    for name in shots:
        print('  ', name)
    print()
    print('筛选输入框计算样式：', probe)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
