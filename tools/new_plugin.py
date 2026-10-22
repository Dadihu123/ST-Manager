"""插件脚手架：生成一个符合契约 v3 的最小插件骨架。

用法（在仓库根目录执行）：

```powershell
python tools/new_plugin.py my-plugin --name "我的插件"
python tools/new_plugin.py my-plugin --out samples/plugins --no-backend
```

生成内容：

```
<out>/<plugin-id>/
├─ manifest.json                    # 契约 v3：contributions + capabilities
├─ README.md
├─ backend/__init__.py              # register(api)：注册 /ping 路由（可关）
└─ frontend/
   ├─ plugin.js                     # activate(api)：登记 surface + 事件
   ├─ plugin.css                    # 作用域样式（.plugin-<id>…）
   ├─ commands/ping.js              # 命令处理器（contributions.commands[]）
   └─ slots/settingsSection.js      # 插槽渲染器（contributions.slots[]）
```

默认输出到 `data/plugins/`，即应用启动时会自动加载的目录；生成后需重启应用生效。
生成后建议立即跑严格自检：

```powershell
python tools/stm_plugin_check.py data/plugins/my-plugin
```
"""

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 插件 id 规则与 manifest 版本号来自契约单一事实源，避免脚手架与宿主漂移。
from core.plugins import contract

DEFAULT_OUT_DIR = os.path.join('data', 'plugins')

MANIFEST_TEMPLATE = {
    'manifest_version': contract.MANIFEST_VERSION,
    'id': '{plugin_id}',
    'name': '{name}',
    'version': '{version}',
    'api_version': contract.API_VERSION,
    'author': '',
    'description': '',
    'license': 'MIT',
    'backend': {
        'entry': 'backend',
        'register': 'register',
        'jobs': [],
        'hooks': [],
    },
    'frontend': {
        'entry': 'frontend/plugin.js',
        'styles': ['frontend/plugin.css'],
        'render_mode': contract.DEFAULT_RENDER_MODE,
        'contributions': {
            'menus': [
                {
                    'id': 'open-settings',
                    'placement': 'settings.nav',
                    'type': 'item',
                    'label': '{name}',
                    'icon': 'settings',
                    'action': {'type': 'surface', 'id': 'settings'},
                },
                {
                    'id': 'ping',
                    'placement': 'commandPalette',
                    'type': 'item',
                    'label': '{plugin_id}：检查后端',
                    'icon': 'wand',
                    'action': {'type': 'command', 'id': 'ping'},
                },
            ],
            'slots': [
                {
                    'id': 'settings-inline',
                    'slot': 'settings.section',
                    'title': '{name}',
                    'order': 50,
                    'module': 'frontend/slots/settingsSection.js',
                    'export': 'mountSettingsSection',
                },
            ],
            'commands': [
                {
                    'id': 'ping',
                    'title': '{plugin_id}：检查后端',
                    'description': '调用插件后端 /ping 并弹出结果',
                    'icon': 'wand',
                    'shortcut': 'Ctrl+Alt+P',
                    'module': 'frontend/commands/ping.js',
                    'export': 'ping',
                },
            ],
        },
    },
    'capabilities': [],
    'config_schema': {
        'type': 'object',
        'properties': {
            'greeting': {
                'type': 'string',
                'title': '问候语',
                'default': '你好',
            },
        },
    },
    'secret_schema': {
        'type': 'object',
        'properties': {
            'api_key': {
                'type': 'string',
                'title': 'API Key',
                'secret': True,
            },
        },
    },
}

README_TEMPLATE = """# {name}

{plugin_id} 插件（由 `tools/new_plugin.py` 生成，契约 v3）。

## 目录结构

- `manifest.json`：插件声明（`contributions` 菜单 / 插槽 / 命令、能力位、表单 schema）
- `backend/__init__.py`：`register(api)` 后端入口
- `frontend/plugin.js`：`activate(api)` 前端入口（surface 登记、事件）
- `frontend/commands/ping.js`：命令处理器
- `frontend/slots/settingsSection.js`：插槽渲染器

## 契约要点（v3）

- **结构静态声明**：菜单树 / 插槽 / 命令只能写在 `frontend.contributions` 里；
  运行期只能 `api.contributions.update(id, patch)` / `remove(id)`，不能新增结构。
- **能力位是披露**：用到的读写能力写进 `capabilities`（如 `cards.read`），
  宿主在插件管理器展示给用户，不做运行期鉴权。
- **自绘要登记**：`api.createRoot({ portal: true })` 之外的浮层用
  `api.overlays.register()` 登记，才能参与 ESC / 焦点协调与 kill switch。
- **样式必须作用域化**：选择器以 `.plugin-{plugin_id}` 或
  `[data-plugin="{plugin_id}"]` 开头；想改全局样式必须用 `frontend.global_styles`
  并声明 `ui.global_styles` 能力位。
- 清单 schema：`docs/plugin-manifest.schema.json`；前端类型：`docs/plugin-api.d.ts`；
  完整参考：`docs/plugin-api.md`。

## 开发提示

- 插件内部导入自己的子模块必须用相对导入（`from . import service`），不要写 `import backend`
- 能力按**域命名空间**组织：`api.cards.*` / `api.tags.*` / `api.worldbook.*` /
  `api.jobs.*` / `api.private.*` / `api.backups.*` / `api.index.*` 等
- 需要长任务时用 `api.jobs.submit()`；密钥用 `api.secrets.set()`（不要写进 manifest）
- 修改后端代码后重启应用生效

## 自检

```powershell
python tools/stm_plugin_check.py <插件目录>          # 严格模式（CI 用）
python tools/stm_plugin_check.py <插件目录> --json   # 机器可读
```
"""

BACKEND_TEMPLATE = '''\
"""<{plugin_id}> 后端入口（契约 v3）。"""

from flask import jsonify


def register(api):
    """插件入口（manifest.backend.register 指向本函数）。"""

    @api.http.route('/ping', ['GET'])
    def ping():
        return jsonify({
            'success': True,
            'plugin': api.plugin_id,
            'greeting': api.config.get().get('greeting', ''),
        })

    api.log.info('{plugin_id} 已注册')
'''

FRONTEND_TEMPLATE = '''\
/**
 * <{plugin_id}> 前端入口（契约 v3）。
 *
 * 结构声明在 manifest.json 的 `frontend.contributions`（菜单 / 插槽 / 命令）；
 * 本文件只导出 `activate(api)`，负责运行期需要代码的部分（surface 登记、事件）。
 * 插槽渲染器与命令处理器是独立模块：frontend/slots/、frontend/commands/。
 */

export async function activate(api) {
  // settings.nav 的菜单项 action 指向这个 surface；容器与生命周期由宿主负责。
  api.surfaces.register("settings", {
    type: "modal",
    size: "md",
    title: api.manifest.name || "{plugin_id}",
    mount(container) {
      container.classList.add("plugin-{plugin_id}-panel");

      const title = document.createElement("h4");
      title.className = "plugin-{plugin_id}-title";
      title.textContent = "设置";

      const button = document.createElement("button");
      button.type = "button";
      button.className = "plugin-{plugin_id}-button";
      button.textContent = "调用后端 /ping";

      const output = document.createElement("pre");
      output.className = "plugin-{plugin_id}-output";

      button.addEventListener("click", async () => {
        const data = await api.api("/ping");
        if (!data.success) {
          api.toast(data.msg || "请求失败");
          return;
        }
        api.toast(`pong · ${data.plugin}`);
        output.textContent = JSON.stringify(data, null, 2);
      });

      container.append(title, button, output);
      return () => container.replaceChildren();
    },
  });

  const offConfig = api.onConfigChange((config) => {
    console.log("[{plugin_id}] 配置已更新", config);
  });

  return () => offConfig();
}
'''

COMMAND_TEMPLATE = '''\
/**
 * 命令处理器（manifest.frontend.contributions.commands[] 指向这里）。
 *
 * 导出名必须与 manifest 的 `export` 一致；ctx 形状见 docs/plugin-api.d.ts。
 */

export async function ping(ctx) {
  const data = await ctx.api.api("/ping");
  if (!data.success) {
    ctx.api.toast(data.msg || "请求失败");
    return;
  }
  ctx.api.toast(`pong · ${data.plugin}（来自 ${ctx.trigger.kind}）`);
}
'''

SLOT_TEMPLATE = '''\
/**
 * 插槽渲染器（manifest.frontend.contributions.slots[] 指向这里）。
 *
 * 宿主传入容器与 ctx，返回可选清理函数；渲染器抛错只让该插槽降级，
 * 不影响其他插件。
 */

export function mountSettingsSection(container, ctx) {
  container.classList.add("plugin-{plugin_id}-slot");

  const line = document.createElement("p");
  line.className = "plugin-{plugin_id}-title";
  line.textContent = "{name}（当前模式：${ctx.mode}）";

  container.replaceChildren(line);

  return () => {
    container.replaceChildren();
  };
}
'''

CSS_TEMPLATE = '''\
/* <{plugin_id}> 样式。
 *
 * 作用域规则：所有选择器必须以 .plugin-{plugin_id} 或
 * [data-plugin="{plugin_id}"] 开头，否则安装失败（前端自动注入的插槽容器
 * 与 root 都带 data-plugin）。想改全局样式走 frontend.global_styles + 能力位。
 */

.plugin-{plugin_id}-panel {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  margin: 0.75rem;
  padding: 0.75rem;
  border: 1px solid var(--border-default);
  border-radius: 0.5rem;
  background: var(--surface-container);
}

.plugin-{plugin_id}-title {
  margin: 0;
  font-size: 0.9rem;
  color: var(--content-primary);
}

.plugin-{plugin_id}-button {
  align-self: flex-start;
  padding: 0.3rem 0.75rem;
  border: 1px solid var(--action-border, var(--border-default));
  border-radius: 0.4rem;
  background: var(--action-surface);
  color: var(--action-text, var(--content-primary));
  font-size: 0.8rem;
  cursor: pointer;
}

.plugin-{plugin_id}-output {
  margin: 0;
  font-size: 0.72rem;
  color: var(--content-muted);
  white-space: pre-wrap;
}

.plugin-{plugin_id}-slot {
  margin: 0;
  color: var(--content-secondary);
}
'''


def validate_plugin_id(plugin_id: str) -> str:
    """校验插件 id（规则来自 `core/plugins/contract.py`）。"""
    value = str(plugin_id or '').strip()
    if not contract.PLUGIN_ID_PATTERN.match(value):
        raise ValueError(
            f'插件 id 非法: {plugin_id!r}（要求 {contract.PLUGIN_ID_PATTERN.pattern}）'
        )
    return value


def _render(template: str, plugin_id: str, name: str = '') -> str:
    """模板变量替换。

    用 replace 而不是 `str.format`：模板里含 JSON / JS 花括号（`{ ... }`、`${x}`），
    format 会把它们当成占位符而报错。
    """
    return template.replace('{plugin_id}', plugin_id).replace('{name}', name)


def _render_manifest(plugin_id: str, name: str, version: str) -> str:
    payload = json.loads(json.dumps(MANIFEST_TEMPLATE))
    payload['id'] = plugin_id
    payload['version'] = version
    payload['name'] = name
    text = json.dumps(payload, ensure_ascii=False, indent=2) + '\n'
    return _render(text, plugin_id, name)


def _write_text(path: str, content: str) -> None:
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(content)


def scaffold_plugin(
    plugin_id: str,
    *,
    name: str = '',
    version: str = '0.1.0',
    out_dir: str = DEFAULT_OUT_DIR,
    with_backend: bool = True,
    with_frontend: bool = True,
    force: bool = False,
) -> str:
    """生成插件骨架，返回插件目录的绝对路径。"""
    plugin_id = validate_plugin_id(plugin_id)
    display_name = str(name or plugin_id).strip() or plugin_id

    target_dir = os.path.abspath(os.path.join(str(out_dir), plugin_id))
    if os.path.exists(target_dir) and not force:
        raise FileExistsError(f'目标目录已存在: {target_dir}（如需覆盖请加 --force）')

    os.makedirs(target_dir, exist_ok=True)

    manifest_text = _render_manifest(plugin_id, display_name, version)

    # 纯后端 / 纯前端插件：整体删掉另一端声明（空对象会被宿主拒绝）。
    manifest = json.loads(manifest_text)
    if not with_backend:
        manifest.pop('backend', None)
    if not with_frontend:
        manifest.pop('frontend', None)

    _write_text(
        os.path.join(target_dir, 'manifest.json'),
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n',
    )
    _write_text(
        os.path.join(target_dir, 'README.md'),
        _render(README_TEMPLATE, plugin_id, display_name),
    )

    if with_backend:
        os.makedirs(os.path.join(target_dir, 'backend'), exist_ok=True)
        _write_text(
            os.path.join(target_dir, 'backend', '__init__.py'),
            _render(BACKEND_TEMPLATE, plugin_id),
        )

    if with_frontend:
        os.makedirs(os.path.join(target_dir, 'frontend'), exist_ok=True)
        _write_text(
            os.path.join(target_dir, 'frontend', 'plugin.js'),
            _render(FRONTEND_TEMPLATE, plugin_id),
        )
        _write_text(
            os.path.join(target_dir, 'frontend', 'plugin.css'),
            _render(CSS_TEMPLATE, plugin_id),
        )
        commands_dir = os.path.join(target_dir, 'frontend', 'commands')
        os.makedirs(commands_dir, exist_ok=True)
        _write_text(
            os.path.join(commands_dir, 'ping.js'),
            _render(COMMAND_TEMPLATE, plugin_id),
        )
        slots_dir = os.path.join(target_dir, 'frontend', 'slots')
        os.makedirs(slots_dir, exist_ok=True)
        _write_text(
            os.path.join(slots_dir, 'settingsSection.js'),
            _render(SLOT_TEMPLATE, plugin_id, display_name),
        )

    return target_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='生成一个符合 ST-Manager 插件契约 v3 的骨架',
    )
    parser.add_argument('plugin_id', help='插件 id（小写，连字符，如 my-plugin）')
    parser.add_argument('--name', default='', help='插件显示名（默认与 id 相同）')
    parser.add_argument('--version', default='0.1.0', help='初始版本（语义化版本）')
    parser.add_argument('--out', default=DEFAULT_OUT_DIR, help=f'输出目录（默认 {DEFAULT_OUT_DIR}）')
    parser.add_argument('--no-backend', action='store_true', help='不生成 backend/（纯前端插件）')
    parser.add_argument('--no-frontend', action='store_true', help='不生成 frontend/（纯后端插件）')
    parser.add_argument('--force', action='store_true', help='目标目录已存在时覆盖')
    return parser


def _configure_stdout() -> None:
    """Windows 控制台默认 GBK，直接打印非 ASCII 会抛 UnicodeEncodeError。"""
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, OSError, ValueError):
        pass


def main(argv=None) -> int:
    _configure_stdout()
    args = build_parser().parse_args(argv)

    if args.no_backend and args.no_frontend:
        print('❌ 不能同时禁用 backend 与 frontend（至少保留一个）')
        return 2

    try:
        target_dir = scaffold_plugin(
            args.plugin_id,
            name=args.name,
            version=args.version,
            out_dir=args.out,
            with_backend=not args.no_backend,
            with_frontend=not args.no_frontend,
            force=args.force,
        )
    except (ValueError, FileExistsError) as exc:
        print(f'❌ {exc}')
        return 1

    print(f'✅ 已生成插件骨架: {target_dir}')
    for current_root, _dirs, files in os.walk(target_dir):
        for name in sorted(files):
            print('   -', os.path.relpath(os.path.join(current_root, name), target_dir).replace('\\', '/'))
    print('提示: 生成到 data/plugins/ 的插件需要重启应用后生效。')
    print(f'自检: python tools/stm_plugin_check.py "{target_dir}"')
    return 0


if __name__ == '__main__':
    sys.exit(main())
