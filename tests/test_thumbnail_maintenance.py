import hashlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.services.maintenance_service import clean_orphaned_thumbnail_cache


def _cache_name(source_name):
    return hashlib.md5(source_name.replace('\\', '/').encode('utf-8')).hexdigest() + '.webp'


def test_clean_orphaned_thumbnail_cache_keeps_current_sources_and_removes_orphans(tmp_path):
    cards_dir = tmp_path / 'cards'
    thumbnails_dir = tmp_path / 'thumbnails'
    nested_dir = cards_dir / 'nested'
    nested_dir.mkdir(parents=True)
    thumbnails_dir.mkdir()

    (cards_dir / 'alice.png').write_bytes(b'png')
    (nested_dir / 'bob.json').write_text('{}', encoding='utf-8')
    (nested_dir / 'bob.png').write_bytes(b'png')

    kept_direct = thumbnails_dir / _cache_name('alice.png')
    kept_json = thumbnails_dir / _cache_name('bob.png')
    kept_nested_direct = thumbnails_dir / _cache_name('nested/bob.png')
    orphan = thumbnails_dir / _cache_name('missing.png')
    for path in (kept_direct, kept_json, kept_nested_direct, orphan):
        path.write_bytes(b'webp')

    result = clean_orphaned_thumbnail_cache(cards_dir, thumbnails_dir)

    assert result['scanned'] == 4
    assert result['kept'] == 3
    assert result['removed'] == 1
    assert result['errors'] == []
    assert kept_direct.exists()
    assert kept_json.exists()
    assert kept_nested_direct.exists()
    assert not orphan.exists()


def test_clean_orphaned_thumbnail_cache_refuses_missing_cards_directory(tmp_path):
    thumbnails_dir = tmp_path / 'thumbnails'
    thumbnails_dir.mkdir()

    try:
        clean_orphaned_thumbnail_cache(tmp_path / 'missing-cards', thumbnails_dir)
    except FileNotFoundError as exc:
        assert '角色卡目录不存在' in str(exc)
    else:
        raise AssertionError('missing cards directory should stop cleanup')
