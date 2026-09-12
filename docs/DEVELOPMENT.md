# 开发指南

本文档描述 ST Manager 当前代码的开发入口和运行模型。项目是一个 Python Flask 服务加浏览器端 ES modules 的单体应用，资源文件本身仍保存在文件系统中，SQLite 负责元数据、索引和运行时任务。

## 环境

- Python 3.10 或更高版本。
- 运行依赖：Flask、Pillow、requests、watchdog，见 `requirements.txt`。
- 前端样式构建需要 Node.js/npm；`package.json` 只声明 Tailwind CSS 3.4.17。
- 浏览器端代码使用原生 ES modules 和 Alpine.js，不需要 Vite、Webpack 或 React 构建链。

### 初始化

```bash
python -m venv .venv

# Windows PowerShell
.\\.venv\\Scripts\\Activate.ps1

# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
pip install pytest
```

## 启动链路

入口是 `app.py`：

1. 解析 `--debug`、`--host`、`--port`。
2. 创建/读取根目录 `config.json`，再创建运行时目录。
3. 检查监听端口是否被占用。
4. 在 daemon 线程中启动 `init_services()`，避免数据库扫描阻塞 Flask 页面启动。
5. 通过 `core.create_app()` 创建 Flask 应用，注册 API 蓝图、页面蓝图和认证钩子。
6. 非 debug 模式下自动打开浏览器；debug 模式只在 Werkzeug 子进程启动后台服务。

`init_services()` 的顺序是：清理 `data/temp`、初始化/迁移 SQLite、恢复或引导索引、加载内存缓存、启动文件扫描器、启动索引任务 worker、启动来源更新监控调度器，最后把全局状态切换为 `ready`。

## 项目结构

```text
app.py                         # CLI 启动入口
core/
├─ __init__.py                 # create_app / init_services
├─ config.py                   # 配置默认值、路径解析和归一化
├─ context.py                  # 全局运行时状态、锁和队列
├─ auth.py                     # 可选外网认证、白名单和失败限流
├─ api/
│  ├─ views.py                 # 首页、预览资源页面
│  └─ v1/                      # Flask 业务蓝图
├─ data/                       # SQLite、UI 数据、聊天和索引存储
├─ services/                   # 文件扫描、缓存、索引、同步和业务服务
├─ automation/                 # 规则引擎、动作执行、模板和标签合并
└─ utils/                      # 图片、路径、解析、哈希和纯函数工具
templates/                     # Jinja 页面、组件和模态框
static/
├─ js/api/                     # 浏览器端 API 封装
├─ js/components/              # Alpine 页面组件和编辑器
├─ js/runtime/                 # 聊天/预览 iframe 运行时
├─ css/                        # Tailwind 产物和模块样式
├─ icons/                      # SVG 精灵及独立图标
└─ vendor/sillytavern/         # 隔离的 ST 预览资源
tests/                         # pytest、Node runtime 和前端契约测试
docs/                          # API、配置、开发和设计说明
```

## 后端边界

### Flask 工厂和蓝图

所有页面和业务接口都在 `create_app()` 中注册。新增 HTTP 功能时：

- 页面入口放到 `core/api/views.py` 或新的页面蓝图。
- 业务 API 放到 `core/api/v1/` 的对应蓝图中。
- 解析、持久化和外部服务调用放到 `core/services/`，不要把长业务流程塞进路由函数。
- 纯粹的路径、文本、解析和转换逻辑放到 `core/utils/`。
- 返回 JSON 错误时使用结构化字段，不把 Python traceback 返回给浏览器。

当前主要蓝图如下：

| 蓝图 | 负责范围 |
| --- | --- |
| `cards` | 角色卡、标签、文件夹、上传、来源更新 |
| `world_info` | 全局/资源/内嵌世界书、编辑、历史和剪贴板 |
| `chats` | JSONL 聊天索引、范围读取、阅读和绑定 |
| `presets` | 预设、扩展、版本和 SillyTavern 发送 |
| `extensions` / `resources` | 扩展脚本、角色资源和静态文件 |
| `beautify` | 主题包、变体、壁纸、头像和预览 |
| `automation` | 规则集、条件、动作和批量执行 |
| `st_sync` | SillyTavern 本地/API 连接、扩展资源和 JS-Slash-Runner 脚本同步 |
| `system` | 状态、设置、扫描、索引、快照、备份和维护 |
| `forum` | 来源论坛帖子预览 |

### 数据流

```text
浏览器 Alpine 组件
        │  fetch JSON / FormData
        ▼
Flask Blueprint 路由
        │  参数校验、路径安全、权限边界
        ▼
Service / Automation / STClient
        ├─ 文件系统：卡片、世界书、聊天、预设、扩展、主题
        ├─ ST settings.json：JS-Slash-Runner 全局脚本树
        ├─ SQLite：元数据、UI 关联、索引、任务、监控运行
        └─ 内存状态：ctx.cache、初始化状态、索引唤醒事件
        ▼
JSON 响应、下载流或静态资源
```

### SQLite 约定

- 请求上下文内通过 `core.data.db_session.get_db()` 获取连接。
- 连接启用 WAL 和 `synchronous=NORMAL`，请求结束由 Flask teardown 关闭。
- 可能遇到锁的写入使用 `execute_with_retry()` 或业务已有的重试/锁封装。
- 所有查询使用参数化 SQL；不要拼接用户输入。
- 数据库初始化和迁移集中在 `init_database()` 及对应的数据模块。
- 索引采用代际构建：卡片和世界书索引可以后台重建，任务由 daemon worker 消费并记录状态。

### 文件系统安全

文件接口必须先规范化相对路径，再验证目标位于允许根目录内。删除优先移动到 `data/system/trash`，不要直接 `os.remove()` 绕过回收站、UI 关联和索引清理。绝对资源根只有在 `allowed_abs_resource_roots` 或已有资源绑定允许时才可访问。

## 前端开发

### 入口和组件

`static/js/app.js` 初始化全局状态并注册 Alpine 组件；`static/js/state.js` 维护跨工作区状态。页面组件按领域拆分：

- `cardGrid.js`、`detailModal.js`：角色卡网格和详情编辑。
- `wiGrid.js`、`wiEditor.js`、`wiDetailPopup.js`：世界书列表、编辑器和预览。
- `chatGrid.js`：聊天列表、阅读器、范围加载、书签和变量快照。
- `presetGrid.js`、`presetEditor.js`、`presetDetailReader.js`：预设列表、编辑器和阅读器。
- `extensionGrid.js`、`automationModal.js`、`beautifyGrid.js`：扩展、自动化和 Beautify。
- `runtime/`：隔离的 HTML/Markdown/脚本/聊天预览运行时。

与后端交互的函数集中在 `static/js/api/`；新增请求时优先在对应 API 模块添加封装，再由组件调用。模板图标使用 `templates/components/icon.html` 的宏和 `static/icons/*.svg` 精灵，不要复制 SVG path。

### CSS

源文件是 `static/css/tailwind-input.css` 和模块 CSS；压缩后的 `static/css/tailwind.css` 由 Tailwind 生成。聊天和 Beautify 的样式分别位于 `static/css/modules/view-chats.css`、`static/css/modules/view-beautify.css` 及其局部文件。

```bash
npm install
npm run build:css
```

手动调整模块样式后，应确认桌面、窄屏和移动端布局，以及深色/浅色主题下的文本、图标和弹窗状态。

## 测试

### Python

```bash
pytest tests/
pytest -q tests/test_st_auth_flow.py
pytest -q tests/test_settings_api.py tests/test_st_path_safety.py
pytest -q tests/test_index_schema.py tests/test_index_job_worker.py
```

### 前端和运行时

仓库中还有 Node `.mjs` 测试以及读取模板/JavaScript 源码的契约测试。可直接执行：

```bash
node tests/chat_reader_variable_merge_test.mjs
node tests/tag_filter_modal_blacklist_regression_test.mjs
```

新增行为时，优先补充对应服务/API 测试；涉及模板、图标、Alpine 状态或 iframe 预览时，同时更新前端契约测试。

## 调试与常见检查

```bash
python app.py --debug
python -m core.auth
python -m core.auth --set-auth <username> <password>
python -m core.auth --add-ip <ip-or-cidr-or-domain>
```

检查启动状态：

```bash
curl http://127.0.0.1:5000/api/status
curl http://127.0.0.1:5000/api/index/status
```

如果页面停留在初始化遮罩，先查看 `/api/status`，再检查 `data/system/db/cards_metadata.db` 是否可写、索引任务是否报错、配置目录是否有效。不要通过删除数据库解决普通数据问题；优先使用扫描、索引重建、备份和回滚能力。

## Docker 与桌面打包

### Docker

```bash
docker compose up --build
```

镜像使用 Python 3.10 slim，安装 Pillow 所需的系统库，暴露 5000 端口。Compose 中的 `init-config` 服务只负责在工作区生成配置，主服务挂载 `./data` 和 `./config.json`。

### PyInstaller

`.github/workflows/build-desktop.yml` 会在 Windows、macOS arm64 和 macOS x86_64 上安装依赖并把 `templates/`、`static/` 一并打包。修改资源路径或新增静态目录时，需要同步检查 `--add-data` 参数和 PyInstaller frozen 路径逻辑。

标签以 `v*` 发布时，Docker workflow 会构建并推送 GHCR 镜像；桌面构建 workflow 还支持手动触发。

## 代码风格与提交边界

- Python 使用 4 空格、绝对导入和小范围改动；导入顺序为标准库、第三方、本地模块。
- API、服务、数据层保持单向依赖，避免在模块顶层制造循环导入。
- 用户可见文字优先保持中文；技术标识符、函数名和模块名使用英文。
- 新增文件读写、JSON、网络和子进程操作时处理具体异常并记录日志。
- 路径、SQL、认证和同步相关改动必须补安全边界测试。
- 不要把 `config.json`、`data/`、运行时 DB、Token、Cookie 和个人资源写入提交。
