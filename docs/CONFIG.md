# 配置说明

ST-Manager 在仓库根目录使用 `config.json` 作为主配置文件。本文档按当前代码实现整理配置生成规则、默认值、认证说明与 Docker 注意事项。

---

## 1. 配置生成与生效规则

### 1.1 首次生成

- 本地直接运行 `python app.py` 时，如果根目录缺少 `config.json`，程序会自动生成默认配置
- Docker Compose 首次启动时，会先通过 `init-config` 服务在宿主机项目根目录生成 `./config.json`
- 自动生成只会在配置文件缺失时发生，不会覆盖已有文件

### 1.2 本地与 Docker 的默认监听差异

- 本地首次生成默认监听 `127.0.0.1:5000`
- Docker Compose 首次生成默认监听 `0.0.0.0:5000`

### 1.3 启动优先级

`host` / `port` 的优先级为：

1. 命令行参数 `--host` / `--port`
2. `config.json`
3. 内置默认值

说明：

- `python app.py --host ... --port ...` 只影响当前进程，不会写回 `config.json`
- `debug` 不来自配置文件，只由 `--debug` 或 `FLASK_DEBUG=1` 控制

### 1.4 配置损坏时的回退逻辑

如果 `config.json` 存在但 JSON 无法解析：

- 程序会记录警告日志
- 当前进程仅回退到内置默认配置继续运行
- 不会自动修复或覆盖原文件

Docker 额外注意：

- 如果宿主机上的 `config.json` 已损坏，`init-config` 不会覆盖它
- 主服务会仅在当前进程兜底回退到默认配置
- 这种情况下 Flask 可能重新监听 `127.0.0.1`，从而导致容器外无法访问

---

## 2. 路径与目录规则

- 相对路径都相对于项目根目录解析
- 目录型配置在启动时会自动创建对应目录
- 系统内部固定目录位于：

| 目录 | 说明 |
| --- | --- |
| `data/system/db` | SQLite 与 JSON 辅助数据 |
| `data/system/thumbnails` | 缩略图缓存 |
| `data/system/trash` | 回收站 |
| `data/temp` | 临时文件 |

---

## 3. 默认配置总览

完整默认配置会在运行时做归一化处理。以下表格按功能分组列出当前主要字段。

### 3.1 基础与界面

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `host` | `127.0.0.1` | Web 服务监听地址 |
| `port` | `5000` | Web 服务监听端口 |
| `dark_mode` | `true` | 暗色模式开关 |
| `theme_accent` | `blue` | 主题强调色 |
| `default_sort` | `date_desc` | 角色卡默认排序 |
| `show_header_sort` | `true` | 是否显示顶部临时排序控件 |
| `items_per_page` | `0` | 角色卡列表每页数量，`0` 表示自动 |
| `items_per_page_wi` | `0` | 世界书列表每页数量，`0` 表示自动 |
| `card_width` | `220` | 角色卡网格宽度 |
| `font_style` | `sans` | 字体风格 |
| `bg_url` | `/assets/backgrounds/default_background.jpeg` | 默认背景图 |
| `bg_opacity` | `0.45` | 背景遮罩透明度 |
| `bg_blur` | `2` | 背景模糊度 |

`default_sort` 支持：

- `date_desc`
- `date_asc`
- `import_desc`
- `import_asc`
- `name_asc`
- `name_desc`
- `token_desc`
- `token_asc`

### 3.2 数据目录

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `cards_dir` | `data/library/characters` | 角色卡目录 |
| `world_info_dir` | `data/library/lorebooks` | 世界书目录 |
| `chats_dir` | `data/library/chats` | 聊天目录 |
| `presets_dir` | `data/library/presets` | 预设目录 |
| `st_openai_preset_dir` | `""` | 额外 OpenAI 预设目录 |
| `regex_dir` | `data/library/extensions/regex` | Regex 目录 |
| `scripts_dir` | `data/library/extensions/tavern_helper` | Tavern Helper 脚本目录 |
| `quick_replies_dir` | `data/library/extensions/quick-replies` | Quick Replies 目录 |
| `beautify_dir` | `data/library/beautify` | 美化库目录 |
| `resources_dir` | `data/assets/card_assets` | 角色资源目录根 |

### 3.3 SillyTavern 连接与认证

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `st_url` | `http://127.0.0.1:8000` | ST Web 地址 |
| `st_data_dir` | `""` | ST 数据目录，留空自动探测 |
| `st_auth_type` | `basic` | ST 认证模式 |
| `st_username` | `""` | 兼容字段，运行时自动归一化 |
| `st_password` | `""` | 兼容字段，运行时自动归一化 |
| `st_basic_username` | `""` | Basic 认证用户名 |
| `st_basic_password` | `""` | Basic 认证密码 |
| `st_web_username` | `""` | Web 登录用户名 |
| `st_web_password` | `""` | Web 登录密码 |
| `st_proxy` | `""` | requests 代理地址 |

`st_auth_type` 当前支持：

- `basic`
- `web`
- `auth_web`

说明：

- `st_username` / `st_password` 仍保留用于兼容旧配置
- 程序会根据 `st_auth_type` 在兼容字段与新字段之间做归一化
- `st_proxy` 为空时，会显式禁用代理继承

### 3.4 自动保存、快照与世界书预览

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `auto_save_enabled` | `false` | 是否启用自动保存 |
| `auto_save_interval` | `3` | 自动保存间隔，单位分钟 |
| `snapshot_limit_manual` | `50` | 手动快照保留上限 |
| `snapshot_limit_auto` | `5` | 自动快照保留上限 |
| `wi_preview_limit` | `300` | 世界书详情最大预览条目数，`0` 为不限制 |
| `wi_preview_entry_max_chars` | `2000` | 单条预览最大字符数，`0` 为不截断 |
| `wi_entry_history_limit` | `7` | 世界书条目历史保留数 |

### 3.5 扫描、索引与性能相关开关

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `enable_auto_scan` | `true` | 是否启用 watchdog 文件监听 |
| `png_deterministic_sort` | `false` | 是否对 PNG 元数据做确定性排序 |
| `cards_list_use_index` | `false` | 角色卡列表是否优先走索引 |
| `fast_search_use_index` | `false` | 快速搜索是否优先走索引 |
| `worldinfo_list_use_index` | `false` | 世界书列表是否优先走索引 |
| `index_auto_bootstrap` | `true` | 启动时是否自动进行索引引导 / 恢复 |
| `allowed_abs_resource_roots` | `[]` | 允许资源接口访问的额外绝对路径白名单 |

说明：

- `enable_auto_scan=false` 仅关闭文件系统监听，手动扫描接口仍然可用
- `allowed_abs_resource_roots` 用于为资源文件接口额外放行安全目录

### 3.6 导入与自动化辅助项

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `auto_rename_on_import` | `true` | 导入时是否按角色名自动重命名文件 |
| `automation_slash_is_tag_separator` | `false` | 是否将 `/` 也视为自动化标签分隔符 |

规则：

- `false` 时，仅将 `|` 视为自动化标签分隔符
- `true` 时，`/` 也会参与拆分标签

### 3.7 Discord 抓取配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `discord_auth_type` | `token` | Discord 认证方式 |
| `discord_bot_token` | `""` | Bot Token |
| `discord_user_cookie` | `""` | 浏览器 Cookie 字符串 |

说明：

- `token` 对应 Bot Token 方案
- `cookie` 对应浏览器 Cookie 方案
- Cookie 方案为备用方案，优先建议使用 Bot Token

### 3.8 类脑搜索站预览

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `shimmerday_forum_cookie` | `""` | 类脑搜索站会话 Cookie |

说明：

- 用于角色卡网格「类脑搜索」按钮的帖子只读预览
- 与 Discord 标签抓取 Cookie（`discord_user_cookie`）相互独立
- 角色卡需配置可解析的 Discord `channels` 来源链接后才会显示按钮
- Cookie 获取：登录 [https://odysseia-forum-webpage.pages.dev/](https://odysseia-forum-webpage.pages.dev/)，在开发者工具 Network 面板复制请求 Cookie

---

## 4. 外网访问认证

项目内置登录保护、白名单、失败限流与硬锁定机制。

### 4.1 启用条件

满足以下任一方式即可启用认证：

- `config.json` 中同时设置 `auth_username` 和 `auth_password`
- 环境变量中同时设置 `STM_AUTH_USER` 和 `STM_AUTH_PASS`

优先级：

1. `STM_AUTH_USER` + `STM_AUTH_PASS`
2. `config.json` 中的 `auth_username` + `auth_password`

### 4.2 默认白名单行为

- 默认免登录来源只有 `127.0.0.1` 和 `::1`
- 局域网访问不会自动免登录
- 如需放行局域网 / 内网穿透来源，请显式配置 `auth_trusted_ips`

### 4.3 认证相关字段

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `auth_username` | `""` | 登录用户名 |
| `auth_password` | `""` | 登录密码 |
| `auth_trusted_ips` | `[]` | 免登录白名单 |
| `auth_domain_cache_seconds` | `60` | 白名单域名解析缓存时间 |
| `auth_trusted_proxies` | `[]` | 受信任代理列表 |
| `auth_max_attempts` | `5` | 失败阈值 |
| `auth_fail_window_seconds` | `600` | 失败统计窗口 |
| `auth_lockout_seconds` | `900` | 临时锁定时长 |
| `auth_hard_lock_threshold` | `50` | 硬锁定阈值 |

`auth_trusted_ips` 支持：

- 单个 IP：`192.168.1.100`
- CIDR：`192.168.1.0/24`
- IPv4 通配符：`192.168.*.*`
- 域名：`your-ddns.example.com`

### 4.4 代理与真实 IP

- 只有当请求本身来自 `auth_trusted_proxies` 中的代理地址时，后端才会信任 `X-Forwarded-For` / `X-Real-IP`
- 默认受信任代理额外包含 `127.0.0.1` 和 `::1`
- 建议将应用放在 Nginx / Caddy / Traefik 等反向代理之后，并确保代理会覆盖客户端自带转发头

### 4.5 限流与锁定

- 达到 `auth_max_attempts` 后，会对对应来源进行临时锁定
- 连续失败达到 `auth_hard_lock_threshold` 后，会进入硬锁定模式
- 硬锁定时 API 将返回 `503`，需要手动重启进程

### 4.6 认证相关环境变量

| 环境变量 | 说明 |
| --- | --- |
| `STM_AUTH_USER` | 登录用户名 |
| `STM_AUTH_PASS` | 登录密码 |
| `STM_SECRET_KEY` | 显式指定 Flask Session Secret |

如果未提供 `STM_SECRET_KEY`，程序会尝试在 `data/.secret_key` 中持久化生成一份随机密钥。

### 4.7 命令行工具

```bash
# 查看当前认证状态
python -m core.auth

# 设置账号密码
python -m core.auth --set-auth admin your_password

# 添加白名单
python -m core.auth --add-ip 192.168.*.*
python -m core.auth --add-ip your-ddns.example.com
```

---

## 5. 示例配置

```json
{
  "host": "127.0.0.1",
  "port": 5000,
  "cards_dir": "data/library/characters",
  "world_info_dir": "data/library/lorebooks",
  "chats_dir": "data/library/chats",
  "presets_dir": "data/library/presets",
  "beautify_dir": "data/library/beautify",
  "resources_dir": "data/assets/card_assets",
  "st_url": "http://127.0.0.1:8000",
  "st_data_dir": "",
  "st_auth_type": "basic",
  "st_basic_username": "",
  "st_basic_password": "",
  "dark_mode": true,
  "theme_accent": "blue",
  "enable_auto_scan": true,
  "cards_list_use_index": false,
  "worldinfo_list_use_index": false,
  "auto_save_enabled": false,
  "snapshot_limit_manual": 50,
  "auth_username": "",
  "auth_password": "",
  "discord_auth_type": "token",
  "discord_bot_token": ""
}
```

---

## 6. Docker 相关说明

当前 `docker-compose.yaml` 行为：

- `init-config` 服务会先在宿主机生成 `./config.json`
- 主服务将 `./data` 挂载到 `/app/data`
- 主服务将 `./config.json` 挂载到 `/app/config.json`
- `extra_hosts` 中已包含 `host.docker.internal:host-gateway`

因此容器内访问宿主机服务时，可优先考虑 `host.docker.internal`。

---

## 7. 推荐排查顺序

### 服务无法从外部访问

1. 检查 `config.json` 是否损坏
2. 检查最终监听地址是否为 `0.0.0.0`
3. 检查 Docker 是否正确挂载了宿主机 `config.json`
4. 检查端口占用与防火墙

### ST 无法连接

1. 检查 `st_url`
2. 检查 `st_auth_type` 与凭据字段是否匹配
3. 检查 `st_data_dir` 是否有效
4. 检查是否误用了系统代理或 `st_proxy`

### 公网访问异常

1. 检查 `auth_username` / `auth_password` 或 `STM_AUTH_USER` / `STM_AUTH_PASS`
2. 检查 `auth_trusted_ips` 是否配置错误
3. 检查 `auth_trusted_proxies` 是否允许当前反向代理
4. 检查是否触发了临时锁定或硬锁定
