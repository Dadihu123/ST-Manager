"""插件脚手架：生成一个符合 manifest 规范的最小插件骨架。

用法（在仓库根目录执行）：

```powershell
python tools/new_plugin.py my-plugin --name "我的插件"
python tools/new_plugin.py my-plugin --out samples/plugins --no-backend
```

生成内容：

```
<out>/<plugin-id>/
├─ manifest.json
├─ README.md
├─ backend/__init__.py      # register(api)：注册 /ping 路由
└─ frontend/
   ├─ plugin.js             # activate(api)：注入面板并调用 /ping
   └─ plugin.css            # 作用域样式（.plugin-<id>…，满足 F11）
```

默认输出到 `data/plugins/`，即应用启动时会自动加载的目录；生成后需重启应用生效。
"""

import argparse
import json
import os
import re
import sys

PLUGIN_ID_PATTERN = re.compile(r'^[a-z][a-z0-9-]{1,63}$')
DEFAULT_OUT_DIR = os.path.join('data', 'plugins')

MANIFEST_TEMPLATE = {
    'id': '{plugin_id}',
    'name': '{name}',
    'version': '{version}',
    'api_version': 1,
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
    },
    'permissions': [],
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

{plugin_id} 插件（由 `tools/new_plugin.py` 生成）。

## 目录结构

- `backend/__init__.py`：`register(api)`，后端入口
- `frontend/plugin.js`：`activate(api)`，前端入口
- `manifest.json`：插件声明（id / 版本 / 权限 / 表单 schema）

## 开发提示

- 插件内部导入自己的子模块必须用相对导入（`from . import service`），不要写 `import backend`
- 样式必须以 `.plugin-{plugin_id}` 或 `[data-plugin="{plugin_id}"]` 作用域开头
- 需要长任务时用 `api.submit_job()`；密钥用 `api.set_secret()`（不要写进 manifest）
- 修改后端代码后重启应用生效
"""

BACKEND_TEMPLATE = '''\
"""<{plugin_id}> 后端入口。"""

from flask import jsonify


def register(api):
    """插件入口（manifest.backend.register 指向本函数）。"""

    @api.route('/ping', ['GET'])
    def ping():
        return jsonify({
            'success': True,
            'plugin': api.plugin_id,
            'greeting': api.get_config().get('greeting', ''),
        })

    api.log('info', '{plugin_id} 已注册')
'''

FRONTEND_TEMPLATE = '''\
/**
 * <{plugin_id}> 前端入口。
 *
 * 契约：导出 `activate(api)`，可选导出 `deactivate(api)`。
 */

export async function activate(api) {
  const root = api.createRoot("div");
  root.classList.add("plugin-{plugin_id}-panel");

  const title = document.createElement("h4");
  title.className = "plugin-{plugin_id}-title";
  title.textContent = api.manifest.name || "{plugin_id}";

  const button = document.createElement("button");
  button.type = "button";
  button.className = "plugin-{plugin_id}-button";
  button.textContent = "ping 后端";
  button.dataset.marqueeIgnore = "true";

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

  root.append(title, button, output);

  return () => {
    root.remove();
  };
}
'''

CSS_TEMPLATE = '''\
/* <{plugin_id}> 样式。F11：所有选择器必须以 .plugin-{plugin_id} 作用域开头。 */

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
}
'''


def validate_plugin_id(plugin_id: str) -> str:
    """校验插件 id（与 manifest 规则一致：小写、连字符、不以数字开头）。"""
    value = str(plugin_id or '').strip()
    if not PLUGIN_ID_PATTERN.match(value):
        raise ValueError(
            f'插件 id 非法: {plugin_id!r}（要求 ^[a-z][a-z0-9-]{{1,63}}$）'
        )
    return value


def _render(template: str, plugin_id: str, name: str = '') -> str:
    """模板变量替换。

    用 replace 而不是 `str.format`：模板里含 JSON / JS 花括号（`{ ... }`、`${x}`），
    format 会把它们当成占位符而报错。
    """
    return template.replace('{plugin_id}', plugin_id).replace('{name}', name)


def _write_text(path: str, content: str) -> None:
    with open(path, 'w', encoding='utf-8') as handle:
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

    manifest = json.loads(json.dumps(MANIFEST_TEMPLATE))
    manifest['id'] = plugin_id
    manifest['name'] = display_name
    manifest['version'] = version
    if not with_backend:
        manifest['backend'] = {}
    if not with_frontend:
        manifest['frontend'] = {}

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

    return target_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description='生成一个符合 ST-Manager 插件规范的骨架',
    )
    parser.add_argument('plugin_id', help='插件 id（小写，连字符，如 my-plugin）')
    parser.add_argument('--name', default='', help='插件显示名（默认与 id 相同）')
    parser.add_argument('--version', default='0.1.0', help='初始版本（语义化版本）')
    parser.add_argument('--out', default=DEFAULT_OUT_DIR, help=f'输出目录（默认 {DEFAULT_OUT_DIR}）')
    parser.add_argument('--no-backend', action='store_true', help='不生成 backend/（纯前端插件）')
    parser.add_argument('--no-frontend', action='store_true', help='不生成 frontend/（纯后端插件）')
    parser.add_argument('--force', action='store_true', help='目标目录已存在时覆盖')
    return parser


def main(argv=None) -> int:
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
    return 0


if __name__ == '__main__':
    sys.exit(main())
