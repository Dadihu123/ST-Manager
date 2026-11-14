"""Android 壳工程的静态契约测试。

此文件覆盖工程配置及 Python 启动行为。Kotlin 写入行为由
`:app:testDebugUnitTest` 验证，APK 构建由本地或 Android CI 验证。

这里断言的每一条都对应一个「配错了要到构建期才炸、甚至装到手机上才炸」的点。
"""

import re
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANDROID = PROJECT_ROOT / 'android'
APP_SRC = ANDROID / 'app' / 'src' / 'main'


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


# --- 工程结构完整性 ---


def test_gradle_project_files_exist():
    for rel in (
        'settings.gradle.kts',
        'build.gradle.kts',
        'gradle.properties',
        'gradle/wrapper/gradle-wrapper.properties',
        'app/build.gradle.kts',
        'app/src/main/AndroidManifest.xml',
    ):
        assert (ANDROID / rel).is_file(), f'缺少 {rel}'


def test_settings_includes_chaquopy_maven_repo():
    """Chaquopy 运行时依赖来自自己的 Maven 仓库，漏了会在解析依赖时失败。"""
    source = read(ANDROID / 'settings.gradle.kts')
    assert 'chaquo.com/maven' in source
    assert 'mavenCentral()' in source
    assert 'google()' in source


def test_chaquopy_version_supports_fts5():
    """Chaquopy >= 17.1 才启用 FTS5；本项目的全文索引依赖它。"""
    source = read(ANDROID / 'build.gradle.kts')
    match = re.search(r'id\("com\.chaquo\.python"\)\s+version\s+"([\d.]+)"', source)
    assert match, '未找到 Chaquopy 插件版本声明'
    version = tuple(int(x) for x in match.group(1).split('.')[:2])
    assert version >= (17, 1), f'Chaquopy {match.group(1)} 低于 17.1，FTS5 未启用'


def test_min_sdk_meets_chaquopy_requirement():
    """Chaquopy 要求 minSdk >= 24。"""
    source = read(ANDROID / 'app' / 'build.gradle.kts')
    match = re.search(r'minSdk\s*=\s*(\d+)', source)
    assert match, '未找到 minSdk'
    assert int(match.group(1)) >= 24


def test_android_10_manifest_preserves_direct_external_directory_access():
    from xml.etree import ElementTree

    root = ElementTree.parse(APP_SRC / 'AndroidManifest.xml').getroot()
    android = '{http://schemas.android.com/apk/res/android}'
    assert root.find('application').get(android + 'requestLegacyExternalStorage') == 'true'
    permissions = {item.get(android + 'name'): item for item in root.findall('uses-permission')}
    for name in ('READ_EXTERNAL_STORAGE', 'WRITE_EXTERNAL_STORAGE'):
        assert permissions['android.permission.' + name].get(android + 'maxSdkVersion') == '29'
    assert 'android.permission.MANAGE_EXTERNAL_STORAGE' in permissions


def test_app_python_version_is_declared_and_supported():
    """app 的 Python 版本必须与 CI 的 setup-python 一致（Chaquopy 编译字节码需要）。"""
    build = read(ANDROID / 'app' / 'build.gradle.kts')
    match = re.search(r'version\s*=\s*"(3\.\d+)"', build)
    assert match, '未声明 chaquopy version'
    app_py = match.group(1)

    workflow = read(PROJECT_ROOT / '.github' / 'workflows' / 'build-android.yml')
    assert f"python-version: '{app_py}'" in workflow, (
        f'app 用 Python {app_py}，但 CI 没装同版本 → Chaquopy 会退化为设备端编译'
    )


def test_build_config_enabled():
    """显式保留构建元信息，AGP 8 默认关闭该特性。"""
    build = read(ANDROID / 'app' / 'build.gradle.kts')
    assert 'buildConfig = true' in build


# --- Manifest 契约 ---


def test_manifest_declares_required_permissions():
    manifest = read(APP_SRC / 'AndroidManifest.xml')
    # loopback 也需要 INTERNET
    assert 'android.permission.INTERNET' in manifest
    # 直接操作 /storage/emulated/0 的前提
    assert 'MANAGE_EXTERNAL_STORAGE' in manifest
    # 长扫描不被回收
    assert 'FOREGROUND_SERVICE' in manifest


def test_manifest_allows_cleartext_for_loopback_only():
    """targetSdk >= 28 默认禁止明文；只给 loopback 开口子，不全局放开。"""
    manifest = read(APP_SRC / 'AndroidManifest.xml')
    config = read(APP_SRC / 'res' / 'xml' / 'network_security_config.xml')

    assert 'networkSecurityConfig' in manifest
    assert '127.0.0.1' in config
    assert 'cleartextTrafficPermitted="true"' in config
    # 确认没有用 base-config 全局放开
    assert '<base-config' not in config, '不应全局放开明文流量'


def test_manifest_uses_pyapplication():
    """Chaquopy 要求在 application 上声明 PyApplication 才会启动 Python 运行时。"""
    manifest = read(APP_SRC / 'AndroidManifest.xml')
    assert 'com.chaquo.python.android.PyApplication' in manifest


def test_manifest_declares_service_and_activity():
    manifest = read(APP_SRC / 'AndroidManifest.xml')
    assert '.MainActivity' in manifest
    assert '.BackendService' in manifest
    assert 'foregroundServiceType' in manifest


# --- WebView 四个必备回调 ---


def test_webview_host_callbacks_present():
    """缺任何一个都有一个功能瞎掉（可行性文档 §4.4）。"""
    source = read(APP_SRC / 'java' / 'com' / 'stmanager' / 'pro' / 'MainActivity.kt')

    assert 'onShowFileChooser' in source, '缺文件选择回调 → 29 处 input[type=file] 无反应'
    assert 'setDownloadListener' in source, '缺下载回调 → blob 导出全部失效'
    assert 'onCreateWindow' in source, '缺新窗口回调 → target=_blank 点击无反应'
    assert 'addOnBackPressedCallback' in source or 'onBackPressedDispatcher' in source, (
        '缺返回键处理 → 返回手势直接退出应用'
    )


def test_native_bridge_wires_checked_message_listener_without_legacy_interface():
    source = read(APP_SRC / 'java' / 'com' / 'stmanager' / 'pro' / 'MainActivity.kt')
    assert 'addJavascriptInterface(' not in source
    assert 'WebViewCompat.addWebMessageListener' in source
    assert 'NativeBridgePolicy().dispatch(sourceOrigin.toString(), isMainFrame)' in source


def test_back_key_consults_js_view_stack():
    """返回键必须先问 JS 视图栈，不能直接退出。"""
    source = read(APP_SRC / 'java' / 'com' / 'stmanager' / 'pro' / 'MainActivity.kt')
    assert '__stmHostBack' in source, '返回键应调用 viewStack 暴露的 __stmHostBack'


def test_download_handles_blob_urls():
    """blob: 下载在 WebView 里必须走 JS 读取，不能用 DownloadManager。"""
    source = read(APP_SRC / 'java' / 'com' / 'stmanager' / 'pro' / 'MainActivity.kt')
    assert 'blob:' in source
    assert 'saveBase64File' in source


# --- Python 侧入口 ---


def test_python_shell_entry_exists_and_importable():
    module_dir = APP_SRC / 'python'
    assert (module_dir / 'android_shell' / 'boot.py').is_file()
    assert (module_dir / 'android_shell' / '__init__.py').is_file()


def test_python_shell_disables_auto_scan():
    """Android 的 FUSE 不投递 inotify，自动扫描必须关掉。"""
    source = read(APP_SRC / 'python' / 'android_shell' / 'boot.py')
    assert 'enable_auto_scan' in source
    assert '127.0.0.1' in source, '必须只监听 loopback'


def test_python_shell_has_no_circular_import():
    """boot.py 曾经从自身导入导致 ImportError；这里做回归断言。"""
    source = read(APP_SRC / 'python' / 'android_shell' / 'boot.py')
    assert 'from android_shell.boot import' not in source, '不得从自身导入（循环导入）'


def test_python_shell_actually_imports():
    """真实 import 一次，确保没有语法/导入错误。"""
    module_dir = APP_SRC / 'python'
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    import importlib

    try:
        module = importlib.import_module('android_shell.boot')
        assert hasattr(module, 'start_server')
        assert hasattr(module, '_prepare_runtime')
    finally:
        # import 会在源码树里生成 __pycache__，必须清掉：
        # 它会被当作 assets 打进 APK，且是主机 Python 版本的 .pyc。
        import shutil

        for cache in (APP_SRC / 'python').rglob('__pycache__'):
            shutil.rmtree(cache, ignore_errors=True)


# --- CI 契约 ---


def test_ci_workflow_is_separate_from_desktop_release():
    """移动端工作流不得加入桌面的 publish-release.needs，否则会拦住桌面 Release。"""
    desktop = read(PROJECT_ROOT / '.github' / 'workflows' / 'build-desktop.yml')
    android = read(PROJECT_ROOT / '.github' / 'workflows' / 'build-android.yml')

    assert 'build-android' not in desktop, '桌面工作流不应依赖移动端'
    # 检查是否真的定义了 publish-release job（而不是注释里提了一句）
    android_jobs = re.findall(r'^\s{2}([a-zA-Z][\w-]*):\s*$', android, re.MULTILINE)
    assert 'publish-release' not in android_jobs, (
        f'移动端不应定义 publish-release job；实际 jobs={android_jobs}'
    )


def test_ci_apk_artifact_name_not_colliding_with_desktop():
    """桌面 publish-release 按 ST-Manager-Pro-* 前缀下载；移动端不能用这个前缀。"""
    android = read(PROJECT_ROOT / '.github' / 'workflows' / 'build-android.yml')
    desktop = read(PROJECT_ROOT / '.github' / 'workflows' / 'build-desktop.yml')

    assert 'pattern: ST-Manager-Pro-*' in desktop or 'ST-Manager-Pro-' in desktop
    # 移动端产物名不应以 ST-Manager-Pro- 开头
    match = re.search(r'name:\s*(ST-Manager[^\s]*)', android)
    assert match, '未找到 artifact 名称'
    assert not match.group(1).startswith('ST-Manager-Pro-'), (
        f'{match.group(1)} 会污染桌面的 publish-release 匹配'
    )


# --- 图标资源 ---


def test_gradle_wrapper_complete():
    """wrapper 必须完整：缺 gradlew 就跑不了标准命令，缺 jar 则脚本直接报错。"""
    import zipfile

    wrapper_jar = ANDROID / 'gradle' / 'wrapper' / 'gradle-wrapper.jar'
    assert (ANDROID / 'gradlew').is_file(), '缺 gradlew（POSIX/CI 用）'
    assert (ANDROID / 'gradlew.bat').is_file(), '缺 gradlew.bat（Windows 用）'
    assert wrapper_jar.is_file(), '缺 gradle-wrapper.jar（脚本靠它启动）'

    with zipfile.ZipFile(wrapper_jar) as zf:
        names = zf.namelist()
    assert any('GradleWrapperMain' in n for n in names), 'jar 里没有 GradleWrapperMain'

    # properties 的版本必须与 build.gradle.kts 的 AGP 兼容
    props = read(ANDROID / 'gradle' / 'wrapper' / 'gradle-wrapper.properties')
    match = re.search(r'gradle-([\d.]+)-bin\.zip', props)
    assert match, 'wrapper properties 里没有 distributionUrl'
    gradle_version = tuple(int(x) for x in match.group(1).split('.')[:2])
    # AGP 8.7 要求 Gradle >= 8.9
    assert gradle_version >= (8, 9), f'Gradle {match.group(1)} 低于 AGP 8.7 要求的 8.9'


def test_gradlew_bat_is_pure_ascii():
    """.bat 必须纯 ASCII。

    cmd.exe 按系统 ANSI 代码页解析 .bat。文件里一旦出现非 ASCII 字节（例如
    中文注释），命令边界会被拆错，表现为「'Windows' 不是内部或外部命令」
    「'ar' 不是内部或外部命令」这类莫名其妙的报错，且不提示编码问题。
    """
    raw = (ANDROID / 'gradlew.bat').read_bytes()
    assert not raw.startswith(b'\xef\xbb\xbf'), 'gradlew.bat 不应带 UTF-8 BOM'

    bad = [(i, b) for i, b in enumerate(raw) if b > 127]
    if bad:
        offset, _ = bad[0]
        snippet = raw[max(0, offset - 40):offset + 40]
        pytest.fail(
            f'gradlew.bat 含 {len(bad)} 个非 ASCII 字节（首个偏移 {offset}）：'
            f'{snippet!r}'
        )


def test_wrapper_network_timeout_is_generous():
    """超时太小会在慢网络上失败（实测官方源国内带宽下必需 > 10 秒）。"""
    props = read(ANDROID / 'gradle' / 'wrapper' / 'gradle-wrapper.properties')
    match = re.search(r'networkTimeout=(\d+)', props)
    assert match, 'wrapper properties 没有 networkTimeout'
    assert int(match.group(1)) >= 60000, (
        f'networkTimeout={match.group(1)}ms 偏小，慢网络下会下载失败'
    )


def test_wrapper_properties_is_ascii_safe():
    """properties 也保持 ASCII，避免不同 JVM/平台下编码差异带来的困扰。"""
    raw = (ANDROID / 'gradle' / 'wrapper' / 'gradle-wrapper.properties').read_bytes()
    bad = [b for b in raw if b > 127]
    assert not bad, 'gradle-wrapper.properties 含非 ASCII 字节'


def test_ci_uses_gradlew_not_bare_gradle():
    """CI 用 wrapper 更可复现（版本由 properties 锁定，不依赖 runner 预装）。"""
    workflow = read(PROJECT_ROOT / '.github' / 'workflows' / 'build-android.yml')
    assert './gradlew' in workflow
    assert 'chmod +x ./gradlew' in workflow, 'Linux runner 上必须先给可执行权限'


def test_ci_installs_python_before_gradle():
    """Chaquopy 在 Gradle 配置阶段就要找 Python，顺序反了会失败。"""
    workflow = read(PROJECT_ROOT / '.github' / 'workflows' / 'build-android.yml')
    py_pos = workflow.find('setup-python')
    jdk_pos = workflow.find('setup-java')
    gradle_pos = workflow.find('setup-gradle')
    assert py_pos > 0 and jdk_pos > 0 and gradle_pos > 0
    assert py_pos < gradle_pos, 'Python 必须在 setup-gradle 之前'
    assert jdk_pos < gradle_pos, 'JDK 必须在 setup-gradle 之前'


def test_app_dependencies_declared():
    """MainActivity 用到 AppCompatActivity / registerForActivityResult / OnBackPressedDispatcher。

    漏掉 dependencies 会报一堆 "Unresolved reference: appcompat / activity"，
    这次是实际构建时才发现的。
    """
    build = read(ANDROID / 'app' / 'build.gradle.kts')
    assert 'androidx.appcompat:appcompat' in build
    assert 'androidx.activity:activity-ktx' in build


def test_theme_inherits_appcompat():
    """AppCompatActivity 要求主题继承 Theme.AppCompat，否则运行时崩在 setContentView 前。"""
    themes = read(APP_SRC / 'res' / 'values' / 'themes.xml')
    assert 'Theme.AppCompat' in themes, (
        '必须继承 Theme.AppCompat*，否则报 '
        '"You need to use a Theme.AppCompat theme with this activity"'
    )


def test_assets_are_nested_under_static_and_templates():
    """assets 必须保留 static/ 与 templates/ 两层。

    `assets.srcDirs("../../static")` 会把 static 的**内容**摊平到 assets 根，
    导致 core/config.py 的 INTERNAL_DIR/static 找不到东西（白屏）。
    正确做法是用 Sync 任务按目录名复制（见 app/build.gradle.kts）。
    """
    build = read(ANDROID / 'app' / 'build.gradle.kts')
    assert 'syncShellAssets' in build, '应有把 static/templates 按名复制的 Sync 任务'
    assert 'into("static")' in build
    assert 'into("templates")' in build
    # 不应再直接用 assets.srcDirs 指向仓库的 static/templates
    assert 'assets.srcDirs(\n                file("../../static")' not in build


def test_shell_extracts_assets_for_flask():
    """壳必须把 assets 解包成真实文件，Flask 才能按路径读。

    APK 里的 assets 只能通过 AssetManager 访问，不是普通文件；
    send_from_directory / render_template 都需要真实路径。
    """
    kt = read(APP_SRC / 'java' / 'com' / 'stmanager' / 'pro' / 'BackendService.kt')
    assert 'extractAssetsToFiles' in kt
    assert 'copyAssetTree' in kt
    assert 'INTERNAL_DIR' not in kt or 'internalDir' in kt


def test_python_entry_prepares_roots_before_importing_core(tmp_path):
    import json
    import subprocess

    data_root = tmp_path / 'user'
    internal = tmp_path / 'resources'
    data_root.mkdir()
    internal.mkdir()
    script = '''
import json, sys
sys.path.insert(0, sys.argv[1])
from android_shell.boot import _prepare_runtime
result = _prepare_runtime(sys.argv[2], sys.argv[3])
from core import create_app
from core.services.shared_wallpaper_service import SharedWallpaperService
result['static'] = create_app().static_folder
result['wallpaper_root'] = SharedWallpaperService().internal_root
print('RESULT=' + json.dumps(result))
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, str(APP_SRC / 'python'),
                             str(internal), str(data_root)], cwd=PROJECT_ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    payload = json.loads(next(line[7:] for line in result.stdout.splitlines() if line.startswith('RESULT=')))
    assert payload['base_dir'] == str(data_root)
    assert payload['internal_dir'] == payload['wallpaper_root'] == str(internal)
    assert Path(payload['static']) == internal / 'static'
    assert payload['enable_auto_scan'] is False


def test_wheelhouse_generator_covers_all_dependencies():
    """生成脚本必须覆盖可离线的全部依赖（不依赖 wheelhouse 是否已生成）。

    `android/wheelhouse/` 被 .gitignore 忽略（2.4 MB 二进制、可重建），
    所以这里**不能**断言目录存在——干净克隆会直接失败。
    改为断言生成脚本本身的契约：它必须下载这三组包，并做离线校验。
    """
    script = read(PROJECT_ROOT / 'tools' / 'build_android_wheelhouse.py')

    # 纯 Python 依赖树
    assert 'Flask>=2.0.0' in script
    assert 'requests>=2.28.0' in script

    # Pillow 及其 Chaquopy 专有依赖必须单独走 chaquo.com
    assert 'chaquo.com/pypi' in script
    assert 'Pillow==' in script
    assert 'chaquopy-freetype' in script
    assert 'chaquopy-libjpeg' in script

    # 目标平台参数（漏了就会拿到主机平台 wheel）
    assert 'android_24_arm64_v8a' in script
    assert '--python-version' in script

    # 必须自带「离线能否解析」的校验，失败即非零退出
    assert '--no-index' in script
    assert 'verify_offline' in script or 'dry-run' in script


@pytest.mark.skipif(
    not (ANDROID / 'wheelhouse').is_dir(),
    reason='android/wheelhouse 未生成（已被 .gitignore 忽略）；'
           '跑 python tools/build_android_wheelhouse.py 生成后再验',
)
def test_wheelhouse_covers_dependencies_when_present():
    """wheelhouse 已生成时，抽查它确实含 Android 原生 wheel。

    这条只在本地生成过 wheelhouse 后才执行，不会让干净克隆失败。
    """
    wheelhouse = ANDROID / 'wheelhouse'
    wheels = {w.name.lower() for w in wheelhouse.glob('*.whl')}
    assert wheels, 'wheelhouse 是空的'

    joined = ' '.join(wheels)
    assert 'flask' in joined
    assert 'werkzeug' in joined
    assert 'jinja2' in joined
    assert 'requests' in joined
    # Android 原生 wheel：只有 chaquo.com 提供
    assert any('pillow' in w and 'android' in w for w in wheels), '缺 Android 版 Pillow'
    assert any('chaquopy' in w for w in wheels), '缺 chaquopy-* 原生依赖'


def test_gradle_uses_offline_wheelhouse():
    build = read(ANDROID / 'app' / 'build.gradle.kts')
    assert '--no-index' in build
    assert 'wheelhouse' in build


def test_core_package_is_synced_into_python_sources():
    """`core/` 必须被同步进 Chaquopy 的 Python 源目录。

    这是真机上「黑屏」的根因：Chaquopy 默认只打包 app/src/main/python/，
    而 core/ 在仓库根，不做同步的话 APK 里只有 android_shell/，
    启动即崩：
        ModuleNotFoundError: No module named 'core'
        at <python>.android_shell.boot.start_server(boot.py:109)
    """
    build = read(ANDROID / 'app' / 'build.gradle.kts')
    assert 'syncCorePython' in build, '应有把仓库根 core/ 同步进 Python 源目录的任务'
    assert 'python-src' in build, '同步目标应是 build/python-src'
    assert 'srcDirs' in build, '同步目录必须加进 chaquopy 的 sourceSets.srcDirs'


def test_core_sync_excludes_host_bytecode():
    """同步 core/ 时必须排除 __pycache__ 与 .pyc。

    主机 Python（3.12）的 .pyc 打进 APK 会和 target 侧（3.13）字节码版本冲突。
    """
    build = read(ANDROID / 'app' / 'build.gradle.kts')
    assert '__pycache__' in build
    assert '*.pyc' in build


def test_core_sync_declares_gradle_dependency():
    """Gradle 8 会把「未声明的任务依赖」当**构建失败**（不是警告）。

    Chaquopy 的 merge<Variant>PythonSources 消费同步目录，
    必须显式 dependsOn，否则报 implicit dependency 并 BUILD FAILED。
    """
    build = read(ANDROID / 'app' / 'build.gradle.kts')
    assert 'endsWith("PythonSources")' in build
    assert 'dependsOn(syncCorePython)' in build


def test_core_package_is_self_contained():
    """core/ 不应 import 仓库根的其它顶级模块（否则还得再同步）。"""
    core = PROJECT_ROOT / 'core'
    offenders = []
    for py in core.rglob('*.py'):
        for line in py.read_text(encoding='utf-8').splitlines():
            stripped = line.strip()
            for prefix in ('import app', 'from app', 'import clean_ui_data',
                           'from clean_ui_data', 'from tools', 'import tools'):
                if stripped.startswith(prefix):
                    offenders.append(f'{py.relative_to(PROJECT_ROOT)}: {stripped}')
    assert not offenders, f'core/ 依赖了仓库根其它模块: {offenders[:5]}'


def test_manifest_enables_modern_back_callback():
    """targetSdk 33+ 必须在 manifest 里开 enableOnBackInvokedCallback。

    不开的话 Android 13+ 的预测性返回不走 OnBackPressedCallback，
    日志会刷 "OnBackInvokedCallback is not enabled for the application"，
    返回手势分层就是失效的。
    """
    manifest = read(APP_SRC / 'AndroidManifest.xml')
    assert 'enableOnBackInvokedCallback="true"' in manifest


def test_backend_service_has_timeout_and_cancellable_subscription():
    kt = read(APP_SRC / 'java' / 'com' / 'stmanager' / 'pro' / 'BackendService.kt')
    assert 'override fun onTimeout' in kt
    assert 'stopSelf()' in kt
    assert 'fun whenReady(listener: (Int) -> Unit): () -> Unit' in kt
    assert 'transport.webView = webView' not in read(APP_SRC / 'java' / 'com' / 'stmanager' / 'pro' / 'MainActivity.kt')


def test_webview_failures_are_visible():
    """加载失败必须画在屏幕上，不能只留黑屏。

    黑屏是最难排查的形态：用户看不到任何信息，只能靠 adb。
    """
    kt = read(APP_SRC / 'java' / 'com' / 'stmanager' / 'pro' / 'MainActivity.kt')
    assert 'showErrorPage' in kt, '应有把错误画到 WebView 的方法'
    assert 'onReceivedError' in kt, '应处理主文档加载失败'
    assert 'onPageFinished' in kt, '应记录页面加载完成（便于判断到底加载到哪步）'


def test_backend_ready_is_logged():
    """就绪日志是判断「黑屏是后端没起来还是 WebView 没加载」的关键分界。"""
    kt = read(APP_SRC / 'java' / 'com' / 'stmanager' / 'pro' / 'BackendService.kt')
    assert '后端就绪' in kt
    # 探活失败也要有明确日志
    assert '未就绪' in kt


def test_launcher_icons_generated_for_all_densities():
    for density in ('mdpi', 'hdpi', 'xhdpi', 'xxhdpi', 'xxxhdpi'):
        icon = APP_SRC / 'res' / f'mipmap-{density}' / 'ic_launcher.png'
        assert icon.is_file(), f'缺少 {density} 图标'


def test_no_pycache_in_android_python_tree():
    """__pycache__ 混进 assets 会让 APK 带上主机 Python 的 .pyc。"""
    pycache = list((APP_SRC / 'python').rglob('__pycache__'))
    assert pycache == [], f'发现 __pycache__: {pycache}'


# --- Kotlin 结构粗检（本机无 JDK，只能做括号深度追踪）---


def _strip_kotlin_line(line: str) -> str:
    """去掉行内注释与字符串内容，但保留 ${} 内的真实代码。"""
    out = []
    in_str = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == '"' and (i == 0 or line[i - 1] != '\\'):
            in_str = not in_str
            out.append(' ')
            i += 1
            continue
        if not in_str and ch == '/' and i + 1 < len(line) and line[i + 1] == '/':
            break
        out.append(' ' if in_str else ch)
        i += 1
    return ''.join(out)


def test_kotlin_braces_are_balanced():
    """追踪每行花括号深度，最终必须归零且中途不为负。

    这不是编译，但能抓住「编辑时漏了/多了一个 }」这类本机会静默通过的破坏。
    """
    kt_files = list(APP_SRC.rglob('*.kt'))
    assert kt_files, '未找到 Kotlin 源文件'

    for kt in kt_files:
        depth = 0
        negatives = []
        for lineno, raw in enumerate(kt.read_text(encoding='utf-8').splitlines(), 1):
            for ch in _strip_kotlin_line(raw):
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth < 0:
                        negatives.append(lineno)
                        depth = 0
        assert depth == 0, f'{kt.name} 花括号未闭合，残留深度 {depth}'
        assert not negatives, f'{kt.name} 第 {negatives} 行出现多余的 }}'


def test_kotlin_classes_declared_once():
    """每个 Kotlin 文件只应有一个顶层 class（避免误删导致类丢失）。"""
    for kt in APP_SRC.rglob('*.kt'):
        source = kt.read_text(encoding='utf-8')
        classes = re.findall(r'^(?:private )?(?:inner )?class\s+(\w+)', source, re.MULTILINE)
        assert classes, f'{kt.name} 没有 class 声明'
        assert len(classes) == 1, f'{kt.name} 有多个 class: {classes}'


def test_python_backend_binds_before_ready_and_reuses_owned_server(tmp_path):
    import subprocess

    data_root = tmp_path / 'private'
    data_root.mkdir()
    script = r"""
import sys, urllib.request, threading
sys.path.insert(0, sys.argv[1])
from android_shell import boot
boot._prepare_runtime(sys.argv[2], sys.argv[2])
import core
from flask import Flask
app = Flask(__name__)
app.add_url_rule('/', view_func=lambda: 'owned-backend')
core.create_app = lambda: app
initialized = threading.Event()
core.init_services = initialized.set
port = boot.start_server(0, sys.argv[2], sys.argv[2])
assert port > 0
assert urllib.request.urlopen(f'http://127.0.0.1:{port}/').read() == b'owned-backend'
assert boot.start_server(0, sys.argv[2], sys.argv[2]) == port
assert initialized.wait(5)
boot._server.shutdown()
boot._server.server_close()
"""
    result = subprocess.run([sys.executable, '-B', '-c', script, str(APP_SRC / 'python'),
                             str(data_root)], cwd=PROJECT_ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
