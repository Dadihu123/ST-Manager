"""私有数据域：`api.private.*`（四层：命名空间 / 文件 / 表 / 只读查询）。

- **命名空间**（`read` / `update`）：只暴露 `_plugins_v1.<id>`，写入走
  `update_ui_data` 的锁内合并，避免与宿主 UI 的并发写丢更新。
- **文件**（`dir`）：`data/plugins/<id>/data/`，不在扫描器监视范围内。
- **表**（`migrate` / `table_prefix`）：表名与索引名强制 `plugin_<id>_` 前缀。
- **查询**（`query`）：能跑任意 **只读** SQL（这是放开能力），
  但**拒绝非 SELECT 语句**（这是机制内部化）。写入一律走域方法。

`query` 取代了原来的 `api.db()`：裸连接是机制泄漏，而真正需要它的两个场景
已由 `api.jobs.items()` / `api.cards.list()` 正式覆盖。
"""

import json
import re

from core.plugins import job_store
from core.plugins.domains._base import DomainBase

#: 只允许的只读语句起始关键字（`WITH` 用于 CTE 形式的 SELECT）
_READONLY_PATTERN = re.compile(r'^\s*(?:SELECT|WITH)\b', re.IGNORECASE)

#: 明确拒绝的写入/DDL 关键字（防止 `WITH … INSERT` 这类绕过）
_FORBIDDEN_PATTERN = re.compile(
    r'\b(INSERT|UPDATE|DELETE|REPLACE|DROP|ALTER|CREATE|TRUNCATE|ATTACH|DETACH|'
    r'VACUUM|REINDEX|PRAGMA|BEGIN|COMMIT|ROLLBACK|SAVEPOINT|GRANT|REVOKE)\b',
    re.IGNORECASE,
)

#: 单次查询返回行数上限（防止插件用一条 SELECT 拉爆内存）
_QUERY_ROW_LIMIT = 5000

_MIGRATION_PATTERN = re.compile(
    r'^\s*CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][A-Za-z0-9_]*)',
    re.IGNORECASE,
)


class PrivateDomain(DomainBase):
    """插件私有命名空间、私有目录、私有表与只读查询。"""

    domain_name = 'private'

    # ---------------------------------------------------------- 命名空间

    def read(self) -> dict:
        """只读快照：仅本插件的 `_plugins_v1.<id>` 命名空间。"""
        return self._api._ui_data_read()

    def update(self, mutator) -> bool:
        """在锁内修改本插件的命名空间（禁止直接读写整个 ui_data，避免 lost update）。

        `mutator(entry)` 收到本插件的命名空间字典；返回 dict 时整块替换，
        返回其他值（或 `None`）时按原地修改处理。超过体积配额时整次写入被拒绝
        并返回 `False`，磁盘内容保持不变。
        """
        return self._api._ui_data_update(mutator)

    # ---------------------------------------------------------- 文件

    def dir(self) -> str:
        """插件私有数据目录 `data/plugins/<id>/data/`（不存在时创建）。

        该目录**不在**扫描器/监控的监视范围内，写文件不需要 fs 事件抑制。
        """
        return self._api._data_dir()

    # ---------------------------------------------------------- 表

    def table_prefix(self) -> str:
        """插件私有表的强制前缀：`plugin_<id（连字符转下划线）>_`。"""
        return self._api._table_prefix()

    def migrate(self, statements) -> None:
        """执行建表语句；表名与索引名强制 `plugin_<id>_` 前缀。"""
        return self._api._migrate(statements)

    # ---------------------------------------------------------- 只读查询

    def query(self, sql: str, params=()) -> list:
        """执行**只读** SQL（主库），返回 `list[dict]`。

        能力面：可以查任意表（含 `card_metadata`、`plugin_jobs`、自己的私有表），
        不受域方法形状限制。
        机制面：**只接受 SELECT / WITH…SELECT**，其余语句一律抛 `ValueError`；
        一次调用只允许一条语句；返回行数上限 5000。

        写操作请走域方法（`cards.*` / `tags.*` / `worldbook.*` / `backups.*`），
        由域内部保证卡片锁、fs 抑制与缓存/索引同步。
        """
        text = str(sql or '').strip().rstrip(';').strip()
        if not text:
            raise ValueError('query 需要一条 SQL 语句')

        # 只允许单条语句：分号后还有内容说明调用方想跑多语句
        if ';' in str(sql or '').rstrip().rstrip(';'):
            raise ValueError('query 一次只允许执行一条语句')

        if not _READONLY_PATTERN.match(text):
            raise ValueError('query 只接受 SELECT 语句；写入请走对应的域方法')

        forbidden = _FORBIDDEN_PATTERN.search(text)
        if forbidden:
            raise ValueError(
                f'query 只接受只读 SELECT 语句，检测到不允许的关键字: '
                f'{forbidden.group(1).upper()}'
            )

        if isinstance(params, dict):
            param_seq = params
        elif params is None:
            param_seq = ()
        elif isinstance(params, (list, tuple)):
            param_seq = tuple(params)
        else:
            param_seq = (params,)

        conn = job_store.connect(ensure_schema=False)
        try:
            cursor = conn.execute(text, param_seq)
            rows = cursor.fetchmany(_QUERY_ROW_LIMIT)
            columns = [item[0] for item in (cursor.description or ())]
        finally:
            conn.close()

        return [dict(zip(columns, row)) for row in rows]
