"""抽卡服务：稀有度派生、抽取、十连保底与卡池边界处理。

纯逻辑，不依赖 Flask 请求上下文，便于单测直接调用。

设计要点：
- 稀有度**完全由现有卡片字段派生**（收藏 + Token 分档），不引入新的持久化字段。
- Token 阈值与前端 ``static/js/utils/format.js`` 的 ``TOKEN_THRESHOLDS`` 保持一致，
  否则前端徽标分档与抽卡稀有度会互相矛盾。
- 抽取结果始终是**卡片副本**：``ctx.cache.cards`` 里的字典是缓存共享对象，
  直接写入 ``rarity`` 会污染缓存与列表接口。
"""

import random

# 与前端 TOKEN_THRESHOLDS 对齐：CARD_WARN / CARD_DANGER / EXTREME
TOKEN_WARN = 5000
TOKEN_DANGER = 20000
TOKEN_EXTREME = 100000

RARITY_N = 'N'
RARITY_R = 'R'
RARITY_SR = 'SR'
RARITY_SSR = 'SSR'
RARITY_UR = 'UR'

RARITY_ORDER = (RARITY_N, RARITY_R, RARITY_SR, RARITY_SSR, RARITY_UR)
HIGH_RARITIES = frozenset({RARITY_SR, RARITY_SSR, RARITY_UR})

# 抽卡支持的最大张数（单抽 / 十连）
MAX_DRAW_COUNT = 10

# 保底只对多连生效；单抽不改变基础概率。
PITY_MIN_COUNT = 2


def derive_rarity(card) -> str:
    """由现有字段派生稀有度。

    收藏视为最高档 UR；其余按 Token 数分四档，正好对应前端已有的四个等级。
    """
    if not isinstance(card, dict):
        return RARITY_N

    if card.get('is_favorite'):
        return RARITY_UR

    try:
        token_count = int(card.get('token_count') or 0)
    except (TypeError, ValueError):
        token_count = 0

    if token_count > TOKEN_EXTREME:
        return RARITY_SSR
    if token_count > TOKEN_DANGER:
        return RARITY_SR
    if token_count > TOKEN_WARN:
        return RARITY_R
    return RARITY_N


def normalize_count(value, *, default: int = 1) -> int:
    """把请求里的 count 规整到 ``1..MAX_DRAW_COUNT``。非法值回落为 default。"""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return default
    if count < 1:
        return default
    return min(count, MAX_DRAW_COUNT)


def draw_cards(candidates, count, *, apply_pity=True, rng=None) -> dict:
    """从候选中抽取 ``count`` 张卡，返回结果与卡池状态。

    返回 ``dict``：
    - ``cards``：卡片副本列表，每项附带 ``rarity``，重复项额外带 ``duplicate: True``
    - ``pool_size``：候选总数（前端据此提示「卡池不足」）
    - ``pool_exhausted``：候选不足 count 时为 True（本次使用了有放回抽取）
    - ``pity_applied``：是否真的触发了保底（卡池无高稀有度时为 False）

    卡池策略：
    - 候选 >= count：``random.sample`` 无放回，十连不重复。
    - 候选 <  count：``random.choices`` 有放回，重复项标 ``duplicate``。
      （真实抽卡里「重复」是常态，比直接报错更合理。）
    """
    pool = [card for card in (candidates or []) if isinstance(card, dict)]
    pool_size = len(pool)
    draw_count = normalize_count(count)

    if pool_size == 0 or draw_count < 1:
        return {
            'cards': [],
            'pool_size': 0,
            'pool_exhausted': False,
            'pity_applied': False,
        }

    picker = rng or random
    pool_exhausted = pool_size < draw_count

    if pool_exhausted:
        picks = list(picker.choices(pool, k=draw_count))
    else:
        picks = list(picker.sample(pool, draw_count))

    # 保底：把其中一位换成高稀有度。卡池没有高稀有度时静默跳过，不算失败。
    pity_applied = False
    if apply_pity and draw_count >= PITY_MIN_COUNT:
        high_pool = [card for card in pool if derive_rarity(card) in HIGH_RARITIES]
        if high_pool:
            pity_index = picker.randrange(draw_count)
            picks[pity_index] = picker.choice(high_pool)
            pity_applied = True

    # 复制后再写入派生字段，避免污染缓存里的共享字典。
    seen_ids = set()
    cards = []
    for card in picks:
        result = dict(card)
        result['rarity'] = derive_rarity(result)

        # 只在 id 存在时判定重复：无 id 的卡片互相之间不可比较，
        # 若按 None 去重会把不同卡片误标为重复。
        card_id = result.get('id')
        if card_id:
            if card_id in seen_ids:
                result['duplicate'] = True
            seen_ids.add(card_id)

        cards.append(result)

    return {
        'cards': cards,
        'pool_size': pool_size,
        'pool_exhausted': pool_exhausted,
        'pity_applied': pity_applied,
    }
