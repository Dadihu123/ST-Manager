"""PNG 角色卡文本块（``chara`` / ``ccv3``）的读写规则。

这些规则必须与 SillyTavern 的 ``src/character-card-parser.js`` 保持一致：

- 读取时 ``ccv3`` **优先于** ``chara``（V3 覆盖 V2）。
- 写入时两个块都要写，先把旧的同名块移除。

本模块只依赖标准库与 Pillow，位于 ``core.utils.image`` 与
``core.utils.filesystem`` 之下，避免循环导入。
"""
import json
import base64

# 角色卡专用的 PNG 文本块关键字（按 SillyTavern 的优先级排列，越靠前越优先）
CCV3_KEY = 'ccv3'
CHARA_KEY = 'chara'
CARD_TEXT_KEYS = (CCV3_KEY, CHARA_KEY)

V3_SPEC = 'chara_card_v3'
V3_SPEC_VERSION = '3.0'


def is_card_text_key(key) -> bool:
    """判断某个 PNG 文本块关键字是否属于角色卡数据（不区分大小写）。"""
    return isinstance(key, str) and key.lower() in CARD_TEXT_KEYS


def iter_card_payloads(metadata):
    """按 SillyTavern 的优先级产出 ``(关键字, 载荷)``，``ccv3`` 在前。

    同一张卡片可能同时携带两个块。调用方应按顺序尝试，取第一个能解析成功的；
    这样既能保证 ``ccv3`` 优先（与 SillyTavern 一致），又能在 ``ccv3`` 损坏时
    退回到 ``chara``，不会把卡片误判成「非有效卡片」。
    """
    if not metadata:
        return

    lowered = {}
    for key, value in metadata.items():
        if is_card_text_key(key) and value:
            lowered.setdefault(str(key).lower(), (key, value))

    seen = set()
    for key in CARD_TEXT_KEYS:
        entry = lowered.get(key)
        if entry is None:
            continue
        identity = id(entry[1])
        if identity in seen:
            continue
        seen.add(identity)
        yield entry


def iter_preserved_text_chunks(metadata):
    """产出除角色卡之外、可以安全保留的 PNG 文本块。"""
    if not metadata:
        return
    for key, value in metadata.items():
        if not isinstance(value, str) or is_card_text_key(key):
            continue
        yield key, value


def encode_card_chunks(json_str):
    """把卡片 JSON 字符串编码成要写入的文本块列表。

    与 SillyTavern 的 ``write()`` 一致：先写 ``chara``（原样），再尝试写
    ``ccv3``（把 ``spec`` / ``spec_version`` 改成 V3 标头）。``ccv3`` 构造失败时
    只返回 ``chara``，不影响主流程。
    """
    chunks = [(CHARA_KEY, base64.b64encode(json_str.encode('utf-8')).decode('utf-8'))]

    try:
        v3_data = json.loads(json_str)
        v3_data['spec'] = V3_SPEC
        v3_data['spec_version'] = V3_SPEC_VERSION
        v3_str = json.dumps(v3_data, ensure_ascii=False, separators=(',', ':'))
        chunks.append((CCV3_KEY, base64.b64encode(v3_str.encode('utf-8')).decode('utf-8')))
    except Exception:
        # 无法解析成 JSON 时跳过 V3 块（与 SillyTavern 的 try/catch 行为一致）
        pass

    return chunks


def build_card_pnginfo(json_str, metadata=None, pnginfo_cls=None):
    """构造写入用的 ``PngInfo``：保留其他文本块，并写入 ``chara`` 与 ``ccv3``。

    ``pnginfo_cls`` 仅用于测试时注入替身，默认使用 Pillow 的 ``PngInfo``。
    与 SillyTavern 的 ``write()`` 一致，原来的同名块会被覆盖而不是追加，
    因此调用方直接传完整的 ``img.info`` 即可，不需要自己过滤。
    """
    if pnginfo_cls is None:
        from PIL import PngImagePlugin
        pnginfo_cls = PngImagePlugin.PngInfo

    meta = pnginfo_cls()

    for key, value in iter_preserved_text_chunks(metadata):
        meta.add_text(key, value)

    for key, value in encode_card_chunks(json_str):
        meta.add_text(key, value)

    return meta


# 允许大型角色卡：压缩图像流不驻留内存；所有文本合计最多 128 MiB。
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
MAX_PNG_BYTES = 2 * 1024 ** 3
MAX_TEXT_BYTES = 128 * 1024 ** 2
PNG_COPY_BUFFER = 1024 * 1024


class PngFormatError(ValueError):
    """PNG 流损坏或超出预算；不能按空卡覆盖。"""


def _inflate_text(data, remaining):
    import zlib
    try:
        decoder = zlib.decompressobj()
        result = decoder.decompress(data, remaining + 1)
        if len(result) > remaining or decoder.unconsumed_tail or decoder.unused_data or not decoder.eof:
            raise PngFormatError('PNG text exceeds decompression budget or is truncated')
        return result
    except zlib.error as exc:
        raise PngFormatError('Invalid compressed PNG text') from exc


def _decode_text(kind, data, remaining):
    try:
        key, value = data.split(b'\0', 1)
        if not 1 <= len(key) <= 79:
            raise PngFormatError('Invalid PNG text keyword')
        if kind == b'zTXt':
            if not value or value[0] != 0:
                raise PngFormatError('Invalid PNG text compression method')
            value = _inflate_text(value[1:], remaining)
        elif kind == b'iTXt':
            flag, method = value[:2]
            if flag not in (0, 1) or method != 0:
                raise PngFormatError('Invalid international PNG text compression')
            _, _, value = value[2:].split(b'\0', 2)
            if flag:
                value = _inflate_text(value, remaining)
        if len(value) > remaining:
            raise PngFormatError('PNG text exceeds budget')
        return key.decode('latin-1'), value.decode('utf-8' if kind == b'iTXt' else 'latin-1')
    except (ValueError, IndexError) as exc:
        raise PngFormatError('Invalid PNG text') from exc


def _scan_png(path, *, output=None, replacements=None):
    """严格完整扫描，CRC 流式验证；可原样复制非角色块（含 APNG）。"""
    import hashlib
    import struct
    import zlib
    metadata = {}
    image_hash = hashlib.sha256(b'stm-image-v1')
    text_bytes = kept_text_bytes = total = 0
    seen_header = seen_data = False
    with open(path, 'rb') as source:
        if source.read(8) != PNG_SIGNATURE:
            raise PngFormatError('Invalid PNG signature')
        if output:
            output.write(PNG_SIGNATURE)
        while True:
            header = source.read(8)
            if len(header) != 8:
                raise PngFormatError('Truncated PNG chunk header')
            length, kind = struct.unpack('>I4s', header)
            total += length + 12
            if length > 0x7fffffff or total > MAX_PNG_BYTES:
                raise PngFormatError('PNG exceeds stream budget')
            if not seen_header and (kind != b'IHDR' or length != 13):
                raise PngFormatError('PNG must start with IHDR')
            if seen_header and kind == b'IHDR':
                raise PngFormatError('Duplicate PNG header')
            if len(kind) != 4 or not all(65 <= byte <= 90 or 97 <= byte <= 122 for byte in kind):
                raise PngFormatError('Invalid PNG chunk type')
            if kind[0] < 97 and kind not in (b'IHDR', b'PLTE', b'IDAT', b'IEND'):
                raise PngFormatError('Unsupported critical PNG chunk')
            seen_header = True
            is_text = kind in (b'tEXt', b'zTXt', b'iTXt')
            if is_text and length > MAX_TEXT_BYTES - text_bytes:
                raise PngFormatError('PNG text exceeds read budget')
            # 先读关键字判断角色块，其余大块始终分段处理。
            prefix = source.read(min(length, 81))
            if len(prefix) != min(length, 81):
                raise PngFormatError('Truncated PNG chunk')
            key = prefix.split(b'\0', 1)[0].decode('latin-1') if is_text else ''
            keep = not (replacements is not None and is_card_text_key(key))
            if output and keep:
                output.write(header)
            # 保守地包含所有非文本块，覆盖 PLTE/tRNS/ICC/gamma/APNG 等渲染信息。
            rendered = not is_text and kind not in (b'tIME', b'IEND')
            if rendered:
                image_hash.update(header)
            crc = zlib.crc32(kind)
            remaining = length
            parts = []
            block = prefix
            while remaining:
                if not block:
                    raise PngFormatError('Truncated PNG chunk data')
                remaining -= len(block)
                crc = zlib.crc32(block, crc)
                if rendered:
                    image_hash.update(block)
                if is_text:
                    parts.append(block)
                if output and keep:
                    output.write(block)
                block = source.read(min(PNG_COPY_BUFFER, remaining)) if remaining else b''
            checksum = source.read(4)
            if len(checksum) != 4 or struct.unpack('>I', checksum)[0] != crc & 0xffffffff:
                raise PngFormatError('PNG chunk CRC mismatch')
            if output and keep:
                output.write(checksum)
            if is_text:
                key, value = _decode_text(kind, b''.join(parts), MAX_TEXT_BYTES - text_bytes)
                text_cost = max(length, len(value.encode('utf-8')) + len(key.encode('latin-1')) + 1)
                if text_cost > MAX_TEXT_BYTES - text_bytes:
                    raise PngFormatError('PNG text exceeds read budget')
                text_bytes += text_cost
                if keep:
                    kept_text_bytes += text_cost
                # 与旧 metadata 字典一致：同名块最后一个生效，大小写变体保留顺序。
                metadata[key] = value
            if kind == b'IDAT':
                seen_data = True
            if kind == b'IEND':
                if length or not seen_data:
                    raise PngFormatError('Invalid PNG end/data')
                if output and replacements is not None:
                    replacement_bytes = sum(len(key.encode('latin-1')) + 1 + len(value.encode('latin-1')) for key, value in replacements)
                    replacement_stream_bytes = sum(13 + len(key) + len(value) for key, value in replacements)
                    if kept_text_bytes + replacement_bytes > MAX_TEXT_BYTES:
                        raise PngFormatError('Replacement PNG text exceeds read budget')
                    if output.tell() + replacement_stream_bytes > MAX_PNG_BYTES + 8:
                        raise PngFormatError('Replacement PNG exceeds stream budget')
                    # IEND 已复制，后退并在其前插入新角色文本。
                    output.seek(-12, 1)
                    for key, value in replacements:
                        data = key.encode('latin-1') + b'\0' + value.encode('latin-1')
                        output.write(struct.pack('>I', len(data)) + b'tEXt' + data)
                        output.write(struct.pack('>I', zlib.crc32(b'tEXt' + data) & 0xffffffff))
                    output.write(header + checksum)
                if source.read(1):
                    raise PngFormatError('Unexpected data after PNG end')
                return metadata, image_hash.hexdigest()


def read_png_text(path):
    return _scan_png(path)[0]


def png_image_revision(path):
    return _scan_png(path)[1]


def rewrite_png_text(path, json_str, destination=None):
    """同目录临时文件 + fsync + replace；失败时原文件保持完整。"""
    import os
    import tempfile
    target = os.fspath(destination or path)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w+b', dir=os.path.dirname(os.path.abspath(target)),
                                         prefix='.stm-png-', delete=False) as output:
            temp_path = output.name
            _scan_png(path, output=output, replacements=encode_card_chunks(json_str))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp_path, target)
        temp_path = None
        if os.name != 'nt':
            fd = os.open(os.path.dirname(os.path.abspath(target)), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        return True
    finally:
        if temp_path is not None:
            os.unlink(temp_path)
