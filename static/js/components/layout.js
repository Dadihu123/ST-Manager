/**
 * static/js/components/layout.js
 * 根布局组件：管理浏览状态(筛选/选中)与全局拖拽
 */

import { moveFolder } from '../api/system.js';
import { moveCard } from '../api/card.js';

export default function layout() {
    return {
        // === 代理状态 (为了兼容 HTML 中可能存在的引用) ===
        // === 1. 映射全局状态 (Global Store Proxies) ===
        get serverStatus() { return this.$store.global.serverStatus; },
        get isDarkMode() { return this.$store.global.isDarkMode; },
        get isLoading() { return this.$store.global.isLoading; },
        get toastMessage() { return this.$store.global.toastMessage; },
        get showToastState() { return this.$store.global.showToastState; },
        
        // 映射模式状态
        get currentMode() { return this.$store.global.currentMode; },
        
        // 映射全屏遮罩状态 (如果不属于特定组件)
        get showSettingsModal() { return this.$store.global.showSettingsModal; },
        
        // 映射全局操作 (Actions)
        toggleDarkMode() { this.$store.global.toggleDarkMode(); },

        // 如果 HTML 直接引用了 searchType，这里提供代理
        get searchQuery() { return this.$store.global.viewState.searchQuery; },
        get filterCategory() { return this.$store.global.viewState.filterCategory; },
        get selectedIds() { return this.$store.global.viewState.selectedIds; },
        set selectedIds(val) { this.$store.global.viewState.selectedIds = val; return true; },
        
        // 拖拽状态也建议走 Store，特别是 draggedCards
        get draggedCards() { return this.$store.global.viewState.draggedCards; },
        set draggedCards(val) { this.$store.global.viewState.draggedCards = val; return true; },
        
        get draggedFolder() { return this.$store.global.viewState.draggedFolder; },
        set draggedFolder(val) { this.$store.global.viewState.draggedFolder = val; return true; },

        // 本地 UI 状态 (仅 Layout 自身使用)
        dragCounter: 0,
        dragOverMain: false,      // 主视图拖拽遮罩
        dragOverCat: null,        // 侧边栏文件夹高亮

        // 初始化
        init() {
            // 监听全局快捷键或事件
            window.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && (this.draggedFolder || this.draggedCards.length > 0)) {
                    this.handleGlobalDragEnd();
                }
            });
            // 监听来自其他组件的重置信号
            window.addEventListener('reset-selection', () => {
                this.selectedIds = [];
            });
            // 监听全局拖拽结束事件 (由 Sidebar/Grid 触发)
            window.addEventListener('global-drag-end', () => {
                this.handleGlobalDragEnd();
            });
            
            // 监听 Escape 取消拖拽
            window.addEventListener('keydown', (e) => {
                if (e.key === 'Escape' && (this.draggedFolder || this.draggedCards.length > 0)) {
                    this.handleGlobalDragEnd();
                }
            });
        },

        handleBackgroundClick(e) {
            // 检查点击目标是否是卡片本身或按钮，如果不是，则清空
            if (!e.target.closest('.st-card') && 
                !e.target.closest('button') && 
                !e.target.closest('.clickable-area')) {
                
                this.selectedIds = []; // 清空 Store
            }
        },

        // 切换模式 (Cards / WorldInfo)
        switchMode(mode) {
            this.$store.global.currentMode = mode;
            this.selectedIds = []; // 清空选中
            
            // 触发数据加载 (通过事件通知 Grid 组件)
            if (mode === 'worldinfo') {
                window.dispatchEvent(new CustomEvent('refresh-wi-list'));
            } else {
                window.dispatchEvent(new CustomEvent('refresh-card-list'));
            }
        },

        // === 全局拖拽逻辑 ===

        handleGlobalDragEnd() {
            this.dragCounter = 0;
            this.draggedFolder = null;
            this.dragOverCat = null;
            this.dragOverMain = false;
            this.draggedCards = [];
            
            // 清理 DOM 类名
            document.querySelectorAll('.drag-source').forEach(el => el.classList.remove('drag-source'));
            document.querySelectorAll('.drag-over').forEach(el => el.classList.remove('drag-over'));
            
            if (window.dragImageElement) {
                if(window.dragImageElement.parentNode) window.dragImageElement.parentNode.removeChild(window.dragImageElement);
                window.dragImageElement = null;
            }
        },

        // 根容器拖拽进入 (显示遮罩)
        handleDragEnterRoot(e) {
            this.dragCounter++;
        },

        // 根容器拖拽离开
        handleDragLeaveRoot(e) {
            this.dragCounter--;
            if (this.dragCounter <= 0) {
                this.dragCounter = 0;
                // 注意：这里通常不清除 dragOverMain，因为它由 main area 控制
                // 但可以清除一些全局的高亮
                this.dragOverCat = null;
            }
        },

        // 根容器拖拽悬停 (处理侧边栏根目录高亮)
        handleDragOverRoot(e) {
            e.preventDefault();
            e.stopPropagation();
            
            // 检查拖拽类型是否匹配
            const isCard = e.dataTransfer.types.includes('application/x-st-card');
            const isFolder = !!this.draggedFolder;
            const isFile = e.dataTransfer.files.length > 0;

            if (isCard || isFolder || isFile) {
                // 如果鼠标悬停在“全部卡片”区域 (需要配合 HTML 绑定)
                // 这里逻辑由 Sidebar HTML 中的 @dragover 触发具体赋值
                // 此函数主要作为兜底 preventDefault
            }
        },

        // 根容器放下 (Drop)
        handleDropOnRoot(e) {
            e.preventDefault();
            e.stopPropagation();
            
            this.dragOverCat = null;
            this.dragOverMain = false;
            
            // 1. 卡片拖拽 -> 根目录
            if (this.draggedCards.length > 0) {
                const count = this.draggedCards.length;
                if(confirm(`移动 ${count} 张卡片到根目录?`)) {
                    moveCard({ card_ids: this.draggedCards, target_category: '' })
                        .then(res => {
                            if(res.success) {
                                if(res.category_counts) this.$store.global.categoryCounts = res.category_counts;
                                window.dispatchEvent(new CustomEvent('refresh-card-list'));
                            } else alert(res.msg);
                        });
                }
            }
            // 2. 文件夹 -> 根目录
            else if (this.draggedFolder) {
                const sourceName = this.draggedFolder.split('/').pop();
                if (confirm(`移动文件夹 "${sourceName}" 到根目录?`)) {
                    moveFolder({ 
                        source_path: this.draggedFolder, 
                        target_parent_path: '', 
                        merge_if_exists: false 
                    }).then(res => {
                        if(res.success) window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                        else alert(res.msg);
                    });
                }
            }
            // 3. 外部文件
            else if (e.dataTransfer.files.length > 0) {
                window.dispatchEvent(new CustomEvent('handle-files-drop', { 
                    detail: { event: e, category: '' } 
                }));
            }
            
            this.handleGlobalDragEnd();
        },

        // 仅处理主视图区域的遮罩状态 (由 grid_cards.html 调用)
        handleMainDragEnter(e) {
            this.dragCounter++;
            this.dragOverMain = true;
        },

        handleMainDragLeave(e) {
            this.dragCounter--;
            if (this.dragCounter <= 0) {
                this.dragCounter = 0;
                this.dragOverMain = false;
            }
        }
    }
}