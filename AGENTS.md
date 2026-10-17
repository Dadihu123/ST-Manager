# AGENTS.md

## Project Snapshot

- Stack: Python 3.10+, Flask, SQLite, Pillow, requests, watchdog
- Entry point: `app.py`
- App factory: `core/__init__.py:create_app`
- Background startup: `core/__init__.py:init_services`
- Main code areas: `core/api/v1/`, `core/services/`, `core/data/`, `core/utils/`, `tests/`

## Rules Files Present

- Existing agent guide found at repo root: `AGENTS.md`
- No `.cursorrules` file found
- No `.cursor/rules/` directory found
- No `.github/copilot-instructions.md` file found

If any of those files are added later, treat them as additional constraints.

## Environment And Setup

- Recommended Python: 3.10+
- Install runtime dependencies:

```bash
pip install -r requirements.txt
```

- Test tooling is not listed in `requirements.txt`; install it when needed:

```bash
pip install pytest
```

- Optional local dev tools:

```bash
pip install black flake8 mypy
```

## Run Commands

- Start the app normally:

```bash
python app.py
```

- Start in debug mode with Flask reloader:

```bash
python app.py --debug
```

- Equivalent debug env form:

```bash
FLASK_DEBUG=1 python app.py
```

- Docker build/run paths also exist:

```bash
docker-compose up -d
docker-compose up --build
```

## Test Commands

Pytest tests exist in `tests/`; do not assume the repo is untested.

- Run the full suite:

```bash
pytest tests/
```

- Run a single test file:

```bash
pytest tests/test_st_auth_flow.py
```

- Run one specific test function:

```bash
pytest tests/test_st_auth_flow.py::test_st_http_client_web_performs_login
```

- Run a single test with verbose output:

```bash
pytest -v tests/test_chat_list_filters.py::test_chat_list_fav_filter_included
```

## Generated Artifacts

Two files in this repo are **generated**; never hand-edit them, and re-run their
generator after touching the corresponding source. CI-style tests assert that the
on-disk file matches the generator output.

| Generated file | Source of truth | Regenerate | Verify |
|---|---|---|---|
| `docs/plugin-api.md` | `core/plugins/api.py` (`PluginAPI`) + `core/plugins/domains/*` + `static/js/pluginHost.js` (`buildApi()`) | `python tools/gen_plugin_api_docs.py` | `python tools/gen_plugin_api_docs.py --check` |
| `static/js/utils/iconMap.js` | `static/icons/*.svg` (`id="icon-*"`) | `python tools/gen_plugin_ui_icons.py` | `python tools/gen_plugin_ui_icons.py --check` |

`PluginAPI` is a **domain-namespace facade**: its class body only holds `on` /
`emit` / `estimate_tokens` (plus the internal `finalize` / `bind_job`), and every
other capability hangs off domain objects (`api.cards.*`, `api.tags.*`,
`api.worldbook.*`, `api.backups.*`, `api.jobs.*`, `api.private.*`, …) created in
`__init__`. See `docs/2026-10-12-plugin-api-expansion.md` for the full design and
`docs/plugin-api.md` for the generated reference.

Registration rules for the API docs generator:

- a new **top-level** member of `PluginAPI` → `BACKEND_GROUPS`;
- a new **domain method** → `BACKEND_DOMAINS` (`('domain', '说明', 'Stable', ['method', …])`);
- a new **domain** → add a row to `DOMAIN_CLASSES` in `core/plugins/domains/__init__.py`,
  then register it in `BACKEND_DOMAINS` **and** `BACKEND_ATTRIBUTES`;
- an internal/non-contract method → `BACKEND_INTERNAL`.

Three hard constraints that fail tests immediately if violated:

1. **Domains must be instance attributes, never `@property`.** The generator
   collects public methods through two independent paths (AST parse of the class
   body vs. runtime `inspect.getmembers`), and `@property` makes them disagree —
   `test_ast_and_introspection_agree_on_public_methods` fails.
2. **Domain methods must not go into `BACKEND_GROUPS`** (`test_grouped_methods_actually_exist`
   checks `hasattr(PluginAPI, name)`, which is false for domain methods), and
   conversely must not collide with top-level names.
3. **`DOMAIN_CLASSES` is the single source of truth for domain names.**
   `PluginAPI.__init__` builds domains from it, and the generator/tests enumerate
   the same table, so a domain missing from it fails
   `test_domain_classes_match_backend_domains_registry`.

A member nested under an existing namespace (`host.onState`, `entries.*`,
`surfaces.*`) is documented **inside that namespace's row** — do not add it as a
separate top-level key, or `test_frontend_declared_members_are_exposed_by_host`
fails (it checks the declared set against `buildApi()`'s literal top-level keys).

Consistency mechanisms (card locks, `suppress_fs_events`, cache/DB/index
synchronisation, path-boundary checks) live **once** in `core/plugins/api.py` as
underscore-prefixed members, and domains reach them through
`core/plugins/domains/_base.py`. Never re-implement them in a domain — that is how
"card list doesn't refresh after a plugin moves a card" bugs get introduced.

Prose sections of `docs/plugin-api.md` that are not derived from code (for example
the `前端 window 事件（Provisional）` section) live as constants in
`tools/gen_plugin_api_docs.py` (see `WINDOW_EVENTS_SECTION`) and are appended in
`render()`. **Editing `docs/plugin-api.md` by hand is always lost** on the next
regeneration, including those prose sections.

Adding a new icon to a sprite requires re-running `tools/gen_plugin_ui_icons.py`,
or `tests/test_plugin_icons.py` fails.

## Lint And Type Check

No repo-enforced linter, formatter, or type checker config files were found, so keep edits minimal.

- Safe optional formatting target:

```bash
black app.py core tests
```

- Safe optional lint target:

```bash
flake8 app.py core tests
```

- Safe optional type-check target:

```bash
mypy core
```

## Architecture Conventions

- Use `create_app()` as the Flask app factory
- Register HTTP endpoints as Blueprints under `core/api/v1/`
- Keep business logic in `core/services/`, not inside route handlers
- Keep reusable pure helpers in `core/utils/`
- Use `core/context.py` singleton `ctx` for shared runtime state
- Use `core/data/db_session.py` for SQLite connection patterns and retry helpers
- Background workers should be daemon threads
- File-system-triggered rescans should go through scan/cache services, not ad hoc logic
- Chat module styles live in `static/css/modules/view-chats.css` (entry) with partials under `static/css/modules/view-chats/` (`tokens.css`, `grid.css`, `reader-shell.css`, etc.)
- Beautify module styles live in `static/css/modules/view-beautify.css` (flat tokens aligned with chat module)
- Hover hints are global: keep writing `title="..."`, and `static/js/utils/tooltip.js` migrates it to `data-tooltip` at hover time so `static/css/modules/tooltip.css` can render the host tooltip. Any CSS selector or read-back that keys off `title` text must also match `data-tooltip`; `data-tooltip-placement` / `data-tooltip-disabled` are the opt-in extras

## Build And Packaging

- Container build file: `Dockerfile`
- Compose file: `docker-compose.yaml`
- Docker image runs `python app.py` and exposes port `5000`
- Data/config are expected to be mounted into `/app/data` and `/app/config.json`
- Desktop packaging workflow: `.github/workflows/build-desktop.yaml`
- Desktop builds run on pushes to `main`, `v*` tags, or manual dispatch, and upload Windows, macOS arm64, and macOS x86_64 artifacts

## Imports

- Order imports: standard library, third-party, local modules
- Separate import groups with one blank line
- Prefer absolute imports from `core`, for example `from core.config import load_config`
- Avoid circular imports; if necessary, use narrow local imports inside functions
- Do not leave unused imports behind

## Naming

- Classes: `PascalCase`
- Functions and methods: `snake_case`
- Local variables: `snake_case`
- Constants: `UPPER_CASE`
- Private helpers: leading underscore, such as `_resolve_safe_path`
- Blueprint objects are typically named `bp`

## Formatting

- Use 4 spaces, never tabs
- Prefer lines under roughly 100-120 characters
- Keep top-level functions separated by two blank lines
- Keep method definitions separated by one blank line when helpful
- Prefer single quotes in Python code unless double quotes improve readability or are required
- Do not reformat unrelated files just to match a formatter

## Types And Signatures

- Type hints are optional but welcome for new or heavily edited functions
- Add return types to service/helper functions when it improves clarity
- Use `typing` imports for complex structures if needed
- Do not add noisy annotations to trivial locals

## Docstrings And Comments

- Use concise triple-double-quoted docstrings for non-trivial public functions
- Keep user-facing text and many explanatory comments Chinese-friendly, matching the repo
- Keep technical identifiers and module names in English
- Add comments only where behavior is non-obvious; avoid narrating obvious code

## Error Handling And Logging

- Wrap file I/O, JSON parsing, network access, and subprocess calls in `try/except`
- Prefer specific exceptions when practical; avoid bare `except:`
- Log through `logger = logging.getLogger(__name__)`
- Use `logger.warning()` for recoverable issues and `logger.error()` for failures
- Return structured JSON errors from API routes via `jsonify()`
- Do not expose stack traces in API responses
- CLI/startup flows may still print clear status messages for the local user

## Database And State

- SQLite is used directly via `sqlite3`
- Use parameterized queries, never string-built SQL
- Reuse `execute_with_retry()` for lock-prone writes
- Use `with sqlite3.connect(...)` or the Flask `g` connection pattern
- Preserve WAL-related setup already used in `core/data/db_session.py`
- For shared mutable state, use locks/queues from `ctx`

## Paths, Files, And Data

- Build paths with `os.path.join()`
- Normalize stored relative paths with forward slashes using `.replace('\\', '/')`
- Check that paths stay inside allowed roots before reading/writing
- Respect dynamic config-driven folders from `core.config`
- Use `ensure_ascii=False` when writing JSON that may contain Chinese text
- Avoid destructive file operations unless the task explicitly requires them

## Testing Expectations For Changes

- Prefer adding or updating pytest tests in `tests/` for behavior changes
- Keep test filenames as `test_*.py`
- For Flask endpoints, small app fixtures using `Flask(__name__)` and blueprint registration are acceptable and already used in the repo
- When changing auth, config normalization, chat filters, parsers, or filesystem safety logic, run the most targeted relevant test file first

## Agent Editing Guidance

- Make focused changes that match surrounding style
- Preserve Chinese user-facing strings unless the task is explicitly to rewrite them
- Do not replace existing architectural patterns with new frameworks or abstractions without a strong reason
- Do not silently add new tooling configs unless requested
- If you introduce a new command or workflow, update this file when it becomes repo-standard
