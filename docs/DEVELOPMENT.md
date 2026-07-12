# 开发指南

本文档面向当前仓库的实际结构，概述启动链路、模块分层、数据存储、测试方式与常用开发约定。

---

## 1. 技术栈与入口

- Python 3.10+
- Flask
- SQLite
- Pillow
- requests
- watchdog

关键入口：

- 主入口：`app.py`
- 应用工厂：`core/__init__.py:create_app`
- 后台初始化：`core/__init__.py:init_services`

前端形态：

- 单页入口：`/` -> `templates/index.html`
- 模板层：Jinja2
- 交互层：Alpine.js
- 样式层：Tailwind CSS
- 逻辑组织：原生 ES Modules

---

## 2. 项目结构

```text
ST-Manager/
├── app.py
├── config.json
├── requirements.txt
├── Dockerfile
├── docker-compose.yaml
├── AGENTS.md
├── core/
│   ├── __init__.py              # create_app + init_services
│   ├── auth.py                  # 外网认证、白名单、限流、Session
│   ├── config.py                # 默认配置、配置归一化、路径解析
│   ├── context.py               # 全局运行时上下文
│   ├── consts.py                # 常量
│   ├── event_bus.py             # 事件总线
│   ├── api/
│   │   ├── views.py             # 单页入口与 favicon
│   │   └── v1/
│   │       ├── cards.py         # 角色卡 API
│   │       ├── chats.py         # 聊天 API
│   │       ├── world_info.py    # 世界书 API
│   │       ├── presets.py       # 预设 API
│   │       ├── extensions.py    # 扩展脚本 API
│   │       ├── automation.py    # 自动化 API
│   │       ├── system.py        # 设置、快照、索引、系统动作
│   │       ├── st_sync.py       # ST 同步 API
│   │       ├── beautify.py      # 美化库 API
│   │       └── resources.py     # 文件预览与资源服务
│   ├── services/                # 业务服务、索引、ST 集成、版本逻辑
│   ├── automation/              # 自动化规则引擎
│   ├── data/                    # SQLite、UI 存储、聊天存储、索引状态
│   └── utils/                   # 纯工具函数
├── templates/                   # 单页模板、组件模板、模态模板
├── static/
│   └── js/
│       ├── api/                 # 前端 API 封装
│       ├── components/          # 页面组件与模态逻辑
│       ├── runtime/             # 运行时预览、脚本执行、聊天展示
│       ├── utils/               # 前端工具函数
│       └── vendor/              # 本地第三方脚本
├── tests/                       # pytest 与前端契约回归测试
└── data/                        # 运行时数据目录
```

---

## 3. 启动流程

### 3.1 本地启动

`app.py` 的实际流程如下：

1. 解析命令行参数 `--debug`、`--host`、`--port`
2. 判断是否运行在 Docker 中
3. 自动确保 `config.json` 存在
4. 读取配置并创建运行时目录
5. 解析最终 `host` / `port` / `debug`
6. 在主进程中进行端口占用检测
7. 在后台线程中启动 `init_services()`
8. 创建 Flask 应用并注册全部蓝图
9. 启动 Web 服务，并在合适场景下自动打开浏览器

`debug` 模式下只会在 Flask reloader 子进程中启动后台服务，避免数据库初始化、扫描器和索引 worker 被重复拉起。

### 3.2 后台初始化

`core.__init__.init_services()` 负责：

1. 清理 `data/temp`
2. 初始化数据库与迁移
3. 检查索引升级状态
4. 加载缓存
5. 启动后台扫描器
6. 启动索引任务 worker
7. 更新全局状态为 ready

### 3.3 Docker Compose 启动

`docker-compose.yaml` 包含两个服务：

- `init-config`：先在宿主机根目录生成 `./config.json`
- `st-manager`：等待初始化成功后再启动主服务

这意味着文档、测试和部署脚本都应默认假设 `config.json` 来自宿主机挂载，而不是容器内部临时生成。

---

## 4. 后端架构

### 4.1 API 层

API 主要集中在 `core/api/v1/`，按资源域拆分：

- `cards.py`：角色卡列表、编辑、导入、标签、文件夹、Bundle、资源联动
- `chats.py`：聊天列表、阅读、搜索、书签、绑定、保存
- `world_info.py`：全局 / 资源 / 内嵌世界书管理
- `presets.py`：预设详情、保存、版本家族、发送到 ST
- `extensions.py`：Regex、Quick Replies、Tavern Helper 扩展统一入口
- `automation.py`：规则集和执行
- `system.py`：设置、扫描、索引、快照、回收站、系统动作
- `st_sync.py`：SillyTavern 探测、校验、同步、概览
- `beautify.py`：主题美化库、壁纸、头像、变体、发送到 ST
- `resources.py`：缩略图、资源文件、背景图、资源上传与删除
- `forum.py`：类脑搜索站预览转发（`forum.shimmerday.top`）

### 4.2 服务层

`core/services/` 是主要业务逻辑承载层，包含：

- 文件扫描与缓存刷新
- 索引构建、状态查询、升级恢复与任务 worker
- 角色卡读写与同步
- 世界书索引查询
- 预设存储、建模与版本家族管理
- ST 认证、ST 客户端与路径安全校验
- 标签治理
- 共享壁纸库与用户数据库备份

### 4.3 自动化引擎

`core/automation/` 负责：

- 规则集模型与标准化
- 条件评估
- 动作执行
- 模板运行时
- 标签合并逻辑
- 论坛标签抓取

### 4.4 全局上下文

`core/context.py` 中的 `ctx` 提供共享运行时状态，包括：

- 启动状态
- 缓存对象
- 锁 / 队列
- 后台服务之间的协作状态

---

## 5. 前端架构

### 5.1 单页入口

- `/` 由 `core/api/views.py` 返回 `templates/index.html`
- 页面模式由前端状态切换，而不是多路由页面切换

### 5.2 目录分层

| 目录 | 职责 |
| --- | --- |
| `static/js/api/` | 浏览器端 API 封装 |
| `static/js/components/` | 网格、详情、设置、模态、编辑器 |
| `static/js/runtime/` | 聊天运行时、脚本运行时、预览框架 |
| `static/js/utils/` | 格式化、差异、DOM、下载等工具 |
| `templates/components/` | 页面级组件模板 |
| `templates/modals/` | 各类弹窗模板 |

### 5.3 运行时子系统

前端不仅是列表与表单界面，还包含多个运行时子系统：

- 聊天阅读器运行时
- 统一文本 / Markdown / HTML 预览
- 正则测试台
- ST 脚本运行时
- 主题美化预览 frame

因此修改聊天阅读器、预设编辑器或美化预览时，通常需要同时检查模板、组件脚本和 `static/js/runtime/`。

---

## 6. 配置与路径管理

配置逻辑在 `core/config.py`：

- `DEFAULT_CONFIG` 定义默认配置项
- `normalize_config()` 会做 ST 认证字段归一化
- `ensure_config_file()` 负责首次生成
- `ensure_runtime_dirs()` 负责创建主要运行目录

路径相关约定：

- 相对路径以项目根目录为基准
- 统一使用 `os.path.join()` 生成本地路径
- 存储到 ID 或 JSON 中的相对路径统一转为 `/`

---

## 7. 数据存储

项目当前采用“SQLite 主索引 + JSON 辅助存储”的混合模式。

### 7.1 SQLite

数据库入口：`core/data/db_session.py`

主要职责：

- 提供请求内数据库连接
- 在连接上开启 WAL 与 `synchronous=NORMAL`
- 通过 `execute_with_retry()` 处理 `database is locked`
- 初始化核心表与迁移
- 引导索引运行时 schema

核心表包括：

| 表名 | 作用 |
| --- | --- |
| `card_metadata` | 角色卡元数据索引 |
| `folder_structure` | 文件夹结构缓存 |
| `ui_data_cache` | 卡片 UI 关联信息缓存 |
| `wi_clipboard` | 世界书剪贴板 |

索引运行时 schema 由 `core/data/index_runtime_store.py` 创建，主要包括：

| 表名 | 作用 |
| --- | --- |
| `index_schema_state` | schema 状态 |
| `index_build_state` | cards / worldinfo 索引构建状态 |
| `index_entities_v2` | 索引实体投影 |
| `index_entity_tags_v2` | 索引标签投影 |
| `index_search_fast_v2` | FTS5 快速搜索索引 |
| `index_search_full_v2` | FTS5 全文搜索索引 |
| `index_category_stats_v2` | 分类统计 |
| `index_facet_stats_v2` | Facet 统计 |
| `index_jobs` | 索引任务队列表 |

### 7.2 JSON 辅助存储

| 文件 | 模块 | 作用 |
| --- | --- | --- |
| `data/system/db/ui_data.json` | `core/data/ui_store.py` | 标签体系、隔离分类、资源分类覆盖、世界书备注、美化库、共享壁纸等 UI 数据 |
| `data/system/db/chat_data.json` | `core/data/chat_store.py` | 聊天收藏、备注、显示名、书签、阅读位置等本地元数据 |

这些 JSON 文件由各自 store 模块负责规范化读写，不建议在其他模块中直接手写结构。

---

## 8. 测试

### 8.1 安装

```bash
pip install -r requirements.txt
pip install pytest
```

### 8.2 常用命令

```bash
# 全量
pytest tests/

# 单文件
pytest tests/test_st_auth_flow.py

# 单用例
pytest tests/test_st_auth_flow.py::test_st_http_client_web_performs_login

# 详细输出
pytest -v tests/test_chat_list_filters.py::test_chat_list_fav_filter_included
```

### 8.3 覆盖面

当前 `tests/` 已覆盖多个层面：

- API 行为测试
- 服务层与存储层测试
- 配置启动测试
- 索引状态与任务测试
- 路径安全与 ST 认证测试
- 前端模板契约测试
- 聊天阅读器 / 预设编辑器 / 美化预览等前端契约测试

仓库中还包含部分 `.mjs` 运行时回归脚本，主要用于专项验证前端行为。

---

## 9. 常用开发命令

```bash
# 启动应用
python app.py

# Debug 模式
python app.py --debug

# 黑格式化（可选）
black app.py core tests

# flake8（可选）
flake8 app.py core tests

# mypy（可选）
mypy core
```

---

## 10. 开发约定

### 10.1 Python

- 导入顺序：标准库、第三方、本地模块
- 命名：`PascalCase`、`snake_case`、`UPPER_CASE`
- Blueprint 对象通常命名为 `bp`
- 对文件系统、网络、JSON、子进程操作使用显式错误处理
- 日志统一使用 `logging.getLogger(__name__)`

### 10.2 数据与路径

- SQL 必须参数化，避免拼接 SQL
- 写操作优先通过 `execute_with_retry()` 处理锁冲突
- 路径写入存储前统一转为 `/`
- 修改资源 / 配置路径时要注意路径安全检查逻辑

### 10.3 编辑策略

- 优先做小而准的改动
- 跟随现有模块边界，不随意引入新的框架层
- 改动角色卡、世界书、预设、聊天等核心流程时，优先补充或更新对应测试

---

## 11. 文档与排查建议

- API 变更优先同步 `docs/API.md`
- 配置字段或 Docker 行为变更优先同步 `docs/CONFIG.md`
- 启动链路、数据层或目录结构变更优先同步本文件

排查问题时建议按以下顺序：

1. 先确认配置是否正确加载
2. 再看 `ctx` 状态、扫描状态与索引状态
3. 再看具体 API / 服务层日志
4. 最后补充或运行针对性的 pytest 用例
