from pathlib import Path
import re
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_preset_grid_uses_semantic_icon_mappings():
    source = read_project_file('templates/components/grid_presets.html')

    expected_fragments = [
        "detail_icon('preset'",
        "icon('refresh', 'ui-icon--sm ')",
        "icon('file-import'",
        "loading_icon('",
        "icon('check'",
        "icon('trash'",
        "icon('upload'",
        "icon('send'",
        "detail_icon('regex'",
        "preset_icon('thermometer'",
        "preset_icon('token-count'",
        "preset_icon('prompt-count'",
        "preset_icon('owner'",
    ]

    for fragment in expected_fragments:
        assert fragment in source

    for emoji in ('📝', '↻', '📥', '⏳', '✓', '✕', '⇩', '🌡️', '📊', '💬', '🧩', '👤', '📭', '🚀'):
        assert emoji not in source


def test_preset_icon_sprite_contains_all_custom_assets_without_white_canvas():
    sprite_source = read_project_file('static/icons/preset.svg')
    root = ET.fromstring(sprite_source)
    namespace = '{http://www.w3.org/2000/svg}'
    symbol_ids = {
        symbol.attrib['id']
        for symbol in root.findall(f'{namespace}symbol')
    }
    expected_ids = {
        'icon-definition-after',
        'icon-definition-before',
        'icon-character-description',
        'icon-scenario',
        'icon-character-personality',
        'icon-owner',
        'icon-thermometer',
        'icon-persona-description',
        'icon-chat-examples',
        'icon-chat-history',
        'icon-prompt-count',
        'icon-token-count',
        'icon-empty-state',
    }

    assert symbol_ids == expected_ids
    assert 'background' not in sprite_source.lower()
    assert 'style=' not in sprite_source
    assert re.search(r'fill="currentColor"', sprite_source)


def test_prompt_marker_visuals_point_to_the_new_custom_assets():
    source = read_project_file('static/js/utils/promptMarkerVisuals.js')
    expected_assets = {
        'worldInfoBefore': 'definition-before',
        'worldInfoAfter': 'definition-after',
        'charDescription': 'character-description',
        'charPersonality': 'character-personality',
        'personaDescription': 'persona-description',
        'scenario': 'scenario',
        'dialogueExamples': 'chat-examples',
        'chatHistory': 'chat-history',
    }

    for key, asset in expected_assets.items():
        assert re.search(
            rf'{re.escape(key)}:\s*\{{[\s\S]*?asset:\s*"{re.escape(asset)}"',
            source,
        )

    assert 'PRESET_ICON_SPRITE_URL = "/static/icons/preset.svg"' in source


def test_preset_loading_icon_uses_the_animated_asset_and_shared_size():
    preset_source = read_project_file('templates/components/grid_presets.html')
    extension_source = read_project_file('templates/components/grid_extensions.html')
    cards_css = read_project_file('static/css/modules/view-cards.css')
    icons_css = read_project_file('static/css/modules/icons.css')
    icon_source = read_project_file('templates/components/icon.html')
    loading_asset = read_project_file('static/icons/loading-animation.svg')

    assert "loading_icon('ui-icon--xl')" in preset_source
    assert "loading_icon('ui-icon--xl')" in extension_source
    assert 'loading-animation.svg' in icon_source
    assert '<animateTransform' in loading_asset
    assert '<animate ' in loading_asset
    assert 'ui-icon--spin' not in preset_source
    assert 'ui-icon--spin' not in extension_source

    loading_rule = re.search(
        r'\.preset-list-loading-icon \.ui-icon\s*\{(?P<body>[^}]*)\}',
        cards_css,
    )
    assert loading_rule is not None
    assert 'width: 64px;' in loading_rule.group('body')
    assert 'height: 64px;' in loading_rule.group('body')

    assert '.ui-icon--spin' not in icons_css
