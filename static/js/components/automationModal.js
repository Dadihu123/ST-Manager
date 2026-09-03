/**
 * static/js/components/automationModal.js
 * 自动化规则图形化编辑器
 */

import { listRuleSets, getRuleSet, saveRuleSet, deleteRuleSet, setGlobalRuleset, getGlobalRuleset, importRuleSet, getExportRuleSetUrl } from '../api/automation.js';
import { createLocalId } from '../utils/data.js';
import { splitTagTokens } from '../state.js';

const TEMPLATE_ACTION_TYPES = ['rename_file_by_template', 'split_category_to_tags'];
const SOURCE_ACTION_TYPES = [
    'fetch_forum_tags',
    'refresh_source_baseline',
    'add_tags_from_source_title',
    'set_creator_from_source'
];
const DEFAULT_SOURCE_TITLE_PATTERN = '(?:【|\\[)([^】\\]]+)(?:】|\\])';
const DEFAULT_SOURCE_TITLE_SPLIT_PATTERN = '[/|]';
const DEFAULT_RULE_TRIGGER_CONTEXTS = ['manual_run', 'auto_import'];
const SUPPORTED_RULE_TRIGGER_CONTEXTS = [
    'manual_run',
    'auto_import',
    'card_update',
    'link_update',
    'tag_edit'
];
const AUTOMATION_ACTION_OPTIONS = [
    { value: 'move_folder', label: '移动到...' },
    { value: 'add_tag', label: '添加标签' },
    { value: 'remove_tag', label: '移除标签' },
    { value: 'set_favorite', label: '设为收藏' },
    { value: 'merge_tags', label: '标签合并' },
    { value: 'fetch_forum_tags', label: '抓取论坛标签' },
    { value: 'refresh_source_baseline', label: '刷新来源更新基线' },
    { value: 'add_tags_from_source_title', label: '来源标题→标签' },
    { value: 'set_creator_from_source', label: '来源作者→创作者' },
    { value: 'rename_file_by_template', label: '模板重命名文件' },
    { value: 'split_category_to_tags', label: '分类拆分为标签' },
    { value: 'set_char_name_from_filename', label: '文件名→角色名' },
    { value: 'set_wi_name_from_filename', label: '文件名→世界书名' },
    { value: 'set_filename_from_char_name', label: '角色名→文件名' },
    { value: 'set_filename_from_wi_name', label: '世界书名→文件名' }
];


function deriveLegacyRuleTriggerContexts(rule) {
    const normalized = [...DEFAULT_RULE_TRIGGER_CONTEXTS];
    const actions = Array.isArray(rule?.actions) ? rule.actions : [];

    actions.forEach(action => {
        if (!action || typeof action !== 'object') return;

        if (SOURCE_ACTION_TYPES.includes(action.type) && !normalized.includes('link_update')) {
            normalized.push('link_update');
        }

        if (action.type === 'merge_tags' && !normalized.includes('tag_edit')) {
            normalized.push('tag_edit');
        }
    });

    return normalized;
}


function normalizeCaptureGroups(value) {
    const raw = Array.isArray(value) ? value : (value === undefined || value === null ? [1] : [value]);
    const groups = raw
        .flatMap(item => typeof item === 'string' ? item.split(/[,，\s]+/) : [item])
        .map(item => (item === null || item === undefined ? '' : item.toString().trim()))
        .filter(item => item !== '')
        .map(item => /^\d+$/.test(item) ? Number(item) : item);
    return groups.length ? groups : [1];
}


function createSourceTitleTagsConfig(value = {}) {
    const rawCaptureGroups = value.capture_groups !== undefined
        ? value.capture_groups
        : (value.capture_groups_text !== undefined ? value.capture_groups_text : value.capture_group);
    const captureGroups = normalizeCaptureGroups(rawCaptureGroups);

    return {
        pattern: typeof value.pattern === 'string' && value.pattern
            ? value.pattern
            : DEFAULT_SOURCE_TITLE_PATTERN,
        capture_groups: captureGroups,
        capture_groups_text: captureGroups.join(','),
        split_pattern: typeof value.split_pattern === 'string'
            ? value.split_pattern
            : DEFAULT_SOURCE_TITLE_SPLIT_PATTERN,
        flags: typeof value.flags === 'string' ? value.flags : ''
    };
}


function createSourceCreatorConfig(value = {}) {
    const provider = ['auto', 'discord', 'shimmerday'].includes(value.provider)
        ? value.provider
        : 'auto';
    const authorField = ['username', 'display_name', 'global_name', 'author_id'].includes(value.author_field)
        ? value.author_field
        : 'username';
    return {
        provider,
        author_field: authorField,
        format: typeof value.format === 'string' && value.format ? value.format : '{{author}}',
        overwrite: value.overwrite === true
            || value.overwrite === 1
            || value.overwrite === '1'
            || value.overwrite === 'true'
            || value.overwrite === 'yes'
            || value.overwrite === 'on'
    };
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
        showMobileOverview: false,
        showAutomationModal: false,
        showHelpModal: false,
        showCreateModal: false,
        showConfirmModal: false,
        helpActiveTab: 'conditions',
        ruleSets: [],
        activeRuleSet: null,
        globalRulesetId: null,
        actionTypeOptions: AUTOMATION_ACTION_OPTIONS,
        openActionMenuKey: null,
        rulesetQuery: '',
        loadingRuleSetId: null,
        isLoadingList: false,
        isImporting: false,
        isCreating: false,
        isSaving: false,
        isDeleting: false,
        isSettingGlobal: false,
        isConfirming: false,
        loadError: '',
        globalError: '',
        editorError: '',
        editorErrorTitle: '编辑器无法加载',
        metaError: '',
        createError: '',
        saveState: 'saved',
        savedSnapshot: '',
        newRuleSetName: '',
        collapsedRuleIds: [],
        confirmDialog: {
            title: '确认操作',
            message: '',
            details: '',
            confirmLabel: '确认'
        },
        pendingConfirmAction: null,
        allowDiscard: false,
        allowRuleSetSwitch: false,
        
        // 编辑缓冲区 (Deep Copy)
        editingMeta: { name: "", description: "", author: "", version: "" },
        editingRules: [],

        get filteredRuleSets() {
            const query = (this.rulesetQuery || '').trim().toLocaleLowerCase();
            if (!query) return this.ruleSets;

            return this.ruleSets.filter(ruleSet => {
                const meta = ruleSet?.meta || {};
                return [meta.name, meta.description, meta.author, meta.version]
                    .filter(Boolean)
                    .some(value => value.toString().toLocaleLowerCase().includes(query));
            });
        },

        get globalRulesetName() {
            const globalRuleSet = this.ruleSets.find(ruleSet => ruleSet.id === this.globalRulesetId);
            return globalRuleSet?.meta?.name || '';
        },

        get isDirty() {
            return Boolean(this.activeRuleSet && this.savedSnapshot && this.getSnapshot() !== this.savedSnapshot);
        },

        get saveStateLabel() {
            if (this.isSaving) return '保存中';
            if (this.saveState === 'error') return '保存失败';
            if (this.isDirty) return '有未保存修改';
            return '已保存';
        },

        get enabledRuleCount() {
            return this.editingRules.filter(rule => rule?.enabled !== false).length;
        },

        get triggerCount() {
            return new Set(this.editingRules.flatMap(rule => this.normalizeRuleTriggerContexts(rule))).size;
        },

        get conditionGroupCount() {
            return this.editingRules.reduce((count, rule) => count + (rule?.groups || []).length, 0);
        },

        get actionCount() {
            return this.editingRules.reduce((count, rule) => count + (rule?.actions || []).length, 0);
        },

        init() {
            // 监听打开事件 (Settings 或 Header 触发)
            window.addEventListener('open-automation-modal', () => {
                this.openModal();
            });

            this.$watch('editingMeta', () => this.markDirty());
            this.$watch('editingRules', () => this.markDirty());
        },

        async openModal() {
            this.showAutomationModal = true;
            this.showMobileSidebar = false;
            this.showMobileOverview = false;
            this.rulesetQuery = '';
            this.loadError = '';
            this.globalError = '';
            await this.loadGlobalSetting();
            await this.loadList({ autoSelect: true });
            this.$nextTick(() => this.$refs.dialog?.focus());
        },

        getSnapshot() {
            return JSON.stringify({
                meta: this.editingMeta || {},
                rules: this.editingRules || []
            });
        },

        markDirty() {
            if (!this.isSaving && this.activeRuleSet && this.savedSnapshot && this.getSnapshot() !== this.savedSnapshot) {
                this.saveState = 'dirty';
            }
        },

        ruleSummary(rule) {
            const groups = (rule?.groups || []).length;
            const actions = (rule?.actions || []).length;
            const triggers = this.normalizeRuleTriggerContexts(rule).length;
            return `${groups} 组条件 · ${actions} 个动作 · ${triggers} 个触发入口`;
        },

        conditionCount(rule) {
            return (rule?.groups || []).reduce(
                (count, group) => count + (group?.conditions || []).length,
                0
            );
        },

        isRuleCollapsed(ruleId) {
            return this.collapsedRuleIds.includes(ruleId);
        },

        toggleRuleCollapsed(ruleId) {
            if (!ruleId) return;
            this.collapsedRuleIds = this.isRuleCollapsed(ruleId)
                ? this.collapsedRuleIds.filter(id => id !== ruleId)
                : [...this.collapsedRuleIds, ruleId];
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
            const file = e.target?.files?.[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('file', file);

            // 清空 input 允许重复导入同名文件
            e.target.value = '';

            this.isImporting = true;
            this.editorError = '';
            const runImport = async () => {
                try {
                    const res = await importRuleSet(formData);
                    if (!res.success) throw new Error(res.msg || '导入失败');

                    this.$store.global.showToast(`导入成功: ${res.name}`, 3000, 'check');
                    await this.loadList({ selectId: res.id });
                } catch (error) {
                    this.editorErrorTitle = '导入失败';
                    this.editorError = error?.message || '无法导入规则集，请检查 JSON 文件后重试。';
                } finally {
                    this.isImporting = false;
                }
            };

            return runImport();
        },

        async loadGlobalSetting() {
            try {
                const res = await getGlobalRuleset();
                if (!res.success) throw new Error(res.msg || '全局规则设置读取失败');
                this.globalRulesetId = res.ruleset_id || null;
                this.globalError = '';
            } catch (error) {
                this.globalError = error?.message || '全局规则状态暂时无法读取。';
            }
        },

        toggleGlobalActive(id) {
            if (!id || this.isSettingGlobal) return;
            const newVal = (this.globalRulesetId === id) ? null : id;
            this.isSettingGlobal = true;
            const runToggle = async () => {
                try {
                    const res = await setGlobalRuleset(newVal);
                    if (!res.success) throw new Error(res.msg || '全局规则设置失败');

                    this.globalRulesetId = newVal;
                    this.globalError = '';
                    // 给用户一点反馈
                    if (newVal) this.$store.global.showToast('已设为全局自动规则 (按动作在不同场景触发)', 3000, 'check');
                    else this.$store.global.showToast('已关闭全局自动规则', 3000, 'forbidden');
                } catch (error) {
                    this.globalError = error?.message || '全局规则设置失败，请重试。';
                } finally {
                    this.isSettingGlobal = false;
                }
            };

            return runToggle();
        },

        loadList(options = {}) {
            const { autoSelect = false, selectId = null } = options;
            this.isLoadingList = true;
            this.loadError = '';

            const runLoad = async () => {
                try {
                    const res = await listRuleSets();
                    if (!res.success) throw new Error(res.msg || '规则集列表加载失败');

                    this.ruleSets = Array.isArray(res.items) ? res.items : [];
                    const preferredId = selectId
                        || (autoSelect ? this.globalRulesetId || this.activeRuleSet?.id || this.ruleSets[0]?.id : null);
                    if (preferredId && this.ruleSets.some(ruleSet => ruleSet.id === preferredId)) {
                        await this.selectRuleSet(preferredId);
                    } else if (!this.ruleSets.length) {
                        this.activeRuleSet = null;
                        this.editingRules = [];
                    }
                } catch (error) {
                    this.loadError = error?.message || '规则集列表加载失败，请重试。';
                } finally {
                    this.isLoadingList = false;
                }
            };

            return runLoad();
        },

        createNewRuleSet() {
            const name = (this.newRuleSetName || '').trim();
            if (!name) {
                this.createError = '请先填写规则集名称。';
                return Promise.resolve(false);
            }

            const newSet = {
                id: null, // Let backend generate UUID
                meta: { name: name, description: '', author: "User", version: "1.0" },
                rules: []
            };

            this.isCreating = true;
            this.createError = '';
            const runCreate = async () => {
                try {
                    const res = await saveRuleSet(newSet);
                    if (!res.success) throw new Error(res.msg || '创建失败');

                    this.showCreateModal = false;
                    this.newRuleSetName = '';
                    await this.loadList({ selectId: res.id });
                    this.$store.global.showToast('规则集已创建', 3000, 'check');
                } catch (error) {
                    this.createError = error?.message || '规则集创建失败，请重试。';
                } finally {
                    this.isCreating = false;
                }
            };

            return runCreate();
        },

        selectRuleSet(id) {
            if (!id || this.loadingRuleSetId === id) return Promise.resolve(false);

            if (this.isDirty && this.activeRuleSet?.id !== id && !this.allowRuleSetSwitch) {
                this.requestConfirmation(
                    '放弃未保存修改？',
                    `切换到“${this.ruleSets.find(ruleSet => ruleSet.id === id)?.meta?.name || '另一套规则集'}”会丢失当前编辑内容。`,
                    '先保存当前规则集，或确认放弃这些修改。',
                    '放弃并切换',
                    () => {
                        this.allowRuleSetSwitch = true;
                        return this.selectRuleSet(id).finally(() => {
                            this.allowRuleSetSwitch = false;
                        });
                    }
                );
                return Promise.resolve(false);
            }

            this.loadingRuleSetId = id;
            this.editorError = '';
            const runSelect = async () => {
                try {
                    const res = await getRuleSet(id);
                    if (!res.success) throw new Error(res.msg || '规则集加载失败');

                    {
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

                                if (action.type === 'add_tags_from_source_title') {
                                    action.config = createSourceTitleTagsConfig(action.value || {});
                                }

                                if (action.type === 'set_creator_from_source') {
                                    action.config = createSourceCreatorConfig(action.value || {});
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
                    this.savedSnapshot = this.getSnapshot();
                    this.saveState = 'saved';
                    this.collapsedRuleIds = [];
                    this.showMobileSidebar = false;
                    this.$nextTick(() => document.getElementById('automation-name')?.focus());
                    return true;
                    }
                } catch (error) {
                    this.editorErrorTitle = '规则集加载失败';
                    this.editorError = error?.message || '无法读取这套规则集，请重试。';
                    return false;
                } finally {
                    this.loadingRuleSetId = null;
                }
            };

            return runSelect();
        },

        saveCurrentRuleSet() {
            if (!this.activeRuleSet || this.isSaving) return;
            if (!this.validateMeta()) return;

            this.isSaving = true;
            this.saveState = 'saving';
            this.editorError = '';

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

                        if (action.type === 'add_tags_from_source_title' && action.config) {
                            const config = createSourceTitleTagsConfig(action.config);
                            action.value = {
                                pattern: config.pattern,
                                capture_groups: normalizeCaptureGroups(
                                    config.capture_groups_text || config.capture_groups
                                ),
                                split_pattern: config.split_pattern,
                                flags: config.flags,
                            };
                            delete action.config;
                        }

                        if (action.type === 'set_creator_from_source' && action.config) {
                            const config = createSourceCreatorConfig(action.config);
                            action.value = {
                                provider: config.provider,
                                author_field: config.author_field,
                                format: config.format,
                                overwrite: config.overwrite,
                            };
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
                    this.$store.global.showToast('规则集已保存', 3000, 'settings-save');
                    
                    // === 更新当前激活对象的 ID ===
                    // 因为保存可能导致重命名（ID变化），或者从 null 变为真实 ID
                    const newId = res.id;
                    this.activeRuleSet.id = newId;

                    this.loadGlobalSetting();
                    
                    // 刷新左侧列表，并保持高亮
                    this.savedSnapshot = this.getSnapshot();
                    this.saveState = 'saved';
                    this.loadList({ selectId: newId });
                } else {
                    this.saveState = 'error';
                    this.editorErrorTitle = '保存失败';
                    this.editorError = res.msg || '规则集保存失败，请重试。';
                }
            }).catch(error => {
                this.saveState = 'error';
                this.editorErrorTitle = '保存失败';
                this.editorError = error?.message || '规则集保存失败，请检查网络后重试。';
            }).finally(() => {
                this.isSaving = false;
            });
        },

        deleteCurrentRuleSet() {
            if (!this.activeRuleSet) return;
            this.requestConfirmation(
                '删除当前规则集？',
                `确定删除“${this.editingMeta.name || '未命名规则集'}”吗？`,
                '删除后无法从工作台恢复，请先导出 JSON 备份。',
                '删除规则集',
                () => this.performDeleteCurrentRuleSet()
            );
        },

        async performDeleteCurrentRuleSet() {
            if (!this.activeRuleSet?.id) return;

            this.isDeleting = true;
            try {
                const res = await deleteRuleSet(this.activeRuleSet.id);
                if (!res.success) throw new Error(res.msg || '删除失败');

                this.activeRuleSet = null;
                this.editingRules = [];
                this.savedSnapshot = '';
                this.saveState = 'saved';
                await this.loadList({ autoSelect: true });
                this.$store.global.showToast('规则集已删除', 3000, 'check');
            } finally {
                this.isDeleting = false;
            }
        },

        closeModal() {
            if (this.isDirty && !this.allowDiscard) {
                this.requestConfirmation(
                    '放弃未保存修改？',
                    '当前规则集还有未保存的编辑内容。',
                    '关闭后这些修改将被丢弃。',
                    '放弃修改',
                    () => {
                        this.allowDiscard = true;
                        this.closeModal();
                        this.allowDiscard = false;
                    }
                );
                return;
            }

            this.showAutomationModal = false;
            this.activeRuleSet = null;
            this.showHelpModal = false;
            this.helpActiveTab = 'conditions';
            this.openActionMenuKey = null;
            this.showMobileSidebar = false;
            this.showMobileOverview = false;
            this.savedSnapshot = '';
            this.saveState = 'saved';
            this.editorError = '';
            this.metaError = '';
        },

        handleEscape(event) {
            if (event?.defaultPrevented) return;
            if (this.showConfirmModal) {
                this.cancelConfirmation();
            } else if (this.showCreateModal) {
                this.closeCreateModal();
            } else if (this.showHelpModal) {
                this.closeHelpModal();
            } else if (this.showMobileSidebar) {
                this.showMobileSidebar = false;
            } else {
                this.closeModal();
            }
            event?.preventDefault();
        },

        validateMeta() {
            const name = (this.editingMeta?.name || '').trim();
            if (!name) {
                this.metaError = '规则集名称不能为空。';
                this.$nextTick(() => document.getElementById('automation-name')?.focus());
                return false;
            }

            this.metaError = '';
            this.editingMeta = { ...this.editingMeta, name };
            return true;
        },

        openCreateModal() {
            this.newRuleSetName = '';
            this.createError = '';
            this.showCreateModal = true;
            this.$nextTick(() => document.getElementById('automation-new-name')?.focus());
        },

        closeCreateModal() {
            if (this.isCreating) return;
            this.showCreateModal = false;
            this.createError = '';
        },

        closeHelpModal() {
            this.showHelpModal = false;
            this.helpActiveTab = 'conditions';
        },

        requestConfirmation(title, message, details, confirmLabel, action) {
            this.confirmDialog = {
                title,
                message,
                details,
                confirmLabel
            };
            this.pendingConfirmAction = action;
            this.showConfirmModal = true;
            this.$nextTick(() => document.querySelector('.automation-dialog--confirm button')?.focus());
        },

        async confirmPendingAction() {
            if (!this.pendingConfirmAction || this.isConfirming) return;

            const action = this.pendingConfirmAction;
            this.isConfirming = true;
            try {
                await action();
                this.showConfirmModal = false;
                this.pendingConfirmAction = null;
            } catch (error) {
                this.editorErrorTitle = '操作失败';
                this.editorError = error?.message || '操作未完成，请重试。';
            } finally {
                this.isConfirming = false;
            }
        },

        cancelConfirmation() {
            if (this.isConfirming) return;
            this.showConfirmModal = false;
            this.pendingConfirmAction = null;
        },

        openHelpTab(tab) {
            this.helpActiveTab = tab;
            this.showHelpModal = true;
        },

        getActionMenuKey(ruleIdx, actionIdx) {
            return `${ruleIdx}:${actionIdx}`;
        },

        isActionMenuOpen(ruleIdx, actionIdx) {
            return this.openActionMenuKey === this.getActionMenuKey(ruleIdx, actionIdx);
        },

        openActionMenu(ruleIdx, actionIdx) {
            this.openActionMenuKey = this.getActionMenuKey(ruleIdx, actionIdx);
        },

        toggleActionMenu(ruleIdx, actionIdx) {
            const key = this.getActionMenuKey(ruleIdx, actionIdx);
            this.openActionMenuKey = this.openActionMenuKey === key ? null : key;
        },

        closeActionMenu(event = null) {
            // Every action row listens for outside clicks, so ignore clicks
            // inside another action menu before clearing the shared state.
            if (event?.target?.closest?.('.automation-action-type-select')) return;

            this.openActionMenuKey = null;
        },

        actionTypeLabel(type) {
            return this.actionTypeOptions.find(option => option.value === type)?.label || '选择动作';
        },

        selectActionType(action, type) {
            if (!action || !this.actionTypeOptions.some(option => option.value === type)) return;

            action.type = type;
            if (type === 'add_tags_from_source_title') {
                action.value = createSourceTitleTagsConfig();
            } else if (type === 'set_creator_from_source') {
                action.value = createSourceCreatorConfig();
            }
            this.initActionConfig(action);
            this.openActionMenuKey = null;
        },

        conditionUsesMetadata(condition) {
            return condition?.field === 'metadata';
        },

        ruleUsesMetadata(rule) {
            return (rule?.groups || []).some(group =>
                (group?.conditions || []).some(condition => this.conditionUsesMetadata(condition))
            );
        },

        editingUsesMetadata() {
            return this.editingRules.some(rule => this.ruleUsesMetadata(rule));
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

            const hasSourceAction = (Array.isArray(rule?.actions) ? rule.actions : [])
                .some(action => action && SOURCE_ACTION_TYPES.includes(action.type));
            if (hasSourceAction && !normalized.includes('link_update')) {
                normalized.push('link_update');
            }

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
            const rule = this.editingRules[index];
            if (!rule) return;

            this.requestConfirmation(
                '删除这条规则？',
                `确定删除“${rule.name || `规则 ${index + 1}`}”吗？`,
                '删除后会从当前规则集移除，保存后正式生效。',
                '删除规则',
                () => {
                this.editingRules.splice(index, 1);
                this.editingRules = [...this.editingRules];
                }
            );
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
            this.requestConfirmation(
                '删除条件组？',
                '这个条件组及其中的条件会被移除。',
                '保存规则集后才会写入配置。',
                '删除条件组',
                () => {
                this.editingRules[ruleIdx].groups.splice(groupIdx, 1);
                this.editingRules = [...this.editingRules];
                }
            );
        },

        // Condition Operations
        addConditionToGroup(ruleIdx, groupIdx) {
            this.editingRules[ruleIdx].groups[groupIdx].conditions.push({
                field: "tags",
                operator: "contains",
                value: "",
                metadata_path: "",
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
            } else if (action.type === 'add_tags_from_source_title') {
                action.config = createSourceTitleTagsConfig(action.config || action.value || {});
            } else if (action.type === 'set_creator_from_source') {
                action.config = createSourceCreatorConfig(action.config || action.value || {});
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
