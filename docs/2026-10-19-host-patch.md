# 宿主侧补丁清单（ST-Manager）

> 配套方案：[2026-10-19-task-centric-redesign.md](2026-10-19-task-centric-redesign.md) §9。
> 插件侧已按本清单的**目标契约**实现；未打补丁时插件走兼容降级（见各条「降级」说明），
> 因此本清单可以分条独立应用、独立回滚。
>
> 行号以 `8242a66 perf(startup): 索引升级改为后台重建` 为基准。

---

## 1. `ctx.target` 语义化（必须）

### 1.1 现状与问题

宿主把「右键目标」拆成三个扁平字段交给插件（`targetKind` / `targetPath` / `targetIds`），
并在**点击瞬间**同步解析 id 列表：

`static/js/components/contextMenu.js:162-183` `resolvePluginEntryTargetIds()`
用 `listCards({ page: 1, page_size: 100000, ... })` 拉整个分类的卡片，
`catch` 返回 `[]`。

后果：

1. 右键一个上万张卡片的分类，菜单点击会卡住（一次同步 HTTP + 巨量 JSON）；
2. 解析失败与「该分类确实为空」都变成 `[]`，插件无法如实报错，只能显示「0 张」；
3. 世界书视图的分类右键也走这个函数——它拉的是**卡片**，对世界书毫无意义；
4. 命令面板根本不传 target，`context` 类入口在那里被激活时语义不成立。

### 1.2 目标契约

宿主只传「语义目标」，解析留给插件（插件有 `api.cards.list` / `api.worldbook.sources`）：

```js
ctx.target = {
  kind: 'selection' | 'folder' | 'card' | 'none',
  mode: 'cards' | 'worldinfo' | ...,
  path: '科幻/太空',   // folder 时；'' 表示根目录（合法值）
  id: '',              // card 时
  ids: [],             // selection 时
}
```

### 1.3 改动点

#### A. `static/js/pluginSurfaceHost.js`：统一构造并转发

`openSurface(key, ctx)` 有两处把 ctx 交给插件（复用已打开 surface 的 `onOpen`、
首次 mount 的 `mount(body, ctx)`），两处都要改成同一个 helper，避免形状分叉。

```js
/** 入口上下文 → 交给插件的打开上下文（唯一构造点）。 */
function buildOpenContext(ctx = {}, record = {}) {
  const target = ctx.target && typeof ctx.target === 'object' ? ctx.target : null;
  return {
    source: String(ctx.source || ''),
    surfaceId: record.id || '',
    pluginId: record.pluginId || '',
    entryId: String(ctx.targetId || ctx.entryId || ''),
    mode: String(ctx.mode || (target && target.mode) || ''),
    target: target
      ? {
        kind: String(target.kind || 'none'),
        mode: String(target.mode || ctx.mode || ''),
        path: String(target.path == null ? '' : target.path),
        id: String(target.id || ''),
        ids: Array.isArray(target.ids) ? target.ids.map(String) : [],
      }
      : null,
    // 其余字段原样透传（插件自定义上下文）
    ...ctx,
  };
}
```

- `openSurface` 复用处（当前 `:315-324`）：
  `record.onOpen(buildOpenContext(ctx, record))`
- 首次 mount 处（当前 `:428-446`）：
  `const mountContext = buildOpenContext(ctx, record); record.mount(body, mountContext);`
  以及 `if (record.onOpen) record.onOpen(mountContext);`

同时删除 `mount()` 里对 `targetKind` / `targetPath` / `targetIds` 三个字段的单独赋值
（它们现在由 `target` 承载；保留会诱导插件继续读旧形状）。

#### B. `static/js/components/contextMenu.js`

`runPluginEntry()`（当前 `:196-229`）：

```js
runPluginEntry(entry) {
  if (!entry || !entry.enabled) return false;
  const surfaceId = (entry.surface && entry.surface.id) || entry.id;
  const surfaceKey = `${entry.pluginId}:${surfaceId}`;
  this.visible = false;

  // 只传语义目标：不在这里解析 id（解析归插件，且有 api.cards.list 可用）
  const kind = String(this.type || '');           // 'folder' | 'card'
  const target = {
    kind: kind === 'card' ? 'card' : 'folder',
    mode:EntryRegistry.context().mode,
    path: kind === 'folder' ? String(this.target == null ? '' : this.target) : '',
    id: kind === 'card' ? String(this.target == null ? '' : this.target) : '',
    ids: [],
  };

  if (PluginSurfaceHost.has(surfaceKey)) {
    PluginSurfaceHost.openSurface(surfaceKey, {
      source: 'context',
      targetId: entry.id,
      mode: target.mode,
      target,
    });
    return true;
  }
  window.dispatchEvent(new CustomEvent('entry:activate', {
    detail: { key: entry.key, entry, source: 'context', target },
  }));
  return true;
}
```

删除 `resolvePluginEntryTargetIds()`（当前 `:162-183`）与 `pluginEntryContext()` 里对
`selectionCount` 的推导（`when.selection` 在右键上下文里恒为 none，无需再算）；
`refreshPluginEntries()`（当前 `:116-126`）改为传 `{ targetKind: this.type }` 即可。

#### C. `static/js/components/header.js`：批量入口

`runPluginBatchEntry()`（当前 `:496-523`）：

```js
const target = {
  kind: 'selection',
  mode: String(this.currentMode || ''),
  path: '',
  id: '',
  ids: [...this.selectedIds],
};
```

两处 `PluginSurfaceHost.openSurface(...)` / `entry:activate` 的 detail 都改用
`{ source: 'batch', targetId: entry.id, mode: this.currentMode, target }`。
`pluginEntryContext()`（同文件）改为返回 `{ targetKind: 'selection', selectionCount: this.selectedIds.length }`。

#### D. `static/js/components/commandPalette.js`

`activate()`（当前 `:299-326`）与 `handleEntryShortcut()`（当前 `:107-160`）：
命令面板没有「右键目标」，但有**当前选中集**，因此按入口 kind 决定：

```js
import { readSelectionSnapshot } from './selectionSnapshot.js'; // 见 §2

buildCommandTarget(entry) {
  if (entry.kind === 'batch') {
    const snap = readSelectionSnapshot();
    return { kind: 'selection', mode: snap.mode, path: '', id: '', ids: snap.ids };
  }
  return null;   // dock / command / settings：无作用域
}
```

#### E. `static/js/components/entryDock.js`

坞入口点击处统一传 `target: null`（不继承任何上一次的作用域）。

### 1.4 降级

未打补丁时插件仍能工作：`frontend/scope.js` 的 `normalizeTarget()` 会把
`targetKind` / `targetPath` / `targetIds` 折算成新形状（该文件是**唯一**读取旧字段的地方）。
补丁合入后删掉这个函数即可。

---

## 2. `api.host.selection()`（必须）

插件需要一个「当前选中集」的读取接口。现状是插件直接读
`store.viewState.selectedIds`——`docs/plugin-api.md:429` 明确写了这属于 Provisional 耦合。

`static/js/pluginHost.js` 的 `host:` 命名空间（当前 `:794-851`）新增：

```js
/**
 * 读取主程序当前的选中集（视图 + id 列表）。
 *
 * 返回 `{ mode: 'cards' | 'worldinfo' | 'presets' | …, ids: string[] }`。
 * 与 `onState()` 不同：这个接口给的是**数据**，状态快照只给界面字段。
 */
selection() {
  const store = storeRef();
  const viewState = (store && store.viewState) || {};
  const ids = Array.isArray(viewState.selectedIds) ? viewState.selectedIds : [];
  return {
    mode: String((store && store.currentMode) || ''),
    ids: ids.map((item) => String(item || '')).filter(Boolean),
  };
},
```

同时新增 `static/js/components/selectionSnapshot.js`（供命令面板等宿主内部复用）：

```js
/** 当前选中集快照（宿主内部用；插件请走 api.host.selection()）。 */
export function readSelectionSnapshot() {
  const store = window.Alpine && typeof window.Alpine.store === 'function'
    ? window.Alpine.store('global')
    : null;
  const viewState = (store && store.viewState) || {};
  const ids = Array.isArray(viewState.selectedIds) ? viewState.selectedIds : [];
  return {
    mode: String((store && store.currentMode) || ''),
    ids: ids.map((item) => String(item || '')).filter(Boolean),
  };
}
```

**降级**：插件在 `readHostSelection()` 里已经实现了同样的兜底（读 `store.viewState`），
接口出现后自动优先走接口。

---

## 3. `api.worldbook.sources()`（必须）

世界书任务的作用域是「世界书文件」，但前端 `worldbook` 域只有
`read` / `write` / `list_entries` / `history`——**没有列出来源的能力**。

`static/js/pluginHost.js` 的 `worldbook` 域新增（纯前端实现，数据取自全局 store，
不新增后端路由）：

```js
/**
 * 列出世界书来源（文件级）。
 *
 * 数据取自主程序世界书视图的列表缓存（`store.wiList`），因此**只覆盖当前已加载的
 * 条目**；作为「右键分类 → 处理该分类世界书」的作用域够用，因为右键时该分类
 * 一定在视图里可见。需要全量时用 `api.index.search('', { scope: 'worldinfo', limit: 0 })`。
 */
sources({ category = '', sourceType = '' } = {}) {
  const store = storeRef();
  const list = (store && store.wiList) || [];
  const prefix = String(category || '');
  return (Array.isArray(list) ? list : [])
    .filter((item) => !prefix || String(item.display_category || '').startsWith(prefix))
    .filter((item) => !sourceType || String(item.source_type || item.type) === sourceType)
    .map((item) => ({
      source_type: String(item.source_type || item.type || 'global'),
      file_path: String(item.path || ''),
      card_id: String(item.owner_card_id || ''),
      category: String(item.display_category || ''),
      name: String(item.name || ''),
      entry_count: Number(item.entry_count || item.entries_count || 0) || 0,
    }));
}
```

**降级**：插件 `listWorldbookSources()` 读同一个 `store.wiList`，字段名一致。

---

## 4. 批量菜单：移动端 + 角标（必须）

### 4.1 移动端没有插件批量入口

`templates/components/header.html`：

- 桌面批量区 `:277`，选中提示条 `:281`，插件项块 `:531-557`；
- 移动端选中栏 `:819-993` —— **完全没有插件入口块**；
- 移动端「更多」菜单 `:997+` 也没有。

在移动端选中栏的操作组里（`:819-993` 之间，与「批量标签」按钮同级）追加：

```html
<template x-for="entry in pluginBatchEntries" :key="entry.key">
  <button
    type="button"
    class="ui-batch-action-button"
    :disabled="!entry.enabled"
    :title="entry.enabled ? entry.label : (entry.disabledHint || entry.label)"
    @click="runPluginBatchEntry(entry)"
  >
    <span aria-hidden="true" x-html="pluginBatchEntryIconHtml(entry)"></span>
    <span class="sr-only" x-text="entry.label"></span>
  </button>
</template>
```

`refreshPluginBatchEntries()`（`static/js/components/header.js:472-481`）已由
`init()` 里的监听器调用（同文件 `:443-447`），移动端无需额外初始化。

### 4.2 批量菜单项不画角标/进度

`templates/components/header.html:531-557` 的插件项只渲染 label + icon；右键菜单
（`templates/components/context_menu.html:136-139`）却渲染了 `entry.badge` 与进度条。
两边不一致 → 「有 3 条待审批」只在右键菜单可见。

在批量项里补上与右键菜单相同的角标结构：

```html
<template x-if="entry.badge !== null && entry.badge !== undefined && entry.badge !== ''">
  <span class="plugin-entry-badge" x-text="entry.badge"></span>
</template>
<template x-if="entry.progress">
  <span class="plugin-entry-progress">
    <span class="plugin-entry-progress-bar" :style="'width:' + entry.progress + '%'"></span>
  </span>
</template>
```

---

## 5. 命令面板：过滤 + 传选中集 + `kindLabel`（必须）

`static/js/components/commandPalette.js`

### 5.1 列出 `context` 类入口，却给不出右键目标

`EntryRegistry.searchable()`（`static/js/entryRegistry.js:869-871`）把 `context` 也放进了
搜索结果。用户在命令面板里搜到「AI 打标此分类全部卡片」，激活后得到一个**没有作用域**
的面板——语义直接不成立。

`rebuild()` / `onQueryInput()`（`:221-229`）改为：

```js
rebuild() {
  this.items = this.filter(EntryRegistry.searchable().filter((entry) => entry.kind !== 'context'));
  this.activeIndex = 0;
},
```

`searchable()` 保持不变（它服务于「入口总览」等其它消费者）。

### 5.2 `batch` 入口没有 target

见 §1.3.D：`activate()` 与 `handleEntryShortcut()` 都要带上 `target`。

### 5.3 `kindLabel()` 缺 `batch`

`:339-349` 的映射表补一行：

```js
batch: '批量',
```

否则批量入口在命令面板里显示为「入口」，与右键/坞入口无法区分。

---

## 6. `api.jobs.review()` / `reviewBatch()`（建议）

插件现在要手拼路径调宿主的审批端点：

```js
call(`/jobs/${runId}/items/${encodeURIComponent(key)}/review`, { method: 'POST', body: { status } })
```

`api.jobs` 域（`static/js/pluginHost.js:1187-1238`）补两个方法，与其它 `jobs.*` 对称：

```js
async review(runId, itemKey, status) {
  const data = await api.api(
    `/jobs/${encodeURIComponent(runId)}/items/${encodeURIComponent(itemKey)}/review`,
    { method: 'POST', body: { status } },
  );
  return Boolean(data && data.success);
},
async reviewBatch(runId, updates) {
  const list = Array.isArray(updates) ? updates : [];
  const results = await Promise.allSettled(
    list.map((item) => this.review(runId, item.key, item.status)),
  );
  return {
    total: list.length,
    failed: results.filter((item) => item.status === 'rejected').length,
  };
},
```

**降级**：插件 `client.reviewItems()` 已经用 `api.api()` 并发实现了同样的批量语义，
接口出现后改一行即可。

---

## 7. 不做的宿主改动

| 提议 | 不做理由 |
|---|---|
| 卡片级右键菜单 | 单卡场景用「勾选一张 → 批量菜单」已经覆盖；新增一种右键目标要同步改 `when.target` 枚举、菜单渲染、移动端长按，收益不抵成本 |
| 入口二级子菜单（按插件分组） | 当前插件 4 条右键入口，全宿主最多也就十几条；宿主现有 `entries[]` 契约没有 `parent`/`group` 字段，为一个插件加特性不划算 |
| `when.target` 新增 `worldbook` 等取值 | `target: 'folder'` + `when.mode: ['worldinfo']` 已能表达「世界书分类」，枚举无需扩张 |
| 世界书视图允许选中内嵌书 | 内嵌书不可选中是既有设计（删除/移动只对文件型生效）。需要的场景由「cards 模式 → 右键卡片分类 → 精简嵌入世界书」覆盖 |

---

## 8. 应用顺序与验收

1. §1（ctx.target）→ 验收：右键上万卡片分类，菜单**立即**关闭；面板先出骨架再填数字。
2. §2（host.selection）→ 验收：坞打开「打标」→ 点「更改」→「使用主程序选中项」能读到正确数量。
3. §3（worldbook.sources）→ 验收：世界书视图右键分类 → 精简面板显示正确的书数。
4. §4（移动端 + 角标）→ 验收：手机视图选中卡片后能看到插件批量按钮；批量菜单项显示待审批角标。
5. §5（命令面板）→ 验收：搜「打标」只出现 dock / batch 入口；`context` 入口不再出现。
6. §6（jobs.review）→ 纯重构，无行为变化。

每条都可以独立应用：插件侧对每个缺口都有降级路径，不会因为宿主只打了部分补丁而坏掉。
