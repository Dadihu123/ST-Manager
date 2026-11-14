"""重建 Android 壳的离线 wheelhouse。

用法：
    python tools/build_android_wheelhouse.py

背景（为什么需要离线 wheelhouse）：
    Chaquopy 默认让 pip 联网装 `pip { install(...) }` 里的依赖。实际构建时
    pip 会对**每个包**同时查询 pypi 与 chaquo.com；后者对不在其仓库里的包
    返回 404，pip 必须等这一轮响应再回退 —— 实测
    `:app:installDebugPythonRequirements` 在这个组合下卡 30+ 分钟无输出。

    解法：把 Android 目标的完整依赖树预下载到 `android/wheelhouse/`，
    构建时用 `--no-index --find-links` 只从本地解析。

关键约束：
    - 必须带 `--platform android_24_arm64_v8a --python-version 3.13
      --implementation cp --abi cp313`，否则拿到的是主机平台的 wheel；
    - Pillow / markupsafe / charset_normalizer 需要 **Android 版** wheel，
      其中 Pillow 及其 `chaquopy-freetype` / `chaquopy-libjpeg` 只有
      chaquo.com 提供；
    - 纯 Python 包（flask/werkzeug/jinja2/click/urllib3/...）平台无关，
      走国内镜像更快。

判定成功的标准：最后的 `pip install --dry-run --no-index` 校验返回 0。
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHEELHOUSE = ROOT / 'android' / 'wheelhouse'

# 与 android/app/build.gradle.kts 的 chaquopy 配置保持一致。
PYTHON_VERSION = '3.13'
PLATFORM = 'android_24_arm64_v8a'
ABI = 'cp313'
REQUIREMENTS = ['Flask>=2.0.0', 'Pillow>=9.0.0', 'requests>=2.28.0']

# 纯 Python 部分：从 PyPI 镜像就能取到全部 wheel。
# Pillow 不在其中 —— 镜像没有 Android 版，见 main() 里的说明。
PYTHON_ONLY_REQUIREMENTS = ['Flask>=2.0.0', 'requests>=2.28.0']

# Pillow 在 Chaquopy 仓库里是 11.0.0，且只依赖这两个专有包。
# 它们的版本下限抄自 pillow wheel 的 METADATA（Requires-Dist）。
CHAQUOPY_ONLY_DEPS = ['chaquopy-freetype>=2.9.1', 'chaquopy-libjpeg>=1.5.3']

MIRROR = 'https://pypi.tuna.tsinghua.edu.cn/simple'
CHAQUO = 'https://chaquo.com/pypi-13.1'

TARGET_ARGS = [
    '--only-binary', ':all:',
    '--platform', PLATFORM,
    '--python-version', PYTHON_VERSION,
    '--implementation', 'cp',
    '--abi', ABI,
    '--disable-pip-version-check',
]


def _pip(args):
    """在当前解释器上跑 pip，返回 (rc, stdout, stderr)。"""
    cmd = [sys.executable, '-m', 'pip', *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    return proc.returncode, proc.stdout or '', proc.stderr or ''


def download(label, packages, index_args):
    print(f'--- {label} ---')
    print(f'    {packages}')
    start = time.time()
    rc, out, err = _pip(['download', *TARGET_ARGS, '-d', str(WHEELHOUSE),
                         *index_args, *packages])
    print(f'    {time.time() - start:.1f}s rc={rc}')
    if rc == 0:
        for line in out.splitlines():
            if 'Saved' in line:
                print('    +', Path(line.split()[-1]).name)
    else:
        print(out)
        print(err, file=sys.stderr)
    return rc == 0


def verify_offline():
    """用 --no-index 校验 wheelhouse 能独立满足全部需求。"""
    print('\n=== 校验：--no-index 能否满足全部依赖 ===')
    rc, out, err = _pip(['install', '--dry-run', '--ignore-installed', *TARGET_ARGS,
                         '--no-index', '--find-links', str(WHEELHOUSE),
                         *REQUIREMENTS])
    print(f'    rc={rc}')
    if rc != 0:
        print(out)
        print(err, file=sys.stderr)
        return False
    return True


def main() -> int:
    WHEELHOUSE.mkdir(parents=True, exist_ok=True)
    print(f'wheelhouse: {WHEELHOUSE}\n')

    # 1) 纯 Python 依赖树走镜像。
    #
    # ⚠️ 这里**不能**把 REQUIREMENTS 整批传进来：PyPI 镜像上没有 Android 版
    # Pillow，pip 会因「Pillow 无法解析」让**整条命令**失败，连 flask/requests
    # 也一起拿不到（曾导致从空目录重建只得到 3 个 wheel）。
    # 因此 Pillow 拆到第 2 步单独走 Chaquopy 仓库。
    if not download('纯 Python 依赖树（镜像）', PYTHON_ONLY_REQUIREMENTS,
                    ['--index-url', MIRROR]):
        return 1

    # 2) Pillow：只有 Chaquopy 仓库有 android_24_arm64_v8a 的 cp313 wheel
    if not download('Pillow（Chaquopy 仓库）', ['Pillow==11.0.0'],
                    ['--index-url', CHAQUO, '--no-deps']):
        return 1

    # 3) Pillow 的两个 Chaquopy 专有依赖
    if not download('Chaquopy 专有依赖', CHAQUOPY_ONLY_DEPS,
                    ['--index-url', CHAQUO, '--no-deps']):
        return 1

    wheels = sorted(WHEELHOUSE.glob('*.whl'))
    print(f'\n=== wheelhouse 共 {len(wheels)} 个 wheel ===')
    for w in wheels:
        print(f'  {w.name}  ({w.stat().st_size // 1024} KB)')

    # 硬性检查：Pillow 必须是 Android wheel
    pillow = [w.name for w in wheels if w.name.lower().startswith('pillow')]
    if not pillow:
        print('\n*** 缺 Pillow wheel ***')
        return 1
    if 'android' not in pillow[0]:
        print(f'\n*** Pillow 不是 Android wheel: {pillow[0]} ***')
        return 1

    if not verify_offline():
        print('\n*** 离线校验失败 ***')
        return 1

    print('\n完成：android/wheelhouse 可用于离线构建')
    return 0


if __name__ == '__main__':
    sys.exit(main())
