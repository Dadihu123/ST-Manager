"""设计令牌契约测试。

守护 `docs/ui-audit-refactoring-ui.md` 里定下的标尺：

- 字号 / 间距 / 圆角 / 层级 / 字重五套标尺必须存在；
- 不允许引用未定义的 CSS 变量（无 fallback 的引用会静默失效）；
- 不再新增标尺外的圆角与字重字面量。

这些断言刻意只锁“新增不退化”，不强行改写历史值 —— 逐屏迁移需要时间，
一次性断言全部合规会立刻红。已有白名单量出当前基线，迁移时只允许缩小。
"""

from pathlib import Path
import re

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CSS_DIR = PROJECT_ROOT / 'static' / 'css'
TOKENS_CSS = CSS_DIR / 'modules' / 'ui-refresh.css'
VARIABLES_CSS = CSS_DIR / 'modules' / 'variables.css'


def _read(path):
    return path.read_text(encoding='utf-8')


def _all_css():
    return {
        path.name: path.read_text(encoding='utf-8')
        for path in CSS_DIR.rglob('*.css')
        if path.name != 'tailwind.css'
    }


def test_scale_tokens_are_defined():
    """五套标尺必须都在 `ui-refresh.css` 的 `:root` 里。"""
    tokens = _read(TOKENS_CSS)

    # 字号：12 / 14 / 16 / 18 / 20 / 24 / 30
    for name, value in (
        ('--text-xs', '0.75rem'),
        ('--text-sm', '0.875rem'),
        ('--text-md', '1rem'),
        ('--text-lg', '1.125rem'),
        ('--text-xl', '1.25rem'),
        ('--text-2xl', '1.5rem'),
        ('--text-3xl', '1.875rem'),
    ):
        assert re.search(rf'{name}:\s*{re.escape(value)};', tokens), f'缺少或写错 {name}'

    # 间距：4 / 8 / 12 / 16 / 24 / 32 / 48 / 64
    for name, value in (
        ('--space-1', '0.25rem'),
        ('--space-2', '0.5rem'),
        ('--space-3', '0.75rem'),
        ('--space-4', '1rem'),
        ('--space-5', '1.5rem'),
        ('--space-6', '2rem'),
        ('--space-7', '3rem'),
        ('--space-8', '4rem'),
    ):
        assert re.search(rf'{name}:\s*{re.escape(value)};', tokens), f'缺少或写错 {name}'

    # 圆角：4 / 8 / 12 / 16 四档 + pill
    for name, value in (
        ('--radius-sm', '0.25rem'),
        ('--radius-md', '0.5rem'),
        ('--radius-lg', '0.75rem'),
        ('--radius-xl', '1rem'),
        ('--radius-pill', '999px'),
    ):
        assert re.search(rf'{name}:\s*{re.escape(value)};', tokens), f'缺少或写错 {name}'

    # 字重：只有两档语义
    assert '--weight-regular: 500;' in tokens
    assert '--weight-strong: 700;' in tokens


def test_five_elevation_steps_are_defined():
    """层级必须有五档，且不能与既有 `--shadow-elevation` 冲突。"""
    tokens = _read(TOKENS_CSS)
    for step in range(1, 6):
        assert re.search(rf'--elevation-{step}:\s*0\s', tokens), f'缺少 --elevation-{step}'

    # 旧名映射必须指向新标尺，而不是各自写死的字面量
    for alias in ('--shadow-sm', '--shadow-md', '--shadow-lg', '--shadow-xl'):
        assert re.search(rf'{alias}:\s*var\(--elevation-\d\)', tokens), f'{alias} 未映射到 elevation'

    # --shadow-elevation 由 variables.css 拥有，ui-refresh 不得覆盖它
    assert '--shadow-elevation:' not in tokens, (
        'ui-refresh.css 不应重定义 --shadow-elevation，会静默改变所有模态的阴影'
    )


def test_no_undefined_css_variable_references():
    """所有 `var(--x)` 引用都必须有定义。

    允许两类例外：
    - 由 JS 写入的变量（`state.js` / `uiPrimitives.js` 等）；
    - 测试/插件侧动态注入的变量。
    """
    js_sources = '\n'.join(
        path.read_text(encoding='utf-8', errors='ignore')
        for path in (PROJECT_ROOT / 'static' / 'js').rglob('*.js')
    )
    js_defined = set(re.findall(r'["\'](--[a-zA-Z0-9-]+)["\']', js_sources))
    js_defined |= set(re.findall(r'updateCssVariable\(\s*["\'](--[a-zA-Z0-9-]+)["\']', js_sources))

    # 由 JS 在运行时注入，CSS 侧查不到定义是正常的
    runtime_defined = {
        '--app-viewport-height',
        '--app-viewport-height-safe',
        '--ui-icon-mask',
        '--ui-grid-columns',
        '--ui-grid-gap',
        '--ui-split-left',
        '--deal-index',
        '--from-rot',
        '--from-x',
        '--rarity-color',
        '--rarity-gradient',
        '--preset-editor-range-progress',
        '--beautify-active-shadow',
        # state.js 的 buildTagColorStyle() 逐次注入明/暗两套标签颜色
        '--tag-cat-color',
        '--tag-cat-opacity',
        '--tag-cat-bg-dark',
        '--tag-cat-bg-light',
        '--tag-cat-border-dark',
        '--tag-cat-border-light',
        '--tag-cat-text-dark',
        '--tag-cat-text-light',
        '--tag-cat-hover-bg-dark',
        '--tag-cat-hover-bg-light',
        '--tag-cat-hover-text-dark',
        '--tag-cat-hover-text-light',
        '--tag-cat-active-bg-dark',
        '--tag-cat-active-bg-light',
        '--tag-cat-active-border-dark',
        '--tag-cat-active-border-light',
        '--tag-cat-active-text-dark',
        '--tag-cat-active-text-light',
        # detailModal.js 在运行时写入的正文分栏轨道宽度
        '--detail-basic-left-track',
        '--detail-basic-right-track',
    }

    css_sources = _all_css()
    defined = set()
    for source in css_sources.values():
        defined |= set(re.findall(r'(--[a-zA-Z0-9-]+)\s*:', source))
    defined |= js_defined | runtime_defined

    undefined = {}
    for name, source in css_sources.items():
        for match in re.finditer(r'var\(\s*(--[a-zA-Z0-9-]+)', source):
            token = match.group(1)
            if token not in defined:
                undefined.setdefault(token, set()).add(name)

    assert not undefined, '存在未定义的 CSS 变量引用：' + ', '.join(
        f'{token} ({", ".join(sorted(files))})' for token, files in sorted(undefined.items())
    )


def test_letter_spacing_on_uppercase_labels():
    """全大写文本必须带字距，默认字距是按句首大写调校的。"""
    css_sources = _all_css()
    offenders = []
    for name, source in css_sources.items():
        for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', source):
            selector, body = match.group(1).strip(), match.group(2)
            if 'text-transform: uppercase' in body and 'letter-spacing' not in body:
                offenders.append(f'{name}: {selector.splitlines()[-1].strip()}')
    assert not offenders, '全大写但缺 letter-spacing：' + '; '.join(offenders)


def test_primary_action_outweighs_secondary():
    """主操作必须比次操作更有视觉权重，但仍然属于本项目的材质语言。

    这条契约的由来：
    - 初版审计发现 `.btn-primary` 用 accent 9–14% 极浅 tint，实测文字对比度
      5.91:1，而 `.btn-secondary` 的中性底是 10.48:1 —— 主操作反而更弱。
    - 第一版修复把它改成了不透明实心 accent + 白字。那在深色玻璃质感界面里
      像贴纸一样浮在表面，与整体材质脱节（设置页"保存并应用"一直在用染色
      抬升底，那才是本项目的语言）。
    - 现在的做法：**提高 accent 染色浓度 + accent 描边 + accent 亮文字**，
      与 secondary 的"中性底 + 中性描边 + 灰字"在色相与饱和上拉开，
      不靠不透明实心来区分。
    """
    semantic = _read(CSS_DIR / 'color-system.css')
    block = semantic.split('.btn-primary,\nbutton.btn-primary {', 1)[1].split('}', 1)[0]

    # 必须是 accent 染色底，不是中性底、也不是不透明实心
    assert 'background-color: var(--action-surface-hover) !important;' in block
    assert 'color: var(--accent-text) !important;' in block
    # 不能退回最浅的一档（那会再次弱于 secondary）
    assert 'var(--action-surface) !important' not in block
    # 也不能用不透明实心（会与深色玻璃材质脱节）
    assert 'var(--accent-action) !important' not in block

    # 三级层级必须齐全
    assert '.btn-secondary,' in semantic
    assert '.btn-tertiary {' in semantic


def test_global_toast_is_a_live_region():
    """全局 Toast 是唯一的反馈通道，必须能被屏幕阅读器读到。"""
    layout = (PROJECT_ROOT / 'templates' / 'layout.html').read_text(encoding='utf-8')
    toast_index = layout.index('toast-notification')
    window = layout[toast_index : toast_index + 400]
    assert 'role="status"' in window, 'Toast 缺 role="status"'
    assert 'aria-live="polite"' in window, 'Toast 缺 aria-live'


@pytest.mark.parametrize(
    'token_path',
    ['static/css/modules/ui-primitives.css', 'static/css/modules/view-wi.css'],
)
def test_disabled_workbench_surfaces_use_defined_tokens(token_path):
    """曾经引用过不存在的令牌，导致整条声明静默失效。"""
    source = (PROJECT_ROOT / token_path).read_text(encoding='utf-8')
    for bad in ('--border-danger', '--surface-violet', '--accent-tint', '--action-text-hover'):
        assert f'var({bad}' not in source, f'{token_path} 又引用了未定义的 {bad}'


# ---------------------------------------------------------------- 跨页面一致性

CONSISTENCY_CSS = CSS_DIR / 'modules' / 'consistency.css'


def test_cross_page_consistency_layer_exists():
    """跨页面组件一致性层必须存在，且用足够的特异性真正压过模块规则。"""
    css = _read(CONSISTENCY_CSS)
    marker = '跨页面组件一致性层'
    assert marker in css, '一致性层被删除了'

    layer = css.split(marker, 1)[1]
    for family in (
        '图标按钮',
        '徽章',
        '空状态',
        '工具条',
        '表单标签',
        '行宽（measure）',
        '破坏性动作',
    ):
        assert family in layer, f'一致性层缺少「{family}」小节'

    # 这条是踩过坑的：第一版用 `:where()`（特异性 0），结果**压不过任何模块规则**。
    # 例如 `.ui-detail-modal .detail-modal--workbench .detail-topbar-icon-action`
    # 是 (0,3,0)，直接盖掉了 `:where(...)` 的 border-radius。
    # 因此一致性层必须在文件里留下"为什么不用 :where"的说明，并确实不用它作为主选择器。
    assert '为什么不用' in layer or '第一版用了' in layer, (
        '一致性层应保留「为何不用 :where()」的说明，避免后人重蹈覆辙'
    )
    # 主选择器必须是普通类选择器（能拿到真实特异性）
    assert re.search(r'^\.(ui-close-button|ui-icon-button|wi-badge)', layer, re.M), (
        '一致性层的主选择器必须是普通类选择器，不能全靠 :where()'
    )


def test_consistency_layer_is_imported_last():
    """一致性层必须**最后**加载，否则同特异性的规则会被模块靠源序压过。

    真实教训：最初一致性层写在 `ui-refresh.css` 里（第 31 个 @import），
    后面还有 detail-card-workbench、resource-workbench、advanced-editor 等
    13 个模块。同特异性下靠源序决胜，于是等待统一的关���按钮仍被后面的
    模块规则覆盖 —— 改了等于没改。拆成独立文件并移到末尾才真正生效。
    """
    style_css = _read(CSS_DIR / 'style.css')
    imports = re.findall(r'@import\s+"([^"]+)"', style_css)
    assert imports, 'style.css 没有 @import'
    assert imports[-1].endswith('consistency.css'), (
        f'consistency.css 必须是最后一个 @import，实际最后一个是 {imports[-1]}'
    )


def test_icon_buttons_cannot_inherit_text_button_foreground():
    """纯图标按钮不得被 `.btn-primary` 的白色前景污染。

    真实事故：预设阅览的全屏按钮同时带 `.preset-reader-header-icon-button`
    （模块强制 `background: transparent !important`）和 `.btn-primary`。
    当 primary 的文字色是 `--content-on-accent`（近白）时，浅色模式下
    白字压在近白 header 上，对比度 **1.00:1**，必须悬浮才可见。
    """
    css = _read(CONSISTENCY_CSS)
    assert '图标按钮不得被文字语义污染' in css, '缺图标按钮保护小节'

    guard = css.split('图标按钮不得被文字语义污染', 1)[1]
    assert 'color: var(--accent-text) !important;' in guard, (
        '图标按钮的 primary 前景必须用可压表面的 accent-text，不能用 content-on-accent'
    )
    assert 'content-on-accent' not in guard.split('*/', 1)[1].split('color:', 1)[1].split(';', 1)[0]


def test_badge_semantics_use_tint_pairs_in_both_modes():
    """徽章必须用「tint 底 + 同色相深文字 + 同色相描边」，双主题同一配方。

    真实事故：`.wi-badge.embedded` 在浅色模式下
    `background: --decoration-violet` 与 `color: --decoration-violet-solid`
    取值相同（都是 #6d28d9），对比度 **1.00:1**，徽章文字完全隐形。
    """
    css = _read(CONSISTENCY_CSS)
    badge_section = css.split('徽章', 1)[1].split('空状态', 1)[0]

    for kind, surface, text, border in (
        ('global', '--action-surface', '--accent-text', '--action-border'),
        ('resource', '--status-success-surface', '--status-success-text', '--status-success-border'),
        ('embedded', '--decoration-violet-surface', '--decoration-violet-text', '--decoration-violet-border'),
        ('file', '--surface-container-raised', '--content-secondary', '--border-default'),
    ):
        # 规则加了 [class] 属性选择器以抬升特异性（压过 resource-workbench 的
        # `.resource-grid-view .resource-source-badge.embedded` (0,3,0)）。
        block = badge_section.split(f'.{kind}[class]', 1)
        assert len(block) == 2, f'徽章缺 {kind} 变体'
        rule = block[1].split('}', 1)[0]
        assert f'background: var({surface}) !important;' in rule, f'{kind} 背景应为 {surface}'
        assert f'color: var({text}) !important;' in rule, f'{kind} 文字应为 {text}'
        assert f'border-color: var({border}) !important;' in rule, f'{kind} 描边应为 {border}'

        # 每种变体都必须同时覆盖深色与浅色模式，避免"两种配方"
        assert f'html.light-mode .wi-badge.{kind}[class]' in badge_section, (
            f'{kind} 变体缺少浅色模式覆盖，会与深色模式分裂成两套配色'
        )

    # 浅色模式不能再单独写一套与深色不同的配方（那正是事故来源）
    assert '--decoration-violet-surface) !important' in badge_section, (
        '浅色与深色必须共用同一组 decorated tint 令牌'
    )


def test_text_measure_is_capped_on_reading_surfaces():
    """正文阅读区必须有行宽上限（Refactoring UI：45–75 字符）。"""
    css = _read(CONSISTENCY_CSS)
    assert '行宽（measure）' in css, '缺行宽小节'
    measure = css.split('行宽（measure）', 1)[1].split('破坏性动作', 1)[0]
    assert 'max-width: 70ch' in measure, '正文行宽应限制在 ~70ch'
    # 阅读正文必须被覆盖到
    for surface in ('chat-message-content', 'wi-entry-content', 'markdown-body'):
        assert surface in measure, f'行宽规则未覆盖 {surface}'


def test_destructive_actions_are_tertiary_outside_confirmation_dialogs():
    """破坏性动作在行内应是三级样式，只在确认对话框里升级为实心红。"""
    css = _read(CONSISTENCY_CSS)
    assert '破坏性动作' in css
    section = css.split('破坏性动作', 1)[1].split('颜色不是唯一信号', 1)[0]
    assert 'background: transparent !important;' in section, '行内危险按钮应完全透明'
    assert '--status-danger-surface' in section, 'hover 时才显现危险语义'
    assert '--status-danger-solid' in section, '确认框内应升级为实心红'



# ---------------------------------------------------------------- 裁决落地
# 以下五条来自 2026-10-19 的评审裁决（Q-01~Q-05），见
# docs/ui-spec-compliance-matrix.md 第四部分。


def test_icon_button_layering_is_documented_and_preserved():
    """裁决 Q-01：图标按钮分层保留，不是「全部统一」。

    L1 标准层（无边框透明）覆盖绝大多数界面；
    L2 强主题层（有边框实底）只保留抽卡、插件管理、插件任务三个模块。

    这条测试防止两种错误：
    1. 后人把 L2 当疏漏改掉，破坏抽卡/插件的视觉语言；
    2. 后人在 L1 新增有边框的图标按钮，让主流语汇再次分裂。
    """
    css = _read(CONSISTENCY_CSS)
    assert '裁决 Q-01' in css, '一致性层应记录 Q-01 裁决'
    assert 'L1 标准层' in css and 'L2 强主题层' in css, '应写明两层定义'

    # L2 三个模块必须被显式列为「有意保留」
    layering = css.split('裁决 Q-01', 1)[1].split('图标按钮', 1)[1]
    for cls in ('gacha-icon-btn', 'plugin-manager-icon-button', 'plugin-job-icon-button'):
        assert cls in layering, f'L2 强主题层的 {cls} 未被显式保留'


def test_badge_radius_is_unified_to_radius_md():
    """裁决 Q-03：徽章圆角统一 8px（--radius-md）。

    此前四档并存：5px / 8px / 12px / 999px。
    """
    css = _read(CONSISTENCY_CSS)
    badge_section = css.split('徽章', 1)[1].split('空状态', 1)[0]
    assert 'border-radius: var(--radius-md) !important;' in badge_section, (
        '徽章圆角应统一为 --radius-md（8px）'
    )
    assert '裁决 Q-03' in badge_section, '应注明这是 Q-03 的裁决结果'


def test_empty_states_are_tiered_by_scenario():
    """裁决 Q-04：空状态按场景分级，不是「全部统一」。

    L-完整：整页/整列表 -> 图标 + 标题 + 描述 + 动作
    L-精简：内联/小节   -> 图标 + 单行文字
    """
    css = _read(CONSISTENCY_CSS)
    assert '裁决 Q-04' in css
    empty = css.split('裁决 Q-04', 1)[1].split('工具条', 1)[0]
    assert 'L-完整档' in empty and 'L-精简档' in empty, '应写明两档定义'

    # 整页空态必须覆盖到插件相关（此前是纯文本，信息量与其他差 3 倍）
    for cls in ('plugin-manager-empty', 'plugin-job-empty', 'automation-empty-state'):
        assert cls in empty, f'L-完整档未覆盖 {cls}'

    # 内联空态走精简档
    for cls in ('advanced-inline-empty', 'advanced-list-empty', 'detail-empty-state'):
        assert cls in empty, f'L-精简档未覆盖 {cls}'


def test_sidebar_icon_overrides_are_single_layer():
    """裁决 Q-05：保留侧栏独立档位，但不得有四层重复覆写。

    此前 `.sidebar-filter-label .ui-icon--xs/sm/md/lg` 四条 + `nav-icon-slot`
    + `category-root` 的目标值都是 24px，属冗余。
    """
    icons = _read(CSS_DIR / 'modules' / 'icons.css')
    assert '裁决 Q-05' in icons, 'icons.css 应记录 Q-05 裁决'
    # 合并后的单一层
    assert '.sidebar .sidebar-filter-label .ui-icon,' in icons
    # 旧的逐尺寸覆写必须消失
    for old in (
        '.sidebar .sidebar-filter-label .ui-icon--xs {',
        '.sidebar .sidebar-filter-label .ui-icon--sm {',
        '.sidebar .sidebar-filter-label .ui-icon--md {',
        '.sidebar .sidebar-filter-label .ui-icon--lg {',
    ):
        assert old not in icons, f'冗余覆写未清理：{old}'


def test_l1_icon_buttons_have_no_filled_background():
    """L1 标准层的图标按钮不得有实心底。

    实测发现两个漏网者：`.automation-icon-button--small`（automation.html 7 处）
    与 `.detail-mini-btn`（detail_card.html 7 处）—— 它们有实心底但无边框，
    在 L1 标准层里与同屏的透明图标按钮并列时读作两套体系。
    """
    css = _read(CONSISTENCY_CSS)
    # 必须存在针对这两个的收回规则
    assert '.automation-icon-button--small,' in css
    assert '.detail-mini-btn {' in css

    section = css.split('.automation-icon-button--small,', 1)[1].split('}', 1)[0]
    assert 'background: transparent;' in section, 'L1 漏网者应收回透明底'
    assert 'border: 1px solid transparent;' in section, 'L1 漏网者应改为透明边框'


def test_l2_icon_buttons_are_explicitly_kept():
    """L2 强主题层的按钮必须被显式标注，防止后人当疏漏改掉。"""
    css = _read(CONSISTENCY_CSS)
    # 四个 L2 类（gacha 两个 + 插件两个）
    for cls in ('gacha-icon-btn', 'plugin-manager-icon-button', 'plugin-job-icon-button'):
        assert cls in css
    # gacha-action-btn 是图标+文字混合，但同样属抽卡 L2
    assert 'gacha' in css.lower()


def test_form_controls_have_accessible_names():
    """R-09：每个非隐藏表单控件都必须有可访问名称。

    WCAG 2.1 AA 4.1.2 / 3.3.2。placeholder 不能替代 aria-label ——
    输入后 placeholder 消失，且部分读屏不播报它。

    实测修复前 439 个控件里 136 个（31%）没有名称，主要是顶部 12 个搜索框
    和插件管理器的动态表单。
    """
    templates = PROJECT_ROOT / 'templates'
    control_re = re.compile(r'<(input|select|textarea)\b([^>]*)>', re.I | re.S)
    skip_types = {'hidden', 'submit', 'button', 'reset', 'image'}

    def get_attr(attrs, name):
        m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', attrs) or re.search(
            rf"\b{name}\s*=\s*'([^']*)'", attrs
        )
        return m.group(1) if m else None

    offenders = []
    for path in sorted(templates.rglob('*.html')):
        text = path.read_text(encoding='utf-8', errors='ignore')
        for m in control_re.finditer(text):
            tag = m.group(1).lower()
            attrs = m.group(2)
            ctype = (get_attr(attrs, 'type') or 'text').lower()
            if tag == 'input' and ctype in skip_types:
                continue
            # 隐藏的 file input 由可见按钮触发，不需要名称
            if tag == 'input' and ctype == 'file':
                cls = get_attr(attrs, 'class') or ''
                if re.search(r'\bhidden\b', attrs) or 'hidden' in cls:
                    continue
            if (
                get_attr(attrs, 'aria-label')
                or get_attr(attrs, 'aria-labelledby')
                or get_attr(attrs, 'title')
            ):
                continue
            # aria-hidden + tabindex=-1 的原生控件只是状态桥接（styled_select 宏），
            # 真正可交互的是旁边的 listbox button，不需要独立名称。
            if get_attr(attrs, 'aria-hidden') == 'true':
                continue
            cid = get_attr(attrs, 'id')
            if cid and re.search(
                rf'<label\b[^>]*\bfor\s*=\s*["\']{re.escape(cid)}["\']', text, re.I
            ):
                continue
            before = text[: m.start()]
            if before.rfind('<label') > before.rfind('</label>'):
                continue
            line = text[: m.start()].count('\n') + 1
            offenders.append(f'{path.relative_to(templates)}:{line} <{tag} {ctype}>')

    # 允许的例外：styled_select 宏内部的隐藏原生 select（视觉由 listbox 承担，
    # 其 <button> 已带 aria-label）
    offenders = [o for o in offenders if 'icon-select-source' not in o]
    assert not offenders, '以下表单控件缺少可访问名称:\n' + '\n'.join(offenders[:15])


def test_styled_select_calls_pass_aria_label():
    """所有 styled_select 调用都必须传 aria_label。

    宏内部的原生 <select> 被视觉隐藏，真正的可交互元素是 <button>，
    它只在调用方传了 aria_label 时才有名称。
    """
    templates = PROJECT_ROOT / 'templates'
    missing = []
    for path in sorted(templates.rglob('*.html')):
        text = path.read_text(encoding='utf-8', errors='ignore')
        for m in re.finditer(r'\{%\s*call\s+styled_select(?:_content)?\s*\((.*?)\)\s*%\}', text, re.S):
            if 'aria_label' not in m.group(1):
                line = text[: m.start()].count('\n') + 1
                missing.append(f'{path.relative_to(templates)}:{line}')
    assert not missing, 'styled_select 调用缺 aria_label:\n' + '\n'.join(missing[:10])


def test_toolbar_controls_share_one_height():
    """R-11：同一工具条内的控件必须同高。

    实测发现 `tag-filter-desktop-toolbar` 里搜索框 46.8px、按钮 44px，
    同一行"高矮不齐"。根因是搜索框 padding 0.65rem×2 + 24px 行盒 + 2px 边框
    算出 46.8，而按钮是 44。

    这条测试锁住「同一工具条只用一档控件高度」，防止以后再混入别的尺寸。
    """
    tools_css = _read(CSS_DIR / 'modules' / 'modal-tools.css')

    # tag-filter 工具条：搜索框必须与按钮同档（2.75rem = 44px）
    search_block = tools_css.split(
        '.tag-filter-workspace-topbar-search .tag-filter-workspace-search-input {', 1
    )[1].split('}', 1)[0]
    assert 'min-height: 2.75rem' in search_block, '搜索框应与同排按钮同为 44px'
    assert 'padding: 0.55rem' in search_block, (
        'padding-block 必须是 0.55rem —— 0.65rem 会算出 46.8px，比按钮高 2.8px'
    )


def test_toolbar_padding_uses_scale_tokens():
    """R-11：工具条 padding 必须用标尺令牌，不得写字面量。

    实测 `settings-toolbar` 原为 `padding: 10px 22px`（10 与 22 都不在
    4/8/12/16/24/32 标尺上），已收敛到 `--space-3 / --space-5`（12/24）。
    """
    settings_css = _read(CSS_DIR / 'modules' / 'modal-settings.css')
    block = settings_css.split('.settings-toolbar {', 1)[1].split('}', 1)[0]
    assert 'padding: var(--space-3) var(--space-5);' in block
    assert 'padding: 10px 22px' not in block


def test_rule_trigger_strip_lets_chips_share_one_row():
    """规则集的「触发场景」按钮组必须能横向平铺，不被说明文字挤成竖排。

    用户反馈：5 个同级 chip 曾排成 4 行，因为 `.rule-trigger-note`
    （约 480px 的长说明）和按钮同处一个 flex 行，把 `.rule-trigger-options`
    压到 162px 宽。

    修法是让 strip 允许换行、说明文字独占整行。这条测试锁住那个布局契约。
    """
    css = _read(CSS_DIR / 'modules' / 'automation-workbench.css')

    strip = css.split('.rule-trigger-strip {', 1)[1].split('}', 1)[0]
    assert 'flex-wrap: wrap;' in strip, 'strip 必须允许换行，否则说明文字会和按钮抢宽度'

    note = css.split('.rule-trigger-note {', 1)[1].split('}', 1)[0]
    assert 'flex: 0 0 100%;' in note, '说明文字必须独占整行'

    options = css.split('.rule-trigger-options {', 1)[1].split('}', 1)[0]
    assert 'flex: 1 1 auto;' in options
    assert 'flex-wrap: wrap;' in options
    assert 'min-width: 0;' in options


def test_preset_prompt_toggle_matches_automation_switch():
    """预设编辑器的条目开关必须与规则集开关视觉一致。

    用户反馈：预设全屏编辑器的「条目开启」开关不如规则集的开关好看，
    要求对齐。实测差异不在尺寸，而在**圆点是否跟随状态变色**：

      规则集 .automation-switch  开启=绿点 / 关闭=灰点（--status-success-solid / --content-muted）
      预设   .prompt-toggle-input 圆点始终是 --surface-control（纯白，关闭态尤其刺眼）

    修法是只用 CSS 覆盖预设开关的圆点颜色与尺寸，不动模板结构
    （模板里那些 Tailwind 类被 test_preset_editor_frontend_contracts.py 锁定）。
    """
    css = _read(CONSISTENCY_CSS)

    # 关闭态圆点：中性灰
    off_rule = css.split('.preset-editor-workbench .prompt-toggle-input ~ .pointer-events-none {', 1)
    assert len(off_rule) == 2, '预设开关的关闭态圆点规则必须存在'
    assert 'background: var(--content-muted) !important;' in off_rule[1].split('}', 1)[0]

    # 开启态圆点：状态成功色
    on_rule = css.split(
        '.preset-editor-workbench .prompt-toggle-input:checked ~ .pointer-events-none {', 1
    )
    assert len(on_rule) == 2, '预设开关的开启态圆点规则必须存在'
    assert 'background: var(--status-success-solid) !important;' in on_rule[1].split('}', 1)[0]

    # 尺寸对齐到规则集的 1.35rem × 2.3rem
    assert 'width: 2.3rem;' in css
    assert 'height: 1.35rem;' in css
    # 圆点 0.85rem
    thumb_block = css.split(
        '.preset-editor-workbench label:has(> span > .prompt-toggle-input) > span > .pointer-events-none {', 1
    )
    assert len(thumb_block) == 2
    assert 'width: 0.85rem;' in thumb_block[1].split('}', 1)[0]


def test_text_editors_keep_native_scrollbar_with_arrows():
    """文本编辑框（textarea / 可编辑区）保留原生经典滚动条（带上下箭头）。

    2026-10-25 用户裁决：原生经典滚动条只适合编辑框类的地方，其余界面回退到
    Refactoring UI 重构（c0fbaf2）之前的细滚动条。

    机制（headed Chromium 实测）：元素上只要出现**非 auto 的 scrollbar-color**，
    Chrome 就用原生经典滚动条渲染，并忽略该元素的 ::-webkit-scrollbar 规则。
    所以编辑框必须显式写 scrollbar-color，且自定义规则必须用 :not 把它们排除。
    """
    css = _read(CONSISTENCY_CSS)

    block = re.search(r'(?m)^textarea,\s*\n\[contenteditable\]\s*\{([^}]*)\}', css)
    assert block, '缺少编辑框规则（textarea, [contenteditable]）'
    assert 'scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track);' in block.group(1), (
        '编辑框必须写 scrollbar-color，否则拿不到原生经典滚动条（带箭头）'
    )


def test_non_editor_scrollbars_use_pre_refactor_thin_style():
    """编辑框之外的界面回退到重构前的主界面滚动条。

    - 全局默认：8px、实色轨道、圆角滑块（重构前 base.css 的配置）
    - .custom-scrollbar：6px、透明轨道（重构前 view-wi.css 的配置）
    """
    css = _read(CONSISTENCY_CSS)

    def rule_body(selector):
        match = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css, flags=re.S)
        return match.group(1) if match else None

    global_selector = '*:not(textarea):not([contenteditable])'
    expectations = {
        global_selector + '::-webkit-scrollbar': ('width: 8px;', 'height: 8px;'),
        global_selector + '::-webkit-scrollbar-track': ('background: var(--scrollbar-track);',),
        global_selector + '::-webkit-scrollbar-thumb': (
            'background: var(--scrollbar-thumb);',
            'border-radius: 4px;',
            'border: 2px solid var(--scrollbar-track);',
        ),
    }
    for selector, needles in expectations.items():
        body = rule_body(selector)
        assert body is not None, f'缺少规则：{selector}'
        for needle in needles:
            assert needle in body, f'{selector} 缺少 {needle}'

    # 非编辑框必须显式把 scrollbar-color 重置为 auto ——
    # 否则（继承或残留的）配色会让 Chrome 退回原生渲染，::-webkit-scrollbar 规则失效
    reset = rule_body(global_selector)
    assert reset is not None and 'scrollbar-color: auto;' in reset, (
        '非编辑框必须写 scrollbar-color: auto，否则自定义滚动条规则会被 Chrome 忽略'
    )

    custom_selector = '.custom-scrollbar:not(textarea):not([contenteditable])'
    thumb_selector = custom_selector + '::-webkit-scrollbar-thumb'
    track_selector = custom_selector + '::-webkit-scrollbar-track'
    size = rule_body(custom_selector + '::-webkit-scrollbar')
    track = rule_body(track_selector)
    thumb = rule_body(thumb_selector)
    assert size is not None and 'width: 6px;' in size and 'height: 6px;' in size, (
        '.custom-scrollbar 必须回到重构前的 6px'
    )
    assert track is not None and 'background: transparent;' in track, (
        '.custom-scrollbar 的轨道必须是透明的'
    )
    assert thumb is not None and 'background: var(--border-default);' in thumb, (
        '.custom-scrollbar 的滑块色必须回到重构前的 --border-default'
    )


def test_webkit_scrollbar_rules_stay_out_of_editors():
    """::-webkit-scrollbar 规则只能出现在 consistency.css，且必须排除编辑框。

    全站统一在 consistency.css 里定义一次；其它文件里再写自定义滚动条规则
    = 局部宿主又会出现"细滚动条/箭头丢失"的碎片化。选择器还必须带
    :not(textarea)，否则编辑框会被一起改成细滚动条。

    刻意隐藏滚动条的规则（width:0 + height:0）保留，不受此限。
    """
    import re as _re

    offenders = []
    for path in sorted(CSS_DIR.rglob('*.css')):
        if path.name in ('tailwind.css', 'tailwind-input.css'):
            continue
        stripped = _re.sub(r'/\*.*?\*/', '', _read(path), flags=_re.S)
        for m in _re.finditer(
            r'(?m)^[ \t]*([^{}\n]*(?:-webkit-scrollbar)[^{}\n]*)\{([^{}]*)\}', stripped
        ):
            selectors, body = m.group(1), m.group(2)
            if _re.search(r'width\s*:\s*0(?:px)?\s*;', body) and _re.search(
                r'height\s*:\s*0(?:px)?\s*;', body
            ):
                continue
            line = stripped[: m.start()].count('\n') + 1
            if path.name != 'consistency.css':
                offenders.append(f'{path.name}:{line} 在 consistency.css 之外自定义滚动条')
                continue
            if ':not(textarea)' not in selectors:
                offenders.append(f'{path.name}:{line} 未排除编辑框：{selectors.strip()[:60]}')

    assert not offenders, (
        '::-webkit-scrollbar 只能在 consistency.css 定义，且必须用 :not 排除编辑框：\n'
        + '\n'.join(offenders[:12])
    )

    # scrollbar-width 只能是 none（刻意隐藏），不能是 thin/auto：
    # 标准属性一旦出现，Chrome 会忽略该元素上的全部 ::-webkit-scrollbar 规则
    violations = []
    for path in sorted(CSS_DIR.rglob('*.css')):
        if path.name in ('tailwind.css', 'tailwind-input.css'):
            continue
        stripped = _re.sub(r'/\*.*?\*/', '', _read(path), flags=_re.S)
        for m in _re.finditer(r'(?m)^[ \t]*scrollbar-width\s*:\s*([^;]+);', stripped):
            value = m.group(1).strip()
            if value == 'none':
                continue
            line = stripped[: m.start()].count('\n') + 1
            violations.append(f'{path.name}:{line} scrollbar-width: {value}')
    assert not violations, (
        'scrollbar-width 只能是 none（刻意隐藏滚动条）：\n' + '\n'.join(violations[:10])
    )
