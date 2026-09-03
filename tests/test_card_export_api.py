import json
import sys
from pathlib import Path

from flask import Flask
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.api.v1 import cards as cards_api
from core.utils.image import write_card_metadata


def _make_app():
    app = Flask(__name__)
    app.register_blueprint(cards_api.bp)
    return app


def test_export_json_card_preserves_v3_payload(monkeypatch, tmp_path):
    cards_root = tmp_path / 'cards'
    cards_root.mkdir()
    card_path = cards_root / 'hero.json'
    payload = {
        'spec': 'chara_card_v3',
        'spec_version': '3.0',
        'data': {
            'name': '测试角色',
            'description': '角色描述',
            'first_mes': '你好',
            'alternate_greetings': ['备用开场白'],
            'extensions': {'custom_extension': {'enabled': True}},
            'character_book': {'name': '角色世界书', 'entries': []},
        },
        'custom_top_level': {'preserve': 'yes'},
    }
    card_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_root))

    response = _make_app().test_client().post('/api/cards/export', json={'id': 'hero.json'})

    assert response.status_code == 200
    assert 'attachment' in response.headers['Content-Disposition']
    assert 'hero.json' in response.headers['Content-Disposition']
    assert response.get_json() == payload


def test_export_png_card_from_bundle_preserves_embedded_card_data(monkeypatch, tmp_path):
    cards_root = tmp_path / 'cards'
    bundle_root = cards_root / 'pack'
    bundle_root.mkdir(parents=True)
    (bundle_root / '.bundle').write_text('1', encoding='utf-8')
    card_path = bundle_root / 'cover.png'
    payload = {
        'spec': 'chara_card_v3',
        'spec_version': '3.0',
        'data': {
            'name': 'Bundle 角色',
            'first_mes': '来自 bundle 的开场白',
            'alternate_greetings': ['备用版本一', '备用版本二'],
            'extensions': {'source': {'revision': 2}},
            'character_book': {'name': 'Bundle Book', 'entries': []},
        },
    }
    Image.new('RGBA', (2, 2), (80, 120, 180, 255)).save(card_path, format='PNG')
    assert write_card_metadata(str(card_path), payload) is True
    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_root))

    response = _make_app().test_client().post('/api/cards/export', json={'id': 'pack/cover.png'})

    assert response.status_code == 200
    exported = response.get_json()
    assert exported['data']['name'] == 'Bundle 角色'
    assert exported['data']['alternate_greetings'] == ['备用版本一', '备用版本二']
    assert exported['data']['extensions'] == {'source': {'revision': 2}}
    assert exported['data']['character_book']['name'] == 'Bundle Book'


def test_export_card_rejects_unsafe_or_non_card_paths(monkeypatch, tmp_path):
    cards_root = tmp_path / 'cards'
    cards_root.mkdir()
    (cards_root / 'notes.txt').write_text('not a card', encoding='utf-8')
    monkeypatch.setattr(cards_api, 'CARDS_FOLDER', str(cards_root))
    client = _make_app().test_client()

    unsafe = client.post('/api/cards/export', json={'id': '../hero.png'})
    non_card = client.post('/api/cards/export', json={'id': 'notes.txt'})

    assert unsafe.status_code == 400
    assert non_card.status_code == 400
