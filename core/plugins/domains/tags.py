"""标签域：`api.tags.*`。

标签库（`library()`）是从 `card_metadata.tags` **聚合**出来的；
分类体系（taxonomy）与治理偏好（prefs）存在 `ui_data`。

> `create()` 的语义是**单一**的：只把标签写进分类体系，**不碰任何卡片**。
> 要同时给卡片打标签，调用方自己再调 `api.cards.apply_tags(...)`——可组合。
"""

from core.plugins.domains._base import DomainBase


class TagDomain(DomainBase):
    """标签库读取、分类体系与治理偏好读写、标签创建与合并。"""

    domain_name = 'tags'

    def library(self) -> dict:
        """读取标签库：全部标签、排序、分类体系与治理偏好。

        Returns:
            `{'tags': [...], 'order': [...], 'order_enabled': bool,
              'order_enabled_keys': list|None, 'taxonomy': dict, 'prefs': dict}`
        """
        return self._api._read_tag_library()

    def taxonomy(self) -> dict:
        """读取标签分类体系（`ui_data` 里的 `tag_to_category` / `category_tag_order`）。"""
        return self._api._read_tag_taxonomy()

    def update_taxonomy(self, patch: dict) -> bool:
        """更新标签分类体系。

        `patch` **浅合并**到当前分类体系上（未提到的键保持原值），
        写入走 `ui_data` 的锁内合并，不会与宿主 UI 的并发写丢更新。
        """
        return self._api._update_tag_taxonomy(patch)

    def prefs(self) -> dict:
        """读取标签治理偏好（`tag_blacklist` / `lock_tag_library` 等）。"""
        return self._api._read_tag_prefs()

    def update_prefs(self, patch: dict) -> bool:
        """更新标签治理偏好（浅合并）。"""
        return self._api._update_tag_prefs(patch)

    def create(self, tags) -> dict:
        """把标签加入分类体系（**不写任何卡片**）。

        已存在于标签库或分类体系里的标签会被识别为 `existing`，不重复添加。

        Returns:
            `{'created': [...], 'existing': [...], 'failed': [...]}`
        """
        return self._api._create_tags(tags)

    def merge(self, replace_rules) -> dict:
        """按规则合并标签（复用 `core/automation/tag_merge.py`，含链式解析与环检测）。

        `replace_rules` 支持 `{'旧标签': '新标签'}` 或 `'旧1|旧2 → 新'` 文本形态。
        本方法**只计算合并结果**，不写卡片——要落盘由调用方调
        `api.cards.apply_tags(..., replace=True)`。

        Returns:
            `{'tags': [...], 'changed': bool, 'replacements': [{'from', 'to'}],
              'replace_rules': dict, 'cycles': [...]}`
        """
        return self._api._merge_tags(replace_rules)
