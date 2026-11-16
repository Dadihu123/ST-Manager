# Android 壳工程（ST Manager Pro）

> 本目录是「ST Manager 的原生 Android 外壳」。
> 设计依据：`docs/2026-10-16-android-apk-feasibility.md`、
> `docs/2026-11-12-multi-target-release-addendum.md`、
> `docs/2026-11-12-three-platform-refactor-plan.md`。
>
> **状态（2026-11-15）：已完成本机 APK 构建及 Mi 10 Pro / Android 14 的目录操作真机复验。**
> 系统目录入口显隐、应用内资源浏览、配置与用户 DB 备份实际落盘均已验证；既有记录包含返回手势验证。
> Kotlin 测试、APK 打包与 Chromium 回归测试通过；Android 7–9 保存选择器和 Android 15 行为仍需对应设备覆盖。
> CI 工作流为 `.github/workflows/build-android.yml`。

---

## 1. 它是什么

一个 **单 Activity + WebView** 的外壳，内部嵌入 CPython 跑现有的 Flask 应用：

```
┌──────────────────────────────────────────────┐
│ MainActivity (WebView)                       │
│   └─► http://127.0.0.1:17863             │
│        • onShowFileChooser  (29 处文件输入)   │
│        • DownloadListener   (blob 导出)       │
│        • onCreateWindow     (target=_blank)   │
│        • 返回键 → __stmHostBack()             │
│                                              │
│ BackendService（前台服务 + 常驻通知）          │
│   └─ Chaquopy CPython 3.13                   │
│       └─ android_shell/boot.py:start_server  │
│           └─ core.create_app() + init_services│
└──────────────────────────────────────────────┘
```

**关键设计：不改业务代码。** 壳只提供「宿主能力」，业务仍由仓库里同一套
`core/` 跑起来。这与 iOS 完全一致（iOS 用 WKWebView + 同一份 Python）。

## 2. 已经落地的部分

| 能力 | 位置 | 对应仓库既有逻辑 |
|---|---|---|
| 内嵌 CPython + Flask | `app/src/main/python/android_shell/boot.py` | 复用 `core.create_app()`、`init_services()` |
| 稳定页面 origin | `boot.py: make_server` 固定绑定 17863 | 保留 localStorage；占用时报告启动失败 |
| 只监听 loopback | `boot.py: make_server('127.0.0.1', ...)` | 与桌面端一致，不对外暴露 |
| 关自动扫描 | `boot.py: enable_auto_scan=False` | 对应 `CAN_WATCH_FILESYSTEM=False`（FUSE 不投递 inotify） |
| 文件选择 | `MainActivity.onShowFileChooser` | 29 处 `<input type=file>` |
| blob 下载 | `saveBlobToHost` + `MainActivity.saveBase64FileAsync` | API 29+ 写 MediaStore；API 24–28 由系统创建文档，完成写入后回报结果 |
| 新窗口 | `MainActivity.onCreateWindow` | `target="_blank"`、`window.open` |
| 返回键 | `MainActivity` 调 `__stmHostBack()` | 复用 `static/js/utils/viewStack.js` |
| 原生能力桥 | `WebViewCompat.addWebMessageListener` + `NativeBridgePolicy` | 只接受固定 loopback origin 的顶层消息；业务沙盒不能调用原生能力 |
| 所有文件访问权 | `MainActivity.requestStorageAccess` | 仅保存变更路径时按需申请，读写验证成功才保存；解析/规范化失败返回 false |
| Android 10 外部目录 | Manifest 的 `requestLegacyExternalStorage` | API 29 授权后允许直接路径读写；API 30+ 继续申请所有文件访问权 |
| 明文 HTTP 放行 | `res/xml/network_security_config.xml` | 只对 loopback，不全局放开 |

## 3. 环境：本机需要装什么（以及能不能用 WSA）

### 3.1 本机当前状态（2026-11-14 实测）

| 组件 | 状态 |
|---|---|
| Python 3.12 / 3.13 | ✅ 有；构建使用 3.13 |
| JDK 17 | ✅ 有 |
| Gradle | ✅ 使用仓库 wrapper |
| Android SDK | ✅ 有；API 35 |
| adb | SDK 提供；Mi 10 Pro / Android 14 已完成本轮目录操作与备份导出验收 |

构建验证使用 `gradlew.bat :app:testDebugUnitTest :app:assembleDebug`。
Kotlin 单元测试覆盖下载失败回收、消息来源与主框架门禁、非法路径失败和重试。
Chromium 验证实际组件返回、沙盒不安装宿主 facade；这两类测试不能替代 Android WebView
回调和系统生命周期验证。API 24–28 的系统保存页面与 API 29 外部目录授权仍需对应系统设备验收。

安全消息通道要求系统 WebView 支持 `WEB_MESSAGE_LISTENER`。不支持时显示更新提示，
不会退回向所有 iframe 注入宿主对象的旧接口。目录暂时不可访问时，扫描回滚元数据和历史清理，
状态栏显示“资源目录不可访问”；恢复权限后可重新扫描。
首次升级时，历史表建表与资源路径转换分开执行。路径转换失权会回滚并保留待重试的旧根，
不阻断扫描器、索引 worker 和设置等恢复入口；权限恢复后的历史访问或扫描会自动重试，
转换完成前不清理孤儿历史。
世界书索引重建同样要求完整读取：目录枚举或文件访问失败时保留旧活动索引和搜索格式版本，
清除未完成的 generation 并显示可重试错误；恢复后可重建，下次启动也会再次安排失败的升级。
活动索引的增量更新也保持原子性：全局世界书、内嵌和资源的访问失败会回滚，
owner 内部及共享资源的多个 owner 全部成功后才提交，避免重建失败后的积压任务破坏旧索引。

### 3.2 要在本机构建，最少需要

| 组件 | 版本 | 用途 | 体积 |
|---|---|---|---|
| **JDK 17** | Temurin 17 | Gradle/AGP 必需 | ~180 MB |
| **Android SDK** | platform 35 + build-tools 35 | 编译 APK | ~1.5 GB（含 emulator 会更多） |
| **Python 3.13** | 与 `chaquopy.version` 一致 | Chaquopy 编译 `.pyc`（缺了会退化为设备端编译，启动变慢） | ~30 MB |
| Gradle 8.11 | — | 由 wrapper 自动下载 | ~130 MB |

**逐步安装清单见 `docs/2026-11-13-windows-android-build-setup.md`**
（含 winget 命令、sdkmanager 包名、真机 adb 调试、验收清单与报错对照表）。

**最省事的装法**：装 **Android Studio**（自带 SDK Manager、JDK、模拟器），
再单独装 Python 3.13。命令行党可以只装 `commandlinetools` + `sdkmanager`。

### 3.3 用 Windows 11 的 Android 支持（WSA）行不行？

**不行，这条路已经关了。** 事实：

- **WSA（Windows Subsystem for Android）已于 2025-03-05 从 Microsoft Store 下架**，
  Amazon Appstore 同步停止（来源：[Microsoft Learn WSA 页](https://learn.microsoft.com/en-us/windows/android/wsa/)）。
- 即使当年没下架，WSA 的定位也是**运行** Android 应用，不是**构建**；
  构建仍然需要 JDK + Android SDK。
- WSA 当年对 `MANAGE_EXTERNAL_STORAGE` 与 `/storage/emulated/0` 的映射也和真机不同，
  用它验证「直接读写用户 SillyTavern 目录」并不可靠。

**可用的替代（按推荐度）：**

| 方案 | 能否构建 | 能否验证触摸/返回手势 | 说明 |
|---|---|---|---|
| **GitHub Actions（ubuntu runner）** | ✅ | ❌ | **已配好**（`build-android.yml`）。runner 预装 Android SDK，只缺 JDK/Python，workflow 里都装了。免费（公开仓库） |
| **本机装 SDK + 真机 adb** | ✅ | ✅ | 最接近发布形态；需要 USB 调试或无线调试 |
| **本机 SDK + Android 模拟器** | ✅ | 🟡 | 模拟器能验证布局与基本交互，但**触摸长按/侧滑的手感与真机差异大** |
| WSA | ❌ | ❌ | 已下架 |

> **给当前阶段的建议**：先在 CI 跑通 `assembleDebug`（证明工程能构建），
> 再借一台安卓真机用 `adb install` 验证 WebView 外壳与返回手势。
> 触摸长按（`data-long-press-menu`）与拖拽降级**必须真机验收**，模拟器不可信。

### 3.4 本机构建命令（装好 SDK 后）

```bash
# 0) 先生成离线依赖（首次构建必须；wheelhouse 不入库）
python tools/build_android_wheelhouse.py

cd android
# 1) 指向你的 SDK（或设 ANDROID_HOME 环境变量）
echo "sdk.dir=C:\\Users\\<you>\\AppData\\Local\\Android\\Sdk" > local.properties

# 2) Chaquopy 需要同版本 python 在 PATH 上
python --version   # 必须是 3.13.x

# 3) Kotlin 行为测试和打包
./gradlew :app:testDebugUnitTest :app:assembleDebug  # Windows 使用 .\gradlew.bat
# 产物：app/build/outputs/apk/debug/app-debug.apk
```

> `android/wheelhouse/` 被 `.gitignore` 忽略：15 个 wheel 共 2.4 MB，
> 且能由 `tools/build_android_wheelhouse.py` 完整重建。CI 在构建前自动跑该脚本。

## 4. 已知限制与未完成项

| # | 项 | 说明 |
|---|---|---|
| 1 | **设备覆盖尚不完整** | Mi 10 Pro / Android 14 已验证目录入口、应用内浏览与备份导出；Android 7–9 系统保存页面及 Android 15 超时仍需对应设备验收 |
| 2 | **系统目录浏览有边界** | 已删除旧 `openFolder` 跳存储设置的占位逻辑；不支持的系统目录入口隐藏，私有资源通过应用内浏览与导出访问，见下表 |
| 3 | **触摸拖放采用替代操作** | 触摸端关闭原生拖拽，避免与长按冲突；角色卡移动使用批量操作，其他拖放场景仍需逐项适配 |
| 4 | **`MANAGE_EXTERNAL_STORAGE` 不能上 Google Play** | 本项目走侧载分发；若将来要上架需重做文件层（不推荐） |
| 5 | **API 30 以下的存储权限** | `minSdk 24` 时 Android 10 及以下还需 `READ/WRITE_EXTERNAL_STORAGE` 运行时权限，变更外部路径时按需申请；默认私有目录无需授权 |
| 6 | **首次启动要解包 38 MB assets** | `BackendService.extractAssetsToFiles` 把 assets 解到 `$HOME/.shell-resources`，首次启动会慢几秒（按内容摘要缓存，完整解包才写标记） |
| 7 | **只出 arm64-v8a** | 老设备（armeabi-v7a）装不了。加 ABI 会让 APK 接近翻倍，属有意取舍 |
| 8 | **未开 R8/混淆** | `isMinifyEnabled = false`。Chaquopy 对 R8 有额外要求，且 APK 体积主要来自 Python 运行时与 assets，收益有限 |

### 移动端文件操作

系统目录按钮由后端能力与客户端环境共同决定，不使用屏幕宽度判断：本机桌面保留；Android/iOS 客户端、平板和远程浏览器访问隐藏，避免在服务端电脑上意外打开窗口。

| 操作 | 移动端行为 |
|---|---|
| 角色卡、世界书、聊天等浏览与编辑 | 复用应用内工作区，支持应用私有目录 |
| 角色卡资源栏“浏览” | 进入已有的应用内资源页；系统目录另设桌面按钮 |
| 文件导入、导出 | 保留系统文件选择与下载；Android 10+ 导出写系统下载目录，Android 7–9 选择保存位置 |
| 配置备份、用户 DB 备份 | 直接下载 JSON，不要求进入后端目录取文件；不包含角色卡等资源原文件 |
| 时光机 | 保留查看、比较与恢复；隐藏“打开备份目录” |
| 回收站 | 保留清空；隐藏“打开”；当前没有应用内逐项浏览/恢复入口 |
| 设置中的路径与外部目录 | 保留路径配置及按需授权；隐藏系统目录快捷按钮。SAF 文档 URI 不能直接填入真实路径字段 |

2026-11-15 真机复验：13 个系统目录入口均隐藏，卡片“浏览”进入应用内资源页；
配置与用户 DB 的 JSON 备份均收到原生成功回调，并在系统 Download 目录确认落盘，
文件大小和 SHA-256 与 HTTP 附件一致。

应用能读写自己的 `filesDir`，不代表外部文件管理器有权限进入 `/data/user/0/<包名>/files`。
`ACTION_OPEN_DOCUMENT_TREE` 用于选择并授权共享文档目录，不是浏览应用私有目录的替代方案；
`content://` 需要 URI 授权及 Provider 支持，不能把文件路径换个前缀就打开。
当前不提供通用文件管理器或 DocumentsProvider；私有目录里的业务文件通过各工作区使用，需带出应用时导出。
若将来需要把整个私有资源库暴露给系统“文件”，应单独实现 DocumentsProvider，并处理目录授权与文件操作。
参见 Android 官方的[应用专属存储](https://developer.android.com/training/data-storage/app-specific)与
[共享文档访问](https://developer.android.com/training/data-storage/shared/documents-files)。

## 3.5 发布流程（签名 + Release）

### 版本号

**单一来源是仓库根的 `core/version.py` 的 `APP_VERSION`**，桌面端也用它。
`app/build.gradle.kts` 在配置阶段读取并推导：

| 字段 | 来源 |
|---|---|
| `versionName` | `APP_VERSION` 原值（如 `1.2.0`） |
| `versionCode` | `major*10000 + minor*100 + patch`（`1.2.0` → `10200`） |

`versionCode` 必须严格递增，否则覆盖安装失败；因此 gradle 里有
`minor < 100 && patch < 100` 的守卫，避免 `1.100.0` 与 `2.0.0` 撞车。

发版时**只需改 `core/version.py` 并打 tag**，Android 版本自动跟上。
`tests/test_android_version.py` 断言这两处不会漂移。

### 签名

密钥材料**全部来自环境变量，绝不入库**：

| 变量 | 用途 |
|---|---|
| `ANDROID_KEYSTORE_PATH` | keystore 文件路径 |
| `ANDROID_KEYSTORE_PASSWORD` | keystore 口令 |
| `ANDROID_KEY_ALIAS` | key 别名 |
| `ANDROID_KEY_PASSWORD` | key 口令 |

四个**全有且文件存在**才启用签名；缺任何一个时 release 变体产出
`app-release-unsigned.apk` 并打印提示——本地只跑 debug 时不会被拦住。

本地签一次：

```bash
export ANDROID_KEYSTORE_PATH=/path/to/release.keystore
export ANDROID_KEYSTORE_PASSWORD=...
export ANDROID_KEY_ALIAS=...
export ANDROID_KEY_PASSWORD=...
cd android && ./gradlew :app:assembleRelease
# 产物：app/build/outputs/apk/release/app-release.apk
```

> ⚠️ 变量名刻意与 `SigningConfig` 属性名不同（`envKeyAlias` vs `keyAlias`）。
> 写成同名会让 `this.keyAlias = keyAlias` 静默丢赋值，
> 报错是 `SigningConfig "release" is missing required property "keyPassword"`。

### CI

`.github/workflows/build-android.yml`：

- **push / PR**：只出 debug 包，验证编译与单测。
- **tag（`v*`）**：额外签出 release 包，`apksigner verify` 校验后
  命名为 `ST-Manager-Pro-<ver>-android-arm64.apk` 并挂到 GitHub Release。

所需 4 个 Secret：`ANDROID_KEYSTORE_PASSWORD`、`ANDROID_KEY_ALIAS`、
`ANDROID_KEY_PASSWORD`、`ANDROID_KEYSTORE_BASE64`。
最后一个是 keystore 的 base64；CI 解码到 `$RUNNER_TEMP` 并 `chmod 600`，自动设置 `ANDROID_KEYSTORE_PATH`。
**缺任何 secret 直接失败**，绝不悄悄产出装不上的包。

Android 的 `publish-release` 与桌面端是**两个独立 job**：
桌面失败不阻断 Android 发布，反之亦然。两边都用 `--clobber` 上传，
谁先跑到谁先传，互不覆盖。

## 4.1 构建系统里几个「踩过才知道」的点

这些都已在 `tests/test_android_shell.py` 里加了断言，改错了会立刻红：

| 点 | 症状 | 正确做法 |
|---|---|---|
| `gradlew.bat` 含中文注释 | `'Windows' 不是内部或外部命令`、`'ar' 不是…` 一连串怪错 | **.bat 必须纯 ASCII**（cmd.exe 按 ANSI 代码页解析，非 ASCII 字节会拆坏命令边界） |
| wrapper 走官方源 | `timeout (10000ms)` 下载失败 | 国内实测官方 0.13 MB/s（130 MB 要 17 分钟），改用腾讯云镜像 + `networkTimeout=120000` |
| `assets.srcDirs("../../static")` | APK 里出现 `assets/index.html`、`assets/assets/wallpapers/...`（目录被摊平） | 用 `Sync` 任务按目录名复制到 `build/android-shell-assets/{static,templates}` |
| 缺 `androidx.appcompat` 依赖 | 几十条 `Unresolved reference: appcompat / activity` | `dependencies { implementation("androidx.appcompat:appcompat") ... }` |
| `syncShellAssets` 只挂 `merge*Assets` | `assembleRelease` 直接失败：`Task ':app:lintVitalAnalyzeRelease' uses this output of task ':app:syncShellAssets' without declaring an explicit or implicit dependency` | Gradle 8 把未声明的任务依赖当**构建失败**。要把 `lint*`、`package*`、`generate*PythonBuildAssets` 等所有消费该目录的任务都 `dependsOn` 上。CI 只跑 debug 时会漏掉这个坑 |
| 主题用 `android:Theme.Material` | 运行时崩：`You need to use a Theme.AppCompat theme` | 继承 `Theme.AppCompat.NoActionBar` |
| pip 联网装 Chaquopy 依赖 | 卡 30+ 分钟无输出 | 预下载到 `android/wheelhouse/`，`--no-index --find-links` 离线装 |
| APK 里 assets 不是普通文件 | `render_template` / `send_from_directory` 读不到 | 壳把 assets 解包到 `$HOME/.shell-resources`，再把 `INTERNAL_DIR` 指过去 |

### 重新生成 wheelhouse

当 `pip { install(...) }` 里的依赖变化时需要重建：

```powershell
python tools/build_android_wheelhouse.py   # 见该脚本内的说明
```

或手动：

```powershell
python -m pip download Flask>=2.0.0 requests>=2.28.0 ^
  --only-binary :all: --platform android_24_arm64_v8a ^
  --python-version 3.13 --implementation cp --abi cp313 ^
  -d android/wheelhouse --index-url https://pypi.tuna.tsinghua.edu.cn/simple

python -m pip download Pillow==11.0.0 --no-deps ^
  --only-binary :all: --platform android_24_arm64_v8a ^
  --python-version 3.13 --implementation cp --abi cp313 ^
  -d android/wheelhouse --index-url https://chaquo.com/pypi-13.1

# 还要补 Pillow 的两个 Chaquopy 专有依赖
python -m pip download chaquopy-freetype>=2.9.1 chaquopy-libjpeg>=1.5.3 --no-deps ^
  --only-binary :all: --platform android_24_arm64_v8a ^
  --python-version 3.13 --implementation cp --abi cp313 ^
  -d android/wheelhouse --index-url https://chaquo.com/pypi-13.1
```

> 判断标准：`pip install --dry-run --ignore-installed --no-index --find-links android/wheelhouse Flask Pillow requests`
> 能解析成功（rc=0）即可。

## 5. 与仓库其它部分的接线点

| 仓库文件 | 关系 |
|---|---|
| `core/config.py` | `resolve_base_dir()` 仅在壳显式设置 `STM_ANDROID_SHELL=1` 时采用 `STM_DATA_ROOT`（默认 filesDir）；Termux 保留源码根（`/data/data/<pkg>/files`） |
| `core/utils/host_capabilities.py` | `CAN_WATCH_FILESYSTEM` / `CAN_OPEN_SYSTEM_FILE_MANAGER` 在移动端为 False |
| `core/data/sqlite_capabilities.py` | Chaquopy ≥ 17.1 自带 FTS5，探测为 True（full 表可用） |
| `static/js/utils/viewStack.js` | 暴露 `window.__stmHostBack()` 供返回键调用 |
| `static/js/utils/longPress.js` | 触摸长按合成 `contextmenu`，11 处右键入口零改动生效 |
| `.github/workflows/build-android.yml` | 独立工作流，**不**进桌面 `publish-release` 的 `needs` |

## 6. 测试

```bash
pytest tests/test_android_shell.py -v
```

该文件包含静态契约检查与独立 Python 进程的实际启动准备验证。另有
`tests/test_review_browser_regressions.py` 的 Chromium 行为回归；APK 构建检查由 wrapper 执行。静态部分断言的是
「配错了要到构建期甚至装到真机才炸」的那些点：Chaquopy 版本下限、
minSdk、Python 版本与 CI 一致、assets 路径上溯层级、Manifest 权限、
WebView 四个回调齐全、`blob:` 下载路径、Python 入口无循环导入等。

## 本轮运行约束

- Kotlin 在首次导入 `core` 之前声明 `STM_ANDROID_SHELL`、`STM_DATA_ROOT` 与 `STM_INTERNAL_ROOT`；模块级路径常量仍是字符串，运行中不切根。
- `INTERNAL_DIR` 对应按内容摘要缓存的包内资源；内置壁纸使用 `static/...` 标识。
- 默认数据目录不申请存储权限。设置外部真实目录时先授权、验证读写，再保存；`content://` 不作为文件路径。
- Activity 不可见时结束前台服务；进程内 Python 可继续运行，但不承诺后台驻留。回前台重新订阅并幂等恢复。
- 旧用户 DB JSON 仅用于其声明的局部状态；完整换机请使用下方「完整备份与换机（ZIP）」入口。


## 完整备份与换机（ZIP）

入口与范围见 [README 的数据备份与迁移](../README.md#数据备份与迁移)。应用私有 `files/data/` 无须由文件管理器读取：
点击生成完整 ZIP 后，通过系统 ACTION_CREATE_DOCUMENT 选择用户可传输的位置；恢复通过 ACTION_OPEN_DOCUMENT 选 ZIP。
ContentResolver 打开文档输入/输出流，原生层以 64 KiB 缓冲连接固定的后端任务端点；整份 ZIP 不进入 JS，也不编码为 Base64。
ZIP 包含自动化规则文件及全局规则集选择/关闭状态。旧 ZIP 缺少该设置时，预览会提示，恢复后默认关闭，需重新选择规则或从源设备重新导出。
新增能力不申请所有文件访问权限。配置外部业务目录仍复用现有按需授权流程，权限不足会导致备份失败。
原消息通道仍限制可信 loopback origin 和主框架；备份消息只接收任务 ID，不接受任意 URL 或私有文件路径，HTTP 禁止重定向。

取消选择、空间不足或传输截断会报告失败；保存成功才显示文档 URI。文件选择中的 Activity 重建会保存任务 ID，后台线程结果写回持久任务状态。
系统杀进程后的未完成任务需重新操作；不能把停留在「生成完成」或「等待保存」当作文件已经落盘。
恢复校验和预览后确认，完全退出并重启才能启用。预览前验证数据库升级和业务表结构；目录切换后，直到配置、数据库和缓存成功初始化才确认完成。
启动验证失败自动回滚，中断则下次启动回滚；日志在回滚完成前保留。源设备绝对路径不会成为目标业务目录，资源 ID 保持相对形式，普通备注原样保存。
美化主题、截图与头像使用应用根相对路径；Windows 世界书备注按实际文件名迁移，避免大小写规则差异造成失联。
当前 ZIP 格式版本为 3，必需清单记录可移动业务根的共用和嵌套关系；绑定、备注及历史共享同一目录定位规则。
业务根等于或位于 `assets`、壁纸、美化固定目录内时同样保留共享关系；固定目录互相重叠、业务根包含固定目录或位于系统目录内的组合，在导出前明确拒绝。
下划线开头的卡片同样迁移绑定，导出前检查文件、目录和祖先路径的 Unicode / 大小写冲突。
每个文件名和目录名最多 255 个 UTF-8 字节，Windows 上可用但超过 Android 文件系统限制的长中文名称会在导出前明确拒绝，不自动改名。
脚本及 JSON 原子保存使用同目录独立短临时文件名，不给目标名追加 `.tmp`，避免合法长名称恢复后无法保存；写入或替换失败会保留原文件。
完整 ZIP 相对路径最多 3,072 个 UTF-8 字节，为目标前缀及原子写入后缀合计留出 1,023 字节；导入同时检查实际目标绝对路径及后缀不超过 4,095 字节。超长目录树或目标数据根会明确拒绝。
Windows 相对资源绑定按资源根及真实目录名规范化，反斜杠和大小写差异不带入 Android。
SQLite 附件按文件头识别并生成包含已提交 WAL 的独立快照；普通同后缀附件保留原字节，异常日志或快照失败明确报错。
插件仅排除根下私有 `data/`，`frontend/data/` 等程序目录保留；插件私有数据仍需另行迁移。
导出按源文件系统识别插件私有目录的大小写别名（如 Windows 的 `Data/`），防止私有凭据混入程序备份；内置数据库及备注/聊天状态文件的大小写变体使用规范 ZIP 名称，供 Android 读取。
早期开发版格式 1/2 缺少可靠的路径或目录关联信息，请重新导出；历史局部 JSON 仍兼容。
插件程序恢复后禁用，插件配置/私有数据默认排除，集中密钥及目标本机认证保留。旧 JSON 格式导入仍在统一区域中可用。
导出和导入共同限制 ZIP / 解压总量各 100 GiB、20 万资源文件及必要元数据，清单 32 MiB、设置 16 MiB（UTF-8 字节）；超限导出不会进入生成成功状态。
资源接口禁止修改迁移暂存、待启用目录与保护副本。确认恢复时在维护锁内重新核对清单、文件/目录集合、大小和 SHA-256；任何变更都会停止恢复，要求重新选择并预览。
旧快照恢复也受相同保护；确认后统一暂停业务写请求，直到重启完成。路径转换后的配置、SQLite、文件与空目录生成独立启动校验清单，启动切换前全部复核，不一致则拒绝启用并继续使用当前库。
升级前未生成该校验清单的待恢复事务会被拒绝，需重新选择原 ZIP 预览；ZIP v3 和历史 JSON 格式兼容不变。

验证区分：JVM 的 BackupTransferTest 覆盖有界流复制、长度不符、输出失败和固定端点限制；pytest 覆盖实际 ZIP、WAL 快照、
跨平台路径、关联状态、恶意条目、不可访问目录、空间不足及恢复回滚。上述自动测试不等于系统文档提供者、切后台或真机生命周期验证。


本次验证（2026-11-15）：已通过 Kotlin 单元测试、标准 debug 构建和实际 ZIP / Chromium 隔离库往返。
另构建了独立包名 `com.stmanager.pro.migrationtest`、独立端口 17864 的测试包，以保护手机现有应用与数据；
Mi 10 Pro 安装返回 `INSTALL_FAILED_USER_RESTRICTED`，未能进入系统文档提供者实测。
因此本次没有将系统保存、取消、后台切换或桌面与 Android 真机互恢复标记为已验证；原应用未覆盖、资源库未改动。

审核修复验证还覆盖真实美化服务的主题、截图和头像 ZIP 往返，Windows 大小写备注到 POSIX 路径规则的查询，
以及隔离子进程中的真实数据库和缓存启动、启动失败回滚、回滚中断后重试。这些桌面测试没有替代 Android 真机验证。
后续目录关联回归在移走源目录后检查下划线卡片绑定、嵌套外部根及共享世界书/资源根，并在历史清理后再次查询记录；
另验证 NFC/NFD 目录冲突在导出阶段失败。再次尝试了独立包名 `com.stmanager.pro.migrationroots`、端口 17864 的设备测试包，
Mi 10 Pro 仍返回 `INSTALL_FAILED_USER_RESTRICTED`，未进入系统文件选择器验收。

2026-11-16 用户提供的独立应用验收报告（Mi 10 Pro / Android 13）已验证系统文件选择、ZIP 预览确认及冷启动、Windows → Android → Windows 往返、
原文件和关联状态、SQLite WAL 附件、128 MiB 随机附件的后台导出和系统保存/重新上传校验、选择/保存取消及同源 iframe 原生桥拦截，全程未授予所有文件访问权限。
该验收发现正式库因 `/data/user/0/` 与 `/data/data/` 别名混用被误拦截。本次修复统一在实际工作区路径下比较边界，保留 `library/<类型>` 的限制，
并以真实目录链接、真实 ZIP 冷启动和保存/附件上传接口回归验证；暂存区、保护副本和逃逸链接继续禁止写入。
修复后的独立包 `com.stmanager.pro.migrationaliasfix`（端口 17865）构建成功，但设备安装返回 `INSTALL_FAILED_USER_RESTRICTED`，未运行修复后的真机复测。
2026-11-16 后续用户确认：审核及修复后的 adb 验证均已通过。该确认更新上述安装受阻时的验证结论。
Activity 重建、目录切换中途杀进程、真机低磁盘空间及其他文档提供者仍未完成验收；上述桌面回归不替代这些设备验证。
