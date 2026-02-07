/**
 * static/js/components/executeRulesMobileModal.js
 * 移动端执行规则弹窗组件
 */

import { listRuleSets, executeRules } from '../api/automation.js';

export default function executeRulesMobileModal() {
    return {
        showExecuteRulesModal: false,
        cardIds: [],
        availableRuleSets: [],
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
        executeRuleSet(rulesetId) {
            let confirmMsg = '';
            let payload = { ruleset_id: rulesetId };

            if (this.executeMode === 'folder') {
                // 文件夹模式
                const folderName = this.folderCategory === '' ? '根目录' : this.folderCategory;
                confirmMsg = `确定对 "${folderName}" 下的所有卡片${this.folderRecursive ? ' (包括子文件夹)' : ''} 执行此自动化规则吗？\n\n注意：这可能会移动大量文件。`;
                
                payload.category = this.folderCategory;
                payload.recursive = this.folderRecursive;
            } else {
                // 卡片模式
                if (this.cardIds.length === 0) {
                    alert("未选择任何卡片");
                    return;
                }
                const count = this.cardIds.length;
                confirmMsg = `确定对选中的 ${count} 张卡片执行此规则集吗？`;
                
                payload.card_ids = this.cardIds;
            }

            if (!confirm(confirmMsg)) return;

            this.$store.global.isLoading = true;
            executeRules(payload).then(res => {
                this.$store.global.isLoading = false;
                if (res.success) {
                    let msg = `✅ 执行完成！\n已处理: ${res.processed}`;
                    // 简报（使用 summary 字段，如果没有则尝试 moves_plan/tags_plan）
                    if (res.summary) {
                        if (res.summary.moves > 0) msg += `\n移动: ${res.summary.moves} 张`;
                        if (res.summary.tag_changes > 0) msg += `\n打标: ${res.summary.tag_changes} 次`;
                    } else {
                        // 兼容旧格式
                        const moves = Object.keys(res.moves_plan || {}).length;
                        const tags = Object.values(res.tags_plan?.add || {}).flat().length;
                        if (moves > 0) msg += `\n移动: ${moves} 张`;
                        if (tags > 0) msg += `\n打标: ${tags} 次`;
                    }

                    alert(msg);
                    // 关闭弹窗
                    this.showExecuteRulesModal = false;
                    
                    // 卡片模式：清空选中
                    if (this.executeMode === 'cards') {
                        this.$store.global.viewState.selectedIds = [];
                    }
                    
                    // 刷新列表
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    if (this.executeMode === 'folder') {
                        window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                    }
                } else {
                    alert("执行失败: " + res.msg);
                }
            }).catch(e => {
                this.$store.global.isLoading = false;
                alert("Error: " + e);
            });
        }
    }
}
