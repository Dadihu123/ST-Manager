"""插件更新说明：按锚点切分 CHANGELOG（纯函数，无 IO、无网络）。

**只认锚点，不从标题猜版本。** 原因是插件仓库的 CHANGELOG 是长期演进的自由文本，
真实结构很乱：`## 0.3.0（2026-10-25）` 这类版本标题与 `### 2026-10-24 …` 这类
日期标题混用，甚至出现 `## P3 可用性修复（2026-10-11…）` 这种根本不是版本号的
标题。任何「从标题里猜版本」的规则都会在真实文件上错切，而错切比没有更糟——用户
会在更新确认弹层里看到**别的版本**的改动说明，并据此决定要不要更新。

因此宿主与插件仓库约定显式锚点（两侧同一格式）：

    <!-- release: 0.4.1 -->
    ## 0.4.1（2026-11-10）
    ### 修复
    - …
    <!-- /release -->

版本标题行在锚点**内部**，所以切出来的 `body` 含 `## 0.4.1` 这一行（前端直接渲染
markdown 即可）。**没有锚点的旧内容一律忽略**：插件侧补齐锚点之前，该插件的更新
说明就是空的（回退到「无说明」分支），而不是给出可能错误的说明。

语义化版本比较复用 `core.plugins.manifest` 的 `parse_semver` / `compare_versions`，
本模块不重复实现。
"""

import re

from core.plugins.manifest import compare_versions, parse_semver

# `<!-- release: 0.4.1 -->`：拦截 HTML 注释形式的开锚点
OPEN_ANCHOR_PATTERN = re.compile(r'<!--\s*release\s*:\s*(?P<version>[^\s<>]+)\s*-->')
# `<!-- /release -->`：闭锚点（没有版本号，所以不会被开锚点正则匹配到）
CLOSE_ANCHOR_PATTERN = re.compile(r'<!--\s*/\s*release\s*-->')


def parse_release_sections(text) -> list:
    """把 CHANGELOG 正文按锚点切成 `[{'version', 'body'}]`，保持文件出现顺序。

    - 版本号不是合法 semver 的段落跳过（标题里的版本号**不参与**判断）；
    - 开锚点之后找不到闭锚点即视为未闭合，跳过该段及之后的内容（后半段无法可靠
      界定，宁缺毋错）；
    - `body` 是两锚点之间的原文并 strip，含版本标题行；
    - 空正文的段落跳过（带上它只会得到一条空说明）。
    """
    if not isinstance(text, str) or not text:
        return []

    sections = []
    cursor = 0
    while True:
        opening = OPEN_ANCHOR_PATTERN.search(text, cursor)
        if opening is None:
            break

        closing = CLOSE_ANCHOR_PATTERN.search(text, opening.end())
        if closing is None:
            break

        version = opening.group('version').strip()
        body = text[opening.end():closing.start()].strip()
        cursor = closing.end()

        if parse_semver(version) is None or not body:
            continue
        sections.append({'version': version, 'body': body})

    return sections


def slice_release_sections(sections, *, from_version, to_version) -> list:
    """取 `(from_version, to_version]` 区间，按版本号**倒序**（新的在前）。

    - `from_version` 为空或非法时视为「无下界」，只受 `to_version` 约束；
    - `to_version` 为空或非法时返回空列表（没有上界就无法确定区间）；
    - 同版本去重，保留首次出现。
    """
    if not sections:
        return []

    upper = parse_semver(to_version) if isinstance(to_version, str) else None
    if upper is None:
        return []

    lower = parse_semver(from_version) if isinstance(from_version, str) else None

    picked = []
    seen = set()
    for section in sections:
        if not isinstance(section, dict):
            continue
        version = str(section.get('version') or '').strip()
        if parse_semver(version) is None or version in seen:
            continue
        seen.add(version)

        if compare_versions(version, to_version) > 0:
            continue
        if lower is not None and compare_versions(version, from_version) <= 0:
            continue

        picked.append({'version': version, 'body': str(section.get('body') or '').strip()})

    picked.sort(key=lambda item: parse_semver(item['version']) or (0, 0, 0), reverse=True)
    return picked


def compose_release_notes(text, *, from_version, to_version) -> str:
    """parse + slice + `\\n\\n` join；拿不到就返回 `''`，**绝不抛异常**。

    更新说明只是提示信息，它不能成为更新检查失败的原因：Release 正文、远端
    CHANGELOG 都是外部输入，任何形状都只允许降级为「无说明」。
    """
    try:
        picked = slice_release_sections(
            parse_release_sections(text),
            from_version=from_version,
            to_version=to_version,
        )
    except Exception:  # noqa: BLE001 - 更新说明绝不能中断更新检查
        return ''

    return '\n\n'.join(item['body'] for item in picked if item['body'])
