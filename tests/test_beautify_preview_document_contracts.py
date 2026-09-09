import json
import re
import subprocess
import textwrap
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / 'static/js/components/beautifyPreviewDocument.js'
ADAPTER_MODULE_PATH = ROOT / 'static/js/components/beautifyPreviewDrawerAdapters.js'
VENDOR_SHELL_MODULE_PATH = ROOT / 'static/vendor/sillytavern/preview-shell.js'
VENDOR_DRAWERS_MODULE_PATH = ROOT / 'static/vendor/sillytavern/preview-drawers.js'


def test_vendored_sillytavern_shell_assets_exist_for_vendor_first_preview():
    root = ROOT / 'static' / 'vendor' / 'sillytavern'
    required_paths = [
        root / 'index.html',
        root / 'style.css',
        root / 'css' / 'fontawesome.min.css',
        root / 'css' / 'solid.min.css',
        root / 'css' / 'brands.min.css',
        root / 'webfonts',
    ]

    missing = [str(path.relative_to(ROOT)) for path in required_paths if not path.exists()]
    assert not missing, f'Missing required vendored ST preview assets: {missing}'


def test_vendored_sillytavern_index_html_direct_local_dependencies_exist():
    root = ROOT / 'static' / 'vendor' / 'sillytavern'
    index_html = (root / 'index.html').read_text(encoding='utf-8')
    dependency_pattern = re.compile(r'(?:href|src)="(?!https?:|//|/|#|data:|mailto:|javascript:)([^"]+)"')
    expected_dependencies = sorted(set(dependency_pattern.findall(index_html)))

    missing = [
        str((root / relative_path).relative_to(ROOT)).replace('\\', '/')
        for relative_path in expected_dependencies
        if not (root / relative_path).exists()
    ]

    assert expected_dependencies, 'Expected vendored index.html to declare local relative dependencies'
    assert not missing, f'Missing direct local vendored index.html dependencies: {missing}'


def test_vendor_first_preview_shell_artifact_exists_and_tracks_provenance():
    shell_module = ROOT / 'static' / 'vendor' / 'sillytavern' / 'preview-shell.js'
    source_md = (ROOT / 'static' / 'vendor' / 'sillytavern' / 'SOURCE.md').read_text(encoding='utf-8')

    assert shell_module.exists(), 'Expected vendor-derived preview shell artifact to exist'
    assert 'preview-shell.js' in source_md, 'Expected SOURCE.md to document preview-shell.js provenance'


def test_drawer_module_exists_and_exports_three_markup_constants():
    node_script = textwrap.dedent(
        f'''
        import {{ pathToFileURL }} from 'node:url';
        const modulePath = {json.dumps(str(VENDOR_DRAWERS_MODULE_PATH.resolve()))};
        const module = await import(pathToFileURL(modulePath).href);

        const expectedExports = [
          'SETTINGS_DRAWER_VENDOR_MARKUP',
          'FORMATTING_DRAWER_VENDOR_MARKUP',
          'CHARACTER_DRAWER_VENDOR_MARKUP',
        ];

        for (const exportName of expectedExports) {{
          const value = module[exportName];
          if (typeof value !== 'string') throw new Error(`expected string export: ${{exportName}}`);
          if (!value.trim()) throw new Error(`expected non-empty export: ${{exportName}}`);
        }}
        '''
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_keeps_expected_upstream_tokens_for_each_supported_drawer():
    node_script = textwrap.dedent(
        f'''
        import {{ pathToFileURL }} from 'node:url';
        const module = await import(pathToFileURL({json.dumps(str(VENDOR_DRAWERS_MODULE_PATH.resolve()))}).href);

        const expectedTokensByExport = {{
          SETTINGS_DRAWER_VENDOR_MARKUP: [
            'id="clickSlidersTips"',
            'id="amount_gen"',
            'id="max_context"',
            'id="kobold_order"',
            'id="samplers_order_recommended"',
          ],
          FORMATTING_DRAWER_VENDOR_MARKUP: [
            'id="ContextSettings"',
            'id="instruct_presets"',
            'id="sysprompt_select"',
            'id="custom_stopping_strings"',
            'id="tokenizer"',
          ],
          CHARACTER_DRAWER_VENDOR_MARKUP: [
            'id="rm_PinAndTabs"',
            'id="rm_characters_block"',
            'id="character_search_bar"',
            'id="charListGridToggle"',
            'id="rm_print_characters_block"',
          ],
        }};

        for (const [exportName, expectedTokens] of Object.entries(expectedTokensByExport)) {{
          const markup = module[exportName];
          if (typeof markup !== 'string') throw new Error(`expected string export: ${{exportName}}`);

          for (const token of expectedTokens) {{
            if (!markup.includes(token)) {{
              throw new Error(`missing token in ${{exportName}}: ${{token}}`);
            }}
          }}
        }}
        '''
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_character_drawer_vendor_markup_keeps_contiguous_upstream_region_between_tabs_and_list_end():
    node_script = textwrap.dedent(
        f'''
        import {{ pathToFileURL }} from 'node:url';
        const module = await import(pathToFileURL({json.dumps(str(VENDOR_DRAWERS_MODULE_PATH.resolve()))}).href);
        const markup = module.CHARACTER_DRAWER_VENDOR_MARKUP;

        const orderedTokens = [
          'id="rm_PinAndTabs"',
          'id="description_textarea"',
          'id="firstmessage_textarea"',
          'id="hidden-divs"',
          'id="group-chat-lorebook-dropdown"',
          'id="rm_group_generation_mode"',
          'id="groupCurrentMemberListToggle"',
          'id="rm_group_members"',
          'id="groupAddMemberListToggle"',
          'id="rm_group_add_members"',
          'id="rm_print_characters_block"',
        ];

        let previousIndex = -1;
        for (const token of orderedTokens) {{
          const index = markup.indexOf(token);
          if (index === -1) throw new Error(`missing contiguous character drawer token: ${{token}}`);
          if (index <= previousIndex) throw new Error(`out-of-order contiguous character drawer token: ${{token}}`);
          previousIndex = index;
        }}

        for (const shellOwnedToken of [
          'id="right-nav-panelheader"',
          'id="CharListButtonAndHotSwaps"',
        ]) {{
          if (markup.includes(shellOwnedToken)) {{
            throw new Error(`shell-owned token leaked into character drawer markup: ${{shellOwnedToken}}`);
          }}
        }}
        '''
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def run_preview_document_check(script_body: str) -> None:
    node_script = textwrap.dedent(
        f'''
        import {{ pathToFileURL }} from 'node:url';
        const module = await import(pathToFileURL({json.dumps(str(MODULE_PATH.resolve()))}).href);
        {textwrap.dedent(script_body)}
        '''
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def run_preview_drawer_adapter_check(script_body: str) -> None:
    node_script = textwrap.dedent(
        f'''
        import {{ pathToFileURL }} from 'node:url';
        const module = await import(pathToFileURL({json.dumps(str(ADAPTER_MODULE_PATH.resolve()))}).href);
        {textwrap.dedent(script_body)}
        '''
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_settings_drawer_adapter_preserves_vendor_first_screen_without_preview_layout_override():
    run_preview_drawer_adapter_check(
        '''
        const markup = module.buildSettingsDrawerPreviewMarkupFromVendor({ theme: {} });
        const hasAttributes = (tag, attributes) => attributes.every((attribute) => tag.includes(attribute));

        for (const token of [
          'id="clickSlidersTips"',
          'id="labModeWarning"',
          'id="kobold_api-presets"',
          'id="amount_gen_block"',
          'id="max_context_block"',
          'id="kobold_api-settings"',
        ]) {
          if (!markup.includes(token)) throw new Error(`missing preserved settings token: ${token}`);
        }

        const responseConfigurationMatch = markup.match(/<[^>]*id="ai_response_configuration"[^>]*>/);
        if (!responseConfigurationMatch) {
          throw new Error('missing ai_response_configuration opening tag');
        }
        if (responseConfigurationMatch[0].includes('display: flex; flex-direction: column; gap: 10px;')) {
          throw new Error(`unexpected preview-owned layout override on ai_response_configuration: ${responseConfigurationMatch[0]}`);
        }

        for (const hiddenSectionId of ['ai_module_block_novel', 'prompt_cost_block']) {
          const match = markup.match(new RegExp(`<[^>]*id="${hiddenSectionId}"[^>]*>`));
          if (!match) throw new Error(`missing hidden section opening tag: ${hiddenSectionId}`);
          if (!match[0].includes('style="display: none;"')) {
            throw new Error(`expected hidden section style on ${hiddenSectionId}`);
          }
        }

        const sectionIndexes = [
          'id="kobold_api-presets"',
          'id="amount_gen_block"',
          'id="kobold_api-settings"',
        ].map((token) => markup.indexOf(token));
        if (sectionIndexes.some((index) => index === -1)) {
          throw new Error('missing settings section required for first-screen order assertion');
        }
        if (!(sectionIndexes[0] < sectionIndexes[1] && sectionIndexes[1] < sectionIndexes[2])) {
          throw new Error('expected settings first-screen section order to remain presets -> amount_gen_block -> kobold_api-settings');
        }

        for (const selector of [
          'data-preset-manager-import="kobold"',
          'data-preset-manager-export="kobold"',
          'data-preset-manager-delete="kobold"',
          'data-preset-manager-update="kobold"',
          'data-preset-manager-rename="kobold"',
          'data-preset-manager-new="kobold"',
          'data-preset-manager-restore="kobold"',
        ]) {
          const match = markup.match(new RegExp(`<[^>]*${selector}[^>]*>`));
          if (!match) throw new Error(`missing disabled settings action tag: ${selector}`);
          if (!hasAttributes(match[0], [selector, 'data-preview-disabled="true"'])) {
            throw new Error(`missing disabled settings action attribute: ${selector}`);
          }
        }
        '''
    )


def test_formatting_drawer_adapter_injects_scene_prompt_and_keeps_core_sections():
    run_preview_drawer_adapter_check(
        '''
        const scenePromptContent = '<scene prompt & details>';
        const markup = module.buildFormattingDrawerPreviewMarkupFromVendor({ scenePromptContent });
        const hasAttributes = (tag, attributes) => attributes.every((attribute) => tag.includes(attribute));

        for (const token of [
          'id="ContextSettings"',
          'id="instruct_presets"',
          'id="sysprompt_select"',
          'id="custom_stopping_strings"',
          'id="tokenizer"',
        ]) {
          if (!markup.includes(token)) throw new Error(`missing preserved formatting token: ${token}`);
        }

        if (!markup.includes('&lt;scene prompt &amp; details&gt;')) {
          throw new Error('expected escaped scene prompt content in formatting drawer');
        }

        for (const selector of ['id="af_master_import"', 'id="af_master_export"']) {
          const match = markup.match(new RegExp(`<[^>]*${selector}[^>]*>`));
          if (!match) throw new Error(`missing disabled formatting action tag: ${selector}`);
          if (!hasAttributes(match[0], [selector, 'data-preview-disabled="true"'])) {
            throw new Error(`missing disabled formatting action attribute: ${selector}`);
          }
        }
        '''
    )


def test_drawer_adapters_consume_vendor_markup_overrides_when_provided():
    run_preview_drawer_adapter_check(
        '''
        const settingsMarkup = module.buildSettingsDrawerPreviewMarkupFromVendor({
          vendorMarkup: '<section data-override="settings"><div data-preset-manager-import="kobold"></div></section>',
        });
        if (!settingsMarkup.includes('data-override="settings"')) {
          throw new Error('settings adapter did not consume vendorMarkup override');
        }
        if (settingsMarkup.includes('id="amount_gen"')) {
          throw new Error('settings adapter unexpectedly fell back to module-level vendor markup');
        }
        if (!settingsMarkup.includes('data-preview-disabled="true"')) {
          throw new Error('settings adapter should still augment override markup');
        }

        const formattingMarkup = module.buildFormattingDrawerPreviewMarkupFromVendor({
          scenePromptContent: 'override prompt',
          vendorMarkup: '<section data-override="formatting"><textarea id="context_story_string"></textarea><button id="af_master_import"></button><button id="af_master_export"></button></section>',
        });
        if (!formattingMarkup.includes('data-override="formatting"')) {
          throw new Error('formatting adapter did not consume vendorMarkup override');
        }
        if (formattingMarkup.includes('id="ContextSettings"')) {
          throw new Error('formatting adapter unexpectedly fell back to module-level vendor markup');
        }
        if (!formattingMarkup.includes('>override prompt</textarea>')) {
          throw new Error('formatting adapter should still inject prompt content into override markup');
        }

        const characterMarkup = module.buildCharacterDrawerPreviewMarkupFromVendor({
          identities: { character: { name: 'Override Hero', avatarSrc: '/static/img/override-hero.webp' } },
          detail: {
            packageName: 'Override Package',
            description: 'Override <b>Description</b>',
          },
          vendorMarkup: `
            <section data-override="character">
              <div id="character_search_bar"></div>
              <div id="rm_print_characters_block" class="flexFlowColumn"></div>
              <div id="rm_button_search" class="search-btn"></div>
              <div id="charListGridToggle" class="grid-btn"></div>
              <div id="rm_button_create"></div>
              <div id="rm_ch_create_block"></div>
              <div id="rm_group_chats_block"></div>
              <div id="rm_character_import"></div>
              <div id="rm_characters_block"></div>
            </section>`,
        });
        if (!characterMarkup.includes('data-override="character"')) {
          throw new Error('character adapter did not consume vendorMarkup override');
        }
        if (characterMarkup.includes('id="rm_PinAndTabs"')) {
          throw new Error('character adapter unexpectedly fell back to module-level vendor markup');
        }
        if (!characterMarkup.includes('Override Hero')) {
          throw new Error('character adapter should still inject identity data into override markup');
        }
        for (const token of [
          'class="flex-container wide100pLess70px character_select_container"',
          'class="character_select"',
          '/static/img/override-hero.webp',
          'Override Hero',
          'Override Package',
          'Override &lt;b&gt;Description&lt;/b&gt;',
          'data-preview-action="toggle-search"',
          'data-preview-action="toggle-grid"',
        ]) {
          if (!characterMarkup.includes(token)) throw new Error(`missing override character token: ${token}`);
        }
        if (characterMarkup.includes('data-preview-character-card="primary"')) {
          throw new Error('legacy preview character card token should not remain in override path');
        }
        for (const forbidden of [
          'data-preview-action="show-detail"',
          'data-preview-action="show-list"',
          'id="personality_textarea"',
          'id="creator_notes_textarea"',
        ]) {
          if (characterMarkup.includes(forbidden)) throw new Error(`unexpected override character token: ${forbidden}`);
        }
        '''
    )


def test_character_drawer_adapter_emits_st_list_row_preview():
    run_preview_drawer_adapter_check(
        '''
        const hasAttributes = (tag, attributes) => attributes.every((attribute) => tag.includes(attribute));
        const markup = module.buildCharacterDrawerPreviewMarkupFromVendor({
          identities: {
            character: {
              name: 'Preview Hero',
              avatarSrc: '/static/img/preview-hero.webp',
            },
          },
          detail: {
            packageName: 'Demo Package',
            description: 'A <b>preview</b> description',
          },
        });

        for (const token of [
          'id="rm_characters_block"',
          'id="character_search_bar"',
          'id="rm_print_characters_block"',
          'class="flex-container wide100pLess70px character_select_container"',
          'class="character_select"',
          '/static/img/preview-hero.webp',
          'Preview Hero',
          'Demo Package',
          'A &lt;b&gt;preview&lt;/b&gt; description',
          'data-preview-disabled="true"',
        ]) {
          if (!markup.includes(token)) throw new Error(`missing ST character preview token: ${token}`);
        }

        if (markup.includes('data-preview-character-card="primary"')) {
          throw new Error('unexpected legacy custom preview character card remains');
        }

        for (const [selector, attributes] of [
          ['id="rm_button_search"', ['data-preview-action="toggle-search"']],
          ['id="charListGridToggle"', ['data-preview-action="toggle-grid"']],
          ['id="rm_ch_create_block"', ['style="display: none;"']],
          ['id="rm_group_chats_block"', ['style="display: none;"']],
          ['id="rm_character_import"', ['style="display: none;"']],
          ['id="rm_characters_block"', ['style="display: block;"']],
        ]) {
          const match = markup.match(new RegExp(`<[^>]*${selector}[^>]*>`));
          if (!match) throw new Error(`missing character preview hook tag: ${selector}`);
          if (!hasAttributes(match[0], [selector, ...attributes])) {
            throw new Error(`missing character preview hook attribute: ${selector}`);
          }
        }

        for (const forbidden of [
          'data-preview-action="show-detail"',
          'data-preview-action="show-list"',
          'id="personality_textarea"',
          'id="creator_notes_textarea"',
        ]) {
          if (markup.includes(forbidden)) throw new Error(`unexpected character preview token: ${forbidden}`);
        }
        '''
    )


def test_build_beautify_preview_document_loads_pc_vendored_st_assets_without_mobile_stylesheet():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          platform: 'pc',
          theme: { custom_css: 'body { color: red; }' },
          wallpaperUrl: '/api/beautify/preview-asset/packages/pkg_demo/wallpapers/demo.webp',
        });

        if (!html.includes('/static/vendor/sillytavern/style.css')) throw new Error('missing vendored ST style.css');
        if (html.includes('/static/vendor/sillytavern/css/mobile-styles.css')) throw new Error('pc preview should not load mobile stylesheet');
        if (html.includes('st-preview-base.css')) throw new Error('old preview base css should not load');
        if (!html.includes('body { color: red; }')) throw new Error('missing custom css');
        if (!html.includes('id="top-settings-holder"')) throw new Error('missing ST top settings holder');
        if (!html.includes('id="chat"')) throw new Error('missing ST chat');
        if (!html.includes('id="send_form"')) throw new Error('missing ST send form');
        '''
    )


def test_build_beautify_preview_document_loads_mobile_stylesheet_only_for_mobile_preview():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          platform: 'mobile',
          theme: { custom_css: 'body { color: red; }' },
          wallpaperUrl: '/api/beautify/preview-asset/packages/pkg_demo/wallpapers/demo.webp',
        });

        if (!html.includes('/static/vendor/sillytavern/style.css')) throw new Error('missing vendored ST style.css');
        if (!html.includes('/static/vendor/sillytavern/css/mobile-styles.css')) throw new Error('missing vendored ST mobile stylesheet');
        if (!html.includes("body[data-st-preview-platform='mobile'] #leftSendForm")) throw new Error('mobile preview should keep send tools on one row');
        '''
    )


def test_build_beautify_preview_document_loads_vendored_icon_stylesheets():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc', theme: {} });

        for (const token of [
          '/static/vendor/sillytavern/style.css',
          '/static/vendor/sillytavern/css/fontawesome.min.css',
          '/static/vendor/sillytavern/css/solid.min.css',
          '/static/vendor/sillytavern/css/brands.min.css',
        ]) {
          if (!html.includes(token)) throw new Error(`missing vendored stylesheet: ${token}`);
        }
        '''
    )


def test_build_beautify_preview_document_keeps_fontawesome_stylesheets_ahead_of_style_css_like_st():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'mobile', theme: {} });

        const fontawesomeIndex = html.indexOf('/static/vendor/sillytavern/css/fontawesome.min.css');
        const solidIndex = html.indexOf('/static/vendor/sillytavern/css/solid.min.css');
        const brandsIndex = html.indexOf('/static/vendor/sillytavern/css/brands.min.css');
        const styleIndex = html.indexOf('/static/vendor/sillytavern/style.css');

        if (fontawesomeIndex === -1 || solidIndex === -1 || brandsIndex === -1 || styleIndex === -1) {
          throw new Error('missing core vendored stylesheet link');
        }
        if (!(fontawesomeIndex < styleIndex && solidIndex < styleIndex && brandsIndex < styleIndex)) {
          throw new Error('expected Font Awesome stylesheets to load before style.css to match current ST');
        }
        '''
    )


def test_build_beautify_preview_document_imports_vendor_derived_shell_artifact():
    source = MODULE_PATH.read_text(encoding='utf-8')

    assert 'vendor/sillytavern/preview-shell.js' in source
    assert 'buildVendorFirstPreviewShell' in source


def test_vendor_derived_preview_shell_module_exposes_full_vendored_toolbar_and_send_form_structure():
    node_script = textwrap.dedent(
        f'''
        import {{ pathToFileURL }} from 'node:url';
        const shellModule = await import(pathToFileURL({json.dumps(str(VENDOR_SHELL_MODULE_PATH.resolve()))}).href);
        if (typeof shellModule.buildVendorFirstPreviewShell !== 'function') {{
          throw new Error('missing buildVendorFirstPreviewShell export');
        }}
        const markup = shellModule.buildVendorFirstPreviewShell({{
          activeSceneId: 'daily',
          settingsDrawerContentMarkup: '<div>settings</div>',
          formattingDrawerContentMarkup: '<div>formatting</div>',
          characterDrawerContentMarkup: '<div>character</div>',
          chatMarkup: '<div>chat</div>',
          sendFormClassNames: 'no-connection compact',
        }});

        for (const token of [
          'id="ai-config-button"',
          'id="sys-settings-button"',
          'id="advanced-formatting-button"',
          'id="WI-SP-button"',
          'id="user-settings-button"',
          'id="backgrounds-button"',
          'id="extensions-settings-button"',
          'id="persona-management-button"',
          'id="rightNavHolder"',
          'id="send_form"',
          'id="leftSendForm"',
          'id="rightSendForm"',
        ]) {{
          if (!markup.includes(token)) throw new Error(`missing vendored shell token: ${{token}}`);
        }}

        for (const token of ['<div>settings</div>', '<div>formatting</div>', '<div>character</div>', '<div>chat</div>']) {{
          if (!markup.includes(token)) throw new Error(`missing hydrated content token: ${{token}}`);
        }}

        if (!markup.includes('class="no-connection compact"')) {{
          throw new Error('expected vendored send form classes to be applied on #send_form');
        }}
        '''
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_vendor_derived_preview_shell_module_drops_hand_built_topbar_and_send_form_slots():
    source = VENDOR_SHELL_MODULE_PATH.read_text(encoding='utf-8')

    for removed in [
        'topBarStaticActionsMarkup',
        'sendFormMarkup',
        'right-drawer-anchor',
        'st-preview-topbar-section',
    ]:
        assert removed not in source, f'stale shell shim remains: {removed}'


def test_vendor_derived_preview_shell_keeps_current_st_character_management_button_strip():
    node_script = textwrap.dedent(
        f'''
        import {{ pathToFileURL }} from 'node:url';
        const shellModule = await import(pathToFileURL({json.dumps(str(VENDOR_SHELL_MODULE_PATH.resolve()))}).href);
        if (typeof shellModule.buildVendorFirstPreviewShell !== 'function') {{
          throw new Error('missing buildVendorFirstPreviewShell export');
        }}
        const markup = shellModule.buildVendorFirstPreviewShell();

        for (const token of [
          'id="rightNavHolder"',
          'id="right-nav-panelheader" class="fa-solid fa-grip drag-grabber"',
          'id="rm_button_characters"',
          'id="HotSwapWrapper"',
          'class="hotswap avatars_inline scroll-reset-container expander"',
        ]) {{
          if (!markup.includes(token)) throw new Error(`missing current ST character shell token: ${{token}}`);
        }}
        '''
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_vendor_derived_preview_shell_matches_current_st_drawer_class_shape_for_right_nav_holder():
    source = (ROOT / 'static/vendor/sillytavern/preview-shell.js').read_text(encoding='utf-8')

    assert '<div id="rightNavHolder" class="drawer">' in source
    assert '<div id="unimportantYes" class="drawer-toggle drawer-header" data-panel-target="character">' in source
    assert '<nav id="right-nav-panel" class="drawer-content closedDrawer fillRight" data-panel-surface="character">' in source


def test_build_beautify_preview_document_keeps_vendor_character_strip_ids_unique_in_final_markup():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc');

        const buttonMatches = html.match(/id="rm_button_characters"/g) || [];
        const hotSwapMatches = html.match(/id="HotSwapWrapper"/g) || [];
        const pinAndTabsMatches = html.match(/id="rm_PinAndTabs"/g) || [];
        const panelTabsMatches = html.match(/id="right-nav-panel-tabs"/g) || [];
        const selectedCharacterMatches = html.match(/id="rm_button_selected_ch"/g) || [];

        if (buttonMatches.length !== 1) {
          throw new Error(`expected exactly one rm_button_characters id, got ${buttonMatches.length}`);
        }
        if (hotSwapMatches.length !== 1) {
          throw new Error(`expected exactly one HotSwapWrapper id, got ${hotSwapMatches.length}`);
        }
        if (pinAndTabsMatches.length !== 1) {
          throw new Error(`expected exactly one vendor character drawer rm_PinAndTabs id, got ${pinAndTabsMatches.length}`);
        }
        if (panelTabsMatches.length !== 1) {
          throw new Error(`expected exactly one vendor character drawer right-nav-panel-tabs id, got ${panelTabsMatches.length}`);
        }
        if (selectedCharacterMatches.length !== 1) {
          throw new Error(`expected exactly one vendor selected-character id, got ${selectedCharacterMatches.length}`);
        }
        '''
    )


def test_build_beautify_preview_scene_options_renames_system_scene_to_style_demo():
    run_preview_document_check(
        '''
        if (module.DEFAULT_PREVIEW_SCENE_ID !== 'daily') {
          throw new Error(`expected exported default preview scene id, got ${module.DEFAULT_PREVIEW_SCENE_ID}`);
        }

        if (!Array.isArray(module.PREVIEW_SCENE_OPTIONS)) {
          throw new Error('expected PREVIEW_SCENE_OPTIONS export to be an array');
        }

        const sceneIds = module.PREVIEW_SCENE_OPTIONS.map((scene) => scene.id);
        const expectedIds = ['daily', 'flirty', 'lore', 'story', 'style-demo'];
        if (JSON.stringify(sceneIds) !== JSON.stringify(expectedIds)) {
          throw new Error(`unexpected exported preview scene ids: ${JSON.stringify(sceneIds)}`);
        }

        const expectedScenes = {
          daily: { label: '日常陪伴', description: '更自然的日常多轮聊天' },
          flirty: { label: '暧昧互动', description: '更柔和的情绪和停顿' },
          lore: { label: '设定说明', description: '长段落和说明性文本' },
          story: { label: '剧情推进', description: '连续叙事与状态推进' },
          'style-demo': { label: '样式演示', description: '用于校验富文本、系统提示和代码块等样式表现' },
        };

        for (const scene of module.PREVIEW_SCENE_OPTIONS) {
          if (!scene.label || !scene.description) {
            throw new Error(`scene metadata should include label and description: ${JSON.stringify(scene)}`);
          }
          const expectedScene = expectedScenes[scene.id];
          if (!expectedScene) {
            throw new Error(`unexpected scene metadata entry: ${JSON.stringify(scene)}`);
          }
          if (scene.label !== expectedScene.label || scene.description !== expectedScene.description) {
            throw new Error(`unexpected scene metadata for ${scene.id}: ${JSON.stringify(scene)}`);
          }
        }

        if (sceneIds.includes('system')) {
          throw new Error('legacy system scene should not remain exported');
        }
        '''
    )


def test_build_beautify_preview_document_imports_vendor_drawers_through_adapter_layer():
    source = MODULE_PATH.read_text(encoding='utf-8')

    for token in [
        'vendor/sillytavern/preview-drawers.js',
        'beautifyPreviewDrawerAdapters.js',
        'buildSettingsDrawerPreviewMarkupFromVendor',
        'buildFormattingDrawerPreviewMarkupFromVendor',
        'buildCharacterDrawerPreviewMarkupFromVendor',
    ]:
        assert token in source, f'missing vendor drawer adapter token: {token}'

    for removed in [
        'function buildSettingsDrawerPreviewMarkup()',
        'function buildFormattingDrawerPreviewMarkup(',
        'function buildCharacterDrawerPreviewMarkup(',
    ]:
        assert removed not in source, f'legacy local drawer helper remains: {removed}'


def test_build_beautify_preview_document_assembles_vendor_drawers_with_st_character_row_preview():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          platform: 'pc',
          theme: {},
          identities: {
            character: {
              name: 'Preview Hero',
              avatarSrc: '/static/img/preview-hero.webp',
            },
          },
          detail: {
            packageName: 'Demo Package',
            description: 'A <b>preview</b> description',
          },
        });

        for (const token of [
          'id="amount_gen"',
          'id="sysprompt_select"',
          'id="rm_characters_block"',
          'id="character_search_bar"',
          'id="rm_print_characters_block"',
          'class="flex-container wide100pLess70px character_select_container"',
          'class="character_select"',
          'data-preview-disabled="true"',
          'data-preview-action="toggle-search"',
          'data-preview-action="toggle-grid"',
          '/static/img/preview-hero.webp',
          'Preview Hero',
          'Demo Package',
          'A &lt;b&gt;preview&lt;/b&gt; description',
        ]) {
          if (!html.includes(token)) throw new Error(`missing assembled vendor drawer token: ${token}`);
        }

        if (html.includes('data-preview-character-card="primary"')) {
          throw new Error('legacy custom preview character card should not remain in final document');
        }

        const characterPanelStart = html.indexOf('data-panel-surface="character"');
        const characterPanelEnd = html.indexOf('id="form_sheld"', characterPanelStart);
        if (characterPanelStart === -1 || characterPanelEnd === -1) {
          throw new Error('missing character drawer panel bounds in final document');
        }
        const characterPanelMarkup = html.slice(characterPanelStart, characterPanelEnd);

        for (const selector of ['id="rm_button_create"', 'id="bulkEditButton"']) {
          const match = characterPanelMarkup.match(new RegExp(`<[^>]*${selector}[^>]*>`));
          if (!match) throw new Error(`missing dangerous character control in final document: ${selector}`);
          if (!match[0].includes('data-preview-disabled="true"')) {
            throw new Error(`expected disabled dangerous character control in final document: ${selector}`);
          }
        }
        '''
    )


def test_build_beautify_preview_document_preserves_vendor_settings_first_screen_without_preview_layout_override():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc', theme: {} });

        for (const token of [
          'id="clickSlidersTips"',
          'id="labModeWarning"',
          'id="kobold_api-presets"',
          'id="amount_gen_block"',
          'id="max_context_block"',
          'id="kobold_api-settings"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing preserved settings token in final document: ${token}`);
        }

        const responseConfigurationMatch = html.match(/<[^>]*id="ai_response_configuration"[^>]*>/);
        if (!responseConfigurationMatch) {
          throw new Error('missing ai_response_configuration opening tag in final document');
        }
        if (responseConfigurationMatch[0].includes('display: flex; flex-direction: column; gap: 10px;')) {
          throw new Error(`unexpected preview-owned layout override in final document: ${responseConfigurationMatch[0]}`);
        }

        for (const hiddenSectionId of ['ai_module_block_novel', 'prompt_cost_block']) {
          const match = html.match(new RegExp(`<[^>]*id="${hiddenSectionId}"[^>]*>`));
          if (!match) throw new Error(`missing hidden section opening tag in final document: ${hiddenSectionId}`);
          if (!match[0].includes('style="display: none;"')) {
            throw new Error(`expected hidden section style in final document on ${hiddenSectionId}`);
          }
        }
        '''
    )


def test_build_vendor_first_preview_shell_accepts_full_drawer_bodies_without_owned_scrollable_wrappers():
    node_script = textwrap.dedent(
        f'''
        import {{ pathToFileURL }} from 'node:url';
        const shellModule = await import(pathToFileURL({json.dumps(str(VENDOR_SHELL_MODULE_PATH.resolve()))}).href);
        const markup = shellModule.buildVendorFirstPreviewShell({{
          settingsDrawerContentMarkup: '<section class="scrollableInner" data-slot="settings">settings body</section>',
          formattingDrawerContentMarkup: '<section class="scrollableInner" data-slot="formatting">formatting body</section>',
          characterDrawerContentMarkup: '<section class="scrollableInner" data-slot="character">character body</section>',
        }});

        const expectedBodies = [
          '<section class="scrollableInner" data-slot="settings">settings body</section>',
          '<section class="scrollableInner" data-slot="formatting">formatting body</section>',
          '<section class="scrollableInner" data-slot="character">character body</section>',
        ];

        for (const body of expectedBodies) {{
          if (!markup.includes(body)) throw new Error(`missing full drawer body fragment: ${{body}}`);
        }}

        if (markup.includes('<div class="scrollableInner"><section class="scrollableInner" data-slot="settings">')) {{
          throw new Error('settings drawer body should be inserted directly without shell-owned scrollableInner wrapper');
        }}
        if (markup.includes('<div class="scrollableInner"><section class="scrollableInner" data-slot="formatting">')) {{
          throw new Error('formatting drawer body should be inserted directly without shell-owned scrollableInner wrapper');
        }}
        if (markup.includes('<div class="scrollableInner"><section class="scrollableInner" data-slot="character">')) {{
          throw new Error('character drawer body should be inserted directly without shell-owned scrollableInner wrapper');
        }}
        '''
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_build_vendor_first_preview_shell_keeps_full_drawer_body_slots_after_fixed_anchors():
    node_script = textwrap.dedent(
        f'''
        import {{ pathToFileURL }} from 'node:url';
        const shellModule = await import(pathToFileURL({json.dumps(str(VENDOR_SHELL_MODULE_PATH.resolve()))}).href);
        const markup = shellModule.buildVendorFirstPreviewShell({{
          settingsDrawerContentMarkup: '<section data-slot="settings">settings body</section>',
          formattingDrawerContentMarkup: '<section data-slot="formatting">formatting body</section>',
          characterDrawerContentMarkup: '<section data-slot="character">character body</section>',
        }});

        const requiredOrder = [
          ['id="left-nav-panelheader"', 'id="lm_button_panel_pin_div"', 'data-slot="settings"'],
          ['id="advanced-formatting-button"', 'id="AdvancedFormatting"', 'data-slot="formatting"'],
          ['id="right-nav-panelheader"', 'id="CharListButtonAndHotSwaps"', 'data-slot="character"'],
        ];

        for (const tokens of requiredOrder) {{
          const indexes = tokens.map((token) => markup.indexOf(token));
          if (indexes.some((index) => index === -1)) {{
            throw new Error(`missing required drawer slot anchor: ${{JSON.stringify(tokens)}}`);
          }}
          if (!(indexes[0] < indexes[1] && indexes[1] < indexes[2])) {{
            throw new Error(`expected fixed anchors before inserted drawer body: ${{JSON.stringify(tokens)}}`);
          }}
        }}
        '''
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_build_beautify_preview_document_uses_vendored_shell_without_preview_scene_switcher_markup():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc', theme: {} });

        for (const token of [
          'id="bg1"',
          'id="top-bar"',
          'id="top-settings-holder"',
          'id="leftNavDrawerIcon"',
          'id="left-nav-panel"',
          'id="rightNavDrawerIcon"',
          'id="right-nav-panel"',
          'id="sheld"',
          'id="chat"',
          'id="form_sheld"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing vendored shell anchor: ${token}`);
        }

        for (const forbidden of [
          'st-preview-scene-switcher',
          'data-preview-scene-button',
          'data-preview-scene-description',
        ]) {
          if (html.includes(forbidden)) throw new Error(`scene switcher must stay outside isolated ST frame: ${forbidden}`);
        }
        '''
    )


def test_build_beautify_preview_document_keeps_real_drawer_relationships_for_core_drawers():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc', theme: {} });

        const requiredPairs = [
          ['leftNavDrawerIcon', 'left-nav-panel'],
          ['rightNavDrawerIcon', 'right-nav-panel'],
        ];

        for (const [iconId, panelId] of requiredPairs) {
          const iconIndex = html.indexOf(`id="${iconId}"`);
          const panelIndex = html.indexOf(`id="${panelId}"`);
          if (iconIndex === -1 || panelIndex === -1) throw new Error(`missing drawer pair ${iconId}/${panelId}`);
          if (iconIndex > panelIndex) throw new Error(`expected icon ${iconId} before panel ${panelId} in vendored shell structure`);
        }
        '''
    )


def test_build_beautify_preview_document_uses_explicit_identity_names_and_avatar_urls():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          platform: 'pc',
          theme: {},
          wallpaperUrl: '',
          identities: {
            character: { name: '包角色', avatarSrc: '/api/beautify/preview-asset/packages/pkg_demo/avatars/character.png' },
            user: { name: '访客', avatarSrc: '/api/beautify/preview-asset/global/avatars/user.png' },
          },
        });

        if (!html.includes('包角色')) throw new Error('missing package character name');
        if (!html.includes('访客')) throw new Error('missing user name');
        if (!html.includes('/api/beautify/preview-asset/packages/pkg_demo/avatars/character.png')) throw new Error('missing character avatar src');
        if (!html.includes('/api/beautify/preview-asset/global/avatars/user.png')) throw new Error('missing user avatar src');
        '''
    )


def test_build_beautify_preview_document_uses_builtin_identity_defaults_when_none_resolved():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          platform: 'pc',
          theme: {},
          wallpaperUrl: '',
          identities: {
            character: { name: '', avatarSrc: '' },
            user: { name: '', avatarSrc: '' },
          },
        });

        if (!html.includes('苏眠')) throw new Error('missing built-in character fallback');
        if (!html.includes('凌砚')) throw new Error('missing built-in user fallback');
        if (!html.includes('/static/images/beautify-preview/sumian.png')) throw new Error('missing built-in character avatar fallback');
        if (!html.includes('/static/images/beautify-preview/lingyan.png')) throw new Error('missing built-in user avatar fallback');
        '''
    )


def test_build_beautify_preview_document_preserves_theme_variables_and_platform_markers():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          theme: {
            main_text_color: '#f8fafc',
            italics_text_color: '#c084fc',
            underline_text_color: '#22d3ee',
            quote_text_color: '#f59e0b',
            blur_tint_color: 'rgba(15, 23, 42, 0.48)',
            chat_tint_color: 'rgba(15, 23, 42, 0.52)',
            user_mes_blur_tint_color: 'rgba(59, 130, 246, 0.22)',
            bot_mes_blur_tint_color: 'rgba(15, 23, 42, 0.58)',
            shadow_color: 'rgba(15, 23, 42, 0.35)',
            border_color: 'rgba(148, 163, 184, 0.24)',
            font_scale: 1.1,
            blur_strength: 12,
            shadow_width: 3,
            chat_width: 55,
            timer_enabled: false,
            timestamps_enabled: false,
            message_token_count_enabled: false,
            mesIDDisplay_enabled: false,
            hideChatAvatars_enabled: true,
            avatar_style: 3,
            chat_display: 1,
            compact_input_area: true,
          },
          wallpaperUrl: '/api/beautify/preview-asset/demo.png',
          platform: 'mobile',
        });

        for (const token of [
          '--SmartThemeBodyColor:#f8fafc',
          '--SmartThemeEmColor:#c084fc',
          '--SmartThemeUnderlineColor:#22d3ee',
          '--SmartThemeQuoteColor:#f59e0b',
          '--SmartThemeBlurTintColor:rgba(15, 23, 42, 0.48)',
          '--SmartThemeChatTintColor:rgba(15, 23, 42, 0.52)',
          '--SmartThemeUserMesBlurTintColor:rgba(59, 130, 246, 0.22)',
          '--SmartThemeBotMesBlurTintColor:rgba(15, 23, 42, 0.58)',
          '--SmartThemeShadowColor:rgba(15, 23, 42, 0.35)',
          '--SmartThemeBorderColor:rgba(148, 163, 184, 0.24)',
          '--fontScale:1.1',
          '--blurStrength:12px',
          '--shadowWidth:3px',
          '--SmartThemeBlurStrength:var(--blurStrength)',
          '--mainFontSize:calc(var(--fontScale) * 16px)',
          '--wallpaperUrl:url("/api/beautify/preview-asset/demo.png")',
          '<title>Beautify Native ST Preview</title>',
          '<body data-st-preview-platform="mobile" class="no-timer no-timestamps no-tokenCount no-mesIDDisplay hideChatAvatars rounded-avatars bubblechat">',
          '<div id="send_form" class="no-connection compact">',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }
        '''
    )


def test_build_beautify_preview_theme_vars_normalizes_and_clamps_theme_inputs():
    run_preview_document_check(
        '''
        const vars = module.buildBeautifyPreviewThemeVars({
          font_scale: 'bad-value',
          blur_strength: -4,
          shadow_width: -2,
          chat_width: 300,
        }, '');

        if (vars['--fontScale'] !== '1') throw new Error(`expected normalized fontScale, got ${vars['--fontScale']}`);
        if (vars['--blurStrength'] !== '0px') throw new Error(`expected clamped blurStrength, got ${vars['--blurStrength']}`);
        if (vars['--shadowWidth'] !== '0px') throw new Error(`expected clamped shadowWidth, got ${vars['--shadowWidth']}`);
        if (vars['--SmartThemeBlurStrength'] !== 'var(--blurStrength)') throw new Error(`expected derived SmartThemeBlurStrength, got ${vars['--SmartThemeBlurStrength']}`);
        if ('--sheldWidth' in vars) throw new Error('preview theme vars should no longer expose sheld width');
        '''
    )


def test_build_beautify_preview_theme_vars_derives_preview_shell_width_from_chat_width():
    run_preview_document_check(
        '''
        const pcVars = module.buildBeautifyPreviewThemeVars({ chat_width: 50 }, '', 'pc');
        const clampedPcVars = module.buildBeautifyPreviewThemeVars({ chat_width: 300 }, '', 'pc');
        const lowPcVars = module.buildBeautifyPreviewThemeVars({ chat_width: 0 }, '', 'pc');
        const negativePcVars = module.buildBeautifyPreviewThemeVars({ chat_width: -5 }, '', 'pc');
        const mobileVars = module.buildBeautifyPreviewThemeVars({ chat_width: 50 }, '', 'mobile');

        if (pcVars['--stPreviewShellWidth'] !== '50vw') {
          throw new Error(`expected pc preview shell width from chat_width, got ${pcVars['--stPreviewShellWidth']}`);
        }
        if (clampedPcVars['--stPreviewShellWidth'] !== '100vw') {
          throw new Error(`expected clamped pc preview shell width, got ${clampedPcVars['--stPreviewShellWidth']}`);
        }
        if (lowPcVars['--stPreviewShellWidth'] !== '25vw') {
          throw new Error(`expected low pc preview shell width to clamp to ST minimum, got ${lowPcVars['--stPreviewShellWidth']}`);
        }
        if (negativePcVars['--stPreviewShellWidth'] !== '25vw') {
          throw new Error(`expected negative pc preview shell width to clamp to ST minimum, got ${negativePcVars['--stPreviewShellWidth']}`);
        }
        if (mobileVars['--stPreviewShellWidth'] !== '100%') {
          throw new Error(`expected mobile preview shell width to stay full width, got ${mobileVars['--stPreviewShellWidth']}`);
        }
        if ('--sheldWidth' in pcVars) throw new Error('preview theme vars should not expose raw sheld width');
        '''
    )


def test_build_beautify_preview_document_reasserts_preview_shell_width_after_package_custom_css():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          platform: 'pc',
          theme: {
            chat_width: 50,
            custom_css: ':root { --sheldWidth: 90%; }',
          },
        });

        if (!html.includes('--stPreviewShellWidth:50vw')) {
          throw new Error('missing derived preview shell width variable');
        }
        if (!html.includes('<style>:root{--sheldWidth:var(--stPreviewShellWidth);}</style>')) {
          throw new Error('missing final sheld width reassertion');
        }
        if (!html.includes('<style>:root { --sheldWidth: 90%; }</style><style>:root{--sheldWidth:var(--stPreviewShellWidth);}</style>')) {
          throw new Error('expected final sheld width reassertion after package custom css');
        }
        '''
    )


def test_build_beautify_preview_document_escapes_css_sensitive_content():
    run_preview_document_check(
        r'''
        const wallpaper = String.raw`https://example.com/a") ;background:red;/*\\unsafe`;
        const escapedCustomClose = String.raw`<\/style><script>window.BAD=1</script>`;
        const escapedThemeValue = String.raw`--SmartThemeBodyColor:<\/style><script>window.BAD_THEME=1</script><style>;`;
        const escapedWallpaperSuffix = String.raw`/*\\\\unsafe")`;
        const html = module.buildBeautifyPreviewDocument({
          theme: {
            custom_css: 'body::before{content:"</style><script>window.BAD=1</script>";}',
            main_text_color: '</style><script>window.BAD_THEME=1</script><style>',
          },
          wallpaperUrl: wallpaper,
          platform: 'mobile',
        });

        if (html.includes('</style><script>window.BAD=1</script>')) throw new Error('custom css escaped unsafely');
        if (html.includes('</style><script>window.BAD_THEME=1</script><style>')) throw new Error('theme variable escaped unsafely');
        if (!html.includes(escapedCustomClose)) throw new Error('custom css escape marker missing');
        if (!html.includes(escapedThemeValue)) throw new Error('theme variable escape marker missing');

        const wallpaperUrlValue = module.buildBeautifyPreviewThemeVars({}, wallpaper)['--wallpaperUrl'];
        if (!html.includes(`--wallpaperUrl:${wallpaperUrlValue}`)) throw new Error('wallpaper css variable missing');
        if (!wallpaperUrlValue.includes('\\"')) throw new Error('wallpaper quote was not escaped');
        if (!wallpaperUrlValue.endsWith(escapedWallpaperSuffix)) throw new Error('wallpaper backslash was not escaped');
        '''
    )


def test_build_beautify_preview_document_blocks_external_theme_resource_loads_with_csp():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          theme: {
            custom_css: '@import url("https://fontsapi.zeoseven.com/437/main/result.css"); #chat { background-image: url("https://iili.io/qs8cjZN.png"); }',
          },
          platform: 'pc',
        });

        for (const token of [
          '<meta http-equiv="Content-Security-Policy"',
          "default-src 'none'",
          "script-src 'unsafe-inline'",
          "style-src 'self' 'unsafe-inline' http://127.0.0.1:5000 https://127.0.0.1:5000",
          "font-src 'self' data: blob: http://127.0.0.1:5000 https://127.0.0.1:5000",
          "img-src 'self' data: blob: http://127.0.0.1:5000 https://127.0.0.1:5000 http: https:",
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }
        '''
    )


def test_build_beautify_preview_document_strips_remote_theme_imports_but_keeps_remote_background_images():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          theme: {
            custom_css: '@import url("https://fontsapi.zeoseven.com/437/main/result.css"); #chat { background-image: url("https://iili.io/qs8cjZN.png"); color: rgb(1, 2, 3); } .mes { background-image: url("/static/vendor/sillytavern/img/down-arrow.svg"); }',
          },
          platform: 'pc',
        });

        for (const token of [
          'color: rgb(1, 2, 3);',
          'url("https://iili.io/qs8cjZN.png")',
          'url("/static/vendor/sillytavern/img/down-arrow.svg")',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        for (const token of [
          '@import url("https://fontsapi.zeoseven.com/437/main/result.css")',
        ]) {
          if (html.includes(token)) throw new Error(`unexpected remote resource token: ${token}`);
        }
        '''
    )


def test_build_beautify_preview_document_strips_protocol_relative_and_layered_remote_imports():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          theme: {
            custom_css: '@import "//example.com/base.css"; @import url(https://example.com/layered.css) layer(theme); #chat { color: rgb(1, 2, 3); }',
          },
          platform: 'pc',
        });

        if (!html.includes('color: rgb(1, 2, 3);')) throw new Error('expected local css to remain');
        if (html.includes('@import "//example.com/base.css"')) throw new Error('protocol-relative import should be stripped');
        if (html.includes('@import url(https://example.com/layered.css) layer(theme)')) throw new Error('layered remote import should be stripped');
        '''
    )


def test_build_beautify_preview_sample_markup_contains_vendor_first_shell_surfaces():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc', {}, {}, 'style-demo');

        for (const token of [
          'id="bg1"',
          'id="top-bar"',
          'id="top-settings-holder"',
          'id="ai-config-button"',
          'id="left-nav-panel"',
          'id="AdvancedFormatting"',
          'id="right-nav-panel"',
          'id="sheld"',
          'id="sheldheader"',
          'id="chat"',
          'class="mesAvatarWrapper"',
          'class="mes_buttons"',
          'class="mes_reasoning_summary"',
          'id="form_sheld"',
          'id="send_form"',
          'id="leftSendForm"',
          'id="rightSendForm"',
          'id="send_textarea"',
          'id="send_but"',
          'id="sys-settings-button"',
          'id="WI-SP-button"',
          'id="user-settings-button"',
          'id="backgrounds-button"',
          'id="extensions-settings-button"',
          'id="persona-management-button"',
          'data-panel-target="settings"',
          'data-panel-target="formatting"',
          'data-panel-target="character"',
          'data-panel-surface="settings"',
          'data-panel-surface="formatting"',
          'data-panel-surface="character"',
          'class="drawer-toggle drawer-header" data-panel-target="settings"',
          'class="drawer-toggle" data-panel-target="formatting"',
          'class="drawer-toggle drawer-header" data-panel-target="character"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        for (const forbidden of [
          'data-preview-static-action=',
          'st-preview-topbar-action',
        ]) {
          if (html.includes(forbidden)) throw new Error(`unexpected legacy surrogate topbar token: ${forbidden}`);
        }

        const sheldIndex = html.indexOf('id="sheld"');
        const sheldHeaderIndex = html.indexOf('id="sheldheader"');
        const chatIndex = html.indexOf('id="chat"');
        const formSheldIndex = html.indexOf('id="form_sheld"');
        const topBarIndex = html.indexOf('id="top-bar"');
        const topSettingsHolderIndex = html.indexOf('id="top-settings-holder"');

        if (!(sheldIndex < sheldHeaderIndex && sheldHeaderIndex < chatIndex && chatIndex < formSheldIndex)) {
          throw new Error('preview #sheld should contain #sheldheader before #chat and #form_sheld');
        }

        if (!(topBarIndex < topSettingsHolderIndex && topSettingsHolderIndex < sheldIndex)) {
          throw new Error('toolbar shell should render before the simulated #sheld frame');
        }

        for (const token of [
          'id="sheldheader" class="fa-solid fa-grip drag-grabber"',
          '<div id="sheld">',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        if (html.indexOf('id="chat"') > html.indexOf('id="form_sheld"')) {
          throw new Error('chat should render before the send form shell');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_contains_st_send_form_scaffolding():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc');

        for (const token of [
          'id="dialogue_del_mes"',
          'id="dialogue_del_mes_ok"',
          'id="dialogue_del_mes_cancel"',
          'id="file_form" class="wide100p displayNone"',
          'id="file_form_input" type="file" multiple hidden',
          'id="embed_file_input" type="file" multiple hidden',
          'class="file_attached"',
          'class="file_name"',
          'class="file_size"',
          'id="file_form_reset" type="reset" class="menu_button"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        const formSheldIndex = html.indexOf('id="form_sheld"');
        const dialogueIndex = html.indexOf('id="dialogue_del_mes"');
        const sendFormIndex = html.indexOf('id="send_form"');
        const fileFormIndex = html.indexOf('id="file_form"');
        const nonQrIndex = html.indexOf('id="nonQRFormItems"');

        if (!(formSheldIndex < dialogueIndex && dialogueIndex < sendFormIndex && sendFormIndex < fileFormIndex && fileFormIndex < nonQrIndex)) {
          throw new Error('preview send-form scaffold should match ST ordering under #form_sheld');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_contains_st_right_send_form_actions():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc');

        for (const token of [
          'id="rightSendForm" class="alignContentCenter"',
          'id="stscript_continue" title="Continue script execution" class="stscript_btn stscript_continue"',
          'id="stscript_pause" title="Pause script execution" class="stscript_btn stscript_pause"',
          'id="stscript_stop" title="Abort script execution" class="stscript_btn stscript_stop"',
          'id="mes_stop" title="Abort request" class="mes_stop"',
          'id="mes_impersonate" class="fa-solid fa-user-secret interactable displayNone"',
          'id="mes_continue" class="fa-fw fa-solid fa-arrow-right interactable displayNone"',
          'id="send_but" class="fa-solid fa-paper-plane interactable"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        const rightSendFormIndex = html.indexOf('id="rightSendForm"');
        const continueScriptIndex = html.indexOf('id="stscript_continue"');
        const pauseScriptIndex = html.indexOf('id="stscript_pause"');
        const stopScriptIndex = html.indexOf('id="stscript_stop"');
        const mesStopIndex = html.indexOf('id="mes_stop"');
        const impersonateIndex = html.indexOf('id="mes_impersonate"');
        const continueIndex = html.indexOf('id="mes_continue"');
        const sendButIndex = html.indexOf('id="send_but"');

        if (!(rightSendFormIndex < continueScriptIndex && continueScriptIndex < pauseScriptIndex && pauseScriptIndex < stopScriptIndex && stopScriptIndex < mesStopIndex && mesStopIndex < impersonateIndex && impersonateIndex < continueIndex && continueIndex < sendButIndex)) {
          throw new Error('preview right send-form actions should follow ST ordering');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_contains_scene_switcher_and_default_scene():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc', {}, {}, 'flirty');

        for (const token of [
          'data-active-scene="flirty"',
          'ch_name="苏眠"',
          'mesid="1"',
          'mesid="2"',
          '你刚刚那句“只看一眼消息”听起来，可不像真的只看一眼。',
          '被你发现了。我本来只是想确认你睡了没。',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        for (const forbidden of [
          'data-preview-scene-switcher',
          'data-preview-scene-button=',
          'data-preview-default-scene=',
          'data-preview-chat-messages',
          'data-preview-scene-template=',
          '日常陪伴',
          '设定说明',
          '剧情推进',
          '样式演示',
        ]) {
          if (html.includes(forbidden)) throw new Error(`unexpected in-frame scene-switcher token: ${forbidden}`);
        }
        '''
    )


def test_build_beautify_preview_sample_markup_keeps_preview_link_as_marked_real_anchor():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc', {}, {}, 'style-demo');

        if (!html.includes('data-preview-link="disabled"')) throw new Error('missing marked preview link');
        if (html.includes('<a role="link" aria-disabled="true">')) throw new Error('preview link should not use fake link semantics');
        if (!html.includes('<a href="#" data-preview-link="disabled">')) throw new Error('preview link should remain a real anchor with a preview disable marker');
        '''
    )


def test_build_beautify_preview_sample_markup_moves_rich_text_showcase_out_of_daily_scene():
    run_preview_document_check(
        '''
        const dailyHtml = module.buildBeautifyPreviewSampleMarkup('pc');
        const styleDemoHtml = module.buildBeautifyPreviewSampleMarkup('pc', {}, {}, 'style-demo');

        for (const token of [
          '<strong>粗体</strong>',
          '<em>斜体</em>',
          '<u>下划线</u>',
          '<code>inline code</code>',
          '<pre><code>',
        ]) {
          if (dailyHtml.includes(token)) throw new Error(`daily scene should not include rich-text showcase token: ${token}`);
          if (!styleDemoHtml.includes(token)) throw new Error(`style-demo scene missing showcase token: ${token}`);
        }

        if (!dailyHtml.includes('日常陪伴预览：观察更自然的多轮来回节奏。')) {
          throw new Error('daily scene should keep the new daily preview system message');
        }
        if (!styleDemoHtml.includes('样式演示场景：集中观察富文本、系统提示和代码样式。')) {
          throw new Error('style-demo scene should include its system message');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_mobile_code_sample_reflects_mobile_platform():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('mobile', {}, {}, 'style-demo');

        if (!html.includes("platform: 'mobile'")) throw new Error('missing mobile platform code sample');
        if (html.includes("platform: 'pc'")) throw new Error('mobile preview should not hard-code pc platform sample');
        '''
    )


def test_build_beautify_preview_document_uses_scene_aware_context_story_string_copy():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          platform: 'pc',
          theme: {},
          wallpaperUrl: '',
          activeScene: 'style-demo',
        });

        const expectedPrompt = '样式演示专用：集中展示粗体、斜体、引用、列表、链接、行内代码、代码块和系统提示样式。';
        if (!html.includes('id="context_story_string"')) {
          throw new Error('missing formatting drawer context story textarea');
        }
        if (!html.includes(expectedPrompt)) {
          throw new Error('missing style-demo scene-aware context story copy');
        }
        if (html.includes('{{system}}')) {
          throw new Error('legacy generic context story placeholder should not remain');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_keeps_example_link_as_marked_real_anchor():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc', {}, {}, 'style-demo');

        if (!html.includes('Example link')) throw new Error('missing example link text');
        if (html.includes('<a role="link" aria-disabled="true">Example link</a>')) throw new Error('example link should not use fake link semantics');
        if (!html.includes('<a href="#" data-preview-link="disabled">Example link</a>')) throw new Error('example link should remain a real anchor with a preview disable marker');
        '''
    )


def test_build_beautify_preview_document_disables_navigation_for_marked_example_link():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          platform: 'pc',
          theme: {},
          wallpaperUrl: '',
        });

        const scriptMatch = html.match(/<script>([\s\S]*)<\/script>/);
        if (!scriptMatch) throw new Error('missing preview behavior script');

        let clickHandler = null;
        let unmarkedClickHandler = null;
        let preventDefaultCalls = 0;
        let loadHandler = null;
        const root = { dataset: { activePanel: 'none' } };
        const chat = { scrollTop: 0, scrollHeight: 42 };
        const previewLink = {
          addEventListener(type, handler) {
            if (type === 'click') {
              clickHandler = handler;
            }
          },
        };
        const unmarkedLink = {
          addEventListener(type, handler) {
            if (type === 'click') {
              unmarkedClickHandler = handler;
            }
          },
        };

        const document = {
          querySelector(selector) {
            if (selector === '.st-preview-root') return root;
            if (selector === '#chat') return chat;
            return null;
          },
          querySelectorAll(selector) {
            if (selector === '[data-preview-link="disabled"]') return [previewLink];
            if (selector === 'a') return [previewLink, unmarkedLink];
            return [];
          },
        };

        const window = {
          requestAnimationFrame(callback) {
            callback();
          },
          addEventListener(type, handler) {
            if (type === 'load') {
              loadHandler = handler;
            }
          },
        };

        class CustomEvent {
          constructor(type, options = {}) {
            this.type = type;
            this.bubbles = Boolean(options.bubbles);
          }
        }

        const runScript = new Function('document', 'window', 'CustomEvent', scriptMatch[1]);
        runScript(document, window, CustomEvent);

        if (typeof clickHandler !== 'function') throw new Error('marked example link did not receive a click handler');
        if (unmarkedClickHandler !== null) throw new Error('unmarked anchor should not receive preview link interception');
        if (typeof loadHandler !== 'function') throw new Error('preview script did not bind its load handler');
        if (chat.scrollTop !== chat.scrollHeight) throw new Error('preview script did not run initial chat scroll');

        const event = {
          defaultPrevented: false,
          preventDefault() {
            this.defaultPrevented = true;
            preventDefaultCalls += 1;
          },
        };

        clickHandler(event);

        if (!event.defaultPrevented) throw new Error('marked example link click was not prevented');
        if (preventDefaultCalls !== 1) throw new Error(`expected one preventDefault call, got ${preventDefaultCalls}`);
        '''
    )


def test_build_beautify_preview_document_runtime_supports_st_character_list_home_controls():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc', theme: {} });

        const scriptMatch = html.match(/<script>([\s\S]*)<\/script>/);
        if (!scriptMatch) throw new Error('missing preview behavior script');

        function createClassList(initial = []) {
          const set = new Set(initial);
          return {
            add(...tokens) {
              tokens.forEach((token) => set.add(token));
            },
            remove(...tokens) {
              tokens.forEach((token) => set.delete(token));
            },
            toggle(token, force) {
              if (force === undefined) {
                if (set.has(token)) {
                  set.delete(token);
                  return false;
                }
                set.add(token);
                return true;
              }
              if (force) {
                set.add(token);
                return true;
              }
              set.delete(token);
              return false;
            },
            contains(token) {
              return set.has(token);
            },
          };
        }

        function createClickableNode(dataset = {}) {
          return {
            dataset,
            handler: null,
            addEventListener(type, handler) {
              if (type === 'click') {
                this.handler = handler;
              }
            },
          };
        }

        const body = { classList: createClassList() };
        const root = { dataset: { activePanel: 'none' } };
        const chat = { scrollTop: 0, scrollHeight: 30 };
        const searchForm = { style: { display: 'none' } };
        const listBlock = { style: { display: 'block' }, classList: createClassList() };
        const toggleSearch = createClickableNode({ previewAction: 'toggle-search' });
        const toggleGrid = createClickableNode({ previewAction: 'toggle-grid' });
        const queriedSelectors = [];

        const document = {
          body,
          querySelector(selector) {
            if (selector === '.st-preview-root') return root;
            if (selector === '#chat') return chat;
            if (selector === '#form_character_search_form') return searchForm;
            if (selector === '#rm_print_characters_block') return listBlock;
            return null;
          },
          querySelectorAll(selector) {
            queriedSelectors.push(selector);
            if (selector === '[data-panel-target]' || selector === '.inline-drawer' || selector === '[data-preview-link="disabled"]' || selector === '[data-preview-disabled="true"]') {
              return [];
            }
            if (selector === '.drawer-content[data-panel-surface]') {
              return [];
            }
            if (selector === '[data-preview-action="toggle-search"]') {
              return [toggleSearch];
            }
            if (selector === '[data-preview-action="toggle-grid"]') {
              return [toggleGrid];
            }
            if (selector === '[data-preview-action="show-detail"]') {
              throw new Error('show-detail should not be queried');
            }
            if (selector === '[data-preview-action="show-list"]') {
              throw new Error('show-list should not be queried');
            }
            return [];
          },
        };

        const window = {
          requestAnimationFrame(callback) {
            callback();
          },
          addEventListener() {},
        };

        class CustomEvent {
          constructor(type, options = {}) {
            this.type = type;
            this.bubbles = Boolean(options.bubbles);
          }
        }

        const runScript = new Function('document', 'window', 'CustomEvent', scriptMatch[1]);
        runScript(document, window, CustomEvent);

        if (typeof toggleSearch.handler !== 'function') throw new Error('missing toggle-search click binding');
        if (typeof toggleGrid.handler !== 'function') throw new Error('missing toggle-grid click binding');
        if (!queriedSelectors.includes('[data-preview-action="toggle-search"]')) throw new Error('toggle-search selector was not queried');
        if (!queriedSelectors.includes('[data-preview-action="toggle-grid"]')) throw new Error('toggle-grid selector was not queried');

        toggleSearch.handler({ preventDefault() {} });
        if (searchForm.style.display !== 'block') throw new Error(`toggle-search should show search form, got ${searchForm.style.display}`);

        toggleSearch.handler({ preventDefault() {} });
        if (searchForm.style.display !== 'none') throw new Error(`toggle-search should hide search form, got ${searchForm.style.display}`);

        toggleGrid.handler({ preventDefault() {} });
        if (!body.classList.contains('charListGrid')) throw new Error('toggle-grid should enable body.charListGrid');
        if (listBlock.classList.contains('is-grid-view')) throw new Error('toggle-grid should not rely on legacy is-grid-view state');

        toggleGrid.handler({ preventDefault() {} });
        if (body.classList.contains('charListGrid')) throw new Error('toggle-grid should disable body.charListGrid');
        '''
    )


def test_build_beautify_preview_document_runtime_prevents_preview_disabled_actions():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc', theme: {} });

        const scriptMatch = html.match(/<script>([\s\S]*)<\/script>/);
        if (!scriptMatch) throw new Error('missing preview behavior script');

        let disabledHandler = null;
        const root = { dataset: { activePanel: 'none' } };
        const chat = { scrollTop: 0, scrollHeight: 12 };
        const disabledAction = {
          addEventListener(type, handler) {
            if (type === 'click') {
              disabledHandler = handler;
            }
          },
        };

        const document = {
          querySelector(selector) {
            if (selector === '.st-preview-root') return root;
            if (selector === '#chat') return chat;
            return null;
          },
          querySelectorAll(selector) {
            if (selector === '[data-preview-disabled="true"]') return [disabledAction];
            if (
              selector === '[data-panel-target]' ||
              selector === '.drawer-content[data-panel-surface]' ||
              selector === '.inline-drawer' ||
              selector === '[data-preview-link="disabled"]' ||
              selector === '[data-preview-action="toggle-search"]' ||
              selector === '[data-preview-action="toggle-grid"]' ||
              selector === '[data-preview-action="show-detail"]' ||
              selector === '[data-preview-action="show-list"]'
            ) {
              return [];
            }
            return [];
          },
        };

        const window = {
          requestAnimationFrame(callback) {
            callback();
          },
          addEventListener() {},
        };

        class CustomEvent {
          constructor(type, options = {}) {
            this.type = type;
            this.bubbles = Boolean(options.bubbles);
          }
        }

        const runScript = new Function('document', 'window', 'CustomEvent', scriptMatch[1]);
        runScript(document, window, CustomEvent);

        if (typeof disabledHandler !== 'function') throw new Error('missing preview-disabled click binding');

        let preventDefaultCalls = 0;
        let stopPropagationCalls = 0;
        const event = {
          preventDefault() {
            preventDefaultCalls += 1;
          },
          stopPropagation() {
            stopPropagationCalls += 1;
          },
        };

        disabledHandler(event);

        if (preventDefaultCalls !== 1) throw new Error(`expected one preventDefault call, got ${preventDefaultCalls}`);
        if (stopPropagationCalls !== 1) throw new Error(`expected one stopPropagation call, got ${stopPropagationCalls}`);
        '''
    )


def test_build_beautify_preview_document_uses_host_owned_active_scene_for_initial_message_render():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({
          platform: 'pc',
          theme: {},
          wallpaperUrl: '',
          activeScene: 'flirty',
        });

        for (const token of [
          'data-active-scene="flirty"',
          'ch_name="苏眠"',
          'mesid="1"',
          'mesid="2"',
          '你刚刚那句“只看一眼消息”听起来，可不像真的只看一眼。',
          '被你发现了。我本来只是想确认你睡了没。',
        ]) {
          if (!html.includes(token)) throw new Error(`missing host-owned active scene token: ${token}`);
        }

        for (const forbidden of [
          'data-preview-scene-button=',
          'data-preview-scene-template=',
          '更自然的日常多轮聊天',
          '日常节奏不需要铺满屏幕，留一些安静给角色的呼吸。',
        ]) {
          if (html.includes(forbidden)) throw new Error(`unexpected in-frame runtime scene token: ${forbidden}`);
        }
        '''
    )


def test_build_beautify_preview_sample_markup_contains_st_send_form_and_textarea_attributes():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc');

        for (const token of [
          'id="send_form" class="no-connection"',
          'id="send_textarea" name="text" class="mdHotkeys"',
          'placeholder="Not connected to API!"',
          'no_connection_text="Not connected to API!"',
          'connected_text="Type a message, or /? for help"',
          'autocomplete="off"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        if (html.includes('data-i18n="[no_connection_text]Not connected to API!;[connected_text]Type a message, or /? for help"')) {
          throw new Error('preview send textarea should follow vendored shell attributes instead of legacy hand-built i18n scaffolding');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_keeps_extensions_button_and_visible_send_button_in_send_form():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc');

        for (const token of [
          'id="leftSendForm" class="alignContentCenter"',
          'id="extensionsMenuButton"',
          'class="fa-solid fa-magic-wand-sparkles interactable"',
          'title="Extensions"',
          'id="send_but" class="fa-solid fa-paper-plane interactable"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        if (html.includes('id="send_but" class="fa-solid fa-paper-plane interactable displayNone"')) {
          throw new Error('preview send button should be visible in the isolated shell');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_contains_st_message_edit_controls():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc');

        for (const token of [
          'class="mes_edit_buttons"',
          'class="mes_edit_done menu_button fa-solid fa-check"',
          'class="mes_edit_copy menu_button fa-solid fa-copy"',
          'class="mes_edit_add_reasoning menu_button fa-solid fa-lightbulb"',
          'class="mes_edit_delete menu_button fa-solid fa-trash-can"',
          'class="mes_edit_up menu_button fa-solid fa-chevron-up"',
          'class="mes_edit_down menu_button fa-solid fa-chevron-down"',
          'class="mes_edit_cancel menu_button fa-solid fa-xmark"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        const editButtonsIndex = html.indexOf('class="mes_edit_buttons"');
        const doneIndex = html.indexOf('class="mes_edit_done menu_button fa-solid fa-check"');
        const copyIndex = html.indexOf('class="mes_edit_copy menu_button fa-solid fa-copy"');
        const reasoningIndex = html.indexOf('class="mes_edit_add_reasoning menu_button fa-solid fa-lightbulb"');
        const deleteIndex = html.indexOf('class="mes_edit_delete menu_button fa-solid fa-trash-can"');
        const upIndex = html.indexOf('class="mes_edit_up menu_button fa-solid fa-chevron-up"');
        const downIndex = html.indexOf('class="mes_edit_down menu_button fa-solid fa-chevron-down"');
        const cancelIndex = html.indexOf('class="mes_edit_cancel menu_button fa-solid fa-xmark"');

        if (!(editButtonsIndex < doneIndex && doneIndex < copyIndex && copyIndex < reasoningIndex && reasoningIndex < deleteIndex && deleteIndex < upIndex && upIndex < downIndex && downIndex < cancelIndex)) {
          throw new Error('preview message edit controls should follow ST ordering');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_separates_timestamp_from_generation_timer():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc');

        const messageStart = html.indexOf('mesid="2"');
        const nextMessageStart = html.indexOf('mesid="3"', messageStart);
        const messageHtml = html.slice(messageStart, nextMessageStart === -1 ? undefined : nextMessageStart);

        if (!messageHtml.includes('<small class="timestamp">2026年4月27日 20:11</small>')) {
          throw new Error('expected full timestamp in visible timestamp slot');
        }
        if (!messageHtml.includes('<div class="mes_timer"></div>')) {
          throw new Error('expected empty mes_timer slot for static preview scene');
        }
        if (messageHtml.includes('<div class="mes_timer">2026年4月27日 20:11</div>')) {
          throw new Error('preview should not mirror timestamp into mes_timer');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_keeps_non_system_messages_from_showing_mes_ghost():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc');

        const characterStart = html.indexOf('mesid="2"');
        const userStart = html.indexOf('mesid="3"', characterStart);
        const characterHtml = html.slice(characterStart, userStart === -1 ? undefined : userStart);

        if (!characterHtml.includes('class="mes_ghost fa-solid fa-ghost"')) {
          throw new Error('expected ST ghost node to remain in the DOM');
        }
        if (!characterHtml.includes('is_system="false"')) {
          throw new Error('expected character message to stay non-system');
        }
        if (!characterHtml.includes('class="mes_button extraMesButtonsHint fa-solid fa-ellipsis"')) {
          throw new Error('expected visible ellipsis action');
        }
        if (!characterHtml.includes('class="mes_button mes_edit fa-solid fa-pencil"')) {
          throw new Error('expected visible edit action');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_uses_full_date_time_seed_values_for_character_messages():
    run_preview_document_check(
        '''
        const sceneMarkup = {
          daily: module.buildBeautifyPreviewSampleMarkup('pc'),
          flirty: module.buildBeautifyPreviewSampleMarkup('pc', {}, {}, 'flirty'),
          lore: module.buildBeautifyPreviewSampleMarkup('pc', {}, {}, 'lore'),
          story: module.buildBeautifyPreviewSampleMarkup('pc', {}, {}, 'story'),
          styleDemo: module.buildBeautifyPreviewSampleMarkup('pc', {}, {}, 'style-demo'),
        };

        for (const [sceneId, token] of [
          ['daily', '2026年4月27日 20:11'],
          ['daily', '2026年4月27日 20:12'],
          ['daily', '2026年4月27日 20:13'],
          ['flirty', '2026年4月27日 22:06'],
          ['lore', '2026年4月27日 19:25'],
          ['story', '2026年4月27日 23:11'],
          ['styleDemo', '2026年4月27日 21:40'],
          ['styleDemo', '2026年4月27日 21:41'],
        ]) {
          if (!sceneMarkup[sceneId].includes(token)) throw new Error(`missing full timestamp seed in ${sceneId}: ${token}`);
        }
        '''
    )


def test_build_beautify_preview_sample_markup_contains_st_reasoning_controls():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc', {}, {}, 'style-demo');

        for (const token of [
          'class="mes_reasoning_actions flex-container"',
          'class="mes_reasoning_edit_done menu_button edit_button fa-solid fa-check"',
          'class="mes_reasoning_delete menu_button edit_button fa-solid fa-trash-can"',
          'class="mes_reasoning_edit_cancel menu_button edit_button fa-solid fa-xmark"',
          'class="mes_reasoning_close_all mes_button fa-solid fa-minimize"',
          'class="mes_reasoning_copy mes_button fa-solid fa-copy"',
          'class="mes_reasoning_edit mes_button fa-solid fa-pencil"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        const actionsIndex = html.indexOf('class="mes_reasoning_actions flex-container"');
        const doneIndex = html.indexOf('class="mes_reasoning_edit_done menu_button edit_button fa-solid fa-check"');
        const deleteIndex = html.indexOf('class="mes_reasoning_delete menu_button edit_button fa-solid fa-trash-can"');
        const cancelIndex = html.indexOf('class="mes_reasoning_edit_cancel menu_button edit_button fa-solid fa-xmark"');
        const closeAllIndex = html.indexOf('class="mes_reasoning_close_all mes_button fa-solid fa-minimize"');
        const copyIndex = html.indexOf('class="mes_reasoning_copy mes_button fa-solid fa-copy"');
        const editIndex = html.indexOf('class="mes_reasoning_edit mes_button fa-solid fa-pencil"');

        if (!(actionsIndex < doneIndex && doneIndex < deleteIndex && deleteIndex < cancelIndex && cancelIndex < closeAllIndex && closeAllIndex < copyIndex && copyIndex < editIndex)) {
          throw new Error('preview reasoning controls should follow ST ordering');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_contains_st_extra_message_actions():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc');

        for (const token of [
          'class="extraMesButtons"',
          'class="mes_button mes_translate fa-solid fa-language"',
          'class="mes_button sd_message_gen fa-solid fa-paintbrush"',
          'class="mes_button mes_narrate fa-solid fa-bullhorn"',
          'class="mes_button mes_prompt fa-solid fa-square-poll-horizontal"',
          'class="mes_button mes_hide fa-solid fa-eye"',
          'class="mes_button mes_unhide fa-solid fa-eye-slash"',
          'class="mes_button mes_media_gallery fa-solid fa-photo-film"',
          'class="mes_button mes_media_list fa-solid fa-table-cells-large"',
          'class="mes_button mes_embed fa-solid fa-paperclip"',
          'class="mes_button mes_swipe_picker fa-solid fa-bookmark"',
          'class="mes_button mes_create_bookmark fa-regular fa-solid fa-flag-checkered"',
          'class="mes_button mes_create_branch fa-regular fa-code-branch"',
          'class="mes_button mes_copy fa-solid fa-copy"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        const extraIndex = html.indexOf('class="extraMesButtons"');
        const translateIndex = html.indexOf('class="mes_button mes_translate fa-solid fa-language"');
        const imageIndex = html.indexOf('class="mes_button sd_message_gen fa-solid fa-paintbrush"');
        const narrateIndex = html.indexOf('class="mes_button mes_narrate fa-solid fa-bullhorn"');
        const promptIndex = html.indexOf('class="mes_button mes_prompt fa-solid fa-square-poll-horizontal"');
        const hideIndex = html.indexOf('class="mes_button mes_hide fa-solid fa-eye"');
        const unhideIndex = html.indexOf('class="mes_button mes_unhide fa-solid fa-eye-slash"');
        const galleryIndex = html.indexOf('class="mes_button mes_media_gallery fa-solid fa-photo-film"');
        const listIndex = html.indexOf('class="mes_button mes_media_list fa-solid fa-table-cells-large"');
        const embedIndex = html.indexOf('class="mes_button mes_embed fa-solid fa-paperclip"');
        const swipeIndex = html.indexOf('class="mes_button mes_swipe_picker fa-solid fa-bookmark"');
        const bookmarkIndex = html.indexOf('class="mes_button mes_create_bookmark fa-regular fa-solid fa-flag-checkered"');
        const branchIndex = html.indexOf('class="mes_button mes_create_branch fa-regular fa-code-branch"');
        const copyIndex = html.indexOf('class="mes_button mes_copy fa-solid fa-copy"');

        if (!(extraIndex < translateIndex && translateIndex < imageIndex && imageIndex < narrateIndex && narrateIndex < promptIndex && promptIndex < hideIndex && hideIndex < unhideIndex && unhideIndex < galleryIndex && galleryIndex < listIndex && listIndex < embedIndex && embedIndex < swipeIndex && swipeIndex < bookmarkIndex && bookmarkIndex < branchIndex && branchIndex < copyIndex)) {
          throw new Error('preview extra message actions should follow ST ordering');
        }
        '''
    )


def test_build_beautify_preview_sample_markup_preserves_st_default_hidden_message_actions():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc');

        for (const token of [
          'class="mes_button mes_prompt fa-solid fa-square-poll-horizontal"',
          'title="Prompt" style="display: none;"',
          'class="mes_button mes_swipe_picker fa-solid fa-bookmark"',
          'title="Jump to swipe history" style="display: none;"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }
        '''
    )


def test_build_beautify_preview_sample_markup_contains_st_character_result_info_attributes():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewSampleMarkup('pc');

        for (const token of [
          'id="result_info" class="flex-container" style="display: none;"',
          'id="result_info_text" title="Token counts may be inaccurate and provided just for reference."',
          'data-i18n="[title]Token counts may be inaccurate and provided just for reference."',
          'id="result_info_total_tokens" title="Total tokens"',
          'data-i18n="[title]Total tokens"',
          '<span data-i18n="Calculating...">Calculating...</span>',
          '<small title="Permanent tokens" data-i18n="[title]Permanent tokens">',
          'id="chartokenwarning"',
          'href="https://docs.sillytavern.app/usage/core-concepts/characterdesign/#character-tokens"',
          'target="_blank"',
          "About Token 'Limits'",
          'class="right_menu_button fa-solid fa-triangle-exclamation"',
          "[title]About Token 'Limits'",
          'class="fa-solid fa-ranking-star right_menu_button rm_stats_button"',
          'title="Click for stats!"',
          'data-i18n="[title]Click for stats!"',
          'id="hideCharPanelAvatarButton"',
          'class="fa-solid fa-eye right_menu_button"',
          'title="Toggle character info panel"',
          'data-i18n="[title]Toggle character info panel"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }
        '''
    )


def test_build_beautify_preview_document_uses_local_demo_identity_avatar_paths():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc' });

        for (const token of [
          '/static/images/beautify-preview/sumian.png',
          '/static/images/beautify-preview/lingyan.png',
          'ch_name="苏眠"',
          'ch_name="凌砚"',
          'class="flex-container wide100pLess70px character_select_container"',
          'class="character_select"',
          'name_text">苏眠</span>',
          'name_text">凌砚</span>',
          'alt="苏眠" src="/static/images/beautify-preview/sumian.png"',
          'alt="凌砚" src="/static/images/beautify-preview/lingyan.png"',
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }

        for (const token of [
          'ch_name="Astra"',
          'name_text">Astra</span>',
          'ch_name="You"',
          'name_text">You</span>',
        ]) {
          if (html.includes(token)) throw new Error(`unexpected placeholder token: ${token}`);
        }

        const systemMessageStart = html.indexOf('ch_name="SillyTavern System"');
        const systemMessageEnd = html.indexOf('mesid="2"', systemMessageStart);
        const systemMessageHtml = html.slice(systemMessageStart, systemMessageEnd === -1 ? undefined : systemMessageEnd);
        if (!systemMessageHtml.includes('alt="SillyTavern System" src="data:image/svg+xml')) {
          throw new Error('system message should keep the simple inline placeholder avatar');
        }
        const systemInlineAvatarMatches = systemMessageHtml.match(/src="data:image\/svg\+xml/g) || [];
        if (systemInlineAvatarMatches.length !== 1) {
          throw new Error(`expected exactly one inline system avatar, got ${systemInlineAvatarMatches.length}`);
        }
        if (systemMessageHtml.includes('hidden aria-hidden="true"')) {
          throw new Error('system message should not include hidden duplicate avatar markup');
        }
        '''
    )


def test_build_beautify_preview_document_wires_panel_toggle_script_and_default_state():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc' });

        for (const token of [
          'data-active-panel="none"',
          'root.dataset.activePanel',
          'button.dataset.panelTarget',
          'aria-pressed',
          "panel.classList.toggle('openDrawer', isActive);",
          "panel.classList.toggle('closedDrawer', !isActive);",
          "const drawer = panel.closest('.drawer');",
          "drawer.classList.toggle('openDrawer', isActive);",
          "drawer.classList.toggle('open', isActive);",
          "drawer.dispatchEvent(new CustomEvent('inline-drawer-toggle', { bubbles: true }));",
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }
        '''
    )


def test_build_beautify_preview_document_scrolls_chat_to_bottom_on_load():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc' });
        for (const token of [
          "const chat = document.querySelector('#chat');",
          'chat.scrollTop = chat.scrollHeight;',
          'window.requestAnimationFrame(scrollChatToBottom);',
          "window.addEventListener('load', scrollChatToBottom);",
        ]) {
          if (!html.includes(token)) throw new Error(`missing token: ${token}`);
        }
        '''
    )


def test_build_beautify_preview_document_does_not_leave_unmatched_topbar_panel_targets():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc' });
        if (html.includes('data-panel-target="menu"')) throw new Error('preview should not expose unmatched menu panel target');
        if (html.includes('data-panel-target="api"')) throw new Error('preview should not expose unmatched api panel target');
        if (html.includes('data-panel-target="world-info"')) throw new Error('preview should not expose unmatched world info panel target');
        if (html.includes('data-panel-target="extensions"')) throw new Error('preview should not expose unmatched extensions panel target');
        if (html.includes('data-panel-target="moving-ui"')) throw new Error('preview should not expose unmatched moving ui panel target');
        if (html.includes('data-panel-target="notes"')) throw new Error('preview should not expose unmatched notes panel target');
        if (html.includes('data-panel-shell="menu"')) throw new Error('unexpected menu panel shell');
        if (html.includes('data-panel-shell="api"')) throw new Error('unexpected api panel shell');
        if (html.includes('data-panel-shell="world-info"')) throw new Error('unexpected world info panel shell');
        if (html.includes('data-panel-shell="moving-ui"')) throw new Error('unexpected moving ui panel shell');
        if (html.includes('data-panel-surface="menu"')) throw new Error('unexpected menu panel surface');
        if (html.includes('data-panel-surface="api"')) throw new Error('unexpected api panel surface');
        if (html.includes('data-panel-surface="world-info"')) throw new Error('unexpected world info panel surface');
        if (html.includes('data-panel-surface="moving-ui"')) throw new Error('unexpected moving ui panel surface');
        if (html.includes('data-preview-static-action=')) throw new Error('preview should not emit surrogate static topbar actions');
        '''
    )


def test_build_beautify_preview_document_preserves_vendor_toolbar_layout_and_only_overrides_drawer_visibility():
    source = (ROOT / 'static/js/components/beautifyPreviewDocument.js').read_text(encoding='utf-8')

    for token in [
        '.st-preview-panel-body {',
        'min-width: 0;',
        'max-height: min(680px, calc(100vh - 160px));',
        ".st-preview-root[data-active-panel='settings'] [data-panel-surface='settings']",
        ".st-preview-root[data-active-panel='formatting'] [data-panel-surface='formatting']",
        ".st-preview-root[data-active-panel='character'] [data-panel-surface='character']",
        'display: block;',
        'pointer-events: auto;',
    ]:
        assert token in source, f'missing drawer visibility override token: {token}'

    for removed in [
        '--st-preview-panel-width: min(420px, calc(100vw - 48px));',
        '--st-preview-left-panel-offset: 20px;',
        '--st-preview-right-panel-offset: 20px;',
        'inset: 72px 20px auto 20px;',
        'max-width: var(--st-preview-panel-width);',
        '#ai-config-button,',
        '#advanced-formatting-button {',
        'left: var(--st-preview-left-panel-offset);',
        '#right-nav-drawer {',
        'right: var(--st-preview-right-panel-offset);',
        '#sheld {',
        'width: min(var(--sheldWidth), 100%);',
        'margin: 0 auto;',
    ]:
        assert removed not in source, f'legacy preview-owned shell layout override should be removed: {removed}'


def test_build_beautify_preview_document_keeps_top_toolbar_flush_without_shell_top_padding():
    source = (ROOT / 'static/js/components/beautifyPreviewDocument.js').read_text(encoding='utf-8')

    shell_block = source.split('.st-preview-shell {', 1)[1].split('}', 1)[0]

    assert 'padding: 20px;' not in shell_block
    assert 'padding: 0 20px 20px;' in shell_block


def test_build_beautify_preview_document_keeps_vendor_toolbar_shell_visible_after_top_seam_fix():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc', theme: {} });

        const shellStart = html.indexOf('<div class="st-preview-shell">');
        if (shellStart === -1) throw new Error('missing preview shell wrapper');

        const shellEnd = html.indexOf('<div id="sheld">', shellStart);
        if (shellEnd === -1) throw new Error('missing ST sheld inside preview shell');

        const shellMarkup = html.slice(shellStart, shellEnd);
        const orderedTokens = [
          '<div id="top-bar"></div>',
          '<div id="top-settings-holder">',
        ];

        let previousIndex = -1;
        for (const token of orderedTokens) {
          const index = shellMarkup.indexOf(token);
          if (index === -1) throw new Error(`missing vendor toolbar token inside preview shell: ${token}`);
          if (index <= previousIndex) throw new Error(`vendor toolbar token order changed for ${token}`);
          previousIndex = index;
        }

        for (const token of [
          '<div id="ai-config-button" class="drawer closedDrawer">',
          '<div id="advanced-formatting-button" class="drawer closedDrawer">',
          'data-panel-surface="settings"',
          'data-panel-surface="formatting"',
        ]) {
          if (!shellMarkup.includes(token)) {
            throw new Error(`expected vendor toolbar controls to remain inside the shell: ${token}`);
          }
        }
        '''
    )


def test_build_beautify_preview_document_binds_only_supported_drawer_controls():
    run_preview_document_check(
        '''
        const html = module.buildBeautifyPreviewDocument({ platform: 'pc' });

        const scriptMatch = html.match(/<script>([\s\S]*)<\/script>/);
        if (!scriptMatch) throw new Error('missing preview behavior script');

        let loadHandler = null;
        let requestAnimationFrameCalls = 0;
        const interactiveClickHandlers = [];

        const root = { dataset: { activePanel: 'none', defaultScene: 'daily' } };
        const chat = {
          scrollTop: 0,
          scrollHeight: 40,
          innerHTML: '',
        };
        const description = { textContent: '' };

        function createClassList(initial = []) {
          const set = new Set(initial);
          return {
            add(...tokens) {
              tokens.forEach((token) => set.add(token));
            },
            remove(...tokens) {
              tokens.forEach((token) => set.delete(token));
            },
            toggle(token, force) {
              if (force === undefined) {
                if (set.has(token)) {
                  set.delete(token);
                  return false;
                }
                set.add(token);
                return true;
              }
              if (force) {
                set.add(token);
                return true;
              }
              set.delete(token);
              return false;
            },
            contains(token) {
              return set.has(token);
            },
          };
        }

        function createPanelButton(panelTarget) {
          return {
            dataset: { panelTarget },
            classList: createClassList(),
            attributes: {},
            addEventListener(type, handler) {
              if (type === 'click') {
                interactiveClickHandlers.push({ panelTarget, handler });
              }
            },
            setAttribute(name, value) {
              this.attributes[name] = String(value);
            },
          };
        }

        const panelButtons = [createPanelButton('settings')];

        const document = {
          querySelector(selector) {
            if (selector === '.st-preview-root') return root;
            if (selector === '#chat') return chat;
            if (selector === '[data-preview-chat-messages]') return chat;
            if (selector === '[data-preview-scene-description]') return description;
            if (selector === '[data-preview-scene-template="daily"]') {
              return { innerHTML: '<div>daily</div>', dataset: { previewSceneDescription: 'daily desc' } };
            }
            return null;
          },
          querySelectorAll(selector) {
            if (selector === '[data-panel-target]') return panelButtons;
            if (selector === '[data-panel-surface]' || selector === '[data-panel-shell]' || selector === '.inline-drawer' || selector === '[data-preview-scene-button]' || selector === '[data-preview-link="disabled"]') {
              return [];
            }
            return [];
          },
        };

        const window = {
          requestAnimationFrame(callback) {
            requestAnimationFrameCalls += 1;
            callback();
          },
          addEventListener(type, handler) {
            if (type === 'load') {
              loadHandler = handler;
            }
          },
        };

        class CustomEvent {
          constructor(type, options = {}) {
            this.type = type;
            this.bubbles = Boolean(options.bubbles);
          }
        }

        const runScript = new Function('document', 'window', 'CustomEvent', scriptMatch[1]);
        runScript(document, window, CustomEvent);

        if (interactiveClickHandlers.length !== 1) throw new Error(`expected one interactive panel handler, got ${interactiveClickHandlers.length}`);
        if (typeof loadHandler !== 'function') throw new Error('preview script did not bind load handler');
        if (requestAnimationFrameCalls === 0) throw new Error('preview script did not schedule initial chat scroll');

        interactiveClickHandlers[0].handler();

        if (root.dataset.activePanel !== 'settings') {
          throw new Error(`supported drawer control should activate its panel, got ${root.dataset.activePanel}`);
        }
        if (panelButtons[0].attributes['aria-pressed'] !== 'true') {
          throw new Error(`supported drawer control should set aria-pressed, got ${panelButtons[0].attributes['aria-pressed']}`);
        }
        '''
    )


def test_build_beautify_preview_document_shows_top_settings_holder_in_default_preview_state():
    source = (ROOT / 'static/js/components/beautifyPreviewDocument.js').read_text(encoding='utf-8')

    assert '#top-settings-holder {' not in source


def test_build_beautify_preview_document_explicitly_anchors_mobile_top_bars_inside_isolated_shell():
    source = (ROOT / 'static/js/components/beautifyPreviewDocument.js').read_text(encoding='utf-8')

    assert "body[data-st-preview-platform='mobile'] #top-settings-holder" in source
    assert "body[data-st-preview-platform='mobile'] #top-bar" in source

    mobile_topbar_block = source.split("body[data-st-preview-platform='mobile'] #top-settings-holder,", 1)[1].split('}', 1)[0]

    assert 'left: 0;' in mobile_topbar_block
    assert 'right: 0;' in mobile_topbar_block


def test_beautify_preview_identity_assets_exist_in_project_static_images():
    for relative_path in [
        'static/images/beautify-preview/sumian.png',
        'static/images/beautify-preview/lingyan.png',
    ]:
        assert (ROOT / relative_path).is_file(), f'missing preview identity asset: {relative_path}'


def test_vendored_sillytavern_style_css_uses_vendor_local_icon_asset_paths():
    style_css = (ROOT / 'static/vendor/sillytavern/style.css').read_text(encoding='utf-8')

    assert "background-image: url('/img/down-arrow.svg');" not in style_css
    assert "background-image: url('../img/down-arrow.svg');" not in style_css
    assert "background-image: url('img/down-arrow.svg');" in style_css
    assert "mask: url('/img/times-circle.svg') no-repeat 50% 50%;" not in style_css
    assert "mask: url('img/times-circle.svg') no-repeat 50% 50%;" in style_css


def test_render_iframe_template_does_not_force_fixed_and_sticky_positions_to_absolute():
    source = (ROOT / 'static/js/runtime/renderIframeTemplate.js').read_text(encoding='utf-8')

    assert '[style*="position: fixed"]' not in source
    assert '[style*="position:fixed"]' not in source
    assert '[style*="position: sticky"]' not in source
    assert '[style*="position:sticky"]' not in source
    assert 'position: absolute !important;' not in source
