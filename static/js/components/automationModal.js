/**
 * static/js/components/automationModal.js
 * 自动化规则图形化编辑器
 */

import { listRuleSets, getRuleSet, saveRuleSet, deleteRuleSet, setGlobalRuleset, getGlobalRuleset, importRuleSet, getExportRuleSetUrl } from '../api/automation.js';

export default function automationModal() {
    return {
        showMobileSidebar: false,
        showAutomationModal: false,
        showHelpModal: false,
        ruleSets: [],
        activeRuleSet: null,
        globalRulesetId: null,
        
        // 编辑缓冲区 (Deep Copy)
        editingMeta: { name: "", description: "", author: "", version: "" },
        editingRules: [],

        init() {
            // 监听打开事件 (Settings 或 Header 触发)
            window.addEventListener('open-automation-modal', () => {
                this.loadList();
                this.loadGlobalSetting();
                this.showAutomationModal = true;
            });
        },

        // 导出
        exportCurrentRuleSet() {
            if (!this.activeRuleSet || !this.activeRuleSet.id) return;
            // 触发下载
            const url = getExportRuleSetUrl(this.activeRuleSet.id);
            window.open(url, '_blank');
        },

        // 导入
        handleImportRuleSet(e) {
            const file = e.target.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('file', file);

            // 清空 input 允许重复导入同名文件
            e.target.value = '';

            importRuleSet(formData).then(res => {
                if (res.success) {
                    this.$store.global.showToast(`✅ 导入成功: ${res.name}`);
                    this.loadList(); // 刷新列表
                    // 自动选中导入的规则集
                    this.selectRuleSet(res.id);
                } else {
                    alert("导入失败: " + res.msg);
                }
            });
        },

        loadGlobalSetting() {
            getGlobalRuleset().then(res => {
                if (res.success) this.globalRulesetId = res.ruleset_id;
            });
        },

        toggleGlobalActive(id) {
            const newVal = (this.globalRulesetId === id) ? null : id;
            setGlobalRuleset(newVal).then(res => {
                if (res.success) {
                    this.globalRulesetId = newVal;
                    // 给用户一点反馈
                    if (newVal) this.$store.global.showToast("✅ 已设为全局自动规则 (导入时生效)");
                    else this.$store.global.showToast("🚫 已关闭全局自动规则");
                }
            });
        },

        loadList() {
            listRuleSets().then(res => {
                if (res.success) {
                    this.ruleSets = res.items;
                }
            });
        },

        createNewRuleSet() {
            const name = prompt("请输入规则集名称:");
            if (!name) return;

            const newSet = {
                id: null, // Let backend generate UUID
                meta: { name: name, author: "User", version: "1.0" },
                rules: []
            };

            saveRuleSet(newSet).then(res => {
                if (res.success) {
                    this.loadList();
                    // 自动选中新建的 (需要获取 ID，这里为了简单先由用户点选)
                } else {
                    alert("创建失败: " + res.msg);
                }
            });
        },

        selectRuleSet(id) {
            getRuleSet(id).then(res => {
                if (res.success) {
                    this.activeRuleSet = res.data;
                    this.editingMeta = JSON.parse(JSON.stringify(res.data.meta));
                    
                    // === 数据迁移与标准化 ===
                    let rules = JSON.parse(JSON.stringify(res.data.rules || []));
                    rules.forEach(rule => {
                        // 如果是旧版扁平结构，转换为 Groups 结构
                        if (!rule.groups || rule.groups.length === 0) {
                            if (rule.conditions && rule.conditions.length > 0) {
                                rule.groups = [{
                                    id: crypto.randomUUID(),
                                    logic: "AND", // 旧版默认为 AND
                                    conditions: rule.conditions
                                }];
                            } else {
                                rule.groups = [];
                            }
                        }
                        // 确保 Rule Logic 存在
                        if (!rule.logic) rule.logic = "OR"; // 默认规则间是 OR 关系 (满足任意一组即可)
                        
                        // 清理旧字段以免混淆
                        delete rule.conditions; 
                    });
                    
                    this.editingRules = rules;
                } else {
                    alert("加载失败: " + res.msg);
                }
            });
        },

        saveCurrentRuleSet() {
            if (!this.activeRuleSet) return;

            const payload = {
                id: this.activeRuleSet.id, // ID 不变
                meta: this.editingMeta,
                rules: this.editingRules
            };

            saveRuleSet(payload).then(res => {
                if (res.success) {
                    this.$store.global.showToast("💾 规则集已保存");
                    
                    // === 更新当前激活对象的 ID ===
                    // 因为保存可能导致重命名（ID变化），或者从 null 变为真实 ID
                    const newId = res.id;
                    this.activeRuleSet.id = newId;

                    this.loadGlobalSetting();
                    
                    // 刷新左侧列表，并保持高亮
                    this.loadList(); 
                } else {
                    alert("保存失败: " + res.msg);
                }
            });
        },

        deleteCurrentRuleSet() {
            if (!this.activeRuleSet) return;
            if (!confirm(`确定删除规则集 "${this.editingMeta.name}" 吗？`)) return;

            deleteRuleSet(this.activeRuleSet.id).then(res => {
                if (res.success) {
                    this.activeRuleSet = null;
                    this.loadList();
                } else {
                    alert("删除失败: " + res.msg);
                }
            });
        },

        closeModal() {
            this.showAutomationModal = false;
            this.activeRuleSet = null;
        },

        // === 规则编辑器逻辑 ===

        addRule() {
            this.editingRules.push({
                id: crypto.randomUUID(),
                name: "新规则",
                enabled: true,
                stop_on_match: false,
                logic: "OR", // 规则内各组之间默认 OR
                groups: [    // 默认带一个组
                    {
                        id: crypto.randomUUID(),
                        logic: "AND", // 组内条件默认 AND
                        conditions: []
                    }
                ],
                actions: []
            });
            this.scrollToBottom();
        },

        deleteRule(index) {
            if(confirm("删除此规则？")) {
                this.editingRules.splice(index, 1);
            }
        },

        moveRule(index, dir) {
            const newIndex = index + dir;
            if (newIndex < 0 || newIndex >= this.editingRules.length) return;
            const temp = this.editingRules[index];
            this.editingRules[index] = this.editingRules[newIndex];
            this.editingRules[newIndex] = temp;
            // 强制刷新 Alpine 数组
            this.editingRules = [...this.editingRules]; 
        },

        // Group Operations
        addGroup(ruleIdx) {
            this.editingRules[ruleIdx].groups.push({
                id: crypto.randomUUID(),
                logic: "AND",
                conditions: []
            });
        },

        removeGroup(ruleIdx, groupIdx) {
            if(confirm("删除此条件组？")) {
                this.editingRules[ruleIdx].groups.splice(groupIdx, 1);
            }
        },

        // Condition Operations
        addConditionToGroup(ruleIdx, groupIdx) {
            this.editingRules[ruleIdx].groups[groupIdx].conditions.push({
                field: "tags",
                operator: "contains",
                value: "",
                case_sensitive: false
            });
        },

        removeConditionFromGroup(ruleIdx, groupIdx, condIdx) {
            this.editingRules[ruleIdx].groups[groupIdx].conditions.splice(condIdx, 1);
        },

        // Action Operations (Keep flat)
        addAction(ruleIdx) {
            this.editingRules[ruleIdx].actions.push({
                type: "add_tag",
                value: ""
            });
        },
        removeAction(ruleIdx, actIdx) {
            this.editingRules[ruleIdx].actions.splice(actIdx, 1);
        },
        
        // Utils
        deleteRule(index) {
            if(confirm("删除此规则？")) this.editingRules.splice(index, 1);
        },
        moveRule(index, dir) {
            const newIndex = index + dir;
            if (newIndex < 0 || newIndex >= this.editingRules.length) return;
            const temp = this.editingRules[index];
            this.editingRules[index] = this.editingRules[newIndex];
            this.editingRules[newIndex] = temp;
            this.editingRules = [...this.editingRules]; 
        },
        scrollToBottom() {
            this.$nextTick(() => {
                const container = document.querySelector('.auto-body');
                if (container) container.scrollTop = container.scrollHeight;
            });
        }
    }
}