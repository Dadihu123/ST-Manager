"""宿主图标名映射生成器（前端）。

把 `static/icons/*.svg` 里的 `id="icon-*"` 解析成 `名字 → 精灵文件` 映射，写出
`static/js/utils/iconMap.js`。前端 `api.ui.icon(name)` 据此拼出
`<use href="/static/icons/<sprite>.svg#icon-<name>">`。

为什么需要生成而不是运行期解析：前端在首屏就要用图标，若靠 `fetch` 拉
`GET /api/plugins/ui-icons` 会引入一次额外的网络往返与启动顺序耦合；而
`static/` 在 PyInstaller 打包态是只读快照，运行期解析也要读文件。
生成成常量表最省事，且与后端 `core/plugins/icons.py` 用的是同一份来源。

用法（仓库根目录）：

```powershell
python tools/gen_plugin_ui_icons.py           # 重新生成
python tools/gen_plugin_ui_icons.py --check   # 只校验是否为最新（不写文件）
```

新增图标后必须重跑本脚本；`tests/test_plugin_icons.py` 会断言生成物与精灵一致。
"""

import argparse
import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins.icons import HOST_ICON_SPRITES, icons_dir

TARGET_PATH = os.path.join(PROJECT_ROOT, 'static', 'js', 'utils', 'iconMap.js')

GENERATED_HEADER = (
    '/**\n'
    ' * static/js/utils/iconMap.js\n'
    ' * 宿主图标名 → 精灵文件映射。\n'
    ' *\n'
    ' * ⚠️ 本文件由 `python tools/gen_plugin_ui_icons.py` 生成，请勿手工编辑。\n'
    ' * 来源：`static/icons/*.svg` 里的 `id="icon-*"`，与后端\n'
    ' * `core/plugins/icons.py` 读的是同一份精灵，因此两侧永不漂移。\n'
    ' */\n'
)

_ICON_ID_PATTERN = re.compile(r'id="icon-([^"]+)"')

# 模板宏里的别名（`templates/components/icon.html`）：
# - `icon()` 宏把 `plus` 映射为 `plus-square`
# - `detail_icon()` 宏把 `grid` 映射为 `layout`
# 插件写别名时必须能解析，否则「宿主图标名」这层契约就漏了最常见的两个。
#
# 历史改名（D4 契约：图标名改名走 deprecation，旧名保留为别名）：
# - `arrow-left` → `arrow-left-outline`：空心长柄箭头，与实心粗箭头 arrow-right
#   不是同一套图形；改名是让名字自己说清楚，避免再被当成左右镜像对使用。
ICON_ALIASES = {
    'plus': 'plus-square',
    'grid': 'layout',
    'arrow-left': 'arrow-left-outline',
}


def build_icon_map() -> dict:
    """解析全部精灵，返回 `{名字: 精灵文件名}`（同名以先声明者为准）。"""
    index = {}
    directory = icons_dir()
    for sprite in HOST_ICON_SPRITES:
        path = os.path.join(directory, sprite)
        try:
            with open(path, 'r', encoding='utf-8') as handle:
                source = handle.read()
        except OSError as exc:
            print(f'⚠️  读取图标精灵失败 {sprite}: {exc}', file=sys.stderr)
            continue
        for name in _ICON_ID_PATTERN.findall(source):
            index.setdefault(str(name), sprite)
    return index


def render() -> str:
    index = build_icon_map()

    lines = [GENERATED_HEADER]
    lines.append('/** 名字 → 精灵文件名（如 `wand` → `ui.svg`）。 */')
    lines.append('export const ICON_SPRITE_MAP = Object.freeze({')
    for name in sorted(index):
        lines.append(f'  "{name}": "{index[name]}",')
    lines.append('});')
    lines.append('')
    lines.append('/** 模板宏里的别名，插件写别名也能解析。 */')
    lines.append('export const ICON_ALIASES = Object.freeze({')
    for alias, target in sorted(ICON_ALIASES.items()):
        lines.append(f'  "{alias}": "{target}",')
    lines.append('});')
    lines.append('')
    lines.append(f'/** 宿主图标总数（{len(index)}）。 */')
    lines.append(f'export const HOST_ICON_COUNT = {len(index)};')
    lines.append('')
    return '\n'.join(lines)


def write_document() -> bool:
    """写入映射；内容无变化时返回 False。"""
    content = render()
    if os.path.isfile(TARGET_PATH):
        with open(TARGET_PATH, 'r', encoding='utf-8') as handle:
            if handle.read() == content:
                return False
    with open(TARGET_PATH, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(content)
    return True


def check_document() -> bool:
    """生成物是否与当前精灵一致。"""
    if not os.path.isfile(TARGET_PATH):
        return False
    with open(TARGET_PATH, 'r', encoding='utf-8') as handle:
        return handle.read() == render()


def _configure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError, ValueError):
        pass


def main(argv=None) -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description='生成前端宿主图标名映射')
    parser.add_argument('--check', action='store_true', help='只校验，不写文件')
    args = parser.parse_args(argv)

    if args.check:
        if check_document():
            print('✅ static/js/utils/iconMap.js 已是最新')
            return 0
        print('❌ iconMap.js 与精灵不一致，请运行 python tools/gen_plugin_ui_icons.py')
        return 1

    changed = write_document()
    print('✅ 已生成 static/js/utils/iconMap.js' if changed else '✅ iconMap.js 无变化')
    return 0


if __name__ == '__main__':
    sys.exit(main())
