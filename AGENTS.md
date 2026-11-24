# AGENTS.md

Python 3.10+ / Flask / SQLite / Pillow / requests / watchdog. Entry `app.py`; factory
`core/__init__.py:create_app`; startup `init_services`; code in `core/api/v1/`, `core/services/`,
`core/data/`, `core/utils/`, `tests/`. Any `.cursorrules`, `.cursor/rules/` or
`.github/copilot-instructions.md` added later is an extra constraint.

Detailed rules — environment, test commands, docs allowlist, plugin contract v3, generated
artifacts, architecture conventions, database and state, paths, packaging, imports/naming/
formatting, testing — live in `docs/agents/repo-handbook.md`. Read the matching section there
before editing anything bigger than a one-line fix.

## Non-negotiables

- Never hand-edit generated files. `docs/plugin-api.md`, `docs/plugin-manifest.schema.json`,
  `docs/plugin-api.d.ts` and `tools/stm_plugin_check.py` come from
  `python tools/gen_plugin_api_docs.py`; `static/js/utils/iconMap.js` from
  `python tools/gen_plugin_ui_icons.py`. Both generators take `--check`.
- `docs/` is excluded in `.gitignore` behind a narrow allowlist. Drafts, plans, audits and logs
  are local-only: never commit them, never assume they exist in a clean clone, and any test that
  reads one must `pytest.skip` instead of failing.
- An inaccessible directory is not a removed file. Removal decisions require complete
  enumeration via `walk_directory_strict`; on an enumeration error abort and roll back, and never
  activate a rebuilt index.
- UI and chat state are authoritative only in `core/data/local_state_repository.py` (ADR-0017),
  written at `synchronous=FULL`; never bulk-overwrite it from an unversioned dict.
- Every overlay registers in the `layers` table in `layout.js:_installBackGestureSupport`, or the
  Android back key exits the app instead of closing the overlay.
- Edit-state field drafts (`static/js/utils/fieldDraft.js`) keep exactly one tracking Proxy per
  raw object and unwrap `Alpine.raw` on read and write; nesting draft and reactive proxies grows
  the chain until the detail modal dies in `RangeError: Maximum call stack size exceeded`
  (guard: `tests/field_draft_proxy_layering_test.mjs`).
- Business content stays isolated: no `addJavascriptInterface`; the WebMessage listener verifies
  `sourceOrigin` and `isMainFrame`.
- User-facing strings stay Chinese, identifiers English.

## Commands

`pip install -r requirements.txt` · `python app.py` (`--debug` to reload) · `pytest tests/` ·
`pytest tests/test_st_auth_flow.py::test_st_http_client_web_performs_login` ·
`black app.py core tests` / `flake8 app.py core tests` / `mypy core` (optional, unenforced) ·
`python tools/benchmark_daily_operations.py` · from `android/`: `./gradlew
:app:testDebugUnitTest :app:assembleDebug` (Windows `gradlew.bat`) ·
`pytest tests/test_android_build_artifacts.py` (`-m slow` for the real Gradle signing chain).

## Editing

Focused diffs that match surrounding style. No new frameworks or tooling configs without a
stated reason. Behavior changes get a `tests/test_*.py` test. When a command or workflow becomes
repo-standard, update this file and the handbook.
