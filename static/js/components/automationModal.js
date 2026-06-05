/**
 * static/js/components/automationModal.js
 * 自动化规则图形化编辑器
 */

import { listRuleSets, getRuleSet, saveRuleSet, deleteRuleSet, setGlobalRuleset, getGlobalRuleset, importRuleSet, getExportRuleSetUrl } from '../api/automation.js';
import { createLocalId } from '../utils/data.js';
import { splitTagTokens } from '../state.js';

const TEMPLATE_ACTION_TYPES = ['rename_file_by_template', 'split_category_to_tags'];
const DEFAULT_RULE_TRIGGER_CONTEXTS = ['manual_run', 'auto_import'];
const SUPPORTED_RULE_TRIGGER_CONTEXTS = [
    'manual_run',
    'auto_import',
    'card_update',
    'link_update',
    'tag_edit'
];


function deriveLegacyRuleTriggerContexts(rule) {
    const normalized = [...DEFAULT_RULE_TRIGGER_CONTEXTS];
    const actions = Array.isArray(rule?.actions) ? rule.actions : [];

    actions.forEach(action => {
        if (!action || typeof action !== 'object') return;

        if (action.type === 'fetch_forum_tags' && !normalized.includes('link_update')) {
            normalized.push('link_update');
        }

        if (action.type === 'merge_tags' && !normalized.includes('tag_edit')) {
            normalized.push('tag_edit');
        }
    });

    return normalized;
}

function createFetchForumTagsConfig(value = {}) {
    return {
        exclude_tags: typeof value.exclude_tags === 'string' ? value.exclude_tags : '',
        replace_rules_text: typeof value.replace_rules_text === 'string' ? value.replace_rules_text : '',
        merge_mode: typeof value.merge_mode === 'string' && value.merge_mode ? value.merge_mode : 'merge'
    };
}

function createRenameTemplateConfig(value = {}) {
    return {
        template: typeof value.template === 'string' ? value.template : '',
        fallback_template: typeof value.fallback_template === 'string' ? value.fallback_template : '',
        max_length: Number.isFinite(Number(value.max_length)) && Number(value.max_length) > 0
            ? Number(value.max_length)
            : 120,
    };
}

function createSplitCategoryTagsConfig(value = {}) {
    return {
        exclude_category_tags: typeof value.exclude_category_tags === 'string'
            ? value.exclude_category_tags
            : (Array.isArray(value.exclude_segments) ? value.exclude_segments.join('|') : '')
    };
}

function getRenameTemplatePreset(preset) {
    if (preset === 'name_version') {
        return {
            template: '{{char_name}} - {{char_version|version}}',
            fallback_template: '{{char_name}}',
            max_length: 120,
        };
    }

    if (preset === 'name_import_date') {
        return {
            template: '{{char_name}} - {{import_date|date:%Y-%m-%d}}',
            fallback_template: '{{char_name}}',
            max_length: 120,
        };
    }

    if (preset === 'name_version_modified_date') {
        return {
            template: '{{char_name}} - {{char_version|version}} - {{modified_date|date:%Y-%m-%d}}',
            fallback_template: '{{char_name}}',
            max_length: 120,
        };
    }

    return createRenameTemplateConfig();
}

export default function automationModal() {
    return {
        showMobileSidebar: false,
        showAutomationModal: false,
        showHelpModal: false,
        helpActiveTab: 'conditions',
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
                    if (newVal) this.$store.global.showToast("✅ 已设为全局自动规则 (按动作在不同场景触发)");
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
                                    id: createLocalId(),
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
                        
                        // 处理 fetch_forum_tags 动作的配置转换
                        if (rule.actions) {
                            rule.actions.forEach(action => {
                                if (action.type === 'fetch_forum_tags' && action.value) {
                                    const valueObj = action.value;
                                    // 创建前端 config 对象
                                    action.config = {
                                        exclude_tags: Array.isArray(valueObj.exclude_tags)
                                            ? valueObj.exclude_tags.join('|')
                                            : '',
                                        replace_rules_text: valueObj.replace_rules
                                            ? Object.entries(valueObj.replace_rules)
                                                .map(([from, to]) => `${from}→${to}`)
                                                .join('|')
                                            : '',
                                        merge_mode: valueObj.merge_mode || 'merge'
                                    };
                                }

                                if (action.type === 'merge_tags') {
                                    const rawValue = action.value;
                                    if (rawValue && typeof rawValue === 'object' && !Array.isArray(rawValue)) {
                                        const mapSource =
                                            (rawValue.replace_rules && typeof rawValue.replace_rules === 'object')
                                                ? rawValue.replace_rules
                                                : ((rawValue.merge_rules && typeof rawValue.merge_rules === 'object')
                                                    ? rawValue.merge_rules
                                                    : null);

                                        if (mapSource) {
                                            action.value = Object.entries(mapSource)
                                                .map(([from, to]) => `${from}→${to}`)
                                                .join('|');
                                        } else if (rawValue.source_tags && (rawValue.target_tag || rawValue.target)) {
                                            action.value = `${rawValue.source_tags}→${rawValue.target_tag || rawValue.target}`;
                                        } else if (rawValue.from_tags && (rawValue.target_tag || rawValue.target)) {
                                            action.value = `${rawValue.from_tags}→${rawValue.target_tag || rawValue.target}`;
                                        } else {
                                            action.value = Object.entries(rawValue)
                                                .filter(([, to]) => to !== null && to !== undefined && to !== '')
                                                .map(([from, to]) => `${from}→${to}`)
                                                .join('|');
                                        }
                                    } else if (Array.isArray(rawValue)) {
                                        action.value = rawValue.join('|');
                                    } else {
                                        action.value = (rawValue || '').toString();
                                    }
                                }

                                if (TEMPLATE_ACTION_TYPES.includes(action.type)) {
                                    const rawValue = (action.value && typeof action.value === 'object' && !Array.isArray(action.value))
                                        ? action.value
                                        : {};
                                    action.config = action.type === 'rename_file_by_template'
                                        ? createRenameTemplateConfig(rawValue)
                                        : createSplitCategoryTagsConfig(rawValue);
                                }
                            });
                        }

                        rule.trigger_contexts = this.normalizeRuleTriggerContexts(rule);
                    });
                    
                    this.editingRules = rules;
                } else {
                    alert("加载失败: " + res.msg);
                }
            });
        },

        saveCurrentRuleSet() {
            if (!this.activeRuleSet) return;

            const slashAsSeparator = !!(this.$store?.global?.settingsForm?.automation_slash_is_tag_separator);
            const parseReplaceRulesText = (text) => {
                const out = {};
                const raw = (text || '').toString().trim();
                if (!raw) return out;

                const rulePattern = /(.*?)(?:→|->|=>)([^|]+)(?:\||$)/g;
                let match;
                while ((match = rulePattern.exec(raw)) !== null) {
                    const left = (match[1] || '').trim();
                    const right = (match[2] || '').trim();
                    if (!left || !right) continue;

                    const fromTags = splitTagTokens(left, { slashIsSeparator: slashAsSeparator });
                    const toTags = splitTagTokens(right, { slashIsSeparator: slashAsSeparator });
                    if (!fromTags.length || !toTags.length) continue;

                    const target = toTags[0];
                    fromTags.forEach(from => {
                        out[from] = target;
                    });
                }

                return out;
            };

            // 深拷贝规则，避免修改原始数据
            const rulesToSave = JSON.parse(JSON.stringify(this.editingRules));
            
            // 处理 fetch_forum_tags 动作的配置
            rulesToSave.forEach(rule => {
                rule.trigger_contexts = this.normalizeRuleTriggerContexts(rule);

                if (rule.actions) {
                    rule.actions.forEach(action => {
                        if (action.type === 'fetch_forum_tags' && action.config) {
                            // 构建 value 对象
                            const config = action.config;
                            const valueObj = {
                                exclude_tags: splitTagTokens(config.exclude_tags, { slashIsSeparator: slashAsSeparator }),
                                replace_rules: {},
                                merge_mode: config.merge_mode || 'merge'
                            };

                            // 解析替换规则（支持逗号/管道符，且可按设置支持斜杠分隔）
                            if (config.replace_rules_text) {
                                valueObj.replace_rules = parseReplaceRulesText(config.replace_rules_text);
                            }
                            
                            // 替换 value 为配置对象
                            action.value = valueObj;
                            // 删除临时 config 对象
                            delete action.config;
                        }

                        if (action.type === 'merge_tags') {
                            action.value = (action.value || '').toString().trim();
                        }

                        if (TEMPLATE_ACTION_TYPES.includes(action.type)) {
                            const config = action.type === 'rename_file_by_template'
                                ? createRenameTemplateConfig(action.config || action.value || {})
                                : createSplitCategoryTagsConfig(action.config || action.value || {});
                            action.value = action.type === 'rename_file_by_template'
                                ? {
                                    template: config.template,
                                    fallback_template: config.fallback_template,
                                    max_length: config.max_length,
                                }
                                : {
                                    exclude_segments: splitTagTokens(config.exclude_category_tags, { slashIsSeparator: slashAsSeparator })
                                };
                            delete action.config;
                        }
                    });
                }
            });

            const payload = {
                id: this.activeRuleSet.id, // ID 不变
                meta: this.editingMeta,
                rules: rulesToSave
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
            this.showHelpModal = false;
            this.helpActiveTab = 'conditions';
        },

        openHelpTab(tab) {
            this.helpActiveTab = tab;
            this.showHelpModal = true;
        },

        // === 规则编辑器逻辑 ===

        normalizeRuleTriggerContexts(rule) {
            const trigger_contexts = Array.isArray(rule?.trigger_contexts) ? rule.trigger_contexts : null;

            if (!trigger_contexts || trigger_contexts.length === 0) {
                return deriveLegacyRuleTriggerContexts(rule);
            }

            const normalized = [];
            trigger_contexts.filter(trigger => {
                return typeof trigger === 'string' && trigger.trim();
            }).map(trigger => trigger.trim()).filter(trigger => {
                return SUPPORTED_RULE_TRIGGER_CONTEXTS.includes(trigger);
            }).forEach(trigger => {
                if (!normalized.includes(trigger)) {
                    normalized.push(trigger);
                }
            });

            return normalized.length ? normalized : deriveLegacyRuleTriggerContexts(rule);
        },

        toggleRuleTrigger(rule, trigger) {
            if (!rule || typeof trigger !== 'string' || !trigger.trim()) return;

            const currentTriggers = this.normalizeRuleTriggerContexts(rule);
            const normalizedTrigger = trigger.trim();
            if (currentTriggers.length === 1 && currentTriggers[0] === normalizedTrigger) return;

            const nextTriggers = currentTriggers.includes(normalizedTrigger)
                ? currentTriggers.filter(item => item !== normalizedTrigger)
                : [...currentTriggers, normalizedTrigger];

            rule.trigger_contexts = nextTriggers;
            this.editingRules = [...this.editingRules];
        },

        ruleHasTrigger(rule, trigger) {
            return this.normalizeRuleTriggerContexts(rule).includes(trigger);
        },

        addRule() {
            this.editingRules.push({
                id: createLocalId(),
                name: "新规则",
                enabled: true,
                stop_on_match: false,
                trigger_contexts: ['manual_run', 'auto_import'],
                logic: "OR", // 规则内各组之间默认 OR
                groups: [    // 默认带一个组
                    {
                        id: createLocalId(),
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
                this.editingRules = [...this.editingRules];
            }
        },

        moveArrayItem(items, index, dir) {
            if (!Array.isArray(items)) return false;

            const newIndex = index + dir;
            if (index < 0 || index >= items.length || newIndex < 0 || newIndex >= items.length) {
                return false;
            }

            const temp = items[index];
            items[index] = items[newIndex];
            items[newIndex] = temp;
            return true;
        },

        moveRule(index, dir) {
            if (!this.moveArrayItem(this.editingRules, index, dir)) return;
            this.editingRules = [...this.editingRules];
        },

        // Group Operations
        addGroup(ruleIdx) {
            this.editingRules[ruleIdx].groups.push({
                id: createLocalId(),
                logic: "AND",
                conditions: []
            });
            this.editingRules = [...this.editingRules];
        },

        moveGroup(ruleIdx, groupIdx, dir) {
            const groups = this.editingRules[ruleIdx]?.groups;
            if (!this.moveArrayItem(groups, groupIdx, dir)) return;
            this.editingRules = [...this.editingRules];
        },

        removeGroup(ruleIdx, groupIdx) {
            if(confirm("删除此条件组？")) {
                this.editingRules[ruleIdx].groups.splice(groupIdx, 1);
                this.editingRules = [...this.editingRules];
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
            this.editingRules = [...this.editingRules];
        },

        moveConditionInGroup(ruleIdx, groupIdx, condIdx, dir) {
            const conditions = this.editingRules[ruleIdx]?.groups[groupIdx]?.conditions;
            if (!this.moveArrayItem(conditions, condIdx, dir)) return;
            this.editingRules = [...this.editingRules];
        },

        removeConditionFromGroup(ruleIdx, groupIdx, condIdx) {
            this.editingRules[ruleIdx].groups[groupIdx].conditions.splice(condIdx, 1);
            this.editingRules = [...this.editingRules];
        },

        // Action Operations (Keep flat)
        addAction(ruleIdx) {
            const newAction = {
                type: "add_tag",
                value: ""
            };
            this.editingRules[ruleIdx].actions.push(newAction);
            this.editingRules = [...this.editingRules];
        },

        moveAction(ruleIdx, actIdx, dir) {
            const actions = this.editingRules[ruleIdx]?.actions;
            if (!this.moveArrayItem(actions, actIdx, dir)) return;
            this.editingRules = [...this.editingRules];
        },

        removeAction(ruleIdx, actIdx) {
            this.editingRules[ruleIdx].actions.splice(actIdx, 1);
            this.editingRules = [...this.editingRules];
        },

        // Initialize action config (for fetch_forum_tags)
        initActionConfig(action) {
            if (action.type === 'fetch_forum_tags') {
                action.config = createFetchForumTagsConfig(action.config || action.value || {});
            } else if (action.type === 'rename_file_by_template') {
                action.config = createRenameTemplateConfig(action.config || action.value || {});
            } else if (action.type === 'split_category_to_tags') {
                action.config = createSplitCategoryTagsConfig(action.config || action.value || {});
            } else {
                // For other action types, remove config if exists
                if (action.config) {
                    delete action.config;
                }
            }

            return action.config || null;
        },

        applyRenameTemplatePreset(action, preset) {
            if (!action || action.type !== 'rename_file_by_template') return;
            action.config = getRenameTemplatePreset(preset);
            return action.config;
        },
        
        // Utils
        scrollToBottom() {
            this.$nextTick(() => {
                const container = document.querySelector('.auto-body');
                if (container) container.scrollTop = container.scrollHeight;
            });
        }
    }
}
