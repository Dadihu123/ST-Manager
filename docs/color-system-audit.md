# ST Manager 颜色系统审计记录

## 审计范围

本次审计覆盖了应用运行时会触达的颜色来源，而不是只检查当前首页：

- `static/css/style.css` 及其导入的全部模块，包括侧边栏、卡片、聊天阅读器、世界信息、Beautify、详情、设置、工具、自动化、论坛预览和源更新监控。
- `static/css/color-system.css`、`static/css/tailwind.css`，以及模板中使用的内联 `style`、伪元素和动态 CSS 自定义属性。
- `templates/**/*.html` 的页面、组件、弹窗、表单、Toast、Tooltip、空状态、加载状态、错误状态、移动端布局和交互状态。
- `static/js/state.js`、组件、运行时 iframe/Shadow DOM、Beautify 预览、Markdown/HTML 渲染和动态 `style`/CSS 变量写入。
- `static/icons/**/*.svg` 以及模板内联 SVG 的 `fill`、`stroke` 和图标继承关系。
- `core/auth.py` 的独立登录页和 `core/data/ui_store.py` 的用户标签颜色持久化/规范化。

代码搜索同时覆盖十六进制、`rgb/rgba`、`hsl/hsla`、颜色名称、CSS 变量、渐变、阴影和运行时颜色拼接。当前应用 SVG 图标统一使用 `currentColor`；图片处理代码中的 RGB 白色是图像画布回退值，不属于 UI 颜色。

## 语义 Token

Token 定义集中在 [`static/css/modules/variables.css`](../static/css/modules/variables.css)，最终覆盖规则集中在 [`static/css/color-system.css`](../static/css/color-system.css)。业务模块不再直接依赖 Tailwind 调色板或散落的颜色字面量。

- 表面层级：`--surface-page`、`--surface-container`、`--surface-container-raised`、`--surface-container-hover`、`--surface-container-sunken`、`--surface-overlay`、`--surface-code`、`--surface-media`、`--surface-scrim`。
- 文字层级：`--content-primary`、`--content-secondary`、`--content-muted`、`--content-disabled`、`--content-on-accent`、`--content-on-status-solid`、`--content-on-decoration-solid`、`--content-on-dark`、`--content-on-light`、`--content-code`、`--content-quote`。
- 图标层级：`--icon-default`、`--icon-muted`、`--icon-interactive`、`--icon-on-accent`。
- 边界与状态：`--border-subtle`、`--border-default`、`--border-strong`、`--border-divider`、`--state-hover-surface`、`--state-active-surface`、`--state-selected-surface`、`--state-focus-ring`、`--state-focus-shadow`、`--state-disabled-surface`。
- 主题主色：`--accent-action`、`--accent-action-hover`、`--accent-action-active`、`--accent-text`、`--accent-soft`、`--accent-soft-strong`、`--accent-outline`。
- 语义状态：success、info、warning、danger、neutral 均提供 `*-text`、`*-solid`、`*-hover-solid`、`*-surface`、`*-border`；实心状态背景统一使用 `--content-on-status-solid`。
- 装饰与品牌：`--decoration-violet-*`、`--decoration-cyan-*`、`--decoration-rose-*`、`--decoration-amber-*`、`--brand-preset-*`；实心装饰背景统一使用 `--content-on-decoration-solid`。
- 表单、标签和层次：`--form-*`、`--tag-default-*`、`--tag-image-*`、`--shadow-*`、滚动条 Token，以及具名的 Sidebar Token。

旧 Token 名称暂时保留为兼容别名，方便未迁移的第三方预览和外部扩展继续工作；新业务样式应使用上述语义名称。

## 组件映射

侧边栏上半部导航作为视觉参考：页面/容器/导航容器使用逐级抬升的表面层级，普通导航文字和图标使用主/次级内容 Token，弱化图标使用 `--icon-muted`，Hover 使用 `--state-hover-surface`，选中项使用 `--state-selected-surface` 加主题边界和主题文字。下方用户标签区域只复用这套语义规则，不复制上半部的视觉结构。

- 卡片、列表和表格使用 page/container/raised 三层背景，分割线使用 `--border-divider`，收藏、重要操作和选中态使用独立的主题或语义状态色。
- 聊天列表、阅读器、详情、预设和世界信息使用同一套 surface/content/border 层级；消息引用、代码块、加载、空内容和异常内容均有明确的弱提示或语义状态 Token。
- 表单控件统一使用 `--form-surface`、`--form-border`、`--form-border-focus`，Hover、Disabled 和 Placeholder 不再依赖透明度伪造可读性。
- 弹窗、下拉菜单、Context Menu、Toast 和遮罩使用 `--surface-overlay`、`--surface-scrim` 与 `--shadow-elevation`，并保留键盘 Focus Ring。
- SVG 和装饰性图标继承 `currentColor`；交互图标根据默认、Hover、Active、Disabled 和 Focus 状态继承相应的图标/内容 Token。
- 空状态、加载条、成功/信息/警告/错误提示和状态点按语义类别映射，不把所有提示统一成灰色。

## 用户自定义标签颜色

标签保存的原始字符串继续保存在现有分类数据结构中，`core/data/ui_store.py` 和 `static/js/state.js` 都接受并规范化三/四/六/八位十六进制、逗号格式的 `rgb/rgba` 和 `hsl/hsla`；非法值、危险 CSS 片段和缺失值回退到默认分类颜色，透明度限制在 0 到 100。

`buildTagColorStyle()` 保留 `--tag-cat-color` 作为识别用的原始安全值，同时根据当前明/暗背景计算：

- 明暗主题各自的标签背景、Hover 背景、边框和文字颜色；
- 文字候选保证至少 4.5:1，对非文字边框候选保证至少 3:1；
- 过亮、过暗、低饱和度、高饱和度颜色都通过浅色/深色文字、混合背景和描边保留识别度；
- 用户颜色继续用于色点和装饰识别，但不强制作为整块背景或正文颜色。

标签样式通过 `--tag-cat-bg-*`、`--tag-cat-border-*`、`--tag-cat-text-*` 及 Hover 变量映射，避免在模板中直接把用户输入拼接到 CSS 属性之外。

## 主题适配与隔离预览

沿用现有 `isDarkMode`、`html.light-mode`、`applyDarkMode()` 和 `applyTheme()` 机制。六种已有主题色会同步更新主色、Hover、Active、浅色背景、Focus Ring、边界和按钮上的可读文字；`applyTheme()` 会根据实际主色动态选择主色上的文字/图标颜色。

不能继承宿主 CSS 变量的 iframe、Shadow DOM 和 Beautify 预览使用 [`static/js/runtime/previewColorTokens.js`](../static/js/runtime/previewColorTokens.js) 的隔离回退 Token，并在 `theme-mode-changed` 事件后刷新；用户在预览中编写的主题 CSS 仍保持原有优先级。

## 验证

- `tests/test_color_system_contracts.py` 覆盖 Token/样式加载顺序、旧调色板回流、标签颜色格式、非法输入回退以及多个极端颜色在明暗主题下的文字/边框对比度。
- `core/data/ui_store.py` 已通过 Python 编译检查；应用 JavaScript 已通过 Node 语法检查；Tailwind 产物由 `npm run build:css` 重新生成。
- 全量 pytest 结果和剩余的非颜色基线失败以最终交付消息为准；颜色相关的定向契约测试必须全部通过。
- 本地浏览器已检查首页和设置弹窗在浅色/深色下的层级、侧边栏选中态、表单 Focus 以及六种主题色的主按钮文字；六种主题色的主按钮文字对比度为 4.57:1–5.45:1。

## 有意保留的例外

- `static/css/tailwind.css` 是生成产物，包含 Tailwind reset 和未使用工具类的默认颜色；应用层 `color-system.css` 在其后加载，业务源码不再引用这些调色板类。
- `static/lib/cards-css/holo-cards.css` 是独立的全息卡片效果库，内部颜色用于材质、光泽、扫描线和卡面艺术效果，不能用普通正文 Token 替换，否则会破坏卡片效果；卡片容器和操作层已接入应用语义 Token。
- `static/vendor/sillytavern/**` 和 Beautify 的用户自定义 CSS 属于隔离的第三方/用户内容边界，应用只为其外壳提供语义回退，不重写作者内容。
- 登录页在认证前独立渲染，因此在 [`core/auth.py`](../core/auth.py) 中保留一组同名的局部 Token；它与主应用使用相同语义和明暗映射。
