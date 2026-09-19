from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_project_file(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8')


def test_source_creator_action_exposes_field_tokens_and_help_reference():
    template = read_project_file('templates/modals/automation.html')
    automation_js = read_project_file('static/js/components/automationModal.js')
    stylesheet = read_project_file('static/css/modules/automation-workbench.css')

    for fragment in (
        '默认作者字段',
        '{{ \'{{username}}\' }}',
        '{{ \'{{display_name}}\' }}',
        '{{ \'{{global_name}}\' }}',
        '{{ \'{{author_id}}\' }}',
        'syncSourceCreatorFormat(cfg)',
        'sourceCreatorFieldDescription(cfg.author_field)',
        "insertSourceCreatorToken(cfg, 'author')",
        '查看字段格式说明',
        '来源作者→创作者：字段与格式',
        '{% raw %}{{author}}{% endraw %}',
        '{% raw %}{{source_url}}{% endraw %}',
    ):
        assert fragment in template

    for fragment in (
        'SOURCE_CREATOR_FIELD_META',
        "token: '{{username}}'",
        "token: '{{display_name}}'",
        "token: '{{global_name}}'",
        "token: '{{author_id}}'",
        'syncSourceCreatorFormat(config)',
        'markSourceCreatorFormatEdited(config)',
        'insertSourceCreatorToken(config, field)',
    ):
        assert fragment in automation_js

    for fragment in (
        '@media (min-width: 769px)',
        'align-items: center',
        'grid-template-columns: minmax(11rem, 0.8fr) minmax(0, 1.7fr) auto',
        'grid-column: 1 / 3',
        'grid-column: 3',
        '.action-row--fetch_forum_tags .action-config-panel',
        '.action-row--add_tags_from_source_title .action-config-grid',
        'grid-template-columns: repeat(3, minmax(0, 1fr))',
        'flex-direction: row',
        '.action-config-panel--creator',
        '.source-creator-field-note',
        '.source-creator-token-button',
        '.automation-source-field-reference',
    ):
        assert fragment in stylesheet


def test_sparse_action_rows_rebalance_into_three_columns_on_desktop():
    """留白较多的动作按「动作列表自身宽度」重排成「左工具 / 中输入 / 右说明」三栏。"""
    template = read_project_file('templates/modals/automation.html')
    stylesheet = read_project_file('static/css/modules/automation-workbench.css')

    # 两个副栏容器必须存在，且窄屏下不产生多余盒子。
    for fragment in (
        'action-row-tools',
        'action-row-notes',
        'action-row-aside',
        'action-row-tool-group',
    ):
        assert fragment in template
        assert '.' + fragment in stylesheet

    assert 'display: contents;' in stylesheet

    # 排布依据必须是行自身宽度，而不是视口宽度：弹窗有 75rem 上限，
    # 视口再宽行宽也停在 ~784px，用视口断点会让宽屏白白留空。
    assert '.action-list {\n  container-type: inline-size;\n}' in stylesheet
    assert '@container (min-width: 47rem)' in stylesheet
    assert '@container (max-width: 33.99rem)' in stylesheet
    assert '@container (min-width: 34rem) and (max-width: 46.99rem)' in stylesheet
    assert "@media (min-width: 769px) and (max-width: 1199px)" not in stylesheet

    wide = stylesheet.split('@container (min-width: 47rem)', 1)[1]
    assert "grid-template-areas:\n        'head detail aside'\n        'tools detail aside';" in wide
    assert "grid-template-areas: 'head detail aside';" in wide
    assert 'grid-template-columns: minmax(13rem, 15rem) minmax(0, 1fr) minmax(10rem, 11rem);' in wide

    # 放不下三栏但放得下两栏时，走中间档，而不是直接塌成单列。
    # 单列会让四个动作的行高合计从 ~917px 涨到 ~1263px，中间输入框反而更窄。
    mid = stylesheet.split('@container (min-width: 34rem) and (max-width: 46.99rem)', 1)[1]
    mid = mid.split('@container (min-width: 34rem) {', 1)[0]
    assert "grid-template-areas:\n        'head aside'\n        'tools aside'\n        'detail aside';" in mid
    assert "grid-template-areas:\n        'head aside'\n        'detail aside';" in mid
    assert 'grid-template-columns: minmax(0, 1fr) minmax(9.5rem, 11rem);' in mid

    # 连两栏都放不下时退回单列堆叠，不能把中间栏压成 0（那样会横向溢出）。
    narrow = stylesheet.split('@container (max-width: 33.99rem)', 1)[1].split('@container (min-width: 34rem)', 1)[0]
    assert 'display: flex;' in narrow
    assert 'flex-direction: column;' in narrow
    assert 'flex-direction: column-reverse;' in narrow

    # 只有留白明显的四个动作参与重排；短动作保持原来的居中单行。
    for action_type in (
        'set_creator_from_source',
        'rename_file_by_template',
        'add_tags_from_source_title',
        'fetch_forum_tags',
    ):
        assert '.action-row--%s' % action_type in stylesheet

    # 左栏只有选择器的两个动作要收窄左栏，并让选择器在本列内居中。
    head_centered = wide.split('.action-row--fetch_forum_tags .automation-action-type-select', 1)[1]
    assert 'align-self: center;' in head_centered

    # 右栏整体垂直居中，短说明不会独自贴在顶端。
    assert '.action-row--fetch_forum_tags .action-row-aside' in wide
    assert 'align-self: center;' in wide

    # 创作者下拉的标签必须允许换行，否则「显示名（display_name） · {{display_name}}」
    # 在双列网格里无论如何都会被截断（实测每一档宽度只拿得到 124–176px，
    # 769px 窗口下更是横向溢出 119px）。这条对所有桌面档位都成立，故不放进容器查询。
    wrap_block = stylesheet.split('.action-config-grid--creator .icon-select-label', 1)[1]
    assert 'white-space: normal;' in wrap_block
    assert 'overflow: visible;' in wrap_block
    assert '@container' not in wrap_block.split('}', 1)[0]

    # 快捷工具从中间栏移动到左栏后，两处必须共用同一个 config 对象。
    creator_tools = template.split('class="action-row-tools"', 1)[1].split('class="action-config"', 1)[0]
    assert 'source-creator-format-tools' in creator_tools
    assert '套用示例' in creator_tools
    assert 'action-config-label-row' in creator_tools
    assert 'x-if="action.type === \'set_creator_from_source\'"' in creator_tools
    assert 'x-if="action.type === \'rename_file_by_template\'"' in creator_tools
    # 切换动作类型必须重建作用域，否则工具会指向旧动作的 config。
    assert 'x-show="action.type === \'set_creator_from_source\'"' not in creator_tools
    assert 'x-show="action.type === \'rename_file_by_template\'"' not in creator_tools

    # 说明文字挪到右栏，且仍然保留各自的动作判定。
    notes = template.split('class="action-row-notes"', 1)[1].split('class="action-config"', 1)[0]
    for fragment in (
        '若想在覆盖更新后重命名',
        '查看字段格式说明',
        '使用 Python 正则提取标题标签',
        '从角色卡来源链接抓取类脑论坛标签',
    ):
        assert fragment in notes


def test_rename_preset_writes_through_the_shared_action_config():
    """左栏「套用示例」与中间模板输入分属两个 Alpine 作用域，必须就地写入同一个对象。"""
    automation_js = read_project_file('static/js/components/automationModal.js')
    preset_block = automation_js.split('applyRenameTemplatePreset(action, preset) {', 1)[1].split('\n        },', 1)[0]

    assert 'Object.assign(target, getRenameTemplatePreset(preset));' in preset_block
    assert 'this.initActionConfig(action)' in preset_block
    # 不能再整体替换 config，否则中间栏的输入框看不到变化。
    assert 'action.config = getRenameTemplatePreset(preset)' not in preset_block

    init_block = automation_js.split('initActionConfig(action) {', 1)[1].split('\n        },', 1)[0]
    assert 'Object.assign(action.config, normalized);' in init_block
    assert 'action.config = normalized;' in init_block
    # 复用对象不能把上一个动作类型的字段带过来，切换类型的语义要和整对象替换一致。
    assert 'const keep = new Set(Object.keys(normalized));' in init_block
    assert "!key.startsWith('_') && !keep.has(key)" in init_block
