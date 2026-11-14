import java.security.MessageDigest

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.stmanager.pro"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.stmanager.pro"
        // Chaquopy 要求 minSdk >= 24；24 同时覆盖约 97% 活跃设备。
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.2.0"

        ndk {
            // 只出 arm64-v8a：Chaquopy 说明每多一个 ABI 就多几 MB。
            // 需要模拟器时再临时加 x86_64。
            abiFilters += listOf("arm64-v8a")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            // 侧载分发：暂时不接签名，CI 出 debug 包用于验证构建。
            // 真要发布时补 signingConfigs（见 docs 的侧载说明）。
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
tasks.matching { it.name.startsWith("merge") && it.name.endsWith("Assets") }
    .configureEach { dependsOn(syncShellAssets) }

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
