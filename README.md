# ST-Manager

<div align="center">

**SillyTavern 资源可视化管理工具**

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/Flask-2.0%2B-green)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

功能强大 • 界面美观 • 操作便捷

</div>

## 🧭 导航

- [简介](#nav-intro)
- [快速开始](#nav-quickstart)
- [Docker 部署](#nav-docker)
- [项目结构](#nav-structure)
- [配置说明](#nav-config)
- [公网/外网访问身份验证](#nav-auth)
- [功能详解](#nav-features)
  - [角色卡管理](#nav-feature-cards)
  - [世界书管理](#nav-feature-wi)
  - [预设管理](#nav-feature-presets)
  - [正则脚本管理](#nav-feature-regex)
  - [ST脚本管理](#nav-feature-scripts)
  - [快速回复管理](#nav-feature-quickreplies)
  - [自动化规则引擎](#nav-feature-automation)

<a id="nav-intro"></a>

## 📖 简介

ST-Manager 是一款专为 SillyTavern AI 聊天程序设计的资源可视化管理工具。它提供了一个现代化的 Web 界面，帮助用户高效管理角色卡、世界书、扩展脚本等各种资源，支持批量操作、自动化规则引擎、智能缓存等功能。

### ✨ 核心特性

- 🎴 **角色卡管理** - 支持 PNG/JSON 格式角色卡的浏览、编辑、导入导出
- 📚 **世界书管理** - 统一管理全局世界书、资源目录世界书和内嵌世界书
- 📝 **预设管理** - 完整的生成参数预设管理，支持拖拽上传、三栏详情阅读器、Prompts 筛选
- 🧩 **正则脚本管理** - 管理 SillyTavern 正则替换脚本，支持编辑和批量操作
- 📜 **ST脚本管理** - 管理 Tavern Helper 脚本库，支持脚本解析和分类展示
- ⚡ **快速回复管理** - 快速回复模板管理，支持分类、搜索和批量操作
- 🤖 **自动化引擎** - 基于规则的自动化任务执行，支持复杂的条件判断
- 🔄 **实时同步** - 文件系统自动监听，实时同步变更到数据库
- 🎨 **可视化界面** - 现代化响应式 UI，支持暗色/亮色主题
- 📦 **版本管理** - 支持角色卡 Bundle 多版本管理
- 🏷️ **标签系统** - 强大的标签过滤和批量标签管理
- 🔍 **智能搜索** - 支持名称、文件名、标签、创作者等多维度搜索
- 🔗 **酒馆资源同步** - 从本地 SillyTavern 读取并同步角色卡、世界书、预设、正则、ST脚本、快速回复

---

<a id="nav-quickstart"></a>

## 🚀 快速开始

### 环境要求

- Python 3.10 或更高版本
- pip 包管理器

### 安装步骤

1. **克隆仓库**

```bash
git clone https://github.com/Dadihu123/ST-Manager.git
cd st-manager
```

2. **安装依赖**

```bash
pip install -r requirements.txt
```

3. **运行程序**

```bash
python app.py
```

4. **访问界面**

程序启动后会自动打开浏览器访问 `http://127.0.0.1:5000`

<a id="nav-docker"></a>

### Docker 部署（推荐）

1. **使用 Docker Compose**

```bash
docker-compose up -d
```

2. **访问服务**

服务将在 `http://localhost:5000` 上运行

---

<a id="nav-structure"></a>

## 📁 项目结构

```
ST-Manager/
├── app.py                      # 主入口文件
├── config.json                 # 配置文件（自动生成）
├── requirements.txt            # Python 依赖
├── Dockerfile                  # Docker 镜像构建文件
├── docker-compose.yaml         # Docker Compose 配置
├── AGENTS.md                   # AI 助手指南
│
├── core/                       # 核心业务逻辑
│   ├── __init__.py            # 模块初始化
│   ├── auth.py                # 外网访问认证（账号密码 + IP 白名单）
│   ├── config.py              # 配置管理
│   ├── consts.py              # 常量定义
│   ├── context.py             # 全局上下文（Singleton）
│   ├── event_bus.py           # 事件总线
│   │
│   ├── api/                   # API 路由层
│   │   ├── views.py          # 页面视图
│   │   └── v1/               # API v1
│   │       ├── cards.py      # 角色卡 API
│   │       ├── world_info.py # 世界书 API
│   │       ├── system.py     # 系统 API
│   │       ├── resources.py  # 资源 API
│   │       ├── automation.py # 自动化 API
│   │       └── extensions.py # 扩展 API
│   │       └── presets.py    # 预设 API
│   │
│   ├── services/              # 业务服务层
│   │   ├── scan_service.py   # 文件扫描服务
│   │   ├── cache_service.py  # 缓存管理服务
│   │   ├── card_service.py   # 卡片业务服务
│   │   └── automation_service.py # 自动化服务
│   │
│   ├── automation/            # 自动化引擎
│   │   ├── engine.py         # 规则引擎核心
│   │   ├── manager.py        # 规则集管理
│   │   ├── executor.py       # 规则执行器
│   │   └── constants.py      # 常量定义
│   │
│   ├── data/                  # 数据层
│   │   ├── db_session.py     # 数据库会话
│   │   ├── cache.py          # 全局缓存
│   │   └── ui_store.py       # UI 数据存储
│   │
│   └── utils/                 # 工具函数
│       ├── data.py           # 数据处理工具
│       ├── filesystem.py     # 文件系统工具
│       ├── image.py          # 图片处理工具
│       ├── text.py           # 文本处理工具
│       ├── hash.py           # 哈希计算工具
│       └── net.py            # 网络工具
│
├── templates/                 # HTML 模板
│   ├── layout.html           # 主布局
│   ├── index.html            # 首页
│   ├── components/            # 组件模板
│   │   ├── header.html
│   │   ├── sidebar.html
│   │   ├── grid_cards.html
│   │   ├── grid_wi.html
│   │   └── grid_extensions.html
│   │   └── grid_presets.html
│   └── modals/               # 模态框模板
│       ├── detail_card.html
│       ├── detail_wi_fullscreen.html
│       ├── detail_wi_popup.html
│       ├── settings.html
│       ├── advanced_editor.html
│       ├── automation.html
│       └── ...
│
├── static/                    # 静态资源
│   ├── css/                  # 样式文件
│   │   └── modules/
│   ├── js/                   # JavaScript 文件
│   │   └── utils/
│   │   └── components/presetGrid.js
│   └── lib/                  # 第三方库
│       ├── alpine.js
│       ├── tailwindcss.js
│       ├── marked.min.js
│       └── diff.min.js
│
└── data/                      # 数据目录（运行时生成）
    ├── system/               # 系统数据
    │   ├── db/              # 数据库
    │   ├── thumbnails/      # 缩略图
    │   ├── trash/           # 回收站
    │   └── automation/      # 自动化规则
    ├── library/              # 资源库
    │   ├── characters/      # 角色卡目录
    │   ├── lorebooks/       # 世界书目录
    │   └── extensions/      # 扩展脚本
    │   └── presets/         # 预设目录
    └── temp/                # 临时文件
```

---

<a id="nav-config"></a>

## ⚙️ 配置说明

程序首次运行时会自动生成 `config.json` 配置文件。以下是主要配置项：

### 基础配置

```json
{
  "host": "127.0.0.1",
  "port": 5000,
  "dark_mode": true,
  "theme_accent": "blue"
}
```

### 目录配置

```json
{
  "cards_dir": "data/library/characters",
  "world_info_dir": "data/library/lorebooks",
  "regex_dir": "data/library/extensions/regex",
  "scripts_dir": "data/library/extensions/tavern_helper",
  "quick_replies_dir": "data/library/extensions/quick-replies",
  "presets_dir": "data/library/presets",
  "resources_dir": "data/assets/card_assets"
}
```

### SillyTavern 本地路径配置

```json
{
  "st_url": "http://127.0.0.1:8000",
  "st_data_dir": "",
  "st_auth_type": "basic",
  "st_username": "",
  "st_password": "",
  "st_proxy": ""
}
```

`st_data_dir` 留空时会自动探测常见安装路径（Windows: D:\SillyTavern / E:\SillyTavern 等）。
```

### SillyTavern 集成

```json
{
  "st_url": "http://127.0.0.1:8000",
  "st_auth_type": "basic",
  "st_username": "",
  "st_password": "",
  "st_proxy": ""
}
```

### 显示设置

```json
{
  "default_sort": "date_desc",
  "items_per_page": 0,
  "items_per_page_wi": 0,
  "card_width": 220,
  "font_style": "sans",
  "bg_url": "/assets/backgrounds/default_background.jpeg",
  "bg_opacity": 0.45,
  "bg_blur": 2
}
```

### 自动保存设置

```json
{
  "auto_save_enabled": false,
  "auto_save_interval": 3,
  "snapshot_limit_manual": 50,
  "snapshot_limit_auto": 5
}
```

### 系统设置

```json
{
  "enable_auto_scan": true,
  "png_deterministic_sort": false,
  "allowed_abs_resource_roots": [],
  "wi_preview_limit": 300,
  "wi_preview_entry_max_chars": 2000
}
```

#### 说明
- `png_deterministic_sort`：是否对 PNG 元数据进行确定性排序（默认关闭，避免改变外部工具的字节级行为）
- `allowed_abs_resource_roots`：允许访问的绝对资源目录白名单（用于资源文件列表接口）
- `wi_preview_limit`：世界书详情预览最大条目数（0 表示不限制）
- `wi_preview_entry_max_chars`：世界书单条内容预览最大字符数（0 表示不截断）

---

<a id="nav-auth"></a>

## 🔐 公网/外网访问身份验证（账号密码）

强烈建议：**只要通过内网穿透/公网暴露，就开启认证**。本项目提供“账号密码 + IP 白名单”的保护方案：

- **默认仅本机免登录**：`127.0.0.1`、`::1`
- 其他来源（包括局域网）默认都需要登录
- 如需让某些 IP 免登录，可加入 **IP 白名单**

### 配置项（config.json）

```json
{
  "auth_username": "admin",
  "auth_password": "your_password",
  "auth_trusted_ips": [
    "192.168.1.100",
    "192.168.1.0/24",
    "192.168.*.*"
  ],
  "auth_trusted_proxies": [],
  "auth_max_attempts": 5,
  "auth_fail_window_seconds": 600,
  "auth_lockout_seconds": 900,
  "auth_hard_lock_threshold": 50
}
```

说明：
- 仅当 `auth_username` 和 `auth_password` **都不为空**时才启用认证。
- `auth_trusted_ips` 支持三种格式：单个 IP、CIDR 网段、通配符（如 `192.168.*.*`）。
- `auth_trusted_proxies`：仅当请求来自这些代理 IP 时，才信任 `X-Forwarded-For / X-Real-IP`。
- `auth_max_attempts` / `auth_fail_window_seconds` / `auth_lockout_seconds`：登录失败限流与锁定。
- `auth_hard_lock_threshold`：连续失败达到阈值后进入锁定模式（需要后台手动重启）。

### 登录失败限流与锁定模式

- **限流锁定**：默认 10 分钟内失败 ≥ 5 次，锁定 15 分钟。
- **硬锁模式**：连续失败达到阈值（默认 50 次）后，系统进入锁定模式，所有 API 返回 503，需要后台重启。

### 环境变量（适合 Docker/systemd）

认证凭据优先级为：**环境变量 > config.json**。

- `STM_AUTH_USER`：用户名
- `STM_AUTH_PASS`：密码

示例：

```bash
STM_AUTH_USER=admin STM_AUTH_PASS=your_password python app.py
```

### 命令行工具（适合纯公网 Linux 服务器首次配置）

无需先打开 Web 页面，可直接在服务器上执行：

```bash
# 查看当前认证状态
python -m core.auth

# 设置账号密码
python -m core.auth --set-auth admin your_password

# 添加白名单（可选）
python -m core.auth --add-ip 192.168.*.*
```

### 反向代理/内网穿透注意事项

本项目会读取 `X-Forwarded-For` / `X-Real-IP` 来识别真实客户端 IP。

- 如果你**直接把 Flask 端口暴露到公网**，请确保代理/网关会**覆盖或移除**客户端自带的这些 Header，避免被伪造。
- 更推荐：在 Nginx/Caddy/Traefik 后面运行，并只允许代理访问后端端口。
- 仅当请求来自 `auth_trusted_proxies` 中的代理地址时，才会信任 `X-Forwarded-For / X-Real-IP`。


---

<a id="nav-features"></a>

## 🎯 功能详解

<a id="nav-feature-cards"></a>

### 角色卡管理

#### 支持的格式
- **PNG 卡片** - 包含嵌入式元数据的 PNG 图片
- **JSON 卡片** - 独立的 JSON 格式角色文件
- **伴生图片** - 支持 PNG/JSON 配套的伴生图片

#### 核心功能

| 功能 | 描述 |
|------|------|
| **浏览查看** | 网格/列表视图，支持缩略图预览 |
| **编辑修改** | 支持编辑角色名称、描述、人格、场景等所有字段 |
| **导入导出** | 支持从 URL 导入、文件上传、导出 |
| **批量操作** | 批量移动、删除、标签管理 |
| **收藏标记** | 快速收藏常用角色 |
| **搜索过滤** | 多维度搜索和标签过滤 |
| **Bundle 管理** | 支持多版本角色聚合显示 |

#### Token 计算

自动计算角色卡的总 Token 数量（包括描述、人格、消息示例、世界书等），帮助用户了解资源消耗。

---

<a id="nav-feature-wi"></a>

### 世界书管理

#### 世界书类型

| 类型 | 说明 |
|------|------|
| **全局世界书** | 存储在 `lorebooks/` 目录，全局共享 |
| **资源世界书** | 存储在角色资源目录的 `lorebooks/` 子目录 |
| **内嵌世界书** | 直接嵌入在角色卡文件中的世界书 |

#### 核心功能

- 📑 统一浏览所有类型的世界书
- ✏️ 在线编辑世界书内容
- 📋 世界书剪切板（暂存、排序）
- 📤 导出世界书为独立 JSON 文件
- 🔗 与角色卡关联显示
- 🔄 一键整理资源目录结构
- ⚡ 大型世界书预览优化：详情弹窗默认预览前 300 条，避免卡死（可手动加载全部）
- 🧹 全局列表去重：自动剔除与内嵌世界书内容重复的条目，避免混杂展示

---

<a id="nav-feature-presets"></a>

### 预设管理

ST-Manager 提供完整的 SillyTavern 生成参数预设管理功能，支持全局预设和资源目录预设的统一管理。

#### 预设类型

| 类型 | 说明 | 存储位置 |
|------|------|----------|
| **全局预设** | 适用于所有聊天的通用预设 | `data/library/presets/` |
| **资源目录预设** | 与特定角色卡绑定的预设 | 角色资源目录内 |

#### 核心功能

| 功能 | 描述 |
|------|------|
| **网格浏览** | 卡片式网格布局，显示预设名称、来源、修改时间 |
| **拖拽上传** | 支持拖拽 JSON 文件直接上传，自动识别预设格式 |
| **详情阅读器** | 三栏式布局展示预设完整内容：采样器、参数、Prompts、扩展 |
| **Prompts 管理** | 支持查看、筛选（启用/禁用/全部）角色卡的 Prompt 注入 |
| **扩展集成** | 显示预设绑定的正则脚本和 Tavern Helper 脚本 |
| **批量操作** | 支持删除、移动预设文件 |
| **来源角标** | 区分 GLOBAL（全局）和 RES（资源目录）预设 |

#### 支持的预设字段

- **采样器参数**：temperature、top_p、top_k、repetition_penalty 等
- **Prompts**：角色描述、世界信息、对话示例等注入内容
- **扩展**：regex_scripts（正则脚本）、tavern_helper（ST脚本）

#### 操作说明

1. **上传预设**：拖拽 JSON 文件到预设网格区域，自动保存到全局预设目录
2. **查看详情**：点击预设卡片，打开三栏式详情阅读器
3. **筛选 Prompts**：在详情界面使用"全部/启用/禁用"筛选器查看不同状态的 Prompts
4. **编辑扩展**：点击"高级扩展"按钮，编辑预设绑定的正则和 ST 脚本
5. **删除预设**：在网格界面悬停显示删除按钮，或在详情界面点击删除

---

<a id="nav-feature-regex"></a>

### 正则脚本管理

统一管理 SillyTavern 的正则替换脚本（Regex Scripts），支持全局正则和资源目录正则。

#### 正则脚本来源

| 来源 | 说明 |
|------|------|
| **全局正则** | 从 SillyTavern settings.json 读取，存储为 `global__*.json` |
| **预设绑定** | 嵌入在角色卡或预设文件中的正则脚本 |
| **独立文件** | 存储在 `data/library/extensions/regex/` 的 JSON 文件 |

#### 核心功能

| 功能 | 描述 |
|------|------|
| **可视化展示** | 在角色卡/预设详情页展示绑定的正则脚本列表 |
| **编辑支持** | 通过高级编辑器修改正则脚本的查找/替换模式 |
| **格式兼容** | 支持 SillyTavern 原生正则格式和第三方格式 |

#### 正则脚本字段

```json
{
  "id": "脚本ID",
  "name": "脚本名称",
  "find": "查找正则",
  "replace": "替换内容",
  "enabled": true,
  "markdown_only": false,
  "prompt_only": false,
  "run_on_edit": false
}
```

---

<a id="nav-feature-scripts"></a>

### ST脚本管理

管理 SillyTavern 的 Tavern Helper 脚本（原名 ST-Scripts），支持脚本库的统一管理。

#### 脚本类型

| 类型 | 说明 |
|------|------|
| **脚本库** | 通过 `//<prefix>:` 语法定义的脚本集合 |
| **变量脚本** | 使用 `//<base>` 定义的基础脚本 |
| **触发脚本** | 使用 `//<button>` 定义的按钮触发脚本 |

#### 核心功能

| 功能 | 描述 |
|------|------|
| **脚本解析** | 自动解析脚本文件的 prefix、base、button 定义 |
| **列表展示** | 在角色卡/预设详情页展示绑定的脚本列表 |
| **编辑支持** | 通过高级编辑器查看和修改脚本内容 |
| **存储管理** | 支持存储在 `data/library/extensions/tavern_helper/` |

#### 脚本格式示例

```javascript
//<prefix>:我的脚本库
//<base>:基础响应模板
//<button>:打招呼|sayHello
function sayHello() {
  return "你好！";
}
```

---

<a id="nav-feature-quickreplies"></a>

### 快速回复管理

管理 SillyTavern 的快速回复（Quick Replies），支持模板管理和分类浏览。

#### 快速回复类型

| 类型 | 说明 |
|------|------|
| **全局快速回复** | 适用于所有聊天的通用模板 |
| **角色专用** | 与特定角色卡绑定的快速回复 |
| **预设绑定** | 嵌入在预设文件中的快速回复配置 |

#### 核心功能

| 功能 | 描述 |
|------|------|
| **列表浏览** | 网格/列表视图展示快速回复模板 |
| **内容查看** | 查看快速回复的标题、消息内容、快捷键 |
| **导入导出** | 支持 JSON 格式的导入导出 |
| **搜索过滤** | 按名称、内容、标签搜索快速回复 |
| **批量管理** | 批量删除、移动、分类快速回复 |

#### 快速回复字段

```json
{
  "label": "显示标签",
  "message": "回复消息内容",
  "title": "悬停提示",
  "shortcut": "快捷键",
  "inject": true,
  "hidden": false
}
```

#### 界面特性

- **标签分类**：按功能分类（问候、动作、表情等）
- **图标显示**：根据内容自动匹配 Emoji 图标
- **快捷预览**：卡片形式展示消息内容预览
- **拖拽排序**：支持拖拽调整快速回复顺序

---

<a id="nav-feature-automation"></a>

### 自动化规则引擎

#### 规则引擎概述

ST-Manager 内置强大的规则引擎，支持基于条件的自动化任务执行。用户可以定义规则集，当卡片满足特定条件时自动执行预设操作。

#### 规则结构

```json
{
  "spec": "st_manager_ruleset",
  "spec_version": "1.0",
  "meta": {
    "name": "规则集名称",
    "description": "规则集描述",
    "author": "作者"
  },
  "logic": "OR",
  "rules": [
    {
      "name": "规则名称",
      "enabled": true,
      "logic": "OR",
      "groups": [
        {
          "logic": "AND",
          "conditions": [
            {
              "field": "char_name",
              "operator": "contains",
              "value": "关键词"
            }
          ]
        }
      ],
      "actions": [
        {
          "type": "set_tag",
          "value": "标签名称"
        }
      ],
      "stop_on_match": false
    }
  ]
}
```

#### 支持的字段

- `char_name` - 角色名称
- `description` - 角色描述
- `creator` - 创作者
- `tags` - 标签列表
- `token_count` - Token 数量
- `character_book` - 世界书
- `extensions.regex_scripts` - 正则脚本
- `extensions.tavern_helper` - Tavern Helper 脚本

#### 支持的操作符

| 操作符 | 说明 |
|--------|------|
| `exists` | 字段存在 |
| `not_exists` | 字段不存在 |
| `eq` | 等于 |
| `neq` | 不等于 |
| `contains` | 包含 |
| `not_contains` | 不包含 |
| `gt` | 大于 |
| `lt` | 小于 |
| `regex` | 正则匹配 |
| `true` / `false` | 布尔判断 |

#### 支持的动作

- `set_tag` - 添加标签
- `remove_tag` - 移除标签
- `set_favorite` - 设为收藏
- `unset_favorite` - 取消收藏
- `set_summary` - 设置备注
- `set_resource_folder` - 设置资源目录

---

### SillyTavern 本地资源读取与同步

ST-Manager 支持与本地 SillyTavern 实例进行资源双向同步，方便统一管理所有 AI 聊天资源。

#### 支持的资源类型

| 资源类型 | 英文标识 | 同步来源 | 目标目录 |
|---------|---------|---------|----------|
| **角色卡** | characters | SillyTavern `data/default-user/characters/` | `data/library/characters/` |
| **世界书** | worlds | SillyTavern `data/default-user/worlds/` | `data/library/lorebooks/` |
| **生成预设** | presets | SillyTavern `data/default-user/presets/` | `data/library/presets/` |
| **正则脚本** | regex | SillyTavern `data/default-user/extensions/regex/` + settings.json 全局正则 | `data/library/extensions/regex/` |
| **快速回复** | quick_replies | SillyTavern `data/default-user/quick-replies/` | `data/library/extensions/quick-replies/` |

#### 配置方式

在 设置 → 连接与服务 中配置：

```json
{
  "st_data_dir": "D:/SillyTavern",
  "st_url": "http://127.0.0.1:8000",
  "st_auth_type": "basic",
  "st_username": "",
  "st_password": ""
}
```

- `st_data_dir`: SillyTavern 安装目录（留空自动探测常见路径）
- `st_url`: SillyTavern API 地址（如使用 API 模式）
- 支持认证：Basic Auth 或 API Key

#### 同步模式

1. **文件系统模式**（推荐）：直接读取 SillyTavern 数据目录
   - 无需 SillyTavern 运行
   - 支持离线同步
   - 复制文件到 ST-Manager 目录

2. **API 模式**：通过 SillyTavern 的 st-api-wrapper 接口读取
   - 需要 SillyTavern 运行
   - 支持远程同步
   - 适合 Docker/服务器部署

#### 操作步骤

1. 打开 设置 → 连接与服务 标签页
2. 点击"自动探测路径"或手动输入 SillyTavern 目录
3. 验证路径后，系统显示各资源类型数量
4. 点击单个资源类型的"同步"按钮，或点击"全部同步"
5. 同步完成后自动刷新对应管理界面

#### 正则脚本同步说明

正则脚本同步会将以下两部分合并：
- **本地正则文件**：`data/default-user/extensions/regex/` 目录下的 `.json` 文件
- **全局正则**：从 `data/settings.json` 中读取的 `regex` 数组，导出为 `global__*.json` 文件

同步后的正则脚本可在 ST-Manager 的正则管理界面查看和编辑。

---

### 缓存与性能优化

#### 全局元数据缓存

- **内存缓存** - 所有卡片元数据加载到内存，实现毫秒级查询
- **增量更新** - 单卡编辑时仅更新内存，无需重载
- **分类计数** - 实时维护分类统计
- **标签池** - 全局标签索引

#### 文件系统监听

使用 `watchdog` 库实时监听文件变化：
- 自动同步新增文件
- 自动更新修改文件
- 自动清理删除文件
- 防抖处理，避免重复扫描

#### 缩略图系统

- 自动生成卡片缩略图（后台线程）
- 支持 PNG、JPEG 格式
- 并发控制（默认 4 线程）
- 智能清理无效缓存

---

## 🔌 API 文档

### 角色卡 API

#### 获取卡片列表

```
GET /api/list_cards?page=1&page_size=20&category=&tags=&search=&sort=date_desc
```

#### 更新卡片

```
POST /api/update_card
Content-Type: application/json

{
  "id": "卡片ID",
  "char_name": "角色名称",
  "description": "描述",
  "tags": ["标签1", "标签2"],
  ...
}
```

#### 移动卡片

```
POST /api/move_card
Content-Type: application/json

{
  "target_category": "目标分类",
  "card_ids": ["卡片ID1", "卡片ID2"]
}
```

#### 删除卡片

```
POST /api/delete_cards
Content-Type: application/json

{
  "card_ids": ["卡片ID1", "卡片ID2"]
}
```

### 世界书 API

#### 获取世界书列表

```
GET /api/world_info/list?type=all&search=&page=1&page_size=20
```

#### 上传世界书

```
POST /api/upload_world_info
Content-Type: multipart/form-data

files: [worldbook1.json, worldbook2.json]
```

#### 获取世界书详情

```
POST /api/world_info/detail
Content-Type: application/json

{
  "id": "world_info_id",
  "source_type": "global",
  "file_path": "/path/to/file.json",
  "preview_limit": 300,
  "force_full": false
}
```

### 预设 API

#### 获取预设列表

```
GET /api/presets/list?filter_type=all&search=
```

参数：
- `filter_type`: `all` | `global` | `resource` - 筛选类型
- `search`: 搜索关键词

#### 获取预设详情

```
GET /api/presets/detail/{preset_id}
```

#### 上传预设

```
POST /api/presets/upload
Content-Type: multipart/form-data

files: [preset1.json, preset2.json]
```

#### 删除预设

```
POST /api/presets/delete
Content-Type: application/json

{
  "id": "preset_id"
}
```

#### 保存预设扩展

```
POST /api/presets/save-extensions
Content-Type: application/json

{
  "id": "preset_id",
  "extensions": {
    "regex_scripts": [...],
    "tavern_helper": { "scripts": [...] }
  }
}
```

### 快速回复 API

#### 获取快速回复列表

```
GET /api/quick-replies/list?type=all&search=
```

#### 获取快速回复详情

```
GET /api/quick-replies/detail/{qr_id}
```

#### 上传快速回复

```
POST /api/quick-replies/upload
Content-Type: multipart/form-data

files: [quickreply1.json]
```

### 正则脚本 API

#### 获取正则脚本列表

```
GET /api/regex/list?source=all
```

参数：
- `source`: `all` | `global` | `preset` | `character` - 脚本来源

#### 保存正则脚本

```
POST /api/regex/save
Content-Type: application/json

{
  "id": "regex_id",
  "name": "脚本名称",
  "find": "查找模式",
  "replace": "替换内容",
  "enabled": true
}
```

### 自动化 API

#### 获取规则集列表

```
GET /api/automation/rulesets
```

#### 执行规则

```
POST /api/automation/execute
Content-Type: application/json

{
  "ruleset_id": "ruleset_id",
  "card_ids": ["card_id1", "card_id2"]
}
```

### 系统 API

#### 获取系统状态

```
GET /api/system/status
```

#### 扫描文件系统

```
POST /api/system/scan
Content-Type: application/json

{
  "full_scan": true
}
```

---

## 🛠️ 开发指南

### 开发环境设置

1. **安装开发依赖**

```bash
pip install -r requirements.txt
pip install black flake8 mypy pylint
```

2. **启动调试模式**

```bash
python app.py --debug
# 或
FLASK_DEBUG=1 python app.py
```

调试模式会启用热重载，修改代码后自动重启。

### 代码风格

项目遵循以下代码规范：

#### Python 代码风格

```python
# 导入顺序：标准库 -> 第三方库 -> 本地模块
import os
import sys
import json

from flask import Blueprint, request, jsonify

from core.config import CARDS_FOLDER, load_config
from core.utils.image import extract_card_info


# 命名约定
class ClassName:        # PascalCase
def function_name():    # snake_case
CONSTANT_VALUE = 1      # UPPER_CASE
_private_method()      # _leading_underscore


# 类型提示（推荐）
def process_card(card_id: str, data: dict) -> bool:
    """处理角色卡数据"""
    try:
        # 业务逻辑
        return True
    except Exception as e:
        logger.error(f"Failed to process card: {e}")
        return False


# 错误处理
try:
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
except FileNotFoundError:
    logger.error(f"File not found: {filepath}")
    return None
except json.JSONDecodeError as e:
    logger.error(f"Invalid JSON: {e}")
    return None
```

#### 前端代码风格

```javascript
// 使用模块化
import { Alpine } from 'alpinejs';
import { marked } from 'marked';

// 数据函数
function cardData() {
    return {
        loading: false,
        cards: [],
        selectedIds: [],
        
        async loadCards() {
            this.loading = true;
            try {
                const response = await fetch('/api/list_cards');
                const data = await response.json();
                this.cards = data.cards;
            } catch (error) {
                console.error('Failed to load cards:', error);
            } finally {
                this.loading = false;
            }
        },
        
        toggleSelect(id) {
            const idx = this.selectedIds.indexOf(id);
            if (idx > -1) {
                this.selectedIds.splice(idx, 1);
            } else {
                this.selectedIds.push(id);
            }
        }
    };
}
```

### 数据库结构

#### 卡片元数据表（card_metadata）

```sql
CREATE TABLE card_metadata (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    char_name TEXT,
    description TEXT,
    tags TEXT,
    token_count INTEGER,
    file_size INTEGER,
    file_hash TEXT,
    last_modified REAL,
    category TEXT,
    char_version TEXT,
    creator TEXT,
    is_favorite INTEGER DEFAULT 0,
    has_character_book INTEGER DEFAULT 0,
    character_book_name TEXT
);
```

#### 世界书剪切板表（wi_clipboard）

```sql
CREATE TABLE wi_clipboard (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_json TEXT NOT NULL,
    sort_order INTEGER DEFAULT 0,
    created_at REAL DEFAULT (strftime('%s', 'now'))
);
```

### 运行测试

```bash
# 运行所有测试
pytest tests/

# 运行单个测试
pytest tests/test_card_service.py::test_extract_card_info
```

### 代码质量检查

```bash
# 格式化代码
black .

# 检查代码风格
flake8 .

# 类型检查
mypy core/
```

---

## 🔧 故障排除

### 常见问题

#### 1. 端口被占用

**错误信息**：
```
❌ 启动失败：地址 127.0.0.1:5000 已被占用！
```

**解决方案**：
- 关闭其他占用端口的程序
- 修改 `config.json` 中的 `port` 设置为其他端口

#### 2. 数据库锁定

**错误信息**：
```
database is locked
```

**解决方案**：
- 关闭所有 ST-Manager 实例
- 删除 `data/system/db/cards_metadata.db-wal` 和 `-shm` 文件
- 重启程序

#### 3. 缩略图生成失败

**症状**：卡片缩略图显示为空白

**解决方案**：
- 检查图片文件是否损坏
- 清空 `data/system/thumbnails/` 目录
- 重启程序重新生成

#### 4. 自动扫描不工作

**症状**：文件修改后界面不更新

**解决方案**：
- 检查 `config.json` 中 `enable_auto_scan` 是否为 `true`
- 检查是否安装了 `watchdog` 库
- 手动触发扫描：系统设置 → 扫描文件系统

---

## 🤝 贡献指南

欢迎贡献代码、报告问题或提出建议！

### 贡献流程

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

### 开发规范

- 遵循现有的代码风格
- 为新功能添加测试
- 更新相关文档
- 编写清晰的提交信息

---

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

---

## 🙏 致谢

- [SillyTavern](https://github.com/SillyTavern/SillyTavern) - 本项目管理的目标程序
- [Flask](https://flask.palletsprojects.com/) - Web 框架
- [Tailwind CSS](https://tailwindcss.com/) - CSS 框架
- [Alpine.js](https://alpinejs.dev/) - 轻量级 JavaScript 框架

---

## 📮 联系方式

- 问题反馈：[GitHub Issues](https://github.com/Dadihu123/ST-Manager/issues)
- 功能建议：[Discord 类脑](https://discord.com/channels/1134557553011998840/1448353646596325578)

---

<div align="center">

**如果这个项目对你有帮助，请给个 ⭐️ Star 支持一下！**

Made with ❤️ by ST-Manager Team

</div>
