# 世界书搜索性能分析与搜索分类方案

> 第 4 点需求的分析报告，以及后续落地的修复记录。
> 原始分析数字均在本机复现；第六节记录实际实现与实测对比。

## 一、结论速览

慢的**主因不是数据量，而是一条写错的关联子查询**。它让 SQLite 对每一行外层记录
都重新扫一遍 FTS 表。改成参数化后，同一条查询从 **1524 ms 降到 4 ms（381 倍）**。

| 症状 | 真正的成因 | 量级 |
| --- | --- | --- |
| 每敲一个字都要等约 10 秒 | 关联子查询 `generation = e.generation` | 慢 380 倍 |
| 页面本身慢一倍 | 同一条件被独立 `COUNT(*)` 又算一遍 | 慢 2 倍 |
| 搜不到、还慢 | `entity_type LIKE 'world_%'` 让索引失效，扫描全部 5000 行（含角色卡） | 慢 40 倍 |
| 全文模式搜中文永远 0 条 | `unicode61` 分词器不切分中文 | 功能缺失 |
| 输入 `.`、`-`、`:` 报错或搜错 | FTS5 语法字符未转义 | 功能缺陷 |

**性能修复不需要加表、不需要改前端、不需要动索引结构**，只改
`worldinfo_index_query_service.py` 的 SQL 写法即可（`card_index_query_service.py`
存在完全相同的三处问题，一并修复）。

---

## 二、复现环境

合成库按用户实际规模构造：**3000 张角色卡 + 2000 本世界书（global/resource/embedded
三类混合）**，走真实的 `RUNTIME_SCHEMA_STATEMENTS` 建表。

```python
# 现状 SQL（core/services/worldinfo_index_query_service.py:236/239）
... WHERE e.entity_id IN (SELECT entity_id FROM index_search_fast_v2
                          WHERE generation = e.generation AND content LIKE ?)
```

### 实测耗时

| 查询写法 | 耗时 | 倍率 |
| --- | ---: | ---: |
| **现状**（关联子查询 + 独立 COUNT） | **1524 ms** | 1× |
| 仅把关联子查询换成字面量 `generation = 1` | 4.0 ms | **381× 更快** |
| 字面量 + `entity_type IN (...)` + 窗口函数 COUNT | 2.3 ms | 663× 更快 |
| 纯名称 `LIKE`（去掉 FTS 子查询） | 1.1 ms | 1385× 更快 |
| **现状，但零命中**（`%zzz-no-such-thing%`） | **1925 ms** | 比有结果还慢 |

最后一行很关键：**零命中比有命中更慢**，这直接证明瓶颈是"扫了多少次索引"，
与"匹配到多少行"无关 —— 符合关联子查询的特征。

### EXPLAIN QUERY PLAN 对比

```
现状：  SEARCH e USING INDEX idx_index_entities_v2_gen_owner (generation=?)
        CORRELATED LIST SUBQUERY 1        ← 逐行重算
        SCAN index_search_fast_v2 VIRTUAL TABLE INDEX 0:
        USE TEMP B-TREE FOR ORDER BY

优化后：SEARCH e USING INDEX idx_index_entities_v2_gen_type_sort (generation=? AND entity_type=?)
        LIST SUBQUERY 1                   ← 只算一次
        SCAN index_search_fast_v2 VIRTUAL TABLE INDEX 0:
        CREATE BLOOM FILTER
        USE TEMP B-TREE FOR ORDER BY
```

`CORRELATED LIST SUBQUERY` 消失是性能跃升的直接原因：优化器从"每行一次子查询"
变成"一次子查询 + bloom filter 探测"。

---

## 三、逐条根因

### 1. 关联子查询（主因，占 ~99% 耗时）

```python
# core/services/worldinfo_index_query_service.py:236、:239
'... WHERE generation = e.generation AND content LIKE ? ...'
```

`e.generation` 引用外层表，SQLite 无法把它当常量预计算子查询结果，只能**逐行重跑**。
外层的 `SEARCH e USING INDEX ...(generation=?)` 会返回全部 5000 行（见第 3 条），
于是子查询被触发数千次。

**修法**：`generation` 在函数里本来就是已知参数（`_build_query_parts(filters, generation)`），
直接内插成字面量。这**不是** SQL 注入面 —— 它是 `int`，来自 `get_active_generation()` 的
数据库读取，不是用户输入。若想保留参数化，可改用 `CROSS JOIN` 或先把匹配的
`entity_id` 收进临时集合再 `IN (...)`。

### 2. 独立 COUNT 让成本翻倍

```python
# core/services/worldinfo_index_query_service.py:299-302
total = conn.execute(f"SELECT COUNT(*) FROM index_entities_v2 e WHERE {' AND '.join(where)}", params)
```

WHERE 里同样带着那条关联子查询，等于把最贵的部分**完整算第二遍**。
这条正是"页面 3971 ms + COUNT 6679 ms"的来源 —— COUNT 甚至比取数据还贵，
因为它不能靠 `LIMIT` 提前结束。

**修法**：用窗口函数一次搞定。

```sql
SELECT ..., COUNT(*) OVER () AS total FROM index_entities_v2 e WHERE ... LIMIT ? OFFSET ?
```

无匹配行时拿不到 total，用一个 `if items: total = items[0]['total'] else: 0` 兜底即可。

### 3. `entity_type LIKE 'world_%'` 让索引失效

```python
# core/services/worldinfo_index_query_service.py:213
where = ['e.generation = ?', "e.entity_type LIKE 'world_%'"]
```

实测 5000 行库：

| 写法 | 计划 | 耗时 |
| --- | --- | ---: |
| `entity_type LIKE 'world_%'` | `SEARCH ... USING INDEX idx_index_entities_v2_gen_owner` | 0.44 ms |
| `entity_type IN ('world_global','world_resource','world_embedded')` | `SEARCH ... USING INDEX idx_index_entities_v2_gen_type_sort` | 0.01 ms |

`LIKE` 走的是 `gen_owner` 索引，**只用到 generation**，于是把 3000 张角色卡也扫进来；
`IN` 才能命中 `idx_index_entities_v2_gen_type_sort` 的复合键。

**修法**：换成 `IN (...)`。三个值在 `index_build_service` 里是本项目的固定枚举，
不存在"将来出现第四种 world_ 类型"的隐患；真加了新类型，这里会**漏报而非报错**，
所以建议顺带加一条测试锁定枚举集合。

### 4. 全文模式对中文完全无效

`index_search_full_v2` 建表用的是 `unicode61` 分词器：

| 查询 | 结果 |
| --- | --- |
| `MATCH '血族'`（内容是"血族王子 血脉觉醒…"） | **0 命中** |
| `MATCH '血脉'` | **0 命中** |
| `MATCH '设定'` | **0 命中** |
| `MATCH 'Dragon'` | 1 命中 ✅ |
| `MATCH 'book7'` | 1 命中 ✅ |

`unicode61` 不切分汉字，整串"血族王子血脉觉醒家族"被当成**一个 token**，
所以只有前缀完整的整词能匹配，任何子串都 0 条。这正是"全文模式搜中文搜不到"的原因。

**修法**：改用 `trigram` 分词器（`tokenize='trigram'`，SQLite ≥ 3.34），
它按三字符滑窗切分，天然支持中文子串。代价是索引体积增大约 3–4 倍。
另一种选择是在写入时把中文预切分成空格分隔的单字（利用 `unicode61` 会按空格切），
但会让 `content` 列不再是原文，影响其他读取路径。

### 5. 两种 FTS 表内容完全相同

实测 `index_search_fast_v2` 与 `index_search_full_v2` 的行**逐字节一致**：
`_insert_worldinfo_search`（`core/services/index_build_service.py:73-82`）把同一段
`name/filename/category/summary/char_name` 同时写进两张表。

也就是说"快搜/全文"的区别**只在于 SQL 用 `LIKE` 还是 `MATCH`**，与"索引里有什么"无关。
所以：
- 也没有任何一张表索引了**条目正文**（entry content），搜世界书内部的词注定搜不到；
- 若要做真正的全文，`full` 表应写入 entry 正文，`fast` 表保持轻量 —— 这才是分表的理由。

### 6. 未识别的 FTS 语法错误会冒泡成 500

`_is_malformed_match_error`（`:14-21`）只认三种消息，实测覆盖面不足：

| 输入 | 实际异常 | 被识别? |
| --- | --- | --- |
| `book7.json` | `fts5: syntax error near "."` | ✅ 降级为名称 LIKE |
| `AND` | `fts5: syntax error near "AND"` | ✅ 降级 |
| **`a-b`** | `no such column: b` | ❌ **抛出** |
| **`a:b`** | `no such column: a` | ❌ **抛出** |

带连字符或冒号的搜索词（很常见，比如文件名 `world-info`、`分类:奇幻`）会走到
`raise`（`:347`）变成 500。降级后也只有**名称** LIKE，等于"搜了但搜不到"，
用户没有任何提示。

**修法**：把异常识别放宽到 `OperationalError` 一律降级（搜索功能不该 500），
并在响应里带一个 `search_degraded: true` 让前端提示"已退化为名称匹配"。

### 7. PNG 抽取循环是死代码（但很危险）

```python
# core/api/v1/world_info.py:1219-1244
for card in ctx.cache.cards:
    if not card.get('has_character_book'):   # ← 这个键不存在
        continue
```

实测缓存条目共 25 个字段，**没有 `has_character_book`**：

```
['card_uid','category','char_name','char_version','creator','dir_path','file_hash',
 'filename','id','image_url','import_time','is_bundle','is_favorite','last_modified',
 'last_sent_to_st','last_sent_to_tt','resource_folder','source_link','source_title',
 'source_update','tags','thumb_url','token_count','ui_summary','versions']
```

`card.get(...)` 返回 `None` → `continue`，所以循环**每次都空转**，目前是无害的。

但危险在于：这正是遗留路径（`worldinfo_list_use_index = false`，**当前默认值**）的
必经之路。一旦谁"顺手"补上 `has_character_book` 字段，这段会立刻变成对每张卡
`extract_card_info(full_path)` —— 单张 4.8 MB 卡实测 34–62 ms，**3000 张卡就是
70–120 秒**，且每个请求都跑一次。**建议直接删掉这个循环**，而不是补字段。

### 8. 遗留路径的签名与缓存键

当前默认 `worldinfo_list_use_index = false`，走的是遗留分支，另有两个成本：

```python
# core/api/v1/world_info.py:1154
cache_key = f"{wi_type}||{category}||{search_mode}||{search.lower()}"
```

**搜索词进了缓存键** → 每敲一个字都是全新 key，`ctx.wi_list_cache` 永远 miss，
缓存等于不存在。实测签名计算本身也不便宜：

| 操作 | 耗时 |
| --- | ---: |
| `_build_dir_tree_sig`（15000 文件 / 50 目录） | **342 ms** |
| 同上，第二次调用（OS 缓存已热） | 340 ms |

**每敲一个字都付 342 ms**，且 `sig` 字符串长度 809317（80 万字符），
本身就带来可观的内存与比较开销。

**修法**：把 search 从缓存键里拿掉（缓存"无搜索的全集"，在内存里过滤），
并给目录签名加短期记忆（比如 1–2 秒 TTL），或改用 `os.scandir` 只收 mtime。

### 9. 前端节流已做到位，但服务端仍在空转

现有防线是充分的：
- `header.html:47` `x-model.debounce.300ms="wiSearchQuery"`（300 ms）
- `wiGrid.js:494-499` `scheduleFetchWorldInfoList()` 再 debounce 250 ms
- `wiGrid.js:842/851/855` 用 `AbortController` 取消过期请求

但 Flask 以 `threaded=True` 运行：**前端 abort 只是断开会话，服务端那条 10 秒的
查询照样跑完**。所以快速输入 10 个字符 = 服务端排队 10 条重查询，把 SQLite 打满、
反过来拖慢一切（包括角色卡列表）。

**修法**：先把 SQL 修对（这一步收益最大），再考虑服务端短 TTL 结果缓存。

### 10. 附带发现：`wi-search-changed` 是死监听

```javascript
// static/js/components/wiGrid.js:788-792
window.addEventListener("wi-search-changed", (e) => { ... });
```

全仓库搜索：**只有这一个监听，没有任何 `dispatchEvent`**。搜索实际是靠
`wiGrid.js:719` 的 `$watch("$store.global.wiSearchQuery")` 生效的。
这段死代码可以删（顺带避免"改了它却不生效"的困惑）。

---

## 四、你提的搜索分类方案

四种分类**在现有索引上全部可做，不需要新表、不需要重建索引**。
推荐落地为 `search_field` 参数，与现有 `search_mode` 正交。

| 分类 | 实现 | 实测成本 | 说明 |
| --- | --- | ---: | --- |
| **世界书名** | `LOWER(e.name) LIKE ?` | ~1 ms | 已存在于 `where` 里，只需单独暴露 |
| **文件名** | `LOWER(e.filename) LIKE ?` | ~1 ms | `filename` 已是索引列，直接可用 |
| **所属角色卡** | `e.owner_entity_id IN (...)` | ~1 ms | **关键**：`world_info.py:1111-1113` 已经按 `char_name` 做前置子查询算出 `owner_entity_ids` 并传进来了，UI 只需暴露这个开关 |
| **智能搜索** | 现行为（名称 OR 内容 OR 备注 OR 角色卡） | 修 SQL 后 ~2 ms | 语义不变，只是变快 |

### 落地建议

1. **`search_field` 与 `search_mode` 解耦**。`search_mode`（快搜/全文）决定
   "用 LIKE 还是 MATCH"，`search_field`（新）决定"在哪些列上找"。两者组合
   语义清晰，也不用推翻现有 UI。
2. **智能搜索 = 默认值**，保持老用户习惯不变；其余三项是精确缩小范围的加速选项。
3. **世界书名 / 文件名 / 所属角色卡 三项绕开 FTS 子查询**，直接对索引列 LIKE ——
   这就是它们都快的原因，也顺带绕过了第 6 条的 FTS 语法陷阱（搜 `a-b` 不再报错）。
4. **UI 提示**：选中精确分类时，可以在搜索框旁标注"仅在名称中搜索"，避免用户
   误以为"搜不到 = 没有这本书"。这也正好补上第 6 条缺失的降级提示。
5. **保留 `extra_source_paths` / `extra_owner_entity_ids` 的 OR 合并**逻辑
   （`world_info.py:1098-1128`）—— 它让"备注里有这个词"和"角色卡名匹配"也能命中，
   是当前智能搜索的实际行为，不要在这次改动里丢掉。

---

## 五、建议的修复顺序（按性价比）

| 优先级 | 改动 | 预期收益 | 风险 |
| --- | --- | --- | --- |
| **P0** | 关联子查询改字面量（`:236/239`） | **~380×** | 极低 |
| **P0** | 独立 COUNT 改 `COUNT(*) OVER ()`（`:299-302`） | ~2× | 低 |
| **P1** | `entity_type LIKE` → `IN (...)`（`:213`） | 索引可用 | 低（需锁枚举测试） |
| **P1** | 删掉 PNG 抽取死循环（`world_info.py:1219-1244`） | 消除 70–120 s 隐患 | 低 |
| **P2** | 放宽 FTS 异常降级 + `search_degraded` 标记 | 消灭 500、明确反馈 | 低 |
| **P2** | 搜索分类 `search_field`（本节第四节） | 可用性 + 精确速度 | 中（UI + 接口） |
| **P3** | 全文改 `trigram` 分词器 | 中文全文可用 | 中（索引体积 / 需重建） |
| **P3** | 缓存键去掉 search + 签名 TTL | 遗留路径提速 | 中（缓存语义） |

P0 两项合起来就能把"约 10 秒"压到**约 5 毫秒**，而且改动量极小 —— 建议先做这两项，
再谈分类和全文索引。

---

## 六、复现方式

本报告的每个数字都可用下面的方式重新验证（合成库 + EXPLAIN，不依赖用户数据）：

1. 用 `core.data.index_runtime_store.RUNTIME_SCHEMA_STATEMENTS` 建库；
2. 插入 3000 `card` + 2000 `world_*` 行及对应 FTS 行；
3. 分别对 `query_worldinfo_index._build_query_parts` 的现状 SQL 与字面量版本计时；
4. `EXPLAIN QUERY PLAN` 确认 `CORRELATED LIST SUBQUERY` 是否消失。

第 4、5 条可直接对 `index_search_full_v2` 用 `MATCH` 验证中文子串返回 0 行，
以及 `index_search_fast_v2` / `index_search_full_v2` 的 `content` 列逐行相等。

---

## 七、落地记录（已实现）

按上面的优先级实施，并与原分析有两处**刻意的偏离**（见 7.3）。

### 7.1 实际改动

| 位置 | 改动 |
| --- | --- |
| `core/services/worldinfo_index_query_service.py` | FTS 子查询的 `generation` 改为**占位符**（非关联）；`LIKE 'world_%'` → `WORLD_ENTITY_TYPE_FILTER`（`IN` 枚举）；新增 `search_field` 分类与 `search_degraded`；`_not_ready_result()` 固定未就绪键集合 |
| `core/services/card_index_query_service.py` | 同样三处：关联子查询、`MATCH` 输入规范化、`escape_like` 统一（原先漏了 `.lower()`） |
| `core/services/index_build_service.py` | 新增 `_insert_search_rows` / `collect_worldbook_fulltext`；两张 FTS 表**内容不再相同**；全文索引收录条目正文（带上限） |
| `core/data/index_runtime_store.py` | `_scope_generation_filters` 的 `LIKE 'world_%'` → `IN` 枚举 |
| `core/api/v1/world_info.py` | 删除 PNG 抽取死循环；缓存键去掉 `search`/`category`（改为缓存未过滤全集、命中后内存过滤）；目录签名按 `wi_type` 按需计算；抽出 `_apply_worldinfo_list_filters` 保证缓存命中时筛选仍生效；新增 `search_field` 参数与 `search_degraded` 透出 |
| `core/utils/search_text.py` | **新增**：CJK 逐字切分（写入侧）与 FTS5 查询构造（查询侧） |
| 前端 | `header.html` 新增世界书「搜索分类」下拉（桌面+移动）；`wiGrid.js` 传 `search_field`、处理 `search_degraded`、移除死监听 `wi-search-changed`；`grid_wi.html` 空结果区分「无关键字」提示 |

### 7.2 实测对比（3000 卡 + 2000 世界书，走真实 `query_worldinfo_index`）

| 查询 | 修复前 | 修复后 |
| --- | ---: | ---: |
| 中文两字 `血族`（fast） | 约 1500 ms 且**命中 0** | **8.0 ms，命中 20** |
| 中文两字 `血族`（fulltext） | 约 1500 ms 且**命中 0** | **5.2 ms，命中 20** |
| 英文 `book`（fast） | 约 1500 ms | 7.7 ms |
| 零命中查询 | **1925 ms** | 6.3 ms |
| 世界书名分类 | 不支持 | 4.0 ms |
| 文件名分类 | 不支持 | 4.7 ms |
| 所属角色卡分类 | 不支持 | 3.9 ms |
| 标点输入 `...` | 500 / 静默降级 | 4.4 ms，`search_degraded=true` |

独立 COUNT 保留（未改窗口函数）：关联子查询修好后它已降到毫秒级，改窗口函数需要
把合成列从行字典里剔除，收益不足以承担这个风险。

### 7.3 与原分析的两处刻意偏离

**（1）不用 `trigram` 分词器，改为写入侧 CJK 逐字切分。**
实测 `trigram` 对**两字中文查询恒返回 0 行**（它要求 ≥3 字符），而两字是中文搜索
最常见的长度：

| 查询 | 默认 `unicode61` | `trigram` | 逐字切分 + 短语 |
| --- | ---: | ---: | ---: |
| `血族`（2 字） | 0 | **0** | **1** |
| `血族王`（3 字） | 0 | 1 | **1** |
| `Dragon` | 1 | 1 | **1** |

逐字切分方案对任意长度 ≥1 都成立，且**不需要改 DDL**，因此绕开了
`CREATE VIRTUAL TABLE IF NOT EXISTS` 的迁移陷阱（老库会保留旧分词器，除非提升
`INDEX_RUNTIME_SCHEMA_VERSION`，而那会打破 `tests/test_index_runtime_schema.py`）。
代价是全文表内容膨胀约 1.73 倍。

**（2）不给 `_build_dir_tree_sig` 加 TTL。**
`tests/test_worldinfo_category_model.py:1844` 会在改写文件后立即重新请求并断言新内容，
TTL 会让它读到过期签名。改为**按 `wi_type` 只计算实际需要的目录签名**，
收益相似且不破坏该契约。

### 7.4 两张 FTS 表现在真正分工

原先两表内容逐字节相同。现在：

- `index_search_fast_v2` → **原文**。查询侧用 `LIKE` 子串匹配，中文本来就成立，
  无需分词，索引最小。
- `index_search_full_v2` → **逐字切分后的 CJK + 世界书条目正文**。查询侧用短语
  `"血 族"` 匹配相邻 token，得到真正的子串语义；正文收录有
  `WORLDBOOK_FULLTEXT_MAX_CHARS`（每本 20 万字符）与
  `WORLDBOOK_FULLTEXT_ENTRY_MAX_CHARS`（单条 2 万字符）双重上限。

写入侧统一走 `_insert_search_rows`，**角色卡也一并受益**（此前中文卡片全文搜索同样失效）。

### 7.5 索引重建：靠内容格式版本自动触发

CJK 切分只影响新写入的内容，老库的全文表仍是未切分文本。为了不要求用户手动重建，
索引现在自带**搜索内容格式版本**（`SEARCH_CONTENT_FORMAT_VERSION`）：

- `activate_generation` 在**同一个事务**里把该版本写入 `scan_runtime_state`
  （键 `search_content_format::<scope>`）。同事务保证不会出现「已激活但版本未记录」，
  从而避免每次启动都重建。
- 启动时 `run_startup_upgrade_if_needed` 对已就绪的 scope 也比对版本：
  记录值 < 当前值即重建，`build_reason='search_content_format_upgrade'`。
- 版本 1 = 原文（历史格式）；版本 2 = CJK 逐字切分 + 条目正文。
  以后只要写入侧改变内容形态，把常量 +1 即可自动触发一次重建。

**关于 `worldinfo_list_use_index` 开关**：它只出现在读路径分支
（`core/api/v1/world_info.py` 2 处），索引维护侧（`scan_service`、`index_job_worker`、
`card_index_sync_service`）**完全不检查它**。因此：

| 场景 | 索引状态 | 是否需要重建 |
| --- | --- | --- |
| 开关一直是开 | 正常增量维护 | 否 |
| 关掉开关 → 增删改卡片/世界书 → 重新打开 | **索引仍是新的**（维护不受开关影响） | 否 |
| 从旧版本升级到含 CJK 切分的版本 | 内容格式过时 | **是，启动时自动重建** |
| 全新库 | 从未构建 | 是，bootstrap |

所以「关掉再打开」本身不需要重建 —— 开关只是读路径的开关，不是索引的开关。
需要重建的唯一原因是**内容格式升级**，而这已由版本比对自动处理。

### 7.6 测试

新增 `tests/test_search_text.py`（22 项）与 `tests/test_worldinfo_search_optimization.py`
（25 项），覆盖：CJK 切分、短语构造、布尔运算符保留、标点输入、两字中文命中、
条目正文收录与上限、搜索分类精度、`search_degraded`、SQL 形状锁定（禁止
`generation = e.generation`、禁止 `LIKE 'world_%'`）、`world_*` 枚举锁定、
以及「数据库故障必须继续抛出」的反向保护。

> 注：原分析中「PNG 抽取循环在运行时始终空转」的结论对**生产代码**成立
> （`core/data/cache.py` 构建的卡片字典没有 `has_character_book`），但测试夹具
> 会注入该字段（`tests/test_worldinfo_category_model.py` 有 6 处），因此该循环
> 在测试下确实执行过。删除它是测试安全的：没有任何测试断言 list 路径上
> `extract_card_info` 的调用参数。
