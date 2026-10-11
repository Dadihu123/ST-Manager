# 宠物插件能力缺口分析（主程序适配清单）

> 日期：2026-10-11
> 范围：分析现有插件系统能否支撑「官方宠物插件」，以及主程序需要补的契约与实现。
> 前置阅读：`docs/2026-09-22-plugin-system-design.md`（第 8 / 10 部分）、
> `docs/2026-10-10-plugin-entry-unification-design.md`（§4.2、§6.1、§7.1）
> 引用格式 `文件:行号`。**未标 [推断] 的结论均有代码或实测证据。**
>
> **状态：已排期。** 本文件列出的宿主侧缺口已由
> `docs/2026-10-11-host-ambient-layer-prompt.md` 立项实施（阶段 0–5），
> 落地进展与偏差记录集中在 **§9「实施进展」**。
> 本文件中「宠物插件本体」等插件侧内容**不在**该实施范围内。

---

## 0. 结论摘要

**现有插件系统不足以支撑宠物插件，且缺口是结构性的。**

技术上，插件 JS 可以自由 `document.body.appendChild()` 一个 `position: fixed` 的元素，
所以「能写出来」。但这等于让宠物插件**重走悬浮球的老路**——而那正是过去两份设计文档
花大力气消灭的模式：

| 宿主已有的承诺 | 宠物需要的 | 冲突 |
|---|---|---|
| 四种 surface 全部是「用户打开、可关闭的对话框」 | 常驻、非模态、无焦点、与壳层同生命周期 | **语义相反** |
| `F13`：插件不得自绘 `position: fixed` 浮层（安装期扫描 warning + UI 标记） | 宠物**必须**是固定定位浮层 | **正面冲突** |
| `api.createRoot()` 的容器在文档流内（`.plugin-host-root{position:relative}`） | 宠物不能占布局、不能推挤内容区 | **容器不可用** |
| z-index 令牌沿 50 → 60 → 70 → 80 一路排满（卡片选中 / surface / 美化抽屉 / 入口坞） | 宠物要一个「高于卡片、低于一切宿主浮层」的档位 | **无档位**（50 与 60 之间是唯一空档） |
| 后端核心事件（`card.updated` 等）**没有前端投递通路** | 「提示播报」需要知道宿主发生了什么 | **通路缺失** |
| 插件更新用 `os.replace` 原子替换整个目录，`data/` 不保留 | 用户自定义形象必须活过插件更新 | **会丢数据** |

核心判断：**主程序需要一个「环境层（ambient layer）」契约**，与现有四种 surface 并列但语义相反。
宠物、桌面挂件、常驻状态徽标都吃这一层，不是给宠物开的特例。

另外，**契约版本不需要升**（沿用 entry-unification §6.4 的裁定：
纯增量、可选的能力不构成不兼容变更）。

---

## 1. 需求拆解

把需求逐条映射到「需要宿主提供什么」：

| # | 需求 | 归谁 | 需要宿主提供的东西 |
|---|---|---|---|
| R1 | 与界面联动 | 宿主 + 插件 | 宿主状态广播（当前视图、是否开着模态、是否忙） |
| R2 | 鼠标/触屏交互（拖拽） | 插件 | ① 一个接收指针事件的常驻容器；② 不被框选/宿主拖拽抢事件 |
| R3 | 下坠（物理） | 插件 | ① 每帧驱动（rAF 自己来）；② **可用活动区域的量测**（视口底边在哪） |
| R4 | 行走 | 插件 | 同 R3 |
| R5 | 静息动画 | 插件 | 图片刷新式动画的执行环境（`background-position` 换帧） |
| R6 | 提示播报 | 宿主 + 插件 | **核心事件的前端投递通路**（当前缺失）；toast 已有 |
| R7 | 性能（图片刷新） | 宿主 + 插件 | **插件资产的缓存/条件请求**（当前每次全量重传） |
| R8 | 用户自定义形象 | 插件 | ① 用户图片的存取位置（`data_dir()` 已有，但更新会丢）；② 图片上传通道 |
| R9 | 必要/非必要动作 + 默认回退 | 插件 | 宿主不参与（插件侧 schema + fallback 链） |

R2/R3/R4/R5 全部落在同一个东西上：**一个受宿主管辖、常驻、非模态、不抢焦点的图层容器**。
这就是下面 P0-1 要还的债。

---

## 2. 现状盘点：够 / 勉强 / 不够

### 2.1 已经够用的部分（不用改）

| 能力 | 证据 | 对宠物的价值 |
|---|---|---|
| 前端生命周期与 disposer | `static/js/pluginHost.js:233-242`（`activate()` 返回值记为 disposer）、`:861-900`（`destroy` 真实调用方） | 宠物必须可靠停掉 rAF / 定时器 / 全局监听；**这一条已经做对了** |
| 强制回收 | `static/js/pluginSurfaceHost.js:368-390`（`unregisterPlugin` / `closePlugin`）；`pluginHost.js:158-161` 监听 `plugin:unloaded` | 禁用插件时宿主强制卸载，不依赖插件自觉 |
| 框选天然安全 | `static/js/utils/marqueeSelection.js:175-180`：`isStartTarget` 里 `!root.contains(target)` 直接返回 false | 宠物不在卡片网格内，**框选本来就不会命中它**，无需额外适配 |
| 文案/提示 | `pluginHost.js:362-368`（`toast`）、`:400-402`（`host.*`） | R6 的「发声」部分已有 |
| 主题令牌 | `static/css/modules/variables.css`、`docs/color-system-audit.md` | 宠物容器继承主题，不改一行颜色 |
| 用户私有存储 | `api.storage.*`（`ui_data._plugins_v1.<id>.storage`） | 存位置、缩放、当前宠物 id 足够 |
| 插件私有目录 | `core/plugins/api.py:396-403` `data_dir()` | 存用户自定义形象文件的**正确位置**（前置条件是 P0-3） |
| 生成式文档与图标契约 | `tools/gen_plugin_api_docs.py`、`api.ui.icon()`、`GET /api/plugins/ui-icons` | 新 API 登记流程已经成熟 |

### 2.2 勉强能用、但有代价的部分

| 能力 | 现状 | 代价 |
|---|---|---|
| 事件名匹配 | `api.on()` **不校验**事件名（`pluginHost.js:318-324` 只做 `addEventListener`） | 插件可以听 `card-updated` / `refresh-card-list` / `entry:activate` / `theme-mode-changed` 等宿主实际派发的 window 事件——但**这些名字一个都不在文档里**，属于隐性耦合，宿主改名插件就静默失效 |
| 宿主状态读取 | `api.store`（Alpine `global` store，`pluginHost.js:309-315`） | 能读到 `currentMode` / `isDarkMode` / `deviceType` / `isLoading`，但这是 **Provisional 耦合**，进入的是宿主内部状态树 |
| 指针自监听 | 插件自己 `window.addEventListener('pointermove')` | 宿主的 `marqueeSelection`、卡片拖拽、坞拖拽都在同一批事件上；entry-unification §4.2 已记录过「宿主再叠一层拖拽，两者会争夺同一批指针事件」（`docs/2026-10-10-plugin-entry-unification-design.md:219`） |
| `prefers-reduced-motion` | CSS 侧宿主各模块自己写（`plugin-surfaces.css:272-277` 等 20+ 处） | JS 侧**没有**统一信号；`hostFeatures()`（`entryRegistry.js:143-153`）只产出 `hasNetwork` / `hasSSE` / `hasFetch`，无法用于能力门控 |
| `config_schema` | `core/plugins/manifest.py:83`：`{string, integer, number, boolean, enum}` | 表达不了 `{idle:'a.png', walk:[...]}` 这类映射；`set_config` 又只接受 schema 声明过的键（`api.py:156-159`） |
| 全屏遮罩记账 | `static/js/utils/dom.js:513-528`，`isFullscreenScrimActive()` 存在但**未导出给插件** | 插件无法知道「宿主现在是否盖着全屏遮罩」 |

### 2.3 不够用，必须补的部分（详见第 3 节）

| # | 缺口 | 一句话 |
|---|---|---|
| G1 | **没有环境层容器** | 四种 surface 全是「对话框」，宠物没有合法容器 |
| G2 | **没有环境层 z-index 档位** | 令牌表 55–500 空白且无语义 |
| G3 | **插件 `data/` 在更新时丢失** | 用户自定义形象会被 `os.replace` 抹掉 |
| G4 | **后端核心事件无前端通路** | `api.on('card.updated')` 在浏览器里永远收不到 |
| G5 | **插件资产无缓存/条件请求** | 实测每次帧图都是完整重传 |
| G6 | **无宿主状态广播** | 宠物做反应要靠猜 DOM |
| G7 | **`settings` 入口 kind 无渲染消费者** | 形象管理面板无处安放 |
| G8 | **无文件投递契约** | 「拖图进窗口」做不了 |

---

## 3. 缺口清单与宿主改动点

### P0 — 不做就无法合规实现

#### P0-1 · 新增「环境层」surface（G1 / G2）

**问题**

```
static/js/pluginSurfaceHost.js:23   SURFACE_TYPES = ["panel", "modal", "page", "sheet"]
core/plugins/entries.py:29          SURFACE_TYPES = frozenset({'panel','modal','page','sheet'})
```

四种全部走同一条挂载路径，且**全部**被打上对话框语义：

| 行为 | 代码位置 | 对宠物是致命的 |
|---|---|---|
| `role="dialog"` + `aria-modal="true"` | `pluginSurfaceHost.js:179-180` | 常驻元素不该是对话框 |
| 焦点陷阱 | `pluginSurfaceHost.js:301` → `_trapFocus` | 宠物会**抢走焦点**，用户按 Tab 就掉进宠物里 |
| ESC 关闭 | `pluginSurfaceHost.js:80-85` | 按 ESC 关模态会**顺手把宠物删掉** |
| 全屏遮罩记账 | `pluginSurfaceHost.js:256` | 非 `page` 类型一律 `setFullscreenScrim(true)`，宠物会让宿主关掉页面壳的 `backdrop-filter` |
| 头部 + 关闭按钮 | `pluginSurfaceHost.js:183-245` | 宠物不该有标题栏 |
| `createRoot()` 容器在流内 | `pluginHost.js:821-827` + `modal-plugin-manager.css:849-855` | `.plugin-host-root{position:relative}` 无 z-index、无 inset；`body` 是 `display:flex; flex-direction:column; height:100dvh; overflow:hidden`（`base.css:37-44`），所以插件根节点是 body 的**流内 flex 子项** —— 往里画宠物会**挤压 `.main-container`** |

**建议设计：`surface.type = 'ambient'`（常驻型）**

```js
api.surfaces.register('pet', {
  type: 'ambient',
  mount(container) {
    // container: 宿主提供的 fixed 全屏层（pointer-events: none）
    // 插件在里面放自己的宠物 DOM，交互元素自行 pointer-events: auto
    return () => { /* disposer */ };
  },
});
```

宿主承诺（与现有四种 type 的差异）：

| 项 | panel/modal/page/sheet | **ambient** |
|---|---|---|
| 触发 | `surfaces.open()` / 入口点击 | **注册即挂载**，无 open/close |
| 容器 | 带定位的 shell + header + body | `position:fixed; inset:0; pointer-events:none` 全屏透明层 |
| 层级 | `--z-surface` / `--z-modal-popover` | **`--z-ambient`**（新增令牌） |
| 对话语义 | `role="dialog"` + `aria-modal` | **无** |
| 焦点 | 焦点陷阱 + 恢复焦点 | **不碰焦点** |
| ESC | 关闭 | **忽略** |
| 遮罩记账 | `setFullscreenScrim(true)` | **不参与** |
| 框选 | `data-marquee-ignore` | `data-marquee-ignore`（同） |
| 回收 | 关闭时 unmount | **插件 disable/unload/destroy 时强制 unmount**（复用 `closePlugin` / `unregisterPlugin`） |

**层级取值**：`--z-ambient: 55`，插在 `--z-card-selected: 50` 与 `--z-surface: 60` 之间
（`variables.css:21` 与 `:32`；这中间是令牌表里唯一的空档——60/70/80 已被 surface、
美化抽屉、入口坞占满）。
理由：宠物应盖住内容卡片与其选中态，但**必须低于**抽屉（60）、坞（80）、下拉（500）、
模态（1000+）——宿主的功能性 UI 绝不能被宠物遮挡。

**全屏遮罩打开时的降级**：宿主在 `body.has-fullscreen-scrim` 或任何 surface 打开时给
ambient 容器加一个状态类（如 `is-host-occluded`），宠物据此暂停动画/降低刷新率。
这样「打开详情页时宠物别乱动」由**宿主统一触发**，插件不用各自监听。

**改动点**

| 文件 | 改动 |
|---|---|
| `static/js/pluginSurfaceHost.js` | `SURFACE_TYPES` 加 `ambient`；`SURFACE_CLASSES` 加 `.plugin-surface--ambient`；`register()` 时若 `type==='ambient'` 立即挂载（无 header/close/scrim/focus-trap/ESC） |
| `static/js/entryRegistry.js` | `SURFACE_TYPES` 加 `ambient`（运行期注册路径 `register()` 会校验） |
| `static/css/modules/plugin-surfaces.css` | `.plugin-surface--ambient` 规则 |
| `static/css/modules/variables.css` | `--z-ambient: 55` |
| `core/plugins/entries.py` | **可不改**——ambient 是运行期注册、不进 manifest `entries[]`（它没有用户可见入口）。若希望 manifest 声明式，再同步加 |
| `tools/gen_plugin_api_docs.py` | 登记 `surfaces.*` 说明中的 ambient 能力 |
| `docs/2026-09-22-plugin-system-design.md` | 第 8 部分补 ambient 契约（F16） |
| `tests/` | 新增 `tests/test_plugin_ambient_surface.py`；更新 `test_plugin_host_contracts.py` |

#### P0-2 · 修复插件核心事件的前端投递（G4）

**问题（实测）**

- 后端定义并派发：`core/plugins/hooks.py:23-35` 的 `CORE_EVENTS`，由
  `core/api/v1/cards.py:2181`（`card.updated`）、`:2294`（`card.moved`）、`:2551`（`card.deleted`）、
  `:4585`（`tag.deleted`）、`:4710`（`tag.applied`）、`:5823`（`card.created`）、
  `core/api/v1/world_info.py:2331`、`core/services/scan_service.py:724`、`core/services/index_job_worker.py:132` 触发。
- 前端 `pluginHost.js:318-324` 的 `on()` **只做 `window.addEventListener`**。
- 全仓 `grep 'app\.ready|card\.created|scan\.completed|worldbook\.saved' static/js`
  → **只命中 `pluginHost.js:32-43` 的 `CORE_EVENTS` 白名单本身**，零个 dispatch。
- 前端实际派发的是另一套名字：`card-updated`（`detailModal.js:2667` 等）、
  `refresh-card-list`、`card-imported`、`entry:activate`……**与后端点分名完全对不上**。

结论：`api.on('card.created', h)` 在浏览器里**永远不会被调用**。宠物要做「提示播报」
（新卡来了、扫描完成、世界书保存），拿不到任何后端信号。

**建议方案：新增插件事件流 `GET /api/plugins/events`（SSE）**

- 复用 `core/plugins/jobs.py:756-838` 已验证的 SSE 基础设施：
  `Response(generator, mimetype='text/event-stream')`、`:` heartbeat 帧、
  连接配额与降级。前端复用 `pluginHost.js:679-727` 的 `EventSource` + 轮询降级模式。
- 后端 `hooks.emit()` 时把 **CORE_EVENTS**（不含插件的自定义事件，避免插件间流量放大）
  广播给已订阅的连接。插件按 `api.on(event)` 的注册表在前端过滤。
- 顺带把前端已有的 window 事件**升级为正式契约**（至少是 Provisional）：
  `card-updated` / `card-imported` / `refresh-*` / `entry:activate` / `theme-mode-changed` /
  `settings-saved`。这些已经在派发，只是没写进文档。

**改动点**：`core/plugins/hooks.py`（增加订阅者注册表或事件环形缓冲）、
`core/plugins/routes.py`（新端点 + 连接配额）、`static/js/pluginHost.js`（`on()` 对
`CORE_EVENTS` 自动挂 SSE，其余走 window）、`docs/plugin-api.md`（重新生成）。

> **替代方案（成本更低，完整性更差）**：只在前端变更点补 dispatch 同名事件。
> 缺点：扫描器、来源监控等**无 UI 触发**的变更永远送不到前端。宠物播报恰恰需要这些。

#### P0-3 · 插件更新时保留 `data/`（G3）

**问题**

```
core/plugins/installer.py:326   shutil.move(source_dir, staging_dir)
core/plugins/installer.py:333   trash_path = move_plugin_to_trash(...)   # 旧目录整体进回收站
core/plugins/installer.py:335   os.replace(staging_dir, target_dir)     # 原子替换
core/plugins/installer.py:348   os.makedirs(os.path.join(target_dir, 'data'), exist_ok=True)
```

旧 `data/` 随旧目录一起进回收站，新 `data/` 是空目录。用户自定义的宠物形象
（`api.data_dir()`，`core/plugins/api.py:396-403`）**每次插件更新都会丢失**。

这不是宠物插件独有的问题：`data/plugins/stm-ai-assistant/data/providers.json`
（该插件自己的供应商配置）同样会丢。

**建议方案**：`os.replace` 之前把旧 `target/data/` 移出到 `staging` 同级临时位置，
替换后**合并**回新目录（新包携带的同名文件不覆盖用户数据，冲突项改名备份）。
并在 `install_plugin_dir` 的返回值与安装日志里带上 `preserved_data` 计数。

**改动点**：`core/plugins/installer.py`（`install_plugin_dir`）、
`tests/test_plugin_installer.py` 新增用例、`docs/2026-09-22-plugin-system-design.md` 3.6 节补充语义。

### P1 — 不做能跑，但体验/性能明显劣化

#### P1-1 · 插件资产的缓存与条件请求（G5）

**实测**（在 `data/plugins/hello-world` 上跑 Flask test client）：

```
status 200
  Cache-Control: no-cache
  ETag: "1791352479.0715444-2438-208018582"
  Last-Modified: Wed, 07 Oct 2026 05:54:39 GMT
  Content-Length: 2438
  Accept-Ranges: None
revalidate status (If-None-Match): 200    len 2438     ← 有 ETag 却不返回 304
range status (Range: bytes=0-9): 200      len 2438     ← 不支持 Range
```

根因：`core/plugins/assets.py:103` `send_file(target, mimetype=..., conditional=False, max_age=0)`。
`conditional=False` 关掉了条件请求处理，所以 `If-None-Match` 也回 200 全量。

对序列帧动画（几十张帧图、每帧几十 KB）来说，**每次换帧都是一次完整网络往返**，
「图片刷新式动画」的低开销优势会被网络层吃光。

**建议**：
1. `conditional=True`，让 ETag 生效返回 304（零成本修复）；
2. 因为资产 URL 已带 `?v=<插件版本>`（`pluginHost.js:93-98` `withAssetVersion`），
   可以给强缓存：`Cache-Control: private, max-age=31536000, immutable`；
3. 顺手给 `ALLOWED_EXTENSIONS`（`assets.py:29-31`）加 `.gif` 与 `.avif`——
   用户若想直接用 GIF 当宠物形象，改一行即可支持。

> 注意 `pluginHost.js:93-98` 的注释已经指出：`no-cache` 只保证发请求，
> 浏览器仍可能用启发式新鲜度给旧响应；改成版本化强缓存反而**更安全**。

#### P1-2 · 宿主状态广播（G6 / R1）

宠物要做的自然反应：用户打开详情页 → 躲开；进入某个视图 → 换个姿势；
系统开了「减少动态效果」→ 停下动画；宿主在跑批处理 → 降频。

建议 `api.host.onState(handler)`，首次订阅推一次快照，之后变化时推送：

```js
{
  mode: 'cards',              // 现取 store.currentMode
  deviceType: 'desktop',      // 现取 store.deviceType
  darkMode: true,
  modalOpen: true,            // 任一 surface / 宿主模态打开
  scrimActive: true,          // 复用 dom.js:526-528 isFullscreenScrimActive()
  busy: false,                // 批处理 / 索引 / 扫描进行中
  reducedMotion: false,       // matchMedia('(prefers-reduced-motion: reduce)')
  visible: true,              // document.visibilityState
}
```

现成的原料都在：`dom.js:513-528`（遮罩记账，只差导出）、`entryRegistry.js:711-727`（`context()`）、
`state.js:518+`（store）。宿主统一做，还顺带解决了「页面隐藏时自动暂停」这件
每个插件都得自己写、且很容易写漏的事。

`reducedMotion` 特别重要：宿主 CSS 侧有 20+ 处 `@media (prefers-reduced-motion: reduce)`，
JS 侧却没有任何信号。宠物动画**必须**能在这里被关掉。

#### P1-3 · 补上 `settings` 入口 kind 的渲染消费者（G7）

`static/js/components/pluginManager.js:79-99` 写得很明确：

> `settings` / `nav` / `status` 三种 kind 目前宿主**没有任何渲染消费者**
> `IMPLEMENTED_ENTRY_KINDS = new Set(["dock", "context", "command", "batch"])`

宠物插件的「自定义形象」需要管理界面：上传、预览、动作映射、必要动作校验、删除。
放在设置页的一个插件区块里最自然。目前只能自己做入口 + 自己开 surface——
虽然可行（`kind:'command'` 或 `dock` 都能开 surface），但用户找不到。

优先级：**中**。可以先复用 `kind:'settings'` 的声明，等宿主补消费者；
短期用 `kind:'dock'` + `kind:'command'` 双入口兜底。

### P2 — 锦上添花

| # | 项 | 说明 |
|---|---|---|
| P2-1 | 文件投递契约（G8） | 宿主已有全局拖放：`static/js/components/layout.js:361-362` 派发 `handle-files-drop`（宿主私有）。把它变成 `api.host.pickFiles({accept, multiple})` + `on('host.files-dropped')`，插件才能做「把图拖进窗口就变成宠物」 |
| P2-2 | `tools/new_plugin.py --template ambient` | 脚手架加一个环境层模板 |
| P2-3 | `docs/plugin-api.md` 增「常驻内容」章节 | 宠物 / 桌面挂件 / 实时状态徽标共用同一份说明 |
| P2-4 | 环境层的「勿扰开关」 | 宿主提供一个全局 `quietMode`，宠物一律静音 —— 打扰型功能的必备逃生口 |

### 明确**不做**的

| 项 | 理由 |
|---|---|
| `config_schema` 支持 `array` / `object` | 宠物形象管理需要**专门 UI**（预览、拖拽排序、必要动作齐全性校验），宿主通用表单满足不了。让插件自带 UI 更合理，也符合「功能不做用户自定义」的边界 |
| 宿主解析/校验宠物包格式（动画清单、帧数、fps） | 这是插件内部领域模型，塞进宿主会污染契约。宿主只负责「给容器、给资源通路、给生命周期」 |
| 宠物的物理引擎 / 骨骼 / 寻路 | 同上，纯插件侧 |
| `api_version` 升级 | 本次全部为**增量、可选**能力，沿用 entry-unification §6.4 的裁定（`docs/2026-10-10-plugin-entry-unification-design.md:413`）：纯增量不构成不兼容变更 |

---

## 4. 宠物插件侧设计建议（不进宿主契约）

### 4.1 动作词表与回退链

用户提出「必要动作必须设置，非必要可省略，省略时做默认处理」。建议把回退链写死成契约：

| 动作 | 级别 | 触发 | 省略时的回退 |
|---|---|---|---|
| `idle` | **必要** | 无输入 | —— （唯一硬必要动作） |
| `walk` | **必要** | 水平移动 | → `idle`（只位移容器，不播帧） |
| `drag` | **必要** | 指针按住拖拽中 | → `idle` |
| `fall` | **必要** | 自由下落中 | → `idle` |
| `land` | 可选 | 触地瞬间 | → `fall` 尾帧 / 直接切 `idle` |
| `sleep` | 可选 | 长时间无操作 | → `idle`（降频） |
| `click` | 可选 | 被单击 | → `idle` |
| `happy` / `sad` / `angry` | 可选 | 事件播报时 | → `idle` |
| `look` | 可选 | 指针靠近 | → `idle` + 容器翻转（`scaleX(-1)`） |

**回退链的语义**：`缺失 → 沿链下溯 → 最终一定落到 idle`。
「必要动作」的真正含义不是「不给就报错」，而是**「不给就退化为静态位移」**——
这样任何一张单帧图都能跑起来，符合「非必要则省略」的诉求。

### 4.2 宠物包格式（插件自定义）

```json
{
  "id": "my-pet",
  "name": "小猫",
  "size": { "w": 64, "h": 64 },
  "anchor": { "x": 0.5, "y": 1.0 },
  "physics": { "gravity": 1800, "walkSpeed": 60, "friction": 0.85 },
  "animations": {
    "idle": { "sheet": "idle.png", "frames": 4, "fps": 6,  "loop": true },
    "walk": { "sheet": "walk.png", "frames": 6, "fps": 10, "loop": true },
    "fall": { "sheet": "fall.png", "frames": 2, "fps": 8,  "loop": true },
    "drag": { "sheet": "drag.png", "frames": 2, "fps": 4,  "loop": true }
  }
}
```

### 4.3 性能要点（对应「图片刷新式动画」）

1. **用 spritesheet + `background-position` 换帧，不要改 `<img src>`**
   —— 换 `src` 会走网络/解码；换 `background-position` 只改绘制。
   前提是这张表已经被浏览器缓存（→ 依赖 P1-1）。
2. **rAF + 时间累加推进帧**，不要 `setInterval`：掉帧时不会累积漂移。
3. **位移用 `transform: translate3d()`**，走合成层，不触发 layout。
   `will-change: transform` 只在运动期间加，停下就摘掉（常驻会占显存）。
4. **空闲降频**：`idle` 且无输入时把帧率降到 4–6fps；静止不动时可完全停绘。
5. **页面不可见 / `reducedMotion` / 宿主 busy / 全屏遮罩打开 → 暂停或降频**
   （依赖 P1-2 的广播；短期可自己监听 `visibilitychange` 兜底）。
6. **像素风图片加 `image-rendering: pixelated`**，避免缩放糊掉。
7. 必须在 `activate()` 返回的 disposer 里 `cancelAnimationFrame` +
   移除全局监听 —— `pluginHost.js:233-242` + `:861-900` 会保证调用。

---

## 5. 实施顺序与验收

| 阶段 | 内容 | 验收 |
|---|---|---|
| **阶段 1（P0）** | P0-1 环境层 surface + `--z-ambient`；P0-3 更新保留 `data/` | `pytest tests/test_plugin_installer.py tests/test_plugin_host_contracts.py -q` 全绿；手工：注册一个 ambient surface 的样例插件，确认它不抢焦点、ESC 不关它、禁用插件后被强制卸载、不推挤内容区 |
| **阶段 2（P0）** | P0-2 核心事件 SSE 通路 | `pytest tests/test_plugin_sse.py tests/test_plugin_events.py -q`；手工：改一张卡，浏览器端 `api.on('card.updated')` 收到 |
| **阶段 3（P1）** | P1-1 资产缓存；P1-2 状态广播 | 实测 `If-None-Match` 返回 304；`node` 侧断言状态对象字段齐全 |
| **阶段 4** | 宠物插件本体（独立仓库，对齐 `stm-ai-assistant` 的分发方式） | 形象导入、四种必要动作、拖拽/下坠/行走/静息、播报、禁用即彻底停止 |
| **阶段 5（P2）** | P1-3 settings 消费者、P2-* | 按需 |

**每次改动后必须执行**（AGENTS.md「Generated Artifacts」）：

```powershell
python tools/gen_plugin_api_docs.py           # PluginAPI / buildApi 变更后
python tools/gen_plugin_ui_icons.py           # 若新增图标
python tools/gen_plugin_api_docs.py --check
python tools/gen_plugin_ui_icons.py --check
```

新增公开方法后要在 `tools/gen_plugin_api_docs.py` 的 `BACKEND_GROUPS` / `FRONTEND_MEMBERS`
登记，否则 `tests/test_plugin_api_docs.py` 会失败。

---

## 6. 一句话总结

现有插件系统的表面契约（四种对话框 surface）与宠物的本质（常驻非模态图层）
**是相反的**；主程序需要还的第一笔债是**环境层**，第二笔是**后端事件的前端通路**，
第三笔是**插件数据在更新时的存续**。这三笔还完，宠物插件可以完全在
「宿主拥有容器、插件拥有内容」的既有架构内实现，不必重走悬浮球的老路。

---

## 7. 实施进展（2026-10-11 回填）

宿主侧缺口已由 `docs/2026-10-11-host-ambient-layer-prompt.md` 全部实施完毕。
下表逐项对应第 3 节的缺口清单。

| 缺口 | 状态 | 落点 |
|---|---|---|
| **P0-1 环境层 surface** | ✅ 已实现 | `type: 'ambient'`：`pluginSurfaceHost.js` 的独立挂载路径（**不复用** `openSurface`，那条路径会建 header / 设 `role="dialog"` / 装焦点陷阱 / 调 `setFullscreenScrim`，对常驻图层每一项都是错的）；`--z-ambient: 55` + `.z-ambient`；`hostFeatures()` 新增 `hasAmbient`（仅非移动端） |
| **P0-2 核心事件前端通路** | ✅ 已实现 | `GET /api/plugins/events`（SSE）+ `hooks.publish_core_event()`（fire-and-forget，不阻塞派发方）；`api.on()` 按 `CORE_EVENTS` 分流，懒连接、每插件一条流 |
| **P0-3 更新保留 `data/`** | ✅ 已实现 | `installer.install_plugin_dir()`：`os.replace` **之前**把旧 `data/` 移出，替换后合并回来；用户数据优先，冲突项新包那份改名 `<name>.plugin-default`；迁移失败**不阻断安装** |
| **P1-1 资产缓存 / 条件请求** | ✅ 已实现 | `assets.py` 改 `conditional=True` + `Cache-Control: private, max-age=31536000, immutable`；实测 `If-None-Match` → **304**、`Range` → **206**；白名单新增 `.gif` / `.avif` |
| **P1-2 宿主状态广播** | ✅ 已实现 | `api.host.onState(handler)`：首次订阅立即推快照，之后去抖推送；`reducedMotion` 监听 `change`（用户改系统设置即推，无需刷新） |
| **P1-3 settings 入口消费者** | ✅ 已实现 | 渲染为插件管理页内的「插件设置入口」区块（**挂在既有 `plugins` 分区内**，规避 `settingsHelpContent` 硬闸门）；`IMPLEMENTED_ENTRY_KINDS` 同步加入 `settings` |

### 与本文档的偏差

1. **`api_version` 仍为 `2`**（未升级）。本次全部是增量、可选能力：旧插件不调用新
   API 时行为完全不变，没有任何既有签名被删除或改变。与 entry-unification §6.4 的
   既有裁定一致。
2. **移动端不实现 ambient**（D1.6）。移动端屏幕小，常驻图层会遮挡内容且没有「挪开」
   的手段；`register()` 返回空串并 `console.warn`。这与入口坞在 `deviceType === 'mobile'`
   时退化为顶栏按钮的既有设计一致。留给后续独立任务。
3. **后端 `SURFACE_TYPES` 保持四元组不变**。它用于校验 manifest 的
   `entries[].surface.type`，而 ambient **没有用户可见入口**（注册即挂载），
   在 manifest 里声明它没有意义。宿主前端支持的集合是后端可声明集合的**超集**，
   相应的一致性断言已从「两边恒等」改为「前端 ⊇ 后端」。
4. **`nav` / `status` 两种 kind 仍无渲染消费者**——本次只补 `settings`，二者继续在
   总览页如实标注为「宿主未实现」。
5. **未实现「勿扰开关」（`quietMode`）**。想法正确但需要产品决策（默认值、全局 vs
   单插件、UI 入口），记录为后续项。
6. **插件侧内容全部未做**（宠物包格式、动画清单、物理引擎、`config_schema` 扩展
   `array` / `object`）。这些属于插件领域模型，宿主只负责「给容器、给资源通路、给
   生命周期」——第 4 节的建议仍然有效，但不在本次实施范围。

### 验收证据

- `python -m pytest tests/ -q` → **3220 passed, 0 failed**（基线 3114 passed）。
- `python tools/gen_plugin_api_docs.py --check` → 0；`python tools/gen_plugin_ui_icons.py --check` → 0。
- 新增测试：`tests/test_plugin_ambient_surface.py`（24）、`tests/test_plugin_events.py`（24）、
  `tests/test_plugin_host_state.py`（22），以及既有文件内的增量断言。
- `data/plugins/` 下两个既有插件仍能被 `load_all()` 正常加载。

**判定标准**：做完之后，插件**不需要**自绘 `position: fixed` 就能常驻在界面上——
`ambient` 契约成立。若仍要自绘，则本次没做对。

