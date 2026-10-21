/**
 * static/js/components/contextMenu.js
 * 上下文菜单组件 (右键菜单)
 */

import { deleteFolder } from '../api/system.js';

import { toggleBundleMode } from '../api/card.js';

import {
    isBatchOperationRunning,
    runAutomationBatch,
    runSourceUpdateBatch,
} from '../utils/batchOperations.js';

import { EntryRegistry } from '../entryRegistry.js';
import { PluginSurfaceHost } from '../pluginSurfaceHost.js';
import { icon as buildIcon } from '../uiPrimitives.js';
import { positionFlyoutElement, resolveAnchorElement } from '../utils/flyoutPosition.js';

export default function contextMenu() {
    return {
        visible: false,
        x: 0,
        y: 0,
        target: null, // path
        type: null,   // 'folder' | 'card'
        targetFolder: null, // 文件夹对象引用
        /** 插件声明的 `kind: "context"` 入口（右键菜单项）。 */
        pluginEntries: [],
        /**
         * 当前展开的二级菜单：`''` = 没有，`'ruleset'` = 运行自动化的规则集，
         * 其余是插件分组的 key（形如 `p1::AI 助手`）。
         *
         * 桌面端是一个**独立的 fixed 浮层**（`[data-plugin-group-flyout]` /
         * `[data-context-ruleset-flyout]`），**固定向右展开**，纵向按剩余空间
         * 自适应（放不下就向上延申）。不能就地展开，也不能用 `absolute left-full`：
         * 菜单盒有 `max-height + overflow:auto`（CSS 里还有 overflow:hidden），
         * 子元素会被裁掉——「运行自动化」的规则集子菜单就是这么坏的。
         *
         * 移动端插件分组退化为「弹层内的第二屏」（点父项切内容 + 返回行）。
         */
        activeSubmenu: '',
        /**
         * 菜单内容的最大高度（px）：插件入口较多时菜单会变高，
         * 不钳住就会顶出视口底部，最后几项永远点不到。留 12px 边距。
         */
        menuMaxHeight: 0,
        /** 二级浮层的锚点（父项按钮元素），只用于定位，不参与渲染。 */
        _submenuAnchor: null,
        _entriesHandler: null,
        _keyHandler: null,
        _scrollHandler: null,
        // 删除文件夹确认弹窗状态（包含“是否删除子文件”可选项）
        deleteFolderConfirm: {
            visible: false,
            path: '',
            cardCount: 0,
            hasSubfolders: false,
            deleteChildren: false
        },

        // 设备类型辅助：用于区分移动端样式
        get isMobile() {
            try {
                return this.$store && this.$store.global && this.$store.global.deviceType === 'mobile';
            } catch (e) {
                return false;
            }
        },

        init() {
            // 监听显示事件 (由 Sidebar 触发)
            window.addEventListener('show-context-menu', (e) => {
                const { x, y, type, target, targetFolder } = e.detail;

                // 边界检测 (防止菜单溢出屏幕)
                const menuWidth = 160;
                const menuHeight = 200;

                this.x = (x + menuWidth > window.innerWidth) ? x - menuWidth : x;
                this.y = (y + menuHeight > window.innerHeight) ? y - menuHeight : y;
                // 分组展开会让菜单变高：按落点算出可用的最大高度，内部滚动
                this.menuMaxHeight = Math.max(200, window.innerHeight - this.y - 12);

                this.type = type;
                this.target = target;
                this.targetFolder = targetFolder;
                this.visible = true;

                // 插件 context 入口：每次打开时重算（`when` 依赖当前模式与选中项），
                // 并收起上次展开的插件分组
                this.refreshPluginEntries();
                this.resetPluginGroups();

                window.dispatchEvent(new CustomEvent('load-rulesets-for-menu'));
            });

            // 入口注册表变更 → 重算（插件加载 / 禁用 / 配置变更都会触发）
            this._entriesHandler = () => this.refreshPluginEntries();
            window.addEventListener('entries:changed', this._entriesHandler);
            window.addEventListener('plugins:loaded', this._entriesHandler);

            // 监听隐藏事件
            window.addEventListener('hide-context-menu', () => {
                this.hideContextMenu();
            });

            // Escape 只关二级浮层（没有二级时交给其它处理器，比如弹窗关闭）
            this._keyHandler = (event) => {
                if (event.key !== 'Escape' || !this.activeSubmenu) return;
                event.stopPropagation();
                this.closeSubmenu();
            };
            window.addEventListener('keydown', this._keyHandler, true);

            // 宿主页面 / 菜单盒滚动时父项会跑位，二级浮层直接收起。
            // 浮层自身滚动不算（长列表要能在浮层里滚）。
            this._scrollHandler = (event) => {
                if (!this.activeSubmenu) return;
                const flyout = this.submenuFlyoutEl(
                    this.activeSubmenu === 'ruleset' ? 'ruleset' : 'plugin',
                );
                if (flyout && event.target instanceof Node && flyout.contains(event.target)) return;
                this.closeSubmenu();
            };
            window.addEventListener('scroll', this._scrollHandler, true);

            // 点击外部自动关闭
            window.addEventListener('click', () => {
                // 弹窗打开时不要被全局 click 立刻关闭，确保可切换复选框并点确认
                if (this.deleteFolderConfirm && this.deleteFolderConfirm.visible) return;
                this.hideContextMenu();
            });
        },

        destroy() {
            if (this._entriesHandler) {
                window.removeEventListener('entries:changed', this._entriesHandler);
                window.removeEventListener('plugins:loaded', this._entriesHandler);
                this._entriesHandler = null;
            }
            if (this._keyHandler) {
                window.removeEventListener('keydown', this._keyHandler, true);
                this._keyHandler = null;
            }
            if (this._scrollHandler) {
                window.removeEventListener('scroll', this._scrollHandler, true);
                this._scrollHandler = null;
            }
        },

        hideContextMenu() {
            this.visible = false;
            this.closeSubmenu();
        },

        // === 插件 context 入口（D1：`kind: "context"` 落到右键菜单） ===

        /**
         * 取当前可用的插件 context 入口。
         *
         * `EntryRegistry.list()` 已经做过 `when` 求值（模式、选中项、配置），
         * 返回的每项带 `enabled` 与 `disabledHint`——所以这里不需要自己判断条件，
         * 也不该判断（D7：`when` 统一在注册表求值）。
         *
         * 右键菜单的作用域由**右键目标**决定，与全局卡片选中无关：
         * 右键文件夹 = 对该分类整体操作，右键卡片 = 对那一张操作。
         * 因此这里用 `contextOverride` 覆盖 `targetKind`，让 `when.target` 生效。
         * `selectionCount` 不再推导：右键上下文里 `when.selection` 恒为 none，
         * 把它归零即可（右键卡片的作用域是「右键目标」，不是「选中集」）。
         */
        refreshPluginEntries() {
            try {
                // `menuGroups` 只返回 `when` 通过的入口，并按插件分组折叠：
                // 右键分类时菜单里只出现一个「AI 助手」，子项是打标/归类/精简。
                // 不适用的动作（比如世界书专用的精简在角色卡视图里）直接不出现，
                // 不再渲染成点不动的灰项。
                this.pluginEntries = EntryRegistry.menuGroups({
                    kind: 'context',
                    contextOverride: this.pluginEntryContext(),
                });
            } catch (error) {
                console.warn('[contextMenu] 读取插件 context 入口失败:', error);
                this.pluginEntries = [];
            }
        },

        /** 菜单每次打开都收起二级浮层（避免沿用上次的分组）。 */
        resetPluginGroups() {
            this.closeSubmenu();
        },

        /**
         * 取二级浮层元素。
         *
         * **不能用 `this.$el`**：Alpine 的 `$el` magic 绑定的是「当前表达式所在元素」，
         * 在 `@click` 处理器里发起、`$nextTick` / `requestAnimationFrame` 回调里读取时，
         * 它指向被点的那个按钮（实测拿到 BUTTON，`querySelector` 自然找不到浮层）。
         * 用 data 属性从 document 找：页面上只有一个右键菜单实例。
         */
        submenuFlyoutEl(kind) {
            if (typeof document === 'undefined') return null;
            const attr = kind === 'ruleset' ? 'data-context-ruleset-flyout' : 'data-plugin-group-flyout';
            return document.querySelector(`[${attr}]`);
        },

        /** 右键菜单求值 `when` 用的上下文覆盖（见 `refreshPluginEntries`）。 */
        pluginEntryContext() {
            return {
                targetKind: String(this.type || ''),
                // 右键不是「选中集」语境：全局选中数与本操作无关，必须归零。
                selectionCount: 0,
            };
        },

        /** 右键菜单里的插件项图标（资源路径需要 pluginId 才能解析）。 */
        pluginEntryIcon(entry) {
            return buildIcon(String((entry && entry.icon) || 'circle-dot'), {
                className: 'ui-icon--sm',
                pluginId: String((entry && entry.pluginId) || ''),
            });
        },

        /** 兼容父项（group）与单条入口：父项同样带 icon / pluginId。 */
        pluginEntryIconHtml(entry) {
            const node = entry && entry.type === 'group' ? entry : entry;
            return buildIcon(String((node && node.icon) || 'circle-dot'), {
                className: 'ui-icon--sm',
                pluginId: String((node && node.pluginId) || ''),
            }).outerHTML;
        },

        // === 二级浮层（「运行自动化」规则集 / 插件分组共用一套） ===

        /**
         * 打开一个二级浮层（同时只开一个）。
         *
         * 浮层固定向右展开、纵向按剩余空间自适应（见 `utils/flyoutPosition.js`）。
         * 坐标在**渲染后**测量：先让 x-show 生效，再在下一帧量高度。
         *
         * @param {'ruleset'|string} kind `'ruleset'` 或插件分组的 key
         * @param {Event|Element} anchorEl 父项按钮（模板传 `$event.currentTarget`）
         */
        openSubmenu(kind, anchorEl) {
            const target = String(kind || '');
            if (!target) return;
            this.activeSubmenu = target;
            this._submenuAnchor = resolveAnchorElement(anchorEl);
            // 移动端走「弹层第二屏」/ 直接开弹窗，没有浮层可定位
            if (this.isMobile) return;
            const flyoutKind = target === 'ruleset' ? 'ruleset' : 'plugin';
            this.$nextTick(() => {
                requestAnimationFrame(() => {
                    const flyout = this.submenuFlyoutEl(flyoutKind);
                    if (!flyout || !this._submenuAnchor) return;
                    if (!positionFlyoutElement(flyout, this._submenuAnchor)) {
                        // 首帧还没完成布局，下一帧重试。
                        requestAnimationFrame(() => {
                            const retry = this.submenuFlyoutEl(flyoutKind);
                            if (retry && this._submenuAnchor) {
                                positionFlyoutElement(retry, this._submenuAnchor);
                            }
                        });
                    }
                });
            });
        },

        /** 关闭二级浮层。 */
        closeSubmenu() {
            this.activeSubmenu = '';
            this._submenuAnchor = null;
        },

        /** 同一个父项再点一次就收起（其它情况切到新的那一项）。 */
        toggleSubmenu(kind, anchorEl) {
            const target = String(kind || '');
            if (!target) return;
            if (String(this.activeSubmenu || '') === target) {
                this.closeSubmenu();
                return;
            }
            this.openSubmenu(target, anchorEl);
        },

        /** 「运行自动化」的规则集子菜单开关（桌面端）。 */
        toggleRuleSetSubmenu(anchorEl) {
            window.dispatchEvent(new CustomEvent('load-rulesets-for-menu'));
            this.toggleSubmenu('ruleset', anchorEl);
        },

        /** 插件分组父项的开关。 */
        togglePluginGroup(key, anchorEl) {
            this.toggleSubmenu(String(key || ''), anchorEl);
        },

        /** 某个插件分组是否正在显示二级浮层。 */
        isPluginGroupOpen(key) {
            const target = String(key || '');
            return Boolean(target) && String(this.activeSubmenu || '') === target;
        },

        /** 移动端第二屏的返回行。 */
        backFromPluginGroup() {
            this.closeSubmenu();
        },

        /** 当前显示二级菜单的插件分组单元（找不到时返回 null）。 */
        activePluginGroupUnit() {
            const key = String(this.activeSubmenu || '');
            if (!key || key === 'ruleset') return null;
            return (this.pluginEntries || []).find(
                (unit) => unit && unit.type === 'group' && unit.key === key,
            ) || null;
        },

        /** 分组父项的角标：取组内入口角标之和（只有一个带角标时用它）。 */
        pluginGroupBadge(group) {
            const list = (group && group.entries) || [];
            let total = 0;
            let hasNumeric = false;
            for (const entry of list) {
                const raw = entry && entry.badge;
                if (raw === null || raw === undefined || raw === '') continue;
                const num = Number(raw);
                if (Number.isFinite(num)) {
                    total += num;
                    hasNumeric = true;
                } else {
                    return String(raw);
                }
            }
            if (!hasNumeric) return '';
            return total > 99 ? '99+' : String(total);
        },

        /**
         * 执行一个插件 context 入口。
         *
         * 优先打开插件注册的 surface；没有 surface 时派发 `entry:activate`
         * 交给插件自己处理（与坞 / 命令面板同一套约定，见 `entryDock.js:open`）。
         * 置灰项不执行——但菜单里仍可见并附 `disabledHint`（D7：不是隐藏）。
         *
         * **只传语义目标**：作用域的解析归插件（它有 `api.cards.list` /
         * `api.worldbook.sources`）。宿主在这里同步拉一遍分类卡片列表会让右键
         * 上万张卡片的分类时菜单点不动，而且解析失败与「分类确实为空」都会变成
         * 空数组，插件无法如实报错。
         */
        runPluginEntry(entry) {
            if (!entry || !entry.enabled) return false;

            const surfaceId = (entry.surface && entry.surface.id) || entry.id;
            const surfaceKey = `${entry.pluginId}:${surfaceId}`;
            this.closeSubmenu();
            this.visible = false;

            const kind = String(this.type || '');
            const rawTarget = String(this.target == null ? '' : this.target);
            const target = {
                kind: kind === 'card' ? 'card' : 'folder',
                mode: EntryRegistry.context().mode,
                // `''` 表示根目录，是**合法值**：不能用真值判断来区分「没有目标」，
                // `kind` 才是存在性标志。
                path: kind === 'folder' ? rawTarget : '',
                id: kind === 'card' ? rawTarget : '',
                ids: [],
            };

            if (PluginSurfaceHost.has(surfaceKey)) {
                PluginSurfaceHost.openSurface(surfaceKey, {
                    source: 'context',
                    targetId: entry.id,
                    mode: target.mode,
                    target,
                });
                return true;
            }

            window.dispatchEvent(new CustomEvent('entry:activate', {
                detail: { key: entry.key, entry, source: 'context', target },
            }));
            return true;
        },

        // === 菜单动作 ===

        handleToggleIsolation() {
            if (this.type !== 'folder' || !this.target) return;

            const isIsolated = (this.$store.global.isolatedCategories || []).includes(this.target);
            const action = isIsolated
                ? this.$store.global.removeIsolatedCategory(this.target)
                : this.$store.global.addIsolatedCategory(this.target);

            Promise.resolve(action).finally(() => {
                this.visible = false;
            });
        },

        get targetMode() {
            return this.targetFolder?.mode || this.$store.global.currentMode;
        },

        get targetFolderCapabilities() {
            const path = this.target || '';
            if (this.targetMode === 'worldinfo') {
                return (this.$store.global.wiFolderCapabilities || {})[path] || {};
            }
            if (this.targetMode === 'presets') {
                return (this.$store.global.presetFolderCapabilities || {})[path] || {};
            }
            return {};
        },

        get deleteFolderItemLabel() {
            return (this.deleteFolderConfirm.mode === 'worldinfo' || this.deleteFolderConfirm.mode === 'presets')
                ? '个项目'
                : '张卡片';
        },

        get deleteFolderModeSummary() {
            return (this.deleteFolderConfirm.mode === 'worldinfo' || this.deleteFolderConfirm.mode === 'presets')
                ? '仅支持删除空目录；若目录内仍有项目或子目录，请先清空后再删除。'
                : '未勾选：文件夹解散，内容将移动到上一级目录。已勾选：递归删除内容，并移动到回收站（可恢复；空目录将直接删除）。';
        },

        get supportsRecursiveFolderDelete() {
            return !(this.deleteFolderConfirm.mode === 'worldinfo' || this.deleteFolderConfirm.mode === 'presets');
        },

        getDeleteFolderCount(path) {
            const store = Alpine.store('global');
            if (this.targetMode === 'worldinfo') {
                return (store.wiCategoryCounts && store.wiCategoryCounts[path]) || 0;
            }
            if (this.targetMode === 'presets') {
                return (store.presetCategoryCounts && store.presetCategoryCounts[path]) || 0;
            }
            return (store.categoryCounts && store.categoryCounts[path]) || 0;
        },

        hasDeleteFolderSubfolders(path) {
            const store = Alpine.store('global');
            let folders = [];
            if (this.targetMode === 'worldinfo') {
                folders = store.wiAllFolders || [];
            } else if (this.targetMode === 'presets') {
                folders = store.presetAllFolders || [];
            } else {
                folders = (store.allFoldersList || []).map(f => f.path);
            }
            return folders.some(folderPath => folderPath.startsWith(path + '/') && folderPath !== path);
        },

        handleFolderResponse(res) {
            if (!res?.success) {
                alert(res?.msg || '操作失败');
                return;
            }

            if (this.targetMode === 'worldinfo') {
                this.$store.global.wiAllFolders = res.all_folders || [];
                this.$store.global.wiCategoryCounts = res.category_counts || {};
                this.$store.global.wiFolderCapabilities = res.folder_capabilities || {};
                window.dispatchEvent(new CustomEvent('refresh-wi-list', { detail: { resetPage: false } }));
                return;
            }

            if (this.targetMode === 'presets') {
                this.$store.global.presetAllFolders = res.all_folders || [];
                this.$store.global.presetCategoryCounts = res.category_counts || {};
                this.$store.global.presetFolderCapabilities = res.folder_capabilities || {};
                window.dispatchEvent(new CustomEvent('refresh-preset-list'));
                return;
            }

            window.dispatchEvent(new CustomEvent('refresh-folder-list'));
        },

        // 运行自动化（桌面端）
        async handleRunAuto(rulesetId) {
            if (this.target === null || this.target === undefined) return;
            if (isBatchOperationRunning()) {
                this.$store.global.showToast('已有批量操作正在进行', 2400);
                return;
            }

            const folderName = this.target === '' ? '根目录' : this.target;
            const msg = `确定对 "${folderName}" 下的所有卡片 (包括子文件夹) 执行此自动化规则吗？\n\n注意：这可能会移动大量文件。`;

            if (!confirm(msg)) return;

            // 关闭菜单
            this.visible = false;

            try {
                const result = await runAutomationBatch({
                    rulesetId,
                    targetPayload: { category: this.target, recursive: true },
                    title: `自动处理分类：${folderName}`,
                });
                if (result?.selected) {
                    this.$store.global.showToast('执行完成！', 2400, 'check');
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                }
            } catch (error) {
                this.$store.global.showToast(error?.message || '批量执行失败', 3600, 'close');
            }
        },

        async handleCheckSourceUpdates() {
            if (this.type !== 'folder' || this.target === null || this.target === undefined) return;
            if (isBatchOperationRunning()) {
                this.$store.global.showToast('已有批量操作正在进行', 2400);
                return;
            }

            const folderName = this.target === '' ? '根目录' : this.target;
            const msg = `确定检查“${folderName}”下所有卡片（包括子文件夹）的来源更新吗？\n\n不支持的来源会跳过，网络失败会记录并继续。`;
            if (!confirm(msg)) return;

            this.visible = false;
            try {
                const result = await runSourceUpdateBatch({
                    targetPayload: { category: this.target, recursive: true },
                    title: `检查分类来源更新：${folderName}`,
                });
                if (result?.selected) {
                    this.$store.global.showToast('检查完成！', 2400, 'check');
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                }
            } catch (error) {
                this.$store.global.showToast(error?.message || '批量检查失败', 3600, 'close');
            }
        },

        // 打开移动端执行规则弹窗（文件夹模式）
        handleOpenExecuteRulesMobile() {
            if (this.type !== 'folder' || this.target === null || this.target === undefined) return;
            
            // 关闭菜单
            this.visible = false;
            
            // 触发打开移动端执行规则弹窗事件，传递文件夹信息
            window.dispatchEvent(new CustomEvent('open-execute-rules-mobile-modal', {
                detail: {
                    mode: 'folder',
                    category: this.target,
                    recursive: true
                }
            }));
        },

        // 重命名
        handleRename() {
            if (this.type === 'folder' && this.target) {
                if ((this.targetMode === 'worldinfo' || this.targetMode === 'presets') && !this.targetFolderCapabilities.can_rename_physical_folder) {
                    this.visible = false;
                    return;
                }
                const currentName = this.target.split('/').pop();

                // 直接操作全局 Store
                this.$store.global.folderModals.rename = {
                    visible: true,
                    path: this.target,
                    name: currentName
                };

                this.visible = false;
            }
        },

        // 新建子文件夹
        handleCreateSub() {
            if (this.type === 'folder') {
                if ((this.targetMode === 'worldinfo' || this.targetMode === 'presets') && !this.targetFolderCapabilities.can_create_child_folder) {
                    this.visible = false;
                    return;
                }
                // 直接操作全局 Store
                this.$store.global.folderModals.createSub = {
                    visible: true,
                    parentPath: this.target,
                    name: '',
                    mode: this.targetMode,
                };

                this.visible = false;
            }
        },

        // 删除
        handleDelete() {
            if (this.type === 'folder') {
                if ((this.targetMode === 'worldinfo' || this.targetMode === 'presets') && !this.targetFolderCapabilities.can_delete_physical_folder) {
                    this.visible = false;
                    return;
                }
                const store = Alpine.store('global');
                const path = this.target;

                // 1. 获取卡片计数 (防止 undefined 默认为 0)
                const cardCount = this.getDeleteFolderCount(path);

                // 2. 检查是否有子文件夹
                // 遍历 allFoldersList，看是否有路径以 "path/" 开头的
                const hasSubfolders = this.hasDeleteFolderSubfolders(path);

                // 3. 判断是否需要确认
                // 如果既有卡片又有子文件夹，或者其中之一存在，则需要确认 (因为涉及移动文件)
                // 默认不勾选递归删除子内容（保持原“文件夹解散”行为）
                // 打开自定义确认弹窗：默认不勾选递归删除子内容（保持原“文件夹解散”行为）
                this.deleteFolderConfirm = {
                    visible: true,
                    path: path,
                    cardCount: cardCount,
                    hasSubfolders: hasSubfolders,
                    deleteChildren: false,
                    mode: this.targetMode,
                };
            }
        },
        
        cancelDeleteFolder() {
            this.deleteFolderConfirm.visible = false;
            this.visible = false;
        },

        confirmDeleteFolder() {
            const path = this.deleteFolderConfirm.path;
            const deleteChildren = this.supportsRecursiveFolderDelete && !!this.deleteFolderConfirm.deleteChildren;

            // 关闭弹窗
            this.deleteFolderConfirm.visible = false;
            this.visible = false;

            // 执行删除
            if (this.deleteFolderConfirm.mode === 'worldinfo' || this.deleteFolderConfirm.mode === 'presets') {
                const endpoint = this.deleteFolderConfirm.mode === 'worldinfo'
                    ? '/api/world_info/folders/delete'
                    : '/api/presets/folders/delete';
                fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ category: path })
                })
                    .then(res => res.json())
                    .then(res => this.handleFolderResponse(res))
                    .catch(err => alert(err));
                return;
            }

            deleteFolder({ folder_path: path, delete_children: deleteChildren }).then(res => {
                if (res.success) {
                    // 刷新文件夹树和卡片列表
                    window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                    // 即使是空文件夹，删除后也建议刷新列表，确保同步
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                } else {
                    alert(res.msg);
                }
            });
        },

        // 聚合模式
        handleBundle() {
            if (this.type === 'folder') {
                // Toggle Bundle Mode
                // 1. Check
                toggleBundleMode({ folder_path: this.target, action: 'check' }).then(res => {
                    if (!res.success) return alert(res.msg);

                    if (confirm(`将 "${this.target}" 设为聚合角色包？\n包含 ${res.count} 张图片。`)) {
                        toggleBundleMode({ folder_path: this.target, action: 'enable' }).then(r2 => {
                            if (r2.success) {
                                alert(r2.msg);
                                window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                                window.dispatchEvent(new CustomEvent('refresh-card-list'));
                            } else alert(r2.msg);
                        });
                    }
                });
            }
        }
    }
}
