# 角色卡「资源目录绑定丢失」与「换图后保存失败」问题分析

> 状态：**已按第六节方案实施**（见 §6 的「实施记录」）。
> 范围：`static/js/components/detailModal.js`、`templates/modals/detail_card.html`、
> `core/api/v1/resources.py`、`core/api/v1/system.py`、`core/api/v1/cards.py`、
> `core/services/card_service.py`、`core/data/ui_store.py`、`core/data/cache.py`、
> `core/services/scan_service.py`。
> 现象来源：用户反馈的**历史发布版本**行为（当前 main 上部分成因已被修掉，但同类缺口仍在）。

---

## 一、现象回顾（按用户描述拆解）

### 现象 A：拖拽加皮肤后资源页「闪一下回退成空状态」，重启后绑定彻底消失

1. 新卡 → 保存 URL 与备注 → 拖拽几张皮肤图进资源页。
2. 资源页**先切到"有资源"布局，随即又变回"点击或拖拽导入首个资源"**。
3. 左侧皮肤条仍可见、图片能正常访问。
4. 关闭详情页重开、甚至整页刷新后重开资源页，**仍是空状态**。
5. 重启管理器后，**皮肤条也没了**，资源目录绑定关系消失；但磁盘上资源目录和图片都在。
6. 非必现。

### 现象 B：JSON 格式角色卡「换图」后，填 URL / 备注再保存失败

- 卡片是 `.json`，执行换图（图片替换）后，编辑来源链接与备注，点保存 → 失败。

---

## 二、结论先行

| 现象 | 主因 | 性质 |
|---|---|---|
| A-2「闪一下回退」 | 详情页打开时发出的 `refreshActiveCardDetail()` 响应**晚到**，用旧快照无条件覆盖 `editingData.resource_folder` | 前端竞态 |
| A-4/A-5「重开仍空、重启后绑定消失」 | 绑定写入 `ui_data.json` 这条链路**不具备持久化保证**：①`save_ui_data()` 返回值被忽略；②`load → 改 → save` 不是原子事务（存在并发丢失更新）；③任何一次带空 `resource_folder` 的卡片保存都会把它清掉 | 后端持久化缺陷 |
| A-3「左侧皮肤条还在」 | 左侧条读的是 `skinImages`（由列表缓存里的 `resource_folder` 驱动），与资源页读的 `editingData.resource_folder` 是**两个数据源**，所以内存有、磁盘没有时两者表现分裂 | 状态源不统一 |
| B | 换图/换封改写了卡文件（JSON→PNG 还会换 ID），但**没有把新的 `source_revision`（以及新 ID）回传给前端**，下一次保存被 `api_update_card` 的乐观锁以 409 拒绝；JSON→PNG 场景则是前端仍持旧 `.json` ID，保存时文件已不存在 | 前后端契约缺口 |

两条现象在「之前的发布版本」上都是**确定性可解释**的，B 已有一次针对性修复（见 4.3），A 的持久化缺陷至今仍在。

---

## 三、现象 A 的链路与根因

### 3.1 资源页的显示条件（为什么"空状态"= `editingData.resource_folder` 为空）

`templates/modals/detail_card.html`：

- L3187：标题文本 `editingData.resource_folder ? '点击或拖拽文件上传' : '点击或拖拽导入首个资源'`
- L3209：空目录提示条 `x-show="!editingData.resource_folder"`
- L3217：`<template x-if="editingData.resource_folder">` 包住整个「皮肤 + 世界书/正则/脚本」双栏

所以只要 `editingData.resource_folder` 变成 `""`，界面立刻退回空状态。**与皮肤文件是否真的存在无关**。

而左侧皮肤条（`detail_card.html` L62 起）渲染的是 `currentSkinItems` ← `skinImages`，由 `fetchResourceFiles()` 填充；它的 URL 走 `getSkinUrl()` ← `activeCard.resource_folder || editingData.resource_folder`（`detailModal.js` L2907-2911）。这就是"左侧还在、资源页空了"的直接原因：**同一份绑定被复制到了三处（`editingData` / `activeCard` / `skinImages`），没有任何一处是唯一真源**。

### 3.2 「闪一下」的直接原因：晚到的详情刷新覆盖了新值

`detailModal.js`：

- L2118 `openDetail(c)`：先把 `activeCard = c`，用列表缓存构造 `editingData`（L2189 `rawData.resource_folder = rawData.resource_folder || c.resource_folder || ""`），随后 L2228 `refreshActiveCardDetail(c.id)`。
- L2232 `refreshActiveCardDetail()`：`const requestToken = ++this.detailRequestToken;`（L2233），响应回来后 L2243 只判断"是否还有更新的请求"，然后 **L2304 无条件赋值**：

  ```js
  this.editingData.resource_folder = safeCard.resource_folder || "";
  ```

  这个 `safeCard` 是**请求发出那一刻**服务端读到的 `ui_data` 快照。
- 拖拽上传链路（L1546 `handleResourceDrop` → L1640 `ensureResourceFolder` → L1613 `uploadSingleResource`）会在 L1660/L1624 写入 `editingData.resource_folder = res.resource_folder`，页面因此短暂切到"有资源"布局。

**竞态**：`get_card_detail` 的响应如果在资源目录创建之后才返回，却携带创建之前的快照（`resource_folder: ""`），就会把刚写入的值覆盖回空 → 界面"闪一下又变回去"。`detailRequestToken` 只比较请求先后，**不能识别"响应里的数据比本地状态旧"**，因此这类陈旧响应不会被丢弃。

服务端 `load_ui_data()`（`ui_store.py` L1765）**每次请求都完整读取并解析整个 `ui_data.json`**（实测量级 1.75MB），叠加 `get_card_detail` 还要读 DB、读卡文件、计算 token，慢响应完全可能跨过用户拖拽的几秒钟；再加上整页/缓存层的并发扫描，响应耗时波动大，所以**不是必现**。

同类"整对象替换"风险点还有：
- L2308 `this.editingData = this._normalizeEditingDataShape(this.editingData)`（本身保留字段，但紧跟 L2304）；
- L2672 `handleUpdateResponse` 直接用 `updatedCard` 重建 `editingData`（`update_card_file` 流程）；
- L3113 `switchVersion` 重建 `editingData`（这里对 `resource_folder` 做了 dirty 保护，是正确写法，可作参照）。

### 3.3 「重开仍空」的原因：磁盘上的绑定真的丢了，但内存缓存还留着

`openDetail` 时 `editingData.resource_folder` 来自列表卡片对象 `c.resource_folder`；而 `activeCard === c` 是**同一对象引用**，`uploadSingleResource`（L1625）已经把 `activeCard.resource_folder` 改成了新目录名 —— 于是重开详情页时：

1. 先按内存里的旧值/新值显示（皮肤条因此出现）；
2. `refreshActiveCardDetail` 返回后按 `ui_data` 覆盖 → 若磁盘已无绑定，则再次变空。

**整页刷新**后列表缓存从 `ui_data` 重建（`core/data/cache.py` L546 → L765 `_enrich_card_ui`），此时绑定确实为空，于是"仍旧一样的现象"。

### 3.4 绑定为什么会从 `ui_data.json` 丢掉（三条独立路径，都会导致"内存有、磁盘无"）

#### 路径 ①：写入失败被静默吞掉，但内存缓存照常更新

`core/api/v1/resources.py` L196-230 `_ensure_card_resource_folder()`：

```python
ui_data[ui_key]['resource_folder'] = resource_folder_name
save_ui_data(ui_data)                       # L225 ← 返回值被忽略
...
ctx.cache.update_card_data(target_id, {'resource_folder': resource_folder_name})  # L228
```

`save_ui_data()`（`ui_store.py` L1956-2006）**任何异常都 `return False`**（L2004），并且还有两道主动拒绝：

- L1979 降级状态（上一次读取失败未恢复）时拒绝保存；
- L1987 退化护栏（卡片条目数骤降 >50%）时拒绝保存。

写入本身是 `mkstemp + fsync + os.replace`（L1689-1720），在 Windows 上被杀毒/索引/同步盘短暂占用时失败是常见事件。**失败被忽略 → 内存缓存（前端看到的一切）是对的，磁盘是错的**，重启后自然消失。这与"非必现 + 重启后消失 + 磁盘目录和图片都在"完全吻合。

同样的写法还出现在：

- `core/api/v1/system.py` L1295-1307 `api_create_resource_folder()`（L1299 `save_ui_data` 忽略返回值）
- `core/api/v1/system.py` L1360-1374 `api_set_resource_folder()`（L1367 同上）
- `core/services/card_service.py` L146-148 `_ensure_resource_folder_exists()`、L510、L795 等

#### 路径 ②：并发"读-改-写"丢失更新（lost update）

`ui_store.py` 已经提供了事务入口 `update_ui_data()`（L2023-2068，把 load/modify/save 收进同一把 `_UI_DATA_LOCK`），但**资源相关端点一个都没用**，仍是"先 `load_ui_data()`、后 `save_ui_data()`"两段式；`_UI_DATA_LOCK` 只在单次 load 或单次 save 内部生效（L1783、L1971），**锁不住整个读改写区间**。

于是完全可能：

```
请求 X（上传皮肤）: load(无绑定) ──────────────── save(有绑定)   → 磁盘正确
请求 Y（其他保存）:      load(无绑定) ─ save(无绑定)              → 覆盖，绑定丢失
```

会在这个窗口里整份回写 `ui_data` 的已知位置（都读了整份文件再整体保存）：

- `core/data/cache.py` L546 读、L701-703 `save_ui_data(ui_data, allow_shrink=True)`（缓存重载，watchdog/扫描/各类操作都会触发）；
- `core/services/scan_service.py` L807 读、L1009-1011 保存（全量扫描，`resources_dir` 本身就在 watchdog 监视列表里，见 L635-638）；
- `core/api/v1/cards.py` L4237-4241（`get_card_detail` 里 `ensure_import_time` 变更后回写整份）；
- `core/services/card_service.py` L462/L510、`core/api/v1/cards.py` L1777 等。

这些写回都携带**各自读到的旧快照**，任何一次落在"上传创建绑定"与"其保存"之间，就会把绑定抹掉。大库 + 后台扫描/索引重建时窗口明显变长，这也解释了"非必现"。

另外，资源相关端点**没有卡片锁**：`api_upload_card_resource`（`resources.py` L428）、`api_create_resource_folder`（`system.py` L1239）、`api_set_resource_folder`（L1318）都没有 `@request_card_locks`，而 `api_update_card`（`cards.py` L1495）有 —— 两者并发时连"同一张卡串行"的弱保证都没有。

#### 路径 ③：任何一次「带空 `resource_folder` 的卡片保存」都会清掉绑定

`core/api/v1/cards.py` L1718-1774：

```python
new_resource_folder = data.get('resource_folder', '')          # L1722
...
if ui_only:                                                    # L1726
    if new_resource_folder == '' and 'resource_folder' not in ui_only_fields:
        new_resource_folder = existing_ui_entry.get('resource_folder', '')
...
resource_folder_changed = old_resource_folder != new_resource_folder   # L1762-1763
if resource_folder_changed:
    ui_data[ui_key]['resource_folder'] = new_resource_folder           # L1772-1773
```

即：**`resource_folder` 是"权威字段"，传空 = 主动解绑**，唯一的逃生门是 `ui_only_fields` 里显式包含 `resource_folder`。而前端**从未发送过 `ui_only_fields`**（全仓只有后端与测试出现该字段），`ui_only` 也仅由 `wiEditor.js` L3424 和 `wiDetailPopup.js` L729 发送。

于是只要出现下面任一情况，绑定就被真正清空：

- 3.2 的竞态让 `editingData.resource_folder` 变成 `""`，用户随后点了一次「保存」（此时 `hasUnsavedChanges` 为 true，保存几乎必然发生）；
- 用户在详情页「世界书」tab 打开内嵌世界书全屏编辑器（`wiEditor` 保存时透传自己的 `resource_folder`，可能是旧值/空值）；
- 任何第三方路径用陈旧卡片对象调用 `update_card`。

这与"重开/刷新后仍空"完全一致：不是 UI 没刷新，而是 `ui_data.json` 里那条绑定已经没了。

> 补充：清空后如果用户继续拖图，`ensureResourceFolder()`（L1646 看到空值）会再次调用 `/api/create_resource_folder`；若磁盘绑定已空，就会**新建一个 `角色名_1` 的空目录**，图片进新目录，而原来那批图片留在旧目录成为孤儿 —— 与"后台看目录和图片都在"的现象也能对上（此时绑定指向的是新空目录）。

### 3.5 为什么"左侧皮肤条还能看到、图片也能访问"

- `skinImages` 由 `fetchResourceFiles(c.resource_folder)` 用**列表缓存里的**绑定填充（L2224），图片 URL 由 `getSkinUrl()` 直接拼 `/resources_file/<folder>/<path>`（L2907-2911），后端 `serve_resource_file` 只按路径取文件（`resources.py` L334 起），**不校验绑定关系**；
- 资源页的布局却只看 `editingData.resource_folder`。

所以"绑定丢失但文件可访问"是必然表现，不是矛盾。

---

## 四、现象 B 的链路与根因

### 4.1 保存链路上的乐观锁

`core/api/v1/cards.py` L1516-1524：

```python
old_full_path = os.path.join(CARDS_FOLDER, card_id)
requested_revision = str(data.get('source_revision') or '').strip()
current_revision = build_file_source_revision(old_full_path)      # mtime_ns:size
if requested_revision and current_revision and requested_revision != current_revision:
    return jsonify({... 'msg': f'source_revision mismatch: expected {current_revision}'}), 409
```

前端每次保存都带 `source_revision`（`detailModal.js` L2393）。所以**只要卡文件在"前端拿到 revision"之后被改写过，保存就会 409**。

### 4.2 「换图」改写了文件却没回传新 revision / 新 ID（历史版本缺陷）

- 前端入口：`detail_card.html` L329-338「更换图片」→ `detailModal.js` L3383 `triggerImageUpload()` → L3387 `handleImageUpload()` → `/api/change_image`。
- 后端：`core/api/v1/cards.py` L2913-3173 `api_change_image()`：
  - **JSON → PNG 分支**（L2944-3011）：`clean_sidecar_images` → 删除原 `.json`（L2968-2969）→ 保存新 `.png`（L2977）→ `write_card_metadata`（L2980）→ 迁移 `ui_data` 键（L2990）→ 删除旧 DB 行（L3001-3007）→ 删除旧缓存对象（L3011）。**卡片 ID 从 `x.json` 变成 `x.png`**。
  - **PNG → PNG 分支**（L3016-3035）：原地覆盖 + 重写元数据，**mtime/size 必然变化**。
  - 之后 L3042-3048 `os.utime` 并计算 `refreshed_source_revision`，L3158-3167 返回 `new_id` / `source_revision` / `updated_card`。

**历史版本的问题**：`handleImageUpload` 当时只更新了 `activeCard.image_url`，**既没有把 `new_id` 落到 `editingData.id`，也没有同步 `source_revision`**。于是：

- PNG→PNG：前端 revision 是换图前的，文件已变 → 下一次保存 **409 `source_revision mismatch`**；
- JSON→PNG：前端 `editingData.id` 仍指向已删除的 `.json` → 下一次保存时 `old_full_path` 不存在：
  - `extract_card_info` 返回 `None`（L1578），跳过元数据写入；
  - `should_touch_file` 为 False，走到 L1791 `os.path.getmtime(current_full_path)` → `FileNotFoundError` → 被外层 `except` 捕获（L3170-3173）→ 返回 `{"success": False, "msg": ...}`；
  - 顺带在 L1706 给**已不存在的旧 ID 建了一条空 `ui_data` 条目**（脏数据）。

这与"从 json 执行换图后，填 url/备注保存失败"完全对应，且是**确定性复现**的。

该问题已在提交 `03e7079 fix: handle card format updates and preset owner links`（2026-05-14）中修复：后端补 `updated_card.source_revision`，前端补 `Object.assign(activeCard, updatedCard)`、ID 变更处理、`editingData.source_revision` 同步与 `_syncPersistedBaseline(['id','filename','source_revision'])`。用户所述"之前的发布版本"正好落在这个修复之前。

### 4.3 同类缺口仍然存在：皮肤「换封」`set_skin_cover`

当前 main 上**同样的 bug 模式还在另一条链路上**：

- 前端：`detailModal.js` L2562-2597 `setSkinAsCover()` —— 成功后只做：`activeCard.image_url` 加时间戳、`refresh-card-list`、`fetchResourceFiles`、`currentSkinIndex = -1`。**没有更新 `editingData.id` / `filename` / `source_revision`**。
- 后端：`core/api/v1/cards.py` L5068-5085 → `core/services/card_service.py` L676-836 `swap_skin_to_cover()`：
  - JSON 分支（L744-813）把 `.json` 转成 `.png`（换 ID、删旧文件、改 DB、迁移 `ui_data`），返回 `{"success": True, "new_hash", "new_card_id", "converted_to_png": True}` —— **没有 `source_revision`，也没有 `updated_card`**；
  - PNG 分支（L815-833）原地覆盖，返回 `{"success": True, "new_hash"}` —— **同样没有 `source_revision`**。

于是「换封」之后立刻保存：

- JSON 卡：前端仍用 `.json` ID 保存 → 同 4.2 的"文件不存在 → 保存失败"；
- PNG 卡：文件已被改写，前端 revision 陈旧 → **409 mismatch**。

也就是说，**4.2 的修复只覆盖了「更换图片」入口，没有覆盖「皮肤换封」入口**。这是本次分析里最值得优先补的同类缺口。

### 4.4 其它会加剧 B 的因素

- `source_revision` 用的是 `st_mtime_ns:st_size`（`core/utils/source_revision.py`）。换封/换图/外部工具（SillyTavern 写卡、网盘同步、脚本）任何一次触碰都会让已打开的详情页保存失败；这是设计使然，但前端目前**没有 409 的差异化处理**（`detailModal.js` L2404-2484 只做 `alert("保存失败: " + res.msg)`，没有"文件已在别处更新，是否重新载入"的引导）。
- `change_image` 用 `suppress_fs_events(2.5)`（L2923）压制 watchdog；若转换 + 缩略图清理耗时超过 2.5s，watchdog 仍可能看到"删 `.json` + 新增 `.png`"，触发扫描/重命名推断，与 DB/缓存产生二次竞争。
- `change_image` 没有 `@request_card_locks`，可与 `update_card` 并发。
- JSON→PNG 后，前端 `activeCard` 对象被就地改写，但 `cardGrid` 里若存在 `_old_id` 之外的引用（例如收藏/监控池），仍可能持有旧 ID。

---

## 五、如何稳定复现 / 验证（不改代码即可做）

### A 组

1. **竞态复现**：在大库（`ui_data.json` 数 MB）上打开详情页后**立刻**拖入皮肤图；用浏览器 DevTools 把 `/api/get_card_detail` 的响应延迟（Network 面板加节流或 request blocking 后放行）→ 可稳定看到资源页"闪一下回空"。
2. **持久化丢失复现**：把 `data/.../ui_data.json` 设为只读，或临时注入 `save_ui_data` 失败（例如让 `_UI_DATA_LOCK` 内的写抛异常），再拖图：前端一切正常（皮肤条 + 资源页都在），但 `ui_data.json` 无 `resource_folder`；重启后现象与用户描述一致。
3. **清空复现**：手动在 `ui_data` 中写入 `resource_folder` → 打开详情页 → 在 DevTools 里把 `editingData.resource_folder = ''` → 点保存 → `ui_data.json` 中绑定被清空（L1772）。
4. **并发丢更新复现**：脚本并行发起 `/api/upload_card_resource` 与任意整份回写 `ui_data` 的接口（如触发一次缓存重载），多轮后可看到绑定丢失。

### B 组

1. 准备一张 `.json` 卡 → 打开详情 → 用「更换图片」换成 PNG（历史版本）→ 填 URL/备注 → 保存 → 必失败。
2. 当前 main 上换成 **「资源页 → 选中皮肤 → 设为封面」**：
   - JSON 卡：换封后保存 → 失败（文件不存在）；
   - PNG 卡：换封后保存 → `source_revision mismatch` 409。
3. 直接对 `POST /api/set_skin_cover` 断言响应字段：当前不含 `source_revision` / `updated_card`，可作为回归测试的断言点。

---

## 六、修复方向（已全部实施，见第八节）

按"先堵数据丢失、再修竞态、最后补契约"排序：

1. **绑定写入必须原子且可感知失败**
   - 把 `_ensure_card_resource_folder`、`api_create_resource_folder`、`api_set_resource_folder`、`card_service._ensure_resource_folder_exists` 改成 `update_ui_data(mutator)`；
   - **检查返回值**：失败时不要更新缓存，接口返回明确错误（前端提示"资源目录已创建但绑定保存失败，请重试"），避免"内存有、磁盘无"。
2. **`resource_folder` 改为"缺省不覆盖"语义**
   - `api_update_card`：当请求里 `resource_folder` 为 `''` 且不是显式解绑时，保留既有值（把现在 `ui_only` 分支的兜底逻辑推广到所有保存），或让前端统一发送 `ui_only_fields`；
   - 前端保存 payload 里区分"未修改"与"显式清空"。
3. **消除详情页陈旧响应覆盖**
   - `refreshActiveCardDetail` 记录响应里的 `source_revision`（或服务端返回 `ui_revision`），**比本地旧就丢弃**；至少对 `resource_folder` 做"本地已非空则不被空值覆盖"的保护；
   - 上传/建目录成功后调用一次 `refreshActiveCardDetail`，让基线一致。
4. **统一状态源**
   - 资源页布局改读一个 `get effectiveResourceFolder()`（`activeCard` / `editingData` 取其一为真源），避免三份副本漂移；上传成功后补发 `card-updated`，让 `cardGrid` 里的卡片对象同步。
5. **换封补齐契约（B 的同类缺口）**
   - `swap_skin_to_cover` 返回 `new_card_id` / `source_revision`（JSON→PNG 时同时返回 `updated_card`）；
   - 前端 `setSkinAsCover` 复用 `handleImageUpload` 的 ID/revision 同步逻辑；
   - 保存遇到 409 时给出"重新载入并重试"的引导，而不是裸 alert。
6. **补回归测试**
   - 后端：`save_ui_data` 失败时资源目录接口不得更新缓存且要返回失败；`update_card` 传空 `resource_folder` 不得清空既有绑定（除非显式声明）；
   - 前端契约（仓库已有 `tests/test_detail_modal_advanced_editor_contracts.py` 的运行时检查范式）：陈旧 `get_card_detail` 响应不得把非空 `resource_folder` 覆盖为空；`setSkinAsCover` 必须更新 `editingData.id` 与 `source_revision`。

---

## 七、附：关键代码位置索引

| 主题 | 位置 |
|---|---|
| 资源页显示条件 | `templates/modals/detail_card.html` L3187、L3209、L3217 |
| 左侧皮肤条 | `templates/modals/detail_card.html` L33-L104 |
| 详情刷新覆盖 `resource_folder` | `static/js/components/detailModal.js` L2304（请求令牌 L2233/L2243） |
| 打开详情初始值 | `static/js/components/detailModal.js` L2189、L2224、L2228 |
| 拖拽/上传/建目录 | `static/js/components/detailModal.js` L1546、L1613-1638、L1640-1684 |
| 皮肤 URL / 列表 | `static/js/components/detailModal.js` L1687-1721、L2907-2915 |
| 后端自动建目录 | `core/api/v1/resources.py` L196-230（`save_ui_data` L225 忽略返回值） |
| 后端手动建/设目录 | `core/api/v1/system.py` L1239-1316、L1318-1383 |
| 保存时清空绑定 | `core/api/v1/cards.py` L1718-1774（`ui_only_fields` L1723-1730） |
| 乐观锁 409 | `core/api/v1/cards.py` L1516-1524 |
| `source_revision` 定义 | `core/utils/source_revision.py` L4-L9 |
| 换图（更换图片） | `core/api/v1/cards.py` L2913-3173；前端 `detailModal.js` L3387-3432 |
| 换封（设为封面） | `core/services/card_service.py` L676-836；`core/api/v1/cards.py` L5068-5085；前端 `detailModal.js` L2562-2597 |
| ui_data 事务写入口 | `core/data/ui_store.py` L2023-2068 |
| 保存失败语义 | `core/data/ui_store.py` L1956-2006 |
| 整份回写 `ui_data` 的并发点 | `core/data/cache.py` L546/L701-703；`core/services/scan_service.py` L807/L1009；`core/api/v1/cards.py` L4237-4241 |
| 历史修复（现象 B） | commit `03e7079`（2026-05-14） |

---

## 八、实施记录

按 §6 的六条建议逐条落地，**未压缩为最小补丁**：把「资源目录绑定」收口为单一服务，
把「卡片文件已改写」收口为单一前端收敛点。

### 8.1 新增：绑定的单一写入口

`core/services/card_resource_binding_service.py`（新文件）：

| 函数 | 职责 |
|---|---|
| `resolve_resource_root(cfg=None)` | 资源根目录解析（兼容绝对路径配置） |
| `resource_folder_abs_path(binding, root=None)` | 绑定值 → 绝对路径 |
| `build_unique_resource_folder_name(root, name)` | 安全且不重名的目录名（原 `resources.py` 逻辑上移） |
| `read_card_resource_folder(ui_key, loader=None)` | 只读绑定 |
| `bind_card_resource_folder(ui_key, folder=None, *, allow_existing, loader, saver)` | **原子**写入绑定，返回 `{'ok','resource_folder','changed','msg'}` |
| `find_recoverable_resource_folder(name, *, card_ui_key, resources_root, loader)` | 找「名字」或「名字_N」且未被他人绑定的既有目录 |

`bind_card_resource_folder` 用 `update_ui_data(mutator)` 在 `_UI_DATA_LOCK` 内完成
「读→改→写」，写入失败返回 `ok=False` 而不是静默成功。

### 8.2 四条绑定链路改为原子写入 + 失败传播

| 入口 | 改法 |
|---|---|
| `resources.py:_ensure_card_resource_folder` | 读绑定 → 尝试接管既有目录 → 否则建目录并原子绑定；**绑定失败不写缓存**，返回错误并 `os.rmdir` 回滚空目录 |
| `system.py:api_create_resource_folder` | 同上；接管成功返回 `binding_restored: true`；绑定失败返回 `500` + `binding_failed: true` 并清理空目录 |
| `system.py:api_set_resource_folder` | 原子绑定；失败 `500` + `binding_failed: true`，不更新缓存 |
| `card_service.py:_ensure_resource_folder_exists` | 原子绑定；失败抛新增的 `ResourceFolderBindingError`，由归档链路决定收尾（`_archive_file` 重新抛出，`update_card_content` 转成明确的失败结果，不再「归档失败但继续覆盖」） |

### 8.3 `resource_folder` 改为「缺省不覆盖」语义

- 后端 `api_update_card`：`clear_ui_fields` 白名单与 `ui_only_fields` 合并；
  `resource_folder` 为空且不在白名单里时，沿用既有绑定（`cards.py` L1718-1745）。
  显式解绑需要传 `clear_ui_fields: ['resource_folder']`。
- 前端 `detailModal._internalSaveCard`：本来就没绑定时才发 `clear_ui_fields`，
  非空时发空数组，语义与旧行为一致。
- `card_service.update_card_content`：`keep_ui_data` 里的空 `resource_folder` 不再覆盖既有绑定。
- 两处 `save_ui_data` 补齐返回值检查：`update_card_content` 与 `api_update_card` 失败时
  返回结构化错误（`ui_data_save_failed: true`），不再「文件改了但备注丢了」。

### 8.4 前端消除陈旧响应覆盖

`static/js/components/detailModal.js`：

- 新增状态 `editingRevision` / `lastPersistedResourceFolder` / `_saveConflictRetried`；
- `refreshActiveCardDetail` 记录请求发出前的本地值，响应回来时判定
  `staleResourceFolder`（本地已持久化非空、响应为空）与 `staleRevision`
  （响应不比本地新），命中则不覆盖；
- 上传资源、建目录、设目录、换图、换封、覆盖更新成功后都更新
  `lastPersistedResourceFolder` 并派发 `card-updated`，让 `cardGrid` 同步。

### 8.5 换封补齐修订号契约

- `card_service.swap_skin_to_cover` 统一走新增的 `_build_skin_cover_result`，
  返回 `source_revision` / `new_card_id` / `new_filename` / `new_image_url` /
  `new_thumb_url` / `updated_card`，并刷新内存缓存里的 URL 与修订号；
  JSON→PNG 分支同样返回（旧实现连 `new_card_id` 都没有 revision 伴随）。
- `api_set_skin_cover` 直接透传（`jsonify(result)`，无需改动）。
- 前端 `detailModal` 新增 `_applyPersistedCardMutation(res)`，`handleImageUpload`
  与 `setSkinAsCover` 共用：吸收 `source_revision` / `id` / `filename` /
  `image_url` / `thumb_url` 并同步到自动保存基线。

### 8.6 回归测试

- `tests/test_resource_binding_durability.py`（新增 8 项）：绑定写失败不写缓存且清空目录、
  上传失败如实报错、孤儿目录接管不新建 `_1`、不抢占他人绑定、原子绑定幂等、
  空值不清绑定、显式清空生效、换封返回修订号与新 ID。
- `tests/test_card_source_revision_contracts.py` 扩充：陈旧响应保护、`card-updated`
  吸收、409 恢复、`clear_ui_fields` 语义、`wi-editor-closed` 交还修订号。
- `tests/test_detail_modal_advanced_editor_contracts.py` 扩充运行时断言：
  `_absorbExternalCardUpdate` 的新旧判定与跨卡忽略、`_applyPersistedCardMutation`
  的 ID/修订号同步、保存 payload 的 `clear_ui_fields`、409「重新载入/覆盖保存」
  两条分支与二次冲突收敛。

