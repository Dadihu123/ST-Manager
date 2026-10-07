"""前端资产契约测试：图标 / CSS 变量 / 状态样式 / 状态标签。

这类问题浏览器**不会报错**——缺失的图标只渲染成空白、未定义的 CSS 变量
静默回退、没写规则的状态类让不同状态看起来一模一样。因此必须静态锁死。

对齐的后端事实来源：
- `core/plugins/job_store.py:JOB_STATUSES` / `ITEM_STATUSES` / `TERMINAL_STATUSES`
- `core/plugins/jobs.py` 的日志级别用法
"""

import os
import re
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import job_store

PLUGIN_TEMPLATES = (
    'templates/modals/plugin_manager.html',
    'templates/components/plugin_job_panel.html',
    'templates/modals/markdown_preview.html',
)

PLUGIN_STYLE_FILES = (
    'static/css/modules/modal-plugin-manager.css',
    'static/css/modules/modal-plugin-job.css',
)

UI_SPRITE = 'static/icons/ui.svg'


def _read(relative_path: str) -> str:
    with open(os.path.join(PROJECT_ROOT, relative_path), 'r', encoding='utf-8') as handle:
        return handle.read()


def _sprite_icon_names() -> set:
    return set(re.findall(r'id="icon-([a-z0-9-]+)"', _read(UI_SPRITE)))


def _defined_css_variables() -> set:
    names = set()
    css_root = os.path.join(PROJECT_ROOT, 'static', 'css')
    for current_root, _dirs, files in os.walk(css_root):
        for name in files:
            if not name.endswith('.css'):
                continue
            with open(os.path.join(current_root, name), 'r', encoding='utf-8') as handle:
                names.update(re.findall(r'(--[a-zA-Z0-9-]+)\s*:', handle.read()))
    return names


def _collect_css_classes(*relative_paths: str) -> set:
    """收集类选择器。

    同时收集**单类名**（`is-pending`）与**复合选择器**（`plugin-job-item.is-pending`），
    因为 `'is-' + status` 这类动态拼接必须靠复合选择器才能验证到底挂在哪个容器上。
    """
    singles = set()
    compounds = set()

    for relative_path in relative_paths:
        text = re.sub(r'/\*.*?\*/', '', _read(relative_path), flags=re.S)
        # 复合选择器：连续的 .a.b.c（中间无空格与组合符）
        for match in re.finditer(r'(\.[a-zA-Z][a-zA-Z0-9_-]*(?:\.[a-zA-Z][a-zA-Z0-9_-]*)+)', text):
            compounds.add(match.group(1))
        singles.update(re.findall(r'\.([a-zA-Z][a-zA-Z0-9_-]*)', text))

    return singles | compounds


def _template_icons(relative_path: str) -> list:
    return re.findall(r"\{\{\s*icon\(\s*'([a-z0-9-]+)'", _read(relative_path))


# ------------------------------------------------------------------ 图标


def test_plugin_templates_only_use_existing_icons():
    available = _sprite_icon_names()

    missing = []
    for template in PLUGIN_TEMPLATES:
        for name in _template_icons(template):
            if name not in available:
                missing.append(f'{template}: {name}')

    assert missing == [], f'引用了 ui.svg 中不存在的图标: {missing}'


def test_sprite_is_non_trivial():
    assert len(_sprite_icon_names()) > 100


# ------------------------------------------------------------------ CSS 变量


def test_plugin_styles_only_use_defined_variables():
    defined = _defined_css_variables()

    missing = []
    for style_file in PLUGIN_STYLE_FILES:
        for name in sorted(set(re.findall(r'var\(\s*(--[a-zA-Z0-9-]+)', _read(style_file)))):
            if name not in defined:
                missing.append(f'{style_file}: {name}')

    assert missing == [], f'使用了未定义的 CSS 变量: {missing}'


def test_plugin_styles_avoid_tailwind_palette_classes():
    """F3：不得使用 Tailwind 调色板类（项目用语义 token）。"""
    for style_file in PLUGIN_STYLE_FILES:
        content = _read(style_file)
        for pattern in (r'\bbg-(red|blue|green|gray|zinc|slate)-\d', r'\btext-(red|blue|green)-\d'):
            assert not re.search(pattern, content), f'{style_file} 出现调色板类: {pattern}'


# ------------------------------------------------------------------ 状态样式


def test_every_job_status_has_a_style_rule():
    """作业状态类必须在插件 CSS 里有规则（否则不同状态视觉相同）。"""
    classes = _collect_css_classes(*PLUGIN_STYLE_FILES)

    # 作业级状态展示在摘要区的状态徽标里（.plugin-job-status）
    missing = [
        status for status in job_store.JOB_STATUSES
        if f'.plugin-job-status.is-{status}' not in classes
    ]

    assert missing == [], f'作业状态缺少样式规则: {missing}'


def test_every_item_status_has_a_style_rule():
    classes = _collect_css_classes(*PLUGIN_STYLE_FILES)

    missing = [
        status for status in job_store.ITEM_STATUSES
        if f'.plugin-job-item.is-{status}' not in classes
    ]

    assert missing == [], f'条目状态缺少样式规则（会静默渲染成同一外观）: {missing}'


def test_log_levels_have_style_rules():
    classes = _collect_css_classes(*PLUGIN_STYLE_FILES)

    for level in ('info', 'warning', 'error'):
        assert f'.plugin-job-log.is-{level}' in classes, level


def test_secret_state_styles_cover_both_variants():
    classes = _collect_css_classes(*PLUGIN_STYLE_FILES)

    assert '.plugin-secret-state.is-set' in classes
    assert '.plugin-secret-state.is-unset' in classes


def test_dynamically_composed_status_classes_are_covered():
    """模板用 `'is-' + status` 拼接类名，因此无法靠字面量搜索发现遗漏。"""
    template = _read('templates/components/plugin_job_panel.html')

    assert "'is-' + (item.status || 'pending')" in template, '条目状态拼接方式发生了变化'
    assert "itemStatusLabel(item.status)" in template

    classes = _collect_css_classes(*PLUGIN_STYLE_FILES)
    for status in job_store.ITEM_STATUSES:
        assert f'.plugin-job-item.is-{status}' in classes, status


# ------------------------------------------------------------------ 状态标签


def _label_map(component: str, const_name: str) -> dict:
    """提取 `const <name> = { key: "值", ... }` 块内的键值对。

    必须按块提取：文件里 `skipped` 之类的标识符在别处（如 counts getter）
    也会出现，全文搜索会给出假通过。
    """
    match = re.search(rf'const {const_name} = \{{(.*?)\n\}};', component, re.S)
    assert match is not None, f'未找到 {const_name} 定义'
    return {
        key: value
        for key, value in re.findall(r'^\s{2}([a-z_]+):\s*"([^"]*)",', match.group(1), re.MULTILINE)
    }


def test_frontend_labels_cover_all_backend_statuses():
    component = _read('static/js/components/pluginJobPanel.js')

    job_labels = _label_map(component, 'JOB_STATUS_LABELS')
    item_labels = _label_map(component, 'ITEM_STATUS_LABELS')

    assert list(job_labels) == list(job_store.JOB_STATUSES), (
        f'作业状态标签与后端不一致: 前端 {list(job_labels)} / 后端 {list(job_store.JOB_STATUSES)}'
    )
    assert list(item_labels) == list(job_store.ITEM_STATUSES), (
        f'条目状态标签与后端不一致: 前端 {list(item_labels)} / 后端 {list(job_store.ITEM_STATUSES)}'
    )


def test_frontend_labels_are_localized():
    """标签值必须是中文译文。

    若写成英文（或与状态名相同），用户看到的与「映射缺失回退到原始状态值」
    毫无区别——等于没翻译，因此必须断言。
    """
    component = _read('static/js/components/pluginJobPanel.js')

    for const_name in ('JOB_STATUS_LABELS', 'ITEM_STATUS_LABELS'):
        for key, value in _label_map(component, const_name).items():
            assert re.search(r'[\u4e00-\u9fff]', value), (
                f'{const_name}.{key} 的值不是中文译文: {value!r}'
            )
            assert value.lower() != key, f'{const_name}.{key} 的值与状态名相同: {value!r}'


def test_frontend_terminal_statuses_match_backend():
    component = _read('static/js/components/pluginJobPanel.js')

    match = re.search(r'const TERMINAL_STATUSES = \[([^\]]*)\]', component)
    assert match is not None

    frontend = [item.strip().strip('"') for item in match.group(1).split(',') if item.strip()]

    assert frontend == list(job_store.TERMINAL_STATUSES)


def test_panel_uses_dedicated_item_label_helper():
    component = _read('static/js/components/pluginJobPanel.js')
    template = _read('templates/components/plugin_job_panel.html')

    assert 'itemStatusLabel(status)' in component
    assert 'itemStatusLabel(item.status)' in template


# ------------------------------------------------------------------ 模板挂载点


def test_plugin_modal_and_panel_are_registered_in_app_js():
    app_source = _read('static/js/app.js')

    assert 'Alpine.data("pluginManager"' in app_source
    assert 'Alpine.data("pluginJobPanel"' in app_source


def test_x_data_components_are_imported():
    for relative_path, component in (
        ('templates/modals/plugin_manager.html', 'pluginManager'),
        ('templates/components/plugin_job_panel.html', 'pluginJobPanel'),
    ):
        assert f'x-data="{component}"' in _read(relative_path), relative_path


def test_plugin_styles_are_imported_by_entry_css():
    entry = _read('static/css/style.css')

    for style_file in PLUGIN_STYLE_FILES:
        assert os.path.basename(style_file) in entry, style_file


def test_plugin_templates_are_included_in_index():
    index = _read('templates/index.html')

    assert 'modals/plugin_manager.html' in index
    assert 'components/plugin_job_panel.html' in index
