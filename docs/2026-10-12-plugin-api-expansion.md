# 插件 API 全面放开方案（主程序适配清单）

> 消费者：`stm-ai-assistant`（AI 角色卡分析助手插件，**未发布**，无需兼容）。
> 本文是**主程序侧改动方案**，与插件侧文档
> `D:\Workspace\MyOwn\ST-Manager-AI-Assistant\docs\2026-10-12-capability-analysis.md` 配套。
>
> 参照体裁：`docs/2026-10-11-plugin-pet-capability-gap.md`（同类「能力缺口 + 宿主改动点」文档）。

---

## 0. 结论摘要

**现有 `PluginAPI` 只投影了服务层的一小部分，而插件系统的价值恰恰取决于这个投影的完整性。**

`core/plugins/api.py` 目前暴露 30 个公开方法，覆盖：配置、密钥、事件、HTTP、作业、
CLI、私有数据、卡片读写、标签库读取、世界书读写、快照、`ui_data`、日志。

但 `core/services/` 下有 50+ 个服务模块，`core/api/v1/` 下有 11 个蓝图
（`cards.py` 单文件 260KB），其中**大量能力插件拿不到**。结果是插件被迫用两种
劣质手段绕行：

| 绕行手段 | 实例 | 代价 |
|---|---|---|
| **内部模块 import** | `stm-ai-assistant/backend/summary_bridge.py:25-37` 直接 `from core.data.ui_store import update_ui_data` + `from core.services.card_service import resolve_ui_key` | 越过「PluginAPI 是唯一契约面」；主程序重构即静默降级 |
| **裸 SQL 查内部表** | `stm-ai-assistant/backend/jobs.py:85-119`（`SELECT tags FROM card_metadata`）、`routes.py:91-127`（`SELECT … FROM plugin_job_items`） | 依赖 `db()` 这个 Provisional 接口 + 表结构，schema 一变就崩 |

**核心判断**：这两条路都不是插件作者不守规矩，而是**契约面不足的必然结果**。
本次应把 `PluginAPI` 从「白名单子集」升级为「**服务层能力的完整投影**」。

**契约版本不需要升**（沿用 entry-unification §6.4 的裁定：纯增量、可选的能力
不构成不兼容变更）。

---

## 1. 原则：放开能力，机制内部化

用户的原话是「没必要放开一部分，禁止一部分」。这个方向是对的，但要落成可实施的
规则，需要区分两个层次：

| 层次 | 内容 | 态度 |
|---|---|---|
| **能力面**（能做什么） | 服务层的公开操作：读/写卡片、移动、改名、标签治理、世界书、会话、预设、正则、脚本、索引查询、快照、备份… | **全面放开** |
| **机制**（怎么做才不破坏一致性） | 卡片锁、`suppress_fs_events`、缓存/索引同步、`db_session` 重试、路径安全校验、原子写 | **内部化**，插件看不到也不该看到 |

`PluginAPI` 现有实现已经遵守这条原则（`core/plugins/api.py:513-546`
的 `write_card_fields` 内部处理了卡片锁 + fs 事件抑制 + 缓存/索引同步），
**只需把同一条原则贯彻到全部服务层能力上**。

这样「放开」不等于「放任」：

- 插件能移动卡片，但拿不到「怎么移动才不会让缓存和索引错乱」——那是 API 内部的事。
- 插件能改标签体系，但拿不到「怎么写 `ui_data` 才不丢更新」——那是 `ui_data_update` 的事。

**同时必须放开的还有「破坏性操作」**：删除卡片、删除世界书条目、批量覆盖。
这些是主程序自己路由层已经在做的事（`core/api/v1/cards.py` 等），
没有理由对插件关门。但见 §5 的「快照先行」约定。

---

## 2. 现状盘点：PluginAPI 覆盖了服务层的多少

### 2.1 已覆盖（够用）

下表左列是**现有扁平名**，右列是 §3.1 改造后的**新名**。

| 能力 | 现有 PluginAPI | 新契约 | 主程序实现 |
|---|---|---|---|
| 配置 | `get_config` / `set_config` | `config.get` / `config.set` | `api.py:137-168` |
| 密钥 | `get_secret` / `set_secret` / `list_secrets` | `secrets.get` / `.set` / `.list` | `core/plugins/secrets.py` |
| 事件 | `on` / `emit` | **不变** | `core/plugins/hooks.py` |
| HTTP | `route` / `blueprint` | `http.route` / `http.blueprint` | `api.py:232-285` |
| 作业 | `register_job` / `submit_job` / `get_job` / `cancel_job` / `retry_job` / `pause_job` / `resume_job` | `jobs.register` / `.submit` / `.get` / `.cancel` / `.retry` / `.pause` / `.resume` | `core/plugins/jobs.py` |
| 私有数据 | `db`（Provisional）/ `table_prefix` / `migrate` / `data_dir` | `private.query`（只读）/ `.table_prefix` / `.migrate` / `.dir` | `api.py:356-403` |
| 卡片读 | `read_card` / `read_cards` | `cards.read` / `cards.read_many` | `api.py:416-435` → `core/utils/image.py:179` |
| 卡片写 | `write_card_fields`（13 字段白名单）/ `apply_tags` | `cards.write_fields` / `cards.apply_tags` | `api.py:513-627` |
| 标签库读 | `read_tag_library` | `tags.library` | `api.py:629-654` |
| 世界书 | `read_worldbook` / `write_worldbook` | `worldbook.read` / `worldbook.write` | `api.py:679-788` |
| 快照 | `snapshot_card` | `backups.snapshot_card` | `api.py:819-868` |
| ui_data | `ui_data_read` / `ui_data_update` | `private.read` / `private.update` | `api.py:872-921` |
| 日志 | `notify` / `log` | `log.debug` / `.info` / `.warn` / `.error` | `api.py:948-974` |
| 机制泄漏 | `suppress_fs_events` | **删除**（内部化） | `api.py:925-944` |

### 2.2 缺口（AI 插件需要但拿不到）

| # | 缺口 | 插件现状 | 服务层实现（已存在） |
|---|---|---|---|
| G1 | **移动卡片 / 分类** | 做不到（无 API） | `card_service.move_card_internal(card_id, target_category)`（`card_service.py:1477`）；`cards.py:2235` `api_move_card`；`cards.py:5051` `api_create_folder` |
| G2 | **本地备注读写** | 内部 import `core.data.ui_store` | `ui_store` 的 `get_version_remark` / `set_version_remark`（`ui_store.py:2071` / `:2112`）；`cache.py:765-790` 的 `_enrich_card_ui` |
| G3 | **标签治理写** | 做不到 | `ui_store.set_tag_taxonomy`（`:1240`）/ `get_tag_taxonomy`（`:1233`）/ `set_tag_management_prefs`（`:1264`）/ `get_tag_management_prefs`（`:1257`）；`tag_management_service.py` |
| G4 | **后端 token 估算** | 自带同公式实现（`tokens.py:18-26`） | ⚠️ **不存在通用版本**：`core/utils/text.py:5` `calculate_token_count(card_data)` 接收的是**卡片字典**（聚合 name/description/first_mes/mes_example + 世界书），不是任意文本。需新增通用包装 |
| G5 | **卡片结构化查询** | 裸 SQL 查 `card_metadata` | `card_index_query_service.py`（`search` / 筛选 / 排序）、`worldinfo_index_query_service.py` |
| G6 | **扩展字段归一** | 做不到（`read_card` 返回原始 `extensions`） | `core/services/preset_extensions.py:81` `extract_tavern_helper_scripts` / `:122` `extract_regex_script_items` |
| G7 | **会话 / 预设 / 正则 / 脚本 读取** | 做不到 | `core/data/chat_store.py`、`preset_model.py`、`st_client.py:905-1330` |
| G8 | **快照列举 / 回滚** | 只能创建（`snapshot_card`），不能列出与恢复 | `core/utils/filesystem.py` 的 `cleanup_old_snapshots` / `write_snapshot_file`；备份目录约定见 `api.py:819-868` |
| G9 | **世界书条目历史** | 做不到 | `wi_entry_history_service.py` |
| G10 | **索引状态与重建** | 做不到 | `index_service.py` / `index_build_service.py` / `index_upgrade_service.py` |

---

## 3. 域命名空间设计（脚手架）

现有 `PluginAPI` 是**扁平方法名**（`read_card` / `apply_tags` / `read_worldbook`）。
继续扁平化会撞上两个问题：

1. 名字会越来越长（`move_cards_to_category` / `read_card_local_note` …）；
2. 无法表达「同一资源的多个操作」的归属，文档生成器的分组也会膨胀。

**采用域命名空间，并且不保留扁平别名。**

> **决策依据**：插件系统**从未发布**，现有两个插件（`stm-ai-assistant` /
> `stm-pet`）可以同步改写。因此没有兼容包袱，**直接改成正确的形状**
> 比「新名 + 旧名双份」更好：双份会让文档、生成器、测试都要维护两套，
> 且插件作者会不确定该用哪个。
>
> **副带收益**：不保留别名后，生成器不需要「双份登记」的概念——
> 只要新增一个 `BACKEND_DOMAINS` 结构即可（§3.4）。

### 3.1 新契约：完整 API 面

命名规则：**资源操作进命名空间；跨域惯用法（事件）保持顶层扁平**
（`on` / `emit` 与前端 `api.on` / `api.off` / `api.emit` 对齐，是 EventEmitter 惯用法）。

```python
# ---- 属性（实例属性，登记进 BACKEND_ATTRIBUTES）----
api.plugin_id, api.manifest, api.app_version

# ---- 事件（惯用法，保持扁平；与前端 on/off/emit 对齐）----
api.on(event, handler)
api.emit(event, payload)

# ---- 配置与密钥 ----
api.config.get() -> dict
api.config.set(patch) -> bool
api.secrets.get(key) -> str | None
api.secrets.set(key, value) -> bool
api.secrets.list() -> dict

# ---- 日志（把字符串 level 换成具名方法）----
api.log.debug(message, **extra)
api.log.info(message, **extra)
api.log.warn(message, **extra)
api.log.error(message, **extra)

# ---- HTTP ----
api.http.route(rule, methods=None)          # 装饰器
api.http.blueprint(bp) -> bool

# ---- 作业 ----
api.jobs.register(job_type, handler)
api.jobs.submit(job_type, *, items, payload=None) -> run_id
api.jobs.get(run_id) -> dict | None
api.jobs.items(run_id, *, status=None, limit=0, offset=0) -> list   # 新增，见下
api.jobs.cancel(run_id) -> bool
api.jobs.retry(run_id, *, only_failed=True) -> run_id
api.jobs.pause(run_id) -> bool
api.jobs.resume(run_id) -> bool

# ---- CLI ----
api.cli.register(name, handler, description='')

# ---- 私有数据（四层：命名空间 / 键值 / 文件 / 表）----
api.private.read() -> dict
api.private.update(mutator) -> bool
api.private.dir() -> str
api.private.query(sql, params=()) -> list   # 只读，语句类型校验
api.private.migrate(statements)
api.private.table_prefix() -> str

# ---- 卡片 ----
api.cards.read(card_id) -> dict | None
api.cards.read_many(card_ids) -> dict
api.cards.write_fields(card_id, patch) -> bool
api.cards.apply_tags(card_ids, *, add=(), remove=(), replace=False) -> dict
api.cards.read_note(card_id) -> str                    # P0-2
api.cards.write_note(card_id, text) -> bool            # P0-2
api.cards.read_notes(card_ids) -> dict                 # P0-2
api.cards.move(card_ids, target_category) -> dict      # P0-1
api.cards.list_categories() -> list                    # P0-1
api.cards.create_category(name) -> bool                # P0-1
api.cards.rename_category(old_path, new_path) -> bool  # P0-1
api.cards.list(**filters) -> dict                      # P1-1
api.cards.count(**filters) -> int                      # P1-1
api.cards.read_extensions(card_id) -> dict             # P1-2

# ---- 标签 ----
api.tags.library() -> dict                             # 原 read_tag_library
api.tags.taxonomy() -> dict                            # P0-3
api.tags.update_taxonomy(patch) -> bool                # P0-3
api.tags.prefs() -> dict                               # P0-3
api.tags.update_prefs(patch) -> bool                   # P0-3
api.tags.create(tags) -> dict                          # P0-3
api.tags.merge(replace_rules) -> dict                  # P0-3

# ---- 世界书 ----
api.worldbook.read(source) -> dict | None
api.worldbook.write(source, data, *, expected_revision='') -> dict
api.worldbook.list_entries(source) -> list             # P1
api.worldbook.history(source, entry_uid) -> list       # P2-4

# ---- 备份 ----
api.backups.snapshot_card(card_id, *, remark='') -> str | None
api.backups.list_card_snapshots(card_id) -> list       # P1-3
api.backups.restore_card_snapshot(card_id, path) -> bool  # P1-3

# ---- 索引 ----
api.index.status() -> dict                             # P1-4
api.index.search(query, *, scope='cards', limit=50) -> dict  # P1-4
api.index.rebuild(*, scope='cards') -> run_id          # P1-4

# ---- 其它资源（P2）----
api.chats.* / api.presets.* / api.extensions.*

# ---- token 估算 ----
api.estimate_tokens(text) -> int                       # P0-4（保持顶层，无归属域）
```

**顶层保留的扁平成员**：`on` / `emit`（事件惯用法）、`estimate_tokens`
（跨域工具）、以及三个属性。其余全部进命名空间。

### 3.2 两个「被消掉的」成员（不是改名，是删除）

| 原成员 | 处理 | 理由 |
|---|---|---|
| `db()` | **删除**，改为 `api.private.query(sql, params)`（只读 + 语句类型校验） | 裸连接是**机制泄漏**（§1）。真正需要它的两个场景都已用正规 API 覆盖：读 `plugin_job_items` → `api.jobs.items()`；读 `card_metadata` → `api.cards.list()` |
| `suppress_fs_events()` | **删除**（降为域内部机制） | 同上。插件写自己的 `data_dir()` 不需要它；写卡片/世界书走域方法时由域内部抑制。**当前两个插件都不需要它** |
| `notify(level, msg)` | **合并进 `api.log.*`** | 现有实现里 `notify` 就是 `log` 的纯转发（`api.py:948-950`），是冗余 |
| `snapshot_card` | 移到 `api.backups.*` | 概念归属是备份，不是卡片读写 |
| `table_prefix()` | 移到 `api.private.*` | 私有表前缀属于私有数据域 |

> **`db()` 删除的影响面**：`api.private.query` 仍保留「能跑任意只读 SQL」的能力
> （这是「放开能力」），但**拒绝非 SELECT 语句**（这是「机制内部化」）。
> 写入一律走域方法，由域保证一致性。

### 3.3 旧名 → 新名对照（迁移两个插件用）

| 旧 | 新 |
|---|---|
| `get_config()` / `set_config(p)` | `config.get()` / `config.set(p)` |
| `get_secret(k)` / `set_secret(k,v)` / `list_secrets()` | `secrets.get(k)` / `secrets.set(k,v)` / `secrets.list()` |
| `on` / `emit` | **不变** |
| `log(level, msg)` / `notify(level, msg)` | `log.info(msg)` / `log.warn(msg)` / `log.error(msg)` / `log.debug(msg)` |
| `route(rule, methods)` / `blueprint(bp)` | `http.route(...)` / `http.blueprint(...)` |
| `register_job(t, h)` | `jobs.register(t, h)` |
| `submit_job(t, items=, payload=)` | `jobs.submit(t, items=, payload=)` |
| `get_job(run_id)` | `jobs.get(run_id)` |
| `cancel_job` / `retry_job` / `pause_job` / `resume_job` | `jobs.cancel` / `jobs.retry` / `jobs.pause` / `jobs.resume` |
| `register_cli(n, h, d)` | `cli.register(n, h, d)` |
| `data_dir()` | `private.dir()` |
| `db()` | `private.query(sql, params)`（只读） |
| `migrate(stmts)` | `private.migrate(stmts)` |
| `table_prefix()` | `private.table_prefix()` |
| `ui_data_read()` / `ui_data_update(m)` | `private.read()` / `private.update(m)` |
| `read_card(id)` / `read_cards(ids)` | `cards.read(id)` / `cards.read_many(ids)` |
| `write_card_fields(id, p)` | `cards.write_fields(id, p)` |
| `apply_tags(ids, add=, remove=, replace=)` | `cards.apply_tags(...)`（签名不变） |
| `read_tag_library()` | `tags.library()` |
| `read_worldbook(src)` / `write_worldbook(src, data, expected_revision=)` | `worldbook.read(src)` / `worldbook.write(...)` |
| `snapshot_card(id, remark=)` | `backups.snapshot_card(id, remark=)` |
| `suppress_fs_events()` | **删除**（不再需要） |
| `estimate_tokens(text)` | **不变** |

### 3.4 关键约束（必须遵守，否则插件会误用）

- 域对象**每次访问返回同一个实例**（在 `PluginAPI.__init__` 里构造一次），
  不要在 `@property` 里 `new`——否则插件的 `isinstance` / 缓存会失效。
- 域对象**不持有密钥**：需要密钥的操作不接受 `api_key` 参数，
  由域内部通过 `api.secrets.get` 解析。
- 域对象**不接受 `card_id` 之外的原始路径**：路径一律走
  `_resolve_card_path`（`api.py:407-414`）做边界校验。
- 域对象**不缓存可变的宿主状态**：每次调用重新解析（卡片可能被移走）。

### 3.5 ⚠️ 域必须是「实例属性」而不是 `@property`（已实测验证）

这一条是**脚手架阶段的硬约束**，写错会立刻红两条测试。

`tools/gen_plugin_api_docs.py` 用**两条独立路径**收集 `PluginAPI` 的公开方法：

| 路径 | 实现 | 看到什么 |
|---|---|---|
| AST 静态解析 | `collect_source_defined_methods()`（`:553-565`）——遍历 `PluginAPI` 类体里的**全部** `FunctionDef`（名字不以 `_` 开头） | **会**看到 `@property def cards` |
| 运行时反射 | `collect_backend_api()`（`:173-176`）——`inspect.getmembers(PluginAPI, predicate=inspect.isfunction)` | **不会**看到 `@property`（property 对象不是 function） |

`tests/test_plugin_api_docs.py:70-72` 断言两者必须一致：

```python
def test_ast_and_introspection_agree_on_public_methods():
    assert collect_source_defined_methods() == collect_backend_api()['public']
```

**实测结果**（已运行验证）：

```
# 用 @property
AST  : ['cards', 'read_card']
反射 : ['read_card']
一致 : False          ← test_ast_and_introspection_agree_on_public_methods 失败

# 用实例属性（__init__ 里 self.cards = CardDomain(self)）
AST  : ['read_card']
反射 : ['read_card']
一致 : True           ← 通过
```

**结论**：域一律写成 `__init__` 里的实例属性。
`__init__` 里对域赋值不会产生 `FunctionDef`，AST 与反射都看不到，两边一致。

### 3.6 域方法如何进文档（第二个硬约束）

即使域是实例属性，**域方法仍无法直接登记进 `BACKEND_GROUPS`**：

```python
# tests/test_plugin_api_docs.py:58-64
for _title, _stability, methods in BACKEND_GROUPS:
    for entry in methods:
        name = entry[0] if isinstance(entry, tuple) else entry
        assert hasattr(PluginAPI, name), f'分组表引用了不存在的方法: {name}'
```

`hasattr(PluginAPI, 'move')` 为 `False`（`move` 在 `CardDomain` 上），
所以把 `'move'` 直接写进 `BACKEND_GROUPS` 会失败。

同时 `test_every_public_method_is_grouped`（`:50-55`）要求
**每个公开方法都要被登记**——域方法不在 `PluginAPI` 上，
所以它不会被算进 `public`，**不会**触发这条；但也因此**永远不会出现在文档里**。

**因此需要给生成器加一层「域 → 方法」登记**。建议结构：

```python
# tools/gen_plugin_api_docs.py
# 域分组：(域属性名, 展示名, [方法名…])
BACKEND_DOMAINS = [
    ('cards', '`api.cards.*`', [
        'read', 'read_many', 'write_fields', 'apply_tags',
        'read_note', 'write_note', 'read_notes',
        'move', 'list_categories', 'create_category', 'rename_category',
        'list', 'count', 'read_extensions',
    ]),
    ('tags', '`api.tags.*`', [
        'library', 'taxonomy', 'update_taxonomy', 'prefs', 'update_prefs',
        'create', 'merge',
    ]),
    ('worldbook', '`api.worldbook.*`', ['read', 'write', 'list_entries', 'history']),
    ('backups', '`api.backups.*`', [
        'snapshot_card', 'list_card_snapshots', 'restore_card_snapshot',
    ]),
    ('jobs', '`api.jobs.*`', [
        'register', 'submit', 'get', 'items',
        'cancel', 'retry', 'pause', 'resume',
    ]),
    ('private', '`api.private.*`', [
        'read', 'update', 'dir', 'query', 'migrate', 'table_prefix',
    ]),
    ('config', '`api.config.*`', ['get', 'set']),
    ('secrets', '`api.secrets.*`', ['get', 'set', 'list']),
    ('http', '`api.http.*`', ['route', 'blueprint']),
    ('cli', '`api.cli.*`', ['register']),
    ('log', '`api.log.*`', ['debug', 'info', 'warn', 'error']),
    ('index', '`api.index.*`', ['status', 'search', 'rebuild']),
    # P2 域：chats / presets / extensions
]
```

配套改动：

1. `collect_backend_api()` 增加对 `BACKEND_DOMAINS` 的遍历，
   用 `getattr(getattr(PluginAPI, domain), method)` 取函数与签名
   （复用现有的 `_format_signature`，它已处理 `self` 剥离）。
2. `test_grouped_methods_actually_exist` 增加域路径的 `hasattr` 校验
   （校验到域对象上）。
3. `render()` 增加域分组的渲染分支。
4. 域属性本身（`cards` / `tags` / …）作为**实例属性**登记到
   `BACKEND_ATTRIBUTES`（`:35-39`），那里本来就是给实例属性用的。

> **`BACKEND_ATTRIBUTES` 是现成的机制**：它已经在文档里渲染
> 「属性名 | 类型 | 稳定性 | 说明」表格，域属性天然适合放进去
> （类型写 `` `CardDomain` ``，说明写「卡片域，见下表」）。

> **不保留别名让这一步更简单**：不需要「扁平名与域方法同时登记」的概念，
> `BACKEND_GROUPS` 只留 `on` / `emit` / `estimate_tokens` 三项，
> 其余全部走 `BACKEND_DOMAINS`。若保留别名，则两个结构都要填一遍，
> 且 `test_every_public_method_is_grouped` 会同时约束两边。

### 3.7 脚手架落地步骤

```
core/plugins/
├─ api.py                  # PluginAPI 门面（只留 on/emit/estimate_tokens + 域属性）
├─ domains/
│  ├─ __init__.py          # 导出各域类
│  ├─ _base.py             # DomainBase：持有 api 引用 + 路径/锁/fs 抑制工具
│  ├─ cards.py             # CardDomain
│  ├─ tags.py              # TagDomain
│  ├─ worldbook.py         # WorldbookDomain
│  ├─ backups.py           # BackupDomain
│  ├─ jobs.py              # JobDomain
│  ├─ private.py           # PrivateDomain（命名空间 / 文件 / 表 / 只读查询）
│  ├─ config.py            # ConfigDomain
│  ├─ secrets.py           # SecretDomain
│  ├─ http.py              # HttpDomain
│  ├─ cli.py               # CliDomain
│  ├─ log.py               # LogDomain
│  ├─ index.py             # IndexDomain
│  ├─ chats.py             # ChatDomain（P2）
│  ├─ presets.py           # PresetDomain（P2）
│  └─ extensions.py        # ExtensionDomain（P2）
└─ ...
```

> **`api.py` 里 `PluginAPI` 类体只剩 3 个公开方法 + `__init__`**，
> 所以 `collect_source_defined_methods`（AST）与反射两边都只看到
> `['emit', 'estimate_tokens', 'on']`，天然一致（§3.5）。

`_base.py` 提供三个共享工具（所有域统一走它们，避免各域各写一份）：

```python
class DomainBase:
    def __init__(self, api):
        self._api = api

    def _resolve_card_path(self, card_id) -> str:
        """复用 PluginAPI._resolve_card_path，保持路径安全口径唯一。"""

    def _card_lock(self, card_id):
        """复用 ctx.get_card_lock；拿不到时返回 nullcontext。"""

    def _suppress_fs(self):
        """复用 PluginAPI.suppress_fs_events。"""

    def _sync_card_index(self, card_id, path, card_data):
        """复用 PluginAPI._sync_card_index，保持缓存/DB/索引三处同步口径唯一。"""
```

> **要点**：`_sync_card_index` 是现有实现里最容易漏掉的一环
> （`api.py:444-511` 同时更新内存缓存、`card_metadata` 行、增量索引）。
> 新域必须复用它，**不要各写一份**——否则会出现「插件移动卡片后列表不刷新」
> 这类难查的 bug。

---

## 4. 缺口清单与宿主改动点

### P0 — 不做就无法合规实现

#### P0-1 · 卡片移动与分类（G1）

**问题**：AI 插件要做「自动分类」，必须能移动卡片。现在 `PluginAPI` 完全没有
移动能力，插件只能产出建议、由用户手动拖——批量场景不可用。

**服务层已有完整实现**：

```python
# core/services/card_service.py:1477
def move_card_internal(card_id, target_category):
    """返回 (success, new_id, msg)"""
```

主程序路由层已经用它做了批量移动 + 失败明细 + `card.moved` hook 派发
（`core/api/v1/cards.py:2235-2322`），**逻辑可直接复用**。

**建议 API**：

```python
class CardDomain:
    def move(self, card_ids, target_category: str) -> dict:
        """批量移动卡片到分类（空串 = 根目录）。

        Returns:
            {'moved': [{'old_id','new_id','new_category'}],
             'failed': [{'old_id','msg'}],
             'count': int}
        """

    def list_categories(self) -> list:
        """全部分类路径（含子分类），相对 CARDS_FOLDER。"""

    def create_category(self, name: str) -> bool:
        """创建分类目录（已存在时返回 True，幂等）。"""

    def rename_category(self, old_path: str, new_path: str) -> bool:
        """重命名分类（含 DB 与 ui_data 前缀迁移）。"""
```

**内部必须处理**（照抄 `api_move_card` 的做法，不要简化）：

| 机制 | 位置 | 漏掉的后果 |
|---|---|---|
| `suppress_fs_events` | `cards.py:2240` | 扫描器把一次批量移动识别成几百次文件变动 |
| `_is_safe_rel_path` 校验 | `cards.py:2247-2251` | 路径穿越；AI 生成的分类名**绝不能**直接当路径用 |
| `rename_folder_in_db` / `rename_folder_in_ui` | `card_service.py:960` / `:968` | 分类改名后 DB 与 ui_data 的旧前缀残留 |
| `card.moved` hook | `cards.py:2308-2318` | 其它插件（如桌宠）收不到通知 |
| 卡片锁 | `request_card_locks` 装饰器 | 与用户的并发操作打架 |

> **安全提醒**：分类名来自 AI 输出，必须做 **slug 化 + 白名单校验**。
> 建议在 `create_category` 内部强制：
> 拒绝 `..`、绝对路径、Windows 非法字符（`\/:*?"<>|`）、超长名（>64）、
> 保留名（`notes` / `backups` / `lorebooks` / `thumbnails` / `cards` / `trash`，
> 见 `core/consts.py:5` `RESERVED_RESOURCE_NAMES`）。

#### P0-2 · 本地备注读写（G2）

**问题**：卡片「本地备注」= `ui_data[<ui_key>]['summary']`（UI 标签见
`templates/components/grid_cards.html:336` `title="本地备注"`）。
AI 插件要**读**它作为分析输入（用户写的备注很有价值），
要**写**它作为分析产出（概览）。

现状：插件用内部 import 绕过（`summary_bridge.py`），
属于 Provisional 耦合——**这是本次最应该消掉的一处越界**。

**建议 API**：

```python
class CardDomain:
    def read_note(self, card_id: str) -> str:
        """读本地备注；无备注返回空串。"""

    def write_note(self, card_id: str, text: str) -> bool:
        """写本地备注（走 update_ui_data，锁内写入）。"""

    def read_notes(self, card_ids) -> dict:
        """批量读：{card_id: text}。"""
```

**内部必须处理**：

- `resolve_ui_key(card_id)`（`card_service.py:838`）——卡片可能是 bundle，
  `ui_key` 与 `card_id` 不同；bundle 还要走版本级备注
  （`get_version_remark`，`ui_store.py:2071`）。
- `update_ui_data(mutator)`（`ui_store`）——**不能直接写文件**，
  否则会与宿主 UI 的并发写丢更新。
- 版本级备注的向后兼容逻辑（`ui_store.py:2076-2104`）——根上 `summary` 与
  `_version_remarks` 两级存储，插件不该知道这个细节。

> **注意**：`write_card_fields` 的字段白名单（`api.py:62-66`）**不含** `summary`，
> 因为备注不在卡片文件里。所以这是**新增能力**，不是扩大白名单。

#### P0-3 · 标签治理读写（G3）

**问题**：AI 插件要「新标签落地建库」与「标签池设计」，需要写分类体系。
现在只能写卡片标签（`apply_tags`），新标签**进不了分类体系**
（`taxonomy` 存在 `ui_data`，插件无权写）。

**建议 API**：

```python
class TagDomain:
    def read_taxonomy(self) -> dict: ...
    def update_taxonomy(self, patch: dict) -> bool: ...
    def read_prefs(self) -> dict: ...
    def update_prefs(self, patch: dict) -> bool: ...
    def create(self, tags) -> dict:
        """把标签加入标签库（不写任何卡片）。

        Returns: {'created': [...], 'existing': [...]}
        """
    def merge(self, replace_rules: dict) -> dict:
        """按规则合并标签（复用 core/automation/tag_merge.py）。

        Returns: {'tags': [...], 'changed': bool, 'replacements': [...]}
        """
```

**服务层已有**：

- `ui_store.get_tag_taxonomy`（`:1233`）/ `set_tag_taxonomy`（`:1240`）
- `ui_store.get_tag_management_prefs`（`:1257`）/ `set_tag_management_prefs`（`:1264`）
- `core/automation/tag_merge.py:135` `merge_tags_with_rules(tags, replace_rules)`
  （**含链式解析与环检测**，`_resolve_target:117-132`）
- `core/services/tag_management_service.py` 的 `build_known_tag_set` / `filter_governed_tags`

> **`create` 的语义要明确**：标签库是从 `card_metadata.tags` **聚合**出来的
> （`api.py:656-675` `_read_tags_from_db`），所以「创建标签」有两种可能语义：
> ① 只是把名字写进分类体系（不碰卡片）；② 同时写某张卡片的标签。
> 建议 `create` 只做 ①，② 由调用方自己调 `apply_tags`——**语义单一，可组合**。

#### P0-4 · 后端通用 token 估算（G4）

**问题**：`estimateTokens()` 只在前端（`static/js/pluginHost.js:1150-1155`），
后端没有通用版本。AI 插件因此自带一份同公式实现
（`stm-ai-assistant/backend/core/tokens.py:18-26`），
**一旦主程序调整公式就会静默漂移**。

**注意**：`core/utils/text.py:5` 的 `calculate_token_count(card_data)`
**不是**通用估算器——它接收卡片字典并聚合 name/description/first_mes/
mes_example + 世界书条目。需要新增：

```python
# core/utils/text.py
def estimate_text_tokens(text) -> int:
    """通用文本 token 估算：ceil(CJK 数 + 非 CJK 数 / 3.5)。

    公式与 calculate_token_count / 前端 estimateTokens 保持同源。
    """
```

然后：

```python
class PluginAPI:
    def estimate_tokens(self, text) -> int: ...
```

并让 `calculate_token_count` 内部改调 `estimate_text_tokens`，
**保证三处（后端通用 / 后端卡片 / 前端）永不漂移**。

### P1 — 不做能跑，但体验/性能明显劣化

#### P1-1 · 卡片结构化查询（G5）

**问题**：插件要列出候选卡片，现在只能
`SELECT id, char_name, tags FROM card_metadata`（裸 SQL）。
代价：① 依赖 Provisional 的 `db()`；② 依赖表结构；
③ 无法用索引，10k 卡时全表扫。

**建议 API**：

```python
class CardDomain:
    def list(self, *, query: str = '', category: str = '', tags=(),
             limit: int = 100, offset: int = 0, sort: str = '') -> dict:
        """结构化查询，返回 {'items': [...], 'total': int}。"""

    def count(self, **filters) -> int: ...
```

**服务层已有**：`core/services/card_index_query_service.py`
（`e.summary_preview AS ui_summary` 等），`worldinfo_index_query_service.py`。

#### P1-2 · 扩展字段归一读取（G6）

**问题**：卡片的正则脚本与 ST 脚本藏在 `data.extensions` 里，
且 ST 历史上用过**大量别名键**：
- 正则：`regex_scripts` / `regexScripts` / `regex` / `regexes` / `regular_expressions` / `RegexBinding`
- 脚本：`tavern_helper` / `tavernHelper` / `TavernHelper_scripts` / `tavern_helper_scripts` / `tavernHelper_scripts` / `TavernHelper` / `scripts`

（完整清单见 `core/services/preset_extensions.py:6-33`）

`api.read_card()` 返回**原始**结构，插件要自己写兼容——
而 `preset_extensions.py` 已经有一套成熟的口径（含 `[['scripts', [...]]]`
这种 list-of-pairs 形态的兼容，`:55-78`）。

**建议**：两个选项，推荐 ②

① 新增 `CardDomain.read_extensions(card_id)` 返回归一后的
`{regex_scripts: [...], tavern_helper: {scripts: [...], variables: {...}}}`；
② **让 `read_card()` 直接返回归一后的 `extensions`**（内部调
`normalize_extensions_for_save` 的读取侧）。

选 ② 的理由：插件拿到原始结构后**没有能力判断哪个别名才是真的**，
归一应该发生在唯一的读入口，而不是让每个插件各写一份兼容。

> **风险**：改变 `read_card` 的返回会让既有插件（`stm-pet` 等）看到不同数据。
> 但 `extensions` 归一只是**补齐别名**、不删键，向后兼容。
> 若担心，可先加 `read_card(card_id, *, normalize_extensions=False)` 开关，
> 默认 `False` 保持现状，新插件显式打开。

#### P1-3 · 快照列举与回滚（G8）

**问题**：`snapshot_card` 只能创建，不能列出与恢复。AI 插件做了破坏性写操作
（改写世界书、批量改字段）后，用户想回滚却没有 API。

**建议 API**：

```python
class BackupDomain:
    def list_card_snapshots(self, card_id: str) -> list:
        """列出该卡片的快照：[{path, name, created_at, size, remark}]。"""

    def restore_card_snapshot(self, card_id: str, snapshot_path: str) -> bool:
        """恢复快照（恢复前自动再快照一次当前状态）。"""
```

**服务层已有**：备份目录约定与命名规则在 `api.py:819-868`
（`{name}_{timestamp}__KEY__{remark}{ext}`），清理在
`core/utils/filesystem.py:cleanup_old_snapshots`。

> 这一项对 AI 插件**特别重要**：AI 的写操作是批量且不可预审的，
> 「能一键回滚」是放开破坏性写权限的前提（见 §5）。

#### P1-4 · 索引查询与状态（G10）

**建议 API**：

```python
class IndexDomain:
    def search(self, query: str, *, scope: str = 'cards', limit: int = 50) -> dict: ...
    def status(self) -> dict:
        """{'ready': bool, 'cards': int, 'worldinfo': int, 'building': bool, 'progress': float}"""
    def rebuild(self, *, scope: str = 'cards') -> str:
        """触发重建，返回 job id。"""
```

**服务层已有**：`core/services/index_service.py`、
`index_build_service.py`、`index_job_worker.py`（`enqueue_index_job`，
`api.py:507-511` 已在用）。

### P2 — 锦上添花

| 项 | 说明 | 服务层 |
|---|---|---|
| P2-1 · 会话读取 | AI 插件未来做「对话总结」需要 | `core/data/chat_store.py`、`core/utils/chat_parser.py` |
| P2-2 · 预设读取 | 读 ST 预设做提示词分析 | `core/services/preset_model.py` |
| P2-3 · 正则/脚本库 | 全局扩展资源（非卡片内嵌） | `core/services/st_client.py:905-1330` |
| P2-4 · 世界书条目历史 | 条目级 diff / 回滚 | `core/services/wi_entry_history_service.py` |
| P2-5 · 卡片版本管理 | bundle 的多版本枚举与切换 | `card_service.py`、`ui_store.get_version_remark` |
| P2-6 · 用量/统计 | 卡片总数、标签分布 | `card_index_query_service.py` |

### 明确**不做**的

| 不做 | 理由 |
|---|---|
| 暴露任意 SQL **写** | `db()` 保持只读。写操作一律走域方法，由域内部保证一致性 |
| 暴露「绕过卡片锁 / fs 抑制」的开关 | 这是机制层，不是能力层。插件拿到它只会制造难查的 bug |
| 暴露宿主内部状态树（`store`）为 Stable | 保持 Provisional（`pluginHost.js:694-696`）。要用就加语义化的 `host.onState` 字段 |
| 暴露密钥明文给前端 | 密钥纪律不变（`api.py:6-7` 的注释） |
| 让插件注册新的后端路由前缀 | 保持 `/api/plugins/<id>` 强制前缀（`api.py:239`），防止路由冲突 |

---

## 5. 破坏性操作的处理：快照先行

放开破坏性操作（删除卡片、删除世界书条目、批量覆盖字段）是本次方案的一部分，
但需要一条统一约定：

> **`destructive=True` 的域方法在内部自动先创建快照，再执行。**

理由：

1. AI 插件的写操作是**批量且事后审批**的，用户无法逐条预审；
2. 主程序自己的路由层已经在做类似的事（世界书写入会登记条目历史，
   `api.py:790-817` `_record_worldbook_history`）；
3. 有快照兜底，才敢把删除类能力交给插件。

实现上：

```python
def _destructive(self, card_id, remark: str):
    """破坏性操作的统一前置：先快照。"""
    self._api.backups.snapshot_card(card_id, remark=remark)
```

配套需要 P1-3（列举/回滚）才有意义——否则快照存了但用户找不到。

> **注意**：`api.backups.snapshot_card` 是 `destructive` 前置依赖的**内部机制**，
> 但它同时也是对插件公开的能力（插件可以主动给自己的批量操作打快照）。
> 两者不冲突：域内部调用与插件调用走同一个方法。

---

## 6. 文档与测试契约的同步（**必须做，否则 CI 失败**）

这一节是**硬约束**，漏掉会直接红。

### 6.1 `docs/plugin-api.md` 是生成物

`AGENTS.md:104` 明确：`docs/plugin-api.md` 由
`tools/gen_plugin_api_docs.py` 生成，**手工编辑必然丢失**。

验证：`python tools/gen_plugin_api_docs.py --check`

### 6.2 新增方法必须登记，否则测试失败

`tests/test_plugin_api_docs.py:50-55`：

```python
def test_every_public_method_is_grouped():
    ...
    assert ungrouped == [], f'以下公开方法未在生成器的分组表中登记: {ungrouped}'
```

因此每个新增公开方法都必须加进 `tools/gen_plugin_api_docs.py` 的
`BACKEND_GROUPS`（`gen_plugin_api_docs.py:42-62`）。
非契约的内部方法（如 `finalize` / `bind_job`）登记到 `BACKEND_INTERNAL`（`:65`）。

**本次改造后的登记分工**（不保留别名，所以分工很干净）：

| 成员 | 登记位置 |
|---|---|
| `on` / `emit` / `estimate_tokens`（顶层扁平） | `BACKEND_GROUPS`（只留这三项） |
| `plugin_id` / `manifest` / `app_version` + 各域属性（`cards` / `tags` / …） | `BACKEND_ATTRIBUTES`（`:35-39`） |
| 全部域方法 | **新增的 `BACKEND_DOMAINS`**（§3.6） |
| `finalize` / `bind_job` / `_suppress_fs_events` 等 | `BACKEND_INTERNAL`（`:65`） |

**两条硬约束**（详见 §3.5 / §3.6，均已实测验证）：

- 域属性写成 `__init__` 里的**实例属性**，**不能用 `@property`**——
  否则 `test_ast_and_introspection_agree_on_public_methods` 失败。
- 域方法**不能**塞进 `BACKEND_GROUPS`——`test_grouped_methods_actually_exist`
  用 `hasattr(PluginAPI, name)` 校验，域方法在 `PluginAPI` 上取不到。

这是**阶段 0 的硬骨头**（§7 的 0-3），必须在填充具体能力之前完成。

> **注意既有测试的连带影响**：本次是**改名 + 删除**，不是纯增量，
> 所以 `tests/test_plugin_api.py` / `test_plugin_api_docs.py` /
> `test_plugin_isolation.py` 都会失败，必须同步改写。
> `test_plugin_api_docs.py:118-124` 断言的具体签名
> （`apply_tags(card_ids, *, add=(), remove=(), replace: bool = False)`、
> `submit_job(...)`、`write_worldbook(...)`）都要换成新名。

### 6.3 其它相关测试

| 测试 | 断言 |
|---|---|
| `tests/test_plugin_api_docs.py:35-39` | 磁盘文档与 `render()` 完全一致 |
| `tests/test_plugin_api_docs.py:118-124` | 关键签名出现在文档里 |
| `tests/test_plugin_api.py` | API 行为（含密钥、配置、`apply_tags` 治理） |
| `tests/test_plugin_isolation.py` | 插件间隔离（密钥、`ui_data` 命名空间） |

**建议**：为每个新域补一个 `tests/test_plugin_api_domains_<domain>.py`，
覆盖「一致性机制确实生效」——例如移动卡片后
① 缓存里 `id_map` 已更新、② `card_metadata` 行的路径已变、③ 索引增量已入队。
**这类测试比「函数返回 True」有价值得多**。

---

## 7. 实施顺序与验收

### 阶段 0 · 脚手架 + 改名（先做这个，再谈具体能力）

| 步骤 | 产出 | 验收 |
|---|---|---|
| 0-1 | `core/plugins/domains/` 目录 + `_base.py`（共享路径/锁/fs/索引同步工具） | 目录存在；`_base` 有单测 |
| 0-2 | 按 §3.1 的完整 API 面**改名**：`PluginAPI` 只留 `on` / `emit` / `estimate_tokens` + 各域**实例属性**；域类先只搬现有方法（不新增能力） | `api.cards is api.cards`（同实例）；`test_ast_and_introspection_agree_on_public_methods` 仍通过（**用实例属性而非 `@property`**，见 §3.5） |
| 0-3 | 删除 `db()` / `suppress_fs_events()` / `notify()`；新增 `api.private.query` / `api.jobs.items`（补上裸 SQL 的两个缺口） | `api.private.query('DELETE …')` 被拒；`api.jobs.items(run_id)` 能取到全部分页之外的项目 |
| 0-4 | **改造 `tools/gen_plugin_api_docs.py`**：新增 `BACKEND_DOMAINS` + 域路径 `hasattr` 校验 + 渲染分支；域属性登记进 `BACKEND_ATTRIBUTES`；`BACKEND_GROUPS` 精简到三项 | `python tools/gen_plugin_api_docs.py --check` 通过 |
| 0-5 | 同步改写受影响的测试（`test_plugin_api.py` / `test_plugin_api_docs.py` / `test_plugin_isolation.py`） | 主程序 `pytest tests/ -q` 全绿 |
| 0-6 | 重新生成 `docs/plugin-api.md`；改写 `samples/plugins/hello-world` 与 `tools/new_plugin.py` 模板 | `test_rendered_document_contains_key_sections` 通过；新插件脚手架产出新名 |

**阶段 0 是本次最大的工作量，也是最关键的一步**：它决定了后面每个能力是
「加一个方法」还是「改一次架构」。0-4 是唯一的硬骨头（生成器当前不支持域方法），
但它是一次性成本——做完之后，加能力就是
「在域类里写方法 + 在 `BACKEND_DOMAINS` 里加一行」。

> **0-2 刻意不新增能力**：先把「改名 + 搬进域」做干净，确保既有行为不变、
> 测试全绿，再在阶段 1 加 P0 的新能力。混在一起做会让「改名引入的回归」
> 与「新能力的 bug」难以区分。

### 阶段 1 · P0 四项

| 项 | 验收 |
|---|---|
| P0-1 移动与分类 | 批量移动 3 张卡到新分类 → ① 卡片列表立刻显示新分类（缓存已同步）② `card.moved` hook 被派发（`stm-pet` 能收到）③ 非法分类名被拒（`..`、绝对路径、保留名） |
| P0-2 备注读写 | 写备注 → 卡片网格的「本地备注」区域立刻显示（说明走的是 `ui_data` 而非卡片文件）；bundle 卡片的版本级备注正确 |
| P0-3 标签治理 | 新建标签进分类体系 → 主程序标签管理页可见；`merge` 能检测环（`a→b→a`） |
| P0-4 token 估算 | `api.estimate_tokens('中文abc')` 与前端 `api.estimateTokens` 结果**完全一致**（同一样本集交叉验证） |

### 阶段 2 · P1 四项
### 阶段 3 · P2 按需

### 回归底线

```
python -m pytest tests/ -q          # 当前基线 3102 passed（见插件设计文档 §G.6）
python tools/gen_plugin_api_docs.py --check
python tools/gen_plugin_ui_icons.py --check
```

### 阶段 0 完成后的下游动作

| 仓库 | 动作 |
|---|---|
| `ST-Manager-Pet` | 按 §3.3 对照表改名（`api.toast` 等前端名不变，只改后端调用） |
| `ST-Manager-AI-Assistant` | 按 §3.3 改名；**删除 `backend/summary_bridge.py` 的 bridge 分支**，改用 `api.cards.read_note` / `write_note`；`jobs.py` / `routes.py` 的裸 SQL 改用 `api.jobs.items` / `api.cards.list` |
| `samples/plugins/hello-world` | 同步改名（它是文档里的示例，留着旧名会误导） |
| `tools/new_plugin.py` | 生成的脚手架用新名 |

---

## 8. 需要拍板的点

1. **`read_card` 是否直接归一 `extensions`**（§P1-2）：
   推荐直接归一（只补别名不删键，向后兼容）；
   保守方案是加 `normalize_extensions` 开关。

2. **`tags.create` 的语义**（§P0-3）：推荐「只写分类体系，不碰卡片」。

3. **破坏性操作是否全开**（§5）：推荐全开 + 强制快照先行，
   并且 P1-3（快照列举/回滚）要**同期**做，否则快照存了找不到。

4. **`suppress_fs_events` 是否真的删除**（§3.2）：本文推荐删除（机制内部化），
   前提是「插件不直接写被监视目录」。当前两个插件都不需要。
   若将来出现「插件批量生成卡片文件」这类需求，应由
   `api.cards.create(...)` 提供，而不是把抑制开关放回去。

5. **`pyyaml` 依赖**：主程序 `requirements.txt` 目前只有
   Flask / Pillow / requests / watchdog。AI 插件的世界书简化**不需要**它
   （用户已确认：不要求严格格式校验，只是提示词里让 AI 优先输出 YAML）。
   所以**本次不必加**。若将来要做 YAML 语义校验再评估。

---

## 9. 已拍板（2026-10-12）

| # | 议题 | 决定 |
|---|---|---|
| 1 | 是否保留扁平别名 | **不保留**。插件系统未发布，直接改成域命名空间，同步改写现有两个插件 |
| 2 | API 放开范围 | **能力全面放开，机制内部化**（§1）。破坏性操作也放开，但强制快照先行（§5） |

---

## 10. 实施记录（已落地）

阶段 0、阶段 1（P0 四项）、阶段 2（P1 四项）与阶段 3 的 P2 只读部分均已实现。
本节记录**与方案原文的偏差**和新增的硬约束，供后续维护参考。

### 10.1 与方案原文的偏差

| 位置 | 方案原文 | 实际实现 | 原因 |
|---|---|---|---|
| §3.6 域方法收集 | 「用 `getattr(getattr(PluginAPI, domain), method)` 取函数与签名」 | 新增 `core/plugins/domains/__init__.py` 的 `DOMAIN_CLASSES`，生成器按它枚举 | 域是 `__init__` 里的**实例属性**（§3.5 的硬约束），`getattr(PluginAPI, 'cards')` 取不到；类属性与实例属性无法同时满足两条测试 |
| §3.1 `api.jobs.*` | 列出 8 个方法 | 一致（未额外加 `list`） | 保持与方案逐字对应 |
| §3.1 `api.cards.create_category` | `create_category(name)` | `create_category(name, *, parent='')` | 分类树需要创建子分类；不传 `parent` 时行为与原文一致 |
| §3.1 `api.backups.restore_card_snapshot` | 返回 `bool` | 返回 `{'success', 'msg', 'error', 'safety_snapshot'}` | 需要区分 `card_not_found` / `snapshot_not_found` / `snapshot_out_of_scope` / `restore_failed`；且要能回报自动前置快照的路径 |
| §P1-2 扩展归一 | 「推荐让 `read_card()` 直接归一」（§8.1 的推荐项 ②） | 采用保守方案：`read_card()` 保持原始结构，归一走新增的 `cards.read_extensions()` | 避免改变既有插件（`stm-pet`）看到的数据；归一入口仍然唯一 |
| §P2 | 「`api.chats.*` / `api.presets.*` / `api.extensions.*`」 | 只做**读取**，写入暂不投影 | 预设写入涉及家族版本、默认版本标记等语义，放开前需要单独设计 |
| §3.2 `notify` | 「合并进 `api.log.*`」 | 一致，且 `api.log.*` 只保留 4 个具名方法（字符串 level 版本降级为内部 `_write_log`） | 具名方法才是契约；作业 worker 走内部路径 |

### 10.2 新增的硬约束（后续改动必须遵守）

1. **域类清单只有一处**：新增域要在 `core/plugins/domains/DOMAIN_CLASSES` 加一行，
   否则 `test_domain_classes_match_backend_domains_registry` 失败。
   `PluginAPI.__init__` 按这份清单 `setattr`，生成器与测试也按它枚举。
2. **域必须是实例属性**，不能是 `@property`（§3.5）。
   `test_domain_attributes_are_instance_attributes_not_properties` 会拦住。
3. **域方法不能写进 `BACKEND_GROUPS`**，只能进 `BACKEND_DOMAINS`（§3.6）。
4. **绝对路径校验要在 `strip('/')` 之前做**：`_is_valid_category_path` /
   `_move_cards` / `_create_category` / `_rename_category` 都遵守这条。
   曾经的写法会把 `/abs/path` 静默归一成相对路径 `abs/path` 而绕过校验
   （`test_move_rejects_unsafe_target_categories[/abs/path]` 覆盖）。
5. **快照的排序不能用 `st_mtime`**：`write_snapshot_file` 走 `shutil.copy2`
   会保留源文件 mtime，同一张卡的所有快照 mtime 相同。
   真正的时间戳在文件名里（`_snapshot_stamp_key`）。
6. **`job_store.list_items` 返回的键是 `key`**（不是 `item_key`），
   且 `limit` 有 `max(1, ...)` 下限——`api.jobs.items(limit=0)` 在域内
   换算成 `jobs.MAX_ITEMS_PER_RUN`。

### 10.3 新增测试

| 文件 | 覆盖 |
|---|---|
| `tests/test_plugin_api_domains_cards.py` | 移动后缓存/DB/索引三处一致、`card.moved` hook、fs 抑制窗口、分类名校验、备注走 `ui_data`、bundle 版本级备注 |
| `tests/test_plugin_api_domains_tags.py` | `create` 只写分类体系、`merge` 链式解析与环检测、taxonomy/prefs 浅合并、与标签治理联动 |
| `tests/test_plugin_api_domains_backups.py` | 快照创建/列举/回滚、恢复前自动快照、越界快照拒绝、已删卡片的还原 |
| `tests/test_plugin_api_domains_index.py` | `cards.list/count` 走索引服务、扩展字段别名归一、索引未就绪/未知 scope |
| `tests/test_plugin_api_domains_private_jobs.py` | `private.query` 只读校验（含 CTE 夹带）、`jobs.items` 全量分页与归属隔离 |

### 10.4 下游动作的状态

| 仓库 | 动作 | 状态 |
|---|---|---|
| `samples/plugins/hello-world` | 同步改名 | **已改**（含 README 与注释） |
| `tools/new_plugin.py` | 脚手架用新名 | **已改** |
| `ST-Manager-Pet` | 按 §3.3 对照表改名 | 待办（跨仓库，不在本次改动范围） |
| `ST-Manager-AI-Assistant` | 按 §3.3 改名；删 `summary_bridge.py` bridge 分支；`jobs.py` / `routes.py` 裸 SQL 改用 `api.jobs.items` / `api.cards.list` | 待办（跨仓库，不在本次改动范围） |
