"""数据目录独占锁的行为测试。"""

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from core.data import data_dir_lock  # noqa: E402


def _child_script(lock_dir):
    return (
        'import sys;'
        f'sys.path.insert(0, {str(ROOT)!r});'
        'from core.data.data_dir_lock import acquire_data_directory_lock;'
        f'print(acquire_data_directory_lock({str(lock_dir)!r}))'
    )


def _run_child(lock_dir):
    result = subprocess.run(
        [sys.executable, '-c', _child_script(lock_dir)],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_acquire_is_idempotent_within_process(tmp_path):
    try:
        assert data_dir_lock.acquire_data_directory_lock(tmp_path) is True
        assert data_dir_lock.is_data_directory_locked() is True
        # 重复获取应幂等成功
        assert data_dir_lock.acquire_data_directory_lock(tmp_path) is True
    finally:
        data_dir_lock.release_data_directory_lock()


def test_second_process_is_refused_while_held(tmp_path):
    """同一数据目录被第二个进程打开时必须被拒绝。"""
    try:
        assert data_dir_lock.acquire_data_directory_lock(tmp_path) is True
        assert _run_child(tmp_path) == 'False'
    finally:
        data_dir_lock.release_data_directory_lock()


def test_second_process_succeeds_after_release(tmp_path):
    assert data_dir_lock.acquire_data_directory_lock(tmp_path) is True
    data_dir_lock.release_data_directory_lock()

    assert data_dir_lock.is_data_directory_locked() is False
    assert _run_child(tmp_path) == 'True'


def test_stale_lock_file_does_not_block(tmp_path):
    """残留的锁文件（没有活着的持有者）不应阻止启动。"""
    (tmp_path / 'st_manager.lock').write_text('99999', encoding='utf-8')

    try:
        assert data_dir_lock.acquire_data_directory_lock(tmp_path) is True
    finally:
        data_dir_lock.release_data_directory_lock()


def test_release_is_idempotent(tmp_path):
    data_dir_lock.acquire_data_directory_lock(tmp_path)
    data_dir_lock.release_data_directory_lock()
    # 再次释放不应抛异常
    data_dir_lock.release_data_directory_lock()
    assert data_dir_lock.is_data_directory_locked() is False
