# 插件契约 v3 实现日志

> 设计事实源：`docs/2026-10-21-plugin-contract-v3-design.md`（下称「设计文档」）。
> 决策记录：`docs/adr/0001`–`0016`；术语：`GLOSSARY.md`。
> 本文件按设计文档 §10.3 的五阶段追加：完成了什么、测试结果、与设计的偏差。
> 任务 prompt：`docs/2026-10-21-plugin-contract-v3-implementation-prompt.md`。

---

## 阶段 0 · 基线与共享实现决策

### 0.1 环境与基线

- Windows + PowerShell；Python 3.12.10；pytest 全量基线：**3855 passed, 1 skipped**（142.96s，2026-10-22）。
- 工作区既有的未提交设计产物（GLOSSARY.md、`docs/adr/`、v3 设计文档、implementation prompt、
  AGENTS.md 的 v3 段落、旧设计文档的 superseded banner）在本任务开始时已经存在，不重复创建。
- 不修改与插件契约无关的既有未跟踪文件：`debug.log`、`run5000.log`、
  `docs/2026-10-16-android-apk-feasibility.md`、`docs/agents/`、`scripts/`。

### 0.2 共享实现决策（所有工作流必须遵守）

以下决策把设计文档落成**唯一一种实现形状**，避免并行实现时前后端/工具链各写一套。

#### S1 契约版本与单一事实源

- `core/version.py`：`PLUGIN_API_VERSION = 3`、`SUPPORTED_PLUGIN_API_VERSIONS = (3,)`。
- 新增 `core/plugins/contract.py`：**纯标准库、不 import 宿主其它模块、无副作用**。
  集中定义 manifest/api 版本、键白名单、7 个落点、5+`empty.*` 插槽、能力位、`when` 键、
  容量上限、ID/版本/shortcut 正则与声明层校验（`validate_manifest` / `normalize_contributions` …）。
- `core/plugins/entries.py` **删除**，由 `core/plugins/contributions.py` 取代（宿主适配层：
  调 contract、补图标检查/计数、把 issues 转成 warnings）。
- 独立校验器 `tools/stm_plugin_check.py` 由生成器把 `contract.py` 源码**逐字内嵌**，
  因此与宿主同源；宿主 `manifest.py` 也走同一套 `contract.validate_manifest()`。
  `core/version.py` 不 import contract（避免循环导入），`test_plugin_contract_values.py`
  断言两处 API 版本一致。

#### S2 后端 manifest v3 归一化快照（`PluginManifest.to_dict()`）

```json
{
  "id": "…", "name": "…", "version": "0.3.0",
  "api_version": 3, "manifest_version": 3,
  "author": "…", "description": "…", "homepage": "…", "license": "…",
  "icon": "…", "min_app_version": "…",
  "backend": true, "frontend": true, "frontend_only": false,
  "frontend_entry": "frontend/plugin.js",
  "frontend_styles": ["frontend/plugin.css"],
  "frontend_global_styles": ["frontend/global.css"],
  "render_mode": "declarative",
  "capabilities": ["cards.read", "ui.custom"],
  "requires": {}, "jobs": [], "hooks": [],
  "contributions": {
    "menus": [ …根节点，children 递归… ],
    "slots": [ {"id","slot","title","order","when","module","export"} ],
    "commands": [ {"id","title","description","icon","shortcut","when","module","export"} ]
  },
  "config_schema": {}, "secret_schema": {}
}
```

- **删除** `entries` 与 `permissions`（不保留别名）。
- 菜单节点归一化形状（默认值总是补齐）：
  `{id, placement(仅根), type, label, description, icon, order, when, badge, disabledHint, action, children}`
  - `type: "item"` → `action` 必填；`type: "submenu"` → `children` 必填（数组）；`type: "separator"` → 其余字段可省。
  - `action`: `{"type":"surface","id"}` / `{"type":"command","id"}` / `{"type":"url","url"}`；
    `command` 的 id 必须在 `contributions.commands` 中存在（安装期校验）；`url` 仅 `http(s)://`。
  - `order` 默认 `100`；`when` 归一化为 `{}` 或受支持子键。
- `frontend_global_styles`：只有声明了 `ui.global_styles` 能力位时才保留可注入路径，
  否则置空 + 警告（宿主拒绝注入）；`render_mode` 缺省 `"declarative"`。
- `PluginState.build_header()`（`/api/plugins/list` 的 item 顶层）把 `permissions` 改为
  `capabilities`、把 `entries` 改为 `contributions`（快照；失败插件为空对象），并补 `render_mode`。
- catalog（`static/plugins/catalog.json` + `core/plugins/catalog.py`）：`permissions` → `capabilities`，
  `schema_version`/`api_version` 升 3；`tier` 只作披露，不再限制贡献类型（删除 `apply_tier`）。

#### S3 前端贡献注册表 `static/js/contributionRegistry.js`

替换 `entryRegistry.js`（删除后者；排序/过滤/`when` 求值工具保留在新文件里）。
数据来源：`/api/plugins/list` 的 `item.manifest.contributions`（`enabled !== false` 的插件）。

```js
export const MENU_PLACEMENTS = [...];       // 7 个落点，与 contract.MENU_PLACEMENTS 一致
export const SLOT_NAMES = [...];            // 5 个命名插槽
export const EMPTY_SLOT_PREFIX = "empty.";
export const MENU_NODE_TYPES = ["item","submenu","separator"];
export const MAX_MENU_NODES_PER_PLUGIN = 64;
export const MAX_MENU_DEPTH = 3;
export const MAX_COMMANDS_PER_PLUGIN = 32;
export const MAX_SLOTS_PER_PLUGIN = 16;
export const MAX_DOCK_SLOTS = 8;
export const MAX_DOCK_PER_PLUGIN = 2;
export const CORE_PLUGIN_ID = "core";
export const KILL_SWITCH_COMMAND_ID = "core:plugins:close-overlays";

export function isKnownSlot(name) { … }                 // 含 empty.<mode>（8 个模式）
export function evaluateWhen(when, context = {}) { … }  // 返回 {ok, reasons}；无 when.target（落点隐含）
export function hostAppVersion() / hostDeviceType() / hostFeatures()

export const ContributionRegistry = {
  init(),                       // 幂等：监听 plugins:loaded / 配置/密钥变更 / 模式与选中变化；广播 contributions:changed
  setPlugins(items),            // 由 pluginHost.loadAll() 调用；声明层整体重建，运行期 update 重置
  context(overrides),           // {mode, selectionCount, config, hostVersion, feature, indexState, targetKind}
  menuTree(placement, options), // 根节点数组（children 递归），排序：order → pluginId → id；每节点带 ok/reasons/enabled
  menus(placement, options),    // 根层扁平别名
  slotRecords(slot, options),   // 插槽记录数组（排序同上）
  commandRecords(options),      // 命令记录数组
  paletteEntries(options),      // 命令面板：commands（when 通过）+ commandPalette 落点菜单
  dockItems(), dockOverflow(),  // dock：全局 ≤8、单插件 ≤2；溢出进「更多」
  searchable(),                 // 兼容入口总览：菜单节点 + 命令
  findByShortcut(combo),        // 命令/核心命令（Ctrl/Alt/Meta 组合，规范化比较）
  get(pluginId, id),            // 菜单节点；不存在 → null
  getByKey(key),                // 全局键 `<pluginId>:<id>`
  list(pluginId),               // 本插件全部菜单节点（扁平，含 children）
  update(pluginId, id, patch),  // 仅 patch 白名单字段；不存在/被移除 → false
  remove(pluginId, id),         // 本次激活内移除；重新激活恢复静态声明
  coreCommands,                 // [{id: KILL_SWITCH_COMMAND_ID, pluginId: "core", title: "插件：关闭所有浮动界面", …}]
  notifyChange(),               // 派发 window CustomEvent "contributions:changed"
};
```

- 运行期记录形状（菜单）：`{id, key, pluginId, placement, type, label, description, icon, order,
  badge, disabledHint, action, when, children, status:"idle", busy:false, progress:null, ok, reasons}`；
  插槽/命令记录额外有 `slot` / `shortcut` / `module` / `export`。
- `update()` patch 白名单：`label` / `description` / `icon` / `badge` / `progress` / `status` /
  `enabled` / `disabledHint` / `busy` / `children`（`children` 仅 submenu，完整替换）。
- **删除** v2 的布局偏好（order/pinned/hidden/shortcuts 的 `_entry_layout_v1` 前端消费）
  与 `api.entries.*`；后端 `/api/plugins/entries/layout` 接口与 ui_data 键本期保留不动（无前端消费者）。
- `when` 求值失败 = **可见但置灰**（`ok:false` + `reasons`，渲染用 `disabledHint` 兜底文案），
  与 v2 行为一致；命令面板只列 `ok:true` 的命令。

#### S4 触发链路（渲染层 → 运行时）

- 渲染层不直接 import `pluginHost.js`（避免循环），统一派发：
  ```js
  window.dispatchEvent(new CustomEvent("contribution:trigger", {
    detail: { pluginId, nodeId, trigger: "menu" | "palette" | "shortcut" | "dock", ctx },
  }));
  ```
- `pluginHost` 在 `init()` 注册唯一监听，按节点 `action` 执行：
  - `surface` → `PluginSurfaceHost.openSurface(`${pluginId}:${id}`, ctx)`；
  - `command` → 动态 import `{module, export}` 并调用 `handler(ctx)`（`ctx.trigger` 见设计 §4.6）；
  - `url` → `window.open(url, "_blank", "noopener")`；
  - 核心命令（`pluginId === "core"` + `KILL_SWITCH_COMMAND_ID`）→ kill switch。
- `api.contributions.trigger(id, ctx)` 走同一执行器；节点不存在或 `when` 不满足返回 `false`。
- 异常一律宿主捕获（日志 + toast），连续错误触发「降级」（见 S6）。

#### S5 模块加载（插槽 / 命令）

- `module` 是**相对插件根目录**的路径；URL 用既有 `toAbsoluteAssetUrl(pluginId, path, version)`
  → `/api/plugins/<id>/assets/<path>?v=<version>`，再动态 `import()`；按 `(pluginId, path)` 缓存模块。
- **激活期静态校验**（设计 §4.9）：插件激活时预加载全部 `contributions.slots[].module` 与
  `contributions.commands[].module`，并校验导出存在且是函数；任一缺失/不可解析 →
  **该插件前端激活失败**（`PluginHost.failed` + 管理器显示错误与重试），**后端继续运行**。
- 运行期渲染器/处理器抛错（§4.5、§7.2）→ 该插槽显示错误占位 / 该命令警告，插件标记「降级」，
  不扩散到其他插件，不因此卸载插件。
- 插槽渲染器契约：`mount(container, ctx) -> cleanup`；`ctx = {api, pluginId, slot, mode, target, selection}`；
  容器由宿主创建并带 `data-plugin="<id>"`。

#### S6 根节点 / portal / overlay / kill switch

- 新增 `static/js/pluginRootHost.js`：
  `PluginRootHost.ensureLayers()` / `create(pluginId, {tag, portal})` / `clear(pluginId)` / `clearAll()`。
  两个层都是 `document.body` 直接子元素、`position:fixed; inset:0; pointer-events:none`：
  `.plugin-layer--content`（z-index `var(--z-plugin-content)`）、`.plugin-layer--portal`（`--z-plugin-portal`）。
  `api.createRoot()` 的返回元素由宿主创建、带 `data-plugin` 与 `plugin-<id>`；`createRoot(tag)` /
  `createRoot({portal:true})` / `createRoot({tag:"button"})` 都接受。
- 新增 `static/js/pluginOverlayHost.js`：`register(pluginId, spec) -> unregister` / `unregister` /
  `list` / `closeAll(pluginId)` / `closeAllPlugins()`；ESC 关最上层 `modal:true` 并归还焦点；
  `layer` 枚举 `content|ambient|surface|dock|popover|tooltip|alert`（建议值）。
- kill switch：命令面板内置命令 + 插件管理器按钮（都派发 `plugins:close-overlays`）→
  对每个插件：①已登记浮层逐个 `onDismiss`；②广播 `overlays:force-closed` `{pluginId}`；
  ③清空并移除该插件全部 root。不卸载/不停用插件。
- 崩溃隔离：渲染/命令/overlay 回调异常一律捕获；同一插件 5 次/分钟 → 标记 `degraded`
  （`PluginHost.isDegraded()` + `plugin:degraded` 事件 + 管理器提示），后端不受影响。
- 新 CSS：`static/css/modules/plugin-layers.css`（层级注入到 `tokens.css` 的
  `--z-plugin-content|ambient|dock|surface|popover|tooltip|alert` 令牌）。

#### S7 插槽容器锚点（模板约定）

- 宿主模板在插槽位置放容器：`<div data-plugin-slot="<slot name>"></div>`；
  `empty.<mode>` 用精确名（如 `data-plugin-slot="empty.cards"`）。
- `static/js/pluginSlotHost.js` 扫描锚点、建立/回收每个贡献的包装节点
  （包装节点带 `data-plugin`、`data-slot`），并调用渲染器；`contributions:changed` /
  `mode-changed` / `plugins:loaded` / `plugin:unloaded` 时整体刷新。
- 插槽位置（宿主模板）：`settings.section` → 设置弹窗内容区；`header.actions` → 顶栏动作区；
  `card.detail.tabs` → 卡片详情弹窗标签页；`page.cards.toolbar` → 角色卡视图工具栏；
  `page.worldinfo.toolbar` → 世界书视图工具栏；`empty.<mode>` → 各视图空状态区。

#### S8 事件收紧

- `api.emit()` 核心事件（`CORE_EVENTS`）→ **`console.warn` 并忽略**（不再派发）；
  自定义事件仍必须以 `<pluginId>:` 开头。
- `entries:changed` → `contributions:changed`；新增宿主事件 `overlays:force-closed`（`{pluginId}`）。
- `api.on("overlays:force-closed", h)` 走普通 window 事件订阅，插件据此重置状态。

#### S9 前端 API 顶层键（生成器会逐个校验）

`buildApi()` 顶层键：保留 `id` / `manifest` / `state` / `store` / `on` / `off` / `emit` /
`onConfigChange` / `toast` / `progress` / `host` / `surfaces` / `ui` / `storage` / `worldbook` /
`openDetail` / `refresh` / `switchMode` / `openSettingsSection` / `registerAlpineComponent` /
`api` / `subscribeJob` / `estimateTokens` / `utils` / `setFullscreenScrim` / `jobs` / `createRoot`；
**新增** `contributions` / `overlays`；**删除** `entries` / `registerModal` / `registerSettingsSection`。
`FRONTEND_MEMBERS` 由工具链同步更新。

#### S10 生成物与工具链

| 生成物 | 来源 | 生成/校验 |
|---|---|---|
| `docs/plugin-api.md` | `core/plugins/api.py` + `core/plugins/domains/*` + `pluginHost.js buildApi()` + `contract.py` + 生成器常量 | `python tools/gen_plugin_api_docs.py [--check]` |
| `docs/plugin-manifest.schema.json` | `contract.py` + 生成器常量 | 同上 |
| `docs/plugin-api.d.ts` | `contract.py` + `buildApi()` + 生成器常量 | 同上 |
| `tools/stm_plugin_check.py` | `contract.py` 源码逐字内嵌 + 独立严格检查逻辑 | 同上（`--check` 比对内嵌区） |
| `static/js/utils/iconMap.js` | `static/icons/*.svg`（本期不动） | `python tools/gen_plugin_ui_icons.py [--check]` |

- `stm_plugin_check.py` 用法：`python stm_plugin_check.py path/to/plugin [--json]`，非零退出 =
  存在宿主会丢弃/降级的问题；检查项按设计 §8.2 的 9 条（含 CSS 作用域扫描、模块/导出静态检查）。
- `tools/new_plugin.py` 脚手架升 v3（manifest 用 contributions + capabilities）。
- 新增生成物必须写进 `AGENTS.md` 的 Generated Artifacts 表；`entries.*` 的登记规则说明同步改。

#### S11 迁移

- 顺序：`data/plugins/stm-pet` → `samples/plugins/hello-world` → `data/plugins/hello-world` →
  `data/plugins/stm-ai-assistant` → 外部仓库（`D:\Workspace\MyOwn\ST-Manager-AI-Assistant`、
  `D:\Workspace\MyOwn\ST-Manager-Pet` 若可访问）。
- 外部仓库同时接 `stm_plugin_check` 到其 CI（脚本复制到插件仓库，standalone 运行）。
- 新增 `docs/plugin-migration-v2-to-v3.md`（第三方迁移指南，按设计 §10.1 对照表 + update 映射）。
- 迁移后插件仍须通过自身测试（外部仓库若有）。

#### S12 测试归属（避免同一测试文件被两人改）

- **backend-contract**：`tests/plugins_test_support.py`、`test_plugin_manifest.py`、
  `test_plugin_entries_contracts.py`（改写为 contributions 契约）、`test_plugin_contract_values.py`、
  `test_plugin_registry.py`、`test_plugin_catalog*.py`、`test_plugin_installer.py`、
  `test_plugin_install_source.py`、`test_plugin_routes.py`、`test_plugin_error_codes.py`、
  `test_plugin_cli.py`、`test_plugin_dependencies.py`、`test_plugin_loader.py`、
  `test_plugin_load_failure_isolation.py`、`test_plugin_isolation.py`、`test_plugin_css_scope.py`、
  `test_plugin_icons.py`、`test_plugin_icon_resolution.py`、`test_plugin_secrets.py`、
  `test_plugin_hooks.py`、`test_plugin_jobs.py`、`test_plugin_job_order.py`、`test_plugin_api*.py`、
  `test_plugin_sse*.py`、`test_ui_data_plugin_namespace_isolation.py`、`test_plugin_assets.py`
- **frontend-runtime**：`test_plugin_host_contracts.py`、`test_plugin_events.py`、
  `test_plugin_host_state.py`、`test_plugin_entry_registry_frontend_contracts.py`（改写为
  contributionRegistry）、`test_plugin_entry_notify_reentry.py`、`test_plugin_surface_contracts.py`、
  `test_plugin_ambient_surface.py` + 新增自绘/overlay/kill switch 契约测试
- **frontend-render**：`test_plugin_entry_dock_contracts.py`、`test_plugin_context_and_shortcuts.py`、
  `test_plugin_manager_contracts.py`、`test_plugin_job_panel_contracts.py`、`test_plugin_frontend_assets.py`
  + 新增插槽模板锚点契约测试
- **toolchain**：`test_plugin_api_docs.py` + 新增 schema/d.ts/checker 测试、`test_plugin_scaffold.py`
- **migration**：不新增宿主测试；用 `stm_plugin_check` 与外部插件自身测试自证

> 仓库没有 JS 测试框架：前端可自动化部分继续用「源码扫描式契约测试」写法
> （参考 `test_plugin_*_frontend_contracts.py`）。

### 0.3 工作流与写入范围

| 工作流 | 写入范围（互不重叠） |
|---|---|
| Lead | `docs/2026-10-21-plugin-contract-v3-implementation-log.md`、`AGENTS.md`（v3 段落）、
最终集成修复、全量测试 |
| backend-contract | `core/version.py`、`core/plugins/{contract.py 由 Lead 先行落地, contributions.py, manifest.py, entries.py 删除, registry.py, catalog.py, routes.py, installer.py, icons.py, cli.py, assets.py}`、`static/plugins/catalog.json`、`tests/` 中 S12 归属的测试 |
| frontend-runtime | `static/js/contributionRegistry.js`、`static/js/pluginHost.js`、`static/js/pluginRootHost.js`、
`static/js/pluginOverlayHost.js`、`static/js/pluginSlotHost.js`、`static/js/pluginSurfaceHost.js`、对应测试 |
| frontend-render | `static/js/components/*`（entryDock/commandPalette/contextMenu/header/pluginManager）、
`static/js/app.js`、`static/js/uiPrimitives.js`、`static/js/state.js`（仅注释）、`templates/**`、
`static/css/modules/**`、对应测试 |
| toolchain | `tools/**`、`docs/plugin-api.md`、`docs/plugin-manifest.schema.json`、
`docs/plugin-api.d.ts`、`.github/**`、`AGENTS.md`（Generated Artifacts 表 / 登记规则）、对应测试 |
| migration | `samples/plugins/**`、`data/plugins/**`、外部插件仓库、`docs/plugin-migration-v2-to-v3.md` |

**纪律**：不 `git commit/push`；不手改生成物（改源头后跑生成器）；不跨范围写别人的文件（需要时先
在共享任务/消息里说明）；用 `read`/`edit`/`write`/`grep`/`glob` 工具读写文件（PowerShell 控制台对
中文输出会乱码，读内容一律用 `read`）；每个阶段先改测试再实现，阶段末尾跑目标测试子集。

---

## 阶段 1 · 契约层（已完成）

### 实现

- `core/plugins/contract.py`（Lead 先行落地，宿主与 `stm-plugin-check` 的单一事实源，纯标准库、
  无宿主 import）：版本 `MANIFEST_VERSION/API_VERSION=3`、`SUPPORTED_*=(3,)`；结构键白名单
  （顶层 / `backend` / `frontend` / `contributions`）；7 落点、5 命名插槽 + `empty.<mode>`、8 工作模式；
  三原语、`when`、`action`、能力位、hook、JSON-Schema 子集、语义化版本/依赖约束/快捷键正则；
  容量与深度常量；`validate_manifest(payload, strict=)`、`normalize_contributions`、
  `normalize_when/normalize_action/normalize_menu_roots/normalize_slots/normalize_commands`、
  `normalize_capabilities`、`normalize_schema`、`finalize_issues(strict=True)`、
  `make_issue`/`has_errors`/`issue_summary`。宿主宽容 / CLI 严格的两级策略用
  `make_issue(..., escalate=True)` + `finalize_issues(strict=True)` 表达（设计 §4.9 / §8.2）。
- `core/plugins/contributions.py`（新，替代 `entries.py`）：宿主适配层——调用 contract 归一化、
  node 级 issue→warnings、图标资源检查、计数与 snapshot。
- `core/plugins/manifest.py`：`contract.validate_manifest(strict=False)` 薄封装 + 路径/入口解析 +
  `PluginManifest` v3 dataclass + `to_dict()`（S2 形状）。v2 manifest 优先报
  `PluginApiVersionError`（提示升级主程序）；x- 键不在宿主侧重校验。
- `core/plugins/entries.py`：**已删除**（`ENTRY_KINDS` / `normalize_entries` / `apply_tier` 一并移除）。
- `core/plugins/registry.py`：`build_header()` 的 `permissions→capabilities`、`entries→contributions`
  快照、`+render_mode`；删除 `apply_entry_tiers` 及加载期 tier 过滤（ADR-0008：tier 只披露）；
  `detail()['manifest']` 直接给 `to_dict()`。
- `core/plugins/catalog.py`：`CATALOG_SCHEMA_VERSION=3`、`permissions→capabilities`、tier 常量内聚
  （默认 `community`，只披露）；`static/plugins/catalog.json` 升 3（pet 的 `ui.custom` 与迁移后 manifest 一致）。
- `core/version.py`：`PLUGIN_API_VERSION=3`、`SUPPORTED_PLUGIN_API_VERSIONS=(3,)`。
- `routes.py` / `icons.py` / `api.py` 的 docstring 与字段清理；`installer.py` 无需改
  （仍按 `manifest.frontend_styles` 扫描作用域，`global_styles` 天然免扫）。

### 验证

- **Lead 独立验收矩阵**（45 项，覆盖 §11.1 全部条目：合法矩阵 / v2 拒绝 / 未知键 / 节点级容错 /
  x- 静默 / 容量 64 / 深度 3 / dock 2·8 / 命令 32 / 插槽 16 / 命令引用 / when / capabilities /
  global_styles 能力位 / render_mode / 依赖 / backend）：45/45 通过。
- `python -c "from core import create_app; create_app()"` → EXIT 0，本地插件加载正常。
- `python -m pytest tests/test_plugin_manifest.py tests/test_plugin_contract_values.py tests/test_plugin_contributions_contracts.py -q` → 121 passed。

### 偏差

- 无（唯一解释性取舍：深度 3 允许 3 层节点；第 4 层节点被丢弃，若其父 submenu 因此无子节点则整支丢弃，
  与「submenu 必须有非空 children」一致）。

## 阶段 2 · 前端注册表/渲染（已完成）

- `static/js/contributionRegistry.js`（新，~1400 行）：S3 全量 API——7 落点 / 5 插槽 / 容量常量与
  `contract.py` 对齐；`evaluateWhen`（可见但置灰，无 `when.target`）、`hostAppVersion/hostDeviceType/
  hostFeatures`、`menuTree/menus/slotRecords/commandRecords/paletteEntries/dockItems/dockOverflow/
  searchable/findByShortcut/get/getByKey/list/update/remove/coreCommands/notifyChange`；
  `update()` patch 白名单与 children 校验（command 必须已声明、surface 必须已注册）；
  运行期记录形状按 S3。`static/js/entryRegistry.js` **已删除**。
- 宿主 UI 消费端（frontend-render）：
  - `components/contextMenu.js`：`context.folder` / `context.card` / `context.footer` 三落点 +
    显式 submenu（fixed flyout，二级 `details` 折叠三级）+ 语义目标（folder path / card id）+
    可见但置灰 + 动态 badge/progress/status 重放。
  - `components/header.js` + `templates/components/header.html`：`batch.actions` 菜单树（父项开
    独立 fixed flyout，`x-teleport` 到 body 避开 header backdrop-filter 包含块）、
    `when.selection` 过滤、动态态、移动端 selection bar。
  - `components/entryDock.js`：`dockItems()`/`dockOverflow()`，全局 8 / 每插件 2 上限由注册表裁剪，
    「更多」溢出浮层（搜索 + 按插件分组），删除 v2 的 pinned/hidden/order/拖拽。
  - `components/commandPalette.js`：命令 + `commandPalette` 落点 + 宿主内建命令（含 kill switch）、
    插件 `shortcut` 派发、执行走统一 `contribution:trigger`。
  - `components/settingsModal.js` + `templates/modals/settings.html`：`settings.nav` 渲染进设置页
    导航（先探测 surface 存在，缺 surface 警告忽略）。
  - 插槽锚点：`[data-plugin-slot]` 覆盖 `settings.section`、`header.actions`、`card.detail.tabs`、
    `page.cards.toolbar`、`page.worldinfo.toolbar`、8 个 `empty.<mode>`（空容器，由 `pluginSlotHost`
    挂载渲染器）。
  - `components/pluginManager.js`：贡献总览（menus/slots/commands 静态只读）、capabilities、render_mode、
    全局样式警告、失败原因 + 重试（`plugin:reload`）、kill switch 按钮（tab 栏 + footer）。
  - `uiPrimitives.js`：menu / popover / tabs / layout 原语；`static/css/modules/plugin-layers.css`（新）
    + `variables.css` 的 `--z-plugin-*` 令牌 + 坞栏/设置/管理器样式 v3 化；`app.js` 初始化
    `PluginSlotHost` 并监听 `contributions:changed` / `plugins:loaded` / `mode-changed`。
- 测试：重写 `test_plugin_entry_dock_contracts.py` / `test_plugin_context_and_shortcuts.py` /
  `test_plugin_manager_contracts.py` / `test_plugin_job_panel_contracts.py` /
  `test_plugin_frontend_assets.py` / `test_plugin_slot_frontend_contracts.py`，
  6 文件 **100 passed**（另加图标解析 + 设计令牌 139 passed）。
- 宿主 UI 全部只读静态声明；运行时内容更新只走 `api.contributions.update`；渲染层不 import
  `pluginHost`，触发统一派发 `contribution:trigger`（设计 §6.4）。

## 阶段 3 · 自绘与共存（已完成）

- `static/js/pluginRootHost.js`：内容层/portal 层（`document.body` 直接子元素、
  `position:fixed;inset:0;pointer-events:none`）、`create(pluginId,{tag,portal})` / `getRoots` /
  `clear` / `clearAll` / `reset`，root 带 `data-plugin` 与 `plugin-<id>`。
- `static/js/pluginOverlayHost.js`：`register/unregister/list/get/count/closeAll/closeAllPlugins/
  killSwitch/handleKeydown`；ESC 只关最上层 `modal:true` 并归还焦点；kill switch 逐个插件
  ①`onDismiss` ②广播 `overlays:force-closed` `{pluginId}` ③（由 pluginHost）清 root。
- `static/js/pluginSlotHost.js`：扫描 `[data-plugin-slot]` 锚点、动态 import 渲染器、
  `mount(container, ctx) -> cleanup`、错误占位、`contributions:changed`/`plugins:loaded`/
  `mode-changed` 刷新；容器带 `data-plugin`/`data-slot`。
- `pluginHost.js`：S4 执行器（`contribution:trigger` 单一监听 → surface/command/url/核心命令）；
  S5 贡献模块激活期预加载与导出校验，失败 → 前端激活失败（回滚样式/root/disposer，
  `reloadPlugin` 可重试，后端继续）；运行期异常 → 占位/警告 + 5 次/60s 降级（`plugin:degraded`）；
  S8 `api.emit` 核心事件 warn+ignore、自定义事件必须 `<pluginId>:` 前缀；
  `global_styles` 仅能力位存在时注入（`data-plugin-style`）。
- 测试：`test_plugin_self_render_contracts.py`（12）、`test_plugin_overlay_contracts.py`（11）、
  `test_plugin_slot_contracts.py`（12），连同 runtime 重写的 7 个文件共 **190 passed**。

## 阶段 4 · 原语与工具链（已完成）

- `tools/gen_plugin_api_docs.py` 扩展为一次产出 4 件：`docs/plugin-api.md`（新增贡献 / `createRoot`
  两层 / `overlays` / 共存与 kill switch / 契约工具链章节，窗口事件表更新并标注 `entries:changed`
  已删除）、`docs/plugin-manifest.schema.json`（v3 完整 schema，`additionalProperties:false` +
  `^x-` 命名空间）、`docs/plugin-api.d.ts`（`PluginApiV3` 顶层 29 键与 `buildApi()` 逐一对齐）、
  `tools/stm_plugin_check.py`（`contract.py` 逐字内嵌 + 宿主事实内嵌，`--check` 校验漂移）。
  文档描述表（落点/插槽/when/节点字段/action/能力位/overlay 层级）在生成期与 `contract.py` 对账，
  新增枚举未补描述会直接 RuntimeError。
- `tools/stm_plugin_check.py`：独立单文件（不 import `core.*`），9 项检查（manifest 合法/大小/白名单/
  版本、落点/插槽/容量/深度/唯一 id、action 引用与 url 协议、模块存在与导出、`when`/shortcut、
  render_mode/capabilities/global_styles 一致性、CSS 作用域、图标资源、宿主版本提示），`--json`、
  错误非零退出、行号定位；`manifest_id_dir_mismatch` 在插件仓库根只 warning（宿主安装目录
  `.../plugins/<id>` 下才是 error）。
- `tools/new_plugin.py` 脚手架 v3（contributions + capabilities + render_mode + commands/slots 示例模块），
  生成物过 9 项检查 0 error / 0 warning；`tools/README.md` 同步。
- `.github/workflows/plugin-contract.yml`（新）：四件 `--check` + 5 个工具链测试 + samples/data
  插件严格校验（ADR-0010）。
- `AGENTS.md`：Plugin Contract v3 段重写为已实现契约摘要；Generated Artifacts 表 +3 行、
  内嵌 marker 规则、登记规则改为 `contributions.*`；Build & Packaging 登记新 workflow。

### 验证

- `python tools/gen_plugin_api_docs.py --check` → 4 件全部「已是最新」，exit 0；
  `python tools/gen_plugin_ui_icons.py --check` → exit 0。
- 工具链测试（docs/schema/checker/scaffold/icons）→ **122 passed**；checker 单文件 29 项
  （正例 + 19 个非零退出反例 + 目录名分级 + 内嵌区篡改可被抓到）。

## 阶段 5 · 迁移与收尾（已完成）

- `samples/plugins/hello-world`（git 跟踪夹具）→ v3 声明式：dock ×2、`context.card`、
  `batch.actions` submenu（含 separator + 2 个 command 项）、`commandPalette`、`settings.nav` +
  `settings.section` 插槽（`frontend/views/settingsSection.js`）、3 条命令
  （`frontend/commands.js`，`Ctrl+Shift+H`）；删除 `api.entries.register`，`plugin.js` 改用
  `api.contributions.update/trigger` 并订阅 `contributions:changed` 重放。
- `data/plugins/stm-pet`（0.4.0）：`render_mode:"custom"` + `ui.custom`；dock `pet-dock` +
  `settings.nav` `pet-settings`（`action.surface`），ambient surface 常驻宠物保留。
- `data/plugins/stm-ai-assistant`（0.3.0）：12 条 v2 入口 → 7 根节点 / 14 节点 + 4 条命令：
  dock `workbench`（命令 `open-workbench`，`Ctrl+Shift+A`）、`context.folder` submenu、
  `batch.actions` submenu、3 个 `commandPalette` 项、`settings.nav` → surface；
  `plugin.js` 状态回报改 `api.contributions.update`（progress 0–1）并订阅重放。
- 外部官方插件仓库：`ST-Manager-AI-Assistant`（744 passed）、`ST-Manager-Pet`（958 passed）
  均迁移 v3，接 `scripts/stm_plugin_check.py` + CI workflow（先摊到 `manifest.id` 同名目录再严格校验）。
- `docs/plugin-migration-v2-to-v3.md`（新，~470 行）：§10.1 对照表、kind→placement / group→submenu
  映射、`api.entries`→`api.contributions`、capabilities、自绘路线、迁移流程、错误码表、checker
  用法与 CI staging、三个迁移实例。
- `static/plugins/catalog.json` 版本与迁移后 manifest 同步（pet 0.4.0 / AI 0.3.0，api_version 3）；
  `docs/plugin-migration-v2-to-v3.md` 的 `manifest_id_dir_mismatch` 处置说明按 checker 新行为更新。

### 阶段 5.1 集成验证（Lead，真实浏览器冒烟）

`python app.py --port 5055` 起真实服务，浏览器加载并用 CDP 注入 console 捕获，逐项验证：
页面 0 JS 错误、`PluginHost.loaded=[stm-ai-assistant,stm-pet]`、插件入口/commands/chunks 全部请求、
坞栏 2 项（`workbench` + `pet-dock`）、`settings.nav` 2 项且点击打开对应 surface、右键分类菜单出现
「AI 助手」子菜单、批量操作出现插件子菜单（3 条命令，点击「AI 打标选中卡片」打开 `analyze` surface）、
`Ctrl+K` 命令面板 12 项且合并行「AI 结果与审批」可执行、pet ambient surface 挂载、
kill switch 清空内容层/portal 层 root。冒烟中发现并修复 4 个跨层集成缺陷：

1. **插件前端从未激活**（严重）：`pluginHost.loadAll()` 用 v2 的 `manifest.frontend` 对象守卫，
   而 S2 快照是 `frontend: true` 的扁平形状 → 所有插件被跳过。改为
   `needsFrontendActivation(manifest)` + 扁平 `frontend_entry` / `contributions`；新增用真实 S2
   payload 驱动 `loadAll()`（Node loader hook + 真实 `import()`）的回归测试。
2. **静态 surface 菜单被丢弃**：静态 ingest 阶段误用「surface 已注册」运行时校验，pet/AI 的
   `settings.nav` / dock surface 项全部消失。改为显式参数
   `{requireRegisteredSurface:false}`（静态路径只校验格式）与 `true`（`api.contributions.update`
   的 children），执行期未注册 surface → 警告忽略。
3. **命令面板永远空白**：`paletteEntries()` 同时返回命令记录与同 id 的 `commandPalette` 菜单项，
   3 对重复 key 触发 Alpine `x-for` 崩溃（`reading 'after'`）。改为命令+菜单语义合并为一行、
   key 唯一（撞名加 `#menu`），新增唯一性/合并回归测试。
4. **渲染层回归**：`ui-primitives.css` 的 `scrollbar-width: thin` 违反滚动条契约；
   `pluginManager.js` 仍读 nested `manifest.frontend.*`；`modal-settings.css` 混入非 UTF-8 字节；
   `pluginManager.js` 仍 import 已删除的 `entryRegistry.js`。均已修复并有测试守护。

另修正两处宿主测试/文档：`templates/components/header.html` 新增插件批量菜单行使
`test_source_update_pending_contracts.py` 的 `role="menuitem"` 计数 9→10（注释同步）；
checker 目录名分级行为写入迁移指南。kill switch 只回收已登记浮层 + root、不关闭宿主 surface，
与设计 §7.3 一致（浏览器实测确认，非缺陷）。

## 最终验收（§11）

| 验收项 | 结果 |
|---|---|
| `pytest tests/` | **3950 passed, 1 skipped**（基线 3855 passed/1 skipped，净增 95） |
| `gen_plugin_api_docs.py --check`（4 件） | exit 0，全部「已是最新」 |
| `gen_plugin_ui_icons.py --check` | exit 0 |
| `stm-plugin-check` samples/data 4 个插件 | 全部 0 error / 0 warning，exit 0 |
| 外部官方插件仓库 checker | 两仓均在仓库根 exit 0（0 error / 1 warning：目录名与 id 不同，预期） |
| JS 语法（104 个 `static/js/**/*.js`） | Node `--check` 全通过 |
| `create_app()` | EXIT 0（本地插件加载成功 2 / 失败 0 / 禁用 1） |
| 真实浏览器冒烟（7 落点 / 插槽锚点 / 面板 / 批量 / 右键 / 自绘 / kill switch） | 全部通过，console 0 错误 |
| v2 残留（`entries` / `permissions` / `api.entries.*` / `EntryRegistry`） | 宿主、samples、data、外部仓库均无实际使用 |

## 偏差记录

设计契约本体零偏差（版本、字段、三原语、落点/插槽、容量、校验分级、运行时 API、共存行为均按设计）。
以下是实现中需要解释的取舍/边界，逐条记录「设计 vs 实现 + 理由」：

1. **菜单深度 3 的边界语义**：深度超过 3 的节点被丢弃；若父 submenu 因此没有子节点，整支丢弃
   （含父节点）。设计只规定「最大深度 3」未规定父节点处理；取「submenu 必须非空」的一致解释。
2. **`/api/plugins/entries/layout` + `_entry_layout_v1` 保留**：v3 前端已无消费者（坞栏不再拖拽/
   排序），但保留路由与后端逻辑不做删除，避免超出本任务范围（设计 §10.2 未要求删除，只要求
   前端行为变更）。标注为可在后续版本清理的死代码。
3. **5 组前端运行时枚举放在生成器/前端本地**（overlay 层级、surface 类型/尺寸、device 类型、
   trigger 类型）：这些是运行时登记 API 的枚举，不属于 manifest 声明层，`contract.py` 只覆盖
   声明层；生成期常量在 `gen_plugin_api_docs.py` 与运行时 JS 中各有一份并有测试对账。
4. **生成文档的 `d.ts` 对不透明 payload 用 `any`/`unknown`**（事件 detail、`api()` 返回、
   Alpine factory）：运行时对象无法静态建模，用宽松类型避免发布错误类型；其余接口按实现具体化。
5. **uiPrimitives 的 menu/popover/tabs/layout 返回句柄对象**（`{element, close, destroy,
   reposition, focusFirst}`）而非裸 Node：渲染层需要统一清理/定位，句柄是内部约定，不构成插件契约。
6. **面板自行合并 `coreCommands`、管理器不 import 运行时**：kill switch 内置命令由渲染层读取
   `ContributionRegistry.coreCommands` 展示并用共享事件 `plugins:close-overlays` 派发；管理器用
   `plugin:reload` 事件而非直接 import `pluginHost`，避免循环依赖（设计 §6.4 的「渲染→运行时解耦」）。
7. **命令面板命令+菜单合并为一行**：设计 §10.2 允许同一 id 同时出现在 `commands` 与
   `commandPalette`；实现按「菜单展示字段覆盖、命令执行字段保留」合并为一行（否则重复 key/重复行
   是用户可见缺陷）。这是对设计的细化解释，不改契约。
8. **kill switch 不关闭宿主 surface**：设计 §7.3 只列已登记浮层 + root；surface 是宿主容器，
   由用户/插件显式开关。浏览器实测保留 surface 与设计一致；若产品希望「一键全关」需改设计。
9. **管理器贡献总览只展示 manifest 静态声明**（不含运行时 `api.contributions.update` 动态内容）：
   运行时动态态按设计属于运行期数据，静态只读视图是管理器的合理语义，页面已注明「只读」。
10. **`stm-plugin-check` 目录名检查分级**：插件仓库根目录名通常 ≠ `manifest.id`（GitHub 检出），
    设计 §8.2 的 9 项检查未包含目录名约束；实现为仓库根 warning、宿主安装目录（`.../plugins/<id>`）
    error，既保住宿主安装约束又不阻断插件 CI。
11. **自绘插件仍可声明声明式菜单**（pet 的 dock/settings.nav 用 `action.surface`）：
    `render_mode:"custom"` 只表示「界面自管」，设计 §10.3 明确 migration 目标即为该形状，
    故声明式落点与自绘共存，不作为偏差。
12. **`data/plugins/*` 是运行期克隆副本（git 未跟踪）**，与外部官方仓库同步；仓库内以
    `samples/plugins/hello-world` 作为 git 跟踪夹具。

无未完成项；阶段 5.1 浏览器冒烟发现的 4 个集成缺陷已全部修复并加回归测试，最终全量测试、
生成物校验、checker、JS 语法、应用启动与浏览器冒烟全部通过。
