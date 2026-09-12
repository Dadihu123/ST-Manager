# ST Manager API

本文档按当前 Flask 应用注册的路由整理业务 HTTP API。项目没有单独的 `/v1` URL 前缀；`core/api/v1/` 是代码目录名称，实际请求路径以本文档为准。

## 基本约定

- 默认基地址：`http://127.0.0.1:5000`。
- JSON 请求使用 `Content-Type: application/json`；上传接口使用 `multipart/form-data`。
- 成功响应通常包含 `success: true`；失败响应通常包含 `success: false` 和 `msg` 或 `error`。
- 列表接口的分页字段一般为 `page`、`page_size`、`total_count`；具体业务可能使用 `items`、`cards`、`chat` 或 `item` 作为数据字段。
- 路径型参数必须是项目允许目录下的相对路径，不能包含 `..`。服务器会对角色卡、资源目录、世界书和 SillyTavern 路径做边界检查。
- 导出接口返回文件流，成功时通常带 `Content-Disposition: attachment`，而不是 JSON。
- 开启外网认证后，页面请求会重定向到 `/auth/login`，API 请求返回 `401`；触发全局锁定时 API 返回 `503`。

### 最小请求示例

```bash
curl http://127.0.0.1:5000/api/status

curl "http://127.0.0.1:5000/api/list_cards?page=1&page_size=24&sort=date_desc"

curl -X POST http://127.0.0.1:5000/api/toggle_favorite \
  -H "Content-Type: application/json" \
  -d '{"id":"characters/example.png"}'
```

## 系统、设置与维护

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/status` | 获取启动/后台服务状态 | 无 |
| `GET` | `/api/index/status` | 获取卡片与世界书索引、构建任务状态 | 无 |
| `POST` | `/api/index/rebuild` | 请求重建索引 | JSON `scope`: `cards` 或 `worldinfo` |
| `POST` | `/api/scan_now` | 请求一次文件系统扫描 | 无 |
| `POST` | `/api/settings_path_safety` | 评估管理器目录和 ST 目录是否重叠 | JSON 配置对象，或 `{ "config": {...} }` |
| `POST` | `/api/save_settings` | 保存配置并刷新 ST 客户端 | JSON 配置；存在路径冲突时需要 `confirm_risky_paths: true` |
| `GET` | `/api/get_settings` | 读取归一化后的配置和共享壁纸信息 | 无 |
| `POST` | `/api/shared-wallpapers/import` | 导入共享壁纸 | multipart `file`；可选 `selection_target`: `manager`/`preview` |
| `POST` | `/api/shared-wallpapers/select` | 选择管理器或预览壁纸 | JSON `wallpaper_id`、`selection_target` |
| `POST` | `/api/upload_background` | 上传管理器背景图 | multipart 图片字段 `file` |
| `POST` | `/api/user-db-backup/export` | 导出用户 UI/聊天等数据库关联数据 | 无；返回备份信息 |
| `POST` | `/api/user-db-backup/import` | 导入用户数据库备份 | multipart 备份文件 |
| `POST` | `/api/system_action` | 执行维护动作 | JSON `action` 与动作参数 |
| `POST` | `/api/trash/open` | 打开回收站目录 | 无；桌面环境下调用系统打开动作 |
| `POST` | `/api/trash/empty` | 清空回收站 | 无；会永久删除回收站内容 |
| `POST` | `/api/create_snapshot` | 创建角色卡或预设快照 | JSON 目标类型、ID 和快照备注 |
| `POST` | `/api/smart_auto_snapshot` | 按配置创建自动快照 | JSON 目标信息 |
| `POST` | `/api/list_backups` | 列出某个资源的快照 | JSON 资源类型和 ID |
| `POST` | `/api/cleanup_init_backups` | 清理初始化备份 | JSON 清理范围 |
| `POST` | `/api/restore_backup` | 恢复快照 | JSON 备份路径/目标信息 |
| `POST` | `/api/read_file_content` | 读取允许范围内的文本文件 | JSON `file_path` |
| `POST` | `/api/open_path` | 在本机打开文件或目录 | JSON `path` |

### 文件夹和资源根

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `POST` | `/api/create_resource_folder` | 创建角色资源目录 | JSON 角色 ID/目录名 |
| `POST` | `/api/set_resource_folder` | 绑定角色资源目录 | JSON `card_id`、`folder_name` |
| `POST` | `/api/open_resource_folder` | 打开角色资源目录 | JSON `card_id` |
| `POST` | `/api/list_resource_skins` | 列出角色资源中的可用皮肤/图片 | JSON `card_id` |

## 角色卡、标签与文件

### 列表和元数据

`GET /api/list_cards` 支持分页、分类递归、标签包含/排除、收藏、搜索和日期/Token 范围筛选。常用 query 参数如下：

| 参数 | 说明 |
| --- | --- |
| `page`、`page_size` | 页码和每页数量 |
| `category`、`recursive` | 当前分类和是否包含子分类 |
| `search`、`search_type` | 搜索词；类型可为 `mix`、`name`、`filename`、`tags`、`creator` |
| `search_mode` | `fast` 或 `fulltext` |
| `search_scope` | `current`、`all_dirs`、`full` |
| `tags`、`excluded_tags` | 多个标签使用 `|||` 分隔 |
| `fav_filter`、`favorites_first` | 收藏过滤和置顶收藏 |
| `sort` | 如 `date_desc`，默认取 `default_sort` |
| `import_date_from`、`import_date_to` | 导入时间范围 |
| `modified_date_from`、`modified_date_to` | 文件修改时间范围 |
| `token_min`、`token_max` | Token 数范围 |

响应至少包含 `cards`、`total_count`、`page`、`page_size`、`global_tags`、`all_folders` 和分类统计信息。

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/list_cards` | 分页读取角色卡列表 | 见上方 query 参数 |
| `POST` | `/api/get_card_detail` | 获取角色卡详情、UI 数据和来源状态 | JSON `id`；可选 `preview_wi`、`force_full_wi`、预览限制 |
| `POST` | `/api/get_raw_metadata` | 读取原始卡片数据 | JSON `id` |
| `POST` | `/api/normalize_card_data` | 按写入规则清洗原始卡片数据，用于 Diff/预览 | JSON 原始卡片数据 |
| `POST` | `/api/find_card_page` | 计算卡片在当前筛选条件下的页码 | JSON `card_id`、`category`、`sort`、`page_size` |
| `POST` | `/api/random_card` | 在当前筛选条件中随机返回角色卡 | JSON 分类、标签、搜索条件 |
| `POST` | `/api/toggle_favorite` | 切换收藏状态 | JSON `id` |
| `POST` | `/api/update_card` | 保存卡片字段、UI 备注或聚合包封面 | JSON 角色卡 ID 与字段；`set_as_cover` 用于版本封面 |
| `POST` | `/api/set_skin_cover` | 将角色资源中的皮肤图片设为卡片封面 | JSON `card_id`、`skin_filename`、可选 `save_old` |
| `POST` | `/api/update_card_file` | 上传并替换角色卡文件 | multipart 卡片文件和目标参数 |
| `POST` | `/api/update_card_from_url` | 从 URL 更新现有角色卡 | JSON `card_id`、`url`、可选 `is_bundle_update`、`keep_ui_data` |
| `POST` | `/api/import_from_url` | 从 URL 导入新角色卡 | JSON `url`、`category` |
| `POST` | `/api/change_image` | 更换卡片图片 | multipart 图片和卡片 ID |
| `POST` | `/api/cards/export` | 导出角色卡 JSON | JSON `id`；返回下载文件 |
| `POST` | `/api/send_to_st` | 将角色卡发送到 SillyTavern | JSON `card_id` |
| `POST` | `/api/convert_to_bundle` | 把单卡转换为聚合包 | JSON `card_id`、`bundle_name` |
| `POST` | `/api/toggle_bundle_mode` | 检查/启用/禁用目录聚合模式 | JSON `folder_path`、`action` |
| `POST` | `/api/delete_cards` | 将卡片移入回收站 | JSON `card_ids`、可选 `delete_resources` |
| `POST` | `/api/move_card` | 移动一张或多张卡片 | JSON `card_ids`、`target_category` |
| `POST` | `/api/check_resource_folders` | 检查卡片资源目录 | JSON `card_ids` |

### 上传分阶段接口

对于多文件导入，前端先调用 `POST /api/upload/stage`，使用返回的批次 ID 生成临时预览，再调用 `POST /api/upload/commit` 完成写入。临时文件可以通过 `GET /api/temp_preview/<batch_id>/<filename>` 读取；临时目录会在服务启动时清理。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/upload/stage` | 暂存上传批次并解析预览 |
| `GET` | `/api/temp_preview/<batch_id>/<path:filename>` | 读取暂存预览文件 |
| `POST` | `/api/upload/commit` | 按用户确认结果提交批次 |
| `POST` | `/api/upload_note_image` | 上传详情备注中的图片 |

### 标签治理

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` / `POST` | `/api/tag_order` | 读取/保存标签排序开关与顺序 | POST JSON `order`、`enabled` |
| `GET` / `POST` | `/api/tag_taxonomy` | 读取/保存标签分类、颜色和分类顺序 | POST JSON taxonomy |
| `GET` / `POST` | `/api/tag_management_prefs` | 读取/保存标签管理偏好 | POST JSON prefs |
| `GET` / `POST` | `/api/isolated_categories` | 读取/保存隔离分类 | POST JSON `paths` 等字段 |
| `POST` | `/api/delete_tags` | 批量删除标签 | JSON `tags`、目标范围 |
| `POST` | `/api/batch_tags` | 批量增加/移除标签 | JSON `card_ids`、`add`、`remove`、可选 `trigger_merge` |
| `POST` | `/api/preview_merge_tags` | 预览自动标签合并结果 | JSON `id`、`tags` |

### 来源更新监控

这些接口负责来源帖子基线、批量检查和前端进度显示。`/api/cards/source_update/check` 与 `/api/check_card_source_update` 是同一能力的兼容路径；`runs` 和 `runs/start` 也保留了兼容入口。

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `POST` | `/api/cards/source_update/targets` | 解析分类或选择项对应的卡片目标 |
| `POST` | `/api/cards/source_update/check` | 检查单张卡片的来源是否有更新 |
| `POST` | `/api/check_card_source_update` | 上一接口的兼容路径 |
| `POST` | `/api/cards/source_update/check_batch` | 批量检查来源更新 |
| `POST` | `/api/cards/source_update/acknowledge` | 确认当前来源版本 |
| `GET` | `/api/cards/source_update/monitor/status` | 读取监控池和调度状态 |
| `GET` | `/api/cards/source_update/monitor/entries` | 列出监控卡片 |
| `POST` | `/api/cards/source_update/monitor/entries/add` | 添加监控卡片，JSON `card_ids` |
| `POST` | `/api/cards/source_update/monitor/entries/remove` | 移除监控卡片，JSON `card_ids` |
| `POST` | `/api/cards/source_update/monitor/entries/enabled` | 开关单条监控，JSON `card_id`、`enabled` |
| `POST` / `PUT` | `/api/cards/source_update/monitor/settings` | 保存监控间隔和运行设置 |
| `POST` | `/api/cards/source_update/monitor/runs` | 创建监控运行 |
| `POST` | `/api/cards/source_update/monitor/runs/start` | 创建并启动监控运行 |
| `GET` | `/api/cards/source_update/monitor/runs/<run_id>` | 读取运行状态 |
| `POST` | `/api/cards/source_update/monitor/runs/<run_id>/progress` | 上报运行进度 |
| `POST` | `/api/cards/source_update/monitor/runs/<run_id>/complete` | 标记运行完成 |
| `POST` | `/api/cards/source_update/monitor/runs/<run_id>/cancel` | 取消运行 |

### 文件夹

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `POST` | `/api/create_folder` | 创建角色卡分类目录 | JSON `parent_category`、`name` |
| `POST` | `/api/rename_folder` | 重命名分类目录 | JSON 旧路径和新名称 |
| `POST` | `/api/delete_folder` | 删除空分类目录 | JSON 分类路径 |
| `POST` | `/api/move_folder` | 移动分类目录 | JSON 源路径和目标分类 |

## 世界书

世界书列表将来源区分为 `global`（全局目录）、`resource`（角色卡资源目录）和 `embedded`（角色卡内嵌）。内嵌世界书跟随所属角色卡移动，不能像独立文件一样直接删除或发送。

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/world_info/list` | 分页列出世界书 | query `page`、`page_size`、`category`、`search`、`source_type`、`recursive`、排序参数 |
| `POST` | `/api/world_info/create` | 创建全局世界书 | JSON 名称和分类 |
| `POST` | `/api/upload_world_info` | 上传一个或多个世界书 | multipart `files`/`file`、可选分类 |
| `POST` | `/api/world_info/detail` | 读取世界书详情与预览 | JSON 世界书 `id` 或来源路径 |
| `POST` | `/api/world_info/detail_search` | 在详情条目中搜索 | JSON `data`、`query` |
| `POST` | `/api/world_info/save` | 保存独立世界书 | JSON `id`、数据、来源修订信息 |
| `POST` | `/api/world_info/note/save` | 保存内嵌世界书的本地备注 | JSON 来源和 `summary` |
| `POST` | `/api/world_info/entry_history/list` | 查看条目历史版本 | JSON 世界书来源和条目 UID |
| `POST` | `/api/world_info/export` | 导出独立或内嵌世界书 | JSON 来源信息；返回 JSON 下载 |
| `POST` | `/api/export_worldbook_single` | 从角色卡导出内嵌世界书 | JSON `card_id`；返回 JSON 下载 |
| `POST` | `/api/world_info/send_to_st` | 将独立世界书发送到 SillyTavern | JSON 世界书路径/名称 |
| `POST` | `/api/world_info/delete` | 将独立世界书移入回收站 | JSON 来源路径；不支持直接删除内嵌世界书 |
| `POST` | `/api/world_info/category/move` | 移动资源世界书或保存分类覆盖 | JSON 世界书 ID、目标分类 |
| `POST` | `/api/world_info/category/reset` | 清除资源世界书的分类覆盖 | JSON 世界书 ID |
| `POST` | `/api/world_info/folders/create` | 创建世界书分类目录 | JSON `parent_category`、`name` |
| `POST` | `/api/world_info/folders/rename` | 重命名世界书分类目录 | JSON 旧路径和新名称 |
| `POST` | `/api/world_info/folders/delete` | 删除空世界书分类目录 | JSON 分类路径 |
| `POST` | `/api/tools/migrate_lorebooks` | 将资源目录中的世界书迁移到约定位置 | 无或 JSON 迁移选项 |

### 世界书剪贴板

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` | `/api/wi/clipboard/list` | 列出剪贴板条目 |
| `POST` | `/api/wi/clipboard/add` | 添加或覆盖条目 |
| `POST` | `/api/wi/clipboard/delete` | 删除条目 |
| `POST` | `/api/wi/clipboard/clear` | 清空剪贴板 |
| `POST` | `/api/wi/clipboard/reorder` | 保存条目顺序 |

## 聊天记录

聊天记录以 SillyTavern JSONL 文件为主。读取详情时可以只请求范围，避免一次性加载大型会话。

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/chats/list` | 列出聊天记录和统计 | query `search`、分页/排序参数 |
| `POST` | `/api/chats/detail` | 读取完整聊天详情 | JSON `path` |
| `POST` | `/api/chats/range` | 按楼层范围读取消息 | JSON `path`、`start_floor`、`end_floor` |
| `POST` | `/api/chats/update_meta` | 更新聊天标题、备注等元数据 | JSON `path` 和元数据 |
| `POST` | `/api/chats/bind` | 绑定聊天与角色卡 | JSON `path`、卡片 ID/绑定操作 |
| `POST` | `/api/chats/import` | 导入 JSONL 聊天文件 | multipart `.jsonl` 文件 |
| `POST` | `/api/chats/save` | 写回 JSONL 聊天 | JSON `path`、`metadata`、`raw_messages` |
| `POST` | `/api/chats/delete` | 将聊天移入回收站 | JSON `path` |
| `POST` | `/api/chats/search` | 搜索消息内容 | JSON `query` 与范围/分页参数 |

## 预设

预设既可以来自管理器自己的 `presets_dir`，也可以来自角色资源目录或 SillyTavern 的 `OpenAI Settings` 目录。详情编辑器返回经过归一化的编辑模型，保存时再转换回文件格式。

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/presets/list` | 列出预设、来源、分类和版本数 | query `filter_type` 等 |
| `GET` | `/api/presets/detail/<path:preset_id>` | 读取预设详情和可编辑字段 | 路径参数必须是返回的预设 ID |
| `POST` | `/api/presets/upload` | 上传预设 JSON | multipart `file`、可选分类 |
| `POST` | `/api/presets/save` | 保存预设或另存为新文件 | JSON 预设编辑模型、保存模式和目标 ID |
| `POST` | `/api/presets/save-extensions` | 保存预设关联的正则/ST 扩展 | JSON 预设 ID 和扩展列表 |
| `POST` | `/api/presets/delete` | 删除预设或版本 | JSON 预设 ID/版本 ID |
| `POST` | `/api/presets/export` | 导出预设 JSON | JSON 预设 ID；返回文件流 |
| `POST` | `/api/presets/send_to_st` | 发送预设到 SillyTavern | JSON 预设 ID、版本信息 |
| `POST` | `/api/presets/category/move` | 移动资源预设或保存分类覆盖 | JSON 预设 ID、目标分类 |
| `POST` | `/api/presets/category/reset` | 清除资源预设分类覆盖 | JSON 预设 ID |
| `POST` | `/api/presets/folders/create` | 创建预设分类目录 | JSON `parent_category`、`name` |
| `POST` | `/api/presets/folders/rename` | 重命名预设分类目录 | JSON 旧路径和新名称 |
| `POST` | `/api/presets/folders/delete` | 删除空预设分类目录 | JSON 分类路径 |
| `POST` | `/api/presets/version/set-default` | 设置聚合预设的默认版本 | JSON 预设/版本 ID |
| `POST` | `/api/presets/version/merge` | 合并两个预设版本 | JSON 版本来源和合并选项 |
| `POST` | `/api/presets/version/import` | 导入一个预设版本 | multipart 或 JSON 版本数据 |

## 扩展脚本与资源

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/extensions/list` | 列出 Regex、Tavern Helper、Quick Replies | query/JSON 选择 `type`、来源范围 |
| `POST` | `/api/extensions/upload` | 上传扩展 JSON | multipart `file`、目标类型/来源 |
| `POST` | `/api/list_resource_files` | 列出角色资源目录中的分类文件 | JSON `folder_name` |
| `POST` | `/api/upload_card_resource` | 上传并自动识别角色资源 | multipart `card_id`、`file` |
| `POST` | `/api/delete_resource_file` | 将角色资源文件移入回收站 | JSON `card_id`、`filename` |
| `POST` | `/api/scripts/save` | 原子保存 Regex/ST Helper JSON | JSON `file_path`、`content` |
| `GET` | `/cards_file/<path:filename>` | 提供角色卡原图或伴生图片 | 路径相对于 `cards_dir` |
| `GET` | `/api/thumbnail/<path:filename>` | 生成/读取 WebP 缩略图缓存 | 路径相对于 `cards_dir` |
| `GET` | `/resources_file/<path:subpath>` | 提供角色资源文件 | 路径相对于 `resources_dir` |
| `GET` | `/assets/backgrounds/<path:filename>` | 提供管理器背景图 | 相对于 `data/assets/backgrounds` |
| `GET` | `/assets/notes/<path:filename>` | 提供备注图片 | 相对于 `data/assets/notes_images` |

## Beautify 视觉库

Beautify API 的根路径为 `/api/beautify`。文件上传使用 `multipart/form-data`，主题和变体数据由服务层负责归一化并写入 `beautify_dir`。

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/beautify/list` | 列出美化包和变体摘要 | 无 |
| `GET` | `/api/beautify/<package_id>` | 读取一个美化包详情 | 路径参数 `package_id` |
| `GET` | `/api/beautify/settings` | 读取全局美化设置 | 无 |
| `POST` | `/api/beautify/update-settings` | 保存全局美化设置 | JSON 设置对象 |
| `POST` | `/api/beautify/import-theme` | 导入主题 JSON，可自动创建美化包 | multipart `file`；可选 `package_id`、`platform` |
| `POST` | `/api/beautify/import-wallpaper` | 导入变体壁纸 | multipart `file`、`package_id`、`variant_id` |
| `POST` | `/api/beautify/import-global-wallpaper` | 导入全局壁纸 | multipart `file` |
| `POST` | `/api/beautify/import-global-avatar` | 导入全局头像 | multipart `file`、`target` |
| `POST` | `/api/beautify/import-screenshot` | 导入美化包截图 | multipart `file`、`package_id` |
| `POST` | `/api/beautify/update-package-identities` | 更新包内角色/用户身份信息 | JSON `package_id` 与身份对象 |
| `POST` | `/api/beautify/import-package-avatar` | 导入包级头像 | multipart `file`、`package_id`、`target` |
| `POST` | `/api/beautify/update-variant` | 更新变体平台和选中壁纸 | JSON `package_id`、`variant_id`、变体字段 |
| `POST` | `/api/beautify/send-theme-to-st` | 将主题/变体发送到 SillyTavern | JSON 包和变体 ID |
| `POST` | `/api/beautify/delete-package` | 删除美化包 | JSON `package_id` |
| `GET` | `/api/beautify/preview-asset/<path:subpath>` | 提供预览资产 | 路径必须位于美化库内 |

## 自动化规则

规则集由 `meta`、`rules` 和动作描述组成；动作可以在手动执行、导入、标签修改或来源链接更新时触发。当前引擎覆盖条件匹配、标签合并、文件名模板、角色名/世界书名与文件名互转、来源标签抓取和来源基线刷新等能力。

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `POST` | `/api/automation/targets` | 根据选中项/分类冻结执行目标 | JSON `card_ids`、`category`、`recursive` |
| `GET` | `/api/automation/rulesets` | 列出规则集 | 无 |
| `GET` | `/api/automation/rulesets/<ruleset_id>` | 读取规则集 | 路径参数 ID |
| `POST` | `/api/automation/rulesets` | 新建或保存规则集 | JSON `id`、`meta`、`rules` |
| `DELETE` | `/api/automation/rulesets/<ruleset_id>` | 删除规则集 | 路径参数 ID |
| `POST` | `/api/automation/execute` | 对冻结/分类目标执行规则 | JSON `card_ids`、`ruleset_id`、可选分类参数 |
| `GET` | `/api/automation/global_setting` | 读取全局启用规则集 | 无 |
| `POST` | `/api/automation/global_setting` | 设置或关闭全局规则集 | JSON `ruleset_id`，`null` 表示关闭 |
| `GET` | `/api/automation/rulesets/<ruleset_id>/export` | 导出规则集 JSON | 返回文件流 |
| `POST` | `/api/automation/rulesets/import` | 导入规则集 JSON | multipart `file` |

## SillyTavern 同步

同步接口根路径为 `/api/st`。服务可以读取本地 SillyTavern 用户目录，也可以按 `st_url` 使用其 HTTP API；`st_data_dir` 和 `st_user_handle` 可以通过 query 或 JSON 临时覆盖配置。

支持的 `resource_type`：`characters`、`chats`、`worlds`、`presets`、`regex`、`scripts`、`quick_replies`。

其中 `scripts` 专指 JS-Slash-Runner（Tavern Helper）的全局脚本资源。ST 原生把它们保存在用户 `settings.json` 的 `extension_settings.tavern_helper.script.scripts`；管理器同步时会为每个脚本或脚本文件夹生成一个独立 JSON 文件，并兼容旧版 `TavernHelper.script.scriptsRepository`。

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/st/test_connection` | 测试 ST HTTP 连接/版本 | 无 |
| `GET` | `/api/st/detect_path` | 自动探测 ST 安装路径 | 无 |
| `POST` | `/api/st/validate_path` | 校验 ST 路径并统计资源 | JSON `path`、可选 `st_user_handle` |
| `GET` | `/api/st/list/<resource_type>` | 列出 ST 资源 | query `st_data_dir`、`st_user_handle`、`use_api` |
| `GET` | `/api/st/get/<resource_type>/<resource_id>` | 读取单个 ST 资源 | 路径参数和可选 ST 选择 query |
| `POST` | `/api/st/sync` | 将资源同步到管理器目录 | JSON `resource_type`、可选 `resource_ids`、`st_data_dir`、`st_user_handle`、`use_api` |
| `POST` | `/api/st/refresh` | 按最新配置刷新 ST 客户端 | 无 |
| `GET` | `/api/st/summary` | 获取七类资源数量概览 | query 可覆盖 ST 路径/用户 |
| `GET` | `/api/st/regex` | 聚合全局和预设关联正则 | query `presets_path`、`settings_path`、ST 选择参数 |

同步前会执行路径重叠检查；如果管理器目录和 ST 核心目录混用，接口会返回风险评估并拒绝受影响的同步动作，除非用户明确确认。

## 论坛预览

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `POST` | `/api/forum/thread_preview` | 获取来源论坛/Discord 帖子的预览 | JSON `url` 或卡片来源信息；返回标题、作者、时间、正文摘要和标签等 |

## 认证页面

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| `GET` / `POST` | `/auth/login` | 登录页面和登录提交 |
| `GET` | `/auth/logout` | 清除会话并返回登录页 |

认证默认关闭。配置 `auth_username` 与 `auth_password`，或设置环境变量 `STM_AUTH_USER`、`STM_AUTH_PASS` 后启用；本机地址和配置的信任地址可以免登录。
