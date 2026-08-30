"""颜色 Token、用户自定义标签颜色和隔离预览的契约测试。"""

from pathlib import Path
import shutil
import subprocess
import sys
import textwrap

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.data.ui_store import _normalize_hex_color


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def test_ui_store_keeps_supported_color_formats_and_rejects_unsafe_values():
    assert _normalize_hex_color('#AbC') == '#aabbcc'
    assert _normalize_hex_color('#1234') == '#11223344'
    assert _normalize_hex_color('rgb(255, 0, 12)') == 'rgb(255, 0, 12)'
    assert _normalize_hex_color('rgba(0%, 50%, 100%, 0.4)') == 'rgba(0%, 50%, 100%, 0.4)'
    assert _normalize_hex_color('hsl(210, 40%, 50%)') == 'hsl(210, 40%, 50%)'
    assert _normalize_hex_color('url(javascript:alert(1))') == '#64748b'
    assert _normalize_hex_color('rgb(255, 0, 0); color: red') == '#64748b'
    assert _normalize_hex_color('hsl(210, 140%, 50%)') == '#64748b'
    assert _normalize_hex_color('invalid', 'hsl(210, 40%, 50%)') == 'hsl(210, 40%, 50%)'
    assert _normalize_hex_color('', 'url(javascript:alert(1))') == '#64748b'


def test_layout_loads_semantic_color_layer_after_generated_tailwind():
    layout = read_project_file('templates/layout.html')
    tailwind_index = layout.index('/static/css/tailwind.css')
    semantic_index = layout.index('/static/css/color-system.css')
    assert semantic_index > tailwind_index


def test_semantic_color_contract_covers_surface_content_state_status_and_focus():
    variables = read_project_file('static/css/modules/variables.css')
    semantic_css = read_project_file('static/css/color-system.css')

    for token in (
        '--surface-page',
        '--surface-container',
        '--surface-overlay',
        '--content-primary',
        '--content-secondary',
        '--content-muted',
        '--content-disabled',
        '--content-on-status-solid',
        '--content-on-decoration-solid',
        '--icon-default',
        '--icon-muted',
        '--border-default',
        '--state-hover-surface',
        '--state-selected-surface',
        '--state-focus-ring',
        '--accent-action',
        '--accent-action-hover',
        '--accent-soft',
        '--action-surface',
        '--action-surface-hover',
        '--action-surface-active',
        '--action-border',
        '--action-text',
        '--decoration-violet-surface',
        '--decoration-violet-surface-hover',
        '--decoration-violet-border',
        '--decoration-violet-text',
        '--status-success-text',
        '--status-info-text',
        '--status-warning-text',
        '--status-danger-text',
        '--status-success-hover-solid',
        '--status-danger-hover-solid',
        '--decoration-violet-hover-solid',
        '--tag-default-surface',
    ):
        assert token in variables

    for selector in (
        '.color-surface-violet-solid',
        '.color-surface-rose-solid',
        '.color-status-success',
        '.color-status-danger',
        '.color-focus-border-accent',
        '.btn-action-soft',
        '.modal-overlay',
        '.toast-notification',
        '.sidebar-tag-category-pill',
    ):
        assert selector in semantic_css

    assert '.color-surface-danger-solid' in semantic_css
    assert 'color: var(--content-on-status-solid)' in semantic_css

    primary_button = semantic_css.split('.btn-primary,\nbutton.btn-primary {', 1)[1].split('}', 1)[0]
    assert 'background-color: var(--action-surface) !important;' in primary_button
    assert 'border: 1px solid var(--action-border) !important;' in primary_button
    assert 'color: var(--action-text) !important;' in primary_button
    assert 'content-on-accent' not in primary_button

    for utility in (
        '.color-surface-action',
        '.color-text-action',
        '.color-border-action',
        '.color-hover-surface-action',
    ):
        assert utility in semantic_css


def test_application_sources_do_not_reintroduce_palette_color_utilities():
    source_paths = list((PROJECT_ROOT / 'templates').rglob('*.html'))
    source_paths.extend((PROJECT_ROOT / 'static/js').rglob('*.js'))
    legacy_palette_fragments = (
        'bg-red-',
        'bg-blue-',
        'bg-green-',
        'bg-purple-',
        'text-red-',
        'text-blue-',
        'text-green-',
        'text-purple-',
        'border-red-',
        'border-blue-',
        'border-green-',
        'border-purple-',
    )

    for path in source_paths:
        source = path.read_text(encoding='utf-8')
        assert not any(fragment in source for fragment in legacy_palette_fragments), path


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is required for runtime color checks')
def test_runtime_tag_color_combinations_meet_text_and_border_contrast():
    node_script = textwrap.dedent(
        r"""
        import assert from 'node:assert/strict';
        import {
          buildTagColorStyle,
          contrastRatio,
          parseCssColor,
        } from './static/js/state.js';

        const readVar = (style, name) => {
          const match = style.match(new RegExp(`${name}:([^;]+)`));
          assert.ok(match, `missing ${name}`);
          return match[1];
        };

        const cases = [
          '#000000',
          '#ffffff',
          '#ff00ff',
          '#808080',
          'rgb(255, 0, 0)',
          'rgba(0%, 60%, 100%, 0.45)',
          'hsl(210, 40%, 50%)',
          'invalid-color',
        ];

        for (const color of cases) {
          const style = buildTagColorStyle(color, 0);
          for (const mode of ['dark', 'light']) {
            const background = parseCssColor(readVar(style, `--tag-cat-bg-${mode}`));
            const text = parseCssColor(readVar(style, `--tag-cat-text-${mode}`));
            const border = parseCssColor(readVar(style, `--tag-cat-border-${mode}`));
            const activeBackground = parseCssColor(readVar(style, `--tag-cat-active-bg-${mode}`));
            const activeText = parseCssColor(readVar(style, `--tag-cat-active-text-${mode}`));
            const activeBorder = parseCssColor(readVar(style, `--tag-cat-active-border-${mode}`));
            assert.ok(contrastRatio(text, background) >= 4.5, `${color}/${mode} text`);
            assert.ok(contrastRatio(border, background) >= 3, `${color}/${mode} border`);
            assert.ok(contrastRatio(activeText, activeBackground) >= 4.5, `${color}/${mode} active text`);
            assert.ok(contrastRatio(activeBorder, activeBackground) >= 3, `${color}/${mode} active border`);
          }
        }

        const preserved = buildTagColorStyle('rgb(12, 34, 56)', 72);
        assert.match(preserved, /--tag-cat-color:rgb\(12, 34, 56\)/);
        assert.match(buildTagColorStyle('not-a-color', 72), /--tag-cat-color:#64748b/);
        """
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is required for token contrast checks')
def test_status_and_decoration_solid_tokens_meet_text_contrast_in_both_modes():
    node_script = textwrap.dedent(
        r"""
        import assert from 'node:assert/strict';
        import { readFileSync } from 'node:fs';
        import { contrastRatio, parseCssColor } from './static/js/state.js';

        const source = readFileSync('./static/css/modules/variables.css', 'utf8');

        function readBlock(startIndex) {
          const openIndex = source.indexOf('{', startIndex);
          let depth = 0;
          for (let index = openIndex; index < source.length; index += 1) {
            if (source[index] === '{') depth += 1;
            if (source[index] === '}') {
              depth -= 1;
              if (depth === 0) return source.slice(openIndex + 1, index);
            }
          }
          throw new Error('unterminated CSS block');
        }

        const semanticStart = source.indexOf(':root {', source.indexOf('Semantic color system'));
        const blocks = [
          ['dark', readBlock(semanticStart)],
          ['light', readBlock(source.indexOf('html.light-mode {'))],
        ];
        const solidTokens = [
          '--status-success-solid', '--status-success-hover-solid',
          '--status-info-solid', '--status-info-hover-solid',
          '--status-warning-solid', '--status-warning-hover-solid',
          '--status-danger-solid', '--status-danger-hover-solid',
          '--status-neutral-solid', '--status-neutral-hover-solid',
          '--decoration-violet-solid', '--decoration-violet-hover-solid',
          '--decoration-cyan-solid', '--decoration-cyan-hover-solid',
          '--decoration-rose-solid', '--decoration-rose-hover-solid',
          '--decoration-amber-solid', '--decoration-amber-hover-solid',
        ];
        const lightText = parseCssColor('#f8fafc');

        for (const [mode, block] of blocks) {
          for (const token of solidTokens) {
            const match = block.match(new RegExp(`${token}:\\s*(#[0-9a-fA-F]{6})`));
            assert.ok(match, `${mode} missing ${token}`);
            const background = parseCssColor(match[1]);
            assert.ok(
              contrastRatio(lightText, background) >= 4.5,
              `${mode} ${token} contrast`,
            );
          }
        }
        """
    )
    result = subprocess.run(
        ['node', '--input-type=module', '-e', node_script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
