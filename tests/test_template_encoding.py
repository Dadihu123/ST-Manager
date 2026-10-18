"""模板编码契约。

模板里一旦混进 U+FEFF（UTF-8 BOM / 零宽不换行空格），Jinja 会把它原样拼进
最终 HTML。它在 <body> 里是一个真实文本节点：`body` 是 `display: flex;
flex-direction: column; height: 100dvh` 的容器，这个文本节点会生成一个匿名
flex item（行盒约 20px），把 `.main-container` 往上挤，页面底部就会留一条缝隙。

历史：`templates/modals/settings.html` 在 3990a7d 被写入时带了 BOM，导致主界面
底部出现一条 24px 的空白。这里用测试把契约钉住，避免编辑器再次写入 BOM。
"""

from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / 'templates'
BOM_BYTES = b'\xef\xbb\xbf'
ZERO_WIDTH_NO_BREAK_SPACE = '\ufeff'


def _template_files():
    return sorted(TEMPLATE_DIR.rglob('*.html'))


def test_templates_are_discovered():
    assert len(_template_files()) > 20


@pytest.mark.parametrize('template', _template_files(), ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_template_has_no_utf8_bom(template):
    assert not template.read_bytes().startswith(BOM_BYTES), (
        f'{template.relative_to(PROJECT_ROOT)} 以 UTF-8 BOM 开头；'
        'BOM 会被 Jinja 拼进 HTML 正文，在 flex 布局的 body 里生成匿名行盒，'
        '把主容器顶上去、页面底部留缝。请用无 BOM 的 UTF-8 保存。'
    )


@pytest.mark.parametrize('template', _template_files(), ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_template_has_no_stray_zero_width_no_break_space(template):
    text = template.read_text(encoding='utf-8')
    assert ZERO_WIDTH_NO_BREAK_SPACE not in text, (
        f'{template.relative_to(PROJECT_ROOT)} 含 U+FEFF；'
        '该字符不可见但会撑出文本行盒，破坏 body 的整屏 flex 布局。'
    )
