"""PNG 角色卡 ``chara`` / ``ccv3`` 块的读写规则。

回归背景一：同一张卡片同时携带 ``chara``（V2）与 ``ccv3``（V3）两个块时，
SillyTavern 的 ``character-card-parser.js read()`` 优先读 ``ccv3``，
而 ST-Manager 曾优先读 ``chara``，导致 ``chara`` 那份不合规的卡片
被判为「非有效卡片」而导入失败。

回归背景二：``character_book`` 缺 ``extensions`` 的 V2 卡片 ST 可以正常导入，
宿主曾按 V2 规范把它判为非卡片，见
``test_v2_card_with_character_book_missing_extensions_is_readable``。
"""
import base64
import json
import sys
from pathlib import Path

from PIL import Image, PngImagePlugin


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.utils.image import extract_card_info_with_status, write_card_metadata
from core.utils.png_metadata import build_card_pnginfo, encode_card_chunks, iter_card_payloads


def _v1_card(name='Hero'):
    return {
        'name': name,
        'description': 'A character',
        'personality': 'Calm',
        'scenario': 'A test',
        'first_mes': 'Hello',
        'mes_example': '<START>\n{{user}}: Hi',
    }


def _v3_card(name='Hero', with_book_extensions=True):
    book = {'name': 'Book', 'entries': []}
    if with_book_extensions:
        book['extensions'] = {}
    return {
        'spec': 'chara_card_v3',
        'spec_version': '3.0',
        'data': {
            'name': name,
            'description': 'A character',
            'personality': 'Calm',
            'scenario': 'A test',
            'first_mes': 'Hello',
            'mes_example': '<START>\n{{user}}: Hi',
            'creator_notes': '',
            'system_prompt': '',
            'post_history_instructions': '',
            'alternate_greetings': [],
            'tags': [],
            'creator': '',
            'character_version': '',
            'extensions': {},
            'character_book': book,
        },
    }


def _v2_card_without_book_extensions(name='Hero'):
    """``character_book`` 缺 ``extensions`` 的 V2 卡片（SillyTavern 可正常导入）。"""
    card = _v3_card(name, with_book_extensions=False)
    card['spec'] = 'chara_card_v2'
    card['spec_version'] = '2.0'
    return card


def _b64(obj):
    return base64.b64encode(json.dumps(obj, ensure_ascii=False).encode('utf-8')).decode('utf-8')


def _name_of(info):
    """V1 卡片的名字在根层，V2/V3 在 ``data`` 里。"""
    if not info:
        return None
    return info.get('name') or (info.get('data') or {}).get('name')


def _write_png(path, chunks, extra=None):
    meta = PngImagePlugin.PngInfo()
    for key, value in (extra or []):
        meta.add_text(key, value)
    for key, value in chunks:
        meta.add_text(key, value)
    Image.new('RGBA', (8, 8), (0, 0, 0, 0)).save(str(path), 'PNG', pnginfo=meta)
    return path


def _read_text_chunks(path):
    """直接从 PNG 二进制里读出所有 tEXt 块，用于统计重复块数量。"""
    raw = path.read_bytes()
    assert raw[:8] == b'\x89PNG\r\n\x1a\n'

    chunks = []
    offset = 8
    while offset < len(raw):
        length = int.from_bytes(raw[offset:offset + 4], 'big')
        keyword = raw[offset + 4:offset + 8]
        body = raw[offset + 8:offset + 8 + length]
        if keyword == b'tEXt':
            name, _, value = body.partition(b'\x00')
            chunks.append((name.decode('latin-1'), value.decode('latin-1')))
        offset += 12 + length
    return chunks


def _pnginfo_keys(meta):
    return [chunk[1].split(b'\x00', 1)[0].decode('latin-1') for chunk in meta.chunks]


def test_ccv3_wins_over_chara_when_both_present(tmp_path):
    """两个块都可解析时，按 SillyTavern 的优先级采用 ccv3。"""
    path = _write_png(
        tmp_path / 'both.png',
        [
            ('chara', _b64(_v2_card_without_book_extensions('FromChara'))),
            ('ccv3', _b64(_v3_card(name='FromCcv3'))),
        ],
    )

    info, status = extract_card_info_with_status(str(path))

    assert status == 'ok'
    assert _name_of(info) == 'FromCcv3'


def test_v2_card_with_character_book_missing_extensions_is_readable(tmp_path):
    """回归：chara 块里 character_book 缺 extensions 的 V2 卡片应被判为有效。

    SillyTavern 的 importFromPng 只要求 PNG 文本块里是合法 JSON 且带 ``spec``
    标头；``character_book.extensions`` 在实际卡片里经常缺失。宿主曾要求它
    必须存在，导致这类卡片（例如用户反馈的 v0.4.png）导入时报
    「无法读取卡片元数据」。
    """
    card = _v2_card_without_book_extensions('FromChara')
    path = _write_png(tmp_path / 'v2_no_book_extensions.png', [('chara', _b64(card))])

    info, status = extract_card_info_with_status(str(path))

    assert status == 'ok'
    assert _name_of(info) == 'FromChara'
    assert info['data']['character_book']['name'] == 'Book'
    assert 'extensions' not in info['data']['character_book']


def test_chunk_file_order_does_not_affect_precedence(tmp_path):
    """优先级由块名决定，与文件中块的物理顺序无关。"""
    path = _write_png(
        tmp_path / 'reversed.png',
        [
            ('ccv3', _b64(_v3_card(name='FromCcv3'))),
            ('chara', _b64(_v2_card_without_book_extensions('FromChara'))),
        ],
    )

    info, status = extract_card_info_with_status(str(path))

    assert status == 'ok'
    assert _name_of(info) == 'FromCcv3'


def test_falls_back_to_chara_when_ccv3_is_unusable(tmp_path):
    """ccv3 无法解析或校验不通过时，退回 chara 而不是直接判为非卡片。"""
    undecodable = _write_png(
        tmp_path / 'ccv3_junk.png',
        [('ccv3', 'not-json-at-all'), ('chara', _b64(_v1_card('FromChara')))],
    )
    invalid = _write_png(
        tmp_path / 'ccv3_invalid.png',
        [
            ('ccv3', _b64({'spec': 'chara_card_v3', 'spec_version': '3.0'})),
            ('chara', _b64(_v1_card('FromChara'))),
        ],
    )

    for path in (undecodable, invalid):
        info, status = extract_card_info_with_status(str(path))
        assert status == 'ok', path
        assert _name_of(info) == 'FromChara', path


def test_chara_only_card_still_reads(tmp_path):
    path = _write_png(tmp_path / 'chara_only.png', [('chara', _b64(_v1_card('OnlyChara')))])

    info, status = extract_card_info_with_status(str(path))

    assert status == 'ok'
    assert _name_of(info) == 'OnlyChara'


def test_non_card_png_reports_not_a_card(tmp_path):
    path = _write_png(tmp_path / 'plain.png', [], extra=[('Software', 'ST-Manager')])

    info, status = extract_card_info_with_status(str(path))

    assert info is None
    assert status == 'not_a_card'


def test_write_emits_both_chunks_and_preserves_other_text(tmp_path):
    path = _write_png(
        tmp_path / 'src.png',
        [('chara', _b64(_v1_card()))],
        extra=[('Software', 'ST-Manager')],
    )

    assert write_card_metadata(str(path), _v3_card('Rewritten')) is True

    with Image.open(str(path)) as img:
        img.load()
        assert set(img.info) >= {'chara', 'ccv3'}
        assert img.info['Software'] == 'ST-Manager'
        chara = json.loads(base64.b64decode(img.info['chara']).decode('utf-8'))
        ccv3 = json.loads(base64.b64decode(img.info['ccv3']).decode('utf-8'))

    # 两个块都带 V3 标头，与 SillyTavern 的 write() 行为一致
    assert chara['spec'] == 'chara_card_v3'
    assert ccv3['spec'] == 'chara_card_v3'
    assert ccv3['spec_version'] == '3.0'

    info, status = extract_card_info_with_status(str(path))
    assert status == 'ok'
    assert _name_of(info) == 'Rewritten'


def test_write_strips_stale_card_chunks_instead_of_duplicating(tmp_path):
    """写回时旧块被丢弃，同一张 PNG 里只会留下各一个 chara/ccv3。"""
    path = _write_png(
        tmp_path / 'dupe.png',
        [('chara', _b64(_v1_card('Old'))), ('ccv3', _b64(_v3_card('Old')))],
    )

    assert write_card_metadata(str(path), _v3_card('New')) is True

    card_keys = [key.lower() for key, _ in _read_text_chunks(path) if key.lower() in ('chara', 'ccv3')]

    assert card_keys == ['chara', 'ccv3']


def test_build_card_pnginfo_drops_previous_card_chunks():
    meta = build_card_pnginfo(
        json.dumps(_v1_card('New')),
        metadata={'chara': 'stale-chara', 'ccv3': 'stale-ccv3', 'Software': 'ST-Manager'},
    )

    assert _pnginfo_keys(meta) == ['Software', 'chara', 'ccv3']


def test_encode_card_chunks_returns_chara_only_for_non_json():
    chunks = encode_card_chunks('definitely not json')

    assert [key for key, _ in chunks] == ['chara']


def test_encode_card_chunks_returns_both_for_json():
    chunks = encode_card_chunks(json.dumps(_v1_card()))

    assert [key for key, _ in chunks] == ['chara', 'ccv3']
    assert json.loads(base64.b64decode(dict(chunks)['ccv3']))['spec'] == 'chara_card_v3'


def test_iter_card_payloads_is_case_insensitive_and_prioritised():
    payloads = list(iter_card_payloads({'CHARA': 'a', 'CCv3': 'b'}))

    assert [key for key, _ in payloads] == ['CCv3', 'CHARA']


def test_iter_card_payloads_skips_empty_values():
    assert list(iter_card_payloads({'chara': '', 'ccv3': None})) == []


def test_build_card_pnginfo_ignores_non_string_text_chunks():
    meta = build_card_pnginfo(
        json.dumps(_v1_card()),
        metadata={'Software': 'x', 'icc_profile': b'bytes'},
    )

    assert _pnginfo_keys(meta) == ['Software', 'chara', 'ccv3']
