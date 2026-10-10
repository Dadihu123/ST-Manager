# 主程序插件系统「地基」修缮 —— 实施提示词

> 用途：把本文件整份交给一个全新的编码会话（或直接作为本会话的后续指令），按其执行。
> 目标仓库：`D:\Workspace\MyOwn\ST-Manager`（主程序）。
> 生成日期：2026-10-10。
> 设计依据（只读参考，**本文件的决策优先**）：`docs/2026-10-10-plugin-entry-unification-design.md`、`docs/2026-10-10-plugin-entry-unification-addendum.md`、`docs/2026-10-10-plugin-third-party-ecosystem.md`。

---

## 0. 任务陈述

**只改主程序，不动任何插件。** 把宿主侧的插件系统从「只能给插件一条硬编码模态框通道」改造成「契约驱动 + 宿主提供容器」的地基，让后续的入口坞、导航项、命令面板、第三方生态都建立在它之上。

**"地基"的边界**：契约层 + 校验层 + 运行时层 + 界面层。呈现层（坞/面板）只做最小可用，作为地基的**验收装置**——没有它就无法端到端验证 entries 契约。

**明确不在本次范围**：
- 迁移 `data/plugins/hello-world` 与 `data/plugins/stm-ai-assistant`（AI 助手在独立仓库 `D:\Workspace\MyOwn\ST-Manager-AI-Assistant`，本次一律不碰）。
- 给 `static/plugins/catalog.json` 填条目、把 AI 助手加入官方列表。
- 侧栏导航数据化改造（阶段 5 之后的独立工作）。
- 插件热重载、插件日志面板。

---

## 1. 硬约束（来自 `AGENTS.md`，违反即返工）

**风格**
- 4 空格缩进；Python 优先单引号；行宽 ~100–120；顶层函数之间两空行。
- import 顺序 stdlib / third-party / local，组间空行；优先 `from core.xxx import yyy` 绝对导入；不留无用 import。
- 命名：类 `PascalCase`、函数 `snake_case`、常量 `UPPER_CASE`、私有前缀 `_`、Blueprint 变量名惯例 `bp`。

**数据与路径**
- SQLite 直接 `sqlite3`、**必须参数化、禁止拼 SQL**；`with sqlite3.connect(...)` 或 Flask `g`；保留 `core/data/db_session.py` 的 WAL 设置；写锁用 `execute_with_retry()`。
- 路径一律 `os.path.join()`；存储的相对路径用 `.replace('\\', '/')` 归一为斜杠；读写前校验路径在允许根内。
- 写中文 JSON 用 `ensure_ascii=False`。
- 不做破坏性文件操作，除非任务明确要求。

**日志与错误**
- `logger = logging.getLogger(__name__)`。
- 文件 I/O、JSON 解析、网络、subprocess 一律 try/except；优先具体异常、**禁止裸 `except:`**；可恢复用 warning、失败用 error。
- API 返回 `jsonify()` 结构化错误，**不得暴露堆栈**。

**测试**
- 行为变更必须在 `tests/` 加/改 pytest（`test_*.py`）。
- 改 manifest 解析、安装器、CSS 作用域检查、插件 API 时，先跑最相关的单文件测试。
- 全仓**无 pytest 配置文件**；`tests/conftest.py:40-49` 已把 `ui_store.UI_DATA_FILE` 与 `chat_store.CHAT_DATA_FILE` 重定向到临时目录，不要破坏这个隔离。

**其它**
- 保留中文用户可见字符串（除非任务明确要求改写）。
- 不得无强理由替换既有架构模式或引入新框架/抽象。**本次不引入任何新依赖、不引入打包器**（`docs/DEVELOPMENT.md:9-10` 明确无打包器约束）。
- 不得静默新增工具配置；新增命令/工作流须同步更新 `AGENTS.md`。

**行号说明**：下文所有 `文件:行号` 都是**当前 HEAD 的定位起点**，实施过程中会漂移，请以内容匹配为准。

---

## 2. 权威决策清单（不要再回去协调三份设计文档）

三份设计文档有演进与反转，以下为**最终决策**。文档只用于查证依据。

### D1 — `frontend.entries` 取代旧三字段，且不保留别名

- **新增** `frontend.entries[]`：`{ id, kind, label, description?, icon?, contexts?, requires_selection?, surface?, priority?, badge?, shortcut?, when?, disabledHint? }`
- **删除** `frontend.panels` / `frontend.settings_tab` / `frontend.detail_tab` 的解析与下发（当前零消费者，删除不破坏任何东西）。
- 新增 `manifest_version`（本次为 `2`）；缺省视为 `1`。
- `manifest_version: 1` 的 manifest 若含上述旧字段 → **拒绝加载**并提示改用 `frontend.entries`。
- `kind` ∈ `dock | nav | settings | context | command | status`。
- `surface.type` ∈ `panel | modal | page | sheet`。
- 单插件 `entries` 上限 **16** 项，超出忽略并 warning。

### D2 — `api_version` 升 2，并支持多版本并存

- `core/version.py:11` `PLUGIN_API_VERSION = 1` → **`2`**。
- `core/version.py:13` `SUPPORTED_PLUGIN_API_VERSIONS = (PLUGIN_API_VERSION,)` → **`(2, 1)`**。
- 结构上要留出「按插件声明的版本走兼容分支」的位置（`api_version == 1` 的插件不使用 entries/surfaces/ui 新能力，其余行为不变）。
- **语义**：`api_version` = 宿主契约版本；`min_app_version` = 应用版本。两者独立，不要混用。
- 现状兼容性：`data/plugins/hello-world` 与 `data/plugins/stm-ai-assistant` 都声明 `api_version: 1`，因此本次改动后它们**仍能加载**（这也是多版本机制的第一个真实用例）。

### D3 — manifest 严格校验 + 分层错误信息

- 顶层未知键、`backend.*` / `frontend.*` 未知子键、`entries[].*` 未知子键 → **拒绝加载**。
- 允许的顶层键（白名单，需覆盖现有两个插件的 manifest）：
  `id`、`name`、`version`、`api_version`、`manifest_version`、`author`、`description`、`homepage`、`license`、`icon`、`min_app_version`、`backend`、`frontend`、`permissions`、`requires`、`config_schema`、`secret_schema`、`i18n`（为 N3 预留）。
- 错误信息分两层（这是新增设计）：
  ```python
  {
      'code': 'manifest_unknown_key',        # 机器可读
      'field': 'frontend.entrys',            # 技术细节，给作者/日志
      'msg': 'manifest 中存在未知字段 frontend.entrys',
      'hint': 'frontend 支持的字段：entry, styles, entries',
      'user_msg': '插件「XXX」的清单格式不正确，请联系插件作者更新。',  # 给 UI
  }
  ```
- `core/plugins/registry.py:118-119` 目前只注入单个 `load_error` 字符串，需扩展为结构化错误并保持向后兼容（`load_error` 保留为人类可读摘要）。
- 其余既有 warning 式宽松（未知 hook / 未知权限 / requires 非法项）**保持不动**，只对 `entries` 相关字段从严。

### D4 — 图标名成为正式契约（允许第三方使用宿主图标名）

- **允许**插件（含第三方）在 `entries[].icon` 与 `api.ui.icon()` 中使用宿主图标名。
- 交付四项：
  1. `api.ui.icon(name, options)` → 返回 `<svg><use href="/static/icons/<sprite>.svg#icon-<name>"></use></svg>` 元素；宿主内部持有「名字 → sprite」映射，规则与 `templates/components/icon.html:24` / `:37` 一致。
  2. 图标名清单导出：后端 `GET /api/plugins/ui-icons`，返回 `{name, sprite, category, keywords}[]`。**实现方式**：解析 `static/icons/*.svg` 里的 `id="icon-*"`（`ui.svg` 141 个、`detail.svg` 26 个、`preset.svg` 13 个、`sidebar.svg` 10 个，合计 190）。
  3. **安装期校验**：`entries[].icon` 若为宿主图标名（不含 `/` 与 `.`），校验其存在性；不存在则记 warning 并把图标降级为占位（**不拒绝加载**）。
  4. 契约承诺：图标名整表 `Stable`；允许新增；删除/改名走 deprecation。
- **新约束**：插件**不得**在自己 CSS 里硬编码 sprite 路径（如 `url('/static/icons/ui.svg#icon-x')`）——安装期静态检查发现即 warning。
- 命名空间区分：宿主图标名**不含** `/` 与 `.`；插件自带资源路径**必含** `/`。

### D5 — 入口 `kind` 准入分级（按 tier）

- tier 解析：查 catalog 条目 → `official` / `verified` / `community`；**不在 catalog 中的插件默认 `community`**。
- 分级：
  | kind | official | verified | community |
  |---|---|---|---|
  | `command` / `context` / `settings` / `dock` | ✅ | ✅ | ✅ |
  | `status` | ✅ | ✅ | ❌ |
  | `nav` | ✅ | ✅ | ❌ |
- 不允许的 kind：**忽略该 entry 并记 warning**（不拒绝加载整个插件）。
- `core/plugins/catalog.py:25` `CATALOG_SCHEMA_VERSION` 1 → **2**；`_normalize_entry`（`:85-121`）新增 `tier`（默认 `community`）与 `maintainer`（默认空）。`tier` 只由宿主仓库的清单决定，**插件 manifest 不能声明**。
- 注意：`stm-ai-assistant` 目前既不在 catalog 也未声明 entries，因此本次改动对它无影响。

### D6 — 坞槽位是宿主分配的资源

- 插件声明 `priority` 仅作**建议值**。
- 社区插件的 `dock` 入口**默认进溢出菜单，不进坞槽位**；用户显式拖入才固定。
- 坞可见槽位上限 **8**；单插件在坞内最多占 **2** 个槽位。

### D7 — `when` 条件表达式

```jsonc
"when": {
  "mode": ["cards"],
  "selection": "any",                        // none | any | single | multi
  "indexState": "ready",
  "config": { "requireKeys": ["api_key"] },  // 未配置则置灰
  "hostVersion": ">=1.0.0",
  "feature": ["hasNetwork"]
},
"disabledHint": "请先在插件设置中填写 API Key"
```
- **求值统一放宿主**（注册表算），插件只声明。
- `config.requireKeys` 语义：检查 `config_schema.properties` 与 `secret_schema.properties` 里对应键是否有非空值；不满足 → 入口**可见但置灰**，`title`/tooltip 显示 `disabledHint`，**点击直接跳到该插件的配置/密钥区**（不是无反应）。
- `contexts` 字段保留（等价于 `when.mode`），两者同时存在时取交集。

### D8 — 前端运行时 API（命名统一到「名词命名空间」）

新增/调整为以下形态。**保留**旧成员以避免破坏现有插件，但旧成员内部改为委托到新实现，并在文档标 deprecated。

```js
// ---- 入口 ----
api.entries.register(spec)            // → entryKey
api.entries.update(entryId, patch)
api.entries.remove(entryId)           // → boolean
api.entries.setBadge(entryId, value)  // number | string | null
api.entries.setProgress(entryId, {done, total} | null)
api.entries.setStatus(entryId, 'ok' | 'warn' | 'error' | 'idle')
api.entries.setBusy(entryId, bool)
api.entries.open(entryId)
api.entries.list()

// ---- 界面 ----
api.surfaces.register(surfaceId, { title, mount(container, ctx), unmount(), onOpen(ctx), onClose() })
api.surfaces.open(surfaceId, ctx)     // ctx: { source, targetId, mode }
api.surfaces.close(surfaceId)
api.surfaces.isOpen(surfaceId)

// ---- 宿主 UI 原语 ----
api.ui.icon(name, options)            // → HTMLElement
api.ui.panel({ title, subtitle, actions })
api.ui.section({ title, description })
api.ui.card({ title, meta })
api.ui.field(schemaEntry, { value, onChange })
api.ui.form(schema, { values, onSubmit })
api.ui.button({ label, variant, icon, onClick, disabled })   // variant: primary|secondary|danger|ghost
api.ui.toolbar(items)
api.ui.empty({ icon, title, description, action })
api.ui.error({ title, message, retry })
api.ui.loading({ label })
api.ui.badge({ value, tone })         // tone: neutral|info|success|warning|danger
api.ui.list({ items, renderItem, empty })
api.ui.table({ columns, rows })
api.ui.grid({ columns, gap })
api.ui.split({ left, right, ratio })
api.ui.confirm({ title, message, danger })   // → Promise<boolean>
api.ui.prompt({ title, fields })             // → Promise<object|null>

// ---- 存储与配置 ----
api.storage.get(key) / set(key, value) / remove(key) / keys()   // 底层走 ui_data._plugins_v1.<id>.storage
api.onConfigChange(handler)           // → unsubscribe

// ---- 宿主内建能力（旧的裸动词收敛到这里，旧名保留为别名）----
api.host.toast / refresh / switchMode / openDetail / openSettingsSection / notify / log
```

**`mount(container, ctx)` 契约**（写进文档并在宿主侧强制）：
- 宿主传入的 `container` 已完成定位、尺寸、滚动、`data-marquee-ignore`、`role="dialog"`/`aria-modal`、焦点陷阱、ESC 关闭。
- 插件**只能**在 `container` 内创建 DOM。
- 插件**不得**设置 `container` 或其祖先的 `position` / `z-index` / `inset`。
- `mount` 返回函数时，宿主在关闭时调用它。
- **宿主必须在插件被禁用/卸载时强制卸载所有 surface，不依赖插件的 `deactivate`。**

### D9 — 修掉三个既有缺陷

1. **`activate()` 返回值被丢弃**：`static/js/pluginHost.js:147-178` 调 `await module.activate(api)` 后丢掉返回值。改为记录为插件级 disposer，在 `destroy` 时调用。
2. **`PluginHost.destroy` 无调用方**（`static/js/pluginHost.js:567-583`）：至少让它能被入口注册表/表面宿主调用；`destroy` 内补 surface 卸载。
3. **上传安装不绑定 id**：`core/plugins/installer.py:428-429 install_from_upload` → `install_plugin_dir(plugin_root, source_label=source_label)` **缺 `expected_id`**，而 catalog 路径（`:377` → `:397-399`）有。上传 UI 允许（可选）填写期望 id，不匹配时**警告**（不拒绝，因为上传是离线兜底）。

### D10 — 配置变更通知

- `static/js/components/pluginManager.js:328-342 saveConfig()` 成功后目前只有 `toast("配置已保存")`，**不派发任何事件**，插件 UI 读不到新值。
- 新增宿主事件 `plugin-config-changed`（`detail: { pluginId, config }`）+ `api.onConfigChange(handler)`。
- **不要复用** `settings-saved`（`static/js/components/settingsModal.js:783`、`static/js/state.js:1375` 是宿主自身设置用的，消费方在 `static/js/components/cardGrid.js:291`、`static/js/components/presetEditor.js:291`）。
- 密钥保存同理：`plugin-secrets-changed`。

### D11 — 资产版本化

- `core/plugins/assets.py:108` 只设 `Cache-Control: no-cache`，URL 无版本 → 插件更新后浏览器可能复用旧 CSS/JS。
- 在 `static/js/pluginHost.js:64-74 toAbsoluteAssetUrl` 与 `:76-90 injectStyle` 统一追加 `?v=<plugin version>`。
- 后端 `send_file` 保持 `max_age=0`，无需改响应头策略。

### D12 — 静态检查加强（且必须进入 `@media`）

`core/plugins/installer.py:521-589 scan_css_scope` 现在**只查作用域**。新增三项声明层检查：

| 检查 | 级别 |
|---|---|
| `position: fixed` | warning + UI 标记（**不拒绝加载**） |
| `var(--x)` 引用的 `--x` 不在宿主令牌清单内且**无回退值** | warning |
| 非作用域选择器上的 `!important` | warning |
| 硬编码 sprite 路径 `url('/static/icons/...')`（D4） | warning |

**关键实现陷阱**：`scan_css_scope` 用 `skip_blocks` 计数（`installer.py:563-566`）**跳过** `@media`/`@supports`/`@layer`/`@container`/`@keyframes`/`@font-face` **内部的选择器检查**。`tests/test_plugin_css_scope.py:48-54` 明确断言 `@media (max-width:600px){ .card{display:none} }` → `[]`。

所以：
- **不要修改 `scan_css_scope` 的现有行为**（有测试锁定）。
- 新增**独立的**遍历函数（如 `scan_css_declarations`），它**必须进入** `@media` 块内部——否则插件把浮层写进 media query 就绕过了。
- `tests/test_plugin_css_scope.py:81-87` 的现有行为（`@media print { body{...} }` + 顶层 `.card{...}` → `['.card']`）必须保持不变。

**令牌清单来源**：需要一个可枚举的宿主 CSS 令牌集合。建议从 `static/css/modules/variables.css:17-35` 的 `:root` 块解析生成（可作为构建期产物或启动时缓存），同时作为 `GET /api/plugins/ui-tokens` 导出（第三方查阅用）。

---

## 3. 实施阶段

> 每阶段结束**必须**：跑该阶段相关测试 → 报告改动文件清单 + 测试结果 + 遗留问题。阶段之间不要跳。

### 阶段 0 — 冻结与准备

1. 更新 `docs/2026-09-22-plugin-system-design.md`：
   - 第 2.2 节（`:157-243`）manifest 规范：删除 `frontend.panels` / `settings_tab` / `detail_tab` 样例（`:187-191`），加入 `frontend.entries` 样例与校验规则表。
   - 第 8.3 / 8.4 节：补入口契约、surface 契约。
   - 第 8.4 节 F11 / F12 之后追加 **F13**（插件不得自绘 `position: fixed` 浮层）、**F14**（surface 容器归宿主）、**F15**（插件不得硬编码 sprite 路径与 CSS 令牌无回退值）。
   - 第 9 节：补「入口总览」。
   - 第 10.3 节（`:1368-1421`）：按 D8 更新前端 API 契约。
   - 第 11 节：新增阶段记录。
2. 更新 `AGENTS.md`：若本次引入新命令（如生成图标清单/令牌清单的脚本），必须在此登记。
3. **不要**在此阶段改代码。

**验收**：文档与 D1–D12 一致；`python tools/gen_plugin_api_docs.py --check` 仍然通过（此阶段还没动 API）。

---

### 阶段 1 — 契约层（manifest + version + entries 解析）

**改 `core/plugins/manifest.py`**
- 新增常量：`SUPPORTED_MANIFEST_VERSIONS = (2, 1)`、`DEFAULT_MANIFEST_VERSION = 1`、`MAX_ENTRIES_PER_PLUGIN = 16`、`ENTRY_KINDS = frozenset({'dock','nav','settings','context','command','status'})`、`SURFACE_TYPES = frozenset({'panel','modal','page','sheet'})`、`KNOWN_TOP_LEVEL_KEYS`、`KNOWN_BACKEND_KEYS`、`KNOWN_FRONTEND_KEYS`、`KNOWN_ENTRY_KEYS`。
- `PluginManifest` dataclass（`:252-286`）：新增 `manifest_version: int = 1`、`frontend_entries: list`；**删除** `frontend_panels` / `frontend_settings_tab` / `frontend_detail_tab`。
- `load()`（`:332-`）：
  - 解析 `manifest_version`；不在支持集合 → 拒绝。
  - 顶层/子层未知键 → 拒绝（D3）。
  - `frontend.entries` 解析 + 逐项校验（`id` 非空且 `^[a-z][a-z0-9-]{0,63}$`、`kind` ∈ ENTRY_KINDS、`label` 非空、`icon` 可解析、`surface.type` ∈ SURFACE_TYPES、`contexts` 元素 ∈ 已知 mode 集合）。
  - **删除** `:486-494` 的 `panels` / `settings_tab` / `detail_tab` 解析。
  - `manifest_version == 1` 且含旧三字段 → 拒绝并提示改用 `frontend.entries`。
- `to_dict()`（`:304-330`）：新增 `entries`；**删除** `panels` / `settings_tab`。

**改 `core/plugins/errors.py`**
- `PluginManifestError` 支持结构化字段（`code` / `field` / `hint` / `user_msg`），保持 `str(exc)` 可读。
- `core/plugins/routes.py:41` 的 `exc.to_dict()` 路径要能带出这些字段。

**新增 `core/plugins/entries.py`**
- `build_entry_key(plugin_id, entry_id)` → `f'{plugin_id}:{entry_id}'`
- `normalize_entries(plugin_id, raw_entries, *, tier='community')` → 归一化后的列表（补默认值、丢弃非法项、应用 D5 的 kind 分级、应用 16 项上限）
- `is_host_entry_key(key)` / `CORE_ENTRY_PREFIX = 'core:'`
- 供 manifest 解析与运行时共用。

**改 `core/version.py`**
- `PLUGIN_API_VERSION = 2`；`SUPPORTED_PLUGIN_API_VERSIONS = (2, 1)`。

**改 `core/plugins/registry.py`**
- `PluginState`（`:31-86`）的 `header` / `detail()` 带出 `entries` 与结构化 `load_error`。
- `_mark_failed` 保留结构化错误。

**测试**
- 扩展 `tests/test_plugin_manifest.py`：entries 合法/非法用例、未知键拒绝、旧字段拒绝、`manifest_version` 处理、`api_version: 1` 仍可加载。
- 新增 `tests/test_plugin_entries_contracts.py`：全局键格式、同插件重复 id、跨插件同 id 不冲突、kind 分级、16 项上限、`core:` 前缀。
- **必须同步更新 `tests/test_plugin_contract_values.py:147-152`**：它现在断言 `PLUGIN_API_VERSION == 1` 且 `SUPPORTED_PLUGIN_API_VERSIONS == (1,)`，还要求设计文档含 `'当前 `{1}`'`。改常量就必须改这里 + 改设计文档对应文字，否则测试红。

**验收**：`python -m pytest tests/test_plugin_manifest.py tests/test_plugin_entries_contracts.py tests/test_plugin_contract_values.py tests/test_plugin_registry.py -q` 全绿；`data/plugins/` 下两个插件仍能被 `load_all()` 正常加载（可写一个临时脚本验证，不落盘）。

---

### 阶段 2 — 校验层（静态检查 + 安装期校验 + 分层错误）

**改 `core/plugins/installer.py`**
- **不动** `scan_css_scope`（`:521-589`）与 `_is_keyframe_selector`（`:592-595`）。
- 新增 `scan_css_declarations(css_path, plugin_id, *, known_tokens)` → 返回 `{'position_fixed': [...], 'unknown_tokens': [...], 'important': [...], 'hardcoded_sprite': [...]}`。
  - 必须进入 `@media`/`@supports`/`@layer`/`@container` 块内部。
  - 跳过 `@keyframes`/`@font-face` 内部的声明。
- 新增 `scan_style_declarations(manifest, *, known_tokens)` → `{相对路径: {...}}`。
- 新增 `resolve_known_tokens()`：从 `static/css/modules/variables.css` 的 `:root` 块解析出令牌名集合（带进程内缓存）。
- 安装流程 `install_plugin_dir`（`:275-345`）在现有 `scan_style_scope` 之后追加声明层扫描，结果持久化到 `ui_data._plugins_v1.<id>.style_declaration_warnings`（与现有 `_persist_style_scope_errors` 同风格，不要混用同一个键）。
- `read_style_scope_errors`（`:629`）旁新增 `read_style_declaration_warnings`。
- 上传安装 `install_from_upload`（`:412-434`）支持可选 `expected_id` 参数（D9.3）。

**改 `core/plugins/manifest.py`**
- `entries[].icon` 宿主图标名校验（D4.3），需要图标名清单来源（阶段 3 会做成 API，此处先做一个可复用的解析函数，建议放 `core/plugins/icons.py`）。

**新增 `core/plugins/icons.py`**
- `list_host_icons()` → `[{name, sprite, category, keywords}]`，解析 `static/icons/*.svg` 的 `id="icon-*"`。
- `sprite_for_icon(name)` → sprite 文件名，规则与 `templates/components/icon.html:24` / `:37` 一致（`sidebar_icon` 的 4 个 ui.svg 名字、`detail_icon` 的 24 个 ui.svg 名字、其余按宏归属）。
- `is_host_icon_name(value)` → 不含 `/` 与 `.` 且非空。
- 进程内缓存，注意 PyInstaller 打包态要读 `INTERNAL_DIR`（`core/config.py:12-18`）。

**测试**
- 扩展 `tests/test_plugin_css_scope.py`：**保持现有用例不变**，新增 `scan_css_declarations` 的用例，**必须包含「`@media` 内的 `position:fixed` 被抓到」**。
- 新增 `tests/test_plugin_icons.py`：图标清单解析、sprite 路由规则、宿主名判定。
- 扩展 `tests/test_plugin_installer.py`：声明层警告持久化、上传 `expected_id` 警告路径。

**验收**：`python -m pytest tests/test_plugin_css_scope.py tests/test_plugin_icons.py tests/test_plugin_installer.py tests/test_plugin_assets.py -q` 全绿；手工确认对 `data/plugins/stm-ai-assistant/frontend/plugin.css` 跑声明层扫描能报出 `position: fixed`（该文件 `:15-36` 的 launcher 与 `:72-87` 的 overlay 都是 `position:fixed`）。

---

### 阶段 3 — 运行时层（注册表 + 图标 API + 配置通知 + 资产版本）

**新增 `static/js/entryRegistry.js`**
- 条目增删改查、全局键生成、按 `mode` 过滤、`when` 求值、排序（用户偏好优先，其次 `priority`）、tier 分级应用。
- 监听 `plugins:loaded` 重建；未启用插件（`entry.enabled === false`）的条目不进入注册表。
- 暴露给 `entryDock` / `commandPalette` / 总览页消费。
- 与后端布局偏好同步（`ui_data._entry_layout_v1`，见阶段 5）。

**改 `static/js/pluginHost.js`**
- `loadPlugin`（`:147-178`）：记录 `activate()` 返回值为插件级 disposer（D9.1）；从 `manifest.entries` 注册条目到 `entryRegistry`。
- `buildApi`（`:180-543`）新增 D8 的全部命名空间；旧成员（`registerModal` / `registerSettingsSection` / `toast` / `refresh` / `switchMode` / `openDetail` / `openSettingsSection`）保留为别名并委托到新实现。
- `destroy`（`:567-583`）：补 surface 卸载、disposer 调用、注册表条目移除；并让它**有调用方**（至少注册表与表面宿主可调）。
- `toAbsoluteAssetUrl`（`:64-74`）与 `injectStyle`（`:76-90`）追加 `?v=<manifest.version>`（D11）。

**改 `static/js/components/pluginManager.js`**
- `saveConfig`（`:328-342`）成功后派发 `plugin-config-changed`；密钥保存路径派发 `plugin-secrets-changed`（D10）。

**改 `core/plugins/routes.py`**
- 新增 `GET /api/plugins/ui-icons`（D4.2）。
- 新增 `GET /api/plugins/ui-tokens`（D12 的令牌清单导出）。
- `/api/plugins/list`（`:110-127`）的返回体带出 `entries` 与 `tier`。

**改 `tools/gen_plugin_api_docs.py` + 重新生成 `docs/plugin-api.md`**
- `FRONTEND_MEMBERS`（`:68-94`）登记所有新成员，标注稳定性分级。
- `docs/plugin-api.md` 是**生成物**：`tests/test_plugin_api_docs.py:35-42` 断言磁盘内容 == `render()`。改完必须运行 `python tools/gen_plugin_api_docs.py`。
- 该测试还有 `test_every_public_method_is_grouped` / `test_frontend_keys_are_all_declared` 等断言，新成员必须同时进 `BACKEND_GROUPS`（`:42`）或 `FRONTEND_MEMBERS`。
- 文档末尾（`:139-143`）补 **「演进承诺」** 章节：Stable / Provisional / Experimental 三级的承诺内容 + deprecation 流程。

**测试**
- 扩展 `tests/test_plugin_host_contracts.py`：`activate()` 返回值被记录、`api.entries.*` / `api.surfaces.*` / `api.ui.*` 存在性与签名、旧成员仍可用。
- 扩展 `tests/test_plugin_api_docs.py` 相关断言。
- 新增前端契约测试（参照既有 `tests/test_*_frontend_contracts.py` 风格）：注册表条目数 = manifest entries 数、tier 分级生效、`when` 求值正确。

**验收**：`python -m pytest tests/test_plugin_host_contracts.py tests/test_plugin_api_docs.py tests/test_plugin_routes.py tests/test_plugin_manager_contracts.py -q` 全绿；`python tools/gen_plugin_api_docs.py --check` 返回 0。

---

### 阶段 4 — 界面层（surfaces + UI 原语）

**新增宿主 surface 宿主组件**
- `static/js/components/pluginSurfaceHost.js` + `templates/components/plugin_surface_host.html`（或等价实现）。
- 四种容器：`panel`（右侧抽屉，宽 `min(420px, 92vw)`，≤900px 变全屏 sheet）、`modal`（复用 `.modal-overlay` + `.ui-modal-shell`）、`page`（主内容区整页）、`sheet`（移动端底部 sheet）。
- 宿主负责：层级、尺寸、滚动、`data-marquee-ignore`、`role="dialog"` / `aria-modal`、焦点陷阱、ESC 关闭、**运行时 `mount()` 抛错时销毁该 surface 并把对应入口置错误态，不影响其他插件与宿主**。
- 层级：`panel`/`sheet` 用 `--z-modal` 档以下（建议新增 `--z-surface` 令牌）；`modal` 用 `--z-modal-popover`。
- **不使用 `backdrop-filter`**：`data/plugins/stm-ai-assistant/frontend/plugin.css:89-145` 记录了 Chromium 把 identity `backdrop-filter` 当 backdrop root 导致黑块的缺陷，宿主应避免重蹈。

**新增 UI 原语**
- `static/js/ui/primitives.js`（或 `static/js/utils/uiPrimitives.js`）+ `static/css/modules/ui-primitives.css`。
- 实现 D8 的 `api.ui.*` 全集。
- 表单控件必须与 `pluginManager.js:458-459 schemaEntries` / `:466-467 isRequired` 的既有渲染器**共用同一套**（`config_schema` 子集：`type` / `title` / `description` / `default` / `minimum` / `maximum` / `enum` / `secret` / `required`）。
- **样式只用 `.color-*` 语义类与既有 CSS 变量**：`tests/test_color_system_contracts.py:117-137` 禁止 `bg-red-*` / `text-blue-*` 这类 Tailwind 颜色类。
- 遵守 `prefers-reduced-motion`（仓库已有 33 处该媒体查询）。

**改 `static/js/app.js`**
- `registerComponents()`（`:50-89`）注册新组件。

**测试**
- 新增 `tests/test_plugin_surface_contracts.py`：`surfaces.register/open/close`、`mount` 返回函数在关闭时被调用、插件停用时宿主强制卸载、`container` 带 `data-plugin` 与 `data-marquee-ignore`、`mount` 抛错时的隔离。

**验收**：上述测试全绿；`tests/test_color_system_contracts.py` 全绿。

---

### 阶段 5 — 呈现层最小实现（地基的验收装置）

**新增入口坞**
- `static/js/components/entryDock.js`、`templates/components/entry_dock.html`、`static/css/modules/entry-dock.css`。
- 位置：`position: fixed; right: 0; top: 64px; bottom: 64px`（避开在流顶栏与翻页栏——`static/css/modules/layout.css:36-51` 与 `:2898-2907`）。
- 收起态 8px 热区（`opacity: 0` 但 `pointer-events: auto`），展开态 56px 图标列；hover 停留 150ms 或点击热区展开。
- 坞根元素带 `data-marquee-ignore`（`static/js/utils/marqueeSelection.js:11`）。
- 键盘：`role="toolbar"` + `aria-orientation="vertical"` + roving tabindex；`ArrowUp/Down` 移动、`Enter` 打开、`Delete` 取消固定。参照 `static/js/components/sidebar.js:214-235 handleModuleMenuKeydown` 的模式。
- 任何模态/抽屉打开时自动收起：`body:has(.modal-overlay) .entry-rail { … }`。
- **移动端**（`static/js/components/layout.js:159-191 reDeviceType()` → `deviceType === 'mobile'`）不渲染侧条，改为顶栏按钮 + 底部 sheet。
- 平板默认收起且不自动展开。

**新增溢出菜单 + 命令面板**
- 溢出：坞底部 `⋯` 槽位，弹层列出所有未固定入口，按插件分组 + 搜索框。
- 命令面板：`Ctrl/Cmd+K`（全仓 grep 确认零占用）；`static/js/components/commandPalette.js`；搜索范围 = 全部注册表条目 + 宿主内建命令。

**层级与令牌**
- `static/css/modules/variables.css:17-35` 新增 `--z-entry-rail`（建议 `80`，在 `--z-card-selected:50` 与 `--z-floating:100` 之间）及配套 `.z-entry-rail` 工具类（`:38-108` 风格）。
- **同时**把散落字面量归一到令牌：`view-beautify.css:494`(70)、`view-beautify.css:814`(40)、`modal-detail.css:3492`(46)、`modal-detail.css:3507`(44)。
- 注意：**800–2100 区间当前无任何令牌**，而插件硬编码的 2140/2150 正落此处。补齐时不要与插件现有值冲突。

**布局偏好存储**
- 顺序/固定/隐藏/分组/快捷键 → `ui_data._entry_layout_v1`（在 `core/data/ui_store.py:71-82` 处新增命名空间常量，风格一致）。
- 坞展开态/摆法 → localStorage `st_manager_entry_dock_prefs`（命名参照既有 `static/js/state.js:70 TAG_VIEW_PREFS_STORAGE_KEY = "st_manager_tag_view_prefs"` 与 `st_manager_per_page` / `st_manager_per_page_wi` / `st_manager_per_page_extensions` 的风格）。
- 后端新增 `POST /api/plugins/entries/layout` 保存布局偏好（走 `update_ui_data`）。
- **清理链**：`core/plugins/installer.py:491 _clear_ui_namespace` 扩展为同时剪除 `_entry_layout_v1` 中该插件的键。
- **禁用 vs 卸载**：禁用时条目随 `enabled=false` 从坞消失，但偏好**保留**（重新启用后恢复原位）。

**拖拽**
- 槽内重排用 Pointer Events（**不用 HTML5 DnD**：坞是 fixed 覆盖层，DnD 的 drag image 与 z-index 需额外验证）。先例：`static/js/utils/marqueeSelection.js:333 setPointerCapture`、`static/js/components/detailModal.js:972` / `:1199-1201`。
- MIME 类型（若最终仍用 DnD）：`application/x-st-entry`，沿用 `application/x-st-card` / `x-st-preset` / `x-st-worldinfo` / `x-st-folder` 家族。

**验收**：手工跑通——坞里出现条目；点开是宿主提供的抽屉；拖出/拖入/重排可用并持久化；禁用插件后条目立即消失、重新启用后偏好恢复；移动端退化为顶栏按钮 + 底部 sheet；框选不会命中坞。

---

### 阶段 6 — 治理与收尾

1. **入口总览页**：挂在既有「插件管理」页内（**不新增设置顶层 tab**——`static/js/components/settingsModal.js:304-306 selectSettingTab` 有 `if (!this.settingsHelpContent[section]) return;` 硬闸门，虽然 `plugins` 键已存在于 `:200-205`，但避免设置页膨胀）。表格列：图标+名称 / 归属 / 类型 / 出现位置 / 当前呈现 / 快捷键 / 操作。
2. **深链**：扩展 `static/js/components/pluginManager.js:43-47 ANCHOR_TABS`，支持 `plugin-config-<id>` 与 `plugin-secrets-<id>` 语义（切到 installed 页签 + 自动 `openConfig` + 滚动到位）。
3. **安装期披露**：目录卡片（`templates/modals/plugin_manager.html:353-402`）显示「此插件将添加 N 个入口」；tier 徽标（官方/认证/社区）。
4. **契约活体夹具**：升级 `samples/plugins/hello-world/`——填满全部 `kind`（dock/nav/settings/context/command/status），成为契约的活文档 + CI 夹具。**这是本次唯一需要改的「插件」，且它在 `samples/` 下，不影响 `data/plugins/`。**
5. **死 CSS 清理**：`static/css/modules/layout.css:2522-2533 .sidebar-toggle-button` 全仓零引用，删除。
6. **顺带修正两处不一致**（低成本，可做）：
   - `templates/components/header.html:196` 硬编码 `<span class="app-version-badge">V103</span>`，而 `core/version.py:8 APP_VERSION = '1.0.0'` —— 改为从后端注入。
   - `docs/2026-09-22-plugin-system-design.md:1609`（R2）写「提供 `api.spawn_thread()` 封装」，但该 API **不存在**（`core/plugins/api.py` 内无任何 thread 引用）——要么实现，要么改文档。

---

## 4. 全局验收标准

- [ ] `python -m pytest tests/ -q` 全绿（至少 `tests/test_plugin_*.py`、`tests/test_color_system_contracts.py`、`tests/test_settings_frontend_contracts.py` 全绿）。
- [ ] `python tools/gen_plugin_api_docs.py --check` 返回 0。
- [ ] `data/plugins/` 下两个既有插件仍能被 `load_all()` 正常加载（它们声明 `api_version: 1`）。
- [ ] 新契约在 `docs/plugin-api.md`（生成物）与 `docs/2026-09-22-plugin-system-design.md` 中都有对应描述；`tests/test_plugin_contract_values.py` 的「代码常量 ↔ 文档描述」双向断言通过。
- [ ] 没有引入任何新依赖（`requirements.txt` / `package.json` 不变）。
- [ ] 所有新增前端样式只用 `.color-*` 语义类与既有 CSS 变量。
- [ ] `AGENTS.md` 若涉及新命令/工作流已同步更新。

---

## 5. 已知陷阱清单（踩过或差点踩的）

1. **`scan_css_scope` 的 `skip_blocks`** 会跳过 `@media` 内部选择器（`core/plugins/installer.py:563-566`），有测试锁定（`tests/test_plugin_css_scope.py:48-54`）。新检查必须用**独立遍历**且必须进入 `@media`。
2. **`docs/plugin-api.md` 是生成物**，改前端 API 必须改 `tools/gen_plugin_api_docs.py` 并重新生成，否则 `tests/test_plugin_api_docs.py:35-42` 红。
3. **`tests/test_plugin_contract_values.py:147-152`** 断言 `PLUGIN_API_VERSION == 1` 且文档含 `'当前 `{1}`'`。改常量必须同时改测试与文档。
4. **`settingsHelpContent` 是硬闸门**（`static/js/components/settingsModal.js:304-306`）。新增设置分区必须同时加键，否则 `selectSettingTab` 静默 no-op（F8）。
5. **`PluginHost.destroy` 目前零调用方**，`activate()` 返回值被丢弃（`static/js/pluginHost.js:147-178`、`:567-583`）。改这两处时要一并补调用方，否则是死代码。
6. **`install_from_upload` 不绑定 `expected_id`**（`core/plugins/installer.py:428-429`），而 catalog 路径绑（`:377` → `:397-399`）。别把两者搞混。
7. **`settings-saved` 事件已被宿主自身占用**（`static/js/components/settingsModal.js:783`、`static/js/state.js:1375`；消费方 `static/js/components/cardGrid.js:291`、`static/js/components/presetEditor.js:291`）。插件配置通知要用**新事件名**。
8. **不要在坞/面板上用 `backdrop-filter`**：`.main-container` 已带 `backdrop-filter: blur(var(--bg-blur))`（`static/css/modules/layout.css:12-24`），Chromium 会把它当 backdrop root，叠加固定定位的大内容会渲染出黑块（详见 `data/plugins/stm-ai-assistant/frontend/plugin.css:89-145` 的实测记录）。
9. **PyInstaller 打包态** `static/` 是只读的 `_MEIPASS` 快照（`core/config.py:12-18`、`.github/workflows/build-desktop.yml:39-40`）。图标/令牌清单解析要读 `INTERNAL_DIR`，不要写回 `static/`。
10. **`data/` 被 gitignore**（`.gitignore:9`），插件安装目录不进版本库。任何新增的宿主持久化都应落在 `data/system/` 或 `ui_data.json` 命名空间，不要落在 `static/`。
11. **`tests/conftest.py:40-49` 的数据隔离**：写 `ui_data` 相关测试时不要绕过它。
12. **全仓无 pytest 配置文件**：不要静默新增 `pytest.ini` / `pyproject.toml` / `setup.cfg`。

---

## 6. 建议的执行顺序与停止点

```
阶段 0（文档冻结，不改代码）
   ↓
阶段 1（契约层）  ← 地基核心 1/4
   ↓
阶段 2（校验层）  ← 地基核心 2/4
   ↓
阶段 3（运行时层）← 地基核心 3/4
   ↓
阶段 4（界面层）  ← 地基核心 4/4
   ↓  ← 做完这里，地基已成，可以停下来评审
阶段 5（呈现层）  ← 验收装置
   ↓
阶段 6（治理与收尾）
```

- **最小地基** = 阶段 0–4。做完即可支撑后续的导航数据化、右键菜单项、设置区块等独立工作。
- **建议至少做到阶段 5**：没有坞，`entries` 契约就没有消费者，无法端到端验证，也就无法确认地基真的可用。
- **阶段 6 可分批**：总览页与深链优先，活体夹具与死 CSS 清理可延后。

**每阶段结束报告格式**：
1. 改动文件清单（含行数变化）
2. 该阶段相关测试命令与结果
3. 与本文档的偏差（若有，说明原因）
4. 遗留问题与建议的下一步

---

## 7. 一句话提醒

本次的目标不是「把坞做出来」，而是**把「插件声明、宿主渲染」这条契约立起来**。坞只是第一个消费者。如果做完之后，第三方插件仍然需要自己写 `position: fixed` 的浮层才能暴露入口，那地基就没打对。
