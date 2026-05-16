# ui_data.json Durability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ui_data.json` resilient against partial writes, interrupted writes, and corrupted JSON loads without changing the public `load_ui_data()` / `save_ui_data(data)` caller contract.

**Architecture:** Keep the fix inside `core/data/ui_store.py`: add a module-level reentrant lock, write JSON through same-directory temporary files and `os.replace`, maintain a `ui_data.json.bak` last-good backup, and recover from corrupted primary JSON by snapshotting the bad file and restoring the backup. Prove the behavior with a new focused pytest module before touching implementation code.

**Tech Stack:** Python standard library (`threading`, `tempfile`, `shutil`, `os`, `json`), existing `core/data/ui_store.py`, pytest.

---

## File Map

- Modify: `core/data/ui_store.py`
  Responsibility: own all `ui_data.json` persistence, locking, atomic save, last-good backup, corrupted-file snapshot, and load-time recovery.

- Create: `tests/test_ui_store_durability.py`
  Responsibility: isolate `UI_DATA_FILE` to a temp path and verify atomic-write, backup, corruption snapshot, backup recovery, and dirty-cleanup behavior.

## Task 1: Add Failing Durability Tests

**Files:**
- Create: `tests/test_ui_store_durability.py`

- [ ] **Step 1: Create the test module**

Create `tests/test_ui_store_durability.py` with this content:

```python
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


def test_save_ui_data_writes_primary_and_last_good_backup(monkeypatch, tmp_path):
    ui_path = _patch_ui_path(monkeypatch, tmp_path)
    payload = {'hero.png': {'summary': 'fresh'}}

    assert ui_store_module.save_ui_data(payload) is True

    assert _read_json(ui_path) == payload
    assert _read_json(tmp_path / 'ui_data.json.bak') == payload
    assert not list(tmp_path.glob('*.tmp'))


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
    assert _read_json(tmp_path / 'ui_data.json.bak') == expected
    assert not list(tmp_path.glob('*.tmp'))
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run:

```bash
pytest tests/test_ui_store_durability.py -q
```

Expected result before implementation:

- At least `test_save_ui_data_keeps_existing_file_when_json_dump_fails` fails because the current writer truncates the primary file directly.
- Backup/recovery tests fail because `ui_data.json.bak` and `.corrupted.*` handling do not exist yet.

Do not edit implementation code until this failure is observed.

## Task 2: Add Atomic Persistence Helpers

**Files:**
- Modify: `core/data/ui_store.py`

- [ ] **Step 1: Add imports and module-level lock**

At the top of `core/data/ui_store.py`, replace the current imports:

```python
import os
import json
import logging
import time
```

with:

```python
import os
import json
import logging
import shutil
import tempfile
import threading
import time
```

Then add this lock after `logger = logging.getLogger(__name__)`:

```python
_UI_DATA_LOCK = threading.RLock()
```

- [ ] **Step 2: Add path and file helpers before `load_ui_data()`**

Insert these helpers immediately before the current `def load_ui_data():` block:

```python
def _backup_ui_data_file_path():
    return f'{UI_DATA_FILE}.bak'


def _corrupted_ui_data_file_path():
    timestamp = time.strftime('%Y%m%d%H%M%S')
    return f'{UI_DATA_FILE}.corrupted.{timestamp}.{os.getpid()}'


def _read_json_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _copy_current_primary_to_backup_if_valid():
    if not os.path.exists(UI_DATA_FILE):
        return

    try:
        _read_json_file(UI_DATA_FILE)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(f"当前 ui_data.json 无法作为备份源，跳过预写备份: {exc}")
        return

    shutil.copy2(UI_DATA_FILE, _backup_ui_data_file_path())


def _copy_primary_to_backup():
    if os.path.exists(UI_DATA_FILE):
        shutil.copy2(UI_DATA_FILE, _backup_ui_data_file_path())


def _snapshot_corrupted_ui_data():
    if not os.path.exists(UI_DATA_FILE):
        return ''

    corrupted_path = _corrupted_ui_data_file_path()
    shutil.copy2(UI_DATA_FILE, corrupted_path)
    return corrupted_path


def _write_ui_data_file_atomic(data):
    parent_dir = os.path.dirname(UI_DATA_FILE)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    fd = None
    temp_path = ''
    try:
        fd, temp_path = tempfile.mkstemp(
            prefix=f'.{os.path.basename(UI_DATA_FILE)}.',
            suffix='.tmp',
            dir=parent_dir or None,
        )
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            fd = None
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

        os.replace(temp_path, UI_DATA_FILE)
        temp_path = ''
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                logger.warning(f"清理 ui_data.json 临时文件失败: {temp_path}", exc_info=True)
```

- [ ] **Step 3: Replace `save_ui_data(data)` with the atomic implementation**

Replace the existing `save_ui_data(data)` function with:

```python
def save_ui_data(data):
    """
    保存 UI 辅助数据到 JSON 文件。

    Args:
        data (dict): 要保存的数据字典。
    """
    with _UI_DATA_LOCK:
        try:
            parent_dir = os.path.dirname(UI_DATA_FILE)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            _copy_current_primary_to_backup_if_valid()
            _write_ui_data_file_atomic(data)
            _copy_primary_to_backup()
            return True
        except Exception as e:
            logger.error(f"保存 ui_data.json 失败: {e}")
            return False
```

- [ ] **Step 4: Run the save-focused tests**

Run:

```bash
pytest tests/test_ui_store_durability.py::test_save_ui_data_keeps_existing_file_when_json_dump_fails tests/test_ui_store_durability.py::test_save_ui_data_writes_primary_and_last_good_backup -q
```

Expected result after Task 2:

- Both tests pass.
- Recovery tests may still fail until Task 3 is implemented.

## Task 3: Add Corruption Recovery To `load_ui_data()`

**Files:**
- Modify: `core/data/ui_store.py`

- [ ] **Step 1: Add backup recovery helpers before `load_ui_data()`**

Insert these helpers after `_write_ui_data_file_atomic(data)` and before `load_ui_data()`:

```python
def _load_backup_ui_data():
    backup_path = _backup_ui_data_file_path()
    if not os.path.exists(backup_path):
        return None

    try:
        data = _read_json_file(backup_path)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error(f"加载 ui_data.json 备份失败: {exc}")
        return None

    if not isinstance(data, dict):
        logger.error("ui_data.json 备份内容不是对象，无法恢复。")
        return None

    return data


def _recover_corrupted_ui_data(error):
    logger.error(f"ui_data.json 损坏: {error}")

    try:
        corrupted_path = _snapshot_corrupted_ui_data()
        if corrupted_path:
            logger.error(f"已备份损坏的 ui_data.json: {corrupted_path}")
    except Exception as snapshot_error:
        logger.error(f"备份损坏的 ui_data.json 失败: {snapshot_error}")

    backup_data = _load_backup_ui_data()
    if backup_data is None:
        return {}

    if save_ui_data(backup_data):
        logger.warning("已从 ui_data.json.bak 恢复 ui_data.json。")
    else:
        logger.error("从 ui_data.json.bak 恢复 ui_data.json 失败，已返回备份数据。")

    return backup_data
```

- [ ] **Step 2: Replace `load_ui_data()` with recovery-aware loading**

Replace the current `load_ui_data()` implementation with this version. Keep the
existing dirty cleanup rules exactly as shown:

```python
def load_ui_data():
    """
    加载 UI 辅助数据 (JSON 格式)。
    包含用户的卡片备注、来源链接、资源文件夹映射等信息。

    Returns:
        dict: UI 数据字典。如果文件不存在或解析失败，返回空字典。
    """
    with _UI_DATA_LOCK:
        if os.path.exists(UI_DATA_FILE):
            try:
                data = _read_json_file(UI_DATA_FILE)
            except json.JSONDecodeError as e:
                return _recover_corrupted_ui_data(e)
            except Exception as e:
                logger.error(f"加载 ui_data.json 失败: {e}")
                return {}

            if not isinstance(data, dict):
                logger.error("加载 ui_data.json 失败: 根数据不是对象")
                return {}

            # === 脏数据清理逻辑 ===
            # 检查 resource_folder 是否使用了系统保留名称 (如 'cards', 'thumbnails' 等)
            dirty = False
            for key, info in data.items():
                if not isinstance(info, dict):
                    continue

                rf = info.get('resource_folder', '')
                if rf:
                    # 兼容 Windows/Linux 分隔符，取第一层目录名检查
                    first_part = rf.replace('\\', '/').split('/')[0].lower()
                    if first_part in RESERVED_RESOURCE_NAMES:
                        logger.warning(f"检测到非法资源目录配置 '{rf}' (属于保留目录)，已自动移除关联。")
                        info['resource_folder'] = ""
                        dirty = True

                # 规范化 import_time，兼容历史字符串/非法值
                if IMPORT_TIME_KEY in info:
                    normalized_ts = _normalize_timestamp(info.get(IMPORT_TIME_KEY))
                    if normalized_ts is None:
                        del info[IMPORT_TIME_KEY]
                        dirty = True
                    elif info.get(IMPORT_TIME_KEY) != normalized_ts:
                        info[IMPORT_TIME_KEY] = normalized_ts
                        dirty = True

                if LAST_SENT_TO_ST_KEY in info:
                    normalized_sent_ts = _normalize_timestamp(info.get(LAST_SENT_TO_ST_KEY))
                    if normalized_sent_ts is None:
                        del info[LAST_SENT_TO_ST_KEY]
                        dirty = True
                    elif info.get(LAST_SENT_TO_ST_KEY) != normalized_sent_ts:
                        info[LAST_SENT_TO_ST_KEY] = normalized_sent_ts
                        dirty = True

            if dirty:
                # 如果有清理操作，立即回写文件以修正
                save_ui_data(data)

            return data
        return {}
```

- [ ] **Step 3: Run the recovery-focused tests**

Run:

```bash
pytest tests/test_ui_store_durability.py::test_load_ui_data_restores_valid_backup_when_primary_is_corrupt tests/test_ui_store_durability.py::test_load_ui_data_returns_empty_and_preserves_corrupt_file_without_backup tests/test_ui_store_durability.py::test_load_ui_data_dirty_cleanup_uses_atomic_save -q
```

Expected result:

- All three tests pass.
- The corrupted primary is snapshotted as `ui_data.json.corrupted.*`.
- Dirty cleanup writes `ui_data.json.bak`.

## Task 4: Verify Existing Boundary Behavior

**Files:**
- No new files beyond Tasks 1-3.

- [ ] **Step 1: Run the full new durability test file**

Run:

```bash
pytest tests/test_ui_store_durability.py -q
```

Expected result:

```text
5 passed
```

- [ ] **Step 2: Run the existing bundle durability regression**

Run:

```bash
pytest tests/test_cards_api_import_sync.py::test_cache_reload_preserves_bundle_version_remarks_when_db_row_is_missing -q
```

Expected result:

```text
1 passed
```

- [ ] **Step 3: Run whitespace check on touched files**

Run:

```bash
git diff --check -- core/data/ui_store.py tests/test_ui_store_durability.py
```

Expected result: no output and exit code 0.

- [ ] **Step 4: Inspect the final diff**

Run:

```bash
git diff -- core/data/ui_store.py tests/test_ui_store_durability.py
```

Expected review points:

- `core/data/ui_store.py` is the only existing source file modified.
- `tests/test_ui_store_durability.py` is the only new test file.
- No API, scanner, cache, index worker, frontend, or unrelated files are modified.
- `load_ui_data()` and `save_ui_data(data)` names and return contracts are unchanged.

## Task 5: Commit The Implementation Slice

**Files:**
- Stage: `core/data/ui_store.py`
- Stage: `tests/test_ui_store_durability.py`

- [ ] **Step 1: Confirm unrelated existing work remains unstaged**

Run:

```bash
git status --short
```

Expected result:

- `core/data/ui_store.py` and `tests/test_ui_store_durability.py` are modified/new from this task.
- Pre-existing unrelated changes such as `core/api/v1/cards.py`, `core/services/card_service.py`, `static/js/components/cardGrid.js`, or `tests/test_cards_api_import_sync.py` may still appear, but must not be staged for this commit unless they were intentionally changed by the implementation worker.

- [ ] **Step 2: Stage only the implementation files**

Run:

```bash
git add -- core/data/ui_store.py tests/test_ui_store_durability.py
```

- [ ] **Step 3: Confirm staged files**

Run:

```bash
git diff --cached --name-only
```

Expected result:

```text
core/data/ui_store.py
tests/test_ui_store_durability.py
```

- [ ] **Step 4: Commit**

Run:

```bash
git commit -m "fix: harden ui_data json persistence"
```

## Self-Review Checklist

- Spec coverage:
  - Atomic write: Task 2.
  - Module-level lock: Task 2.
  - Last-good backup: Task 2.
  - Corrupted snapshot: Task 3.
  - Backup restore: Task 3.
  - Dirty cleanup preservation: Task 3 and Task 4.
  - Focused pytest coverage: Task 1 and Task 4.

- Scope check:
  - No call-site transaction helper is introduced.
  - No schema migration is introduced.
  - No cache, scanner, index worker, frontend, or API logic is modified.

- Verification:
  - `pytest tests/test_ui_store_durability.py -q`
  - `pytest tests/test_cards_api_import_sync.py::test_cache_reload_preserves_bundle_version_remarks_when_db_row_is_missing -q`
  - `git diff --check -- core/data/ui_store.py tests/test_ui_store_durability.py`
