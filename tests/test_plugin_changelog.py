"""插件更新说明切分（`core/plugins/changelog.py`）。

锚点格式是宿主与插件仓库的约定，两侧同一份；这里钉住解析与区间切分的语义，
尤其是「只认锚点、不猜标题」——插件的真实 CHANGELOG 结构很乱，从标题猜版本
会把别的版本的改动说明显示在更新确认弹层里。
"""

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import changelog


def _anchored(version, body_lines):
    """按约定拼一段带锚点的 CHANGELOG 段落（版本标题行在锚点内部）。"""
    lines = [f'<!-- release: {version} -->', f'## {version}']
    lines.extend(body_lines)
    lines.append('<!-- /release -->')
    return '\n'.join(lines)


SAMPLE = '\n\n'.join([
    '# 插件变更日志',
    '未加锚点的历史内容（应被忽略）',
    _anchored('0.4.1', ['### 修复', '- 修复 A', '- 修复 B']),
    _anchored('0.3.0', ['### 新增', '- 新增 C']),
    _anchored('0.2.0', ['### 修复', '- 修复 D']),
    '## 1.0.0（没有锚点，忽略）',
])


# ------------------------------------------------------------------ 解析


def test_parse_release_sections_returns_anchored_sections_in_file_order():
    sections = changelog.parse_release_sections(SAMPLE)

    assert [item['version'] for item in sections] == ['0.4.1', '0.3.0', '0.2.0']
    # 版本标题行在锚点内部：body 必须含 `## 0.4.1`
    assert sections[0]['body'].startswith('## 0.4.1')
    assert '- 修复 A' in sections[0]['body']
    assert '- 修复 B' in sections[0]['body']
    # 锚点以外的内容（文件标题、未加锚点的历史、无锚点的 1.0.0）不进 body
    assert '插件变更日志' not in sections[0]['body']
    assert '- 修复 D' not in sections[0]['body']
    assert '1.0.0' not in ''.join(item['version'] for item in sections)


def test_parse_release_sections_ignores_body_outside_anchors():
    text = '前言\n\n<!-- release: 0.1.0 -->\n## 0.1.0\n- 内容\n<!-- /release -->\n\n结尾'

    sections = changelog.parse_release_sections(text)

    assert len(sections) == 1
    assert sections[0]['body'] == '## 0.1.0\n- 内容'


def test_parse_release_sections_skips_unclosed_anchor():
    text = '<!-- release: 0.2.0 -->\n## 0.2.0\n- 没有闭合锚点'

    assert changelog.parse_release_sections(text) == []


def test_parse_release_sections_skips_non_semver_anchor():
    text = '\n'.join([
        '<!-- release: P3 可用性修复 -->',
        '## P3 可用性修复（2026-10-11…）',
        '<!-- /release -->',
        _anchored('0.1.0', ['- 正常段落']),
    ])

    versions = [item['version'] for item in changelog.parse_release_sections(text)]

    assert versions == ['0.1.0']


def test_parse_release_sections_returns_empty_without_anchors():
    """真实插件的 CHANGELOG 里可能有各种日期标题，但没有锚点就是「没有」."""
    text = '\n'.join([
        '# CHANGELOG',
        '## 0.3.0（2026-10-25）',
        '### 2026-10-24 修复',
        '- 旧内容',
        '## P3 可用性修复（2026-10-11…）',
    ])

    assert changelog.parse_release_sections(text) == []


def test_parse_release_sections_tolerates_non_string_and_empty_input():
    for value in (None, b'bytes', 42, '', '   '):
        assert changelog.parse_release_sections(value) == []


# ------------------------------------------------------------------ 切分区间


def test_slice_takes_only_versions_newer_than_installed():
    sections = changelog.parse_release_sections(SAMPLE)

    picked = changelog.slice_release_sections(sections, from_version='0.3.0', to_version='0.4.1')

    # (0.3.0, 0.4.1] —— 只含 0.4.1，不含已安装的 0.3.0 本身
    assert [item['version'] for item in picked] == ['0.4.1']


def test_slice_includes_all_versions_in_range_newest_first():
    sections = changelog.parse_release_sections(SAMPLE)

    picked = changelog.slice_release_sections(sections, from_version='0.2.0', to_version='0.4.1')

    assert [item['version'] for item in picked] == ['0.4.1', '0.3.0']


def test_slice_with_empty_from_version_keeps_everything_up_to_target():
    sections = changelog.parse_release_sections(SAMPLE)

    picked = changelog.slice_release_sections(sections, from_version='', to_version='0.3.0')

    assert [item['version'] for item in picked] == ['0.3.0', '0.2.0']


def test_slice_with_invalid_from_version_keeps_everything_up_to_target():
    sections = changelog.parse_release_sections(SAMPLE)

    picked = changelog.slice_release_sections(sections, from_version='not-a-version', to_version='0.2.0')

    assert [item['version'] for item in picked] == ['0.2.0']


def test_slice_from_equals_to_is_empty():
    """已是最新版本时区间为空——这与「没有更新就不展示说明」一致。"""
    sections = changelog.parse_release_sections(SAMPLE)

    picked = changelog.slice_release_sections(sections, from_version='0.4.1', to_version='0.4.1')

    assert picked == []


def test_slice_requires_a_valid_target_version():
    sections = changelog.parse_release_sections(SAMPLE)

    assert changelog.slice_release_sections(sections, from_version='0.2.0', to_version='') == []
    assert changelog.slice_release_sections(sections, from_version='0.2.0', to_version='abc') == []


def test_slice_deduplicates_repeated_versions_keeping_the_first():
    sections = [
        {'version': '0.2.0', 'body': '## 0.2.0\n- 第一次出现'},
        {'version': '0.2.0', 'body': '## 0.2.0\n- 重复段落'},
    ]

    picked = changelog.slice_release_sections(sections, from_version='0.1.0', to_version='0.2.0')

    assert len(picked) == 1
    assert '第一次出现' in picked[0]['body']


def test_slice_returns_empty_for_empty_sections():
    assert changelog.slice_release_sections([], from_version='0.1.0', to_version='0.2.0') == []
    assert changelog.slice_release_sections(None, from_version='0.1.0', to_version='0.2.0') == []


# ------------------------------------------------------------------ compose


def test_compose_joins_sections_newest_first():
    notes = changelog.compose_release_notes(SAMPLE, from_version='0.2.0', to_version='0.4.1')

    assert notes.startswith('## 0.4.1')
    assert notes.count('## 0.4.1') == 1
    assert notes.count('## 0.3.0') == 1
    # 新的在前
    assert notes.index('## 0.4.1') < notes.index('## 0.3.0')
    # 段落之间空一行（markdown 块级分隔）
    assert '<!-- /release -->' not in notes
    assert '\n\n## 0.3.0' in notes


def test_compose_returns_empty_when_nothing_in_range():
    assert changelog.compose_release_notes('没有锚点', from_version='0.1.0', to_version='0.2.0') == ''
    assert changelog.compose_release_notes(SAMPLE, from_version='0.4.1', to_version='0.4.1') == ''


def test_compose_never_raises_on_hostile_input():
    for text in (None, 42, b'bytes', object(), '<script>x</script>'):
        assert changelog.compose_release_notes(text, from_version='0.1.0', to_version='0.2.0') == ''
    assert changelog.compose_release_notes(SAMPLE, from_version=None, to_version=None) == ''
