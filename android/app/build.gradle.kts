import java.security.MessageDigest

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// ---------------------------------------------------------------------------
// 版本号：单一来源是仓库根的 core/version.py（桌面端也用它）。
//
// 为什么不手写在这里：Android 的 versionName 若与 APP_VERSION 漂移，会出现
// 「设置页显示 1.2.0、APK 实际 1.1.0」这种对不上的情况，且插件 min_app_version
// 校验会按错误的版本判断。测试 tests/test_android_version.py 也断言两边一致。
//
// versionCode 由语义化版本推导为单调递增整数：
//   major*10000 + minor*100 + patch
//   1.2.0 -> 10200，1.2.1 -> 10201，1.3.0 -> 10300
// Android 要求 versionCode 严格递增，否则覆盖安装失败。
// ---------------------------------------------------------------------------
val appVersion: String = run {
    val versionPy = rootProject.projectDir.parentFile.resolve("core/version.py")
    val match = Regex("""APP_VERSION\s*=\s*['"]([^'"]+)['"]""")
        .find(versionPy.readText())
        ?: error("无法从 ${versionPy.path} 解析 APP_VERSION")
    match.groupValues[1]
}

val appVersionCode: Int = run {
    // 容忍 1.2 / 1.2.0 / 1.2.0-beta.1 这几种写法，取前三段数字。
    val parts = appVersion.substringBefore('-').split('.').map { it.toIntOrNull() ?: 0 }
    val major = parts.getOrElse(0) { 0 }
    val minor = parts.getOrElse(1) { 0 }
    val patch = parts.getOrElse(2) { 0 }
    require(minor < 100 && patch < 100) {
        "版本号 $appVersion 的 minor/patch 必须小于 100，否则 versionCode 会串位"
    }
    major * 10000 + minor * 100 + patch
}

// ---------------------------------------------------------------------------
// 发布签名。
//
// 全部从环境变量读，**绝不把密钥材料写进仓库**。四个变量：
//   ANDROID_KEYSTORE_PATH       keystore 文件路径
//   ANDROID_KEYSTORE_PASSWORD   keystore 口令
//   ANDROID_KEY_ALIAS           key 别名
//   ANDROID_KEY_PASSWORD        key 口令
//
// 为什么用「全部存在才启用」而不是直接 require：
// 本地开发者只跑 `assembleDebug` 时不该被签名配置拦住；缺变量时 release
// 变体保持 unsigned 并打印提示，CI 里则由显式的校验步骤失败。
//
// ⚠️ 变量名刻意与 SigningConfig 的属性名不同（`envKeyAlias` vs `keyAlias`）：
// 若写成同名的 `val keyAlias`，块内的 `this.keyAlias = keyAlias` 会因为
// `this` 解析到外部脚本作用域而**静默丢掉赋值**，症状是
// `SigningConfig "release" is missing required property "keyPassword"`。
//
// CI 里 keystore 以 base64 存在 Secret `ANDROID_KEYSTORE_BASE64` 中，
// 由 workflow 解码到临时文件后把路径塞给 ANDROID_KEYSTORE_PATH。
// 这里不直接读 base64：解码落盘是 workflow 的职责，gradle 只管用文件。
// ---------------------------------------------------------------------------
val envKeystorePath: String? = System.getenv("ANDROID_KEYSTORE_PATH")
val envKeystorePassword: String? = System.getenv("ANDROID_KEYSTORE_PASSWORD")
val envKeyAlias: String? = System.getenv("ANDROID_KEY_ALIAS")
val envKeyPassword: String? = System.getenv("ANDROID_KEY_PASSWORD")

val hasReleaseSigning: Boolean =
    !envKeystorePath.isNullOrBlank() &&
        !envKeystorePassword.isNullOrBlank() &&
        !envKeyAlias.isNullOrBlank() &&
        !envKeyPassword.isNullOrBlank() &&
        File(envKeystorePath).isFile

android {
    namespace = "com.stmanager.pro"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.stmanager.pro"
        // Chaquopy 要求 minSdk >= 24；24 同时覆盖约 97% 活跃设备。
        minSdk = 24
        targetSdk = 35
        versionCode = appVersionCode
        versionName = appVersion

        ndk {
            // 只出 arm64-v8a：Chaquopy 说明每多一个 ABI 就多几 MB。
            // 需要模拟器时再临时加 x86_64。
            abiFilters += listOf("arm64-v8a")
        }

        // 构建期把「本次产物是否已签名」写进 BuildConfig，
        // 便于 App 内如实区分「侧载正式包」与「CI 调试包」。
        buildConfigField("boolean", "IS_RELEASE_SIGNED", hasReleaseSigning.toString())
    }

    signingConfigs {
        if (hasReleaseSigning) {
            create("release") {
                storeFile = File(envKeystorePath!!)
                storePassword = envKeystorePassword
                // 用 `this.` 前缀明确写到 SigningConfig 上。
                this.keyAlias = envKeyAlias
                this.keyPassword = envKeyPassword
                // v2 覆盖 Android 7.0（API 24）及以上，正好等于本项目 minSdk，
                // 因此这里只需 v2。不必开 v1：AGP 在 minSdk >= 24 时本就会跳过它
                // （apksigner 报 `v1 scheme: false` 属预期，不是签名失败）。
                // 若将来把 minSdk 降到 23 或更低，必须同时打开 enableV1Signing。
                enableV1Signing = false
                enableV2Signing = true
                enableV3Signing = true
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (hasReleaseSigning) {
                signingConfigs.getByName("release")
            } else {
                logger.lifecycle(
                    "未提供 ANDROID_KEYSTORE_* 环境变量：release 变体将以 unsigned 产出，" +
                        "无法直接安装。仅本地验证构建时属预期行为。",
                )
                null
            }
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }

    // 保留构建版本元信息的生成（AGP 8 起默认关闭）。
    buildFeatures {
        buildConfig = true
    }

    // 前端资源打包。
    //
    // 坑：`assets.srcDirs(file("../../static"))` 会把 static **目录的内容**摊平到
    // assets 根（出现 assets/index.html、assets/assets/wallpapers/...），
    // 而 `core/config.py` 的 INTERNAL_DIR 语义要求 assets 下存在 `static/` 与
    // `templates/` 两个子目录，否则 Flask 找不到静态文件与模板（白屏）。
    //
    // 因此用一个 Copy 任务把两者**按目录名**复制到 build 下的规范位置：
    //   build/android-shell-assets/static/**
    //   build/android-shell-assets/templates/**
    // assets.srcDirs 只指向这个中间目录。
    sourceSets {
        getByName("main") {
            assets.srcDir(layout.buildDirectory.dir("android-shell-assets"))
        }
    }

    packaging {
        // Python 源码与资源已经按需打包，避免重复。
        resources {
            excludes += listOf(
                "META-INF/*.kotlin_module",
                "**/kotlin/**",
            )
        }
    }
}

// 把仓库的 static/ 与 templates/ 复制成「按名字分层」的 assets 结构。
// 用 Sync（而非 Copy）可以清掉上一次残留，避免删掉源文件后 APK 里还在。
//
// 路径：Gradle 的 rootProject 是 android/ 目录，仓库根是它的上一级。
val repoRoot = rootProject.projectDir.parentFile
val syncShellAssets by tasks.registering(Sync::class) {
    from(repoRoot.resolve("static")) { into("static") }
    from(repoRoot.resolve("templates")) { into("templates") }
    into(layout.buildDirectory.dir("android-shell-assets"))
    doLast {
        val root = destinationDir
        val digest = MessageDigest.getInstance("SHA-256")
        root.walkTopDown().filter { it.isFile && it.name != "shell-assets.sha256" }
            .sortedBy { it.relativeTo(root).invariantSeparatorsPath }.forEach { file ->
                digest.update(file.relativeTo(root).invariantSeparatorsPath.toByteArray(Charsets.UTF_8))
                digest.update(0.toByte())
                file.inputStream().use { input ->
                    val buffer = ByteArray(65536)
                    var count = input.read(buffer)
                    while (count >= 0) {
                        digest.update(buffer, 0, count)
                        count = input.read(buffer)
                    }
                }
            }
        root.resolve("shell-assets.sha256").writeText(digest.digest().joinToString("") { "%02x".format(it) })
    }
}

// 所有需要 assets 的任务都依赖这次同步。
//
// ⚠️ 不能只匹配 `merge*Assets`：release 变体还会跑 `lintVitalAnalyzeRelease`、
// `package*` 等任务，它们同样消费这个目录，Gradle 8 会把「未声明的任务依赖」
// 当成**构建失败**（不是警告），症状是 `assembleRelease` 直接挂掉：
//     Task ':app:lintVitalAnalyzeRelease' uses this output of task
//     ':app:syncShellAssets' without declaring an explicit or implicit dependency
// 因此这里覆盖所有会读 assets 的任务名模式。
tasks.matching {
    (it.name.startsWith("merge") && it.name.endsWith("Assets")) ||
        (it.name.startsWith("lint") && it.name.contains("Release")) ||
        (it.name.startsWith("lint") && it.name.contains("Debug")) ||
        (it.name.startsWith("package") && it.name.contains("Release")) ||
        (it.name.startsWith("package") && it.name.contains("Debug")) ||
        it.name.startsWith("generate") && it.name.endsWith("PythonBuildAssets")
}.configureEach { dependsOn(syncShellAssets) }

// ---------------------------------------------------------------------------
// 把仓库根的 core/ 同步进 Python 源目录。
//
// 为什么必须单独做：Chaquopy 默认只打包 `app/src/main/python/` 下的代码，
// 而 `core/` 在仓库根 —— 不做这一步，APK 里只有 `android_shell/`，
// 启动时直接报：
//     ModuleNotFoundError: No module named 'core'
//     at <python>.android_shell.boot.start_server(boot.py:109)
//
// 选择「同步到 build 目录 + 加进 srcDirs」而不是「直接指向仓库根」：
// 后者会把整个仓库（含 data/、tests/、static/）都当成 Python 源码扫描，
// 既慢又可能误打包。
//
// 必须排除 __pycache__：里面是**主机** Python 版本的 .pyc，
// 打进 APK 会让 target 侧的字节码版本对不上。
val syncCorePython by tasks.registering(Sync::class) {
    from(File(rootProject.projectDir.parentFile, "core")) {
        exclude("**/__pycache__/**")
        exclude("**/*.pyc")
        exclude("**/*.pyo")
    }
    into(layout.buildDirectory.dir("python-src/core"))
}

// Chaquopy 的 Python 源合并任务消费这个目录，必须显式声明依赖，
// 否则 Gradle 8 会以「隐式依赖」为由直接判构建失败（不是警告）。
// 任务名按变体生成，形如 mergeDebugPythonSources / mergeReleasePythonSources。
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("PythonSources") }
    .configureEach { dependsOn(syncCorePython) }

dependencies {
    // MainActivity 继承 AppCompatActivity，并用到 registerForActivityResult /
    // OnBackPressedDispatcher / ActivityResultContracts —— 这些都在
    // androidx.appcompat 与 androidx.activity 里。漏掉会报大量
    // "Unresolved reference: appcompat / activity / AppCompatActivity"。
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.activity:activity-ktx:1.9.3")
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.webkit:webkit:1.12.1")
    testImplementation("junit:junit:4.13.2")
}

chaquopy {
    defaultConfig {
        // 与 Python-Apple-support/iOS 侧建议一致：3.13。
        // 桌面端仍钉 3.10（build-desktop.yml），这里是有意的双版本。
        version = "3.13"

        // Chaquopy 编译字节码需要构建机有同版本 Python。
        // CI 上由 setup-python 提供；本地没装 3.13 时请显式指定路径。
        // buildPython("C:/path/to/python3.13.exe")

        // Python 源码来源：
        //   1. app/src/main/python/ —— 默认目录，放 android_shell/ 壳代码
        //   2. build/python-src/    —— syncCorePython 同步进来的 core/
        // 两者在 APK 里合并成同一个 import 空间，因此 `import core` 可用。
        sourceSets {
            getByName("main") {
                srcDirs(
                    "src/main/python",
                    layout.buildDirectory.dir("python-src").get().asFile.absolutePath,
                )
            }
        }

        pip {
            // 与应用运行时依赖保持一致（requirements.txt），
            // 但不装 watchdog：Android 上 inotify 在 FUSE 不生效，
            // 且 CAN_WATCH_FILESYSTEM 已把它关掉（core/utils/host_capabilities.py）。
            install("Flask>=2.0.0")
            install("Pillow>=9.0.0")
            install("requests>=2.28.0")

            // === 离线安装（重要）===
            // 直接走网络会**卡死**：pip 要对每个包同时查询 pypi 与 chaquo.com，
            // 而 chaquo.com 对不在它仓库里的包返回 404，每次都要等一轮响应再回退。
            // 实测 `installDebugPythonRequirements` 在这个组合下卡 30+ 分钟无输出。
            //
            // 解法：把 Android 目标的完整依赖树预下载到 android/wheelhouse/，
            // 让 pip 只从本地目录解析。重新生成 wheelhouse 见 android/README.md。
            //
            // wheelhouse 里必须包含 **Android 版**的原生 wheel：
            //   - pillow-11.0.0-0-cp313-cp313-android_24_arm64_v8a.whl（仅 chaquo.com 有）
            //   - markupsafe / charset_normalizer 同理
            // 纯 Python 包（flask/werkzeug/jinja2/click/urllib3/...）平台无关。
            //
            // 路径说明：此处基准是模块目录 android/app，wheelhouse 在 android/wheelhouse，
            // 因此上溯一级。用 providers 解析成绝对路径，避免相对路径在不同任务里基准漂移。
            options(
                "--no-index",
                "--find-links",
                rootProject.file("wheelhouse").absolutePath,
            )
        }
    }
}
