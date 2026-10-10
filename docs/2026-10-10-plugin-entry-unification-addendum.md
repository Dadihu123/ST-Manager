# 插件入口统一化设计 · 追加篇（无兼容负担下的复核）

> 本文是 [2026-10-10-plugin-entry-unification-design.md](2026-10-10-plugin-entry-unification-design.md) 的追加篇。
> 触发条件：用户追加约束（m00532，逐字）——「插件系统还没有发布，目前已安装的插件也是我自己做的，所以插件方面不用考虑兼容问题，请结合此条信息看看还有哪些值得优化的点没有」。
> 状态：**设计草案，未实现**。本文只做分析与设计。
> **后续修订**：[2026-10-10-plugin-third-party-ecosystem.md](2026-10-10-plugin-third-party-ecosystem.md)（追加篇之二）——用户澄清「插件未来会开放给其他人、AI 助手将作为官方插件发布但非内置」后，对本文 §4.9（插件测试归属）、§1 表（Provisional 分级 / 强制迁移）、§6 反目标 9 的修订，以及一批第三方生态专属的新增点。**冲突时以追加篇之二为准。**

---

## 0. 一句话

兼容负担解除后，**主文档里有一整类设计变差了**（凡是写着「保留别名」「继续可用」「不升 api_version」「deprecated 但保留」的地方，都是为不存在的旧插件付的税），而**同时暴露出一批更大的机会**：宿主与插件是同一批人写的，就不该把插件当外部消费者对待——应该共享主题层、原语层、测试层。

---

## 1. 这条约束移除了什么（主文档需回改的条目）

| 主文档位置 | 原设计（为兼容而保守） | 现在应改为 |
|---|---|---|
| §6.4 兼容与迁移 | `frontend.panels` 保留为 `entries[]` 的 deprecated 别名，解析时自动转换 | **直接删除** `frontend.panels` / `frontend.settings_tab` / `frontend.detail_tab` 三个字段的解析与下发。`core/plugins/manifest.py:277-279`、`:486-494`、`:326-327` 全部移除 |
| §6.4 | `api_version` 不升 | **升到 2**（`core/version.py:11 PLUGIN_API_VERSION = 1` → `2`，`:13 SUPPORTED_PLUGIN_API_VERSIONS = (2,)`）。这不是破坏性变更的成本，而是**发布前的契约塑形窗口**——窗口关闭后再改就要走 D8 的硬闸门流程 |
| §6.4 | `api.registerModal(spec)` 保留为语法糖 | **直接删除**（`static/js/pluginHost.js:317-321`）。它是「往没人渲染的 Map 里塞东西」的半成品，没有迁移价值 |
| §6.4 | `api.registerSettingsSection(spec)` 保留为语法糖 | **直接删除**（`static/js/pluginHost.js:323-327`）。同上 |
| §6.4 | 插件自绘的悬浮球「继续可用」 | **删掉**。`data/plugins/stm-ai-assistant/frontend/plugin.js` 的 launcher 实现（`:33-62`、`:64-95`、`:106-164`、`:200-205`）整体退役，`frontend/plugin.css:15-48`、`:72-87`、`:146-149` 随之删除 |
| §11 阶段 F | 「可选：对尚未迁移的第三方插件球做受限捕获」 | **删除该阶段**。不存在需要过渡的第三方插件 |
| §12 风险 5 | 「旧插件球与新坞并存」 | **删除该风险** |
| §12 风险 10 | 「契约膨胀 → 全部标 Provisional、不升 api_version」 | 改为：**首次发布即定 Stable**。Provisional 是给「已有发布版本、需要试探性扩展」的场景用的；我们没有那个场景 |
| §14 反目标 6 | 「不强制迁移」 | **改为强制迁移**：主程序发布时不存在任何自绘浮层的合法用法 |
| §13 测试策略 | 「不填 entries 的旧 manifest 行为不变」（回归保护） | **反转为**：manifest 出现 `panels`/`settings_tab`/`detail_tab` 或未知键时**拒绝加载并报错**（见 §4.3） |

**净效果**：主文档 §6.4 从「兼容矩阵」退化为一句话「无兼容负担，直接改」；阶段 F 消失；风险表少两条。设计更短、更干净。

---

## 2. 最重要的机会：宿主与插件是同一批人写的

主文档把插件当**外部消费者**对待（只给 API 契约 + 文档）。既然两个插件都是自研的，就应该把关系升级为**同一个产品内的两个模块**：

| 维度 | 主文档（外部消费者模型） | 应改为（同产品模块模型） |
|---|---|---|
| 主题 | 插件自己 `var(--action-surface, #xxx)` 猜令牌名 | **令牌清单成为契约的一部分**，缺失即安装期报错（§4.6） |
| 原语 | 插件自己画 tab / 表单 / 按钮 / 卡片 | 宿主提供 `api.ui.*` 原语，插件消费（§4.1） |
| 测试 | 插件测试不在主测试套件里 | 插件的契约测试进主套件（§4.9） |
| 日志 | `api.log()` 写进服务端 logger，插件作者看不到 | 宿主提供插件日志面板（§4.8） |
| 开发 | 改前端插件要手动刷新整页 | 前端插件热重载（§4.10） |

**最有说服力的数字**：`data/plugins/stm-ai-assistant/frontend/plugin.css` 有 **1191 行**，而其中真正表达「AI 助手」业务语义的只是一小部分；其余是在重画宿主已经有的东西——面板外壳、页签栏、表单控件、空态、错误态、加载态。这个比例就是「没有原语层」的代价。

---

## 3. 量化：两插件与宿主的重复面

| 宿主已有 | 插件重画了 | 证据 |
|---|---|---|
| `.detail-tabs` / `.detail-tab`（`static/css/modules/modal-detail.css:882-919`） | 插件自己的页签栏 | `data/plugins/stm-ai-assistant/frontend/panel.js:17-22` TABS + `plugin.css` 内 `.plugin-stm-ai-assistant-tab*` |
| `.ui-modal-*` 骨架（`static/css/modules/ui-refresh.css:14-43`） | 自己的 shell + header | `plugin.css:151-167`、`:172-182` |
| `.modal-overlay` + `--surface-scrim`（`static/css/modules/components.css:673-685`） | 自己的 overlay + 自己的 scrim 回退值 | `plugin.css:72-87`（`background:var(--surface-scrim,rgba(15,23,42,0.58))`） |
| `.plugin-form` / `schemaEntries` 自动表单（`static/js/components/pluginManager.js:317`、`:458-459`；`templates/modals/plugin_manager.html:206-266`） | 自己的 settings 页签 | `panel.js:17-22` 的 `settings` tab |
| `api.progress.*` → 右下批处理进度条（`static/js/pluginHost.js:238-267`） | 自己的状态显示 | `panel.js:130-153 refreshStatus` |
| 主题令牌（`static/css/modules/variables.css`、`color-system.css`） | 部分用、部分硬编码、部分带自造回退值 | `plugin.css:675-678` 用 `var(--z-dropdown,500)`；`plugin.css:15-36` 用 `var(--action-border)`（无回退）；`plugin.css:72-83` 用 `var(--surface-scrim,rgba(...))`（有回退）——**三种风格混用** |

---

## 4. 值得优化的点（主文档未覆盖或覆盖不足）

### 4.1 宿主 UI 原语库（最高优先级）

主文档 §6.2 只给了 `api.ui.confirm` / `prompt` / `section` / `toolbar` 四个，太薄。补齐后，插件的 panel 代码可以从「画界面」退化为「填数据」。

```js
api.ui = {
  // 容器
  panel({ title, subtitle, actions })        // → { element, header, body, footer, setActions() }
  section({ title, description })            // → { element, body }
  card({ title, meta })                      // → { element, body }
  // 表单（与 config_schema 渲染器共用同一套控件）
  field(schemaEntry, { value, onChange })    // → { element, get(), set(v), validate() }
  form(schema, { values, onSubmit })         // → { element, getValues(), setValues(v), setErrors(e) }
  // 动作
  button({ label, variant, icon, onClick, disabled })  // variant: primary|secondary|danger|ghost
  toolbar(items)                             // 横向/纵向自动排布
  // 反馈
  empty({ icon, title, description, action })
  error({ title, message, retry })
  loading({ label })
  badge({ value, tone })                     // tone: neutral|info|success|warning|danger
  // 列表
  list({ items, renderItem, empty })
  table({ columns, rows })
  // 布局
  grid({ columns, gap })
  split({ left, right, ratio })
}
```

**硬性收益**：`plugin.css` 的 1191 行里，估计 60% 以上可以被删除。这也是验证契约表达力的最好方式——**如果参考实现迁移后 CSS 没有大幅缩短，说明原语库设计失败**。

**新增反目标**：插件不得再定义 `.plugin-<id>-button` / `.plugin-<id>-card` / `.plugin-<id>-panel` 这类通用外观类。安装期可以做启发式检查（§4.6）。

### 4.2 入口可见性需要条件表达式，不只是 `contexts`

主文档的 `contexts: ['cards']` 只能表达「在哪个模式」。真实需求还需要：

```jsonc
{
  "id": "analyze-selection",
  "kind": "context",
  "label": "AI 分析选中卡",
  "when": {
    "mode": ["cards"],                    // 模式
    "selection": "any",                   // none | any | single | multi
    "indexState": "ready",                // 索引就绪才可用
    "config": { "requireKeys": ["api_key"] },  // 未配密钥则置灰并提示去配置
    "hostVersion": ">=1.0.0",
    "feature": ["hasNetwork"]             // 宿主能力开关
  },
  "disabledHint": "请先在插件设置中填写 API Key"
}
```

要点：

- `when.config.requireKeys` 特别有用：插件未配置密钥时，入口应**可见但置灰 + 可点进配置**，而不是消失或点了报错。这是「配置入口」痛点的直接解法。
- `disabledHint` 让置灰状态可解释。
- 求值放宿主（注册表统一算），插件只声明，避免每个插件各写一遍。

### 4.3 manifest 校验：从未知键拒绝开始

既然没有兼容负担，manifest 解析应**严格拒绝未知键**。现在的问题：`core/plugins/manifest.py:431-494` 只挑认识的键，写错 `"entrys"` 或 `"frontend.entrys"` 会**静默忽略**，表现为「入口不出现」而不报错——这是最难查的一类 bug。

建议：

| 规则 | 处理 |
|---|---|
| 顶层未知键 | **拒绝加载**，错误信息列出合法键 |
| `backend.*` / `frontend.*` 未知子键 | **拒绝加载** |
| `entries[].*` 未知子键 | 拒绝该项（或整体拒绝，见下） |
| `entries[].kind` 未知值 | **拒绝加载**（不是 warning）——静默降级为别的 kind 会让作者困惑 |
| 新增 `manifest_version`（建议 `2`） | 缺省视为 1；1 表示旧格式（`panels`/`settings_tab`），此时**拒绝并提示**「该 manifest 使用已废弃的 frontend.panels，请改为 frontend.entries」 |

现有的 warning 式宽松（`manifest.py:426`、`:453` 的 `warnings.append(f'忽略未知 hook: {hook_name}')` 等）在**发布后**是对的，但在**发布前**会掩盖错误。建议：对 `entries` 相关字段从严，其余保持宽松。

### 4.4 设置页配置面的真实短板

主文档 §7.4 只做了深链。实际还有三个洞：

1. **`config_schema` 是硬上限**。子集只有 `type/title/description/default/minimum/maximum/enum/secret/required`（`docs/2026-09-22-plugin-system-design.md:241`）。`stm-ai-assistant` 的 manifest 已经有 **13 个 config 属性 + 3 个 secret 属性**（`data/plugins/stm-ai-assistant/manifest.json:35-157`），且它的 `default_profile_id` 是「提示词档案 id」——**需要从动态列表里选**，schema 表达不了。于是插件只能自己画 settings tab。
   → 解法：`config_schema` 增加 `"x-ui": "custom"` 标记 + `kind:'settings'` 区块（宿主提供容器与原语，插件填内容）。**不允许插件自建设置模态框。**
2. **配置改动无通知**。`static/js/components/pluginManager.js:328-342 saveConfig()` 成功后只 `toast("配置已保存")`，**不派发任何事件**。插件的 UI 读不到新值（`stm-ai-assistant` 的 panel 就依赖 config）。
   → 新增 `api.onConfigChange(handler)` 或宿主事件 `plugin-config-changed`（detail: `{pluginId, config}`）。**注意**：现有 `settings-saved` 事件（`static/js/components/settingsModal.js:783`、`static/js/state.js:1375`）是给宿主自己的设置用的，不要混用。
3. **密钥与配置分离但入口不分离**。`openConfig` 与 `openSecrets` 是两个按钮（`templates/modals/plugin_manager.html:158-161`、`:206`）。深链锚点应支持 `plugin-config-<id>` 与 `plugin-secrets-<id>` 两种。

### 4.5 入口的进度 / 徽标 / 状态语义

主文档只提了 `setBadge`。补齐：

| 语义 | 用途 | API |
|---|---|---|
| 徽标 | 未读、待审批条数 | `api.entries.setBadge(id, n \| 'new' \| null)` |
| 进度 | 作业运行中显示进度环 | `api.entries.setProgress(id, { done, total } \| null)` |
| 状态色 | 正常 / 警告 / 错误（如密钥失效） | `api.entries.setStatus(id, 'ok'\|'warn'\|'error'\|'idle')` |
| 忙碌 | 点击后到 surface 打开之间的过渡 | `api.entries.setBusy(id, bool)` |
| 只读状态 | 纯展示、不可点击 | 新增 `kind: 'status'`（如「连接正常」「今日已用 1.2 元」） |

`kind: 'status'` 值得单列：用户想「一眼看到」的东西（连接状态、用量、索引进度）目前只能靠插件画小球或塞进 header，`kind:'status'` 给了它们合法位置，且**不占用点击语义**。

### 4.6 主题令牌契约（把「猜令牌」变成「查令牌」）

现状三种风格混用（§3 末行）。建议：

1. **导出令牌清单**：宿主提供 `GET /api/plugins/ui-tokens`（或一个静态 JSON），列出全部可用 CSS 变量名与用途分类。插件的 `manifest.frontend.ui_tokens` 可声明自己依赖的令牌，安装期校验存在性。
2. **静态检查扩展**：`core/plugins/installer.py:521 scan_css_scope` 目前只查作用域。增加两项：
   - `var(--x)` 引用的 `--x` 不在令牌清单内且**没有回退值** → 警告（有回退值则不报，允许插件自定义局部变量）；
   - 顶层裸选择器检查保持（F11）；
   - 可选：`!important` 出现在非 `.plugin-<id>` / 非 `[data-plugin]` 选择器上 → 警告。
3. **令牌表补空档**：`static/css/modules/variables.css:17-35` 的 800–2100 无令牌（插件硬编码 2140/2150 正落此处）。除主文档已提的 `--z-entry-rail`，建议一并补齐 `--z-plugin-floating` 之类，让插件有合法位置。

### 4.7 `contexts` 与通用插件页容器之外：导航项配额

主文档 §7.3 让 `kind:'nav'` 数据化。既然没有兼容负担，可以更进一步定**配额策略**：

- 侧栏模块菜单**保持 8 个核心模块不变**；插件导航项走一个独立的「插件」二级入口（或在菜单底部加分隔线 + 「更多」）。
- 理由：侧栏菜单现在已经是下拉（`templates/components/sidebar.html:42-72`，桌面端也是折叠的），再塞 10 个插件项会退化成难用的长列表。
- 规则：`kind:'nav'` 只给「需要主内容区整页的完整功能」；其余一律 `kind:'dock'`。这条规则写进插件开发文档。

### 4.8 插件日志 / 诊断面

`api.log(level, message, **extra)`（`core/plugins/api.py:952`）与 `api.notify(level, message)`（`:948`）目前只进服务端 logger。插件作者在 UI 里看不到自己的插件在干什么。

建议：`templates/modals/plugin_manager.html` 的已安装卡片增加「日志」折叠区（读服务端按 plugin_id 过滤的最近 N 条）。这是**开发期最高性价比**的一项——现在调试插件只能看终端。

### 4.9 插件测试进主套件

- `tests/` 下已有 28 个插件测试文件（`test_plugin_*.py`），覆盖宿主侧。
- `data/plugins/stm-ai-assistant/tests/` 有 **15 个文件**（`conftest.py`、`fake_api.py`、`test_css_scope.py`、`test_hashing.py`、`test_jobs.py`、`test_llm.py`、`test_manifest_contract.py`、`test_module_layout.py`、`test_parsing.py`、`test_profiles.py`、`test_prompt.py`、`test_routes.py`、`test_store.py`、`test_tokens.py`、`test_trimming.py`），但它们在 `data/` 下、被 `.gitignore` 忽略（`.gitignore:9 data/*`），**不在主测试套件里跑**。
- 既然插件是自研的，应把它们纳入：插件源码移到版本库内（如 `plugins/stm-ai-assistant/`，安装时拷到 `data/plugins/`，或直接以 `data/plugins/` 为开发目录但用 `.gitignore` 例外放行）。
- **新增测试类型：入口契约一致性测试** —— 断言插件声明的每个 `entries[].id` 在运行时都能被 `api.surfaces.open()` 打开，反向亦然（声明了没实现、实现了没声明都要报错）。这直接防住 manifest 与代码漂移。

### 4.10 前端插件热重载（开发体验）

`PluginHost.destroy` 无调用方（`static/js/pluginHost.js:567-583`）→ 现在改前端插件必须整页刷新。

**前端插件**的热重载技术上可行且不难：
1. `PluginHost.destroy(pluginId)` 补上调用方；
2. 重新 `import()` 时加缓存穿透（`?v=<Date.now()>`）；
3. `<link id="plugin-style-...">` 换新 href 强制重取；
4. 插件管理页加「重新加载」按钮（仅纯前端插件可用；后端插件仍提示重启，因为 Python 无法热卸载——这是 `docs/2026-09-22-plugin-system-design.md:1618` 的 R11）。

这不需要兼容考虑，纯粹是自用开发效率。

### 4.11 偏好存储要统一走宿主

`stm-ai-assistant` 自己用 localStorage 存球位置（`frontend/plugin.js:13 POSITION_KEY='stm-ai-assistant.launcher-pos'`，`:75-95`）。坞接管后这条消失，但插件还有别的 UI 偏好。

建议提供 `api.storage`：
```js
api.storage.get(key) / set(key, value) / remove(key) / keys()
```
底层走 `ui_data._plugins_v1.<id>.storage`（有配额 256KB、有备份、卸载时随命名空间清理——`core/plugins/installer.py:491 _clear_ui_namespace`）。比插件各自写 localStorage 更可治理。

### 4.12 资产缓存与版本

`core/plugins/assets.py:108` 设 `Cache-Control: no-cache`（每次校验），但 URL 不含版本。插件更新后浏览器仍可能复用旧 CSS/JS。`docs/2026-09-22-plugin-system-design.md:1179` 已提到「生产可按 manifest 版本加 `?v=`」，但未实现。
→ 宿主统一在 `toAbsoluteAssetUrl`（`static/js/pluginHost.js:64-74`）与 `injectStyle`（`:76-90`）里追加 `?v=<plugin version>`。**发布前**改成本为零。

### 4.13 清理主文档漏掉的死代码

- `static/css/modules/layout.css:2522-2533` `.sidebar-toggle-button` —— 全仓零引用的死 CSS（主文档 §3.1 已记录，但没列进改动清单）。既然在动壳层 CSS，顺手删除。
- `core/event_bus.py` 已不存在（`core/plugins/hooks.py:3` 注释说明已被替换），无需处理。

### 4.14 API 命名一致性（发布前最后一次机会）

现在宿主侧 API 是三种命名风格混着：

| 现状 | 风格 |
|---|---|
| `registerAlpineComponent` / `registerModal` / `registerSettingsSection` | 动词开头 + PascalCase 名词 |
| `api.entries.*` / `api.surfaces.*`（主文档新增） | 名词命名空间 + 动词 |
| `api()` / `refresh()` / `switchMode()` / `openDetail()` / `openSettingsSection()` | 裸动词 |
| `progress.*` / `jobs.*` / `utils.*` | 名词命名空间 |

发布前统一到**名词命名空间**风格最干净：`api.ui.*`、`api.entries.*`、`api.surfaces.*`、`api.jobs.*`、`api.store.*`、`api.events.*`（`on`/`off`/`emit`）、`api.data.*`（`storage`）、`api.host.*`（`refresh`/`switchMode`/`openDetail`/`openSettingsSection`/`toast`/`progress`/`notify`/`log`）。

代价：`docs/plugin-api.md` 是**自动生成**的（`tools/gen_plugin_api_docs.py`，由 `tests/test_plugin_api_docs.py:35-42` 断言同步），改 API 必须同步改生成器的 `FRONTEND_MEMBERS`（`tools/gen_plugin_api_docs.py:68-94`）与 `BACKEND_GROUPS`（`:42`），否则测试失败。这是好事——它会强制文档同步。发布前改，一次到位。

### 4.15 命令面板与坞的职责边界

主文档把两者都放进「呈现层」。补一条规则避免它们互相蚕食：

- **坞** = 有持续状态的东西（作业进度、未读数、连接状态、常用功能）。
- **命令面板** = 一次性的动作（分析选中卡、导出、生成概览）。
- 一个入口可以两者都出现，但 `kind` 应显式声明倾向：`kind:'dock'` 默认进坞、`kind:'command'` 默认只在面板。`kind:'context'` 只进右键菜单。

---

## 5. 优先级

### P0 — 现在不做，发布后就要付代价

| # | 项 | 理由 |
|---|---|---|
| 1 | 删除 `panels`/`settings_tab`/`detail_tab`，`api_version` 升 2，删 `registerModal`/`registerSettingsSection`（§1） | 契约塑形窗口 |
| 2 | 宿主 UI 原语库 `api.ui.*`（§4.1） | 决定插件代码量级，后补意味着改所有插件 |
| 3 | `when` 条件表达式含 `config.requireKeys` + `disabledHint`（§4.2） | 直接解「配置入口」痛点；后补要改 manifest 格式 |
| 4 | manifest 未知键拒绝 + `manifest_version`（§4.3） | 静默忽略是最难查的 bug 类型 |
| 5 | `api.onConfigChange`（§4.4.2） | 插件 UI 与配置不同步，是明确的功能缺陷 |
| 6 | API 命名统一（§4.14） | 发布后再改就是破坏性变更 |
| 7 | 资产 `?v=` 版本化（§4.12） | 成本为零 |

### P1 — 与阶段 A/B 同期做

| # | 项 |
|---|---|
| 8 | 徽标/进度/状态/忙碌语义 + `kind:'status'`（§4.5） |
| 9 | 主题令牌清单导出 + 静态检查扩展（§4.6） |
| 10 | `stm-ai-assistant` 整体迁移为参考实现（§1 表末 + §3 重复面） |
| 11 | 插件测试进主套件 + 入口契约一致性测试（§4.9） |
| 12 | 设置页 `plugin-config-<id>` / `plugin-secrets-<id>` 深链 + `x-ui: custom`（§4.4） |

### P2 — 开发体验与治理

| # | 项 |
|---|---|
| 13 | 前端插件热重载（§4.10） |
| 14 | 插件日志面板（§4.8） |
| 15 | `api.storage`（§4.11） |
| 16 | 导航项配额策略（§4.7） |
| 17 | 坞 vs 命令面板职责规则（§4.15） |
| 18 | 死 CSS 清理（§4.13） |

---

## 6. 新增反目标

在追加篇约束下补充（主文档已有 8 条反目标）：

9. **不为兼容保留任何别名、deprecated 字段或过渡阶段。** 没有旧插件，过渡期是纯浪费。
10. **不允许插件定义通用外观类**（`-button` / `-card` / `-panel` / `-tab` / `-modal`）。外观必须来自 `api.ui.*` 或宿主 CSS 契约。
11. **不允许插件自建设置模态框。** 配置只能在宿主设置页内（`config_schema` 自动表单 或 `x-ui: custom` 区块）。
12. **不允许插件自绘 `position: fixed` 浮层。** 需要浮层时用 `api.surfaces`。
13. **不允许插件用 localStorage 存业务偏好。** 用 `api.storage`（可备份、可随卸载清理）。
14. **不把 Provisional 当「以后再说」的垃圾桶。** 首次发布即定 Stable；确需试探的用 `api.experimental.*` 命名空间显式标记。

---

## 7. 复核后的未决问题

在追加篇约束下，主文档 §15 的 7 个未决问题中有 3 个已被约束本身回答：

| 原问题 | 追加篇答案 |
|---|---|
| 5. 阶段 F 的受限捕获是否值得做 | **不做**。无第三方插件可过渡 |
| 6. 坞的拖拽用 HTML5 DnD 还是 Pointer Events | 倾向不变（Pointer），但现在可以**直接试错**——没有兼容包袱，选错了重写成本只是自己的时间 |
| 7. 命令面板的宿主内建命令清单 | 与 §4.15 的职责规则一起定；不再是「兼容问题」而是「产品定义问题」 |

新增未决：

| # | 问题 |
|---|---|
| 8 | 插件源码放哪：继续 `data/plugins/`（被 gitignore，但就是运行目录）还是迁到版本库内 `plugins/`（可测，但需同步/安装步骤）？ |
| 9 | `api_version` 升到 2 之后，是否顺便引入 `manifest_version` 做**格式**版本（与 **API** 版本解耦）？ |
| 10 | `stm-ai-assistant` 的 15 个测试文件迁移后，是否拆成 `tests/plugins/<id>/` 与宿主测试分目录？ |
| 11 | 原语库的样式归属：新增 `static/css/modules/ui-primitives.css`，还是并入既有 `ui-refresh.css`？ |

---

## 附录 · 本次复核新增的取证

| 事实 | 证据 |
|---|---|
| `PLUGIN_API_VERSION = 1`，`SUPPORTED_PLUGIN_API_VERSIONS = (PLUGIN_API_VERSION,)` | `core/version.py:11`、`:13`；`APP_VERSION = '1.0.0'`（`:8`） |
| 设计文档数值契约测试断言 `PLUGIN_API_VERSION == 1` 且 `SUPPORTED_PLUGIN_API_VERSIONS == (1,)`，并要求文档含「当前 `{1}`」 | `tests/test_plugin_contract_values.py:147-152` |
| `plugin-api.md` 是生成物，且测试断言磁盘内容 == `render()` | `tools/gen_plugin_api_docs.py:28 DOC_PATH`、`:68-94 FRONTEND_MEMBERS`、`:42 BACKEND_GROUPS`；`tests/test_plugin_api_docs.py:35-42` |
| manifest 解析对未知项只记 warning，不报错 | `core/plugins/manifest.py:426`（未知 hook）、`:453`（未知权限）、`:461`/`:467`/`:473`（requires 非法项）、`:483`（icon 不可用） |
| `stm-ai-assistant` manifest 有 13 个 config 属性 + 3 个 secret 属性，且含需动态选择的 `default_profile_id` | `data/plugins/stm-ai-assistant/manifest.json:35-157`（`default_profile_id` 在 `:38-43`，`description` 写「未显式指定时使用的档案 id；留空表示按模型自动匹配」） |
| 插件配置保存后无事件通知 | `static/js/components/pluginManager.js:328-342`（成功路径只有 `toast("配置已保存")`） |
| 宿主自身的 `settings-saved` 事件另有其主 | `static/js/components/settingsModal.js:783`、`static/js/state.js:1375`；消费方 `static/js/components/cardGrid.js:291`、`static/js/components/presetEditor.js:281` |
| 资产响应头 `Cache-Control: no-cache`，URL 无版本 | `core/plugins/assets.py:108`；文档预留但未实现见 `docs/2026-09-22-plugin-system-design.md:1179` |
| 插件测试不在主套件：`data/` 被 gitignore | `.gitignore:9 data/*`；`data/plugins/stm-ai-assistant/tests/` 含 15 个文件（`conftest.py`、`fake_api.py`、`test_css_scope.py`、`test_hashing.py`、`test_jobs.py`、`test_llm.py`、`test_manifest_contract.py`、`test_module_layout.py`、`test_parsing.py`、`test_profiles.py`、`test_prompt.py`、`test_routes.py`、`test_store.py`、`test_tokens.py`、`test_trimming.py`） |
| 主测试套件有全局数据隔离 | `tests/conftest.py:40-49` 把 `ui_store.UI_DATA_FILE` 与 `chat_store.CHAT_DATA_FILE` 重定向到临时目录 |
| 打包只含 `templates/` + `static/`，插件目录天然外置 | `.github/workflows/build-desktop.yml:39-40`（`--add-data "templates;templates"`、`--add-data "static;static"`）、`:83-84`（macOS 同） |
| 构建产物与标签策略：Windows onefile、macOS onedir+windowed，`v*` tag 触发 | 同上 `:34-41`、`:77-85`、`:7-8`；另有 Docker 镜像工作流 `.github/workflows/build.yaml:1-43` |
| 当前 `data/plugins/` 只有两个插件 | `data/plugins/` 目录列表：`hello-world`、`stm-ai-assistant` |
| 曾有一次卸载留下的回收站 | `data/system/trash/plugin_stm-ai-assistant_20261010122546/`（含 `tests/conftest.py`）——佐证「回收站」卸载路径已在真实使用 |
| 插件 CSS 作用域检查器只查作用域，不查令牌/`!important` | `core/plugins/installer.py:521-589`（`scope_tokens` 在 `:539-541`，违规收集在 `:568-570`）、`scan_style_scope` `:598-611` |
| 坞与入口槽位需要 `data-marquee-ignore`（否则框选会命中） | `static/js/utils/marqueeSelection.js:11` 的忽略选择器列表；现有生产方仅模态壳与插件按钮 |
