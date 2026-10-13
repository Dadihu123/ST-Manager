"""覆盖升级时的创作者字段保护（creator_policy）。

背景：上传的角色卡里 `creator` 常常为空或是原作者署名。若直接覆盖，
用户在「来源作者→创作者」动作里写入的值会被顶掉。
"""

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import cards as cards_api
from core.services import card_service


class _FakeImage:
    def save(self, path, _fmt):
        Path(path).write_bytes(b'png-data')


class _FakeCache:
    def __init__(self, id_map=None):
        self.id_map = dict(id_map or {})
        self.cards = []
        self.bundle_map = {}

    def reload_from_db(self):
        return None

    def delete_card_update(self, card_id):
        self.id_map.pop(card_id, None)

    def add_card_update(self, payload):
        self.id_map[payload['id']] = dict(payload)
        return self.id_map[payload['id']]

    def update_card_data(self, card_id, payload):
        # 真实缓存条目始终带图片地址，这里补齐以免 update_card_content 取不到。
        entry = self.id_map.setdefault(card_id, {})
        entry.setdefault('image_url', f'/cards_file/{card_id}')
        entry.setdefault('thumb_url', f'/api/thumbnail/{card_id}')
        entry.update(payload)
        return entry


def _setup(monkeypatch, tmp_path, *, extract, cache=None):
    cards_root = tmp_path / 'cards'
    cards_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(card_service, 'CARDS_FOLDER', str(cards_root))
    monkeypatch.setattr(card_service, 'DEFAULT_DB_PATH', str(tmp_path / 'cards_metadata.db'))
    monkeypatch.setattr(card_service, 'THUMB_FOLDER', str(tmp_path / 'thumbs'))
    monkeypatch.setattr(card_service, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr(card_service, 'suppress_fs_events', lambda *_a, **_k: None)
    monkeypatch.setattr(card_service, 'load_config', lambda: {'resources_dir': 'resources'})
    monkeypatch.setattr(card_service, 'extract_card_info', extract)
    monkeypatch.setattr(card_service, 'write_card_metadata', lambda *_a, **_k: True)
    monkeypatch.setattr(card_service, 'resize_image_if_needed', lambda image: image)
    monkeypatch.setattr(card_service, 'clean_sidecar_images', lambda *_a, **_k: None)
    monkeypatch.setattr(card_service, 'clean_thumbnail_cache', lambda *_a, **_k: None)
    monkeypatch.setattr(card_service, 'load_ui_data', lambda: {})
    monkeypatch.setattr(card_service, 'save_ui_data', lambda _p, **_k: None)
    monkeypatch.setattr(card_service, 'resolve_ui_key', lambda card_id: card_id)
    monkeypatch.setattr(card_service, 'ensure_import_time', lambda *_a, **_k: (False, 123.0))
    monkeypatch.setattr(card_service, 'get_import_time', lambda *_a, **_k: 123.0)
    monkeypatch.setattr(card_service, 'calculate_token_count', lambda _p: 42)
    monkeypatch.setattr(card_service, 'get_file_hash_and_size', lambda _p: ('h', 11))
    monkeypatch.setattr(card_service, 'update_card_cache', lambda *_a, **_k: {})
    monkeypatch.setattr(card_service, 'sync_card_index_jobs', lambda **_k: {})
    monkeypatch.setattr(card_service, 'cleanup_embedded_worldbook_history', lambda **_k: 0)
    monkeypatch.setattr(card_service.Image, 'open', lambda _p: _FakeImage())
    monkeypatch.setattr(card_service.ctx, 'cache', cache or _FakeCache())

    card_path = cards_root / 'hero.png'
    card_path.write_bytes(b'old-png')
    temp_path = tmp_path / 'upload.png'
    temp_path.write_bytes(b'new-png')
    return cards_root, card_path, temp_path


def test_update_card_content_preserves_existing_creator_by_default(monkeypatch, tmp_path):
    """旧卡有创作者、上传文件创作者为空时，保留旧值。"""

    def extract(path):
        if str(path).endswith('upload.png'):
            return {'data': {'name': 'Hero', 'creator': ''}}
        return {'data': {'name': 'Hero', 'creator': '原创作者'}}

    cards_root, card_path, temp_path = _setup(monkeypatch, tmp_path, extract=extract)

    result = card_service.update_card_content(
        'hero.png',
        str(temp_path),
        is_bundle_update=False,
        keep_ui_data={},
        new_upload_ext='.png',
    )

    assert result['success'] is True
    assert result['creator_preserved'] == '原创作者'
    assert result['updated_card']['creator'] == '原创作者'


def test_update_card_content_prefers_keep_ui_data_creator(monkeypatch, tmp_path):
    """前端显式传来的创作者优先于旧值。"""

    def extract(path):
        if str(path).endswith('upload.png'):
            return {'data': {'name': 'Hero', 'creator': '上传里的创作者'}}
        return {'data': {'name': 'Hero', 'creator': '旧创作者'}}

    _setup(monkeypatch, tmp_path, extract=extract)

    result = card_service.update_card_content(
        'hero.png',
        str(tmp_path / 'upload.png'),
        is_bundle_update=False,
        keep_ui_data={'creator': '界面里的创作者'},
        new_upload_ext='.png',
    )

    assert result['success'] is True
    assert result['updated_card']['creator'] == '界面里的创作者'
    assert 'creator_preserved' not in result


def test_update_card_content_creator_policy_overwrite_uses_uploaded_value(monkeypatch, tmp_path):
    """显式 overwrite 时才采用上传文件里的创作者。"""

    def extract(path):
        if str(path).endswith('upload.png'):
            return {'data': {'name': 'Hero', 'creator': '上传里的创作者'}}
        return {'data': {'name': 'Hero', 'creator': '旧创作者'}}

    _setup(monkeypatch, tmp_path, extract=extract)

    result = card_service.update_card_content(
        'hero.png',
        str(tmp_path / 'upload.png'),
        is_bundle_update=False,
        keep_ui_data={},
        new_upload_ext='.png',
        creator_policy='overwrite',
    )

    assert result['success'] is True
    assert result['updated_card']['creator'] == '上传里的创作者'
    assert 'creator_preserved' not in result


def test_update_card_content_keeps_uploaded_creator_when_old_card_had_none(monkeypatch, tmp_path):
    """旧卡本来没有创作者时，不应丢弃上传文件里的值。"""

    def extract(path):
        if str(path).endswith('upload.png'):
            return {'data': {'name': 'Hero', 'creator': '新创作者'}}
        return {'data': {'name': 'Hero', 'creator': ''}}

    _setup(monkeypatch, tmp_path, extract=extract)

    result = card_service.update_card_content(
        'hero.png',
        str(tmp_path / 'upload.png'),
        is_bundle_update=False,
        keep_ui_data={},
        new_upload_ext='.png',
    )

    assert result['success'] is True
    assert result['updated_card']['creator'] == '新创作者'
    assert 'creator_preserved' not in result


def test_update_card_content_falls_back_to_cache_creator(monkeypatch, tmp_path):
    """旧文件读不到创作者时，用缓存里的值兜底（来源动作写入后的场景）。"""

    def extract(path):
        return {'data': {'name': 'Hero'}}

    cache = _FakeCache(id_map={'hero.png': {'id': 'hero.png', 'creator': '缓存创作者'}})
    _setup(monkeypatch, tmp_path, extract=extract, cache=cache)

    result = card_service.update_card_content(
        'hero.png',
        str(tmp_path / 'upload.png'),
        is_bundle_update=False,
        keep_ui_data={},
        new_upload_ext='.png',
    )

    assert result['success'] is True
    assert result['creator_preserved'] == '缓存创作者'
    assert result['updated_card']['creator'] == '缓存创作者'


def test_update_card_content_v3_nested_creator_is_preserved(monkeypatch, tmp_path):
    """V3 卡片的 creator 位于 data 节点内，同样要保护。"""

    def extract(path):
        if str(path).endswith('upload.png'):
            return {'spec': 'chara_card_v3', 'data': {'name': 'Hero', 'creator': ''}}
        return {'spec': 'chara_card_v3', 'data': {'name': 'Hero', 'creator': 'V3 原创作者'}}

    _setup(monkeypatch, tmp_path, extract=extract)

    result = card_service.update_card_content(
        'hero.png',
        str(tmp_path / 'upload.png'),
        is_bundle_update=False,
        keep_ui_data={},
        new_upload_ext='.png',
    )

    assert result['success'] is True
    assert result['updated_card']['creator'] == 'V3 原创作者'


@pytest.mark.parametrize(
    'raw,expected',
    [
        (None, 'preserve'),
        ('', 'preserve'),
        ('preserve', 'preserve'),
        ('PRESERVE', 'preserve'),
        ('overwrite', 'overwrite'),
        ('  OVERWRITE  ', 'overwrite'),
        ('garbage', 'preserve'),
    ],
)
def test_normalize_creator_policy_defaults_to_preserve(raw, expected):
    assert cards_api._normalize_creator_policy(raw) == expected


def test_creator_policy_constant_is_shared_with_card_service_default():
    """接口默认值与服务默认值必须一致，否则两条入口行为会分叉。"""
    import inspect

    signature = inspect.signature(card_service.update_card_content)
    assert signature.parameters['creator_policy'].default == cards_api.CREATOR_POLICY_PRESERVE


# --- 前端契约：详情页必须把创作者和策略一起发给后端 ---------------------------


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding='utf-8')


def test_detail_modal_sends_creator_and_policy_on_both_update_paths():
    script = _read('static/js/components/detailModal.js')

    # 文件覆盖与 URL 更新共用同一份 keep_ui_data 结构。
    assert script.count('creator: this.editingData.creator') == 2
    # 文件走 FormData，URL 走 JSON body，两条路径都要带策略。
    assert script.count("formData.append('creator_policy'") == 1
    assert script.count('creator_policy: this.updateCreatorPolicy') == 1
    assert script.count('this.updateCreatorPolicy') == 3  # 2 处发送 + 1 处重置


def test_detail_modal_creator_policy_defaults_to_preserve_and_resets():
    script = _read('static/js/components/detailModal.js')

    assert "updateCreatorPolicy: 'preserve'" in script
    # 切换角色卡时要回到默认值，避免上一张卡的选择泄漏到下一张。
    assert "this.updateCreatorPolicy = 'preserve';" in script


def test_detail_template_exposes_creator_preserve_toggle():
    template = _read('templates/modals/detail_card.html')

    assert 'x-model="updateCreatorPolicy"' in template
    assert 'true-value="preserve"' in template
    assert 'false-value="overwrite"' in template
    assert '覆盖时保留已有创作者' in template


def test_update_card_endpoints_forward_creator_policy_to_service():
    source = _read('core/api/v1/cards.py')

    # 两个更新入口都要解析并透传策略。
    assert source.count('_normalize_creator_policy(') >= 3
    assert 'creator_policy,' in source
    assert "request.form.get('creator_policy')" in source
    assert "data.get('creator_policy')" in source
