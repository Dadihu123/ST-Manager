import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def extract_css_block(css, selector_pattern):
    match = re.search(rf'{selector_pattern}\s*\{{(?P<body>.*?)\}}', css, re.DOTALL)
    assert match, f'Expected CSS block matching {selector_pattern!r}'
    return match.group('body')


def extract_css_block_for_selector(css, selector):
    pattern = re.compile(r'(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}', re.DOTALL)
    normalized_selector = selector.strip()

    for match in pattern.finditer(css):
        selectors = [item.strip() for item in match.group('selectors').split(',')]
        if normalized_selector in selectors:
            return match.group('body')

    raise AssertionError(f'Expected CSS block containing selector {selector!r}')


def extract_beautify_settings_workspace_branch(template):
    start_match = re.search(
        r'''<template\s+x-if=(['"])[^>]*beautifyWorkspace\s*===\s*['"]settings['"][^>]*>''',
        template,
    )
    assert start_match, 'Expected beautify settings workspace template branch start'

    end_match = re.search(
        r'''<template\s+x-if=(['"])[^>]*beautifyWorkspace\s*!==\s*['"]settings['"]\s*&&\s*activePackage[^>]*>''',
        template[start_match.end():],
    )
    assert end_match, 'Expected beautify package workspace template branch start'
    return template[start_match.end():start_match.end() + end_match.start()]


def has_css_declaration(block, property_name, value_fragment):
    return re.search(rf'{re.escape(property_name)}\s*:\s*[^;]*{re.escape(value_fragment)}[^;]*;', block) is not None


def assert_has_css_declaration(block, property_name, value_fragment):
    assert has_css_declaration(block, property_name, value_fragment), (
        f'Expected {property_name!r} declaration containing {value_fragment!r}'
    )


def test_beautify_css_helpers_match_shared_selector_blocks_independent_of_selector_order():
    css = '.second, .first, .third { border: 1px solid var(--border-light); background: var(--bg-sub); }'

    block = extract_css_block_for_selector(css, '.first')

    assert has_css_declaration(block, 'border', 'var(--border-light)')
    assert has_css_declaration(block, 'background', 'var(--bg-sub)')


def test_sidebar_template_places_beautify_last_in_second_resource_row():
    template = read_project_file('templates/components/sidebar.html')

    presets_index = template.index("switchMode('presets')")
    regex_index = template.index("switchMode('regex')")
    scripts_index = template.index("switchMode('scripts')")
    quick_replies_index = template.index("switchMode('quick_replies')")
    beautify_index = template.index("switchMode('beautify')")

    assert presets_index < regex_index < scripts_index < quick_replies_index < beautify_index
    assert '美化' in template[beautify_index: beautify_index + 120]


def test_sidebar_template_keeps_live_beautify_sidebar_panel_hook():
    template = read_project_file('templates/components/sidebar.html')

    assert 'beautify-sidebar-panel' in template


def test_sidebar_template_adds_beautify_workspace_switcher_and_screenshot_import():
    template = read_project_file('templates/components/sidebar.html')

    assert 'beautifyWorkspace' in template
    assert 'switchBeautifyWorkspace(' in template
    assert '导入截图' in template
    assert 'handleScreenshotFiles($event.target.files)' in template
    assert ':disabled="!selectedPackageId"' in template or ":disabled='!selectedPackageId'" in template


def test_sidebar_template_separates_global_theme_import_from_package_scoped_imports():
    template = read_project_file('templates/components/sidebar.html')

    theme_index = template.index('导入主题')
    variant_index = template.index('导入变体')
    wallpaper_index = template.index('导入壁纸')
    screenshot_index = template.index('导入截图')

    assert theme_index < variant_index < wallpaper_index < screenshot_index
    assert 'beautify-toolbar-global-action' in template
    assert 'beautify-toolbar-package-actions' in template


def test_sidebar_template_keeps_wallpaper_import_bound_to_selected_variant_after_variant_button_added():
    template = read_project_file('templates/components/sidebar.html')

    variant_index = template.index('导入变体')
    wallpaper_index = template.index('导入壁纸')
    screenshot_index = template.index('导入截图')

    assert variant_index < wallpaper_index < screenshot_index
    assert 'handleVariantFiles($event.target.files)' in template
    assert 'handleWallpaperFiles($event.target.files)' in template
    assert ':disabled="!selectedVariantId"' in template or ":disabled='!selectedVariantId'" in template
    assert ':disabled="!selectedPackageId"' in template or ":disabled='!selectedPackageId'" in template


def test_beautify_toolbar_actions_center_button_group_on_desktop_and_keep_mobile_stack():
    css = read_project_file('static/css/modules/view-beautify.css')

    desktop_block = extract_css_block(css, r'\.beautify-toolbar-actions')
    assert_has_css_declaration(desktop_block, 'justify-content', 'center')

    mobile_media_match = re.search(
        r'@media \(max-width: 900px\)\s*\{(?P<body>[\s\S]*?)\n\}',
        css,
    )
    assert mobile_media_match, 'Expected beautify mobile media query block'

    mobile_block = extract_css_block_for_selector(
        mobile_media_match.group('body'),
        '.beautify-toolbar-actions',
    )
    assert_has_css_declaration(mobile_block, 'flex-direction', 'column')
    assert_has_css_declaration(mobile_block, 'align-items', 'stretch')


def test_beautify_toolbar_actions_allow_desktop_wrap_and_reset_package_group_separator():
    css = read_project_file('static/css/modules/view-beautify.css')

    desktop_block = extract_css_block(css, r'\.beautify-toolbar-actions')
    package_match = re.search(
        r'\.beautify-toolbar-package-actions\s*\{(?P<body>[^{}]*flex-wrap:\s*wrap;[^{}]*)\}',
        css,
        re.DOTALL,
    )
    assert package_match, 'Expected desktop .beautify-toolbar-package-actions block with wrapping'
    package_block = package_match.group('body')

    assert_has_css_declaration(desktop_block, 'flex-wrap', 'wrap')
    assert_has_css_declaration(package_block, 'flex-wrap', 'wrap')
    assert_has_css_declaration(package_block, 'justify-content', 'center')
    assert_has_css_declaration(package_block, 'padding-left', '0')
    assert_has_css_declaration(package_block, 'margin-left', '0')
    assert_has_css_declaration(package_block, 'border-left', '0')


def test_index_template_includes_dedicated_beautify_grid_view():
    template = read_project_file('templates/index.html')
    assert '{% include "components/grid_beautify.html" %}' in template
    assert '<div class="main-container" x-data="beautifyGrid">' in template


def test_index_template_lifts_beautify_scope_above_sidebar_and_grid_includes():
    template = read_project_file('templates/index.html')

    main_container_index = template.index('<div class="main-container" x-data="beautifyGrid">')
    sidebar_index = template.index('{% include "components/sidebar.html" %}')
    beautify_grid_index = template.index('{% include "components/grid_beautify.html" %}')

    assert main_container_index < sidebar_index < beautify_grid_index


def test_beautify_grid_template_keeps_stage_only_markup_and_controls():
    template = read_project_file('templates/components/grid_beautify.html')

    assert '$store.global.currentMode === \"beautify\"' in template or "$store.global.currentMode === 'beautify'" in template
    assert 'beautify-layout' in template
    assert 'beautify-stage-pane' in template
    assert 'beautify-sidebar-pane' not in template
    assert 'x-data="beautifyGrid"' not in template
    assert 'selectedVariantPlatform === \'pc\'' in template or 'selectedVariantPlatform === "pc"' in template
    assert 'selectedVariantPlatform === \'mobile\'' in template or 'selectedVariantPlatform === "mobile"' in template


def test_beautify_grid_template_supports_screenshot_stage_and_global_settings_form():
    template = read_project_file('templates/components/grid_beautify.html')

    assert 'stageMode === "preview"' in template or "stageMode === 'preview'" in template
    assert 'stageMode === "screenshot"' in template or "stageMode === 'screenshot'" in template
    assert '全局壁纸' in template
    assert '角色默认资料' in template
    assert '用户默认资料' in template
    assert '角色与用户覆盖' in template
    assert '截图查看' in template
    assert 'activeScreenshot' in template
    assert 'beautifyWorkspace === "settings"' in template or "beautifyWorkspace === 'settings'" in template


def test_beautify_grid_template_exposes_shared_wallpaper_picker_for_global_preview_selection():
    template = read_project_file('templates/components/grid_beautify.html')

    assert '共享壁纸库' in template
    assert 'selectGlobalWallpaper(item.id)' in template
    assert 'preview_wallpaper_id' in template


def test_beautify_grid_template_adds_screenshot_picker_package_identity_bindings_and_avatar_actions():
    template = read_project_file('templates/components/grid_beautify.html')

    assert 'x-for="screenshot in screenshotOptions"' in template or "x-for='screenshot in screenshotOptions'" in template
    assert '@click="selectScreenshot(screenshot.id)"' in template or "@click='selectScreenshot(screenshot.id)'" in template
    assert 'x-model="packageCharacterName"' in template or "x-model='packageCharacterName'" in template
    assert 'x-model="packageUserName"' in template or "x-model='packageUserName'" in template
    assert "handlePackageAvatarFile('character', $event.target.files)" in template or 'handlePackageAvatarFile("character", $event.target.files)' in template
    assert "handlePackageAvatarFile('user', $event.target.files)" in template or 'handlePackageAvatarFile("user", $event.target.files)' in template
    assert '@click="clearPackageCharacterAvatar()"' in template or "@click='clearPackageCharacterAvatar()'" in template
    assert '@click="clearPackageUserAvatar()"' in template or "@click='clearPackageUserAvatar()'" in template
    assert '未设置，将使用全局默认角色资料' in template
    assert '未设置，将使用全局默认用户资料' in template
    assert '当前角色头像已覆盖全局设置' in template
    assert '当前用户头像已覆盖全局设置' in template


def test_beautify_grid_template_uses_single_line_inputs_for_package_identity_names():
    template = read_project_file('templates/components/grid_beautify.html')

    package_character_input_pattern = re.compile(
        r'<input\b(?=[^>]*\btype=["\']text["\'])(?=[^>]*\bclass=["\'][^"\']*\bbeautify-filter-input\b[^"\']*["\'])'
        r'(?=[^>]*\bx-model=["\']packageCharacterName["\'])(?=[^>]*\bplaceholder=["\']未设置，将使用全局默认角色资料["\'])[^>]*\/?>',
        re.DOTALL,
    )
    package_user_input_pattern = re.compile(
        r'<input\b(?=[^>]*\btype=["\']text["\'])(?=[^>]*\bclass=["\'][^"\']*\bbeautify-filter-input\b[^"\']*["\'])'
        r'(?=[^>]*\bx-model=["\']packageUserName["\'])(?=[^>]*\bplaceholder=["\']未设置，将使用全局默认用户资料["\'])[^>]*\/?>',
        re.DOTALL,
    )

    assert package_character_input_pattern.search(template)
    assert package_user_input_pattern.search(template)
    assert not re.search(r'<textarea\b[^>]*\bx-model=["\']packageCharacterName["\']', template, re.DOTALL)
    assert not re.search(r'<textarea\b[^>]*\bx-model=["\']packageUserName["\']', template, re.DOTALL)


def test_beautify_grid_template_settings_workspace_keeps_global_preview_surface():
    template = read_project_file('templates/components/grid_beautify.html')

    assert '全局默认预览' in template
    assert '不会带入当前包的主题与覆盖' in template


def test_beautify_grid_template_settings_workspace_reuses_scene_switcher_and_single_real_preview_column():
    template = read_project_file('templates/components/grid_beautify.html')

    settings_branch = extract_beautify_settings_workspace_branch(template)

    assert 'beautify-preview-scene-switcher' in settings_branch
    assert 'x-for="scene in previewScenes"' in settings_branch or "x-for='scene in previewScenes'" in settings_branch
    assert '@click="setPreviewScene(scene.id)"' in settings_branch or "@click='setPreviewScene(scene.id)'" in settings_branch
    assert 'beautify-settings-preview-stage' in settings_branch
    assert 'beautify-settings-preview-layout' in settings_branch
    assert 'beautify-settings-preview-column' in settings_branch
    assert 'beautify-settings-preview-sidebar-gap' not in settings_branch
    assert '加载全局默认预览' in settings_branch


def test_beautify_grid_template_settings_workspace_uses_shared_wallpaper_preview_tiles():
    template = read_project_file('templates/components/grid_beautify.html')

    settings_branch = extract_beautify_settings_workspace_branch(template)

    assert 'beautify-settings-wallpaper-grid' in settings_branch
    assert 'beautify-wallpaper-item beautify-settings-wallpaper-card' in settings_branch
    assert 'beautify-wallpaper-thumb beautify-settings-wallpaper-thumb' in settings_branch
    assert 'sharedWallpaperPreviewUrl(item.file)' in settings_branch
    assert 'wallpaperPreviewUrl(item.file)' not in settings_branch
    assert re.search(
        r'<div\s+class="beautify-wallpaper-thumb beautify-settings-wallpaper-thumb"',
        settings_branch,
    )


def test_beautify_grid_template_keeps_loaded_settings_preview_shell_inside_single_real_column():
    template = read_project_file('templates/components/grid_beautify.html')

    settings_branch = extract_beautify_settings_workspace_branch(template)

    assert re.search(
        r'<div class="beautify-settings-preview-stage">\s*'
        r'<div class="beautify-settings-preview-layout">\s*'
        r'<div class="beautify-settings-preview-column">[\s\S]*'
        r'<template x-if="!isMobileFullscreenEnabled\(\) && isPreviewLoaded">[\s\S]*'
        r'<div\s+class="beautify-preview-frame-shell beautify-settings-preview-shell"',
        settings_branch,
        re.DOTALL,
    )
    assert re.search(
        r'</template>\s*</div>\s*</div>\s*</div>',
        settings_branch,
    )


def test_beautify_grid_template_settings_workspace_preview_stage_keeps_balanced_div_closures():
    template = read_project_file('templates/components/grid_beautify.html')

    settings_branch = extract_beautify_settings_workspace_branch(template)
    assert '全局默认预览' in settings_branch
    assert settings_branch.count('<div') == settings_branch.count('</div>')


def test_beautify_grid_template_disables_preview_only_controls_in_screenshot_mode():
    template = read_project_file('templates/components/grid_beautify.html')

    assert ":disabled=\"stageMode === 'screenshot' || !hasPcVariant || isMobileBeautifyViewport()\"" in template or ':disabled="stageMode === \"screenshot\" || !hasPcVariant || isMobileBeautifyViewport()"' in template
    assert ":disabled=\"stageMode === 'screenshot' || !hasMobileVariant\"" in template or ':disabled="stageMode === \"screenshot\" || !hasMobileVariant"' in template
    assert ":disabled=\"stageMode === 'screenshot' || !canPreviewDualTarget\"" in template or ':disabled="stageMode === \"screenshot\" || !canPreviewDualTarget"' in template
    assert ":disabled=\"stageMode === 'screenshot' || wallpaperOptions.length === 0\"" in template or ':disabled="stageMode === \"screenshot\" || wallpaperOptions.length === 0"' in template


def test_beautify_grid_template_uses_unified_selected_variant_platform_for_dual_button_active_state():
    template = read_project_file('templates/components/grid_beautify.html')

    assert ":class=\"selectedVariantPlatform === 'dual' ? 'is-active' : ''\"" in template or ':class="selectedVariantPlatform === \"dual\" ? \'is-active\' : \'\'"' in template
    assert "activeVariant?.platform === 'dual' ? 'is-active' : ''" not in template
    assert 'activeVariant?.platform === "dual" ? "is-active" : ""' not in template


def test_beautify_grid_template_removes_install_and_apply_actions_and_approximation_copy():
    template = read_project_file('templates/components/grid_beautify.html')

    assert '安装到 ST' not in template
    assert '立即应用' not in template
    assert '当前预览为近似效果' not in template
    assert '安装与立即应用操作' not in template


def test_beautify_grid_template_uses_manual_native_preview_trigger():
    template = read_project_file('templates/components/grid_beautify.html')

    assert '加载原生 ST 预览' in template
    assert '!$store.global.beautifyPreviewUnavailableReason && !isPreviewLoaded' in template
    assert '@click="loadPreview()"' in template or "@click='loadPreview()'" in template
    assert 'previewHost' in template
    assert 'previewApproximateNoticeVisible' not in template


def test_beautify_grid_template_uses_combined_desktop_preview_conditions_for_package_stage():
    template = read_project_file('templates/components/grid_beautify.html')

    assert re.search(
        r'''x-if=(["'])!\$store\.global\.beautifyPreviewUnavailableReason\s*&&\s*!isMobileFullscreenEnabled\(\)\s*&&\s*!isPreviewLoaded\1''',
        template,
    )
    assert re.search(
        r'''x-if=(["'])!\$store\.global\.beautifyPreviewUnavailableReason\s*&&\s*!isMobileFullscreenEnabled\(\)\s*&&\s*isPreviewLoaded\1''',
        template,
    )
    assert not re.search(
        r'''<template\s+x-if=(["'])!isMobileFullscreenEnabled\(\)\1>\s*<template\s+x-if=''',
        template,
    )


def test_beautify_grid_template_wraps_package_preview_states_in_single_root():
    template = read_project_file('templates/components/grid_beautify.html')

    assert re.search(
        r'<template x-if="stageMode === [\'"]preview[\'"]">\s*<div class="beautify-preview-stage">',
        template,
    )


def test_beautify_grid_template_keeps_unavailable_device_button_disabled_instead_of_hidden():
    template = read_project_file('templates/components/grid_beautify.html')
    assert '!hasPcVariant' in template
    assert '!hasMobileVariant' in template


def test_beautify_grid_mobile_viewport_disables_pc_preview_button_in_template():
    template = read_project_file('templates/components/grid_beautify.html')

    assert 'isMobileBeautifyViewport()' in template
    assert 'selectedVariantPlatform === \'pc\'' in template or 'selectedVariantPlatform === "pc"' in template
    assert ":disabled=\"stageMode === 'screenshot' || !hasPcVariant || isMobileBeautifyViewport()\"" in template or ':disabled="stageMode === "screenshot" || !hasPcVariant || isMobileBeautifyViewport()"' in template
    assert 'beautifyPreviewUnavailableReason' in template
    assert '原生 ST 预览不可用' in template


def test_beautify_grid_template_uses_isolated_preview_host_instead_of_inline_preview_dom():
    template = read_project_file('templates/components/grid_beautify.html')

    assert 'beautify-preview-host' in template
    assert 'x-ref="previewHost"' in template or "x-ref='previewHost'" in template
    assert 'beautify-preview-frame-shell' in template
    assert 'beautify-preview-chat-window' not in template
    assert 'beautify-preview-inputbar' not in template
    assert 'customCssMarkup()' not in template


def test_beautify_grid_template_places_scene_switcher_in_host_stage_markup_only():
    template = read_project_file('templates/components/grid_beautify.html')

    assert 'beautify-preview-scene-switcher' in template
    assert '@click="setPreviewScene(' in template or "@click='setPreviewScene(" in template
    assert "x-for=\"scene in previewScenes\"" in template or "x-for='scene in previewScenes'" in template
    assert 'data-preview-scene-button' not in template
    assert 'data-preview-scene-template' not in template


def test_beautify_grid_template_uses_button_driven_mobile_preview_entries():
    template = read_project_file('templates/components/grid_beautify.html')

    assert 'beautify-mobile-entry-card' in template
    assert "openMobileFullscreen('preview'); loadPreview()" in template or 'openMobileFullscreen("preview"); loadPreview()' in template
    assert "openMobileFullscreen('screenshot')" in template or 'openMobileFullscreen("screenshot")' in template
    assert '加载全局默认预览' in template
    assert '加载原生 ST 预览' in template


def test_beautify_grid_template_simplifies_mobile_fullscreen_shell_and_uses_resetting_back_action():
    template = read_project_file('templates/components/grid_beautify.html')

    assert 'beautify-mobile-fullscreen' in template
    assert 'beautify-mobile-topbar' in template
    assert 'beautify-mobile-stage' in template
    assert '@click="closeMobilePreviewAndReset()"' in template or "@click='closeMobilePreviewAndReset()'" in template
    assert 'beautify-mobile-drawer' not in template
    assert 'toggleMobileDrawer()' not in template
    assert 'mobileDrawerSummary' not in template


def test_beautify_grid_template_places_mobile_fullscreen_shell_outside_package_only_branch():
    template = read_project_file('templates/components/grid_beautify.html')

    package_branch_index = template.index(
        '<template x-if="beautifyWorkspace !== \'settings\' && activePackage">'
    )
    mobile_fullscreen_index = template.index('<template x-if="showMobileFullscreen">')
    package_branch = template[package_branch_index:mobile_fullscreen_index]

    assert '{% macro package_detail_cards() %}' in template
    assert 'savePackageIdentityOverrides()' in template
    assert '{{ package_detail_cards() }}' in package_branch
    assert 'beautify-package-detail-drawer' in package_branch


def test_beautify_grid_template_keeps_header_owned_detail_toggle_without_preview_column_reopen_button():
    template = read_project_file('templates/components/grid_beautify.html')

    assert '@click="togglePackageDetailCollapsed()"' in template or "@click='togglePackageDetailCollapsed()'" in template
    assert "packageDetailCollapsed ? '展开详情' : '收起详情'" in template or 'packageDetailCollapsed ? "展开详情" : "收起详情"' in template
    assert 'beautify-package-detail-drawer' in template
    assert 'class="beautify-package-detail-reopen beautify-soft-btn"' not in template
    assert "class='beautify-package-detail-reopen beautify-soft-btn'" not in template
    assert 'openPackageDetailDrawer()' not in template


def test_beautify_layout_css_keeps_mobile_fullscreen_stage_without_drawer_rules():
    css = read_project_file('static/css/modules/view-beautify.css')
    fullscreen_block = extract_css_block_for_selector(css, '.beautify-mobile-fullscreen')
    stage_block = extract_css_block_for_selector(css, '.beautify-mobile-stage')

    assert_has_css_declaration(fullscreen_block, 'position', 'fixed')
    assert_has_css_declaration(fullscreen_block, 'inset', '0')
    assert_has_css_declaration(stage_block, 'flex', '1')
    assert_has_css_declaration(stage_block, 'min-height', '0')
    assert '.beautify-mobile-entry-card {' in css
    assert '.beautify-mobile-drawer {' not in css
    assert '.beautify-mobile-drawer-body {' not in css
    assert 'padding-bottom: 5.5rem;' not in stage_block


def test_beautify_layout_css_removes_preview_shell_chrome_inside_mobile_fullscreen():
    css = read_project_file('static/css/modules/view-beautify.css')
    assert re.search(
        r'\.beautify-mobile-preview-stage \.beautify-preview-frame-shell\s*\{[^}]*block-size:\s*100%;',
        css,
        re.DOTALL,
    )
    assert re.search(
        r'\.beautify-mobile-preview-stage \.beautify-preview-frame-shell\s*\{[^}]*border-radius:\s*0;',
        css,
        re.DOTALL,
    )
    assert re.search(
        r'\.beautify-mobile-preview-stage \.beautify-preview-frame-shell\s*\{[^}]*border:\s*0;',
        css,
        re.DOTALL,
    )


def test_beautify_layout_css_keeps_settings_preview_single_column_and_removes_gap_rules():
    css = read_project_file('static/css/modules/view-beautify.css')

    stage_block = extract_css_block_for_selector(css, '.beautify-settings-preview-stage')
    layout_block = extract_css_block_for_selector(css, '.beautify-settings-preview-layout')
    column_block = extract_css_block_for_selector(css, '.beautify-settings-preview-column')
    shell_block = extract_css_block_for_selector(css, '.beautify-settings-preview-shell')

    assert_has_css_declaration(stage_block, 'margin-top', '0.9rem')
    assert_has_css_declaration(layout_block, 'display', 'grid')
    assert_has_css_declaration(layout_block, 'grid-template-columns', 'minmax(0, 1fr)')
    assert_has_css_declaration(column_block, 'display', 'flex')
    assert_has_css_declaration(column_block, 'gap', '0.9rem')
    assert_has_css_declaration(shell_block, 'margin-top', '0')
    assert '.beautify-settings-preview-sidebar-gap {' not in css


def test_beautify_layout_css_styles_settings_wallpaper_thumb_as_a_block_tile():
    css = read_project_file('static/css/modules/view-beautify.css')

    card_block = extract_css_block_for_selector(css, '.beautify-settings-wallpaper-card')
    thumb_block = extract_css_block_for_selector(
        css,
        '.beautify-wallpaper-thumb.beautify-settings-wallpaper-thumb',
    )

    assert_has_css_declaration(card_block, 'flex-direction', 'column')
    assert_has_css_declaration(card_block, 'padding', '0.7rem')
    assert_has_css_declaration(thumb_block, 'display', 'block')
    assert_has_css_declaration(thumb_block, 'width', '100%')
    assert_has_css_declaration(thumb_block, 'aspect-ratio', '16 / 10')
    assert not re.search(r'^\.beautify-settings-wallpaper-thumb\s*\{', css, re.MULTILINE)


def test_beautify_grid_template_keeps_screenshot_entry_available_without_imported_images():
    template = read_project_file('templates/components/grid_beautify.html')

    assert ':disabled="screenshotOptions.length === 0"' not in template
    assert '@click="setStageMode(\'screenshot\')"' in template or "@click='setStageMode(\'screenshot\')'" in template or '@click="setStageMode("screenshot")"' in template


def test_beautify_layout_css_uses_shared_sidebar_flex_contract():
    css = read_project_file('static/css/modules/view-beautify.css')
    token_block = extract_css_block(css, r':is\(\.beautify-layout, \.beautify-sidebar-panel\)')
    layout_block = extract_css_block_for_selector(css, '.beautify-layout')
    sidebar_block = extract_css_block_for_selector(css, '.beautify-sidebar-panel')
    stage_block = extract_css_block_for_selector(css, '.beautify-stage-pane')

    assert ':is(.beautify-layout, .beautify-sidebar-panel)' in css
    assert '--beautify-control-gap:' in token_block
    assert 'display: flex;' in layout_block
    assert 'min-width: 0;' in layout_block
    assert 'grid-template-columns' not in layout_block
    assert 'display: flex;' in sidebar_block
    assert 'flex-direction: column;' in sidebar_block
    assert 'min-height: 0;' in sidebar_block
    assert '.beautify-stage-pane {' in css
    assert 'flex: 1;' in stage_block
    assert 'min-width: 0;' in stage_block
    assert 'min-height: 0;' in stage_block
    assert 'overflow-y: auto;' in stage_block
    assert 'overflow-x: hidden;' in stage_block
    assert '.beautify-sidebar-pane {' not in css


def test_beautify_layout_css_replaces_dark_shell_colors_with_theme_driven_surfaces():
    css = read_project_file('static/css/modules/view-beautify.css')
    token_block = extract_css_block(css, r':is\(\.beautify-layout, \.beautify-sidebar-panel\)')
    layout_block = extract_css_block_for_selector(css, '.beautify-layout')
    sidebar_block = extract_css_block_for_selector(css, '.beautify-sidebar-panel')
    switcher_block = css.split('.beautify-workspace-switcher {', 1)[1].split('}', 1)[0]
    frame_shell_block = extract_css_block_for_selector(css, '.beautify-preview-frame-shell')
    control_block = extract_css_block_for_selector(css, '.beautify-primary-btn')
    primary_button_block = css.split('.beautify-primary-btn {', 1)[1].split('}', 1)[0]

    assert '--beautify-shell-bg:' in token_block
    assert '--beautify-panel-bg:' in token_block
    assert '--beautify-panel-bg-strong:' in token_block
    assert '--beautify-control-bg:' in token_block
    assert '--beautify-control-bg-hover:' in token_block
    assert_has_css_declaration(layout_block, 'background', 'var(--beautify-shell-bg)')
    assert_has_css_declaration(sidebar_block, 'background', 'var(--beautify-panel-bg)')
    assert_has_css_declaration(switcher_block, 'background', 'var(--beautify-panel-bg-strong)')
    assert_has_css_declaration(control_block, 'background', 'var(--beautify-control-bg)')
    assert '--beautify-shell-frame-bg:' in token_block
    assert '--beautify-shell-frame-border:' in token_block
    # Token definitions may still contain dark fallback mixes, but the shell and controls should not hard-code them.
    assert 'rgba(15, 23, 42' not in token_block
    assert 'rgba(15, 23, 42' not in sidebar_block
    assert 'rgba(15, 23, 42' not in switcher_block
    assert 'rgba(15, 23, 42' not in control_block
    assert 'rgba(30, 41, 59' not in control_block
    assert_has_css_declaration(frame_shell_block, 'background', 'var(--beautify-shell-frame-bg)')
    assert 'border: 1px solid var(--beautify-shell-frame-border);' in frame_shell_block or has_css_declaration(
        frame_shell_block,
        'border',
        'var(--beautify-shell-frame-border)',
    )
    assert 'color-mix(in srgb, var(--accent-main)' in primary_button_block
    assert 'linear-gradient(135deg, var(--accent-main), #8b5cf6)' not in primary_button_block


def test_beautify_layout_css_keeps_shell_root_transparent_while_stage_and_cards_stay_themed():
    css = read_project_file('static/css/modules/view-beautify.css')
    token_block = extract_css_block(css, r':is\(\.beautify-layout, \.beautify-sidebar-panel\)')
    layout_block = extract_css_block_for_selector(css, '.beautify-layout')
    stage_block = extract_css_block_for_selector(css, '.beautify-stage-pane')
    detail_card_block = extract_css_block_for_selector(css, '.beautify-detail-card')

    assert '--beautify-shell-bg: transparent;' in token_block
    assert not has_css_declaration(layout_block, 'background', 'var(--bg-body)')
    assert_has_css_declaration(layout_block, 'background', 'var(--beautify-shell-bg)')
    assert_has_css_declaration(stage_block, 'background', 'var(--beautify-stage-surface)')
    assert_has_css_declaration(detail_card_block, 'background', 'var(--beautify-card-surface)')


def test_beautify_layout_css_styles_isolated_preview_host_shell():
    css = read_project_file('static/css/modules/view-beautify.css')
    unloaded_block = css.split('.beautify-preview-unloaded-card {', 1)[1].split('}', 1)[0]
    frame_shell_block = css.split('.beautify-preview-frame-shell {', 1)[1].split('}', 1)[0]
    preview_host_block = css.split('.beautify-preview-host {', 1)[1].split('}', 1)[0]
    mobile_shell_block = css.split('.beautify-preview-frame-shell.is-mobile {', 1)[1].split('}', 1)[0]

    assert '.beautify-preview-unloaded-card {' in css
    assert 'min-height: 220px;' in unloaded_block
    assert 'justify-content: center;' in unloaded_block
    assert '.beautify-preview-frame-shell {' in css
    assert 'block-size: clamp(' in frame_shell_block
    assert 'overflow: hidden;' in frame_shell_block
    assert '.beautify-preview-host {' in css
    assert 'flex: 1;' in preview_host_block
    assert 'width: 100%;' in preview_host_block
    assert 'height: 100%;' in preview_host_block
    assert 'border: 0;' in preview_host_block
    assert 'background: transparent;' in preview_host_block
    assert '.beautify-preview-frame-shell.is-mobile {' in css
    assert 'max-width: 420px;' in mobile_shell_block
    assert '.beautify-preview-chat-window {' not in css
    assert '.beautify-preview-inputbar {' not in css


def test_beautify_layout_css_styles_host_owned_scene_switcher_surface():
    css = read_project_file('static/css/modules/view-beautify.css')
    switcher_block = extract_css_block_for_selector(css, '.beautify-preview-scene-switcher')
    button_block = extract_css_block_for_selector(css, '.beautify-preview-scene-btn')
    active_button_block = extract_css_block_for_selector(css, '.beautify-preview-scene-btn.is-active')

    assert_has_css_declaration(switcher_block, 'display', 'flex')
    assert_has_css_declaration(switcher_block, 'border', 'var(--border-light)')
    assert_has_css_declaration(switcher_block, 'background', 'var(--beautify-card-surface)')
    assert_has_css_declaration(button_block, 'text-align', 'left')
    assert_has_css_declaration(button_block, 'background', 'transparent')
    assert_has_css_declaration(active_button_block, 'border-color', 'var(--beautify-active-border)')
    assert_has_css_declaration(active_button_block, 'background', 'var(--beautify-active-bg)')


def test_beautify_layout_css_uses_theme_driven_stage_cards_and_active_states():
    css = read_project_file('static/css/modules/view-beautify.css')
    token_block = extract_css_block(css, r':is\(\.beautify-layout, \.beautify-sidebar-panel\)')
    thumb_block = extract_css_block_for_selector(css, '.beautify-screenshot-thumb')
    stage_block = extract_css_block_for_selector(css, '.beautify-stage-pane')
    detail_card_block = extract_css_block_for_selector(css, '.beautify-detail-card')
    muted_surface_block = extract_css_block_for_selector(css, '.beautify-settings-textarea')
    frame_shell_block = extract_css_block_for_selector(css, '.beautify-preview-frame-shell')
    active_state_block = extract_css_block_for_selector(css, '.beautify-package-card.is-active')

    assert '--beautify-stage-surface:' in token_block
    assert '--beautify-card-surface:' in token_block
    assert '--beautify-muted-surface:' in token_block
    assert '--beautify-thumbnail-border:' in token_block
    assert '--beautify-shell-frame-bg:' in token_block
    assert '--beautify-shell-frame-border:' in token_block
    assert '--beautify-active-bg:' in token_block
    assert '--beautify-active-border:' in token_block
    assert '--beautify-active-shadow:' in token_block
    assert_has_css_declaration(thumb_block, 'border', 'var(--beautify-thumbnail-border)')
    assert_has_css_declaration(stage_block, 'background', 'var(--beautify-stage-surface)')
    assert_has_css_declaration(detail_card_block, 'background', 'var(--beautify-card-surface)')
    assert_has_css_declaration(muted_surface_block, 'background', 'var(--beautify-muted-surface)')
    assert_has_css_declaration(frame_shell_block, 'border', 'var(--beautify-shell-frame-border)')
    assert_has_css_declaration(frame_shell_block, 'background', 'var(--beautify-shell-frame-bg)')
    assert_has_css_declaration(active_state_block, 'border-color', 'var(--beautify-active-border)')
    assert_has_css_declaration(active_state_block, 'background', 'var(--beautify-active-bg)')
    assert_has_css_declaration(active_state_block, 'box-shadow', 'var(--beautify-active-shadow)')


def test_beautify_layout_css_avoids_fixed_pale_text_colors_for_status_pills_and_preview_notice():
    css = read_project_file('static/css/modules/view-beautify.css')
    installed_block = extract_css_block_for_selector(css, '.beautify-status-pill.is-installed')
    applied_block = extract_css_block_for_selector(css, '.beautify-status-pill.is-applied')
    preview_notice_block = extract_css_block_for_selector(css, '.beautify-preview-notice')

    assert '#bfdbfe' not in installed_block
    assert '#a7f3d0' not in applied_block
    assert '#fde68a' not in preview_notice_block
    assert_has_css_declaration(installed_block, 'color', 'var(--text-main)')
    assert_has_css_declaration(applied_block, 'color', 'var(--text-main)')
    assert_has_css_declaration(preview_notice_block, 'color', 'var(--text-main)')


def test_beautify_grid_template_mobile_css_drops_grid_area_layout():
    css = read_project_file('static/css/modules/view-beautify.css')

    mobile_block = css.split('@media (max-width: 900px) {', 1)[1]

    assert 'grid-template-areas' not in mobile_block
    assert '.sidebar-mobile .beautify-sidebar-panel {' in mobile_block


def test_beautify_layout_css_keeps_single_column_stage_rows_content_sized():
    css = read_project_file('static/css/modules/view-beautify.css')

    tablet_block = css.split('@media (max-width: 1180px) {', 1)[1].split(
        '@media (max-width: 900px) {', 1
    )[0]
    stage_body_block = extract_css_block_for_selector(tablet_block, '.beautify-stage-body')

    assert_has_css_declaration(stage_body_block, 'flex', '0 0 auto')
    assert_has_css_declaration(stage_body_block, 'align-content', 'start')


def test_beautify_layout_css_supports_package_detail_collapsed_stage_state():
    css = read_project_file('static/css/modules/view-beautify.css')

    assert '.beautify-stage-body.is-detail-collapsed {' in css
    collapsed_block = extract_css_block_for_selector(css, '.beautify-stage-body.is-detail-collapsed')
    assert_has_css_declaration(collapsed_block, 'grid-template-columns', 'minmax(0, 1fr)')
    assert '.beautify-package-detail-reopen {' not in css


def test_beautify_stage_header_actions_keep_delete_button_horizontal():
    css = read_project_file('static/css/modules/view-beautify.css')
    header_actions_block = css.split('.beautify-stage-header-actions {', 1)[1].split('}', 1)[0]
    delete_button_block = css.split('.beautify-stage-header-actions .beautify-soft-btn {', 1)[1].split('}', 1)[0]
    platform_select_block = css.split('.beautify-stage-header-actions .beautify-filter-select {', 1)[1].split('}', 1)[0]

    assert 'flex-wrap: nowrap;' in header_actions_block
    assert 'justify-content: flex-end;' in header_actions_block
    assert 'white-space: nowrap;' in delete_button_block
    assert 'flex: 0 0 auto;' in delete_button_block
    assert 'width: auto;' in platform_select_block
    assert 'flex: 0 1 220px;' in platform_select_block


def test_beautify_toolbar_action_buttons_keep_import_labels_on_single_line():
    css = read_project_file('static/css/modules/view-beautify.css')
    action_button_block = extract_css_block(
        css,
        r'\.beautify-action-btn,\s*\.beautify-soft-btn,\s*\.beautify-primary-btn,\s*\.beautify-device-btn',
    )

    assert_has_css_declaration(action_button_block, 'white-space', 'nowrap')
