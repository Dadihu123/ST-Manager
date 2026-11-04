import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data import st_bridge_store
from core.services import st_bridge_service
from core.services.st_bridge_service import StBridgeError


PNG_BYTES = b'\x89PNG\r\n\x1a\nst-manager-bridge-test-card'


@pytest.fixture()
def bridge_dirs(tmp_path, monkeypatch):
    """隔离的库目录 / 酒馆角色目录 / 桥接清单。"""
    cards = tmp_path / 'library'
    chars = tmp_path / 'st' / 'characters'
    cards.mkdir()
    chars.mkdir(parents=True)
    store_path = tmp_path / 'st_bridge.json'

    monkeypatch.setattr(st_bridge_store, '_store_path', lambda: str(store_path))
    monkeypatch.setattr(st_bridge_service, '_request_scan', lambda reason: None)
    return cards, chars


def _write_card(cards, relative, payload=PNG_BYTES):
    path = Path(cards) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


# ---------------------------------------------------------------- 装载


def test_checkout_copies_card_and_records_source(bridge_dirs):
    cards, chars = bridge_dirs
    _write_card(cards, '🎦已分类卡区/🎮游戏/原神.png')

    result = st_bridge_service.checkout(
        '🎦已分类卡区/🎮游戏/原神.png',
        cards_dir=str(cards),
        characters_dir=str(chars),
    )

    assert result['success'] is True
    assert result['staged_name'] == '原神.png'
    assert result['reused'] is False
    assert (chars / '原神.png').read_bytes() == PNG_BYTES

    entry = st_bridge_store.get('原神.png')
    assert entry is not None
    assert entry['source_id'] == '🎦已分类卡区/🎮游戏/原神.png'
    assert entry['origin'] == 'library'
    assert len(entry['source_hash']) == 64
    assert entry['staged_size'] == len(PNG_BYTES)


def test_checkout_reuses_existing_copy_for_same_source(bridge_dirs):
    cards, chars = bridge_dirs
    _write_card(cards, 'a/card.png')

    first = st_bridge_service.checkout('a/card.png', cards_dir=str(cards), characters_dir=str(chars))
    second = st_bridge_service.checkout('a/card.png', cards_dir=str(cards), characters_dir=str(chars))

    assert second['reused'] is True
    assert second['staged_name'] == first['staged_name']
    assert len(st_bridge_store.load_all()) == 1


def test_checkout_suffixes_name_when_basename_taken(bridge_dirs):
    cards, chars = bridge_dirs
    _write_card(cards, 'aaa/card.png')
    _write_card(cards, 'bbb/card.png', b'\x89PNG\r\n\x1a\nother')

    first = st_bridge_service.checkout('aaa/card.png', cards_dir=str(cards), characters_dir=str(chars))
    second = st_bridge_service.checkout('bbb/card.png', cards_dir=str(cards), characters_dir=str(chars))

    assert first['staged_name'] == 'card.png'
    assert second['staged_name'] == 'card__1.png'
    assert (chars / 'card__1.png').exists()


@pytest.mark.parametrize(
    'unsafe_id',
    [
        '../evil.png',
        '..\\evil.png',
        '/absolute/evil.png',
        'C:/windows/evil.png',
        '',
    ],
)
def test_checkout_rejects_unsafe_or_empty_ids(bridge_dirs, unsafe_id):
    cards, chars = bridge_dirs
    _write_card(cards, 'a/card.png')

    with pytest.raises(StBridgeError) as excinfo:
        st_bridge_service.checkout(unsafe_id, cards_dir=str(cards), characters_dir=str(chars))

    assert excinfo.value.status_code in (400, 404)
    assert st_bridge_store.load_all() == {}


def test_checkout_requires_resolvable_characters_dir(bridge_dirs, monkeypatch):
    cards, _chars = bridge_dirs
    _write_card(cards, 'a/card.png')
    monkeypatch.setattr(st_bridge_service, 'get_characters_dir', lambda: None)

    with pytest.raises(StBridgeError) as excinfo:
        st_bridge_service.checkout('a/card.png', cards_dir=str(cards))

    assert excinfo.value.status_code == 400


# ---------------------------------------------------------------- 提交


def test_commit_writes_back_staged_content_and_backs_up_source(bridge_dirs):
    cards, chars = bridge_dirs
    source = _write_card(cards, 'a/card.png', b'version-one')
    st_bridge_service.checkout('a/card.png', cards_dir=str(cards), characters_dir=str(chars))
    (chars / 'card.png').write_bytes(b'version-two-edited')

    result = st_bridge_service.commit('card.png', cards_dir=str(cards), characters_dir=str(chars))

    assert result['success'] is True
    assert source.read_bytes() == b'version-two-edited'
    assert os.path.isfile(result['backup'])
    assert Path(result['backup']).read_bytes() == b'version-one'

    entry = st_bridge_store.get('card.png')
    assert entry['source_hash'] == st_bridge_service._sha256(str(source))
    assert entry['committed_at']


def test_commit_refuses_to_clobber_source_changed_after_checkout(bridge_dirs):
    cards, chars = bridge_dirs
    source = _write_card(cards, 'a/card.png', b'version-one')
    st_bridge_service.checkout('a/card.png', cards_dir=str(cards), characters_dir=str(chars))
    (chars / 'card.png').write_bytes(b'version-two-edited')
    source.write_bytes(b'changed-elsewhere')

    with pytest.raises(StBridgeError) as excinfo:
        st_bridge_service.commit('card.png', cards_dir=str(cards), characters_dir=str(chars))

    assert excinfo.value.status_code == 409
    assert excinfo.value.extra['conflict'] is True
    assert source.read_bytes() == b'changed-elsewhere'


def test_commit_with_force_overwrites_source(bridge_dirs):
    cards, chars = bridge_dirs
    source = _write_card(cards, 'a/card.png', b'version-one')
    st_bridge_service.checkout('a/card.png', cards_dir=str(cards), characters_dir=str(chars))
    (chars / 'card.png').write_bytes(b'version-two-edited')
    source.write_bytes(b'changed-elsewhere')

    st_bridge_service.commit('card.png', force=True, cards_dir=str(cards), characters_dir=str(chars))

    assert source.read_bytes() == b'version-two-edited'


def test_commit_reports_missing_staged_file(bridge_dirs):
    cards, chars = bridge_dirs
    _write_card(cards, 'a/card.png')
    st_bridge_service.checkout('a/card.png', cards_dir=str(cards), characters_dir=str(chars))
    (chars / 'card.png').unlink()

    with pytest.raises(StBridgeError) as excinfo:
        st_bridge_service.commit('card.png', cards_dir=str(cards), characters_dir=str(chars))

    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------- 丢弃


def test_discard_removes_copy_but_keeps_source(bridge_dirs):
    cards, chars = bridge_dirs
    source = _write_card(cards, 'a/card.png')
    st_bridge_service.checkout('a/card.png', cards_dir=str(cards), characters_dir=str(chars))

    result = st_bridge_service.discard('card.png', characters_dir=str(chars))

    assert result['success'] is True
    assert result['removed'] is True
    assert not (chars / 'card.png').exists()
    assert source.exists()
    assert st_bridge_store.get('card.png') is None


def test_discard_unknown_entry_returns_404(bridge_dirs):
    _cards, chars = bridge_dirs
    with pytest.raises(StBridgeError) as excinfo:
        st_bridge_service.discard('nope.png', characters_dir=str(chars))
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------- 状态与目录树


def test_status_marks_edited_copy_and_missing_source(bridge_dirs):
    cards, chars = bridge_dirs
    _write_card(cards, 'a/edited.png')
    gone = _write_card(cards, 'a/gone.png', b'\x89PNG\r\n\x1a\ngone')
    st_bridge_service.checkout('a/edited.png', cards_dir=str(cards), characters_dir=str(chars))
    st_bridge_service.checkout('a/gone.png', cards_dir=str(cards), characters_dir=str(chars))

    (chars / 'edited.png').write_bytes(b'\x89PNG\r\n\x1a\nrewritten-in-tavern')
    gone.unlink()

    status = st_bridge_service.status(cards_dir=str(cards), characters_dir=str(chars))
    by_source = {item['source_id']: item for item in status['items']}

    assert status['total'] == 2
    assert status['edited'] == 1
    assert by_source['a/edited.png']['edited'] is True
    assert by_source['a/gone.png']['missing_source'] is True
    assert by_source['a/gone.png']['edited'] is False


def test_status_verify_detects_conflict_with_same_size_edit(bridge_dirs):
    cards, chars = bridge_dirs
    source = _write_card(cards, 'a/card.png', b'version-one')
    st_bridge_service.checkout('a/card.png', cards_dir=str(cards), characters_dir=str(chars))
    source.write_bytes(b'version-two')  # 与 version-one 等长，靠哈希才能发现

    cheap = st_bridge_service.status(cards_dir=str(cards), characters_dir=str(chars))
    strict = st_bridge_service.status(verify=True, cards_dir=str(cards), characters_dir=str(chars))

    assert cheap['items'][0]['conflict'] is False
    assert strict['items'][0]['conflict'] is True
    assert strict['conflict'] == 1


def test_status_separates_library_staged_from_tavern_imports(bridge_dirs):
    cards, chars = bridge_dirs
    _write_card(cards, 'a/card.png')
    st_bridge_service.checkout('a/card.png', cards_dir=str(cards), characters_dir=str(chars))
    (chars / 'fresh-from-tavern.png').write_bytes(b'\x89PNG\r\n\x1a\ntavern')

    status = st_bridge_service.status(cards_dir=str(cards), characters_dir=str(chars))
    by_name = {item['filename']: item for item in status['items']}

    assert status['total'] == 2
    assert status['staged'] == 1
    assert by_name['card.png']['origin'] == 'library'
    assert by_name['fresh-from-tavern.png']['origin'] == 'st_import'
    assert by_name['fresh-from-tavern.png']['source_id'] == ''


def test_status_lists_dangling_entry_when_copy_deleted(bridge_dirs):
    cards, chars = bridge_dirs
    _write_card(cards, 'a/card.png')
    st_bridge_service.checkout('a/card.png', cards_dir=str(cards), characters_dir=str(chars))
    (chars / 'card.png').unlink()

    status = st_bridge_service.status(cards_dir=str(cards), characters_dir=str(chars))

    assert status['total'] == 1
    assert status['items'][0]['staged_missing'] is True


def test_public_tree_counts_cards_per_folder(bridge_dirs):
    cards, chars = bridge_dirs
    _write_card(cards, 'a/one.png')
    _write_card(cards, 'a/two.png', b'\x89PNG\r\n\x1a\ntwo')
    _write_card(cards, 'a/b/three.json', b'{}')
    (cards / 'a' / 'notes.txt').write_text('ignore me', encoding='utf-8')

    tree = st_bridge_service.public_tree(cards_dir=str(cards), characters_dir=str(chars))

    assert tree['folders']['a'] == 2
    assert tree['folders']['a/b'] == 1
    assert tree['total'] == 3
    assert tree['pending_dir'] == str(chars)


def test_store_survives_corrupted_manifest(bridge_dirs, tmp_path):
    cards, chars = bridge_dirs
    store_path = Path(st_bridge_store._store_path())
    store_path.write_text('{not json', encoding='utf-8')

    assert st_bridge_store.load_all() == {}
    _write_card(cards, 'a/card.png')
    result = st_bridge_service.checkout('a/card.png', cards_dir=str(cards), characters_dir=str(chars))
    assert result['success'] is True
