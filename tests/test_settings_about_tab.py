"""设置页「关于」分区的契约：官方品牌图标、README 同源链接与顶层分区注册。"""

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_about_tab_is_registered_as_a_top_level_settings_section():
    """新增顶层分区必须同时注册 settingsHelpContent / 命令面板 / 模板三处。"""
    settings_modal = read_project_file('static/js/components/settingsModal.js')
    template = read_project_file('templates/modals/settings.html')

    help_block = settings_modal.split('settingsHelpContent:', 1)[1].split('\n    },', 1)[0]
    assert 'about:' in help_block
    assert 'label: "关于"' in help_block

    # 模板：导航按钮 + 面板 + 内容区图标都要有 about 分支。
    assert 'id="settings-tab-about"' in template
    assert 'id="settings-panel-about"' in template
    assert "selectSettingTab('about')" in template
    assert "activeSettingTab === 'about'" in template


def test_about_tab_is_reachable_from_settings_search():
    settings_modal = read_project_file('static/js/components/settingsModal.js')

    assert 'section: "about"' in settings_modal
    assert 'settings-about-links' in settings_modal


def test_about_links_match_readme_feedback_section():
    """关于页链接必须与 README「反馈与贡献」一致，避免两处漂移。"""
    readme = read_project_file('README.md')
    settings_modal = read_project_file('static/js/components/settingsModal.js')

    github_issues = 'https://github.com/Dadihu123/ST-Manager/issues'
    discord_thread = 'https://discord.com/channels/1134557553011998840/1448353646596325578'

    assert github_issues in readme
    assert discord_thread in readme
    assert github_issues in settings_modal
    assert discord_thread in settings_modal


def test_about_panel_uses_official_brand_icons_with_external_links():
    template = read_project_file('templates/modals/settings.html')

    assert "icon('github', 'ui-icon--lg')" in template
    assert "icon('discord', 'ui-icon--lg')" in template
    assert ':href="aboutLinks.githubIssues"' in template
    assert ':href="aboutLinks.discordThread"' in template

    # 外链必须新开窗口并带 noopener。
    section = template.split('id="settings-about-links"', 1)[1].split('</section>', 1)[0]
    assert section.count('target="_blank"') == 2
    assert section.count('rel="noopener noreferrer"') == 2


def test_about_brand_symbols_exist_and_are_theme_safe():
    sprite = read_project_file('static/icons/ui.svg')

    for name in ('github', 'discord'):
        assert f'id="icon-{name}"' in sprite

    # 单条 currentColor 路径，品牌色由 CSS 提供。
    for name in ('github', 'discord'):
        symbol = sprite.split(f'id="icon-{name}"', 1)[1].split('</symbol>', 1)[0]
        assert 'fill="currentColor"' in symbol
        assert symbol.count('<path') == 1
        assert '#' not in symbol.replace('fill="currentColor"', '')


def test_about_brand_icons_are_resolvable_host_icon_names():
    icon_map = read_project_file('static/js/utils/iconMap.js')

    assert '"github": "ui.svg"' in icon_map
    assert '"discord": "ui.svg"' in icon_map


def test_about_brand_icons_share_a_fixed_light_plate():
    """GitHub 官方图标是近黑色，深色主题下必须有固定浅色底板，两个品牌图标共用同一块。"""
    css = read_project_file('static/css/modules/modal-settings.css')
    plate_block = css.split('.settings-about-link-icon {', 1)[1].split('}', 1)[0]

    assert '--settings-brand-plate: #f1f5f9;' in css
    assert 'background: var(--settings-brand-plate);' in plate_block
    assert 'border: 1px solid var(--settings-brand-plate-border);' in plate_block

    # 底板不跟随主题反转：深色主题的变量仍保持浅色值，只有浅色主题单独微调。
    overlay_block = css.split('.settings-modal-overlay {', 1)[1].split('}', 1)[0]
    assert '--settings-brand-plate: #f1f5f9;' in overlay_block
    light_block = css.split('html.light-mode .settings-modal-overlay {', 1)[1].split('}', 1)[0]
    assert '--settings-brand-plate: #e8eef6;' in light_block

    # 两个品牌图标除品牌色外不引入任何差异化的背景/边框覆盖。
    brand_rules = css.split('/* 官方品牌色只用于图标本身，避免跟随主题被冲淡。 */', 1)[1].split('\n\n', 1)[0]
    assert '.settings-about-link-icon--github { color: #181717; }' in brand_rules
    assert '.settings-about-link-icon--discord { color: #5865f2; }' in brand_rules
    assert 'background' not in brand_rules


def test_about_version_comes_from_the_shared_meta_tag():
    settings_modal = read_project_file('static/js/components/settingsModal.js')
    layout = read_project_file('templates/layout.html')

    assert 'meta[name="app-version"]' in settings_modal
    assert 'name="app-version"' in layout


def test_about_panel_exposes_version_license_and_repo_metadata():
    template = read_project_file('templates/modals/settings.html')
    section = template.split('id="settings-about-project"', 1)[1].split('</section>', 1)[0]

    assert 'GNU AGPL-3.0' in section
    assert 'Dadihu123/ST-Manager' in section
    assert 'aboutVersionLabel' in section
