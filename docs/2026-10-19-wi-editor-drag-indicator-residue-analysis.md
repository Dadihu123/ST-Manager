# 全屏世界书编辑器：拖拽排序高亮边框残留问题分析

> 状态：**已按第六节方案 A 实施**。
> 范围：`templates/modals/detail_wi_fullscreen.html`、`static/js/components/wiEditor.js`、
> `static/css/modules/view-wi.css`。
> 关联文档：[角色卡资源绑定与换图保存失败分析](2026-10-19-card-resource-binding-and-save-failure-analysis.md)。

---

## 一、现象回顾

全屏世界书编辑器左侧条目列表支持拖拽排序。因为条目默认上下边框透明（不可见），
为了指示"将插入到哪两个条目之间"，拖拽经过时会临时给相邻条目加上可见的上/下边框。

问题：**拖拽已经经过、甚至拖拽动作已经结束后，这些边框会概率性残留**，
且"残留的是上边还是下边"不固定；但**每个条目最多只残留一条边**。

---

## 二、结论

高亮状态没有放在组件状态里，而是**用命令式 `classList` 直接写在 DOM 节点上**，
并且**只有"当前指针所在元素"和"drop 目标元素"这两处会清理**。
一旦指针离开某个已高亮的条目，就再没有任何代码负责摘掉它的类名 —— 于是残留。

「每个条目最多残留一条边」这一点，恰好是 `wiDragOver()` 每次都先 `remove` 两个类再
`add` 一个的实现方式决定的，可作为根因的佐证（见 3.3）。

---

## 三、代码事实

### 3.1 模板：只绑了 dragstart / dragover / drop，**没有 dragleave**

`templates/modals/detail_wi_fullscreen.html` L506-517：

```html
<div
  :id="'wi-item-' + index"
  :data-entry-key="getWiEntryIdentity(entry, index)"
  @click="selectMainWiItem(entry, index)"
  :draggable="wiSortMode === 'custom' && !isWiEntryFilterActive()"
  @dragstart="wiDragStart($event, index)"
  @drop="wiDrop($event, index)"
  @dragover="wiDragOver($event, index)"
  class="wi-list-item p-2 rounded cursor-pointer group relative text-xs select-none border border-transparent"
  :data-type="..."
  :class="isCurrentWiEntry(entry, index) ? 'active' : ''"
>
```

- 只有 `dragstart` / `dragover` / `drop` 三个事件。
- 全文件搜索 `dragleave` 只有一处，属于**另一个**功能（标签导入拖放区 L2081）。
- 列表容器（L500 `.wi-list-container`）**也没有** `dragover` / `drop` 绑定。

### 3.2 JS：清理逻辑只覆盖"当前元素"，`wiDragLeave` 是死代码

`static/js/components/wiEditor.js`：

**`wiDragOver()` L3866-3883** —— 只清理 `e.currentTarget`（也就是本次 dragover 落到的那个条目），
然后按指针在条目上半/下半加一个类：

```js
e.preventDefault();
const target = e.currentTarget;
const rect = target.getBoundingClientRect();
const midY = rect.top + rect.height / 2;

target.classList.remove("drag-over-top", "drag-over-bottom");   // L3880 只清自己
if (e.clientY < midY) target.classList.add("drag-over-top");     // L3881
else target.classList.add("drag-over-bottom");                   // L3882
```

**`wiDragLeave()` L3885-3887** —— 写法正确，但**模板从未绑定 `@dragleave`**，所以永不执行：

```js
wiDragLeave(e) {
  e.currentTarget.classList.remove("drag-over-top", "drag-over-bottom");
},
```

**`wiDrop()` L3889-3907** —— 只清理 `e.currentTarget`（drop 落点）：

```js
const el = e.currentTarget;
el.classList.remove("drag-over-top", "drag-over-bottom", "dragging");  // L3907
```

**`wiDragStart()` L3827-3864** —— `dragend` 清理只摘 `dragging`，且挂在 `e.target` 上：

```js
const target = e.target;                    // L3856（注意：不是 currentTarget）
target.classList.add("dragging");           // L3857
const cleanup = () => {
  target.classList.remove("dragging");      // L3859 只清 dragging
  this.wiDraggingIndex = null;
  this.wiDraggingEntryKey = "";
};
target.addEventListener("dragend", cleanup, { once: true });  // L3863
```

### 3.3 CSS：高亮就是加在条目上的两条边框

`static/css/modules/view-wi.css` L256-262：

```css
.wi-list-item.drag-over-top {
  border-top: 2px solid var(--accent-action) !important;
}
.wi-list-item.drag-over-bottom {
  border-bottom: 2px solid var(--accent-action) !important;
}
```

条目基础样式是 `border: 1px solid transparent`（L113-122），所以这两条类名就是"可见边界"的全部来源。

**为什么每个条目最多残留一条边**：`wiDragOver` 每次执行都先 `remove` 两个类、再 `add` 一个类
（L3880-3882），因此在同一个条目上**永远不会同时存在 top 和 bottom**；
而残留发生在"最后一次高亮之后没有任何清理"的条目上，所以最多一条。

---

## 四、残留产生的具体时序（四种都成立）

设拖拽依次经过 A → B → C，最终在 C 上 drop。

### 情形 1：指针离开 A、进入 B —— A 无人清理

1. `dragover` 落在 A → A 得到 `drag-over-bottom`；
2. 指针移入 B → 触发的是 **B 的 `dragover`**，它只清理 **B**（L3880），**A 完全没被碰过**；
3. 模板没有 `@dragleave`，`wiDragLeave` 永不执行；
4. 于是 A 的边框一直亮着 —— **直到页面重绘或其它代码碰巧清掉它**。

这正是"已经经过了之后还残留"的主路径，**几乎必然发生**，只是是否被后续操作覆盖看起来像"概率"。

### 情形 2：drop 只清落点，中途经过的条目全部保留

`wiDrop`（L3907）只清 `e.currentTarget` = C。A、B 的高亮无人清理 →
**拖拽动作完成之后仍然残留**。用户观察到的"拖拽完成后残留"即此路径。

### 情形 3：drop 落在"没有绑定 drop 的地方" → 一个都不清

- 条目之间有空隙：`.wi-list-item` 有 `margin-bottom: 2px`（L119），容器还有 `space-y-1`（L500）——指针落在这条缝里时，`drop` 不会命中任何 `.wi-list-item`；
- 拖到列表容器空白区、画布区、或按 ESC 取消、拖到浏览器外释放；
- 列表容器（L500）没有 `@dragover` / `@drop`。

这些情况下 `wiDrop` 根本不执行，`dragend` 又只清 `dragging`（L3859）→ **所有经过的条目全部残留**。

### 情形 4：高亮类被 Alpine 的"节点复用"带走

列表用 `x-for` + `:key="getWiEntryIdentity(entry, index)"`（L502-505）渲染。
drop 后 `setWiCustomDisplayIndexes(ordered)`（L3976）改变了顺序，Alpine **移动已有 DOM 节点而不是重建**。
命令式 `classList` 加的类属于节点自身，`:`class` 只绑定 `active` 一项，
所以**残留边框会跟着节点跑到新位置**，甚至看起来像"另一个条目突然有了边框"。
（同理，`isCurrentWiEntry()` 变成 `active` 时，`.wi-list-item.active` 会设置 `border-color`，
但残留的 `drag-over-*` 用的是 `border-top/bottom` 简写，两者不会互相清掉。）

---

## 五、次要问题（同一处代码，顺手记录）

1. **`dragstart` 用 `e.target` 而不是 `e.currentTarget`**（L3856）。
   若拖拽起点是条目内部的子元素（标题 `span`、复选框等），`dragging` 类会加到子元素上，
   而 CSS 选择器是 `.wi-list-item.dragging`（L250-254），**拖拽中的半透明/虚线效果可能不生效**，
   `dragend` 也只在那个子元素上清理。建议统一用 `currentTarget`。
2. **`dragover` 与 `dragleave` 的配对**：即使补上 `@dragleave`，因为条目内部有子元素，
   指针在子元素之间移动也会触发 `dragleave` → 高亮闪烁。稳妥做法是判断
   `e.relatedTarget` 是否仍在 `e.currentTarget` 内。
3. **`drag-over-*` 与 `.active` 的 `border-color` 优先级**：两者都用 `!important`、
   选择器特异度相同（0,2,0），当前靠"文件里更靠后"生效（drag-over 在 L256/L260，active 在 L235-243），
   属于隐式依赖书写顺序，改样式时容易踩坑。
4. **拖拽指示在筛选态下的表现**：`wiDragOver` 在筛选激活时只清 `currentTarget`（L3871），
   与上面的残留机制一致；虽然此时 `draggable=false`（L510），但若在拖拽过程中开启筛选，
   已高亮的条目不会被清理。

---

## 六、修复方向（已实施方案 A，见第八节）

按稳妥程度排序：

### 方案 A（推荐）：把高亮变成组件状态，用 `:class` 声明式渲染

```js
// data 里新增
wiDragOverIndex: -1,
wiDragOverPosition: '',   // 'top' | 'bottom'
```

```html
:class="{
  active: isCurrentWiEntry(entry, index),
  'drag-over-top': wiDragOverIndex === index && wiDragOverPosition === 'top',
  'drag-over-bottom': wiDragOverIndex === index && wiDragOverPosition === 'bottom',
}"
```

- `wiDragOver(e, index)` 只改两个状态字段，不再碰 `classList`；
- `wiDragStart` 里先重置；`wiDrop` 里重置；
- 在 `init()` 里挂**一次**全局兜底：`window.addEventListener('dragend', () => this._resetWiDragIndicators())`，
  同时处理 `drop`（捕获阶段）与 `blur`/`keydown Escape`。
- 优点：状态唯一、天然只会高亮一个条目、drop 落在任何地方都能靠 `dragend` 兜底清干净、
  不受 Alpine 节点复用影响；也顺手消灭"最多残留一条边"这种实现细节泄漏。
- 注意：`dragend` 在部分浏览器里对 `document` 触发，挂在 `window` 上最稳。

### 方案 B（最小改动）：保留 classList，但补全清理路径

1. 模板补 `@dragleave="wiDragLeave($event)"`，并在 `wiDragLeave` 里判断
   `e.relatedTarget && e.currentTarget.contains(e.relatedTarget)` 则不清；
2. `wiDragOver` 先清"上一次高亮的元素"（用一个 `this._wiLastDragOverEl` 记录），
   或直接清容器内所有 `.drag-over-top/.drag-over-bottom`；
3. 新增 `_clearWiDragIndicators()`，在 `wiDragStart`、`wiDrop`、以及 `dragend` 里调用，
   清理范围是 `this._getEditorRootEl()?.querySelectorAll('.wi-list-item')`；
4. `dragend` 改挂在 `e.currentTarget` 上（L3856），并同时清 `drag-over-*`；
5. 列表容器补 `@dragover.prevent` / `@drop.prevent`，让缝隙与空白区的 drop 也能落到统一处理。

### 回归验证建议

- 手动：拖过 5~10 个条目后在**空隙**、**列表空白区**、**画布区**分别松开，观察是否还有残留；
- 自动化：仓库已有前端运行时契约测试范式
  （`tests/test_detail_modal_advanced_editor_contracts.py`），可加一条
  "拖拽经过 A→B 后 A 不应保留 drag-over-* 类 / 状态"的断言，
  以及"drop 后所有条目均无 drag-over-*"的断言。

---

## 七、关键位置索引

| 主题 | 位置 |
|---|---|
| 列表项事件绑定（缺 `@dragleave`） | `templates/modals/detail_wi_fullscreen.html` L506-517 |
| 列表容器（无 drop/dragover） | `templates/modals/detail_wi_fullscreen.html` L500 |
| 拖拽开始 / `dragend` 清理 | `static/js/components/wiEditor.js` L3827-3864（`e.target` L3856，清理 L3859，挂载 L3863） |
| dragover 只清当前元素 | `static/js/components/wiEditor.js` L3866-3883（清理 L3880） |
| `wiDragLeave`（死代码，未绑定） | `static/js/components/wiEditor.js` L3885-3887 |
| drop 只清落点 | `static/js/components/wiEditor.js` L3889-3907（清理 L3907） |
| 高亮边框样式 | `static/css/modules/view-wi.css` L256-262 |
| 条目基础边框（透明） | `static/css/modules/view-wi.css` L113-122 |
| `dragging` 样式 | `static/css/modules/view-wi.css` L250-254 |
| Alpine 节点复用（`x-for` + `:key`） | `templates/modals/detail_wi_fullscreen.html` L502-505 |

---

## 八、实施记录（方案 A）

### 8.1 组件状态取代 DOM class

`static/js/components/wiEditor.js` 新增：

```js
wiDragOverIndex: -1,
wiDragOverPosition: "",   // 'top' | 'bottom'
_wiDragCleanupHandler: null,
```

- `wiDragOver(e, index)` 只计算上下半区并写状态，**不再碰 `classList`**；
- `wiDragStart` 先重置状态，并把 `dragging` 类挂在 `e.currentTarget`
  （旧实现用 `e.target`，指针落在内部元素上时会给错误的节点加类）；
- `wiDragLeave(e)` 首次真正被绑定，用 `relatedTarget` 判断「在同一行内部移动」，
  只有真正离开条目才清空，避免子元素间移动导致指示闪烁；
- 新增 `resetWiDragIndicators()`：一次性清空 index / position / 拖拽键，
  并摘掉全局兜底监听；`wiDrop` 的两条分支与编辑器关闭路径都调它。

### 8.2 全局兜底

`_ensureWiDragCleanupListeners()` 在 `wiDragStart` 里挂一次
（`dragend` + `drop`，捕获阶段），用 `setTimeout(..., 0)` 让 `wiDrop` 先读状态再清理。
这样无论松手落在列表空隙、画布还是浏览器外，都不会留下边框。

### 8.3 模板

`templates/modals/detail_wi_fullscreen.html` 的条目节点：

- 补 `@dragleave="wiDragLeave($event)"`；
- `:class` 改为数组，按 `wiDragOverIndex === index && wiDragOverPosition === 'top' / 'bottom'`
  声明式渲染 `drag-over-top` / `drag-over-bottom`。

CSS 未改动：`.wi-list-item.drag-over-top/.drag-over-bottom` 规则继续生效，
只是从「JS 直接加类」变成「Alpine 按状态渲染」。

### 8.4 回归测试

`tests/test_wi_editor_frontend_contracts.py` 新增
`test_wi_editor_runtime_drag_indicator_state_is_cleared_and_never_lingers`：
用 node 直接加载真实函数体，断言

- 上半区/下半区分别标记 `top` / `bottom`；
- `wiDragLeave` 离开后状态清空，子元素间移动不清空；
- `resetWiDragIndicators()` 清空全部拖拽字段；
- 模板仍由状态驱动（防止有人改回命令式 classList）。

同时更新了既有的「筛选态下拖拽被拒绝」用例，适配「改用 `resetWiDragIndicators()`
而非 `classList.remove`」的新实现。

