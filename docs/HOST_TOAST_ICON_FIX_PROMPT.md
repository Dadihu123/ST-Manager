# 修复提示词：`api.toast` 的图标位不支持插件自带图标

> 用途：把本文件整份交给一个在 **ST-Manager 主程序仓库**里工作的会话，按 §5 的方案修复。
> 目标仓库：`D:\Workspace\MyOwn\ST-Manager`（**本次要改的就是它**）。
> 证据来源：宠物插件仓库 `D:\Workspace\MyOwn\ST-Manager-Pet`（只读参考，不要改它）。
> 发现日期：2026-10-11。基准 commit：`1e19a5f`。
> 本文所有事实都在 `1e19a5f` 上**读过源码 / 在真实浏览器里跑过**，标注了证据位置。

---

## 0. 一句话问题

`api.toast(msg, duration, icon)` 的 `icon` 参数只能填 **16 个写死的宿主图标名**，
插件自带图标（哪怕已经在 `entries[].icon` 里合法使用）**无法**用于通知，
且失败时**静默无提示**。

这不是「插件用法不对」，是宿主侧的一处实现缺口 —— 证据见 §2。

---

## 1. 复现（3 步，可独立验证）

```bash
# 1. 在你自己的仓库里，把插件装上（任一插件都行；用现成的 stm-ai-assistant 也行）
#    然后在任意页面的 DevTools Console 里执行：

Alpine.store('global').showToast('测试通知', 4000, 'heart')
#  → 通知弹出来了，但**图标位是空的**。控制台没有任何警告。
#    'heart' 是真实存在的宿主图标（static/icons/ui.svg 里有 icon-heart）

Alpine.store('global').showToast('测试通知', 4000, 'check')
#  → 有对勾图标。'check' 在白名单里。

Alpine.store('global').showToast('测试通知', 4000, 'frontend/assets/icon.svg')
#  → 图标位空的。插件自带图标路径被丢弃。
```

规模对比（实测，见 §2.5）：

| | 数量 |
|---|---|
| 宿主可解析的图标名（`iconMap.js` / `core/plugins/icons.py`） | **192** |
| toast 接受的图标名（`TOAST_ICON_NAMES`） | **16** |
| **被拒比例** | **91.7%** |

---

## 2. 现状与证据（逐条给出文件与行号，不要回退重猜）

### 2.1 判定逻辑

`static/js/state.js:1686-1706`（`showToast`）：

```js
showToast(msg, duration = 3000, iconName = "") {
  if (typeof duration === "string") duration = 3000;
  this.toastMessage = msg;
  const normalizedIconName = String(iconName || "").trim();
  const hasIcon = TOAST_ICON_NAMES.has(normalizedIconName);   // ← 只看白名单
  this.toastIcon = hasIcon ? normalizedIconName : "";         // ← 不在就置空
  this.toastIconHref = hasIcon
    ? TOAST_ICON_IMAGES[normalizedIconName] ||
      TOAST_ICON_SPRITES[normalizedIconName] ||
      `ui.svg#icon-${normalizedIconName}`
    : "";
  this.showToastState = true;
  ...
}
```

`static/js/state.js:71-95`（白名单本体，**16 项**）：

```js
const TOAST_ICON_SPRITES = Object.freeze({
  "backup-rollback": "detail.svg#icon-backup-rollback",
  "tags": "detail.svg#icon-tags",
  "link-source": "detail.svg#icon-link-source",
});
const TOAST_ICON_IMAGES = Object.freeze({
  "loading-animation": "loading-animation.svg",   // ← 独立动效 SVG，不是 sprite
});
const TOAST_ICON_NAMES = new Set([
  "forbidden", "card-send-to-st", "sillytavern", "tauritavern", "folder",
  "loading-animation", "close", "trash", "check", "settings-help-entry",
  "settings-save", "alert-triangle", "clipboard", "snapshot",
  ...Object.keys(TOAST_ICON_SPRITES),
]);
```

### 2.2 渲染处只有 `<use>` 一条路径

`templates/layout.html:48-74`：

```html
<div class="toast-notification" :class="{'show': showToastState}">
  <span x-show="toastIcon" aria-hidden="true">
    <template x-if="toastIcon === 'loading-animation'">
      <img class="ui-icon ui-icon--sm ui-loading-icon"
           :src="'{{ url_for('static', filename='icons/') }}' + toastIconHref" ... />
    </template>
    <template x-if="toastIcon && toastIcon !== 'loading-animation'">
      <svg class="ui-icon ui-icon--sm" viewBox="0 0 24 24" ...>
        <use :href="'{{ url_for('static', filename='icons/') }}' + toastIconHref"></use>
      </svg>
    </template>
  </span>
  <span x-text="toastMessage"></span>
</div>
```

注意两点：

- 前缀 `'/static/icons/'` 是**模板里硬拼**的 —— 因此白名单**不提供**任何安全边界
  （它不参与路径校验，插件想写什么名字都会被拼到前缀后面）。
  真正的路径校验在 `utils/icons.js:resolvePluginIcon()`（它已实现拒绝绝对路径、
  拒绝 `..`、扩展名收窄）。
- **`<use>` 只能引用宿主 sprite 里的 `<symbol>`**，这就是插件图标用不了 toast 的直接原因：
  插件 SVG 是**填充式**（`fill: currentColor`），宿主 sprite 是**描边式**
  （`fill: none; stroke: currentColor`），塞进 `<use>` 会渲染成**空图形**。
  宿主自己在 `static/js/uiPrimitives.js:54-56` 写了这条注释。

### 2.3 插件图标在**别处**是合法且被支持的 —— 只有 toast 不一致

`static/js/utils/icons.js:1-15, 99-111`（`resolveIcon`）：

```
命名空间区分（硬规则，设计文档 2.2「图标名契约（D4）」）：
- 宿主图标名**不含** `/` 与 `.`（如 `wand`）      → { kind: 'host',  href }
- 插件自带资源路径**必含** `/`（如 assets/logo.svg）→ { kind: 'asset', url }
```

`kind: 'asset'` 的渲染方式由调用方决定，`uiPrimitives.js:70-77` 就是这么做的：

```js
if (resolved.kind === "asset") {
  const span = el("span", { className: `${className} ui-icon--asset` });
  span.style.setProperty("--ui-icon-mask", `url("${resolved.url}")`);
  return span;
}
```

配套 CSS 在 `static/css/modules/icons.css:42-47`：

```css
.ui-icon.ui-icon--asset {
  background-color: currentColor;
  -webkit-mask: var(--ui-icon-mask) center / contain no-repeat;
  mask: var(--ui-icon-mask) center / contain no-repeat;
}
```

**后端也有同一套解析**：`core/plugins/icons.py`（`is_host_icon_name` / `resolve_icon`，
以及 `/api/plugins/ui-icons` 接口，`core/plugins/routes.py:152-160`，注释里承诺
「整表承诺 Stable：只增不改」）。

也就是说：`entries[].icon` 与 `api.ui.icon()` 都支持插件自带图标，
**唯独 `showToast` 走了另一套（白名单 + `<use>`）**。

### 2.4 白名单是「谁用谁加」的堆积，不是策略

`tests/test_frontend_icon_runtime_contracts.py:37-41`：

```python
def test_send_target_brand_icons_are_allowed_in_toast_notifications():
    source = read_project_file('static/js/state.js')
    assert '"sillytavern",' in source
    assert '"tauritavern",' in source
```

这条测试的名字直说了：有人想让 **ST / TT 的品牌图标**出现在「发送到 ST」的通知里，
于是往 `Set` 里塞了两个名字，并加了一条测试把它钉住。
**这正是缺口的历史成因**，也说明「加名字」是被当作解法在用 —— 修完本问题后，
这条测试的**意图**（品牌图标能进通知）应被保留，但实现方式可以退休。

### 2.5 规模（实测数据）

```bash
# 在宠物插件仓库里可直接复现（只读宿主源码，不修改）
python tools/check_toast_icons.py
```

输出：

```
宿主图标库总数 (iconMap)     : 190（另有 · 实际解析出 192 个名字）
toast 白名单条目             : 17（16 个可解析 + loading-animation 特殊分支）
白名单 ∩ 宿主图标库          : 16
宿主图标被 toast 接受的比例   : 16/192 = 8.3%
```

被判定的样例：

| 输入 | 结果 | 说明 |
|---|---|---|
| `check` / `trash` / `close` | 接受 | 白名单内 |
| `heart`、`wand` | **丢弃** | **真实存在的宿主图标** |
| `frontend/assets/icon.svg` | **丢弃** | 插件自带路径 |
| `/api/plugins/<id>/assets/.../icon.svg` | **丢弃** | 插件资产绝对 URL |

真实浏览器实测（`tools/verify-toast-icon.mjs`，4/4）—— 被拒时
`toastIcon === ''`、`toastIconHref === ''`、DOM 里没有 `svg`、**没有 warning**。

### 2.6 谁会踩到

- **所有想在通知里用自己品牌图标的插件**（宠物插件是其中一个：
  它的 `entries[].icon` 与 surface 标题图标都正常工作，
  只有通知里只能退化成宿主通用的 `check`）。
- **宿主自己的图标**：192 个里 176 个用不了，任何人写 `showToast(msg, 3000, 'heart')`
  都会静默拿到空图标位。

---

## 3. 期望结果（验收标准）

- [ ] `showToast(msg, duration, 'heart')`（宿主图标、**不在**旧白名单里）能显示心形图标。
- [ ] `showToast(msg, duration, 'frontend/assets/icon.svg')` 这类**插件资源路径**
      能显示对应图标（由插件 id 解析；宿主自身调用没有 pluginId 时按未知处理）。
- [ ] 未知名字（如 `showToast(msg, 3000, 'no-such-icon')`）
      **在控制台留一条 `console.warn`**，而不是完全静默。
- [ ] 白名单里那 16 个名字的行为**逐字节不变**
      （`loading-animation` 仍走 `<img>` + `ui-loading-icon`，其余仍解析成相同的
      `/static/icons/<sprite>#icon-<name>`）。
- [ ] `heart` 等**图标名**仍然走 `<use>`（sprite 引用），
      **不得**被改成 mask —— 宿主 sprite 是描边式，mask 会渲染成实心块。
- [ ] 插件资源路径走 **mask**（与 `uiPrimitives.js` 一致），
      不得塞进 `<use>`（会变空图形）。
- [ ] 既有的 `test_send_target_brand_icons_are_allowed_in_toast_notifications`
      **意图仍然成立**（`sillytavern` / `tauritavern` 仍能出现在通知里），
      但断言方式可以随实现更新。
- [ ] 新增回归测试：至少覆盖「宿主图标不在旧白名单也能用」
      「插件资源路径能用」「未知名字有 warn」三种情况。
- [ ] `pytest -q` 全绿（注意 §4 会列出**必须同步修改**的既有测试）。

---

## 4. ⚠️ 会撞到的既有测试（先读这一节，否则改完必红）

`tests/test_frontend_icon_runtime_contracts.py:23-34` 把**当前实现**逐字锁死了：

```python
def test_layout_uses_compiled_tailwind_and_guards_empty_toast_icon_href():
    source = read_project_file('templates/layout.html')
    ...
    assert '<template x-if="toastIcon === \'loading-animation\'">' in source
    assert '<template x-if="toastIcon && toastIcon !== \'loading-animation\'">' in source
    assert 'ui-loading-icon' in source
    assert (
        "<use :href=\"'{{ url_for('static', filename='icons/') }}' + toastIconHref\"></use>"
        in normalize_markup(source)
    )
```

改完 `layout.html` 后这几条会红。**这是预期的**——它们锁的是实现而不是契约。
处理原则：

1. 保留**真正的契约**：`loading-animation` 走 `<img>` + `ui-loading-icon`；
   `<use>` 仍指向 `/static/icons/...`（顺序/属性写法可随实现调整）；
   **要新增**一条「`kind === 'asset'` 时必须用 mask 而不是 `<use>`」的断言。
2. 不要为了让旧断言继续通过而把新分支写成「拼字符串」的临时形态 —— 那等于没修。
3. 改测试时在注释里说明「这里从『逐字节锁实现』放宽为『锁契约』」的理由，
   避免下一个人以为是随意放松。

---

## 5. 建议方案（改动很小，且不破坏既有行为）

### 5.1 前端：让 toast 复用 `resolveIcon()`

**`static/js/state.js`**：删掉白名单判定，改存「原值 + 解析结果」。

⚠️ 注意：`state.js` **目前没有** import `resolveIcon`（`state.js:6-19` 只有
`api/system.js`、`utils/dom.js`、`api/card.js` 三处 import）。
需要**新增**一行：

```js
import { resolveIcon } from "./utils/icons.js";
```

然后改 `showToast`（`state.js:1686` 起）：

```js
showToast(msg, duration = 3000, iconName = "", options = {}) {
  if (typeof duration === "string") duration = 3000;
  this.toastMessage = msg;

  const requested = String(iconName || "").trim();
  // 解析交给唯一的图标解析器（D4）。它区分 host / asset / missing 三种情况。
  const resolved = requested
    ? resolveIcon(requested, { pluginId: String(options.pluginId || "") })
    : { kind: "missing", name: "" };

  this.toastIcon = resolved.kind === "missing" ? "" : requested;
  this.toastIconResolved = resolved;
  this.toastIconHref = resolved.kind === "host" ? resolved.href : "";
  if (requested && resolved.kind === "missing") {
    console.warn(`[toast] 未知的图标名或非法资源路径，已忽略: ${requested}`);
  }
  this.showToastState = true;
  ...
}
```

对应地，状态初始化（`state.js:546-550`）要加一个字段：

```js
toastMessage: "",
toastIcon: "",
toastIconResolved: null,   // ← 新增
toastIconHref: "",
showToastState: false,
toastTimer: null,
```

并在隐藏 toast 的定时器里一起清空（`state.js:1701-1705` 那段）：

```js
this.showToastState = false;
this.toastIcon = "";
this.toastIconResolved = null;   // ← 新增
this.toastIconHref = "";
```

**`templates/layout.html`**：按 `kind` 分三条渲染分支。

```html
<span x-show="toastIcon" aria-hidden="true">
  <!-- ① 独立动效 SVG（沿用既有特例） -->
  <template x-if="toastIcon === 'loading-animation'">
    <img class="ui-icon ui-icon--sm ui-loading-icon"
         :src="'{{ url_for('static', filename='icons/') }}' + toastIconHref"
         alt="" aria-hidden="true" draggable="false" />
  </template>

  <!-- ② 插件自带资源：**必须**用 mask（插件 SVG 是填充式，塞进 <use> 会是空图形） -->
  <template x-if="toastIconResolved && toastIconResolved.kind === 'asset'">
    <span class="ui-icon ui-icon--sm ui-icon--asset"
          :style="'--ui-icon-mask: url(' + toastIconResolved.url + ')'"></span>
  </template>

  <!-- ③ 宿主图标名：仍是 sprite 引用 -->
  <template x-if="toastIconResolved && toastIconResolved.kind === 'host'">
    <svg class="ui-icon ui-icon--sm" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <use :href="toastIconResolved.href"></use>
    </svg>
  </template>
</span>
```

要点：

- `resolveIcon()` 对白名单里那 16 个名字返回 `kind: 'host'` +
  **完全相同的 href**，因此**行为逐字节不变**，可以直接删掉白名单。
- 新增状态需要初始化：在 `state.js:547` 附近加 `toastIconResolved: null,`，
  并在隐藏 toast 的定时器里一起清空（`state.js:1701-1705`）。

### 5.2 可选：加一条「批量解析」以省掉每帧解析

`resolveIcon()` 是纯函数 + `iconMap.js` 的静态表，开销极低，
**不必**做缓存 —— 除非你测出热点。不要为此引入新的状态。

### 5.3 支持「插件自带图标」需要调用方传 pluginId

`showToast` 原签名只有 `(msg, duration, icon)`，拿不到插件 id，
而插件资源路径必须带 id 才能解析成 `/api/plugins/<id>/assets/<path>`
（`utils/icons.js:67-83` 的 `resolvePluginIcon` 已明确要求 `pluginId`，
拿不到就返回空串，降级为占位图标而不是猜一个 URL）。

三个选项，**建议选 A**：

| 方案 | 做法 | 评价 |
|---|---|---|
| **A（推荐）** | `showToast` 加**可选的第 4 参** `options = { pluginId }`（见 5.1 的代码）；`pluginHost.js` 里 `api.toast` 透传自己的 `pluginId` | 插件无需改代码；宿主自身的既有调用完全不受影响（第 4 参可省，`pluginId` 为空时 `resolvePluginIcon` 返回空串 → `kind: 'missing'` → 走 §6 第 6 条的宽容降级，只 warn） |
| B | 约定插件在图标位写「插件内相对路径」，宿主在 toast 渲染时自动套用「最近一次调用 api.toast 的插件 id」 | 隐式状态，脆弱，不推荐 |
| C | 不改 `showToast`，插件继续只能用宿主图标名 | 等于本问题没修 |

选 A 时，`static/js/pluginHost.js:737-743` 的改动就是把闭包里的 `pluginId` 透传：

```js
// 改前
toast(msg, duration = 3000, icon = "") {
  const store = storeRef();
  if (store && typeof store.showToast === "function") {
    const safeDuration = typeof duration === "string" ? 3000 : duration;
    store.showToast(String(msg ?? ""), safeDuration, icon);
  }
},

// 改后（多透传一个 pluginId；已有调用方无需改动）
toast(msg, duration = 3000, icon = "") {
  const store = storeRef();
  if (store && typeof store.showToast === "function") {
    const safeDuration = typeof duration === "string" ? 3000 : duration;
    store.showToast(String(msg ?? ""), safeDuration, icon, { pluginId });
  }
},
```

`pluginId` 已在 `buildApi()` 的闭包里（`pluginHost.js:632`：`const pluginId = entry.id;`），
不需要 new 任何东西。

### 5.4 后端要不要动？

**不需要。** toast 是纯前端渲染，`core/plugins/icons.py` 与
`/api/plugins/ui-icons` 已经提供了插件作者查询合法名字的能力，
本次只在**前端**补齐渲染分支。

（如果你顺手想让提示词里的「16 个名字」那条测试退休，记得保留
`test_send_target_brand_icons_are_allowed_in_toast_notifications` 的**意图**：
它锁的是「ST/TT 品牌图标能出现在发送通知里」，修完后这个能力由
通用解析提供，测试可以改成断言「`sillytavern` / `tauritavern` 能被 `resolveIcon` 解析成 host」。）

---

## 6. 注意事项 / 陷阱

1. **不要用 `<img>` 渲染宿主图标名。** `<img>` 里的 SVG 解析不到页面 CSS 变量，
   `currentColor` 永远是黑 —— 宿主在 `uiPrimitives.js:56` 明确记录了这一点。
   宿主图标名走 `<use>`，插件资源走 mask。
2. **不要把插件资源塞进 `<use>`。** 填充式 vs 描边式，会渲染成空图形（同上一条的注释）。
3. **不要顺手把白名单扩大**（例如再加几十个名字）。那只是把缺口推后：
   插件的自定义图标永远无法枚举进白名单。**要修就修通路。**
4. **保留 `loading-animation` 特例。** 它是独立动效 SVG
   （`static/icons/loading-animation.svg`，自带 `<style>` 与 `viewBox="0 0 100 100"`），
   **不在** `HOST_ICON_SPRITES`（`core/plugins/icons.py:27`）里，
   因此永远解析不出 symbol，必须继续走 `<img>`。
5. **未知名字要 `console.warn`。** 目前是完全静默的，插件作者很难发现名字没生效
   （本次就是靠人工审计源码才发现的）。**把静默失效变成可见**是这次修复的一半价值。
6. **`resolveIcon` 的默认降级**：它返回 `{ kind: 'missing' }` 而不是抛错
   （`uiPrimitives.js:58` 有注释「图标不该拖垮整个界面」）。toast 侧也要保持同样的宽容度：
   图标缺失只影响图标位，**文案必须照常显示**。
7. **不要引入打包器 / 新依赖。** `utils/icons.js` 与 `iconMap.js` 都是原生 ESM，
   前端保持这条路线。

---

## 7. 验证建议

1. **单元层面**：`tests/test_frontend_icon_runtime_contracts.py` 增改断言（见 §4）。
   仓库没有 JS 测试运行器，宿主对插件 JS 的做法是 **Node + 最小 DOM 垫片**
   （参考 `tests/test_plugin_ambient_surface.py` 的 `DOM_SHIM`，直接驱动真实模块）。
   建议照这个模式加：驱动 `resolveIcon()` 断言三种 kind，
   以及 `showToast()` 在未知名字时确实 `console.warn`。
2. **真实浏览器**：按 §1 的三步在 Console 里手验，外加
   「插件通过 `api.toast(msg, 3000, 'frontend/assets/icon.svg')` 弹出带自己图标的通知」。
   宠物插件仓库里有一个现成的可复现脚本可参考（只读）：
   `ST-Manager-Pet/tools/verify-toast-icon.mjs`（用 CDP 驱动真实 Chrome，
   逐条读取 `toastIcon` / `toastIconHref` / DOM 与 console 警告）。
3. **回归**：`pytest -q` 全绿；另外确认既有插件（`data/plugins/stm-ai-assistant`、
   `hello-world`）的 `api.toast` 调用行为不变。

---

## 8. 一句话总结

宿主已经把「图标名 / 插件资源路径」的命名空间契约立起来了
（`utils/icons.js`、`core/plugins/icons.py`、`/api/plugins/ui-icons` 三处同源），
**只有 toast 是一处漏网的旧实现**：一个 16 项的白名单 + 模板里硬拼前缀的 `<use>`。
把那一条渲染路径接到 `resolveIcon()` 上（补一个 mask 分支 + 一条 warn），
插件的通知就能用上自己的图标，宿主自己的 176 个图标也顺带解锁。
