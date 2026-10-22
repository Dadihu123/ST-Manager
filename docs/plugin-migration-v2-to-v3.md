# 插件迁移指南：v2 → v3

**适用对象**：按停机更新前契约（`api_version: 2` / `manifest_version: 2`，`frontend.entries[]`
+ `api.entries.*` + `permissions`）编写的 ST-Manager 插件。

**总结**：v3 是一次**不保留兼容层**的破坏性升级（ADR-0012）：

- 版本号 `api_version` 与 `manifest_version` **都固定为 3**，旧值直接拒绝加载；
- `frontend.entries[]` → `frontend.contributions{menus, slots, commands}`（**结构静态声明**）；
- `api.entries.*` → `api.contributions.*`（**运行期只能改状态，不能注册结构**）；
- `permissions` → `capabilities`（改名 + 语义收敛为「如实披露」，ADR-0008）；
- 新增 `frontend.render_mode`（`declarative` 默认 / `custom` 自绘）。

参考文档：设计 `docs/2026-10-21-plugin-contract-v3-design.md`（§4 manifest、§4.4–§4.7
三原语、§5 落点/插槽、§8 校验、§10 迁移）；生成版 API 参考 `docs/plugin-api.md`；
契约唯一事实源 `core/plugins/contract.py`。本仓库内的迁移实例见文末 §9。

---

## 1. 变更总览（设计 §10.1）

| v2（已删除） | v3（现状） | 说明 |
|---|---|---|
| `api_version: 2`、`manifest_version: 2` | 两者均为 `3` | 只接受 3；不设兼容分支（ADR-0012） |
| `permissions: [...]` | `capabilities: [...]` | 改名；语义见 §6 |
| `frontend.entries[]` | `frontend.contributions.menus[]` | 菜单树，落点由节点 `placement` 表达 |
| `frontend.entries[].kind`（`dock`/`context`/`batch`/`command`/`settings`/`nav`/`status`） | `placement`（7 种） | `nav` / `status` 语义删除；`command` 变为「命令面板节点 + 命令处理器」 |
| — | `frontend.contributions.slots[]` | 命名插槽（此前只有「设置页内联」这一种能力） |
| — | `frontend.contributions.commands[]` | 命令：标题 / 处理器模块 + 导出名 / 可选快捷键 |
| `frontend.entries[].surface: {id, type, size}` | `action: {type: "surface", id}` | **surface 的 type/size 只来自 `api.surfaces.register()`**，manifest 不再声明 |
| `frontend.entries[].when.target`、`...when.contexts` | 删除 | 落点本身表达目标（`context.folder` / `context.card` / `context.footer`） |
| `frontend.entries[].group`（隐式二级菜单） | 显式 `submenu` 节点（`type: "submenu"` + `children[]`） | 分组从「宿主猜」变成「插件声明」 |
| `frontend.entries` 数量上限 16 | 菜单节点 ≤ 64（含子节点）；命令 ≤ 32；插槽 ≤ 16；dock 全局 8 / 单插件 2 | 见 §3 limits |
| 无 | `frontend.render_mode`：`declarative`（默认）/ `custom` | 自绘插件必须 `custom` + `ui.custom` |
| `frontend.global_styles`（无能力位） | 仍存在，但**只有声明 `ui.global_styles` 时才注入** | 见 §6 |
| `api.entries.*` | `api.contributions.*` | 见 §5 |
| `entries:changed` 事件 | `contributions:changed` 事件 | 供「激活早于注册表建表」时重放状态 |
| `api.entries.register` / 运行期注册入口 | **删除** | 运行期只能 `update` / `remove`；结构必须写进 manifest |
| manifest 未知顶层键 → 拒绝 | 同左；但**贡献节点级**问题 → 丢弃该节点 + 警告（宿主宽容） | CLI 严格：节点级问题算 error，见 §8 |

> **x- 命名空间**：任意层级以 `x-` 开头的键被**静默忽略**，可用于插件私有实验字段，
> 不触发未知键报错。

---

## 2. 三原语

v3 的宿主 UI 消费**三种静态声明**。它们的共同点：manifest 决定「有什么」，
运行期 API 只能改「长什么样 / 是否可用」（ADR-0015）。

### 2.1 菜单树 `contributions.menus[]`

7 种落点（`placement`）：

| placement | 出现位置 | 上下文来源 |
|---|---|---|
| `dock` | 右侧坞 / 快捷键 | 无目标 |
| `context.folder` | 右键「分类」 | 右键的分类路径 |
| `context.card` | 右键「卡片」 | 右键的卡片 |
| `context.footer` | 右键「页脚 / 其它」 | 无目标 |
| `batch.actions` | 批量操作菜单 | 当前选中集 |
| `commandPalette` | 命令面板（可搜索） | 无目标 |
| `settings.nav` | 设置页插件导航 | 无目标 |

**只有根节点写 `placement`**；子节点继承根节点的落点。

节点形状：

```jsonc
{
  "id": "analyze-folder",           // 必填，^[a-z][a-z0-9-]{0,63}$，同插件内唯一
  "type": "item",                   // item | submenu | separator（默认 item）
  "label": "AI 打标此分类全部卡片",   // item/submenu 必填（命令面板按它搜索）
  "description": "……",              // 可选，tooltip / 命令面板副标题
  "icon": "frontend/assets/icon.svg", // 可选：宿主图标名或插件资源相对路径
  "order": 100,                     // 可选，默认 100，小的在前
  "placement": "context.folder",    // 仅根节点；子节点禁止声明
  "when": { /* 见下 */ },           // 可选；只声明不写逻辑（求值归宿主）
  "badge": "3",                     // 可选静态徽标；动态用 update({badge})
  "disabledHint": "先选中至少一张卡片", // 条件不满足时的置灰理由
  "action": { "type": "surface", "id": "analyze" },
  "children": [ /* 仅 submenu；完整替换语义见 §5.2 */ ]
}
```

`action` 三种类型：

| type | 必备键 | 行为 |
|---|---|---|
| `surface` | `id` | 打开 `api.surfaces.register()` 注册过的 surface（未注册 = 点击无反应，只警告） |
| `command` | `id` | 触发 `contributions.commands[]` 里声明过的命令（**安装期校验存在性**） |
| `url` | `url` | `https://` / `http://` 外部链接 |

**limits**：单插件菜单节点 ≤ **64**（含全部 children）；菜单树深度 ≤ **3**；
单插件 dock 节点 ≤ **2**（全局槽位 8）；命令 ≤ **32**；插槽 ≤ **16**。

`when` 支持：`mode` / `selection` / `config` / `hostVersion` / `feature` / `indexState`。

- `mode`：`cards` / `worldinfo` / `chats` / `presets` / `regex` / `scripts` /
  `quick_replies` / `beautify`；
- `selection`：`none` / `any` / `single` / `multi`；
- `config.requireKeys`：要求这些配置键有非空值；
- `indexState` 只允许 `idle` / `running`；
- **`target` 与 `contexts` 已删除**：目标由落点表达，不要写。

### 2.2 插槽 `contributions.slots[]`

命名插槽由宿主提供锚点容器（`[data-plugin-slot="<name>"]`），插件只往容器里挂内容：

| slot | 位置 |
|---|---|
| `settings.section` | 设置 → 插件区的内联段落 |
| `header.actions` | 页面标题行右侧 |
| `card.detail.tabs` | 卡片详情页签 |
| `page.cards.toolbar` | 角色卡页工具栏 |
| `page.worldinfo.toolbar` | 世界书页工具栏 |
| `empty.<mode>` | 空态页（`empty.cards` 等，按工作模式） |

形状：`{id, slot, module, export, order?, icon?, label?}`。`module` 里的
`export` 函数在挂载时被调用，参数 `(container, ctx)`，返回可选清理函数。

### 2.3 命令 `contributions.commands[]`

```jsonc
{
  "id": "open-workbench",
  "title": "打开 AI 助手",
  "description": "……",
  "icon": "frontend/assets/icon.svg",
  "shortcut": "Ctrl+Shift+A",          // 建议值，宿主可被用户覆盖；格式校验严格
  "module": "frontend/commands.js",    // 相对插件根目录，文件必须存在
  "export": "openWorkbench"            // 必须能静态检出（校验器扫描 export 文本）
}
```

- 命令可被菜单节点 `action: {type: "command", id}` 引用，也通过 `api.contributions.trigger(id, ctx)` 触发；
- 快捷键格式：`Ctrl/Alt/Meta/Shift+主键`，主键支持 `A-Z`/`0-9`/`F1-F12`/方向键/
  `Escape`/`Enter`/`Space`/`Tab`/`Backspace`/`Delete`/`Home`/`End`/`PageUp`/`PageDown`，
  **至少含一个 Ctrl/Alt/Meta**（纯 `Shift+X` 不合法）；
- 同插件内快捷键不得重复；`Ctrl+K` 是宿主命令面板，不要占用。

---

## 3. `entries` → `contributions` 映射（设计 §10.2）

按 v2 `kind` 逐个落位：

| v2 `kind` | v3 落点 | 迁移方式 |
|---|---|---|
| `dock` | `menus[placement: "dock"]` | `surface` → `action: {type:"surface", id}`；原 `command`/handler → `action: {type:"command", id}` + 声明命令 |
| `context` | `context.folder` / `context.card` / `context.footer` | **按原 `when.target` 选落点**：`folder` → `context.folder`，`card` → `context.card`，无目标 → `context.footer`；然后**删掉 `when.target`** |
| `batch` | `batch.actions` | 原 `when.selection` 保留；未写也建议显式 `selection: "any"` |
| `command` | `commandPalette` + `commands[]` | 菜单节点 `action: {type:"command"}`；原 handler 移到 `module/export`；`label` 改 `title` 进命令表、菜单节点仍要 `label` |
| `settings` | `settings.nav` | `action: {type:"surface", id:"settings"}`（设置面板仍是 surface） |
| `nav` | — | **语义删除**：导航类入口并入 `settings.nav` 或命令面板 |
| `status` | — | **语义删除**：改用 `api.contributions.update(id, {status, progress, busy})` |
| `group: "AI 助手"`（隐式二级） | 显式 `submenu` 节点 | 父节点 `type:"submenu"` + 子节点放 `children[]`；父节点不写 `action` |

迁移示例（hello-world 样例插件，本仓库 `samples/plugins/hello-world/`）：

```jsonc
// v2: { "id": "main-panel", "kind": "dock", "surface": {"id": "main"}, "icon": "…" }
{
  "id": "main-panel",
  "type": "item",
  "placement": "dock",
  "label": "Hello World",
  "description": "样例插件主面板",
  "icon": "frontend/assets/icon.svg",
  "order": 10,
  "action": { "type": "surface", "id": "main" }
}
```

```jsonc
// v2: 两条 context 入口（原 when.target: "folder" / "card"）
{
  "id": "hello-context",
  "type": "submenu",
  "placement": "context.folder",
  "label": "Hello World",
  "icon": "frontend/assets/icon.svg",
  "children": [
    { "id": "context-folder-item", "type": "item", "label": "……", "disabledHint": "……",
      "when": { "mode": ["cards"] }, "action": { "type": "surface", "id": "main" } }
  ]
}
```

> **注意**：v2 的 `when.target` 不再存在。落点选错时，入口会在错误的右键菜单里出现
> （例如 `context.folder` 写成 `context.card`，右键卡片也会看到「整个分类」的动作）。

---

## 4. 自绘插件（`render_mode: "custom"`）

v2 里「插件自己画 UI」只有 `frontend.entries` 声明入口这一条路；v3 把它拆成**两条明确路线**：

| 路线 | `render_mode` | 能力位 | 用法 |
|---|---|---|---|
| 声明式 | `declarative`（默认） | 无 UI 能力位 | 用 `contributions` + `api.surfaces` + `api.ui.*`，界面由宿主渲染 |
| 自绘 | `custom` | 必须 `ui.custom` | `api.createRoot()` / `api.createRoot({portal: true})` 创建根节点；需要 ESC / 焦点 / 遮挡协调时再 `api.overlays.register(spec)` |

要点：

- `createRoot()` 返回宿主创建、跟踪、**强制回收**的根节点（内容层带
  `position: fixed; inset: 0; pointer-events: none`，可交互子元素自行
  `pointer-events: auto`）；`createRoot({portal: true})` 挂到 body 级 portal 层。
- 常驻型自绘（例如桌面宠物）也可以继续用 `api.surfaces.register(id, {type: "ambient"})`：
  ambient 容器由宿主挂载/卸载，插件只往容器里画——这是 v3 仍支持的稳定通道，
  `ui.custom` 能力位用于如实披露「界面不是宿主渲染的」。
- `frontend.global_styles` 仍可注入全局样式，但 manifest 必须同时声明
  `ui.global_styles` 能力位，否则校验器报 `global_styles_capability_missing`。
- 自绘浮层**不要**再自己实现 ESC / 焦点陷阱 / z-index 体系：登记到
  `api.overlays`，宿主统一调度；宿主 kill switch（`plugins:close-overlays`）会强制
  收起并广播 `overlays:force-closed`。

---

## 5. `api.entries.*` → `api.contributions.*`

### 5.1 API 对照

| v2 | v3 | 备注 |
|---|---|---|
| `api.entries.setStatus(id, value)` | `api.contributions.update(id, {status: value})` | 返回 `boolean`：节点不存在（注册表未就绪）→ `false` |
| `api.entries.setBadge(id, value)` | `api.contributions.update(id, {badge: value})` | `null` 清除 |
| `api.entries.setProgress(id, {done,total})` | `api.contributions.update(id, {progress: done/total, busy: true})` | **progress 是 0–1 比值**（`null` 清除）；旧 `{done,total}` 需插件自己归一化 |
| `api.entries.setBusy(id, bool)` | `api.contributions.update(id, {busy: bool})` | — |
| `api.entries.remove(id)` | `api.contributions.remove(id)` | 只移除该节点，结构本身仍在 manifest 里 |
| `api.entries.list()` / 读节点 | `api.contributions.list()` / `.get(id)` | — |
| `api.entries.open(id)` | `api.surfaces.open(surfaceId, ctx)` 或 `api.contributions.trigger(commandId, ctx)` | 入口点击语义现在由 `action` 决定 |
| `api.entries.register(...)`（运行期注册入口） | **删除** | 结构必须静态声明；运行期只能改已有节点 |
| `api.on('entries:changed', fn)` | `api.on('contributions:changed', fn)` | 重放语义见 §5.3 |
| `api.emit('entries:changed')` | 由宿主在注册表变更后广播 | 插件**不应**再自己 emit 核心事件名（`api.emit` 会警告并忽略） |

### 5.2 `update()` 的 patch 白名单

```js
api.contributions.update('main-panel', {
  label: '…',           // string
  description: '…',     // string
  icon: '…',            // 宿主图标名或插件资源路径
  badge: '3',           // string | null
  progress: 0.62,       // number 0–1（宿主自动钳制）或 null 清除
  status: 'running',    // string；宿主用于状态点 / 胶囊
  enabled: true,        // boolean
  disabledHint: '…',    // string
  busy: true,           // boolean
  children: [ /* … */ ],// 仅 submenu：完整替换子节点（每个子节点必须带 id，走同一套节点校验）
});
```

- 白名单外字段静默忽略（S3 `UPDATE_PATCH_KEYS`）；字符串字段会 `String()` 化、
  `progress` 自动钳制到 `0–1`（`null` / `''` 清除）、`enabled` 只有显式 `false` 才置灰；
- `children` 只对 `submenu` 生效且**整体替换**；任一子节点非法则**整个 patch 被拒绝**
  （返回 `false`，不会只更新一半）；
- 节点不存在 / patch 非法时返回 `false`（不抛错），方便「注册表未就绪」时静默重试。

### 5.3 激活顺序与重放（最常见的坑）

`PluginHost.loadAll()` 先 `activate()`，之后才用 manifest 把贡献树装进
`ContributionRegistry`。因此 **activate 期间 `update()` 会因找不到节点返回 `false`**。

推荐模式（本仓库 hello-world / stm-ai-assistant 均如此）：

```js
function createContributionReporter(api) {
  const status = { current: '' };
  let written = null;
  const write = (value) => {
    let any = false;
    for (const id of ['main-panel', 'hello-palette']) {
      if (api.contributions.update(id, { status: value })) any = true; // 不能 .some()：短路会漏写后面的节点
    }
    return any;
  };
  const apply = () => {
    if (status.current && written !== status.current && write(status.current)) {
      written = status.current;
    }
  };
  apply();                                       // 注册表可能还没就绪 → 失败也先记住
  const off = api.on('contributions:changed', apply); // 就绪后重放
  return {
    setStatus(next) { status.current = next; apply(); },
    dispose() { if (typeof off === 'function') off(); },
  };
}
```

要点：

1. **先存期望值，再尝试写**；写失败不要当错误；
2. 订阅 `contributions:changed` 后重放；
3. 多个节点要同时写时**逐个写**，不要 `.some()` / `.find()` 短路；
4. 所有写入集中在一个 reporter 里，避免「有的状态直接被写丢、有的走重放」两套路径。

---

## 6. `capabilities`（原 `permissions`）

v3 能力位是**如实披露**（ADR-0008），**不是权限闸门**：宿主不会因为没声明就拒绝调用，
但审计、插件管理页与官方评审会按声明核对；虚报 / 漏报都属于契约问题。

| 组 | 能力位 |
|---|---|
| 数据 | `cards.read` / `cards.write`、`worldbook.read` / `worldbook.write`、`tags.read` / `tags.write`、`chats.read` / `chats.write`、`presets.read` / `presets.write` |
| 运行时 | `secrets.read`、`network.outbound`、`jobs.run`、`hooks.subscribe`、`cli.run` |
| UI | `ui.custom`、`ui.global_styles` |

一致性规则（校验器强制）：

- `render_mode: "custom"` ↔ 声明 `ui.custom`：自绘却未披露、或披露了却不自绘，都会报错；
- `frontend.global_styles` 非空 ↔ 声明 `ui.global_styles`；
- 未知能力位报 `capability_unknown`；数组里重复项去重并警告。

v2 → v3 的映射基本就是同名搬移：把 `permissions` 数组原样改名为 `capabilities`，
再按实际 UI 路线补上 `ui.custom` / `ui.global_styles`。

---

## 7. 迁移步骤

1. **改 manifest 头**：`api_version: 3`、`manifest_version: 3`、`permissions` → `capabilities`，
   按需加 `frontend.render_mode`。
2. **搬入口**：把 `frontend.entries[]` 按 §3 的 kind 映射改写成
   `contributions.menus[]`（必要时合并成 submenu）；把「有处理器的 command 入口」
   拆成 `commands[]` + 命令面板节点。
3. **补静态结构**：把 v2 里靠 `api.entries.register()` 或运行时拼出来的入口**全部写进 manifest**
   （v3 不允许运行期新增结构）。
4. **改前端运行期**：`api.entries.*` → `api.contributions.update`，进度归一化为 0–1，
   `entries:changed` → `contributions:changed`，按 §5.3 加重放。
5. **删掉测试里的复刻校验器**：v2 时代插件仓库常备份一份宿主白名单 / `evaluateWhen` /
   CSS 扫描器；v3 起**不要维护副本**（设计附录 B）。改为
   `python scripts/stm_plugin_check.py .`（见 §8）或在测试里直接调用主程序的
   `contract.validate_manifest(..., strict=True)`。
6. **接 CI**：复制校验器 + 加一个 `plugin-check` 工作流（见 §8.3）。
7. **全量自检**：`grep` 旧键（`"entries"`、`"permissions"`、`api.entries.`、`kind`）
   → 跑校验器 → 跑插件自己的测试 → 在真实宿主里加载验收。

---

## 8. 校验器 `stm-plugin-check`

### 8.1 来源与纪律

`tools/stm_plugin_check.py` 是主程序的**生成物**（见 AGENTS.md「Generated Artifacts」）：
把 `core/plugins/contract.py` 逐字内嵌进标记区，并附宿主事实常量（版本 / 图标名），
因此可以脱离宿主仓库、复制到任意插件仓库运行。

- **不要手改**校验器（生成区会被 `python tools/gen_plugin_api_docs.py --check` 判为漂移）；
- 插件仓库把副本放在 `scripts/stm_plugin_check.py`，随主程序升级重新复制；
- 契约规则只从 `core/plugins/contract.py` 引用 / 内嵌，不要在插件里另抄一份。

### 8.2 用法

```bash
python scripts/stm_plugin_check.py path/to/plugin           # 严格模式
python scripts/stm_plugin_check.py path/to/plugin --json    # 机器可读
```

退出码：`0` = 无 error；`1` = 存在 error（任何会被宿主丢弃 / 降级的问题）；
`2` = 命令行用法错误。九项检查（设计 §8.2）：manifest 结构 / 落点与容量 /
action 引用 / 模块与导出 / `when` 与 shortcut / render_mode 与 capabilities /
CSS 作用域 / 图标 / 版本提示。

**目录名约束**：`manifest.id` 必须等于插件目录名。GitHub 归档的顶层目录是
`repo-<branch>`，所以 CI 里先把内容摊到以插件 id 命名的临时目录：

```yaml
# .github/workflows/plugin-check.yml（插件仓库）
name: plugin-check
on: [push, pull_request, workflow_dispatch]
jobs:
  contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Stage plugin under its manifest id
        run: |
          mkdir -p "$RUNNER_TEMP/<plugin-id>"
          rsync -a --exclude '.git' --exclude '.pytest_cache' ./ "$RUNNER_TEMP/<plugin-id>/"
      - name: Validate manifest & contributions (strict)
        run: python scripts/stm_plugin_check.py "$RUNNER_TEMP/<plugin-id>"
```

### 8.3 本仓库的验收基线

主程序 `.github/workflows/plugin-contract.yml` 会：跑生成物 `--check`、跑插件工具链测试、
并对 `samples/plugins/*` 与 `data/plugins/*` 跑严格校验器。官方插件（`official` tier）
必须通过；社区插件也建议接同一工作流。

---

## 9. 常见错误

| 现象 / 错误码 | 原因 | 修复 |
|---|---|---|
| `api_version_unsupported` / `manifest_version_unsupported` | 还写 2，或只改了一个 | 两个都改 3 |
| `manifest_legacy_key`（`entries` / `panels` / `settings_tab` / `detail_tab`） | 旧字段残留 | 全部搬进 `contributions`；旧字段不保留别名 |
| `manifest_unknown_key` | 顶层 / `backend` / `frontend` / `contributions` 下写了未知键 | 删掉或改加 `x-` 前缀（实验字段） |
| `capability_unknown` | `capabilities` 拼错 / 沿用虚构名字 | 对照 §6 名单 |
| `capability_custom_undeclared` / `global_styles_capability_missing` | 自绘或全局样式未声明能力位 | `render_mode: "custom"` 要 `ui.custom`；`global_styles` 要 `ui.global_styles` |
| `menu_placement_unknown` | 用了 v2 的 `kind` 或写错落点 | 用 §2.1 的 7 种 placement；`nav`/`status` 已删除 |
| `menu_placement_forbidden` | 子节点也写了 `placement` | 只根节点写；children 继承 |
| `menu_id_duplicate` / `command_id_duplicate` / `slot_id_duplicate` | id 重复 | 同插件内全局唯一 |
| `menu_capacity` / `menu_depth_exceeded` / `slot_capacity` / `command_capacity` | 超上限 | 见 §2.1 limits；`depth` 从根节点算 1 |
| `action_command_missing` | 菜单节点 `action.command` 引用了未声明的命令 | 在 `contributions.commands[]` 补声明 |
| `action_invalid` / `action_unknown_key` | action 类型或字段不合法 | 只用 `surface`/`command`/`url`；`surface` 不再声明 type/size |
| `menu_node_invalid` | `item` 缺 `label`/`action`，`submenu` 缺 `children` | 按 §2.1 形状补齐 |
| `when_unknown_key` / `when_unknown_mode` | 还在写 `target`/`contexts`，或 mode 拼错 | 删 `target`/`contexts`；mode 用 §2.1 清单 |
| `shortcut_invalid` / `shortcut_duplicate` | 纯 Shift 快捷键 / 重复 / 占宿主键（`Ctrl+K`） | 至少带 Ctrl/Alt/Meta；同插件唯一 |
| `module_missing` / `module_path_invalid` / `module_unreadable` | `module` 路径不存在或越界 | 相对插件根目录、文件必须真实存在 |
| `module_export_missing` | 校验器没在模块里找到 `export <name>` | 用 `export function name(...)` 或 `export { name }` |
| `slot_unknown` / `slot_unknown_key` / `slot_invalid` | 插槽名或形状错 | 对照 §2.2；动态 `empty.<mode>` 检查 mode 名 |
| `icon_missing` / `icon_path_invalid` / `icon_unknown` | 资源不存在 / 路径越界 / 宿主图标名拼错 | 插件资源写相对路径；宿主图标名查生成版 `docs/plugin-api.md`；未知宿主图标名只是 warning |
| `css_unscoped` / `css_read_error` | 插件样式选择器逃逸作用域 / 文件读不到 | 所有选择器以插件作用域前缀开头；`global_styles` 豁免但需能力位 |
| `manifest_id_dir_mismatch` | 目录名 ≠ `manifest.id`（GitHub 检出最常见） | 仓库根目录直接跑只会 **warning**（宿主安装时会以 id 为目录名）；宿主安装目录（`.../plugins/<id>`）下不匹配才是 error，CI 可把内容摊到同名临时目录再严格校验 |
| 启动日志「节点已丢弃」但插件整体加载成功 | 宿主**宽容**：节点级问题只丢弃该节点 | 用严格校验器查看被丢弃项（它把 warning escalate 成 error） |
| 点击入口没反应 | `action.surface.id` 与 `api.surfaces.register()` 不一致 | 两边 id 对齐；控制台看 `[surfaceHost] 未注册的 surface` |
| 状态 / 角标有时丢 | 激活早于注册表建表，且没重放 | 按 §5.3 订阅 `contributions:changed` 重放 |
| 进度条不出现 | 仍写 `{done,total}` | `progress` 是 0–1 比值；配 `busy: true` |

---

## 10. 本仓库已完成的迁移实例

| 插件 | 位置 | 版本 | 迁移形态 |
|---|---|---|---|
| `hello-world`（样例 / 测试夹具） | `samples/plugins/hello-world`（同步到 `data/plugins/hello-world`） | `0.3.0` | 声明式：dock 2 条 + `context.card` + `batch.actions` submenu（含 separator）+ `commandPalette` + `settings.nav`；1 个 `settings.section` 插槽；3 条命令（含 `Ctrl+Shift+H`）；演示 `update(status/badge/busy/progress)` 与 `trigger` |
| `stm-pet`（官方，自绘常驻） | `data/plugins/stm-pet`（源仓库 `ST-Manager-Pet`） | `0.4.0` | `render_mode: "custom"` + `ui.custom`；dock `pet-dock` + `settings.nav` `pet-settings`，都指向 `pet-settings` surface；ambient surface 养宠物 |
| `stm-ai-assistant`（官方） | `data/plugins/stm-ai-assistant`（源仓库 `ST-Manager-AI-Assistant`） | `0.3.0` | 声明式：7 个根菜单节点（展开 14 个，含 `ai-helper-context` / `ai-helper-batch` 两个 submenu）+ 4 条命令；状态回报走 `api.contributions.update` + `contributions:changed` 重放 |

验收结论：四个目录（含 `data/plugins/hello-world` 同步副本）跑
`python tools/stm_plugin_check.py <dir>` 均为 **0 error / 0 warning**；
两个外部官方插件仓库各自接入了 `scripts/stm_plugin_check.py` +
`.github/workflows/plugin-check.yml`，并在 CI 里按 §8.2 摊目录后严格校验。
