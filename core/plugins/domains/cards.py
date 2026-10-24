"""卡片域：`api.cards.*`。

覆盖：读取、字段改写、标签写入、本地备注、移动与分类、结构化查询、扩展归一。

一致性机制（卡片锁、`suppress_fs_events`、缓存/DB/索引三处同步、路径边界校验）
全部由 `PluginAPI` 的唯一实现转发，域内不重复实现。
"""

from core.plugins.domains._base import DomainBase


class CardDomain(DomainBase):
    """角色卡的读、写、移动、查询与备注。"""

    domain_name = 'cards'

    # ------------------------------------------------------------ 读取

    def read(self, card_id: str):
        """读取角色卡完整数据（含内嵌世界书）。

        返回 `None` 表示卡片不存在或路径越界。
        """
        return self._api._read_card(card_id)

    def read_many(self, card_ids) -> dict:
        """批量读取角色卡，返回 `{card_id: card|None}`。"""
        return self._api._read_cards(card_ids)

    def read_extensions(self, card_id: str) -> dict:
        """读取卡片扩展字段的**归一化**视图。

        卡片里的正则脚本与 ST 脚本藏在 `data.extensions`，而 ST 历史上用过
        大量别名键（`regex_scripts` / `regex` / `regular_expressions` /
        `tavern_helper` / `tavernHelper` / `scripts` …）。本方法把它们归一到
        唯一形状，插件不必自己写兼容：

        ```python
        {'regex_scripts': [...], 'tavern_helper': {'scripts': [...], 'variables': {...}}}
        ```

        卡片不存在时返回 `{}`。
        """
        card = self.read(card_id)
        if not isinstance(card, dict):
            return {}

        data_block = card.get('data') if isinstance(card.get('data'), dict) else card
        extensions = data_block.get('extensions')
        if not isinstance(extensions, dict):
            return {}

        from core.services.preset_extensions import (
            extract_regex_script_items,
            extract_tavern_helper_scripts,
            normalize_extensions_for_save,
        )

        normalized = normalize_extensions_for_save(extensions)
        return {
            'regex_scripts': extract_regex_script_items(extensions),
            'tavern_helper': {
                'scripts': extract_tavern_helper_scripts(extensions),
                'variables': (normalized.get('tavern_helper') or {}).get('variables', {}),
            },
        }

    # ------------------------------------------------------------ 写入

    def write_fields(self, card_id: str, patch: dict) -> bool:
        """改写角色卡字段（内部：卡片锁 + `suppress_fs_events` + 缓存/索引同步）。

        只有 `name` / `description` / `first_mes` / `mes_example` / `creator` /
        `character_version` / `tags` / `alternate_greetings` / `system_prompt` /
        `post_history_instructions` / `personality` / `scenario` / `creator_notes`
        这些键会被写入；其余键静默忽略（含 `character_book`，世界书请走
        `api.worldbook.*`）。

        本地备注不在卡片文件里，请用 `write_note()`。
        """
        return self._api._write_card_fields(card_id, patch)

    def apply_tags(self, card_ids, *, add=(), remove=(), replace: bool = False) -> dict:
        """批量写入标签。

        **默认合并**（`replace=False`），不清空既有标签；`replace=True` 才整组替换。
        新增标签会经过标签治理过滤（黑名单 / 标签库锁），被过滤的标签在返回值的
        `skipped_unknown` / `skipped_blacklist` 里。

        Returns:
            `{'updated', 'added', 'removed', 'failed', 'skipped_unknown', 'skipped_blacklist'}`
        """
        return self._api._apply_tags(card_ids, add=add, remove=remove, replace=replace)

    # ------------------------------------------------------------ 本地备注

    def read_note(self, card_id: str) -> str:
        """读本地备注（卡片网格里「本地备注」那一栏）；无备注返回空串。

        备注不存在卡片文件里，而在 `ui_data[<ui_key>]`：
        bundle 卡片走版本级备注（`_version_remarks`），插件不必知道这个细节。
        """
        return self._api._read_card_note(card_id)

    def read_notes(self, card_ids) -> dict:
        """批量读本地备注，返回 `{card_id: text}`（无备注为 `''`）。"""
        result = {}
        for card_id in card_ids or []:
            key = str(card_id or '').strip().replace('\\', '/')
            if not key:
                continue
            result[key] = self.read_note(key)
        return result

    def write_note(self, card_id: str, text: str) -> bool:
        """写本地备注（走 `ui_data` 的锁内合并，不会与宿主 UI 的并发写丢更新）。

        卡片不存在或 `ui_data` 写入失败时返回 `False`。
        """
        return self._api._write_card_note(card_id, text)

    # ------------------------------------------------------------ 移动与分类

    def move(self, card_ids, target_category: str) -> dict:
        """批量移动卡片到分类（空串表示根目录）。

        内部照抄主程序 `/api/move_card` 的完整流程：fs 事件抑制、路径安全校验、
        DB 与 `ui_data` 前缀同步、缓存增量更新，并派发 `card.moved` hook。

        Args:
            card_ids: 卡片 id 列表（相对 `CARDS_FOLDER`）。
            target_category: 目标分类路径；`'根目录'` 等价于空串。

        Returns:
            `{'count': int, 'moved': [{'old_id', 'new_id', 'new_category'}],
              'failed': [{'old_id', 'msg'}], 'category_counts': dict}`
        """
        return self._api._move_cards(card_ids, target_category)

    def list_categories(self) -> list:
        """全部分类（含子分类），相对 `CARDS_FOLDER`，按路径升序。

        每项为 `{'path': str, 'name': str, 'count': int}`：`path` 是完整相对路径，
        `name` 是叶子名，`count` 直接取缓存索引 `category_counts` 里该 path 的值（没有则 0）。
        """
        return self._api._list_categories()

    def create_category(self, name: str, *, parent: str = '') -> bool:
        """创建分类目录（已存在时返回 `True`，幂等）。

        `name` 允许 `a/b` 形式的相对路径，缺失的父级目录会自动补齐；`parent` 是
        相对父路径。分类名来自调用方（很可能是 AI 输出），因此逐段做**白名单校验**：
        拒绝 `..`、绝对路径、空段、Windows 非法字符（`/:*?"<>|`；`\\` 先归一成 `/`）、
        超长名（>64）与保留名（`notes` / `backups` / `lorebooks` / `thumbnails` /
        `cards` / `trash`）。非法时返回 `False`，不落盘。
        """
        return self._api._create_category(name, parent=parent)

    def rename_category(self, old_path: str, new_path: str) -> bool:
        """重命名 / 移动分类（含 DB 与 `ui_data` 前缀迁移）。

        `new_path` 是完整的新分类路径（可以换父级）。校验口径同 `create_category`。
        """
        return self._api._rename_category(old_path, new_path)

    # ------------------------------------------------------------ 结构化查询

    def list(
        self, *, query: str = '', category: str = '', tags=(), exclude_tags=(),
        limit: int = 100, offset: int = 0, sort: str = '', **filters,
    ) -> dict:
        """结构化查询卡片（走索引，不用裸 SQL、不做全表扫）。

        Args:
            query: 搜索词；`search_mode='fulltext'` 时走 FTS5。
            category: 分类前缀（含子分类）。
            tags: 必须包含的标签（全部满足）。
            exclude_tags: 必须排除的标签。
            limit / offset: 分页；`limit=0` 表示不设上限（内部仍受行数保护）。
            sort: 排序键，见 `api.index.search` 的说明；省略时按更新时间倒序。
            其余关键字（`search_mode` / `search_scope` / `fav_filter` /
            `token_min` / `token_max`）直接透传给索引查询服务。

        Returns:
            `{'items': [...], 'total': int, 'index_ready': bool}`
        """
        return self._api._list_cards(
            query=query, category=category, tags=tags, exclude_tags=exclude_tags,
            limit=limit, offset=offset, sort=sort, **filters,
        )

    def count(self, **filters) -> int:
        """按与 `list()` 相同的筛选条件计数（只取总数，不拉数据）。"""
        return self._api._count_cards(**filters)
