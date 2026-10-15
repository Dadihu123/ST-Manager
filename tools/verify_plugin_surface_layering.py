"""在真实浏览器里验证插件 surface 与宿主模态的层叠关系。

回归目标（两个都曾在深色模式下暴露）：
1. `.plugin-surface-root` 上的 `z-index` 会创建层叠上下文，把内部所有 surface
   锁在 `--z-surface`(60) 层，宿主模态（设置页 1100）一开就把它们全部盖住。
2. `panel` / `sheet` 型 surface 层级过低，`page` 型则**刻意**低于模态。

跑法：
    python tools/verify_plugin_surface_layering.py
需要应用已在 http://127.0.0.1:5000 运行（或传 --base-url）。
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

# 在页面里把一个 surface 挂到根节点上，测它与设置弹窗的命中顺序。
PROBE = """
([surfaceClass, extraStyle]) => {
  const root = document.getElementById('plugin-surface-root')
    || (() => {
      const node = document.createElement('div');
      node.id = 'plugin-surface-root';
      node.className = 'plugin-surface-root';
      document.body.appendChild(node);
      return node;
    })();

  const shell = document.createElement('div');
  shell.className = surfaceClass;
  shell.style.cssText = extraStyle || '';
  shell.setAttribute('data-probe', '1');
  // 铺一小块可命中的区域，便于 elementFromPoint 判定谁在上面
  shell.innerHTML = '<div data-probe-hit style="position:absolute;inset:0"></div>';
  root.appendChild(shell);

  const overlay = document.querySelector('.settings-modal-overlay');
  const probe = shell.querySelector('[data-probe-hit]');
  const rect = probe.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;

  const topmost = document.elementFromPoint(cx, cy);
  const result = {
    rootZIndex: getComputedStyle(root).zIndex,
    rootCreatesStackingContext: getComputedStyle(root).zIndex !== 'auto',
    overlayZIndex: overlay ? getComputedStyle(overlay).zIndex : null,
    shellZIndex: getComputedStyle(shell).zIndex,
    settingsOverlayOnTop: Boolean(overlay) && overlay.contains(topmost),
    probeOnTop: probe.contains(topmost) || topmost === probe,
  };
  shell.remove();
  return result;
}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:5000')
    args = parser.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        # 应用有一条常驻 SSE 流，`networkidle` 永远不会触发；等 DOM + 语义令牌即可。
        page.goto(args.base_url, wait_until='domcontentloaded')
        page.wait_for_function(
            "() => getComputedStyle(document.documentElement)"
            ".getPropertyValue('--z-modal-std').trim() !== ''",
            timeout=15000,
        )

        # 打开设置弹窗（命令面板 / 顶部按钮都行，这里走 store 提供的入口）
        page.evaluate(
            "() => window.dispatchEvent(new CustomEvent('open-settings-section',"
            " { detail: { section: 'plugins' } }))"
        )
        page.wait_for_selector('.settings-modal-overlay', state='visible', timeout=8000)

        cases = [
            ('modal', 'plugin-surface plugin-surface--modal',
             'top:50%;left:50%;transform:translate(-50%,-50%);width:320px;height:220px;'),
            ('panel', 'plugin-surface plugin-surface--panel',
             'width:320px;height:60vh;'),
            ('sheet', 'plugin-surface plugin-surface--sheet',
             'left:0;right:0;height:40vh;'),
            ('page', 'plugin-surface plugin-surface--page',
             'top:64px;left:0;right:0;bottom:0;'),
        ]

        failures = []
        print('viewport 1440x900 / settings modal open\n')
        print(f"{'type':7} {'root.z':8} {'shell.z':9} {'overlay.z':10} "
              f"{'probe wins':11} {'settings wins'}")
        print('-' * 62)

        for label, cls, style in cases:
            r = page.evaluate(PROBE, [cls, style])
            print(f"{label:7} {str(r['rootZIndex']):8} {str(r['shellZIndex']):9} "
                  f"{str(r['overlayZIndex']):10} {str(r['probeOnTop']):11} "
                  f"{str(r['settingsOverlayOnTop'])}")

            if r['rootCreatesStackingContext']:
                failures.append(
                    f'.plugin-surface-root 创建了层叠上下文 (z-index: {r["rootZIndex"]})'
                )

            # 对话框型 surface 必须盖住设置页
            if label in ('modal', 'panel', 'sheet'):
                if r['settingsOverlayOnTop']:
                    failures.append(f'{label} 型 surface 被设置页盖住（应在其上方）')
            # page 型刻意在模态之下
            elif label == 'page':
                if r['probeOnTop']:
                    failures.append('page 型 surface 盖住了设置页（应在其下方）')

        browser.close()

    print()
    if failures:
        for item in failures:
            print(f'FAIL  {item}')
        return 1

    print('PASS  对话框型 surface 全部在设置页之上；page 型保持在模态之下')
    return 0


if __name__ == '__main__':
    sys.exit(main())
