# SVG 图标系统

## 1. 整理原则

项目的 SVG 资源按实际使用范围拆分为四个精灵：

- `static/icons/ui.svg`：跨页面复用的操作、状态、设置和系统图标。
- `static/icons/detail.svg`：角色卡详情、资源详情和阅读器专用图标。
- `static/icons/sidebar.svg`：侧边栏导航、分类和侧边栏专用入口。
- `static/icons/preset.svg`：预设字段、提示词 marker 和预设空状态图标。

论坛预览的 SVG 由 CSS mask 直接使用，继续保留在
`static/icons/forum-preview/`；`loading-animation.svg` 是独立加载动效，不属于精灵。
图标 id 使用 `icon-` 前缀和英文 kebab-case，并优先描述图形含义，而不是所属页面。

## 2. 当前结构

| 文件 | 用途 | symbol 数量 |
| --- | --- | ---: |
| `static/icons/ui.svg` | 通用操作、状态、设置和系统工具 | 138 |
| `static/icons/detail.svg` | 详情、阅读器和资源详情 | 26 |
| `static/icons/sidebar.svg` | 侧边栏导航与分类 | 10 |
| `static/icons/preset.svg` | 预设字段与 marker | 13 |
| **精灵合计** |  | **187** |
| `static/icons/forum-preview/*.svg` | CSS mask | 6 个独立文件 |

设置页的缩略图清理动作使用 `ui.svg#icon-broom`。图标来源为
`tmp/其他/扫帚.svg`，路径颜色改为 `currentColor`，可以跟随主题和按钮状态变化。

## 3. 通用化和兼容映射

以下原本位于业务精灵中的通用图标已经移动到 `ui.svg`：

- `icon-version`、`icon-info`、`icon-user`、`icon-layers`、`icon-menu-category`
- 详情和资源列表共用的 `icon-note`、`icon-tags`、`icon-locate`、`icon-overwrite`、
  `icon-edit-mode`、`icon-editor`、`icon-quick-reply`、`icon-link-source`、
  `icon-chat-bubble`、`icon-fullscreen`、`icon-persona`、`icon-clock`、
  `icon-book-open`、`icon-file-name`、`icon-preset`、`icon-book-read`、
  `icon-expand`、`icon-regex`、`icon-script-file`、`icon-chat-empty`
- 跨页面复用的 `icon-character-cards`、`icon-paint-brush`

模板宏 `templates/components/icon.html` 保留旧调用名的兼容映射，避免影响页面逻辑：

- `icon('plus')` 映射到通用的 `icon-plus-square`
- 详情宏的通用图标从 `ui.svg` 读取
- `sidebar_icon('layers' | 'menu-category' | 'character-cards' | 'paint-brush')` 从
  `ui.svg` 读取

设置资源入口的动态图标也已改为通用语义命名，并统一从 `ui.svg` 读取：
`character-cards`、`chat-bubble`、`book-open`、`preset`、`regex`、`quick-reply`、
`script-file`。预设 marker 由 `promptMarkerVisuals.js` 动态拼接 id，因此仍保留在
`preset.svg`。

## 4. 删除的无效定义

经过模板、JavaScript、CSS、后端和测试契约扫描，以下没有有效引用的 symbol 已删除：

- `sidebar.svg`：`icon-cards-stack`、`icon-chat-bubbles`、`icon-preset-stack`、
  `icon-regex-file`、`icon-script-brackets`、`icon-reply-bolt`
- `ui.svg`：`icon-palette`

动态 marker、美化资源图标和 CSS mask 使用的论坛预览文件不在删除范围内。原有仍在
使用但命名偏业务化的图标则迁移或改为通用语义名称，而不是删除。

## 5. 使用约定

新增跨页面使用的图标应放入 `ui.svg`，并使用图形语义命名。只有详情页、侧边栏或
预设字段确实独占的图标，才放入对应专用精灵。模板中优先调用现有宏：

```jinja
{% from "components/icon.html" import icon, detail_icon, sidebar_icon %}
{{ icon('broom', 'ui-icon--sm') }}
{{ detail_icon('image') }}
{{ sidebar_icon('folder-open') }}
```

不要在模板或 CSS 中复制 SVG 路径，也不要为同一图形创建多个业务前缀 id。

## 6. 校验

修改精灵后至少执行：

```powershell
python -c "import xml.etree.ElementTree as ET; [ET.parse(p) for p in ['static/icons/ui.svg', 'static/icons/detail.svg', 'static/icons/sidebar.svg', 'static/icons/preset.svg']]"
pytest -q tests/test_preset_list_icons.py tests/test_settings_icon_templates.py
```

还应使用 `rg` 检查模板宏、`<use>`、CSS mask 和动态 icon id，确认没有缺失引用或未使用定义。
