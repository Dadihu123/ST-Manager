# ST-Manager 插件系统设计（含官方插件目录与 API 契约）

> 状态：**设计文档，不实现**
> 日期：2026-09-22
> 前置阅读：`docs/2026-09-22-plugin-system-and-ai-plugin-analysis.md`（脚本 AI 能力解剖 + 现状盘点）
> 范围：**只做插件系统本身**。AI 分析/打标/世界书缩减等具体插件功能将在独立仓库实现，本文只定义它们所依赖的 API 契约。
> 引用格式 `文件:行号`；推断项标 **[推断]**，未验证项标 **[未验证]**。

---

## 目录

- [第 0 部分 · 决策基线](#第-0-部分--决策基线)
- [第 1 部分 · 架构总览](#第-1-部分--架构总览)
- [第 2 部分 · 插件目录与 manifest 规范](#第-2-部分--插件目录与-manifest-规范)
- [第 3 部分 · 官方插件目录与 GitHub 安装](#第-3-部分--官方插件目录与-github-安装)
- [第 4 部分 · 后端插件运行时](#第-4-部分--后端插件运行时)
- [第 5 部分 · Hook 总线](#第-5-部分--hook-总线)
- [第 6 部分 · 通用作业系统与 SSE](#第-6-部分--通用作业系统与-sse)
- [第 7 部分 · 密钥存储](#第-7-部分--密钥存储)
- [第 8 部分 · 前端插件运行时](#第-8-部分--前端插件运行时)
- [第 9 部分 · 插件管理 UI](#第-9-部分--插件管理-ui)
- [第 10 部分 · API 契约（供独立仓库开发）](#第-10-部分--api-契约供独立仓库开发)
- [第 11 部分 · 分期路线图](#第-11-部分--分期路线图)
- [第 12 部分 · 风险与陷阱](#第-12-部分--风险与陷阱)
- [第 13 部分 · 测试策略](#第-13-部分--测试策略)
- [附录 A · 新增文件清单](#附录-a--新增文件清单)
- [附录 B · 核心代码改动点](#附录-b--核心代码改动点)

---

# 第 0 部分 · 决策基线

本设计基于以下已确认决策（来自需求方）：

| # | 决策 | 对设计的影响 |
|---|---|---|
| D1 | **插件外置**；内置一份「官方插件目录」，含 GitHub 链接，用户可选安装 | 需要插件市场 UI + GitHub 下载/解压/校验 + 版本更新；插件本体**不随包分发** |
| D2 | **独立 `secrets.json`**，但**注意兼容** | 新文件承载插件密钥；**不迁移、不破坏**现有 `config.json` 中的密钥；提供统一读取适配层 |
| D3 | AI 生成结果经**用户确认后直接合并回原文件** | 打标走现有 `/api/batch_tags` 的**合并语义**；无需新的存储层 |
| D4 | 打标**默认合并**（不清空已有标签） | 与 D3 一致；「替换」需显式开关 |
| D5 | **引入 SSE** | 新增首个 `Response(generator)` 端点；前端新增 `EventSource` 消费 + 轮询降级 |
| D6 | 世界书缩减等破坏性操作**逐条确认** | 作业系统需支持 per-item 审批状态，而非只支持「全部应用」 |
| D7 | 插件按**本地可信代码**对待，不做沙箱 | 不做能力隔离；`permissions` 降级为**声明与审计**用途，不作为执行门控 |
| D8 | `api_version` 不兼容时**严格拒绝加载** | 不做「降级加载 + 功能受限」的中间态；UI 明确提示「需更新主程序」 |
| D9 | 插件生命周期为**四个独立操作**：安装 / 卸载 / 禁用 / 启用 | 「禁用」= 完全不加载（不注册路由、不跑作业、不派发 hook）；不设「加载但禁用路由」中间态 |
| D10 | 卸载时**默认清理**插件的 `ui_data._plugins_v1.<id>` 命名空间 | `keep_data` 改为显式 opt-in（默认 `false`），与 D9 的「彻底」语义一致 |
| D11 | catalog 采用**方案 B**：清单放在**本仓库**，应用从本仓库的 GitHub raw 拉取 | 默认远端 URL 指向 `Dadihu123/ST-Manager` 的 `main` 分支；包内保留一份兜底清单；用户可在设置中覆盖 URL 或关闭远端拉取 |
| D12 | 作业事件保留**按作业条数**：completed 保留 100、failed 保留 50 | 与 `index_job_worker.py:28-29` 的现有约定一致；`plugin_jobs` / `plugin_job_items` / `plugin_job_events` 三表共用同一保留决策 |

**关键推论**：因为插件功能将在**独立仓库**实现（D1 + 需求方明确说明），插件系统必须**先把 API 契约冻结**。第 10 部分是本设计的核心交付物——它是跨仓库协作的接口。

**术语约定**（避免歧义，本文档全文遵循）：

| 术语 | 含义 |
|---|---|
| **插件**（plugin） | 一个可独立增删的功能包，位于 `data/plugins/<id>/` |
| **catalog** | 「官方插件清单」——一份**只含元数据、不含插件代码**的 JSON，列出推荐插件的名称/简介/GitHub 地址。用户在 UI 里看到它，点「安装」才去 GitHub 下载真正的插件代码。见第 3.1 节 |
| **manifest** | 每个插件自己的 `manifest.json`，声明 id/版本/入口/权限等。catalog 里的是快照，**以 manifest 为准** |
| **作业**（job） | 插件发起的一次长任务（如「分析 50 张卡」），有 run_id、进度、取消、断点续跑 |
| **作业事件**（job event） | 作业运行中产生的一条条增量记录（某卡完成/失败/日志），存表供 SSE 推送与刷新后回看。见第 6.5 节 |

---

# 第 1 部分 · 架构总览

## 1.1 分层

```
┌─────────────────────────────────────────────────────────────┐
│  浏览器                                                       │
│  ├─ 核心前端 (Alpine.js, 32 个组件)                            │
│  └─ PluginHost ──┬─ 插件 A (ES module, activate(api))          │
│                  └─ 插件 B                                    │
│         ▲ 同源 fetch / EventSource(SSE) / window CustomEvent   │
└─────────┼───────────────────────────────────────────────────┘
          │
┌─────────┼───────────────────────────────────────────────────┐
│  Flask  │  create_app()                                      │
│  ├─ 核心蓝图 (11 个, 177 路由)                                 │
│  ├─ PluginRegistry ──┬─ 插件 A (Blueprint @ /api/plugins/a)    │
│  │                   └─ 插件 B                                │
│  └─ init_auth()                                              │
│                                                              │
│  init_services()                                             │
│  ├─ 核心: 建库→索引恢复→缓存→扫描器→索引worker→监控调度          │
│  └─ PluginJobWorker (新增, 消费 plugin_jobs)                   │
└──────────────────────────────────────────────────────────────┘
          │
┌─────────┴───────────────────────────────────────────────────┐
│  存储                                                         │
│  ├─ data/plugins/<id>/          插件本体 (D1: 外置)             │
│  ├─ data/system/db/cards_metadata.db   核心库 + plugin_jobs     │
│  ├─ data/system/db/ui_data.json        _plugins_v1.<id>.*       │
│  ├─ data/system/plugins/               _catalog_cache.json      │
│  └─ data/system/secrets.json           (D2: 新增)              │
└──────────────────────────────────────────────────────────────┘
```

## 1.2 关键设计取舍

| 取舍 | 选择 | 理由 |
|---|---|---|
| 插件语言 | Python（后端）+ ES module（前端） | 与现有栈一致；无打包器约束（`docs/DEVELOPMENT.md:9-10`） |
| 插件位置 | `data/plugins/` | PyInstaller 只打包 `templates/`+`static/`（`.github/workflows/build-desktop.yml`），放 `data/` 天然不被打包且可增删 |
| 官方插件分发 | catalog 随包 + 插件本体 GitHub 下载 | 满足 D1；避免把第三方代码冻进产物 |
| 事件机制 | 新建 `core/plugins/hooks.py` | `core/event_bus.py` 是 15 行空壳且全仓零引用，直接替换 |
| 作业存储 | 主库新增 `plugin_jobs`/`plugin_job_items` | 复用 WAL + `execute_with_retry`；避免多库事务 |
| 作业蓝本 | `source_update_monitor_runs` | 唯一具备 run_id + 进度 + 协作式取消 + 崩溃恢复的现成实现 |
| 进度推送 | SSE（D5），保留轮询降级 | 浏览器兼容性与代理环境兜底 |
| 密钥 | 独立 `secrets.json`，`config.json` 不动 | D2；避免破坏现有部署 |
| 隔离 | 不做（D7） | 本地单用户工具；沙箱成本 >> 收益 |

## 1.3 已确认的技术前提

| 事实 | 证据 | 影响 |
|---|---|---|
| Flask `run()` 默认 `threaded=True` | werkzeug `run_simple` 的 `options.setdefault("threaded", True)` | SSE 可用，无需改服务器；每个 SSE 连接占一个线程 |
| 全仓 **零** `after_request` | `grep after_request core/` → 0 | 加 SSE/安全头需首次改 `create_app()` |
| 全仓 **零** `Response(generator)` | `grep 'Response(\|stream_with_context' core/` → 0 | SSE 是全新能力 |
| 全仓零 `EventSource` | `grep EventSource static/js` → 0 | 前端 SSE 是全新能力 |
| `_is_under_base` 在 4 处重复（含内联 realpath） | `chats.py:85`、`world_info.py:78`、`system.py:139`（函数定义）+ `cards.py:3742`（内联） | 插件资源路由**不要**再加第 5 份，应抽公共工具 |
| `data_dir_lock` 强制单进程 | `core/data/data_dir_lock.py`、`app.py:121-137` | 插件不得假设多进程；**但插件可以自由在 `data/plugins/<id>/data/` 下写文件**（该目录不在扫描器/监控的监视范围内）。若写 `data/library/` 或 `data/system/` 下的文件会触发扫描/监控，门面方法（`write_card_fields`、`write_worldbook` 等）已内置 `suppress_fs_events`；插件自行写文件时应**先调用 `api.suppress_fs_events()`**（新增该方法，内部用 `ctx.fs_ignore_lock`） |
| SQLite 3.49.1 / Python 3.12 / Flask 3.1.3 | 实测 | 可用 `RETURNING`、`STRICT` 表等新特性 **[可选]** |

---

# 第 2 部分 · 插件目录与 manifest 规范

## 2.1 目录布局

```
data/plugins/                   # 只放插件本体（目录名 = plugin id）
├─ stm-ai-assistant/            # 插件根
   ├─ manifest.json             # 必需
   ├─ README.md                 # 建议
   ├─ CHANGELOG.md              # 建议（更新 UI 展示）
   ├─ backend/
   │  ├─ __init__.py            # 必需：def register(api)
   │  ├─ routes.py              # 可选
   │  ├─ jobs.py                # 可选
   │  ├─ service.py             # 可选
   │  └─ migrations/
   │     └─ 001_init.sql
   ├─ frontend/
   │  ├─ plugin.js              # 可选：export function activate(api)
   │  ├─ plugin.css
   │  └─ templates/             # 可选：Jinja partial
   └─ data/                     # 运行时私有（日志/缓存），安装时创建
```

**约束**
- 目录名必须等于 `manifest.id`，且匹配 `^[a-z][a-z0-9-]{1,63}$`（小写、连字符、不以数字开头）。**这是路径安全的第一道闸门。**
- `backend/` 与 `frontend/` 至少要有一个。
- 插件**不得**包含 `__pycache__`、`.git`、`node_modules`（安装时剥离）。

## 2.2 manifest.json 规范

```jsonc
{
  // ---- 必需 ----
  "id": "stm-ai-assistant",              // 必须等于目录名
  "name": "AI 角色卡分析助手",
  "version": "0.1.0",                    // 语义化版本
  "api_version": 1,                      // 主程序 API 契约版本（硬闸门）

  // ---- 建议 ----
  "author": "",
  "description": "为角色卡生成概览与标签建议",
  "homepage": "https://github.com/<owner>/<repo>",
  "license": "MIT",
  "icon": "frontend/icon.svg",           // 相对插件根
  "min_app_version": "1.0.0",            // 可选：最低主程序版本

  // ---- 后端 ----
  "backend": {
    "entry": "backend",                  // import 路径（相对插件根）
    "register": "register",              // 注册函数名
    "jobs": ["ai.analyze", "ai.translate"],
    "hooks": ["card.updated", "worldbook.saved"]
  },

  // ---- 前端 ----
  "frontend": {
    "entry": "frontend/plugin.js",
    "styles": ["frontend/plugin.css"],
    "panels": [
      { "id": "ai-workbench", "mode": "cards", "label": "AI 分析", "icon": "ai" }
    ],
    "settings_tab": { "id": "ai", "label": "AI 助手" },
    "detail_tab": null                   // 可选：在卡片详情页加 tab
  },

  // ---- 声明（D7：审计用，非执行门控）----
  "permissions": [
    "cards.read", "cards.write",
    "worldbook.read", "worldbook.write",
    "tags.read", "tags.write",
    "secrets.read", "network.outbound", "jobs.run"
  ],

  // ---- 配置 schema（用于自动生成设置表单）----
  "config_schema": {
    "type": "object",
    "properties": {
      "max_tags":   { "type": "integer", "title": "最大标签数", "default": 5, "minimum": 1, "maximum": 20 },
      "batch_size": { "type": "integer", "title": "每批张数", "default": 10, "minimum": 1, "maximum": 50 },
      "concurrency":{ "type": "integer", "title": "并发数", "default": 2, "minimum": 1, "maximum": 8 },
      "apply_tags": { "type": "boolean", "title": "自动应用标签", "default": false }
    }
  },

  // ---- 密钥声明（用于渲染密钥表单，值不在 manifest 里）----
  "secret_schema": {
    "type": "object",
    "properties": {
      "api_key":  { "type": "string", "title": "API Key", "secret": true },
      "base_url": { "type": "string", "title": "API 地址", "default": "https://api.openai.com/v1" }
    }
  }
}
```

### 校验规则

| 字段 | 规则 | 失败处理 |
|---|---|---|
| `id` | 正则 + 等于目录名 | 拒绝加载 |
| `version` | 语义化版本（`X.Y.Z[-pre][+build]`） | 拒绝加载 |
| `api_version` | 必须 ∈ 主程序支持集合（当前 `{1}`） | 拒绝加载，UI 显示「需要更新主程序」 |
| `min_app_version` | ≤ 当前主程序版本 | 拒绝加载，UI 提示升级 |
| `backend.entry` | 归一化后必须位于插件目录内 | 拒绝加载 |
| `backend.jobs` | 非空字符串、全局唯一（跨插件） | 冲突者拒绝注册该 job |
| `backend.hooks` | 必须 ∈ 已知事件集合 | 忽略未知项 + 警告 |
| `permissions` | 白名单校验 | 未知项忽略 + 警告 |
| `requires` | 对象：插件 id → 版本约束（`>=` `>` `<=` `<` `==` `*`；无操作符视为精确匹配） | 非法项忽略 + 警告；依赖缺失 / 被禁用 / 版本不满足 / 循环依赖 → 该插件拒绝加载并写 `load_error` |
| `config_schema` / `secret_schema` | 仅支持 JSON Schema 子集 | 非法则回退为「无表单」 |

**依赖加载语义**：`load_all()` 分三阶段——先解析全部 manifest，再做依赖校验与拓扑排序（**被依赖者先加载**），最后按序实例化。依赖链上任何一环失败（manifest 非法、后端注册抛错）都会让下游插件一并记 `依赖链中存在无法加载的插件` 并跳过，不会带着半可用状态启动。

**JSON Schema 子集**（避免引入 `jsonschema` 依赖）：支持 `type`（`string`/`integer`/`number`/`boolean`/`enum`）、`title`、`description`、`default`、`minimum`、`maximum`、`enum`、`secret`、`required`。复杂结构不支持——需要复杂表单的插件自行渲染前端。

**`required` 语义**：`"required": ["api_key"]` 表示 UI 标红星 + 前端做非空检查；**后端不做强制校验**（secret 可能是「暂存草稿」状态，允许保存空值）。校验失败仅在前端提示，不阻止提交。

---

# 第 3 部分 · 官方插件目录与 GitHub 安装

这是 D1 的核心。目标：**插件本体不随包分发，但用户能在应用内看到官方推荐并一键安装。**

## 3.1 catalog 是什么

**catalog（官方插件清单）= 一张「推荐插件目录」，只含元数据，不含插件代码。**

它解决的是「用户怎么知道有哪些插件可装」。流程：

```
用户在 UI「官方目录」页签看到条目
        ↓  （条目来自 catalog）
  点「安装」
        ↓  （应用按条目里的 GitHub 地址去下载）
  插件代码落到 data/plugins/<id>/
        ↓
  校验、注册、提示重启
```

**catalog 与 manifest 的区别**（关键，别混淆）：

| | catalog | manifest |
|---|---|---|
| 数量 | 一份，列所有推荐插件 | 每个插件一份 |
| 位置 | `static/plugins/catalog.json`（或远端） | `data/plugins/<id>/manifest.json` |
| 含代码 | **否** | 否 |
| 权威性 | 只是「索引/快照」 | **权威**：安装后一切以它为准 |
| 谁维护 | 你（主程序作者） | 插件作者 |

**为什么要区分**：catalog 里写的 `version`/`permissions` 可能过时（你改了插件但没更新清单），也可能被篡改。所以**安装时必须以插件自带的 manifest 为准**，并强制 `manifest.id == catalog.id` 才能防止「清单说装 A、实际装成 B」的投毒。

### catalog 的托管方式（D11：方案 B）

**清单文件放在本仓库**，应用从本仓库的 GitHub raw 拉取。

| 项 | 值 |
|---|---|
| 仓库内路径 | `static/plugins/catalog.json`（随包分发，作为兜底） |
| 远端地址 | `https://raw.githubusercontent.com/Dadihu123/ST-Manager/main/static/plugins/catalog.json` |
| 拉取时机 | 用户打开「官方目录」页签时拉取（**不是**应用启动时）；带缓存 |
| 缓存 | 成功则缓存 6 小时；失败则用包内清单并显示「离线，显示内置目录」 |
| 用户控制 | 设置中可：① 覆盖远端 URL ② 关闭远端拉取（只用包内） |

**工作流**：你新增一个官方插件时，只需在仓库的 `static/plugins/catalog.json` 里加一条 → 用户打开目录页即可看到，**无需发新版 ST-Manager**。

**为什么不是「优先远端 + 隐式兜底」**：拉取由用户打开目录页这个显式动作触发，而非应用启动时静默外联。这样离线用户不会在启动时等超时，也符合项目「外部服务由用户显式触发」的既有风格（`discord_*`、`shimmerday_forum_cookie`，见 `core/config.py:152-160`）。

**安全约束（关键）**：catalog 中**不允许出现任意 URL**——`source.repo` 必须是 `owner/repo` 形式，由应用拼接成 GitHub 官方域名。这是防 SSRF 的核心（见 3.4）。远端 catalog 本身虽来自本仓库，但一旦你误写入外链，应用也只接受 `owner/repo`，不会去访问任意地址。

**新增配置项**（`core/config.py` 的 `DEFAULT_CONFIG`）：

| 键 | 默认值 | 说明 |
|---|---|---|
| `plugin_catalog_url` | `https://raw.githubusercontent.com/Dadihu123/ST-Manager/main/static/plugins/catalog.json` | 远端目录地址；留空则只用包内清单 |
| `plugin_catalog_remote_enabled` | `true` | 是否允许拉取远端目录 |
| `plugin_catalog_cache_hours` | `6` | 缓存时长 |

## 3.2 catalog 格式

```jsonc
{
  "schema_version": 1,
  "updated_at": "2026-09-22T00:00:00Z",
  "plugins": [
    {
      "id": "stm-ai-assistant",
      "name": "AI 角色卡分析助手",
      "description": "结合 LLM 为角色卡生成概览、标签建议、翻译与字段改写",
      "author": "",
      "icon": "https://raw.githubusercontent.com/<owner>/<repo>/main/icon.svg",
      "tags": ["ai", "tags", "translation"],

      // ---- 安装源（只允许 owner/repo，禁止任意 URL）----
      "source": {
        "type": "github",
        "repo": "<owner>/<repo>",            // 必须匹配 ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$
        "ref": "main",                       // 分支 / tag / commit
        "subdir": "",                        // monorepo 时的插件子目录
        "release_channel": "stable"          // stable | beta（可选，改用 Releases 下载）
      },

      // ---- 元数据快照（仅用于「未安装」时展示；安装后以 manifest 为准）----
      "version": "0.1.0",
      "api_version": 1,
      "min_app_version": "1.0.0",
      "permissions": ["cards.read", "cards.write", "tags.write", "secrets.read", "network.outbound"],
      "homepage": "https://github.com/<owner>/<repo>"
    }
  ]
}
```

**关键设计点**
- `catalog.json` **只含元数据**，且其中的 `version`/`api_version`/`permissions` 是**快照**，安装后一切以插件 manifest 为准。
- `source.repo` 强制 `owner/repo` 格式，**不接受任意 URL**（防 SSRF）。
- 安装前必须比对 `manifest.id == catalog.id`，否则拒绝（防供应链投毒）。
- `subdir` 支持 monorepo（一个仓库多个插件）。
- `release_channel: "stable"` 时优先从 GitHub Releases 的 asset 下载（可带校验和）；否则用源码归档。

## 3.2 安装流程

```
POST /api/plugins/catalog/install
  body: { id, ref?, subdir? }        # ref/subdir 可由用户覆盖（装特定版本）
  ↓
1. 从 catalog 查到 source
2. 构造下载 URL：
   - 源码归档: https://codeload.github.com/{repo}/zip/refs/heads/{ref}
              或 .../zip/{sha}（commit 更稳定）
   - Release:  https://api.github.com/repos/{repo}/releases/latest → asset URL
3. 下载到 data/temp/（限流：max 50MB，超时 60s，跟随重定向 ≤ 3 次）
4. 解压到 data/temp/plugin_install_<uuid>/
   ★ zip-slip 防护（见 3.4）
5. 定位插件根：{解压根}/{subdir}/manifest.json
6. 校验 manifest（id 匹配、api_version、min_app_version）
7. 原子替换：data/plugins/<id> ← 解压目录
   - 若已存在：先移到 data/system/trash/plugin_<id>_<ts>/
8. 写 plugin_install_log 表（见 6.6）
9. 返回 { success, id, version, restart_required: true }
```

**为什么需要重启**：后端插件注册 Python 模块、蓝图、作业处理器。Python **无法可靠卸载模块**（`sys.modules` 残留、蓝图无法从 Flask app 移除）。因此：

- **安装/更新/卸载后端插件后，提示用户重启应用**（现有 UI 已有 `POST /api/system_action` 的维护动作模式可参考）。
- **纯前端插件**（只有 `frontend/`）可以**免重启**：重新 `import()` 即可生效。
- 若插件既有后端又有前端，重启后端 + 前端热加载。

**[推断]** 这是本设计最不优雅但最诚实的部分。替代方案（进程内热重载）会引入 `importlib.reload` 的一系列陷阱（类身份变化、装饰器重复注册、蓝图路由冲突），不值得。

## 3.3 更新检查

```
POST /api/plugins/catalog/check_updates
  → { updates: [{ id, installed: "0.1.0", available: "0.2.0", channel }] }
```

**检查策略**（避免 GitHub API 限流）：
- 默认**不自动检查**（用户点击才查）。
- 若 `source.type == "github"`，用 `GET https://api.github.com/repos/{repo}/releases/latest` 取 tag；无 Release 则回退读远端 `manifest.json`（`raw.githubusercontent.com`）。
- **未认证的 GitHub API 限流 60 次/小时**（按 IP）。若用户在设置里填了 GitHub Token，可用 5000 次/小时——这个 Token 存 `secrets.json`（复用第 7 部分）。
- 结果缓存 24h（`data/system/plugins/_catalog_cache.json`）。

**版本比较**：用语义化版本比较，**只提示不自动更新**（D7 本地可信，但供应链风险仍需用户确认）。

## 3.4 解压安全（**最关键**）

从网络解压归档是**最高风险**的操作。必须逐项防护：

| 威胁 | 防护 |
|---|---|
| **zip-slip**（`../../` 路径穿越） | 逐个 entry 校验：`os.path.realpath(os.path.join(dest, name))` 必须以 `os.path.realpath(dest)` 为前缀。**不要**依赖 `zipfile.extractall()` |
| **绝对路径 entry** | 拒绝 `os.path.isabs(name)` 或含盘符（`os.path.splitdrive`） |
| **符号链接逃逸** | 检查 `external_attr >> 16` 的 `S_ISLNK` 位，**拒绝**归档中的符号链接 |
| **zip 炸弹** | 解压前累计 `file_size`，超过 200MB 或压缩比 > 100:1 则中止；限制 entry 数量 ≤ 5000 |
| **磁盘写满** | 下载前检查可用空间（`shutil.disk_usage`）≥ 3× 预估大小 |
| **超时** | `requests.get(..., timeout=(10, 60), stream=True)`；总时长上限 300s |
| **重定向到内网（SSRF）** | **catalog 是本地可信文件**，URL 由它构造，不接受用户任意 URL。用户可覆盖 `ref`/`subdir`，但必须正则校验（`^[A-Za-z0-9._/-]{1,200}$`，且不含 `..`） |
| **manifest 与 catalog 不符** | 强制 `manifest.id == catalog.id` |

**注意**：本仓库**没有**现成的 zip 解压代码（`grep zipfile core/` → 0 命中）。这是全新代码，必须配专门的测试（见第 13 部分）。

## 3.5 手动安装（离线兜底）

```
POST /api/plugins/install_upload     # multipart zip
```

同样的解压校验。用于：
- 内网/无 GitHub 访问
- 开发者测试本地插件
- catalog 中没有的第三方插件

## 3.6 插件生命周期：四个独立操作（D9）

按 D9，插件管理暴露**四个互不重叠的操作**，语义边界必须清晰：

| 操作 | 语义 | 磁盘影响 | 生效方式 |
|---|---|---|---|
| **安装** | 把插件代码放到 `data/plugins/<id>/` | 新增目录 | **需重启**（后端）/ 免重启（纯前端） |
| **卸载** | 从磁盘移除插件 | 目录移入回收站；**默认清理** `ui_data._plugins_v1.<id>`（D10） | **需重启** |
| **禁用** | 保留代码，但**完全不加载** | 无 | **需重启**（后端）/ 免重启（纯前端） |
| **启用** | 恢复加载 | 无 | **需重启**（后端）/ 免重启（纯前端） |

**「禁用」的精确定义（D9）**：不注册蓝图、不注册作业处理器、不派发 hook、不加载前端 bundle。**不存在**「加载了但路由被禁用」的中间态。

**状态存储**：`ui_data._plugins_v1.<id>.enabled`（`true`/`false`，默认 `true`）。

**「禁用」的生效时机（关键，必须明确）**：`enabled` 标志只在 `create_app()` → `registry.load_all()` 时读取**一次**（进程启动期）。禁用操作只写 `ui_data`、**不动运行时状态**——已注册的蓝图、已运行的作业、已订阅的 hook 继续存在直到重启。因此：

```
POST /api/plugins/<id>/disable
  ├─ ui_data._plugins_v1.<id>.enabled = false
  ├─ 返回 { success: true, restart_required: true }
  └─ UI 显示横幅「已标记禁用，重启后生效」

应用重启
  └─ load_all() 发现 enabled=false → 跳过 register（不建蓝图/作业/hook）
```

**运行中作业的处置**：禁用/卸载前**必须**先取消该插件的 `queued`/`running`/`paused` 作业（协作式取消，超时后 `UPDATE status='cancelled'`）。否则作业在禁用后仍在后台跑。

**为什么禁用/启用也要重启**（后端插件）：Python 无法可靠卸载已 import 的模块（`sys.modules` 残留、蓝图无法从 Flask app 移除）。禁用后重新启用需要重新执行 `register()`，而重复注册会导致路由/作业类型冲突。重启是最可靠的方案。

**纯前端插件例外**：只有 `frontend/` 没有 `backend/` 的插件，禁用/启用可立即生效（移除 DOM、取消事件订阅、重新 `import()`）。UI 应区分提示——`GET /api/plugins/list` 响应里需带 `backend: true/false` 供前端判断是否显示「需重启」。

### 卸载实现

```
POST /api/plugins/uninstall
  body: { id, keep_data?: bool }      # keep_data 默认 false（D10）
```

步骤：
1. 校验 `id` 存在且合法
2. 停止该插件的运行中作业（协作式取消；超时后强制标记 `cancelled`）
3. 插件目录移到 `data/system/trash/plugin_<id>_<ts>/`（**不直接删**，对齐 `docs/DEVELOPMENT.md:122-124` 的回收站约定）
4. **默认**清理 `ui_data._plugins_v1.<id>`（D10）；`keep_data=true` 时保留
5. **默认**清理 `secrets.json` 中该插件的密钥段（安全默认：卸载即清密钥）
6. 写入 `plugin_install_log` 表（见 6.6）
7. 提示重启

**密钥清理说明**：卸载时默认删除密钥，避免「卸载了但密钥还留在磁盘上」。若用户想保留（例如重装同一插件），用 `keep_data=true` 同时保留配置与密钥。

---

# 第 4 部分 · 后端插件运行时

## 4.1 模块结构

```
core/plugins/
├─ __init__.py        # 公开导出：registry, hooks, get_api
├─ manifest.py        # manifest 解析与校验
├─ registry.py        # 发现 / 加载 / 启用禁用 / 失败隔离
├─ api.py             # PluginAPI 门面
├─ hooks.py           # HookBus（替换 core/event_bus.py）
├─ jobs.py            # 作业系统（worker + 状态机）
├─ job_store.py       # plugin_jobs / plugin_job_items 表
├─ secrets.py         # secrets.json 读写
├─ installer.py       # GitHub 下载 / 解压 / 校验 / 安装
├─ catalog.py         # 远端目录拉取 + 包内兜底 + 缓存
├─ assets.py          # 插件静态资源路由
├─ errors.py          # 异常类型
└─ routes.py          # 插件管理 API 蓝图
```

## 4.2 加载时机

**后端插件**：`core/__init__.py:create_app()` 内，蓝图注册之后（`:76`）、`init_auth(app)` 之前（`:79`）。

```python
# core/__init__.py（设计草案）
def create_app():
    ...
    app.register_blueprint(views.bp)          # :76

    # === 插件加载（新增）===
    from core.plugins import registry
    registry.load_all(app)                    # 内部逐插件 try/except

    init_auth(app)                            # :79
    return app
```

**为什么在这个位置**
- 在 `init_auth` 之前：插件蓝图自动受认证保护（`core/auth.py:913` 的 `before_request` 对 `/api/*` 生效）。插件**不应**能绕过认证。
- 在核心蓝图之后：插件路由注册在后，Flask 路由匹配按注册顺序，可避免插件覆盖核心路由；但仍需显式冲突检查（见 4.4）。

**插件后台线程**：`init_services()` 末尾（`core/__init__.py:147` 之后，`:150` 之前），与 `start_monitor_scheduler()` 并列。作业 worker 复用 `start_index_job_worker` 的幂等模式（`core/services/index_job_worker.py:256-263`）。

## 4.3 插件模块加载策略（**必须先冻结**）

`manifest.backend.entry`（如 `"backend"`）是**相对插件根**的包路径，插件代码位于 `data/plugins/<id>/backend/`，不在 `sys.path` 上。**必须用 `importlib.util.spec_from_file_location` 显式构造模块**，而非 `sys.path` 注入——否则两个插件都带 `backend/__init__.py` 时会发生模块名冲突。

```python
# core/plugins/registry.py（设计草案）
import importlib.util
import sys

MODULE_PREFIX = "st_plugin_"

def _load_backend_module(manifest, plugin_dir):
    """把 data/plugins/<id>/backend/ 加载为独立模块 st_plugin_<id>.backend"""
    pkg_path = plugin_dir / manifest.backend_entry          # e.g. backend/
    init_py = pkg_path / "__init__.py"
    if not init_py.is_file():
        raise PluginLoadError(f"{init_py} 不存在")

    module_name = f"{MODULE_PREFIX}{manifest.id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        init_py,
        submodule_search_locations=[str(pkg_path)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module          # 先注册再 exec，支持包内相对导入
    spec.loader.exec_module(module)
    return module
```

**约束（插件开发者必读）**
- 插件内部 import 自己的子模块**必须用相对导入**（`from . import service`、`from .jobs import handler`）。
- **禁止** `from backend import xxx` 这类绝对导入——该名称在 `sys.path` 上不存在。
- **禁止**在插件顶层目录放与 `core` 同名的模块（如 `core/utils.py`），`spec_from_file_location` 不会阻止 `import core` 命中主程序——但插件**不应**依赖主程序的内部模块，一切能力走 `PluginAPI`。

## 4.4 失败隔离

```python
def load_all(app):
    for plugin_dir in discover():
        try:
            manifest = Manifest.load(plugin_dir)
            if manifest.api_version not in SUPPORTED_API_VERSIONS:
                _mark_failed(manifest.id, f"api_version {manifest.api_version} 不受支持")
                continue
            module = _load_backend_module(manifest, plugin_dir)   # 见 4.3
            api = PluginAPI(manifest, app)
            module.register(api)              # 插件唯一入口
            _mark_loaded(manifest.id, api)
        except Exception:
            logger.exception("插件 %s 加载失败，已跳过", plugin_dir.name)
            _mark_failed(plugin_dir.name, traceback.format_exc())
```

**硬性要求**
- 单个插件失败**绝不允许**中断 `create_app()`。否则一个坏插件会让整个应用无法启动。
- 失败信息持久化（`ui_data._plugins_v1.<id>.load_error`），供 UI 展示。
- 插件抛出的异常在 hook 派发与作业执行时也要隔离（见第 5、6 部分）。

## 4.5 路由注册与冲突检查

```python
api.blueprint(bp)   # 自动加前缀 /api/plugins/<id>（立即注册）
api.route('/ping', ['GET'])   # 装饰器：先收集到默认蓝图，register() 返回后统一注册
```

- 前缀**强制**由主程序拼接，插件不得自定义。
- 注册前检查 `app.url_map` 是否已存在同 `rule + method`，冲突则拒绝并记录。
- 插件路由同样受 `init_auth` 保护（因为注册在 `init_auth` 之前，`before_request` 是 app 级钩子）。

**注册时机（实现约束）**：Flask 禁止在蓝图注册之后继续 `add_url_rule`。因此
`api.route()` 只把规则收集到插件的**默认蓝图**上，由 `registry._instantiate_plugin()`
在 `register(api)` 返回后调用 `api.finalize()` 统一注册；`api.blueprint(bp)`
是显式注册语义，调用方需在调用前把该蓝图的规则声明完。

## 4.6 PluginAPI 门面（概览）

完整签名见第 10 部分。设计原则：

1. **门面方法内部处理所有核心约定**——插件作者不需要知道 `suppress_fs_events`、`request_card_locks`、`update_ui_data` 的存在。
2. **所有核心能力复用现有服务层**，不重复实现。
3. **`permissions` 只做记录与 UI 展示**（D7），不做执行门控。
4. **`migrate()` 强制表名前缀** `plugin_<id>_`，防止污染核心 schema。

---

# 第 5 部分 · Hook 总线

## 5.1 替换空壳

`core/event_bus.py` 当前是 15 行空壳（`subscribe`/`emit` 全是 `pass`），全仓零引用。**直接删除**，由 `core/plugins/hooks.py` 取代。

## 5.2 事件清单（建议冻结）

**后端事件**（需在核心代码插入 `hooks.emit(...)`）：

| 事件 | 插入点 | payload |
|---|---|---|
| `app.ready` | `init_services()` 末尾 | `{}` |
| `card.created` | 导入提交后 | `{card_ids: [...]}` |
| `card.updated` | `api_update_card` 的 `return jsonify(...)` **之前**（`cards.py:2180` 附近，勿放 return 后） | `{card_id, changed_fields}` |
| `card.deleted` | `api_delete_cards` 后 | `{card_ids}` |
| `card.moved` | `api_move_card` 后 | `{moves}` |
| `tag.applied` | `api_batch_tags` 后（`cards.py:4669` 附近） | `{card_ids, added, removed}` |
| `tag.deleted` | `api_delete_tags` 后 | `{tags, card_ids}` |
| `worldbook.saved` | `api_save_world_info` 后（`world_info.py:2333`） | `{source_type, file_path, card_id}` |
| `worldbook.entry_changed` | 条目历史记账后 | `{scope_key, entry_uids}`，其中 `scope_key` 定义为 `{source_type}:{card_id 或相对 file_path}`（如 `card:abc123` / `standalone:lorebooks/x.json`），与 `read_worldbook`/`write_worldbook` 的 `source` 参数结构对齐 |
| `scan.completed` | `_perform_scan_logic` 末尾 | `{scanned, elapsed}` |
| `index.job_done` | `_mark_job_status` **内部**（终态统一触发，不漏失败/取消） | `{job_type, entity_id, status}` |

**前端事件**：复用现有 `window` CustomEvent 总线（172 处 dispatch），**零改动**。新增 `plugin:*` 命名空间用于插件间通信。

## 5.3 派发语义

```python
def emit(event, payload):
    for handler in _handlers.get(event, ()):
        try:
            start = time.monotonic()
            handler(payload)
            elapsed = time.monotonic() - start
            if elapsed > SLOW_HANDLER_THRESHOLD:   # 默认 0.5s
                logger.warning("插件 %s 的 %s 处理器耗时 %.2fs", handler.plugin_id, event, elapsed)
        except Exception:
            logger.exception("插件 %s 的 %s 处理器异常，已忽略", handler.plugin_id, event)
```

**关键决策**
- **同步派发**：简单、可预测。插件若需长任务，应自己 `api.submit_job()`。
- **异常吞掉**：插件异常不得影响核心流程（例如 `card.updated` 的处理器崩溃不能导致卡片保存失败）。
- **耗时告警**：超过 0.5s 记 warning，帮助用户发现拖慢应用的插件。
- **不提供** `emit_and_collect`（返回值聚合）——会引入插件间的隐式依赖与顺序问题。

---

# 第 6 部分 · 通用作业系统与 SSE

## 6.1 数据模型

```sql
-- core/plugins/job_store.py
CREATE TABLE IF NOT EXISTS plugin_jobs (
    run_id        TEXT PRIMARY KEY,
    plugin_id     TEXT NOT NULL,
    job_type      TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
                  -- queued | running | paused | completed | failed | cancelled | aborted
    payload_json  TEXT NOT NULL DEFAULT '{}',
    total         INTEGER NOT NULL DEFAULT 0,
    completed     INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    skipped       INTEGER NOT NULL DEFAULT 0,
    current_item  TEXT DEFAULT '',
    message       TEXT DEFAULT '',
    summary_json  TEXT DEFAULT '{}',
    error         TEXT DEFAULT '',
    created_at    REAL NOT NULL,
    started_at    REAL DEFAULT 0,
    finished_at   REAL DEFAULT 0,
    claim_token   TEXT DEFAULT ''     -- 认领令牌：独立列，不复用 error（见 6.3）
);
CREATE INDEX IF NOT EXISTS idx_plugin_jobs_status  ON plugin_jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_plugin_jobs_plugin  ON plugin_jobs(plugin_id, created_at DESC);

CREATE TABLE IF NOT EXISTS plugin_job_items (
    run_id      TEXT NOT NULL,
    item_key    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
                -- pending | running | done | failed | skipped | awaiting_review
    attempt     INTEGER NOT NULL DEFAULT 0,
    seq         INTEGER NOT NULL DEFAULT 0,   -- 作业内自增，SSE 的 Last-Event-ID 用它
    payload_json TEXT DEFAULT '{}',          -- 单项参数（如该卡的分析选项）
    result_json TEXT DEFAULT '{}',
    error       TEXT DEFAULT '',
    created_at  REAL NOT NULL,               -- 提交顺序的稳定排序键
    updated_at  REAL NOT NULL,
    PRIMARY KEY (run_id, item_key)
);
CREATE INDEX IF NOT EXISTS idx_plugin_job_items_status ON plugin_job_items(run_id, status, seq);
CREATE INDEX IF NOT EXISTS idx_plugin_job_items_order  ON plugin_job_items(run_id, seq);
```

**为什么需要 `plugin_job_items`**
- **断点续跑**：AI 批量作业中断后，只重跑 `pending`/`failed`，避免重复消耗 token。`created_at`/`seq` 保证续跑顺序与提交顺序一致。
- **逐条审批**（D6）：`awaiting_review` 状态承载「已生成建议，等待用户确认」。
- **失败定位**：精确到条目，而非「整个作业失败」。
- **单项参数**：`payload_json` 存该 item 的独立参数（如「此卡用模型 X」），`submit_job` 时按 `items` 顺序写入，`seq` 即列表索引。

**`payload_json` / `result_json` 大小约束**：建议单项 ≤ 64KB，超过则截断并在 `result_json` 内标 `{"_truncated": true}`。表级用 `CHECK (length(result_json) <= 262144)` 兜底，防止插件误存 base64 撑爆主库。

**状态机**

```
queued ──► running ──┬──► completed
   │           │     ├──► failed
   │           │     ├──► cancelled   (用户取消，协作式)
   │           └──────► paused ──► running
   └──────────────────────► aborted   (崩溃恢复：启动时把 running/queued 置为此)
```

`paused` 用于 D6 的审批流：作业跑到需要人工确认的点时暂停，用户处理后续跑。

## 6.2 作业处理器契约

```python
def handler(ctx: JobContext) -> None:
    """
    ctx.run_id       : str
    ctx.plugin_id    : str
    ctx.payload      : dict           # 创建时的 payload
    ctx.items        : list[JobItem]  # 待处理项（已按 status 过滤，按 seq 排序）
    ctx.should_cancel() -> bool       # 协作式取消检查
    ctx.report(item_key, *, status, result=None, error='') -> None
    ctx.set_message(text) -> None
    ctx.set_total(n) -> None
    ctx.save_state(dict) / ctx.load_state() -> dict   # 断点续跑用
    """
```

`JobItem` 结构：`{key, payload, seq}`——`key` 是 `item_key`，`payload` 来自 `plugin_job_items.payload_json`，`seq` 是提交顺序。

## 6.3 Worker

**蓝本**：`core/services/source_update_monitor_service.py:1192-1221`（`_run_monitor_run`）。

```python
# core/plugins/jobs.py（设计草案）
def worker_loop():
    while True:
        _wakeup.wait(30)          # 照抄 index_job_worker.py:166 的 30s 兜底
        _wakeup.clear()
        rows = _claim_runnable_jobs(limit=4)
        for row in rows:
            try:
                _run_job(row)
            except Exception:
                logger.exception(...)
                _finish_job(row.run_id, 'failed', error=...)
```

**必须补齐 `index_job_worker` 缺的两件事**（`core/services/index_job_worker.py:163-253` 无取消、无进度）：

| 能力 | 实现 | 参照 |
|---|---|---|
| **协作式取消** | 每处理一个 item 前 `_check_status(run_id)`，非 `running` 即退出 | `source_update_monitor_service.py:1196-1198` |
| **进度落库** | 每 item 完成更新 `completed`/`current_item` | `:1014-1044` |
| **崩溃恢复** | 启动时 `UPDATE plugin_jobs SET status='aborted' WHERE status IN ('running','queued')` | `source_update_monitor_store.py:290-300` |
| **并发控制** | 每个作业内按插件 config 的 `concurrency` 用 `ThreadPoolExecutor`；**每线程自建 SQLite 连接** | `index_job_worker.py:32-39` |
| **认领去重** | 用 `claim_token` 写入独立列（**不要**像 `index_job_worker.py:97` 那样复用 `error_msg`——那是权宜之计） | — |
| **单插件并发上限** | `_claim_runnable_jobs` 里 `GROUP BY plugin_id` 各取前 2 个（`MAX_JOBS_PER_PLUGIN=2`），防止插件 A 提交 100 个作业饿死插件 B | — |
| **认领原子性** | 用 `UPDATE ... WHERE run_id IN (SELECT ... LIMIT ?)` + `claim_token` 二次过滤（同 `index_job_worker.py:85-107` 模式），保证多 worker 不重复认领 | `index_job_worker.py:85-107` |

**并发与 SQLite**：`sqlite3` 连接不能跨线程共享。每个 worker 线程必须 `sqlite3.connect(DEFAULT_DB_PATH, timeout=60)` 自建连接，并设 `PRAGMA journal_mode=WAL`（参照 `index_job_worker.py:33-36`）。

**同插件串行化**（可选）：若插件不希望同一时刻跑多个作业，可在创建时检查 `WHERE plugin_id=? AND status IN ('queued','running','paused')`，有则返回 `already_running`（参照 `source_update_monitor_service.py:946-953` 的 `BEGIN IMMEDIATE` 模式）。

**payload 不得含密钥**：`submit_job(payload)` 的 `payload_json` 会明文落库。若作业需要 API key，payload 里只存 `{"secret_ref": "api_key"}`，worker 运行时由 `ctx.api.get_secret("api_key")` 解析，**禁止**把密钥值写进 `payload_json`（`plugin_jobs` 表对插件只读，但防止意外导出/备份泄漏）。

## 6.4 SSE 设计

### 6.4.1 端点

```
GET /api/plugins/<plugin_id>/jobs/<run_id>/events
    → Content-Type: text/event-stream
```

### 6.4.2 事件协议

```
id: 0
event: snapshot
data: {"run_id":"...","status":"running","total":42,"completed":17,"failed":1,"current_item":"卡片A","message":"正在分析第 2 批"}

id: 1
event: item
data: {"item_key":"卡片A","status":"done","result":{"summary":"...","tags":["战斗"]}}

id: 2
event: item
data: {"item_key":"卡片B","status":"failed","error":"API 超时"}

id: 3
event: log
data: {"level":"info","message":"已切换到模型 deepseek-chat"}

id: 4
event: done
data: {"status":"completed","completed":42,"failed":0,"summary":{"prompt_tokens":61203}}

: heartbeat
```

- **`id: <seq>`**：每个事件块**必须**带 `id` 字段，值为 `plugin_job_events.seq`（作业内自增整数，见下）。浏览器 `EventSource` 自动重连时会在 `Last-Event-ID` 请求头里带上它，服务端据此续传。
- `snapshot`：`seq=0`，连接建立时立即推一次全量状态（避免前端先轮询）。
- `item`：逐项结果。**这是 SSE 相对轮询的核心价值**——用户能实时看到每张卡的结果。
- `log`：可选的人类可读进度。
- `done`：终态（`seq` 为该作业最大 seq），推送后服务端关闭连接。
- `: heartbeat`：每 15s 一条注释行，**不带 `id`**（不会覆盖客户端的 `Last-Event-ID`），防止代理/浏览器超时断连。

**`seq` 的生成机制**：`plugin_job_events.seq` 是**作业内自增**（`PRIMARY KEY (run_id, seq)`），**不是**全表自增。写入时用：
```sql
INSERT INTO plugin_job_events (run_id, seq, type, data_json, created_at)
VALUES (?, COALESCE((SELECT MAX(seq) FROM plugin_job_events WHERE run_id=?), 0) + 1, ?, ?, ?)
```
单 worker 写串行无竞争；多 SSE 连接只读不写，无需锁。`snapshot` 固定 `seq=0`，由 SSE 端点合成而非写表——避免「每次连接都插入一条 snapshot」污染事件流。

### 6.4.3 服务端实现要点

```python
# core/plugins/jobs.py（设计草案）
def stream_events(run_id):
    def _sse(event, data, seq=None):
        # SSE 帧格式：id: <seq>\nevent: <type>\ndata: <json>\n\n
        lines = []
        if seq is not None:
            lines.append(f"id: {seq}")
        lines.append(f"event: {event}")
        for line in json.dumps(data, ensure_ascii=False).split('\n'):
            lines.append(f"data: {line}")
        return '\n'.join(lines) + '\n\n'

    def generate():
        last_seq = _last_event_id()           # 从 Last-Event-ID 续传，默认 0
        yield _sse('snapshot', _snapshot(run_id), seq=0)
        while True:
            if _client_gone():          # 见下
                break
            events = _poll_events(run_id, after_seq=last_seq)
            for ev in events:
                last_seq = ev['seq']
                yield _sse(ev['type'], ev['data'], seq=ev['seq'])
            if _is_terminal(run_id) and not events:
                yield _sse('done', _summary(run_id), seq=last_seq + 1)
                break
            yield ': heartbeat\n\n'
            time.sleep(1.0)
    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',       # 关闭 nginx 缓冲
        'Connection': 'keep-alive',
    })

def _last_event_id():
    """从请求头读 Last-Event-ID，转为 int；无则 0"""
    try:
        return int(request.headers.get('Last-Event-ID', '0'))
    except ValueError:
        return 0
```

**关键技术点**

| 点 | 做法 | 理由 |
|---|---|---|
| **事件存储** | 新增 `plugin_job_events(run_id, seq, type, data_json, created_at)` 表；`seq` 为**作业内自增** | SSE 是「读事件流」，必须能按 seq 增量读；不能只靠内存队列（刷新页面/多标签页会丢事件） |
| **`id:` 字段** | 每个 SSE 帧都带 `id: <seq>` | 浏览器 `EventSource` 自动重连时靠它恢复 `Last-Event-ID` |
| **断线续传** | 读 `Last-Event-ID` 请求头（`request.headers.get('Last-Event-ID')`），从该 seq **之后**重放 | 浏览器 `EventSource` 自动重连时会带上此头 |
| **snapshot 不落表** | `seq=0` 的 snapshot 由端点现场合成，不写 `plugin_job_events` | 否则每次连接都插入一条 snapshot 会污染事件流 |
| **客户端断开检测** | `yield` 时捕获 `GeneratorExit`；或检查 `request.environ.get('werkzeug.socket')` | Werkzeug 在客户端断开时会在下次 write 抛异常，`finally` 中清理 |
| **线程占用** | 每个 SSE 连接占一个 werkzeug 线程 | Flask 默认 `threaded=True`（已确认），但**连接数需设上限**（见下） |
| **连接上限** | 每 run_id 最多 4 个并发 SSE；全局最多 32 个 | 防止恶意/异常客户端耗尽线程 |
| **心跳** | 15s 一次 `: heartbeat` | 穿透代理与浏览器空闲超时 |
| **认证** | 复用 `init_auth` 的 `before_request`（路由在 `/api/` 下） | 无需额外处理 |

**事件表**：见 6.5。

### 6.4.4 轮询降级

`EventSource` 在以下情况会失败：企业代理拦截、HTTP/1.0、浏览器策略。前端必须降级：

```js
// 设计草案
async function subscribeJob(runId, handlers) {
  if (typeof EventSource === 'function') {
    const es = new EventSource(`/api/plugins/${pid}/jobs/${runId}/events`);
    let opened = false;
    es.onopen = () => { opened = true; };
    es.onmessage = (e) => dispatch(JSON.parse(e.data));
    es.onerror = () => {
      es.close();
      if (!opened) startPolling(runId, handlers);   // 从未连上 → 直接降级
      // 已连上过 → 让 EventSource 自动重连（浏览器内置退避）
    };
    return () => es.close();
  }
  return startPolling(runId, handlers);
}
```

轮询用现有的 4s 间隔模式（参照 `static/js/components/sourceUpdateMonitor.js:124-129`）。

## 6.5 作业事件保留策略（D12：按作业条数）

### 为什么需要这张表

作业运行中会产生一条条**增量记录**：第 1 张卡完成、第 2 张失败、切换模型…这些记录要落表，原因有两个：

1. **SSE 推送**：服务端需要按 seq 增量读取并推送。
2. **刷新后回看**：用户刷新页面、或第二天打开应用，仍能看到历史作业的逐条结果。

不落表只靠内存队列的话，刷新页面就丢了。

### 表结构

```sql
CREATE TABLE IF NOT EXISTS plugin_job_events (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,          -- 作业内自增，SSE 的 Last-Event-ID 用它
    type       TEXT NOT NULL,             -- snapshot | item | log | done
    data_json  TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_plugin_job_events_run ON plugin_job_events(run_id, seq);
```

### 清理策略（D12：按作业条数）

**决策**：保留最近 N 个已终结作业的事件，更早的整作业删除。

| 参数 | 值 | 常量名 |
|---|---|---|
| 已完成作业保留数 | **100** | `PLUGIN_JOB_DONE_RETENTION` |
| 失败作业保留数 | **50** | `PLUGIN_JOB_FAILED_RETENTION` |

与 `index_job_worker.py:28-29` 的现有约定一致（那里是 `INDEX_JOB_DONE_RETENTION=200` / `INDEX_JOB_FAILED_RETENTION=50`；插件作业量级更小，done 取 100）。

**为什么不用「按时间」**：一天跑 100 个作业会撑很大，而低频用户可能几天后什么都看不到；按条数对两种用户都更均衡，且不需要引入时间参数配置。

### 实现位置

在 `_finish_job()`（作业进入终态时）调用 `_prune_job_events()`，按 `finished_at DESC` 保留最近 N 个作业的事件，其余 `DELETE`。这与 `index_job_worker.py:125-151` 的 `_prune_terminal_jobs` 完全同构，可直接照抄该函数的 SQL 结构：

```sql
-- 保留最近 N 个终态作业，删除其余（照抄 index_job_worker.py:136-151 的结构）
DELETE FROM plugin_job_events
WHERE run_id NOT IN (
    SELECT run_id FROM (
        SELECT run_id FROM plugin_jobs
        WHERE status = ?
        ORDER BY finished_at DESC, created_at DESC
        LIMIT ?
    )
);
```

**注意**：`plugin_jobs` / `plugin_job_items` / `plugin_job_events` 三张表必须**用同一个保留决策**（同一个 `_prune_terminal_jobs()` 事务内一并清理），避免出现「作业记录还在但事件已删」或反之的不一致。

**运行中作业不清理**：只对终态（`completed` / `failed` / `cancelled` / `aborted`）作业计数，`queued` / `running` / `paused` 的作业永不清理。

## 6.6 安装/卸载审计表（替代 `_install_log.json`）

```sql
CREATE TABLE IF NOT EXISTS plugin_install_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plugin_id   TEXT NOT NULL,
    action      TEXT NOT NULL,         -- install | update | uninstall | enable | disable
    version     TEXT DEFAULT '',       -- 操作时的版本（卸载时可为空）
    source      TEXT DEFAULT '',       -- catalog:<repo> | upload | local
    detail_json TEXT DEFAULT '{}',     -- manifest 快照、keep_data、错误信息等
    success     INTEGER NOT NULL DEFAULT 1,
    created_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plugin_install_log ON plugin_install_log(plugin_id, created_at DESC);
```

**为什么不用 JSON 文件**：并发安装、原子性、无限增长都需要自己处理。并入主库复用 WAL + `execute_with_retry`，与 `plugin_jobs` 同库同连接管理。保留所有记录（不随作业清理），写入方在 `installer.py` / `routes.py` 统一调用 `_log_plugin_action()`。

---

# 第 7 部分 · 密钥存储

## 7.1 现状问题（必须避免重演）

| 问题 | 证据 |
|---|---|
| `config.json` 是**明文** JSON | `core/config.py:269-271` `write_config_file` 直接 `json.dump` |
| `GET /api/get_settings` **全量下发前端** | `core/api/v1/system.py:393-428` 返回整个 config，含 `st_basic_password`、`discord_bot_token`、`shimmerday_forum_cookie` |
| 无任何脱敏层 | `grep sanitize` 在 config 相关路径无命中 |

**因此 AI API Key 绝不能走 `config.json`。**

## 7.2 设计

**文件**：`data/system/secrets.json`

```jsonc
{
  "schema_version": 1,
  "plugins": {
    "stm-ai-assistant": {
      "api_key":  { "value": "sk-...", "updated_at": 1758500000 },
      "base_url": { "value": "https://api.openai.com/v1", "updated_at": 1758500000 }
    }
  },
  "app": {
    "github_token": { "value": "ghp_...", "updated_at": 1758500000 }
  }
}
```

- 按 `plugin_id` 命名空间隔离，插件只能读写自己的。
- `app` 段承载主程序自身的敏感项（如 GitHub Token，用于目录更新检查）；读写走 `secrets.get_app_secret()` / `set_app_secret()`，环境变量 `STM_APP_<KEY>` 优先级最高。
- 每项记录 `updated_at` 用于审计与 UI 展示。

## 7.3 兼容策略（D2 的「注意兼容」）

「兼容」有三层含义，逐层给出方案：

### 7.3.1 不破坏现有 `config.json` 密钥（**最重要**）

**决策**：**不迁移**现有 `config.json` 中的密钥。

理由：
- 迁移需要读旧值 → 写新文件 → 从 config 删除。中途失败会导致密钥丢失。
- 现有部署（Docker、桌面版）可能依赖 `config.json` 的当前形态。
- `st_basic_password` 等由 `normalize_config`（`core/config.py:211-250`）做双向映射，迁移会打断该逻辑。

**做法**：`secrets.json` 与 `config.json` **并存**。
- 主程序自身密钥继续留在 `config.json`（行为完全不变）。
- **仅插件密钥**写入 `secrets.json`。
- 提供只读适配层 `get_effective_secret(plugin_id, key)`：先查 `secrets.json`，未命中则**不**回退到 `config.json`（避免插件误读主程序密钥）。

### 7.3.2 文件缺失 / 损坏的健壮性

对齐 `ui_store.py` 的成熟模式：

| 场景 | 行为 |
|---|---|
| 文件不存在 | 返回 `{}`（首次运行正常） |
| JSON 解析失败 | 备份为 `secrets.json.corrupted.<ts>`，返回 `{}`（**不抛异常**——密钥丢失不应阻塞启动） |
| 读取 IO 错误（占用/权限） | 重试 4 次（`0.05s` 递增退避，参照 `ui_store.py:23-24`），仍失败则**拒绝写入**（防止覆盖），读取返回 `{}` 并记 error |
| 写入 | 原子写：同目录 `mkstemp` → `fsync` → `os.replace`（参照 `ui_store.py:1633-1664`） |
| 备份轮转 | 保留 3 代 `.bak` / `.bak.1` / `.bak.2`（参照 `ui_store.py:20`、`:1561-1564`） |

**与 `ui_store` 的关键差异**：`ui_store` 在读失败时**抛 `UiDataLoadError`**（因为静默返回空数据会导致覆盖）。`secrets.json` **不应**抛异常——密钥读不到最多是功能不可用，不该让整个应用起不来。但**写入**必须在读失败后拒绝（防止把仅存的有效密钥覆盖掉）。

### 7.3.3 环境变量优先级

现有模式：`core/auth.py:513-530` 支持 `STM_AUTH_USER` / `STM_AUTH_PASS` 覆盖 `config.json`。**沿用该模式**：

```
优先级（高 → 低）：
1. 环境变量  STM_PLUGIN_<PLUGIN_ID>_<KEY>   （规范化：大写、非字母数字转 _）
2. secrets.json
3. secret_schema 的 default（仅非 secret 项）
```

环境变量适合 Docker/CI 场景（不落盘）。文档需说明命名规则。

## 7.4 文件权限

| 平台 | 措施 |
|---|---|
| POSIX | `os.chmod(path, 0o600)`；目录 `0o700` |
| Windows | `os.chmod` 语义有限；尝试用 `icacls` 限制为当前用户 **[可选]**；至少在 UI 中提示「密钥以明文存储在本机」 |

**诚实说明**：这是**明文存储**（无加密）。加密需要密钥管理（密钥存哪？），对本机单用户工具收益有限。文档必须明确告知用户，而不是假装安全。

## 7.5 HTTP API

```
GET  /api/plugins/<id>/secrets
  → { success: true, secrets: {
        "api_key":  { "set": true,  "hint": "sk-…abcd", "updated_at": 1758500000 },
        "base_url": { "set": true,  "value": "https://api.openai.com/v1" }   // 非 secret 项返回明文
      } }

POST /api/plugins/<id>/secrets
  body: { "api_key": "sk-new..." }       // null 或 "" 表示清除
  → { success: true }

DELETE /api/plugins/<id>/secrets/<key>
  → { success: true }
```

**硬性规则**
- **`secret: true` 的项永不返回明文**，只返回 `{set, hint}`。`hint` = 前 3 + 后 4 字符。
- 非 secret 项（如 `base_url`）可返回明文。
- 服务端日志**必须脱敏**：在 `secrets.py` 内统一处理，任何 logger 调用前过滤。
- 密钥值不得出现在任何错误响应中（API 调用失败时，错误信息里若含 URL，需剥离 query）。

---

# 第 8 部分 · 前端插件运行时

## 8.1 加载

**新增**：`static/js/pluginHost.js`，在 `static/js/app.js:85`（`initPasteImportHandler()` 之后）调用 `PluginHost.init()`。

**关键：必须复用 `app.js:90-96` 的 Alpine 双分支**——`app.js` 是 `type="module"`（天然 defer），`alpine.js` 是 `defer`，加载顺序存在竞态：

```js
// static/js/app.js（现有代码，必须遵循）
if (window.Alpine) {
  registerComponents();
} else {
  document.addEventListener("alpine:init", registerComponents);
}
```

## 8.2 插件加载流程

```
1. GET /api/plugins/list  → 已启用插件列表
2. 对每个插件：
   a. 注入 <link> 样式（frontend.styles）
   b. await import(`/api/plugins/<id>/assets/<frontend.entry>`)
   c. 若导出 activate，则 await activate(api)
   d. 失败则记录，不影响其他插件
```

**懒加载**：默认在首屏渲染完成后（`requestIdleCallback` 或 `setTimeout(0)`）再加载插件，避免拖慢首屏。

## 8.3 PluginAPI（前端）

完整签名见第 10 部分。核心能力：

| 能力 | 实现方式 |
|---|---|
| 状态 | `api.state`（`Alpine.reactive({})`）+ `api.store`（现有 `Alpine.store('global')`） |
| 事件 | `api.on/off/emit` → `window` CustomEvent 总线 |
| 通知 | `api.toast()` → `store.showToast()`（`state.js:1676`） |
| 进度 | `api.progress.*` → `store.startBatchProgress()` 等（`state.js:1698-1741`） |
| 打开 UI | `api.openDetail()` / `api.refresh()` → 现有事件 |
| 注册组件 | `api.registerAlpineComponent()`（复用双分支） |
| 后端调用 | `api.api(path, options)` → `/api/plugins/<id>/*`，内部自动加 `X-Requested-With: XMLHttpRequest` 头 + 若存在 `<meta name="csrf-token">` 则自动带 `X-CSRFToken`（**CSRF 预留**，即使现在不实现也先封装，未来加 `after_request` CSRF 时插件零改动） |
| SSE | `api.subscribeJob(runId, handlers)`（含轮询降级） |

## 8.4 前端硬约束（来自调研，必须遵守）

| # | 约束 | 依据 |
|---|---|---|
| F1 | `api()` 必须检查 `data.success`，不能只看 `res.ok` | `/api/save_settings` 异常路径返回 **HTTP 200** + `{success:false}`（`system.py:390-391`） |
| F2 | 颜色只能用 `.color-*` 语义类 | 契约测试禁止 `bg-red-*`/`text-blue-*`（`tests/test_color_system_contracts.py:117-137`） |
| F3 | 新 Tailwind 类必须 `npm run build:css` | `static/css/tailwind.css` 是提交进 git 的产物（`package.json:4`） |
| F4 | 模态框用 `ui-modal-*` 骨架 + 自带尺寸（`!important`） | `.ui-modal-shell` 无宽高（`ui-refresh.css:957-964`） |
| F5 | 框选区域内的插件控件加 `data-marquee-ignore` | `utils/marqueeSelection.js:2-12` |
| F6 | 图标名须在 `state.js:79-95` 白名单内 | 否则 `showToast` 静默无图标 |
| F7 | `showToast` 的 `duration` 传字符串会被重置为 3000 | `state.js:1677-1679` |
| F8 | `settingsHelpContent` 是 `selectSettingTab` 硬闸门 | `settingsModal.js:295-299`（不加键则静默 no-op） |
| F9 | 卡片 DOM 会被窗口化反复重建 | `utils/windowing.js`、`cardGrid.js:1317-1369` |
| F10 | `refresh-card-list` 事件覆盖不全 | `cardGrid.js:970,1509,1585,1613,1863,1997` 直接 `fetchCards()` |
| F11 | **插件 CSS 必须有作用域** | `frontend.styles` 注入的样式**必须**以 `.plugin-<id>` 或 `[data-plugin="<id>"]` 为根选择器，防止污染核心 UI（如 `.card { border: red }`）。安装时做静态检查：扫 CSS 文件，发现顶层裸选择器（非 `@media`/`@keyframes`/`@font-face` 内的）则**警告并拒绝加载该样式**，UI 提示「样式未通过作用域检查」 |
| F12 | 插件 DOM 容器约定 | 插件注入的面板/模态框根元素应带 `data-plugin="<id>"`，与 F11 的 CSS 作用域配套；`pluginHost` 提供 `api.createRoot(tag)` 辅助函数自动生成带标记的容器。**挂载锚点**：`PluginHost.init()` 在 `document.body` 下创建 `<div id="plugin-host-root">`，`createRoot()` 默认把节点挂到它（该容器同时便于禁用/热卸载时整体清理） |

## 8.5 插件静态资源

```
GET /api/plugins/<plugin_id>/assets/<path:filename>
```

**安全要求**（**不要**再复制第 5 份 `_is_under_base`）：
- 抽出公共工具 `core/utils/paths.py:is_under_base()`，并重构现有 4 处重复（`chats.py:85`、`world_info.py:78`、`system.py:139` 函数定义 + `cards.py:3742` 内联）**[可选，建议单独提交]**
- `plugin_id` 正则校验 + `os.path.realpath` 边界检查
- 扩展名白名单：`.js`、`.mjs`、`.css`、`.svg`、`.png`、`.webp`、`.json`、`.woff2`、`.map`
- **不提供** `.py`、`.md`、`.env`
- 响应头：`Cache-Control: no-cache`（开发期）；生产可按 manifest 版本加 `?v=` 查询串

---

# 第 9 部分 · 插件管理 UI

**新增**：`templates/modals/plugin_manager.html` + `static/js/components/pluginManager.js`

## 9.1 三个页签

**① 已安装**（D9：四个操作）
```
┌─ 已安装插件 ───────────────────────────────────────────────┐
│ ● AI 角色卡分析助手        v0.1.0    [禁用] [更新] [卸载]   │
│    作者: xxx · 权限: 卡片读写, 标签写入, 密钥, 网络          │
│    [配置] [密钥]                                            │
│                                                             │
│ ○ 某插件                   v0.2.0    [启用] [更新] [卸载]   │
│    （已禁用，代码保留但不加载）                              │
│                                                             │
│ ⚠ 另一插件                 v0.1.0              [卸载]        │
│    加载失败: api_version 2 不受支持（需更新主程序）          │
└─────────────────────────────────────────────────────────────┘
```

状态图标：`●` 已启用 / `○` 已禁用 / `⚠` 加载失败。

四个操作的位置与语义（见 3.6）：

| 操作 | 位置 | 何时出现 |
|---|---|---|
| **安装** | 「官方目录」或「手动安装」页签 | 未安装时 |
| **卸载** | 「已安装」页签 | 始终 |
| **禁用** | 「已安装」页签 | 当前已启用时 |
| **启用** | 「已安装」页签 | 当前已禁用时 |

**禁用/启用需重启**（后端插件），UI 需明确提示；纯前端插件即时生效。安装/卸载后显示持久横幅：「插件已变更，重启应用后生效」+「立即重启」按钮。

**② 官方目录**（D1 核心）
```
┌─ 官方插件目录 ────────────────────── [检查更新] ────┐
│ AI 角色卡分析助手                      [安装]        │
│   为角色卡生成概览与标签建议                          │
│   作者: xxx · 标签: ai, tags                         │
│   GitHub ↗                                           │
│                                                      │
│ 世界书压缩助手                          [安装]        │
│   ...                                                │
└──────────────────────────────────────────────────────┘
```

**③ 手动安装**
- 拖拽/选择 zip 上传
- 显示将安装的插件元数据与权限，二次确认

## 9.2 配置与密钥表单

由 `config_schema` / `secret_schema` 自动生成（只支持第 2.2 节的 JSON Schema 子集）。

密钥字段：
- `type=password`，占位符显示 `hint`
- 「已设置 / 未设置」状态标记
- 清除按钮
- 顶部横幅提示：「密钥以明文存储在本机 `data/system/secrets.json`，请勿共享该文件」

## 9.3 入口

**最低成本**：在 `templates/modals/settings.html` 的「维护与高级」tab 内新增一个 `<section class="settings-section-block" id="settings-maintenance-plugins">`。零 JS 改动。

**推荐**：新增第 5 个顶层 tab。需改 4 处（见 `settingsModal.js:172-197` 的 `settingsHelpContent`——**这是硬闸门**，不加键则 `selectSettingTab` 静默失效）。

## 9.4 重启提示

后端插件安装/更新/卸载后，UI 显示持久横幅：「插件已变更，请手动关闭并重新启动 ST-Manager 后生效」，并在插件卡片上标出 `restart_required`。

**实现修订（阶段 0 落地时核实）**：主程序当前**没有**进程内重启端点——`POST /api/system_action` 只支持 `open_folder` / `open_notes` / `backup_data` / `cleanup_thumbnails` / `open_card_dir`。因此阶段 0 只做纯 UI 提示，不提供「立即重启」按钮；若日后引入重启能力，再按本节原方案补按钮。

---

# 第 10 部分 · API 契约（供独立仓库开发）

> **这是本设计的核心交付物。** 插件功能将在独立仓库实现，以下契约必须稳定。

## 10.1 稳定性分级

| 级别 | 含义 | 变更规则 |
|---|---|---|
| **Stable** | 冻结；破坏性变更需提升 `api_version` | 只增不改 |
| **Provisional** | 可能变更 | 变更需在 CHANGELOG 说明 |
| **Internal** | 不对外 | 随时可变 |

以下所有 API 默认 **Stable**，除特别标注。

## 10.2 后端 `PluginAPI`

```python
class PluginAPI:
    # ---- 身份 ----
    plugin_id: str          # Stable
    manifest: dict          # Stable（只读快照）
    app_version: str        # Stable

    # ---- 配置（存 ui_data._plugins_v1.<id>.config）----
    def get_config(self) -> dict: ...                    # Stable
    def set_config(self, patch: dict) -> bool: ...       # Stable（浅合并）

    # ---- 密钥（存 secrets.json）----
    def get_secret(self, key: str) -> str | None: ...     # Stable
    def set_secret(self, key: str, value: str | None) -> bool: ...  # Stable
    def list_secrets(self) -> dict: ...                   # Stable（返回 {key: {set, hint}}）

    # ---- 事件 ----
    def on(self, event: str, handler: Callable[[dict], None]) -> None: ...  # Stable
    def emit(self, event: str, payload: dict) -> None: ...                  # Stable
    # 插件自定义事件必须以 "<plugin_id>:" 开头，防止污染核心事件空间

    # ---- HTTP ----
    def blueprint(self, bp: Blueprint) -> None: ...      # Stable（自动前缀 /api/plugins/<id>）
    def route(self, rule: str, methods: list[str]) -> Callable: ...  # Stable（装饰器）

    # ---- 作业 ----
    def register_job(self, job_type: str, handler: Callable) -> None: ...  # Stable
    def submit_job(self, job_type: str, *,
                   items: list[dict] | list[str],
                   payload: dict | None = None) -> str: ...               # Stable（返回 run_id）
        """
        items 的两种形态（实现层统一归一化为 dict）：
          - list[str]  : ["卡片A", "卡片B"]           → item_key=str(item), payload={}
          - list[dict] : [{"key": "卡片A", "model": "x"}, ...]
                         → item_key=item["key"], payload=item 其余字段
        重复 key 会合并为最后一项（dict 按 key 去重，str 按值去重）。
        items 的顺序写入 plugin_job_items.seq，保证断点续跑顺序一致。
        """
    def get_job(self, run_id: str) -> dict | None: ...                    # Stable
    def cancel_job(self, run_id: str) -> bool: ...                        # Stable
    def retry_job(self, run_id: str, *, only_failed: bool = True) -> str: ...  # Stable
    def pause_job(self, run_id: str) -> bool: ...                         # Stable（D6 审批流）
    def resume_job(self, run_id: str) -> bool: ...                        # Stable

    # ---- 数据 ----
    def db(self) -> sqlite3.Connection: ...              # Provisional（主库；建议只读）
    def migrate(self, statements: list[str]) -> None: ...  # Stable（表名强制 plugin_<id>_ 前缀）
    def data_dir(self) -> str: ...                        # Stable（data/plugins/<id>/data/）

    # ---- 核心能力（复用现有服务层）----
    def read_card(self, card_id: str) -> dict | None: ...                 # Stable
    def read_cards(self, card_ids: list[str]) -> dict[str, dict]: ...     # Stable
    def write_card_fields(self, card_id: str, patch: dict) -> bool: ...   # Stable
        # 内部：@request_card_locks + suppress_fs_events + 缓存/索引同步
    def apply_tags(self, card_ids: list[str], *, add: list[str] = (),
                   remove: list[str] = (), replace: bool = False) -> dict: ...  # Stable
        # 内部：复用 /api/batch_tags 的逻辑 + filter_governed_tags 治理
        # ★ D3/D4：默认 replace=False（合并）
    def read_tag_library(self) -> dict: ...               # Stable（标签 + 分类体系）
    def read_worldbook(self, source: dict) -> dict | None: ...            # Stable
    def write_worldbook(self, source: dict, data: dict,
                        *, expected_revision: str = '') -> dict: ...      # Stable
        # 内部：复用 /api/world_info/save 的逻辑，含 source_revision 乐观锁与条目历史记账
    def snapshot_card(self, card_id: str, *, remark: str = '') -> str | None: ...  # Stable
    def ui_data_read(self) -> dict: ...                   # Provisional（只读快照）
    def ui_data_update(self, mutator: Callable[[dict], None]) -> bool: ...  # Stable

    # ---- 文件系统抑制 ----
    def suppress_fs_events(self) -> ContextManager: ...   # Stable
        # 用法：with api.suppress_fs_events(): fp.write_text(...)
        # 在写 data/library/ 或 data/system/ 下文件前必须用它，
        # 否则触发扫描器/监控造成不必要的重扫。写 data/plugins/<id>/data/ 无需。

    # ---- 通知 ----
    def notify(self, level: str, message: str) -> None: ...  # Stable（写入作业日志/前端 toast）
    def log(self, level: str, message: str, **extra) -> None: ...  # Stable（自动带 plugin_id 前缀）
```

## 10.3 前端 `PluginAPI`

```js
// activate(api) 收到的对象
{
  // ---- 身份 ----
  id: string,                       // Stable
  manifest: object,                 // Stable

  // ---- 状态 ----
  state: Proxy,                     // Stable（Alpine.reactive({})）
  get store(): object,              // Stable（Alpine.store('global')）

  // ---- 事件 ----
  on(event, handler): () => void,   // Stable（返回取消订阅函数）
  off(event, handler): void,        // Stable
  emit(event, detail): void,        // Stable（自定义事件须以 "<id>:" 开头）

  // ---- 通知与进度 ----
  toast(msg, duration = 3000, icon = ''): void,        // Stable
  progress: {
    start(title, total): void,                          // Stable
    update(patch): void,                                // Stable
    cancelRequested(): boolean,                         // Stable
    finish(result): void,                               // Stable
    dismiss(): void,                                    // Stable
  },

  // ---- 打开既有 UI ----
  openDetail(target, id): void,     // Stable（target: 'card'|'preset'|'chat'）
  refresh(target): void,            // Stable（target: 'cards'|'worldinfo'|'chats'|'presets'）
  switchMode(mode): void,           // Stable
  openSettingsSection(section, anchor): void,  // Stable

  // ---- 注册 UI ----
  registerAlpineComponent(name, factory): void,   // Stable
  registerModal(spec): void,                      // Provisional
  registerSettingsSection(spec): void,            // Provisional

  // ---- 后端调用 ----
  async api(path, options = {}): Promise<object>, // Stable
      // 自动加 /api/plugins/<id> 前缀；返回解析后的 JSON
      // ★ 调用方必须检查 data.success

  // ---- SSE / 作业 ----
  subscribeJob(runId, handlers): () => void,      // Stable（含轮询降级）
      // handlers: { snapshot, item, log, done, error }

  // ---- 工具 ----
  estimateTokens(text): number,     // Stable（复用 static/js/utils/format.js:60）
  utils: { ... },                   // Provisional（toAbsoluteAssetUrl / parseSSEFrames / parseSSEPayload / formatDate）
  jobs: { ... },                    // Provisional（get / list / submit / cancel / pause / resume / retry / open）
  createRoot(tag = 'div'): HTMLElement,  // Stable（容器自动带 data-plugin="<id>"，停用时移除）
}
```

## 10.4 HTTP 契约

### 插件管理

**生命周期四操作**（D9，语义见 3.6）：

| 方法 | 路径 | 说明 | 需重启 |
|---|---|---|---|
| `POST` | `/api/plugins/catalog/install` | **安装**（从官方目录） | 是（纯前端否） |
| `POST` | `/api/plugins/install_upload` | **安装**（手动上传 zip） | 是（纯前端否） |
| `POST` | `/api/plugins/uninstall` | **卸载**（含默认清理数据与密钥） | 是 |
| `POST` | `/api/plugins/<id>/disable` | **禁用**（保留代码，不加载） | 是（纯前端否） |
| `POST` | `/api/plugins/<id>/enable` | **启用** | 是（纯前端否） |

**其余管理接口**：

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/plugins/list` | 已安装插件（含 enabled / load_error / 是否纯前端） |
| `GET` | `/api/plugins/<id>/config` | 读取配置（schema 默认值 + 已保存值） |
| `POST` | `/api/plugins/<id>/config` | 保存配置 |
| `GET` | `/api/plugins/<id>/secrets` | 读取（掩码） |
| `POST` | `/api/plugins/<id>/secrets` | 写入 |
| `DELETE` | `/api/plugins/<id>/secrets/<key>` | 清除单项 |
| `GET` | `/api/plugins/catalog` | 官方目录 |
| `POST` | `/api/plugins/catalog/check_updates` | 检查更新 |
| `GET` | `/api/plugins/<id>/assets/<path>` | 静态资源 |
| `GET` | `/api/plugins/<id>/readme` | 插件文档（README / CHANGELOG 原文；`.md` 不在资源白名单，故单独提供） |

**`GET /api/plugins/list` 响应示例**：
```json
{
  "success": true,
  "items": [
    { "id": "stm-ai-assistant", "name": "AI 角色卡分析助手", "version": "0.1.0",
      "enabled": true, "loaded": true, "backend": true, "frontend": true,
      "permissions": ["cards.read", "tags.write", "secrets.read"],
      "load_error": "", "restart_required": false }
  ]
}

### 作业

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/plugins/<id>/jobs` | 创建作业 → `{success, run_id}` |
| `GET` | `/api/plugins/<id>/jobs` | 列出作业（分页） |
| `GET` | `/api/plugins/<id>/jobs/<run_id>` | 作业状态 + 条目（分页） |
| `GET` | `/api/plugins/<id>/jobs/<run_id>/events` | **SSE 事件流** |
| `POST` | `/api/plugins/<id>/jobs/<run_id>/cancel` | 取消 |
| `POST` | `/api/plugins/<id>/jobs/<run_id>/pause` | 暂停（审批流） |
| `POST` | `/api/plugins/<id>/jobs/<run_id>/resume` | 恢复 |
| `POST` | `/api/plugins/<id>/jobs/<run_id>/retry` | 重跑失败项 |
| `POST` | `/api/plugins/<id>/jobs/<run_id>/items/<item_key>/review` | **逐条审批**（D6） |

**统一响应格式**（对齐现有约定）：
```json
{ "success": true, ... }
{ "success": false, "msg": "错误描述" }
```

**统一错误码**（新增 `error` 字段，与 `msg` 并存）：

| `error` | HTTP | 含义 |
|---|---|---|
| `plugin_not_found` | 404 | 插件不存在 |
| `plugin_disabled` | 409 | 插件已禁用 |
| `plugin_load_failed` | 500 | 插件加载失败 |
| `job_not_found` | 404 | 作业不存在 |
| `job_not_running` | 409 | 作业非运行态，无法取消/暂停 |
| `job_already_running` | 409 | 同插件已有运行中作业 |
| `sse_limit_reached` | 429 | SSE 连接数超限 |
| `catalog_offline` | 502 | 目录/仓库不可达 |
| `install_unsafe_archive` | 400 | 归档未通过安全检查 |
| `api_version_unsupported` | 409 | 插件 API 版本不兼容 |

## 10.5 AI 插件需要的能力（需求侧核对表）

供独立仓库开发时对照。**本设计已全部覆盖**：

| AI 插件需求 | 契约中的对应 |
|---|---|
| 读取卡片全字段 + 内嵌世界书 | `read_card()` / `read_cards()` |
| 读取世界书条目 | `read_worldbook()` |
| 读取标签库 + 分类体系 | `read_tag_library()` |
| 生成概览写入 | `ui_data_update()` 或 `write_card_fields()` |
| 标签合并写入（默认合并） | `apply_tags(replace=False)` |
| 批量长任务 + 进度 | `submit_job()` + SSE |
| 中断续跑 | `retry_job(only_failed=True)` |
| 逐条审批 | `pause_job()` + `/items/<key>/review` |
| API Key 存储 | `get_secret()` / `set_secret()` |
| 成本预估 | `estimateTokens()` |
| 结果审阅 UI | `registerModal()` + `subscribeJob()` |
| 世界书缩减写回 | `write_worldbook(expected_revision=...)` |
| 缩减前快照 | `snapshot_card()` |
| 回滚 | `write_worldbook()` 内部走条目历史记账 |

**结论：无需为 AI 插件新增任何契约**——第 4、6、7 部分的能力已足够。

---

# 第 11 部分 · 分期路线图

> 范围：**仅插件系统**。插件功能在独立仓库。

## 阶段 0 · 契约与骨架（无插件功能）

| 任务 | 产出 | 验收 |
|---|---|---|
| 0.1 manifest 解析与校验 | `core/plugins/manifest.py` | 非法 manifest 被拒绝，错误信息明确 |
| 0.2 插件发现与加载 | `core/plugins/registry.py` | 能加载 Hello World；坏插件不影响启动 |
| 0.3 PluginAPI 门面 | `core/plugins/api.py` | 配置/密钥/日志可用 |
| 0.4 Hook 总线 | `core/plugins/hooks.py` | 事件派发 + 异常隔离 + 耗时告警 |
| 0.5 密钥存储 | `core/plugins/secrets.py` | 原子写 + 掩码 + 损坏恢复 + 环境变量覆盖 |
| 0.6 静态资源路由 | `core/plugins/assets.py` | 路径穿越被拒 |
| 0.7 管理 API | `core/plugins/routes.py` | 列表 / 安装 / 卸载 / 禁用 / 启用 / 配置 / 密钥 |
| 0.8 前端 PluginHost | `static/js/pluginHost.js` | 能加载前端插件、注册组件、调 API |
| 0.9 管理 UI（已安装页签） | `templates/modals/plugin_manager.html` | 可视化四操作（安装/卸载/禁用/启用）与配置 |

**验收**：能手动放入一个 Hello World 插件（后端加路由 + 前端加按钮 + 读写自己的配置与密钥）。

## 阶段 1 · 作业系统与 SSE

| 任务 | 产出 |
|---|---|
| 1.1 作业表 + 存储层 | `core/plugins/job_store.py` |
| 1.2 作业 worker（进度 + 协作取消 + 崩溃恢复 + 并发） | `core/plugins/jobs.py` |
| 1.3 作业 HTTP API | 创建/状态/取消/暂停/恢复/重试 |
| 1.4 **SSE 端点** | `/jobs/<run_id>/events` + `plugin_job_events` 表 |
| 1.5 逐条审批 API | `/items/<key>/review` |
| 1.6 前端 `subscribeJob()` + 轮询降级 | `pluginHost.js` |
| 1.7 作业面板 | 复用 `batch_progress.html` 或新建 |

**验收**：跑一个 1000 项的假作业；实时看进度；中途取消；重启后恢复；只重跑失败项。

## 阶段 2 · 官方目录与 GitHub 安装

| 任务 | 产出 |
|---|---|
| 2.1 catalog 格式 + 包内兜底清单 | `static/plugins/catalog.json` |
| 2.2 远端拉取 + 缓存 + 离线降级 | `core/plugins/catalog.py` + 3 个新配置项 |
| 2.3 下载 + 解压 + 安全校验 | `core/plugins/installer.py` |
| 2.4 安装/卸载/禁用/启用 API | 复用 `routes.py` |
| 2.5 更新检查（含 GitHub Token） | `core/plugins/catalog.py` |
| 2.6 目录 UI + 手动安装 UI | 管理模态框新增两个页签 |

**验收**：从 GitHub 安装一个真实插件；改本仓库 catalog 后用户不发版即可看到新条目；zip-slip 攻击被拒；卸载进回收站。

## 阶段 3 · 打磨

- 插件详情页（README 渲染、CHANGELOG）
- 插件间依赖声明与检查 **[可选]**：manifest 加 `"requires": {"stm-another-plugin": ">=1.0.0"}`，加载时检查；依赖缺失则 `load_error` 提示
- 插件开发脚手架 `tools/new_plugin.py`
- API 文档自动生成
- 安全响应头（`after_request`）——**注意**：需先清理现有内联脚本依赖，否则 CSP 会破坏现有页面

### 延后记录（不阻塞当前实现）

| # | 项 | 说明 |
|---|---|---|
| N1 | **插件间通信** | 自定义事件已限定 `<id>:` 前缀。**允许**跨插件订阅（`api.on("other-plugin:xxx")`），但**不保证送达顺序**，也不检测循环触发（A emit → B 处理 → B emit → A 处理）。文档明确「插件间通信是最佳-effort，禁止依赖顺序」 |
| N2 | **插件提供 CLI 子命令** | `python app.py plugin <id> <cmd> [args]`，供批处理/无人值守场景。契约：`api.register_cli(name, handler)`，handler 接收 `argparse.Namespace`。**阶段 3 可选** |
| N3 | **插件 i18n** | `manifest.json` 的 `name`/`description` 只支持单语言。后续可加 `name_zh`/`name_en` 或 `i18n/<lang>.json` 目录。当前阶段不实现，但 manifest 规范预留 `i18n` 字段位 |
| N4 | **`ui_data` 插件命名空间的写入配额** | `_plugins_v1.<id>` 无大小上限，插件可能塞入大对象拖慢 `load_ui_data()`。建议**单插件命名空间 ≤ 256KB**，超限 `ui_data_update` 返回 `False` 并记 warning。阶段 0 先做约定不实现检查 |
| N5 | **`config_schema`/`secret_schema` 的 `secret: true` 项写入磁盘前可加密** | 当前明文存 `secrets.json`。后续若引入 OS keychain（如 Windows DPAPI / macOS Keychain），schema 不变、实现层透明升级。**仅预留** |
| N6 | **作业 `payload_json` 含 `secret_ref` 的运行时解析** | `submit_job` 约定 payload 里只存 `{"secret_ref": "key_name"}`，worker 启动时 `ctx.api.get_secret()` 解析替换，**密钥值不落 `plugin_jobs` 表** |

---

# 第 12 部分 · 风险与陷阱

## 12.1 插件系统

| # | 风险 | 缓解 |
|---|---|---|
| R1 | 坏插件阻止应用启动 | 逐插件 `try/except`（第 4.3） |
| R2 | 插件线程非 daemon 导致进程不退 | 强制 daemon；提供 `api.spawn_thread()` 封装 |
| R3 | 插件污染核心表 | `migrate()` 强制 `plugin_<id>_` 前缀 |
| R4 | 插件写 ui_data 造成 lost update | 强制走 `update_ui_data()` |
| R5 | 插件写文件触发扫描风暴 | 门面写方法内部 `suppress_fs_events()` |
| R6 | 插件路径穿越 | `plugin_id` 正则 + `realpath` 边界 + 扩展名白名单 |
| R7 | 插件密钥泄漏 | 掩码 API + 日志脱敏 + 永不返回明文 |
| R8 | API 演进破坏旧插件 | `api_version` 硬闸门 + 明确提示 |
| R9 | 插件覆盖核心路由 | 强制前缀 + 注册前冲突检查 |
| R10 | 前端插件阻塞首屏 | 懒加载（`requestIdleCallback`） |
| R11 | **Python 无法热卸载** | 安装后提示重启；纯前端插件可热加载 |
| R12 | 插件异常拖垮 hook 派发 | 逐 handler `try/except` + 耗时告警 |
| R13 | 插件模块名冲突（两个插件都带 `backend/`） | `spec_from_file_location` + `st_plugin_<id>` 前缀（第 4.3） |
| R14 | 单插件饿死作业队列 | `_claim_runnable_jobs` 按 `plugin_id` 分组限流（`MAX_JOBS_PER_PLUGIN=2`） |
| R15 | 插件 CSS 污染核心 UI | F11：强制 `.plugin-<id>` 作用域 + 安装时静态检查 |
| R16 | SSE `seq` 语义混乱 | 作业内自增 + `id:` 字段 + snapshot 不落表（第 6.4） |
| R17 | 断点续跑顺序错乱 | `plugin_job_items.seq`/`created_at` 保证提交顺序（第 6.1） |
| R18 | 密钥落 `plugin_jobs` 表 | 契约禁止 payload 含密钥值，用 `secret_ref`（第 6.3） |

## 12.2 供应链（新增，D1 引入）

| # | 风险 | 缓解 |
|---|---|---|
| S1 | **zip-slip** | 逐 entry `realpath` 校验（第 3.4） |
| S2 | **zip 炸弹** | 大小/压缩比/entry 数限制 |
| S3 | **符号链接逃逸** | 拒绝归档中的 symlink |
| S4 | **catalog 与 manifest 不符** | 强制 `id` 一致 |
| S5 | **中间人篡改** | 强制 HTTPS；**[可选]** catalog 支持 `sha256` 校验和 |
| S6 | **GitHub 限流** | 默认手动检查 + 24h 缓存 + 可选 Token |
| S7 | **SSRF** | URL 由本地 catalog 构造，用户只可覆盖 `ref`/`subdir`（正则校验） |
| S8 | **恶意插件**（D7 已接受） | 安装前展示权限清单，用户显式确认；卸载进回收站 |

## 12.3 SSE

| # | 风险 | 缓解 |
|---|---|---|
| E1 | 每个连接占一个线程 | 每 run 最多 4 个、全局最多 32 个连接 |
| E2 | 代理缓冲导致事件不实时 | `X-Accel-Buffering: no` + `Cache-Control: no-cache` |
| E3 | 客户端断开后服务端未察觉 | `GeneratorExit` 捕获 + `finally` 清理 |
| E4 | 刷新页面丢事件 | `plugin_job_events` 表 + `Last-Event-ID` 续传 |
| E5 | 浏览器不支持 / 代理拦截 | 前端轮询降级 |
| E6 | 长时间空闲断连 | 15s 心跳注释行 |
| E7 | werkzeug 单线程模式（若用户改配置） | 文档说明；检测到非 threaded 时降级为轮询 **[推断]** |

## 12.4 前端

见第 8.4 节的 F1–F10（10 条硬约束）。

## 12.5 密钥

| # | 风险 | 缓解 |
|---|---|---|
| K1 | 明文存储被读取 | 文件权限 0600 + UI 明确告知 |
| K2 | 密钥进入日志 | `secrets.py` 内统一脱敏 |
| K3 | 密钥进入错误响应 | 错误信息剥离 URL query |
| K4 | 读失败后覆盖写 | 读失败 → 拒绝写入（第 7.3.2） |
| K5 | 破坏现有 `config.json` 密钥 | **不迁移**（第 7.3.1） |

---

# 第 13 部分 · 测试策略

遵循仓库既有约定（`docs/DEVELOPMENT.md:152-172`、`tests/conftest.py`）：**不用 `create_app()`**，而是 `Flask(__name__) + register_blueprint`；用 `monkeypatch.setattr` 替换路径常量与 `get_db`；`ui_data`/`chat_data` 已由 `tests/conftest.py:40-49` 自动隔离。

## 13.1 新增测试文件

| 文件 | 覆盖 |
|---|---|
| `tests/test_plugin_manifest.py` | id 正则、版本格式、`api_version` 闸门、`min_app_version`、entry 路径逃逸、schema 子集校验 |
| `tests/test_plugin_registry.py` | 发现、加载、**失败隔离**（坏插件不阻止 `create_app`）、重复 id、路由冲突 |
| `tests/test_plugin_api.py` | 配置读写、`migrate` 表名前缀、`read_card`/`apply_tags` 走锁与 `suppress_fs_events` |
| `tests/test_plugin_hooks.py` | 派发、异常隔离、耗时告警、自定义事件命名空间校验 |
| `tests/test_plugin_secrets.py` | 原子写、掩码、清除、环境变量优先级、损坏恢复、**读失败拒绝写**、日志脱敏 |
| `tests/test_plugin_jobs.py` | 创建/认领/进度/取消/暂停/恢复/重试/崩溃恢复/并发/同插件串行化 |
| `tests/test_plugin_sse.py` | 事件格式、`snapshot` 首帧、`done` 终帧、`Last-Event-ID` 续传、连接上限 429、客户端断开清理 |
| `tests/test_plugin_installer.py` | **zip-slip**、绝对路径、符号链接、zip 炸弹、大小限制、`id` 不符、校验和 |
| `tests/test_plugin_catalog.py` | 目录解析、更新检查（fake HTTP）、缓存、限流降级 |
| `tests/test_plugin_assets.py` | 路径穿越、扩展名白名单、404、`plugin_id` 正则 |
| `tests/test_plugin_routes.py` | 管理 API 契约、错误码 |
| `tests/test_plugin_loader.py` | **`spec_from_file_location` 隔离**：两个插件同带 `backend/` 不冲突；`st_plugin_<id>` 前缀；相对导入成功、绝对导入失败；`sys.modules` 无 `backend` 残留 |
| `tests/test_plugin_css_scope.py` | **F11 静态检查**：`frontend/*.css` 中顶层裸选择器（`.card`/`div`/`body`）被拒；`.plugin-<id>`/`[data-plugin="<id>"]` 内的通过；`@media`/`@keyframes`/`@font-face` 内的不检查 |
| `tests/test_plugin_job_order.py` | **G2 顺序保证**：`submit_job(items=[dict,dict,dict])` 的 `seq` 连续且与列表顺序一致；`retry_job` 后只重跑 `failed` 项；`plugin_job_items.created_at` 存在且递增 |
| `tests/test_plugin_sse_seq.py` | **G3 seq 语义**：`plugin_job_events.seq` 作业内自增（非全局）；`id:` 字段存在且等于 `seq`；`Last-Event-ID: 3` 重连后从 `seq=4` 续传；`snapshot` 不落表（`seq=0` 固定） |

## 13.2 前端契约测试

沿用「读源码字符串断言」模式（`tests/test_*_frontend_contracts.py`）：

- `tests/test_plugin_host_contracts.py`：`pluginHost.js` 暴露完整 API；`api()` 检查 `data.success`；Alpine 双分支存在；`api()` 实现里带 `X-Requested-With` 头 + 尝试读 `meta[name=csrf-token]` |
- `tests/test_plugin_manager_contracts.py`：管理模态框用 `ui-modal-*`；无 Tailwind 颜色类
- `tests/test_plugin_sse_frontend_contracts.py`：`subscribeJob` 含轮询降级分支
- 更新 `tests/test_color_system_contracts.py` 覆盖新增 CSS

## 13.3 回归保护（针对本报告揭示的既有脆弱点）

| 测试 | 保护对象 |
|---|---|
| `test_plugin_load_failure_isolation.py` | **一个坏插件不得阻止 `create_app()`** |
| `test_secrets_never_return_plaintext.py` | 密钥永不通过 HTTP 明文返回 |
| `test_secrets_read_failure_blocks_write.py` | 读失败不覆盖既有密钥 |
| `test_apply_tags_defaults_to_merge.py` | **D4：默认合并不清空**（脚本 `replace:true` 的教训） |
| `test_plugin_jobs_abort_on_restart.py` | 崩溃恢复 |
| `test_ui_data_plugin_namespace_isolation.py` | 插件写 `_plugins_v1` 不影响既有键 |

## 13.4 Node 运行时测试

- `tests/plugin_sse_parse_test.mjs`：SSE 事件解析（含多行 `data:`、`event:`、注释行）

---

# 附录 A · 新增文件清单

**后端**
```
core/plugins/__init__.py
core/plugins/manifest.py
core/plugins/registry.py
core/plugins/api.py
core/plugins/hooks.py
core/plugins/jobs.py
core/plugins/job_store.py
core/plugins/secrets.py
core/plugins/installer.py
core/plugins/catalog.py
core/plugins/assets.py
core/plugins/errors.py
core/plugins/routes.py
```

**前端**
```
static/js/pluginHost.js
static/js/components/pluginManager.js
templates/modals/plugin_manager.html
static/css/modules/modal-plugin-manager.css
static/plugins/catalog.json
```

**数据（运行时生成）**
```
data/plugins/                    # 插件本体
data/system/secrets.json         # 密钥
data/system/db/cards_metadata.db → plugin_install_log 表   # 安装历史（审计）
```

**测试**
```
tests/test_plugin_*.py           # 11 个（见 13.1）
tests/test_plugin_*_contracts.py # 3 个（见 13.2）
tests/plugin_sse_parse_test.mjs
```

# 附录 B · 核心代码改动点

**最小侵入清单**（每处 1–3 行）：

| # | 文件:行 | 改动 |
|---|---|---|
| 1 | `core/__init__.py:76` 后 | `registry.load_all(app)` |
| 2 | `core/__init__.py:147` 后 | `start_plugin_job_worker()` |
| 3 | `core/api/v1/cards.py:2180` 附近 | `hooks.emit('card.updated', ...)` |
| 4 | `core/api/v1/cards.py:4669` 附近 | `hooks.emit('tag.applied', ...)` |
| 5 | `core/api/v1/cards.py` 删除/导入后 | `hooks.emit('card.deleted'/'card.created', ...)` |
| 6 | `core/api/v1/cards.py:2269` 附近 | `hooks.emit('card.moved', ...)` |
| 7 | `core/api/v1/world_info.py:2333` 附近 | `hooks.emit('worldbook.saved', ...)` |
| 8 | `core/services/scan_service.py` 扫描末尾 | `hooks.emit('scan.completed', ...)` |
| 9 | `core/services/index_job_worker.py:243` | `hooks.emit('index.job_done', ...)` |
| 10 | `static/js/app.js:85` 后 | `PluginHost.init()` |
| 11 | `templates/layout.html` | 无需改动（插件资源由 `/api/plugins/<id>/assets/` 提供，运行时注入） |
| 12 | `templates/modals/settings.html:203` 附近 | 插件管理入口 section |
| 13 | `core/event_bus.py` | **删除**（被 `hooks.py` 取代） |

**可选重构**（已随阶段 0 单独提交完成）：
- ✅ 抽出 `core/utils/paths.py:is_under_base()`，消除 4 处重复（`chats.py:85`、`world_info.py:78`、`system.py:139` 函数定义 + `cards.py:3742` 内联）；插件资源路由复用该实现，未新增第 5 份

---

## 决策记录

**全部决策已确认，无待定项。**

| # | 问题 | 决策 | 落点 |
|---|---|---|---|
| 1 | catalog 托管位置 | **方案 B**：清单放本仓库，从 `Dadihu123/ST-Manager` 的 `main` 拉取；包内保留兜底 | 3.1、D11 |
| 2 | `api_version` 不兼容 | **严格拒绝加载**（不做降级中间态） | 2.2、D8 |
| 3 | 作业事件保留期 | **按作业条数**：completed 100 / failed 50 | 6.5、D12 |
| 4 | 插件生命周期 | **四个操作**：安装 / 卸载 / 禁用 / 启用；禁用 = 完全不加载 | 3.6、D9 |
| 5 | 卸载时数据清理 | **默认清理** `_plugins_v1.<id>` 与密钥；`keep_data` 为显式 opt-in | 3.6、D10 |

所有决策已确认。第 0 部分的决策基线（D1–D12）与本节是完整一致的；无待定项。

---

# 附录 C · 阶段 0 实现记录

以下是阶段 0 落地时确认的**补充约定**与**与文档原文的差异**（均已回写本文件）：

| # | 项 | 结论 |
|---|---|---|
| 1 | 主程序版本来源 | 新增 `core/version.py`：`APP_VERSION = '1.0.0'`、`PLUGIN_API_VERSION = 1`、`SUPPORTED_PLUGIN_API_VERSIONS = (1,)`；`min_app_version` 与该常量比较 |
| 2 | `plugin_jobs.claim_token` | DDL 补齐**独立列**（6.1），认领去重不再复用 `error` 列 |
| 3 | `api.route()` 注册时机 | 见 4.5：规则先收集到默认蓝图，`register(api)` 返回后由 `api.finalize()` 统一注册 |
| 4 | 前端挂载锚点 | 见 8.4 F12：`PluginHost.init()` 创建 `#plugin-host-root`，`api.createRoot()` 默认挂到它 |
| 5 | 配置读取接口 | 新增 `GET /api/plugins/<id>/config`（10.4） |
| 6 | 重启提示 | 见 9.4：主程序没有重启端点，阶段 0 只做 UI 提示 |
| 7 | 包内 catalog | `static/plugins/catalog.json` 初始为**空清单**（`plugins: []`），真实条目留待阶段 2 |
| 8 | 阶段 0 覆盖范围 | 12 个模块全部落地；`job_store.py` / `jobs.py` / `installer.py` / `catalog.py` 已实现完整逻辑（含 4 张表 DDL、作业 HTTP + SSE 端点），阶段 1/2 剩余的是测试与作业面板 UI |
| 9 | 管理 UI 入口 | `settings.html` 的「维护与高级」tab 内新增 `settings-maintenance-plugins` 区块，按钮派发 `open-plugin-manager` 事件打开模态框 |
| 10 | 样式作用域检查结果 | 安装时扫描失败的样式写入 `ui_data._plugins_v1.<id>.style_scope_errors`，由 `/api/plugins/list` 下发，前端跳过这些样式的加载 |
| 11 | 样例插件 | `samples/plugins/hello-world/`（仓库内留档，验收时复制到 `data/plugins/hello-world/`） |
| 12 | 新增前端文件 | 除附录 A 外补 `static/js/api/plugins.js`（管理 API 封装），符合「与后端交互集中在 `static/js/api/`」的既有约定 |

**测试覆盖**：13.1 的 12 个文件全部落地，另加 13.2 的 3 个前端契约测试与 `test_secrets_*` 回归项；命令见 `docs/DEVELOPMENT.md`。

---

# 附录 D · 阶段 1 实现记录

| # | 项 | 结论 |
|---|---|---|
| 1 | 作业面板 | 新增 `templates/components/plugin_job_panel.html` + `static/js/components/pluginJobPanel.js` + `static/css/modules/modal-plugin-job.css`；由 `open-plugin-job-panel` 事件打开（`api.jobs.open(runId, {title})`） |
| 2 | 前端作业辅助 | `PluginAPI.jobs = { get, list, submit, cancel, pause, resume, retry, open }`（Provisional 扩展，10.3 的 `subscribeJob` 仍为 Stable 主通道） |
| 3 | SSE 解析工具 | 新增 `static/js/utils/sse.js`（`parseSSEFrames` / `parseSSEPayload`，供插件自行消费流与 Node 协议校验），经 `api.utils` 暴露 |
| 4 | 面板数据通道 | 优先用 `PluginHost.getPluginApi(id).subscribeJob()`（内含 SSE + 轮询降级）；插件未加载时退回 4s 轮询作业详情接口 |
| 5 | worker 优雅停机 | 新增 `stop_plugin_job_worker()`（幂等，daemon 线程 + 停机信号）；`reset_for_tests()` 会先停机再清状态，避免残留线程与后续用例争抢作业 |
| 6 | 同类型作业串行化 | `submit_job` 对同 plugin_id + job_type 的活跃作业抛 `job_already_running`（见 6.3） |
| 7 | 样例插件升级 | `samples/plugins/hello-world` 增加 `demo.count` 作业（逐项上报、`ctx.should_cancel()` 协作取消）与「跑 1000 项批量作业」按钮，串起「提交 → 面板 → 取消 → 只重跑失败项」全链路 |
| 8 | 新增测试 | `test_plugin_jobs.py`(38) / `test_plugin_sse.py`(15) / `test_plugin_job_order.py`(9) / `test_plugin_sse_seq.py`(9) / `test_plugin_job_panel_contracts.py`(12) + `plugin_sse_parse_test.mjs`（Node） |
| 9 | 顺带修复 | `job_store._dump_json` 的截断逻辑改为逐字段裁剪（原实现遇到未列入白名单的大字段会撞 `CHECK (length(result_json) <= 262144)`）；`normalize_items` 幂等化，避免 `submit_job → create_job` 双重归一化把 payload 包成 `{"payload": …}` |

**验收实测**（`data/plugins/hello-world`，1000 项作业）：`completed=980 / failed=20 / total=1000`，耗时 2.63s；SSE 首帧 `snapshot`（`id: 0`）与终帧 `done` 正常；`retry(only_failed=True)` 后事件数 1002 → 1024（只重跑 20 个失败项 + 1 条 log + 1 条 done）；取消 → `cancelled`。

---

# 附录 E · 阶段 2 实现记录（安装器与官方目录）

| # | 项 | 结论 |
|---|---|---|
| 1 | 归档完整性校验 | catalog `source.sha256`（可选，64 位小写十六进制）在下载后校验；不符即中止，**不落盘**（12.2 S5 的缓解措施落地） |
| 2 | `app` 段密钥接口 | 新增 `secrets.get_app_secret()` / `set_app_secret()`；GitHub Token 改走该通道，环境变量 `STM_APP_<KEY>` 优先（见 7.2） |
| 3 | 目录名约束放宽 | `PluginManifest.load(check_dir_name=...)`：安装阶段解压目录名不可控（GitHub 归档顶层是 `repo-branch`），此时不校验目录名；安装完成后目录被重命名为 id，**已安装插件仍强校验**。修复前「从 GitHub 安装」必然失败 |
| 4 | 测试 | `test_plugin_installer.py`（47：zip-slip / 绝对路径 / 盘符 / 符号链接 / 炸弹 / 体积与条目上限 / 磁盘空间 / 供应链 id / 回收站 / 卸载清理）+ `test_plugin_catalog.py`（28：清单解析与 SSRF 约束 / 远端拉取 / 缓存新鲜期 / 离线降级 / 关闭远端 / 体积上限 / Release 优先与回退 / 24h 缓存 / Token 透传）+ `test_plugin_secrets.py` 新增 app 段 4 项 |
| 5 | 端到端 | 本地 HTTP 模拟 codeload 走**真实下载路径**：下载 → sha256 → 解压（含 GitHub 风格的 `repo-main/` 顶层目录）→ 安装成功；sha256 不符被拒且目录未创建；安装后 manifest 可被正常重新加载 |

**未覆盖**：真实 GitHub 联调需要你提供插件仓库的 `owner/repo`（当前 `static/plugins/catalog.json` 为空清单）；catalog 的 `release_channel: beta` 分支仅在测试中以远端 manifest 回退路径覆盖。

---

# 附录 F · 阶段 3 实现记录（依赖声明 / 文档预览 / 脚手架）

| # | 项 | 结论 |
|---|---|---|
| 1 | 依赖声明 | manifest 新增 `requires`（`{plugin_id: 版本约束}`）；`manifest.parse_requirement()` / `satisfies_requirement()` 支持 `>= > <= < == =` 与 `*`，无操作符视为精确匹配 |
| 2 | 三阶段加载 | `registry.load_all()` 改为「解析全部 manifest → 依赖校验 + 拓扑排序 → 按序实例化」；新增 `registry.resolve_dependencies()` 返回 `(顺序, 错误)`；依赖缺失 / 被禁用 / 版本不满足 / 循环依赖 / 上游加载失败都会记入 `load_error` 并跳过 |
| 3 | 依赖展示 | `GET /api/plugins/list` 的 `manifest.requires` 下发；管理 UI 卡片新增「依赖: …」一行 |
| 4 | 文档预览 | 新增 `GET /api/plugins/<id>/readme`（只读插件根目录的 `README.md` / `CHANGELOG.md` 等固定文件名，256KB 上限，realpath 边界检查）；管理 UI 新增「详情」按钮，经 `open-markdown-view` 复用既有 Markdown 预览器（事件 detail 扩展为 `{content, title}`，向后兼容纯字符串） |
| 5 | 脚手架 | 新增 `tools/new_plugin.py`：生成 `manifest.json` / `README.md` / `backend/__init__.py` / `frontend/plugin.js` / `frontend/plugin.css`，支持 `--no-backend` / `--no-frontend` / `--out` / `--force`；生成物保证通过 manifest 校验与 CSS 作用域检查 |
| 6 | 测试 | `test_plugin_dependencies.py`(39) / `test_plugin_scaffold.py`(12) / `test_plugin_routes.py` 新增 readme 5 项 / 前端契约新增 2 项；`test_plugin_hooks.py` 的耗时告警用例改为注入确定时钟（原实现依赖真实 sleep，在全量运行下受 monotonic 分辨率影响而抖动） |

**验收实测**：脚手架生成的插件可直接被 `load_all()` 加载并响应 `GET /api/plugins/<id>/ping`；依赖测试覆盖 A→B→C 三级拓扑序、循环依赖、禁用依赖、上游加载失败传播。

---

# 附录 G · 阶段 3 收尾（API 文档自动生成）

| # | 项 | 结论 |
|---|---|---|
| 1 | 生成器 | 新增 `tools/gen_plugin_api_docs.py`：用 `inspect` 读取 `PluginAPI` 的真实签名与 docstring，并用 AST 静态复核公开方法集合；从 `static/js/pluginHost.js` 的 `buildApi()` 提取前端顶层成员。支持 `--check` 只校验 |
| 2 | 产出 | `docs/plugin-api.md`（自动生成，文件头标注「勿手工编辑」），覆盖后端 35 个公开方法与前端 21 个顶层成员，标注 Stable / Provisional |
| 3 | 同步保证 | `tests/test_plugin_api_docs.py`（18 项）断言「磁盘文档 == 当前代码重新渲染的结果」；未登记的新方法、分组表引用的不存在方法、AST 与反射不一致、前端未登记成员都会失败 |
| 4 | docstring 补全 | 为 `get_job` / `cancel_job` / `retry_job` / `pause_job` / `resume_job` / `table_prefix` 补上 docstring（原先生成的表格只能写「见设计文档 10.2」） |
| 5 | Windows 控制台 | 两个 tools 脚本在 `main()` 开头把 stdout 切到 UTF-8（`errors='replace'`）：中文 Windows 默认 GBK，直接 `print` 非 ASCII 会抛 `UnicodeEncodeError` |
| 6 | 文档入口 | `docs/DEVELOPMENT.md` 新增「插件开发」小节（脚手架、文档生成、测试命令、改契约的顺序）；`tools/README.md` 补充两个工具说明 |

**契约维护流程**：改 `core/plugins/api.py` 或 `pluginHost.js` → 先改设计文档第 10 部分 → 改实现 → `python tools/gen_plugin_api_docs.py` → 测试自动校验一致性。
