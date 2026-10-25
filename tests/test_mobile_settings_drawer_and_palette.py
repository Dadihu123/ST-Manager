"""移动端命令面板入口与设置抽屉导航的契约。

覆盖两件事：
1. 命令面板在软键盘环境下的触屏入口（顶栏菜单「命令」按钮 → `open-command-palette`）。
2. 设置页在移动端改为左侧抽屉，抽屉里的导航按钮沿用 PC 端样式。
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


# ---------------------------------------------------------------- 命令面板入口


def test_command_palette_listens_for_the_touch_entry_event():
    """软键盘打不出 Ctrl/Cmd+K，必须另有一条事件通道。"""
    source = read_project_file('static/js/components/commandPalette.js')

    assert '"open-command-palette"' in source
    # 事件通道与快捷键走同一个 show()，不区分设备。
    assert 'this._openHandler = () => this.show();' in source
    # destroy 里要摘掉监听，否则热重载会叠多个。
    assert 'window.removeEventListener("open-command-palette", this._openHandler);' in source


def test_mobile_header_menu_dispatches_the_palette_event():
    template = read_project_file('templates/components/header.html')
    mobile_menu = template.split('class="mobile-menu"', 1)[1]

    assert "$dispatch('open-command-palette')" in mobile_menu
    assert 'class="menu-label">命令<' in mobile_menu
    # 打开面板前先收起菜单，否则菜单会压在面板下层。
    assert "closeMobileMenu()" in mobile_menu.split("open-command-palette", 1)[1][:120]


# ---------------------------------------------------------------- 设置抽屉


def test_mobile_settings_nav_is_a_left_drawer_not_a_two_column_grid():
    css = read_project_file('static/css/modules/modal-settings.css')
    mobile_block = css.split('@media (max-width: 767px)', 1)[1].split(
        '@media (prefers-reduced-motion', 1
    )[0]

    # 抽屉本体：绝对定位 + 负向位移收起 + 展开态归零。
    assert 'transform: translateX(-102%);' in mobile_block
    assert '.settings-sidebar.is-open {' in mobile_block
    assert 'transform: translateX(0);' in mobile_block
    # 导航恢复单列（两列网格正是「占掉半屏」的来源）。
    nav_block = mobile_block.split('.settings-nav {', 1)[1].split('}', 1)[0]
    assert 'grid-template-columns: minmax(0, 1fr);' in nav_block
    assert 'repeat(2' not in nav_block


def test_mobile_settings_drawer_keeps_pc_nav_button_anatomy():
    """抽屉里的按钮要与 PC 端一致：标题、副标题、序号都显示。"""
    css = read_project_file('static/css/modules/modal-settings.css')
    mobile_block = css.split('@media (max-width: 767px)', 1)[1].split(
        '@media (prefers-reduced-motion', 1
    )[0]

    assert '.settings-nav-copy small { display: block; }' in mobile_block
    assert '.settings-nav-index { display: block; }' in mobile_block
    assert '.settings-nav-item { min-height: 64px; padding: 10px; }' in mobile_block
    assert '.settings-nav-copy small { display: none; }' not in mobile_block


def test_settings_nav_trigger_is_hidden_on_desktop():
    """唤起按钮只在移动端出现；桌面端导航常驻侧栏。"""
    css = read_project_file('static/css/modules/modal-settings.css')

    # 桌面端隐藏必须压过 consistency.css 的 `.settings-icon-button { display: inline-flex }`。
    assert '.settings-modal-overlay .settings-nav-trigger { display: none; }' in css
    assert '.settings-nav-scrim { display: none; }' in css


def test_settings_drawer_state_is_closed_by_escape_and_tab_switch():
    source = read_project_file('static/js/components/settingsModal.js')

    assert 'settingsNavOpen: false,' in source
    assert 'toggleSettingsNav() {' in source
    assert 'closeSettingsNav() {' in source
    # 选完分区即收起，把整块屏幕还给内容。
    select_block = source.split('selectSettingTab(section, anchor = "") {', 1)[1].split('},', 1)[0]
    assert 'this.closeSettingsNav();' in select_block
    # Esc 先关抽屉，再关整个设置页。
    escape_block = source.split('handleEscape() {', 1)[1].split('requestClose() {', 1)[0]
    assert 'if (this.settingsNavOpen) {' in escape_block
    assert escape_block.index('settingsNavOpen') < escape_block.index('showSettingsModal')


def test_settings_drawer_has_scrim_and_accessible_trigger():
    template = read_project_file('templates/modals/settings.html')

    assert 'class="settings-nav-scrim"' in template
    assert 'id="settings-nav-panel"' in template
    assert ':aria-expanded="settingsNavOpen' in template
    assert 'aria-controls="settings-nav-panel"' in template
