"""Android 版本号契约测试。

版本号的单一来源是仓库根的 `core/version.py`（桌面端与插件契约都用它）。
`android/app/build.gradle.kts` 从这里读取并推导 `versionCode`，本文件守住两条：

1. versionName 与 APP_VERSION 一致（不允许手写漂移）；
2. versionCode 推导公式单调递增（否则覆盖安装会失败）。
"""

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERSION_PY = PROJECT_ROOT / 'core' / 'version.py'
BUILD_GRADLE = PROJECT_ROOT / 'android' / 'app' / 'build.gradle.kts'


def read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def app_version() -> str:
    match = re.search(r"APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]", read(VERSION_PY))
    assert match, 'core/version.py 里找不到 APP_VERSION'
    return match.group(1)


def expected_version_code(version: str) -> int:
    """与 build.gradle.kts 里的公式保持一致：major*10000 + minor*100 + patch。"""
    parts = [int(p) for p in version.split('-')[0].split('.')]
    parts += [0] * (3 - len(parts))
    return parts[0] * 10000 + parts[1] * 100 + parts[2]


def test_gradle_reads_version_from_version_py():
    """versionName 必须从 core/version.py 读，不能手写常量。

    手写的话，发版时改了 version.py 忘了改 gradle，
    会出现「设置页显示 1.2.0、APK 实际 1.1.0」这种对不上的情况。
    """
    gradle = read(BUILD_GRADLE)

    # 必须真的去读文件，而不是写死
    assert 'core/version.py' in gradle, 'gradle 应从 core/version.py 读版本'
    assert 'APP_VERSION' in gradle

    # versionName 必须绑定到推导出的变量
    assert re.search(r'versionName\s*=\s*appVersion\b', gradle), (
        'versionName 应绑定 appVersion 变量'
    )
    assert re.search(r'versionCode\s*=\s*appVersionCode\b', gradle), (
        'versionCode 应绑定 appVersionCode 变量'
    )


def test_gradle_does_not_hardcode_version():
    """不允许在 gradle 里写死版本号字面量。"""
    gradle = read(BUILD_GRADLE)
    hardcoded_name = re.search(r'versionName\s*=\s*"[\d.]+"', gradle)
    hardcoded_code = re.search(r'versionCode\s*=\s*\d+\s*$', gradle, re.M)
    assert not hardcoded_name, f'versionName 不应写死: {hardcoded_name.group(0)}'
    assert not hardcoded_code, f'versionCode 不应写死: {hardcoded_code.group(0)}'


def test_version_code_formula_is_stable():
    """核对 versionCode 公式，并把边界写清楚。

    公式必须保证：任意两个不同版本推出的 code 不相等，且新版本一定更大。
    这也解释了为什么 minor/patch 必须 < 100（gradle 里有 require 守住）。
    """
    assert expected_version_code('1.2.0') == 10200
    assert expected_version_code('1.2.1') == 10201
    assert expected_version_code('1.3.0') == 10300
    assert expected_version_code('2.0.0') == 20000
    assert expected_version_code('1.2') == 10200  # 缺省段按 0 处理

    # 单调性：1.2.0 < 1.2.1 < 1.3.0 < 2.0.0
    codes = [expected_version_code(v) for v in ('1.2.0', '1.2.1', '1.3.0', '2.0.0')]
    assert codes == sorted(codes)


def test_current_version_code_is_derived_correctly():
    """当前 APP_VERSION 推出的 versionCode 必须与公式一致且为正。"""
    version = app_version()
    code = expected_version_code(version)
    assert code > 0, f'{version} 推出的 versionCode 必须为正'
    # Android 的 versionCode 上限
    assert code < 2_100_000_000


def test_gradle_guards_version_segment_overflow():
    """gradle 里必须有 minor/patch < 100 的守卫。

    没有守卫的话，1.100.0 会推出 20000，与 2.0.0 撞车 —— 覆盖安装会静默失败。
    """
    gradle = read(BUILD_GRADLE)
    assert 'minor < 100' in gradle or 'minor<100' in gradle, (
        'gradle 应校验 minor < 100，避免 versionCode 串位'
    )
    assert 'patch < 100' in gradle or 'patch<100' in gradle


# ---------------------------------------------------------------------------
# 签名契约
# ---------------------------------------------------------------------------

def test_signing_reads_all_material_from_env():
    """签名材料必须全部来自环境变量，仓库里不能有密钥或口令。"""
    gradle = read(BUILD_GRADLE)
    for var in (
        'ANDROID_KEYSTORE_PATH',
        'ANDROID_KEYSTORE_PASSWORD',
        'ANDROID_KEY_ALIAS',
        'ANDROID_KEY_PASSWORD',
    ):
        assert var in gradle, f'签名配置应读取环境变量 {var}'


def test_no_keystore_committed():
    """仓库里不允许出现 keystore 文件。"""
    leaked = [
        p for p in PROJECT_ROOT.rglob('*')
        if p.is_file()
        and p.suffix.lower() in {'.keystore', '.jks'}
        and '.git' not in p.parts
        and 'tmp' not in p.parts          # 本地验证用的临时目录
        and 'build' not in p.parts        # 构建产物
    ]
    assert not leaked, f'发现被提交的 keystore: {leaked[:5]}'


def test_signing_is_optional_for_local_debug():
    """缺签名变量时不能让 `assembleDebug` 失败。

    本地开发者只跑 debug 时不该被迫配置 keystore。
    实现上体现为：signingConfig 只在 hasReleaseSigning 为真时创建。
    """
    gradle = read(BUILD_GRADLE)
    assert 'hasReleaseSigning' in gradle
    # release 的 signingConfig 必须条件赋值，不能无条件 getByName
    assert re.search(
        r'signingConfig\s*=\s*if\s*\(hasReleaseSigning\)', gradle
    ), 'release.signingConfig 应条件赋值，缺变量时退化为 unsigned'


def test_v1_signing_disabled_for_min_sdk_24():
    """minSdk 24 时 v1 签名冗余，应显式关闭并写明理由。

    v2 从 Android 7.0（API 24）开始支持，正好等于 minSdk，
    因此 AGP 会跳过 v1。若将来降低 minSdk，必须同时打开 v1。
    """
    gradle = read(BUILD_GRADLE)
    assert 'enableV1Signing' in gradle
    assert 'enableV2Signing' in gradle
    # 注释里要说明「降 minSdk 就要开 v1」，否则后人不知道为何是 false
    assert 'minSdk' in gradle.split('enableV1Signing')[0][-600:]


# ---------------------------------------------------------------------------
# CI 发布链路契约
# ---------------------------------------------------------------------------

WORKFLOW = PROJECT_ROOT / '.github' / 'workflows' / 'build-android.yml'


def test_ci_builds_signed_release_on_tag():
    """tag 构建必须签出可分发的 release APK，并校验签名。

    只出 debug 包的话，Release 页面上会挂一个所有用户都装不上的包。
    """
    wf = read(WORKFLOW)

    assert 'assembleRelease' in wf, 'CI 应构建 release 变体'
    assert 'ANDROID_KEYSTORE_BASE64' in wf, '应从 secret 解码 keystore'
    # 解码后必须收紧权限
    assert 'chmod 600' in wf, 'keystore 应限制为 600'
    # 关键：必须用 apksigner 验证产物真的被签过。
    # 匹配 `verify` 子命令即可——脚本里是可执行文件变量（"$signer" verify），
    # 不是字面量 `apksigner verify`。
    assert 'apksigner' in wf, '应使用 apksigner 校验'
    assert ' verify ' in wf or 'verify --verbose' in wf, (
        '必须校验产物签名，否则签名配置写错会一路绿灯到用户安装失败'
    )


def test_ci_release_only_on_tags():
    """release 相关步骤只能在 tag 上跑，避免每次 push 都动 Release。"""
    wf = read(WORKFLOW)
    # 每个 release 步骤都应带 tag 条件
    for marker in ('Decode release keystore', 'Build signed release APK',
                   'Verify release APK is signed'):
        block = wf.split(marker, 1)
        assert len(block) == 2, f'未找到步骤 {marker}'
        header = block[1].split('run:', 1)[0]
        assert 'startsWith(github.ref' in header, f'步骤 {marker} 应限定 tag'


def test_ci_fails_loudly_when_secrets_missing():
    """缺签名 secret 时必须**失败**，不能悄悄出 unsigned 包。"""
    wf = read(WORKFLOW)
    assert '缺少 secret ANDROID_KEYSTORE_BASE64' in wf
    assert 'exit 1' in wf
    # 还要校验另外三个变量
    assert 'ANDROID_KEYSTORE_PASSWORD' in wf
    assert 'ANDROID_KEY_ALIAS' in wf
    assert 'ANDROID_KEY_PASSWORD' in wf


def test_ci_publishes_apk_to_release():
    """Android 必须有自己的 Release 上传步骤，否则用户下不到安装包。"""
    wf = read(WORKFLOW)
    assert 'gh release upload' in wf, '应把 APK 挂到 Release'
    assert '--clobber' in wf, '重跑时应覆盖同名资产'
    # 只在缺失时创建，绝不覆盖已有正文（与桌面端约定一致）
    assert 'gh release view' in wf
    assert '--generate-notes' in wf


def test_release_asset_name_matches_desktop_convention():
    """Release 资产名应与桌面端同一格式：ST-Manager-Pro-<ver>-<platform>-<arch>.<ext>"""
    wf = read(WORKFLOW)
    assert 'ST-Manager-Pro-${version}-android-arm64.apk' in wf, (
        'Release 资产名应对齐桌面端命名约定'
    )


def test_artifact_name_does_not_shadow_desktop():
    """artifact 名不得用 ST-Manager-Pro- 前缀（会污染桌面 publish-release 的匹配）。"""
    wf = read(WORKFLOW)
    for match in re.finditer(r'name:\s*(ST-Manager[\w.-]*)', wf):
        name = match.group(1)
        assert not name.startswith('ST-Manager-Pro-'), (
            f'artifact 名 {name} 会污染桌面 publish-release'
        )


# ---------------------------------------------------------------------------
# 工作流结构契约（解析 YAML，而不是字符串匹配）
#
# 字符串断言能挡住「删掉了某行」，但挡不住「步骤顺序错了」「条件挂错 job」。
# 下面几条真的把 YAML 解析成结构再断言。
# ---------------------------------------------------------------------------

def load_workflow() -> dict:
    yaml = pytest.importorskip('yaml')
    # PyYAML 把裸 `on:` 解析成布尔 True，这是 YAML 1.1 的已知行为，
    # 不是文件问题。这里做一次归一化，免得每条用例都处理。
    data = yaml.safe_load(read(WORKFLOW))
    if True in data and 'on' not in data:
        data['on'] = data.pop(True)
    return data


def test_workflow_structure_is_valid():
    """工作流必须解析出预期的 job 图。"""
    wf = load_workflow()

    assert 'build-apk' in wf['jobs']
    assert 'publish-release' in wf['jobs']

    # publish-release 只依赖 build-apk
    assert wf['jobs']['publish-release']['needs'] == ['build-apk']

    # 只在 tag 上发布
    assert 'refs/tags/v' in wf['jobs']['publish-release']['if']


def test_workflow_step_order_is_correct():
    """步骤顺序必须满足依赖链。

    顺序错了会出现很难查的故障：比如先打包再生成 wheelhouse，
    Chaquopy 找不到依赖；或者签名在构建之后才解码 keystore。
    """
    wf = load_workflow()
    steps = wf['jobs']['build-apk']['steps']
    names = [s.get('name', '') for s in steps]

    def idx(fragment: str) -> int:
        for i, n in enumerate(names):
            if fragment in n:
                return i
        raise AssertionError(f'找不到步骤「{fragment}」；实际={names}')

    # Python/Java 必须在 Gradle 之前
    assert idx('Set up Python') < idx('Kotlin compile and unit tests')
    assert idx('Set up JDK') < idx('Kotlin compile and unit tests')

    # wheelhouse 必须在构建之前（Chaquopy 会用 --no-index 找它）
    assert idx('wheelhouse') < idx('Kotlin compile and unit tests')

    # 解码 keystore 必须在使用它构建 release 之前
    assert idx('Decode release keystore') < idx('Build signed release APK')

    # 签名校验必须在构建之后
    assert idx('Build signed release APK') < idx('Verify release APK is signed')

    # 上传 artifact 在最后
    assert idx('Upload debug APK') > idx('Build debug APK')


def test_workflow_signing_steps_are_gated_on_tag():
    """所有签名相关步骤都必须带 tag 条件。"""
    wf = load_workflow()
    steps = wf['jobs']['build-apk']['steps']

    signing_steps = [
        s for s in steps
        if any(k in s.get('name', '')
               for k in ('Decode release keystore', 'Build signed release APK',
                         'Verify release APK is signed', 'Normalize release APK name'))
    ]
    assert len(signing_steps) == 4, (
        f'预期 4 个签名相关步骤，实际 {len(signing_steps)}: '
        f'{[s.get("name") for s in signing_steps]}'
    )

    for step in signing_steps:
        assert 'if' in step, f'步骤「{step["name"]}」缺少 if 条件'
        assert 'refs/tags/v' in step['if'], (
            f'步骤「{step["name"]}」的 if 应限定 tag，实际={step["if"]}'
        )


def test_workflow_uses_secrets_not_hardcoded_values():
    """签名口令必须来自 secrets，不能写在 workflow 里。"""
    wf_text = read(WORKFLOW)

    # 必须引用 secrets 上下文
    assert 'secrets.ANDROID_KEYSTORE_BASE64' in wf_text
    assert 'secrets.ANDROID_KEYSTORE_PASSWORD' in wf_text
    assert 'secrets.ANDROID_KEY_ALIAS' in wf_text
    assert 'secrets.ANDROID_KEY_PASSWORD' in wf_text

    # 不能有像口令的字面量（粗略启发式：等号赋值给 password 类变量）
    suspicious = re.findall(
        r'(?i)(?:password|passwd|storepass)\s*[:=]\s*["\']?[a-zA-Z0-9!@#$%^&*]{6,}',
        wf_text,
    )
    assert not suspicious, f'workflow 里疑似硬编码了口令: {suspicious[:3]}'


def test_workflow_keystore_is_cleaned_up_or_temp():
    """keystore 解码到 runner 临时目录，不能落到仓库工作区。"""
    wf_text = read(WORKFLOW)
    assert 'RUNNER_TEMP' in wf_text, (
        'keystore 应解码到 $RUNNER_TEMP，避免残留到工作区'
    )
