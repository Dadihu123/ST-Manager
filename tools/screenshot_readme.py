"""统一重截 README 用的全部截图。

前置：应用运行在 http://127.0.0.1:5000，且 `tools/seed_screenshot_data.py` 已执行过。
产物直接覆盖 `docs/screenshots/`，尺寸与既有约定一致：
  - 桌面端 viewport 1920x1000，device_scale_factor=1
  - 移动端 viewport 390x844，device_scale_factor=2（输出 780x1688，README 里按 320 宽显示）

跑法（需应用运行在 http://127.0.0.1:5000，且已跑过 tools/seed_screenshot_data.py）：
    python tools/screenshot_readme.py            # 全量
    python tools/screenshot_readme.py gacha      # 只跑名字含 gacha 的
"""

import os
import sys

from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:5000'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'docs', 'screenshots')

DESKTOP = {'width': 1920, 'height': 1000}
MOBILE = {'width': 390, 'height': 844}

results = []


def save(page, name, *, selector=None, clip=None):
    path = os.path.join(OUT, name)
    os.makedirs(OUT, exist_ok=True)
    if selector:
        node = page.query_selector(selector)
        if node is None:
            raise RuntimeError(f'{name}: selector not found {selector}')
        node.screenshot(path=path)
    elif clip:
        page.screenshot(path=path, clip=clip)
    else:
        page.screenshot(path=path)
    size = os.path.getsize(path)
    results.append((name, size))
    print(f'  ✓ {name} ({size // 1024} KB)')


def ready(page, timeout=30000):
    page.wait_for_function(
        "() => Boolean(window.Alpine && window.Alpine.store && window.Alpine.store('global'))",
        timeout=timeout,
    )
    page.wait_for_function(
        "() => { const g = window.Alpine.store('global');"
        " return g && g.serverStatus && g.serverStatus.status === 'ready'; }",
        timeout=timeout,
    )
    page.wait_for_timeout(1200)


def settle(page, ms=600):
    page.wait_for_timeout(ms)


def goto(page, url=''):
    page.goto(BASE + url, wait_until='domcontentloaded', timeout=60000)
    ready(page)
    # 等插件根节点挂载完成，再把常驻宠物之类与截图无关的图层藏掉。
    page.wait_for_timeout(1500)
    hide_noise(page)


def set_dark(page, dark):
    page.evaluate(
        """(dark) => {
          const g = window.Alpine.store('global');
          if (g.isDarkMode !== dark) { g.isDarkMode = dark; g.applyDarkMode(); }
        }""",
        dark,
    )
    settle(page, 400)


def set_mode(page, mode):
    page.evaluate(
        """(mode) => {
          const g = window.Alpine.store('global');
          g.currentMode = mode;
        }""",
        mode,
    )
    settle(page, 1200)
    # 懒加载的列表（聊天 / 预设 / 扩展）需要显式触发一次拉取。
    page.evaluate(
        """(mode) => {
          const map = {
            chats: '[x-data="chatGrid"]',
            presets: '[x-data="presetGrid"]',
            regex: '[x-data="extensionGrid"]',
            scripts: '[x-data="extensionGrid"]',
            quick_replies: '[x-data="extensionGrid"]',
            worldinfo: '[x-data="wiGrid"]',
            beautify: '[x-data="beautifyGrid"]',
          };
          const sel = map[mode];
          if (!sel) return;
          const node = document.querySelector(sel);
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (!data) return;
          if (typeof data.fetchChats === 'function') data.fetchChats();
          if (typeof data.fetchPresets === 'function') data.fetchPresets();
          if (typeof data.fetchExtensions === 'function') data.fetchExtensions();
          if (typeof data.fetchWorldInfos === 'function') data.fetchWorldInfos();
          if (typeof data.fetchPackages === 'function') data.fetchPackages();
        }""",
        mode,
    )
    settle(page, 2000)


def pick_pool(page):
    """把列表切到「测试卡池」目录，作为 README 主页数据。"""
    page.evaluate(
        """() => {
          const g = window.Alpine.store('global');
          g.viewState.filterCategory = '测试卡池';
          g.recursiveFilter = true;
        }"""
    )
    settle(page, 2200)


def hide_noise(page):
    """隐藏与截图主题无关的浮层（toast、常驻宠物等），保持画面干净。

    插件根节点在 `plugins:loaded` 之后才挂载，因此这里既注入样式表（对后续
    挂载的节点也生效），也在当前时刻直接给已存在的宠物根节点打内联 display。
    """
    page.evaluate(
        """() => {
          if (!document.getElementById('shot-hide-noise')) {
            const style = document.createElement('style');
            style.id = 'shot-hide-noise';
            style.textContent = `
              .toast-notification { display: none !important; }
              .plugin-stm-pet,
              .pet-root { display: none !important; visibility: hidden !important; }
            `;
            document.head.appendChild(style);
          }
          document.querySelectorAll('.plugin-stm-pet, .pet-root').forEach((node) => {
            node.style.setProperty('display', 'none', 'important');
          });
        }"""
    )
    # 插件异步加载：稍等后再清一遍。
    page.wait_for_timeout(1500)
    page.evaluate(
        """() => {
          document.querySelectorAll('.plugin-stm-pet, .pet-root').forEach((node) => {
            node.style.setProperty('display', 'none', 'important');
          });
        }"""
    )


def open_detail(page, index=0):
    page.evaluate(
        """(index) => {
          const cards = document.querySelectorAll('.st-card');
          const node = cards[index];
          if (node) node.click();
        }""",
        index,
    )
    settle(page, 1600)


def open_settings(page, section='general'):
    page.evaluate(
        """(section) => window.dispatchEvent(new CustomEvent('open-settings-section',
             { detail: { section } }))""",
        section,
    )
    page.wait_for_selector('.settings-modal-overlay', state='visible', timeout=10000)
    settle(page, 1600)


def close_overlay(page):
    page.evaluate("""() => {
      const g = window.Alpine.store('global');
      g.showSettingsModal = false;
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    }""")
    settle(page, 500)


# ---------------------------------------------------------------- 桌面端

def shoot_desktop_sidebar(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    save(page, 'desktop-sidebar.png')


def shoot_desktop_cards(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    save(page, 'desktop-cards.png')


def shoot_desktop_card_detail(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    open_detail(page, 0)
    save(page, 'desktop-card-detail.png')


def shoot_desktop_tag_workbench(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    page.evaluate(
        """() => {
          const g = window.Alpine.store('global');
          g.showTagFilterModal = true;
        }"""
    )
    settle(page, 1400)
    save(page, 'desktop-tag-workbench.png')


def shoot_desktop_filter_workbench(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    page.evaluate(
        """() => {
          const g = window.Alpine.store('global');
          g.openCardAdvancedFilterDrawer();
        }"""
    )
    settle(page, 1400)
    save(page, 'desktop-filter-workbench.png')


def shoot_desktop_world_info(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'worldinfo')
    save(page, 'desktop-world-info.png')


def shoot_desktop_wi_editor(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'worldinfo')
    settle(page, 800)
    page.evaluate(
        """() => {
          const rows = document.querySelectorAll('[class*="wi-card"], .wi-item, .resource-card');
          if (rows.length) { rows[0].click(); return; }
          const g = window.Alpine.store('global');
          const first = (g.wiList || [])[0];
          if (first) window.dispatchEvent(new CustomEvent('open-wi-detail', { detail: first }));
        }"""
    )
    settle(page, 1800)
    save(page, 'desktop-wi-editor.png')


def shoot_desktop_chats(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'chats')
    save(page, 'desktop-chats.png')


def shoot_desktop_chat_reader(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'chats')
    settle(page, 800)
    page.evaluate(
        """() => {
          const rows = document.querySelectorAll('[class*="chat-card"], .chat-card');
          if (rows.length) rows[0].click();
        }"""
    )
    settle(page, 2200)
    save(page, 'desktop-chat-reader.png')


def shoot_desktop_presets(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'presets')
    save(page, 'desktop-presets.png')


def shoot_desktop_preset_editor(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'presets')
    settle(page, 900)
    page.evaluate(
        """() => {
          const rows = document.querySelectorAll('[class*="preset-card"], .preset-card');
          if (rows.length) rows[0].click();
        }"""
    )
    settle(page, 2200)
    save(page, 'desktop-preset-editor.png')


def shoot_desktop_beautify(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'beautify')
    save(page, 'desktop-beautify.png')


def shoot_desktop_scripts(page):
    goto(page)
    set_dark(page, False)
    # 「高级扩展」是 regex / scripts / quick_replies 三个独立 mode，不是 extensions。
    set_mode(page, 'scripts')
    # 打开第一个脚本的编辑器（README 这一节讲的是编辑器）。
    page.evaluate(
        """() => {
          const cards = document.querySelectorAll('.extension-file-card');
          for (const card of cards) {
            if (card.getBoundingClientRect().width > 0) { card.click(); return; }
          }
        }"""
    )
    settle(page, 2200)
    save(page, 'desktop-scripts.png')


def shoot_desktop_automation(page):
    goto(page)
    set_dark(page, False)
    page.evaluate(
        """() => window.dispatchEvent(new CustomEvent('open-automation-modal'))"""
    )
    settle(page, 1800)
    save(page, 'desktop-automation.png')


def shoot_desktop_automation_replace_text(page):
    goto(page)
    set_dark(page, False)
    page.evaluate(
        """() => window.dispatchEvent(new CustomEvent('open-automation-modal'))"""
    )
    settle(page, 1600)
    page.evaluate(
        """() => {
          const node = document.querySelector('[x-data="automationModal"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (!data) return;
          if (typeof data.openRuleset === 'function' && data.rulesets && data.rulesets.length) {
            data.openRuleset(data.rulesets[0]);
          }
        }"""
    )
    settle(page, 1400)
    save(page, 'desktop-automation.png')


def shoot_desktop_settings(page):
    goto(page)
    set_dark(page, False)
    open_settings(page, 'general')
    save(page, 'desktop-settings.png')


def shoot_desktop_settings_about(page):
    goto(page)
    set_dark(page, False)
    open_settings(page, 'about')
    save(page, 'desktop-settings-about.png')


def shoot_desktop_plugin_manager(page):
    goto(page)
    set_dark(page, False)
    open_settings(page, 'plugins')
    settle(page, 1600)
    save(page, 'desktop-plugin-manager.png')


def shoot_desktop_plugin_catalog(page):
    goto(page)
    set_dark(page, False)
    open_settings(page, 'plugins')
    settle(page, 1200)
    page.evaluate(
        """() => { const el = document.querySelector('#plugin-tab-catalog'); if (el) el.click(); }"""
    )
    settle(page, 2200)
    save(page, 'desktop-plugin-catalog.png')


def shoot_desktop_plugin_contributions(page):
    goto(page)
    set_dark(page, False)
    open_settings(page, 'plugins')
    settle(page, 1200)
    page.evaluate(
        """() => { const el = document.querySelector('#plugin-tab-contributions'); if (el) el.click(); }"""
    )
    settle(page, 1600)
    save(page, 'desktop-plugin-contributions.png')


def shoot_desktop_plugin_job(page):
    """作业面板：注入一份合成作业状态（真实作业需要跑一次 AI 批量任务）。"""
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    injected = page.evaluate(
        """() => {
          const node = document.querySelector('[x-data="pluginJobPanel"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (!data) return false;

          const titles = ['星见 小夜', '雾雨 铃', '白银 澪', '苍崎 灯里', '黑羽 千夏',
                          '神代 凛', '月读 命', '天穹 织姬', '艾莉丝·薇尔', '诺瓦·星辰'];
          const items = titles.map((name, i) => ({
            key: `测试卡池/${name}.png`,
            status: i < 6 ? 'done' : (i === 6 ? 'failed' : 'awaiting_review'),
            result: i < 6 ? { summary: '已生成概览与 5 个标签建议：幻想、长篇、设定集' } : {},
            error: i === 6 ? '上游返回 429，已跳过重试' : '',
          }));

          data.pluginId = 'stm-ai-assistant';
          data.runId = 'demo0f3a9c1b7d4e52';
          data.panelTitle = '角色卡分析与标签建议';
          data.showPluginJobPanel = true;
          data.errorMessage = '';
          data.job = {
            run_id: 'demo0f3a9c1b7d4e52',
            plugin_id: 'stm-ai-assistant',
            job_type: 'card_analysis',
            status: 'running',
            total: 10, completed: 6, failed: 1, skipped: 0,
            message: '正在分析第 8 张卡片…',
            created_at: Date.now() / 1000 - 95,
            updated_at: Date.now() / 1000,
          };
          data.items = items;
          data.logs = [
            { level: 'info', message: '作业已启动，共 10 条' },
            { level: 'info', message: '模型：deepseek-chat，按模型分档的提示词' },
            { level: 'info', message: '已完成 6 条，等待审批 3 条' },
            { level: 'warning', message: '第 7 条请求失败：429 Too Many Requests，已跳过' },
          ];
          return true;
        }"""
    )
    if not injected:
        print('  ! pluginJobPanel data not reachable, skipping')
        return
    settle(page, 1000)
    if page.query_selector('.plugin-job-shell') is None:
        print('  ! job panel shell not rendered, skipping')
        return
    save(page, 'desktop-plugin-job.png')


def _gacha_ten_pull(page):
    """进入十连并把牌全部翻开。"""
    page.evaluate(
        """() => {
          const node = document.querySelector('[x-data="gachaDraw"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (data && typeof data.startDraw === 'function') data.startDraw('multi');
        }"""
    )
    settle(page, 3000)
    page.evaluate(
        """() => {
          const node = document.querySelector('[x-data="gachaDraw"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (data && typeof data.startMultiDeal === 'function') data.startMultiDeal();
        }"""
    )
    settle(page, 2600)
    page.evaluate(
        """() => {
          const node = document.querySelector('[x-data="gachaDraw"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (data && typeof data.revealAll === 'function') data.revealAll();
        }"""
    )
    settle(page, 2200)


def shoot_desktop_gacha(page):
    goto(page)
    set_dark(page, True)
    pick_pool(page)
    page.evaluate(
        """() => window.dispatchEvent(new CustomEvent('open-gacha-draw',
             { detail: { mode: 'single' } }))"""
    )
    settle(page, 2400)
    save(page, 'desktop-gacha.png')


def shoot_desktop_gacha_ten_pull(page):
    goto(page)
    set_dark(page, True)
    pick_pool(page)
    page.evaluate(
        """() => window.dispatchEvent(new CustomEvent('open-gacha-draw',
             { detail: { mode: 'multi' } }))"""
    )
    settle(page, 2000)
    _gacha_ten_pull(page)
    save(page, 'desktop-gacha-ten-pull.png')


def shoot_desktop_command_palette(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    page.evaluate(
        """() => window.dispatchEvent(new CustomEvent('open-command-palette'))"""
    )
    settle(page, 1200)
    page.evaluate(
        """() => { const el = document.querySelector('.command-palette__input'); if (el) el.focus(); }"""
    )
    settle(page, 400)
    save(page, 'desktop-command-palette.png')


def shoot_desktop_plugin_dock(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    page.evaluate(
        """() => {
          const node = document.querySelector('[x-data="entryDock"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (!data) return;
          // 直接置 expanded，并清掉收起计时器，避免鼠标移开后自动收起。
          data.expanded = true;
          if (typeof data.cancelHoverTimer === 'function') data.cancelHoverTimer();
        }"""
    )
    settle(page, 1400)
    page.evaluate(
        """() => {
          const node = document.querySelector('[x-data="entryDock"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (data) data.expanded = true;
        }"""
    )
    settle(page, 500)
    rail = page.query_selector('.entry-rail')
    if rail is None:
        print('  ! entry rail not present (no dock contributions), skipping')
        return
    box = rail.bounding_box()
    if not box:
        print('  ! entry rail has no box, skipping')
        return
    # 坞本身很窄，带上左侧一段界面作为上下文，否则看不出它在哪儿。
    pad_top, pad_bottom = 120, 120
    width = 560
    right = box['x'] + box['width']
    x = max(0, right - width)
    y = max(0, box['y'] - pad_top)
    save(page, 'desktop-plugin-dock.png', clip={
        'x': x,
        'y': y,
        'width': min(DESKTOP['width'] - x, width),
        'height': min(DESKTOP['height'] - y, box['height'] + pad_top + pad_bottom),
    })


def shoot_desktop_index_progress(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    box = None
    for candidate in page.query_selector_all('.index-status-chip'):
        candidate_box = candidate.bounding_box()
        if candidate_box:
            box = candidate_box
            break
    if box is None:
        # 索引就绪时状态条是隐藏的，这里逐字段写入「重建中」让它出现
        # （整体替换 store 对象时 Alpine 的 x-show 不会重算，必须逐键赋值）。
        page.evaluate(
            """() => {
              const s = window.Alpine.store('global').indexStatus;
              s.state = 'building';
              s.scope = 'worldinfo';
              s.upgrade_active = true;
              s.pending_jobs = 3;
              s.jobs = { pending_jobs: 3, worker_state: 'waiting' };
              s.worldinfo = { state: 'running', phase: 'build_entities',
                              progress_done: 842, progress_total: 1200 };
              s.cards = { state: 'ready', phase: '', progress_done: 0, progress_total: 0 };
            }"""
        )
        settle(page, 1400)
        for candidate in page.query_selector_all('.index-status-chip'):
            candidate_box = candidate.bounding_box()
            if candidate_box:
                box = candidate_box
                break
    if box is None:
        print('  ! index chip still missing, skipping')
        return
    pad = 26
    x = max(0, box['x'] - pad)
    y = max(0, box['y'] - pad)
    save(page, 'desktop-index-progress.png', clip={
        'x': x,
        'y': y,
        'width': min(DESKTOP['width'] - x, box['width'] + pad * 2),
        'height': min(DESKTOP['height'] - y, box['height'] + pad * 2),
    })


def _open_worldbook_update(page):
    """从世界书列表打开第一本书的详情，再点「更新内容」。"""
    page.evaluate(
        """() => {
          const cards = document.querySelectorAll('.wi-card, [class*="wi-card"]');
          for (const card of cards) {
            if (card.getBoundingClientRect().width > 0) { card.click(); return; }
          }
        }"""
    )
    settle(page, 2000)
    opened = page.evaluate(
        """() => {
          const node = document.querySelector('[x-data="wiDetailPopup"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (!data || typeof data.openWorldbookUpdate !== 'function') return 'no-data';
          data.openWorldbookUpdate();
          return 'ok';
        }"""
    )
    settle(page, 1600)
    return opened


def shoot_desktop_worldbook_update(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'worldinfo')
    settle(page, 900)
    _open_worldbook_update(page)
    if page.query_selector('.wb-update-modal') is None:
        print('  ! worldbook update dialog not open, skipping')
        return
    save(page, 'desktop-worldbook-update.png')


# ---------------------------------------------------------------- 移动端

def mobile_page(browser):
    context = browser.new_context(
        viewport=MOBILE,
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
        user_agent=(
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
            'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
        ),
    )
    page = context.new_page()
    return context, page


def shoot_mobile_sidebar(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    page.evaluate(
        """() => {
          const g = window.Alpine.store('global');
          g.visibleSidebar = true;
        }"""
    )
    settle(page, 900)
    save(page, 'mobile-sidebar.png')


def shoot_mobile_cards(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    page.evaluate(
        """() => {
          const g = window.Alpine.store('global');
          g.visibleSidebar = false;
        }"""
    )
    settle(page, 900)
    save(page, 'mobile-cards.png')


def shoot_mobile_card_detail(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    open_detail(page, 0)
    save(page, 'mobile-card-detail.png')


def shoot_mobile_tag_workbench(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    page.evaluate(
        """() => {
          const g = window.Alpine.store('global');
          g.showTagFilterModal = true;
        }"""
    )
    settle(page, 1500)
    save(page, 'mobile-tag-workbench.png')


def shoot_mobile_filter_workbench(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    page.evaluate(
        """() => {
          const g = window.Alpine.store('global');
          g.openCardAdvancedFilterDrawer();
        }"""
    )
    settle(page, 1500)
    save(page, 'mobile-filter-workbench.png')


def shoot_mobile_world_info(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'worldinfo')
    save(page, 'mobile-world-info.png')


def shoot_mobile_wi_editor(page):
    """移动端世界书阅览/编辑：点开卡片进入详情（与桌面端同一套阅览器）。"""
    goto(page)
    set_dark(page, False)
    set_mode(page, 'worldinfo')
    settle(page, 900)
    page.evaluate(
        """() => {
          const cards = document.querySelectorAll('.wi-card, [class*="wi-card"]');
          for (const card of cards) {
            if (card.getBoundingClientRect().width > 0) { card.click(); return; }
          }
        }"""
    )
    settle(page, 2400)
    save(page, 'mobile-wi-editor.png')


def shoot_mobile_chats(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'chats')
    save(page, 'mobile-chats.png')


def shoot_mobile_chat_reader(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'chats')
    settle(page, 900)
    page.evaluate(
        """() => {
          const rows = document.querySelectorAll('[class*="chat-card"], .chat-card');
          if (rows.length) rows[0].click();
        }"""
    )
    settle(page, 2200)
    save(page, 'mobile-chat-reader.png')


def shoot_mobile_presets(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'presets')
    save(page, 'mobile-presets.png')


def shoot_mobile_preset_editor(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'presets')
    settle(page, 900)
    page.evaluate(
        """() => {
          const rows = document.querySelectorAll('[class*="preset-card"], .preset-card');
          if (rows.length) rows[0].click();
        }"""
    )
    settle(page, 2200)
    save(page, 'mobile-preset-editor.png')


def shoot_mobile_beautify(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'beautify')
    save(page, 'mobile-beautify.png')


def shoot_mobile_scripts(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'scripts')
    save(page, 'mobile-scripts.png')


def shoot_mobile_automation(page):
    goto(page)
    set_dark(page, False)
    page.evaluate(
        """() => window.dispatchEvent(new CustomEvent('open-automation-modal'))"""
    )
    settle(page, 1800)
    save(page, 'mobile-automation.png')


def shoot_mobile_settings(page):
    goto(page)
    set_dark(page, False)
    open_settings(page, 'general')
    save(page, 'mobile-settings.png')


def shoot_mobile_settings_nav(page):
    """新增：移动端设置导航抽屉展开态。"""
    goto(page)
    set_dark(page, False)
    open_settings(page, 'general')
    opened = page.evaluate(
        """() => {
          const node = document.querySelector('[x-data="settingsModal"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (!data || typeof data.toggleSettingsNav !== 'function') return false;
          data.toggleSettingsNav();
          return true;
        }"""
    )
    if not opened:
        print('  ! settingsModal data not reachable, skipping')
        return
    settle(page, 900)
    if page.query_selector('.settings-sidebar.is-open') is None:
        print('  ! drawer did not open, skipping')
        return
    save(page, 'mobile-settings-nav.png')


def shoot_mobile_settings_about(page):
    goto(page)
    set_dark(page, False)
    open_settings(page, 'about')
    save(page, 'mobile-settings-about.png')


def shoot_mobile_plugin_manager(page):
    goto(page)
    set_dark(page, False)
    open_settings(page, 'plugins')
    settle(page, 1600)
    save(page, 'mobile-plugin-manager.png')


def shoot_mobile_plugin_dock(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    opened = page.evaluate(
        """() => {
          const node = document.querySelector('[x-data="entryDock"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (!data || !data.hasEntries) return false;
          data.expanded = true;
          if (typeof data.cancelHoverTimer === 'function') data.cancelHoverTimer();
          return true;
        }"""
    )
    if not opened:
        print('  ! mobile dock not available (no dock contributions), skipping')
        return
    settle(page, 1000)
    # 收起 tooltip，避免遮住第一项。
    page.evaluate(
        """() => {
          document.querySelectorAll('[data-tooltip]').forEach((n) => n.removeAttribute('data-tooltip'));
          const node = document.querySelector('[x-data="entryDock"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (data) data.expanded = true;
        }"""
    )
    settle(page, 500)
    save(page, 'mobile-plugin-dock.png')


def shoot_mobile_gacha(page):
    goto(page)
    set_dark(page, True)
    pick_pool(page)
    page.evaluate(
        """() => window.dispatchEvent(new CustomEvent('open-gacha-draw',
             { detail: { mode: 'multi' } }))"""
    )
    settle(page, 2000)
    _gacha_ten_pull(page)
    save(page, 'mobile-gacha.png')


def shoot_mobile_command_palette(page):
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    page.evaluate(
        """() => window.dispatchEvent(new CustomEvent('open-command-palette'))"""
    )
    settle(page, 1200)
    save(page, 'mobile-command-palette.png')


def shoot_mobile_menu(page):
    """新增：移动端顶栏菜单（命令面板入口所在处）。"""
    goto(page)
    set_dark(page, False)
    pick_pool(page)
    page.evaluate(
        """() => {
          const node = document.querySelector('[x-data="header"]');
          const data = node && window.Alpine ? window.Alpine.$data(node) : null;
          if (data) {
            if (typeof data.openMobileMenu === 'function') data.openMobileMenu();
            else data.showMobileMenu = true;
          }
        }"""
    )
    settle(page, 900)
    save(page, 'mobile-menu.png')


def shoot_mobile_worldbook_update(page):
    goto(page)
    set_dark(page, False)
    set_mode(page, 'worldinfo')
    settle(page, 900)
    _open_worldbook_update(page)
    if page.query_selector('.wb-update-modal') is None:
        print('  ! worldbook update dialog not open, skipping')
        return
    save(page, 'mobile-worldbook-update.png')


DESKTOP_JOBS = [
    ('sidebar', shoot_desktop_sidebar),
    ('cards', shoot_desktop_cards),
    ('card-detail', shoot_desktop_card_detail),
    ('tag-workbench', shoot_desktop_tag_workbench),
    ('filter-workbench', shoot_desktop_filter_workbench),
    ('world-info', shoot_desktop_world_info),
    ('wi-editor', shoot_desktop_wi_editor),
    ('chats', shoot_desktop_chats),
    ('chat-reader', shoot_desktop_chat_reader),
    ('presets', shoot_desktop_presets),
    ('preset-editor', shoot_desktop_preset_editor),
    ('beautify', shoot_desktop_beautify),
    ('scripts', shoot_desktop_scripts),
    ('automation', shoot_desktop_automation),
    ('settings', shoot_desktop_settings),
    ('settings-about', shoot_desktop_settings_about),
    ('plugin-manager', shoot_desktop_plugin_manager),
    ('plugin-catalog', shoot_desktop_plugin_catalog),
    ('plugin-contributions', shoot_desktop_plugin_contributions),
    ('plugin-job', shoot_desktop_plugin_job),
    ('plugin-dock', shoot_desktop_plugin_dock),
    ('gacha', shoot_desktop_gacha),
    ('gacha-ten-pull', shoot_desktop_gacha_ten_pull),
    ('command-palette', shoot_desktop_command_palette),
    ('index-progress', shoot_desktop_index_progress),
    ('worldbook-update', shoot_desktop_worldbook_update),
]

MOBILE_JOBS = [
    ('sidebar', shoot_mobile_sidebar),
    ('cards', shoot_mobile_cards),
    ('card-detail', shoot_mobile_card_detail),
    ('tag-workbench', shoot_mobile_tag_workbench),
    ('filter-workbench', shoot_mobile_filter_workbench),
    ('world-info', shoot_mobile_world_info),
    ('wi-editor', shoot_mobile_wi_editor),
    ('chats', shoot_mobile_chats),
    ('chat-reader', shoot_mobile_chat_reader),
    ('presets', shoot_mobile_presets),
    ('preset-editor', shoot_mobile_preset_editor),
    ('beautify', shoot_mobile_beautify),
    ('scripts', shoot_mobile_scripts),
    ('automation', shoot_mobile_automation),
    ('settings', shoot_mobile_settings),
    ('settings-nav', shoot_mobile_settings_nav),
    ('settings-about', shoot_mobile_settings_about),
    ('plugin-manager', shoot_mobile_plugin_manager),
    ('plugin-dock', shoot_mobile_plugin_dock),
    ('gacha', shoot_mobile_gacha),
    ('command-palette', shoot_mobile_command_palette),
    ('menu', shoot_mobile_menu),
    ('worldbook-update', shoot_mobile_worldbook_update),
]


def main():
    only = sys.argv[1].lower() if len(sys.argv) > 1 else ''

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        print('=== 桌面端 ===')
        for name, fn in DESKTOP_JOBS:
            if only and only not in name:
                continue
            page = browser.new_page(viewport=DESKTOP, device_scale_factor=1)
            try:
                fn(page)
            except Exception as exc:
                print(f'  ✗ desktop-{name}: {exc}')
            finally:
                page.close()

        print('=== 移动端 ===')
        for name, fn in MOBILE_JOBS:
            if only and only not in name:
                continue
            context, page = mobile_page(browser)
            try:
                fn(page)
            except Exception as exc:
                print(f'  ✗ mobile-{name}: {exc}')
            finally:
                context.close()

        browser.close()

    print()
    print(f'共生成 {len(results)} 张')


if __name__ == '__main__':
    main()
