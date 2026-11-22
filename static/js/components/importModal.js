/**
 * static/js/components/importModal.js
 * URL 导入组件
 */

import { createCharacterCard, getCardIndexJobStatus, importCardFromUrl } from '../api/card.js';

export default function importModal() {
    return {
        // === 本地状态 ===
        showImportUrlModal: false,
        importUrlInput: '',
        importTargetCategory: '', // 默认为空，表示根目录或跟随视图
        conflictData: null, // 冲突数据
        categoryMenuOpen: false,
        createCardMode: false,
        newCardName: '',
        newCardCover: 'unknown',
        newCardError: '',
        creatingCard: false,

        get allFoldersList() { 
            return this.$store.global.allFoldersList; 
        },

        init() {
            // 监听打开事件
            // 通常由 Header 触发
            window.addEventListener('open-import-url', (e) => {
                if (this.creatingCard) return;
                this.createCardMode = false;
                // 可以接收默认分类
                this.importTargetCategory = e.detail && e.detail.category ? e.detail.category : '';
                this.importUrlInput = e.detail && e.detail.url ? e.detail.url : '';
                this.conflictData = null;
                this.categoryMenuOpen = false;
                this.showImportUrlModal = true;
            });
            window.addEventListener('open-create-card', () => {
                if (this.creatingCard) return;
                this.createCardMode = true;
                this.newCardName = '';
                this.newCardCover = 'unknown';
                this.newCardError = '';
                this.conflictData = null;
                this.categoryMenuOpen = false;
                this.importTargetCategory = this.$store.global.viewState.filterCategory || '';
                this.showImportUrlModal = true;
                this.$nextTick(() => this.$refs.newCardName?.focus());
            });

            // 监听键盘事件处理快捷键 (Enter/Esc)
            window.addEventListener('keydown', (e) => {
                if (!this.showImportUrlModal) return;
                if (this.createCardMode) {
                    if (e.key === 'Escape') {
                        e.preventDefault();
                        if (this.categoryMenuOpen) this.categoryMenuOpen = false;
                        else this.closeImportModal();
                    }
                    return;
                }
                
                // 如果正处于冲突解决界面
                if (this.conflictData) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        this.resolveConflict('rename'); // 默认追加
                    } else if (e.key === 'Escape') {
                        e.preventDefault();
                        this.resolveConflict('cancel'); // 放弃
                    }
                } else if (e.key === 'Escape' && this.categoryMenuOpen) {
                    e.preventDefault();
                    this.categoryMenuOpen = false;
                }
            });
        },

        closeImportModal() {
            if (!this.creatingCard) this.showImportUrlModal = false;
        },

        async createCard() {
            if (this.creatingCard) return;
            this.newCardError = '';
            this.creatingCard = true;
            try {
                const result = await createCharacterCard({
                    name: this.newCardName.trim(),
                    cover: this.newCardCover,
                    category: this.importTargetCategory === '根目录' ? '' : this.importTargetCategory,
                });
                if (!result.success) {
                    this.newCardError = result.msg || '创建角色卡失败';
                    return;
                }
                this.showImportUrlModal = false;
                window.dispatchEvent(new CustomEvent('card-imported', { detail: result.new_card }));
                if (result.new_card.index_ready) {
                    window.dispatchEvent(new Event('refresh-card-list'));
                } else if (result.new_card.index_sync_pending) {
                    this.refreshCreatedCardWhenIndexed(result.new_card.id);
                } else {
                    this.$store.global.showToast('角色卡已创建，但列表索引重建未排队，请稍后刷新', 4500, 'warning');
                }
                window.dispatchEvent(new CustomEvent('open-detail', {
                    detail: { ...result.new_card, editOnOpen: true },
                }));
            } catch (error) {
                this.newCardError = '无法创建角色卡，请重试';
            } finally {
                this.creatingCard = false;
            }
        },

        refreshCreatedCardWhenIndexed(cardId, attempt = 0) {
            const delays = [1000, 2000, 4000, 8000, 15000, 30000, 30000, 30000];
            if (attempt >= delays.length) {
                this.$store.global.showToast('角色卡索引仍在重试，稍后请刷新列表', 4500, 'warning');
                return;
            }
            setTimeout(async () => {
                try {
                    const status = await getCardIndexJobStatus(cardId);
                    if (status.success && !status.pending) {
                        window.dispatchEvent(new Event('refresh-card-list'));
                        return;
                    }
                } catch (_error) {
                    // Keep polling through transient status-request failures.
                }
                this.refreshCreatedCardWhenIndexed(cardId, attempt + 1);
            }, delays[attempt]);
        },

        importFromUrl() {
            if (!this.importUrlInput.trim()) {
                alert("请输入 URL");
                return;
            }
            this.doImport('check');
        },

        doImport(resolution, tempFilename = null) {
            this.$store.global.isLoading = true;

            const payload = {
                url: this.importUrlInput.trim(),
                category: this.importTargetCategory,
                resolution: resolution
            };

            if (tempFilename) {
                payload.temp_filename = tempFilename;
            }

            importCardFromUrl(payload)
            .then(res => {
                this.$store.global.isLoading = false;
                
                if (res.success) {
                    // 如果是取消操作，只需关闭
                    if (resolution === 'cancel') {
                        this.conflictData = null;
                        this.showImportUrlModal = false;
                        this.importUrlInput = '';
                        return;
                    }

                    this.showImportUrlModal = false;
                    this.importUrlInput = '';
                    this.conflictData = null;
                    
                    if (res.new_card) {
                        window.dispatchEvent(new CustomEvent('card-imported', { detail: res.new_card }));
                        window.dispatchEvent(new CustomEvent('highlight-card', { detail: res.new_card.id }));
                        
                        if (res.category_counts) {
                            this.$store.global.categoryCounts = res.category_counts;
                        }
                        // 提示
                        this.$store.global.showToast(`导入成功：${res.new_card.char_name}`, 3000, 'check');
                    }
                } else if (res.status === 'conflict') {
                    // 进入冲突解决流程
                    this.conflictData = res;
                } else {
                    alert("导入失败: " + res.msg);
                }
            })
            .catch(err => {
                this.$store.global.isLoading = false;
                alert("网络请求错误: " + err);
            });
        },

        resolveConflict(action) {
            if (!this.conflictData) return;
            
            // action: 'rename' (追加), 'overwrite' (替换), 'cancel' (放弃)
            this.doImport(action, this.conflictData.temp_filename);
        }
    }
}
