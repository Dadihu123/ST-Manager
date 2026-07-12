"""前端契约：类脑搜索按钮与预览弹层。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_grid_cards_has_forum_search_button():
    source = (ROOT / 'templates/components/grid_cards.html').read_text(encoding='utf-8')
    assert 'card-forum-search-btn' in source
    assert 'canOpenForumPreview(card)' in source
    assert 'openForumThreadPreview(card)' in source


def test_forum_thread_preview_modal_template():
    source = (ROOT / 'templates/modals/forum_thread_preview.html').read_text(
        encoding='utf-8'
    )
    assert 'x-data="forumThreadPreview"' in source
    assert 'forum-preview-footer' in source
    assert '简介' in source
    # 移动端全屏：对齐项目 deviceType 判断
    assert "$store.global.deviceType === 'mobile'" in source
    assert 'forum-preview-overlay--mobile' in source
    assert "is-mobile" in source
    # 多图走马灯
    assert 'hasMultipleCovers()' in source
    assert 'forum-preview-carousel-nav' in source
    assert 'forum-preview-carousel-dots' in source


def test_forum_preview_carousel_logic_in_component():
    source = (ROOT / 'static/js/components/forumThreadPreview.js').read_text(
        encoding='utf-8'
    )
    assert 'coverIndex' in source
    assert 'hasMultipleCovers()' in source
    assert 'prevCover()' in source
    assert 'nextCover()' in source
    assert 'coverUrls()' in source


def test_forum_preview_mobile_fullscreen_css():
    css = (ROOT / 'static/css/modules/modal-forum-preview.css').read_text(
        encoding='utf-8'
    )
    assert '.forum-preview-panel.is-mobile' in css
    assert '--app-viewport-height-safe' in css
    assert 'forum-preview-overlay--mobile' in css
    assert '.forum-preview-carousel-dot.is-active' in css


def test_forum_preview_registered_in_app_and_index():
    app_js = (ROOT / 'static/js/app.js').read_text(encoding='utf-8')
    index = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    assert 'forumThreadPreview' in app_js
    assert 'modals/forum_thread_preview.html' in index


def test_settings_has_shimmerday_cookie_field():
    settings = (ROOT / 'templates/modals/settings.html').read_text(encoding='utf-8')
    state = (ROOT / 'static/js/state.js').read_text(encoding='utf-8')
    assert 'shimmerday_forum_cookie' in settings
    assert 'shimmerday_forum_cookie' in state
    assert 'odysseia-forum-webpage.pages.dev' in settings


def test_discord_url_util_matches_backend_rules():
    source = (ROOT / 'static/js/utils/discordUrl.js').read_text(encoding='utf-8')
    assert 'extractDiscordThreadId' in source
    assert "parts[3] === 'threads'" in source
