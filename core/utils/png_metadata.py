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
