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
| `GET` | `/api/index/status` | 获取卡片与世界书索引、构建任务状态（含后台重建进度） | 无 |
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

### 索引状态与后台重建

索引重建（首次引导、搜索内容格式升级）不在启动路径上同步执行，因此 `/api/index/status` 除了 `state`、`pending_jobs`，还会给出进度字段：

| 字段 | 说明 |
| --- | --- |
| `state` | `building` 表示正在建库或后台重建；`error` 表示重建失败（此时搜索仍在用旧索引）；其余为 `ready` / `empty` 等 |
| `upgrade_active` | `true` 表示启动期后台重建仍在进行 |
| `<scope>.phase` | 当前阶段：`backfill_embedded_worldinfo_metadata` → `build_entities` → `activate_generation` |
| `<scope>.progress_done` / `progress_total` | 进度分子分母，取持久化值与内存值的较大者，避免数字回退 |

`scope` 为 `running` 时即使 `pending_jobs` 为 0 也会报 `building`。重建期间索引作业线程与启动全量扫描都会让路，列表走磁盘回退路径或旧索引，完成后自动切到新索引。

### 文件夹和资源根

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `POST` | `/api/create_resource_folder` | 创建角色资源目录 | JSON 角色 ID/目录名；绑定丢失但目录仍在时自动接管并返回 `binding_restored: true` |
| `POST` | `/api/set_resource_folder` | 绑定角色资源目录 | JSON `card_id`、`folder_name`；写失败返回 500 与 `binding_failed: true` |
| `POST` | `/api/rename_resource_folder` | 重命名已绑定的角色资源目录 | JSON `card_id`、`new_name`（仅目录名，不含路径分隔符；保留名与同名冲突会被拒绝） |
| `POST` | `/api/open_resource_folder` | 打开角色资源目录 | JSON `card_id` |
| `POST` | `/api/list_resource_skins` | 列出角色资源中的可用皮肤/图片 | JSON `card_id` |

重命名会连带迁移磁盘目录、`ui_data` 绑定、世界书备注里的 `resource::` 前缀、资源条目分类覆盖、条目历史、内存缓存与索引归属。绝对路径绑定的目录同样支持。

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
| `tags`、`excluded_tags` | 多个标签使用 `\|\|\|` 分隔 |
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
| `POST` | `/api/draw_cards` | 抽卡：单抽（`count=1`）或十连（`count=10`） | JSON `count`、可选 `pity`，以及同 `list_cards` 的筛选条件 |
| `POST` | `/api/toggle_favorite` | 切换收藏状态 | JSON `id` |
| `POST` | `/api/update_card` | 保存卡片字段、UI 备注或聚合包封面 | JSON 角色卡 ID 与字段；`set_as_cover` 用于版本封面；`clear_ui_fields` 显式解绑 |
| `POST` | `/api/set_skin_cover` | 将角色资源中的皮肤图片设为卡片封面 | JSON `card_id`、`skin_filename`、可选 `save_old` |
| `POST` | `/api/update_card_file` | 上传并替换角色卡文件 | multipart 卡片文件、`image_policy`、可选 `keep_ui_data`、`creator_policy` |
| `POST` | `/api/update_card_from_url` | 从 URL 更新现有角色卡 | JSON `card_id`、`url`、可选 `is_bundle_update`、`keep_ui_data`、`creator_policy` |
| `POST` | `/api/import_from_url` | 从 URL 导入新角色卡 | JSON `url`、`category`；`overwrite` 时可带 `creator_policy` |
| `POST` | `/api/change_image` | 更换卡片图片 | multipart 图片和卡片 ID |
| `POST` | `/api/cards/export` | 导出角色卡 JSON | JSON `id`；返回下载文件 |
| `POST` | `/api/send_to_st` | 将角色卡发送到 SillyTavern | JSON `card_id` |
| `POST` | `/api/convert_to_bundle` | 把单卡转换为聚合包 | JSON `card_id`、`bundle_name` |
| `POST` | `/api/toggle_bundle_mode` | 检查/启用/禁用目录聚合模式 | JSON `folder_path`、`action` |
| `POST` | `/api/delete_cards` | 将卡片移入回收站 | JSON `card_ids`、可选 `delete_resources` |
| `POST` | `/api/move_card` | 移动一张或多张卡片 | JSON `card_ids`、`target_category` |
| `POST` | `/api/check_resource_folders` | 检查卡片资源目录 | JSON `card_ids` |

### 抽卡接口

`POST /api/draw_cards` 在「当前筛选条件」内抽取 1 张（单抽）或 10 张（十连）。筛选参数与 `/api/list_cards` 对齐，因此抽到的卡一定在当前视图范围内。

| 入参 | 说明 |
| --- | --- |
| `count` | 抽取张数，规整到 `1..10`；非法值回落为 1 |
| `pity` | 可选，默认 `true`。多连时保证至少 1 张 SR 及以上 |
| `category` / `tags` / `excluded_tags` / `search` / `search_type` / `search_scope` | 同列表接口 |
| `fav_filter` / `import_date_*` / `modified_date_*` / `token_min` / `token_max` / `recursive` | 同列表接口 |

稀有度由现有字段派生，不额外持久化：收藏 → `UR`；其余按 `token_count` 分档（`>100000` → `SSR`，`>20000` → `SR`，`>5000` → `R`，否则 `N`）。

响应：

```json
{
  "success": true,
  "cards": [{ "...card": "…", "rarity": "SSR", "duplicate": true }],
  "count": 10,
  "pool_size": 4,
  "pool_exhausted": true,
  "pity_applied": false
}
```

- `pool_exhausted` 为 `true` 表示候选不足 `count`，本次使用有放回抽取，重复项带 `duplicate: true`。
- `pity_applied` 为 `false` 可能是未请求保底，或卡池里没有 SR 及以上（此时静默跳过，不报错）。
- 候选为空时返回 `{"success": false, "code": "EMPTY_POOL", "pool_size": 0}`（HTTP 200），前端据此不开抽卡动画、直接提示。

`POST /api/random_card` 复用同一套筛选逻辑；历史上它遗漏了收藏筛选、排除标签、时间与 Token 范围，现已对齐。

### 覆盖更新与资源目录绑定

覆盖类接口（`/api/update_card_file`、`/api/update_card_from_url`、`/api/import_from_url` 的 `overwrite`、`/api/upload/commit` 的 `action=overwrite`）都接受 `creator_policy`：

| 取值 | 行为 |
| --- | --- |
| `preserve`（默认） | 覆盖前记住旧卡 `creator`，上传文件把它冲掉时还原。空字符串视为「没有意见」，不会被当成显式清空 |
| `overwrite` | 采用上传文件里的 `creator` 原值 |

资源目录绑定不再随任意保存动作被清空：

- `/api/update_card` 的 `resource_folder` 传空字符串默认视为「未修改」；只有显式传 `clear_ui_fields: ["resource_folder"]` 才解绑。
- 绑定写入失败时接口返回 HTTP 500 且带 `binding_failed: true`，此时**不会**更新内存缓存，也不会留下刚建好的空目录。
- `/api/create_resource_folder` 在绑定丢失但磁盘上仍有同名目录时优先接管，返回 `binding_restored: true`，不再建出「角色名_1」这样的新空目录。

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

搜索相关参数：

| 参数 | 取值 | 说明 |
| --- | --- | --- |
| `search_mode` | `fast`（默认）、`fulltext` | 快速子串匹配或全文索引检索 |
| `search_field` | `smart`（默认）、`name`、`filename`、`owner` | 搜索范围。后三项直接查索引列，绕开分词器，因此更快也不受中文分词限制 |

中文全文搜索在写入侧逐字切分、查询侧按短语匹配，两字及以上的中文关键词都可以命中。查询含标点或语法错误时返回空集并置 `search_degraded`，不再返回 HTTP 500。

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/world_info/list` | 分页列出世界书 | query `page`、`page_size`、`category`、`search`、`search_mode`、`search_field`、`source_type`、`recursive`、排序参数 |
| `POST` | `/api/world_info/create` | 创建全局世界书 | JSON 名称和分类 |
| `POST` | `/api/upload_world_info` | 上传一个或多个世界书 | multipart `files`/`file`、可选分类 |
| `POST` | `/api/world_info/detail` | 读取世界书详情与预览 | JSON 世界书 `id` 或来源路径 |
| `POST` | `/api/world_info/detail_search` | 在详情条目中搜索 | JSON `data`、`query` |
| `POST` | `/api/world_info/save` | 保存独立世界书 | JSON `id`、数据、来源修订信息 |
| `POST` | `/api/world_info/update/preview` | 获取选定书的更新来源并预览完整差异 | `file_path`、`source_type`；multipart `file`，或 JSON `url`／`source_text`，仅选其一 |
| `POST` | `/api/world_info/update/commit` | 备份后替换选定独立世界书 | JSON `file_path`、`source_type`、预览所得 `source_text`、`source_revision` |
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

### 更新选定世界书

在独立世界书详情底部选择“更新内容”，上传文件或填写直接返回 JSON 的 HTTP／HTTPS 地址。预览支持只读红绿条目差异和完整 JSON；确认“替换这本世界书”后才写入。此流程仅支持 `global`／`resource`，不支持 `embedded`，也不自动发送到 SillyTavern。列表的“导入世界书”仍用于新增。

`update/preview` 返回 `current_text`、`source_text` 和当前文件的 SHA-256 `source_revision`。提交时原样发送返回的 `source_text`，不要在 JavaScript 中解析后重新序列化，以免大整数丢失精度。文件名、位置、当前书名字段和 Manager 备注保留；其余内容整本替换，不自动合并个人修改。没有书名字段的目标不会从来源新增该字段。

`update/commit` 只接受 JSON 请求；预览只有实际上传 `file` 时接受 multipart，URL 和文本来源也须使用 JSON。格式不符时返回 HTTP `415`、`code: "invalid_request"`，不会获取 URL 或替换目标。

来源上限为 10 MiB，须为 UTF-8 JSON，包含 `entries` 对象或数组，每个条目包含文字 `content`。重复 JSON 字段和无效关键词类型会被拒绝，未知字段保留。URL 最多跟随五次跳转，使用 5 秒连接和 10 秒读取间隔超时；30 秒流块检查预算属于尽力限制，慢滴流不能保证严格的总耗时上限。

保留书名时只修改根层的书名字段，其他来源文本保持原样，包括大整数和高精度数字。处理后的文本也须满足大小限制；超限时直接拒绝预览，不返回无法提交的候选内容。

`update/commit` 在目标锁内复核强修订，完整备份后原子替换并重读校验，成功返回 `new_path`、普通保存使用的 `source_revision` 和 `backup_path`。预览后目标有改动时返回 HTTP `409`、`code: "source_changed"`，须重新比较并明确提交；备份失败时不替换。普通保存、删除、单书移动和独立书恢复共享目标锁，外部进程或整目录操作不受此锁控制。

更新前快照可在详情的“回滚”中恢复，保留上限清理时优先保留本次快照。长文件名的快照使用短的 `__UPDATE__` 文件名，仍置于原文件主体对应的备份目录，并在原回滚列表展示。备份目录沿用现有按文件基础名汇总的规则，不同目录中的同名书可能共用列表，恢复前应核对快照内容。更新入口拒绝文件级符号链接和越界目标；配置根目录本身可以是符号链接。

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

### 条件与动作

条件字段新增 `token_all_wi`：从卡片正文（名称、简介、开场白、对话示例）算起，叠加内嵌世界书的**全部**条目（含未启用）。评估时读取卡文件现算，不落库、不进列表筛选，读不到卡时为 0；旧 `token_count` 口径不变（只统计默认启用的世界书条目）。

动作新增 `replace_text`（查找 / 替换文本），**只在手动执行时开放**——它会直接改写卡文件且不可撤销：

| 字段 | 说明 |
| --- | --- |
| `find` / `replace` | 查找与替换内容；可选 `regex: true` 使用正则 |
| `flags` | 正则标记，支持 `m` / `s` / `i` |
| `case_sensitive` | 是否区分大小写 |
| `first_only` | 是否只替换首次命中 |
| `targets` | 目标字段，共 14 个可选字段；默认排除角色名与世界书触发词（`keys` 里写 `{{user}}` 不会被 ST 展开，条目会静默失效） |

替换支持字面量与正则、`\1` 与 `$1` 反向引用。无命中不写盘；配置错误时整卡跳过，绝不写半成品。执行位置在名称/文件名同步之前，失败即中止后续会改 ID 的动作。结果通过 `summary.text_replacements` 与批量 toast 汇总。

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
| `POST` | `/api/st/tt/check_connection` | 检查 TauriTavern 目标是否可用（本地数据目录或原生集成 API） | JSON 可覆盖 `tt_mode`、`tt_data_dir`、`tt_user_handle`、`tt_api_url` |

同步前会执行路径重叠检查；如果管理器目录和 ST 核心目录混用，接口会返回风险评估并拒绝受影响的同步动作，除非用户明确确认。

## 插件系统

插件接口位于 `/api/plugins`，没有单独的版本前缀。插件清单、校验规则与前端 API 参考见 [plugin-api.md](plugin-api.md)，迁移到 v3 契约的说明见 [plugin-migration-v2-to-v3.md](plugin-migration-v2-to-v3.md)。

### 统一响应与错误码

插件接口的成功响应一律为 `{"success": true, ...}`；失败响应为：

```json
{ "success": false, "msg": "…", "error": "<code>", "detail": "…", "field": "…", "hint": "…", "user_msg": "…" }
```

`detail` / `field` / `hint` / `user_msg` 只在有值时出现。常用错误码：

| `error` | HTTP | 含义 |
| --- | --- | --- |
| `plugin_not_found` | 404 | 插件不存在 |
| `plugin_manifest_invalid` | 400 | manifest 缺失或不符合规范 |
| `api_version_unsupported` | 409 | 插件 `api_version` 与主程序不兼容（严格拒绝加载） |
| `plugin_load_failed` | 500 | 插件代码加载或注册阶段失败 |
| `plugin_disabled` | 409 | 插件已被禁用 |
| `job_not_found` | 404 | 作业不存在（跨插件越权也走这个码） |
| `job_not_running` | 409 | 作业当前状态不允许该操作 |
| `job_already_running` | 409 | 同插件已有运行中的作业 |
| `sse_limit_reached` | 429 | SSE 连接数超限 |
| `catalog_offline` | 502 | 官方目录不可达或格式非法 |
| `plugin_install_failed` | 400 | 安装流程失败 |
| `install_unsafe_archive` | 400 | 归档未通过安全检查（zip-slip / 解压炸弹 / 链接逃逸） |
| `plugin_asset_invalid` | 404 | 插件静态资源路径非法 |
| `plugin_secret_error` | 500 | 密钥读写失败 |
| `plugin_cli_error` | 400 | 插件 CLI 子命令不存在或参数非法 |

路由层另有 `invalid_payload`(400)、`quota_exceeded`(413)、`ui_data_write_failed`(500)、`secret_read_failed`(503)、`secret_write_failed`(500)、`plugin_not_installed`(404)、`internal_error`(500)。成功一律返回 HTTP 200 + JSON，不使用 201/204。所有管理接口带 `Cache-Control: no-store`。

### 列表与宿主信息

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/plugins/list` | 已安装插件列表 | 无。每项含 `enabled`、`loaded`、`backend`、`frontend`、`capabilities`、`contributions`、`render_mode`、`tier`、`load_error`、`source_url` 等；响应另含 `plugins_dir`、`restart_hint` |
| `GET` | `/api/plugins/ui-icons` | 宿主图标名清单 | 无。整表承诺 Stable：只增不改，删除或改名要走 deprecation |
| `GET` | `/api/plugins/ui-tokens` | 宿主 CSS 令牌清单 | 无。插件样式引用了清单外且无回退值的令牌时，安装期会记录警告（不拒绝加载） |

### 配置与存储

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/plugins/<plugin_id>/config` | 读取插件配置 | 无。返回 schema 默认值与已存值的合并结果 |
| `POST` | `/api/plugins/<plugin_id>/config` | **合并**写入插件配置 | JSON `{"config": {...}}` 或裸对象；只接受 `config_schema.properties` 声明的键；空补丁返回 400 |
| `GET` | `/api/plugins/<plugin_id>/storage` | 插件键值存储 | 无。对应 `api.storage.*` 的持久化后端 |
| `POST` | `/api/plugins/<plugin_id>/storage` | **整体替换**插件存储 | 必须 `{"storage": {...}}`；超过 262144 字节返回 413 `quota_exceeded` |

`config` 按 schema 过滤键并合并写入，`storage` 是插件自由键值空间、整体替换。两者与作业数据、`install_source`、启停状态同存于 `ui_data._plugins_v1.<id>`，卸载时随命名空间清理（`keep_data: true` 可保留）。

### 密钥

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/plugins/<plugin_id>/secrets` | 密钥表单元数据 | 无。`secret: true` 的项只返回 `{set, hint, updated_at, source}`，永不返回明文 |
| `POST` | `/api/plugins/<plugin_id>/secrets` | 批量写入密钥 | JSON `{"secrets": {...}}` 或裸对象；值传 `null` 或 `""` 表示清除该项；密钥文件处于降级态时返回 503 `secret_read_failed` |
| `DELETE` | `/api/plugins/<plugin_id>/secrets/<key>` | 清除单个密钥项 | 路径参数 `key` 不含 `/` |

密钥落盘在 `data/system/secrets.json`，**明文 JSON、不加密**；防护靠原子写（`mkstemp` → `fsync` → `os.replace`）、写前轮转 3 代 `.bak`，以及 POSIX 下的 `0600` / `0700` 权限。读取遇到 IO 失败会进入降级态并拒绝一切写入，避免覆盖掉仅存的有效密钥。环境变量 `STM_PLUGIN_<ID>_<KEY>` 优先级最高（大写，非字母数字转下划线）。

### 生命周期

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `POST` | `/api/plugins/<plugin_id>/enable` | 启用插件 | 无 body。`restart_required` 取决于该插件是否有后端代码 |
| `POST` | `/api/plugins/<plugin_id>/disable` | 禁用插件（保留代码，重启后完全不加载） | 无 body。额外返回被取消的作业数 `cancelled_jobs` |
| `POST` | `/api/plugins/uninstall` | 卸载插件（目录进回收站） | JSON `{"id": "<plugin_id>", "keep_data": false}`。**`id` 在请求体里，不在路径里** |

### 官方目录与安装

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/plugins/catalog` | 官方插件目录（远端优先，失败回退包内清单） | `?refresh=1` 强制刷新。响应含 `source`（`cache`/`remote`/`bundled`）、`offline`、`updated_at`，每项补 `installed` 与 `installed_version` |
| `POST` | `/api/plugins/catalog/install` | 从官方目录安装 | JSON `{"id", "ref"?, "subdir"?}`；`id` 不在目录里返回 502 `catalog_offline` |
| `POST` | `/api/plugins/catalog/check_updates` | 检查已安装插件是否有新版本 | JSON `{"force": false}`；只报告，不自动安装 |
| `POST` | `/api/plugins/catalog/update` | 更新已安装插件到目录指向的版本 | JSON `{"id", "ref"?, "subdir"?}`；未安装返回 404 `plugin_not_installed`；返回 `previous_version` |
| `POST` | `/api/plugins/install_upload` | 手动上传 zip 安装（离线兜底） | `multipart/form-data`：`file` + 可选 `expected_id` |
| `POST` | `/api/plugins/install_github` | 从 GitHub 仓库安装 | JSON `{"repo", "ref"?, "subdir"?}`；`repo` 接受 `owner/repo` 或完整 GitHub URL |

安装链路的安全边界：

- 归档体积上限 50MB，解压后上限 200MB，压缩比上限 100:1，条目数上限 5000。
- 只从 `https://codeload.github.com/<repo>/zip/<ref>` 下载，不接受任意 URL（防 SSRF）；`ref` 与 `subdir` 都会校验 `..` 与前导/尾随斜杠。
- 逐条校验解压路径的绝对路径、盘符、`..` 与符号链接，不使用 `extractall()`。
- 官方目录条目带 `source.sha256` 时会校验下载归档的哈希；哈希为空则跳过校验，格式非法直接拒绝。
- 插件 id 必须匹配 `^[a-z][a-z0-9-]{1,63}$`，安装后目录名必须等于 `manifest.id`。
- 通过 `/api/plugins/install_github` 安装时，归档里的 `manifest.id` 必须等于仓库名，否则返回 400 `plugin_manifest_invalid`。

### 作业与 SSE

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/plugins/<plugin_id>/jobs` | 列出该插件作业 | `?limit`（1–200，默认 50）、`?offset`、`?status`（逗号分隔） |
| `POST` | `/api/plugins/<plugin_id>/jobs` | 创建作业 | JSON `{"job_type", "items", "payload"?}` |
| `GET` | `/api/plugins/<plugin_id>/jobs/<run_id>` | 作业详情 | 无 query；条目固定返回 200 条 |
| `GET` | `/api/plugins/<plugin_id>/jobs/<run_id>/events` | 作业 SSE 事件流 | 请求头 `Last-Event-ID` 断线续传；事件名 `snapshot`、`item`、`log`、`done` |
| `POST` | `/api/plugins/<plugin_id>/jobs/<run_id>/cancel` | 协作式取消 | 无 body |
| `POST` | `/api/plugins/<plugin_id>/jobs/<run_id>/pause` | 暂停（逐条审批流的落点） | 无 body；仅 `queued` / `running` 可暂停 |
| `POST` | `/api/plugins/<plugin_id>/jobs/<run_id>/resume` | 恢复被暂停的作业 | 无 body；仅 `paused` 可恢复 |
| `POST` | `/api/plugins/<plugin_id>/jobs/<run_id>/retry` | 重跑失败项 | JSON `{"only_failed": true}`；返回的 `run_id` 与原作业相同 |
| `POST` | `/api/plugins/<plugin_id>/jobs/<run_id>/items/<path:item_key>/review` | 逐条审批 | JSON `{"status", "result"?, "error"?}`；省略 `result` 时沿用条目原值；`item_key` 用 `<path:...>`，可以包含 `/` |

作业状态为 `queued` / `running` / `paused` / `completed` / `failed` / `cancelled` / `aborted`，条目状态为 `pending` / `running` / `done` / `failed` / `skipped` / `awaiting_review`。单次作业条目上限 20000；单条 `payload` 上限 64KB、`result` 上限 256KB，超限会被裁剪并标记 `_truncated: true`。

SSE 配额按连接计：每个作业最多 4 条、全局最多 32 条，超限返回 429 `sse_limit_reached`；心跳 15 秒。所有按 `run_id` 的端点都会用路径里的 `plugin_id` 校验归属，越权统一按「作业不存在」处理。

### 文档与资产

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/plugins/<plugin_id>/readme` | 读取插件 README 与 CHANGELOG | 无。各为 `{found, name, content, truncated, msg}`；超过 256KB 时 `found: true` 但 `content` 为空、`truncated: true` |
| `GET` | `/api/plugins/<plugin_id>/assets/<path:filename>` | 返回插件内静态资源 | 扩展名白名单：`.js .mjs .css .svg .png .webp .gif .avif .json .woff2 .map`；支持 `If-None-Match` → 304 与 `Range` |

资源响应头是 `Cache-Control: private, no-cache`（配合 ETag / `Last-Modified`，内容未变时仍是 304 无响应体），不是长 `max-age`：ES 模块的相对 import 不继承 `?v=` 查询串，长缓存会让重装插件后仍执行旧代码。`.md` 不在资源白名单内，README 必须走 `/readme`。

### 入口布局

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/plugins/entries/layout` | 读取入口布局偏好 | 无。返回 `layout`，单键为 `null` 表示显式清空 |
| `POST` | `/api/plugins/entries/layout` | 合并写入入口布局偏好 | JSON `{"layout": {...}}` 或裸对象；只认 `order`、`pinned`、`hidden`、`groups`、`shortcuts`，未知键静默丢弃；单键超过 64KB 也静默丢弃 |

### 核心事件流

| 方法 | 路径 | 作用 | 请求要点 |
| --- | --- | --- | --- |
| `GET` | `/api/plugins/events` | 核心事件 SSE 流 | `?events=card.updated,scan.completed` 可选过滤；未知事件名返回 400；连接上限 32 条，超限返回 429 |

只广播核心事件：`app.ready`、`card.created`、`card.updated`、`card.deleted`、`card.moved`、`tag.applied`、`tag.deleted`、`worldbook.saved`、`worldbook.entry_changed`、`scan.completed`、`index.job_done`。插件自定义事件（带 `<plugin_id>:` 前缀）不进这条流。帧事件名为 `core`，首帧 `event: ready`，负载为 `{event, payload, ts}`，心跳 15 秒。

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
