/**
 * static/js/components/batchImportModal.js
 * 批量导入确认模态框 (处理 Stage -> Commit 流程)
 */

export default function batchImportModal() {
    return {
        // === 本地状态 ===
        showBatchImportModal: false,
        isLoading: false,
        
        batchId: null,          // 后端暂存批次 ID
        targetCategory: '',     // 目标分类
        importItems: [],        // 文件列表：{ filename, status, action, existing_info }
        
        // 统计信息
        get conflictCount() {
            return this.importItems.filter(i => i.status === 'conflict').length;
        },
        get totalCount() {
            return this.importItems.length;
        },

        init() {
            // 监听打开事件 (由 cardGrid.js 的 handleFilesDrop 上传 stage 成功后触发)
            window.addEventListener('open-batch-import-modal', (e) => {
                const { batchId, report, category } = e.detail;
                this.openModal(batchId, report, category);
            });
        },

        openModal(batchId, report, category) {
            this.batchId = batchId;
            this.targetCategory = category;
            
            // 初始化列表，设置默认动作
            // status: 'ok' | 'conflict'
            // action: 'import' (默认), 'rename' (追加), 'overwrite' (覆盖), 'skip' (跳过)
            this.importItems = report.map(item => ({
                ...item,
                action: item.status === 'conflict' ? 'rename' : 'import' // 冲突默认重命名，安全第一
            }));

            this.showBatchImportModal = true;
            this.isLoading = false;
        },

        // === 批量操作 ===

        applyToAllConflicts(action) {
            this.importItems.forEach(item => {
                if (item.status === 'conflict') {
                    item.action = action;
                }
            });
        },

        // === 提交逻辑 ===

        commitImport() {
            if (!this.batchId) return;
            this.isLoading = true;

            // 构造 Commit Payload
            const decisions = this.importItems.map(item => ({
                filename: item.filename,
                action: item.action
            }));

            // 这里直接调用 fetch
            fetch('/api/upload/commit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    batch_id: this.batchId,
                    category: this.targetCategory,
                    decisions: decisions
                })
            })
            .then(res => res.json())
            .then(res => {
                this.isLoading = false;
                if (res.success) {
                    this.showBatchImportModal = false;
                    
                    // 1. 发出通知
                    if (res.new_cards && res.new_cards.length > 0) {
                        // 触发列表刷新
                        window.dispatchEvent(new CustomEvent('batch-cards-imported', { 
                            detail: { cards: res.new_cards }
                        }));
                        
                        this.$store.global.showToast(`✅ 成功导入 ${res.new_cards.length} 张卡片`);
                    } else {
                        this.$store.global.showToast("ℹ️ 没有文件被导入 (可能全部跳过)");
                    }

                    // 2. 如果有分类计数更新
                    if (res.category_counts) {
                        this.$store.global.categoryCounts = res.category_counts;
                    }
                } else {
                    alert("导入失败: " + res.msg);
                }
            })
            .catch(err => {
                this.isLoading = false;
                alert("网络错误: " + err);
            });
        },

        cancelImport() {
            // 等待后端定期自动清理 temp
            this.showBatchImportModal = false;
            this.importItems = [];
            this.batchId = null;
        },

        // === 辅助显示 ===
        
        formatSize(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
    }
}