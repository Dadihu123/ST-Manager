"""插件管理模态框契约测试（设计文档第 9 部分 / 13.2）。"""

import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def read_source(relative_path):
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


def strip_js_comments(source: str) -> str:
    """去掉 `//` 行注释与 `/* */` 块注释（字符串字面量按原样保留）。"""
    source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
    return re.sub(r'(?m)^\s*//.*$', '', source)


def test_panel_is_embedded_in_settings_instead_of_a_standalone_modal():
    """插件管理已并入设置页第五个导航页，因此不能再自带模态框外壳。"""
    template = read_source('templates/modals/plugin_manager.html')

    assert 'ui-modal-shell' not in template
    assert 'modal-overlay' not in template
    assert 'ui-modal-body' not in template
    assert 'role="dialog"' not in template

    settings_source = read_source('templates/modals/settings.html')
    assert '{% include "modals/plugin_manager.html" %}' in settings_source
    assert 'settings-panel-plugins' in settings_source
    assert "selectSettingTab('plugins')" in settings_source


def test_modal_component_is_registered_in_app_entry():
    app_source = read_source('static/js/app.js')

    assert 'pluginManager' in app_source
    assert 'pluginManager.js' in app_source


def test_four_tabs_are_present():
    template = read_source('templates/modals/plugin_manager.html')

    assert '已安装' in template
    assert '官方目录' in template
    assert '手动安装' in template
    # 阶段 6.1：入口总览作为第四个页签挂在既有「插件管理」页内
    # （刻意不新增设置顶层 tab —— settingsHelpContent 是硬闸门）。
    assert '入口总览' in template
    assert 'role="tablist"' in template
    # 页签沿用角色卡详情页的 .detail-tabs / .detail-tab 契约。
    assert 'class="detail-tabs plugin-manager-tabs"' in template
    assert template.count('class="detail-tab"') == 4


def test_entry_overview_is_embedded_in_plugin_manager_not_a_new_settings_tab():
    """总览页必须挂在插件管理页内，不能新增设置顶层分区。"""
    template = read_source('templates/modals/plugin_manager.html')
    settings_source = read_source('templates/modals/settings.html')

    assert 'id="plugin-panel-entries"' in template
    assert 'selectTab(\'entries\')' in template
    # 没有新增设置顶层导航项
    assert "selectSettingTab('entries')" not in settings_source


def test_entry_overview_table_columns_match_contract():
    """表格列：图标+名称 / 归属 / 类型 / 出现位置 / 当前呈现 / 快捷键。

    「操作」列已删除：它只有一个「配置」按钮，而插件卡片上本来就有配置按钮，
    同一页里出现两处入口属于重复。入口总览是**审计面**，不是操作面。
    """
    template = read_source('templates/modals/plugin_manager.html')
    component = read_source('static/js/components/pluginManager.js')

    for column in ('名称', '归属', '类型', '出现位置', '当前呈现', '快捷键'):
        assert f'<th scope="col">{column}</th>' in template, column
    assert '<th scope="col">操作</th>' not in template, '「操作」列应已删除'

    assert 'entryKindLabel(row)' in template
    assert 'entryLocationLabel(row)' in template
    assert 'entrySurfaceLabel(row)' in template


def test_entry_overview_labels_unimplemented_kinds_honestly():
    """`nav` / `status` 目前**没有**任何渲染消费者。

    旧文案把出现位置写成「设置页 / 侧栏导航 / 状态栏」，会让用户以为入口已生效。
    这里锁定「如实描述」：未实现的位置标注为宿主未实现，且模板上有显式的未实现标记。

    `settings` 自 D7 起**已实现**（渲染为插件管理页内的「插件设置入口」区块），
    因此它必须从「未实现」名单里移出，并给出真实落点——否则总览页会与
    `IMPLEMENTED_ENTRY_KINDS` 自相矛盾。
    """
    template = read_source('templates/modals/plugin_manager.html')
    component = read_source('static/js/components/pluginManager.js')
    # 注释里会**引用**旧文案来说明为什么要改，因此只看代码
    code = strip_js_comments(component)

    assert 'IMPLEMENTED_ENTRY_KINDS' in code
    assert 'entryKindImplemented' in code
    assert 'entryKindImplemented(row)' in template

    # 已实现的 kind 仍在位置表里给出真实落点
    for kind in ('dock', 'context', 'command', 'batch', 'settings'):
        assert f'{kind}: "' in code

    # `settings` 必须给出真实落点，且被登记为已实现
    assert 'settings: "插件管理页"' in code
    assert '"settings"' in code.split('IMPLEMENTED_ENTRY_KINDS', 1)[1].split(')', 1)[0], (
        'settings 必须登记进 IMPLEMENTED_ENTRY_KINDS'
    )

    # 仍未实现的两种 kind 必须**逐个**标注为未实现（不能靠「整体出现过一次」蒙混）
    for kind in ('nav', 'status'):
        assert f'{kind}: "宿主未实现"' in code, f'{kind} 必须如实标注为宿主未实现'
    for stale in ('侧栏导航', '状态栏'):
        assert stale not in code, f'{stale} 是未实现的落点，不应再出现'
    # 旧文案把 settings 说成「设置页」（一个不存在的落点入口）——已改成「插件管理页」
    assert 'settings: "设置页"' not in code


def test_entry_overview_drops_the_duplicate_refresh_button():
    """刷新按钮只保留工具栏顶部那一个（走 `reloadActiveTab()`，与当前页签一致）。

    页签内的第二个按钮调 `loadEntries()`，在「已安装」页签下点它会静默什么都不刷新
    （只重载入口总览的数据），属于误导性控件。
    """
    template = read_source('templates/modals/plugin_manager.html')

    assert 'reloadActiveTab()' in template
    assert '@click="loadEntries()"' not in template
    # 整个模板只剩一个刷新图标
    assert template.count("icon('refresh'") == 1


def test_entry_shortcut_slot_is_deduplicated_by_surface():
    """快捷键按 surface 去重，且 context 类不提供设置。

    - 多个入口指向同一 surface 时（本插件 4 个入口都指向 `workbench`），
      只有第一个入口持有快捷键位，否则总览页会出现多条指向同一面板的重复快捷键；
    - `context` 类不提供快捷键：右键菜单入口没有「右键目标」这个键盘概念，
      且所有 context 入口打开的是同一个面板（用户原话：「设了也没用」）。
    """
    component = read_source('static/js/components/pluginManager.js')
    template = read_source('templates/modals/plugin_manager.html')
    code = strip_js_comments(component)

    # 定义与调用（用定义签名而不是裸名字，避免改名后子串仍然命中）
    assert 'entryHoldsShortcutSlot(row) {' in code
    assert 'entryShortcutEditable(row) {' in code
    assert 'entryHoldsShortcutSlot(row)' in template
    assert 'entryShortcutEditable(row)' in template

    # 去重依据是 surface，不是 kind 或 priority
    assert 'surfaceId: (entry.surface && entry.surface.id) || entry.id,' in code, (
        '行数据必须带上 surfaceId，否则无法按 surface 去重'
    )
    assert '`${item.pluginId}:${item.surfaceId || item.id}`' in code
    assert 'return !first || first.key === row.key;' in code, (
        '只有排序最靠前的那一个入口持有快捷键位'
    )

    # context 类被明确排除
    assert "String((row && row.kind) || \"\") !== \"context\"" in code

    # 两个被拒绝的入口在 UI 上给出说明，而不是静默显示「—」
    assert '不适用' in template
    assert '共用' in template

    # 取建议快捷键时也要走去重，否则被抑制的入口仍会显示插件建议值
    assert 'if (!this.entryHoldsShortcutSlot(row)) return "";' in code


def test_deep_link_anchors_support_config_and_secrets():
    """阶段 6.2：`plugin-config-<id>` / `plugin-secrets-<id>` 深链。"""
    component = read_source('static/js/components/pluginManager.js')

    assert 'CONFIG_ANCHOR_PATTERN' in component
    assert 'SECRET_ANCHOR_PATTERN' in component
    assert 'plugin-config-' in component
    assert 'plugin-secrets-' in component
    assert 'deepLink(pluginId, target)' in component
    # 深链必须先加载列表再展开表单，否则拿不到 item
    assert 'await this.loadPlugins();' in component
    assert 'scrollToPlugin(id)' in component


def test_tier_badge_is_rendered_on_plugin_cards():
    """阶段 6.3：归属分级徽标（tier 由宿主 catalog 决定）。"""
    template = read_source('templates/modals/plugin_manager.html')
    component = read_source('static/js/components/pluginManager.js')

    assert 'plugin-card-tier' in template
    assert 'tierLabel(item)' in template
    assert 'TIER_LABELS' in component
    assert 'official' in component and 'verified' in component and 'community' in component


def test_install_disclosure_shows_entry_count():
    """阶段 6.3：安装期披露「此插件将添加 N 个入口」。"""
    template = read_source('templates/modals/plugin_manager.html')
    component = read_source('static/js/components/pluginManager.js')

    assert 'entryCountLabel(item)' in template
    assert '此插件将添加' in component

def test_four_lifecycle_actions_are_present():
    template = read_source('templates/modals/plugin_manager.html')
    component = read_source('static/js/components/pluginManager.js')

    for label in ('安装', '卸载', '禁用', '启用'):
        assert label in template, label

    assert 'installCatalogItem' in component
    assert 'uninstall(' in component
    assert 'toggleEnabled(' in component


def test_config_and_secret_forms_are_rendered_from_schema():
    component = read_source('static/js/components/pluginManager.js')

    assert 'schemaEntries(' in component
    assert 'config_schema' in component
    assert 'secret_schema' in component


def test_plugin_docs_button_and_dependency_row_exist():
    template = read_source('templates/modals/plugin_manager.html')
    component = read_source('static/js/components/pluginManager.js')
    api_module = read_source('static/js/api/plugins.js')

    assert 'openDocs(item)' in template
    assert 'requirementLabels(item)' in template
    assert 'async openDocs(' in component
    assert 'requirementLabels(item) {' in component
    assert 'getPluginReadme' in api_module


def test_installed_card_has_a_source_link_alongside_the_other_actions():
    """已安装卡片的操作行里要有「来源」外链，且与目录卡片的 GitHub 链接同款。

    门控在 `item.source_url` 上：后端解析不出来源时（本地目录 / 上传安装且 manifest
    没有 `homepage`）字段是空串，按钮随之消失——不渲染一个点不开的链接。
    """
    template = read_source('templates/modals/plugin_manager.html')

    actions = template.split('<div class="plugin-card-actions">', 1)[1].split(
        '</div>', 1,
    )[0]

    assert 'x-show="item.source_url"' in actions
    assert ':href="item.source_url"' in actions
    assert 'target="_blank"' in actions
    assert 'rel="noopener noreferrer"' in actions
    assert '来源' in actions
    # 外链用与相邻按钮同一套 class，样式才不会跑偏
    assert 'class="plugin-button plugin-button--ghost"' in actions


def test_docs_are_rendered_through_markdown_preview():
    component = read_source('static/js/components/pluginManager.js')
    editor = read_source('static/js/components/largeEditor.js')
    preview = read_source('templates/modals/markdown_preview.html')

    assert 'open-markdown-view' in component
    # detail 支持 { content, title }，且标题可动态切换
    assert 'payload.title' in editor
    assert 'markdownModalTitle' in editor
    assert 'markdownModalTitle' in preview


def test_secret_inputs_are_password_with_hint_placeholder():
    template = read_source('templates/modals/plugin_manager.html')

    assert 'type="password"' in template
    assert 'plugin-secret-state' in template
    assert 'hint' in template


def test_secret_banner_warns_about_plaintext_storage():
    template = read_source('templates/modals/plugin_manager.html')

    assert 'data/system/secrets.json' in template


def test_style_module_is_registered_in_entry_css():
    style_entry = read_source('static/css/style.css')

    assert 'modules/modal-plugin-manager.css' in style_entry


# ------------------------------------------------------------------ settings 入口（D7）


def test_settings_entry_kind_has_a_real_render_consumer():
    """`kind: 'settings'` 的入口必须渲染出可点的落点（D7）。

    此前 `settings` 只存在于契约里、**没有任何渲染消费者**，用户在总览页看到它
    却没处可点。现在渲染为插件管理页内的「插件设置入口」区块。
    """
    template = read_source('templates/modals/plugin_manager.html')
    component = strip_js_comments(read_source('static/js/components/pluginManager.js'))

    assert 'settingsEntries' in component
    assert 'settingsEntries' in template
    assert 'openSettingsEntry(row)' in template
    assert '@click="openSettingsEntry(row)"' in template


def test_settings_block_is_injected_into_the_existing_plugins_section():
    """必须挂在既有 `plugins` 分区内，**不新增设置顶层 tab**。

    `settingsModal.selectSettingTab` 有硬闸门 `if (!this.settingsHelpContent[section]) return;`，
    新增顶层分区要同时改 `settingsHelpContent` + 命令面板 + 模板。`plugins` 键已存在，
    因此注入到既有分区内即可规避该闸门。
    """
    template = read_source('templates/modals/plugin_manager.html')
    settings_source = read_source('templates/modals/settings.html')
    settings_modal = read_source('static/js/components/settingsModal.js')

    # 区块留在插件管理模板内（该模板被 settings.html 的 plugins 分区 include）
    assert 'plugin-settings-entries' in template
    assert '{% include "modals/plugin_manager.html" %}' in settings_source

    # 没有新增顶层设置分区
    help_block = settings_modal.split('settingsHelpContent:', 1)[1].split('\n    },', 1)[0]
    for section in ('general', 'appearance', 'connection', 'maintenance', 'plugins'):
        assert f'{section}:' in help_block, section


def test_settings_entries_only_include_enabled_plugins():
    """被禁用的插件不该在设置页留按钮。"""
    component = strip_js_comments(read_source('static/js/components/pluginManager.js'))

    section = component.split('get settingsEntries()', 1)[1].split('}', 1)[0]
    assert 'row.pluginEnabled' in section
    assert '"settings"' in section


def test_settings_entries_render_uses_plugin_icon_resolution():
    """图标必须走 `entryIconHtml`（宿主图标名 / 插件内资源路径两种取值都能解析）。"""
    template = read_source('templates/modals/plugin_manager.html')

    section = template.split('plugin-settings-entries', 1)[1].split('</section>', 1)[0]
    assert 'entryIconHtml(row)' in section
    assert 'row.label' in section
    assert 'row.pluginName' in section


def test_no_tailwind_palette_utilities_in_plugin_manager_sources():
    legacy_fragments = (
        'bg-red-', 'bg-blue-', 'bg-green-', 'bg-purple-',
        'text-red-', 'text-blue-', 'text-green-', 'text-purple-',
    )

    for relative_path in (
        'templates/modals/plugin_manager.html',
        'static/js/components/pluginManager.js',
        'static/js/api/plugins.js',
        'static/css/modules/modal-plugin-manager.css',
    ):
        source = read_source(relative_path)
        assert not any(fragment in source for fragment in legacy_fragments), relative_path


def test_css_uses_semantic_tokens_only():
    css = read_source('static/css/modules/modal-plugin-manager.css')

    assert 'var(--content-' in css
    assert 'var(--surface-' in css
    assert not re.search(r'#[0-9a-fA-F]{6}\b', css), '模块样式不应写死十六进制颜色'
