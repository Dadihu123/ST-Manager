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
                this.showImportUrlModal = true;
            });
        },

        importFromUrl() {
            if (!this.importUrlInput.trim()) {
                alert("请输入 URL");
                return;
            }

            this.$store.global.isLoading = true;
            importCardFromUrl({
                url: this.importUrlInput.trim(),
                category: this.importTargetCategory
            })
            .then(res => {
                this.$store.global.isLoading = false;
                
                if (res.success) {
                    this.showImportUrlModal = false;
                    this.importUrlInput = '';
                    
                    if (res.new_card) {
                        window.dispatchEvent(new CustomEvent('card-imported', { detail: res.new_card }));
                        window.dispatchEvent(new CustomEvent('highlight-card', { detail: res.new_card.id }));
                        
                        // 提示
                        const target = this.importTargetCategory || '当前目录';
                        this.$store.global.showToast(`✅ 导入成功：${res.new_card.char_name}`, 3000);
                    }
                } else {
                    alert("导入失败: " + res.msg);
                }
            })
            .catch(err => {
                this.$store.global.isLoading = false;
                alert("网络请求错误: " + err);
            });
        }
    }
}