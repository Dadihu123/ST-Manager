# SVG 图标系统变更记录

## 1. 范围与规则

本次只整理已经集成到项目内的图标系统，主要检查和修改了 `static/icons/`，并同步扫描了 `templates/`、`static/js/`、`static/css/`、`core/` 和 `tests/` 中的模板宏、`<use>`、CSS mask、JavaScript 动态 icon id 及测试契约。`static/icons/forum-preview/` 下仍由 CSS mask 直接引用的 6 个独立 SVG 也纳入清单；同时将 Tailwind 浏览器运行时改为由 CLI 编译的静态 CSS。

`tmp/` 和 `static/vendor/` 本次完全未处理、未修改。commit `cddb090` 已完成的 viewBox 裁切结果全部保留；本次没有重新裁切、补回空白或修改图形路径，整理只改变 symbol 所属 sprite、id、引用和外层尺寸规则。

分组原则如下：跨模块复用的操作和状态图形放入 `ui.svg`；详情页、阅读器和资源详情专用图形放入 `detail.svg`；侧边栏导航及侧边栏资源切换图形放入 `sidebar.svg`；预设/提示词字段和 marker 图形放入 `preset.svg`；论坛预览中作为 CSS mask 使用的原始独立 SVG 保持独立。只有在几何相同且引用语义允许共用时才合并，未因“看起来相似”而改变不同图形。

symbol id 统一使用带 `icon-` 前缀的英文 kebab-case，并优先表达图形视觉含义，例如 `icon-search`、`icon-file-edit`、`icon-folder-root`、`icon-book-open`。旧的页面/业务模块前缀已映射到语义名称；只有图形确实存在 open/edit 等视觉变体时才保留限定词。

尺寸统一为少量直接整数像素挡位：基础图标使用 12/16/20/24/32/48/64px；同级组件通过统一 class 或宏参数选择挡位。侧边栏在自身密度规则中使用 16/20/24/32px，论坛 mask 使用 16px，卡片 marker 的外框使用 48px 或 32px。已移除用于补偿单个图标留白的 `scale()`、150%/150% 及其他倍率尺寸规则。

上下移动控件统一使用 `icon-arrow-up` / `icon-arrow-down` 与 `.ui-reorder-button`；数字输入统一使用 `.ui-number-control`、`.ui-number-stepper` 和 `.ui-number-stepper-btn`。设置页保留 `.settings-number-*` 兼容类名，但共享相同的无边框、悬浮显示和键盘焦点状态。图标本身继续使用现有 `ui-icon--xs`（12px）挡位，不添加单独缩放规则。

文件传输图标统一按“管理器内的数据流向”判定：进入管理器的本地文件（包括界面文案为“上传”的选择或拖拽入口）使用向下的 `icon-file-import`；从管理器导出或下载文件使用向上的 `icon-upload`。`icon-book-save-as` 仅用于确实会创建新文件的“另存为”操作，不用于直接导出下载。

## 2. Sprite 结构变更

| 文件 | 用途 | 最终 symbol 数量 | 结构变更 |
| --- | --- | ---: | --- |
| `static/icons/ui.svg` | 通用操作、设置、同步、世界书操作、编辑器和状态图标 | 111 | 删除 38 个确认未引用的旧 symbol；将业务前缀重命名为语义 id，并复用统一图形 |
| `static/icons/detail.svg` | 卡片/资源详情、阅读器、预览和详情操作 | 49 | 将 `icon-detail-*` 改为语义 id；删除未引用的 `icon-detail-character-card` |
| `static/icons/sidebar.svg` | 侧边栏导航、资源分类和模块入口 | 20 | 将 `icon-sidebar-*` 改为语义 id；把两个独立侧边栏 SVG 的原始图形移动为 `icon-character-cards`、`icon-paint-brush` |
| `static/icons/preset.svg` | 预设字段、提示词 marker 和空状态 | 13 | 将 `icon-preset-*` 改为语义 id |
| `static/icons/forum-preview/*.svg` | 论坛预览 CSS mask | 6 个独立 SVG | 继续保留；CSS 对每个文件存在明确 mask 引用 |

独立的 `static/icons/sidebar-nav/角色卡-简.svg` 和 `static/icons/sidebar-nav/美化-简.svg` 已分别移动进 `static/icons/sidebar.svg`，对应为 `icon-character-cards` 和 `icon-paint-brush`，并同步修改侧边栏模板；源文件随后删除，未复制出第二份定义。当前没有删除任何 sprite 文件，也没有删除 `forum-preview` 独立 SVG。

本次逐个比较了重命名 symbol 的子树几何，现有 sprite 之间没有发现可以安全再合并的完全相同几何组；因此没有为了减少数量而冒险合并视觉近似但语义不同的图形。

### 变更统计

- 最终保留 193 个 sprite symbol；其中 173 个沿用原图形完成语义改名，18 个原 id 已经符合语义规则而保持不变，另有 2 个来自独立侧边栏 SVG 的合并 symbol。
- 删除 40 个确认未引用的旧 symbol 定义；删除 2 个已合并完成的独立侧边栏 SVG 文件。
- 论坛预览保留 6 个被 CSS mask 明确引用的独立 SVG 文件。

### 重命名和合并概览

- `ui.svg`：将 `card-*`、`context-*`、`settings-*`、`worldbook-*`、`advanced-editor-*`、`other-*` 等位置型名称改为视觉语义名称，例如 `icon-card-search` → `icon-search`、`icon-worldbook-back` → `icon-arrow-left`、`icon-modal-document-edit` → `icon-file-edit`。
- `detail.svg`：统一移除 `detail` 业务前缀，例如 `icon-detail-worldbook` → `icon-book-open`、`icon-detail-author` → `icon-user`。
- `sidebar.svg`：统一移除 `sidebar` 业务前缀，例如 `icon-sidebar-worldbook` → `icon-book-stack`、`icon-sidebar-category-expanded` → `icon-folder-open`。
- `preset.svg`：统一移除 `preset` 业务前缀，例如 `icon-preset-temperature` → `icon-thermometer`、`icon-preset-owner` → `icon-owner`。
- 两个独立侧边栏文件不是复制保留，而是直接成为 sidebar sprite 中的两个 symbol；它们的 viewBox 和路径几何保持原样。

## 3. 最终完整图标清单

下表覆盖全部最终保留的 193 个 sprite symbol 和 6 个论坛预览独立 SVG。动态调用特别标出来源和拼接规则；“尺寸挡位”表示统一尺寸 token 及其最终直接像素值，具体组件覆盖规则见第 5 节。

| 新图标名称 | 原名称/原文件 | 所属 sprite | 图标视觉含义 | 复用位置 | 尺寸挡位 | 是否改名 |
| ----- | ------- | --------- | ------ | ---- | ---- | ---- |
| icon-version | icon-detail-version | static/icons/detail.svg | 版本 | `templates/modals/detail_card.html:388,666` | sm/16px | 是 |
| icon-image-keep | icon-detail-keep-image | static/icons/detail.svg | 图片保留 | `templates/modals/detail_card.html:2491,3817` | sm/16px、md/20px | 是 |
| icon-backup-rollback | icon-detail-backup-rollback | static/icons/detail.svg | 备份回滚 | `static/js/state.js:72`、`templates/modals/detail_card.html:2412,3754` | sm/16px、lg/24px | 是 |
| icon-note | icon-detail-local-note | static/icons/detail.svg | 备注 | `templates/modals/detail_card.html:749,3671`、`tests/test_cards_api_import_sync.py:2459` | sm/16px、lg/24px | 是 |
| icon-edit-mode | icon-detail-edit-mode | static/icons/detail.svg | 编辑模式 | `templates/modals/detail_card.html:192,330` | sm/16px | 是 |
| icon-tags | icon-detail-tags | static/icons/detail.svg | 标签 | `static/js/state.js:73`、`templates/modals/automation.html:426,433,755`、`templates/modals/detail_card.html:578`、`tests/test_advanced_editor_icon_contracts.py:101` | xs/12px、sm/16px | 是 |
| icon-folder-create | icon-detail-create-resource-folder | static/icons/detail.svg | 文件夹新建 | `templates/modals/detail_card.html:522` | sm/16px | 是 |
| icon-file-current | icon-detail-current-file | static/icons/detail.svg | 文件当前 | `templates/modals/detail_card.html:2361` | sm/16px | 是 |
| icon-locate | icon-detail-locate | static/icons/detail.svg | 定位 | `templates/modals/detail_card.html:2389`、`templates/modals/import.html:39`、`templates/modals/move_cards.html:19`、`tests/test_common_modal_icon_contracts.py:33,42` | sm/16px | 是 |
| icon-dialog | icon-detail-dialog | static/icons/detail.svg | 对话框 | `templates/modals/detail_card.html:570` | xs/12px | 是 |
| icon-arrow-up-left | icon-detail-return-parent | static/icons/detail.svg | 箭头上左 | `templates/modals/detail_card.html:42,2769,3327` | sm/16px、md/20px | 是 |
| icon-maximize | icon-detail-enlarge | static/icons/detail.svg | 最大化 | `templates/modals/detail_card.html:242` | sm/16px | 是 |
| icon-overwrite | icon-detail-overwrite | static/icons/detail.svg | 覆盖 | `templates/modals/batch_import.html:33,111`、`templates/modals/detail_card.html:2488,3813`、`templates/modals/import.html:133`、`tests/test_common_modal_icon_contracts.py:19,35` | xs/12px、sm/16px、md/20px | 是 |
| icon-editor | icon-detail-advanced-editor | static/icons/detail.svg | 编辑器 | `templates/modals/detail_card.html:2632,2641` | sm/16px、lg/24px | 是 |
| icon-image-replace | icon-detail-replace-image | static/icons/detail.svg | 图片替换 | `templates/modals/detail_card.html:180` | sm/16px | 是 |
| icon-update | icon-detail-update | static/icons/detail.svg | 更新 | `templates/modals/detail_card.html:2441` | sm/16px | 是 |
| icon-update-policy | icon-detail-update-policy | static/icons/detail.svg | 更新策略 | `templates/modals/detail_card.html:2483,3803` | sm/16px、lg/24px | 是 |
| icon-toolbox | icon-detail-toolbox | static/icons/detail.svg | 工具箱 | `templates/modals/detail_card.html:2383` | sm/16px | 是 |
| icon-manage | icon-detail-manage | static/icons/detail.svg | 管理 | `templates/modals/detail_card.html:602` | xs/12px | 是 |
| icon-archive-old | icon-detail-archive-old | static/icons/detail.svg | 归档旧 | `templates/modals/detail_card.html:2494,3821` | sm/16px、md/20px | 是 |
| icon-archive-new | icon-detail-archive-new | static/icons/detail.svg | 归档新 | `templates/modals/detail_card.html:2497,3825` | sm/16px、md/20px | 是 |
| icon-info | icon-detail-basic-info | static/icons/detail.svg | 信息 | `templates/modals/detail_card.html:552` | xs/12px | 是 |
| icon-quick-reply | icon-detail-quick-replies | static/icons/detail.svg | 快速回复 | `templates/components/grid_extensions.html:20`、`templates/components/sidebar.html:70,173`、`templates/modals/advanced_editor.html:45`、`templates/modals/detail_card.html:3082,3096`、`tests/test_advanced_editor_icon_contracts.py:21` | sm/16px、md/20px | 是 |
| icon-link-source | icon-detail-source-link | static/icons/detail.svg | 链接source | `static/js/state.js:74`、`templates/modals/automation.html:430`、`templates/modals/detail_card.html:412,690,3717`、`templates/modals/import.html:31`、`tests/test_advanced_editor_icon_contracts.py:104` | sm/16px、lg/24px | 是 |
| icon-chat-bubble | icon-detail-chat | static/icons/detail.svg | 聊天气泡 | `templates/components/grid_chats.html:13`、`templates/components/sidebar.html:66,129`、`templates/modals/detail_card.html:594,2112` | xs/12px、sm/16px、md/20px、xl/32px | 是 |
| icon-resource | icon-detail-other-resource | static/icons/detail.svg | 资源 | `templates/modals/detail_card.html:3182,3195` | sm/16px | 是 |
| icon-fullscreen | icon-detail-fullscreen | static/icons/detail.svg | 全屏 | `templates/modals/detail_card.html:1845,2756` | sm/16px | 是 |
| icon-persona | icon-detail-persona | static/icons/detail.svg | 人格 | `templates/modals/detail_card.html:561` | xs/12px | 是 |
| icon-cover-image | icon-detail-set-cover | static/icons/detail.svg | 封面图片 | `templates/modals/detail_card.html:285,2902,3742` | xs/12px、sm/16px | 是 |
| icon-resource-settings | icon-detail-resource-settings | static/icons/detail.svg | 资源设置 | `templates/modals/detail_card.html:530` | xs/12px | 是 |
| icon-clock | icon-detail-time | static/icons/detail.svg | 时钟 | `templates/modals/automation.html:431`、`templates/modals/detail_card.html:2266`、`templates/modals/settings.html:1818`、`tests/test_advanced_editor_icon_contracts.py:105` | sm/16px | 是 |
| icon-book-open | icon-detail-worldbook | static/icons/detail.svg | 书本打开 | `templates/components/sidebar.html:65,118`、`templates/modals/detail_card.html:586,2932,2946` | sm/16px、md/20px | 是 |
| icon-collapse | icon-detail-shrink | static/icons/detail.svg | 收起 | `templates/modals/detail_card.html:228` | sm/16px | 是 |
| icon-locate-jump | icon-detail-jump-locate | static/icons/detail.svg | 定位跳转 | `templates/modals/detail_card.html:2397` | lg/24px | 是 |
| icon-brand | icon-detail-brand | static/icons/detail.svg | 品牌 | `templates/components/header.html:16,170`、`templates/components/loading.html:8` | md/20px、lg/24px、3xl/64px | 是 |
| icon-image | icon-detail-image | static/icons/detail.svg | 图片 | `templates/modals/detail_card.html:153,2741` | sm/16px | 是 |
| icon-file-name | icon-detail-filename | static/icons/detail.svg | 文件名称 | `templates/modals/automation.html:434,435,436,437`、`templates/modals/detail_card.html:2313`、`tests/test_advanced_editor_icon_contracts.py:107` | sm/16px | 是 |
| icon-heart-broken | icon-detail-heart-broken | static/icons/detail.svg | 爱心破碎 | `templates/modals/detail_card.html:2590` | lg/24px | 是 |
| icon-preset | icon-detail-preset | static/icons/detail.svg | 预设 | `templates/components/grid_presets.html:18,167`、`templates/components/sidebar.html:67,140`、`templates/modals/detail_card.html:3132,3146`、`templates/modals/detail_chat_reader.html:1352`、`tests/test_preset_list_icons.py:17` | sm/16px、md/20px、lg/24px | 是 |
| icon-metadata | icon-detail-metadata | static/icons/detail.svg | 元数据 | `templates/modals/detail_card.html:141,171,544` | xs/12px、sm/16px | 是 |
| icon-book-read | icon-detail-read-mode | static/icons/detail.svg | 书本阅读 | `templates/modals/detail_card.html:191,329`、`templates/modals/html_preview.html:31`、`tests/test_common_modal_icon_contracts.py:55` | sm/16px、md/20px | 是 |
| icon-expand | icon-detail-expand | static/icons/detail.svg | 展开 | `templates/modals/advanced_editor.html:398`、`templates/modals/detail_card.html:757,806,877,949…`、`tests/test_advanced_editor_icon_contracts.py:32` | xs/12px、sm/16px | 是 |
| icon-regex | icon-detail-regex | static/icons/detail.svg | 正则 | `templates/components/grid_extensions.html:14`、`templates/components/grid_presets.html:231`、`templates/components/sidebar.html:68,151`、`templates/modals/advanced_editor.html:31,43,46,434`、`templates/modals/detail_card.html:2982,2996` | sm/16px、md/20px、lg/24px | 是 |
| icon-reset | icon-detail-reset | static/icons/detail.svg | 重置 | `templates/modals/detail_card.html:252` | sm/16px | 是 |
| icon-resources | icon-detail-resources | static/icons/detail.svg | 资源 | `templates/modals/detail_card.html:610`、`tests/test_cards_api_import_sync.py:233,262` | xs/12px | 是 |
| icon-user | icon-detail-author | static/icons/detail.svg | 用户 | `templates/modals/detail_card.html:361,639` | sm/16px | 是 |
| icon-script-file | icon-detail-scripts | static/icons/detail.svg | 脚本文件 | `templates/components/grid_extensions.html:17`、`templates/components/sidebar.html:69,162`、`templates/modals/advanced_editor.html:35,44,804`、`templates/modals/detail_card.html:3032,3046`、`tests/test_advanced_editor_icon_contracts.py:20,40` | sm/16px、md/20px、lg/24px | 是 |
| icon-chat-empty | icon-detail-chat-empty | static/icons/detail.svg | 聊天空 | `templates/components/grid_chats.html:111`、`templates/modals/detail_card.html:2184` | lg/24px、xl/32px | 是 |
| icon-key-snapshot | icon-detail-key-snapshot | static/icons/detail.svg | 钥匙快照 | `templates/modals/detail_card.html:3772` | sm/16px | 是 |
| icon-definition-after | icon-preset-character-definition-after | static/icons/preset.svg | 定义后置 | `tests/test_preset_list_icons.py:48`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px（默认） | 是 |
| icon-definition-before | icon-preset-character-definition-before | static/icons/preset.svg | 定义前置 | `tests/test_preset_list_icons.py:49`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px（默认） | 是 |
| icon-character-description | icon-preset-character-description | static/icons/preset.svg | 角色描述 | `static/js/utils/promptMarkerVisuals.js:29`、`tests/test_preset_list_icons.py:50`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px（默认） | 是 |
| icon-scenario | icon-preset-character-scenario | static/icons/preset.svg | 场景 | `templates/modals/detail_card.html:958`、`tests/test_preset_editor_frontend_contracts.py:1094`、`tests/test_preset_list_icons.py:51`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px | 是 |
| icon-character-personality | icon-preset-character-personality | static/icons/preset.svg | 角色性格 | `static/js/utils/promptMarkerVisuals.js:38`、`tests/test_preset_list_icons.py:52`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px（默认） | 是 |
| icon-owner | icon-preset-owner | static/icons/preset.svg | 所有者 | `templates/components/grid_extensions.html:98`、`templates/components/grid_presets.html:260`、`tests/test_extension_list_icons.py:24`、`tests/test_index_job_worker.py:279,280`、`tests/test_preset_list_icons.py:29,53`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px | 是 |
| icon-thermometer | icon-preset-temperature | static/icons/preset.svg | 温度计 | `templates/components/grid_presets.html:207`、`tests/test_preset_list_icons.py:26,54`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px | 是 |
| icon-persona-description | icon-preset-user-persona-description | static/icons/preset.svg | 人格描述 | `static/js/utils/promptMarkerVisuals.js:49`、`tests/test_preset_list_icons.py:55`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px（默认） | 是 |
| icon-chat-examples | icon-preset-chat-examples | static/icons/preset.svg | 聊天示例 | `static/js/utils/promptMarkerVisuals.js:76`、`tests/test_preset_list_icons.py:56`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px（默认） | 是 |
| icon-chat-history | icon-preset-chat-history | static/icons/preset.svg | 聊天历史 | `static/js/utils/promptMarkerVisuals.js:66`、`tests/test_preset_list_icons.py:57`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px（默认） | 是 |
| icon-prompt-count | icon-preset-prompt-count | static/icons/preset.svg | 提示词计数 | `templates/components/grid_presets.html:223`、`tests/test_preset_list_icons.py:28,58`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px | 是 |
| icon-token-count | icon-preset-token-count | static/icons/preset.svg | token计数 | `templates/components/grid_presets.html:215`、`tests/test_preset_list_icons.py:27,59`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | sm/16px | 是 |
| icon-empty-state | icon-preset-empty-state | static/icons/preset.svg | 空状态 | `templates/components/grid_extensions.html:115`、`templates/components/grid_presets.html:308`、`tests/test_extension_list_icons.py:25`、`tests/test_preset_list_icons.py:60`、`promptMarkerVisuals.js:PROMPT_MARKER_VISUALS` → `#icon-${asset}` | xl/32px | 是 |
| icon-layers | icon-sidebar-all-content | static/icons/sidebar.svg | 图层 | `templates/components/sidebar.html:493,667,722,876` | sm/20px | 是 |
| icon-tag-library | icon-sidebar-tag-library | static/icons/sidebar.svg | 标签库 | `templates/components/sidebar.html:397,463`、`templates/modals/detail_card.html:1526` | xs/16px、sm/20px | 是 |
| icon-directory-tree | icon-sidebar-global-directory | static/icons/sidebar.svg | 目录树 | `templates/components/sidebar.html:504,734,888` | sm/20px | 是 |
| icon-folder-solid | icon-sidebar-folder | static/icons/sidebar.svg | 文件夹solid | `static/js/components/settingsModal.js:501`、`templates/components/sidebar.html:297,516,607,747…`、`templates/modals/detail_card.html:58,490,2343,2794…`、`templates/modals/import.html:46`、`templates/modals/move_cards.html:26` | sm/20px、md/24px、lg/32px | 是 |
| icon-cards-grid | icon-sidebar-all-cards-categories | static/icons/sidebar.svg | 卡片grid | `templates/components/sidebar.html:240,569,788` | sm/20px | 是 |
| icon-file-embedded | icon-sidebar-embedded | static/icons/sidebar.svg | 文件嵌入 | `templates/components/sidebar.html:528` | sm/20px | 是 |
| icon-link-bound | icon-sidebar-bound | static/icons/sidebar.svg | 链接绑定 | `templates/components/sidebar.html:678` | sm/20px | 是 |
| icon-link-unbound | icon-sidebar-unbound | static/icons/sidebar.svg | 链接unbound | `templates/components/sidebar.html:689`、`tests/test_sidebar_icon_templates.py:146,175` | sm/20px | 是 |
| icon-organize | icon-sidebar-organize | static/icons/sidebar.svg | 整理 | `templates/components/sidebar.html:645` | sm/20px | 是 |
| icon-menu-category | icon-sidebar-category-menu | static/icons/sidebar.svg | 菜单分类 | `templates/components/sidebar.html:258,334` | sm/20px | 是 |
| icon-cards-stack | icon-sidebar-cards | static/icons/sidebar.svg | 卡片堆叠 | `settingsModal.js:getResourceIcon(type)` → settings.html 动态拼接 | md/24px | 是 |
| icon-book-stack | icon-sidebar-worldbook | static/icons/sidebar.svg | 书本堆叠 | `templates/modals/detail_card.html:1772`、`templates/modals/detail_wi_fullscreen.html:27,1841`、`templates/modals/detail_wi_popup.html:24`、`settingsModal.js:getResourceIcon(type)` → settings.html 动态拼接 | md/24px、lg/32px | 是 |
| icon-chat-bubbles | icon-sidebar-chats | static/icons/sidebar.svg | 聊天气泡组 | `settingsModal.js:getResourceIcon(type)` → settings.html 动态拼接 | md/24px | 是 |
| icon-preset-stack | icon-sidebar-presets | static/icons/sidebar.svg | 预设堆叠 | `settingsModal.js:getResourceIcon(type)` → settings.html 动态拼接 | md/24px | 是 |
| icon-regex-file | icon-sidebar-regex | static/icons/sidebar.svg | 正则文件 | `settingsModal.js:getResourceIcon(type)` → settings.html 动态拼接 | md/24px | 是 |
| icon-script-brackets | icon-sidebar-scripts | static/icons/sidebar.svg | 脚本括号 | `settingsModal.js:getResourceIcon(type)` → settings.html 动态拼接 | md/24px | 是 |
| icon-reply-bolt | icon-sidebar-quick-replies | static/icons/sidebar.svg | 回复闪电 | `settingsModal.js:getResourceIcon(type)` → settings.html 动态拼接 | md/24px | 是 |
| icon-folder-open | icon-sidebar-category-expanded | static/icons/sidebar.svg | 文件夹打开 | `templates/components/sidebar.html:296,606,828`、`templates/modals/automation.html:425`、`templates/modals/detail_card.html:2404,2457`、`templates/modals/import.html:44`、`templates/modals/move_cards.html:10,24,46` | sm/20px、md/24px、lg/32px | 是 |
| icon-character-cards | static/icons/sidebar-nav/角色卡-简.svg | static/icons/sidebar.svg | 角色卡片 | `templates/components/sidebar.html:64,107`、`templates/modals/detail_chat_reader.html:1272`、`tests/test_sidebar_icon_templates.py:57,72` | md/24px | 是 |
| icon-paint-brush | static/icons/sidebar-nav/美化-简.svg | static/icons/sidebar.svg | 绘画画笔 | `templates/components/sidebar.html:71,184,929`、`tests/test_sidebar_icon_templates.py:58,73` | md/24px | 是 |
| icon-close-small | icon-x | static/icons/ui.svg | 关闭小号 | `templates/components/header.html:133,150,222,241…` | xs/12px、sm/16px | 是 |
| icon-chevron-down | icon-chevron-down | static/icons/ui.svg | 折叠下 | `templates/components/header.html:391,739`、`templates/components/sidebar.html:78,288,380,601…`、`templates/modals/detail_card.html:1859,1961`、`templates/modals/detail_wi_fullscreen.html:871`、`templates/modals/detail_wi_popup.html:281` | xs/12px、sm/16px | 否 |
| icon-ban | icon-ban | static/icons/ui.svg | 禁止 | `templates/modals/detail_wi_fullscreen.html:979` | xs/12px | 否 |
| icon-settings | icon-settings | static/icons/ui.svg | 设置 | `templates/components/header.html:371`、`templates/modals/advanced_editor.html:265,878`、`templates/modals/execute_rules_mobile.html:52`、`tests/test_advanced_editor_icon_contracts.py:29,130`、`tests/test_common_modal_icon_contracts.py:67` | sm/16px | 否 |
| icon-circle-dot | icon-circle-dot | static/icons/ui.svg | 圆形点 | `tests/test_worldbook_icon_contracts.py:149` | sm/16px（默认） | 否 |
| icon-chevron-right | icon-chevron-right | static/icons/ui.svg | 折叠右 | `templates/components/context_menu.html:78`、`templates/components/sidebar.html:289,381,602,824`、`templates/modals/detail_card.html:1866`、`templates/modals/detail_wi_fullscreen.html:422,435,874,1439`、`templates/modals/detail_wi_popup.html:278` | xs/12px、sm/16px | 否 |
| icon-image-upload | icon-settings-background-upload | static/icons/ui.svg | 图片上传（兼容保留，当前传输入口统一使用文件导入图标） | 无直接模板引用；背景选择入口使用 `icon-file-import` | md/20px | 是 |
| icon-wallpaper | icon-settings-wallpaper | static/icons/ui.svg | 壁纸 | `core/data/ui_store.py:707`、`core/services/beautify_service.py:493,534`、`templates/modals/settings.html:1987` | sm/16px | 是 |
| icon-directory-root | icon-settings-general-path | static/icons/ui.svg | 目录根 | `templates/modals/settings.html:56` | sm/16px | 是 |
| icon-sliders-settings | icon-settings-advanced-settings | static/icons/ui.svg | 滑杆设置 | `templates/modals/advanced_editor.html:14`、`templates/modals/detail_card.html:2078`、`templates/modals/detail_wi_fullscreen.html:586,2086`、`templates/modals/settings.html:2226`、`tests/test_advanced_editor_icon_contracts.py:17` | sm/16px、md/20px | 是 |
| icon-folder-path | icon-settings-path | static/icons/ui.svg | 文件夹路径 | `templates/modals/settings.html:1917` | sm/16px | 是 |
| icon-file-check | icon-settings-path-validation | static/icons/ui.svg | 文件勾选 | `templates/modals/settings.html:720` | sm/16px | 是 |
| icon-folder-search | icon-settings-path-auto-detect | static/icons/ui.svg | 文件夹搜索 | `templates/modals/settings.html:711` | sm/16px | 是 |
| icon-key | icon-settings-key | static/icons/ui.svg | 钥匙 | `templates/modals/settings.html:1359,2182` | sm/16px | 是 |
| icon-shield-key | icon-settings-authentication | static/icons/ui.svg | 盾牌钥匙 | `templates/modals/settings.html:1107,2004` | sm/16px | 是 |
| icon-database-backup | icon-settings-data-backup | static/icons/ui.svg | 数据库备份 | `templates/modals/settings.html:1440` | sm/16px | 是 |
| icon-idea | icon-settings-tip | static/icons/ui.svg | 提示 | `templates/modals/settings.html:1945` | sm/16px | 是 |
| icon-cards-sync | icon-settings-sync-cards | static/icons/ui.svg | 卡片同步 | `templates/modals/settings.html:788` | sm/16px | 是 |
| icon-replies-sync | icon-settings-sync-quick-replies | static/icons/ui.svg | 回复同步 | `templates/modals/settings.html:823` | sm/16px | 是 |
| icon-chats-sync | icon-settings-sync-chats | static/icons/ui.svg | 聊天同步 | `templates/modals/settings.html:795` | sm/16px | 是 |
| icon-scan | icon-settings-sync-scan | static/icons/ui.svg | 扫描 | `templates/modals/settings.html:1421` | sm/16px | 是 |
| icon-book-sync | icon-settings-sync-worldbook | static/icons/ui.svg | 书本同步 | `templates/modals/settings.html:802` | sm/16px | 是 |
| icon-presets-sync | icon-settings-sync-presets | static/icons/ui.svg | 预设同步 | `templates/modals/settings.html:809` | sm/16px | 是 |
| icon-regex-sync | icon-settings-sync-regex | static/icons/ui.svg | 正则同步 | `templates/modals/settings.html:816` | sm/16px | 是 |
| icon-display | icon-settings-appearance-display | static/icons/ui.svg | 显示器 | `templates/modals/settings.html:66` | sm/16px | 是 |
| icon-settings-maintenance-advanced | icon-settings-maintenance-advanced | static/icons/ui.svg | 维护与高级工具组合 | `templates/modals/settings.html:86`、`tests/test_settings_icon_templates.py` | sm/16px | 否 |
| icon-database-user | icon-settings-user-database | static/icons/ui.svg | 数据库用户 | `templates/modals/settings.html:1482` | sm/16px | 是 |
| icon-folder-resources | icon-settings-resource-directory | static/icons/ui.svg | 文件夹资源 | `templates/modals/settings.html:148,748,1461,1530` | sm/16px | 是 |
| icon-folder-sync | icon-settings-resource-sync | static/icons/ui.svg | 文件夹同步 | `templates/modals/settings.html:775,830` | sm/16px | 是 |
| icon-file-import | icon-header-import | static/icons/ui.svg | 文件导入（向下，统一覆盖入站传输） | `templates/components/grid_cards.html:74`、`grid_chats.html:40`、`grid_extensions.html:53`、`grid_presets.html:62`、`grid_wi.html:30`、`header.html:79,883`、`templates/modals/advanced_editor.html:81,482`、`automation.html:47`、`batch_import.html:11`、`detail_card.html:2125,2162,2464,2692`、`detail_wi_fullscreen.html:192,1824`、`import.html:63`、`settings.html:522` | sm/16px、md/20px、lg/24px、xl/32px | 是 |
| icon-filter | icon-header-advanced-filter | static/icons/ui.svg | 筛选 | `templates/components/header.html:570,846`、`tests/test_header_icon_templates.py:18` | md/20px | 是 |
| icon-settings-gear | icon-header-settings | static/icons/ui.svg | 设置gear | `templates/components/header.html:659,937`、`templates/modals/settings.html:15`、`tests/test_header_icon_templates.py:25`、`tests/test_settings_icon_templates.py:56` | md/20px、lg/24px | 是 |
| icon-refresh | icon-header-refresh | static/icons/ui.svg | 刷新 | `templates/components/grid_chats.html:44`、`templates/components/grid_extensions.html:41`、`templates/components/grid_presets.html:43`、`templates/components/header.html:634,913`、`templates/components/sidebar.html:937` | sm/16px、md/20px、lg/24px | 是 |
| icon-link-import | icon-header-url-import | static/icons/ui.svg | 链接导入 | `templates/components/header.html:626,898`、`templates/modals/detail_card.html:2566`、`templates/modals/import.html:12`、`tests/test_common_modal_icon_contracts.py:27`、`tests/test_header_icon_templates.py:20` | md/20px、lg/24px | 是 |
| icon-close | icon-context-close | static/icons/ui.svg | 关闭 | `templates/components/context_menu.html:25`、`templates/components/header.html:110`、`templates/components/sidebar.html:48`、`templates/modals/advanced_editor.html:24`、`templates/modals/automation.html:107,650,979` | sm/16px、md/20px、lg/24px、3xl/64px | 是 |
| icon-isolate | icon-context-isolate | static/icons/ui.svg | 隔离 | `templates/components/context_menu.html:42` | sm/16px | 是 |
| icon-unisolate | icon-context-unisolate | static/icons/ui.svg | 取消隔离 | `templates/components/context_menu.html:39` | sm/16px | 是 |
| icon-pencil-edit | icon-context-rename | static/icons/ui.svg | 铅笔编辑 | `templates/components/context_menu.html:50`、`templates/components/grid_wi.html:111`、`templates/modals/automation.html:432`、`templates/modals/batch_import.html:30,110`、`templates/modals/detail_card.html:2352` | xs/12px、sm/16px、md/20px | 是 |
| icon-plus-square | icon-context-new | static/icons/ui.svg | 加号方框 | `templates/components/context_menu.html:54`、`templates/components/header.html:599,875`、`templates/components/sidebar.html:207,636`、`templates/modals/advanced_editor.html:88,470,830`、`templates/modals/automation.html:51` | xs/12px、sm/16px、md/20px、lg/24px | 是 |
| icon-trash | icon-context-delete | static/icons/ui.svg | 垃圾桶 | `templates/components/context_menu.html:61`、`templates/components/grid_presets.html:143`、`templates/components/header.html:290,304,328,793…`、`templates/modals/automation.html:170,246,427`、`templates/modals/detail_card.html:1954,2597,2911` | sm/16px、md/20px、lg/24px | 是 |
| icon-workflow | icon-context-automation | static/icons/ui.svg | 工作流 | `templates/components/context_menu.html:77,111`、`templates/components/header.html:340,651,721,930`、`templates/modals/automation.html:63,85,117,141…`、`templates/modals/execute_rules_mobile.html:10`、`tests/test_advanced_editor_icon_contracts.py:98,129` | xs/12px、sm/16px、md/20px、lg/24px、3xl/64px | 是 |
| icon-refresh-card | icon-card-refresh | static/icons/ui.svg | 刷新卡片 | `templates/components/context_menu.html:68`、`templates/components/grid_cards.html:363`、`templates/modals/detail_card.html:2539` | sm/16px、lg/24px | 是 |
| icon-heart | icon-card-favorite | static/icons/ui.svg | 爱心 | `templates/components/grid_cards.html:193`、`templates/components/grid_chats.html:60`、`templates/components/header.html:954`、`templates/modals/automation.html:428`、`templates/modals/detail_card.html:2218` | sm/16px | 是 |
| icon-file-code | icon-extension-file | static/icons/ui.svg | 文件代码 | `templates/components/grid_extensions.html:81`、`templates/modals/advanced_editor.html:46`、`tests/test_advanced_editor_icon_contracts.py:22`、`tests/test_extension_list_icons.py:23,61` | sm/16px、lg/24px | 是 |
| icon-monitor-users | icon-monitor-pool | static/icons/ui.svg | 监视器users | `templates/modals/source_update_monitor.html:22` | 2xl/48px | 是 |
| icon-monitor-user | icon-monitor-pool-small | static/icons/ui.svg | 监视器用户 | `templates/components/header.html:616,906`、`tests/test_header_icon_templates.py:40` | xl/32px | 是 |
| icon-book-save | icon-worldbook-save-all | static/icons/ui.svg | 书本保存 | `templates/modals/detail_card.html:211,471`、`templates/modals/detail_wi_fullscreen.html:233,279,1931`、`tests/test_worldbook_icon_contracts.py:128` | xs/12px、sm/16px | 是 |
| icon-book-backup | icon-worldbook-backup | static/icons/ui.svg | 书本备份 | `templates/modals/detail_card.html:2427`、`templates/modals/detail_wi_fullscreen.html:183,2013`、`templates/modals/detail_wi_popup.html:499` | md/20px、lg/24px | 是 |
| icon-entry-rollback | icon-worldbook-entry-rollback | static/icons/ui.svg | 条目回滚 | `templates/modals/detail_wi_fullscreen.html:527,1995,2005`、`tests/test_worldbook_icon_contracts.py:129` | xs/12px、md/20px | 是 |
| icon-arrow-left | icon-worldbook-back | static/icons/ui.svg | 箭头左 | `templates/modals/detail_wi_fullscreen.html:505` | sm/16px | 是 |
| icon-history-rollback | icon-worldbook-rollback | static/icons/ui.svg | 历史回滚 | `templates/modals/detail_card.html:2420,3782`、`templates/modals/detail_wi_fullscreen.html:164,1963,1982`、`templates/modals/detail_wi_popup.html:491`、`templates/modals/rollback.html:10,78`、`tests/test_common_modal_icon_contracts.py:59` | sm/16px、md/20px、lg/24px | 是 |
| icon-clipboard | icon-worldbook-clipboard | static/icons/ui.svg | 剪贴板 | `templates/modals/detail_wi_fullscreen.html:456,541,594,2031…` | xs/12px、sm/16px、md/20px | 是 |
| icon-snapshot | icon-worldbook-snapshot | static/icons/ui.svg | 快照 | `templates/modals/detail_card.html:201,461,3759,3765`、`templates/modals/detail_wi_fullscreen.html:174,1969`、`templates/modals/detail_wi_popup.html:483`、`tests/test_worldbook_icon_contracts.py:133` | xs/12px、sm/16px、md/20px | 是 |
| icon-book-save-as | icon-worldbook-save-as | static/icons/ui.svg | 书本另存为 | `templates/modals/detail_wi_fullscreen.html:245,291,1946`、`tests/test_worldbook_icon_contracts.py:196` | xs/12px、sm/16px、md/20px | 是 |
| icon-sort | icon-worldbook-sort | static/icons/ui.svg | 排序 | `templates/modals/detail_wi_fullscreen.html:137`、`templates/modals/detail_wi_popup.html:183` | md/20px | 是 |
| icon-calendar | icon-worldbook-calendar | static/icons/ui.svg | 日历 | `templates/modals/detail_wi_popup.html:54`、`tests/test_worldbook_icon_contracts.py:131` | xs/12px | 是 |
| icon-book-search | icon-worldbook-search | static/icons/ui.svg | 书本搜索 | `templates/modals/advanced_editor.html:195`、`templates/modals/detail_card.html:513`、`templates/modals/detail_wi_fullscreen.html:201,2253`、`templates/modals/detail_wi_popup.html:110,138`、`tests/test_advanced_editor_icon_contracts.py:26` | sm/16px、md/20px | 是 |
| icon-pin | icon-worldbook-constant | static/icons/ui.svg | 图钉 | `templates/modals/detail_wi_fullscreen.html:625,2102`、`tests/test_worldbook_icon_contracts.py:147` | xs/12px、md/20px | 是 |
| icon-wand | icon-worldbook-vectorize | static/icons/ui.svg | 魔杖 | `templates/modals/detail_wi_fullscreen.html:642,2117`、`tests/test_worldbook_icon_contracts.py:130,272` | xs/12px、md/20px | 是 |
| icon-layout | icon-worldbook-layout | static/icons/ui.svg | 布局 | `templates/modals/detail_wi_fullscreen.html:1867` | sm/16px | 是 |
| icon-book-tip | icon-worldbook-tip | static/icons/ui.svg | 书本提示 | `templates/modals/automation.html:184,474,509,558…`、`templates/modals/detail_wi_fullscreen.html:1891`、`templates/modals/large_editor.html:140`、`tests/test_advanced_editor_icon_contracts.py:108`、`tests/test_common_modal_icon_contracts.py:46` | xs/12px、sm/16px | 是 |
| icon-key-trigger | icon-worldbook-keyword-trigger | static/icons/ui.svg | 钥匙触发 | `templates/modals/detail_wi_fullscreen.html:2132` | xs/12px | 是 |
| icon-list | icon-worldbook-list | static/icons/ui.svg | 列表 | `templates/modals/advanced_editor.html:1040`、`templates/modals/automation.html:13`、`templates/modals/detail_wi_fullscreen.html:2291`、`tests/test_advanced_editor_icon_contracts.py:38,91` | sm/16px、lg/24px | 是 |
| icon-keyboard | icon-worldbook-shortcut | static/icons/ui.svg | 键盘 | `templates/modals/detail_wi_fullscreen.html:2327` | lg/24px | 是 |
| icon-book-closed | icon-worldbook-closed | static/icons/ui.svg | 书本闭合 | `templates/components/grid_wi.html:137`、`tests/test_worldbook_icon_contracts.py:160` | xl/32px | 是 |
| icon-merge | icon-automation-merge | static/icons/ui.svg | 合并 | `templates/modals/automation.html:429`、`tests/test_advanced_editor_icon_contracts.py:103,197` | sm/16px | 是 |
| icon-forbidden | icon-automation-forbidden | static/icons/ui.svg | 禁止 | `templates/modals/automation.html:717`、`templates/modals/batch_import.html:36,112`、`tests/test_advanced_editor_icon_contracts.py:110,198`、`tests/test_common_modal_icon_contracts.py:21` | xs/12px、sm/16px | 是 |
| icon-flask | icon-advanced-editor-test-lab | static/icons/ui.svg | 烧瓶 | `templates/modals/advanced_editor.html:360`、`tests/test_advanced_editor_icon_contracts.py:30,169` | sm/16px | 是 |
| icon-replace | icon-advanced-editor-replace | static/icons/ui.svg | 替换 | `templates/modals/advanced_editor.html:234`、`tests/test_advanced_editor_icon_contracts.py:27,170` | sm/16px | 是 |
| icon-scissors | icon-advanced-editor-trim | static/icons/ui.svg | 剪刀 | `templates/modals/advanced_editor.html:248`、`tests/test_advanced_editor_icon_contracts.py:28,171` | sm/16px | 是 |
| icon-play | icon-advanced-editor-execute | static/icons/ui.svg | 播放 | `templates/modals/advanced_editor.html:366`、`tests/test_advanced_editor_icon_contracts.py:31,172` | sm/16px | 是 |
| icon-quick-actions | icon-advanced-editor-quick-buttons | static/icons/ui.svg | 快速操作 | `templates/modals/advanced_editor.html:582`、`tests/test_advanced_editor_icon_contracts.py:33,173` | sm/16px | 是 |
| icon-code-file | icon-advanced-editor-script-code | static/icons/ui.svg | 代码文件 | `templates/modals/advanced_editor.html:642`、`tests/test_advanced_editor_icon_contracts.py:34,174` | sm/16px | 是 |
| icon-data-grid | icon-advanced-editor-data | static/icons/ui.svg | datagrid | `templates/modals/advanced_editor.html:774`、`tests/test_advanced_editor_icon_contracts.py:35,175` | sm/16px | 是 |
| icon-send-content | icon-advanced-editor-send-content | static/icons/ui.svg | 发送内容 | `templates/modals/advanced_editor.html:947`、`tests/test_advanced_editor_icon_contracts.py:36,176` | sm/16px、lg/24px | 是 |
| icon-bolt | icon-advanced-editor-trigger | static/icons/ui.svg | 闪电 | `templates/modals/advanced_editor.html:959`、`tests/test_advanced_editor_icon_contracts.py:37,177` | sm/16px、lg/24px | 是 |
| icon-folder-root | icon-modal-root-directory | static/icons/ui.svg | 文件夹根 | `templates/modals/import.html:45`、`templates/modals/move_cards.html:25`、`tests/test_common_modal_icon_contracts.py:32,41,127` | sm/16px | 是 |
| icon-file | icon-modal-document | static/icons/ui.svg | 文件 | `core/services/beautify_service.py:493,911`、`templates/modals/markdown_preview.html:13`、`tests/test_beautify_service.py:1094`、`tests/test_common_modal_icon_contracts.py:51,128`、`tests/test_settings_api.py:31,184` | md/20px | 是 |
| icon-file-edit | icon-modal-document-edit | static/icons/ui.svg | 文件编辑 | `templates/modals/large_editor.html:21`、`tests/test_common_modal_icon_contracts.py:45,129` | md/20px | 是 |
| icon-lock | icon-other-lock | static/icons/ui.svg | 锁 | `core/auth.py:722` | sm/16px（默认） | 是 |
| icon-shield | icon-other-security | static/icons/ui.svg | 盾牌 | `core/auth.py:747` | sm/16px（默认） | 是 |
| icon-leaf-wind | icon-other-leaf-wind | static/icons/ui.svg | 叶片风 | `templates/modals/detail_wi_popup.html:638` | xl/32px | 是 |
| icon-arrow-up | icon-other-arrow-up | static/icons/ui.svg | 箭头上 | `templates/modals/advanced_editor.html:134,331,348,527,873`、`templates/modals/automation.html:242,292,394,603`、`templates/modals/detail_chat_reader.html:569,579,589,599,609,619,971,981,1125,1135`、`templates/modals/detail_preset_fullscreen.html:549,890,1254,1540,1815`、`templates/modals/settings.html:1083,1620,1652,1710,1743,1777`、`templates/modals/tag_filter.html:374,432,1586` | xs/12px | 是 |
| icon-arrow-down | icon-other-arrow-down | static/icons/ui.svg | 箭头下 | `templates/modals/advanced_editor.html:136,334,351,529,875`、`templates/modals/automation.html:243,293,395,604`、`templates/modals/detail_chat_reader.html:570,580,590,600,610,620,972,982,1126,1136`、`templates/modals/detail_preset_fullscreen.html:559,900,1264,1551,1825`、`templates/modals/settings.html:1091,1628,1660,1718,1751,1785`、`templates/modals/tag_filter.html:385,435,1597` | xs/12px | 是 |
| icon-close-bold | icon-other-close | static/icons/ui.svg | 关闭bold | `templates/components/grid_chats.html:35`、`templates/modals/advanced_editor.html:142,519,624,860`、`templates/modals/automation.html:397,606`、`templates/modals/batch_tag.html:10`、`templates/modals/detail_card.html:1579,1621` | xs/12px、sm/16px | 是 |
| icon-arrow-right | icon-other-arrow-right | static/icons/ui.svg | 箭头右 | `templates/modals/advanced_editor.html:655`、`tests/test_advanced_editor_icon_contracts.py:53` | sm/16px | 是 |
| icon-menu-bold | icon-other-menu | static/icons/ui.svg | 菜单bold | `templates/modals/automation.html:198`、`templates/modals/detail_card.html:1572`、`templates/modals/tag_filter.html:417,1763,1792,1821` | xs/12px | 是 |
| icon-check-bold | icon-other-check | static/icons/ui.svg | 勾选bold | `templates/modals/batch_tag.html:69,88`、`templates/modals/detail_preset_popup.html:651,1056`、`templates/modals/tag_filter.html:467,472,529,534…`、`tests/test_common_modal_icon_contracts.py:142`、`tests/test_preset_detail_reader_frontend_contracts.py:430` | xs/12px | 是 |
| icon-minus | icon-other-minus | static/icons/ui.svg | 减号 | `templates/modals/detail_preset_popup.html:652,1057`、`tests/test_common_modal_icon_contracts.py:143`、`tests/test_preset_detail_reader_frontend_contracts.py:431` | xs/12px | 是 |
| icon-alert-triangle | icon-settings-warning | static/icons/ui.svg | 警告三角形 | `templates/modals/batch_import.html:55`、`templates/modals/detail_card.html:2092`、`templates/modals/detail_wi_fullscreen.html:1348,2072`、`templates/modals/import.html:16`、`templates/modals/settings.html:1098,1113,1217` | xs/12px、sm/16px | 是 |
| icon-check | icon-card-check | static/icons/ui.svg | 勾选 | `templates/components/grid_cards.html:177`、`templates/components/grid_presets.html:128`、`templates/components/grid_wi.html:127`、`templates/modals/automation.html:702`、`templates/modals/batch_import.html:138` | xs/12px、sm/16px、lg/24px | 是 |
| icon-external-link | icon-card-external-link | static/icons/ui.svg | 外部链接 | `templates/components/grid_cards.html:218`、`templates/modals/detail_card.html:425,703,3723` | xs/12px、sm/16px | 是 |
| icon-eye | icon-eye | static/icons/ui.svg | 眼睛 | `templates/modals/detail_card.html:886,912,958,984…`、`templates/modals/detail_wi_fullscreen.html:845`、`templates/modals/settings.html:1294,1337,1385`、`tests/test_worldbook_icon_contracts.py:156` | sm/16px | 否 |
| icon-eye-off | icon-eye-off | static/icons/ui.svg | 眼睛隐藏 | `templates/modals/detail_card.html:886,958,1030,1102…`、`templates/modals/settings.html:1293,1336,1384` | sm/16px | 否 |
| icon-folder | icon-card-folder | static/icons/ui.svg | 文件夹 | `templates/components/grid_cards.html:272`、`templates/components/grid_wi.html:190,254`、`templates/components/header.html:297,321,711,784`、`tests/test_header_icon_templates.py:26`、`tests/test_worldbook_icon_contracts.py:137` | sm/16px | 是 |
| icon-settings-help-entry | icon-settings-help-entry | static/icons/ui.svg | 帮助说明入口 | `templates/modals/automation.html:149`、`templates/modals/detail_card.html:338,3495`、`templates/modals/detail_wi_fullscreen.html:314`、`templates/modals/settings.html:31,1888`、`static/js/state.js:84`、`static/js/components/batchImportModal.js:95`、`tests/test_advanced_editor_icon_contracts.py:99` | sm/16px、md/20px、lg/24px | 否 |
| icon-loader-circle | icon-card-loader | static/icons/ui.svg | 加载圆形 | `static/js/components/settingsModal.js:371`、`static/js/components/wiEditor.js:2991`、`templates/components/grid_cards.html:349,366`、`templates/components/grid_extensions.html:63`、`templates/components/grid_presets.html:91,290` | sm/16px、md/20px、lg/24px、xl/32px、2xl/48px | 是 |
| icon-menu | icon-menu | static/icons/ui.svg | 菜单 | `templates/components/header.html:109`、`templates/modals/detail_wi_popup.html:222`、`tests/test_header_icon_templates.py:16` | md/20px | 否 |
| icon-header-dark-mode | icon-header-dark-mode | static/icons/ui.svg | 深色模式装饰星月 | `templates/components/header.html:642,921`、`templates/modals/settings.html:300`、`tests/test_header_icon_templates.py:22`、`tests/test_settings_icon_templates.py:60` | sm/16px、md/20px、lg/24px | 否 |
| icon-package | icon-card-package | static/icons/ui.svg | 软件包 | `templates/components/context_menu.html:58`、`templates/components/grid_cards.html:150`、`templates/modals/detail_card.html:2317,2582,3732`、`tests/test_card_grid_update_contracts.py:88` | xs/12px、sm/16px、lg/24px | 是 |
| icon-palette | icon-palette | static/icons/ui.svg | 调色板 | `templates/modals/settings.html:1958` | sm/16px | 否 |
| icon-plug | icon-plug | static/icons/ui.svg | 插头 | `templates/modals/settings.html:2084` | sm/16px | 否 |
| icon-settings-save | icon-settings-save | static/icons/ui.svg | 个性化保存（软盘） | `templates/modals/automation.html:173`、`templates/modals/detail_wi_fullscreen.html:220,266,513,1904,1916`、`templates/modals/settings.html:1860`、`static/js/state.js:85`、`static/js/components/advancedEditor.js:870`、`static/js/components/automationModal.js:381`、`static/js/components/detailModal.js:1991`、`static/js/components/wiDetailPopup.js:799`、`static/js/components/wiEditor.js:2336,2338,2786,2855,2857`、相关测试契约 | xs/12px、sm/16px | 否 |
| icon-search | icon-card-search | static/icons/ui.svg | 搜索 | `templates/components/grid_cards.html:334`、`tests/test_worldbook_icon_contracts.py:148` | sm/16px（默认） | 是 |
| icon-send | icon-card-send | static/icons/ui.svg | 发送 | `templates/components/grid_cards.html:346`、`templates/components/grid_presets.html:285`、`templates/components/grid_wi.html:228`、`templates/modals/detail_card.html:2574`、`templates/modals/detail_wi_popup.html:467` | sm/16px、md/20px、lg/24px | 是 |
| icon-settings-connection-service | icon-settings-connection-service | static/icons/ui.svg | 连接与服务链路 | `templates/modals/settings.html:76,1229,2105`、`tests/test_settings_icon_templates.py` | sm/16px | 否 |
| icon-shield-check | icon-shield-check | static/icons/ui.svg | 盾牌勾选 | `templates/modals/settings.html:1347` | xs/12px | 否 |
| icon-sticky-note | icon-card-sticky-note | static/icons/ui.svg | sticky备注 | `templates/components/grid_cards.html:324`、`templates/components/grid_wi.html:214`、`templates/modals/detail_wi_fullscreen.html:568`、`tests/test_worldbook_icon_contracts.py:138` | sm/16px、md/20px、xl/32px | 是 |
| icon-header-light-mode | icon-header-light-mode | static/icons/ui.svg | 浅色模式太阳 | `templates/components/header.html:643,922`、`templates/modals/settings.html:301`、`tests/test_header_icon_templates.py:23`、`tests/test_settings_icon_templates.py:61` | sm/16px、md/20px、lg/24px | 否 |
| icon-upload | icon-card-upload | static/icons/ui.svg | 向上箭头（统一用于导出/下载） | `templates/components/grid_presets.html:152`、`grid_wi.html:102`、`templates/modals/advanced_editor.html:130,523`、`automation.html:166`、`detail_card.html:1831`、`detail_wi_popup.html:475` | sm/16px、md/20px | 是 |
| icon-settings-maintenance | icon-settings-maintenance | static/icons/ui.svg | 维护扳手组合 | `templates/modals/settings.html:2204`、`tests/test_settings_icon_templates.py` | sm/16px | 否 |
| static/icons/forum-preview/close.svg | static/icons/forum-preview/close.svg | forum-preview 独立 SVG | 关闭叉 | `static/css/modules/modal-forum-preview.css:139`、`static/css/modules/modal-forum-preview.css:140` | 16px | 否 |
| static/icons/forum-preview/date.svg | static/icons/forum-preview/date.svg | forum-preview 独立 SVG | 日期日历 | `static/css/modules/modal-forum-preview.css:112`、`static/css/modules/modal-forum-preview.css:113` | 16px | 否 |
| static/icons/forum-preview/reaction.svg | static/icons/forum-preview/reaction.svg | forum-preview 独立 SVG | 反应 | `static/css/modules/modal-forum-preview.css:127`、`static/css/modules/modal-forum-preview.css:128` | 16px | 否 |
| static/icons/forum-preview/reply.svg | static/icons/forum-preview/reply.svg | forum-preview 独立 SVG | 回复 | `static/css/modules/modal-forum-preview.css:122`、`static/css/modules/modal-forum-preview.css:123` | 16px | 否 |
| static/icons/forum-preview/time.svg | static/icons/forum-preview/time.svg | forum-preview 独立 SVG | 时间时钟 | `static/css/modules/modal-forum-preview.css:117`、`static/css/modules/modal-forum-preview.css:118` | 16px | 否 |
| static/icons/forum-preview/view.svg | static/icons/forum-preview/view.svg | forum-preview 独立 SVG | 浏览眼睛 | `static/css/modules/modal-forum-preview.css:132`、`static/css/modules/modal-forum-preview.css:133` | 16px | 否 |
<!-- ICON_TABLE_INSERT -->

## 4. 删除清单与安全确认

### 已删除的 symbol

以下 40 个旧 symbol 定义在源文件、模板宏、`<use>`、JavaScript icon map、CSS、测试契约和已核对的动态规则中均无实际引用；其中部分是与最终语义 symbol 不同的旧重复几何，已由实际使用的语义版本覆盖：

| 旧 symbol | 文件 | 删除原因 | 删除前确认范围 |
| --- | --- | --- | --- |
| `icon-alert-triangle`, `icon-archive`, `icon-book-open`, `icon-bot`, `icon-check`, `icon-circle-check`, `icon-clock-3`, `icon-database`, `icon-download`, `icon-external-link`, `icon-folder`, `icon-globe`, `icon-help-circle`, `icon-header-menu`, `icon-image`, `icon-key-round`, `icon-message-circle`, `icon-moon`, `icon-package`, `icon-pencil`, `icon-plus`, `icon-refresh-cw`, `icon-save`, `icon-search`, `icon-send`, `icon-server`, `icon-settings-appearance`, `icon-settings-hide`, `icon-settings-integration`, `icon-settings-security-status`, `icon-settings-show`, `icon-sliders-horizontal`, `icon-sticky-note`, `icon-sun`, `icon-tools`, `icon-trash-2`, `icon-upload`, `icon-wrench` | `static/icons/ui.svg` | 无引用的旧基础/重复定义；保存流程已恢复使用基线中的个性化 `icon-settings-save`，帮助、主题、连接和维护入口已恢复使用基线中的专用视觉图形，通用重复定义不再保留 | `templates/`、`static/js/`、`static/css/`、`core/`、`tests/` 的精确 id/宏/字符串搜索，以及动态 icon map 核对 |
| `icon-detail-character-card` | `static/icons/detail.svg` | 没有详情 sprite、模板、JS、CSS 或测试引用；角色卡图形来自已合并的独立侧边栏 SVG | 同上，并单独核对 `detail_icon` 和角色卡文件路径 |
| `icon-sidebar-beautify` | `static/icons/sidebar.svg` | 旧的业务命名定义无引用；美化入口改用从独立 SVG 移入的 `icon-paint-brush` | 同上，并核对 `sidebar_icon`、CSS mask 和独立文件路径 |

### 已删除的独立文件

| 文件 | 原用途 | 处理结果 | 安全确认 |
| --- | --- | --- | --- |
| `static/icons/sidebar-nav/角色卡-简.svg` | 角色卡侧边栏入口 | 原图形移动为 `sidebar.svg#icon-character-cards`，模板引用已同步 | 全仓库（排除 `tmp/`、`static/vendor/`）精确路径搜索及模板宏检查 |
| `static/icons/sidebar-nav/美化-简.svg` | 美化侧边栏入口 | 原图形移动为 `sidebar.svg#icon-paint-brush`，模板引用已同步 | 全仓库（排除 `tmp/`、`static/vendor/`）精确路径搜索及模板宏检查 |

没有发现“疑似未引用但无法安全确认”的图标。`static/icons/forum-preview/` 下 6 个独立 SVG 虽没有 symbol id，但 CSS `modal-forum-preview.css` 对每个文件都有 `mask-image` 和 `-webkit-mask-image` 引用，因此保留。

## 5. 尺寸挡位清单

| 挡位 | 直接宽高 | 使用场景 | 关联图标/组件 |
| --- | ---: | --- | --- |
| `ui-icon--xs` | 12px × 12px | 统计数字、紧凑元信息、细小辅助状态 | 卡片统计、步骤/辅助提示、紧凑标签 |
| `ui-icon--sm` | 16px × 16px | 普通文字行、表单、导航次级操作和默认 sprite 图标 | 通用操作、详情 tabs、设置项、论坛预览 mask |
| `ui-icon--md` | 20px × 20px | 普通按钮、工具栏、上下文菜单和中密度导航 | `icon-menu`、`icon-close`、`icon-check`、编辑/筛选操作 |
| `ui-icon--lg` | 24px × 24px | 主按钮、详情动作、侧边栏模块入口和卡片操作 | 详情管理、侧边栏入口、卡片操作、preset send |
| `ui-icon--xl` | 32px × 32px | 头部/大工具按钮和资源操作 | monitor、备份、bookmark、header dice |
| `ui-icon--2xl` | 48px × 48px | 读者 loading、大型空状态/应用图标 | reader loader、source monitor、应用图标、marker 大框 |
| `ui-icon--3xl` | 64px × 64px | 页面 loading 和大型空状态 | loading、automation empty、detail/card 空状态 |
| `sidebar` 覆盖挡位 | 16/20/24/32px | 侧边栏自身的导航、筛选和模块切换密度 | sidebar navigation、filter、category menu、资源入口；仍使用统一 class 选择，不按单个图标放大 |
| `marker` 外框 | 48px 或 32px | 提示词 marker 的大/紧凑卡片框 | `preset.svg` 中的字段 marker；图标填充父框，不使用倍率补偿 |
| `forum-mask` | 16px × 16px | 论坛预览统计信息 | `forum-preview/*.svg` 的 CSS mask |

移除的尺寸 hack 包括旧的 `--150`/150% 图标规则、单图标 `width`/`height` 放大、`scale(1.5)`/`scale(1.2)` 等补偿，以及对应模板中的特殊类。普通卡片 hover、选中、翻转、按钮 active 和图片 hover 的 `transform: scale(...)` 仍然保留，因为它们表达交互或内容预览效果，不是图标尺寸补偿；`.ui-icon--spin` 的旋转动画保留；`modal-tools.css` 中的 `scaleX(-1)` 保留为箭头方向语义翻转；dice 图标内部阴影/pip 的 hover scale 保留为图形动画，不改变外层图标尺寸。

## 6. 验证记录

- 全部当前 SVG 已通过 XML 解析，sprite symbol id 全局唯一，所有静态 `<use>` 引用均可解析。
- 已核对 Jinja 图标宏、模板 inline SVG、JavaScript icon map、toast/prompt marker/sidebar resource 的动态拼接规则；动态资源 map 使用 `sidebar.svg#icon-` 前缀拼接，并覆盖全部资源类型。
- 已删除的通用旧 symbol id 和两个旧独立文件路径在项目源代码中已无错误残留；恢复的专用基线 symbol 已在完整清单中列出，删除清单中的原名称仅用于审计记录。
- `templates/layout.html` 不再加载会触发生产环境警告的 `static/lib/tailwindcss.js`，改为加载 `static/css/tailwind.css`；空 Toast 图标通过 `x-if` 延迟创建，避免初始空 id 请求 `/static/icons/`。
- 相关 icon/template 前端契约定向测试：`462 passed in 8.94s`，覆盖改名涉及的 advanced-editor、beautify、sidebar、worldbook、settings、card、preset、通用 modal、动态 icon map、保存图标基线和 Tailwind 静态资源契约。
- 完整 pytest：`1951 passed, 8 failed, 1 warning in 44.64s`。8 个失败均已用 HEAD 基线复现：1 个是既有 detail 模板测试仍期待 `x-if` 而模板实际一直使用 `x-show`；7 个 preset 前端运行测试的 harness 未 stub 既有的 `createMarqueeSelection`，在未改动的 HEAD `presetGrid.js` 上同样失败。它们不是本次 SVG/图标系统改动引入的失败，仍建议后续单独修复测试基线。
- 浏览器只读 smoke 页面在本地 `127.0.0.1:5001` 实际渲染了应用首屏、设置页导航和角色卡帮助指南；帮助层已被 teleport 到 `body`，计算层级为 `z-index: 3400`，位于详情弹窗之上。页面加载了静态 Tailwind CSS，控制台 error/warn 为空，也没有再请求 `/static/icons/` 目录；未见图标消失、裁切或变形。未修改 `tmp/`、`static/vendor/`。
- `git diff --check` 和最终 `git status` 在交付前复核通过。
