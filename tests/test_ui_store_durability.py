import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data import ui_store as ui_store_module


def _write_json(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _patch_ui_path(monkeypatch, tmp_path):
    ui_path = tmp_path / 'ui_data.json'
    monkeypatch.setattr(ui_store_module, 'UI_DATA_FILE', str(ui_path))
    return ui_path


@pytest.fixture(autouse=True)
def _reset_degraded_state():
    """降级标记是模块级全局状态，每个用例前后都要清干净。"""
    ui_store_module._clear_ui_data_degraded()
    yield
    ui_store_module._clear_ui_data_degraded()


def test_save_ui_data_keeps_existing_file_when_json_dump_fails(monkeypatch, tmp_path):
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    original = {'hero.png': {'summary': 'keep me'}}
    _write_json(ui_path, original)

    def failing_dump(_payload, handle, *args, **kwargs):
        handle.write('{"partial":')
        raise RuntimeError('forced json dump failure')

    monkeypatch.setattr(ui_store_module.json, 'dump', failing_dump)

    assert ui_store_module.save_ui_data({'hero.png': {'summary': 'new'}}) is False
    assert _read_json(ui_path) == original
    assert not list(tmp_path.glob('*.tmp'))


def test_save_ui_data_writes_primary_and_keeps_last_good_backup(monkeypatch, tmp_path):
    """首次写入没有历史内容，因此只写主文件；.bak 保持为「上一个可用版本」。"""
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    payload = {'hero.png': {'summary': 'fresh'}}

    assert ui_store_module.save_ui_data(payload) is True

    assert _read_json(ui_path) == payload
    # .bak 不再镜像刚写入的内容；没有历史内容时不应凭空产生备份。
    assert not (tmp_path / 'ui_data.json.bak').exists()
    assert not list(tmp_path.glob('*.tmp'))


def test_save_ui_data_backup_preserves_previous_good_content(monkeypatch, tmp_path):
    """关键回归：.bak 必须是「上一个可用版本」，而不是新写入的镜像。

    这正是导致用户数据无法恢复的旧行为：旧实现在写入后又把主文件复制到
    .bak，使唯一的备份立刻变成损坏内容。
    """
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    good = {'hero.png': {'summary': 'keep me'}}
    _write_json(ui_path, good)

    assert ui_store_module.save_ui_data({'hero.png': {'summary': 'updated'}}) is True

    assert _read_json(ui_path) == {'hero.png': {'summary': 'updated'}}
    # 备份应保留上一版好数据，而不是最新的写入内容。
    assert _read_json(tmp_path / 'ui_data.json.bak') == good
    assert not list(tmp_path.glob('*.tmp'))


def test_backups_rotate_across_generations(monkeypatch, tmp_path):
    """连续写入时备份按世代轮转，保留多个历史版本。"""
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    payloads = [
        {'hero.png': {'summary': f'v{index}' * 200}}
        for index in range(5)
    ]

    for payload in payloads:
        assert ui_store_module.save_ui_data(payload) is True

    assert _read_json(ui_path) == payloads[-1]
    assert _read_json(tmp_path / 'ui_data.json.bak') == payloads[-2]
    assert _read_json(tmp_path / 'ui_data.json.bak.1') == payloads[-3]
    assert _read_json(tmp_path / 'ui_data.json.bak.2') == payloads[-4]
    # 只保留配置的世代数量。
    assert not (tmp_path / 'ui_data.json.bak.3').exists()


def test_load_ui_data_restores_valid_backup_when_primary_is_corrupt(monkeypatch, tmp_path):
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    backup_payload = {'hero.png': {'summary': 'from backup'}}
    ui_path.write_text('{"broken":', encoding='utf-8')
    _write_json(tmp_path / 'ui_data.json.bak', backup_payload)

    loaded = ui_store_module.load_ui_data()

    assert loaded == backup_payload
    assert _read_json(ui_path) == backup_payload
    assert _read_json(tmp_path / 'ui_data.json.bak') == backup_payload
    corrupted_files = list(tmp_path.glob('ui_data.json.corrupted.*'))
    assert len(corrupted_files) == 1
    assert corrupted_files[0].read_text(encoding='utf-8') == '{"broken":'


def test_load_ui_data_returns_empty_and_preserves_corrupt_file_without_backup(monkeypatch, tmp_path):
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    ui_path.write_text('{"broken":', encoding='utf-8')

    assert ui_store_module.load_ui_data() == {}

    corrupted_files = list(tmp_path.glob('ui_data.json.corrupted.*'))
    assert len(corrupted_files) == 1
    assert corrupted_files[0].read_text(encoding='utf-8') == '{"broken":'
    assert ui_path.read_text(encoding='utf-8') == '{"broken":'

    # 即使返回了 {}（为了不让调用方直接崩），也必须处于降级状态，
    # 否则后续 save_ui_data 会把 {} 覆盖到损坏文件上、丢掉人工恢复的机会。
    assert ui_store_module.is_ui_data_degraded() is True
    assert ui_store_module.save_ui_data({'x.png': {'import_time': 1.0}}) is False
    assert ui_path.read_text(encoding='utf-8') == '{"broken":'


def test_load_ui_data_dirty_cleanup_uses_atomic_save(monkeypatch, tmp_path):
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    payload = {
        'hero.png': {
            'summary': 'note',
            'resource_folder': 'cards/bad',
            ui_store_module.IMPORT_TIME_KEY: '1700000000.5',
        }
    }
    _write_json(ui_path, payload)

    loaded = ui_store_module.load_ui_data()

    expected = {
        'hero.png': {
            'summary': 'note',
            'resource_folder': '',
            ui_store_module.IMPORT_TIME_KEY: 1700000000.5,
        }
    }
    assert loaded == expected
    assert _read_json(ui_path) == expected
    # 规范化回写前会先把「清洗前」的原文件轮转为备份，因此 .bak 保存的是原始内容。
    assert _read_json(tmp_path / 'ui_data.json.bak') == payload
    assert not list(tmp_path.glob('*.tmp'))


def test_load_ui_data_raises_on_read_failure_instead_of_returning_empty(monkeypatch, tmp_path):
    """核心回归：读取失败绝不能静默返回 {}，否则调用方会把空数据覆盖回磁盘。

    旧实现 `except Exception: return {}` 正是 1.75MB 数据被清空的根因。
    """
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    original = {'hero.png': {'summary': 'my precious notes'}}
    _write_json(ui_path, original)

    def failing_read(_path, *_args, **_kwargs):
        raise PermissionError(13, 'The process cannot access the file')

    monkeypatch.setattr(ui_store_module, '_read_json_file', failing_read)

    with pytest.raises(ui_store_module.UiDataLoadError):
        ui_store_module.load_ui_data()

    # 磁盘上的真实数据必须原封不动。
    assert _read_json(ui_path) == original
    # 并且进入降级状态，禁止后续保存。
    assert ui_store_module.is_ui_data_degraded() is True
    assert ui_store_module.save_ui_data({'new.png': {'import_time': 1.0}}) is False
    assert _read_json(ui_path) == original


def test_load_ui_data_recovers_from_backup_on_read_failure(monkeypatch, tmp_path):
    """读取失败但存在可用备份时，应恢复而不是报错。"""
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    backup_payload = {'hero.png': {'summary': 'from backup'}}
    _write_json(tmp_path / 'ui_data.json.bak', backup_payload)
    ui_path.write_text('{"torn":', encoding='utf-8')

    loaded = ui_store_module.load_ui_data()

    assert loaded == backup_payload
    assert _read_json(ui_path) == backup_payload


def _big_payload(card_count=400):
    return {
        f'Hero {index}.png': {
            'summary': f'我的本地备注 {index} ' + 'x' * 200,
            'link': f'https://example.com/{index}',
            'import_time': 1789000000.0 + index,
        }
        for index in range(card_count)
    }


def test_save_ui_data_rejects_catastrophic_shrink(monkeypatch, tmp_path):
    """退化写入护栏：拒绝把大文件覆盖成近乎空的内容。"""
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    original = _big_payload()
    _write_json(ui_path, original)
    original_size = ui_path.stat().st_size

    # 模拟「读失败后只剩一条新卡片」的退化写入。
    assert ui_store_module.save_ui_data({'New Card.png': {'import_time': 1.0}}) is False

    assert ui_path.stat().st_size == original_size
    assert _read_json(ui_path) == original


def test_save_ui_data_allows_shrink_when_explicitly_confirmed(monkeypatch, tmp_path):
    """批量删除等合法场景可显式放行退化护栏。"""
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    _write_json(ui_path, _big_payload())

    reduced = {'Hero 0.png': {'summary': 'only one left'}}
    assert ui_store_module.save_ui_data(reduced, allow_shrink=True) is True

    assert _read_json(ui_path) == reduced


def test_save_ui_data_allows_normal_growth(monkeypatch, tmp_path):
    """正常增长不应被护栏误伤。"""
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    payload = _big_payload()
    _write_json(ui_path, payload)

    payload['Hero new.png'] = {'summary': 'added', 'import_time': 1.0}
    assert ui_store_module.save_ui_data(payload) is True
    assert _read_json(ui_path) == payload


def test_update_ui_data_serializes_concurrent_writers(monkeypatch, tmp_path):
    """update_ui_data 把 load->改->save 收进同一把锁，消除 lost update。"""
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    _write_json(ui_path, {'Base.png': {'summary': 'base'}})

    import threading

    errors = []
    # 让所有线程尽量同时进入 update_ui_data，最大化交错概率。
    start_gate = threading.Barrier(4)

    def writer(index):
        def mutate(data):
            # 注意：此处已持有 ui_data 锁，不能再等待其他写者，
            # 否则会与锁形成死锁。等待只发生在进入锁之前。
            data[f'Hero {index}.png'] = {'summary': f'written by {index}'}
        try:
            start_gate.wait()
            assert ui_store_module.update_ui_data(mutate) is True
        except Exception as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(index,)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    final = _read_json(ui_path)
    # 旧实现下会有写入被覆盖丢失；事务入口应保留全部 4 次写入。
    for index in range(4):
        assert f'Hero {index}.png' in final
    assert final['Base.png'] == {'summary': 'base'}


def test_update_ui_data_aborts_when_read_fails(monkeypatch, tmp_path):
    """读取失败时 update_ui_data 必须中止，不得覆盖磁盘数据。"""
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    original = _big_payload(card_count=50)
    _write_json(ui_path, original)

    def failing_read(_path, *_args, **_kwargs):
        raise PermissionError(13, 'busy')

    monkeypatch.setattr(ui_store_module, '_read_json_file', failing_read)

    def mutate(data):  # pragma: no cover - 不应被调用
        data['Hero new.png'] = {'summary': 'should not persist'}

    assert ui_store_module.update_ui_data(mutate) is False
    assert _read_json(ui_path) == original

