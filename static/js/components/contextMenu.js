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

import { ContributionRegistry } from '../contributionRegistry.js';
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
        /** 右键卡片时命中的卡片对象（`context.card` 的语义目标）。 */
        targetCard: null,
        /**
         * v3 贡献菜单树（三个落点，设计 §5.1）：
         * - `context.folder`：右键分类/目录（含根目录）；
         * - `context.card`：右键卡片（宿主卡片网格的右键入口）；
         * - `context.footer`：右键菜单底部（folder/card 共用）。
         *
         * 节点是注册表 `menuTree()` 的产物：`{id,key,label,icon,type,order,
         * enabled,disabledHint,badge,children}`。`when` 不通过的节点仍然返回，
         * 但 `enabled === false`——渲染成可见的置灰项（设计 §4.4.3，不是隐藏）。
         */
        pluginMenuNodes: [],
        pluginCardNodes: [],
        pluginFooterNodes: [],
        /**
         * 当前展开的二级菜单：`''` = 没有，`'ruleset'` = 运行自动化的规则集，
         * 其余是贡献节点的 id。
         *
         * 桌面端是一个**独立的 fixed 浮层**（`[data-context-ruleset-flyout]` /
         * `[data-plugin-contribution-flyout]`），**固定向右展开**，纵向按剩余空间
         * 自适应（放不下就向上延申）。不能就地展开，也不能用 `absolute left-full`：
         * 菜单盒有 `max-height + overflow:auto`（CSS 里还有 overflow:hidden），
         * 子元素会被裁掉——「运行自动化」的规则集子菜单就是这么坏的。
         *
         * 移动端贡献子菜单退化为「弹层内的第二屏」（点父项切内容 + 返回行）。
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
                const { x, y, type, target, targetFolder, targetCard } = e.detail;

                // 边界检测 (防止菜单溢出屏幕)
                const menuWidth = 160;
                const menuHeight = 200;

                this.x = (x + menuWidth > window.innerWidth) ? x - menuWidth : x;
                this.y = (y + menuHeight > window.innerHeight) ? y - menuHeight : y;
                // 子菜单展开会让菜单变高：按落点算出可用的最大高度，内部滚动
                this.menuMaxHeight = Math.max(200, window.innerHeight - this.y - 12);

                this.type = type;
                this.target = target;
                this.targetFolder = targetFolder || null;
                this.targetCard = targetCard || null;
                this.visible = true;

                // 插件贡献菜单：每次打开时重算（`when` 依赖当前模式与右键目标），
                // 并收起上次展开的子菜单
                this.refreshPluginEntries();
                this.resetContributionSubmenu();

                window.dispatchEvent(new CustomEvent('load-rulesets-for-menu'));
            });

            // 贡献注册表变更 → 重算（插件加载 / 禁用 / 配置变更都会触发）
            this._entriesHandler = () => {
                if (this.visible) this.refreshPluginEntries();
            };
            window.addEventListener('contributions:changed', this._entriesHandler);
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
                    this.activeSubmenu === 'ruleset' ? 'ruleset' : 'contribution',
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
                window.removeEventListener('contributions:changed', this._entriesHandler);
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
            this.targetCard = null;
            this.closeSubmenu();
        },

        /** 当前右键目标对应的一级贡献菜单（card / folder 二选一）。 */
        get pluginContextNodes() {
            return this.type === 'card' ? this.pluginCardNodes : this.pluginMenuNodes;
        },

        /** 当前右键目标对应的落点名（调试/测试用）。 */
        get pluginContextPlacement() {
            return this.type === 'card' ? 'context.card' : 'context.folder';
        },

        // === 插件贡献菜单（v3：context.folder / context.card / context.footer） ===

        /** 当前右键目标的贡献上下文（设计 §5.1：`{mode, target, selection}`）。 */
        contributionContext() {
            const mode = this.contributionMode();
            const kind = this.type === 'card' ? 'card' : 'folder';
            const rawTarget = this.target == null ? '' : String(this.target);
            const folder = this.targetFolder || null;
            const card = this.targetCard || null;
            const name = kind === 'card'
                ? String((card && (card.name || card.title || card.card_name)) || rawTarget)
                : String((folder && folder.name) || (rawTarget ? rawTarget.split('/').pop() : '根目录'));
            return {
                mode,
                target: {
                    type: kind,
                    kind,
                    id: rawTarget,
                    name,
                    // 文件夹用 path；卡片沿用 id（两者在宿主里是同一个字符串）。
                    path: kind === 'folder' ? rawTarget : '',
                    mode,
                    ids: kind === 'card' && rawTarget ? [rawTarget] : [],
                },
                // 右键语义是「对目标操作」，与全局卡片选中集无关（恒为 none）。
                selection: { mode: 'none', ids: [] },
            };
        },

        /** 当前工作模式：优先取注册表快照，回退到全局 store。 */
        contributionMode() {
            try {
                const mode = ContributionRegistry.context().mode;
                if (mode) return String(mode);
            } catch (error) {
                // 注册表未初始化时回退，右键菜单不应该因此不可用。
            }
            try {
                return String((this.$store && this.$store.global && this.$store.global.currentMode) || '');
            } catch (error) {
                return '';
            }
        },

        /**
         * 菜单每次打开时按三个落点重算。
         *
         * `when` 由注册表统一求值（D7）：不通过的节点仍然返回但 `enabled === false`，
         * 渲染层负责置灰 + `disabledHint`，不再自己做条件判断。
         */
        refreshPluginEntries() {
            const ctx = this.contributionContext();
            const read = (placement) => {
                try {
                    return ContributionRegistry.menuTree(placement, {
                        contextOverride: ctx,
                        context: ctx,
                    }) || [];
                } catch (error) {
                    console.warn(`[contextMenu] 读取 ${placement} 菜单失败:`, error);
                    return [];
                }
            };
            // 右键分类只出 context.folder；右键卡片只出 context.card。
            this.pluginMenuNodes = this.type === 'card' ? [] : read('context.folder');
            this.pluginCardNodes = this.type === 'card' ? read('context.card') : [];
            this.pluginFooterNodes = read('context.footer');
        },

        /** 菜单每次打开都收起二级浮层（避免沿用上次的展开项）。 */
        resetContributionSubmenu() {
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
            const attr = kind === 'ruleset' ? 'data-context-ruleset-flyout' : 'data-plugin-contribution-flyout';
            return document.querySelector(`[${attr}]`);
        },

        /** 贡献节点图标（资源路径需要 pluginId 才能解析）。 */
        menuNodeIconHtml(node) {
            return buildIcon(String((node && node.icon) || 'circle-dot'), {
                className: 'ui-icon--sm',
                pluginId: String((node && node.pluginId) || ''),
            }).outerHTML;
        },

        /** 节点是否是子菜单（有 children）。 */
        hasMenuChildren(node) {
            return Boolean(node && Array.isArray(node.children) && node.children.length);
        },

        /** 节点是否不可执行（`when` 不通过或被插件 `update` 置为不可用）。 */
        isMenuNodeDisabled(node) {
            return Boolean(node) && (node.enabled === false || node.ok === false);
        },

        /** 节点角标文案：数字超 99 折成 `99+`；对象形态取 `text/inner/value`。 */
        menuNodeBadge(node) {
            const badge = node && node.badge;
            if (badge === null || badge === undefined || badge === '') return '';
            if (typeof badge === 'object') {
                return String(badge.text ?? badge.inner ?? badge.value ?? '');
            }
            const num = Number(badge);
            if (Number.isFinite(num)) return num > 99 ? '99+' : String(num);
            return String(badge);
        },

        /** 置灰项的悬浮说明（设计 §4.4.3：可见但不可点，给原因）。 */
        menuNodeHint(node) {
            if (!node) return '';
            return String(node.disabledHint || node.description || '');
        },

        /** 执行一个可执行节点：统一派发 `contribution:trigger`（S4）。 */
        runPluginNode(node) {
            if (!node || node.type === 'separator' || this.hasMenuChildren(node)) return false;
            if (this.isMenuNodeDisabled(node)) return false;
            this.closeSubmenu();
            this.visible = false;
            window.dispatchEvent(new CustomEvent('contribution:trigger', {
                detail: {
                    pluginId: String(node.pluginId || ''),
                    nodeId: String(node.id || ''),
                    trigger: 'menu',
                    ctx: this.contributionContext(),
                },
            }));
            return true;
        },

        // === 二级浮层（「运行自动化」规则集 / 贡献子菜单共用一套） ===

        /**
         * 打开一个二级浮层（同时只开一个）。
         *
         * 浮层固定向右展开、纵向按剩余空间自适应（见 `utils/flyoutPosition.js`）。
         * 坐标在**渲染后**测量：先让 x-show 生效，再在下一帧量高度。
         *
         * @param {'ruleset'|string} kind `'ruleset'` 或贡献节点 id
         * @param {Event|Element} anchorEl 父项按钮（模板传 `$event.currentTarget`）
         */
        openSubmenu(kind, anchorEl) {
            const target = String(kind || '');
            if (!target) return;
            this.activeSubmenu = target;
            this._submenuAnchor = resolveAnchorElement(anchorEl);
            // 移动端走「弹层第二屏」/ 直接开弹窗，没有浮层可定位
            if (this.isMobile) return;
            const flyoutKind = target === 'ruleset' ? 'ruleset' : 'contribution';
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

        /** 贡献子菜单父项的开关。 */
        toggleContributionSubmenu(node, anchorEl) {
            if (!node || this.isMenuNodeDisabled(node)) return;
            this.toggleSubmenu(String(node.id || ''), anchorEl);
        },

        /** 某个贡献节点是否正在显示二级浮层。 */
        isContributionsubmenuOpen(node) {
            const target = String((node && node.id) || '');
            return Boolean(target) && String(this.activeSubmenu || '') === target;
        },

        /** 移动端第二屏的返回行。 */
        backFromContributionSubmenu() {
            this.closeSubmenu();
        },

        /** 当前显示二级菜单的贡献节点（找不到时返回 null）。 */
        activeContributionNode() {
            const id = String(this.activeSubmenu || '');
            if (!id || id === 'ruleset') return null;
            const trees = [
                this.pluginMenuNodes,
                this.pluginCardNodes,
                this.pluginFooterNodes,
            ];
            for (const tree of trees) {
                const found = (tree || []).find((node) => node && String(node.id || '') === id);
                if (found) return found;
            }
            return null;
        },

        /**
         * 递归展平一棵贡献树，深度 ≤ 3（设计 §4.4.4）。
         * 移动端第二屏与浮层都用它，避免模板里写三层嵌套。
         */
        flattenMenuNodes(nodes, depth = 1) {
            const rows = [];
            for (const node of nodes || []) {
                if (!node || node.type === 'separator') continue;
                rows.push({ node, depth });
                if (node.children && node.children.length && depth < 3) {
                    rows.push(...this.flattenMenuNodes(node.children, depth + 1));
                }
            }
            return rows;
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
