from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_directional_controls_share_one_visual_and_size_contract():
    style = read_project_file('static/css/style.css')
    controls_css = read_project_file('static/css/modules/icon-controls.css')
    settings_css = read_project_file('static/css/modules/modal-settings.css')

    assert '@import "modules/icon-controls.css";' in style
    assert '.ui-reorder-button:hover' in controls_css
    assert '.ui-reorder-button:focus-visible' in controls_css
    assert '.ui-number-control:hover > .ui-number-stepper' in controls_css
    assert '.ui-number-control:focus-within > .ui-number-stepper' in controls_css
    assert 'opacity: 0;' in controls_css
    assert 'visibility: hidden;' in controls_css
    assert 'border: 0;' in controls_css
    assert '.ui-number-stepper-btn:disabled' in controls_css
    assert 'ui-icon--xs {' not in controls_css

    settings_stepper = settings_css.split('.settings-number-stepper {', 1)[1].split('}', 1)[0]
    assert 'border: 0;' in settings_stepper
    assert 'background: transparent;' in settings_stepper
    assert 'settings-number-stepper-icon' not in settings_css


def test_settings_number_controls_use_automation_arrow_symbols():
    source = read_project_file('templates/modals/settings.html')

    assert source.count("icon('arrow-up', 'ui-icon--xs')") == 13
    assert source.count("icon('arrow-down', 'ui-icon--xs')") == 13
    assert "icon('chevron-down'" not in source
    assert 'settings-number-stepper-icon' not in source


def test_number_adjustments_use_shared_stepper_helper():
    helper = read_project_file('static/js/utils/numberControl.js')
    app = read_project_file('static/js/app.js')
    advanced_editor = read_project_file('templates/modals/advanced_editor.html')
    chat_reader = read_project_file('templates/modals/detail_chat_reader.html')

    assert 'import "./utils/numberControl.js";' in app
    assert 'export function stepNumberInput(button, delta)' in helper
    assert 'input.stepUp(steps)' in helper
    assert 'input.stepDown(steps)' in helper
    assert 'new Event("input", { bubbles: true })' in helper
    assert advanced_editor.count('class="ui-number-control"') == 2
    assert chat_reader.count('class="ui-number-control"') == 10
    assert 'window.stepNumberInput($event.currentTarget, 1)' in advanced_editor
    assert 'window.stepNumberInput($event.currentTarget, -1)' in chat_reader


def test_world_info_fullscreen_number_controls_use_shared_stepper_contract():
    source = read_project_file('templates/modals/detail_wi_fullscreen.html')

    assert source.count('type="number"') == 9
    assert source.count('class="ui-number-control') == 9
    assert source.count('class="ui-number-stepper"') == 9
    assert source.count('ui-number-input') == 9
    assert source.count('step="1"') == 9
    assert source.count("icon('arrow-up', 'ui-icon--xs')") == 9
    assert source.count("icon('arrow-down', 'ui-icon--xs')") == 9
    assert 'window.stepNumberInput($event.currentTarget, 1)' in source
    assert 'window.stepNumberInput($event.currentTarget, -1)' in source


def test_reorderable_modules_use_shared_arrow_buttons():
    template_paths = (
        'templates/modals/advanced_editor.html',
        'templates/modals/automation.html',
        'templates/modals/detail_preset_fullscreen.html',
        'templates/modals/tag_filter.html',
    )

    for relative_path in template_paths:
        source = read_project_file(relative_path)
        assert 'class="ui-reorder-button"' in source
        assert "icon('arrow-up', 'ui-icon--xs')" in source
        assert "icon('arrow-down', 'ui-icon--xs')" in source


def test_world_info_sort_labels_do_not_use_raw_direction_glyphs():
    source = read_project_file('static/js/utils/wiSort.js')

    assert '↑' not in source
    assert '↓' not in source
    assert 'Token 升序' in source
    assert 'Token 降序' in source


def test_chat_reader_prev_next_pairs_share_one_arrow_glyph():
    """阅读器「上一批/下一批」「上一实例/下一实例」必须成对使用同一套箭头。

    `arrow-right` / `arrow-up` / `arrow-down` 是实心粗箭头一套；`arrow-left-outline`
    是空心长柄箭头（世界书回退图标），两者风格不同、并排会明显不搭。成对按钮统一用
    `chevron-right`：上一侧 `rotate-180` 镜像，下一侧正向。
    """
    reader = read_project_file('templates/modals/detail_chat_reader.html')

    assert "{{ icon('chevron-right', 'ui-icon--sm rotate-180') }}<span>上一批</span>" in reader
    assert "{{ icon('chevron-right', 'ui-icon--sm') }}<span>下一批</span>" in reader
    assert "{{ icon('chevron-right', 'ui-icon--sm rotate-180') }}<span>上一实例</span>" in reader
    assert "{{ icon('chevron-right', 'ui-icon--sm') }}<span>下一实例</span>" in reader


def test_arrow_icon_names_expose_their_glyph_family():
    """箭头图标名要能看出图形家族，避免再被当成左右镜像对混用。"""
    sprite = read_project_file('static/icons/ui.svg')

    assert 'id="icon-arrow-left-outline"' in sprite
    assert 'id="icon-arrow-left"' not in sprite
    for name in ('arrow-right', 'arrow-up', 'arrow-down'):
        assert f'id="icon-{name}"' in sprite

    # D4 契约：图标改名走 deprecation，旧名保留为别名，插件写旧名仍能解析
    generator = read_project_file('tools/gen_plugin_ui_icons.py')
    assert "'arrow-left': 'arrow-left-outline'" in generator
