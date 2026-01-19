/**
 * static/js/components/importModal.js
 * URL 导入组件
 */

import { importCardFromUrl } from '../api/card.js';

export default function importModal() {
    return {
        // === 本地状态 ===
        showImportUrlModal: false,
        importUrlInput: '',
        importTargetCategory: '', // 默认为空，表示根目录或跟随视图
        conflictData: null, // 冲突数据

        get allFoldersList() { 
            return this.$store.global.allFoldersList; 
        },

        init() {
            // 监听打开事件
            // 通常由 Header 触发
            window.addEventListener('open-import-url', (e) => {
                // 可以接收默认分类
                this.importTargetCategory = e.detail && e.detail.category ? e.detail.category : '';
                this.importUrlInput = '';
                this.conflictData = null;
                this.showImportUrlModal = true;
            });

            // 监听键盘事件处理快捷键 (Enter/Esc)
            window.addEventListener('keydown', (e) => {
                if (!this.showImportUrlModal) return;
                
                // 如果正处于冲突解决界面
                if (this.conflictData) {
                    if (e.key === 'Enter') {
                        e.preventDefault();
                        this.resolveConflict('rename'); // 默认追加
                    } else if (e.key === 'Escape') {
                        e.preventDefault();
                        this.resolveConflict('cancel'); // 放弃
                    }
                }
            });
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
                        this.$store.global.showToast(`✅ 导入成功：${res.new_card.char_name}`, 3000);
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