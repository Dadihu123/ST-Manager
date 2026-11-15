"""Android 构建产物契约测试（跑真实 Gradle，检查真实 APK）。

为什么需要这个文件
------------------
`test_android_shell.py` 里绝大多数断言是「读源文件 + 断言某个字符串存在」。
这类断言能挡住「别人误删了配置」，但挡不住：

  - Gradle 配置语法写对了、语义却错了（`keyAlias` 赋值被静默丢弃）；
  - 版本号从 `core/version.py` 读到了、但没真正进 APK；
  - APK 打出来了、但 `core/` 没进去（真机上 `ModuleNotFoundError`）。

这些只有**真的构建一次、打开 APK 看**才能发现。本文件就是干这个的。

分层
----
- 标 `slow` 的用例要跑完整 Gradle 构建（首次可能几分钟）。
  默认**跳过**，用 `pytest -m slow` 或 `STM_RUN_SLOW=1` 显式开启。
- 不标 `slow` 的用例只读已存在的构建产物（若产物不存在则 skip），
  这样 CI 先跑 `assembleDebug` 再跑 pytest 就能覆盖到。

设计约束
--------
- 不修改任何源文件；
- 不在仓库里留临时产物（用 tmp_path）；
- 任何「需要 JDK / 需要网络」的前提都 skip 而不是 fail，
  避免在没装 Android 工具链的机器上红一片。
"""

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANDROID_DIR = PROJECT_ROOT / 'android'
DEBUG_APK = ANDROID_DIR / 'app' / 'build' / 'outputs' / 'apk' / 'debug' / 'app-debug.apk'
RELEASE_DIR = ANDROID_DIR / 'app' / 'build' / 'outputs' / 'apk' / 'release'
VERSION_PY = PROJECT_ROOT / 'core' / 'version.py'
BUILD_GRADLE = ANDROID_DIR / 'app' / 'build.gradle.kts'

SLOW = pytest.mark.slow


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def app_version() -> str:
    match = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", read(VERSION_PY))
    assert match, 'core/version.py 里找不到 APP_VERSION'
    return match.group(1)


def expected_version_code(version: str) -> int:
    major, minor, patch = (list(map(int, version.split('-')[0].split('.'))) + [0, 0])[:3]
    return major * 10000 + minor * 100 + patch


def has_gradle() -> bool:
    wrapper = ANDROID_DIR / 'gradlew.bat' if sys.platform == 'win32' else ANDROID_DIR / 'gradlew'
    return wrapper.is_file() and bool(os.environ.get('JAVA_HOME') or shutil.which('java'))


def run_gradle(*args: str, env_extra: dict | None = None, timeout: int = 1800):
    """在 android/ 下跑 gradlew，返回 CompletedProcess。"""
    wrapper = 'gradlew.bat' if sys.platform == 'win32' else './gradlew'
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [wrapper, *args],
        cwd=str(ANDROID_DIR),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
        # Windows 下 gradlew.bat 必须经 cmd 解释
        shell=(sys.platform == 'win32'),
    )


def find_apksigner() -> str | None:
    """定位 apksigner（在 ANDROID_HOME/build-tools/* 下）。"""
    roots = [
        os.environ.get('ANDROID_HOME'),
        os.environ.get('ANDROID_SDK_ROOT'),
        str(Path.home() / 'AppData' / 'Local' / 'Android' / 'Sdk'),
        str(Path.home() / 'Library' / 'Android' / 'sdk'),
        '/usr/local/lib/android/sdk',
    ]
    for root in filter(None, roots):
        build_tools = Path(root) / 'build-tools'
        if not build_tools.is_dir():
            continue
        # 取版本号最大的一个
        versions = sorted(
            (p for p in build_tools.iterdir() if p.is_dir()),
            key=lambda p: [int(x) for x in re.findall(r'\d+', p.name)] or [0],
        )
        for name in ('apksigner.bat', 'apksigner'):
            candidate = versions[-1] / name if versions else None
            if candidate and candidate.is_file():
                return str(candidate)
    return None


def apk_badging(apk: Path) -> dict | None:
    """用 aapt2 读 APK 的 package 信息；找不到 aapt2 返回 None。"""
    roots = [
        os.environ.get('ANDROID_HOME'),
        os.environ.get('ANDROID_SDK_ROOT'),
        str(Path.home() / 'AppData' / 'Local' / 'Android' / 'Sdk'),
        str(Path.home() / 'Library' / 'Android' / 'sdk'),
        '/usr/local/lib/android/sdk',
    ]
    for root in filter(None, roots):
        build_tools = Path(root) / 'build-tools'
        if not build_tools.is_dir():
            continue
        versions = sorted(
            (p for p in build_tools.iterdir() if p.is_dir()),
            key=lambda p: [int(x) for x in re.findall(r'\d+', p.name)] or [0],
        )
        for name in ('aapt2.exe', 'aapt2'):
            aapt2 = versions[-1] / name if versions else None
            if aapt2 and aapt2.is_file():
                proc = subprocess.run(
                    [str(aapt2), 'dump', 'badging', str(apk)],
                    capture_output=True, text=True, timeout=120,
                )
                match = re.search(
                    r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'",
                    proc.stdout,
                )
                if match:
                    return {
                        'package': match.group(1),
                        'versionCode': int(match.group(2)),
                        'versionName': match.group(3),
                    }
    return None


# ---------------------------------------------------------------------------
# 1) 产物内容契约：APK 里必须真的有这些文件
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not DEBUG_APK.is_file(), reason='debug APK 未构建（先在 android/ 跑 assembleDebug）')
def test_debug_apk_contains_core_python_package():
    """`core/` 必须真的打进 APK。

    这是真机第一次跑起来「黑屏」的根因：Chaquopy 默认只打包
    app/src/main/python/，core/ 在仓库根，没同步就报
    `ModuleNotFoundError: No module named 'core'`。
    只看 gradle 文件里有没有 `syncCorePython` 是不够的——
    必须确认编译产物里真的有 core 的字节码。
    """
    with zipfile.ZipFile(DEBUG_APK) as zf:
        names = zf.namelist()
        # Chaquopy 把 Python 源码编译进 app.imy（是个 zip）
        imy = [n for n in names if n.endswith('chaquopy/app.imy')]
        assert imy, f'APK 里找不到 chaquopy/app.imy；条目样例={names[:10]}'
        data = zf.read(imy[0])

    # app.imy 本身是 zip，解出来看内容
    import io
    with zipfile.ZipFile(io.BytesIO(data)) as inner:
        inner_names = inner.namelist()

    core_entries = [n for n in inner_names if n.startswith('core/')]
    assert core_entries, (
        f'app.imy 里没有 core/（真机会报 ModuleNotFoundError）；'
        f'实际条目={inner_names[:15]}'
    )
    # 关键模块抽查，防止只打进一个空目录
    joined = ' '.join(inner_names)
    for module in ('core/__init__', 'core/config', 'core/api/', 'core/services/'):
        assert module in joined, f'app.imy 缺 {module}'

    # 还要有壳自身的入口
    assert any(n.startswith('android_shell/') for n in inner_names), (
        'app.imy 里没有 android_shell/'
    )


@pytest.mark.skipif(not DEBUG_APK.is_file(), reason='debug APK 未构建')
def test_debug_apk_contains_frontend_assets():
    """静态资源必须落在 assets/static 与 assets/templates 下（分层，不摊平）。

    摊平的话 Flask 找不到 INTERNAL_DIR/static，页面白屏。
    """
    with zipfile.ZipFile(DEBUG_APK) as zf:
        names = zf.namelist()

    static_entries = [n for n in names if n.startswith('assets/static/')]
    template_entries = [n for n in names if n.startswith('assets/templates/')]

    assert len(static_entries) > 100, (
        f'assets/static/ 条目过少（{len(static_entries)}），可能目录被摊平'
    )
    assert len(template_entries) > 20, (
        f'assets/templates/ 条目过少（{len(template_entries)}）'
    )

    # 三个关键文件必须在位
    joined = ' '.join(names)
    for needle in ('assets/static/js/state.js', 'assets/templates/layout.html',
                   'assets/templates/index.html'):
        assert needle in joined, f'APK 里缺 {needle}'

    # 不能再出现摊平的痕迹（static 下的同名文件跑到 assets 根）
    flattened = [
        n for n in names
        if n.startswith('assets/') and n.count('/') == 1 and n.endswith('.html')
        and 'templates' not in n and 'static' not in n
    ]
    assert not flattened, f'assets 根下出现摊平的模板文件: {flattened[:5]}'


@pytest.mark.skipif(not DEBUG_APK.is_file(), reason='debug APK 未构建')
def test_debug_apk_has_python_runtime():
    """CPython 运行时与 Chaquopy 依赖必须在。"""
    with zipfile.ZipFile(DEBUG_APK) as zf:
        names = zf.namelist()

    joined = ' '.join(names)
    assert 'lib/arm64-v8a/libpython3' in joined, 'APK 里缺 CPython 运行时'
    assert 'chaquopy/requirements-common.imy' in joined, 'APK 里缺 pip 依赖包'

    # Pip 依赖里必须有 Pillow（把 android 原生 wheel 打进去才有 PIL 可用）
    req = [n for n in names if n.endswith('chaquopy/requirements-common.imy')]
    assert req, '缺 requirements-common.imy'
    with zipfile.ZipFile(DEBUG_APK) as zf:
        size = zf.getinfo(req[0]).file_size
    assert size > 1_000_000, (
        f'requirements-common.imy 只有 {size} 字节，Pillow 等依赖可能没进去'
    )


# ---------------------------------------------------------------------------
# 2) 版本号契约：APK 里的版本必须等于 core/version.py 推导值
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not DEBUG_APK.is_file(), reason='debug APK 未构建')
def test_debug_apk_version_matches_version_py():
    """APK 实际声明的 versionName/versionCode 必须与 core/version.py 一致。

    这是端到端断言：gradle 读没读到文件、读对没有、有没有被覆盖，
    只有看 APK 本身才作数。
    """
    badging = apk_badging(DEBUG_APK)
    if badging is None:
        pytest.skip('未找到 aapt2（需要 Android SDK build-tools）')

    version = app_version()
    assert badging['versionName'] == version, (
        f'APK versionName={badging["versionName"]} 与 core/version.py 的 {version} 不一致'
    )
    assert badging['versionCode'] == expected_version_code(version), (
        f'APK versionCode={badging["versionCode"]}，'
        f'期望 {expected_version_code(version)}（由 {version} 推导）'
    )


@pytest.mark.skipif(not DEBUG_APK.is_file(), reason='debug APK 未构建')
def test_debug_apk_is_signed():
    """debug 包必须带有效签名，否则 `adb install` 直接拒绝。

    注意不能靠查 `META-INF/*.RSA` 判断：AGP 8 在 minSdk >= 24 时**只用 v2**
    签名（v1 被跳过），v2 签名信息在 APK Signing Block 里，不是独立文件。
    因此必须用 apksigner 判断。
    """
    apksigner = find_apksigner()
    if not apksigner:
        pytest.skip('未找到 apksigner（需要 Android SDK build-tools）')

    proc = subprocess.run(
        [apksigner, 'verify', '--verbose', str(DEBUG_APK)],
        capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, (
        f'debug APK 签名无效:\n{proc.stdout}\n{proc.stderr}'
    )
    assert 'Verifies' in proc.stdout


# ---------------------------------------------------------------------------
# 3) 慢速：真的跑一次 release 构建，验证签名链路
# ---------------------------------------------------------------------------

@SLOW
@pytest.mark.skipif(not has_gradle(), reason='需要 JAVA_HOME 与 android/gradlew')
def test_release_build_is_signed_when_secrets_provided(tmp_path):
    """提供签名环境变量时，release 必须产出**已签名且可验证**的 APK。

    想守住的具体故障：`keyAlias = keyAlias` 这类遮蔽会让赋值被静默丢弃，
    Gradle 报 `SigningConfig "release" is missing required property "keyPassword"`。
    光读 gradle 源码看不出这个问题——必须真构建 + apksigner verify。
    """
    apksigner = find_apksigner()
    keytool = shutil.which('keytool')
    if not apksigner or not keytool:
        pytest.skip('需要 apksigner 与 keytool（Android SDK build-tools + JDK）')

    # 生成一次性 keystore
    keystore = tmp_path / 'test.keystore'
    gen = subprocess.run(
        [keytool, '-genkeypair', '-v', '-keystore', str(keystore),
         '-alias', 'testkey', '-keyalg', 'RSA', '-keysize', '2048',
         '-validity', '1', '-storepass', 'testpass123', '-keypass', 'testpass123',
         '-dname', 'CN=Test, OU=Dev, O=STM, L=X, S=X, C=CN'],
        capture_output=True, text=True, timeout=180,
    )
    assert keystore.is_file(), f'keytool 生成 keystore 失败: {gen.stderr[-500:]}'

    result = run_gradle(
        ':app:assembleRelease', '--no-daemon',
        env_extra={
            'ANDROID_KEYSTORE_PATH': str(keystore),
            'ANDROID_KEYSTORE_PASSWORD': 'testpass123',
            'ANDROID_KEY_ALIAS': 'testkey',
            'ANDROID_KEY_PASSWORD': 'testpass123',
        },
    )
    assert result.returncode == 0, (
        f'签名 release 构建失败:\n{(result.stderr or result.stdout)[-3000:]}'
    )

    signed_apk = RELEASE_DIR / 'app-release.apk'
    assert signed_apk.is_file(), (
        f'未产出 app-release.apk（仍可能是 unsigned）；'
        f'实际={[p.name for p in RELEASE_DIR.glob("*.apk")]}'
    )

    verify = subprocess.run(
        [apksigner, 'verify', '--verbose', str(signed_apk)],
        capture_output=True, text=True, timeout=120,
    )
    assert verify.returncode == 0, (
        f'apksigner verify 失败（签名无效）：\n{verify.stdout}\n{verify.stderr}'
    )
    assert 'Verifies' in verify.stdout


@SLOW
@pytest.mark.skipif(not has_gradle(), reason='需要 JAVA_HOME 与 android/gradlew')
def test_release_build_degrades_to_unsigned_without_secrets():
    """不提供签名变量时，release 应以 unsigned 产出并成功构建（本地开发不被拦住）。

    这条和上一条是互斥语义的两半：
      有密钥 → 签出可安装包；
      无密钥 → 仍能构建，但产物名字带 unsigned，且**不应**冒充已签名。
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('ANDROID_KEYSTORE') and not k.startswith('ANDROID_KEY_')}

    result = subprocess.run(
        ['gradlew.bat' if sys.platform == 'win32' else './gradlew',
         ':app:assembleRelease', '--no-daemon'],
        cwd=str(ANDROID_DIR), capture_output=True, text=True,
        timeout=1800, env=env, shell=(sys.platform == 'win32'),
    )
    assert result.returncode == 0, (
        f'无密钥时 release 构建不应失败:\n{(result.stderr or result.stdout)[-3000:]}'
    )

    unsigned = RELEASE_DIR / 'app-release-unsigned.apk'
    assert unsigned.is_file(), (
        f'无密钥时应产出 app-release-unsigned.apk；'
        f'实际={[p.name for p in RELEASE_DIR.glob("*.apk")]}'
    )
