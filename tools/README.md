# Forum update probe

`forum_update_probe.py` is a local diagnostic tool for comparing the two
currently supported ways to inspect a Discord-based 类脑 post. It does not
change cards or application settings.

Run it from the repository root:

```powershell
python tools/forum_update_probe.py `
  --url "https://discord.com/channels/<guild-id>/<thread-id>"
```

The script asks for a Discord Cookie and a 类脑搜索 Cookie through hidden
prompts. To avoid entering them interactively, set temporary environment
variables instead:

```powershell
$env:ST_PROBE_DISCORD_COOKIE = "..."
$env:ST_PROBE_SHIMMERDAY_COOKIE = "..."
python tools/forum_update_probe.py `
  --url "https://discord.com/channels/<guild-id>/<thread-id>" `
  --no-prompt
Remove-Item Env:ST_PROBE_DISCORD_COOKIE,Env:ST_PROBE_SHIMMERDAY_COOKIE
```

Use `--discord-auth token` and `ST_PROBE_DISCORD_TOKEN` when the Discord path
is configured with a Bot/User token. Multiple `--url` arguments or
`--url-file` are supported. The default output directory is
`artifacts/forum_update_probe/`; each run creates a timestamped subdirectory.

The generated `manifest.json` records request order, status, elapsed time,
response size, selected cache headers, and candidate title/timestamp fields.
Request authentication headers are never written, and response fields whose
names look credential-related are redacted.

# Plugin scaffold

`new_plugin.py` generates a minimal **contract v3** plugin skeleton whose
manifest and CSS already satisfy the strict checks:

```powershell
python tools/new_plugin.py my-plugin --name "我的插件"
python tools/new_plugin.py my-plugin --out samples/plugins --no-backend
```

It writes `manifest.json` (v3: `frontend.contributions` with a menu tree,
a slot and a command; `capabilities`; `render_mode`), `README.md`,
`backend/__init__.py` (registers a `/ping` route), and
`frontend/plugin.js` + `frontend/plugin.css` + `frontend/commands/ping.js` +
`frontend/slots/settingsSection.js` (scoped with `.plugin-<id>`). The output
passes `PluginManifest.load()`, `scan_css_scope()` and the full
`stm_plugin_check.py` strict mode, so it can be loaded by `registry.load_all()`
right away. Flags: `--out` (default `data/plugins/`), `--version`,
`--no-backend`, `--no-frontend`, `--force`. Restart the app after generating a
plugin into `data/plugins/`.

# Plugin contract artifacts

`core/plugins/contract.py` is the single source of truth for the manifest
contract (version numbers, enums, limits, regexes and validation). Everything
below is generated from it — never hand-edit these files:

| Artifact | Purpose |
|---|---|
| `docs/plugin-api.md` | API reference (backend `PluginAPI` signatures/docstrings + `buildApi()` members + v3 contribution/overlay prose) |
| `docs/plugin-manifest.schema.json` | JSON Schema for `manifest` v3 (editor completion, third-party validation, CI) |
| `docs/plugin-api.d.ts` | TypeScript types for the frontend plugin API (`activate(api: PluginApiV3)`) |
| `tools/stm_plugin_check.py` | Standalone strict checker; embeds `contract.py` + host facts in marker regions so it can be copied into any plugin repo |

```powershell
python tools/gen_plugin_api_docs.py           # regenerate all four artifacts
python tools/gen_plugin_api_docs.py --check   # verify only (non-zero on drift)
```

The checker runs 9 checks and exits non-zero on errors:

```powershell
python tools/stm_plugin_check.py path/to/plugin          # human-readable report
python tools/stm_plugin_check.py path/to/plugin --json   # machine-readable JSON
```

`tests/test_plugin_api_docs.py`, `tests/test_plugin_manifest_schema.py` and
`tests/test_plugin_stm_plugin_check.py` assert that every artifact on disk
equals a fresh render and that the checker rejects the documented negative
cases, so rerun the generator whenever the plugin contract changes.

# Layering verification

Two Playwright scripts check the parts of the plugin host that only a real
browser can prove. Both need the app running (`python app.py`) and Playwright
installed as a local dev tool (`pip install playwright` +
`playwright install chromium`); neither touches user data.

```powershell
python tools/verify_plugin_surface_layering.py   # surfaces vs. host modals
python tools/verify_primitive_dialog_layering.py # api.ui.confirm vs. plugin surfaces
```

`verify_plugin_surface_layering.py` mounts probe surfaces over the settings
modal and asserts that `modal` / `panel` / `sheet` sit above it while `page`
stays below.

`verify_primitive_dialog_layering.py` replays the AI assistant's outbound
consent prompt by intercepting `/api/plugins/stm-ai-assistant/status` and
forcing `outbound_acknowledged: false`, so the real ack flag is never flipped.
It asserts that the confirm overlay carries `--z-modal-alert` (3600, above
plugin surfaces at `--z-modal-popover` 3400), that a real click lands on the
确定 button and triggers `POST /outbound/ack`, and that Escape closes the
dialog without also closing the plugin panel behind it.