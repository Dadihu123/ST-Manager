from pathlib import Path
import re
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_preset_grid_uses_the_requested_icon_mappings():
    source = read_project_file('templates/components/grid_presets.html')

    expected_fragments = [
        "detail_icon('preset'",
        "icon('header-refresh'",
        "icon('header-import'",
        "icon('card-loader'",
        "icon('card-check'",
        "icon('context-delete'",
        "icon('card-upload'",
        "icon('card-send'",
        "detail_icon('regex'",
        "preset_icon('temperature'",
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
        'icon-preset-character-definition-after',
        'icon-preset-character-definition-before',
        'icon-preset-character-description',
        'icon-preset-character-scenario',
        'icon-preset-character-personality',
        'icon-preset-owner',
        'icon-preset-temperature',
        'icon-preset-user-persona-description',
        'icon-preset-chat-examples',
        'icon-preset-chat-history',
        'icon-preset-prompt-count',
        'icon-preset-token-count',
        'icon-preset-empty-state',
    }

    assert symbol_ids == expected_ids
    assert 'background' not in sprite_source.lower()
    assert 'style=' not in sprite_source
    assert re.search(r'fill="currentColor"', sprite_source)


def test_prompt_marker_visuals_point_to_the_new_custom_assets():
    source = read_project_file('static/js/utils/promptMarkerVisuals.js')
    expected_assets = {
        'worldInfoBefore': 'character-definition-before',
        'worldInfoAfter': 'character-definition-after',
        'charDescription': 'character-description',
        'charPersonality': 'character-personality',
        'personaDescription': 'user-persona-description',
        'scenario': 'character-scenario',
        'dialogueExamples': 'chat-examples',
        'chatHistory': 'chat-history',
    }

    for key, asset in expected_assets.items():
        assert re.search(
            rf'{re.escape(key)}:\s*\{{[\s\S]*?asset:\s*"{re.escape(asset)}"',
            source,
        )

    assert 'PRESET_ICON_SPRITE_URL = "/static/icons/preset.svg"' in source
