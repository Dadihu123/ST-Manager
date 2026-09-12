# 配置参考

ST Manager 使用项目根目录的 `config.json`。文件不存在时，`app.py` 会按 `core/config.py` 中的 `DEFAULT_CONFIG` 自动创建；相对路径相对于项目根目录（打包后相对于可执行文件所在目录），绝对路径也可以使用。

`config.json` 已被仓库忽略。不要把密码、Token、Cookie、外网地址或个人资源路径提交到公开仓库。

## 启动与归一化

- `ensure_config_file()` 只在文件不存在时写入默认配置，不会覆盖已有文件。
- `load_config()` 每次读取时会把缺失键补回默认值，并归一化 SillyTavern 认证字段。
- `st_auth_type` 支持 `basic`、`web`、`auth_web`；旧字段 `st_username`/`st_password` 会根据当前类型迁移到对应字段。
- `ensure_runtime_dirs()` 会创建角色卡、世界书、聊天、预设、扩展、美化和资源目录。
- `data/system/` 下的数据库、缩略图、回收站和临时目录属于运行时基础设施，不需要手动创建。

## 资源目录

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `cards_dir` | `data/library/characters` | 角色卡根目录，支持 `.png` 和 `.json` |
| `world_info_dir` | `data/library/lorebooks` | 全局世界书目录 |
| `chats_dir` | `data/library/chats` | JSONL 聊天目录 |
| `presets_dir` | `data/library/presets` | 管理器自己的预设目录 |
| `st_openai_preset_dir` | `""` | 兼容字段；优先使用 ST 路径探测和 `presets_dir` |
| `regex_dir` | `data/library/extensions/regex` | 全局 Regex 扩展目录 |
| `scripts_dir` | `data/library/extensions/tavern_helper` | Tavern Helper/ST 脚本目录 |
| `quick_replies_dir` | `data/library/extensions/quick-replies` | Quick Replies 目录 |
| `beautify_dir` | `data/library/beautify` | Beautify 包和主题目录 |
| `resources_dir` | `data/assets/card_assets` | 角色卡资源根目录 |
| `allowed_abs_resource_roots` | `[]` | 允许资源列表接口访问的额外绝对路径白名单 |

目录可以配置为绝对路径，例如 `D:/SillyTavern/data/default-user/characters`。修改目录后建议先调用设置页的路径安全检查，再保存配置。

## 服务与 SillyTavern

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `host` | `127.0.0.1` | Flask 监听地址；Docker 初始化时会默认改为 `0.0.0.0` |
| `port` | `5000` | Flask 监听端口 |
| `st_url` | `http://127.0.0.1:8000` | SillyTavern HTTP 地址 |
| `st_data_dir` | `""` | ST 安装目录；为空时尝试自动探测 |
| `st_user_handle` | `default-user` | ST `data/<user>` 用户目录名 |
| `st_auth_type` | `basic` | ST 认证模式：`basic`、`web`、`auth_web` |
| `st_username` | `""` | 兼容字段；由当前 ST 认证模式归一化得到 |
| `st_password` | `""` | 兼容字段；由当前 ST 认证模式归一化得到 |
| `st_basic_username` | `""` | ST Basic 认证用户名 |
| `st_basic_password` | `""` | ST Basic 认证密码 |
| `st_web_username` | `""` | ST Web 登录用户名 |
| `st_web_password` | `""` | ST Web 登录密码 |
| `st_proxy` | `""` | ST HTTP 请求使用的代理地址 |

同步支持 `characters`、`chats`、`worlds`、`presets`、`regex` 和 `quick_replies`。可以使用本地目录同步，也可以根据 ST HTTP 连接能力选择 API 模式。

## 列表与界面

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `default_sort` | `date_desc` | 默认列表排序模式 |
| `show_header_sort` | `true` | 是否在顶部显示排序控件 |
| `theme_accent` | `blue` | 主题强调色名称 |
| `items_per_page` | `0` | 角色卡列表页大小；`0` 表示由界面/后端默认值决定 |
| `items_per_page_wi` | `0` | 世界书列表页大小；`0` 表示由界面/后端默认值决定 |
| `dark_mode` | `true` | 初始深色模式 |
| `font_style` | `sans` | 字体风格：`sans`、`serif`、`mono` |
| `card_width` | `220` | 角色卡网格宽度 |
| `card_effects_enabled` | `true` | 是否启用角色卡悬浮/闪卡效果 |
| `bg_url` | `/assets/backgrounds/default_background.jpeg` | 管理器背景图 URL |
| `bg_opacity` | `0.45` | 背景遮罩浓度 |
| `bg_blur` | `2` | 背景模糊程度 |

## 自动保存与性能

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `auto_save_enabled` | `false` | 是否启用自动快照 |
| `auto_save_interval` | `3` | 自动快照间隔，单位为分钟 |
| `snapshot_limit_manual` | `50` | 每个目标保留的手动快照上限 |
| `snapshot_limit_auto` | `5` | 每个目标保留的自动快照上限 |
| `enable_auto_scan` | `true` | 是否启用 watchdog 文件监听；关闭后仍可手动扫描 |
| `png_deterministic_sort` | `false` | 是否对 PNG 元数据做确定性排序；开启可能改变外部工具看到的字节顺序 |
| `cards_list_use_index` | `false` | 是否允许角色卡列表使用 SQLite 索引 |
| `fast_search_use_index` | `false` | 是否允许快速搜索使用索引；只有列表索引开启时才有意义 |
| `worldinfo_list_use_index` | `false` | 是否允许世界书列表使用索引 |
| `index_auto_bootstrap` | `true` | 启动时是否自动初始化/重建索引 |

索引不是资源的唯一来源。关闭索引或索引不可用时，列表会回退到缓存/文件扫描路径；启用索引可以改善大型资源库的查询响应。

## 世界书预览

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `wi_preview_limit` | `300` | 详情预览最大条目数；`0` 表示不限制 |
| `wi_preview_entry_max_chars` | `2000` | 单条世界书内容最大字符数；`0` 表示不截断 |
| `wi_entry_history_limit` | `7` | 单条世界书保留的历史版本数量 |

这些限制只影响详情预览和历史保留，不会改变磁盘上的原始世界书内容。

## 外网认证与路径信任

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `auth_username` | `""` | 管理器登录用户名；与密码同时非空时启用认证 |
| `auth_password` | `""` | 管理器登录密码 |
| `auth_trusted_ips` | `[]` | 免登录地址，可写单 IP、CIDR、通配符或域名 |
| `auth_domain_cache_seconds` | `60` | 域名白名单解析缓存时间 |
| `auth_trusted_proxies` | `[]` | 允许信任 `X-Forwarded-For`/`X-Real-IP` 的代理地址 |
| `auth_max_attempts` | `5` | 失败窗口内允许的最大登录失败次数 |
| `auth_fail_window_seconds` | `600` | 登录失败统计窗口，单位为秒 |
| `auth_lockout_seconds` | `900` | 超限后的单地址锁定时间，单位为秒 |
| `auth_hard_lock_threshold` | `50` | 全局连续失败达到该值后进入需要重启的锁定模式 |

环境变量优先级高于 `config.json`：

| 环境变量 | 作用 |
| --- | --- |
| `STM_AUTH_USER` | 覆盖管理器认证用户名 |
| `STM_AUTH_PASS` | 覆盖管理器认证密码 |
| `STM_SECRET_KEY` | 覆盖 Flask session secret；未设置时使用 `data/.secret_key` |
| `FLASK_DEBUG=1` | 开启 Flask debug/reloader；等价于 `python app.py --debug` |

首次开启外网访问时，应同时设置强密码、明确的可信代理列表，并确认管理器目录与 SillyTavern 目录没有不期望的重叠。

## 导入与外部服务

| 键 | 默认值 | 说明 |
| --- | --- | --- |
| `auto_rename_on_import` | `true` | 导入时是否根据角色名自动重命名文件；冲突时仍会追加序号 |
| `discord_auth_type` | `token` | Discord 标签读取方式：`token` 或 `cookie` |
| `discord_bot_token` | `""` | Discord Bot Token；需要访问目标论坛的权限 |
| `discord_user_cookie` | `""` | 浏览器复制的 Discord Cookie |
| `shimmerday_forum_cookie` | `""` | 类脑搜索站帖子预览使用的会话 Cookie |
| `sync_source_title_on_update` | `true` | 更新角色卡时是否同步来源贴标题 |
| `automation_slash_is_tag_separator` | `false` | 自动化标签分割时是否把 `/` 与 `|` 都视为分隔符 |

Discord Token、Cookie 和论坛 Cookie 都属于敏感凭据。建议只写入本机配置或通过部署密钥管理，不要放入截图、日志和版本库。

## 运行时目录

这些目录由代码自动创建，通常无需写入 `config.json`：

```text
data/
├─ system/
│  ├─ db/cards_metadata.db      # SQLite 元数据、索引和任务状态
│  ├─ thumbnails/                # 按需生成的 WebP 缩略图
│  ├─ trash/                     # 删除操作的可恢复回收站
│  └─ ...
└─ temp/                         # 上传暂存与启动清理目录
```

UI 关联数据主要保存在 `data/system/db/ui_data.json`，聊天关联数据保存在同一运行时数据库目录。备份和恢复接口会对这些用户数据提供导出/导入能力。
