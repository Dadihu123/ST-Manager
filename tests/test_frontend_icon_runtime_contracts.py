import os
import re
import shutil
import subprocess
import textwrap
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (PROJECT_ROOT / relative_path).read_text(encoding='utf-8')


def run_node(script: str) -> subprocess.CompletedProcess:
    """在 Node 里驱动真实前端模块（仓库没有 JS 测试运行器，沿用既有垫片模式）。"""
    return subprocess.run(
        ['node', '--input-type=module', '-e', textwrap.dedent(script)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )


requires_node = pytest.mark.skipif(
    shutil.which('node') is None,
    reason='Node.js is required for frontend icon runtime contract checks',
)


def normalize_markup(source):
    """折叠空白并去掉标签结束符前的空格，便于断言结构而非排版。

    模板会被格式化器重新折行/缩进（例如把 `>` 单独放到下一行），逐字节断言
    只会在无关改动后变红，而真正要锁的是**绑定表达式与元素结构**。
    """
    collapsed = re.sub(r'\s+', ' ', source)
    return re.sub(r'\s+>', '>', collapsed)


def test_layout_uses_compiled_tailwind_and_renders_toast_icons_by_resolved_kind():
    """toast 图标位锁的是**契约**，不是逐字节的实现形态。

    这里从「逐字节锁实现」放宽为「锁契约」，理由：

    旧实现把判定写成「16 项白名单 + 模板里拼前缀」，于是断言也不得不锁死那两行
    `x-if` 的字符串。结果是**缺口被测试固定住了**——宿主自己 176 个真实图标与
    全部插件图标都进不了通知，而测试全绿（历史成因见
    `test_send_target_brand_icons_are_allowed_in_toast_notifications` 那条「谁用谁加」的断言）。

    现在判定交给唯一的解析器（`resolveToastIcon()` → `resolveIcon()`，与
    `api.ui.icon()` / `entries[].icon` 同源），模板按解析结果的 `kind` 分三条渲染路径。
    真正不可回退的契约是：

    - 独立动效 SVG 走 `<img>` + `ui-loading-icon`（sprite 表里没有它，永远解析不出 symbol）；
    - **插件自带资源必须走 mask**，不能塞进 `<use>`（填充式 vs 描边式，会渲染成空图形）；
    - **宿主图标名仍走 `<use>`**，不得改成 mask（描边式 sprite 用 mask 会渲染成实心块）。

    顺序与属性写法允许随实现调整，因此这里断言分支存在性与绑定取值，
    并对「宿主分支用 mask」这一反向错误显式设卡。
    """
    source = read_project_file('templates/layout.html')
    markup = normalize_markup(source)

    assert '/static/css/tailwind.css' in source
    assert '/static/lib/tailwindcss.js' not in source

    # ① 独立动效 SVG：仍是 <img> + ui-loading-icon
    assert "x-if=\"toastIconKind === 'image'\"" in source
    assert 'ui-loading-icon' in source
    assert '<img' in markup

    # ② 插件自带资源：必须是 mask 分支，且带 .ui-icon--asset
    assert "x-if=\"toastIconKind === 'asset'\"" in source
    assert 'ui-icon--asset' in source
    assert "'--ui-icon-mask': toastIconMask" in markup or '--ui-icon-mask' in markup

    # ③ 宿主图标名：仍是 sprite <use>，指向宿主静态图标目录
    assert "x-if=\"toastIconKind === 'host'\"" in source
    assert '<use' in markup
    assert 'url_for(\'static\', filename=\'icons/\')' not in markup, (
        '宿主图标 href 必须由解析器产出（含 sprite 名），模板不得再硬拼 /static/icons/ 前缀——'
        '硬拼会让「白名单」变成唯一（且并非真正的）路径边界'
    )

    # 反向设卡：宿主分支不得用 mask 渲染
    host_branch = source.split("x-if=\"toastIconKind === 'host'\"", 1)[1].split('</template>', 1)[0]
    assert 'ui-icon--asset' not in host_branch, (
        '宿主 sprite 是描边式（fill: none; stroke: currentColor），用 mask 会渲染成实心块'
    )
    assert '<use' in host_branch


@requires_node
def test_send_target_brand_icons_are_allowed_in_toast_notifications():
    """意图保留：`sillytavern` / `tauritavern` 必须能出现在「发送到 ST/TT」的通知里。

    实现变了，断言也跟着变：修完图标位缺口后，这两个名字**不再需要**被塞进一份
    特权白名单——它们由通用解析器正常解析成宿主 sprite 引用。因此这里断言的是
    「解析能力」而不是「白名单里有这两个字面量」，既不回退能力，也不再固化旧机制。
    """
    result = run_node(
        """
        import assert from 'node:assert/strict';
        import { resolveIcon } from './static/js/utils/icons.js';

        for (const name of ['sillytavern', 'tauritavern']) {
          const resolved = resolveIcon(name);
          assert.equal(resolved.kind, 'host', `${name} 必须解析成宿主图标`);
          assert.equal(
            resolved.href,
            `/static/icons/ui.svg#icon-${name}`,
            `${name} 的 href 必须指向宿主 sprite`,
          );
        }

        // 品牌图标是宿主图标名的普通一员，不是特例
        assert.ok(resolveIcon('heart').href.endsWith('#icon-heart'));
        """
    )
    assert result.returncode == 0, result.stderr or result.stdout

    # 旧机制（16 项特权白名单）必须已经退休：否则缺口只是被推后，没有修通路
    state_source = read_project_file('static/js/state.js')
    assert 'TOAST_ICON_NAMES' not in state_source, (
        'whitelist 判定必须已被 resolveToastIcon() 取代；'
        '扩大白名单只是把「插件自定义图标永远无法枚举」的缺口推后'
    )


@requires_node
def test_toast_icon_slot_runtime_contracts_pass():
    """toast 图标位的**行为**契约（真实驱动 state.js，不只是源码字符串断言）。

    覆盖三类必须支持的情况：
    - 宿主图标名不在旧白名单也能用（`heart`）；
    - 插件自带资源路径能用（带 pluginId → mask）；
    - 未知名字留空图标位并 `console.warn`，且**文案照常显示**。

    用例清单见 `tests/toast_icon_runtime_test.mjs`（自带最小 DOM 垫片，
    与 `test_plugin_ambient_surface.py` 同一模式，不引入新依赖）。
    """
    result = subprocess.run(
        ['node', 'tests/toast_icon_runtime_test.mjs'],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_toast_unknown_icon_warns_instead_of_failing_silently():
    """未知图标名必须留一条显式信号：旧实现是完全静默的。

    静默失效正是这个缺口能长期存在的原因——插件作者看不出名字没生效。
    """
    source = read_project_file('static/js/state.js')

    assert 'console.warn(' in source
    assert '[toast]' in source, '告警要带可检索的前缀'
    # 图标缺失只影响图标位，文案必须照常走
    toast_block = source.split('showToast(msg, duration = 3000, iconName = "", options = {}) {', 1)[1]
    assert 'this.toastMessage = msg;' in toast_block.split('console.warn', 1)[0]


def test_toast_render_paths_match_ui_primitives_icon_kinds():
    """三条渲染路径必须与 `uiPrimitives.icon()` 的 kind 契约一一对应。

    两处一旦漂移，同一份 `entries[].icon` / `api.toast` 取值在通知与其它位置
    会渲染成不同东西（这正是本次要修的缺口形态）。
    """
    primitives = read_project_file('static/js/uiPrimitives.js')
    state_source = read_project_file('static/js/state.js')
    icons_css = read_project_file('static/css/modules/icons.css')

    # uiPrimitives：asset → span + mask；host → svg + use；missing → 占位
    assert "resolved.kind === \"asset\"" in primitives
    assert "ui-icon--asset" in primitives
    assert 'setProperty("--ui-icon-mask"' in primitives
    assert 'resolved.kind === "missing"' in primitives

    # state.js：同一套 kind 命名
    for kind in ('"host"', '"asset"', '"missing"'):
        assert kind in state_source, kind

    # mask 的 CSS 契约必须在（否则 asset 分支渲染不出东西）
    assert '.ui-icon.ui-icon--asset' in icons_css
    assert '--ui-icon-mask' in icons_css


def test_toast_plugin_asset_icon_support_is_wired_end_to_end():
    """插件要能用自带图标，链路必须完整：api.toast 透传 pluginId → store 解析 → 模板 mask。"""
    host_source = read_project_file('static/js/pluginHost.js')
    state_source = read_project_file('static/js/state.js')
    layout_source = read_project_file('templates/layout.html')

    # api.toast 把闭包里的 pluginId 透传出去（既有调用方无需改动）
    toast_block = host_source.split('toast(msg, duration = 3000, icon = "") {', 1)[1].split('},', 1)[0]
    assert '{ pluginId }' in toast_block, '不传 pluginId，插件资源路径永远解析不出来'

    # store 用它去解析资源路径
    assert 'pluginId: options && options.pluginId' in state_source

    # 解析结果经 kind 驱动模板分支
    assert "toastIconKind === 'asset'" in layout_source


def test_card_detail_help_modal_is_teleported_above_detail_modal_stack():
    source = read_project_file('templates/modals/detail_card.html')
    help_start = source.index('<!-- 字段说明帮助模态框 (Help Modal) -->')
    help_source = source[help_start:]

    assert '<template x-teleport="body">' in help_source
    assert "icon('settings-help-entry'" in help_source
    assert 'z-modal-popover' in help_source
    assert 'z-[60]' not in help_source


def test_worldbook_backup_folder_actions_use_the_shared_medium_icon_tier():
    popup_source = read_project_file('templates/modals/detail_wi_popup.html')
    fullscreen_source = read_project_file('templates/modals/detail_wi_fullscreen.html')
    detail_card_source = read_project_file('templates/modals/detail_card.html')

    assert "icon('book-backup', 'ui-icon--md')" in popup_source
    assert "icon('book-backup', 'ui-icon--md')" in fullscreen_source
    assert "icon('book-backup', 'ui-icon--xl')" not in popup_source
    assert "icon('book-backup', 'ui-icon--xl')" not in fullscreen_source
    assert "icon('book-backup', 'ui-icon--lg')" in detail_card_source


def test_personalized_save_icon_is_restored_for_all_production_save_calls():
    sprite = read_project_file('static/icons/ui.svg')

    assert '<symbol id="icon-settings-save" viewBox="46 48 353 350">' in sprite
    assert 'transform="translate(234,76)" fill="currentColor" stroke="none"' in sprite
    assert 'transform="translate(68,48)" fill="currentColor" stroke="none"' in sprite
    assert '<symbol id="icon-save"' not in sprite

    save_sources = (
        'templates/modals/settings.html',
        'templates/modals/automation.html',
        'templates/modals/detail_card.html',
        'templates/modals/detail_wi_fullscreen.html',
        'static/js/state.js',
        'static/js/components/advancedEditor.js',
        'static/js/components/automationModal.js',
        'static/js/components/detailModal.js',
        'static/js/components/wiDetailPopup.js',
        'static/js/components/wiEditor.js',
    )
    for relative_path in save_sources:
        source = read_project_file(relative_path)
        assert "icon('save'" not in source
        assert '"save"' not in source
        assert "'save'" not in source


def test_bulk_flip_icon_uses_the_shared_ui_sprite():
    sprite_path = PROJECT_ROOT / 'static/icons/ui.svg'
    root = ET.parse(sprite_path).getroot()
    symbol = next(
        element
        for element in root
        if element.get('id') == 'icon-vertical-flip'
    )

    assert symbol.get('viewBox') == '0 0 1024 1024'
    assert symbol.get('fill') == 'currentColor'
    assert symbol.find('{http://www.w3.org/2000/svg}path').get('fill') == 'currentColor'

    for relative_path in (
        'templates/components/grid_cards.html',
        'templates/components/grid_wi.html',
    ):
        source = read_project_file(relative_path)
        assert "icon('vertical-flip', 'ui-icon--lg')" in source
        assert 'ui-flip-icon' not in source

    cards_css = read_project_file('static/css/modules/view-cards.css')
    assert 'static/icons/vertical-flip.svg' not in cards_css


def test_pagination_strip_keeps_its_surface_and_clears_inner_flip_surfaces():
    css = read_project_file('static/css/modules/ui-refresh.css')
    pagination_block = css.split('.pagination-bar {', 1)[1].split('}', 1)[0]

    assert 'background:' not in pagination_block
    assert 'background-color:' not in pagination_block
    assert '.pagination-bar .card-flip-toolbar' in css
    assert '.pagination-bar button.card-flip-all-btn' in css
    assert 'background-color: transparent !important;' in css
