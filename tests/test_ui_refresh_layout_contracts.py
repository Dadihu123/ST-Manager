from pathlib import Path
import re


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_automation_shell_keeps_desktop_split_and_mobile_stack_layouts():
    source = (PROJECT_ROOT / 'static/css/modules/ui-refresh.css').read_text(
        encoding='utf-8'
    )

    desktop_match = re.search(
        r'^\.automation-container\s*\{(?P<body>[^}]*)\}',
        source,
        re.MULTILINE,
    )
    assert desktop_match
    assert 'flex-direction: row;' in desktop_match.group('body')

    responsive_source = source.rsplit('@media (max-width: 768px) {', 1)[1]
    mobile_match = re.search(
        r'^\s+\.automation-container\s*\{(?P<body>[^}]*)\}',
        responsive_source,
        re.MULTILINE,
    )
    assert mobile_match
    assert 'flex-direction: column;' in mobile_match.group('body')
