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

`new_plugin.py` generates a minimal plugin skeleton that already satisfies the
manifest and CSS-scope contracts:

```powershell
python tools/new_plugin.py my-plugin --name "我的插件"
python tools/new_plugin.py my-plugin --out samples/plugins --no-backend
```

It writes `manifest.json`, `README.md`, `backend/__init__.py` (registering a
`/ping` route) and `frontend/plugin.js` + `frontend/plugin.css` (scoped with
`.plugin-<id>`). The output passes `PluginManifest.load()` and
`scan_css_scope()` unchanged, so it can be loaded by `registry.load_all()`
right away. Flags: `--out` (default `data/plugins/`), `--version`,
`--no-backend`, `--no-frontend`, `--force`. Restart the app after generating a
plugin into `data/plugins/`.
