"""备份域：`api.backups.*`。

快照是**破坏性操作的前置依赖**：域方法在内部执行破坏性写之前会先打一张快照，
用户才有回滚的余地。这些方法同时也是对插件公开的能力——插件可以主动给自己的
批量操作打快照。
"""

from core.plugins.domains._base import DomainBase


class BackupDomain(DomainBase):
    """角色卡快照的创建、列举与回滚。"""

    domain_name = 'backups'

    def snapshot_card(self, card_id: str, *, remark: str = '') -> str | None:
        """为角色卡创建快照，返回快照文件绝对路径（失败返回 None）。

        `remark` 会写进文件名（作为可检索标记），非法字符自动替换为 `-`。
        快照数量受设置项 `snapshot_limit_manual` 限制，超出时清理最旧的。
        """
        return self._api._snapshot_card(card_id, remark=remark)

    def list_card_snapshots(self, card_id: str) -> list:
        """列出该卡片的全部快照（最新在前）。

        同一秒内创建的多个快照按文件名（含微秒时间戳）倒序，顺序稳定。

        Returns:
            `[{'path', 'name', 'created_at', 'size', 'remark', 'is_auto'}, …]`
        """
        return self._api._list_card_snapshots(card_id)

    def restore_card_snapshot(self, card_id: str, snapshot_path: str) -> dict:
        """恢复快照（**恢复前自动再快照一次当前状态**，因此可回滚恢复本身）。

        Args:
            card_id: 目标卡片 id（快照会写回这个位置）。卡片文件已不存在时
                也可以恢复——等于把快照还原成卡片。
            snapshot_path: `list_card_snapshots()` 返回的 `path`。只接受该卡片
                自己备份目录里的文件，其它路径一律拒绝。

        Returns:
            `{'success': bool, 'msg': str, 'error': str, 'safety_snapshot': str}`；
            `error` 取值：`card_not_found` / `snapshot_not_found` /
            `snapshot_out_of_scope` / `restore_failed`。
        """
        return self._api._restore_card_snapshot(card_id, snapshot_path)
