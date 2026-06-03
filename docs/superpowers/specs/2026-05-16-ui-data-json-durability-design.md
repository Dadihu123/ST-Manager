# ui_data.json Durability Design

## Background

`ui_data.json` is the durable store for ST-Manager UI state such as card notes,
source links, resource-folder mappings, tag/category preferences, worldinfo notes,
beautify state, and bundle version remarks. The SQLite database and runtime caches
may be rebuilt from the filesystem, but `ui_data.json` contains user-authored state
that cannot always be reconstructed.

The current `core/data/ui_store.py` implementation writes the file with
`open(UI_DATA_FILE, 'w')` followed by `json.dump(...)`. Opening in write mode
truncates the existing file before the JSON payload is fully serialized. If the
process exits, serialization fails, or a concurrent reader observes the file during
that window, the next `load_ui_data()` can see an empty or partial JSON document.
Today `load_ui_data()` catches all exceptions, logs the parse failure, and returns
`{}`. A later successful `save_ui_data({})` can then make the data loss permanent.

v100 increased the number of background and startup paths that read `ui_data.json`.
Some reads can also become writes because `load_ui_data()` performs normalization
and immediately saves when it finds dirty fields. The v99 to v100 diff does not show
a direct clearing path, but the non-atomic persistence model is a real durability
risk and should be fixed before investigating wider lost-update semantics.

## Goal

Make `ui_data.json` resilient against partial writes, interrupted writes, and
damaged JSON loads while keeping the existing public `load_ui_data()` and
`save_ui_data(data)` API stable for all current callers.

## In Scope

- Add atomic write behavior for `save_ui_data(data)`.
- Serialize `load_ui_data()` and `save_ui_data(data)` with a module-level lock
  inside `core/data/ui_store.py`.
- Preserve a last-good backup next to `ui_data.json`.
- Back up corrupted JSON before returning fallback data.
- Restore from the last-good backup when the primary file is unreadable and the
  backup is valid.
- Keep `load_ui_data()` dirty cleanup behavior, but route cleanup saves through
  the new atomic writer.
- Add focused pytest coverage for the durability behavior.

## Out Of Scope

- Replacing all `load_ui_data() -> mutate -> save_ui_data()` call sites with a
  transaction/update helper.
- Merging concurrent semantic changes to different keys.
- Changing the JSON schema or migrating existing UI data.
- Changing cache rebuild, scanner, index worker, or API behavior outside the
  persistence helper boundary.
- Changing `core.utils.filesystem.save_json_atomic(...)` or making it a general
  project-wide persistence primitive.

## Chosen Approach

Use a narrow persistence-layer fix in `core/data/ui_store.py`.

The key design is:

1. Add a module-level `threading.RLock`.
2. Make `save_ui_data(data)` write to a unique temporary file in the same directory.
3. Flush and `fsync` the temporary file.
4. Replace `ui_data.json` with `os.replace(...)`.
5. Keep a `ui_data.json.bak` last-good backup.
6. Teach `load_ui_data()` to preserve corrupted files and recover from the backup.

This is intentionally smaller than a full transactional UI-store rewrite. It
addresses file truncation and corrupted reads without changing caller contracts or
business logic.

## Alternatives Considered

### Atomic Write Only

Only changing `save_ui_data()` to write a temporary file and rename it would fix
most partial-write cases. It is not enough because damaged files from older builds,
manual edits, or storage interruptions would still cause `load_ui_data()` to return
`{}` with no recovery attempt.

### Full Transactional Update Helper

A helper such as `update_ui_data(mutator)` could lock a full read-modify-write
operation and reduce lost updates between concurrent callers. That is valuable but
requires touching many API and service call sites. It should be a later follow-up
after the core file durability boundary is safe.

### Reuse `core.utils.filesystem.save_json_atomic(...)`

The existing helper sorts data and writes with 4-space indentation. Reusing it for
`ui_data.json` would introduce broad formatting churn and may reorder user data.
This design keeps the current `ensure_ascii=False, indent=2` behavior in
`ui_store.py`.

## Detailed Design

### Atomic Save

`save_ui_data(data)` will keep the same return contract: `True` on success and
`False` on failure.

Implementation details:

- Ensure the parent directory exists with `os.makedirs(parent_dir, exist_ok=True)`.
- Create the temporary file in the same directory using `tempfile.mkstemp(...)`.
- Use a unique prefix such as `.ui_data.json.` and suffix `.tmp`.
- Open the returned file descriptor with UTF-8 text mode.
- Call `json.dump(data, f, ensure_ascii=False, indent=2)`.
- Flush and `os.fsync(f.fileno())`.
- Before replacing the primary file, copy the current valid primary file to
  `ui_data.json.bak` when it exists and is readable as JSON.
- Replace the primary file with `os.replace(temp_path, UI_DATA_FILE)`.
- After replacement, refresh `ui_data.json.bak` from the newly written primary file.
- Remove the temporary file on failure if it still exists.

The backup refresh after replacement is deliberate. If the previous primary was
already corrupt, the new successful write should become the last-good backup.

### Locking

Add `_UI_DATA_LOCK = threading.RLock()` in `core/data/ui_store.py`.

Both `load_ui_data()` and `save_ui_data(data)` will acquire this lock. `RLock` is
required because `load_ui_data()` can call `save_ui_data(data)` during dirty cleanup.

This lock protects in-process readers from observing a primary file while the same
process is writing or recovering it. Atomic replace protects cross-process readers
from partial primary-file writes at the filesystem boundary.

This lock does not solve semantic lost updates where two callers load the same old
state and later save different modified copies. That remains a separate follow-up.

### Corruption Handling

`load_ui_data()` will distinguish JSON corruption from other I/O failures.

When `json.load(...)` raises `json.JSONDecodeError`:

1. Log an error with the parse exception.
2. Copy the damaged primary file to a timestamped sibling file:
   `ui_data.json.corrupted.<YYYYmmddHHMMSS>.<pid>`.
3. Attempt to load `ui_data.json.bak`.
4. If the backup is valid, restore it to the primary using the same atomic save
   flow and return the backup data.
5. If the backup is missing or invalid, return `{}`.

When opening or reading the primary raises `OSError`, keep the current safe fallback
behavior of logging and returning `{}`. The implementation may still attempt backup
loading for read failures if the primary file cannot be opened, but it must not
delete or overwrite the unreadable primary.

### Backup Naming

Use two backup concepts:

- `ui_data.json.bak`: last-good machine backup, overwritten after successful saves.
- `ui_data.json.corrupted.<timestamp>.<pid>`: forensic snapshot of a damaged primary.

The `.bak` file is for automatic recovery. The `.corrupted.*` file is for manual
inspection and should never be loaded automatically except by a human.

### Dirty Cleanup

`load_ui_data()` currently normalizes invalid `resource_folder`, `import_time`, and
`last_sent_to_st` fields and saves the file immediately if changes were made. This
behavior stays in place.

The only change is that the cleanup save now runs through the locked atomic
`save_ui_data(data)` implementation. No new cleanup rules are introduced.

## Error Handling

- `save_ui_data(data)` logs `logger.error(...)` and returns `False` if JSON
  serialization, temp-file creation, fsync, copy, or replace fails.
- `save_ui_data(data)` must not truncate or replace the primary file when
  serialization fails.
- `load_ui_data()` logs parse failures with enough context to identify the primary
  path and backup outcome.
- If the primary is corrupt and backup recovery succeeds, the log should clearly say
  that the backup was restored.
- If both primary and backup are invalid, the function returns `{}` but leaves both
  files available for manual recovery.

## Testing Strategy

Add `tests/test_ui_store_durability.py`.

Required tests:

1. `test_save_ui_data_keeps_existing_file_when_json_dump_fails`
   - Create a valid `ui_data.json`.
   - Patch `json.dump` in `core.data.ui_store` to write a partial temp payload and
     raise an exception.
   - Assert `save_ui_data(...) is False`.
   - Assert the primary file still contains the original valid JSON.

2. `test_save_ui_data_writes_primary_and_last_good_backup`
   - Save a payload through `save_ui_data(...)`.
   - Assert the primary and `.bak` files both contain the new payload.
   - Assert no `.tmp` files remain in the directory.

3. `test_load_ui_data_restores_valid_backup_when_primary_is_corrupt`
   - Write invalid JSON to `ui_data.json`.
   - Write valid JSON to `ui_data.json.bak`.
   - Assert `load_ui_data()` returns the backup payload.
   - Assert the primary file is restored to valid JSON.
   - Assert a `ui_data.json.corrupted.*` snapshot exists.

4. `test_load_ui_data_returns_empty_and_preserves_corrupt_file_without_backup`
   - Write invalid JSON to `ui_data.json`.
   - Ensure no `.bak` exists.
   - Assert `load_ui_data()` returns `{}`.
   - Assert the invalid primary still exists or has been preserved as a corrupted
     snapshot.

5. `test_load_ui_data_dirty_cleanup_uses_atomic_save`
   - Write valid JSON with a dirty `import_time` or invalid `resource_folder`.
   - Call `load_ui_data()`.
   - Assert returned data and primary file both contain the normalized value.

Targeted verification:

```bash
pytest tests/test_ui_store_durability.py -q
```

Follow-up verification:

```bash
pytest tests/test_cards_api_import_sync.py::test_cache_reload_preserves_bundle_version_remarks_when_db_row_is_missing -q
```

Full-suite verification is useful before release, but this spec only requires the
targeted durability test plus the existing bundle-remark regression because the
implementation stays inside `ui_store.py`.

## Risks

- The module-level lock only covers the current Python process. It does not prevent
  two separate ST-Manager processes from racing semantically, though atomic replace
  still prevents partial-file exposure.
- Refreshing `.bak` on every successful save means a legitimate empty `{}` save can
  eventually become the last-good backup. This is acceptable for this slice because
  the objective is corruption recovery, not business-level write validation.
- `ui_data.json.bak` can become stale if users edit the primary file manually while
  the app is not running. The next successful app save will refresh it.
- Returning `{}` when both primary and backup are invalid preserves current caller
  compatibility but still allows later callers to save empty data. The corrupted
  snapshot makes recovery possible, but the best long-term fix is a transactional
  update helper and stricter caller-side handling.

## Success Criteria

- `save_ui_data(data)` no longer truncates `ui_data.json` before a complete payload
  is available.
- A failed serialization does not alter the existing primary file.
- A successful save creates or refreshes `ui_data.json.bak`.
- A corrupted primary file is copied to a timestamped `.corrupted.*` sibling.
- A valid backup is automatically restored when the primary is corrupt.
- Existing callers can continue using `load_ui_data()` and `save_ui_data(data)`
  without API changes.
- Targeted pytest coverage passes.

## Follow-Up Work

After this durability fix lands, evaluate a second spec for semantic lost-update
protection. That follow-up should introduce an explicit `update_ui_data(mutator)`
or equivalent helper and migrate high-risk call sites gradually, starting with API
routes that update independent top-level keys.
