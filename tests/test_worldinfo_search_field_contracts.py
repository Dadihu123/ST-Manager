"""世界书搜索分类的接口与前端契约。"""

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8')


def test_worldinfo_list_reads_search_field_param():
    source = _read('core/api/v1/world_info.py')
    assert "request.args.get('search_field'" in source
    assert 'SEARCH_FIELD_SMART' in source
    assert 'if search_field not in SEARCH_FIELDS:' in source


def test_search_field_is_only_forwarded_when_not_smart():
    """默认路径的 filters 形状被闭等值断言锁定，因此只在非默认时附加该键。"""
    source = _read('core/api/v1/world_info.py')
    assert 'if search_field != SEARCH_FIELD_SMART:' in source
    assert "query_filters['search_field'] = search_field" in source


def test_worldinfo_list_response_exposes_search_metadata():
    source = _read('core/api/v1/world_info.py')
    assert "'search_field': indexed_source.get('search_field') or search_field" in source
    assert "'search_degraded': bool(indexed_source.get('search_degraded'))" in source


def test_header_exposes_worldinfo_search_field_select():
    template = _read('templates/components/header.html')

    assert 'styled_select( "wiSearchField"' in template
    # 四个分类选项
    for value, label in (
        ('smart', '智能搜索'),
        ('name', '世界书名'),
        ('filename', '文件名'),
        ('owner', '所属角色卡'),
    ):
        assert f'<option value="{value}">{label}</option>' in template
    # 仅在世界书模式显示
    assert "x-show=\"currentMode === 'worldinfo'\"" in template


def test_header_worldinfo_placeholder_reflects_search_field():
    template = _read('templates/components/header.html')
    assert "wiSearchField === 'name' ? '搜索世界书名...'" in template
    assert "wiSearchField === 'filename' ? '搜索文件名...'" in template
    assert "wiSearchField === 'owner' ? '搜索所属角色卡...'" in template


def test_header_component_maps_search_field_to_store():
    script = _read('static/js/components/header.js')

    assert 'get wiSearchField()' in script
    assert 'set wiSearchField(val)' in script
    assert '["smart", "name", "filename", "owner"]' in script


def test_state_declares_search_field_and_degraded_flag():
    state = _read('static/js/state.js')
    assert 'wiSearchField: "smart"' in state
    assert 'wiSearchDegraded: false' in state


def test_wi_grid_sends_search_field_and_watches_it():
    script = _read('static/js/components/wiGrid.js')

    assert 'search_field: this.$store.global.wiSearchField || "smart"' in script
    assert 'this.$store.global.wiSearchField' in script
    # 切换分类要重新拉取
    assert 'this.$watch("$store.global.wiSearchField"' in script


def test_wi_grid_surfaces_degraded_search_state():
    script = _read('static/js/components/wiGrid.js')
    assert 'this.wiSearchDegraded = Boolean(res.search_degraded)' in script
    assert 'get wiSearchDegraded()' in script


def test_empty_state_explains_degraded_search():
    template = _read('templates/components/grid_wi.html')
    assert 'x-show="wiSearchDegraded"' in template
    assert '搜索词没有可用的关键字' in template


def test_dead_wi_search_changed_listener_is_removed():
    """全仓库没有任何 dispatchEvent，保留监听只会误导后续维护者。

    注释里提到该事件名是允许的（用于解释为何删除），但不能再有实际的
    addEventListener / dispatchEvent 代码。
    """
    for relative_path in (
        'static/js/components/wiGrid.js',
        'templates/components/header.html',
        'templates/components/grid_wi.html',
    ):
        source = _read(relative_path)
        assert 'addEventListener("wi-search-changed"' not in source, relative_path
        assert "addEventListener('wi-search-changed'" not in source, relative_path
        assert 'dispatchEvent(new CustomEvent("wi-search-changed"' not in source, relative_path
        assert '@wi-search-changed' not in source, relative_path


def test_no_dispatcher_exists_for_wi_search_changed_anywhere():
    """确认该事件在整个前端都没有生产者。"""
    static_root = ROOT / 'static'
    template_root = ROOT / 'templates'
    offenders = []
    for path in list(static_root.rglob('*.js')) + list(template_root.rglob('*.html')):
        text = path.read_text(encoding='utf-8')
        if 'dispatchEvent(new CustomEvent("wi-search-changed"' in text:
            offenders.append(str(path.relative_to(ROOT)))
        if "$dispatch('wi-search-changed'" in text or '$dispatch("wi-search-changed"' in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []
