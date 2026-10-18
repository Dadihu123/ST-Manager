# 插件入口统一化设计（入口坞 / 入口注册表）

> 状态：**设计草案，未实现**。本文只做分析与设计，不含任何代码改动。
> 目标读者：主程序维护者 + 插件作者（独立仓库）。
> 前置文档：`docs/2026-09-22-plugin-system-design.md`（插件系统总体设计）、`docs/plugin-api.md`（API 参考）。
> **追加篇**：[2026-10-10-plugin-entry-unification-addendum.md](2026-10-10-plugin-entry-unification-addendum.md) —— 用户追加约束「插件系统未发布、已装插件均自研、无需考虑兼容」后，对本文 §6.4 / §11 阶段 F / §12 / §14 的修订，以及一批新增优化点（宿主 UI 原语库、`when` 条件表达式、manifest 严格校验、配置变更通知、API 命名统一等）。**两份文档有冲突时以追加篇为准。**

---

## 0. 结论摘要

1. **真正的问题不是「悬浮球太多」，而是「入口没有契约」。**
   今天插件想暴露一个入口，只能自己画：自己 `position: fixed`、自己定坐标、自己写 z-index、自己存位置、自己处理拖拽。宿主对这些元素**零可见、零控制、零清理**。球多了乱，只是这个缺口的表征。

2. **「捕获悬浮球」不可取**（技术否证见 §4.2）。它试图在**呈现层**补救一个**契约层**的缺失：无法可靠地重定父、会和插件自己的拖拽/定位逻辑打架、无法在插件停用时清理、且只能识别「长得像球」的东西，对页头按钮、卡片角标一律失效。

3. **推荐方案：注册表优先，呈现层可换。**
   - 插件**声明**入口（declaration），宿主**渲染**入口（presentation）。
   - 入口（entry）与界面（surface）解耦：入口只是一个「图标 + 标签 + 动作」的指针；点开什么由 surface 决定。
   - 因为解耦，宿主可以把同一批入口自由摆成：右侧入口坞、溢出菜单、命令面板、导航项、右键菜单项、设置区块——**插件代码一行不改**。这直接回答「最终结果不一定做成捕获悬浮球」。

4. **关键杠杆已经躺在代码里**：`manifest.json` 的 `frontend.panels` / `frontend.settings_tab` / `frontend.detail_tab` 三个字段**已经解析、已经下发到前端、前端零消费者**，且两个真实插件都没填。契约位是现成的、无人依赖、改动成本最低（§3.4、§6.4）。

5. **必须是主程序能力，不能做成插件**（论证见 §4.3）。但宿主应把自己的若干入口也用同一套契约声明，做到「宿主即第一个插件」。

6. **配置入口不需要第二套**。现状已经是统一的：设置 → 插件管理 → 就地展开配置（`pluginManager.js:308 openConfig`）。要做的是**让它可深链**、可从入口直达，而不是再造一个配置面板。

---

## 1. 问题重述

用户原话（m00001，逐字）：

> 「考虑这么一个需求，目前项目已经有了插件系统，而新插件意味着很多时候它们自己也要有自己的配置选项，而这种配置选项入口可能有多种形式，例如悬浮球（当前主程序已经安装了一个有悬浮球的插件），例如融合到某个页面中去成为新的导航项，我在想的时如果做了很多悬浮球（或者按钮），这样到时候看起来会很乱，我在想屏幕右侧比如弄一个隐藏条，靠近时可以展开，把悬浮球可以拖拽上去固定在对应的槽上，可以拖拽更换槽位，或者直接拖出去，这样便于管理，也便于整理，这个功能可以做成一个内置插件？或者直接修改主程序？目前只是个大概的想法，还不够成熟，请你从插件未来生态的角度考虑下这个问题，最终的结果也不一定就要做成捕获悬浮球的这种形式。」

拆成可判定的子问题：

| # | 子问题 | 本文对应章节 |
|---|---|---|
| Q1 | 入口形态发散（球 / 按钮 / 导航项 / 配置项）导致 UI 混乱，怎么治本？ | §2、§5、§6 |
| Q2 | 右侧隐藏条 + 槽位 + 拖拽固定/换位/拖出，是否可行、是否值得？ | §7.1、§4.2 |
| Q3 | 做成内置插件，还是改主程序？ | §4.3 |
| Q4 | 从插件未来生态看，什么形态才经得起增长（3 个 → 30 个插件）？ | §5、§7.2、§8、§11 |

---

## 2. 真实痛点分解

把「乱」拆开，会发现是五个不同的问题，各自需要不同解法：

| 痛点 | 表现 | 根因 | 本文解法 |
|---|---|---|---|
| **P1 位置冲突** | 两个插件都把球放在 `right:20px; bottom:96px`，完全重叠 | 没有「谁占哪块地」的概念，宿主不参与布局 | 宿主拥有容器（§7.1） |
| **P2 层级失控** | 插件硬编码 `z-index: 2140/2150`；宿主令牌表在 800–2100 是空的 | 插件自带浮层，层级由插件决定 | 入口不再自带浮层；浮层由宿主 surface 提供（§6.2、§12） |
| **P3 无法治理** | 宿主不知道有几个入口、属于谁、能不能关；禁用插件后球可能还在 | 入口是插件画的 DOM，宿主没有清单 | 入口注册表（§6） |
| **P4 无法个性化** | 用户不喜欢球的位置/顺序/是否显示，只能忍 | 没有用户侧偏好层 | 偏好层 + 管理总览（§8、§9） |
| **P5 形态不统一** | 每个插件的面板各写一套外壳、ESC 行为、移动端适配 | 宿主只提供了「单例作业面板」一种 UI 通道 | 宿主 surface 契约（§6.2） |

**关键判断**：P1/P2/P3 是**结构性**的，靠「整理球的工具」治不了——工具本身也得知道球在哪、属于谁。而只要插件还在自己画球，宿主就永远不知道。所以必须先有 **P3 的清单**，才谈得上 P1/P2 的治理，也才谈得上 Q2 的拖拽整理。**顺序不能反。**

---

## 3. 现状取证（全部只读核实，行号精确）

### 3.1 宿主壳层：右侧是空的

| 事实 | 证据 |
|---|---|
| `.main-container` 从侧栏右缘铺到视口右边缘，全站**没有右侧停靠栏/抽屉槽位** | `static/css/modules/layout.css:12-24`（`display:flex; flex:1; overflow:hidden`）、`static/css/modules/layout.css:26-34` `.content-area{flex:1; position:relative}` |
| 侧栏宽度是字面量，**没有宽度令牌** | `static/css/modules/layout.css:1703` `width: clamp(288px, 22vw, 336px)` |
| 顶栏是**在流内**的 64px 条，不是 fixed | `static/css/modules/layout.css:36-51` `.header-bar{height:64px; position:relative; z-index:var(--z-card-selected); flex-shrink:0}` |
| 视口四边的运行时占用：上=64px 顶栏；下=在流翻页栏 + toast（中）+ 批处理进度（右）；左=移动端固定侧栏；**右=无** | `static/css/modules/components.css:507-527`（toast）、`components.css:534-541`（batch progress）、`layout.css:2898-2907`（`.pagination-bar`） |
| `.sidebar-toggle-button` 是**死 CSS**：`position:fixed; bottom:3rem; left:1rem`，模板/JS 零引用 | `static/css/modules/layout.css:2522-2533`；全仓 grep 仅命中该 CSS 自身 |

**推论**：右侧边缘是宿主壳层里唯一空闲的全局位置。把它做成入口坞，不需要动 `.main-container` 的 flex 结构（坞是 overlay），零回流代价。

### 3.2 z-index 令牌表存在，且留了空档

- 令牌定义：`static/css/modules/variables.css:17-35`，取值 `--z-base:0`、`--z-card-highlight:40`、`--z-marquee-selection:45`、`--z-card-selected:50`、`--z-floating:100`、`--z-sticky:100`、`--z-dropdown:500`、`--z-sidebar-overlay:999`、`--z-sidebar-mobile:1000`、`--z-modal:1000`、`--z-modal-std:1100`、`--z-modal-editor:2000`、`--z-modal-detail:3000`、`--z-chat-reader:3200`、`--z-modal-popover:3400`、`--z-modal-alert:3600`、`--z-context-menu:9000`、`--z-toast:9500`、`--z-loading:9999`、`--z-topmost:10000`；配套 `!important` 工具类在 `variables.css:38-108`。
- **800–2100 区间无任何令牌**；已装插件 `stm-ai-assistant` 硬编码的 2140/2150 正好落在这个空档。
- `static/js` 全仓**零** z-index 引用（grep `z-floating|z-modal|z-dropdown|z-toast` 无命中）——层级完全由 CSS 侧掌控。
- 特征文件里另有散落字面量：`view-beautify.css:494` `z-index:70`、`view-beautify.css:814` `z-index:40`、`modal-detail.css:3492` `46`、`modal-detail.css:3507` `44`、`detail-card-workbench.css:3356` `105`、`:3375` `110`、`modal-preset-workbench.css:2933` `20`、`layout.css:1719` `20`。

### 3.3 右侧抽屉已有先例（可复用模式，非槽位）

| 先例 | 证据 | 形态 |
|---|---|---|
| 卡片高级筛选 | `static/css/modules/layout.css:262-274` `.card-advanced-filter-overlay{position:fixed;inset:0;display:flex;justify-content:flex-end;z-index:var(--z-modal,1200)}` + `:276` 起 `.card-advanced-filter-drawer`；小屏 `width:min(100vw,32rem)`（`layout.css:1195-1200`、`:3970-3972`）；粘底页脚 `layout.css:1509-1521` | 全屏遮罩 + 右侧面板 |
| 美化包详情 | `static/css/modules/view-beautify.css:493-509` `.beautify-package-detail-drawer{position:fixed;inset:0;display:flex;justify-content:flex-end;z-index:70}`，面板 `width:min(360px,100vw);height:100%;border-left:1px solid var(--border-default)` | 同上，**z-index 字面量 70** |
| 聊天阅读器三栏 | `static/css/modules/view-chats/reader-shell.css:1-4`；列宽在 JS：`static/js/components/chatGrid.js:5337-5369` `get readerBodyGridStyle()` 桌面 `320px minmax(0,1fr) 300px`；rail 令牌 `static/css/modules/view-chats/reader-workbench.css:6-7` `--chat-reader-rail-width:16rem; --chat-reader-inspector-width:19rem`；≤900px 变全屏 sheet（`reader-workbench.css:864-876`、`responsive.css:629-644`） | 固定三栏工作台 |

**推论**：宿主已经有「右侧抽屉」的视觉与交互词汇，入口坞应沿用同一套语言，但**层级必须低于抽屉/模态**（否则坞会浮在抽屉之上）。

### 3.4 契约位已存在但无人消费（本设计最重要的发现）

`core/plugins/manifest.py` 已声明并解析：

| 字段 | 声明 | 解析 | 下发前端 |
|---|---|---|---|
| `frontend.panels`（list[dict]，须含 `id`） | `manifest.py:277` | `manifest.py:486-491` | `to_dict()` 的 `panels`，`manifest.py:326` |
| `frontend.settings_tab`（dict） | `manifest.py:278` | `manifest.py:493` | `to_dict()` 的 `settings_tab`，`manifest.py:327` |
| `frontend.detail_tab`（dict） | `manifest.py:279` | `manifest.py:494` | 未进 `to_dict()` |

设计文档里这三者的形态样例（`docs/2026-09-22-plugin-system-design.md:187-191`）：

```jsonc
"panels": [
  { "id": "ai-workbench", "mode": "cards", "label": "AI 分析", "icon": "ai" }
],
"settings_tab": { "id": "ai", "label": "AI 助手" },
"detail_tab": null
```

**消费面实测（全仓 grep）**：

- `static/js` 中 `frontend_panels` / `settings_tab` / `detail_tab` / `.panels` 的**唯一**命中是 `pluginHost.js:319-320`、`:325-326`——那是 `registerModal` / `registerSettingsSection` 往内存 Map 里塞东西，**没有任何渲染方**。
- `templates/` 中这些名字**零命中**。
- 两个真实插件的 manifest **都没填**这三个字段：`data/plugins/stm-ai-assistant/manifest.json:18-23` 与 `samples/plugins/hello-world/manifest.json:15-18` 的 `frontend` 段只有 `entry` 与 `styles`。
- `docs/plugin-api.md:131-132` 把 `registerModal` / `registerSettingsSection` 标为 **Provisional**；`data/plugins/stm-ai-assistant/frontend/panel.js:1-9` 的头部注释明确记录了这个结论：manifest 的 `panels`/`settings_tab`/`detail_tab` 没有前端消费者，`registerModal()`/`registerSettingsSection()` 只填没人渲染的 Map，**所以该插件才自己画了一套 launcher + overlay**。

> 这就是「球」的来历：不是插件作者偏爱球，而是宿主没有别的通道。

### 3.5 宿主目前只有一条插件 UI 通道

- 唯一的宿主渲染插件界面：**作业面板**。`templates/components/plugin_job_panel.html:1` 导入图标宏、`:3` 注释「插件作业面板（设计文档 1.7）：由 api.jobs.open(runId) 触发」、`:4-12` 根元素 `x-data="pluginJobPanel" x-show="showPluginJobPanel" x-cloak class="modal-overlay ui-modal-overlay ui-refresh-surface z-modal-popover" data-marquee-ignore @click.self="close()"`、`:13-18` `.ui-modal-shell.plugin-job-shell` `role="dialog" aria-modal="true"`；尺寸 `static/css/modules/modal-plugin-job.css:5-14` `width:min(56rem, …); height:min(46rem, …) !important`。
- 打开方式只有事件：`static/js/components/pluginJobPanel.js:60-63` 监听 `open-plugin-job-panel`（`:65-68` 移除），或 `api.jobs.open(runId)`（`pluginHost.js:483-534`）。
- 结论：**单例硬编码模态框 + 插件事件被动打开**。没有任何可注册的入口/导航/停靠通道。

### 3.6 导航是硬编码的，加一项要改四处

| 位置 | 内容 |
|---|---|
| `templates/components/sidebar.html`（1204 行） | `#sidebar-module-menu`（`:75` 开、`:87-90` `role="menu"`、`:179` 收）内 **8 个硬编码 `<button role="menuitem">`**：cards `:91-101`（`@click` 在 `:94`）、worldinfo `:102-112`（`:105`）、chats `:113-123`（`:116`）、presets `:124-134`（`:127`）、regex `:135-145`（`:138`）、scripts `:146-156`（`:149`）、quick_replies `:157-167`（`:160`）、beautify `:168-178`（`:171`）；切换器 8 个 `x-cloak x-show="currentMode === 'X'"` 图标分支在 `:44-72`；移动端关闭按钮 `:182-190` |
| `static/js/components/sidebar.js`（1319 行） | `:18-27` `const MODULE_LABELS = Object.freeze({cards:"角色卡", worldinfo:"世界书", chats:"聊天", presets:"预设", regex:"正则脚本", scripts:"ST 脚本", quick_replies:"快速回复", beautify:"美化"})`；`:192-194` `get currentModeLabel(){ return MODULE_LABELS[this.currentMode] \|\| "管理模块" }`；`:214-235` `handleModuleMenuKeydown`（Escape/Home/End/ArrowDown(offset 2)/ArrowUp） |
| `static/js/components/layout.js` | `:221-260` `switchMode(mode)`——置 `$store.global.currentMode`、清 `selectedIds`、派发 `cancel-marquee-selection`、对 `cards/worldinfo/chats/beautify` 之外的模式清过滤条件、再派发 `refresh-wi-list`/`refresh-chat-list`/`refresh-beautify-list`/`refresh-card-list`；`:119-122` 监听 window 事件 `switch-mode`（`e.detail.mode`） |
| 各视图容器 | `x-show="currentMode === '...'"`：`grid_cards`、`grid_wi`、`chat_manager`、`grid_extensions.html:3`（`['regex','scripts','quick_replies'].includes($store.global.currentMode)`）、`grid_presets`、`grid_beautify`；`templates/components/header.html` 内 100+ 处 `currentMode === ...` 条件 |

**结论**：新增一个插件导航项，至少改 sidebar.html（菜单 8 按钮 + 切换器 8 分支）、sidebar.js 的 `MODULE_LABELS`、视图模板、header.html 的条件分支。**没有数据驱动的导航注册机制**——这是 Q1 里「融合到某个页面成为新导航项」这条路的真实成本。

### 3.7 插件运行时与生命周期

- 宿主根：`static/js/pluginHost.js:19` `const PLUGIN_ROOT_ID = "plugin-host-root";`；`:52-62` `ensureRootNode()` 复用或创建 `<div id="plugin-host-root" class="plugin-host-root" aria-live="off">` 并 `document.body.appendChild(node)`——**body 的最后一个子元素**，排在 toast div 之后，无内联定位。
- 宿主根 CSS：`static/css/modules/modal-plugin-manager.css:669-676` `.plugin-host-root{position:relative}`、`.plugin-host-root > [data-plugin]{display:block}`——**无 z-index、无 inset**。要浮起来全靠插件自己的 CSS。
- 加载：`pluginHost.js:92-110` `PluginHost`（`initialized/loading/root/loaded/failed/init()`），`init()` 幂等，`scheduleIdle(() => this.loadAll())`（`:44-50`，`requestIdleCallback(cb,{timeout:2000})` 否则 `setTimeout(cb,0)`）；`:112-145` `loadAll()` GET `/api/plugins/list`，跳过 `entry.enabled === false`，要求 `manifest.frontend && manifest.frontend_entry`，结束派发 `plugins:loaded`；`:147-178` `loadPlugin()` 跳过 `entry.style_scope_errors` 中的样式（console.warn，F11）、`injectStyle()` 其余、`await import(entryUrl)`、`api.createRoot("div")` 后 `root.classList.add('plugin-'+pluginId)`、`await module.activate(api)`——**`activate()` 的返回值被丢弃**（`samples/plugins/hello-world/frontend/plugin.js:71-73` 返回的 disposer 从未被调用）。
- `createRoot(tag='div')`：`pluginHost.js:537-543`，`node.dataset.plugin = pluginId`，`ensureRootNode().appendChild(node)`。
- 前端 API 全表：`id`(189)、`manifest`(190)、`state`(192，`Alpine.reactive({})`)、`get store`(194-200)、`on`(203-209)、`off`(211-215)、`emit`(217-227，仅核心事件或 `<pluginId>:` 前缀)、`toast`(230-236)、`progress`(238-267)、`openDetail`(270-280)、`refresh`(282-286)、`switchMode`(288-291)、`openSettingsSection`(293-301)、`registerAlpineComponent`(304-315)、`registerModal`(317-321)、`registerSettingsSection`(323-327)、`api()`(330-374)、`subscribeJob`(377-461)、`estimateTokens`(464-469)、`utils`(471-481)、`jobs`(483-534)、`createRoot`(537-543)。
- **没有实时卸载路径**：`PluginHost.destroy(pluginId)`（`pluginHost.js:567-583`）在全仓 `static/js` 与 `core/` 中**没有任何调用方**；`static/js/components/pluginManager.js:266-282` `toggleEnabled(item)` 只调启停 API、置 `restartHint`、`await this.loadPlugins()` 重取列表——**不 destroy、不重新 import、不刷新页面**。后端侧 `core/plugins/routes.py:197-210` `/enable`、`:213-231` `/disable`（先 `installer.cancel_plugin_jobs`）返回 `restart_required = bool(state.has_backend)`；`core/plugins/registry.py:198-199` 注释「写入 enabled 标志（只影响下次启动的加载行为）」。
- 现实语义：**UI 里启停插件，要到下次整页加载（后端插件还要重启进程）才生效。**

> 这条对本设计是**利好**：既然卸载路径缺失，那么「宿主拥有入口 DOM」就成了唯一能在停用时立刻消失的方案——坞从插件列表重新渲染即可，不需要调用任何插件代码。

### 3.8 现有「球」的实现（被治理对象）

`data/plugins/stm-ai-assistant/`（`frontend/plugin.js` 202 行、`frontend/panel.js` 167 行、`frontend/plugin.css` 1191 行）：

| 项 | 证据 |
|---|---|
| 位置键 | `frontend/plugin.js:13` `POSITION_KEY='stm-ai-assistant.launcher-pos'`（localStorage 自管） |
| 拖拽阈值 | `frontend/plugin.js:14` `DRAG_THRESHOLD=6` |
| 根容器 | `frontend/plugin.js:33` `const root = api.createRoot('div'); root.classList.add('plugin-stm-ai-assistant-root')` |
| 按钮 | `frontend/plugin.js:38-42` `<button class="plugin-stm-ai-assistant-launcher">` + `dataset.marqueeIgnore` |
| 挂载 | `frontend/plugin.js:53` `root.append(launcher, panel.element)` |
| 定位写内联 | `frontend/plugin.js:57-62` `applyPos(x,y)` 写 `left/top` 并清 `right/bottom` |
| 默认位 | `frontend/plugin.js:64-68` `{x: innerWidth - offsetWidth - 20, y: innerHeight - offsetHeight - 96}` |
| 拖拽 | `frontend/plugin.js:106-145` 自实现 pointerdown/move/up，位移超阈值才算拖 |
| resize 重夹 | `frontend/plugin.js:159-164` `requestAnimationFrame(restorePos)` + `resize` 监听 |
| 停用 | `frontend/plugin.js:200-205` disposer 移除监听、`panel.destroy()`、`root.remove()`；`:208-210` `export function deactivate(api)` **只打日志** |
| 球样式 | `frontend/plugin.css:15-36` `position:fixed; right:20px; bottom:96px; z-index:2140; width:44px; height:44px; border-radius:50%; cursor:grab`（注释写明「默认抬高，避开右下角翻页工具栏」） |
| 面板遮罩 | `frontend/plugin.css:72-87` `position:fixed; inset:0; z-index:2150`，`.is-open{display:flex}` |
| 面板壳 | `frontend/plugin.css:151-167` `width:min(1080px,94vw); height:min(760px,90vh); border-radius:14px` |
| 内部浮层**用了宿主令牌** | `frontend/plugin.css:675-678` `z-index:var(--z-dropdown,500)` |
| 唯一媒体查询 | `frontend/plugin.css:1170-1191` `@media (max-width:720px)`（球**没有**媒体查询，靠 96px 底距硬躲） |
| 合成器规避 | `frontend/plugin.css:146-149` `body:has(.plugin-stm-ai-assistant-overlay.is-open) .main-container{backdrop-filter:none !important}`；`:89-145` 记录了 Chromium 把 identity `backdrop-filter` 当 backdrop root 的缺陷与实测数据（`none: sd 4.774`、`brightness(1.02): sd 45.2, 63.2% navy`） |

**注意最后三行**：这个插件已经在**用宿主令牌**、已经在**给宿主写补丁式 CSS**（`body:has(...) .main-container`）。它其实是在徒手补一个本该由宿主提供的 surface 层。

### 3.9 前端既有能力盘点（可复用，不新增依赖）

| 能力 | 证据 | 对本设计的用途 |
|---|---|---|
| Alpine 组件注册表 | `static/js/app.js:55-89` 40+ 个 `Alpine.data(...)`（含 `pluginManager`、`pluginJobPanel`、`styledSelect`）；`:102-108` `if (window.Alpine) registerComponents(); else document.addEventListener("alpine:init", registerComponents)` | 坞组件按同一模式注册 |
| 全局事件总线（无 schema） | `static/js` 内全部 `window.dispatchEvent(new CustomEvent(...))`；与本设计相关的：`switch-mode`、`open-settings-section`、`settings-section-changed`、`plugins:loaded`、`open-plugin-job-panel`、`show-context-menu`/`hide-context-menu`、`refresh-*-list` | 坞与各入口的通信沿用事件，不引入新机制 |
| 插件核心事件白名单 | `pluginHost.js:21-33` `CORE_EVENTS`（11 个，与 `core/plugins/hooks.py:23-35` 一致）；`:35-42` `REFRESH_EVENTS` | 徽标刷新可挂 `card.updated` 等 |
| 拖拽 MIME 惯例 | `application/x-st-card`（`cardGrid.js:1633`）、`application/x-st-preset`（`presetGrid.js:371`）、`application/x-st-worldinfo`（`wiGrid.js:644`）、`application/x-st-folder`（`sidebar.js:783`）、`application/x-wi-clipboard` / `application/x-wi-entry-key` / `application/x-wi-clipboard-index`（`wiEditor.js:3910/3960/3994`） | 槽位排序用 `application/x-st-entry` |
| 指针级拖拽先例 | `static/js/utils/marqueeSelection.js:333` `session.root.setPointerCapture?.(session.pointerId)`；`static/js/components/detailModal.js:972`、`:1199-1201` `handle.setPointerCapture(event.pointerId)` | 坞手柄（如需）沿用 pointer capture |
| 列表排序 DnD 先例 | `static/js/components/tagFilterModal.js:2068-2091`（标签）、`:2141-2159`（分类） | 槽位重排照抄该模式 |
| localStorage UI 偏好先例 | `static/js/state.js:70` `const TAG_VIEW_PREFS_STORAGE_KEY = "st_manager_tag_view_prefs";`（`:1063` 读、`:1135` 写） | 坞的临时 UI 态（展开/收起）用 localStorage |
| 服务端偏好存储 | `core/data/ui_store.py:13` `UI_DATA_FILE`、`:71-82` 命名空间键常量、`:1967` `update_ui_data(mutator, …)`；插件命名空间 `_plugins_v1.<id>` 有 256KB 配额（`core/plugins/api.py:46-47`） | 入口布局偏好走 ui_data（可备份、可随卸载清理） |
| 图标通道 | `templates/components/icon.html` 宏 `icon`/`loading_icon`/`sidebar_icon`/`detail_icon`/`preset_icon`/`beautify_asset_icon`，渲染为 `<use href="{{ url_for('static', filename='icons/<sprite>') }}#icon-<name>">`；图标名白名单在 `static/js/state.js:79-95` | 坞槽位图标：宿主图标名 或 插件资源 URL |
| 框选忽略 | `static/js/utils/marqueeSelection.js:11` 含 `"[data-marquee-ignore]"` | 坞必须带该属性 |
| 设置页导航 | `templates/modals/settings.html:62-66` 五个 `role="tab"`；`static/js/components/settingsModal.js:175-206` `settingsHelpContent` **五键**（第五键 `plugins` 在 `:200-205`）；`:304-306` `selectSettingTab` 硬闸门 `if (!this.settingsHelpContent[section]) return;` | 插件配置区块挂在既有 plugins 页内，不新增顶层 tab |
| 插件管理页锚点 | `static/js/components/pluginManager.js:43-47` `ANCHOR_TABS = {"plugin-panel-installed":"installed","plugin-panel-catalog":"catalog","plugin-panel-upload":"upload"}`；`:99-105` 监听 `settings-section-changed`；`:114-130` `activate(anchor)`/`reloadActiveTab()`/`selectTab(tab)` | 深链需要扩展这张表（§7.4） |
| 配置就地展开 | `static/js/components/pluginManager.js:308-327` `openConfig(item)`（再点收起）、`:317` `this.configSchema = manifest.config_schema \|\| {}`、`:458-459` `schemaEntries`、`:466-467` `isRequired`；模板 `templates/modals/plugin_manager.html:206` `<div class="plugin-form" x-show="configTargetId === item.id" x-cloak>`、`:211-212` 「该插件未声明 config_schema，无自动表单。」、`:214` `x-template x-for="field in schemaEntries(configSchema)"`、`:158-161` 按钮文案 `configTargetId === item.id ? '收起配置' : '配置'` | 配置入口已经是统一的，只需加深链 |
| 作业面板契约 | `templates/components/plugin_job_panel.html`；`pluginJobPanel.js:49` `showPluginJobPanel:false`、`:61-62` 监听、`:70-81` `open(detail)`、`:89` `close()`、`:149` SSE/轮询刷新受 `if (!this.showPluginJobPanel) return;` 门控 | 作业可自动注册为「进度类入口」 |

### 3.10 测试面

`tests/` 下插件相关 28 个文件：`test_plugin_manifest.py`、`test_plugin_css_scope.py`、`test_plugin_loader.py`、`test_plugin_registry.py`、`test_plugin_load_failure_isolation.py`、`test_plugin_sse_frontend_contracts.py`、`test_plugin_jobs.py`、`test_plugin_sse.py`、`test_plugin_job_order.py`、`test_plugin_sse_seq.py`、`test_plugin_job_panel_contracts.py`、`test_plugin_catalog.py`、`test_plugin_secrets.py`、`test_plugin_dependencies.py`、`test_plugin_scaffold.py`、`test_plugin_hooks.py`、`test_plugin_api_docs.py`、`test_plugin_assets.py`、`test_plugin_routes.py`、`test_plugin_api.py`、`test_plugin_cli.py`、`test_plugin_error_codes.py`、`test_plugin_contract_values.py`、`test_plugin_isolation.py`、`test_plugin_frontend_assets.py`、`test_plugin_host_contracts.py`、`test_plugin_manager_contracts.py`、`test_plugin_installer.py`。

**已有「契约测试」传统**（`test_plugin_host_contracts.py`、`test_plugin_manager_contracts.py`、`test_plugin_contract_values.py`、`test_plugin_job_panel_contracts.py`）——本设计应沿用它，为入口契约加一组（§13）。

---

## 4. 方案空间与取舍

### 4.1 三个候选

| 方案 | 做法 | 评价 |
|---|---|---|
| **A. 捕获悬浮球** | 宿主扫描 `#plugin-host-root` 下的固定定位元素，把它们搬进右侧坞的槽位 | 见 §4.2，**否决** |
| **B. 约定 + 文档** | 只发一份「插件入口规范」文档，要求插件把球放某处 | **不足**：无法强制、无法治理、无法个性化；不解决 P3 |
| **C. 注册表 + 宿主渲染** | 插件声明入口，宿主渲染并提供 surface | **推荐**，见 §5 起 |

### 4.2 为什么「捕获悬浮球」不可取（技术否证）

| # | 问题 | 证据 |
|---|---|---|
| 1 | **会与插件自己的定位逻辑打架** | 插件在 `frontend/plugin.js:57-62` 用内联 `left/top` 定位、`:159-164` 在 `resize` 时 `restorePos` 重算。宿主改写它的 `right/bottom` 或搬动父节点后，插件下一次 resize 就把位置改回去 |
| 2 | **会与插件自己的拖拽打架** | `frontend/plugin.js:106-145` 自实现 pointerdown/move/up，`DRAG_THRESHOLD=6`。宿主再叠一层拖拽，两者会争夺同一批指针事件 |
| 3 | **停用时清不掉** | 捕获的是插件的 DOM；`PluginHost.destroy` 无调用方（§3.7），插件停用后坞里会留下孤儿节点，且它引用的插件状态已死 |
| 4 | **样式耦合到插件内部类名** | F11 允许宿主用 `[data-plugin="<id>"]` 作根选择器，但要让球「长得像坞里的一员」，宿主仍得写 `.plugin-stm-ai-assistant-launcher { … }` 这类内部类名——把宿主绑死在插件私有实现上 |
| 5 | **只认「长得像球」的东西** | 页头按钮、卡片角标、右键菜单项、导航项一律捕获不到。**不通用**，等于给未来的混乱留了后门 |
| 6 | **顺序不可逆** | 捕获需要先知道「哪些元素是入口」。在缺少声明的前提下，宿主只能靠启发式（`position:fixed` + 圆形 + 小尺寸）猜。猜错的代价是搬错东西 |

**保留价值**：捕获可以作为**过渡期的兼容垫片**（§11 阶段 4 的可选项），用于把尚未迁移的第三方插件球收进坞——但必须明确它是临时措施，且只对「宿主可识别的、无自绘拖拽的」球生效。**不能作为架构。**

### 4.3 内置插件，还是改主程序？

| 维度 | 做成插件 | 改主程序 |
|---|---|---|
| 需要的能力 | 注册导航项、拥有壳层右侧区域、列举/移除**其它插件**的入口、改写设置页 | 这些正是当前缺失的能力 |
| 鸡生蛋 | 要「注册导航项」得先有导航注册表——而它本身还不存在 | 无 |
| CSS 边界 | F11 强制 `.plugin-<id>` 作用域（`core/plugins/installer.py:521 scan_css_scope`，违规**拒绝加载整份样式**）→ 插件**无法**为壳层元素（`.main-container`、`.content-area`）写样式 | 无此限制 |
| 治理权 | 插件没有权限枚举/移除别的插件的 DOM | 宿主天然拥有 |
| 加载时序 | 插件在 `requestIdleCallback` 后才加载（`pluginHost.js:44-50`），坞会比首屏晚出现，且**未安装时整个功能不存在** | 随壳层一起渲染 |

**结论：入口注册表 + 坞 + 管理总览必须是主程序能力。** 但宿主应把**自己**的若干入口（如「批处理进度」「索引状态」「设置」）也用同一套契约声明——**宿主即第一个插件**——这样契约一落地就有真实消费者，也顺带验证了契约的表达力。

**不做成插件的代价**：`api_version` 需要 +1（新增 `api.entries` / `api.surfaces` 契约），或把这些能力定为「Provisional 增量、向后兼容、不升 api_version」。**建议后者**（见 §6.5），因为纯增量 API 不破坏既有插件，而 D8 的硬闸门本意是防破坏性变更。

---

## 5. 推荐方案总览

### 5.1 分层

```
┌──────────────────────────────────────────────────────────────────────┐
│ 声明层（插件 / 宿主自己）                                              │
│   manifest.frontend.entries[]  ──静态声明，安装即可见                  │
│   api.entries.register/update/remove/setBadge  ──运行时动态            │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ 归一化、校验、全局键 = <plugin_id>:<entry_id>
┌───────────────────────────▼──────────────────────────────────────────┐
│ 注册表层（主程序 core/plugins/entries.py + 前端 entryRegistry.js）      │
│   清单：谁、什么类型、什么标签、什么图标、在哪些模式出现、开哪个 surface │
│   这是宿主唯一的真相来源（single source of truth）                      │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ 只读投影（同一批入口，多种摆法）
┌───────────────────────────▼──────────────────────────────────────────┐
│ 呈现层（宿主拥有 DOM）                                                 │
│   ① 入口坞（右侧，默认）   ② 溢出菜单   ③ 命令面板（Ctrl/Cmd+K）        │
│   ④ 侧栏导航项            ⑤ 右键菜单项 ⑥ 设置区块   ⑦ 作业进度条       │
└───────────────────────────┬──────────────────────────────────────────┘
                            │ 打开
┌───────────────────────────▼──────────────────────────────────────────┐
│ 界面层（宿主提供容器，插件填充内容）                                    │
│   api.surfaces.register(id, { mount(container, ctx), unmount() })      │
│   宿主决定：抽屉 / 模态 / 整页 / 底部 sheet、层级、ESC、焦点陷阱、移动端  │
└──────────────────────────────────────────────────────────────────────┘
```

### 5.2 三条设计原则

1. **入口 ≠ 界面。** 入口是「图标 + 标签 + 动作」的指针；界面是它打开的东西。解耦之后，宿主可以随时改变入口的摆法（坞 / 溢出 / 面板 / 快捷键），插件零感知。
2. **宿主拥有容器，插件拥有内容。** 层级、尺寸、响应式、ESC、焦点陷阱、`data-marquee-ignore` 全由宿主负责；插件只往给定的 container 里 `mount`。
3. **声明优先于自绘。** 插件不应再画 `position:fixed` 的浮层。自绘球保留兼容，但不再是推荐路径。

### 5.3 与用户原始设想的对应

| 用户设想 | 本方案对应 |
|---|---|
| 「屏幕右侧弄一个隐藏条，靠近时可以展开」 | 入口坞：右侧热区 8px，hover/点击展开为 56px 图标列（§7.1） |
| 「把悬浮球拖拽上去固定在对应的槽上」 | 槽位 = 注册表条目的 `pinned` 状态；把「未固定」拖入坞即固定（§8.1） |
| 「可以拖拽更换槽位」 | 槽内重排，MIME `application/x-st-entry`（§8.1） |
| 「或者直接拖出去」 | 拖出坞 → 取消固定 → 落入溢出菜单（§7.2） |
| 「便于管理，也便于整理」 | 入口总览（设置 → 插件管理 → 入口）列出全部条目与归属、可见性、呈现位置（§8.2） |
| 「这个功能可以做成一个内置插件？或者直接修改主程序？」 | 主程序能力；宿主自身也用同一契约声明入口（§4.3） |
| 「最终的结果也不一定就要做成捕获悬浮球的这种形式」 | 采纳：不做捕获，做声明 + 注册表；坞只是**默认摆法**，可切换（§7.2 末、§11 阶段 4） |

---

## 6. 契约设计

### 6.1 manifest 扩展：`frontend.entries`

```jsonc
"frontend": {
  "entry": "frontend/plugin.js",
  "styles": ["frontend/plugin.css"],

  "entries": [
    {
      "id": "ai-workbench",          // 插件内唯一；全局键 = "<plugin_id>:ai-workbench"
      "kind": "dock",                // dock | nav | settings | context | command
      "label": "AI 分析",
      "description": "为角色卡生成概览与标签建议",
      "icon": "frontend/icon.svg",   // 相对插件根的资源路径；或宿主图标名（见下）
      "contexts": ["cards"],         // 在哪些 mode 下出现；空数组/缺省 = 全部模式
      "requires_selection": false,   // true 时无选中项则置灰
      "surface": { "type": "panel", "id": "workbench" },  // 点击后打开的界面
      "priority": 50,                // 默认排序权重（用户显式排序优先）
      "badge": null,                 // 静态徽标（如 "new"）；动态徽标用 API
      "shortcut": null               // 建议快捷键，如 "mod+shift+a"；用户可改
    }
  ]
}
```

**`kind` 语义表**

| kind | 默认落点 | 说明 |
|---|---|---|
| `dock` | 入口坞槽位（未固定则入溢出菜单） | 「悬浮球」的正式替代形态 |
| `nav` | 侧栏模块菜单 | 需要在主内容区占一个整页的模式 |
| `settings` | 设置 → 插件管理 内的区块 | 复杂配置（`config_schema` 覆盖不了的部分） |
| `context` | 右键菜单 / 卡片操作菜单 | 对当前对象生效的动作 |
| `command` | 命令面板（Ctrl/Cmd+K） | 可搜索的一次性动作，**不占任何视觉空间** |

**`icon` 解析规则**（按序尝试）

1. 形如 `frontend/icon.svg` 的相对路径 → 渲染 `<img src="/api/plugins/<id>/assets/frontend/icon.svg">`（资源路由扩展名白名单已含 `.svg/.png/.webp`，见 `docs/2026-09-22-plugin-system-design.md:1177`）。
2. 命中宿主图标白名单（`static/js/state.js:79-95` + `templates/components/icon.html` 各宏）→ 走宿主 sprite，自动继承主题色。
3. 都不命中 → 坞渲染首字母占位块，并在插件管理页记一条 warning。

**`surface.type` 取值**

| type | 宿主提供的容器 | 层级 |
|---|---|---|
| `panel` | 右侧抽屉（宽 `min(420px, 92vw)`；≤900px 变全屏 sheet） | 低于模态、高于坞 |
| `modal` | 居中模态（复用 `.modal-overlay` + `.ui-modal-shell`） | `--z-modal-popover` |
| `page` | 主内容区整页（用于 `kind: nav`） | 在流内 |
| `sheet` | 移动端底部 sheet | 移动端专用 |

**校验规则**（并入 `core/plugins/manifest.py` 现有校验，`docs/2026-09-22-plugin-system-design.md:226-237` 风格）

| 字段 | 规则 | 失败处理 |
|---|---|---|
| `entries[].id` | 非空、`^[a-z][a-z0-9-]{0,63}$`、插件内唯一 | 忽略该项 + warning |
| `entries[].kind` | ∈ `{dock,nav,settings,context,command}` | 忽略该项 + warning |
| `entries[].label` | 非空字符串，建议 ≤ 12 字符 | 忽略该项 + warning |
| `entries[].icon` | 解析后须在插件目录内（复用 `_resolve_plugin_path`） | 记 warning，图标降级为占位 |
| `entries[].surface.type` | ∈ `{panel,modal,page,sheet}` | 忽略该项 + warning |
| `entries[].contexts` | 元素 ∈ 已知 mode 集合 | 未知项忽略 + warning |
| `entries` 整体 | 最多 16 项（防一个插件塞满坞） | 超出部分忽略 + warning |

### 6.2 前端运行时 API

```js
// ---- 入口 ----
api.entries.register(spec)        // → entryKey；等价于 manifest 声明，供动态入口
api.entries.update(entryId, patch) // 局部更新 label/icon/badge/contexts/disabled
api.entries.remove(entryId)        // → boolean
api.entries.setBadge(entryId, value) // value: number | string | null
api.entries.open(entryId)          // 打开自己的入口（等价于用户点击）
api.entries.list()                 // 自己的入口列表（只读快照）

// ---- 界面 ----
api.surfaces.register(surfaceId, {
  title: 'AI 分析',
  mount(container, ctx) { /* 往 container 里画 */ return () => {/* 清理 */}; },
  unmount() {},
  onOpen(ctx) {}, onClose() {},
})
api.surfaces.open(surfaceId, ctx)  // ctx: { source: 'dock'|'context'|'command', targetId, mode }
api.surfaces.close(surfaceId)
api.surfaces.isOpen(surfaceId)     // → boolean

// ---- 宿主提供的 UI 原语（避免插件重造）----
api.ui.confirm({ title, message, danger })   // → Promise<boolean>
api.ui.prompt({ title, fields })             // → Promise<object|null>
api.ui.section({ title })                    // → HTMLElement（带宿主标题样式）
api.ui.toolbar(container, buttons)           // 统一的按钮排布
```

**`mount(container, ctx)` 的契约**

- 宿主传入的 `container` 已完成定位、尺寸、滚动、`data-marquee-ignore`、`role="dialog"`/`aria-modal`、焦点陷阱、ESC 关闭。
- 插件**必须**只在 `container` 内创建 DOM（F11/F12 精神：容器已带 `data-plugin="<id>"`）。
- 插件**不得**设置 `container` 或其祖先的 `position` / `z-index` / `inset`。
- `mount` 的返回值若是函数，宿主在关闭时调用它（**修掉现有 `activate()` 返回值被丢弃的问题**，`pluginHost.js:147-178`）。
- 宿主负责在插件被禁用/卸载时**强制卸载**所有 surface——不依赖插件的 `deactivate`（因为 `PluginHost.destroy` 无调用方，§3.7）。

### 6.3 全局键与命名

- 入口全局键：`<plugin_id>:<entry_id>`，例 `stm-ai-assistant:ai-workbench`。
  - 与既有惯例一致：插件自定义事件强制 `<plugin_id>:` 前缀（`core/plugins/hooks.py:59-66` `build_custom_event_name`）、数据库表强制 `plugin_<id>_` 前缀（`api.table_prefix`，`core/plugins/api.py:360`）。
- 宿主自身入口的键：`core:<entry_id>`，例 `core:job-progress`、`core:index-status`。
- 前端 MIME：`application/x-st-entry`（沿用 `application/x-st-*` 家族，§3.9）。
- localStorage 键：`st_manager_entry_dock_prefs`（沿用 `st_manager_tag_view_prefs` 命名，`static/js/state.js:70`）。
- ui_data 命名空间：`_entry_layout_v1`（顶层，与 `_tag_management_prefs_v1` 同级，`core/data/ui_store.py:71-82` 风格）。

### 6.4 兼容与迁移

| 现状 | 处理 |
|---|---|
| `frontend.panels[{id, mode, label, icon}]` | **保留为 `entries[]` 的 deprecated 别名**，解析时自动转成 `{kind:'nav', contexts:[mode], label, icon, id}`；`to_dict()` 继续下发 `panels` 字段（向后兼容）。因为**当前零消费者**，转换不会破坏任何插件 |
| `frontend.settings_tab{id,label}` | 转为 `{kind:'settings', label, id}` |
| `frontend.detail_tab` | 转为 `{kind:'context', contexts:['detail']}`（当前未进 `to_dict()`，需补） |
| `api.registerModal(spec)` | 保留，但改为「注册一个 `kind:'command'` 入口 + `surface.type:'modal'`」的语法糖；不再往无人渲染的 Map 里塞（`pluginHost.js:317-321`） |
| `api.registerSettingsSection(spec)` | 同上，映射为 `kind:'settings'` |
| 插件自绘的悬浮球 | **继续可用**（不破坏）。坞提供「迁移提示」：检测到插件已注册 `dock` 入口时，提示插件作者可退役自绘球。宿主**不做捕获**（§4.2） |
| `api_version` | **不升**。新增 API 全部为增量、可选；D8 的硬闸门语义是拒绝不兼容变更，纯增量不构成不兼容 |

---

## 7. 呈现层设计

### 7.1 入口坞（默认摆法）

> **2026 改版（「入口坞美化」）**：坞从「贯穿整屏的竖条」改成「垂直居中的毛玻璃
> 箭头 + 高自适应浮层」，收起态为默认。下方表格已同步更新；小节末尾记录改版理由。

**结构**（收起态 = 右边缘一枚毛玻璃小箭头；展开态 = 箭头左侧的毛玻璃浮层）

```
  ┌────────────────────────┐
  │                        │
  │                        │   ┌──────┐
  │                        │   │  ▣   │ ╮
  │      .content-area     │   ├──────┤ │ 浮层：毛玻璃、垂直居中、
  │                        │   │  ▣   │ │ 高度随入口数量塌缩
  │                        │   ├──────┤ │（入口少时框就矮，不留空白）
  │                        │   │  ⋯   │ ╯
  │                        │   └──────┘◀── 毛玻璃箭头（常驻、垂直居中）
  │                        │
  └────────────────────────┘
```

**行为**

| 项 | 规格 |
|---|---|
| 位置 | `position: fixed; right: 0; top: 64px（顶栏高度）; bottom: 64px（避开在流翻页栏）`；坞是**不可见**定位带（`pointer-events: none`），自身不绘制任何东西 |
| 空态门控 | 坞只由插件的 `kind: "dock"` 入口填充（宿主内建命令是 `kind: "command"`，不进坞）。`slots` 与 `overflow` **同时为空**时坞整体不渲染（`hasEntries`），移动端顶栏按钮与底部 sheet 同样门控 —— 没装带 dock 入口的插件时，右侧不留一枚点了没用的箭头。门控用 `x-show` 而非并进外层 `x-if`（后者会让插件装卸触发整树销毁重建，实测多抛 Alpine reconcile 报错） |
| 收起态（默认） | 右边缘**垂直居中**一枚毛玻璃小箭头（22×40px，`--dock-handle-*` 令牌），角上带入口数量数字标。浮层 `width: 0`、`border-width: 0`、`background: transparent`，**不占内容区宽度**，屏幕上没有常驻竖条 |
| 箭头朝向 | **指向"点它会去的方向"**：收起态朝**内**（左，`rotate(180deg)`），展开态朝**外**（右，`rotate(0deg)`）。sprite 只有 `icon-chevron-right`，左向由 180° 旋转得到 |
| 展开态 | 箭头左侧弹出毛玻璃浮层，宽 `--dock-panel-width`（= 槽位宽 + 10px 内边距与边框），**高度 `auto` 随入口数量塌缩**，仅 `max-height: 100%` 兜底滚动。展开触发 = hover 箭头/热区停留 150ms，或点击箭头 |
| 悬停热区 | 箭头周围一圈窄环（`calc(var(--dock-handle-width) + .5rem)`），**不再贯穿整屏高度** —— 旧的全高 8px 透明热区会在内容区右侧形成看不见的鼠标死区 |
| 收起动作 | 点击箭头。`collapse()` **必须取消挂起的 hover 展开定时器**，否则指针移向箭头触发的 150ms 定时器会在收起后把坞重新弹开（实测为必现竞态） |
| 槽位内容 | **只保留图标** + 可选徽标/进度/忙碌点。文字标签已从坞内移除；名称改由 `title` tooltip 与 `aria-label` 提供，溢出菜单里仍有完整文字 |
| 图标尺寸 | `--dock-icon-size`，与槽位配套：桌面 26/44 ≈ **0.59**、平板 24/40 = 0.60。覆盖规则用 `.entry-rail__icon > svg` / `> .ui-icon`（要压过 `icon()` 必带的 `ui-icon--sm`） |
| 数量数字标 | PC 挂在**箭头**左上角（`.entry-rail__toggle-count`），移动端挂在底部箭头上（`entry-dock-mobile-trigger__count`）。取值 `entryCount = entries.length` —— **不能**用 `slots.length`：社区插件默认不固定、只进溢出菜单，那样会让「只装了社区插件」时徽标凭空消失。挂左上角是因为右上角贴屏幕边缘会被裁掉 |
| 固定 | 点击坞顶部「📌」进入 pinned 态（不自动收起），存 localStorage |
| 键盘 | `role="toolbar"`，`aria-orientation="vertical"`，roving tabindex；`ArrowUp/Down` 移动、`Enter` 打开、`Delete` 取消固定。参照 `static/js/components/sidebar.js:214-235` 的 `handleModuleMenuKeydown` 模式 |
| 层级 | 令牌 `--z-entry-rail: 80`（在 `--z-card-selected:50` 之上、`--z-floating:100` 之下） |
| 遮挡处理 | **只有真正与坞重叠**的 surface（`panel` / `sheet`）打开时才收起：`body:has(.plugin-surface--panel) …`。**不得**写 `body:has(.modal-overlay)`：`:has()` 只看元素存在不看可见性，而主程序 28 个模态框全部用 `x-show` 常驻 DOM，那条规则几乎永久成立，会把坞永久压成不可见 |
| 溢出菜单 | `.entry-rail` 整体 `pointer-events: none`，因此**每个**可交互后代（`__panel` / `__toggle` / `__overflow`）都必须显式取回 `auto`；开合走事件身份守卫，Escape 由菜单自己处理（见下方「溢出菜单」小节） |
| 框选 | 坞根元素带 `data-marquee-ignore`（`static/js/utils/marqueeSelection.js:11`） |
| 移动端 | 无 hover。`deviceType === 'mobile'` 时坞不渲染为侧条，改为：**贴底部翻页栏**的向上箭头（`position: fixed`，36×36px，`bottom/right: 0.25rem`）→ 打开底部 sheet 列出全部入口。箭头收起态朝上（`rotate(-90deg)`）、展开态朝下（`rotate(90deg)`），与 PC 同一套语义 |
| 平板 | `deviceType === 'tablet'` 时坞默认收起且不自动展开（避免误触），点击展开；浮层与槽位各窄一档 |
| 主题 | 只用 `.color-*` 语义类与既有 CSS 变量（F2：`tests/test_color_system_contracts.py:117-137` 禁止 `bg-red-*`/`text-blue-*`） |
| 动效 | 遵守 `prefers-reduced-motion`（含箭头旋转） |
| backdrop-filter | **坞使用 `backdrop-filter`**（见下方改版说明）。契约由 `tests/test_plugin_entry_dock_contracts.py::test_dock_backdrop_filter_is_allowed_and_justified` 锁定 |

**改版说明（为什么推翻了旧的两条硬约束）**

1. **旧形态不可接受**：收起态 40px / 展开态 56px 的 `top:64px; bottom:64px` 竖条，
   视觉上是一条从顶栏通到翻页栏的白条；入口只有一两个时，浮层下方是大片空白。
   现改为「垂直居中 + 高度自适应」，两处都用 `align-items: center` +
   `height: auto`（`align-items: stretch` 会把浮层重新拉满整屏）。

2. **`backdrop-filter` 禁令的依据已经消失**。原禁令来自 `.main-container` 的
   backdrop root 黑块缺陷：它曾是几乎所有全屏遮罩的**祖先**，一旦自己成为
   backdrop root，遮罩的 `backdrop-filter` 就只能采样到不完整的 backdrop，
   极端情况画成纯黑矩形。现状：
   - `.main-container` 现在完全不带 `backdrop-filter`（壁纸模糊改走
     `body::before { filter: blur() }`），见 `layout.css` / `base.css`；
   - 坞是 `.main-container` 的**兄弟**节点（`templates/index.html`），
     不在任何全屏遮罩的祖先链上，不可能成为遮罩的 backdrop root。

   实测（Playwright + Chromium，1440×900，真实页面 + 真插件）：
   `getComputedStyle(.entry-rail__panel).backdropFilter` 取回
   `blur(14px) saturate(1.45)`，彩虹底图下可见明显磨砂混色；
   打开全屏「系统设置」模态时坞被遮罩正常盖住（`elementFromPoint` 命中
   `.modal-overlay`，z 1100 > 坞 z 80），坞所在区域**无黑块**，遮罩控件交互正常。

   因此坞启用 `backdrop-filter`，同时把「`.main-container` 不得带
   backdrop-filter」「坞不得成为遮罩祖先」这两条**真正的不变量**写进契约测试。

**溢出菜单（2026 修复的三处「画得出但用不了」）**

改版顺带查出溢出菜单**一直是完全不可用的**（既有缺陷，非改版引入，已用 HEAD
对照回放确认），三处都已修复并被契约锁定：

1. **打不开**：`@click.outside` 会捕获「打开菜单的那一次点击」。Alpine 的
   `@click` 先置 `overflowOpen = true`，响应式副作用随即把 `.entry-overflow`
   插入 DOM 并挂上 document 级 `@click.outside`；此时原点击**仍在冒泡**，按 DOM
   规范「派发中新增的监听器」会对尚未访问的祖先生效，于是菜单在同一轮派发里被
   自己那次点击关掉（`overflowOpen` 同帧 true→false，DOM 里数量恒为 0）。
   修法：事件身份守卫 `_overflowOpenedByEvent`，`closeOverflow($event)` 跳过它。
   **不用 `@click.stop`** —— 那会让点击到不了 document，破坏仓库里「点任意处
   关闭其它浮层」的既有约定（`contextMenu.js` 的全局 click 监听）。
2. **点不动**：`pointer-events` 是**继承**属性，`.entry-rail` 整体
   `pointer-events: none`（避免整屏定位带变成鼠标死区），而 `.entry-overflow`
   没像 `__panel` / `__toggle` 那样取回 `auto`。症状是菜单正常渲染但
   `elementFromPoint` 穿过它命中下面的 `.card-grid`，搜索框、条目、固定按钮全失效。
   修法：`.entry-overflow` 显式 `pointer-events: auto`。
3. **Escape 失灵**：坞的 `handleKeydown` 挂在 `.entry-rail__panel` 上，而
   `.entry-overflow` 是它的**兄弟**节点；菜单打开后焦点自动落在搜索框，
   面板的 keydown 树根本收不到。修法：菜单自己处理
   `@keydown.escape.stop="closeOverflow()"`（`.stop` 防止冒泡到坞根去收起整个坞）。

**空态门控（2026-10 补充）**

原先坞**无条件渲染**（只按 `deviceType` 分桌面/移动两套），因此一个插件 dock
入口都没有时，右侧仍常驻一枚箭头、移动端仍有一个点开是空 sheet 的顶栏按钮。
坞只由插件的 `kind: "dock"` 入口填充（`CORE_ENTRIES` 全是 `kind: "command"`，
`dockSlots()` / `overflowEntries()` 都只取 `dock`），所以「完全没有入口」是
新装主程序的正常状态，不该有这个死控件。

修法：JS 侧加 `get hasEntries() { return slots.length > 0 || overflow.length > 0; }`，
模板侧桌面坞、移动端按钮、底部 sheet 三处都用 `x-show="hasEntries"` 门控。

⚠️ 两个实现细节（都有实测依据）：

- 必须同时看 `slots` **与** `overflow`。社区插件默认不进槽位、只进溢出菜单
  （`isPinned()` 对 `tier === "community"` 返回 false），只看 `slots` 会让
  「只装了社区插件」的用户看不到入口。
- 必须用 `x-show`（切 `display`），**不要**把 `hasEntries` 并进外层
  `x-if="deviceType !== 'mobile'"`。外层 `x-if` 本意是「按设备类型重建子树」，
  并进 `hasEntries` 会让「插件装卸」也触发整树销毁重建。真实 Chromium 对照
  （同一序列：装入 → 清空 → 重装 → 清空，走真实 `plugins:loaded` 路径）：

  | 实现 | pageerror 次数 |
  |---|---|
  | HEAD（无门控） | 6 |
  | `x-if="… && hasEntries"` | 10 |
  | `x-show="hasEntries"` | **6** |

  多出来的报错是 `Cannot read properties of undefined (reading 'length')`
  （Alpine 的 x-for 在宿主 x-if 拆除子树时重入 reconcile）。`x-show` 只切
  `display`，不动 x-for 生命周期，因此与 HEAD 持平。

  > 附带发现：该 pageerror **本身是既有缺陷**，与坞无关 —— 把坞整块 DOM 从页面
  > 删掉后它照样出现（对照实验：`neither` 组仍 1 次）。它来自**别处**同样
  > 结构的 `x-if` + `x-for`（如 `header.html` 的 `pluginBatchEntries` 区块），
  > 触发条件是注册表在运行期变化。这属于独立问题，本次未处理，仅确保**不因本次
  > 改动而增多**。

**第二轮外观修正（2026-10 补充）**

四处调整，全部有真实浏览器实测依据（Playwright + Chromium，真实页面 + 真插件）：

**① 箭头朝向原本是反的。** 旧实现收起态 `rotate(0)`（`chevron-right`，指向**屏幕
边缘**）、展开态 `rotate(180deg)`（指向**内容区**）。用户反馈「展开不是向外而是向内，
收起不是向内而是向外，请调换」。

改为「**朝向 = 点它会去的方向**」：收起态朝内（左，`rotate(180deg)`），展开态朝外
（右，`rotate(0deg)`）。sprite 里只有 `icon-chevron-right`（无 left 变体），左向靠
180° 旋转取得。

实测（`getComputedStyle(svg).transform` 解成角度）：

| 状态 | 旧 | 新 |
|---|---|---|
| 收起 | `matrix(1,0,0,1,0,0)` = 0° 朝右 | `matrix(-1,0,0,-1,0,0)` = **180°** 朝左 |
| 展开 | `matrix(-1,0,0,-1,0,0)` = 180° 朝左 | `matrix(1,0,0,1,0,0)` = **0°** 朝右 |

**② 图标占槽位比例过小。** 实测旧值：槽位 40×40，而内层 `<svg>` 只有 **16×16**
（`buildIcon()` 的 `icon()` 调用带 `ui-icon--sm`，坞自己的 `.entry-rail__icon`
容器是 20px，内层 svg 仍由尺寸类决定），`iconToSlotRatio` = **0.40** —— 按钮四周
一圈空白。用户反馈「图标占比按钮比例很小，感觉上没有必要」。

改为令牌化并配套放大：新增 `--dock-icon-size`，与 `--dock-slot-size` 成比例。

| | 槽位 | 图标 | 占比 |
|---|---|---|---|
| 桌面 | 40 → **44** | 16 → **26** | 0.40 → **0.59** |
| 平板 | 36 → **40** | 16 → **24** | 0.44 → 0.60 |

⚠️ 覆盖规则必须写成 `.entry-rail__icon > svg` / `.entry-rail__icon > .ui-icon`，
**不能**用 `.entry-rail__icon > *`：后者特异度 0,1,0 与 `.ui-icon--sm` 同分，
只能靠源序取胜，改动引入顺序就会静默失效。图标节点有两种形态（`uiPrimitives.js:icon()`
对宿主图标返回 `<svg>`、对插件资源图标返回 `<span class="ui-icon--asset">`），
两条选择器都要写。

**③ 移动端触发器不再独占一行。** 旧实现是 `position: relative` 的普通块级按钮，
而 `.entry-dock-root` 处在 `body` 的 column flex 流里 ⇒ 根节点**独占一整行**。
实测根节点高 32px、把翻页栏整体顶上去（翻页栏 `y=788..848`、按钮 `y=848`），
屏幕底部白多一条。用户反馈「单独占据了一行没有必要了」。

改为贴视口右下角的 `position: fixed` 箭头（36×36px，`bottom/right: 0.25rem`，
层级 `--z-entry-rail`），落到翻页栏那条带子里。

实测对照（420×880 与 360×880 两种视口都测）：

| | 旧 | 新 |
|---|---|---|
| `.entry-dock-root` 高度 | 32px（占一行） | **0** |
| 触发按钮 | `relative`，`y=848` | `fixed`，`y=840..876` |
| 翻页栏 | `y=788..848` | `y=820..880`（贴住真正底边） |
| 箭头中心 `elementFromPoint` | — | `entry-dock-mobile-trigger` |

⚠️ 必须给箭头留出横向空间。实测 420px 视口下翻页控件右边缘**正好** 404px =
栏内容区右边界，一点空位都没有，直接叠上去会盖住「下一页」。因此在 `<body>` 上挂
`entry-dock-mobile-docked` 类，由 `.pagination-bar { padding-right: 2.75rem }` 让位。

- 让位后：控件右边缘 404 → **376**，箭头左边缘 380 ⇒ 不重叠（实测
  `overlapWithControls: false`）。
- **不能**用 CSS `body:has(.entry-dock-mobile-trigger)`：`:has()` 只看元素是否存在于
  DOM，而模板里箭头被 `<template x-if>` 包着，Alpine 克隆后常驻，`x-show="hasEntries"`
  只切 `display` ⇒ 空态下 `:has()` 依然成立，会白留一段空隙。实测空态
  `padding-right` 正确回到 16px、`bodyHasDockedClass: false`。这与「遮挡处理」小节里
  `:has()` 的坑是同一个。

**④ 数量数字标移到箭头上（PC + 移动端）。** 旧实现在移动端按钮上已有徽标，但用
`x-show="slots.length"`；PC 端完全没有。用户要求「放到箭头按钮上，PC 端也是」。

统一改为 `entryCount`（= `entries.length`），PC 挂 `.entry-rail__toggle-count`、
移动端挂 `.entry-dock-mobile-trigger__count`。取值理由：`slots` 只含**已固定**的入口
且受 `MAX_DOCK_SLOTS` / 每插件上限裁剪，社区插件默认不进槽位 —— 只看 `slots` 会让
「只装了社区插件」时徽标凭空消失（实测 `slots=0, overflow=1` 时旧判据为假）。

徽标挂**左上角**：右上角贴着屏幕边缘（PC 箭头 `right: 0`），会被视口裁掉。

实测：PC 收起/展开态徽标均在箭头内（`x=1413, y=427, 16×12`）；移动端徽标
`x=377, y=837` 在箭头（`x=380..416`）左上角外沿，不越界。

⚠️ 这四处契约已由 4 个新测试锁定，并经**变异测试**验证真的会失败（10/10）：
把箭头角度调回旧值、图标缩回 1rem、覆盖选择器退回裸 `> *`、`entryCount` 退回
`slots.length`、触发器退回 `relative`、让位规则退回 `:has()`、删掉任一端徽标 ——
每一项都能让对应测试变红。

> 变异测试顺带抓出一个**假绿**：图标覆盖规则的断言原本写成
> `assert '.entry-rail__icon > svg' in css`，而上面那段解释性注释里逐字写了这两个
> 选择器，于是把真正的规则删掉后断言依然通过。现已改为先剥掉注释再断言。

**槽位内容**

- 主图标（24px）
- 可选徽标（右上角圆点或数字，`api.entries.setBadge`）
- hover tooltip：`title` 带 `label` + `description`（坞内不再有常驻文字）
- 右键/长按上下文菜单：`打开`、`固定/取消固定`、`移到溢出`、`配置`（深链到设置，§7.4）、`隐藏`、`关于此插件`

### 7.2 溢出与命令面板（解决「3 个 → 30 个」）

**溢出菜单**：坞底部的 `⋯` 槽位。点击弹出一个弹层，列出**所有未固定的入口**，按插件分组，带搜索框。这一层是规模化的关键：

| 入口数 | 用户看到 |
|---|---|
| 1–4 | 全部固定，坞里全是图标，溢出为空 |
| 5–10 | 固定常用的 5–6 个，其余在溢出；坞有 `⋯` 角标提示数量 |
| 10+ | 溢出成为主入口，坞只留 3–4 个高频 + `⋯`；推荐用户改用命令面板 |

**命令面板（Ctrl/Cmd+K）**：全仓 grep 确认 `Ctrl+K` / `command-palette` **零占用**，是干净的空位。

- 搜索范围：全部入口（含 `kind: command`）+ 宿主内建命令（切换模式、打开设置分区、打开插件管理、刷新列表、切换主题…）。
- 键盘优先：`↑↓` 选择、`Enter` 执行、`Esc` 关闭。
- 这是**唯一能同时容纳 100 个入口且不占视觉空间**的形态，也是本设计对「生态增长」的核心回答。
- 插件可以只声明 `kind: command` 的入口（不出现在坞里），这是最轻量的集成方式。

**摆法切换**（回应用户「不一定做成捕获悬浮球的形式」）：

| 摆法 | 适用 | 存哪 |
|---|---|---|
| `rail`（默认） | 桌面、入口 3–8 个 | localStorage |
| `overflow-only` | 入口多、想保持界面干净 | localStorage |
| `topbar` | 偏好顶部横向排列（顶栏右侧） | localStorage |
| `palette-only` | 极简：只有快捷键唤出命令面板 | localStorage |

四种摆法渲染的是**同一批注册表条目**，插件无感知。

### 7.3 导航项数据化（修掉 §3.6 的硬编码）

`kind: 'nav'` 的入口进入侧栏模块菜单。做法：

1. **注册表驱动菜单**：把 `templates/components/sidebar.html:80-179` 的 8 个硬编码按钮改为 `<template x-for="entry in navEntries">`，`navEntries` 来自注册表（宿主 8 个内建 + 插件项）。`static/js/components/sidebar.js:18-27` 的 `MODULE_LABELS` 退役，标签从条目读。
2. **切换器图标**：`sidebar.html:44-72` 的 8 个 `x-cloak x-show="currentMode === 'X'"` 分支改为按 `currentEntry.icon` 渲染。
3. **通用插件页容器**：`templates/index.html:22-36` 的 5 个 `x-show` 视图块之外，**新增一个通用宿主容器**：
   ```html
   <div x-show="isPluginMode(currentMode)" x-data="pluginSurfaceHost" class="plugin-page-host"></div>
   ```
   它按 `currentMode` 找到对应入口，调 `api.surfaces.mount` 把插件内容挂进来。**这样加一个插件导航项不再需要改任何模板。**
4. **`switchMode` 的兜底**：`static/js/components/layout.js:221-260` 对未知 mode 会走 `else` 分支派发 `refresh-card-list`——对插件模式无害，但应改为「插件模式不发刷新事件」。同时 `:237-248` 的清过滤条件逻辑对插件模式同样适用（保留）。

### 7.4 配置入口统一（不新增第二套）

现状已经统一：配置在 设置 → 插件管理 → 每个已安装插件的「配置」按钮就地展开（`static/js/components/pluginManager.js:308-327`；模板 `templates/modals/plugin_manager.html:206-266`）。要做三件事：

1. **深链锚点**。扩展 `static/js/components/pluginManager.js:43-47` 的 `ANCHOR_TABS`，新增形如 `plugin-config-<plugin_id>` 的锚点语义：命中时切到 `installed` 页签 + `openConfig(item)` 自动展开 + 滚动到位。
   现状锚点只有三个子页签（`plugin-panel-installed`/`plugin-panel-catalog`/`plugin-panel-upload`），需加第四类。
2. **从入口直达配置**。坞槽位上下文菜单的「配置」→ `api.openSettingsSection('plugins', 'plugin-config-<id>')`（`pluginHost.js:293-301` 已实现 `openSettingsSection`，它置 `store.showSettingsModal = true` 后派发 `open-settings-section`）。**注意**：`plugins` 必须在 `settingsHelpContent` 里，否则 `selectSettingTab` 静默 no-op（`static/js/components/settingsModal.js:304-306`，即设计文档 F8 硬闸门）。**实测已满足**：`settingsHelpContent` 现为**五键**（`static/js/components/settingsModal.js:175-206`），第五键 `plugins` 在 `:200-205`（title「插件管理帮助」、label「插件管理」、kicker「PLUGINS & EXTENSIONS」、description「安装、启停与配置本地插件，管理插件配置与密钥。」）；对应导航按钮 `templates/modals/settings.html:66`（`settings-tab-plugins` / 序号 05 / `<strong>插件管理</strong><small>安装、启停与配置</small>`）。
3. **`kind: 'settings'` 区块**。`config_schema` 表达不了的复杂配置，插件声明一个 settings 入口，宿主在插件管理页内渲染为区块（不是新顶层 tab——避开 F8 闸门与「设置页膨胀」）。

**规则**（写进 `docs/plugin-api.md`）：插件的**用户可调参数**应优先用 `config_schema`（宿主自动生成表单，`static/js/components/pluginManager.js:317`、`:458-459`）；只有在 schema 子集（`docs/2026-09-22-plugin-system-design.md:241`：`type/title/description/default/minimum/maximum/enum/secret/required`）表达不了时，才用 `kind: 'settings'` 区块。**不允许插件自建独立的「设置」模态框。**

### 7.5 上下文菜单项（`kind: 'context'`）

宿主已有右键菜单：`templates/components/context_menu.html`（`:6-9` `:class="isMobile ? 'fixed inset-0 z-context-menu …' : 'fixed z-context-menu'"`，`:style` 定位），由 `show-context-menu` / `hide-context-menu` 事件驱动，层级 `--z-context-menu: 9000`。

- 插件声明 `kind:'context'` 且 `contexts:['cards']` 的入口，会追加到卡片右键菜单（分组在「插件」分隔线之后）。
- 菜单项的 `requires_selection` 与当前选中项数联动（`api.store.viewState.selectedIds`，参照 `data/plugins/stm-ai-assistant/frontend/plugin.js:169-175` 的现有做法）。
- 这是「AI 分析这张卡」这类动作的正确位置——比球和导航项都合适。

### 7.6 作业进度（复用既有通道）

作业面板已经是宿主渲染的（§3.5）。新增：**运行中的作业自动成为一条 `dock` 入口**（图标 + 进度环徽标），点击打开既有作业面板。`api.jobs.open(runId)`（`pluginHost.js:483-534`）与 `open-plugin-job-panel` 事件（`pluginJobPanel.js:61-62`）都不需要改。

---

## 8. 管理层：用户偏好与总览

### 8.1 用户偏好

| 偏好 | 粒度 | 交互 | 存储 |
|---|---|---|---|
| 顺序 | 每入口 | 坞内拖拽重排（MIME `application/x-st-entry`，参照 `static/js/components/tagFilterModal.js:2068-2091`） | ui_data `_entry_layout_v1` |
| 固定 / 未固定 | 每入口 | 拖入坞 = 固定；拖出坞 = 取消固定 | ui_data |
| 隐藏 | 每入口 | 上下文菜单「隐藏」或总览页开关 | ui_data |
| 分组 | 每组 | 把多个入口折叠进一个组（坞里显示为组图标，展开后是子项） | ui_data |
| 摆法 | 全局 | 坞 / 仅溢出 / 顶栏 / 仅命令面板 | localStorage |
| 坞展开态 | 全局 | 是否 pinned 常驻 | localStorage |
| 快捷键 | 每入口 | 总览页录制；冲突检测 | ui_data |
| 顺序策略 | 全局 | 手动排序 / 按插件 / 按使用频率（宿主记录点击次数） | ui_data |

**为什么顺序/可见性走 ui_data 而不是 localStorage**：这些偏好必须与插件生命周期对齐——插件卸载后条目消失，偏好应可被清理；ui_data 有备份与原子写（`core/data/ui_store.py:1900 save_ui_data`、`:1967 update_ui_data`），且卸载流程已经在动 ui_data（`core/plugins/installer.py:491 _clear_ui_namespace`）。**扩展点**：`_clear_ui_namespace` 同时从 `_entry_layout_v1` 中剪除该插件的条目键。

### 8.2 入口总览（治理视图）

位置：设置 → 插件管理 → 新增第四个页签「入口」（或作为「已安装」页签顶部的一个折叠区）。

内容表格：

| 列 | 说明 |
|---|---|
| 图标 + 名称 | 入口 `label` |
| 归属 | 插件名（`<plugin_id>`） |
| 类型 | dock / nav / settings / context / command |
| 出现位置 | 哪些 mode（`contexts`） |
| 当前呈现 | 坞槽位 N / 溢出 / 隐藏 |
| 快捷键 | 可编辑 |
| 操作 | 固定/取消固定、隐藏、重置位置 |

**这直接兑现用户要的「便于管理，也便于整理」**：坞是紧凑视图，总览是完整视图。20 个入口时用户在总览里排布，坞只呈现排布结果。

**安装期披露**：`docs/2026-09-22-plugin-system-design.md:1638`（S8）已有「安装前展示权限清单，用户显式确认」。扩展为「此插件将添加 **N** 个入口」，并列出 label——让用户在安装前就知道界面会被加什么。

### 8.3 发现性（避免「装了插件找不到入口」）

| 场景 | 处理 |
|---|---|
| 插件刚安装/刚启用 | 坞对应槽位播放一次「新」脉冲（`prefers-reduced-motion` 下改为静态角标）；顶栏 toast 提示「AI 助手 已添加 2 个入口」并带「查看」按钮 |
| 入口被用户隐藏 | 总览页显示「已隐藏」计数徽标，避免「消失了」的困惑 |
| 插件加载失败 | 坞不渲染其入口；总览页在插件行显示 `load_error`（`core/plugins/routes.py:118-119` 已下发 `load_error`） |

---

## 9. 存储与清理

| 数据 | 位置 | 生命周期 |
|---|---|---|
| 入口声明 | `manifest.json`（`frontend.entries`） | 随插件目录，卸载即消失 |
| 运行时入口 | 前端内存注册表 | 页面会话；`plugins:loaded` 后重建 |
| 用户布局偏好 | ui_data `_entry_layout_v1` | 持久；卸载时剪除该插件条目键 |
| 坞 UI 态 | localStorage `st_manager_entry_dock_prefs` | 持久；纯前端 |
| 使用频率计数 | ui_data `_entry_layout_v1.usage` | 持久；用于「按使用频率」排序 |

**清理链**：`core/plugins/installer.py:437 uninstall_plugin` → `:491 _clear_ui_namespace(plugin_id)` 现在清 `ui_data._plugins_v1.<id>`；**需扩展**为同时调用一个新的 `prune_entry_layout(plugin_id)`。若走「禁用」而非卸载（`core/plugins/routes.py:213-231`），条目应随 `enabled=false` 从坞消失（前端只渲染 enabled 的插件的条目，`pluginHost.js:112-145` 已有该过滤语义），偏好**保留**（重新启用后恢复原位）。

---

## 10. 主程序改动点清单（文件级）

> 与 `docs/2026-09-22-plugin-system-design.md` 附录 B 同风格。**本文不实现，仅列清单。**

### 后端

| 文件 | 改动 |
|---|---|
| `core/plugins/manifest.py` | `PluginManifest` 增 `frontend_entries: list`（`manifest.py:277-279` 附近）；解析 + 校验（§6.1 表）在 `manifest.py:486-494` 附近；`to_dict()` 增 `entries` 键（`manifest.py:326-327` 附近）；`panels`/`settings_tab` 保留为别名并归一化 |
| `core/plugins/entries.py` | **新增**：服务端侧的入口归一化与全局键生成（`<plugin_id>:<entry_id>`）、上下文校验、条数上限；供 manifest 与运行时共用 |
| `core/plugins/routes.py` | `/api/plugins/list`（`:110-127`）的 `state.detail()` 里带 `entries`；新增 `GET /api/plugins/entries`（全量入口视图，含宿主内建项）；新增 `POST /api/plugins/entries/layout`（保存布局偏好，走 `update_ui_data`） |
| `core/plugins/installer.py` | `_clear_ui_namespace`（`:491`）扩展为同时剪除 `_entry_layout_v1` 中该插件的键 |
| `core/data/ui_store.py` | 新增命名空间常量 `ENTRY_LAYOUT_KEY = '_entry_layout_v1'`（`ui_store.py:71-82` 处，风格一致） |
| `core/plugins/api.py` | 无需改（前端 API 在 `pluginHost.js`）；可选：后端暴露 `api.entries` 供服务端渲染场景 |

### 前端

| 文件 | 改动 |
|---|---|
| `static/js/pluginHost.js` | `buildApi()`（`:180` 起）新增 `entries`（`:304-315` 附近）与 `surfaces` 分组；`registerModal`/`registerSettingsSection`（`:317-327`）改为映射到 entries；`loadPlugin`（`:147-178`）读取 `manifest.entries` 并注册；**记录 `activate()` 返回值并作为插件级 disposer**；`destroy`（`:567-583`）补上 surface 卸载（并新增调用方） |
| `static/js/entryRegistry.js` | **新增**：前端注册表（条目增删改查、按 mode 过滤、排序、持久化协调、`plugins:loaded` 重建） |
| `static/js/components/entryDock.js` | **新增**：坞组件（收起/展开/pinned、槽位渲染、拖拽重排、溢出弹层、键盘导航、移动端退化） |
| `static/js/components/entryOverview.js` | **新增**：入口总览（设置页内的治理表格） |
| `static/js/components/commandPalette.js` | **新增**：命令面板（Ctrl/Cmd+K） |
| `static/js/components/pluginSurfaceHost.js` | **新增**：通用插件页容器（§7.3 第 3 点），供 `kind:'nav'` 使用 |
| `static/js/app.js` | `registerComponents()`（`:50-89`）注册上述 5 个 Alpine 组件 |
| `static/js/components/sidebar.js` | `MODULE_LABELS`（`:18-27`）退役，改为从注册表读；`currentModeLabel`（`:192-194`）同上；`handleModuleMenuKeydown`（`:214-235`）适配动态条目数 |
| `static/js/components/layout.js` | `switchMode`（`:221-260`）识别插件模式（不发 `refresh-card-list`）；新增 `isPluginMode(mode)` |
| `static/js/components/pluginManager.js` | `ANCHOR_TABS`（`:43-47`）扩展 `plugin-config-<id>` 语义；`openConfig`（`:308`）支持从锚点直达；新增「入口」子页签 |
| `static/js/components/contextMenu.js` | 渲染 `kind:'context'` 条目（分组 + 分隔线） |
| `static/js/state.js` | 新增坞/面板的 store 状态；localStorage 键常量 `ENTRY_DOCK_PREFS_KEY`（风格参照 `:70`） |

### 模板与样式

| 文件 | 改动 |
|---|---|
| `templates/index.html` | 新增坞容器 include + 通用插件页容器（`:22-36` 区域）；模态区（`:40-73`）加 surface 宿主 |
| `templates/components/sidebar.html` | `:80-179` 的 8 个硬编码按钮改 `x-for`；`:44-72` 切换器图标改动态 |
| `templates/components/entry_dock.html` | **新增** |
| `templates/components/plugin_surface_host.html` | **新增** |
| `templates/modals/plugin_manager.html` | 新增「入口」子页签与总览表格 |
| `static/css/modules/entry-dock.css` | **新增**（坞、槽位、溢出弹层、命令面板） |
| `static/css/modules/variables.css` | 新增 `--z-entry-rail: 80`（`:17-35` 处）及配套 `.z-entry-rail` 工具类（`:38-108` 风格）；**同时**把 `view-beautify.css:494`（`70`）、`view-beautify.css:814`（`40`）、`modal-detail.css:3492`（`46`）、`:3507`（`44`）等散落字面量归一到令牌 |
| `static/js/components/entryDock.js` 对应的 CSS 引入点 | 在 `static/css/modules/layout.css` 之后引入，保证令牌可用 |

### 文档与脚手架

| 文件 | 改动 |
|---|---|
| `docs/plugin-api.md` | 新增 `entries.*` / `surfaces.*` / `ui.*` 章节；`registerModal`/`registerSettingsSection` 标为 deprecated 别名 |
| `docs/2026-09-22-plugin-system-design.md` | 第 8.3/8.4 节补入口契约；第 9 节补入口总览；F11/F12 后追加 F13（不得自绘浮层）、F14（surface 容器归宿主） |
| `tools/new_plugin.py` | 脚手架生成带 `entries` 示例的 manifest |
| `data/plugins/stm-ai-assistant/` | **参考实现**：退役自绘 launcher（`frontend/plugin.js:33-62`、`:106-164`），改为声明 `dock` 入口 + `panel` surface；删除 `plugin.css:15-36`、`:72-87`、`:146-149` 中不再需要的部分 |
| `samples/plugins/hello-world/` | 加一个 `command` 入口示例（最小集成形态） |

### 测试

新增（沿用既有契约测试传统，§3.10）：`tests/test_plugin_entries_contracts.py`、`tests/test_entry_layout_store.py`、`tests/test_plugin_surface_contracts.py`；扩展 `tests/test_plugin_manifest.py`、`tests/test_plugin_host_contracts.py`、`tests/test_plugin_manager_contracts.py`。

---

## 11. 分期路线

| 阶段 | 范围 | 验收 |
|---|---|---|
| **阶段 A：契约 + 坞**（核心） | manifest `entries` + 别名归一化；`api.entries`；`api.surfaces`（仅 `panel`/`modal`）；入口注册表；坞（固定/重排/拖出/溢出）；`--z-entry-rail` 令牌；`stm-ai-assistant` 迁移为参考实现 | 该插件不再自绘球；坞里出现它的入口；点开是宿主提供的抽屉；拖出/拖入/重排可用并持久化；禁用插件后入口立即消失 |
| **阶段 B：治理 + 发现** | 入口总览（设置内子页签）；安装期「将添加 N 个入口」披露；深链 `plugin-config-<id>`；新入口脉冲提示 | 用户能在总览里看到全部入口与归属，能隐藏/重排，能从坞直达配置 |
| **阶段 C：规模化** | 命令面板（Ctrl/Cmd+K）；`kind:'command'`；宿主内建命令纳入；摆法切换（rail/overflow/topbar/palette） | 声明 12 个入口的测试插件下界面仍整洁；键盘可完成全部操作 |
| **阶段 D：导航数据化** | `kind:'nav'`；侧栏菜单改注册表驱动；通用插件页容器；`MODULE_LABELS` 退役 | 新增一个插件导航项**不需要改任何模板**；移动端切换器自动包含它 |
| **阶段 E：深度整合** | `kind:'context'`（右键菜单）；`kind:'settings'` 区块；作业自动入口；每入口快捷键 + 冲突检测；使用频率排序 | 卡片右键出现插件的「AI 分析」；快捷键可自定义 |
| **阶段 F（可选）：兼容垫片** | 对尚未迁移的第三方插件球做**受限捕获**（仅识别无自绘拖拽的固定定位小元素），收进坞并提示作者迁移 | 明确标注为临时措施，默认关闭 |

**建议**：A + B 是「解决问题」的最小集；C 是「生态可持续」的关键；D 是「修掉既有硬编码」的额外收益，可以后做。

---

## 12. 风险与对策

| # | 风险 | 对策 |
|---|---|---|
| 1 | 坞遮挡右侧内容（滚动条、卡片边缘操作） | 坞收起态仅 8px 热区且不拦截点击；展开态是 overlay 不挤压 `.content-area`；任何模态/抽屉打开时自动收起 |
| 2 | 层级冲突（美化包抽屉字面量 `70`、坞 `80`） | **同时**把散落 z-index 字面量归一到令牌（§10 表），并把坞定在 `--z-card-selected`(50) 与 `--z-floating`(100) 之间；写入文档：插件不得硬编码 z-index |
| 3 | Chromium identity `backdrop-filter` 黑块缺陷 | 坞**不使用** `backdrop-filter`；沿用插件已经发现的规避思路（`data/plugins/stm-ai-assistant/frontend/plugin.css:89-145`） |
| 4 | 插件停用后坞残留（无 `PluginHost.destroy` 调用方） | 坞**只从插件列表渲染**（`pluginHost.js:112-145` 的 enabled 过滤），宿主自持 DOM，不依赖插件清理代码。这反而是坞的架构优势 |
| 5 | 旧插件球与新坞并存 | 兼容不破坏；提供迁移指南 + 参考实现；阶段 F 的受限捕获作为过渡 |
| 6 | 入口爆炸（一个插件声明 16 个） | manifest 上限 16 项（§6.1 校验表）；溢出 + 命令面板吸收；总览页可批量隐藏 |
| 7 | 坞抢焦点 / 打断框选 | 根元素 `data-marquee-ignore`；键盘导航只在坞内 roving tabindex |
| 8 | 移动端无 hover | `deviceType === 'mobile'` 时坞不渲染为侧条，改为顶栏按钮 + 底部 sheet（§7.1） |
| 9 | 深链配置打不开（`settingsHelpContent` 硬闸门） | `plugins` 键已存在（`static/js/components/settingsModal.js:200-205` 第五键 + `templates/modals/settings.html:66` 第 05 项）；新增锚点语义时同步补测试，防止回归（F8） |
| 10 | 契约膨胀 | 新增 API 全部标 Provisional 且向后兼容，**不升 `api_version`**；稳定性分级遵循 `docs/2026-09-22-plugin-system-design.md:1268` |
| 11 | 与 `x-teleport` / 现有模态体系冲突 | 坞与 surface 宿主不用 teleport（现有 teleport 只用于 `body`：`templates/components/chat_manager.html:5-9`、`modals/automation.html:583/594/606`、`modals/detail_card.html:4174`），直接挂在 `templates/index.html` 的固定位置 |
| 12 | 宿主自己也是「插件」，排序时被用户隐藏 | 宿主内建入口（`core:` 前缀）在总览页标为「系统」，默认不可隐藏（但可移入溢出） |

---

## 13. 测试策略

| 测试 | 内容 |
|---|---|
| `tests/test_plugin_manifest.py`（扩展） | `entries` 解析与校验：非法 `kind`/缺 `id`/图标越界/超 16 项 → 忽略 + warning；`panels`/`settings_tab` 别名归一化正确；**不填 entries 的旧 manifest 行为不变**（回归保护） |
| `tests/test_plugin_entries_contracts.py`（新增） | 全局键格式 `<plugin_id>:<entry_id>`；宿主键 `core:`；同插件重复 id 拒绝；跨插件同 id 不冲突 |
| `tests/test_plugin_surface_contracts.py`（新增） | `surfaces.register/open/close`；`mount` 返回函数在关闭时被调用；插件停用时宿主强制卸载；`container` 带 `data-plugin` 与 `data-marquee-ignore` |
| `tests/test_entry_layout_store.py`（新增） | 布局偏好写入 ui_data `_entry_layout_v1`；`update_ui_data` 原子性；卸载时剪除该插件键；重新启用后偏好保留 |
| `tests/test_plugin_host_contracts.py`（扩展） | `activate()` 返回值被记录为 disposer；`api.entries.*` 存在性与签名；`registerModal`/`registerSettingsSection` 仍可用（兼容） |
| `tests/test_plugin_manager_contracts.py`（扩展） | `plugin-config-<id>` 锚点直达并自动展开配置 |
| 前端契约测试（新风格，参照 `tests/test_settings_frontend_contracts.py`） | 坞渲染条目数 = 注册表中 `kind:'dock'` 且 enabled 的条目数；隐藏的条目不渲染；溢出角标数正确；命令面板可搜索到全部条目 |
| 回归 | `tests/test_plugin_css_scope.py` 保持通过（坞样式属于宿主，不在 F11 管辖范围）；`tests/test_color_system_contracts.py` 保持通过（坞只用 `.color-*`） |

---

## 14. 反目标（明确不做）

1. **不做 DOM 捕获/劫持**（除阶段 F 的可选受限垫片）。理由见 §4.2。
2. **不让坞变成第二套导航**。坞是入口，导航是导航；`kind:'nav'` 的入口进侧栏菜单，不进坞。
3. **不新增设置顶层 tab**。入口总览挂在既有「插件管理」页内（避开 `settingsHelpContent` 硬闸门，`static/js/components/settingsModal.js:304-306`）。
4. **不引入新框架 / 打包器 / 依赖**。全部用 Alpine + 原生 DOM + 既有 CSS 令牌（`docs/DEVELOPMENT.md:9-10` 无打包器约束）。
5. **不做插件沙箱**。D7 已定：插件按本地可信代码对待（`docs/2026-09-22-plugin-system-design.md:44`）。
6. **不强制迁移**。旧的自绘球继续工作；迁移是推荐而非强制。
7. **不为每个插件写模板**。通用插件页容器（§7.3）就是为此。
8. **不改 `api_version`**。纯增量契约（§6.4）。

---

## 15. 未决问题

| # | 问题 | 待定因素 |
|---|---|---|
| 1 | 坞的默认宽度 56px 是否够（插件 label 是中文，tooltip 才显示全名） | 需要在真实插件数量下做一次可用性验证 |
| 2 | 坞与聊天阅读器（`--z-chat-reader: 3200`，全屏三栏）的关系 | 阅读器是全屏 overlay，坞会被盖住——是否应在阅读器内也提供入口？倾向：不提供，阅读器内用 `kind:'context'` 入口 |
| 3 | 是否允许插件声明 `kind:'dock'` 且 `surface.type:'page'` | 语义上可行（坞槽位 = 快捷方式，打开整页），但会与 `kind:'nav'` 重复；倾向：允许，坞是「快捷方式」而 nav 是「常驻导航」 |
| 4 | 使用频率统计的隐私/性能 | 纯本地计数，无外发；是否需要在设置里提供「清除统计」 |
| 5 | 阶段 F 的受限捕获是否值得做 | 取决于第三方插件数量；当前只有 1 个真实插件且是一方的，倾向**不做**，直接迁移 |
| 6 | 坞的拖拽用 HTML5 DnD 还是 Pointer Events | HTML5 DnD 有既有先例（`tagFilterModal.js:2068-2091`），但坞是 fixed 覆盖层，DnD 的 drag image 与 z-index 需要验证；Pointer 方案更可控（`marqueeSelection.js:333`、`detailModal.js:972` 有先例）。**倾向 Pointer Events** |
| 7 | 命令面板的宿主内建命令清单 | 需要与现有 60+ 个 CustomEvent（§3.9）对齐，避免重复实现 |

---

## 附录 A · 与既有设计文档的接口

| 本文 | 既有文档 |
|---|---|
| §6.1 `frontend.entries` | `docs/2026-09-22-plugin-system-design.md:184-192`（`frontend` 段原样例）、`:226-237`（校验规则表） |
| §6.2 `api.entries` / `api.surfaces` | `docs/plugin-api.md:114-137`（前端 API 稳定性表）、`docs/2026-09-22-plugin-system-design.md:1368-1421`（10.3 前端 PluginAPI 契约） |
| §6.4 兼容 | `:44-47`（D7/D9/D10）、`:1593`（N1 插件间通信） |
| §7.1 层级 | `static/css/modules/variables.css:17-35`（令牌表） |
| §7.4 配置入口 | `:1250-1254`（9.3 入口）、`:1162`（F8 硬闸门） |
| §8.2 安装期披露 | `:1638`（S8 安装前展示权限清单） |
| §12 风险 | `:1604-1625`（R1-R18）、`:1652`（12.4 前端） |

## 附录 B · 一句话回答原始四问

- **Q1（怎么治本）**：把入口从「插件自绘的 DOM」变成「插件声明的数据 + 宿主渲染的容器」。
- **Q2（右侧隐藏条可行吗）**：可行且推荐，右侧是壳层唯一空闲边缘；但它是**默认摆法**，不是架构。拖拽固定/换位/拖出映射为 `pinned` + `order` 两个字段。
- **Q3（插件还是主程序）**：主程序。插件做不到「列举并移除别的插件的入口」，且 F11 的 CSS 作用域使它无法为壳层写样式。
- **Q4（生态形态）**：注册表 + 三种呈现（坞 / 溢出 / 命令面板）+ 一个治理总览。坞管「常用的少数」，溢出与命令面板管「长尾的多数」，总览管「用户的意志」。
