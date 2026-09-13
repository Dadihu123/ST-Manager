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
