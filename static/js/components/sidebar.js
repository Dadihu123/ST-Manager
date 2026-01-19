/**
 * static/js/components/sidebar.js
 * 侧边栏组件：文件夹树与标签索引
 */

import { createFolder, moveFolder } from '../api/system.js';
import { moveCard } from '../api/card.js';
import { migrateLorebooks } from '../api/wi.js';

export default function sidebar() {
    return {
        // 本地展开状态
        expandedFolders: {},
        dragOverFolder: null,

        // 设备类型和模式
        get deviceType() {
            return this.$store.global.deviceType;
        },
    
        get currentMode() {
            return this.$store.global.currentMode;
        },
    
        get visibleSidebar() {
            return this.$store.global.visibleSidebar;
        },
    
        set visibleSidebar(val) {
            this.$store.global.visibleSidebar = val;
            return true;
        },
        
        get filterCategory() { return this.$store.global.viewState.filterCategory; },
        set filterCategory(val) { this.$store.global.viewState.filterCategory = val; return true; },

        get filterTags() { return this.$store.global.viewState.filterTags; },
        set filterTags(val) { this.$store.global.viewState.filterTags = val; return true; },

        // === 代理拖拽状态 ===
        get draggedCards() { return this.$store.global.viewState.draggedCards; },
        get draggedFolder() { return this.$store.global.viewState.draggedFolder; },
        set draggedFolder(val) { this.$store.global.viewState.draggedFolder = val; return true; },

        get allTagsPool() { return this.$store.global.allTagsPool; },
        get sidebarTagsPool() { return this.$store.global.sidebarTagsPool; },
        get libraryTotal() { return this.$store.global.libraryTotal; },
        get tagSearchQuery() { return this.$store.global.tagSearchQuery; },
        set showTagFilterModal(val) { this.$store.global.showTagFilterModal = val; return true; },

        get wiFilterType() { return this.$store.global.wiFilterType; },

        // 选中状态 (用于清空)
        set selectedIds(val) { this.$store.global.viewState.selectedIds = val; return true; },

        // 计算属性：构建文件夹树 (依赖全局 Store 数据)
        get folderTree() {
            const list = this.$store.global.allFoldersList || [];
            return list.map(folder => {
                let isVisible = true;
                
                // 计算可见性 (父级是否展开)
                if (folder.level > 0) {
                    let parts = folder.path.split('/');
                    let currentPath = '';
                    
                    for (let i = 0; i < parts.length - 1; i++) {
                        currentPath = i === 0 ? parts[i] : `${currentPath}/${parts[i]}`;
                        if (!this.expandedFolders[currentPath]) {
                            isVisible = false;
                            break;
                        }
                    }
                }
                
                return {
                    ...folder,
                    visible: isVisible,
                    expanded: !!this.expandedFolders[folder.path]
                };
            });
        },

        init() {
            window.addEventListener('refresh-folder-list', () => {
                window.dispatchEvent(new CustomEvent('refresh-card-list'));
            });

            // === 监听当前分类变化，自动展开目录树并滚动 ===
            this.$watch('$store.global.viewState.filterCategory', (newPath) => {
                if (!newPath) return;

                // 1. 自动展开父级目录
                const parts = newPath.split('/');
                // 如果路径是 A/B/C，我们需要确保 A 和 A/B 都是展开状态
                let currentPath = '';
                for (let i = 0; i < parts.length - 1; i++) {
                    currentPath = currentPath ? `${currentPath}/${parts[i]}` : parts[i];
                    this.expandedFolders[currentPath] = true;
                }
                // 强制更新对象以触发 Alpine 响应式
                this.expandedFolders = { ...this.expandedFolders };

                // 2. 滚动到对应的文件夹条目
                // 使用 $nextTick 确保 DOM 已经根据 expandedFolders 更新完毕
                this.$nextTick(() => {
                    // 查找侧边栏中所有 active 的元素，取最后一个（通常是当前选中的最深层级）
                    const activeElements = document.querySelectorAll('.sidebar .folder-item.active');
                    if (activeElements.length > 0) {
                        const targetEl = activeElements[activeElements.length - 1];
                        
                        // 使用 scrollIntoView 将其滚动到中间
                        targetEl.scrollIntoView({ 
                            behavior: 'smooth', 
                            block: 'center',
                            inline: 'nearest'
                        });
                    }
                });
            });
            // 初始化sidebar显示状态
            if (this.$store.global.deviceType === "mobile") {
                this.$store.global.visibleSidebar = false;
            }
        },
      
          // 切换侧边栏可见性
        toggleSidebarVisible() {
            this.$store.global.visibleSidebar = !this.$store.global.visibleSidebar;
            // 移动端打开侧边栏时，阻止 body 滚动
            if (this.$store.global.deviceType === "mobile") {
                if (this.$store.global.visibleSidebar) {
                    document.body.style.overflow = "hidden";
                } else {
                    document.body.style.overflow = "";
                }
            }
        },

        openTagFilter() {
            window.dispatchEvent(new CustomEvent('open-tag-filter-modal'));
        },

        // 切换文件夹展开/收起
        toggleFolder(path) {
            this.expandedFolders[path] = !this.expandedFolders[path];
            // 强制更新 (Alpine sometimes needs help with deep object mutation reactivity)
            this.expandedFolders = { ...this.expandedFolders };
        },

        // 设置当前分类
        setCategory(category) {
            // 更新父级 layout 的状态
            this.filterCategory = category;
            this.selectedIds = []; // 清空选中
            
            // 触发 Grid 刷新
            window.dispatchEvent(new CustomEvent('reset-scroll'));
        },

        // 获取分类计数 (从 Store 读取)
        getCategoryCount(category) {
            const counts = this.$store.global.categoryCounts || {};
            if (category === "" || category === "根目录") {
                return counts[""] || 0;
            }
            return counts[category] || 0;
        },

        // === 右键菜单 ===
        showFolderContextMenu(e, folder) {
            e.preventDefault();
            e.stopPropagation();
            // 触发全局右键菜单事件 (ContextMenu 组件会监听)
            window.dispatchEvent(new CustomEvent('show-context-menu', {
                detail: {
                    x: e.clientX,
                    y: e.clientY,
                    type: 'folder',
                    target: folder.path,
                    targetFolder: folder
                }
            }));
        },

        hideContextMenu() {
            window.dispatchEvent(new CustomEvent('hide-context-menu'));
        },

        // === 文件夹 CRUD (通常由模态框回调触发，这里提供逻辑) ===
        // 注意：HTML 中通常调用 $store.global.showCreateFolder = true
        
        createFolder() {
            // 这个函数绑定在模态框的确认按钮上
            const name = this.$store.global.newFolderName;
            const parent = this.$store.global.newFolderParent;
            
            createFolder({ name, parent }).then(res => {
                if (res.success) {
                    // 刷新文件夹列表
                    window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                    this.$store.global.showCreateFolder = false;
                    this.$store.global.newFolderName = '';
                } else {
                    alert(res.msg);
                }
            });
        },

        // === 拖拽逻辑 (Folder Drag) ===

        folderDragStart(e, folder) {
            // 更新 layout 中的拖拽状态
            this.draggedFolder = folder.path;
            
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('application/x-st-folder', folder.path);
            
            // 样式
            e.target.classList.add('drag-source');
            
            const handleDragEnd = () => {
                window.dispatchEvent(new CustomEvent('global-drag-end'));
                e.currentTarget.removeEventListener('dragend', handleDragEnd);
            };
            e.currentTarget.addEventListener('dragend', handleDragEnd);
        },

        folderDragOver(e, folder) {
            e.preventDefault();
            e.stopPropagation();
            
            // 如果正在拖拽卡片，则高亮当前文件夹 (除非是当前所在目录)
            if (this.draggedCards.length > 0) {
                if (folder.path !== this.filterCategory) {
                    this.dragOverFolder = folder.path; // 设置 layout 状态
                }
                return;
            }

            // 文件夹拖拽检查：不能拖到自己或子目录
            if (this.draggedFolder) {
                if (folder.path === this.draggedFolder || 
                    folder.path.startsWith(this.draggedFolder + '/') ||
                    this.draggedFolder.startsWith(folder.path + '/')) {
                    return;
                }
                this.dragOverFolder = folder.path;
            }
        },

        folderDragLeave(e, folder) {
            const relatedTarget = e.relatedTarget;
            if (!relatedTarget || !relatedTarget.closest('.folder-item')) {
                this.dragOverFolder = null;
            }
        },

        folderDrop(e, targetFolder) {
            e.preventDefault();
            e.stopPropagation();
            
            // 清理视觉
            document.querySelectorAll('.drag-source').forEach(el => el.classList.remove('drag-source'));
            this.dragOverCat = null;
            this.dragOverMain = false;
            this.dragOverFolder = null;
            
            // 1. 文件夹 -> 文件夹
            if (this.draggedFolder && targetFolder) {
                if (this.draggedFolder === targetFolder.path) return;
                const sourceName = this.draggedFolder.split('/').pop();
                if (confirm(`移动文件夹 "${sourceName}" 到 "${targetFolder.name}" 下?`)) {
                    moveFolder({
                        source_path: this.draggedFolder,
                        target_parent_path: targetFolder.path,
                        merge_if_exists: false
                    }).then(res => {
                         if (res.success) window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                         else alert(res.msg);
                    });
                }
            }
            // 2. 卡片 -> 文件夹
            else if (this.draggedCards.length > 0 && targetFolder) {
                const targetName = targetFolder.name;
                const count = this.draggedCards.length;
                
                if (confirm(`移动 ${count} 张卡片到 "${targetName}"?`)) {
                    moveCard({
                        card_ids: this.draggedCards,
                        target_category: targetFolder.path
                    }).then(res => {
                        if(res.success) {
                            // 更新计数
                            if(res.category_counts) this.$store.global.categoryCounts = res.category_counts;
                            window.dispatchEvent(new CustomEvent('refresh-card-list'));
                        } else alert(res.msg);
                    });
                }
            }
            // 3. 外部文件 -> 文件夹
            else if (e.dataTransfer.files.length > 0 && targetFolder) {
                window.dispatchEvent(new CustomEvent('handle-files-drop', { 
                    detail: { event: e, category: targetFolder.path } 
                }));
            }

            // 触发全局清理
            window.dispatchEvent(new CustomEvent('global-drag-end'));
        },

        // === 标签云 ===

        toggleFilterTag(t) {
            // 操作 layout 中的 filterTags
            let tags = [...this.filterTags];
            if (tags.includes(t)) {
                tags = tags.filter(x => x !== t);
            } else {
                tags.push(t);
            }

            this.filterTags = tags; // 触发更新
            
            // 刷新 Grid
            window.dispatchEvent(new CustomEvent('reset-scroll'));
        },

        // === 世界书侧边栏逻辑 ===

        setWiFilter(type) {
            this.$store.global.wiFilterType = type;
        },

        migrateLorebooks() {
            if(!confirm("这将扫描所有角色资源目录，并将散乱的 JSON 世界书移动到 'lorebooks' 子文件夹中。\n是否继续？")) return;
            
            migrateLorebooks().then(res => {
                alert(`整理完成，共移动了 ${res.count} 个文件。`);
                window.dispatchEvent(new CustomEvent('refresh-wi-list'));
            });
        }
    }
}