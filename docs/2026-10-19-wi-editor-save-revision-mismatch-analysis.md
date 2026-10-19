# 详情页「全屏世界书编辑器保存后，详情页再保存报 source_revision mismatch」分析

> 状态：**已按第六节方案实施**（见第八节）。
> 范围：`static/js/components/detailModal.js`、`static/js/components/wiEditor.js`、
> `static/js/components/cardGrid.js`、`core/api/v1/cards.py`、`core/utils/source_revision.py`。
> 关联文档：
> - [角色卡资源绑定与换图保存失败分析](2026-10-19-card-resource-binding-and-save-failure-analysis.md)
> - [全屏世界书编辑器拖拽高亮残留分析](2026-10-19-wi-editor-drag-indicator-residue-analysis.md)

---

## 一、复现步骤

1. 详情页 → 世界书 tab → 打开**全屏世界书编辑器**（内嵌 / embedded 模式）。
2. 修改世界书内容 → 在编辑器里保存。
3. 关闭世界书编辑器，回到详情页。
4. 在详情页点「保存」→ 报错：

   ```
   保存失败: source_revision mismatch: expected <mtime_ns>:<size>
   ```

---

## 二、结论

**是同一个「乐观锁契约」问题，但与你前面问的「资源目录绑定」问题不是同一个问题；
它与「换图 / 换封后保存失败」属于同一个根因族，而且是在那次修复（commit `03e7079`）之后
仍然存在的第二个未修复实例。**

一句话：

> 全屏世界书编辑器保存时**改写了卡片文件**，新的 `source_revision` 只回写到了**编辑器自己**
> 的 `editingData`，没有回传给**详情页**的 `editingData`；详情页随后保存时仍带着旧 revision，
> 被 `api_update_card` 的乐观锁以 409 拒绝。

对照之前两个问题：

| 问题 | 触发组件 | 是否同一问题 |
|---|---|---|
| 资源页闪回空状态 / 重启后绑定消失 | 资源上传 + `ui_data` 持久化 | **不同**（那是状态/持久化问题，不涉及乐观锁） |
| JSON 卡换图后保存失败 | `change_image` / `set_skin_cover` → 详情页 | **同一根因族**（改了文件没回传 revision） |
| 本问题：世界书编辑器保存后详情页保存失败 | `wiEditor` → 详情页 | **同一根因族的新实例**，但组件对、触发路径不同 |

---

## 三、机制拆解（逐跳证据）

### 3.1 世界书编辑器的编辑态是详情页的**深拷贝快照**

`static/js/components/detailModal.js` L1919-1932 `openFullScreenWI()`：

```js
const item = {
    type: 'embedded',
    card_id: this.activeCard.id,
    name: this.editingData.character_book?.name || "World Info",
    character_book: JSON.parse(JSON.stringify(this.editingData.character_book)),
    editingData: JSON.parse(JSON.stringify(this.editingData)),   // L1929 ← 整份深拷贝
};
window.dispatchEvent(new CustomEvent('open-wi-editor', { detail: item }));
```

`JSON.parse(JSON.stringify(...))` 让两边**完全脱离引用关系**：
此后编辑器里对 `editingData.source_revision` 的任何更新，详情页都感知不到。

（打开前详情页的 revision 是有效的：`refreshActiveCardDetail` 在 L2305 从
`/api/get_card_detail` 写入了 `editingData.source_revision`，后端在 `cards.py` L4183 返回当前文件 revision。）

### 3.2 编辑器保存 → 卡文件被改写 → revision 变化

`static/js/components/wiEditor.js` L2941-2966 `saveChanges()` 构造 payload：

```js
const payload = {
  id: this.editingData.id,
  ...cleanData,
  char_name: cleanData.name || this.editingData.char_name,
  new_filename: this.editingData.filename,
  ui_summary: this.editingData.ui_summary || "",
  source_link: this.editingData.source_link || "",
  resource_folder: this.editingData.resource_folder || "",
  source_revision: this.editingData.source_revision || "",        // L2954 编辑器自己的 revision
  ...
  character_book: cleanData.character_book,
};
updateCard(payload)
```

后端 `core/api/v1/cards.py`：

- L1590 起比对 `character_book`，内容变化 → `target['character_book'] = new_book`、`file_content_modified = True`（L1661-1664）；
- L1666-1668 `write_card_metadata(old_full_path, info)` **重写卡文件**（PNG 的元数据块，文件 size 变化）；
- L1781-1788 `should_touch_file = True` → `os.utime(...)` 更新 mtime；
- L2208-2210 `refreshed_source_revision = build_file_source_revision(current_full_path)` 并写入返回对象。

`source_revision` 的定义是 `f'{st_mtime_ns}:{st_size}'`（`core/utils/source_revision.py` L4-9），
所以**内容一改，revision 必然变化**。

### 3.3 新 revision 只回写给编辑器自己

`wiEditor.js` L2970-2973（保存成功分支）：

```js
this.editingData.source_revision =
  res.updated_card?.source_revision ||
  this.editingData.source_revision || "";
```

注意这是**编辑器实例**的 `editingData` —— 前面 3.1 已经证明它与详情页的 `editingData`
不是同一个对象。随后 L2982-2984 只派发了 `card-updated` 事件：

```js
window.dispatchEvent(new CustomEvent("card-updated", { detail: res.updated_card }));
```

而**详情页没有监听 `card-updated`**（全仓只有 `static/js/components/cardGrid.js` L307 监听，
用于刷新卡片列表；`detailModal.js` 里没有任何 `card-updated` 监听）。所以详情页拿不到新 revision。

### 3.4 关闭编辑器时回传的载荷里**没有 revision**

`wiEditor.js` L733-774，`$watch("showFullScreenWI")` 关闭分支：

```js
const closeDetail = {
  card_id: this.editingData.id || this.editingWiFile.card_id,   // L757-760
  changed: hasWorldbookChanges,
};
if (hasWorldbookChanges || hasSavedWorldbook) {
  closeDetail.character_book = JSON.parse(currentWorldbookJson);        // 只回传世界书内容
}
if (hasSavedWorldbook) {
  closeDetail.persisted_character_book = JSON.parse(this.embeddedWorldbookLastSavedJson);
}
window.dispatchEvent(new CustomEvent("wi-editor-closed", { detail: closeDetail }));
```

`detailModal.js` L1935-1964 的 `handleEditorClosed` 也只做两件事：

```js
this.editingData.character_book = currentWorldbook;
this.editingData.character_book_raw = JSON.stringify(currentWorldbook, null, 2);
...
this._syncPersistedBaseline(
  ['character_book', 'character_book_raw'],     // L1950-1956 只重置世界书基线
  { character_book: persisted_character_book, character_book_raw: ... },
);
```

**全程没有触碰 `editingData.source_revision`。**

### 3.5 详情页保存 → 带着旧 revision → 409

`detailModal.js` L2382-2404 `_internalSaveCard()`：

```js
const payload = {
  id: this.editingData.id,
  new_filename: this.editingData.filename,
  ...cleanData,
  ui_summary: ...,
  source_link: ...,
  resource_folder: ...,
  source_revision: this.editingData.source_revision || "",   // L2393 ← 旧值
  ...
};
return updateCard(payload).then(...)
```

后端 `cards.py` L1516-1524：

```python
old_full_path = os.path.join(CARDS_FOLDER, card_id)
requested_revision = str(data.get('source_revision') or '').strip()
current_revision = build_file_source_revision(old_full_path)
if requested_revision and current_revision and requested_revision != current_revision:
    return jsonify({
        'success': False,
        'msg': f'source_revision mismatch: expected {current_revision}',
        'current_source_revision': current_revision,
    }), 409
```

前端 L2476-2479 直接 `alert("保存失败: " + res.msg)` —— 就是你看到的报错。

### 3.6 为什么"看起来没改什么却报错"

关闭编辑器时 `_syncPersistedBaseline(['character_book', 'character_book_raw'])`（L1950-1956）
已经把世界书基线重置成"已保存"状态，所以 `hasUnsavedChanges` 可能为 false，
详情页看起来一切正常；但 revision 是**文件级**的，与世界书内容是否已同步无关。
这就是"我明明没改详情页的数据，怎么一保存就冲突"的直观困惑来源。

---

## 四、与前面两个问题的准确关系

| 维度 | 现象 A（资源绑定/闪回） | 现象 B（换图/换封后保存失败） | 本问题 |
|---|---|---|---|
| 直接错误 | 布局回退、绑定丢失 | `source_revision mismatch` / 文件不存在 | `source_revision mismatch` |
| 失败点 | `ui_data` 持久化 + 前端竞态 | `cards.py` L1516-1524 乐观锁；JSON→PNG 后文件不存在 | `cards.py` L1516-1524 乐观锁 |
| 根因 | 状态源分裂 / 写入不落盘 | 「改了卡文件，但新 revision（和新 ID）没回传前端」 | 同上，只是"前端"具体是**详情页** |
| 组件对 | 资源上传 ↔ 详情页 | 换图/换封 ↔ 详情页 | **世界书编辑器 ↔ 详情页** |
| 是否已被修 | 否 | 「换图」入口已由 `03e7079` 修复；「换封」入口仍未修 | **否（未修）** |

所以：

- **不是**和"资源目录绑定消失"同一个问题（那边根本不涉及乐观锁）；
- **是**和"换图后保存失败"同一个契约缺口的不同实例。可以把它们统一表述为：

  > **凡是会在后台改写卡片文件的操作，都必须把新的 `source_revision`
  > （以及可能变化的 `id` / `filename`）广播给所有持有该卡编辑态的前端组件。
  > 目前只有"更换图片"入口做到了；"换封""全屏世界书编辑器保存"都还是漏的。**

---

## 五、同一流程里还藏着两个相邻风险（建议一起看）

### 5.1 世界书编辑器保存可能顺手清空资源目录绑定

`wiEditor.js` L2953：

```js
resource_folder: this.editingData.resource_folder || "",
```

它**没有** `ui_only`，也**没有** `ui_only_fields`。而 `cards.py` L1722-1774 把
`resource_folder` 当权威字段：传空即解绑（详见资源绑定分析文档 3.4 路径③）。
于是：如果世界书编辑器是**在资源目录创建/变更之前**打开的（或详情页处于"闪回空值"状态时打开），
这次世界书保存就会把 `ui_data` 里的 `resource_folder` 清空 —— 与现象 A 的持久化丢失是同一条路径。

### 5.2 编辑器持有的是打开瞬间的 `id` / `filename`

若在编辑器打开期间卡片发生过 JSON→PNG 转换（换图 / 换封 / 覆盖更新），
`wiEditor` 的 `this.editingData.id` 仍指向已删除的旧文件，保存会失败（同现象 B 的 JSON 分支）。

### 5.3 反向也会冲突

反过来：先在详情页保存、再在（已打开的）世界书编辑器里保存 → 编辑器同样会 409。
只要两个组件同时持有编辑态，这个对称的冲突就会存在。

---

## 六、修复方向（已实施 6.1 + 6.2 + 6.4 + 6.5，见第八节）

### 6.1 首选：编辑器保存成功后把新 revision 同步回详情页

在 `wi-editor-closed` 的载荷里补 `source_revision`（以及 `id` / `filename`），
`handleEditorClosed` 里做：

```js
this.editingData.source_revision = detail.source_revision || this.editingData.source_revision;
this._syncPersistedBaseline(['character_book', 'character_book_raw', 'source_revision']);
```

这能最小代价修掉当前症状。

### 6.2 更稳：让详情页订阅 `card-updated` 并只吸收"文件级"字段

``detailModal` 在 `init()` 里监听 `card-updated`，若 `detail.id` 与当前 `editingData.id` 一致，
只合并 `source_revision` / `id` / `filename` / `image_url` 等**非编辑内容字段**，
并用 `_syncPersistedBaseline` 同步基线。这样所有"后台改写卡片"的入口（换图、换封、
世界书保存、插件写入、外部文件变更）都能自动收敛，不必逐个补。

### 6.3 统一"修订号广播"的机制

更彻底的做法是把 `source_revision` 当作卡片级的**版本令牌**：

- 后端所有写卡路径都返回新 revision（换封现在就缺，见现象 B 文档 4.3）；
- 前端有一个共享的 `cardRevisions[cardId]` 存储，任何组件保存成功后更新它；
- 各编辑组件在保存前取最新值，或在 409 时自动"重新载入该卡 revision 后重试一次"
  （对纯文本/世界书这类可自动合并的场景，重试是安全的）。

### 6.4 409 的用户体验兜底

当前详情页遇到 409 只弹 `保存失败: source_revision mismatch: ...`（`detailModal.js` L2477），
用户完全不知道该怎么办。建议识别 409 / `current_source_revision`：

- 提示"卡片文件已在其他窗口/编辑器中被修改"，并提供「重新载入最新内容（放弃本次改动）」
  与「覆盖保存（用最新 revision 重试）」两个选项；
- 至少要**自动刷新一次 `refreshActiveCardDetail`**，避免用户卡在死循环里反复点保存。

### 6.5 补回归测试

- 前端契约（仓库已有 `tests/test_detail_modal_advanced_editor_contracts.py` 的运行时范式）：
  「`wi-editor-closed` 带 `source_revision` 时，详情页 `editingData.source_revision` 必须更新」；
  「详情页收到 `card-updated` 时必须吸收 `source_revision`」。
- 后端：`POST /api/update_card`（世界书内容变化）响应必须含最新 `source_revision`（当前已有，
  `cards.py` L2208-2210），建议再加一条"保存后立刻用返回值再次保存应成功"的端到端断言。

---

## 七、关键位置索引

| 主题 | 位置 |
|---|---|
| 详情页打开世界书编辑器（深拷贝 `editingData`） | `static/js/components/detailModal.js` L1919-1932（L1929） |
| 详情页接收关闭事件（只同步世界书，无 revision） | `static/js/components/detailModal.js` L1935-1964（基线 L1950-1956） |
| 详情页保存 payload（旧 revision） | `static/js/components/detailModal.js` L2382-2404（L2393） |
| 详情页 409 处理（裸 alert） | `static/js/components/detailModal.js` L2476-2479 |
| 世界书编辑器保存 payload | `static/js/components/wiEditor.js` L2941-2966（L2953 / L2954） |
| 编辑器更新自己的 revision | `static/js/components/wiEditor.js` L2970-2973 |
| 编辑器广播 `card-updated`（详情页未订阅） | `static/js/components/wiEditor.js` L2982-2984；订阅方仅 `cardGrid.js` L307-342 |
| 编辑器关闭事件载荷 | `static/js/components/wiEditor.js` L733-774（L757-773） |
| 乐观锁校验（409） | `core/api/v1/cards.py` L1516-1524 |
| 写卡文件 / utime | `core/api/v1/cards.py` L1666-1668、L1781-1788 |
| 响应回填最新 revision | `core/api/v1/cards.py` L2208-2210 |
| `get_card_detail` 返回 revision | `core/api/v1/cards.py` L4183 |
| revision 定义 | `core/utils/source_revision.py` L4-9 |
| `resource_folder` 权威字段语义 | `core/api/v1/cards.py` L1718-1774 |

---

## 八、实施记录

采用「6.1 + 6.2 + 6.4 + 6.5 一起上」的组合：单点补丁只能修掉当前这条路径，
下一个改写卡文件的入口（换图、换封、插件写入、外部变更）还会复现同一个 409，
所以把「修订号广播与吸收」做成统一机制。

### 8.1 编辑器交还修订号（6.1）

`static/js/components/wiEditor.js`：

- 保存成功后除自身的 `editingData.source_revision`，还跟随后端返回的
  `res.source_revision` / `res.new_id` / `res.updated_card.filename`，
  避免格式转换后拿着已不存在的旧 ID 继续保存；
- `showFullScreenWI` 关闭分支的 `wi-editor-closed` 载荷补充
  `source_revision` / `card_id` / `filename`。

`static/js/components/detailModal.js:handleEditorClosed` 接收后：

- 更新 `editingRevision` 与 `editingData.source_revision`，并
  `_syncPersistedBaseline(['source_revision'])`，让自动保存基线不再认为"有未保存改动"；
- 同步 `id` / `filename` 并刷新基线。

### 8.2 详情页订阅 `card-updated`（6.2）

`detailModal.init()` 注册全局监听，`_absorbExternalCardUpdate(detail)` 只吸收
**文件级字段**：

- 校验同一卡片（`id` 相同，或同 bundle 的 `bundle_dir` 相同），跨卡事件直接忽略；
- `source_revision` 用 `_isRevisionNewer` 判定（`<mtime_ns>:<size>` 取时间戳部分比较），
  旧修订号与相同修订号都不写入；
- `filename` / `image_url` / `resource_folder` 按需合并，正文内容一律不碰。

这样换图、换封、世界书保存、插件写入、外部文件变更都能自动收敛。

### 8.3 统一广播的配套设施

- `_applyPersistedCardMutation(res, {refreshListEvent})`：换图 / 换封 / 覆盖更新共用，
  吸收新 ID、新修订号、新图片 URL，并派发 `card-updated` 给其他组件；
- 上传资源与自动建目录成功后也派发 `card-updated`（带新 `resource_folder`），
  让 `cardGrid` 里的卡片对象同步，不再只更新详情页本地状态。

### 8.4 409 的用户体验（6.4）

`detailModal.handleSaveConflict(res)`：

- `api/card.js:updateCard` 在非 2xx 时把 `status` / `http_status` 带回前端，
  `cards.py` 的 409 响应补 `status: 409`；
- 识别冲突后弹确认框，明确两个选项：
  「确定 = 重新载入最新内容（放弃本次改动）」「取消 = 用最新修订号覆盖保存」；
- 覆盖保存只自动重试**一次**：`_saveConflictRetried` 标记，二次冲突直接转为重新载入，
  避免在别人持续写入时无限覆盖；
- `reloadActiveCardFromDisk()` 清掉本地修订号后调 `refreshActiveCardDetail`，
  并提示「已重新载入最新内容」。

### 8.5 回归测试（6.5）

- `tests/test_card_source_revision_contracts.py`：锁定编辑器关闭载荷带
  `source_revision` / `card_id` / `filename`、详情页吸收、409 处理、`clear_ui_fields` 语义；
- `tests/test_detail_modal_advanced_editor_contracts.py`：
  - `test_detail_modal_runtime_absorbs_newer_revision_only`：新修订号吸收、相同/更旧/跨卡忽略；
  - `test_detail_modal_runtime_apply_persisted_mutation_syncs_id_and_revision`：
    换封后 ID 与修订号同步、图片 URL 走缓存刷新；
  - `test_detail_modal_runtime_save_sends_clear_ui_fields_only_when_unbound`：保存语义；
  - `test_detail_modal_runtime_conflict_offers_reload_or_retry_with_latest_revision`：
    两条分支 + 二次冲突收敛。

### 8.6 验证结果

- 全套 `pytest tests/`：**3832 passed / 2 skipped**；
  仅 4 个 `test_worldbook_content_update.py` 的符号链接用例因本机缺少
  `SeCreateSymbolicLinkPrivilege`（`WinError 1314`）失败，与本次改动无关且文件未改动。
- `node --check` 覆盖三个改动的 JS 文件。

