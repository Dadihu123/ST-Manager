/**
 * static/js/components/moveCardsModal.js
 * 移动卡片弹窗组件
 */

import { moveCard } from '../api/card.js';

export default function moveCardsModal() {
    return {
        showMoveCardsModal: false,
        cardIds: [],
        targetCategory: '',

        get allFoldersList() {
            return this.$store.global.allFoldersList || [];
        },

        init() {
            // 监听打开移动弹窗事件
            window.addEventListener('open-move-cards-modal', (e) => {
                this.cardIds = e.detail && e.detail.ids ? [...e.detail.ids] : [];
                
                if (this.cardIds.length === 0) {
                    // 如果事件没传，尝试直接读 Store (容错)
                    this.cardIds = this.$store.global.viewState.selectedIds || [];
                }

                if (this.cardIds.length === 0) {
                    alert("未选择任何卡片");
                    return;
                }

                // 默认选择当前浏览目录
                this.targetCategory = this.$store.global.viewState.filterCategory || '';
                this.showMoveCardsModal = true;
            });
        },

        // 执行移动操作（参考 cardGrid 的 moveCardsToCategory）
        executeMove() {
            if (this.cardIds.length === 0) return;

            const targetCategory = this.targetCategory === '根目录' ? '' : (this.targetCategory || '');
            const count = this.cardIds.length;
            const targetName = targetCategory || '根目录';

            if (!confirm(`移动 ${count} 张卡片到 "${targetName}"?`)) return;

            this.$store.global.isLoading = true;
            document.body.style.cursor = 'wait';

            moveCard({
                card_ids: this.cardIds,
                target_category: targetCategory
            })
                .then(res => {
                    document.body.style.cursor = 'default';
                    this.$store.global.isLoading = false;
                    
                    if (res.success) {
                        // 更新计数
                        if (res.category_counts) {
                            this.$store.global.categoryCounts = res.category_counts;
                        }
                        // 清空选中
                        this.$store.global.viewState.selectedIds = [];
                        // 关闭弹窗
                        this.showMoveCardsModal = false;
                        // 刷新列表
                        window.dispatchEvent(new CustomEvent('refresh-card-list'));
                        // 显示提示
                        this.$store.global.showToast(`✅ 已移动 ${count} 张卡片`);
                    } else {
                        alert("移动失败: " + res.msg);
                    }
                })
                .catch(err => {
                    document.body.style.cursor = 'default';
                    this.$store.global.isLoading = false;
                    alert("网络请求错误: " + err);
                });
        }
    }
}
