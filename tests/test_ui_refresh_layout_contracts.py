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

    responsive_sources = source.split('@media (max-width: 768px) {')[1:]
    mobile_match = next(
        (
            re.search(
                r'^\s*\.automation-container\s*\{(?P<body>[^}]*)\}',
                responsive_source,
                re.MULTILINE,
            )
            for responsive_source in responsive_sources
            if re.search(
                r'^\s*\.automation-container\s*\{(?P<body>[^}]*)\}',
                responsive_source,
                re.MULTILINE,
            )
        ),
        None,
    )
    assert mobile_match
    assert 'flex-direction: column;' in mobile_match.group('body')
