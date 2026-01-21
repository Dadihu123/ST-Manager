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

        init() {
            // 监听打开执行规则弹窗事件
            window.addEventListener('open-execute-rules-mobile-modal', (e) => {
                this.cardIds = e.detail && e.detail.ids ? [...e.detail.ids] : [];
                
                if (this.cardIds.length === 0) {
                    // 如果事件没传，尝试直接读 Store (容错)
                    this.cardIds = this.$store.global.viewState.selectedIds || [];
                }

                if (this.cardIds.length === 0) {
                    alert("未选择任何卡片");
                    return;
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
                    this.availableRuleSets = res.items || [];
                } else {
                    this.availableRuleSets = [];
                    console.error("加载规则集失败:", res.msg);
                }
            }).catch(err => {
                this.availableRuleSets = [];
                console.error("加载规则集错误:", err);
            });
        },

        // 执行规则集（参考 header.js 的 executeRuleSet）
        executeRuleSet(rulesetId) {
            if (this.cardIds.length === 0) return;

            const count = this.cardIds.length;
            if (!confirm(`确定对选中的 ${count} 张卡片执行此规则集吗？`)) return;

            this.$store.global.isLoading = true;
            executeRules({
                card_ids: this.cardIds,
                ruleset_id: rulesetId
            }).then(res => {
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
                    // 清空选中
                    this.$store.global.viewState.selectedIds = [];
                    // 刷新列表
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
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
