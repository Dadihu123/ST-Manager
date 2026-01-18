/**
 * static/js/components/header.js
 * 顶部导航栏组件
 */

import { getRandomCard } from '../api/card.js';
import { batchUpdateTags } from '../api/system.js';

export default function header() {
    return {
        get searchQuery() { return this.$store.global.viewState.searchQuery; },
        set searchQuery(val) { this.$store.global.viewState.searchQuery = val; },

        get wiSearchQuery() { return this.$store.global.wiSearchQuery; },
        set wiSearchQuery(val) { this.$store.global.wiSearchQuery = val; },

        get searchType() { return this.$store.global.viewState.searchType; },
        set searchType(val) { this.$store.global.viewState.searchType = val; },

        get filterTags() { return this.$store.global.viewState.filterTags; },
        set filterTags(val) { this.$store.global.viewState.filterTags = val; },

        get recursiveFilter() { return this.$store.global.viewState.recursiveFilter; },
        set recursiveFilter(val) { this.$store.global.viewState.recursiveFilter = val; },

        get selectedIds() { return this.$store.global.viewState.selectedIds; },
        set selectedIds(val) { this.$store.global.viewState.selectedIds = val; },

        isCheckingFavs: false,
        favUpdateCount: 0,
        favUpdates: [],

        fetchCards() {
            window.dispatchEvent(new CustomEvent('refresh-card-list'));
        },

        fetchWorldInfoList() {
            window.dispatchEvent(new CustomEvent('refresh-wi-list'));
        },

        get showImportUrlModal() {
            // 这里返回什么不重要，因为弹窗状态由 importModal 组件自己管理
            return false; 
        },
        set showImportUrlModal(val) {
            if (val) {
                // 获取当前浏览的分类作为默认导入位置
                const currentCat = this.$store.global.viewState.filterCategory;
                // 触发 importModal 打开
                window.dispatchEvent(new CustomEvent('open-import-url', { 
                    detail: { category: currentCat } 
                }));
            }
        },

        // 打开设置模态框
        openSettings() {
            this.$store.global.showSettingsModal = true;
        },

        async checkAllFavUpdates() {
            if (this.isCheckingFavs) return;
            
            const { checkFavUpdates } = await import('../api/card.js');
            
            this.isCheckingFavs = true;
            this.favUpdateCount = 0;
            this.favUpdates = [];
            
            try {
                const res = await checkFavUpdates();
                if (res.success) {
                    this.favUpdates = res.updates;
                    this.favUpdateCount = res.updates.length;
                    
                    if (this.favUpdateCount === 0) {
                        this.$store.global.showToast('✅ 收藏卡片目前均是最新版本');
                    } else {
                        const names = res.updates.map(u => u.name).join('、');
                        if (confirm(`检测到 ${this.favUpdateCount} 张收藏卡片有更新：\n${names}\n\n是否打开详情逐个查看？(可点击详情中的来源链接手动前往下载)`)) {
                            // 标记这些卡片
                            this.$store.global.showToast(`✨ 发现 ${this.favUpdateCount} 条更新，已在列表标记`);
                            // 这里可以触发一个全局事件，让 CardGrid 组件高亮这些卡片，或者直接过滤显示它们
                            this.$store.global.viewState.searchQuery = names.split('、')[0]; // 简单引导
                        }
                    }
                } else {
                    alert('批量检测失败: ' + res.msg);
                }
            } catch (err) {
                console.error(err);
                alert('检测出错: ' + err);
            } finally {
                this.isCheckingFavs = false;
            }
        },

        openBatchTagModal() {
            if (this.selectedIds.length === 0) return;
            
            // 派发事件，将 Store 中的 selectedIds 传给 Modal
            window.dispatchEvent(new CustomEvent('open-batch-tag-modal', { 
                detail: { ids: [...this.selectedIds] } 
            }));
        },

        // 触发导入弹窗
        triggerImport() {
            if (this.currentMode !== 'cards') {
                alert('暂不支持世界书URL导入');
                return;
            }
            
            // 获取当前浏览的分类 (作为默认导入位置)
            const currentCat = this.$store.global.viewState.filterCategory;
            
            window.dispatchEvent(new CustomEvent('open-import-url', { 
                detail: { category: currentCat } 
            }));
        },

        deleteSelectedCards() {
            const ids = this.selectedIds;
            if (ids.length === 0) return;
            
            // 复用 CardGrid 的删除逻辑不太方便，建议直接调用 API
            import('../api/card.js').then(module => {
                const { deleteCards } = module;
                
                if (!confirm(`确定将选中的 ${ids.length} 张卡片移至回收站吗？`)) return;

                deleteCards(ids).then(res => {
                    if (res.success) {
                        this.$store.global.showToast(`🗑️ 已删除 ${ids.length} 张卡片`);
                        this.selectedIds = []; // 清空 Store
                        window.dispatchEvent(new CustomEvent('refresh-card-list')); // 通知 Grid 刷新
                    } else {
                        alert("删除失败: " + res.msg);
                    }
                });
            });
        },

        // 随机抽取角色卡
        randomCard() {
            if (this.$store.global.isLoading) return;
            this.$store.global.isLoading = true;

            const vs = this.$store.global.viewState;

            // 使用 layout 中的筛选条件
            const params = {
                category: vs.filterCategory, // 访问父级 scope
                tags: vs.filterTags,
                search: vs.searchQuery,
                search_type: vs.searchType
            };

            getRandomCard(params)
                .then(res => {
                    this.$store.global.isLoading = false;
                    if (res.success && res.card) {
                        // 触发打开详情页事件
                        window.dispatchEvent(new CustomEvent('open-detail', { detail: res.card }));
                        
                        // 高亮逻辑交给 Grid 监听
                        window.dispatchEvent(new CustomEvent('highlight-card', { detail: res.card.id }));
                    } else {
                        alert("抽取失败: " + (res.msg || "未知错误"));
                    }
                })
                .catch(err => {
                    this.$store.global.isLoading = false;
                    alert("网络错误: " + err);
                });
        },

        // 随机世界书
        randomWorldInfo() {
            // 世界书列表在 State 中，可以直接取
            const list = this.$store.global.wiList || [];
            if (list.length === 0) return;
            
            const item = list[Math.floor(Math.random() * list.length)];
            
            if (item.type === 'embedded') {
                // 触发跳转事件
                window.dispatchEvent(new CustomEvent('jump-to-card-wi', { detail: item.card_id }));
                alert(`随机选中了内嵌世界书: ${item.name}\n即将跳转到对应角色卡...`);
            } else {
                // 打开编辑器事件
                window.dispatchEvent(new CustomEvent('open-wi-editor', { detail: item }));
            }
        },

        // 删除当前筛选的所有标签 (批量操作)
        deleteFilterTags() {
            if (this.filterTags.length === 0) {
                return alert("请先选择要删除的标签");
            }
            
            if (this.selectedIds.length === 0) {
                 return alert("请先全选或选中卡片，再执行批量删除标签操作。");
            }

            if (!confirm(`确定从选中的 ${this.selectedIds.length} 张卡片中移除标签: ${this.filterTags.join(', ')}?`)) return;

            batchUpdateTags({
                card_ids: this.selectedIds,
                remove: this.filterTags
            }).then(res => {
                if (res.success) {
                    alert(`成功更新 ${res.updated} 张卡片`);
                    this.filterTags = []; // 清空筛选
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                } else {
                    alert(res.msg);
                }
            });
        },

        // 切换递归筛选
        toggleRecursiveFilter() {
            this.recursiveFilter = !this.recursiveFilter;
        }
    }
}