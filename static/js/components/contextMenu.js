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

export default function contextMenu() {
    return {
        visible: false,
        x: 0,
        y: 0,
        target: null, // path
        type: null,   // 'folder' | 'card'
        targetFolder: null, // 文件夹对象引用
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

                this.type = type;
                this.target = target;
                this.targetFolder = targetFolder;
                this.visible = true;

                window.dispatchEvent(new CustomEvent('load-rulesets-for-menu'));
            });

            // 监听隐藏事件
            window.addEventListener('hide-context-menu', () => {
                this.visible = false;
            });

            // 点击外部自动关闭
            window.addEventListener('click', () => {
                // 弹窗打开时不要被全局 click 立刻关闭，确保可切换复选框并点确认
                if (this.deleteFolderConfirm && this.deleteFolderConfirm.visible) return;
                this.visible = false;
            });
        },

        hideContextMenu() {
            this.visible = false;
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
                    this.$store.global.showToast('执行完成！', 2400, 'card-check');
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                }
            } catch (error) {
                this.$store.global.showToast(error?.message || '批量执行失败', 3600, 'context-close');
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
                    this.$store.global.showToast('检查完成！', 2400, 'card-check');
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                }
            } catch (error) {
                this.$store.global.showToast(error?.message || '批量检查失败', 3600, 'context-close');
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
