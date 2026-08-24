/**
 * static/js/components/executeRulesMobileModal.js
 * 移动端执行规则弹窗组件
 */

import { listRuleSets } from '../api/automation.js';
import {
    isBatchOperationRunning,
    runAutomationBatch,
} from '../utils/batchOperations.js';

export default function executeRulesMobileModal() {
    return {
        showExecuteRulesModal: false,
        cardIds: [],
        // 执行模式：'cards' 或 'folder'
        executeMode: 'cards',
        // 文件夹模式参数
        folderCategory: '',
        folderRecursive: true,

        init() {
            // 监听打开执行规则弹窗事件
            window.addEventListener('open-execute-rules-mobile-modal', (e) => {
                const detail = e.detail || {};
                
                // 判断模式
                if (detail.mode === 'folder') {
                    // 文件夹模式
                    this.executeMode = 'folder';
                    this.folderCategory = detail.category || '';
                    this.folderRecursive = detail.recursive !== undefined ? detail.recursive : true;
                    this.cardIds = [];
                } else {
                    // 卡片模式（默认）
                    this.executeMode = 'cards';
                    this.cardIds = detail.ids ? [...detail.ids] : [];
                    
                    if (this.cardIds.length === 0) {
                        // 如果事件没传，尝试直接读 Store (容错)
                        this.cardIds = this.$store.global.viewState.selectedIds || [];
                    }

                    if (this.cardIds.length === 0) {
                        alert("未选择任何卡片");
                        return;
                    }
                }

                // 加载规则集列表
                this.loadRuleSets();
                this.showExecuteRulesModal = true;
            });
        },

        // 加载规则集列表
        loadRuleSets() {
            listRuleSets().then(res => {
                if (res.success) {
                    // 更新全局 store 供所有组件使用
                    this.$store.global.availableRuleSets = res.items || [];
                } else {
                    this.$store.global.availableRuleSets = [];
                    console.error("加载规则集失败:", res.msg);
                }
            }).catch(err => {
                this.$store.global.availableRuleSets = [];
                console.error("加载规则集错误:", err);
            });
        },

        // 执行规则集
        async executeRuleSet(rulesetId) {
            if (isBatchOperationRunning()) {
                this.$store.global.showToast('已有批量操作正在进行', 2400);
                return;
            }

            let confirmMsg = '';
            let targetPayload = {};

            if (this.executeMode === 'folder') {
                // 文件夹模式
                const folderName = this.folderCategory === '' ? '根目录' : this.folderCategory;
                confirmMsg = `确定对 "${folderName}" 下的所有卡片${this.folderRecursive ? ' (包括子文件夹)' : ''} 执行此自动化规则吗？\n\n注意：这可能会移动大量文件。`;
                
                targetPayload.category = this.folderCategory;
                targetPayload.recursive = this.folderRecursive;
            } else {
                // 卡片模式
                if (this.cardIds.length === 0) {
                    alert("未选择任何卡片");
                    return;
                }
                const count = this.cardIds.length;
                confirmMsg = `确定对选中的 ${count} 张卡片执行此规则集吗？`;
                
                targetPayload.card_ids = [...this.cardIds];
            }

            if (!confirm(confirmMsg)) return;

            this.showExecuteRulesModal = false;
            try {
                const result = await runAutomationBatch({
                    rulesetId,
                    targetPayload,
                    title: this.executeMode === 'folder'
                        ? `自动处理分类：${this.folderCategory || '根目录'}`
                        : `自动处理 ${this.cardIds.length} 张卡片`,
                });
                if (result?.selected) {
                    let msg = `✅ 执行完成！\n已处理: ${result.processed || 0}\n移动: ${result.moves || 0} 张\n打标: ${result.tag_changes || 0} 次\n跳过: ${result.skipped || 0} 张\n失败: ${result.failed || 0} 张`;
                    if (result.cancelled) msg += '\n\n已停止后续处理。';
                    alert(msg);
                    if (this.executeMode === 'cards') {
                        this.$store.global.viewState.selectedIds = [];
                    }
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    if (this.executeMode === 'folder') {
                        window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                    }
                }
            } catch (error) {
                this.$store.global.showToast(`❌ ${error?.message || '批量执行失败'}`, 3600);
            }
        }
    }
}
