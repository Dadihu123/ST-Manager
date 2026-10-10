# stm-ai-assistant 插件重写 —— 适配新插件系统地基

> 用途：把本文件整份交给一个全新的编码会话，按其执行。
> 目标仓库：`D:\Workspace\MyOwn\ST-Manager-AI-Assistant`（**插件**仓库，不是主程序）。
> 主程序仓库（只读参考）：`D:\Workspace\MyOwn\ST-Manager`。
> 生成日期：2026-10-11。
> 前置事实：主程序已完成「插件系统地基修缮」（commit `78465b5`），契约见
> `docs/plugin-api.md`（生成物）与 `docs/2026-09-22-plugin-system-design.md` 第 2 / 8 / 10 部分。

---

## 0. 任务陈述

把 `stm-ai-assistant` 从「插件自绘 `position: fixed` 浮层 + 自建模态框骨架」改造成
「**插件声明入口与 surface，宿主提供容器**」。

这次重写的**唯一目的**是让插件不再自己承担层级、焦点、滚动、遮罩合成这些宿主职责。
**后端业务逻辑（LLM 调用、提示词工程、作业、幂等、成本记账）基本不动**——它们是这个
插件的价值所在，本次重写不该碰。

**边界**：

- ✅ 改：`manifest.json`、`frontend/plugin.js`、`frontend/panel.js`、`frontend/dom.js`、
  `frontend/plugin.css`、`frontend/views/*.js`、`tests/test_manifest_contract.py`、
  `tests/test_css_scope.py`、`docs/2026-10-08-stm-ai-assistant-design.md`。
- ❌ 不改：`backend/**`（除下面点名的两处）、`tools/**`。
- ❌ 不引入新依赖、不引入打包器。

---

## 1. 现状诊断（已实测，不要重新猜）

主程序的新校验器对本插件当前状态的实测结果：

```
scan_css_scope(frontend/plugin.css)        → []            # 作用域合规，保持
scan_css_declarations(frontend/plugin.css) → position_fixed × 2
    .plugin-stm-ai-assistant-launcher  (z-index: 2140)
    .plugin-stm-ai-assistant-overlay   (z-index: 2150)
```

也就是说：**作用域没问题，问题是「插件自绘 fixed 浮层」这条模式本身**——正是地基修缮
要消灭的东西。另外：

| 项 | 现状 | 目标 |
|---|---|---|
| `manifest.api_version` | `1` | `2` |
| `manifest.manifest_version` | 缺省（=1） | `2` |
| `frontend` 段 | 只有 `entry` / `styles` | 增加 `entries[]` |
| 入口 | 自绘可拖拽浮动按钮（`position: fixed`） | `dock` 入口，坞托管 |
| 面板 | 自绘 overlay + 自建 header/tabBar/ESC/点击遮罩关闭 | `surfaces.register` + 宿主容器 |
| 遮罩合成 | `overlay` 带 `backdrop-filter: blur(5px)`，另加 `body:has(...) .main-container { backdrop-filter: none }` 兜底 | **删掉两者**，改由宿主统一处理 |
| 图标 | 自建 `icon()` 拼 `/static/icons/ui.svg#icon-x` | `api.ui.icon(name)` |
| 提示 | `api.toast(...)` × 62 处 | `api.host.toast(...)`（`api.toast` 是保留别名，可分批） |
| 选中卡片 | 读 `api.store.viewState.selectedIds` | `entries[].when.selection` + 宿主求值 |
| 状态徽标 | 自建 `badge()` | `api.ui.badge()`；入口角标用 `api.entries.setBadge()` |

### 关键：本插件的 tier 是 `community`

实测 `tier_for_plugin('stm-ai-assistant') == 'community'`（不在 `static/plugins/catalog.json` 里）。
按 D5 准入表：

| kind | 本插件可用？ |
|---|---|
| `dock` / `command` / `context` / `settings` | ✅ |
| `nav` / `status` | ❌ **声明了会被宿主静默忽略 + 记 warning** |

因此本次**不要声明 `nav` 或 `status`**。若确实需要侧栏导航项，另开任务把本插件加进
主程序 catalog 并标 `tier: "official"`（`tier` 只能由宿主仓库清单决定，插件 manifest
无权声明）。

---

## 2. 硬约束

**主程序侧契约（违反会被拒绝加载或记警告）**

- `frontend.entries[]` 的每项**只允许**这些键：
  `id` / `kind` / `label` / `description` / `icon` / `contexts` / `requires_selection` /
  `surface` / `priority` / `badge` / `shortcut` / `when` / `disabledHint`。
  多一个键 → **整个插件拒绝加载**（不是忽略）。
- 顶层 / `backend.*` / `frontend.*` 同样白名单严格校验。`frontend` 只允许
  `entry` / `styles` / `entries`；**旧的 `panels` / `settings_tab` / `detail_tab` 已彻底删除，
  不保留别名**，出现即拒绝加载（`manifest_version: 1` 时也会给出「改用 frontend.entries」的提示）。
- `entries[].id` 必须匹配 `^[a-z][a-z0-9-]{0,63}$`；单插件上限 **16** 项。
- `entries[].kind` ∈ `dock | nav | settings | context | command | status`。
- `entries[].surface.type` ∈ `panel | modal | page | sheet`（缺省 `panel`）。
- `entries[].icon` 用**宿主图标名**（不含 `/` 与 `.`）。不存在时**不拒绝加载**，
  但会记 warning 并把图标降级为占位——所以仍然必须校验。
- `mount(container, ctx)` 契约：
  - 宿主传入的 `container` 已完成定位、尺寸、滚动、`data-marquee-ignore`、
    `role="dialog"` / `aria-modal`、焦点陷阱、ESC 关闭。
  - 插件**只能**在 `container` 内创建 DOM。
  - 插件**不得**设置 `container` 或其祖先的 `position` / `z-index` / `inset`。
  - `mount` 返回函数时，宿主在关闭时调用它。
  - 宿主**强制**在插件禁用/卸载时卸载全部 surface，不依赖 `deactivate`。

**样式（F11 / F15，`scan_css_scope` + `scan_css_declarations` 会查）**

- 所有选择器必须以 `.plugin-stm-ai-assistant` 或 `[data-plugin="stm-ai-assistant"]` 开头
  （现有 CSS 已合规，重构时别破坏）。
- **不得**出现 `position: fixed`（声明层检查会记 warning）。
- `var(--x)` 引用的令牌若不在宿主令牌清单内，**必须带回退值**。
  实测本插件只差一个 `--font-mono`，而它**已经带了回退**（`var(--font-mono, ui-monospace, …)`），
  所以这条目前是干净的——保持即可。完整令牌清单：`GET /api/plugins/ui-tokens`。
- **不得**硬编码宿主 sprite 路径（`url('/static/icons/…')` 或 `icons/ui.svg`）。
  引用**插件自己**的 `frontend/assets/icon.svg` 是允许的。
- 只用 `.color-*` 语义类与既有 CSS 变量，不写死颜色（现有 CSS 零十六进制字面量，保持）。

**其它**

- 4 空格缩进；JS 用 2 空格（跟随现有文件）；优先单引号；行宽 ~100–120。
- 保留中文用户可见字符串。
- 不要 `import backend`（只能用相对导入）；`backend/core/**` 不得依赖 flask / 主程序 /
  requests；只有 `backend/summary_bridge.py` 允许 `from core import …`。这三条现有测试
  （`tests/test_manifest_contract.py`）在锁定，别破坏。

---

## 3. 新契约速查（本次要用的全部 API）

### manifest

```jsonc
{
  "id": "stm-ai-assistant",
  "version": "0.2.0",            // 建议一并升版本：资产 URL 会带 ?v=<version>
  "api_version": 2,
  "manifest_version": 2,
  "frontend": {
    "entry": "frontend/plugin.js",
    "styles": ["frontend/plugin.css"],
    "entries": [ /* 见下 */ ]
  }
}
```

### entries（建议声明 4 项）

| id | kind | 用途 | 备注 |
|---|---|---|---|
| `workbench` | `dock` | 主面板（工作台 / 结果与审批 / 提示词档案 / 设置 四个页签） | `surface: {id, type: "panel"}` |
| `analyze-selected` | `context` | 对选中卡片跑分析 | `requires_selection: true`，`when: {mode:["cards"], selection:"any"}`，`disabledHint` 提示先选卡 |
| `open-review` | `command` | 直接跳到「结果与审批」 | 未配 Provider 时置灰：`when: {config: {requireKeys: ["default_profile_id"]}}` |
| `assistant-settings` | `settings` | 设置入口 | |

`surface.id` 缺省时回退为 `entry.id`；坞与命令面板都按
`<pluginId>:<surface.id ?? entry.id>` 查找 surface，**两侧必须一致**。

### 前端 API

```js
// 入口
api.entries.register({ id, kind, label, description, icon, surface, when, disabledHint })
api.entries.update(id, patch) / remove(id)
api.entries.setBadge(id, value)      // number | string | null
api.entries.setProgress(id, {done, total} | null)
api.entries.setStatus(id, 'ok' | 'warn' | 'error' | 'idle')
api.entries.setBusy(id, bool)
api.entries.open(id) / list()

// surface（容器由宿主提供）
api.surfaces.register(surfaceId, {
  title, type,                        // type: panel | modal | page | sheet
  mount(container, ctx),              // ctx: { source, targetId, mode, pluginId, surfaceId }
  unmount(container), onOpen(ctx), onClose(),
})
api.surfaces.open(surfaceId, ctx) / close(surfaceId) / isOpen(surfaceId)

// 宿主 UI 原语（18 个）
api.ui.icon(name, {className})        // → HTMLElement，宿主图标名
api.ui.panel({title, subtitle, actions, children})
api.ui.section({title, description, children})
api.ui.card({title, meta, children})
api.ui.field({key, spec}, {value, onChange, required, hint})
api.ui.form(schema, {values, onSubmit, submitLabel, onCancel, hints})
api.ui.button({label, variant, icon, onClick, disabled, title})
                                  // variant: primary | secondary | danger | ghost
api.ui.toolbar([node | '-', ...])
api.ui.empty({icon, title, description, action})
api.ui.error({title, message, retry})
api.ui.loading({label})
api.ui.badge({value, tone})       // tone: neutral | info | success | warning | danger
api.ui.list({items, renderItem, empty})
api.ui.table({columns: [{key, label, render}], rows})
api.ui.grid({columns, gap, children})
api.ui.split({left, right, ratio})
api.ui.confirm({title, message, danger})   // → Promise<boolean>
api.ui.prompt({title, fields})             // → Promise<object|null>

// 存储（ui_data._plugins_v1.<id>.storage，受 256KB 配额）
await api.storage.set(key, value) / remove(key)
api.storage.get(key) / keys()               // 同步读（本地缓存）

// 宿主能力
api.host.toast(msg, duration, icon) / refresh(target) / switchMode(mode)
api.host.openDetail(target, id) / openSettingsSection(section, anchor)
api.host.notify(message, level) / log(message, level)

// 配置变更（替代轮询）
api.onConfigChange((config) => {})          // → unsubscribe

// 保留别名（可继续用，但新代码请用上面的形态）
api.toast / api.refresh / api.switchMode / api.openDetail / api.openSettingsSection
api.createRoot(tag)                          // 仍在，但入口/面板不该再用它
api.jobs.* / api.subscribeJob(runId, {snapshot, item, log, done, error})
api.api(path, options)                       // F1：以 data.success 判成败
```

### 不再需要的东西（删掉）

- ❌ `api.setFullscreenScrim(true, 'panel')` —— 宿主现在自己管遮罩合成。
- ❌ `plugin.css` 里 `body:has(.plugin-stm-ai-assistant-overlay.is-open) .main-container { backdrop-filter: none }`
  这条兜底规则（主程序已从根源修复：`.main-container` 的 `backdrop-filter` 已删除，
  壁纸模糊改挂 `body::before { filter: blur() }`）。
- ❌ `overlay` 上的 `backdrop-filter: blur(5px)` —— 宿主 surface 不提供模糊，
  这是刻意的（Chromium backdrop root 会画出黑块/平坦灰）。
- ❌ 自绘的拖拽定位 + `localStorage` 记位置（`POSITION_KEY`）—— 坞负责位置。

---

## 4. 实施步骤

### 步骤 1 — manifest

1. `api_version` → `2`，新增 `manifest_version: 2`，`version` → `0.2.0`。
2. `frontend.entries` 按第 3 节表格声明 4 项。
3. 确认没有 `panels` / `settings_tab` / `detail_tab` 残留。
4. 用主程序的真实校验器自检（`tests/test_manifest_contract.py` 已有该用例）。

### 步骤 2 — plugin.js（入口重写）

现在的 210 行几乎全是「浮动按钮 + 拖拽 + 位置记忆」。目标：

1. 删掉 launcher、拖拽、`POSITION_KEY`、`clampPos` / `restorePos` / `savePos`、
   `DRAG_THRESHOLD`。
2. `api.surfaces.register('workbench', { title: 'AI 助手', type: 'panel', mount(container, ctx) {…} })`
   —— 把 `createPanel` 的**内容**（header 状态行 + 四页签 + body）挂进 `container`，
   但**不再创建 overlay / shell 外壳**（宿主给的就是外壳）。
3. 保留并迁移这些行为：
   - 启动自检（`client.health()` 的三个 `api.toast` 分支）→ `api.host.toast`，
     **并且**把结果反映到 `api.entries.setStatus('workbench', 'ok'|'warn'|'error')`。
   - `api.on('card.updated', …)` → 刷新工作台。
   - `syncSelection()`：改为**不再自己读 `api.store.viewState.selectedIds`**。
     选中态由 `entries[].when.selection` 交给宿主求值；真正要拿卡片 id 时，
     在 `mount(container, ctx)` 里用 `ctx.targetId`，或走
     `api.entries.list()` 看 `enabled` 状态。
     > 若确实必须读实时选中集合，保留原写法但加注释标注「Provisional 耦合」，
     > 并在设计文档里登记——不要假装它是 Stable。
4. 用 `api.entries.setBadge('open-review', pending)` 替代自绘的页签角标
   （待审批数 > 0 时显示）。
5. `activate` 的返回值：把清理逻辑收进一个函数并 `return` 它（宿主会调用，D9.1）。
   同时保留 `deactivate` 作为兜底。

### 步骤 3 — panel.js → surface 内容渲染器

`createPanel` 目前返回 `{element: overlay, open, close, destroy, showTab}`。目标形态：

```js
export function createPanelBody(api, client, context) {
  // 只构建「header 状态行 + tabBar + body」，不建 overlay、不绑 ESC、不绑点击遮罩关闭
  // 返回 { element, showTab, refreshStatus, destroy }
}
```

要点：

- 删掉 `overlay` / `shell` / `document.addEventListener('keydown', onKeydown)` /
  `overlay.addEventListener('click', …)` —— 焦点陷阱与 ESC 归宿主。
- 删掉 `closeBtn`（宿主 surface 自带关闭按钮）。若视觉上想去掉，在
  `plugin.css` 里用作用域选择器隐藏 `.plugin-surface__close` 是不可行的
  （那是宿主元素，不在插件作用域内）——**接受宿主自带的关闭按钮**。
- 页签切换逻辑（`showTab` / `cleanupView` / `refreshStatus`）**原样保留**，
  这是插件自己的信息架构。
- `refreshStatus()` 里的 `badge()` 改用 `api.ui.badge({value, tone})`；
  自绘的 `is-muted` / `is-warn` / `is-error` 映射到
  `neutral` / `warning` / `danger`。
- 另外注册一个 `type: 'modal'` 的 surface 用于「Prompt 预览」这类次级内容
  （现在是塞在页签里的），验证四种容器类型都能用。

### 步骤 4 — views/*.js

四个视图（`workbench` / `review` / `profiles` / `settings`，合计约 1360 行）
**逻辑基本不动**，只做替换：

| 旧 | 新 |
|---|---|
| `api.toast(...)` | `api.host.toast(...)` |
| `badge(text, 'is-warn')`（`dom.js`） | `api.ui.badge({value: text, tone: 'warning'})` |
| `button(label, 'is-ghost', fn)`（`dom.js`） | `api.ui.button({label, variant: 'ghost', onClick: fn})` |
| `section(title, subtitle)`（`dom.js`） | `api.ui.section({title, description})` |
| `icon(name, cls)`（`dom.js`） | `api.ui.icon(name, {className: cls})` |
| `api.setFullscreenScrim(...)` | 删除 |
| `localStorage` 存界面偏好 | `api.storage.set/get`（跟着插件走，卸载即清理） |

> `frontend/dom.js` 里的 `styledSelect` / `numberInput` / `checkbox` / `textarea` /
> `closeSelectMenus` / `destroySelects` 是**自定义下拉框**实现，宿主原语没有等价物。
> 保留它们（它们有 403 行且已测试过），但 `el` / `button` / `badge` / `section` / `icon`
> 这些薄封装应改为委托到 `api.ui.*`，避免两套外观。
> 注意：`dom.js` 的 `icon()` 目前硬编码 `/static/icons/ui.svg`。改用 `api.ui.icon()`
> 后**不再需要**这个函数——宿主负责名字 → sprite 的映射，插件也不会因为宿主
> 调整精灵划分而失效。

### 步骤 5 — plugin.css

1. 删掉 `.plugin-stm-ai-assistant-launcher` 及其 `:hover` / `.is-dragging` /
   `-icon` 全部规则（连同 `z-index: 2140`）。
2. 删掉 `.plugin-stm-ai-assistant-overlay` 的 `position: fixed` / `inset` /
   `z-index: 2150` / `backdrop-filter` / `background: var(--surface-scrim…)`。
   面板内容现在活在宿主容器里，不需要自己的遮罩。
3. 删掉 `body:has(.plugin-stm-ai-assistant-overlay.is-open) .main-container {…}`
   兜底规则（连同它上面那一大段根因注释——那是对旧宿主的记录，现在宿主已修）。
4. 保留：`.plugin-stm-ai-assistant-root` 之外的**所有内容级样式**
   （tabs / body / card / field / badge / progress / log …）。
5. `frontend/assets/icon.svg` 的 `mask` 引用：这是**插件自己的资源**，合规，保留。
   但如果插件图标不再出现在坞里（坞用 `entries[].icon` 的宿主图标名），
   确认它是否还有消费者；没有就一并删掉。
6. 自检：
   ```powershell
   python -c "from core.plugins import installer; print(installer.scan_css_scope(r'D:\Workspace\MyOwn\ST-Manager-AI-Assistant\frontend\plugin.css','stm-ai-assistant'))"
   python -c "from core.plugins import installer; import json; print(json.dumps(installer.scan_css_declarations(r'D:\Workspace\MyOwn\ST-Manager-AI-Assistant\frontend\plugin.css','stm-ai-assistant'), ensure_ascii=False, indent=2))"
   ```
   两个都应为空（或只剩有意的 warning）。

### 步骤 6 — 测试与文档

1. `tests/test_manifest_contract.py`：
   - `test_api_version_and_min_app_version` 断言 `api_version == 1` → 改 `2`，
     并补 `manifest_version == 2`。
   - 新增：`frontend.entries` 结构校验（键白名单、id 正则、kind 集合、
     surface.type 集合、16 项上限、无旧三字段）。
   - 新增：`entries[].icon` 的宿主图标名**全部存在**——用
     `GET /api/plugins/ui-icons` 或主程序的 `core.plugins.icons.has_host_icon()`。
     本插件用到：`sliders-settings` / `tags` / `note` / `settings-gear` /
     `settings-help-entry` / `close` / `arrow-up` / `arrow-down` / `chevron-down` /
     `forbidden` / `check`（**均已实测存在**）。
   - `test_manifest_passes_main_app_validator` 里 `parsed.warnings == []` 保持，
     这是「新契约零警告」的最强断言。
2. `tests/test_css_scope.py`：
   - 保留现有作用域复刻。
   - 新增声明层自检：无 `position: fixed`、无硬编码宿主 sprite 路径、
     `var(--x)` 无回退时必须在宿主令牌清单内。
3. `docs/2026-10-08-stm-ai-assistant-design.md`：
   - 删掉/改写引用 `frontend.panels` / `settings_tab` / `detail_tab` 的段落
     （C4 那段「主程序没有前端消费者，因此插件 UI 自建」的结论**已经反转**）。
   - 更新为「插件声明 entries，宿主渲染坞与容器」。
   - 记录本次重写的入口表与 surface 表。
4. `CHANGELOG.md` 记一条：`api_version` 1 → 2，需要主程序 `PLUGIN_API_VERSION >= 2`。

---

## 5. 验收标准

- [ ] `python -m pytest tests/ -q` 全绿（插件仓库自身的 15 个测试文件）。
- [ ] 主程序侧：
      `python -m pytest tests/test_plugin_manifest.py tests/test_plugin_installer.py tests/test_plugin_css_scope.py -q` 全绿
      （把本插件目录作为夹具喂给主程序校验器时不报错）。
- [ ] `scan_css_scope` 返回 `[]`；`scan_css_declarations` 的 `position_fixed` 为空。
- [ ] 主程序 `PluginManifest.load(插件目录)` 的 `warnings == []`。
- [ ] 端到端（手工，需启动主程序）：
      1. 重启主程序 → 坞里出现「AI 助手」入口（`dock`）。
      2. 点击 → 打开宿主提供的右侧抽屉，四个页签可切换。
      3. 未配 Provider 时 `open-review` 命令在命令面板里**可见但置灰**，
         点击跳转到插件配置区（不是无反应）。
      4. 选中若干卡片后，右键菜单/命令面板里 `analyze-selected` 变为可用；
         未选卡时置灰并显示 `disabledHint`。
      5. 跑一次批量分析 → 坞入口显示进度；待审批数 > 0 时 `open-review` 显示角标。
      6. 在设置页改插件配置 → 插件 UI 通过 `onConfigChange` 立即读到新值。
      7. 禁用插件 → 坞入口**立即消失**、surface 被强制卸载、无残留浮层。
      8. 框选卡片 → 不命中坞，也不命中面板。
- [ ] `frontend/plugin.css` 不再出现 `position: fixed`、`z-index: 2140/2150`、
      `backdrop-filter`、`body:has(...)`。
- [ ] 无新增依赖（`package.json` / 无 requirements 变化）。

---

## 6. 已知陷阱

1. **`entries[]` 键是严格白名单**。多写一个 `tooltip` 之类会让**整个插件拒绝加载**，
   错误信息形如 `manifest_unknown_key` / `field: frontend.entries[0].tooltip`。
   开发期先用主程序校验器自检，别等装上去才发现。
2. **`surface.id` 两侧必须一致**。坞按 `<pluginId>:<surface.id ?? entry.id>` 查表；
   如果你在 manifest 写了 `surface: {id: 'main'}`，`api.surfaces.register` 就必须用
   `'main'`，写 `'workbench'` 会导致点击无反应（且不报错）。
3. **`when.config.requireKeys` 读的是 `config_schema` 与 `secret_schema` 的键**。
   本插件 `api_key` 在 `secret_schema` 里，所以
   `when: {config: {requireKeys: ["api_key"]}}` 是合法的（宿主会把密钥的「是否已设置」
   也纳入判断），但**只有非空值才算满足**。
4. **不要在 surface 里再写 `position: fixed`**。宿主容器已经定位好了；
   你在里面写 fixed 会相对视口定位，直接把布局打散。声明层检查也会记 warning。
5. **不要试图隐藏宿主的关闭按钮**。`.plugin-surface__close` 是宿主 DOM，
   不在 `.plugin-stm-ai-assistant` 作用域内，插件 CSS 选不中它。
6. **`api.toast` 的 `duration` 必须是数字**。传字符串会被强制成 3000。
   本插件现有 62 处调用基本都是 `api.toast(msg, 5000, 'icon-name')`，迁移时保留数字。
7. **图标名不含 `/` 与 `.`**。`api.ui.icon('assets/icon.svg')` 不会被解析；
   插件自带资源走 `api.utils.toAbsoluteAssetUrl()` 自己拼 URL（或直接写
   `/api/plugins/stm-ai-assistant/assets/…`，如现有 CSS 的 mask 那样）。
8. **`api.storage.get` 是同步的、`set` 是异步的**。`get` 读本地缓存（激活时预热一次），
   所以不要指望「`set` 完立刻在别处 `get` 到」跨上下文生效。
9. **卸载/禁用时宿主会强制卸载 surface**，但**不会**替你清 `backend` 的作业。
   现有 `deactivate` 里的清理逻辑保留。
10. **`data/plugins/stm-ai-assistant/` 是运行期目录**，不要直接在里面改代码——
    改插件仓库，然后重新安装或做符号链接。

---

## 7. 建议的执行顺序

```
步骤 1 manifest（+ 测试自检）      ← 先让新契约通过，哪怕前端还没动
   ↓
步骤 5 plugin.css（删 fixed/overlay/backdrop-filter）  ← 先拆掉旧壳
   ↓
步骤 3 panel.js（拆出 surface 内容渲染器）
   ↓
步骤 2 plugin.js（entries + surfaces 接线）
   ↓
步骤 4 views/*.js（批量替换 api.ui.* / api.host.*）
   ↓
步骤 6 测试与文档
```

先做 manifest 与 CSS 的原因：这两步能立刻用主程序校验器验证，
而前端接线要等 surface 骨架就位才能跑通。

**每步结束报告**：改动文件清单 → 该步自检命令与结果 → 与本文档的偏差 → 遗留问题。

---

## 8. 一句话提醒

这次重写**不是为了换一套写法**，而是为了让插件不再自己承担宿主的职责。
如果改完之后插件里仍然有 `position: fixed`、仍然自己处理 ESC 与焦点、
仍然自己算 z-index，那这次重写就没做对。

**后端一行业务逻辑都不该因为这次重写而变化。**
