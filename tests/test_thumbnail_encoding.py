"""真实生成缩略图，覆盖 Android Pillow 没有 WebP 编码器的环境。"""

import hashlib
import io

import pytest
from flask import Flask
from PIL import Image, features

from core.api.v1 import resources
from core.services import maintenance_service
from core.services.maintenance_service import clean_orphaned_thumbnail_cache
from core.utils.image import clean_thumbnail_cache


@pytest.fixture
def thumbnail_client(monkeypatch, tmp_path):
    cards = tmp_path / 'cards'
    thumbs = tmp_path / 'thumbnails'
    cards.mkdir()
    thumbs.mkdir()
    monkeypatch.setattr(resources, 'CARDS_FOLDER', str(cards))
    monkeypatch.setattr(resources, 'THUMB_FOLDER', str(thumbs))
    app = Flask(__name__)
    app.register_blueprint(resources.bp)
    return app.test_client(), cards, thumbs


@pytest.mark.parametrize('webp', [False, True])
def test_thumbnail_uses_supported_encoder_and_reuses_cache(thumbnail_client, monkeypatch, webp):
    if webp and not features.check('webp'):
        pytest.skip('Local Pillow has no WebP encoder')
    client, cards, thumbs = thumbnail_client
    Image.new('RGBA', (600, 900), (220, 20, 30, 255)).save(cards / '角色.png')
    monkeypatch.setattr(resources.features, 'check', lambda _feature: webp)

    response = client.get('/api/thumbnail/角色.png')

    assert response.status_code == 200
    assert response.mimetype == ('image/webp' if webp else 'image/jpeg')
    with Image.open(io.BytesIO(response.data)) as thumbnail:
        assert thumbnail.size == (300, 450)
        assert thumbnail.getpixel((0, 0))[0] > 200
    cache_file, = thumbs.iterdir()
    mtime = cache_file.stat().st_mtime_ns
    monkeypatch.setattr(resources.Image, 'open', lambda *_: pytest.fail('Cache was not reused'))
    assert client.get('/api/thumbnail/角色.png').data == response.data
    assert cache_file.stat().st_mtime_ns == mtime


def test_nested_json_sidecars_have_distinct_jpeg_caches(thumbnail_client, monkeypatch):
    client, cards, thumbs = thumbnail_client
    monkeypatch.setattr(resources.features, 'check', lambda _feature: False)
    for folder, color in [('a', 'red'), ('b', 'blue')]:
        (cards / folder).mkdir()
        (cards / folder / 'card.json').write_text('{}')
        Image.new('RGB', (600, 900), color).save(cards / folder / 'card.png')
    red = client.get('/api/thumbnail/a/card.json')
    blue = client.get('/api/thumbnail/b/card.json')
    assert red.data != blue.data
    assert len(list(thumbs.glob('*.jpg'))) == 2
    assert clean_orphaned_thumbnail_cache(cards, thumbs)['kept'] == 2


def test_cache_invalidation_and_maintenance_cover_jpeg(thumbnail_client):
    _client, cards, thumbs = thumbnail_client
    (cards / 'nested').mkdir()
    Image.new('RGB', (10, 10)).save(cards / 'nested' / 'card.png')
    for name in ['nested/card.png', 'missing.png']:
        cache_hash = hashlib.md5(name.encode('utf-8')).hexdigest()
        for extension in ['.webp', '.jpg']:
            (thumbs / (cache_hash + extension)).write_bytes(b'cached')
    result = clean_orphaned_thumbnail_cache(cards, thumbs)
    assert result['kept'] == result['removed'] == 2
    clean_thumbnail_cache('nested/card.png', str(thumbs))
    assert list(thumbs.iterdir()) == []


def test_thumbnail_rejects_parent_directory(thumbnail_client):
    client, cards, _thumbs = thumbnail_client
    Image.new('RGB', (10, 10)).save(cards.parent / 'outside.png')
    assert client.get('/api/thumbnail/../outside.png').status_code == 403


def test_inaccessible_directory_aborts_thumbnail_cleanup(thumbnail_client, monkeypatch):
    _client, cards, thumbs = thumbnail_client
    cached = thumbs / ('a' * 32 + '.jpg')
    cached.write_bytes(b'cached')

    def incomplete_walk(_root):
        yield str(cards), ['inaccessible'], []
        raise PermissionError('inaccessible directory')

    monkeypatch.setattr(maintenance_service, 'walk_directory_strict', incomplete_walk)
    with pytest.raises(PermissionError):
        clean_orphaned_thumbnail_cache(cards, thumbs)
    assert cached.exists()
