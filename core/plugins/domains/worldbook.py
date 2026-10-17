"""世界书域：`api.worldbook.*`。

来源形态（`source` 参数）与主程序路由层一致：

```python
{'source_type': 'global',   'file_path': 'lorebooks/book.json'}   # 全局世界书
{'source_type': 'resource', 'file_path': '…/lorebooks/book.json'} # 资源目录世界书
{'source_type': 'embedded', 'card_id': 'sub/card.json'}           # 卡片内嵌世界书
```

路径一律经边界校验：只有 `world_info_dir` 与资源目录下的 `lorebooks/`
才被接受，越界返回空。
"""

import json

from core.plugins.domains._base import DomainBase


class WorldbookDomain(DomainBase):
    """世界书读取、写回与条目历史。"""

    domain_name = 'worldbook'

    def _resolve(self, source) -> tuple:
        return self._api._resolve_worldbook_source(source)

    def read(self, source: dict):
        """读取世界书内容（global / resource / embedded 三类来源）。

        返回世界书对象（含 `source_revision`，写回时用作乐观锁）；无法解析返回 None。
        """
        return self._api._read_worldbook(source)

    def write(self, source: dict, data: dict, *, expected_revision: str = '') -> dict:
        """写回世界书（含 `source_revision` 乐观锁与条目历史记账）。

        Args:
            source: 世界书来源。
            data: 完整世界书对象（不是增量 patch）。
            expected_revision: 读取时拿到的 `source_revision`；与当前值不一致时
                返回 `{'success': False, 'error': 'revision_conflict'}`，不写入。

        Returns:
            `{'success': bool, 'source_revision': str, 'msg': str, 'error': str}`
        """
        return self._api._write_worldbook(source, data, expected_revision=expected_revision)

    def list_entries(self, source: dict) -> list:
        """列出世界书条目（读取的便捷投影，只返回 `entries` 列表）。

        条目里的 `uid` 缺失时会被就地补齐（与主程序保存路径口径一致），
        便于用 `history()` 查条目历史。
        """
        book = self.read(source)
        if not isinstance(book, dict):
            return []

        entries = book.get('entries')
        if isinstance(entries, dict):
            entries = list(entries.values())
        if not isinstance(entries, list):
            return []

        items = [item for item in entries if isinstance(item, dict)]
        try:
            from core.services.wi_entry_history_service import ensure_entry_uids

            if ensure_entry_uids({'entries': items}):
                # 补齐的 uid 需要落盘才能与历史记录对上
                kind = self._resolve(source)[0]
                if kind and kind != 'embedded':
                    updated = dict(book)
                    updated['entries'] = items
                    self.write(source, updated)
        except Exception:  # noqa: BLE001 - uid 补齐失败不应影响读取
            self._log('debug', '未知条目 uid 补齐失败')
        return items

    def history(self, source: dict, entry_uid) -> list:
        """读取某个世界书条目的历史版本（最新在前）。

        Returns:
            `[{'id': int, 'created_at': str, 'snapshot': dict}, …]`
        """
        kind, path, card_id = self._resolve(source)
        if not kind or not path:
            return []

        from core.services.wi_entry_history_service import list_entry_history_records

        if kind == 'embedded':
            return list_entry_history_records(
                source_type='card', source_id=card_id, file_path=path,
                entry_uid=entry_uid,
            )
        return list_entry_history_records(
            source_type='lorebook', source_id='', file_path=path,
            entry_uid=entry_uid,
        )

    # ------------------------------------------------------------ 内部

    def _record_history(self, path: str, data: dict) -> None:
        self._api._record_worldbook_history(path, data)
