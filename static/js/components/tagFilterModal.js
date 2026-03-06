/**
 * static/js/components/tagFilterModal.js
 * 标签管理模态框 (查看全库标签/删除标签)
 */

import { deleteTags } from '../api/system.js';
import { getTagOrder } from '../api/system.js';
import { saveTagOrder } from '../api/system.js';

export default function tagFilterModal() {
    return {
        // === 本地状态 ===
        showTagFilterModal: false,
        tagSearchQuery: '',
        customOrderEnabled: false,
        _syncClosing: false,

        // 排序模式（仅全量标签库）
        isSortMode: false,
        sortWorkingTags: [],
        sortOriginalTags: [],
        dragTag: null,
        dragOverTag: null,
        
        // 删除模式状态
        isDeleteMode: false,
        selectedTagsForDeletion: [],

        get sidebarTagsPool() {
            return this.$store.global.sidebarTagsPool || [];
        },

        get globalTagsPool() {
            return this.$store.global.globalTagsPool || [];
        },

        // 获取过滤后的标签池 (搜索用)
        get filteredTagsPool() {
            const query = this.tagSearchQuery || '';
            const pool = this.sidebarTagsPool || []; // 使用侧边栏专用池
            if (!query) return pool;
            return pool.filter(t => t.toLowerCase().includes(query.toLowerCase()));
        },

        get sortModeTagsPool() {
            return this.sortWorkingTags || [];
        },

        get isSortDirty() {
            const a = this.sortWorkingTags || [];
            const b = this.sortOriginalTags || [];
            if (a.length !== b.length) return true;
            for (let i = 0; i < a.length; i += 1) {
                if (a[i] !== b[i]) return true;
            }
            return false;
        },

        get filterTags() { return this.$store.global.viewState.filterTags; },
        set filterTags(val) { this.$store.global.viewState.filterTags = val; },

        init() {
            this.$watch('$store.global.showTagFilterModal', (val) => {
                if (this._syncClosing) return;

                if (val) {
                    this.showTagFilterModal = true;
                    this.loadTagOrderMeta();
                    return;
                }

                this.showTagFilterModal = val;
                if (!val) {
                    if (this.isSortMode && this.isSortDirty) {
                        const ok = confirm('当前排序尚未保存，关闭后将丢失改动。确定关闭吗？');
                        if (!ok) {
                            this.$store.global.showTagFilterModal = true;
                            this.showTagFilterModal = true;
                            return;
                        }
                    }
                    this.isDeleteMode = false;
                    this.isSortMode = false;
                    this.selectedTagsForDeletion = [];
                    this.sortWorkingTags = [];
                    this.sortOriginalTags = [];
                    this.dragTag = null;
                    this.dragOverTag = null;
                }
            });
            
            // 双向绑定：组件关闭时更新 store
            this.$watch('showTagFilterModal', (val) => {
                this.$store.global.showTagFilterModal = val;
            });

            window.addEventListener('open-tag-filter-modal', () => {
                this.showTagFilterModal = true;
                this.$store.global.showTagFilterModal = true;
                this.loadTagOrderMeta();
            });
        },

        loadTagOrderMeta() {
            getTagOrder()
                .then((res) => {
                    if (!res || !res.success) return;
                    this.customOrderEnabled = !!res.enabled;
                })
                .catch(() => {});
        },

        requestCloseModal() {
            if (this.isSortMode && this.isSortDirty) {
                const ok = confirm('当前排序尚未保存，关闭后将丢失改动。确定关闭吗？');
                if (!ok) return;
            }

            this._syncClosing = true;
            this.showTagFilterModal = false;
            this.$store.global.showTagFilterModal = false;
            this._syncClosing = false;
        },

        toggleFilterTag(tag, event = null) {
            this.$store.global.toggleFilterTag(tag, {
                forceExclude: !!(event && event.shiftKey)
            });
        },

        toggleSortMode() {
            if (this.isDeleteMode) {
                alert('删除模式下无法排序，请先退出删除模式');
                return;
            }

            if (this.isSortMode) {
                this.cancelSortMode();
                return;
            }

            this.isSortMode = true;
            this.tagSearchQuery = '';
            this.sortWorkingTags = [...(this.globalTagsPool || [])];
            this.sortOriginalTags = [...this.sortWorkingTags];
            this.dragTag = null;
            this.dragOverTag = null;
        },

        cancelSortMode() {
            if (this.isSortDirty) {
                const ok = confirm('当前排序尚未保存，确定放弃改动吗？');
                if (!ok) return;
            }
            this.isSortMode = false;
            this.sortWorkingTags = [];
            this.sortOriginalTags = [];
            this.dragTag = null;
            this.dragOverTag = null;
        },

        onSortDragStart(e, tag) {
            if (!this.isSortMode) return;
            this.dragTag = tag;
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', tag);
        },

        onSortDragOver(e, tag) {
            if (!this.isSortMode) return;
            e.preventDefault();
            this.dragOverTag = tag;
        },

        onSortDrop(e, targetTag) {
            if (!this.isSortMode) return;
            e.preventDefault();
            const sourceTag = this.dragTag || e.dataTransfer.getData('text/plain');
            if (!sourceTag || !targetTag || sourceTag === targetTag) return;

            const list = [...this.sortWorkingTags];
            const from = list.indexOf(sourceTag);
            const to = list.indexOf(targetTag);
            if (from < 0 || to < 0) return;

            list.splice(from, 1);
            const targetIndex = list.indexOf(targetTag);
            list.splice(targetIndex, 0, sourceTag);
            this.sortWorkingTags = list;
            this.dragOverTag = null;
        },

        onSortDragEnd() {
            this.dragTag = null;
            this.dragOverTag = null;
        },

        saveSortMode() {
            if (!this.isSortMode) return;

            const nextOrder = [...this.sortWorkingTags];
            saveTagOrder({ order: nextOrder, enabled: true })
                .then((res) => {
                    if (!res.success) {
                        alert('保存排序失败: ' + (res.msg || '未知错误'));
                        return;
                    }

                    this.$store.global.globalTagsPool = [...nextOrder];

                    const sidebarSet = new Set(this.$store.global.sidebarTagsPool || []);
                    const orderedSidebar = nextOrder.filter(t => sidebarSet.has(t));
                    this.$store.global.sidebarTagsPool = orderedSidebar;
                    this.$store.global.allTagsPool = orderedSidebar;
                    this.customOrderEnabled = true;
                    this.sortOriginalTags = [...nextOrder];

                    this.$store.global.showToast('✅ 标签顺序已保存', 1800);
                    this.cancelSortMode();
                })
                .catch((err) => {
                    alert('保存排序失败: ' + err);
                });
        },

        clearCustomOrder() {
            if (this.isSortMode && this.isSortDirty) {
                const ok = confirm('当前排序尚未保存，清除自定义排序会丢失这些改动。确定继续吗？');
                if (!ok) return;
            }

            if (!confirm('确定清除自定义标签排序并恢复字符排序吗？')) return;

            saveTagOrder({ order: [], enabled: false })
                .then((res) => {
                    if (!res.success) {
                        alert('清除自定义排序失败: ' + (res.msg || '未知错误'));
                        return;
                    }

                    this.customOrderEnabled = false;
                    this.isSortMode = false;
                    this.sortWorkingTags = [];
                    this.sortOriginalTags = [];
                    this.dragTag = null;
                    this.dragOverTag = null;

                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    this.$store.global.showToast('✅ 已恢复字符排序', 1800);
                })
                .catch((err) => {
                    alert('清除自定义排序失败: ' + err);
                });
        },

        // === 删除模式逻辑 ===

        toggleDeleteMode() {
            if (this.isSortMode) {
                alert('排序模式下无法删除，请先取消排序');
                return;
            }

            this.isDeleteMode = !this.isDeleteMode;
            if (!this.isDeleteMode) {
                this.selectedTagsForDeletion = []; // 退出时清空
            }
        },

        toggleTagSelectionForDeletion(tag) {
            const index = this.selectedTagsForDeletion.indexOf(tag);
            if (index > -1) {
                this.selectedTagsForDeletion.splice(index, 1);
            } else {
                this.selectedTagsForDeletion.push(tag);
            }
        },

        // 从当前视图的卡片中移除选中的标签
        deleteFilterTags() {
            // 合并包含和排除的标签
            const includeTags = this.$store.global.viewState.filterTags;
            const excludeTags = this.$store.global.viewState.excludedTags;

            // 合并并去重
            const tags = [...new Set([...includeTags, ...excludeTags])];
            
            if (!tags || tags.length === 0) {
                alert("请先选择要删除的标签");
                return;
            }
            
            // 派发事件给 CardGrid 处理（因为只有 CardGrid 知道当前显示了哪些卡片 ID）
            window.dispatchEvent(new CustomEvent('req-batch-remove-current-tags', {
                detail: { tags: [...tags] }
            }));
        },

        deleteSelectedTags() {
            if (this.selectedTagsForDeletion.length === 0) {
                alert("请先选择要删除的标签");
                return;
            }
            
            const tagsToDelete = this.selectedTagsForDeletion.join(', ');
            
            // 获取当前分类 (从全局状态)
            const currentCategory = this.$store.global.viewState.filterCategory;
            const scopeText = currentCategory ? `"${currentCategory}" 分类下` : "所有";
            
            const confirmMsg = `⚠️ 警告：确定要从【${scopeText}】的角色卡中移除以下标签吗？\n\n${tagsToDelete}\n\n此操作不可撤销！`;
            
            if (!confirm(confirmMsg)) return;
            
            deleteTags({ 
                tags: this.selectedTagsForDeletion,
                category: currentCategory 
            })
            .then(res => {
                if (res.success) {
                    alert(`成功删除 ${res.total_tags_deleted} 个标签，更新了 ${res.updated_cards} 张卡片`);
                    
                    // 1. 更新全局标签池
                    const globalPool = this.$store.global.globalTagsPool || [];
                    const sidebarPool = this.$store.global.sidebarTagsPool || [];
                    
                    this.$store.global.globalTagsPool = globalPool.filter(t => !this.selectedTagsForDeletion.includes(t));
                    this.$store.global.sidebarTagsPool = sidebarPool.filter(t => !this.selectedTagsForDeletion.includes(t));
                    this.$store.global.allTagsPool = this.$store.global.sidebarTagsPool;

                    // 2. 更新 Layout 中的筛选标签 (如果正好删除了当前正在筛选的标签)
                    // 需要访问 Layout 状态，这里通过事件通知
                    // 其实 Layout 可以自己监听 refresh-card-list 并重新校验 tags，这里简单触发刷新即可
                    
                    // 3. 清空选择
                    this.selectedTagsForDeletion = [];
                    this.isDeleteMode = false;
                    
                    // 4. 刷新列表
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                } else {
                    alert("删除失败: " + res.msg);
                }
            })
            .catch(err => {
                alert("网络错误: " + err);
            });
        }
    }
}
