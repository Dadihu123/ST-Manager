# 宠物插件 —— 设计与实现提示词

> 用途：把本文件整份交给一个全新的编码会话，在**宠物插件仓库**里按其执行。
> 目标仓库：新建（建议 `D:\Workspace\MyOwn\ST-Manager-Pet`，与 `ST-Manager-AI-Assistant` 同级）。
> 宿主仓库（**只读参考，不要修改**）：`D:\Workspace\MyOwn\ST-Manager`。
> 生成日期：2026-10-11。
> 设计依据：`ST-Manager/docs/2026-10-11-plugin-pet-capability-gap.md`（需求拆解与缺口分析）、
> `ST-Manager/docs/2026-09-22-plugin-system-design.md`（第 8 部分 F11–F16）、
> `ST-Manager/docs/plugin-api.md`（API 参考，生成物）。
> **本文件的宿主事实全部在 `ST-Manager@29aa4f4` 上实测过**，标注了证据。凡是本文写明的
> 契约，直接采用，不要重新猜、不要回宿主仓库翻代码去"验证一遍"（除少数明确标了
> 「需现场确认」的）。

---

## 0. 任务陈述

在宠物插件仓库里实现一个**官方宠物插件**：一只常驻在界面上的桌面宠物，会随宿主
状态活动、被拖动、被丢下会下坠、会自己行走、长时间没人理就睡着；用户能导入自己的
形象图；宿主里发生事情（卡片更新、扫描完成）时它会播报。

**这不是一个「能显示出来就算完成」的任务。** 判定标准是下面这一条：

> 插件**不得**自绘 `position: fixed` 浮层。所有常驻内容的容器由宿主的
> `ambient` surface 提供；插件只负责在容器内画东西、并管好自己的动画循环。

宿主侧为此专门立了契约（F16 / `--z-ambient` / `is-host-occluded` / 生命周期强制回收）。
如果你发现自己在写 `position: fixed`、在算 z-index、在处理 ESC 或焦点——说明用法错了，
停下来回去读 §2.1。

### 0.1 明确**不做**的（防止越界）

| 项 | 理由 |
|---|---|
| 修改宿主仓库任何文件 | 宿主契约已冻结在 `29aa4f4`；宠物需求宿主侧已全部补齐。发现宿主 bug → 记录在 `docs/HOST_FEEDBACK.md`，不要就地改 |
| 让宿主解析宠物包格式 | 宿主不解析动画清单、帧数、fps——那是插件内部领域模型 |
| 要求宿主 `config_schema` 支持 `array` / `object` | 形象管理需要预览、拖拽排序、必要动作齐全性校验，宿主通用表单满足不了。**自带 UI 更合理** |
| 移动端常驻图层 | 宿主在移动端**不挂载** ambient（见 §2.1）。移动端做降级形态，不要试图绕过 |
| 物理引擎 / 骨骼 / 寻路 的宿主侧支持 | 纯插件侧。宿主只给容器、资源通路、生命周期、状态广播 |
| 桌面通知 / 系统级提醒 | 不在插件系统范围。用 `api.toast()` |
| 「勿扰开关」的宿主实现 | 宿主侧未做（需产品决策）。**插件侧自己实现**（见 §4.4） |

---

## 1. 硬约束

### 1.1 仓库与工具链

- 本仓库是**插件仓库**，不是宿主仓库。`manifest.json` 在仓库根。
- 目录布局对齐 `ST-Manager-AI-Assistant`（已装插件 `data/plugins/stm-ai-assistant` 可作参照）：

```
<repo-root>/
├─ manifest.json          # 插件清单（必需）
├─ README.md
├─ CHANGELOG.md
├─ LICENSE
├─ .gitignore
├─ backend/               # Python 包，__init__.py 里 def register(api)
├─ frontend/
│  ├─ plugin.js           # export async function activate(api)
│  ├─ plugin.css          # 必须带作用域（见 §1.3）
│  └─ assets/             # 图标等随包资源
├─ data/                  # 运行时用户数据（.gitignore，宿主保证更新时保留）
└─ tests/                 # pytest
```

- 宿主仓库的 `tools/new_plugin.py` 可生成骨架，**但它的模板有两处需要你手工修正**（已实测）：
  1. `manifest.json` 里 `api_version: 1` —— 当前宿主是 **2**，改成 `2`。
  2. 模板没有 `manifest_version`；建议加 `"manifest_version": 2`（对齐 ai-assistant）。
- **不引入打包器**（不要 webpack / vite / esbuild）。前端是浏览器原生 ESM，
  由宿主 `import()` 加载。没有 `package.json` 也没关系。
- 后端只用宿主已有依赖（Flask / Pillow 等已在宿主环境里）。**不要新增宿主未安装的第三方包**；
  若确需新增，必须在 README 里写明并同步通知宿主。

### 1.2 语言与风格

**Python**（对齐宿主 `AGENTS.md`）：

- 4 空格缩进；优先单引号；行宽 ~100–120；顶层函数之间两空行。
- import 顺序 stdlib / third-party / local，组间空行；不留无用 import。
- 命名：类 `PascalCase`、函数/变量 `snake_case`、常量 `UPPER_CASE`、私有前缀 `_`。
- `logger = logging.getLogger(__name__)`；文件 I/O / JSON / 网络**一律** try/except；
  优先具体异常、**禁止裸 `except:`**；可恢复 `logger.warning`、失败 `logger.error`。
- 路径用 `os.path.join()`；存储的相对路径用 `.replace('\\', '/')` 归一。
- 写中文 JSON 用 `ensure_ascii=False`。
- **不得**把 traceback 塞进 API 响应；返回 `jsonify()` 结构化错误。

**JavaScript**：

- 跟随 `frontend/plugin.js` 既有风格（2 空格缩进，与宿主插件 JS 一致）。
- 原生 ESM；不引入任何 npm 依赖。
- 只用 `api.*` 提供的宿主能力，**不要**去读 `window.Alpine.store` —— 那是 Provisional
  耦合，宿主改字段名你就静默失效。需要宿主状态用 `api.host.onState()`（§2.5）。

### 1.3 CSS 作用域（**宿主会静态检查，不过就拒绝加载整份样式**）

宿主在安装期扫描插件 CSS，**顶层裸选择器会被拒绝加载**（F11）。规则：

- 每一条规则的选择器必须以 `.plugin-<你的插件id>` 或 `[data-plugin="<你的插件id>"]` 为根。
  `api.createRoot()` 生成的容器自动带 `data-plugin`，`pluginHost.js` 也会给根加
  `plugin-<id>` 类。
- 允许 `@media` / `@supports` / `@layer` / `@container` 包裹（内部选择器同样要带作用域）；
  `@keyframes` / `@font-face` 内部豁免。

**另外三条声明层检查**（F13 / F15，只 warning 不拒绝，但留着就是技术债）：

| 检查 | 要求 |
|---|---|
| `position: fixed` | **不得出现**。常驻容器是宿主给的；宠物元素在容器内用 `position: absolute` 定位 |
| `var(--x)` 无回退值 | 引用的令牌必须在宿主令牌清单内，否则**必须**写回退值：`var(--content-primary, #fff)` |
| 硬编码 sprite | 不得写 `url('/static/icons/ui.svg#icon-x')`，用 `api.ui.icon(name)` |
| 非作用域选择器上的 `!important` | 避免；必要时先加作用域 |

**颜色只用 `.color-*` 语义类与既有 CSS 变量**，不写字面量颜色（宿主的
`test_color_system_contracts.py` 与 `test_plugin_surface_contracts.py` 在查这一条）。
**遵守 `prefers-reduced-motion`**（§4.5 有专门要求）。

### 1.4 测试

- 行为变更必须加/改 pytest（`test_*.py`）。
- 后端逻辑（包格式解析、回退链、物理积分、用户数据读写）**必须**有单测。
- 前端**没有** JS 测试运行器。宿主侧对插件 JS 的做法是：Node + 一份最小 DOM 垫片
  （见 `ST-Manager/tests/test_plugin_ambient_surface.py` 的 `DOM_SHIM`），直接驱动真实模块。
  **照抄这个模式**，不要引入 jsdom / vitest。
- 物理与动画的测试要**注入确定性时钟**（不要 `sleep` 后断言 elapsed——Windows 的
  `monotonic` 分辨率约 15.6ms，会 flaky）。宿主 `test_plugin_hooks.py` 有现成写法。

---

## 2. 宿主契约（**已实测，直接采用**）

> 全部在 `ST-Manager@29aa4f4` 上验证。证据摘要见 §7。

### 2.1 `ambient` 环境层 surface —— 宠物的容器

```js
export async function activate(api) {
  const key = api.surfaces.register('pet', {
    type: 'ambient',
    mount(container, ctx) {
      // container 是宿主的全屏透明层
      const pet = document.createElement('div');
      pet.className = 'pet-body';           // 样式写 .plugin-<id> .pet-body 之类
      container.appendChild(pet);
      return () => { /* 清理：cancelAnimationFrame、摘全局监听 */ };
    },
  });
  // 没有 api.surfaces.open('pet') —— 注册那一刻它已经挂在屏幕上了
}
```

**语义（与 `panel`/`modal`/`page`/`sheet` 每一项都相反，不要按对话框的心智模型写）**：

| 项 | ambient 的行为 |
|---|---|
| 触发 | **`register()` 即挂载**。没有 open/close 动作 |
| 容器 | `position: fixed; inset: 0`，全屏透明层，**整体 `pointer-events: none`** |
| 层级 | `var(--z-ambient)` = **55**（高于卡片选中态 50，低于 surface 60 / 坞 80 / 模态 1000+）。**你不需要也不得自己设 z-index** |
| 对话框语义 | **无** `role="dialog"`、无 `aria-modal` |
| 焦点 | **完全不碰**。挂载不改变 `document.activeElement`，不装焦点陷阱 |
| ESC | **忽略**（不会关闭你） |
| 全屏遮罩记账 | **不参与**（不会给 `body` 加 `has-fullscreen-scrim`） |
| 头部 / 关闭按钮 | **不渲染**（你要给自己的宠物做交互，就在容器内自绘，但**不要**做"关闭宠物"的窗口按钮） |
| `data-marquee-ignore` | 容器带（框选不会命中宠物） |
| 回收 | 插件 **disable / unload / destroy** 时宿主**强制** unmount，不依赖你的 `deactivate` |

**两个必须内化的细节**：

1. **`pointer-events` 是继承属性。** 容器整体 `none`，所以你在容器里放的**每一个**可交互
   子元素都必须显式取回：
   ```css
   .plugin-<id> .pet-body { pointer-events: auto; }
   ```
   漏掉的表现是「拖不动 / 点了没反应」。宿主入口坞踩过同一个坑并留有实测记录。

2. **父容器是 `position: fixed`，但你自己的 CSS 里不得出现 `position: fixed`**（F13 会
   warning）。宠物元素在容器内用 `position: absolute` + `transform: translate3d()` 定位。

**移动端不挂载**：`register()` 直接返回空串（`""`）并 `console.warn`。移动端屏幕小、
常驻图层会遮挡内容且没有"挪开"的手段。**插件必须处理这个返回值**（见 §4.6）。

**判定是否可用**：`hostFeatures()` 在桌面/平板产出 `hasAmbient`，移动端不产出。
但那是给 `entries[].when.feature` 用的；**ambient 注册本身没有 `when`**，你要自己判断：

```js
const key = api.surfaces.register('pet', { type: 'ambient', mount });
if (!key) {
  // 移动端/不支持：降级形态（见 §4.6）。不要 throw，不要 toast 报错。
  api.host.log('ambient 不可用，已降级', 'info');
}
```

### 2.2 核心事件（后端 → 浏览器，经 SSE）

```js
const off = api.on('card.updated', (payload) => {
  pet.react('happy');            // payload 是后端 hooks.emit() 的原样对象
});
// off() 取消订阅；连接随插件销毁自动断开，无需手动清理
```

**这条通路是本次新修好的**——在此之前 `api.on('card.updated', h)` 永远不会被调用
（前端只做 `window.addEventListener`，与后端 `hooks.emit` 是两条独立总线）。

| 项 | 行为 |
|---|---|
| 可用事件名 | `app.ready`、`card.created`、`card.updated`、`card.deleted`、`card.moved`、`tag.applied`、`tag.deleted`、`worldbook.saved`、`worldbook.entry_changed`、`scan.completed`、`index.job_done` |
| 连接 | **懒连接**：首次订阅核心事件才建立。**每插件一条流**，N 次 `api.on()` 复用同一条 |
| 回收 | 随插件销毁自动断开 |
| 自定义事件 | `api.emit()` 的 `<id>:` 事件**不进**这条流（那是同页面内的 best-effort 通信）。同页面的 `api.on('你的id:xxx', h)` 仍走 `window` CustomEvent，行为不变 |

**播报重点用 `scan.completed` / `index.job_done`**——它们**没有任何 UI 动作触发**，
在这条通路之前前端无从得知操作已完成。这两个最能体现通路价值。

**不要**用前端 `window` 事件（`card-updated`、`refresh-card-list` 等）做播报：那是 UI 本地
信号，覆盖不全。宿主文档 `docs/plugin-api.md` 的「前端 window 事件（Provisional）」一节
列了它们，但核心事件一律走 `api.on()`。

### 2.3 宿主状态广播

```js
const off = api.host.onState((state) => {
  if (state.busy) pet.calm();                     // 宿主忙 → 安静
  if (!state.surfaceOpen) pet.resume();
  pet.setReducedMotion(state.reducedMotion);      // 尊重系统「减少动效」
});

// {
//   mode: 'cards',          // 当前视图
//   deviceType: 'desktop',  // 'desktop' | 'mobile'
//   darkMode: true,
//   scrimActive: false,     // 全屏遮罩活跃
//   surfaceOpen: false,     // 有对话框型 surface 打开（ambient 不算）
//   busy: false,            // 批处理 / 索引构建 / 全量扫描进行中
//   reducedMotion: false,   // 系统「减少动效」偏好
//   visible: true,          // 页面可见性
// }
```

- 首次订阅**立即**推一次快照（你不必自己先探一次）。
- 之后变化时推送，**已合并去抖**（一帧一次）——你可以在 handler 里放心做较重的响应。
- `reducedMotion` 会在用户改系统设置时**立即**推送，无需刷新页面。
- 同上，取消订阅函数 `off()`。

**这条替代了「自己去读 store」**，请务必用它。若你确实需要地图/UI 的其他字段，
在 `docs/HOST_FEEDBACK.md` 里记"希望 `onState` 增加 X"，而不是偷偷读 store。

### 2.4 插件私有数据（`api.data_dir()`）

```python
# 后端
data_dir = api.data_dir()      # → data/plugins/<id>/data/，不存在时自动创建
```

- **宿主现在保证插件更新时保留这个目录**（本次新修）。旧行为是整个目录被原子替换、
  用户数据全丢——`api.data_dir()` 是宿主官方承诺的目录，承诺了却保不住是契约级缺陷。
- 合并规则：**用户数据优先**。若新包也带了同名文件，用户那份保留，新包那份被宿主改名
  为 `<name>.plugin-default`。所以：**不要把默认资源放 `data/`**，放 `frontend/assets/`
  或包里的 `resources/`，否则每次更新都会在用户目录留一堆 `.plugin-default`。
- **用户上传的形象图必须落在 `data_dir()` 里的文件**，不要塞进 `api.storage`：
  `storage` 与 `ui_data` 的命名空间有 **256KB** 配额（`PLUGIN_DATA_QUOTA_BYTES`），
  超了整次写入被拒绝（HTTP 413）。文件系统没有这个限制。

### 2.5 静态资源通路（**性能关键**）

```js
api.utils.toAbsoluteAssetUrl('frontend/assets/pet/idle.png')
// → /api/plugins/<id>/assets/frontend/assets/pet/idle.png?v=<版本>
```

**已实测的行为**（本次新修）：

| 项 | 值 |
|---|---|
| 条件请求 | `If-None-Match` → **304**；`If-Modified-Since` → **304** |
| 分段请求 | `Range: bytes=0-9` → **206** |
| 缓存 | `Cache-Control: private, max-age=31536000, immutable` |
| URL 版本化 | 宿主自动追加 `?v=<插件版本>`（`pluginHost` 对 `frontend.entry` / `styles` 做；你自己拼 URL 时用 `api.utils.toAbsoluteAssetUrl`） |

**允许的扩展名（白名单）**：
`.js` `.mjs` `.css` `.svg` `.png` `.webp` `.gif` `.avif` `.json` `.woff2` `.map`

> **注意：`.jpg` / `.jpeg` 不在白名单里。** 用户的形象图若是 JPEG，两种处理方式：
> ① 上传时用 Pillow 转成 PNG/WebP 存盘（推荐，顺带可以裁剪/缩放）；
> ② 走你**自己的后端路由**返回（`@api.route('/avatar/<name>')` 前缀是
> `/api/plugins/<id>`，不受资产白名单限制——但要自己防路径穿越，见 §3.4）。
>
> 图标位（`entries[].icon`）另有更窄的子集 `.svg/.png/.webp`——图标是 16–24px 的
> mask 渲染，`.gif`/`.avif` 作图标无意义。

**分帧动画务必用 spritesheet + `background-position`**，不要换 `<img src>`：换 `src` 会走
网络与解码，换 `background-position` 只改绘制。现在上游有 304/206 与强缓存，这张表
只会被真正下载一次。

### 2.6 入口（可选，但播报/设置通常需要）

```json
{
  "frontend": {
    "entries": [
      {
        "id": "pet-settings",
        "kind": "settings",
        "label": "宠物设置",
        "surface": { "id": "settings-panel", "type": "modal", "size": "lg" }
      }
    ]
  }
}
```

| kind | 宿主渲染落点 |
|---|---|
| `settings` | 插件管理页内的「插件设置入口」区块（**本次新实现**） |
| `dock` | 入口坞槽位 |
| `context` | 右键菜单 |
| `command` | 命令面板 |
| `batch` | 批量操作菜单 |
| `nav` / `status` | **宿主未实现**，不要用 |

**`settings` 之外还有一种做法**：宠物的设置面板可以直接由宠物本体触发（右键宠物 →
浮出自绘面板）。宿主不禁止在 `ambient` 容器内自绘面板——但那是个**全屏透明层**，你自己
处理点击外部关闭、并且注意容器 `pointer-events: none`（面板要取回 `auto`）。
更省事的做法是用 `settings` 入口 + `modal` surface（宿主给你 header、焦点陷阱、ESC）。

**`when` 条件**（可门控入口可见性，宿主替你求值）：
`mode` / `selection` / `indexState` / `config.requireKeys` / `hostVersion` / `feature` / `target`。
例如 `"when": { "feature": ["hasAmbient"] }` 让入口在移动端自动置灰。

**manifest 里不要写 `"surface": { "type": "ambient" }`** —— 后端 `SURFACE_TYPES` 只允许
`panel`/`modal`/`page`/`sheet`（`entries[]` 是"用户可见入口"，而 ambient 注册即挂载、
没有用户可见入口）。写了会被丢弃该项 + warning。

### 2.7 后端路由

```python
# backend/__init__.py
from flask import jsonify, request

def register(api):
    @api.route('/pets', ['GET'])
    def list_pets():
        return jsonify({'success': True, 'items': [...]})
```

- 前缀自动是 `/api/plugins/<id>`，前端用 `api.api('/pets')` 调用（自动带 CSRF 头、
  以 `data.success` 判定成败）。
- 注册发生在 `finalize()`；规则冲突会被拒绝并记 error。不要注册宿主已有路由。
- 宿主**没有**全站 CSRF 强校验，但**仍然**按 §3.4 做自己的输入校验。

### 2.8 manifest 白名单（**写错键会被拒绝加载**）

顶层允许的键：
`id` `name` `version` `api_version` `manifest_version` `author` `description`
`homepage` `license` `icon` `min_app_version` `backend` `frontend` `permissions`
`requires` `config_schema` `secret_schema` `i18n`

- `id` 必须匹配 `^[a-z][a-z0-9-]{1,63}$`，且**等于目录名**。
- `api_version` 填 **2**。
- `permissions` 白名单：`cards.read` `cards.write` `worldbook.read` `worldbook.write`
  `tags.read` `tags.write` `secrets.read` `network.outbound` `jobs.run`。
  **宠物插件不需要任何一条**（它不读卡片、不联网）—— 权限目前只做声明与审计，
  不是执行门控，但声明了就要在 README 里解释用途。宁少勿多。
- `config_schema` 只支持 `string` / `integer` / `number` / `boolean` / `enum`，
  以及 `required` / `properties`。**不支持 `array` / `object`**（形象列表这类结构必须自带 UI，
  宿主通用表单渲染不了）。允许的键：`type` `title` `description` `default` `minimum`
  `maximum` `enum` `secret` `required` `properties`。

### 2.9 生命周期与回收

- `activate(api)` 的**返回值**会被记录为插件级 disposer：返回函数，或返回带
  `dispose()` 的对象。
- 插件被禁用 / 卸载 / 重载时，宿主按此顺序回收：
  `ambient 强制 unmount` → `disposer 列表` → `deactivate(api)` → 摘除容器与注入的样式。
- **你必须**在 disposer 里：`cancelAnimationFrame`、摘掉所有全局监听
  （`window` / `document` 上的 resize、pointermove、visibilitychange）、
  断开你自己建的 `EventSource`/`WebSocket`（如果有）。
- **不要**依赖 `deactivate`——ambient 的卸载由宿主强制完成，不保证先调你的钩子。

---

## 3. 宠物包格式（**这是插件侧领域模型，宿主完全不解析**）

### 3.1 设计目标

1. **任何一张单帧图都能跑起来**——缺失的动作沿回退链下溯，最终一定落到 `idle`。
2. 用户能导入自己的形象；能覆盖单个动作的图。
3. 格式**向前兼容**：多出来的字段忽略而不是报错。

### 3.2 建议格式（可调整，但要写进 README 并冻结）

```json
{
  "format": 1,
  "id": "my-pet",
  "name": "小猫",
  "author": "",
  "size": { "w": 64, "h": 64 },
  "anchor": { "x": 0.5, "y": 1.0 },
  "physics": {
    "gravity": 1800, "walkSpeed": 60, "friction": 0.85,
    "terminalVelocity": 2400, "bounce": 0.15
  },
  "animations": {
    "idle": { "sheet": "idle.png", "frames": 4, "fps": 6,  "loop": true },
    "walk": { "sheet": "walk.png", "frames": 6, "fps": 10, "loop": true },
    "fall": { "sheet": "fall.png", "frames": 2, "fps": 8,  "loop": true },
    "drag": { "sheet": "drag.png", "frames": 2, "fps": 4,  "loop": true },
    "land": { "sheet": "land.png", "frames": 3, "fps": 12, "loop": false }
  }
}
```

- `anchor`：贴图内哪个点对齐世界坐标（`0.5, 1.0` = 底边中点，脚踩地）。
- `sheet`：**水平排布的 spritesheet**（帧 0..n-1 从左到右）。垂直排布用 `"layout": "vertical"`。
- `size`：单帧的逻辑尺寸（CSS px）。贴图实际像素可以是它的 N 倍（高分屏用 2x 帧）。
- 建议支持 **`assets/` 相对路径**与 **`data_dir()` 用户覆盖**两层：
  用户覆盖优先，缺失则回落到包内默认。

### 3.3 动作词表与回退链（**照抄，这是契约**）

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
「必要动作」的真正含义不是「不给就报错」，而是**「不给就退化为静态位移」**。
解析器必须实现这条链，并对"连 idle 都没有"给出**可读的**错误（`user_msg` 面向用户、
`hint` 面向作者）。

### 3.4 导入安全（**必须做**）

用户能导入图片与包，这是**不可信输入**。必须：

1. **路径穿越**：`os.path.realpath` 后校验在 `data_dir()` 内。宿主有
   `core/utils/paths.py:is_under_base()` 可参照实现（但插件仓库不能 import 宿主模块——
   自己写一份等价的、有单测的实现）。
2. **图片解码炸弹**：用 Pillow 打开后用 `Image.MAX_IMAGE_PIXELS` 限制，
   并检查 `size` 上限（如 4096×4096）。
3. **只接受白名单格式**：上传时验证真实格式（读 magic bytes，不要信扩展名），
   转码成 PNG/WebP 存盘。
4. **体积上限**：单文件与单包都要有上限，超限返回结构化错误。
5. **包 JSON 解析**：`json.loads` 包在 try/except 里；字段类型逐个校验；
   `frames` 必须是合理正整数；拒绝 `sheet` 里的绝对路径与 `..`。

---

## 4. 运行时行为要求

### 4.1 物理与运动

在 ambient 容器内，坐标系就是**视口**（容器 `inset: 0`）。因此：

- 地面 = 容器底边（`container.clientHeight`），要监听 resize 重算。
- 用 `transform: translate3d(x, y, 0)` 位移（走合成层，不触发 layout）。
- `will-change: transform` **只在运动期间加**，停下就摘掉（常驻会占显存）。
- 拖拽：`pointerdown` 在宠物上（记得 `pointer-events: auto`）→ `setPointerCapture`
  → `pointermove` 跟手 → `pointerup` 交回物理（给一个初速度，让它有"甩出去"的手感）。
- 物理积分用 **固定步长**（如 1/120s）+ 累加器，不要用可变 `dt` 直接积分——
  掉帧时可变步长会让物理表现依赖帧率。

### 4.2 动画循环

- **一个 rAF 循环**驱动一切（物理 + 帧推进 + 状态机），不要每个动作一个定时器。
- 帧推进用**时间累加**（`accumulator += dt; while (accumulator >= 1/fps) {...}`），
  不要 `setInterval`——掉帧时不会累积漂移。
- **空闲降频**：`idle` 且无输入时降到 4–6fps；完全静止且无动画时可**停止 rAF**，
  被事件唤醒再重启（省电，笔记本用户会感谢你）。
- 像素风图加 `image-rendering: pixelated`。

### 4.3 状态机

明确定义状态与迁移，写在 README 里：

```
idle ⇄ walk（随机漫游 / 被指定移动）
idle → drag → fall → land → idle
idle → sleep（长时间无操作）→ idle（任何输入）
任意 → happy/sad/angry（事件播报，播完回 idle）
```

**必须**：任何状态都能被 `drag` 打断（用户抓它时立刻响应）。
**必须**：`sleep` 期间收到核心事件要唤醒（用户不会希望"因为宠物睡了所以没看到播报"）。

### 4.4 播报（含「勿扰」）

- 事件 → 动作映射由你决定，但要可配置：
  `card.updated` → `happy`；`scan.completed` → `idle` + toast；`index.job_done` → `idle`。
- `api.toast()` 是宿主提供的轻提示（有长度上限意识，别塞长文本）。
- **自实现「勿扰开关」**（宿主侧未做）：宠物设置里给一个 `quietMode` 配置，
  开启后只换动作、不弹 toast，且不在全屏遮罩期间打扰。
- **克制**：`card.updated` 在批量操作时会高频触发。必须**去抖/限流**
  （如 3 秒内最多一次播报），否则宠物会疯狂抽搐。

### 4.5 性能与省电（**验收项，不是"锦上添花"**）

在**下列任一条件**成立时，暂停动画或降到最低帧率：

| 条件 | 来源 |
|---|---|
| 页面不可见 | `onState().visible === false` |
| 系统「减少动效」 | `onState().reducedMotion === true` → **完全停止帧动画**，只保留静态显示 |
| 宿主忙（批处理/索引/扫描） | `onState().busy === true` → 降频 |
| 全屏遮罩 / 对话框打开 | `onState().scrimActive` / `surfaceOpen` → 降频或暂停 |
| 视口太小（如 `< 900px` 宽） | 自己 resize 判断 → 考虑不显示或缩小 |

另外宿主还会给 ambient 容器加 **`is-host-occluded`** 状态类（条件：遮罩活跃 /
任一对话框型 surface 打开 / `document.visibilityState !== 'visible'`）。
**这是宿主统一触发的，插件不得各自监听**——你只需在 CSS 里消费它：

```css
.plugin-<id> .pet-body {
  transition: opacity 0.2s ease;
}
.plugin-<id> .plugin-surface--ambient.is-host-occluded .pet-body {
  animation-play-state: paused;   /* 或降透明度、降频 */
}
```

`onState()` 与 `is-host-occluded` 有重叠，**以 `onState()` 为主做逻辑判断**，
`is-host-occluded` 作为 CSS 侧的兜底（它不必等你处理 JS）。

**`prefers-reduced-motion` 必须遵守**：不是"降速"，而是**关掉循环帧动画**，
只显示一帧静息图。仓库里已有的媒体查询就够：

```css
@media (prefers-reduced-motion: reduce) {
  .plugin-<id> .pet-body { animation: none; }
}
```

### 4.6 移动端降级

移动端 `register()` 返回 `""`（不挂载）。**不要**试图在移动端硬塞常驻图层。可选降级：

- 什么都不做（最省事，可接受）；
- 只在 `settings` 入口里放一个静态预览与配置；
- 提供一个"查看宠物"的 `modal` surface（用户主动打开，非常驻）。

选哪种要写进 README。**移动端不做常驻**是宿主的产品决策，不要在插件里绕过它。

---

## 5. 实施阶段

> 每阶段结束：跑该阶段测试 → 报告改动文件清单 + 测试结果 + 遗留问题。
> **每阶段独立可回滚。** 不要跳阶段。

### 阶段 0 — 仓库与事实核对（不改逻辑）

1. 建仓库骨架（§1.1）。`manifest.json` 的 `api_version` 写 **2**。
2. 加 `.gitignore`（至少 `data/`、`__pycache__/`、`*.pyc`、`.pytest_cache/`）。
3. **现场确认**（只有这三件事需要你去宿主仓库看/问）：
   - 宿主版本与 `api_version` 是否仍为 2（读 `ST-Manager/core/version.py`）。
   - `api.surfaces.register` 对 `type: 'ambient'` 的返回值语义（读
     `ST-Manager/static/js/pluginSurfaceHost.js` 的 `_mountAmbient`）。
   - `onState()` 的实际字段（读 `ST-Manager/static/js/pluginHost.js` 的
     `hostStateBroadcaster.snapshot`）。若字段与 §2.3 不符，**以宿主代码为准**并记录偏差。
4. 写 `docs/HOST_FEEDBACK.md`（空文件即可，用于记录宿主侧问题/期望）。
5. 建一个**最小 ambient 冒烟插件**：只 `register` 一个 ambient，放一个纯色方块。
   装到 `ST-Manager/data/plugins/<id>/`，重启宿主，在**真实浏览器**里确认：
   - 方块出现在屏幕上，且**不推挤**内容区（`.content-area` 布局不变）；
   - 打开一张卡片的详情页 → 容器带上 `is-host-occluded`（DevTools 里看）；
   - 在入口坞里禁用该插件 → 方块**立刻**消失；
   - 框选不命中它；Tab 不会掉进它里面；
   - **给方块加 `pointer-events: auto`，点它能触发 console.log**（验证取回生效）；
   - 缩到移动端宽度（或改 `deviceType`）→ 不挂载。

   **这七条是后续一切的地基，必须在写任何逻辑之前通过。** 若有不符，先记进
   `HOST_FEEDBACK.md` 并停下来确认，不要带着错误的容器认知继续写。

### 阶段 1 — 宠物包解析与回退链（纯后端/纯逻辑，无 DOM）

1. 实现包格式解析器（§3.2）+ 回退链（§3.3）。
2. 单测：完整包 / 缺可选动作 / 缺必要动作 → 回退 / 连 idle 都没有 → 可读错误 /
   畸形 JSON / 类型错误字段 / 向前兼容（多字段忽略）。
3. 单测：导入安全（§3.4）——路径穿越、超大图、伪造扩展名、体积超限。

**验收**：`pytest -q` 全绿；解析器对每个畸形输入都给出 `user_msg` + `hint`。

### 阶段 2 — 渲染与动画循环

1. ambient 挂载 + spritesheet `background-position` 帧推进（§4.2）。
2. `reducedMotion` / `visible` → 停绘；`busy` / `scrimActive` → 降频。
3. Node + DOM 垫片测试：帧累加不漂移（注入时钟）、rAF 在停绘后真的停、
   disposer 被调用后无残留 rAF。

**验收**：真实浏览器里，切到后台标签页再回来，宠物位置/帧序**不跳变**；
DevTools 的 Performance 里空闲时几乎无 rAF 活动。

### 阶段 3 — 交互与物理

1. 拖拽（`setPointerCapture` + 甩出初速度）。
2. 下坠 / 触地 / 摩擦 / 行走（固定步长积分，§4.1）。
3. resize 时重算地面与边界（宠物不能跑到屏幕外）。
4. 单测：物理积分（确定性时钟）、边界钳制、拖拽状态优先级。

**验收**：真实浏览器里拖动跟手、松手有下落与减速、窗口缩放后宠物仍在可见区内。

### 阶段 4 — 事件播报与宿主状态

1. `api.on()` 订阅核心事件 → 动作 + （可选）toast，含**限流**。
2. `api.host.onState()` → 驱动 §4.5 的降频/停绘表。
3. `sleep` 状态 + 任意输入唤醒 + 事件唤醒。
4. 自实现 `quietMode`。
5. 测试：限流（高频 `card.updated` 只播一次）、sleep 被事件唤醒、
   状态机非法迁移被拒。

**验收**：真实宿主里改一张卡 → 宠物反应；跑一次全量扫描 → 扫描结束时宠物有反应
（**这是最能证明后端通路的一条**，因为扫描没有 UI 动作触发）。

### 阶段 5 — 形象管理 UI（用户自定义）

1. `settings` 入口 + `modal` surface：形象列表、导入、预览、删除、设为当前。
2. 上传走后端路由 → Pillow 校验/转码 → 存 `data_dir()`。
3. 每个动作可单独覆盖（不强制用户提供全套）。
4. 必备动作缺失时的**清晰提示**（不要只置灰，要说清缺什么、会怎么回退）。
5. 测试：上传路径安全、转码产物存在、删除后回落默认、并发导入不互相覆盖。

**验收**：导入一张自己的图 → 宠物立刻换形象；重启宿主后仍是新形象；
插件"更新"（重装同一目录）后**形象仍在**（验证宿主的数据保留）。

### 阶段 6 — 打磨与文档

1. README：安装、宠物包格式、动作回退表、配置项、权限说明、移动端行为、
   性能策略、已知限制。
2. CHANGELOG。
3. 全量回归 + 真实浏览器走一遍 §0 的判定标准（无 `position: fixed`）。
4. 回填 `HOST_FEEDBACK.md`。

---

## 6. 验收标准

- [ ] **插件 CSS 里零个 `position: fixed`**（这条不过，整个任务就没做对）。
- [ ] 插件 CSS 全部带 `.plugin-<id>` / `[data-plugin="<id>"]` 作用域，能被宿主加载
      （安装后看 `style_scope_errors` 为空）。
- [ ] 宠物不推挤内容区布局；框选不命中；Tab 不掉进去；ESC 不影响；禁用后**立刻**消失。
- [ ] 桌面端显示、移动端不挂载且不报错。
- [ ] 拖拽跟手；松手有下坠与减速；窗口缩放后宠物在可见区内。
- [ ] 单帧图（只有 `idle`）也能跑起来，且行为合理（只位移不播帧）。
- [ ] 改一张卡 → `api.on('card.updated')` 触发宠物反应（**限流后**）。
- [ ] 跑一次扫描 → 扫描结束时宠物有反应。
- [ ] `reducedMotion` 开启 → 循环帧动画停止（不是降速）。
- [ ] 页面切后台 → rAF 停止；切回不跳变。
- [ ] 上传自己的图 → 生效；重启后仍在；插件重装后**仍在**。
- [ ] 长时间不动 → 睡着；任意输入 / 核心事件 → 唤醒。
- [ ] disposer 被调用后：无残留 rAF、无残留全局监听。
- [ ] 后端路由对路径穿越、伪造扩展名、超大图、体积超限都返回结构化错误（不暴露堆栈）。
- [ ] `pytest -q` 全绿。
- [ ] 没有引入任何 npm 依赖或打包器；没有新增宿主未安装的 Python 依赖。
- [ ] **没有修改宿主仓库任何文件**。

---

## 7. 宿主事实的证据（供你判断是否需要复核）

全部在 `ST-Manager@29aa4f4` 实测。挑几条最关键的：

**ambient 的语义**（`tests/test_plugin_ambient_surface.py`，24 个用例）：
注册即挂载 / 无 `role="dialog"` / 不改变 `activeElement` / ESC 不关闭 /
不给 `body` 加 `has-fullscreen-scrim` / 带 `data-marquee-ignore` /
`is-host-occluded` 随对话框开合与页面可见性切换 / 移动端不挂载 /
`closePlugin` 后 DOM 干净。

**五条手工验收**（真实 JS 模块 + DOM 垫片，全 PASS）：
不推挤 `.content-area`；框选不命中；Tab 不掉进去（无焦点陷阱）；对话框打开时被
`is-host-occluded` 标记且关闭后摘掉；禁用后立刻消失。

**资产通路**（`create_app()` + Flask test client，对 `stm-ai-assistant` 的
`data/probe/avatar.png` 实测）：

```
GET  assets/data/probe/avatar.png          → 200, image/png, len=75
  Cache-Control: private, max-age=31536000, immutable
  If-None-Match: <etag>                     → 304
  Range: bytes=0-9                          → 206
GET  assets/data/probe/notes.txt            → 404（非白名单）
```

**宿主页面无 CSP**（实测 `/` 的响应头只有 `X-Content-Type-Options` 与
`Referrer-Policy`）→ 插件可用 `blob:` / `data:` / 同源 URL 显示用户图片。

**但插件资源自身的响应带 `Content-Security-Policy: default-src 'none'; img-src 'self' data:;
style-src 'unsafe-inline'; font-src 'self'; sandbox`**（实测，`core/utils/security_headers.py`
的 `PLUGIN_ASSET_CSP`；触发条件是路径以 `/api/plugins/` 开头且含 `/assets/`）。
这条只影响**该资源被当作文档加载**的场景：

- `<img src="...">` / CSS `background-image: url(...)`：**不受影响**（图片是外部资源，
  按宿主页面的策略加载）——这是宠物插件的主路径，已实测 5/5 格式可用（含 `.gif`/`.avif`）。
- `fetch()` 拿到文本后 `innerHTML` 注入（典型是内联 `.svg`）：**会踩到 `sandbox`**——
  裸 `sandbox` 让文档拿到不透明源，`'self'` 与 `CORP: same-origin` 都不再匹配。
  **需要内联 SVG 时用 `api.ui.icon(name)` 或 `<img>`，不要 fetch + innerHTML。**
- `sandbox` 不含 `allow-scripts`：**不要指望资产里的 JS 能执行**。宠物逻辑全部写在
  `frontend/plugin.js` 里，资产只放静态资源。

`api.utils.toAbsoluteAssetUrl(relPath)` 会拼上正确的 `?v=<版本>`，**自己拼 URL 时用这个
函数**，不要手写路径。

**核心事件通路**（`tests/test_plugin_events.py`，24 个用例）：事件能到达订阅者 /
插件自定义事件**不进**流 / 广播满队列时丢最旧且**不阻塞**派发方 /
配额超限返回 `429 + sse_limit_reached` / 断开释放配额 / 心跳。

**`api_version` = 2**（`core/version.py`）。**记录 `/api/plugins/events` 是目前唯一的
核心事件前端通路**，没有轮询降级（核心事件是广播，没有历史可查）——
浏览器若无 `EventSource`，宿主会 `console.warn` 且你收不到事件。

---

## 8. 已知陷阱清单（宿主侧踩过或差点踩的）

1. **`pointer-events` 是继承属性。** ambient 容器整体 `none`，**每个**可交互子元素
   都要显式 `auto`。宿主入口坞踩过（`entry-dock.css` 有实测记录），表现为「点了没反应」。
2. **不要在 ambient 上用对话框的心智模型。** 没有 open/close、没有 ESC、没有焦点陷阱、
   没有 header。你「打开设置面板」要靠 `entries` + `modal` surface，或在容器内自绘并
   自己处理外部点击关闭。
3. **`.jpg` / `.jpeg` 不在资产白名单。** 用户图必须转码成 PNG/WebP 存盘，
   或走自己的后端路由返回。
4. **`storage` / `ui_data` 有 256KB 配额，超了整次写入被拒绝（413）。**
   用户图片必须落 `data_dir()` 里的文件。
5. **不要把默认资源放 `data/`。** 更新时用户数据优先，新包同名文件会被改名成
   `<name>.plugin-default` —— 每次更新留一堆垃圾。
6. **manifest 里写 `"surface": {"type":"ambient"}` 会被丢弃**（后端只允许四种），
   而且不会报错，只在日志里 warning。
7. **`api.on()` 的核心事件是 SSE，懒连接、每插件一条流。** 不要为每个事件建一条连接；
   不要指望有轮询降级。
8. **控制台编码**：Windows 终端默认 GBK，脚本里 `print` 中文会乱码。要产出可读报告
   就写 UTF-8 文件，不要靠 stdout。
9. **宿主没有全站 CSP —— 但这不意味着你可以不校验输入。** 用户上传是不可信输入，
   §3.4 的六条必须全做。
10. **物理不要用可变 `dt` 直接积分**（帧率决定表现）；**动画帧推进不要用 `setInterval`**
    （掉帧累积漂移）。
11. **`card.updated` 会高频触发**（批量操作）。播报必须限流，否则宠物疯狂抽搐。
12. **不要依赖 `deactivate` 做清理**——ambient 卸载由宿主强制完成，顺序是
    `unmount → disposer → deactivate`。清理写在 disposer 里。
13. **`reducedMotion` 不是「降速」而是「停」**。用户开这个选项是因为动效让他不适。
14. **移动端不要绕过**——宿主 `register()` 返回空串是刻意的产品决策。
15. **插件仓库不要 import 宿主模块。** 宿主代码在部署时可能不可达（打包态 `_MEIPASS`）。
    需要什么就自己写一份（如 `is_under_base`），并配单测。

---

## 9. 建议的执行顺序与停止点

```
阶段 0（骨架 + 事实核对 + 最小 ambient 冒烟验证）
   ↓
阶段 1（包格式 + 回退链 + 导入安全）      ← 纯逻辑，最易测
   ↓
阶段 2（渲染 + 动画循环 + 省电）
   ↓  ← 建议在这里停下来评审一次：此时宠物已经"活着"了，先确认
   ↓     观感、帧率、省电行为是不是你要的，再叠交互
阶段 3（拖拽 + 物理）
   ↓
阶段 4（事件播报 + 宿主状态）
   ↓
阶段 5（形象管理 UI）
   ↓
阶段 6（打磨与文档）
```

- **阶段 0 的七条浏览器验证不可跳过。** 后面所有代码都建立在"容器行为符合预期"之上。
- **阶段 2 后建议停一次**：动画观感与省电策略是主观的，早发现比晚返工便宜。

**每阶段结束报告格式**：

1. 改动文件清单（含行数变化）
2. 该阶段相关测试命令与结果
3. 与本文档的偏差（若有，说明原因；以宿主实际代码为准时要写明）
4. 遗留问题与建议的下一步

---

## 10. 一句话提醒

宿主已经把「常驻内容也归宿主管」的契约立起来了——**容器、层级、生命周期、资源通路、
状态广播、数据存续都在宿主手里**。你要做的是往里画一只会动、会反应、会记住用户形象的宠物，
并且**在省电与克制上比用户更自觉**。

如果写完发现自己又写了 `position: fixed`、又在算 z-index、又在处理 ESC——
那不是宠物插件该干的事，回去读 §2.1。
