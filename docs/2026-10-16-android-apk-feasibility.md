# 打包成 Android APK 的可行性分析

> 目标：让移动端用户不再需要 Termux + 浏览器，而是安装一个 APK，直接用原生外壳访问 ST Manager，
> 并且能像原生应用一样用**侧滑手势返回上一级**（而不是被浏览器的返回吃掉、直接退出页面）。
>
> 状态：**仅分析，未实施**。本文只回答「能不能做、要改什么、坑在哪、代价多大」。

---

## 0. 结论

**技术可行，但不是「套个壳」的活。** 后端（Python/Flask/SQLite/Pillow）有成熟的嵌入式方案
（Chaquopy），前端是纯 HTML/ESM/Alpine、没有打包器依赖，这两点让 APK 化比一般 Web 应用容易得多。

真正的成本集中在三块，都不在后端运行时上：

| 排序 | 问题 | 性质 | 量级 |
|---|---|---|---|
| 1 | **文件访问模型**：整个应用是「直接读写用户磁盘目录」的文件管理器 | 产品/权限模型冲突 | 大 |
| 2 | **触摸交互层**：拖拽排序、拖拽移动、右键菜单、hover 提示在触摸屏上全部失效 | 前端改造 | 中～大 |
| 3 | **返回手势**：项目目前**完全没有历史栈**，WebView 里侧滑会直接退出应用 | 需要新增基础设施 | 中 |

外加一堆「必须补但量不大」的 WebView 适配：文件选择、下载、新窗口、明文 HTTP 放行、watchdog 失效。

**推荐路线**：Chaquopy + 单 Activity WebView + 内嵌 Flask（监听 `127.0.0.1`），
侧载分发（非 Google Play），`MANAGE_EXTERNAL_STORAGE` 保留现有「直接操作 SillyTavern 目录」的模型。
详见 §6。

---

## 1. 三条候选路线

| 路线 | 做法 | 评价 |
|---|---|---|
| **A. Chaquopy + WebView**（推荐） | APK 内嵌 CPython，`app.py` 的 Flask 跑在 `127.0.0.1:<port>`，WebView 加载该地址 | 复用 100% 现有后端与前端；只需处理「Android 环境差异」 |
| B. Termux 打包 / 引导安装 | 做一个引导 APK，自动装 Termux + 跑脚本 | 没有解决任何用户抱怨的问题（仍是 Termux + 浏览器） |
| C. 前端重写成原生 / PWA | 用 Kotlin/Compose 或 PWA 重写全部 UI | 相当于重写整个项目，与「复用现有代码」目标冲突；PWA 在 Android 上仍受浏览器返回手势支配 |

B 和 C 都不成立。下面只讨论 A。

### 为什么 A 的基础是成立的

- **依赖集极简且干净**：`requirements.txt` 只有 Flask / Pillow / requests / watchdog。
  Flask、Jinja2、Werkzeug、requests 是纯 Python；Pillow 在 Chaquopy 的 Android wheel 仓库里有现成构建；
  watchdog 是纯 Python（本机 `site-packages/watchdog` 下**没有任何 `.so`/`.pyd`/`.dll`**，它靠 `ctypes` 调 libc 的 inotify）。
- **没有进程/并发黑魔法**：全仓库 `multiprocessing` / `os.fork` / `concurrent.futures` / `ProcessPool` **各 0 处匹配**。
  后台任务全部是 `threading.Thread(daemon=True)`（`core/__init__.py:init_services`、扫描线程、索引 worker、监控调度器）。
  Chaquopy 恰好支持线程、不支持 `multiprocessing`（Android 无 System V IPC），这里正好不冲突。
- **没有前端构建链**：`package.json` 只有 Tailwind CLI 一个 devDependency，`static/css/tailwind.css` 是提交进仓库的产物；
  浏览器端是原生 ES modules + Alpine.js，`layout.html` 用 `importmap` 把 `pixi.js` 指到本地 ESM 文件。
  换句话说 **APK 里不需要 Node 构建步骤**，`static/` 和 `templates/` 原样塞进去即可。
- **没有外网 CDN 依赖**：全仓库对 `cdnjs/unpkg/jsdelivr/fonts.googleapis` 的引用只出现在 vendor 注释里，
  所有 JS/CSS/字体都是本地文件。离线可用。
- **SQLite 走标准库**，WAL 模式、参数化查询、`execute_with_retry`，没有需要替换的驱动。

---

## 2. 后端运行时核验

### 2.1 Chaquopy 现状（已核实）

| 项 | 值 |
|---|---|
| 最新版本 | 17.1.0（2026-10-12） |
| 授权 | **自 12.0.1 起完全开源免费**，无任何限制 |
| 支持 Python | 3.10 – 3.15 |
| 要求 minSdk | **≥ 24**（Android 7.0，覆盖约 97% 活跃设备） |
| 支持的 AGP | 7.3 – 9.4 |
| 可用 ABI | `arm64-v8a`、`x86_64`；`armeabi-v7a`/`x86` 仅 Python ≤ 3.11 |

**版本选择建议：Python 3.13 + `arm64-v8a`。**

理由：
1. 项目要求 Python 3.10+，3.13 满足；
2. Chaquopy 的 Android wheel 仓库里 **Pillow 最新只到 `pillow-11.0.0`（2024-10-16），且只覆盖 cp39–cp313** ——
   3.14/3.15 目前**没有 Pillow wheel**，选 3.14+ 会直接装不上；
3. Chaquopy 17.0 的更新日志明确写了：16 KB page size 设备「Chaquopy 自身已支持，但很多既有 Android wheel 仍会加载失败，
   **为获得最佳兼容性请使用 Python 3.13 或更高**」。

### 2.2 标准库可用性

Chaquopy 明确不支持：`crypt`、`grp`、`nis`、`spwd`、`curses`、`dbm.gnu`、`dbm.ndbm`、`readline`、`tkinter`、`turtle`。
`multiprocessing` 大部分 API 会失败（用 `multiprocessing.dummy` 替代）。

对本项目的核验结果：**全部命中 0 次**。项目没有 `pwd`/`grp`/`resource`/`termios`/`pty`/`signal`/`mmap`/`select` 的任何导入。
`zoneinfo` 在 3.9+ 是标准库且纯 Python 数据（`core/services/source_update_monitor_service.py` 用它做时区），可用。

### 2.3 `fcntl.flock` —— 需要实测，但大概率可用

`core/data/data_dir_lock.py` 在非 Windows 分支用 `fcntl.flock` 做数据目录独占锁。
Chaquopy 不支持模块清单里**没有** `fcntl`，且 Android bionic 的 `libc.map.txt` 里 `flock` 与 `flockfile` 都在导出符号表中
（在 API 24 的 `LIBC` 段内）。所以理论上可用，但这是**必须在真机上冒烟验证的第一项**。

失败时的后果不算致命：该模块对 `ImportError` 已退化为「跳过独占检查」（只打 warning）。

### 2.4 `BASE_DIR` —— 这是后端最硬的一处改动

`core/config.py` 顶部：

```python
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
    INTERNAL_DIR = sys._MEIPASS
else:
    _current_dir = os.path.dirname(os.path.abspath(__file__))
    BASE_DIR = os.path.dirname(_current_dir)      # ← 源码目录的父目录
    INTERNAL_DIR = BASE_DIR

CONFIG_FILE = os.path.join(BASE_DIR, 'config.json')
DATA_DIR    = os.path.join(BASE_DIR, 'data')
# 紧接着在 import 期就 makedirs 六个目录（裸 except 吞掉失败）
```

在 Chaquopy 下：
- `sys.frozen` **不会**为真；
- `__file__` 指向 **APK 内的 asset 路径**（Chaquopy 的 importer 直接从 APK 读 `.pyc`，不落盘）；
- 所以 `BASE_DIR` 会变成 APK 内的只读路径，`config.json` 与 `data/` 全部写不进去。

Chaquopy 官方明确禁止往源码目录写文件（「这些文件可能在应用升级时被删除」），并要求写 `os.environ["HOME"]`
（= 应用内部存储 `/data/data/<pkg>/files`）。

**改动面**：`BASE_DIR` 这个常量是唯一的接缝。仓库里 `BASE_DIR` 被引用约 60 处
（`core/api/v1/{system,resources,world_info,cards,presets,extensions,st_sync}.py`、`core/services/*`、`core/plugins/*`），
但它们全都是 `os.path.join(BASE_DIR, ...)` 的形式，**只要让 `BASE_DIR` 指向可写目录即可，调用点一行都不用动**。
另外 `INTERNAL_DIR` 必须继续指向只读资源目录（`static/`、`templates/`、`static/plugins/catalog.json`、
`static/icons/*.svg` 都由它读，见 `core/plugins/{icons,catalog,installer}.py`），所以**两个常量必须解耦**。

判据：`core/config.py` 加一层「Android 检测 → `BASE_DIR = os.environ['HOME']`」即可，
但要把 import 期的 `makedirs` 改成惰性/带日志（现在是 `except: pass`，出问题完全静默）。

### 2.5 `watchdog` —— 在 Android 上基本等于不可用

`core/services/scan_service.py:start_fs_watcher()` 监听 `cards_dir`、`world_info_dir`、`resources_dir`。

Android 上 `/storage/emulated/0` 是 **FUSE/sdcardfs**，**不投递 inotify 事件**；即使拿到
`MANAGE_EXTERNAL_STORAGE`，SELinux 也不允许 `untrusted_app` 域对其它应用的目录做 `inotify_add_watch`。
所以：

- `observer.schedule(...)` 会抛 `OSError` —— 这一层**已有** `try/except OSError` 保护，只会打 warning，安全；
- 但 `observer.start()`（同文件 648 行）**没有被 try 包住**。它一旦抛异常会一路冒到
  `init_services()` 最外层的大 `except Exception`，导致**后续步骤全部不执行**
  （索引 worker、来源监控调度器、插件 job worker 都不会启动），并且 `ctx` 状态被置为 `error`。

**这是当前代码里一个会在 Android 上暴露的既有健壮性缺陷**（桌面端因 inotify 可用而从未触发）。

应对：Android 上强制 `enable_auto_scan = false`（配置项已存在，默认 `True`），
并依赖已有的 `POST /api/scan_now` 手动扫描 + 已有的 `enable_startup_scan` / `startup_scan_min_interval_hours`。
建议同时把 `observer.start()` 也纳入 try/except（无论如何都该修）。

### 2.6 `subprocess` / `platform.system()` 分支

`core/api/v1/system.py` 里「打开文件夹 / 在资源管理器中显示 / 打开回收站」等 6 处用
`platform.system()` 分支：Windows → `os.startfile` / `explorer /select`，Darwin → `open`，else → `xdg-open`。

在 Android 上 `platform.system()` 返回 **`'Linux'`**，所以会走 `xdg-open` 分支 → 必然失败
（应用只能 exec 自己目录下的二进制，`xdg-open` 不存在；`try/except Exception` 会把它变成一句错误 JSON）。

值得注意的既有代码：`open_folder` 这一个分支里已经有 Termux 适配：

```python
else:
    # === Termux 适配 ===
    if "ANDROID_ROOT" in os.environ:
        subprocess.Popen(["termux-open", "--choose", path])
    else:
        subprocess.Popen(["xdg-open", path])
```

问题：APK 里 `ANDROID_ROOT` **是**被 init 设置的（`/system`），于是会尝试 `termux-open` —— 而 APK 里没有 Termux，
必然 `FileNotFoundError`。而且这个 Termux 分支**只存在于 `open_folder` 一处**，
`open_notes` / `open_card_dir` / `trash/open` / `open_resource_folder` / `open_path` 都没有。

结论：这些「打开系统文件管理器」的入口在 APK 里必须整体换成 Android Intent
（`ACTION_VIEW` + `content://` URI，或 SAF 目录选择器）。属于「功能降级/替换」，不是阻塞。

### 2.7 其它后端项

| 项 | 状态 |
|---|---|
| `core/auth.py` 白名单 | **天然兼容**：默认白名单含 `127.0.0.1`/`::1`，WebView 走 loopback → 免登录，不需要动认证 |
| `core/plugins/secrets.py` 权限收紧 | `os.name == 'posix'` 下 `chmod 0600`，Android 上有效；无害 |
| `sqlite3` + WAL | 标准库，Chaquopy 17.1 起「启用了包括 **FTS5** 在内的若干 SQLite 特性」 |
| **FTS5 依赖** | 项目强依赖：`index_search_fast_v2` / `index_search_full_v2` 都是 `USING fts5(...)`，`core/utils/search_text.py` 专门做 CJK 切分配合 `unicode61`。**这要求 Chaquopy ≥ 17.1**（17.0 及以前 FTS5 未启用）—— 这是一个硬版本下限 |
| `webbrowser.open` | `app.py` 启动后自动开浏览器；APK 里应改为「让 WebView 加载该 URL」，或直接删掉这一步 |
| `app.run(use_reloader=debug)` | 生产路径 `debug=False`，不用 reloader，没有双进程问题 |
| Flask `threaded` | Flask 3.x 默认 `threaded=True`，Chaquopy 支持线程，OK |
| SSE（`EventSource`） | `core/plugins/{routes,jobs}.py` 用 `Response(..., mimetype='text/event-stream')`；WebView 支持 EventSource，OK |
| `send_file(..., conditional=True)` / Range | 插件静态资源支持 Range；WebView 支持，OK |

---

## 3. 文件访问模型 —— 最大的产品级冲突

这是整个 APK 化里唯一需要「做决策」而不是「做适配」的地方。

### 现状

ST Manager 的本质是**一个直接操作磁盘目录的文件管理器**：

- 配置里是**可配置的目录路径**（`cards_dir`、`world_info_dir`、`chats_dir`、`presets_dir`、`beautify_dir`、
  `resources_dir`…，支持绝对路径），默认在 `data/library/*` 下；
- 全仓库 `os.walk` 35 处、`os.listdir` 44 处、`open()` 115 处、`os.path.*` 1836 处、`shutil.*` 62 处；
- 「发送到 SillyTavern」是**直接写 ST 的 `data/<user>/{characters,chats,worlds,OpenAI Settings,settings.json}`**；
- 回收站是 `data/system/trash` 里的真实目录移动。

### Android 上的限制

| 位置 | 可访问性 |
|---|---|
| 应用内部存储（`/data/data/<pkg>/files`） | 完全可读写，标准 POSIX 文件 API 全部可用 |
| 外部共享存储（`/storage/emulated/0/...`，即用户的 SillyTavern 目录所在） | API 29+ 起 scoped storage 默认**禁止直接路径访问**，**即使申请了 `READ_EXTERNAL_STORAGE` 也不行**（Chaquopy 官方 FAQ 明确说明） |

要恢复「直接路径读写 /sdcard」的能力，只有两条路：

1. **`MANAGE_EXTERNAL_STORAGE`（"所有文件访问权限"）**
   - 用户在系统设置里手动授权；授权后标准 `os.walk`/`open` 直接可用，**现有代码几乎不用改**；
   - Google Play **严格限制**该权限（只给文件管理器/备份/杀毒/文档管理类应用），所以**不能上架 Play**；
   - 仍然访问不到别的应用的 `/Android/data`、`/Android/obb`（这两处 SillyTavern 一般不会装在那）；
   - **inotify 在 /storage/emulated/0 上依然不工作**（见 §2.5）。

2. **SAF（Storage Access Framework）**
   - 通过系统目录选择器拿到 `content://` tree URI，逐个文件读写；
   - 与现有「路径字符串 + `os.path` + `os.walk`」模型**根本不兼容**，等于把文件层整个重写成 DocumentFile 抽象；
   - 成本极高，且失去 `os.utime`/`os.rename`/硬链接/权限位等语义。

### 结论

**如果目标是「保留现有功能与工作流」→ 必须走 1（`MANAGE_EXTERNAL_STORAGE` + 侧载）。**
如果目标是「上 Google Play」→ 文件模型要重做，工作量数倍于 APK 化本身，不建议。

补充：Termux 之所以现在能直接读写 /sdcard，是因为它把 `targetSdkVersion` 压到 28（legacy external storage 豁免）
并通过 `termux-setup-storage` 申请权限。APK 也可以用同样的「targetSdk 压低」技巧，但这属于
非官方、随 Android 版本收紧而随时失效的做法，**不建议**作为主方案（可作为兼容旧设备的备选）。

---

## 4. WebView 前端兼容性

### 4.1 CSS 特性门槛 —— 这是「能否在低端机跑起来」的硬指标

对 `static/css/**`（不含 `tailwind.css` 产物）的统计：

| 特性 | 出现次数 | 最低 Chrome/WebView |
|---|---|---|
| `color-mix()` | **1308** | **111**（2023-03） |
| `dvh` 单位 | 156 | 108 |
| `:has()` | 25 | 105 |
| `@container` | 0 | — |
| CSS 嵌套 | 0 | — |

**绑定约束是 `color-mix()` → 需要 Android System WebView ≥ 111。**

- 有 Play Store 的设备：WebView 随 Play 更新，2023 年之后的设备基本都满足；
- **无 Play Store 的国内 ROM / AOSP 定制机**：WebView 可能停留在很老的版本，`color-mix()` 不支持会让
  **大量半透明背景、边框、阴影整条声明失效**（不是「稍微难看」，是颜色直接不生效）。1308 处意味着这不是边角料。

应对（按成本排序）：
1. 启动时读 `navigator.userAgent` 里的 Chrome 版本，低于 111 时给出明确提示（最省事）；
2. 构建期加一个 PostCSS/闪电式预处理，把 `color-mix()` 展开成静态 rgba 兜底（Tailwind 已在用 PostCSS，管线存在）；
3. 打包一个自带的内核（腾讯 X5 / 系统 WebView 独立分发）——成本高，不建议。

`:has()`（25 处，最低 105）与 `dvh`（156 处，最低 108）门槛更低，且项目已对 `dvh` 做了
`--app-viewport-height` 的 JS 兜底（`static/js/state.js` 用 `visualViewport` 计算并写 CSS 变量），
说明这块作者已经有意识，风险不大。

### 4.2 触摸交互 —— 第二大改造面

| 交互 | 现状（统计） | 触摸屏上的后果 |
|---|---|---|
| HTML5 拖放 | `draggable="true"` **10 处**、`@drop` **25 处**（卡片拖到文件夹、文件夹拖动、标签排序、世界书条目排序、剪贴板重排、入口坞排序…） | **完全失效**。HTML5 DnD 不响应触摸事件，`dragstart` 不会触发 |
| 右键菜单 | `@contextmenu.prevent` **11 处**（文件夹菜单、卡片/世界书/预设的快照） | 长按能触发 `contextmenu`，但行为与桌面不一致；`preventDefault` 后无替代手势 |
| hover 提示 | 全局 `title=` → `data-tooltip`（`static/js/utils/tooltip.js`），但该文件**显式跳过触摸**（`if (event.pointerType === "touch") return;`） | 所有 `title=` 提示在手机上**永远不会显示** |
| 框选 | `marqueeSelection.js` 只在 `pointerType === 'mouse'` 下工作 | 批量选择失去主要入口（需依赖已有的「全选/多选」按钮） |
| 键盘快捷键 | `Escape` 关闭弹窗、命令面板（`commandPalette.js`）、`@keydown` 大量使用 | 手机无键盘，需要等效的可见按钮 |

其中**拖放是硬伤**：卡片移动到文件夹、标签排序、世界书条目排序、预设排序、入口坞排序等核心操作，
在触屏上需要改成 pointer-events 长按拖拽，或提供「选择目标文件夹」的对话框替代（项目里已经有
`moveCardsModal.js` / `folderOperations.js`，可以作为触屏降级入口）。

好消息：项目的移动端布局**已经存在且相当完整**（README 有 14 组移动端截图，`layout.js` 按
`innerWidth < 900` 切 `deviceType='mobile'`，CSS 里有 156 处 `dvh`、大量 `env(safe-area-inset-*)` 适配、
`overscroll-behavior: contain`）。所以是「补齐触摸交互」而不是「重做移动端」。

### 4.3 返回手势 —— 用户抱怨的那一条

**现状核验：项目里没有任何 SPA 历史栈。**

- `pushState` / `replaceState` / `popstate` / `location.hash`：在项目自有 JS 中 **0 处**
  （只在 vendored 的 `jquery-3.5.1.min.js`、`jquery-ui.min.js` 里出现）；
- `window.history` / `history.back` / `onpopstate`：**0 处**；
- 页面切换靠 `x-show`（模板里 **1205 处**）+ `$store.global.currentMode`；
- 弹窗靠 `x-show` 控制 `display`，层级靠**手工调好的 z-index**
  （`--z-modal` 1000 / `--z-modal-std` 1100 / `--z-modal-popover` 3400，
  `gachaDraw.js` 的注释明确写了「`.gacha-overlay` 的 z-index 被压到 1000，低于详情页的 1100」这种手工排序），
  **没有统一的弹窗栈管理**。

所以在浏览器里：打开详情 → 打开设置 → 按返回 → 浏览器回退到上一个 URL（或退出），
而不是关闭最上层弹窗 —— 这正是用户描述的痛点。

在 WebView 里如果什么都不做，情况**更糟**：WebView 只有一个历史项，
系统返回手势会直接**退出应用**（因为 `webView.canGoBack()` 为 false）。

**必须新增的基础设施**：
1. 一个**弹窗/视图栈**（记录「打开了什么」，按 LIFO 关闭）；
2. 每次入栈 `history.pushState(state, '', '#' + key)`，监听 `popstate` 关闭栈顶；
3. WebView 侧 `OnBackInvokedCallback`（Android 13+ 预测性返回）/ `onBackPressed` 先问
   `webView.canGoBack()`，为 true 就 `goBack()`，为 false 才交还系统（此时才真正退出）；
4. 处理「栈顶是弹窗」与「栈顶是工作区切换（cards → wi → chats）」的优先级。

现有代码的**有利条件**：`Escape` 关闭弹窗的逻辑已经分散存在（`uiPrimitives.js`、`advancedEditor.js`、
`presetEditor.js`、`wiEditor.js`、`sidebar.js`、`entryDock.js`、`commandPalette.js` 等 18 处），
可以以此为「关闭栈顶」的统一语义抽一层出来，改造成本可控。

### 4.4 WebView 必须补的宿主能力（缺一个就有一个功能瞎掉）

| 前端用法 | 位置 | WebView 需要 |
|---|---|---|
| `<input type="file">` **29 处** | `detail_card.html`、`grid_*.html`、`settings.html`、`plugin_manager.html`、`file_update_dropzone.html` … | `WebChromeClient.onShowFileChooser()` + `startActivityForResult`（**不实现则「选择文件」完全无反应**） |
| 拖放上传文件 | 各处 `@drop` 读 `e.dataTransfer.files` | 与 §4.2 同源问题，触屏无 DnD |
| blob 下载 | `static/js/utils/download.js`（`URL.createObjectURL` + `<a download>`）、`wiHelpers.js`、`presetEditor.js`、`advancedEditor.js`、`chatGrid.js` | `WebView.setDownloadListener()`；**`blob:` 下载在 WebView 里默认不工作**，需要 `DownloadListener` + 自己写文件（导出 JSON/PNG/备份全靠它） |
| `window.open(url, '_blank')` | `automationModal.js:381`、`forumThreadPreview.js`、模板里大量 `target="_blank"` | `WebSettings.setSupportMultipleWindows(true)` + `WebChromeClient.onCreateWindow()`，否则点击无反应 |
| `navigator.clipboard.writeText` | `presetDetailReader.js:1494` | 需要 secure context —— `http://127.0.0.1` 属于 potentially trustworthy origin，**OK** |
| `EventSource` | `pluginHost.js` | 支持 |
| `localStorage` | `state.js`、`chatGrid.js`、`entryDock.js`、`gachaDraw.js`、`wiSort.js`、`sidebar.js` | 支持（需确保未开启「无痕/清除数据」类设置） |
| `iframe` + `srcdoc` + `blob:` | `runtime/{chatAppStage,renderRuntime,scriptRuntime}.js`（聊天渲染、预览沙箱） | 支持；注意 `srcdoc` 继承不到宿主 CSS 变量（项目已用 `previewColorTokens.js` 处理过） |

### 4.5 网络 / 安全

| 项 | 说明 |
|---|---|
| **明文 HTTP** | `targetSdk ≥ 28` 起 Android 默认**禁止明文流量**。WebView 加载 `http://127.0.0.1:5000` 也需要显式放行：`android:usesCleartextTraffic="true"`，或更精确的 `network_security_config.xml` 只为 `127.0.0.1` 开 `cleartextTrafficPermitted`。**漏了会白屏** |
| `INTERNET` 权限 | 即使只连 loopback 也必须声明（Android 要求任何 socket 都需该权限） |
| 端口 | `app.py` 默认 `127.0.0.1:5000`；APK 里建议随机空闲端口（`core/utils/net.py:is_port_available` 已有检测逻辑），避免与设备上别的服务撞车 |
| 认证 | loopback 命中白名单 → 免登录，无需处理 |
| 安全响应头 | `core/utils/security_headers.py` 只加 `nosniff` + `Referrer-Policy`，无全站 CSP，对 WebView 无影响 |
| 后台存活 | 长扫描/索引任务期间若应用退到后台，进程可能被回收。需要前台服务（`FOREGROUND_SERVICE` + 常驻通知）或至少接受「切后台即暂停」 |

---

## 5. 体积

### 需要打进 APK 的资产（实测）

| 目录 | 大小 |
|---|---|
| `static/` | **38.39 MB** |
| ├ `assets/`（6 张壁纸） | 13.97 MB |
| ├ `vendor/sillytavern/`（**其中 webfonts 9.25 MB**） | 11.70 MB |
| ├ `images/`（含 gacha `pack.png` 1.46 + `card-back.png` 1.47） | 5.69 MB |
| ├ `lib/`（pixi、cards-css、pokemon-cards-css、CodeMirror 等） | 2.78 MB |
| ├ `js/`（含 325 KB 的 `chatGrid.js`、166 KB 的 `detailModal.js`） | 2.31 MB |
| ├ `css/` | 1.51 MB |
| └ `icons/` | 0.42 MB |
| `templates/` | 1.56 MB |
| `core/`（102 个 `.py`，48,770 行含 `app.py`） | 4.46 MB |
| **合计（不含 tests/data/node_modules/docs）** | **44.43 MB** |

`tests/`（19.9 MB）、`docs/`（10.0 MB）、`data/`、`node_modules/`、`build/`、`tmp/`、`dsh-image-gen/` 都不需要打包。

### 估算

- 文本资源（py/html/js/css/json/svg）压缩率约 3–4×：约 12.3 MB → ~3.5 MB
- 二进制资源（PNG/JPEG/woff2）几乎不压缩：约 29 MB → ~28 MB
- 所以**前端资源在 APK 里约 31–32 MB**
- 加 Python 运行时（Chaquopy 官方说明：**每个 ABI 会增加数 MB**）+ Pillow wheel + 纯 Python 依赖：**约 10–15 MB/ABI**

**结论：**

| 打包方式 | 预估 APK |
|---|---|
| `arm64-v8a` 单 ABI | **约 45–50 MB** |
| 通用包（arm64 + armeabi-v7a 或 + x86_64） | 约 60–75 MB |

**瘦身空间（不损功能）**：`vendor/sillytavern/webfonts` 9.25 MB 是 ST 预览壳的字体，可以按需裁剪；
6 张壁纸 13.97 MB 可只保留 1–2 张或改为首次运行时下载；gacha 两张图 2.93 MB 可降分辨率。
**这三项合计可省约 20 MB**，能把单 ABI APK 压到 **30–35 MB**。

建议直接用 `abiFilters` 只出 `arm64-v8a`（Chaquopy 明确说 APK splits / app bundle 对它的 native 组件帮助不大，
用 product flavor 分 ABI 更有效）。

---

## 6. 推荐方案（若决定实施）

### 架构

```
┌─────────────────────────────────────────────┐
│ Android App (minSdk 24, targetSdk 34)       │
│                                             │
│  MainActivity                               │
│   └─ WebView ──► http://127.0.0.1:<port>    │
│        • onShowFileChooser   (29 处文件输入) │
│        • DownloadListener    (blob 导出)     │
│        • onCreateWindow      (target=_blank) │
│        • OnBackInvokedCallback → JS 弹窗栈   │
│                                             │
│  Foreground Service                         │
│   └─ Chaquopy CPython 3.13                  │
│       └─ Flask app (core.create_app)        │
│           • BASE_DIR → $HOME (可写)          │
│           • enable_auto_scan = false        │
│           • 端口 = 随机空闲端口               │
└─────────────────────────────────────────────┘
        │ MANAGE_EXTERNAL_STORAGE
        ▼
   /storage/emulated/0/SillyTavern/...  ← 现有代码原样可用
```

### 分阶段

**阶段 0：可行性冒烟（1 天，必须先做）**
用 Chaquopy 官方 demo 骨架，只验证 4 件事：
1. `import fcntl; fcntl.flock(...)` 在真机上是否可用；
2. `import PIL.Image` 并做一次 `resize`；
3. `import sqlite3` 建一个 `USING fts5(...)` 虚拟表（**验证 FTS5 是否真的启用**）；
4. `from core import create_app` 能否在 Android 上 import 成功（大概率**失败**，因为 `core/config.py` 的 import 期 `makedirs`）。

任何一项失败，后面的估算都要重做。

**阶段 1：后端跑起来（3–5 天）**
- `core/config.py` 加 Android 检测，`BASE_DIR` 指向 `os.environ['HOME']`，`INTERNAL_DIR` 保持只读资源目录；
- import 期 `makedirs` 改为惰性 + 真实日志；
- `observer.start()` 补 try/except；
- 端口改为随机空闲；
- 去掉/替换 `webbrowser.open`；
- `core/api/v1/system.py` 的 6 处「打开文件管理器」换成 Intent 或暂时隐藏入口。

**阶段 2：外壳可用（3–5 天）**
- `AndroidManifest.xml`：`INTERNET`、`MANAGE_EXTERNAL_STORAGE`、`FOREGROUND_SERVICE`、
  `usesCleartextTraffic` 或 `network_security_config`；
- WebView 四个宿主回调（文件选择、下载、新窗口、返回）；
- 首次启动引导用户去系统设置授权「所有文件访问权限」。

**阶段 3：交互补齐（1–2 周，最大块）**
- **弹窗/视图栈 + `pushState`/`popstate`**（解决返回手势，也是用户的核心诉求）；
- 拖放降级：卡片移动→复用 `moveCardsModal`；标签/条目排序→加「上移/下移」或长按拖拽；
- `title=` 提示在触摸下的替代（长按显示，或关键位置改为常驻说明）；
- 右键菜单改为长按。

**阶段 4：体验打磨 + 分发（1 周）**
- WebView 版本门槛检测（`color-mix()` → Chrome 111）；
- 体积瘦身（裁 webfonts / 壁纸 / gacha 图）；
- CI（GitHub Actions 加 `assembleRelease`，与现有 `build-desktop.yml` 并列）；
- 侧载分发说明（AGPL-3.0 与 `LICENSE` 里 vendored 资源的 notice 要求需一并检查）。

**粗估：4–6 周**（单人、熟悉 Android 构建的前提下）。其中真正「APK 化」的部分约 2 周，
剩下 2–4 周是**触摸交互与返回手势的产品化改造** —— 这部分即使不做 APK、只在移动浏览器里也值得做。

---

## 7. 风险清单

| 风险 | 影响 | 应对 |
|---|---|---|
| Pillow 的 Android wheel 停在 11.0.0（2024-10），**16 KB page size 设备可能加载失败** | 新机型（部分 Android 15+ 设备默认 16 KB 页）上崩溃 | 选 Python 3.13；真机验证；必要时自己构建 wheel |
| Chaquopy wheel 仓库里 **3.14/3.15 没有 Pillow** | 无法用最新 Python | 锁定 3.13 |
| `fcntl.flock` 在 bionic 上的实际行为 | 数据目录锁失效（有降级，不致命） | 阶段 0 实测 |
| FTS5 需 Chaquopy ≥ 17.1 | 全文搜索/快速索引不可用 | 锁定 Chaquopy 17.1+ |
| 无 Play Store 的设备 WebView < 111 | `color-mix()` 1308 处失效，UI 大面积失色 | 版本检测 + 提示，或构建期展开 `color-mix()` |
| `MANAGE_EXTERNAL_STORAGE` 被用户拒绝 | 应用完全不可用 | 首次启动强引导 + 明确文案 |
| inotify 在 FUSE 上无效 | 文件变化不自动刷新 | 关 `enable_auto_scan`，用「手动扫描」按钮 + 下拉刷新 |
| 后台被系统回收 | 长任务中断 | 前台服务 + 常驻通知 |
| AGPL-3.0 + vendored 资源（`cards-css`、`pokemon-cards-css`、`pack-opener`、ST 资源）的分发义务 | 合规问题 | 打包前核对各目录 notice 文件 |

---

## 8. 不建议做的事

1. **不要为了上 Google Play 去重写文件层为 SAF。** 那等于重写整个 `core/api/v1/` + `core/services/`，
   工作量是 APK 化的 3–5 倍，且会丢掉 `os.utime`/`rename`/权限位等现有依赖的语义。
2. **不要用 `targetSdk 28` 的老套路绕过 scoped storage。** 能work，但随 Android 版本收紧随时失效，
   且与「APK 化是为了长期可维护」的初衷相反。
3. **不要试图打包一个自带浏览器内核（X5 等）来绕开 WebView 版本问题。** 体积与维护成本都不划算，
   版本检测 + 提示足够。
4. **不要在 APK 里继续用 `webbrowser.open` 走系统浏览器。** 那样返回手势问题原样保留，
   等于白做 APK。
5. **不要把「Termux 适配」当成 APK 方案。** 现有那处 `termux-open` 分支在 APK 里必然失败，
   是**要删掉**的代码，不是要扩展的代码。
