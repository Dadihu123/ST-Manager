"""构造截图用的确定性数据（一次性脚本，产物落在 data/ 下，不进版本库）。

截图需要稳定的「好看」内容：卡片池、世界书、聊天、预设、美化包。
脚本幂等：已存在的文件不覆盖，缺失的才生成。

跑法：
    python tools/seed_screenshot_data.py
"""

import json
import os
import random
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CARDS_DIR = os.path.join(ROOT, 'data', 'library', 'characters', '测试卡池')
WI_DIR = os.path.join(ROOT, 'data', 'library', 'lorebooks')
CHATS_DIR = os.path.join(ROOT, 'data', 'library', 'chats')
PRESETS_DIR = os.path.join(ROOT, 'data', 'library', 'presets')

rng = random.Random(20261025)


def png_bytes(width, height, rgb, text_chunks=None):
    """生成一张纯色 PNG（可选 tEXt 块），用于补齐缺少图片的测试卡。"""
    raw = b''
    for _ in range(height):
        raw += b'\x00' + bytes(rgb) * width

    def chunk(tag, payload):
        data = tag + payload
        return struct.pack('>I', len(payload)) + data + struct.pack('>I', zlib.crc32(data) & 0xFFFFFFFF)

    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    out = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
    for key, value in (text_chunks or {}).items():
        out += chunk(b'tEXt', key.encode('latin-1') + b'\x00' + value.encode('latin-1'))
    out += chunk(b'IDAT', zlib.compress(raw, 6))
    out += chunk(b'IEND', b'')
    return out


def write_if_missing(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return False
    mode = 'wb' if isinstance(payload, bytes) else 'w'
    if mode == 'wb':
        with open(path, 'wb') as handle:
            handle.write(payload)
    else:
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(payload)
    return True


LOREM = (
    '在这个世界里，记忆是可以被交易的货币。你作为刚刚抵达此地的旅人，'
    '需要用自己的过去换取一个立足之地。'
)

CARDS = [
    ('01_星见 小夜', '星见 小夜', 8200, ['都市', '悬疑'], '观测星空的天文社少女，说话总带着一层留白。'),
    ('02_雾雨 铃', '雾雨 铃', 24000, ['学院', '日常'], '雨季转学生，随身带着一把不会干的伞。'),
    ('03_白银 澪', '白银 澪', 46000, ['学院', '竞技'], '学生会会计，用数字衡量一切，包括感情。'),
    ('04_苍崎 灯里', '苍崎 灯里', 128000, ['学院', '奇幻'], '图书馆深处的管理人，记得每一本没被写完的书。'),
    ('05_黑羽 千夏', '黑羽 千夏', 18000, ['都市', '战斗'], '夜间巡逻的巡查员，习惯把危险说成「加班」。'),
    ('06_神代 凛', '神代 凛', 31000, ['都市', '悬疑'], '古董店的店主，收的从来不是钱。'),
    ('07_月读 命', '月读 命', 64000, ['幻想', '神话'], '月面的记录者，负责把人间传说抄进星图。'),
    ('08_天穹 织姬', '天穹 织姬', 210000, ['幻想', '神话'], '织补天穹裂隙的织者，线用完了就用自己的影子。'),
    ('09_艾莉丝·薇尔', '艾莉丝·薇尔', 9600, ['特别', '西幻'], '边境的药草师，药箱里总有一只不听话的猫。'),
    ('10_诺瓦·星辰', '诺瓦·星辰', 52000, ['特别', '科幻'], '报废空间站的唯一乘务员，仍在按时刻表广播。'),
    ('11_「深渊回响」终末观测者·阿卡夏记录', '阿卡夏记录', 420000, ['幻想', '史诗'], '记录世界终末的观测者，本卡用于测试超长 Token 显示。'),
    ('12_无名旅人', '无名旅人', 3200, ['特别', '日常'], '没有名字也没有过去的旅人，适合作为最小卡片样本。'),
]

FOLDERS = {
    '01_星见 小夜': '',
    '02_雾雨 铃': '',
    '03_白银 澪': '学院',
    '04_苍崎 灯里': '学院',
    '05_黑羽 千夏': '都市',
    '06_神代 凛': '都市',
    '07_月读 命': '幻想',
    '08_天穹 织姬': '幻想',
    '09_艾莉丝·薇尔': '特别',
    '10_诺瓦·星辰': '特别',
    '11_「深渊回响」终末观测者·阿卡夏记录': '幻想',
    '12_无名旅人': '',
}

PALETTE = [
    (58, 92, 148), (96, 74, 140), (44, 118, 118), (140, 78, 96),
    (72, 104, 68), (128, 96, 56), (60, 76, 120), (110, 62, 110),
    (48, 108, 96), (132, 88, 68), (78, 70, 124), (100, 100, 108),
]


def make_card_payload(name, tokens, tags, summary, index):
    book = {
        'name': f'{name} 的世界书',
        'entries': {},
        'extensions': {},
    }
    for slot in range(1, 4):
        book['entries'][str(slot)] = {
            'uid': slot,
            'key': [f'{name}设定{slot}'],
            'keysecondary': [],
            'comment': f'{name} · 设定 {slot}',
            'content': f'{LOREM} 这是 {name} 的第 {slot} 条世界书设定。' * (3 + slot),
            'constant': False,
            'selective': True,
            'selectiveLogic': 0,
            'order': 100 + slot,
            'position': 0,
            'disable': slot == 3,
            'probability': 100,
            'useProbability': True,
            'depth': 4,
            'group': '',
            'scanDepth': None,
            'caseSensitive': None,
            'matchWholeWords': None,
        }

    data = {
        'name': name,
        'description': f'{summary}\n\n{LOREM}',
        'personality': '克制、好奇、偶尔固执。',
        'scenario': '雨停之前，两个人在同一处屋檐下等车。',
        'first_mes': f'「你也是被这场雨困住的吗？」{name} 把伞往旁边挪了挪。',
        'mes_example': '<START>\n{{user}}: 你为什么还留在这里？\n{{char}}: 因为还没等到要等的人。',
        'creator_notes': '截图用测试卡，数据全部为构造内容。',
        'system_prompt': '',
        'post_history_instructions': '',
        'alternate_greetings': ['「别急着走，雨还要下一会儿。」', '「伞给你，我习惯淋雨。」'],
        'character_book': book,
        'tags': tags,
        'creator': 'ST-Manager 测试数据',
        'character_version': '1.0',
        'extensions': {},
    }
    card = {
        'spec': 'chara_card_v2',
        'spec_version': '2.0',
        'data': data,
        'name': name,
        'description': data['description'],
        'personality': data['personality'],
        'scenario': data['scenario'],
        'first_mes': data['first_mes'],
        'mes_example': data['mes_example'],
        'tags': tags,
        'creator': data['creator'],
        'character_version': '1.0',
    }
    # 让 token_count 落进目标档位（渲染时后端会按正文重算，这里只保证数量级）
    filler = '设定文本。' * max(1, tokens // 40)
    card['data']['description'] += '\n\n' + filler
    card['description'] = card['data']['description']
    return card


def seed_cards():
    created = 0
    for index, (stem, name, tokens, tags, summary) in enumerate(CARDS):
        sub = FOLDERS[stem]
        base = os.path.join(CARDS_DIR, sub) if sub else CARDS_DIR
        json_path = os.path.join(base, f'{stem}.json')
        png_path = os.path.join(base, f'{stem}.png')

        card = make_card_payload(name, tokens, tags, summary, index)
        payload = json.dumps(card, ensure_ascii=False, indent=2)
        if write_if_missing(json_path, payload):
            created += 1

        if not os.path.exists(png_path):
            color = PALETTE[index % len(PALETTE)]
            embed = json.dumps({'spec': 'chara_card_v2', 'spec_version': '2.0', 'data': card['data']}, ensure_ascii=False)
            write_if_missing(
                png_path,
                png_bytes(512, 768, color, {'chara': embed}),
            )
    return created


WORLDBOOKS = [
    ('世界设定 · 灰塔纪元', 8),
    ('都市异闻录', 6),
    ('学院人物关系', 5),
    ('幻想种族志', 7),
]


def seed_worldbooks():
    created = 0
    for name, entries in WORLDBOOKS:
        payload = {'entries': {}}
        for slot in range(1, entries + 1):
            payload['entries'][str(slot)] = {
                'uid': slot,
                'key': [f'{name}关键词{slot}', f'{name}别名{slot}'],
                'keysecondary': [],
                'comment': f'{name} · 条目 {slot}',
                'content': f'{LOREM} 这是《{name}》的第 {slot} 条条目，用于截图展示条目列表。',
                'constant': slot == 1,
                'selective': False,
                'order': 100 + slot,
                'position': 0,
                'disable': slot == entries,
                'probability': 100,
                'useProbability': True,
                'depth': 4,
            }
        path = os.path.join(WI_DIR, f'{name}.json')
        if write_if_missing(path, json.dumps(payload, ensure_ascii=False, indent=2)):
            created += 1
    return created


def seed_chats():
    created = 0
    chats = [
        ('星见 小夜 - 2026-10-20', '星见 小夜', 24),
        ('雾雨 铃 - 2026-10-21', '雾雨 铃', 16),
        ('黑羽 千夏 - 2026-10-22', '黑羽 千夏', 32),
    ]
    for file_stem, char, floors in chats:
        lines = [
            json.dumps({
                'user_name': 'You',
                'character_name': char,
                'create_date': '2026-10-20 @12h 00m 00s',
                'chat_metadata': {},
            }, ensure_ascii=False),
        ]
        for floor in range(floors):
            speaker = char if floor % 2 == 0 else 'You'
            lines.append(json.dumps({
                'name': speaker,
                'is_user': speaker == 'You',
                'is_system': False,
                'send_date': f'2026-10-20 @12h {floor:02d}m 00s',
                'mes': f'{LOREM} 第 {floor + 1} 层对话内容，用于截图展示阅读器排版。',
                'extra': {},
            }, ensure_ascii=False))
        path = os.path.join(CHATS_DIR, f'{file_stem}.jsonl')
        if write_if_missing(path, '\n'.join(lines) + '\n'):
            created += 1
    return created


def seed_presets():
    created = 0
    presets = [
        ('截图用 · 均衡叙事', 28),
        ('截图用 · 长上下文', 34),
    ]
    for name, prompts in presets:
        items = []
        for index in range(prompts):
            items.append({
                'identifier': f'prompt-{index}',
                'name': f'提示词 {index + 1:02d}',
                'role': 'system' if index % 3 else 'user',
                'content': f'{LOREM} 这是第 {index + 1} 条提示词。',
                'system_prompt': True,
                'marker': False,
                'enabled': index % 7 != 0,
                'injection_position': 0,
                'injection_depth': 4,
            })
        payload = {
            'name': name,
            'temperature': 0.8,
            'frequency_penalty': 0.2,
            'presence_penalty': 0.2,
            'openai_max_context': 128000,
            'openai_max_tokens': 4096,
            'top_p': 0.95,
            'prompts': items,
            'prompt_order': [{'character_id': 100001, 'order': [
                {'identifier': item['identifier'], 'enabled': item['enabled']} for item in items
            ]}],
            'extensions': {'regex_scripts': []},
        }
        path = os.path.join(PRESETS_DIR, f'{name}.json')
        if write_if_missing(path, json.dumps(payload, ensure_ascii=False, indent=2)):
            created += 1
    return created


def main():
    print('cards created:', seed_cards())
    print('worldbooks created:', seed_worldbooks())
    print('chats created:', seed_chats())
    print('presets created:', seed_presets())


if __name__ == '__main__':
    main()
