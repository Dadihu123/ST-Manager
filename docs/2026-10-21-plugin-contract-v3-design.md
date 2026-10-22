# ST-Manager 插件契约 v3 设计：贡献通道 + 自绘模式

> **状态**：设计定稿（2026-10-21 与用户逐条 grill 确认），待实现。
> **取代**：`docs/2026-09-22-plugin-system-design.md`（已标记 superseded，保留为历史决策记录）。
> **决策记录**：`docs/adr/0001`–`0016`；术语表：`GLOSSARY.md`。
> **事实源**：插件契约（manifest 形状、落点清单、API 语义）以本文为准。`docs/plugin-api.md`、JSON Schema、TS 类型是生成物，不手改。
> **读者**：宿主实现者、官方插件作者、第三方插件作者。第三方作者可只读第 4–7 章与附录 B。

---

## 0. 一句话

宿主不再枚举 UI 功能：插件用三种原语（**菜单树 / 插槽 / 命令**）声明宿主 UI，或直接用**自绘模式**拥有自己的界面；宿主保留六条边界——数据安全、CSS 作用域、DOM 根节点、强制回收、共存止损、静态可校验。

## 1. 背景：为什么要重塑

旧契约 `frontend.entries[]` 是「kind 枚举 + 单层列表」：

- 每出现一种宿主 UI 位置，就要加一个 `kind`（`dock/nav/settings/context/command/status/batch`），并在每个消费点各写一份渲染分支（右键菜单、批量菜单、header、命令面板、设置页……）。二级菜单事件证明：连「按组折叠」都需要宿主改模板。
- 未知子键直接拒绝整个插件（`manifest_unknown_key`），导致插件作者只能用宿主已实现过的字段。
- 契约与呈现逻辑的成本比约 200:1（宿主改动里绝大部分是渲染与测试，而不是契约本身）。
- 插件仓库为了自测，维护了三份宿主逻辑的复刻（manifest 白名单、`evaluateWhen`、CSS 扫描器）。

结论：**不缺能力，缺的是「表达宿主 UI 结构」的通用机制**，以及一个能被插件离线自测的契约。

本次重塑的三个支点：

1. **推荐通道**：菜单树 / 插槽 / 命令，覆盖宿主 UI 的声明式扩展（ADR-0009）。
2. **自绘模式**：插件可拥有容器与浮层，宿主只发根节点、做最小共存协调（ADR-0001、0006、0007）。
3. **契约工程**：manifest v3 + 代码生成 schema/类型/文档 + `stm-plugin-check`（ADR-0011、0014、0015）。

## 2. 目标与非目标

### 2.1 目标

1. **呈现类需求零宿主改动**：新增菜单项、二级菜单、插槽内容、命令，只改 manifest 与插件前端。
2. **自绘不被限制**：插件可自建容器与浮层，形态不受宿主枚举约束（ADR-0001）。
3. **契约可离线自测**：schema 与 `stm-plugin-check` 在插件仓库即可跑（ADR-0014）。
4. **多插件可共存**：层级建议、可选 overlay 登记、kill switch（ADR-0007）。
5. **契约可演进**：一次成型后按 Stability / deprecation 规则演进（ADR-0012）。

### 2.2 非目标（明确不做）

- 插件间调用、组件复用、服务注册（ADR-0003）。
- 沙箱与强制权限（ADR-0008）；`capabilities` 只披露。
- 插件向宿主 UI 直接注入 DOM（ADR-0005）。
- 宿主替自绘插件做移动端降级（ADR-0006）。
- v1 清单外的落点/插槽（ADR-0013）；新增按 additive 处理。
- 宿主自身 UI 全部走贡献机制（dogfooding）——后续可选，不在本次范围。
- 后端 `PluginAPI` 的能力域重构——本次只做契约版本与生成物更新。

## 3. 责任边界

| 领域 | 宿主负责 | 插件负责 |
|---|---|---|
| 数据 / 文件 / 密钥 | 边界校验、路径 realpath、密钥隔离、私有数据命名空间 | 通过 `api.*` 域调用，不绕过 |
| 宿主 UI 结构 | 拥有模板、渲染、排序、定位、样式基线 | 只声明数据（菜单树）或在插槽容器内渲染内容 |
| 插件自有 UI | 提供根节点、共享 portal root、强制回收、kill switch | 自绘内容、自己定位、自己适配移动端 |
| 共存 | 层级建议、ESC/焦点协调（已登记浮层）、崩溃隔离、止损 | 声明层级、可选登记浮层、监听止损事件清理 |
| 生命周期 | 加载/停用/卸载、DOM/样式/事件回收 | `deactivate` 清理自有资源 |
| 信任 | 展示 `capabilities`、目录 `tier` 徽章 | 如实声明能力位 |

## 4. manifest v3

### 4.1 顶层字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `manifest_version` | int | 是 | 固定 `3`；宿主只支持 `(3,)` |
| `id` | string | 是 | `^[a-z][a-z0-9-]{1,63}$`，必须等于目录名 |
| `name` | string | 是 | 展示名 |
| `version` | string | 是 | 插件语义化版本 |
| `api_version` | int | 是 | 固定 `3`；宿主只支持 `(3,)`（ADR-0012） |
| `min_app_version` | string | 否 | 最低主程序版本，普通语义化版本（不带比较符），如 `1.0.0` |
| `author` / `description` / `homepage` / `license` / `icon` | string | 否 | 元信息 |
| `backend` | object | 否 | `{entry, register, jobs[], hooks[]}`，语义不变 |
| `frontend` | object | 否 | 见 §4.2 |
| `capabilities` | string[] | 否 | 能力披露，见 §4.7；**取代** v2 的 `permissions` |
| `requires` | object | 否 | 插件依赖，语义不变 |
| `config_schema` / `secret_schema` | object | 否 | 语义不变 |
| `i18n` | object | 否 | 语义不变 |

**删除**：`frontend.entries[]`、`permissions`（改名为 `capabilities`，不保留别名）。未知顶层键 → 拒绝加载（拼写错误要立刻暴露）。

### 4.2 `frontend` 字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `entry` | string | 前端入口模块，导出 `activate(api)` / 可选 `deactivate(api)`；`activate` 返回函数则作为 disposer |
| `styles` | string[] | 受作用域约束的样式文件，见 §7.5 |
| `global_styles` | string[] | 免作用域的全局样式文件；需要 `ui.global_styles` 能力位 |
| `render_mode` | `"declarative"` \| `"custom"` | 默认 `declarative`；`custom` 表示插件会自绘界面，需要 `ui.custom` 能力位（披露，非审批） |
| `contributions` | object | `{menus[], slots[], commands[]}`，见 §4.4–§4.6 |

### 4.3 完整示例（迁移后的 AI 助手，节选）

```json
{
  "manifest_version": 3,
  "id": "stm-ai-assistant",
  "name": "AI 角色卡分析助手",
  "version": "0.3.0",
  "api_version": 3,
  "min_app_version": "1.0.0",
  "author": "ST-Manager",
  "description": "角色卡的 AI 工作台：打标、世界书精简、自动归类、分类体系提议；批量作业、逐条审批与成本记账。",
  "license": "MIT",
  "backend": {
    "entry": "backend",
    "register": "register",
    "jobs": ["ai.analyze", "ai.wi_rewrite", "ai.classify", "ai.propose", "ai.agent"],
    "hooks": []
  },
  "frontend": {
    "entry": "frontend/plugin.js",
    "styles": ["frontend/plugin.css"],
    "render_mode": "declarative",
    "contributions": {
      "menus": [
        {
          "id": "workbench",
          "placement": "dock",
          "type": "item",
          "label": "AI 助手",
          "icon": "frontend/assets/icon.svg",
          "order": 40,
          "action": {"type": "command", "id": "open-workbench"}
        },
        {
          "id": "ai-helper-context",
          "placement": "context.folder",
          "type": "submenu",
          "label": "AI 助手",
          "icon": "frontend/assets/icon.svg",
          "order": 55,
          "children": [
            {
              "id": "analyze-folder",
              "type": "item",
              "label": "AI 打标此分类全部卡片",
              "description": "为该分类（含子分类）下的卡片生成概览与标签建议。",
              "when": {"mode": ["cards"]},
              "action": {"type": "surface", "id": "analyze"},
              "disabledHint": "仅支持右键分类"
            },
            {
              "id": "polish-folder",
              "type": "item",
              "label": "AI 精简此分类世界书",
              "when": {"mode": ["worldinfo"]},
              "action": {"type": "surface", "id": "polish"},
              "disabledHint": "仅支持右键分类"
            }
          ]
        }
      ],
      "slots": [
        {
          "id": "ai-settings-inline",
          "slot": "settings.section",
          "title": "AI 助手",
          "order": 80,
          "module": "frontend/views/settingsSection.js",
          "export": "mountSettingsSection"
        }
      ],
      "commands": [
        {
          "id": "open-workbench",
          "title": "打开 AI 助手",
          "shortcut": "Ctrl+Shift+A",
          "module": "frontend/commands.js",
          "export": "openWorkbench"
        }
      ]
    }
  },
  "capabilities": [
    "cards.read", "cards.write", "worldbook.read", "worldbook.write",
    "tags.read", "tags.write", "secrets.read", "network.outbound", "jobs.run"
  ],
  "config_schema": {"type": "object", "properties": {}},
  "secret_schema": {"type": "object", "properties": {}}
}
```

### 4.4 `contributions.menus[]`

菜单树是**扁平列表 + 显式树**：每个根节点带 `placement`，子节点嵌在 `children` 里，不再有 `kind` 与隐式 `group`。

#### 4.4.1 节点字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | `^[a-z][a-z0-9-]{0,63}$`，插件内菜单节点唯一；`api.contributions.update()` 用它定位 |
| `placement` | string | 根节点必填 | 落点，取值见 §5.1；子节点禁止 |
| `type` | `"item"` \| `"submenu"` \| `"separator"` | 是 | |
| `label` | string | `item` / `submenu` 必填 | |
| `description` | string | 否 | 命令面板/提示使用 |
| `icon` | string | 否 | 宿主图标名（如 `wand`）或插件资源路径（如 `frontend/assets/icon.svg`） |
| `order` | int | 否 | 默认 `100`，升序；宿主只把它当建议值 |
| `when` | object | 否 | 条件，见 §4.4.3；全部条件 AND |
| `badge` | string \| number | 否 | 静态徽标；动态值走 `api.contributions.update` |
| `disabledHint` | string | 否 | 被 `when` 拦下时展示 |
| `action` | object | `item` 必填 | 见 §4.4.2 |
| `children` | array | `submenu` 必填 | 子节点；子节点字段同上（不含 `placement`） |

#### 4.4.2 `action`

| `action.type` | 负载 | 语义 |
|---|---|---|
| `surface` | `{"type":"surface","id":"hub"}` | 打开插件已注册的宿主容器（`api.surfaces.register` 注册过），透传当前上下文 |
| `command` | `{"type":"command","id":"open-review"}` | 调用本插件声明的命令处理器 |
| `url` | `{"type":"url","url":"https://…"}` | 仅允许 `http(s)://`；宿主用新标签页打开，不继承插件权限 |

`surface` 的 id 在运行时才存在，安装期只校验格式；打开时若未注册 → 警告并忽略点击。`command` 的 id 必须存在于 `contributions.commands`，安装期即可校验。

#### 4.4.3 `when` 条件

| 键 | 类型 | 语义 |
|---|---|---|
| `mode` | string[] | 命中任一工作模式（`cards` / `worldinfo` / `chats` / `presets` / `regex` / `scripts` / `quick_replies` / `beautify`） |
| `selection` | `"none"` \| `"any"` \| `"single"` \| `"multi"` | 当前选中集状态 |
| `config.requireKeys` | string[] | 插件配置里这些键都存在且非空 |
| `hostVersion` | string | 主程序版本门槛：普通语义化版本，主程序 ≥ 该版本时条件成立（如 `1.2.0`） |
| `feature` | string[] | 宿主 feature flag 全部开启 |
| `indexState` | `"idle"` \| `"running"` | 索引作业状态 |

旧字段 `contexts` 用 `placement` 表达；旧字段 `when.target` 由 `context.folder` / `context.card` 落点隐含，**删除**。

#### 4.4.4 排序、容量与深度

- 同一落点内按 `order` 升序；相同 `order` 按「插件 id → 节点 id」稳定排序。
- 单插件菜单节点上限 **64**（含子节点）；超出的节点丢弃并警告。
- 菜单树最大深度 **3**（根 → 子菜单 → 子菜单的子项）；更深的部分丢弃并警告。
- `dock` 落点额外限制：全局 8 个槽位，单插件最多 2 个；超出的进入坞栏「更多」浮层（`dock.overflow` 由宿主渲染）。

### 4.5 `contributions.slots[]`

插槽是宿主 UI 中的命名嵌入点：宿主给一个有边界的容器，插件在容器内自绘内容。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 插件内唯一 |
| `slot` | string | 是 | 插槽名，取值见 §5.2 |
| `title` | string | 否 | 宿主渲染的分区标题；为空则容器无标题 |
| `order` | int | 否 | 默认 `100` |
| `when` | object | 否 | 同 §4.4.3 |
| `module` | string | 是 | 相对插件根目录的 ES 模块路径 |
| `export` | string | 是 | 导出函数名 |

渲染器契约：

```js
// frontend/views/settingsSection.js
export function mountSettingsSection(container, ctx) {
  // container：宿主创建的容器元素（已带 data-plugin="<id>"）
  // ctx: { api, pluginId, slot, mode, target, selection }
  const root = document.createElement('div');
  root.className = 'ai-settings'; // 样式必须在 [data-plugin] 作用域下
  container.append(root);

  const off = ctx.api.onConfigChange(() => rerender(root, ctx));
  rerender(root, ctx);

  return () => {
    off();
    root.remove();
  };
}
```

宿主保证：

- 容器由宿主创建、定位、滚动与回收；插件**不得**在容器或祖先上设置 `position` / `z-index` / `inset`。
- 挂载时调用渲染器；卸载（关闭容器、切换页面、禁用插件、kill switch）时调用其返回的清理函数，然后移除容器。
- 渲染器抛错被宿主捕获：该插槽显示错误占位，插件标记为「降级」，不影响其他插件。
- 插槽容器带 `data-plugin="<id>"`，插件 CSS 必须以此为根。

### 4.6 `contributions.commands[]`

命令 = 具名动作 + 处理器。它可以被菜单项引用（`action.type: "command"`）、被命令面板列出、被全局快捷键触发。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 插件内唯一 |
| `title` | string | 是 | 命令面板展示名 |
| `description` | string | 否 | |
| `icon` | string | 否 | |
| `shortcut` | string | 否 | 如 `Ctrl+Shift+A`；必须含修饰键（Ctrl/Alt/Meta），冲突时宿主保留先到者并警告 |
| `when` | object | 否 | 同 §4.4.3 |
| `module` | string | 是 | 相对插件根目录的 ES 模块路径 |
| `export` | string | 是 | 处理器导出名 |

处理器契约：

```js
// frontend/commands.js
export async function openWorkbench(ctx) {
  // ctx: { api, pluginId, mode, target, selection, trigger }
  // trigger: { kind: "menu" | "palette" | "shortcut", nodeId? }
  ctx.api.surfaces.open('hub');
}
```

命令面板只列出通过 `when` 的命令；快捷键绑定与 `when` 无关（按下时求值，不满足则忽略）。

### 4.7 `capabilities`

能力位是**披露**，不是审批，也不是强制隔离（ADR-0008）。宿主在安装/启用时展示给人看，不做运行时拦截；CLI 严格模式要求声明与实际行为一致。

已知能力位（v3）：

| 类别 | 值 |
|---|---|
| 数据 | `cards.read` `cards.write` `worldbook.read` `worldbook.write` `tags.read` `tags.write` `chats.read` `chats.write` `presets.read` `presets.write` |
| 运行时 | `secrets.read` `network.outbound` `jobs.run` `hooks.subscribe` `cli.run` |
| UI | `ui.custom` `ui.global_styles` |

规则：

- 未知能力位：宿主保留并原样展示，标注「未知名」；CLI 警告。
- `render_mode: "custom"` 应声明 `ui.custom`；缺失时宿主仍加载，但披露里会显示「未声明自绘」并记录警告。
- `frontend.global_styles` 非空应声明 `ui.global_styles`；否则宿主拒绝注入这些文件并警告。
- 能力位只增不改：删除某个能力位属于破坏性变更，需要升 `api_version`。

### 4.8 `render_mode`

- `declarative`（默认）：插件通过 `contributions` 使用推荐通道；仍可注册 `surfaces`。
- `custom`：插件自绘 UI，使用 `api.createRoot` / `api.overlays`；`contributions` 可选（混合模式允许）。
- 两种模式都受 §7 的 DOM 根节点与共存契约约束；区别只在「是否声明界面自管」。

### 4.9 校验与容错

两级策略：

**宿主加载（宽容）**

| 情形 | 行为 |
|---|---|
| JSON 非法 / 超过 256 KB | 拒绝加载 |
| `manifest_version` / `api_version` 不在 `(3,)` | 拒绝加载，提示更新主程序或插件 |
| 未知顶层 / `backend` / `frontend` 键 | 拒绝加载（`manifest_unknown_key`，带字段提示） |
| 菜单节点/插槽/命令的单个节点非法 | 丢弃该节点 + 警告，插件其余部分照常加载 |
| 未知节点子键 | 忽略 + 警告（节点级字段允许 additive） |
| `x-` 前缀的任意键 | 静默忽略（实验命名空间） |
| 渲染器模块缺失 / 导出不存在 | 激活失败：该插件前端停用、后端继续运行、插件管理器显示错误与重试 |
| 超过容量上限 | 截断 + 警告 |

**`stm-plugin-check`（严格）**

任何会导致宿主丢弃/降级的问题都以非零退出码报出；同时做静态引用检查（模块/导出/命令引用/落点/能力位一致性/样式作用域）。见 §8.3。

## 5. v1 落点与插槽

落点是**数据**：后续新增是 additive 变更，不需要升 `api_version`。v1 清单之外的位置不开放（ADR-0013）。

### 5.1 菜单落点

| 落点 | 宿主位置 | 上下文 `ctx` | 备注 |
|---|---|---|---|
| `context.folder` | 文件夹/分类右键菜单 | `{mode, target: {type:"folder", id, name}, selection}` | 移动端使用长按菜单 |
| `context.card` | 卡片右键菜单 | `{mode, target: {type:"card", id, name}, selection}` | 需要宿主为卡片网格补右键入口 |
| `context.footer` | 右键菜单尾部分区 | 同上 | 渲染在分隔线之后 |
| `batch.actions` | 批量操作菜单 / 选中栏动作 | `{mode, selection}` | 选中数量由宿主提供 |
| `commandPalette` | 命令面板（Ctrl+K） | `{mode, selection}` | 通常是 `action.type: "command"` 的项 |
| `dock` | 左侧/顶部坞栏按钮 | `{mode}` | 支持 `badge` / `progress` / `status` 动态更新 |
| `settings.nav` | 设置页导航项 | `{}` | 通常 `action.type: "surface"` 打开插件设置 |

### 5.2 插槽

| 插槽 | 宿主位置 | 上下文 `ctx` | 备注 |
|---|---|---|---|
| `settings.section` | 设置页内容区 | `{config}` | 适合「插件设置内联到宿主设置页」 |
| `header.actions` | 顶栏动作区 | `{mode}` | 移动端折叠进「更多」 |
| `card.detail.tabs` | 卡片详情页标签页 | `{target: {type:"card", id}}` | 适合详情页自绘面板 |
| `page.cards.toolbar` | 角色卡视图工具栏 | `{mode, selection}` | |
| `page.worldinfo.toolbar` | 世界书视图工具栏 | `{mode, selection}` | |
| `empty.<mode>` | 各视图空状态区 | `{mode}` | `<mode>` ∈ 8 个工作模式，如 `empty.cards` |

### 5.3 排序与移动端

- 宿主给插槽与菜单项一个稳定的默认顺序；插件 `order` 只作建议，宿主可因移动端空间不足折叠。
- 移动端：宿主渲染的落点自动适配（折叠进「更多」/长按菜单）；**自绘插件自行适配**。宿主通过 `api.host.onState` 提供 `{mode, deviceType, darkMode, scrimActive, surfaceOpen, busy, reducedMotion, visible}`。
- 宿主不保证自绘 UI 在窄屏可用；这是插件责任（ADR-0006）。

## 6. 运行时 API

### 6.1 `api.contributions`

静态声明是唯一的结构来源（ADR-0015）；运行时只允许**更新**与**移除**，不允许新增落点/节点类型。

| 方法 | 签名 | 说明 |
|---|---|---|
| `update` | `update(id, patch) -> boolean` | 更新一个菜单节点；`id` 不存在或节点已被移除返回 `false` |
| `remove` | `remove(id) -> boolean` | 移除节点（本次激活内有效；重新激活恢复静态声明） |
| `get` | `get(id) -> object \| null` | 返回节点快照（只读） |
| `list` | `list() -> object[]` | 本插件全部菜单节点快照 |
| `trigger` | `trigger(id, ctx?) -> boolean` | 以编程方式执行节点 action；节点被 `when` 过滤时返回 `false` |

`patch` 允许的字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `label` / `description` / `icon` | string | 动态文案与图标 |
| `badge` | string \| number \| null | 徽标 |
| `progress` | number 0–1 \| null | 坞栏进度环 |
| `status` | string | 自由文本状态，宿主只展示 |
| `enabled` | boolean | 置灰/恢复 |
| `disabledHint` | string | 置灰原因 |
| `busy` | boolean | 忙碌指示（坞栏旋转/禁用点击） |
| `children` | array | 仅 `submenu`；完整替换子节点；每个子节点必须带 `id`，`action` 只能引用已声明命令或已注册 surface |

示例：

```js
api.contributions.update("workbench", { progress: 0.42, status: "打标 42/100", busy: true });
api.contributions.update("workbench", { progress: null, status: "", busy: false });
```

### 6.2 `api.createRoot`

```js
const root = api.createRoot();                 // -> HTMLElement
const root2 = api.createRoot({ portal: true }); // body 级 portal root 下的元素
const button = api.createRoot('button');        // 指定标签名
```

- 返回的元素由宿主创建并跟踪；插件只能往里挂内容，不能替换/移除根节点本身。
- 插件停用、卸载、kill switch 时，宿主清空并移除所有 root。
- 内容层与 portal 层的差异：
  - 内容层（默认）：挂在宿主内容带，适合「插件在宿主页面内的自绘内容」。
  - portal 层（`portal: true`）：挂在 body 级层，用于浮层/弹层——避开 `backdrop-filter`/`transform` 造成的包含块与层叠上下文陷阱。
- 两个层都由宿主创建为 body 直接子元素、`position: fixed; inset: 0; pointer-events: none`；插件中需要交互的子元素必须显式 `pointer-events: auto`。
- 层叠：内容层位于宿主内容之上、宿主模态之下；portal 层位于宿主模态之上、宿主提示/告警之下。具体 z-index 在实现时与现有 CSS token 对齐（建议 token：`--z-plugin-content` / `--z-plugin-portal`）。

### 6.3 `api.overlays`

可选登记，用于让宿主参与 ESC / 焦点 / 遮挡协调（ADR-0007、0016）。不登记也能运行。

```js
const unregister = api.overlays.register({
  id: "preview",
  element: root,          // createRoot 返回的元素（或其子元素）
  layer: "popover",       // 建议层级：content/ambient/surface/dock/popover/tooltip/alert
  modal: true,            // 模态：宿主处理 ESC 与焦点归还
  label: "预览",           // 调试面板显示名
  onDismiss: () => closePreview(),
});
// 之后可 unregister() 或 api.overlays.unregister("preview")
```

| 方法 | 说明 |
|---|---|
| `register(spec) -> () => void` | 登记浮层，返回取消函数 |
| `unregister(id) -> boolean` | 取消登记 |
| `list() -> array` | 本插件已登记浮层元数据（不含 DOM 引用） |
| `closeAll() -> number` | 关闭本插件所有已登记浮层（逐个调用 `onDismiss`），返回数量 |

宿主行为：

- 已登记且 `modal: true` 的浮层：ESC 关闭最上层；关闭后焦点归还给打开前的元素。
- 未登记的浮层：宿主不干预（kill switch 只能通过清空 root 回收）。
- `layer` 是建议值，不是强制层叠；宿主用它做调试展示与遮挡提示，不改变插件元素的 z-index。

### 6.4 保留的前端 API

| 命名空间 | 状态 | 说明 |
|---|---|---|
| `api.surfaces` | 保留 | `register` / `open` / `close` / `isOpen`；宿主容器仍是推荐通道 |
| `api.ui` | 保留并扩展 | 原语（按钮/徽标/区块/表单/空状态/确认框…） |
| `api.host` | 保留 | `toast` / `refresh` / `switchMode` / `openDetail` / `openSettingsSection` / `notify` / `log` / `onState` / `selection` |
| `api.storage` | 保留 | 前端插件私有存储 |
| `api.toast` / `api.progress` | 保留 | 通知与批量进度 |
| `api.on` / `emit` / `onConfigChange` | 保留 | 事件；见 §6.6 的收紧 |
| `api.estimate_tokens` | 保留 | 后端能力代理 |
| `api.manifest` / `api.id` / `api.state` | 保留 | 只读元信息 |

### 6.5 删除 / 替换的 API

| v2 | v3 | 处置 |
|---|---|---|
| `api.entries.register(spec)` | 无 | **删除**：结构只能静态声明（ADR-0015） |
| `api.entries.update(id, patch)` | `api.contributions.update(id, patch)` | 迁移 |
| `api.entries.setBadge(id, v)` | `update(id, {badge: v})` | 迁移 |
| `api.entries.setProgress(id, p)` | `update(id, {progress: p})` | 迁移 |
| `api.entries.setStatus(id, s)` | `update(id, {status: s})` | 迁移 |
| `api.entries.setBusy(id, b)` | `update(id, {busy: b})` | 迁移 |
| `api.entries.open(id)` | `api.contributions.trigger(id)` | 迁移 |
| `api.entries.list()` | `api.contributions.list()` | 迁移 |
| `frontend.entries[]` | `frontend.contributions.*` | **删除** |

### 6.6 事件与后端 API

- 前端事件：自定义事件仍必须以 `<plugin_id>:` 开头；**核心事件只能宿主发出**，插件 `emit` 核心事件将被警告并忽略（修正旧契约里「可伪造核心事件」的漏洞）。
- 新增宿主事件：`overlays:force-closed`，`detail = {pluginId}`；插件在 kill switch 后据此重置 UI 状态。
- 后端 `PluginAPI`：15 个域 / 63 个域方法不变；`docs/plugin-api.md` 由生成器按 v3 重新产出。后端不能访问前端贡献树，前端不能直接调后端外的能力（维持现状）。

## 7. 共存契约

### 7.1 层级带（建议值）

| 层级 | 建议用途 | token |
|---|---|---|
| content | 页面内插件内容 | `--z-plugin-content` |
| ambient | 常驻环境层（宠物等） | `--z-plugin-ambient` |
| dock | 坞栏浮层 | `--z-plugin-dock` |
| surface | 插件宿主容器 | `--z-plugin-surface` |
| popover | 插件弹层/菜单 | `--z-plugin-popover` |
| tooltip | 插件提示 | `--z-plugin-tooltip` |
| alert | 需要立刻被看见的插件告警 | `--z-plugin-alert` |

宿主自身层级始终在插件之上（宿主提示/确认框/告警不可被遮挡）。建议值不是强制；冲突由插件与用户承担，但 kill switch 与调试面板用于止损。

### 7.2 崩溃隔离

- 贡献渲染、插槽渲染器、命令处理器、overlay 回调中的异常均被宿主捕获：记日志 + 用户可感知的错误提示，不扩散到其他插件。
- 异常连续超过阈值（实现时定，建议 5 次/分钟）→ 该插件前端标记「降级」，可一键停用；后端不受影响。
- 不能捕获的情形（如死循环）由浏览器资源限制兜底；kill switch 是最后手段。

### 7.3 kill switch

入口：

1. 命令面板内置命令「插件：关闭所有浮动界面」。
2. 插件管理器页面按钮「关闭所有插件浮层」。

行为（对每个插件依次）：

1. 依次调用已登记浮层的 `onDismiss` 并关闭；
2. 广播 `overlays:force-closed`；
3. 清空并移除该插件的所有 root（内容层 + portal 层）。

不卸载插件、不停用插件、不丢插件状态。未登记浮层只能被第 3 步（清 root）回收；若插件把节点挂到了 root 之外，属于违反契约，宿主不保证回收。

### 7.4 CSS 作用域与全局样式

- `frontend.styles[]`：沿用现有扫描器——选择器必须以 `.plugin-<id>` 或 `[data-plugin="<id>"]` 为根；宿主注入的插槽容器与 root 都带 `data-plugin`。
- `frontend.global_styles[]`：免扫描文件；仅在声明 `ui.global_styles` 能力位时注入，安装/启用时明确提示「此插件会修改全局样式」。
- 样式注入带 `data-plugin-style="<id>"`，停用/卸载时整体移除。
- 自绘插件同样受作用域约束；想改全局就必须走 `global_styles` + 能力位。

### 7.5 移动端

- 宿主渲染的落点：由宿主负责响应式（折叠/长按/全屏 sheet）。
- 自绘插件：自行负责；宿主只提供 `api.host.onState().deviceType` 与断点 token，不做降级容器、不替插件隐藏浮层。

## 8. 契约工具链

### 8.1 单一事实源

契约定义以**宿主代码**为源（沿用 `DOMAIN_CLASSES` / 白名单/常量的模式），生成：

| 生成物 | 路径（实现时确定） | 用途 |
|---|---|---|
| JSON Schema | `docs/plugin-manifest.schema.json` | 编辑器补全、第三方校验、CI |
| 前端 TS 类型 | `docs/plugin-api.d.ts` | 插件仓库类型提示 |
| API 参考 | `docs/plugin-api.md` | 现有生成器扩展：新增 contributions / roots / overlays 章节 |
| 校验器 | `core/plugins/contract.py`（宿主校验） | 宿主加载与 CLI 共用同一套规则 |

`tools/gen_plugin_api_docs.py` 扩展为同时产出 schema 与 d.ts，避免多套生成管线（ADR 未单列，但属于「代码为源」的直接实现）。

### 8.2 `stm-plugin-check`

独立脚本（不依赖宿主仓库即可运行），与宿主共用同一版校验规则与 schema。检查项：

1. manifest JSON 合法、大小限制、字段白名单、版本（`api_version` / `manifest_version`）。
2. 落点/插槽名合法；菜单节点数量/深度/容量限制；`id` 唯一。
3. `action` 引用：`command` 必须存在；`surface` 只校验格式；`url` 协议。
4. 模块引用：`module` 文件存在、可被解析；`export` 存在（静态 import 检查）。
5. `when` 键与枚举合法；`shortcut` 格式/修饰键/冲突（同一插件内）。
6. `render_mode` 与 `capabilities` 一致性；`global_styles` 与 `ui.global_styles` 一致性。
7. CSS 作用域扫描（`styles` 全部、`global_styles` 豁免）。
8. 图标名/资源存在性（沿用宿主现有检查）。
9. 契约版本提示：宿主版本低于所需能力时给出明确信息。

用法：

```bash
python stm_plugin_check.py path/to/plugin          # 严格模式
python stm_plugin_check.py path/to/plugin --json   # 机器可读
```

官方插件 CI 必须包含 `stm-plugin-check`（ADR-0010：官方走推荐通道，自然要过严格检查）。

## 9. 版本与治理

### 9.1 版本

| 版本 | v3 取值 | 说明 |
|---|---|---|
| `api_version` | `3` | 宿主只支持 `(3,)`；契约破坏性变更才升 |
| `manifest_version` | `3` | manifest 结构版本；与 `api_version` 同步升 |
| 插件 `version` | 自由 | 插件自身语义化版本 |
| `min_app_version` | 可选 | 主程序版本要求 |

### 9.2 Stability 与弃用

- 契约条目（API/字段/落点/能力位）分 `Stable` / `Provisional` / `Internal` 三级，生成文档时标注。
- 破坏性变更：升 `api_version` + 迁移指南 + 至少一个发布周期弃用提示。
- additive 变更（新增落点/插槽/能力位/可选字段）：不升 `api_version`，在文档 changelog 标注。
- 删除条目：先 `Provisional` 或 deprecation 警告，再删除。

### 9.3 变更流程

- 设计级：ADR（`docs/adr/NNNN-*.md`），只记录硬难逆、意外、有真实取舍的决定。
- 契约级：ADR + 更新本文 + 生成物；插件侧同步迁移。
- 实现级：直接改代码 + 测试，不写 ADR。

### 9.4 文档地图

| 文档 | 角色 |
|---|---|
| `docs/2026-10-21-plugin-contract-v3-design.md`（本文） | **唯一事实源**：契约形状、落点、API 语义 |
| `docs/plugin-api.md` | 生成物：后端域 + 前端 API 参考（不手改） |
| `docs/plugin-manifest.schema.json` | 生成物：manifest schema |
| `docs/plugin-api.d.ts` | 生成物：前端类型 |
| `docs/adr/0001`–`0016` | 决策记录 |
| `GLOSSARY.md` | 术语表 |
| 插件仓库的迁移指南（新增） | 面向第三方作者：v2 → v3 对照 |
| `AGENTS.md` | 仓库级约束：当前代码仍为 v2 的过渡说明 |

## 10. 迁移

### 10.1 旧 → 新对照

| v2 | v3 |
|---|---|
| `frontend.entries[]` | `frontend.contributions.{menus,slots,commands}` |
| `entry.kind`（7 种枚举） | `placement`（落点）+ 节点 `type` |
| `entry.group`（宿主隐式折叠） | 显式 `submenu` 节点 |
| `entry.surface {id,type,size}` | `action: {type:"surface", id}`；surface 类型以 `api.surfaces.register` 的 `type` 为准（修正旧文档与实现的漂移） |
| `entry.contexts` | `placement` + `when.mode` |
| `entry.when.target` | 落点隐含（`context.folder` / `context.card`） |
| `entry.requires_selection` | `when.selection` |
| `entry.priority` | `order` |
| `entry.shortcut` | `commands[].shortcut` |
| `entry.badge`（静态） | `badge` + `api.contributions.update` 动态更新 |
| `permissions` | `capabilities`（仅披露） |
| `frontend.entries` 的运行时注册（`api.entries.register`） | 删除；结构必须静态声明 |

### 10.2 官方插件逐条映射

**`stm-ai-assistant`（12 条 → 贡献树）**

| v2 入口 | v3 |
|---|---|
| `workbench`（dock，surface `hub`，快捷键） | `menus` dock 项 `workbench`，`action: command open-workbench`；`commands` 声明 `open-workbench`（快捷键 `Ctrl+Shift+A`，处理器打开 `hub`） |
| `analyze-folder` / `classify-folder` / `polish-embedded` / `polish-folder`（context folder） | `menus` `context.folder` 下一个 `submenu`「AI 助手」，4 个 `item`；`when.mode` 保留 |
| `analyze-selected` / `classify-selected` / `polish-selector`（batch） | `menus` `batch.actions` 下一个 `submenu`「AI 助手」，3 个 `item` |
| `open-review` / `propose-library` / `open-profiles`（command） | `commands` 三条 + `menus` `commandPalette` 三个 `item`（`action: command`） |
| `assistant-settings`（settings） | `menus` `settings.nav` 一项，`action: surface settings` |
| `permissions[]` | `capabilities[]` 原样迁移 + 按需增加 `ui.*` |
| `api.entries.setBadge/setProgress/setStatus` | `api.contributions.update` |
| `frontend/plugin.js` 的 `api.entries.*` | 删除；`activate` 只管 surfaces、命令、事件 |

**`stm-pet`（2 条）**

| v2 入口 | v3 |
|---|---|
| `pet-dock`（dock，surface `pet-settings`） | `menus` dock 项，`action: surface pet-settings` |
| `pet-settings`（settings，surface `pet-settings`） | `menus` `settings.nav` 项，`action: surface pet-settings` |
| ambient surface（常驻宠物） | 不变（`render_mode: "custom"` + `ui.custom` + ambient surface） |

**`hello-world`（夹具）**

- 删除运行时 `api.entries.register`（ADR-0015 不再允许）；命令改为静态 `contributions.commands` + `commandPalette` 菜单项。
- manifest 升 `manifest_version: 3` / `api_version: 3` / `capabilities: []`。
- 继续作为 `docs/plugin-api.md` 的可运行对照与 `stm-plugin-check` 的夹具。

迁移顺序：`stm-pet` → `hello-world` → `stm-ai-assistant`（由简到繁；前两个验证契约，最后一个验证真实复杂度）。

### 10.3 实现步骤（与 ADR-0014 对齐）

1. **契约层**：新增 `core/plugins/contract.py`（常量/枚举/校验）；重写 `core/plugins/entries.py` → `contributions.py`；manifest 解析改 v3；`core/version.py` 升 `PLUGIN_API_VERSION = 3` / `SUPPORTED_PLUGIN_API_VERSIONS = (3,)`、`SUPPORTED_MANIFEST_VERSIONS = (3,)`；生成 schema + d.ts；测试先行（manifest v3 合法/非法矩阵）。
2. **前端注册表与渲染**：贡献注册表（静态转运行时树）、菜单树渲染（7 个落点）、命令面板与命令绑定、插槽宿主、dock（含 overflow/动态态）；删除 `entryRegistry` 的 v2 路径。
3. **自绘与共存**：root 层、portal 层、`overlays`、kill switch、错误隔离、`overlays:force-closed`。
4. **原语与工具链**：补 `api.ui` 的 menu/popover/tabs/layout 原语；`global_styles` 注入；`stm-plugin-check`；官方插件 CI。
5. **迁移与收尾**：三个插件迁移；删除旧 entries/surface 声明解析；重新生成 `docs/plugin-api.md`；更新 `AGENTS.md`、旧设计文档 banner、迁移指南；全量回归。

### 10.4 删除清单（实现时）

- `core/plugins/entries.py` 的 kind/tier/group 逻辑（`ENTRY_KINDS`、`_KIND_TIER_ALLOWLIST`、`normalize_entries`、`apply_tier`）。
- `frontend_entries` 字段与 `PluginManifest.to_dict()` 的 `entries` 快照。
- `static/js/entryRegistry.js` 的 v2 注册/渲染分支（保留可复用的排序/过滤工具）。
- `pluginManager.js` 的 `IMPLEMENTED_ENTRY_KINDS`。
- 插件侧 `api.entries.*` 调用与 `frontend.entries` 声明。
- 旧文档中 `db()` / `suppress_fs_events()` / 跨插件订阅等已不存在的 API 描述（随旧文档 superseded 一并冻结）。

## 11. 验收测试

### 11.1 契约与校验（Python）

- manifest v3 合法矩阵：三个官方插件 + hello-world 夹具全部通过；v2 manifest 被拒绝且错误码清晰。
- 节点级容错：非法节点被丢弃、其余加载；未知节点子键只警告；`x-` 键静默忽略。
- 容量/深度：64 节点、深度 3、dock 2/8、命令 32、插槽 16 的边界。
- 生成物一致性：`gen_plugin_api_docs.py --check`、schema/d.ts 的 `--check`。
- `stm-plugin-check` 负例矩阵：未知落点、缺失模块、缺失导出、重复命令 id、非法 shortcut、无作用域 CSS、`global_styles` 未声明能力位，全部非零退出并给出定位。

### 11.2 渲染与交互（宿主手工 + 前端契约测试）

- 7 个落点全部渲染；子菜单、分隔线、排序、`when` 过滤（mode/selection/config/hostVersion/feature/indexState）。
- dock：进度环、徽标、状态、忙碌、置灰、溢出「更多」、单插件 2 个上限。
- 命令：面板列出、快捷键触发、冲突警告、`when` 不满足时忽略。
- 插槽：挂载/卸载/清理调用；渲染器抛错的错误占位；`settings.section` 与 `card.detail.tabs` 的上下文正确。
- 移动端：菜单折叠、长按、插槽折叠（宿主侧）。

### 11.3 自绘与共存

- `render_mode: "custom"` 加载；`createRoot` 内容层/portal 层位置正确；停用后 root 清空。
- overlay 登记/取消；ESC 关闭最上层并归还焦点；`closeAll`；kill switch 清 root + 广播 `overlays:force-closed`。
- 崩溃隔离：渲染器/处理器抛错不扩散；连续错误触发「降级」。
- CSS：作用域通过/拒绝；`global_styles` 仅在能力位存在时注入并在安装时提示。

### 11.4 迁移与回归

- 三个官方插件在 v3 宿主加载并行为对齐：右键二级菜单、批量二级菜单、dock 进度、设置入口、ambient 宠物。
- `api_version` 2 插件被拒绝；`manifest_version` 2 被拒绝。
- 事件收紧：插件 emit 核心事件被警告并忽略；自定义事件仍可用。
- 全量 `pytest tests/` 通过；三个插件仓库各自测试通过。

## 12. 未决与后续

- 层级带的具体 z-index 数值：实现时与现有 CSS token 对齐，本文只定相对顺序。
- overlay `layer` 枚举最终集合：实现时确认是否保留 `alert` 给插件使用（宿主告警永远在最上）。
- 宿主自身 UI 的 dogfooding：后续可选，评估把宿主部分入口也走贡献机制。
- 插件间组合：等生态出现明确需求再评估（ADR-0003）。
- 后端能力域的披露/门控：维持「披露不强制」（ADR-0008）。
- 契约变更流程的落地工具（changelog 生成、deprecation 检查）：实现后补。

## 附录 A · 决策索引

| ADR | 决定 |
|---|---|
| [0001](adr/0001-plugin-owns-ui-container.md) | 插件拥有自己的 UI 容器 |
| [0002](adr/0002-reshape-plugin-contract-before-release.md) | 发布前一次性重塑契约 |
| [0003](adr/0003-no-cross-plugin-composition.md) | 暂不提供插件间组合 |
| [0004](adr/0004-retain-css-scope-with-global-styles-permission.md) | 保留 CSS 作用域 + 全局样式权限 |
| [0005](adr/0005-host-ui-accepts-declarative-contributions-and-slot-renderers.md) | 宿主 UI 只接受声明式贡献与插槽渲染器 |
| [0006](adr/0006-plugin-dom-under-host-provided-roots.md) | 插件 DOM 挂在宿主根节点下 |
| [0007](adr/0007-minimal-coexistence-coordination.md) | 最小共存协调 |
| [0008](adr/0008-permissions-and-tier-are-disclosure-only.md) | 权限与 tier 仅作披露 |
| [0009](adr/0009-three-contribution-primitives.md) | 三原语贡献通道 |
| [0010](adr/0010-official-plugins-use-recommended-channels.md) | 官方插件优先走推荐通道 |
| [0011](adr/0011-manifest-v3-contributions-under-frontend.md) | manifest v3 结构 |
| [0012](adr/0012-api-version-3-drop-old-compat.md) | api_version 3，删除旧兼容 |
| [0013](adr/0013-v1-placements-and-slots.md) | v1 落点与插槽清单 |
| [0014](adr/0014-plugin-contract-v3-single-release.md) | 一次成型 |
| [0015](adr/0015-static-structure-dynamic-content.md) | 静态结构 + 动态内容 |
| [0016](adr/0016-self-rendered-ui-api.md) | 自绘 API |

## 附录 B · 已知实现漂移（实现时修正）

| 漂移 | 处置 |
|---|---|
| 旧设计文档 §10 仍列 `db()` / `suppress_fs_events()` 等已删 API | 旧文档已 superseded；生成物按新代码重出 |
| 核心事件可被插件伪造（`api.emit` 允许核心事件名） | §6.6：插件 emit 核心事件警告并忽略 |
| 跨插件 hook 订阅被实现拒绝，旧文档却写成允许 | 以 ADR-0003 为准：不支持，文档对齐实现 |
| `surface.type` 在 manifest 与 `register()` 两处声明，后者为准 | v3 删除 manifest 侧的 surface 声明（改用 `action`），类型只来自 `register()` |
| `pluginManager.js` 的 `IMPLEMENTED_ENTRY_KINDS` 与 `ENTRY_KINDS` 不一致（`nav`/`status` 无消费者） | v3 删除概念；落点清单见 §5 |
| 插件仓库维护三份宿主逻辑复刻（白名单/`evaluateWhen`/CSS 扫描） | `stm-plugin-check` 作为官方自测入口；插件仓库删除复刻 |
