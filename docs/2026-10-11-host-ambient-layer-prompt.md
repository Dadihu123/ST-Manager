# 主程序「环境层 + 事件通路 + 数据存续」补全 —— 实施提示词

> 用途：把本文件整份交给一个全新的编码会话，按其执行。
> 目标仓库：`D:\Workspace\MyOwn\ST-Manager`（主程序）。
> 生成日期：2026-10-11。
> 设计依据（只读参考，**本文件的决策优先**）：`docs/2026-10-11-plugin-pet-capability-gap.md`。
> 前置事实：主程序已完成插件系统地基修缮与入口坞（`frontend.entries` / `surfaces` / `api.ui.*` /
> `entryRegistry` / `entryDock` / 命令面板均已在 `HEAD 886cacc` 上可用）。

---

## 0. 任务陈述

**只改主程序，不写任何宠物插件代码。** 本次的目的是把「宠物插件」这类
**常驻型插件**的宿主侧前提补齐——现有四种 surface 全部是「用户打开、可关闭、抢焦点」的
对话框，与常驻图层的语义相反，所以此类插件现在只能靠自绘 `position: fixed` 浮层来实现，
而那正是地基修缮要消灭的模式。

三件事，按优先级：

1. **环境层 surface**（P0）——给常驻型内容一个受宿主管辖、非模态、不抢焦点的容器。
2. **后端事件的前端通路**（P0）——`api.on('card.updated')` 目前在浏览器里**永远不会被调用**。
3. **插件更新时保留 `data/`**（P0）——用户自定义资产现在每次更新都被抹掉。

外加三项 P1：插件资产的缓存/条件请求、宿主状态广播、`settings` 入口 kind 的渲染消费者。

**这次改的是宿主的地基，不是给宠物开的特例。** 做完之后，桌面挂件、常驻状态徽标、
任何「一直在屏幕上但不是一个窗口」的插件内容都吃同一套契约。判定标准：
**如果做完之后插件仍然需要自绘 `position: fixed` 才能常驻，那就是没做对。**

**明确不在本次范围**：

- 宠物插件本体、宠物包格式、动画清单、物理引擎（那是插件侧领域模型）。
- `config_schema` 扩展 `array` / `object`（形象管理需要专门 UI，宿主通用表单满足不了，
  让插件自带 UI 更合理）。
- `api_version` 升级（见 §2 D0）。
- 迁移 `data/plugins/stm-ai-assistant`（独立仓库 `D:\Workspace\MyOwn\ST-Manager-AI-Assistant`，一律不碰）。
- 移动端的常驻图层（**本文件对 ambient 的规定全部以桌面/平板为前提**，见 §2 D1.6）。

---

## 1. 硬约束（来自 `AGENTS.md`，违反即返工）

**风格**

- 4 空格缩进；Python 优先单引号；行宽 ~100–120；顶层函数之间两空行。
- JS 跟随所在文件既有缩进（现有插件相关 JS 为 2 空格）。
- import 顺序 stdlib / third-party / local，组间空行；优先 `from core.xxx import yyy`；不留无用 import。
- 命名：类 `PascalCase`、函数 `snake_case`、常量 `UPPER_CASE`、私有前缀 `_`、Blueprint 变量名惯例 `bp`。

**数据与路径**

- SQLite 直接 `sqlite3`、**必须参数化、禁止拼 SQL**；保留 `core/data/db_session.py` 的 WAL 设置；
  写锁用 `execute_with_retry()`。
- 路径一律 `os.path.join()`；存储的相对路径用 `.replace('\\', '/')` 归一。
- 写中文 JSON 用 `ensure_ascii=False`。
- 不做破坏性文件操作，除非任务明确要求。

**日志与错误**

- `logger = logging.getLogger(__name__)`。
- 文件 I/O、JSON 解析、网络一律 try/except；优先具体异常、**禁止裸 `except:`**；
  可恢复用 warning、失败用 error。
- API 返回 `jsonify()` 结构化错误，**不得暴露堆栈**。

**测试**

- 行为变更必须在 `tests/` 加/改 pytest（`test_*.py`）。
- 全仓**无 pytest 配置文件**；`tests/conftest.py` 已把 `ui_store.UI_DATA_FILE` 等重定向到临时目录，
  **不要破坏这个隔离，也不要绕过它**。
- 插件相关测试已有 37 个 `tests/test_plugin*.py`，改契约前先跑最相关的单文件。

**其它**

- 保留中文用户可见字符串。
- 不得无强理由替换既有架构模式或引入新框架/抽象。**本次不引入任何新依赖、不引入打包器**
  （`requirements.txt` / `package.json` 保持不动）。
- 不得静默新增工具配置。
- **样式只用 `.color-*` 语义类与既有 CSS 变量**，不写字面量颜色
  （`tests/test_color_system_contracts.py` 与 `tests/test_plugin_surface_contracts.py:250-254` 在查）。
- **`prefers-reduced-motion`**：任何新动效都要遵守（仓库已有 30+ 处该媒体查询）。

**行号说明**：下文所有 `文件:行号` 都是 **`HEAD 886cacc` 的定位起点**，实施过程中会漂移，
请以内容匹配为准。

---

## 2. 权威决策清单

### D0 — `api_version` **不升**（保持 `2`）

`core/version.py` 的 `PLUGIN_API_VERSION` 与 `SUPPORTED_PLUGIN_API_VERSIONS` 不改。

理由：本次全部为**增量、可选**能力——旧插件不调用新 API 时行为完全不变，没有任何既有
签名被删除或改变。这与 `docs/2026-10-10-plugin-entry-unification-design.md` §6.4 的既有裁定一致
（「纯增量不构成不兼容变更」）。**不要**顺手升版，那会无谓地让所有现存插件面临
`min_app_version` 检查。

### D1 — 环境层 surface（`type: 'ambient'`）

#### D1.1 语义

`ambient` 是**常驻型** surface：注册即挂载、无打开/关闭动作、非模态、不抢焦点。
它与现有四种（`panel` / `modal` / `page` / `sheet`）的差异是**每一项都相反**：

| 项 | panel / modal / page / sheet | **ambient** |
|---|---|---|
| 触发 | `surfaces.open(id, ctx)` 或入口点击 | **`register()` 即挂载**，无 open/close |
| 容器 | 带定位的 shell + header + body | `position: fixed; inset: 0` 全屏透明层，**`pointer-events: none`** |
| 层级 | `--z-surface` / `--z-modal-popover` | **`--z-ambient`**（新增令牌） |
| 对话框语义 | `role="dialog"` + `aria-modal="true"` | **无**（不设 role，或 `role="presentation"`） |
| 焦点 | 焦点陷阱 + 关闭后恢复焦点 | **完全不碰焦点** |
| ESC | 关闭 | **忽略** |
| 全屏遮罩记账 | 非 `page` 一律 `setFullscreenScrim(true)` | **不参与** |
| 头部 / 关闭按钮 | 渲染 | **不渲染** |
| `data-marquee-ignore` | 有 | 有（同） |
| 回收 | `close()` 时 unmount | **插件 disable / unload / destroy 时强制 unmount** |

#### D1.2 层级：`--z-ambient: 55`

插在 `--z-card-selected: 50`（`variables.css:21`）与 `--z-surface: 60`（`:32`）之间。
这中间是令牌表里**唯一**的空档——60 / 70 / 80 已被 surface、美化抽屉、入口坞占满。

理由：环境层应盖住内容卡片与其选中态，但**必须低于**抽屉（60）、坞（80）、下拉（500）、
模态（1000+）。**宿主的功能性 UI 绝不能被常驻内容遮挡。**

实现要求：

- `static/css/modules/plugin-surfaces.css` 里**必须走 `var(--z-ambient)`**，不得写裸数字
  （`tests/test_plugin_surface_contracts.py:237-247` 会抓 `z-index:\s*(\d+)` 字面量）。
- 同时补 `.z-ambient` 工具类，风格对齐 `variables.css` 既有的 `.z-*` 系列。

#### D1.3 指针穿透（关键实现细节）

容器整体 `pointer-events: none`，插件在其中放置的**可交互子元素自行取回 `auto`**。
这是既有的成熟模式——`entry-dock.css:435` 记录了同样的问题：
「`pointer-events` 是**继承**属性」，坞的整体 `none` 导致每个可交互后代都必须显式取回。

必须在文档与示例里写明这一点，否则插件作者会踩「点了没反应」的坑。

#### D1.4 宿主遮挡降级

宿主在以下任一条件成立时，给 ambient 容器加状态类 **`is-host-occluded`**，移除时摘掉：

- `body.has-fullscreen-scrim`（复用 `static/js/utils/dom.js` 的 `isFullscreenScrimActive()`）
- 任何 `panel` / `modal` / `sheet` surface 处于打开态
- `document.visibilityState !== 'visible'`

**这是宿主统一触发的**，插件不得各自监听。插件据此暂停动画或降频。

实现位置建议：`pluginSurfaceHost.js` 内维护一个 `_syncAmbientOcclusion()`，
在 `openSurface` / `close` / `setFullscreenScrim` 调用点与 `visibilitychange` 上调用它。

#### D1.5 生命周期回收

**必须复用现有的强制回收链**，不要另造一套：

- `PluginSurfaceHost.unregisterPlugin(pluginId)` 要一并卸载该插件的 ambient
- `PluginSurfaceHost.closePlugin(pluginId)` 同理
- `pluginHost.js` 的 `destroy()`（`:861-900`）与 `plugin:unloaded` 监听（`:158-161`）链路保持有效

**语义要求**：禁用一个带 ambient 的插件后，屏幕上必须**立刻**什么都不剩，
且不依赖插件的 `deactivate`。

#### D1.6 移动端：**本次不实现**

移动端不挂载 ambient，`register()` 返回空串并在 `console.warn` 说明原因
（与 `pluginSurfaceHost.js:98-101` 现有的非法参数警告同风格）。

理由：移动端屏幕小，常驻图层会遮挡内容且无「挪开」的手段。这与坞的既有设计一致
（`entry_dock.html:19-34`：`deviceType === 'mobile'` 时坞不渲染侧条，退化为顶栏按钮）。
留给后续独立任务，不要在本次顺手做。

#### D1.7 门控写进 `hostFeatures()`

`static/js/entryRegistry.js:143-153` 的 `hostFeatures()` 是 `when.feature` 的取值来源
（当前只产出 `hasNetwork` / `hasSSE` / `hasFetch`）。**新增 `hasAmbient`**，仅在
非移动端时为真。

这样插件可以声明 `when: { feature: ['hasAmbient'] }`，宿主替它做门控——
比让插件自己去读 `store.deviceType` 更合规。

#### D1.8 品牌位图：附带加 `hasPixelRatio`（低成本，推荐做）

同一处再加 `hasPixelRatio`：`window.devicePixelRatio >= 1.5` 时为真。
留给插件做「高分屏用 2x 帧图」的能力探测。一行代码，但省掉插件自己去读 window。

---

### D2 — `SURFACE_TYPES` 与相关测试的**真实关系**（不读清这一条必然返工）

#### D2.1 逐行核对：**恰好 3 条断言会红**，其余 3 条不受影响

逐行读过之后的精确结果（不要凭猜测扩大或缩小范围）：

| 文件:行 | 断言内容 | 会红？ |
|---|---|---|
| `tests/test_plugin_surface_contracts.py:205` | `pluginSurfaceHost.js` 源码含字面量 `'export const SURFACE_TYPES = ["panel", "modal", "page", "sheet"]'` | ✅ **红** |
| `tests/test_plugin_surface_contracts.py:220` | 同上字面量（`read_source(SURFACE_HOST_PATH)`） | ✅ **红** |
| `tests/test_plugin_surface_contracts.py:221` | `set(SURFACE_TYPES) == {四元组}` —— 此处 `SURFACE_TYPES` 是 `:217` 从 **`core.plugins.entries` import 的后端变量** | ❌ 不红（后端不变） |
| `tests/test_plugin_entry_registry_frontend_contracts.py:79` | `entryRegistry.js` 源码含同一字面量 | ✅ **红** |
| `tests/test_plugin_entry_registry_frontend_contracts.py:83` | `set(SURFACE_TYPES)` —— 同样是从 **后端** `:71` import 的变量 | ❌ 不红 |
| `tests/test_plugin_entries_contracts.py:224` | 后端 `SURFACE_TYPES == frozenset({四元组})` | ❌ 不红 |

**注意 `:221` / `:83` 的陷阱**：这两条读起来像「跨前后端一致性检查」，
但它们比较的是**从后端 import 的变量与后端应该相等** —— 是同义反复，本来就没在查前端。
改的时候不要被它们的措辞误导去动它们。

另外两处**注释/文档串会变成错误陈述**，要一并订正（不会导致红，但留着就是谎）：

- `tests/test_plugin_entry_registry_frontend_contracts.py:70` 的 docstring「前端集合必须与
  `core/plugins/entries.py` **完全一致**」——按 D2.2 改为「必须是其**超集**」。
- `tests/test_plugin_surface_contracts.py:216` 的函数名 `test_surface_types_match_backend_contract`
  —— 保留函数名以避免无谓变更，但把语义在 docstring 里说清。

#### D2.2 决策：后端集合**不动**，前端集合**新增**，一致性断言改成**子集关系**

具体：

- `static/js/pluginSurfaceHost.js:23` 与 `static/js/entryRegistry.js:30` 的
  `SURFACE_TYPES` → 加入 `"ambient"`（**两个文件必须同步，否则运行期注册会被
  `entryRegistry` 拒掉**）。
- `core/plugins/entries.py:29` 的 `SURFACE_TYPES` **保持四元组不变**。
  理由：后端那份用于 **manifest `entries[].surface.type` 校验**（`entries.py:187`
  `_normalize_surface`）。manifest 的 `entries[]` 是「用户可见入口」，而 ambient
  **没有用户可见入口**（注册即挂载），在 manifest 里声明它没有意义。保持后端集合不变，
  等于让「manifest 里写 ambient」自然落到既有的「非法 surface.type → 丢弃该项 + warning」
  路径（`entries.py:187-191`），**不需要新增任何拒绝逻辑**。

- 一致性断言改为：**前端 `SURFACE_TYPES` 必须包含后端全部取值**，并各自断言自己的精确集合。
  这条新断言表达的真实契约是：「宿主前端支持的 surface 类型 ⊇ manifest 允许声明的类型」——
  比原来的「两边恒等」更准确（后者本来就是同义反复，见 D2.1 的说明），
  且不会在下次新增宿主专属类型时又红一片。

  落地形态：

  ```python
  # tests/test_plugin_entry_registry_frontend_contracts.py
  assert 'SURFACE_TYPES = ["panel", "modal", "page", "sheet", "ambient"]' in source
  # 前端 ⊇ 后端：新增宿主专属类型不应打破契约
  assert {'panel', 'modal', 'page', 'sheet'} <= {'panel', 'modal', 'page', 'sheet', 'ambient'}
  ```

  更稳的写法是从源码里**解析出前端集合再比较**，而不是硬编码第二份字面量——
  否则下次加类型要改三处。是否投入取决于你对本仓测试风格的判断，**两种都可接受**，
  但**不要**为了省事直接删掉断言。

- `tests/test_plugin_entries_contracts.py:224` 的**后端**断言保持原样（后端确实没变）。

**更新测试时不要削弱断言强度**——把「精确集合」换成「至少包含」，而不是直接删掉。

---

### D3 — 后端核心事件的前端通路

#### D3.1 问题（已实测，不要重新猜）

- 后端定义并派发：`core/plugins/hooks.py:23-35` 的 `CORE_EVENTS`，由
  `core/api/v1/cards.py:2181`（`card.updated`）、`:2294`（`card.moved`）、`:2551`（`card.deleted`）、
  `:4585`（`tag.deleted`）、`:4710`（`tag.applied`）、`:5823`（`card.created`）、
  `core/api/v1/world_info.py:2331`（`worldbook.saved`）、
  `core/services/scan_service.py:724`（`scan.completed`）、
  `core/services/index_job_worker.py:132`（`index.job_done`）触发。
- 前端 `pluginHost.js:318-324` 的 `on()` **只做 `window.addEventListener`**，不碰后端。
- 全仓 `grep 'app\.ready|card\.created|scan\.completed|worldbook\.saved' static/js`
  → **只命中 `pluginHost.js:32-43` 的 `CORE_EVENTS` 白名单本身**，零个 dispatch。

**结论：`api.on('card.created', h)` 在浏览器里永远不会被调用。**
而「扫描完成」「索引重建完毕」这类**无 UI 触发**的变更，前端更是没有任何其他途径得知。

#### D3.2 方案：新增 `GET /api/plugins/events`（SSE）

**复用已验证的 SSE 基础设施，不要另造**：`core/plugins/jobs.py:756-838` 的
`Response(generator, mimetype='text/event-stream')` + `: heartbeat` 帧 + 连接配额。

要求：

1. **只广播 `CORE_EVENTS`**。插件的自定义事件（`<id>:` 前缀）**不进这条流**——
   否则插件 A 的噪声会灌给所有插件，且 N1（`docs/2026-09-22-plugin-system-design.md:2080`）
   对插件间通信的「best-effort、不保证顺序」承诺会被这条流误读成强保证。
2. 连接配额：参照 `jobs.SSE_MAX_CONNECTIONS_TOTAL` 的既有做法设一个全局上限，
   超限返回结构化错误（不要静默挂住）。
3. 心跳间隔复用 `jobs.SSE_HEARTBEAT_INTERVAL_SECONDS`（15s）的既有取值风格。
4. 事件负载：`{event, payload, ts}`；**不得**携带插件密钥或卡片正文等敏感内容——
   这是广播信道，只放 `hooks.emit()` 已经给出的 payload 原样。
5. 一次 SSE 连接即可服务一个插件的全部订阅；**按插件连接数计**，
   不要把每个 `api.on()` 变成一条连接。

#### D3.3 前端改造：`api.on()` 分流

`pluginHost.js:318-324` 的 `on()` 改为：

- 事件名 ∈ `CORE_EVENTS` → 走 SSE（**懒连接**：首次订阅核心事件时才建立，
  零订阅的插件不占连接）。同一插件多次 `on()` 复用同一条流。
- 其余事件名 → 保持现状（`window.addEventListener`），**行为不变**。
- 返回的取消订阅函数语义不变。
- 连接生命周期挂到插件 disposer（`own()`，`pluginHost.js:269-272`），
  与 `subscribeJob`（`:719-726`）完全同一个模式。

#### D3.4 顺带：把前端既有 window 事件升格为 Provisional 契约

前端已经在派发的事件名（实测存在）：`card-updated`（`detailModal.js:2667` 等 6 处）、
`card-created`、`card-deleted`、`card-imported`、`refresh-card-list`、`refresh-wi-list`、
`refresh-chat-list`、`refresh-preset-list`、`refresh-beautify-list`、`refresh-folder-list`、
`entry:activate`、`theme-mode-changed`、`settings-saved`。

这些**名字一个都没写进文档**，属于隐性耦合：宿主改名插件就静默失效。
在 `docs/plugin-api.md` 里补一节「前端 window 事件（Provisional）」，列名 + 说明 +
`detail` 结构。**标注 Provisional**（形态已定但仍在收集反馈），不要标 Stable。

---

### D4 — 插件更新时保留 `data/`

#### D4.1 问题（已实测）

```
core/plugins/installer.py:326   shutil.move(source_dir, staging_dir)
core/plugins/installer.py:333   trash_path = move_plugin_to_trash(...)   # 旧目录整体进回收站
core/plugins/installer.py:335   os.replace(staging_dir, target_dir)     # 原子替换
core/plugins/installer.py:348   os.makedirs(os.path.join(target_dir, 'data'), exist_ok=True)
```

旧 `data/` 随旧目录一起进回收站，新 `data/` 是空目录。

**这不是宠物插件独有的问题**：`data/plugins/stm-ai-assistant/data/providers.json`
（该插件自己的供应商配置）同样每次更新都丢。`api.data_dir()`（`core/plugins/api.py:396-403`）
是宿主**官方提供的**插件私有数据目录，承诺了却保不住，是契约级缺陷。

#### D4.2 方案

`os.replace` **之前**，把旧 `target_dir/data/` 移出到 staging 同级临时位置；
替换完成后**合并**回新目录。

合并规则（必须明确，否则会有隐性的数据覆盖）：

- 新包携带的文件**不覆盖**用户已有数据（用户数据优先）。
- 冲突项（新包也有同名文件）→ 用户数据保留，新包那份**改名备份**
  （如 `<name>.plugin-default`），并在安装日志里记录。
- 目录整体移动失败时（跨卷、权限）→ 记 warning 并继续安装，
  **不得让数据迁移失败阻断安装**。

`install_plugin_dir` 的返回值与 `_log_action` 的 `detail` 里带上 `preserved_data` 计数。

#### D4.3 与 `uninstall_plugin` 的关系

`uninstall_plugin`（`installer.py:489-521`）的 `keep_data` 语义**不变**——
卸载是用户显式动作，默认清理是对的。本次只改**更新**路径。

---

### D5 — 插件资产的缓存与条件请求

#### D5.1 实测（在 `data/plugins/hello-world` 上跑 Flask test client 的真实输出）

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

根因：`core/plugins/assets.py:103`
`send_file(target, mimetype=..., conditional=False, max_age=0)`。
`conditional=False` 关掉了条件请求处理。

#### D5.2 方案

1. `conditional=True`，让 ETag 生效返回 304（零成本修复）。
2. 因为资产 URL 已带 `?v=<插件版本>`（`pluginHost.js:93-98` 的 `withAssetVersion`），
   可以给强缓存：`Cache-Control: private, max-age=31536000, immutable`。
   **注意**：`pluginHost.js:86-98` 的注释已经指出 `no-cache` 只保证发请求、
   浏览器仍可能用启发式新鲜度给旧响应；改成版本化强缓存反而**更安全**。
3. 顺手给 `ALLOWED_EXTENSIONS`（`assets.py:29-31`）加 `.gif` 与 `.avif`，
   并在 `DEFAULT_MIME_TYPES`（`:33-43`）补对应 MIME。
   用户若想直接用 GIF 当形象，改一行即可支持。

#### D5.3 **必须同步的四处**

- `core/utils/security_headers.py:25-31` 的 `PLUGIN_ASSET_CSP` 的 `img-src 'self' data:`
  要覆盖新扩展名——`img-src` 按 scheme 放行，**不需要逐个列扩展名**，但请实测确认。
- `tests/test_plugin_assets.py:45` **当前断言 `Cache-Control == 'no-cache'`**，
  改缓存策略必须同步改这里。
- `tests/test_security_headers.py:94-111`（端到端 CSP 断言）要保持绿。
- `static/js/utils/icons.js:23` 的 `PLUGIN_ICON_EXTENSIONS = new Set([".svg", ".png", ".webp"])`
  与 `tests/test_plugin_icon_resolution.py:54` 注释明确说「与后端 `ALLOWED_EXTENSIONS` 对齐」——
  若后端扩展名变了，这个**图标**子集是否要跟着变需要判断：**建议保持不变**，
  因为图标位是 16–24px 的 mask 渲染，`.gif` / `.avif` 作图标无意义。
  但要确认 `tests/test_plugin_icon_resolution.py:54` 的注释不会变成错误陈述。

---

### D6 — 宿主状态广播

新增 `api.host.onState(handler)`：首次订阅立即推一次快照，之后变化时推送。
返回取消订阅函数（与其他订阅 API 一致）。

```js
{
  mode: 'cards',            // 复用 EntryRegistry.context() 的取法
  deviceType: 'desktop',    // 复用 store.deviceType
  darkMode: true,           // 复用 store.isDarkMode
  scrimActive: true,        // 复用 dom.js 的 isFullscreenScrimActive()
  surfaceOpen: false,       // 任一 surface 打开
  busy: false,              // 批处理 / 索引 / 扫描进行中
  reducedMotion: false,     // matchMedia('(prefers-reduced-motion: reduce)')
  visible: true,            // document.visibilityState
}
```

现成原料都在：`dom.js:513-528`（遮罩记账，**只差把它导出**）、
`entryRegistry.js:711-727`（`context()`）、`store`（`pluginHost.js:309-315`）。

实现要点：

- `reducedMotion` **必须**支持 `change` 事件监听（用户可以在系统设置里改，
  不改页面就变），不能只读一次。
- 推送要**合并去抖**（如 rAF 或 100ms 微批），不要每个字段变化各推一次。
- `busy` 的判定复用 `store.batchProgress` / `store.indexStatus`，
  不要新造一套状态。**实现前先读 `static/js/state.js` 确认字段名。**

---

### D7 — `settings` 入口 kind 的渲染消费者

`static/js/components/pluginManager.js:76-99` 写得很明确：

```js
// settings / nav / status 三种 kind 目前宿主没有任何渲染消费者
const IMPLEMENTED_ENTRY_KINDS = new Set(["dock", "context", "command", "batch"]);
```

本次**只补 `settings`**（`nav` / `status` 不在范围）。

**关键陷阱**：设置页有硬闸门。`static/js/components/settingsModal.js:304-306`：

```js
selectSettingTab(section, anchor = "") {
  if (!this.settingsHelpContent[section]) return;   // ← 闸门
```

`plugins` 键已存在（`settingsModal.js:200-205`），所以**区块注入挂到既有 `plugins` 分区内**即可，
**不要新增顶层 tab**（会触发设置页膨胀，且需同时改 `settingsHelpContent`、
`COMMAND_PALETTE_ENTRIES`（`:120-122`）与模板，成本远大于收益）。

- `kind: 'settings'` 的入口渲染为插件管理页内的一个区块，点击打开该插件的 surface。
- `IMPLEMENTED_ENTRY_KINDS` 要同步加 `settings`，否则总览页（`pluginManager.js:84-92`
  的 `ENTRY_LOCATION_LABELS`）会继续显示「宿主未实现」，自相矛盾。
- `tests/test_plugin_manager_contracts.py:100` 断言源码含 `IMPLEMENTED_ENTRY_KINDS`。

---

### D8 — 明确**不做**的（写下来防止实施时越界）

| 项 | 理由 |
|---|---|
| `config_schema` 支持 `array` / `object` | 形象管理需要预览、拖拽排序、必要动作齐全性校验，宿主通用表单满足不了。让插件自带 UI 更合理 |
| 宿主解析/校验宠物包格式（动画清单、帧数、fps） | 插件内部领域模型，塞进宿主会污染契约。宿主只负责「给容器、给资源通路、给生命周期」 |
| 物理引擎 / 骨骼 / 寻路 | 同上，纯插件侧 |
| 移动端的 ambient | D1.6 已说明 |
| 环境层的「勿扰开关」（`quietMode`） | 想法正确但需要产品决策（默认值、全局 vs 单插件、UI 入口）。**记录在文档的「后续项」里，本次不实现** |
| 桌面通知 / 系统级提醒 | 不在插件系统范围 |

---

## 3. 实施阶段

> 每阶段结束**必须**：跑该阶段相关测试 → 报告改动文件清单 + 测试结果 + 遗留问题。
> 阶段之间不要跳。**每阶段独立可回滚。**

### 阶段 0 — 文档冻结与测试基线（不改代码）

1. 在 `docs/2026-09-22-plugin-system-design.md` 第 8 部分 F15 之后追加 **F16**（环境层契约）：
   常驻型 surface 的语义表（照抄 D1.1）、`pointer-events` 继承陷阱、`is-host-occluded` 降级、
   「插件仍不得自绘 `position: fixed`」这条**不变**。
2. 同文档第 6 部分补「插件事件流」小节（D3）。
3. 同文档第 3.6 节补「更新保留 `data/`」的语义（D4）。
4. 同文档第 8.5 节补资产缓存策略（D5）。
5. `docs/2026-10-11-plugin-pet-capability-gap.md` 标记为「已排期」，指向本次实施。
6. 先跑一次基线，**记录当前红绿状态**（有些测试可能本来就红）：

```powershell
python -m pytest tests/ -q --tb=no 2>&1 | Select-Object -Last 20
python tools/gen_plugin_api_docs.py --check
python tools/gen_plugin_ui_icons.py --check
```

**验收**：文档与 D0–D8 一致；基线测试结果被记录；`--check` 两个脚本状态已知。

---

### 阶段 1 — 环境层 surface（P0，最高优先级）

**改 `static/js/pluginSurfaceHost.js`**

- `:23` `SURFACE_TYPES` 加 `"ambient"`。
- `:40-45` `SURFACE_CLASSES` 加 `ambient: "plugin-surface plugin-surface--ambient"`。
- `register()`（`:95-129`）：`type === 'ambient'` 时走**独立挂载路径**——
  不建 header / close / 不调 `setFullscreenScrim` / 不调 `_trapFocus` / 不设 `role="dialog"`；
  移动端直接返回空串 + `console.warn`（D1.6）。
- 新增 `_syncAmbientOcclusion()`（D1.4），在 `openSurface` / `close` /
  遮罩变更 / `visibilitychange` 调用点触发。
- `closePlugin`（`:369-376`）/ `unregisterPlugin`（`:379-390`）要覆盖 ambient。

**改 `static/js/entryRegistry.js`**

- `:30` `SURFACE_TYPES` 同步加 `"ambient"`（**漏了这里会导致运行期注册被 `:574` 的校验拒掉**）。
- `:143-153` `hostFeatures()` 加 `hasAmbient`（D1.7）与 `hasPixelRatio`（D1.8）。

**改 `static/css/modules/plugin-surfaces.css`**

- 新增 `.plugin-surface--ambient`：`position: fixed; inset: 0; pointer-events: none;
  z-index: var(--z-ambient)`，无背景、无边框、无阴影。
- 新增 `.plugin-surface--ambient.is-host-occluded`（降级态；具体视觉由插件决定，
  宿主只提供一个可检测的钩子）。
- **不得**出现 `backdrop-filter`（`tests/test_plugin_surface_contracts.py:224-234` 会抓）
  与 z-index 字面量。

**改 `static/css/modules/variables.css`**

- 新增 `--z-ambient: 55` + `.z-ambient` 工具类。
- 注释说明「介于卡片选中态与 surface 之间，宿主功能性 UI 不得低于此层」。

**改 `static/js/pluginHost.js`**

- `surfaces.*` 的注释与文档串补 ambient 用法（不影响签名）。

**测试**

- 新增 `tests/test_plugin_ambient_surface.py`，覆盖：
  - 注册即挂载（不调 `openSurface` 也有 DOM）
  - **无 `role="dialog"`**、**不抢焦点**（`document.activeElement` 不变）
  - **ESC 不关闭它**
  - 不调 `setFullscreenScrim`（断言 `document.body` 无 `has-fullscreen-scrim`）
  - 容器带 `data-marquee-ignore`
  - 重复 `register` 同 id 的行为明确（覆盖或拒绝，二选一并测）
  - `unregisterPlugin` / `closePlugin` 后 DOM 干净
  - 移动端不挂载
  - `is-host-occluded` 在 surface 打开时被加上、关闭时被摘掉
- **按 D2.2 更新四处 `SURFACE_TYPES` 断言**。

**验收**：

```powershell
python -m pytest tests/test_plugin_ambient_surface.py tests/test_plugin_surface_contracts.py `
  tests/test_plugin_entry_registry_frontend_contracts.py tests/test_plugin_entries_contracts.py `
  tests/test_plugin_entry_dock_contracts.py tests/test_plugin_host_contracts.py -q
```

手工（必须做，这是本阶段的真正验收）：写一个临时样例插件注册 ambient surface，确认——
① 它不推挤 `.content-area` 的布局；② 打开详情页时它被 `is-host-occluded` 标记；
③ 在坞里禁用该插件后**立刻消失**；④ 框选不命中它；⑤ 键盘 Tab 不会掉进它里面。
**临时样例用完删除，不要留在 `samples/` 或 `data/plugins/`。**

---

### 阶段 2 — 后端事件的前端通路（P0）

**改 `core/plugins/hooks.py`**

- 增加订阅者注册表（或事件环形缓冲），让 `emit()`（`:122-155`）在派发的同时
  把 `CORE_EVENTS` 喂给事件流。
- **保持现有语义不变**：同步派发、异常吞掉、慢 handler 告警。新增的广播必须是
  **非阻塞**的——不得因为某个客户端慢而拖住核心流程（这是硬要求，
  `hooks.py:6-10` 的派发语义是核心不变量）。
- 新增 `reset_event_stream_for_tests()` 之类的测试隔离钩子（对齐 `reset()`，`:169-172`）。

**改 `core/plugins/routes.py`**

- 新增 `GET /api/plugins/events`（D3.2）。注意本蓝图已有
  `_no_store_for_management_api`（`:62-66`）与 `_handle_plugin_errors`（`:38-52`），
  新端点要遵从同一套约定。
- **SSE 端点不要被 `_no_store_for_management_api` 的 `Cache-Control: no-store` 搞坏**——
  实测确认这条头不影响 SSE 流。

**改 `static/js/pluginHost.js`**

- `on()`（`:318-324`）按 D3.3 分流。
- 新增内部 SSE 连接管理（复用 `:679-727` `subscribeJob` 的 EventSource + 轮询降级模式与 `own()` 清理）。
- **不要**把 SSE 连接建在 `loadPlugin` 里——懒连接，零订阅不占配额。

**测试**

- 新增 `tests/test_plugin_events.py`：核心事件能到达订阅者、**插件自定义事件不进流**、
  配额上限、断开清理。
- 扩展 `tests/test_plugin_sse_frontend_contracts.py`（若适用）。
- 确认 `tests/test_plugin_isolation.py:259-267` 的跨插件越权语义不被破坏。

**验收**：改一张卡后，浏览器端 `api.on('card.updated')` 真的收到；跑一次扫描，
`api.on('scan.completed')` 真的收到（**这是本阶段的真正验收**，
因为扫描是无 UI 触发的场景，最能证明通路是后端来的）。

---

### 阶段 3 — 插件更新保留 `data/`（P0）

**改 `core/plugins/installer.py`**

- `install_plugin_dir`（`:299-386`）按 D4.2 实现数据存续。
- 改动点集中在 `:330-351` 那段（`existed` → `move_plugin_to_trash` → `os.replace` → `makedirs`）。
- 严格遵守 §1 的错误处理约定：数据迁移失败**不得**阻断安装。

**测试**

- 扩展 `tests/test_plugin_installer.py`：
  - 更新时用户数据保留
  - 新包同名文件不覆盖用户数据、且被改名备份
  - 首次安装（无旧目录）不受影响
  - 迁移失败时安装仍然成功（monkeypatch 制造 `OSError`）
- 确认 `uninstall_plugin` 的 `keep_data` 用例**保持绿**（不该受影响）。

**验收**：`python -m pytest tests/test_plugin_installer.py tests/test_plugin_isolation.py -q` 全绿；
手工：在 `data/plugins/hello-world/data/` 放一个文件，重装该插件，确认文件还在。

---

### 阶段 4 — 三项 P1

**D5 资产缓存**：改 `core/plugins/assets.py`，同步更新
`tests/test_plugin_assets.py:45` 的 `Cache-Control` 断言。手工验证返回 304。

**D6 状态广播**：`pluginHost.js` 新增 `api.host.onState`；实现前先读 `state.js`
确认 `batchProgress` / `indexStatus` 的真实字段名，不要猜。

**D7 settings kind**：改 `pluginManager.js` 的 `IMPLEMENTED_ENTRY_KINDS` 与
`ENTRY_LOCATION_LABELS`，在既有 `plugins` 设置分区内注入区块。

**测试**：`tests/test_plugin_assets.py`、`tests/test_plugin_manager_contracts.py`、
新增 `tests/test_plugin_host_state.py`。

---

### 阶段 5 — 契约收尾（**不可跳过**）

1. **API 文档是生成物**：本次新增 `api.host.onState` 与 `surfaces` 的 ambient 说明后，
   必须在 `tools/gen_plugin_api_docs.py` 的 `FRONTEND_MEMBERS`（`:68-120`）登记，
   否则 `tests/test_plugin_api_docs.py` 会失败：

```powershell
python tools/gen_plugin_api_docs.py
python tools/gen_plugin_api_docs.py --check
```

2. `docs/plugin-api.md` 补「前端 window 事件（Provisional）」一节（D3.4）。
3. 若新增了宿主图标，跑 `python tools/gen_plugin_ui_icons.py`。
4. `AGENTS.md`：若引入新命令/工作流要登记。
5. 更新 `docs/2026-10-11-plugin-pet-capability-gap.md`，把已完成的项标记为「已实现」，
   并留一节记录**与本文档的偏差**。

---

## 4. 全局验收标准

- [ ] `python -m pytest tests/ -q` 全绿（基线若是红的，至少不能新增红项）。
- [ ] `python tools/gen_plugin_api_docs.py --check` 返回 0。
- [ ] `python tools/gen_plugin_ui_icons.py --check` 返回 0。
- [ ] `data/plugins/` 下两个既有插件仍能被 `load_all()` 正常加载。
- [ ] **一个注册 ambient 的临时样例插件**验证通过：不抢占焦点、ESC 不影响、
      不推挤布局、surface 打开时被降级标记、禁用后立刻消失（**本文件最重要的一条**）。
- [ ] 改一张卡 → `api.on('card.updated')` 收到；跑一次扫描 → `api.on('scan.completed')` 收到。
- [ ] 重装 `hello-world` 后 `data/plugins/hello-world/data/` 下的文件仍在。
- [ ] 插件资产 `If-None-Match` 返回 304。
- [ ] 没有引入任何新依赖（`requirements.txt` / `package.json` 不变）。
- [ ] 所有新增前端样式只用 `.color-*` 语义类与既有 CSS 变量；`plugin-surfaces.css`
      无 z-index 字面量、无 `backdrop-filter`。
- [ ] `api_version` 仍为 `2`（D0）。
- [ ] 没有改动 `D:\Workspace\MyOwn\ST-Manager-AI-Assistant`。

---

## 5. 已知陷阱清单（踩过或差点踩的）

1. **`SURFACE_TYPES` 被恰好 3 条断言锁死**（D2.1 的逐行核对表）。
   只改代码不改测试会红 3 条；`test_plugin_surface_contracts.py:221` 与
   `test_plugin_entry_registry_frontend_contracts.py:83` 读起来像跨端一致性检查，
   **实际两边都是后端变量，是同义反复**，不要被措辞误导去动它们。
2. **`entryRegistry.js:30` 与 `pluginSurfaceHost.js:23` 是两份 `SURFACE_TYPES`**。
   只改后者，运行期 `api.surfaces.register('x', {type:'ambient'})` 会在
   `entryRegistry.js:574` 被静默降级成 `panel`——表现为「宠物变成了一个抽屉」，很难查。
3. **`pointer-events` 是继承属性**（`entry-dock.css:435` 的实测记录）。ambient 容器整体
   `none` 之后，**每个**可交互子元素都必须显式取回 `auto`，否则「点了没反应」。
4. **`tests/test_plugin_assets.py:45` 断言 `Cache-Control == 'no-cache'`**。
   改缓存策略必须同步改，否则红。
5. **`settingsHelpContent` 是硬闸门**（`settingsModal.js:304-306`）。
   新增设置分区必须同时加键，否则 `selectSettingTab` 静默 no-op。D7 已选择挂在既有
   `plugins` 分区内规避这条。
6. **`docs/plugin-api.md` 是生成物**。改 `buildApi()` 的顶层成员必须改
   `tools/gen_plugin_api_docs.py` 并重跑，否则 `tests/test_plugin_api_docs.py` 红。
7. **不要在 ambient 上复用 `openSurface` 的代码路径**。它会建 header、设
   `role="dialog"`、装焦点陷阱、调 `setFullscreenScrim` —— 每一项对常驻图层都是错的。
   走独立挂载路径。
8. **SSE 广播不得阻塞核心流程**。`hooks.py:6-10` 的「同步派发、异常吞掉」是核心不变量；
   新增的广播必须是 fire-and-forget，不能让慢客户端拖住 `card.updated` 的调用方。
9. **不要用 `settings-saved` 事件**（`settingsModal.js:783`、`state.js:1375` 是宿主自身设置用的，
   消费方在 `cardGrid.js:291`、`presetEditor.js:291`）。
10. **PyInstaller 打包态** `static/` 是只读的 `_MEIPASS` 快照（`core/config.py:12-18`）。
    任何清单解析要读 `INTERNAL_DIR`。
11. **`data/` 被 gitignore**（`.gitignore:9`）。任何新增持久化应落在 `data/system/` 或
    `ui_data.json` 命名空间，不要落在 `static/`。
12. **全仓无 pytest 配置文件**：不要静默新增 `pytest.ini` / `pyproject.toml` / `setup.cfg`。
13. **不要在 `pluginSurfaceHost.js` 里给 `ambient` 走 `openSurface` 路径**，也不要把
    ambient 塞进任何「按 `SURFACE_TYPES` 遍历、逐个 open/close」的测试——
    `tests/test_plugin_surface_contracts.py:728` 目前用的是**硬编码字面量**
    `['panel','modal','page','sheet']`（不加 ambient 就不会波及），
    新增测试时也不要顺手把它改成遍历 `SURFACE_TYPES`，那会让模态语义用例去跑常驻类型。

---

## 6. 建议的执行顺序与停止点

```
阶段 0（文档冻结 + 测试基线）
   ↓
阶段 1（环境层 surface）      ← P0，最高价值；做完就可以开始写宠物插件
   ↓  ← 建议在这里停下来评审一次
阶段 2（事件通路）            ← P0
   ↓
阶段 3（data 存续）           ← P0，最小改动
   ↓
阶段 4（三项 P1）
   ↓
阶段 5（契约收尾，不可跳过）
```

- **阶段 1 做完就具备写宠物插件的最小前提**（容器 + 生命周期 + 层级）。
  此时可以先让宠物插件在「拖拽/下坠/行走/静息」四件事上跑起来，
  播报功能等阶段 2。
- **阶段 1 与 2 之间建议停下评审**：环境层是新增的架构面，值得先确认它真的是对的方向，
  再往上叠事件通路。

**每阶段结束报告格式**：

1. 改动文件清单（含行数变化）
2. 该阶段相关测试命令与结果
3. 与本文档的偏差（若有，说明原因）
4. 遗留问题与建议的下一步

---

## 7. 一句话提醒

本次的目标不是「让宠物能显示出来」，而是**把「常驻内容也归宿主管」这条契约立起来**。
如果做完之后，插件仍然需要自己写 `position: fixed` 才能常驻在界面上，
那这次就没做对——无论宠物最终能不能显示。
