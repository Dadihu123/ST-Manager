# API 文档

本文档整理当前项目中主要对外接口，覆盖角色卡、聊天、世界书、预设、扩展脚本、自动化、系统设置、SillyTavern 同步、美化库与资源服务。

说明：

- 绝大多数接口返回 JSON
- 上传接口通常使用 `multipart/form-data`
- 开启外网认证后，未命中白名单的请求需要先登录会话
- 少量文件预览 / 导出接口返回文件流而不是 JSON
- 最终实现以 `core/api/v1/*.py` 为准

---

## 1. 系统与设置

### 1.1 系统状态与索引

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/status` | 获取后台初始化状态 |
| `GET` | `/api/index/status` | 获取索引构建状态 |
| `POST` | `/api/index/rebuild` | 重建索引 |
| `POST` | `/api/scan_now` | 手动触发扫描 |

索引重建示例：

```json
{
  "scope": "cards"
}
```

`scope` 当前主要为 `cards` 或 `worldinfo`。

### 1.2 设置读取与保存

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/get_settings` | 获取当前设置 |
| `POST` | `/api/save_settings` | 保存设置 |
| `POST` | `/api/settings_path_safety` | 检查 ST 路径与资源路径安全性 |

保存设置时可直接提交配置对象，也可包在 `config` 字段内。若路径冲突或存在高风险覆盖，后端可能返回 `409`，要求前端二次确认。

### 1.3 快照、备份与系统动作

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/create_snapshot` | 创建手动快照 |
| `POST` | `/api/smart_auto_snapshot` | 按内容哈希智能创建自动快照 |
| `POST` | `/api/list_backups` | 获取备份 / 快照列表 |
| `POST` | `/api/restore_backup` | 从备份恢复 |
| `POST` | `/api/cleanup_init_backups` | 清理初始化快照 |
| `POST` | `/api/system_action` | 执行打开目录等系统动作 |
| `POST` | `/api/trash/open` | 打开回收站目录 |
| `POST` | `/api/trash/empty` | 清空回收站 |
| `POST` | `/api/read_file_content` | 读取文件内容供差异预览 / 编辑器使用 |
| `POST` | `/api/user-db-backup/export` | 导出用户数据库包 |
| `POST` | `/api/user-db-backup/import` | 导入用户数据库包 |

### 1.4 共享壁纸与背景

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/shared-wallpapers/import` | 导入共享壁纸 |
| `POST` | `/api/shared-wallpapers/select` | 选择共享壁纸 |
| `POST` | `/api/upload_background` | 上传管理器背景图 |

---

## 2. 角色卡 API

来源：`core/api/v1/cards.py`

### 2.1 列表与详情

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/list_cards` | 角色卡主列表 |
| `POST` | `/api/get_card_detail` | 获取单张角色卡详情 |
| `POST` | `/api/find_card_page` | 根据目标卡定位页码 |
| `POST` | `/api/random_card` | 随机返回一张角色卡 |
| `POST` | `/api/get_raw_metadata` | 读取原始卡片元数据 |
| `POST` | `/api/cards/source_update/targets` | 解析并冻结批量来源检查目标 |
| `POST` | `/api/cards/source_update/check` | 检查单张卡片来源更新 |
| `POST` | `/api/cards/source_update/check_batch` | 顺序检查多张卡片来源更新，记录失败并继续 |

`/api/cards/source_update/check_batch` 返回 `selected`、`checked`、`updated`、`unchanged`、`skipped`、`failed` 和 `details`。不支持的来源计入 `skipped`；网络或其他单卡异常计入 `failed`，不会阻止后续卡片检查。

`/api/list_cards` 常用查询参数：

| 参数 | 说明 |
| --- | --- |
| `page` / `page_size` | 分页 |
| `category` | 当前分类 |
| `tags` | 以 `|||` 分隔的标签列表 |
| `excluded_tags` | 排除标签 |
| `search` | 搜索关键词 |
| `search_mode` | `fast` 或 `fulltext` |
| `search_type` | `mix`、`name`、`filename`、`tags`、`creator` |
| `search_scope` | `current`、`all_dirs`、`full` |
| `all_dirs_only_with_filters` | 为 `true` 且 `recursive=true` 时，`all_dirs` 仅在存在实际筛选条件时生效；无筛选时回到当前分类 |
| `sort` | `date_desc`、`date_asc`、`import_desc`、`import_asc`、`name_asc`、`name_desc`、`token_desc`、`token_asc` |
| `fav_filter` | `none`、`included`、`excluded` |
| `favorites_first` | 收藏置顶 |
| `recursive` | 递归分类 |
| `token_min` / `token_max` | Token 范围 |
| `import_date_from` / `import_date_to` | 导入时间范围 |
| `modified_date_from` / `modified_date_to` | 修改时间范围 |

详情接口示例：

```json
{
  "id": "角色/示例卡.png",
  "preview_wi": true,
  "force_full_wi": false,
  "wi_preview_limit": 300,
  "wi_preview_entry_max_chars": 2000
}
```

### 2.2 编辑、收藏与文件替换

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/update_card` | 更新角色卡内容或 UI 元数据 |
| `POST` | `/api/update_card_file` | 用新文件替换已有角色卡 |
| `POST` | `/api/toggle_favorite` | 切换收藏状态 |
| `POST` | `/api/change_image` | 更换角色卡图片 |
| `POST` | `/api/normalize_card_data` | 规范化卡片数据 |
| `POST` | `/api/update_card_from_url` | 根据来源链接重新抓取并更新 |

### 2.2.1 类脑搜索站预览

来源：`core/api/v1/forum.py`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/forum/thread_preview` | 从来源链接解析帖子 ID，转发查询类脑搜索站 |

请求体（二选一或同时提供）：

```json
{
  "source_link": "https://discord.com/channels/{guild}/{thread}",
  "card_id": "角色/示例卡.png"
}
```

说明：

- URL 为两段 ID 时取最后一段；三段 ID 时取中间段作为帖子 ID
- 使用配置项 `shimmerday_forum_cookie` 访问 `https://forum.shimmerday.top/v1/search/thread/{id}`
- 成功时返回 `{ "success": true, "thread_id": "...", "data": { ...上游 JSON... } }`

`/api/update_card` 支持大量字段，常见字段如下：

```json
{
  "id": "角色/示例卡.png",
  "char_name": "角色名",
  "description": "描述",
  "tags": ["标签1", "标签2"],
  "extensions": {},
  "character_book": {},
  "ui_summary": "本地摘要",
  "source_link": "https://example.com/card",
  "resource_folder": "角色资源目录",
  "source_revision": "..."
}
```

说明：

- `source_revision` 用于并发写保护，冲突时会返回 `409`
- 可通过 `ui_only` 只更新本地 UI 字段而不改原卡文件
- 支持 Bundle / 版本保存相关字段

### 2.3 导入、批量上传与删除

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/import_from_url` | 从 URL 下载并导入角色卡 |
| `POST` | `/api/upload/stage` | 批量上传第一阶段：暂存并分析冲突 |
| `POST` | `/api/upload/commit` | 批量上传第二阶段：按决策正式导入 |
| `GET` | `/api/temp_preview/<batch_id>/<path:filename>` | 预览暂存图片 |
| `POST` | `/api/delete_cards` | 批量删除角色卡 |
| `POST` | `/api/check_resource_folders` | 删除前检查关联资源目录 |
| `POST` | `/api/upload_note_image` | 上传笔记图片 |

删除示例：

```json
{
  "card_ids": ["角色/卡1.png", "角色/卡2.json"],
  "delete_resources": true
}
```

### 2.4 分类、文件夹与资源目录

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/move_card` | 移动角色卡到目标分类 |
| `POST` | `/api/create_folder` | 创建分类目录 |
| `POST` | `/api/rename_folder` | 重命名分类目录 |
| `POST` | `/api/delete_folder` | 删除或解散分类目录 |
| `POST` | `/api/move_folder` | 移动或合并分类目录 |
| `POST` | `/api/set_skin_cover` | 将资源皮肤设为封面 |

### 2.5 标签治理与分类视图

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/tag_order` | 获取标签排序配置 |
| `POST` | `/api/tag_order` | 保存标签排序配置 |
| `GET` | `/api/tag_taxonomy` | 获取标签分类体系 |
| `POST` | `/api/tag_taxonomy` | 保存标签分类体系 |
| `GET` | `/api/tag_management_prefs` | 获取标签管理偏好 |
| `POST` | `/api/tag_management_prefs` | 保存标签管理偏好 |
| `GET` | `/api/isolated_categories` | 获取隔离分类配置 |
| `POST` | `/api/isolated_categories` | 保存隔离分类配置 |
| `POST` | `/api/delete_tags` | 批量删除标签 |
| `POST` | `/api/batch_tags` | 批量增删标签 |
| `POST` | `/api/preview_merge_tags` | 预览标签合并结果 |

### 2.6 Bundle 与辅助接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/toggle_bundle_mode` | 切换 Bundle 模式 |
| `POST` | `/api/convert_to_bundle` | 将卡片转换为 Bundle |

---

## 3. 聊天记录 API

来源：`core/api/v1/chats.py`

### 3.1 列表与详情

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/chats/list` | 获取聊天列表 |
| `POST` | `/api/chats/detail` | 获取聊天详情 |
| `POST` | `/api/chats/range` | 分页读取消息区间 |

`/api/chats/list` 常用参数：

| 参数 | 说明 |
| --- | --- |
| `page` / `page_size` | 分页 |
| `search` | 搜索关键词 |
| `filter` | `all`、`bound`、`unbound`、`favorites` |
| `fav_filter` | `none`、`included`、`excluded` |
| `card_id` | 仅返回绑定到指定角色卡的聊天 |

详情示例：

```json
{
  "id": "角色名/聊天文件.jsonl",
  "include_messages": true,
  "include_message_index": true
}
```

### 3.2 元数据、绑定与保存

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/chats/update_meta` | 更新本地元数据 |
| `POST` | `/api/chats/bind` | 绑定或解绑到角色卡 |
| `POST` | `/api/chats/import` | 导入聊天文件 |
| `POST` | `/api/chats/save` | 保存聊天内容 |

更新元数据示例：

```json
{
  "id": "角色名/聊天文件.jsonl",
  "display_name": "自定义显示名",
  "notes": "本地备注",
  "favorite": true,
  "last_view_floor": 128,
  "bookmarks": []
}
```

### 3.3 搜索与删除

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/chats/search` | 搜索聊天正文 |
| `POST` | `/api/chats/delete` | 删除聊天记录 |

搜索示例：

```json
{
  "query": "关键词",
  "limit": 80,
  "card_id": "可选角色卡ID",
  "chat_ids": []
}
```

---

## 4. 世界书 API

来源：`core/api/v1/world_info.py`

### 4.1 列表、详情与搜索

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/world_info/list` | 获取世界书列表 |
| `POST` | `/api/world_info/detail` | 获取世界书详情 |
| `POST` | `/api/world_info/detail_search` | 在详情数据中检索条目 |
| `POST` | `/api/world_info/entry_history/list` | 获取条目历史 |

`/api/world_info/list` 常用参数：

| 参数 | 说明 |
| --- | --- |
| `type` | `all`、`global`、`resource`、`embedded` |
| `search` | 搜索关键词 |
| `category` | 分类 |
| `search_mode` | `fast` 或 `fulltext` |
| `page` / `page_size` | 分页 |

详情示例：

```json
{
  "id": "world_info_id",
  "source_type": "global",
  "file_path": "data/library/lorebooks/example.json",
  "card_id": "可选",
  "preview_limit": 300,
  "force_full": false
}
```

### 4.2 创建、上传、保存、删除

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/world_info/create` | 创建新的全局世界书 |
| `POST` | `/api/upload_world_info` | 上传世界书 JSON |
| `POST` | `/api/world_info/save` | 保存世界书 |
| `POST` | `/api/world_info/delete` | 删除全局或资源世界书 |

保存示例：

```json
{
  "save_mode": "overwrite",
  "file_path": "data/library/lorebooks/example.json",
  "content": {},
  "compact": false,
  "source_revision": "..."
}
```

`save_mode` 常见值：

- `overwrite`
- `new_global`
- `new_resource`

### 4.3 分类、文件夹、导出与 ST 同步

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/world_info/category/move` | 调整分类 |
| `POST` | `/api/world_info/category/reset` | 重置资源世界书分类覆盖 |
| `POST` | `/api/world_info/folders/create` | 创建全局目录 |
| `POST` | `/api/world_info/folders/rename` | 重命名全局目录 |
| `POST` | `/api/world_info/folders/delete` | 删除空目录 |
| `POST` | `/api/world_info/export` | 导出世界书 |
| `POST` | `/api/export_worldbook_single` | 导出内嵌世界书兼容接口 |
| `POST` | `/api/world_info/send_to_st` | 发送到 SillyTavern |
| `POST` | `/api/world_info/note/save` | 保存本地备注 |

### 4.4 世界书剪贴板与工具接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/wi/clipboard/list` | 获取剪贴板列表 |
| `POST` | `/api/wi/clipboard/add` | 添加条目到剪贴板 |
| `POST` | `/api/wi/clipboard/delete` | 删除剪贴板项 |
| `POST` | `/api/wi/clipboard/clear` | 清空剪贴板 |
| `POST` | `/api/wi/clipboard/reorder` | 调整剪贴板顺序 |
| `POST` | `/api/tools/migrate_lorebooks` | 修复资源目录世界书位置 |

---

## 5. 预设 API

来源：`core/api/v1/presets.py`

### 5.1 列表与详情

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/presets/list` | 获取预设列表 |
| `GET` | `/api/presets/detail/<path:preset_id>` | 获取预设详情 |

`/api/presets/list` 常用参数：

| 参数 | 说明 |
| --- | --- |
| `search` | 搜索关键词 |
| `filter_type` | `all`、`global`、`resource` |
| `category` | 分类 |

### 5.2 上传、保存、删除、导出

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/presets/upload` | 上传预设 JSON |
| `POST` | `/api/presets/save` | 保存、另存、重命名或删除预设 |
| `POST` | `/api/presets/delete` | 删除预设 |
| `POST` | `/api/presets/export` | 导出预设 |
| `POST` | `/api/presets/save-extensions` | 只更新预设扩展字段 |
| `POST` | `/api/presets/send_to_st` | 发送预设到 ST |

保存示例：

```json
{
  "save_mode": "overwrite",
  "preset_id": "preset_id",
  "content": {},
  "source_revision": "...",
  "preset_kind": "openai"
}
```

常见 `save_mode`：

- `overwrite`
- `save_as`
- `rename`
- `delete`

### 5.3 分类、文件夹与版本家族

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/presets/category/move` | 调整分类 |
| `POST` | `/api/presets/category/reset` | 重置资源预设分类覆盖 |
| `POST` | `/api/presets/folders/create` | 创建全局目录 |
| `POST` | `/api/presets/folders/rename` | 重命名全局目录 |
| `POST` | `/api/presets/folders/delete` | 删除全局目录 |
| `POST` | `/api/presets/version/set-default` | 设置默认版本 |
| `POST` | `/api/presets/version/merge` | 合并到版本家族 |
| `POST` | `/api/presets/version/import` | 导入新版本文件 |

---

## 6. 扩展脚本 API

来源：`core/api/v1/extensions.py` 与部分资源接口

当前实现将 Regex、Tavern Helper 脚本与 Quick Replies 统一收敛到扩展列表接口，而不是继续拆成三个完全独立的 REST 集合。

### 6.1 扩展列表与上传

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/extensions/list` | 获取扩展列表 |
| `POST` | `/api/extensions/upload` | 上传扩展文件 |
| `POST` | `/api/scripts/save` | 保存扩展 JSON 文件 |

`/api/extensions/list` 参数：

| 参数 | 说明 |
| --- | --- |
| `mode` | `regex`、`scripts`、`quick_replies` |
| `filter_type` | `all`、`global`、`resource` |
| `search` | 搜索关键词 |

---

## 7. 自动化 API

来源：`core/api/v1/automation.py`

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/automation/rulesets` | 获取规则集列表 |
| `GET` | `/api/automation/rulesets/<ruleset_id>` | 获取规则集详情 |
| `POST` | `/api/automation/rulesets` | 创建或保存规则集 |
| `DELETE` | `/api/automation/rulesets/<ruleset_id>` | 删除规则集 |
| `GET` | `/api/automation/rulesets/<ruleset_id>/export` | 导出规则集 |
| `POST` | `/api/automation/rulesets/import` | 导入规则集 |
| `GET` | `/api/automation/global_setting` | 获取全局默认规则集 |
| `POST` | `/api/automation/global_setting` | 设置全局默认规则集 |
| `POST` | `/api/automation/targets` | 解析并冻结规则集批量执行目标 |
| `POST` | `/api/automation/execute` | 手动执行规则集 |

执行示例：

```json
{
  "ruleset_id": "ruleset_id",
  "card_ids": ["card_id1", "card_id2"],
  "category": "可选分类",
  "recursive": true
}
```

自动化条件中的 `metadata` 是独立的原始元数据条件，可通过可选的 `metadata_path`（例如 `data.extensions.foo` 或 `entries[0].comment`）定位嵌套值。该条件会逐张读取并解析原文件，批量执行时可能明显变慢，建议缩小范围使用。

---

## 8. SillyTavern 同步 API

来源：`core/api/v1/st_sync.py`

说明：该 Blueprint 使用 `url_prefix='/api/st'`。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/st/test_connection` | 测试与 ST 的连接 |
| `GET` | `/api/st/detect_path` | 自动探测 ST 安装路径 |
| `POST` | `/api/st/validate_path` | 校验 ST 路径 |
| `GET` | `/api/st/list/<resource_type>` | 列出 ST 资源 |
| `GET` | `/api/st/get/<resource_type>/<resource_id>` | 获取 ST 单个资源详情 |
| `POST` | `/api/st/sync` | 从 ST 同步资源到本地 |
| `POST` | `/api/st/refresh` | 刷新 ST 客户端配置 |
| `GET` | `/api/st/summary` | 获取 ST 资源概览 |
| `GET` | `/api/st/regex` | 聚合 ST 侧正则脚本 |

`resource_type` 常见值：

- `characters`
- `chats`
- `worlds`
- `presets`
- `regex`
- `quick_replies`

同步示例：

```json
{
  "resource_type": "characters",
  "resource_ids": [],
  "use_api": false,
  "st_data_dir": "D:/SillyTavern"
}
```

---

## 9. 美化库 API

来源：`core/api/v1/beautify.py`

说明：该 Blueprint 使用 `url_prefix='/api/beautify'`。

### 9.1 列表、详情与设置

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/api/beautify/list` | 获取美化包列表 |
| `GET` | `/api/beautify/<package_id>` | 获取美化包详情 |
| `GET` | `/api/beautify/settings` | 获取全局设置 |
| `POST` | `/api/beautify/update-settings` | 保存全局设置 |

### 9.2 资源导入与包编辑

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/beautify/import-theme` | 导入主题 JSON |
| `POST` | `/api/beautify/import-wallpaper` | 导入包内壁纸 |
| `POST` | `/api/beautify/import-global-wallpaper` | 导入全局壁纸 |
| `POST` | `/api/beautify/import-global-avatar` | 导入全局头像 |
| `POST` | `/api/beautify/import-screenshot` | 导入截图 |
| `POST` | `/api/beautify/import-package-avatar` | 导入包内头像 |
| `POST` | `/api/beautify/update-package-identities` | 更新包级身份信息 |
| `POST` | `/api/beautify/update-variant` | 更新变体配置 |
| `POST` | `/api/beautify/send-theme-to-st` | 发送主题到 ST |
| `POST` | `/api/beautify/delete-package` | 删除美化包 |
| `GET` | `/api/beautify/preview-asset/<path:subpath>` | 访问预览资源 |

---

## 10. 资源服务与静态访问

来源：`core/api/v1/resources.py`

### 10.1 静态资源访问

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/cards_file/<path:filename>` | 获取角色卡原图或伴生图 |
| `GET` | `/api/thumbnail/<path:filename>` | 获取或按需生成缩略图 |
| `GET` | `/resources_file/<path:subpath>` | 获取资源目录文件 |
| `GET` | `/assets/backgrounds/<path:filename>` | 获取背景图 |
| `GET` | `/assets/notes/<path:filename>` | 获取笔记图片 |

### 10.2 角色资源目录管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/upload_card_resource` | 上传文件到角色资源目录 |
| `POST` | `/api/list_resource_files` | 列出资源目录内容 |
| `POST` | `/api/delete_resource_file` | 删除资源目录中的文件 |
| `POST` | `/api/create_resource_folder` | 为角色卡创建资源目录 |
| `POST` | `/api/set_resource_folder` | 绑定已有资源目录 |
| `POST` | `/api/open_resource_folder` | 打开资源目录 |
| `POST` | `/api/list_resource_skins` | 列出资源皮肤图 |
| `POST` | `/api/open_path` | 打开允许范围内路径 |
| `POST` | `/api/send_to_st` | 将角色卡发送到 ST |

上传到角色资源目录后，后端会按文件类型自动归档到子目录，例如世界书、Regex、Quick Replies、预设或脚本目录。

---

## 11. 认证说明

项目启用外网认证后：

- 默认免登录来源只有 `127.0.0.1` 与 `::1`
- 局域网或公网来源需要先完成登录会话，除非命中 `auth_trusted_ips`
- 只有当请求来自 `auth_trusted_proxies` 中的代理地址时，后端才会信任 `X-Forwarded-For` / `X-Real-IP`

配置细节见 [CONFIG.md](CONFIG.md)。
