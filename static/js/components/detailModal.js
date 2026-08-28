/**
 * static/js/components/detailModal.js
 * 角色卡详情模态框组件
 */

import { 
    getCardDetail, 
    updateCard, 
    previewMergedTags,
    updateCardFile, 
    updateCardFileFromUrl, 
    changeCardImage,
    getCardMetadata,
    sendToSillyTavern,
    acknowledgeCardSourceUpdate,
    checkCardSourceUpdate,
    setAsBundleCover as apiSetAsBundleCover,
    convertToBundle as apiConvertToBundle,
    toggleBundleMode as apiToggleBundleMode
} from '../api/card.js';
import { listChats } from '../api/chat.js';
import { canPreviewForumThread } from '../utils/discordUrl.js';

import { 
    renameFolder, 
    performSystemAction,
    readFileContent
} from '../api/system.js';

import { 
    setSkinAsCover,
    deleteResourceFile,
    uploadCardResource,
    uploadNoteImage,
    listResourceFiles,
    setResourceFolder as apiSetResourceFolder, 
    openResourceFolder as apiOpenResourceFolder, 
    createResourceFolder as apiCreateResourceFolder 
} from '../api/resource.js';

import { getCleanedV3Data, updateWiKeys, toStV3Worldbook } from '../utils/data.js';
import {
    formatDate,
    getVersionName,
    estimateTokens,
    formatWiKeys,
    getTopbarTokenLevelClass
} from '../utils/format.js';
import { insertAtCursor, updateShadowContent, renderUnifiedPreviewHost, updateMixedPreviewContent } from '../utils/dom.js';
import { createAutoSaver } from '../utils/autoSave.js'; 
import { wiHelpers } from '../utils/wiHelpers.js';
import { clearActiveRuntimeContext, setActiveRuntimeContext } from '../runtime/runtimeContext.js';
import { matchAnyTagSearchToken, splitTagTokens } from '../state.js';

export default function detailModal() {
    const autoSaver = createAutoSaver();
    return {
        // === 本地状态 ===
        showDetail: false,
        activeCard: {}, // 当前查看的卡片对象 (原始引用或副本)
        newTagInput: '',
        showTagLibrary: true,
        tagLibrarySearch: '',
        tab: 'basic', 
        lastTab: 'basic',
        dialogPage: 'greeting',
        selectedGreetingKind: 'default',
        showGreetingPreview: true,
        showLocalNotePreview: false,
        updateImagePolicy: 'overwrite', // 默认策略
        syncSourceTitleOnUpdate: true,
        sourceUpdateChecking: false,
        sourceUpdateAcknowledging: false,
        saveOldCoverOnSwap: false,      // 皮肤换封时是否保留旧图
        dragOverUpdate: false,
        dragOverResource: false,
        dragOverCardChats: false,
        showHelpModal: false,
        mixedCategoryView: true,
        detailCategoryFilterInclude: [],
        detailCategoryFilterExclude: [],
        
        // 编辑器状态 (V3 规范扁平化数据)
        editingData: {
            id: null,
            char_name: "",
            description: "",
            first_mes: "",
            mes_example: "",
            personality: "",
            scenario: "",
            creator_notes: "",
            system_prompt: "",
            post_history_instructions: "",
            tags: [],
            creator: "",
            character_version: "",
            alternate_greetings: [],
            extensions: { regex_scripts: [], tavern_helper: {} },
            character_book: { name: "", entries: [] },
            // UI 字段
            filename: "",
            ui_summary: "",
            source_link: "",
            resource_folder: "",
            source_revision: "",
            character_book_raw: "" // 用于 JSON 编辑
        },

        // 界面控制
        isSaving: false,
        isCardFlipped: false,
        zoomLevel: 100,
        altIdx: 0,
        detailAltDragIndex: null,
        detailAltDropIndex: null,
        detailAltPointer: null,
        detailAltSuppressClick: false,
        rawMetadataContent: 'Loading...',
        isEditMode: false, // 编辑模式开关，默认为阅览模式
        personaFieldKeys: [
            'personality',
            'scenario',
            'creator_notes',
            'system_prompt',
            'post_history_instructions',
        ],
        personaHiddenFields: {
            personality: false,
            scenario: false,
            creator_notes: false,
            system_prompt: false,
            post_history_instructions: false,
        },
        personaPreviewField: '',
        personaPreviewTitle: '',
        personaPreviewEnglish: '',
        detailTagDragIndex: null,
        pendingAdvancedEditorApplyHandler: null,
        pendingAdvancedEditorPersistHandler: null,

        // 资源文件列表状态
        resourceLorebooks: [],
        resourceRegex: [],
        resourceScripts: [],
        resourceQuickReplies: [],
        resourcePresets: [],
        resourceUnknown: [],
        cardChats: [],
        cardChatsLoading: false,
        // 皮肤与版本
        skinImages: [],
        currentSkinIndex: -1,
        currentSkinDirectory: '',
        showSkinGallery: false,
        skinGalleryPreviewPath: '',

        // 自动保存
        originalDataJson: '', // 基准快照

        showSetResourceFolderModal: false,
        resourceFolderCreationPromise: null,

        formatDate,
        estimateTokens,
        updateShadowContent,
        renderUnifiedPreviewHost,
        updateMixedPreviewContent,
        formatWiKeys,
        getTopbarTokenLevelClass,
        updateWiKeys,
        ...wiHelpers,

        formatDateWithYear(ts) {
            return formatDate(ts, { includeYear: true });
        },

        formatSourceFirstMessageEditedAt() {
            const sourceUpdate = this.activeCard?.source_update;
            if (sourceUpdate?.first_message_edited_at) {
                return this.formatDateWithYear(sourceUpdate.first_message_edited_at);
            }
            if (sourceUpdate?.first_message_timestamp) {
                return '未编辑过';
            }
            return '未取得';
        },

        formatSourceUpdateCheckedAt() {
            const checkedAt = this.activeCard?.source_update?.last_checked_at;
            return checkedAt ? this.formatDateWithYear(checkedAt) : '未检查';
        },

        buildPreviewRegexConfig() {
            const regexScripts = Array.isArray(this.editingData?.extensions?.regex_scripts)
                ? this.editingData.extensions.regex_scripts
                : [];
            return {
                displayRules: regexScripts,
            };
        },

        _convertLegacyTavernHelper(extensions) {
            if (!extensions || typeof extensions !== 'object') return;
            if (extensions.tavern_helper !== undefined) return;
            if (!Array.isArray(extensions.TavernHelper_scripts)) return;

            // 兼容更老格式: TavernHelper_scripts = [{ type:'script', value:{...} }, ...]
            const scripts = [];
            extensions.TavernHelper_scripts.forEach((item) => {
                if (!item || typeof item !== 'object') return;
                if (item.value && typeof item.value === 'object') {
                    scripts.push(item.value);
                    return;
                }
                scripts.push(item);
            });

            extensions.tavern_helper = { scripts };
        },

        _extractTavernScriptsFromExtensions(extensions) {
            if (!extensions || typeof extensions !== 'object') return [];

            const helper = extensions.tavern_helper;
            if (helper && typeof helper === 'object') {
                if (Array.isArray(helper)) {
                    const scriptBlock = helper.find(item => Array.isArray(item) && item[0] === 'scripts');
                    if (scriptBlock && Array.isArray(scriptBlock[1])) {
                        return scriptBlock[1];
                    }
                } else if (Array.isArray(helper.scripts)) {
                    return helper.scripts;
                }
            }

            if (Array.isArray(extensions.TavernHelper_scripts)) {
                return extensions.TavernHelper_scripts.map((item) => {
                    if (item && typeof item === 'object' && item.value && typeof item.value === 'object') {
                        return item.value;
                    }
                    return item;
                }).filter(Boolean);
            }

            return [];
        },

        _normalizeTavernScriptsForSave(currentExtensions) {
            const scripts = this._extractTavernScriptsFromExtensions(currentExtensions).map((script) => {
                const src = (script && script.value && typeof script.value === 'object') ? script.value : script;
                if (!src || typeof src !== 'object') return null;

                const topButtons = Array.isArray(src.buttons) ? src.buttons : [];
                const nestedButtons = src.button && Array.isArray(src.button.buttons) ? src.button.buttons : [];
                const mergedButtons = (nestedButtons.length > 0 ? nestedButtons : topButtons)
                    .filter(btn => btn && typeof btn === 'object')
                    .map(btn => ({
                        name: btn.name || '新按钮',
                        visible: btn.visible !== false
                    }));

                return {
                    name: src.name || src.scriptName || '未命名脚本',
                    type: src.type || 'script',
                    content: src.content || src.script || '',
                    info: src.info || '',
                    enabled: src.enabled !== false,
                    id: src.id,
                    button: {
                        enabled: !!(src.button && src.button.enabled),
                        buttons: mergedButtons
                    },
                    data: src.data && typeof src.data === 'object' ? src.data : {}
                };
            }).filter(Boolean);

            const helperObj = (currentExtensions && currentExtensions.tavern_helper && typeof currentExtensions.tavern_helper === 'object' && !Array.isArray(currentExtensions.tavern_helper))
                ? currentExtensions.tavern_helper
                : {};

            return {
                scripts,
                variables: helperObj.variables && typeof helperObj.variables === 'object' ? helperObj.variables : {}
            };
        },

        _buildExtensionsForSave(cleanExtensions) {
            const result = JSON.parse(JSON.stringify(cleanExtensions || {}));
            result.tavern_helper = this._normalizeTavernScriptsForSave(result);
            delete result.TavernHelper_scripts;
            return result;
        },

        _cleanupPendingAdvancedEditorHandlers() {
            if (this.pendingAdvancedEditorApplyHandler) {
                window.removeEventListener('advanced-editor-apply', this.pendingAdvancedEditorApplyHandler);
                this.pendingAdvancedEditorApplyHandler = null;
            }
            if (this.pendingAdvancedEditorPersistHandler) {
                window.removeEventListener('advanced-editor-persist', this.pendingAdvancedEditorPersistHandler);
                this.pendingAdvancedEditorPersistHandler = null;
            }
        },

        _normalizeEditingDataShape(source = {}) {
            const normalized = {
                id: null,
                char_name: "",
                description: "",
                first_mes: "",
                mes_example: "",
                personality: "",
                scenario: "",
                creator_notes: "",
                system_prompt: "",
                post_history_instructions: "",
                tags: [],
                creator: "",
                character_version: "",
                alternate_greetings: [],
                extensions: { regex_scripts: [], tavern_helper: {} },
                character_book: { name: "", entries: [] },
                filename: "",
                ui_summary: "",
                source_link: "",
                source_title: "",
                source_update: null,
                resource_folder: "",
                source_revision: "",
                character_book_raw: ""
            };

            const data = { ...normalized, ...(source || {}) };

            if (!Array.isArray(data.tags)) data.tags = [];

            if (!Array.isArray(data.alternate_greetings)) data.alternate_greetings = [];
            data.alternate_greetings = data.alternate_greetings.filter(g => typeof g === 'string');
            if (data.alternate_greetings.length === 0) data.alternate_greetings = [""];

            if (!data.extensions || typeof data.extensions !== 'object') data.extensions = {};
            this._convertLegacyTavernHelper(data.extensions);
            if (!Array.isArray(data.extensions.regex_scripts)) data.extensions.regex_scripts = [];
            const helper = data.extensions.tavern_helper;
            if (helper === null || helper === undefined) {
                data.extensions.tavern_helper = {};
            } else if (Array.isArray(helper)) {
                // 旧版列表结构，保留原样
            } else if (typeof helper === 'object') {
                // 新版对象结构，保留原样
            } else {
                data.extensions.tavern_helper = {};
            }

            if (!data.character_book) {
                data.character_book = { name: "World Info", entries: [] };
            } else if (Array.isArray(data.character_book)) {
                data.character_book = {
                    name: data.char_name || "World Info",
                    entries: data.character_book
                };
            } else if (typeof data.character_book !== 'object') {
                data.character_book = { name: "World Info", entries: [] };
            }

            if (!Array.isArray(data.character_book.entries)) {
                if (data.character_book.entries && typeof data.character_book.entries === 'object') {
                    data.character_book.entries = Object.values(data.character_book.entries);
                } else {
                    data.character_book.entries = [];
                }
            }
            if (!data.character_book.name) data.character_book.name = data.char_name || "World Info";

            [
                'description', 'first_mes', 'mes_example', 'personality', 'scenario',
                'creator_notes', 'system_prompt', 'post_history_instructions',
                'creator', 'character_version', 'filename', 'ui_summary',
                'source_link', 'resource_folder'
            ].forEach((k) => {
                if (data[k] === null || data[k] === undefined) data[k] = "";
            });

            data.character_book_raw = JSON.stringify(data.character_book, null, 2);
            return data;
        },

        hasTextValue(value) {
            if (typeof value === 'string') {
                return value.trim().length > 0;
            }
            return value !== null && value !== undefined && value !== false;
        },

        get hasAlternateGreetings() {
            const greetings = Array.isArray(this.editingData?.alternate_greetings)
                ? this.editingData.alternate_greetings
                : [];
            return greetings.some((g) => this.hasTextValue(g));
        },

        get hasDefaultGreeting() {
            return this.hasTextValue(this.editingData?.first_mes);
        },

        get firstAlternateGreetingIndex() {
            const greetings = Array.isArray(this.editingData?.alternate_greetings)
                ? this.editingData.alternate_greetings
                : [];
            return greetings.findIndex((greeting) => this.hasTextValue(greeting));
        },

        get hasGreetingPage() {
            return this.isEditMode || this.hasDefaultGreeting || this.hasAlternateGreetings;
        },

        get dialogPages() {
            const pages = [];
            if (this.hasGreetingPage) pages.push('greeting');
            if (this.isEditMode || this.hasTextValue(this.editingData?.mes_example)) {
                pages.push('example');
            }
            return pages;
        },

        get dialogPageCount() {
            return this.dialogPages.length;
        },

        get dialogPageIndex() {
            const index = this.dialogPages.indexOf(this.dialogPage);
            return index >= 0 ? index + 1 : 0;
        },

        get dialogPageLabel() {
            return this.dialogPage === 'example' ? '对话示例' : '开场白预览';
        },

        get shouldShowDialogPageNav() {
            return this.dialogPageCount > 1;
        },

        get displayedAlternateGreetingItems() {
            const greetings = Array.isArray(this.editingData?.alternate_greetings)
                ? this.editingData.alternate_greetings
                : [];

            return greetings
                .map((value, index) => ({ index, value }))
                .filter((item) => this.hasTextValue(item.value) || (
                    this.isEditMode
                    && this.selectedGreetingKind === 'alternate'
                    && item.index === this.altIdx
                ))
                .map((item, position) => ({ ...item, position: position + 1 }));
        },

        get selectedAlternateGreetingOrdinal() {
            const selected = this.displayedAlternateGreetingItems.find(
                (item) => item.index === this.altIdx,
            );
            return selected?.position || this.altIdx + 1;
        },

        get selectedGreetingContent() {
            if (this.selectedGreetingKind === 'alternate') {
                const greetings = Array.isArray(this.editingData?.alternate_greetings)
                    ? this.editingData.alternate_greetings
                    : [];
                return greetings[this.altIdx] || '';
            }
            return this.editingData?.first_mes || '';
        },

        get selectedGreetingTitle() {
            if (this.selectedGreetingKind === 'alternate') {
                return '备用开场白 #' + this.selectedAlternateGreetingOrdinal;
            }
            return '默认开场白';
        },

        get canRemoveSelectedAlternate() {
            const greetings = Array.isArray(this.editingData?.alternate_greetings)
                ? this.editingData.alternate_greetings
                : [];
            return this.isEditMode
                && this.selectedGreetingKind === 'alternate'
                && this.altIdx >= 0
                && this.altIdx < greetings.length;
        },

        get hasPersonaFields() {
            // 编辑模式下始终显示设定tab
            if (this.isEditMode) return true;
            
            // 阅览模式下只有存在内容才显示
            const d = this.editingData;
            return !!(
                this.hasTextValue(d.personality) ||
                this.hasTextValue(d.scenario) ||
                this.hasTextValue(d.creator_notes) ||
                this.hasTextValue(d.system_prompt) ||
                this.hasTextValue(d.post_history_instructions)
            );
        },

        resetPersonaFieldState() {
            this.personaHiddenFields = this.personaFieldKeys.reduce((fields, field) => {
                fields[field] = false;
                return fields;
            }, {});
            this.personaPreviewField = '';
            this.personaPreviewTitle = '';
            this.personaPreviewEnglish = '';
        },

        get personaFilledFieldCount() {
            return this.personaFieldKeys.filter((field) => this.personaFieldHasContent(field)).length;
        },

        personaFieldHasContent(field) {
            return this.personaFieldKeys.includes(field)
                && this.hasTextValue(this.editingData?.[field]);
        },

        isPersonaFieldHidden(field) {
            return this.personaHiddenFields?.[field] === true;
        },

        togglePersonaFieldVisibility(field) {
            if (!this.personaFieldHasContent(field)) return;
            this.personaHiddenFields[field] = !this.isPersonaFieldHidden(field);
        },

        getPersonaFieldLength(field) {
            const value = this.editingData?.[field];
            return `${typeof value === 'string' ? value.length : 0} 字符`;
        },

        personaFieldStatusLabel(field) {
            if (!this.personaFieldHasContent(field)) return '空字段';
            return this.isPersonaFieldHidden(field) ? '内容已隐藏' : '已填写';
        },

        personaFieldStatusClass(field) {
            if (!this.personaFieldHasContent(field)) return 'is-empty';
            return this.isPersonaFieldHidden(field) ? 'is-hidden' : 'is-filled';
        },

        personaFieldCardClass(field) {
            return {
                'is-empty': !this.personaFieldHasContent(field),
                'is-hidden': this.personaFieldHasContent(field) && this.isPersonaFieldHidden(field),
                'is-editing': this.isEditMode,
                'is-selected': this.personaPreviewField === field,
            };
        },

        openPersonaPreview(field, title, english = '') {
            if (!this.personaFieldKeys.includes(field)) return;
            this.personaPreviewField = field;
            this.personaPreviewTitle = title || field;
            this.personaPreviewEnglish = english || '';
            this.$nextTick(() => this.$refs.personaPreviewClose?.focus());
        },

        openPersonaFieldAction(field, title, english = '') {
            if (this.isEditMode) {
                this.openLargeEditor(field, title);
                return;
            }
            this.openPersonaPreview(field, title, english);
        },

        closePersonaPreview() {
            this.personaPreviewField = '';
            this.personaPreviewTitle = '';
            this.personaPreviewEnglish = '';
        },

        get personaPreviewContent() {
            return this.personaPreviewField
                ? (this.editingData?.[this.personaPreviewField] || '')
                : '';
        },

        editPersonaPreview() {
            const field = this.personaPreviewField;
            const title = this.personaPreviewTitle;
            this.closePersonaPreview();
            if (field) this.openLargeEditor(field, title);
        },

        get hasDialogFields() {
            return this.dialogPages.length > 0;
        },

        syncDialogState({ preferGreeting = false } = {}) {
            const greetings = Array.isArray(this.editingData?.alternate_greetings)
                ? this.editingData.alternate_greetings
                : [];
            const selectedAlternateIsAvailable = this.selectedGreetingKind === 'alternate'
                && this.altIdx >= 0
                && this.altIdx < greetings.length
                && (this.isEditMode || this.hasTextValue(greetings[this.altIdx]));

            if (!selectedAlternateIsAvailable) {
                const firstAlternateIndex = this.firstAlternateGreetingIndex;
                if (!this.hasDefaultGreeting && firstAlternateIndex >= 0) {
                    this.selectedGreetingKind = 'alternate';
                    this.altIdx = firstAlternateIndex;
                } else {
                    this.selectedGreetingKind = 'default';
                    this.altIdx = 0;
                }
            }

            const pages = this.dialogPages;
            if (preferGreeting && pages.includes('greeting')) {
                this.dialogPage = 'greeting';
            } else if (!pages.includes(this.dialogPage)) {
                this.dialogPage = pages[0] || 'greeting';
            }
        },

        selectDialogPage(page) {
            if (!this.dialogPages.includes(page)) return;
            this.dialogPage = page;
        },

        moveDialogPage(direction) {
            const pages = this.dialogPages;
            if (pages.length < 2) return;
            const currentIndex = pages.indexOf(this.dialogPage);
            const nextIndex = (currentIndex + direction + pages.length) % pages.length;
            this.dialogPage = pages[nextIndex];
        },

        selectGreeting(kind, index = 0) {
            if (kind === 'default') {
                this.selectedGreetingKind = 'default';
                return;
            }

            const greetings = Array.isArray(this.editingData?.alternate_greetings)
                ? this.editingData.alternate_greetings
                : [];
            if (index < 0 || index >= greetings.length) return;
            if (!this.isEditMode && !this.hasTextValue(greetings[index])) return;

            this.selectedGreetingKind = 'alternate';
            this.altIdx = index;
        },

        setSelectedGreetingContent(value) {
            if (this.selectedGreetingKind === 'alternate') {
                if (!Array.isArray(this.editingData.alternate_greetings)) {
                    this.editingData.alternate_greetings = [];
                }
                if (this.altIdx >= 0 && this.altIdx < this.editingData.alternate_greetings.length) {
                    this.editingData.alternate_greetings[this.altIdx] = value;
                    return;
                }
            }
            this.editingData.first_mes = value;
        },

        getGreetingExcerpt(value) {
            const text = typeof value === 'string' ? value.trim().replace(/\s+/g, ' ') : '';
            if (!text) return '未填写';
            return text.length > 56 ? `${text.slice(0, 56)}...` : text;
        },

        openSelectedGreetingEditor() {
            if (this.selectedGreetingKind === 'alternate') {
                this.openLargeEditor(
                    'alternate_greetings',
                    '备用开场白 #' + this.selectedAlternateGreetingOrdinal,
                    true,
                    this.altIdx,
                );
                return;
            }
            this.openLargeEditor('first_mes', '默认开场白');
        },

        addAlt() {
            if (!Array.isArray(this.editingData.alternate_greetings)) {
                this.editingData.alternate_greetings = [];
            }

            const greetings = this.editingData.alternate_greetings;
            let nextIndex = greetings.findIndex((greeting) => !this.hasTextValue(greeting));
            if (nextIndex < 0) {
                greetings.push('');
                nextIndex = greetings.length - 1;
            }

            this.selectedGreetingKind = 'alternate';
            this.altIdx = nextIndex;
            this.dialogPage = 'greeting';
            this.showGreetingPreview = false;
        },

        removeSelectedAlternate() {
            if (!this.canRemoveSelectedAlternate) return;
            if (!confirm('确定删除' + this.selectedGreetingTitle + '吗？')) return;

            this.editingData.alternate_greetings.splice(this.altIdx, 1);
            if (this.editingData.alternate_greetings.length === 0) {
                this.editingData.alternate_greetings = [''];
            }

            this.selectedGreetingKind = 'default';
            this.altIdx = 0;
            this.showGreetingPreview = false;
        },

        moveAlternateGreeting(index, direction) {
            const targetIndex = index + direction;
            const greetings = Array.isArray(this.editingData?.alternate_greetings)
                ? [...this.editingData.alternate_greetings]
                : [];
            if (index < 0 || index >= greetings.length) return;
            if (targetIndex < 0 || targetIndex >= greetings.length) return;

            const [movedGreeting] = greetings.splice(index, 1);
            greetings.splice(targetIndex, 0, movedGreeting);
            this.editingData.alternate_greetings = greetings;
            this.detailAltDropIndex = null;

            if (this.selectedGreetingKind !== 'alternate') return;
            if (this.altIdx === index) {
                this.altIdx = targetIndex;
            } else if (index < this.altIdx && this.altIdx <= targetIndex) {
                this.altIdx -= 1;
            } else if (targetIndex <= this.altIdx && this.altIdx < index) {
                this.altIdx += 1;
            }
        },

        onAltDragStart(event, index) {
            if (!this.isEditMode) return;
            this.detailAltDragIndex = index;
            this.detailAltDropIndex = null;
            this.detailAltSuppressClick = false;
            if (!event.dataTransfer) return;
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', String(index));
        },

        onAltDragOver(event, index) {
            if (!this.isEditMode || this.detailAltDragIndex === null || this.detailAltDragIndex === index) return;
            event.preventDefault();
            this.detailAltDropIndex = index;
            if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
        },

        onAltDrop(event, targetIndex) {
            if (!this.isEditMode) return;
            event.preventDefault();

            const sourceRaw = event.dataTransfer?.getData('text/plain');
            const sourceIndex = Number.isInteger(this.detailAltDragIndex)
                ? this.detailAltDragIndex
                : Number.parseInt(sourceRaw, 10);
            if (!Number.isInteger(sourceIndex) || sourceIndex === targetIndex) {
                this.detailAltDragIndex = null;
                this.detailAltDropIndex = null;
                return;
            }

            this.moveAlternateGreeting(sourceIndex, targetIndex - sourceIndex);
            this.detailAltDragIndex = null;
            this.detailAltDropIndex = null;
            this.detailAltSuppressClick = true;
        },

        onAltDragEnd() {
            this.detailAltDragIndex = null;
            this.detailAltDropIndex = null;
        },

        handleAltCardClick(event, index) {
            if (!this.consumeAltDragClick()) {
                event.preventDefault();
                event.stopPropagation();
                return;
            }
            this.selectGreeting('alternate', index);
        },

        consumeAltDragClick() {
            const suppressed = this.detailAltSuppressClick;
            this.detailAltSuppressClick = false;
            return !suppressed;
        },

        onAltPointerDown(event, index) {
            if (!this.isEditMode || event.pointerType === 'mouse') return;
            if (!event.target?.closest?.('.detail-greeting-drag-handle')) return;
            this.detailAltPointer = {
                index,
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                active: false,
            };
            event.preventDefault();
            event.currentTarget?.setPointerCapture?.(event.pointerId);
        },

        onAltPointerMove(event) {
            const pointer = this.detailAltPointer;
            if (!this.isEditMode || !pointer || pointer.pointerId !== event.pointerId) return;

            const distance = Math.hypot(
                event.clientX - pointer.startX,
                event.clientY - pointer.startY,
            );
            if (!pointer.active && distance < 8) return;

            if (!pointer.active) {
                pointer.active = true;
                this.detailAltDragIndex = pointer.index;
            }
            event.preventDefault();

            const target = document
                .elementFromPoint(event.clientX, event.clientY)
                ?.closest?.('[data-alt-index]');
            const targetIndex = Number.parseInt(target?.dataset?.altIndex ?? '', 10);
            if (Number.isInteger(targetIndex)) this.detailAltDropIndex = targetIndex;
        },

        onAltPointerUp(event) {
            const pointer = this.detailAltPointer;
            if (!pointer || pointer.pointerId !== event.pointerId) return;

            if (pointer.active) {
                const targetIndex = this.detailAltDropIndex;
                if (Number.isInteger(targetIndex) && targetIndex !== pointer.index) {
                    this.moveAlternateGreeting(pointer.index, targetIndex - pointer.index);
                }
                this.detailAltSuppressClick = true;
            }
            this.onAltPointerCancel(event);
        },

        onAltPointerCancel(event) {
            const pointer = this.detailAltPointer;
            if (pointer && event.pointerId !== undefined && pointer.pointerId !== event.pointerId) return;
            this.detailAltPointer = null;
            this.detailAltDragIndex = null;
            this.detailAltDropIndex = null;
        },

        onAltCardKeydown(event, index) {
            if (!this.isEditMode) return;
            const direction = ['ArrowLeft', 'ArrowUp'].includes(event.key)
                ? -1
                : ['ArrowRight', 'ArrowDown'].includes(event.key)
                    ? 1
                    : 0;
            if (!direction) return;

            event.preventDefault();
            this.selectGreeting('alternate', index);
            this.moveAlternateGreeting(index, direction);
        },

        ensureVisibleDetailTab() {
            if (this.isEditMode) return;
            if (this.tab === 'persona' && !this.hasPersonaFields) {
                this.tab = 'basic';
            }
            if (this.tab === 'dialog' && !this.hasDialogFields) {
                this.tab = 'basic';
            }
        },

        toggleEditMode() {
            const enteringEditMode = !this.isEditMode;
            this.isEditMode = enteringEditMode;
            this.showGreetingPreview = !enteringEditMode;
            this.syncDialogState({ preferGreeting: enteringEditMode });
            this.ensureVisibleDetailTab();
        },

        get filteredTagLibraryPool() {
            const pool = Array.isArray(this.$store?.global?.globalTagsPool)
                ? this.$store.global.globalTagsPool
                : [];
            const query = this.tagLibrarySearch || '';
            if (!query.trim()) return pool;
            const slashIsSeparator = !!(this.$store?.global?.settingsForm?.automation_slash_is_tag_separator);
            return pool.filter(tag => matchAnyTagSearchToken(tag, query, { slashIsSeparator }));
        },

        loadTagViewPrefs() {
            const tagViewPrefs = this.$store.global.loadTagViewPrefs();
            const rememberLastTagView = tagViewPrefs.rememberLastTagView === true;
            this.mixedCategoryView = rememberLastTagView
                ? tagViewPrefs.mixedCategoryView !== false
                : true;
            this.detailCategoryFilterInclude = Array.isArray(tagViewPrefs.categoryFilterInclude) && rememberLastTagView
                ? [...tagViewPrefs.categoryFilterInclude]
                : [];
            this.detailCategoryFilterExclude = Array.isArray(tagViewPrefs.categoryFilterExclude) && rememberLastTagView
                ? [...tagViewPrefs.categoryFilterExclude]
                : [];
            return tagViewPrefs;
        },

        saveTagViewPrefs() {
            return this.$store.global.saveTagViewPrefs({
                mixedCategoryView: this.mixedCategoryView,
                categoryFilterInclude: this.detailCategoryFilterInclude,
                categoryFilterExclude: this.detailCategoryFilterExclude,
            });
        },

        get detailBaseTagGroups() {
            const store = this.$store?.global;
            if (!store || typeof store.groupTagsByTaxonomy !== 'function') return [];
            return store.groupTagsByTaxonomy(this.filteredTagLibraryPool || []);
        },

        get detailFilterCategoryNames() {
            return (this.detailBaseTagGroups || []).map(group => group.category);
        },

        get isDetailCategoryFilterAllMixed() {
            return this.mixedCategoryView
                && this.detailCategoryFilterInclude.length === 0
                && this.detailCategoryFilterExclude.length === 0;
        },

        get detailFilteredTagLibraryGroups() {
            const includeSet = new Set(this.detailCategoryFilterInclude || []);
            const excludeSet = new Set(this.detailCategoryFilterExclude || []);
            const groups = this.detailBaseTagGroups || [];

            return groups.filter((group) => {
                const category = String(group.category || '').trim();
                if (!category) return false;
                if (excludeSet.has(category)) return false;
                if (includeSet.size > 0 && !includeSet.has(category)) return false;
                return true;
            });
        },

        get detailFilteredMixedTagsPool() {
            const includeSet = new Set(this.detailCategoryFilterInclude || []);
            const excludeSet = new Set(this.detailCategoryFilterExclude || []);
            const pool = this.filteredTagLibraryPool || [];

            if (includeSet.size === 0 && excludeSet.size === 0) {
                return pool;
            }

            return pool.filter((tag) => {
                const category = this.getTagCategory(tag);
                if (excludeSet.has(category)) return false;
                if (includeSet.size > 0 && !includeSet.has(category)) return false;
                return true;
            });
        },

        get detailFilteredVisibleTagCount() {
            if (this.mixedCategoryView) return this.detailFilteredMixedTagsPool.length;
            return this.detailFilteredTagLibraryGroups.reduce((acc, group) => acc + (group.tags || []).length, 0);
        },

        get filteredTagLibraryGroups() {
            return this.detailFilteredTagLibraryGroups;
        },

        getTagChipStyle(tag) {
            const store = this.$store?.global;
            if (!store || typeof store.getTagChipStyle !== 'function') return '';
            return store.getTagChipStyle(tag);
        },

        getTagCategory(tag) {
            const store = this.$store?.global;
            if (!store || typeof store.getTagCategory !== 'function') return '未分类';
            return store.getTagCategory(tag);
        },

        getCategoryColor(category) {
            const store = this.$store?.global;
            if (!store || typeof store.getCategoryColor !== 'function') return '#64748b';
            return store.getCategoryColor(category);
        },

        getDetailCategoryFilterState(category) {
            if (this.detailCategoryFilterInclude.includes(category)) return 'included';
            if (this.detailCategoryFilterExclude.includes(category)) return 'excluded';
            return 'none';
        },

        toggleDetailCategoryFilter(category, event = null) {
            const name = String(category || '').trim();
            if (!name) return;

            const forceExclude = !!(event && event.shiftKey);
            const include = [...(this.detailCategoryFilterInclude || [])];
            const exclude = [...(this.detailCategoryFilterExclude || [])];

            const inInclude = include.indexOf(name);
            const inExclude = exclude.indexOf(name);

            this.mixedCategoryView = false;

            if (forceExclude) {
                if (inInclude > -1) include.splice(inInclude, 1);
                if (inExclude === -1) exclude.push(name);
            } else if (inInclude > -1) {
                include.splice(inInclude, 1);
                if (inExclude === -1) exclude.push(name);
            } else if (inExclude > -1) {
                exclude.splice(inExclude, 1);
            } else {
                include.push(name);
            }

            this.detailCategoryFilterInclude = include;
            this.detailCategoryFilterExclude = exclude;
            this.saveTagViewPrefs();
        },

        showAllDetailCategoriesMixed() {
            this.detailCategoryFilterInclude = [];
            this.detailCategoryFilterExclude = [];
            this.mixedCategoryView = true;
            this.saveTagViewPrefs();
        },

        sanitizeDetailCategoryFilterState() {
            const valid = new Set(this.detailFilterCategoryNames || []);
            this.detailCategoryFilterInclude = (this.detailCategoryFilterInclude || []).filter(name => valid.has(name));
            this.detailCategoryFilterExclude = (this.detailCategoryFilterExclude || []).filter(name => valid.has(name));
        },

        // === 初始化 ===
        init() {
            // 监听打开详情页事件
            window.addEventListener('open-detail', (e) => {
                this.openDetail(e.detail);
            });

            window.addEventListener('refresh-detail-chats', () => {
                if (this.showDetail && this.activeCard && this.activeCard.id) {
                    this.fetchCardChats(this.activeCard.id);
                }
            });

            window.addEventListener('refresh-chat-list', () => {
                if (this.showDetail && this.activeCard && this.activeCard.id) {
                    this.fetchCardChats(this.activeCard.id);
                }
            });

            window.addEventListener('tags-deleted', (event) => {
                if (!this.showDetail || !this.activeCard || !this.activeCard.id) return;
                const cardIds = Array.isArray(event?.detail?.cardIds)
                    ? event.detail.cardIds
                    : [];
                const activeIds = [this.activeCard.id, this.editingData?.id]
                    .filter(Boolean);
                const changedId = activeIds.find(id => cardIds.includes(id));
                if (changedId) {
                    this.refreshActiveCardDetail(changedId);
                }
            });

            // 监听关闭信号
            this.$watch('showDetail', (val) => {
                if (!val) {
                    this.stopAutoSave();
                    this._cleanupPendingAdvancedEditorHandlers();
                    clearActiveRuntimeContext('card');
                    this.currentSkinIndex = -1;
                    this.currentSkinDirectory = '';
                    this.showSkinGallery = false;
                    this.skinGalleryPreviewPath = '';
                    this.zoomLevel = 100;
                    this.isCardFlipped = false;
                    this.skinImages = [];
                    this.cardChats = [];
                    this.updateImagePolicy = 'overwrite';
                    this.syncSourceTitleOnUpdate = this.$store?.global?.settingsForm?.sync_source_title_on_update !== false;
                    this.sourceUpdateChecking = false;
                    this.sourceUpdateAcknowledging = false;
                    this.saveOldCoverOnSwap = false;
                    this.isEditMode = false; // 重置编辑模式
                    this.showTagLibrary = true;
                    this.tagLibrarySearch = '';
                    this.mixedCategoryView = true;
                    this.detailCategoryFilterInclude = [];
                    this.detailCategoryFilterExclude = [];
                }
            });

            // 标题同步开关是常驻偏好，沿用全局设置接口持久化。
            this.$watch('syncSourceTitleOnUpdate', (value) => {
                if (!this.showDetail || !this.$store?.global?.settingsForm) return;
                const normalized = value !== false;
                if (this.$store.global.settingsForm.sync_source_title_on_update === normalized) return;
                this.$store.global.settingsForm.sync_source_title_on_update = normalized;
                Promise.resolve(this.$store.global.saveSettings(false)).catch(() => {});
            });

        },

        // === 新增：处理资源 Tab 的文件拖拽 ===
        async handleResourceDrop(e) {
            this.dragOverResource = false;
            const files = Array.from(e?.dataTransfer?.files || []);
            if (files.length === 0) return;

            try {
                await this.ensureResourceFolder({ silent: true, auto: true });
                const results = await Promise.all(files.map(file => this.uploadSingleResource(file)));

                if (this.editingData.resource_folder) {
                    this.fetchResourceFiles(this.editingData.resource_folder);
                }

                if (results.some(res => res && res.is_lorebook)) {
                    window.dispatchEvent(new CustomEvent('refresh-wi-list'));
                }
            } catch (error) {
                const msg = error?.message || error;
                alert(`资源导入失败: ${msg}`);
            }
        },

        async handleResourceInputChange(e) {
            const input = e.target;

            try {
                await this.handleResourceDrop({ dataTransfer: { files: input.files } });
            } finally {
                input.value = '';
            }
        },

        getCardChatImportPayload() {
            const card = this.activeCard || {};
            return {
                cardId: card.is_bundle ? (card.bundle_dir || card.id) : card.id,
                characterName: this.editingData.char_name || card.char_name || '',
            };
        },

        uploadCardChatFiles(files) {
            const fileList = Array.from(files || []);
            if (fileList.length === 0) return;

            if (typeof window.stUploadChatFiles !== 'function') {
                alert('聊天网格尚未准备好，稍后再试一次。');
                return;
            }

            window.stUploadChatFiles(fileList, this.getCardChatImportPayload());
        },

        handleCardChatDrop(e) {
            this.dragOverCardChats = false;
            this.uploadCardChatFiles(e?.dataTransfer?.files || []);
        },

        handleCardChatInputChange(e) {
            const input = e?.target;

            try {
                this.uploadCardChatFiles(input?.files || []);
            } finally {
                if (input) input.value = '';
            }
        },

        async uploadSingleResource(file) {
            const formData = new FormData();
            formData.append('card_id', this.editingData.id);
            formData.append('file', file);

            this.$store.global.showToast(`正在上传: ${file.name}...`, 2000, "card-loader");

            try {
                const res = await uploadCardResource(formData);
                if (res.success) {
                    if (res.resource_folder) {
                        this.editingData.resource_folder = res.resource_folder;
                        this.activeCard.resource_folder = res.resource_folder;
                    }
                    this.$store.global.showToast(`${file.name} 上传成功`, 3000, "card-check");
                    return res;
                } else {
                    alert(`上传 ${file.name} 失败: ${res.msg}`);
                }
            } catch (e) {
                alert(`网络错误: ${e}`);
            }

            return null;
        },

        async ensureResourceFolder(options = {}) {
            const {
                silent = false,
                auto = false
            } = options;

            if (this.editingData.resource_folder) {
                return this.editingData.resource_folder;
            }

            if (this.resourceFolderCreationPromise) {
                return this.resourceFolderCreationPromise;
            }

            this.resourceFolderCreationPromise = apiCreateResourceFolder({ card_id: this.editingData.id })
                .then(res => {
                    if (!res.success) {
                        throw new Error(res.msg || '创建资源目录失败');
                    }

                    this.editingData.resource_folder = res.resource_folder;
                    this.activeCard.resource_folder = res.resource_folder;
                    this.fetchResourceFiles(res.resource_folder);

                    if (auto) {
                        this.$store.global.showToast('已自动创建资源目录', 1800, 'card-folder');
                    } else if (!silent) {
                        this.$store.global.showToast('资源目录已创建', 1800, 'card-folder');
                    }

                    return res.resource_folder;
                })
                .catch(err => {
                    if (!silent) {
                        alert('创建资源目录失败: ' + (err?.message || err));
                    }
                    throw err;
                })
                .finally(() => {
                    this.resourceFolderCreationPromise = null;
                });

            return this.resourceFolderCreationPromise;
        },

        // 获取资源目录下的所有文件
        fetchResourceFiles(folderName) {
            // 清空旧数据
            this.skinImages = [];
            this.resourceLorebooks = [];
            this.resourceRegex = [];
            this.resourceScripts = [];
            this.resourceQuickReplies = [];
            this.resourcePresets = [];
            this.resourceUnknown = [];
            this.currentSkinIndex = -1;
            this.currentSkinDirectory = '';
            this.showSkinGallery = false;
            this.skinGalleryPreviewPath = '';

            if (!folderName) return;

            // 调用新 API
            listResourceFiles(folderName).then(res => {
                if (res.success && res.files) {
                    this.skinImages = (res.files.skins || [])
                        .map(pathValue => this.normalizeResourcePath(pathValue))
                        .filter(Boolean);
                    this.resourceLorebooks = res.files.lorebooks || [];
                    this.resourceRegex = res.files.regex || [];
                    this.resourceScripts = res.files.scripts || [];
                    this.resourceQuickReplies = res.files.quick_replies || [];
                    this.resourcePresets = res.files.presets || [];
                    this.resourceUnknown = res.files.unknown || [];
                }
            }).catch(err => {
                console.error("Failed to load resources:", err);
            });
        },

        // 打开资源脚本 (Regex / ST Script)
        openResourceScript(fileItem, type) {
            // fileItem 是 API 返回的对象: { name: "abc.json", path: "data/..." }
            if (!fileItem || !fileItem.path) return;

            this.$store.global.isLoading = true;

            // 1. 读取文件内容
            readFileContent({ path: fileItem.path }).then(res => {
                this.$store.global.isLoading = false;
                
                if (res.success) {
                    const fileContent = res.data;
                    
                    // 2. 触发事件打开 Advanced Editor
                    // 传递 filePath 以便编辑器知道这是一个独立文件，保存时覆盖原文件
                    window.dispatchEvent(new CustomEvent('open-script-file-editor', {
                        detail: {
                            fileData: fileContent, // JSON 对象
                            filePath: fileItem.path, // 文件路径 (用于保存)
                            type: type // 'regex' | 'script'
                        }
                    }));
                } else {
                    alert("无法读取文件内容: " + res.msg);
                }
            }).catch(err => {
                this.$store.global.isLoading = false;
                alert("读取请求失败: " + err);
            });
        },

        // 打开预设文件
        openResourcePreset(fileItem) {
            // fileItem 是 API 返回的对象: { name: "abc.json", path: "data/..." }
            if (!fileItem || !fileItem.path) return;

            // 解析路径生成正确的预设 ID 格式: resource::folder::name
            // 路径格式: data/assets/card_assets/folder/presets/name.json
            const pathParts = fileItem.path.replace(/\\/g, '/').split('/');
            const presetsIndex = pathParts.indexOf('presets');
            
            if (presetsIndex > 0) {
                // 获取文件夹名称 (在 presets 的父目录)
                const folderName = pathParts[presetsIndex - 1];
                // 获取预设名称 (去掉 .json 后缀)
                const presetName = fileItem.name.replace(/\.json$/i, '');
                const presetId = `resource::${folderName}::${presetName}`;
                
                // 触发打开预设阅览界面事件
                window.dispatchEvent(new CustomEvent('open-preset-reader', {
                    detail: {
                        id: presetId,
                        name: fileItem.name,
                        source: 'resource'
                    }
                }));
            } else {
                alert("无效的预设文件路径");
            }
        },

        // 资源文件工具方法
        getResourceRelativePath(fileItem) {
            if (!fileItem) return '';
            if (typeof fileItem === 'string') return fileItem;
            return fileItem.relative_path || fileItem.filename || fileItem.name || '';
        },

        getResourceDisplayName(fileItem) {
            if (!fileItem) return '';
            if (typeof fileItem === 'string') return fileItem;
            return fileItem.name || fileItem.relative_path || fileItem.path || '';
        },

        encodeResourcePath(pathValue) {
            return String(pathValue || '')
                .replace(/\\/g, '/')
                .split('/')
                .filter(Boolean)
                .map(part => encodeURIComponent(part))
                .join('/');
        },

        normalizeResourcePath(pathValue) {
            return String(pathValue || '')
                .replace(/\\/g, '/')
                .split('/')
                .map(part => part.trim())
                .filter(Boolean)
                .join('/');
        },

        getResourcePathName(pathValue) {
            const parts = this.normalizeResourcePath(pathValue).split('/').filter(Boolean);
            return parts.length > 0 ? parts[parts.length - 1] : '';
        },

        getResourceParentPath(pathValue) {
            const parts = this.normalizeResourcePath(pathValue).split('/').filter(Boolean);
            parts.pop();
            return parts.join('/');
        },

        enterSkinDirectory(pathValue = '') {
            this.currentSkinDirectory = this.normalizeResourcePath(pathValue);
            this.currentSkinIndex = -1;
            this.isCardFlipped = false;
        },

        goToSkinDirectory(pathValue = '') {
            this.enterSkinDirectory(pathValue);
        },

        goToSkinParentDirectory() {
            this.enterSkinDirectory(this.getResourceParentPath(this.currentSkinDirectory));
        },

        selectSkinByPath(pathValue) {
            const normalizedPath = this.normalizeResourcePath(pathValue);
            const index = this.skinImages.findIndex(skin => this.normalizeResourcePath(skin) === normalizedPath);
            if (index === -1) return;

            this.currentSkinIndex = index;
            this.currentSkinDirectory = this.getResourceParentPath(normalizedPath);
            this.isCardFlipped = false;
        },

        isSkinPathSelected(pathValue) {
            return this.selectedSkinPath === this.normalizeResourcePath(pathValue);
        },

        async deleteResourceItem(fileItem, label = '资源') {
            const relativePath = this.getResourceRelativePath(fileItem);
            if (!relativePath) return;

            const displayName = this.getResourceDisplayName(fileItem) || relativePath;
            if (!confirm(`确定要删除${label}文件 "${displayName}" 吗？\n文件将被移动到回收站。`)) return;

            this.isSaving = true;
            try {
                const res = await deleteResourceFile({
                    card_id: this.activeCard.id,
                    filename: relativePath,
                });
                if (res.success) {
                    this.$store.global.showToast(`${label}已删除`, 3000, 'context-delete');
                    this.fetchResourceFiles(this.editingData.resource_folder);
                } else {
                    alert("删除失败: " + res.msg);
                }
            } catch (e) {
                alert("请求错误: " + e);
            } finally {
                this.isSaving = false;
            }
        },

        // 删除当前选中的皮肤
        deleteCurrentSkin() {
            if (this.currentSkinIndex === -1) return;
            const skinName = this.selectedSkinPath;
            if (!skinName) return;
            
            if (!confirm(`确定要删除皮肤文件 "${skinName}" 吗？\n文件将被移至回收站。`)) return;
            
            this.isSaving = true; // 借用 loading 状态
            
            deleteResourceFile({
                card_id: this.activeCard.id,
                filename: skinName
            }).then(res => {
                this.isSaving = false;
                if (res.success) {
                    this.$store.global.showToast("皮肤已删除", 3000, "context-delete");
                    
                    // 移除当前项
                    this.skinImages.splice(this.currentSkinIndex, 1);
                    
                    // 重置选择
                    this.currentSkinIndex = -1;
                    
                    // 如果删完了，刷新一下列表（可选）
                    if (this.skinImages.length === 0) {
                        this.fetchSkins(this.editingData.resource_folder);
                    }
                } else {
                    alert("删除失败: " + res.msg);
                }
            }).catch(e => {
                this.isSaving = false;
                alert("请求错误: " + e);
            });
        },

        // 世界书全屏编辑
        openFullScreenWI() {
            // 构造一个临时 item 对象，告诉编辑器这是"内嵌"模式
            // 传递当前内存中的世界书数据，实现双向同步
            const item = {
                type: 'embedded',
                card_id: this.activeCard.id,
                name: this.editingData.character_book?.name || "World Info",
                // 传递当前内存中的世界书数据，避免重新从服务器加载
                character_book: JSON.parse(JSON.stringify(this.editingData.character_book)),
                // 传递整个editingData以支持保存操作
                editingData: JSON.parse(JSON.stringify(this.editingData))
            };
            // 派发事件，由 wiEditor.js 监听处理
            window.dispatchEvent(new CustomEvent('open-wi-editor', { detail: item }));

            // 监听全屏编辑器关闭事件，同步数据回来
            const handleEditorClosed = (e) => {
                const { character_book } = e.detail || {};
                if (character_book) {
                    // 将全屏编辑器的修改同步回detailModal
                    this.editingData.character_book = character_book;
                    this.editingData.character_book_raw = JSON.stringify(character_book, null, 2);
                    this.$store.global.showToast('世界书数据已同步', 1500);
                }
                // 移除监听，避免重复
                window.removeEventListener('wi-editor-closed', handleEditorClosed);
            };
            window.addEventListener('wi-editor-closed', handleEditorClosed);
        },

        fetchCardChats(cardId) {
            if (!cardId) {
                this.cardChats = [];
                return;
            }

            this.cardChatsLoading = true;
            listChats({ page: 1, page_size: 200, card_id: cardId, filter: 'all' })
                .then((res) => {
                    this.cardChatsLoading = false;
                    if (!res.success) {
                        this.cardChats = [];
                        return;
                    }
                    this.cardChats = Array.isArray(res.items) ? res.items : [];
                })
                .catch(() => {
                    this.cardChatsLoading = false;
                    this.cardChats = [];
                });
        },

        formatChatFloorDate(ts) {
            return formatDate(ts);
        },

        openChatManagerForCard(chatId = '') {
            const targetCardId = this.activeCard?.is_bundle ? (this.activeCard.bundle_dir || this.activeCard.id) : this.activeCard.id;
            window.dispatchEvent(new CustomEvent('open-chat-manager', {
                detail: {
                    card_id: targetCardId,
                    card_name: this.editingData.char_name || this.activeCard.char_name || '',
                    chat_id: chatId || '',
                }
            }));
            this.showDetail = false;
        },

        openChatReaderForCard(chatId = '') {
            if (!chatId) return;
            window.dispatchEvent(new CustomEvent('open-chat-reader', {
                detail: {
                    chat_id: chatId,
                    card_id: this.activeCard?.is_bundle ? (this.activeCard.bundle_dir || this.activeCard.id) : this.activeCard.id,
                    card_name: this.editingData.char_name || this.activeCard.char_name || '',
                }
            }));
            this.showDetail = false;
        },

        triggerChatImportForCard() {
            if (typeof window.stUploadChatFiles !== 'function') {
                alert('聊天网格尚未准备好，稍后再试一次。');
                return;
            }

            if (this.$refs?.cardChatImportInput) {
                this.$refs.cardChatImportInput.click();
                return;
            }

            window.dispatchEvent(new CustomEvent('open-chat-file-picker', {
                detail: {
                    mode: 'card',
                    payload: this.getCardChatImportPayload(),
                }
            }));
        },

        // 跳转定位
        locateCard() {
            const locateTarget = {
                id: this.activeCard.id,
                category: this.activeCard.category,
                is_bundle: this.activeCard.is_bundle,
                bundle_dir: this.activeCard.bundle_dir,
                shouldOpenDetail: false
            };
            // 派发事件，由 cardGrid.js 监听处理
            window.dispatchEvent(new CustomEvent('locate-card', { detail: locateTarget }));
            this.showDetail = false; // 关闭详情页
        },

        // 打开所在文件夹
        openCardLocation() {
            if (!this.activeCard || !this.activeCard.id) return;
            performSystemAction('open_card_dir', { card_id: this.activeCard.id });
        },

        // 时光机
        openRollback(type) {
            // 派发事件，由 rollbackModal.js 监听
            window.dispatchEvent(new CustomEvent('open-rollback', {
                detail: {
                    type: type, // 'card'
                    id: this.activeCard.id,
                    path: "", // 角色卡不需要 path，由 ID 决定
                    editingData: this.editingData // 传过去用于获取由 Live Content
                }
            }));
        },

        // 删除当前卡片
        async deleteCards(ids) {
            if (!ids || ids.length === 0) return;
            
            let confirmMsg = "";
            if (this.activeCard.is_bundle) {
                confirmMsg = `【操作确认】\n\n你选中了聚合角色包：\n${this.activeCard.char_name}\n\n确认将其移至回收站吗？\n(这会将整个文件夹及内部所有版本图片移走)`;
            } else {
                confirmMsg = `确定要将角色卡 "${this.activeCard.char_name}" 移至回收站吗？`;
            }
                
            if (!confirm(confirmMsg)) return;

            import('../api/card.js').then(async module => {
                // 检查是否有资源目录需要确认
                const checkRes = await module.checkResourceFolders(ids);
                let deleteResources = false;
                
                if (checkRes.success && checkRes.has_resources) {
                    const folders = checkRes.resource_folders;
                    let resourceMsg = `检测到以下角色卡关联了资源目录：\n\n`;
                    
                    folders.forEach(item => {
                        resourceMsg += `${item.card_name}\n   资源目录: ${item.resource_folder}\n\n`;
                    });
                    
                    resourceMsg += `是否连带删除这些资源目录？\n`;
                    resourceMsg += `（注意：如果资源目录包含重要文件，建议选择"取消"保留目录）`;
                    
                    deleteResources = confirm(resourceMsg);
                }
                
                module.deleteCards(ids, deleteResources).then(res => {
                    if (res.success) {
                        this.$store.global.showToast("已移至回收站", 3000, "context-delete");
                        this.showDetail = false;
                        
                        // 通知列表刷新
                        window.dispatchEvent(new CustomEvent('refresh-card-list'));
                        // 如果有侧边栏计数变化，刷新文件夹
                        if(res.category_counts) this.$store.global.categoryCounts = res.category_counts;
                    } else {
                        alert("删除失败: " + res.msg);
                    }
                });
            });
        },

        // === 打开详情页逻辑 (数据清洗与加载) ===
        openDetail(c) {
            // 重置状态
            this.stopAutoSave();
            this._cleanupPendingAdvancedEditorHandlers();
            this.originalDataJson = null;
            this.activeCard = c;
            this.syncSourceTitleOnUpdate = this.$store?.global?.settingsForm?.sync_source_title_on_update !== false;
            this.sourceUpdateChecking = false;
            this.skinImages = [];
            this.currentSkinIndex = -1;
            this.currentSkinDirectory = '';
            this.showSkinGallery = false;
            this.skinGalleryPreviewPath = '';
            this.isCardFlipped = false;
            this.dialogPage = 'greeting';
            this.selectedGreetingKind = 'default';
            this.showGreetingPreview = true;
            this.isEditMode = false;
            this.resetPersonaFieldState();
            this.altIdx = 0;
            this.detailAltDragIndex = null;
            this.detailAltDropIndex = null;
            this.detailAltPointer = null;
            this.detailAltSuppressClick = false;
            this.showLocalNotePreview = false;
            this.lastTab = this.tab; 
            this.tab = 'basic';
            this.showTagLibrary = true;
            this.tagLibrarySearch = '';
            this.loadTagViewPrefs();

            // 深拷贝并清洗数据 (Flatten & Sanitize)
            let rawData = JSON.parse(JSON.stringify(c));

            // 1. 解包嵌套 data (Tavern V3)
            if (rawData.data && typeof rawData.data === 'object') {
                Object.assign(rawData, rawData.data);
                delete rawData.data;
            }

            // 2. 确保扩展字段存在
            if (!rawData.extensions || typeof rawData.extensions !== 'object') rawData.extensions = {};
            this._convertLegacyTavernHelper(rawData.extensions);
            const rawHelper = rawData.extensions.tavern_helper;
            if (rawHelper === null || rawHelper === undefined) {
                rawData.extensions.tavern_helper = {};
            } else if (Array.isArray(rawHelper)) {
                // 旧版，保留
            } else if (typeof rawHelper === 'object') {
                // 新版，保留
            } else {
                rawData.extensions.tavern_helper = {};
            }
            if (!Array.isArray(rawData.extensions.regex_scripts)) rawData.extensions.regex_scripts = [];

            // 3. 确保备用开场白
            if (!Array.isArray(rawData.alternate_greetings)) rawData.alternate_greetings = [];
            rawData.alternate_greetings = rawData.alternate_greetings.filter(g => typeof g === 'string');
            if (rawData.alternate_greetings.length === 0) rawData.alternate_greetings = [""];

            // 4. 补全 UI 字段
            rawData.ui_summary = rawData.ui_summary || c.ui_summary || "";
            rawData.source_link = rawData.source_link ?? c.source_link ?? "";
            rawData.source_title = rawData.source_title ?? c.source_title ?? "";
            rawData.source_update = rawData.source_update ?? c.source_update ?? null;
            rawData.resource_folder = rawData.resource_folder || c.resource_folder || "";
            
            // === 版本号字段映射 (DB: char_version -> V3: character_version) ===
            // 如果传入的对象只有 char_version (列表数据)，则赋值给 character_version
            if (!rawData.character_version && rawData.char_version) {
                rawData.character_version = rawData.char_version;
            }

            // 5. 确保文本字段不为 null
            ['description', 'first_mes', 'mes_example', 'creator_notes'].forEach(k => {
                if (rawData[k] === null || rawData[k] === undefined) rawData[k] = "";
            });

            // 赋值给编辑器（带结构兜底，避免模板读取 undefined）
            this.editingData = this._normalizeEditingDataShape(rawData);
            this.syncDialogState({ preferGreeting: true });
            this.detailTagDragIndex = null;
            this.editingData.filename = c.filename || this.editingData.filename;
            setActiveRuntimeContext({
                card: {
                    id: c.id || '',
                    name: this.editingData.char_name || c.char_name || '',
                    category: c.category || '',
                    is_bundle: Boolean(c.is_bundle),
                    bundle_dir: c.bundle_dir || '',
                    filename: c.filename || '',
                    resource_folder: this.editingData.resource_folder || c.resource_folder || '',
                },
            });

            // 显示模态框
            this.showDetail = true;

            // 加载资源
            if (c.resource_folder) this.fetchSkins(c.resource_folder);
            this.fetchCardChats(c.id);

            // 后台获取完整数据 (确保是最新的)
            this.refreshActiveCardDetail(c.id);
        },

        // 刷新当前卡片数据 (从后端)
        refreshActiveCardDetail(cardId) {
            if (!cardId) return;
            
            getCardDetail(cardId).then(res => {
                if (res.success && res.card) {
                    let safeCard = res.card;
                    
                    // 再次解包防止嵌套
                    if (safeCard.data && typeof safeCard.data === 'object') {
                        Object.assign(safeCard, safeCard.data);
                        delete safeCard.data;
                    }

                    // 更新核心字段
                    this.editingData.description = safeCard.description || "";
                    this.editingData.first_mes = safeCard.first_mes || "";
                    this.editingData.mes_example = safeCard.mes_example || "";
                    this.editingData.creator_notes = safeCard.creator_notes || "";

                    this.editingData.personality = safeCard.personality || "";
                    this.editingData.scenario = safeCard.scenario || "";
                    this.editingData.system_prompt = safeCard.system_prompt || "";
                    this.editingData.post_history_instructions = safeCard.post_history_instructions || "";
                    this.editingData.creator = safeCard.creator || "";
                    this.editingData.character_version = safeCard.char_version || safeCard.character_version || "";
                    
                    // 更新标签（从后端重新加载，确保显示最新标签）
                    this.editingData.tags = safeCard.tags || [];

                    if (safeCard.tag_taxonomy) {
                        this.$store.global.setTagTaxonomy(safeCard.tag_taxonomy);
                        this.sanitizeDetailCategoryFilterState();
                    }
                    
                    this.editingData.alternate_greetings = Array.isArray(safeCard.alternate_greetings)
                        ? safeCard.alternate_greetings
                        : [];
                    if (this.editingData.alternate_greetings.length === 0) this.editingData.alternate_greetings = [""];

                    if (safeCard.character_book) {
                        let book = safeCard.character_book;
                        if (Array.isArray(book)) book = { name: safeCard.char_name, entries: book };
                        this.editingData.character_book = book;
                        this.editingData.character_book_raw = JSON.stringify(book, null, 2);
                    }

                    if (safeCard.extensions) {
                        this.editingData.extensions = JSON.parse(JSON.stringify(safeCard.extensions));
                        this._convertLegacyTavernHelper(this.editingData.extensions);
                        if (!this.editingData.extensions.regex_scripts) this.editingData.extensions.regex_scripts = [];
                        if (!this.editingData.extensions.tavern_helper) this.editingData.extensions.tavern_helper = {};
                    }

                    if (res.card.image_url) this.activeCard.image_url = res.card.image_url;
                    this.activeCard.import_time = Number(res.card.import_time || 0);
                    this.activeCard.last_sent_to_st = Number(res.card.last_sent_to_st || 0);
                    this.fetchCardChats(safeCard.id || cardId);

                    // 更新 UI 备注字段
                    this.editingData.ui_summary = safeCard.ui_summary || "";
                    this.editingData.source_link = safeCard.source_link || "";
                    this.editingData.source_title = safeCard.source_title ?? "";
                    this.editingData.source_update = safeCard.source_update ?? null;
                    this.editingData.resource_folder = safeCard.resource_folder || "";
                    this.editingData.source_revision = safeCard.source_revision || "";
                    this.activeCard.source_update = safeCard.source_update ?? this.activeCard.source_update ?? null;
                    this.activeCard.source_title = safeCard.source_title ?? this.activeCard.source_title ?? "";
                    this.editingData = this._normalizeEditingDataShape(this.editingData);
                    this.syncDialogState();
                    setActiveRuntimeContext({
                        card: {
                            id: safeCard.id || cardId,
                            name: this.editingData.char_name || safeCard.char_name || '',
                            category: safeCard.category || this.activeCard?.category || '',
                            is_bundle: Boolean(safeCard.is_bundle || this.activeCard?.is_bundle),
                            bundle_dir: safeCard.bundle_dir || this.activeCard?.bundle_dir || '',
                            filename: safeCard.filename || this.activeCard?.filename || '',
                            resource_folder: this.editingData.resource_folder || safeCard.resource_folder || '',
                        },
                    });

                    this.ensureVisibleDetailTab();

                    if (this.lastTab === 'persona' && this.hasPersonaFields) {
                        this.tab = 'persona';
                    }

                    // 启动自动保存
                    this.$nextTick(() => {
                        // 1. 记录当前状态为"原始基准"
                        this.originalDataJson = JSON.stringify(this.editingData);
                        // 2. 启动计时器
                        this.startAutoSave();
                    });
                }
            });
        },

        // === 保存逻辑 ===

        saveChanges() {
            this.isSaving = true;
            
            // 预处理
            if (this.editingData.alternate_greetings) {
                this.editingData.alternate_greetings = this.editingData.alternate_greetings.filter(s => s && s.trim() !== "");
            }
            this.syncDialogState();
            // 同步 Raw JSON 到对象 (如果用户修改了 Textarea)
            if (this.editingData.character_book) {
                this.editingData.character_book_raw = JSON.stringify(this.editingData.character_book, null, 2);
            }

            return this._internalSaveCard(false);
        },

        _internalSaveCard(isBundleRenamed) {
            // 1. 获取清洗后的 V3 数据 (使用 Utils)
            const cleanData = getCleanedV3Data(this.editingData);
            cleanData.extensions = this._buildExtensionsForSave(cleanData.extensions || {});

            // 2. 同步回 editingData (UI 反馈)
            if (this.editingData.alternate_greetings && cleanData.alternate_greetings) {
                this.editingData.alternate_greetings = cleanData.alternate_greetings;
                if (this.editingData.alternate_greetings.length === 0) this.editingData.alternate_greetings = [""];
            }

            // 3. 构建 Payload
            // 使用editingData.id而非activeCard.id
            // Bundle模式下：editingData.id是当前编辑版本的ID，activeCard.id是Bundle主版本ID
            const payload = {
                id: this.editingData.id,
                new_filename: this.editingData.filename,

                // 核心数据 (Spread Clean Data)
                ...cleanData, // 包含 name, description, first_mes, tags 等所有 V3 字段

                // UI 专用字段
                ui_summary: this.editingData.ui_summary,
                source_link: this.editingData.source_link,
                resource_folder: this.editingData.resource_folder,
                source_revision: this.editingData.source_revision || "",

                // Bundle 标记
                save_ui_to_bundle: this.activeCard.is_bundle,
                bundle_dir: this.activeCard.is_bundle ? this.activeCard.bundle_dir : undefined,
                version_id: this.activeCard.is_bundle ? this.editingData.id : undefined
            };

            // 兼容性映射：getCleanedV3Data 返回的是 name，但 updateCard 需要 char_name
            payload.char_name = cleanData.name;

            return updateCard(payload).then(res => {
                this.isSaving = false;
                if (res.success) {
                    this.editingData.source_revision = res.updated_card?.source_revision || this.editingData.source_revision || "";
                    // 更新基准
                    this.originalDataJson = JSON.stringify(this.editingData);
                    const ts = new Date().getTime();

                    // 更新 ID/Filename
                    // Bundle模式下：new_id是主版本ID，不要覆盖当前编辑的版本ID和image_url
                    if (res.new_id && !this.activeCard.is_bundle) {
                        this.activeCard.id = res.new_id;
                        this.editingData.id = res.new_id;
                        this.activeCard.filename = res.new_filename;
                        this.editingData.filename = res.new_filename;
                        if (res.new_image_url) this.activeCard.image_url = res.new_image_url;
                    }

                    // 通知列表更新 (通过事件总线)
                    if (res.updated_card) {
                        // Bundle 模式下不覆盖主版本的备注信息，后端已返回正确的主版本备注
                        // 非 Bundle 模式才需要补充 UI 数据
                        if (!this.activeCard.is_bundle) {
                            res.updated_card.ui_summary = this.editingData.ui_summary;
                            res.updated_card.source_link = this.editingData.source_link;
                            res.updated_card.resource_folder = this.editingData.resource_folder;
                        }

                        // 强制刷新缩略图
                        if (res.file_modified) {
                            res.updated_card.thumb_url = `/api/thumbnail/${encodeURIComponent(res.updated_card.id)}?t=${ts}`;
                        }
                        
                        // 发送更新事件给 cardGrid (使用后端返回的完整 Bundle 数据)
                        window.dispatchEvent(new CustomEvent('card-updated', { 
                            detail: res.updated_card 
                        }));
                        
                        // 更新本地 activeCard
                        // Bundle 模式下：后端返回的是主版本数据，不直接合并到当前编辑版本
                        // 只更新必要的字段，保持当前版本的数据不变
                        if (!this.activeCard.is_bundle) {
                            Object.assign(this.activeCard, res.updated_card);
                        } else {
                            // Bundle 模式下只更新部分字段，避免覆盖当前版本的 UI 数据
                            // 注意：不更新image_url，保持当前版本的封面显示
                            if (res.new_id) this.activeCard.id = res.new_id;
                            if (res.new_filename) this.activeCard.filename = res.new_filename;
                        }
                    } else {
                        // 兜底刷新
                        window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    }

                    if (res.tag_merge && res.tag_merge.triggered && res.tag_merge.changed) {
                        const replacedCount = Array.isArray(res.tag_merge.replacements)
                            ? res.tag_merge.replacements.length
                            : 0;
                        if (replacedCount > 0) {
                            this.$store.global.showToast(`已按全局规则合并标签（${replacedCount} 项）`, 2600, "detail-tags");
                        }
                    }

                    this.$store.global.showToast("保存成功", 2000, "settings-save");
                    
                    // 刷新详情
                    // Bundle模式下：使用current_version_id保持当前版本，不要切换到主版本
                    // 如果没有current_version_id（保存的是主版本），则使用editingData.id
                    const idToRefresh = res.current_version_id || this.editingData.id;
                    this.refreshActiveCardDetail(idToRefresh);
                    autoSaver.initBaseline(this.editingData); // 手动保存后，重置自动保存
                    return true;
                } else {
                    alert("保存失败: " + res.msg);
                    return false;
                }
            }).catch(e => {
                this.isSaving = false;
                alert("请求错误: " + e);
                return false;
            });
        },

        // === 图片与文件更新 ===

        triggerCardUpdate() {
            this.$refs.cardUpdateInput.click();
        },

        handleCardUpdate(e) {
            const file = e.target.files[0];
            if (!file) return;
            
            this.processUpdateFile(file, e.target);
        },

        // 处理拖拽 Drop
        handleUpdateDrop(e) {
            this.dragOverUpdate = false;
            const files = e.dataTransfer.files;
            if (!files || files.length === 0) return;
            
            const file = files[0]; // 只处理第一个文件，防止用户导入多个文件
            this.processUpdateFile(file, null);
        },

        processUpdateFile(file, inputElement) {
            if (!file.name.toLowerCase().endsWith('.png') && !file.name.toLowerCase().endsWith('.json')) {
                alert("请上传 PNG 或 JSON 格式");
                if(inputElement) inputElement.value = '';
                return;
            }

            let isBundleUpdate = false;
            let finalPolicy = this.updateImagePolicy; // 获取当前选中的策略
            
            if (this.activeCard.is_bundle) {
                if (confirm(`检测到这是聚合角色包。\n\n[确定] = 添加为新版本 (推荐)\n[取消] = 覆盖当前选中的版本文件`)) {
                    isBundleUpdate = true;
                } else {
                    isBundleUpdate = false;
                }
            } else {
                if (!confirm(`确定要更新角色卡 "${this.activeCard.char_name}" 吗？\n当前策略: ${this.getPolicyName(finalPolicy)}`)) {
                    if(inputElement) inputElement.value = '';
                    return;
                }
            }

            const formData = new FormData();
            formData.append('new_card', file);
            formData.append('card_id', this.editingData.id);
            formData.append('is_bundle_update', isBundleUpdate);
            formData.append('image_policy', finalPolicy);
            formData.append('sync_source_title', this.syncSourceTitleOnUpdate ? 'true' : 'false');
            // Bundle 新增版本时，不传递 ui_summary（新版本应该无备注）
            formData.append('keep_ui_data', JSON.stringify({
                ui_summary: isBundleUpdate ? '' : this.editingData.ui_summary,
                source_link: this.editingData.source_link,
                resource_folder: this.editingData.resource_folder,
                tags: this.editingData.tags
            }));

            this.performUpdate(formData, '/api/update_card_file', inputElement);
        },

        // 辅助显示策略名称
        getPolicyName(p) {
            const map = {
                'overwrite': '直接覆盖',
                'keep_image': '保留原图',
                'archive_old': '归档旧图',
                'archive_new': '新图存为皮肤'
            };
            return map[p] || p;
        },

        // 皮肤设为封面逻辑
        setSkinAsCover(skinFilename) {
            if (!confirm("确定将此皮肤设为封面吗？" + (this.saveOldCoverOnSwap ? "\n(当前封面将保存到资源目录)" : "\n(当前封面将被覆盖)"))) return;

            this.isSaving = true;
            setSkinAsCover({
                card_id: this.activeCard.id,
                skin_filename: skinFilename,
                save_old: this.saveOldCoverOnSwap
            }).then(res => {
                this.isSaving = false;
                if (res.success) {
                this.$store.global.showToast("封面已切换", 3000, "card-check");
                    
                    // 强制刷新图片显示
                    const ts = new Date().getTime();
                    this.activeCard.image_url += (this.activeCard.image_url.includes('?') ? '&' : '?') + `t=${ts}`;
                    
                    // 刷新列表
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    
                    // 刷新皮肤列表 (如果保存了旧图，皮肤列表会增加)
                    if (this.editingData.resource_folder) {
                        this.fetchResourceFiles(this.editingData.resource_folder);
                    }
                    
                    // 退出皮肤预览模式，显示主图
                    this.currentSkinIndex = -1;
                } else {
                    alert("操作失败: " + res.msg);
                }
            }).catch(e => {
                this.isSaving = false;
                alert(e);
            });
        },

        triggerUrlUpdate() {
            const url = prompt("请输入新的角色卡图片链接 (PNG/WEBP):");
            if (!url) return;

            let isBundleUpdate = false;
            let finalPolicy = this.updateImagePolicy;
            if (this.activeCard.is_bundle) {
                if (confirm(`检测到这是聚合角色包。\n\n[确定] = 添加为新版本 (强制覆盖策略)\n[取消] = 更新当前版本 (应用选中策略)`)) {
                    isBundleUpdate = true;
                    // 如果是新增版本，逻辑上必须是覆盖写入新文件
                    finalPolicy = 'overwrite';
                }
            } else {
                const policyName = this.getPolicyName(finalPolicy);
                if (!confirm(`确定从 URL 更新当前卡片吗？\n\n当前策略: 【${policyName}】`)) {
                    return;
                }
            }

            this.isSaving = true;
            // Bundle 新增版本时，不传 ui_summary（新版本应该无备注）
            updateCardFileFromUrl({
                card_id: this.editingData.id,
                url: url,
                is_bundle_update: isBundleUpdate,
                image_policy: finalPolicy,
                sync_source_title: this.syncSourceTitleOnUpdate,
                keep_ui_data: {
                    ui_summary: isBundleUpdate ? '' : this.editingData.ui_summary,
                    source_link: this.editingData.source_link,
                    resource_folder: this.editingData.resource_folder,
                    tags: this.editingData.tags
                }
            }).then(res => this.handleUpdateResponse(res))
              .catch(err => { this.isSaving = false; alert(err); });
        },

        performUpdate(formData, url, inputElement) {
            this.isSaving = true;
            // 使用通用 fetch (或者 api/card.js 中的 updateCardFile)
            // 这里为了通用性，直接用 fetch 或调用 API 模块
            updateCardFile(formData)
                .then(res => {
                    this.handleUpdateResponse(res);
                    if(inputElement) inputElement.value = '';
                })
                .catch(err => {
                    this.isSaving = false;
                    alert("网络错误: " + err);
                    if(inputElement) inputElement.value = '';
                });
        },

        handleUpdateResponse(res) {
            this.isSaving = false;
            if (res.success) {
                this.$store.global.showToast("更新成功", 2000, "card-check");
                const updatedCard = res.updated_card;
                if (updatedCard) {
                    const responseRevision = updatedCard.source_revision || res.source_revision || "";
                    if (responseRevision) updatedCard.source_revision = responseRevision;
                    const ts = new Date().getTime();
                    if (updatedCard.image_url) updatedCard.image_url += `?t=${ts}`;
                    
                    this.activeCard = updatedCard;
                    this.editingData = this._normalizeEditingDataShape(JSON.parse(JSON.stringify(updatedCard)));
                    this.syncDialogState();
                    
                    window.dispatchEvent(new CustomEvent('card-updated', { detail: updatedCard }));
                    
                    const idToRefresh = res.new_id || updatedCard.id;
                    this.refreshActiveCardDetail(idToRefresh);

                    // 如果存在资源目录（可能是刚自动创建的），立即重新获取列表以显示归档的图片
                    if (updatedCard.resource_folder) {
                        this.fetchSkins(updatedCard.resource_folder);
                    }
                } else {
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                }
            } else {
                alert("更新失败: " + res.msg);
            }
        },

        // === 皮肤与显示 ===

        flipCard() {
            this.isCardFlipped = !this.isCardFlipped;
            if (this.isCardFlipped) {
                this.rawMetadataContent = 'Loading...';
                getCardMetadata(this.editingData.id)
                    .then(data => {
                        this.rawMetadataContent = data.error ? data.error : JSON.stringify(data, null, 4);
                    })
                    .catch(e => {
                        this.rawMetadataContent = 'Error: ' + e.message;
                    });
            }
        },

        get currentSkinItems() {
            const directory = this.normalizeResourcePath(this.currentSkinDirectory);
            const prefix = directory ? `${directory}/` : '';
            const directories = new Map();
            const images = [];

            (this.skinImages || []).forEach((skin, index) => {
                const pathValue = this.normalizeResourcePath(skin);
                if (!pathValue) return;
                if (prefix && !pathValue.startsWith(prefix)) return;

                const remainder = prefix ? pathValue.slice(prefix.length) : pathValue;
                if (!remainder) return;

                const parts = remainder.split('/').filter(Boolean);
                if (parts.length === 0) return;

                if (parts.length > 1) {
                    const directoryPath = prefix ? `${prefix}${parts[0]}` : parts[0];
                    if (!directories.has(directoryPath)) {
                        directories.set(directoryPath, {
                            type: 'directory',
                            name: parts[0],
                            path: directoryPath,
                        });
                    }
                    return;
                }

                images.push({
                    type: 'image',
                    name: parts[0],
                    path: pathValue,
                    index,
                });
            });

            const sortByName = (a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
            return [
                ...Array.from(directories.values()).sort(sortByName),
                ...images.sort(sortByName),
            ];
        },

        get skinGalleryImageItems() {
            return this.currentSkinItems.filter(item => item.type === 'image');
        },

        get selectedSkinPath() {
            if (this.currentSkinIndex === -1 || this.skinImages.length === 0) {
                return '';
            }
            return this.normalizeResourcePath(this.skinImages[this.currentSkinIndex]);
        },

        get selectedSkinName() {
            return this.getResourcePathName(this.selectedSkinPath);
        },

        get skinGalleryPreviewName() {
            return this.getResourcePathName(this.skinGalleryPreviewPath);
        },

        get skinGalleryPreviewUrl() {
            return this.getSkinUrl(this.skinGalleryPreviewPath);
        },

        get displayImageUrl() {
            if (!this.selectedSkinPath) {
                return this.activeCard.image_url;
            }
            const folder = this.activeCard.resource_folder || this.editingData.resource_folder;
            return `/resources_file/${this.encodeResourcePath(folder)}/${this.encodeResourcePath(this.selectedSkinPath)}`;
        },

        getSkinUrl(skinName) {
            const folder = this.activeCard.resource_folder || this.editingData.resource_folder;
            if (!folder || !skinName) return '';
            return `/resources_file/${this.encodeResourcePath(folder)}/${this.encodeResourcePath(this.getResourceRelativePath(skinName))}`;
        },

        fetchSkins(folderName) {
            this.fetchResourceFiles(folderName);
        },

        openSkinGallery() {
            if (!this.editingData.resource_folder && !this.activeCard.resource_folder) return;
            this.showSkinGallery = true;
            this.skinGalleryPreviewPath = '';
            this.isCardFlipped = false;
        },

        closeSkinGallery() {
            this.showSkinGallery = false;
            this.skinGalleryPreviewPath = '';
        },

        openSkinGalleryPreview(pathValue) {
            const normalizedPath = this.normalizeResourcePath(pathValue);
            if (!normalizedPath) return;
            this.selectSkinByPath(normalizedPath);
            this.skinGalleryPreviewPath = this.selectedSkinPath || normalizedPath;
        },

        closeSkinGalleryPreview() {
            this.skinGalleryPreviewPath = '';
        },

        handleSkinGalleryKeydown(event) {
            if (!this.showSkinGallery || !event) return;
            if (event.key !== 'Escape') return;

            if (typeof event.preventDefault === 'function') {
                event.preventDefault();
            }

            if (this.skinGalleryPreviewPath) {
                this.closeSkinGalleryPreview();
                return;
            }

            this.closeSkinGallery();
        },

        nextSkin() {
            const imageItems = this.currentSkinItems.filter(item => item.type === 'image');
            if (imageItems.length === 0) return;

            const currentItemIndex = imageItems.findIndex(item => item.index === this.currentSkinIndex);
            const nextItemIndex = currentItemIndex + 1;
            if (nextItemIndex >= imageItems.length) {
                this.currentSkinIndex = -1;
                return;
            }

            this.selectSkinByPath(imageItems[nextItemIndex].path);
        },

        prevSkin() {
            const imageItems = this.currentSkinItems.filter(item => item.type === 'image');
            if (imageItems.length === 0) return;

            const currentItemIndex = imageItems.findIndex(item => item.index === this.currentSkinIndex);
            const prevItemIndex = currentItemIndex === -1 ? imageItems.length - 1 : currentItemIndex - 1;
            if (prevItemIndex < 0) {
                this.currentSkinIndex = -1;
                return;
            }

            this.selectSkinByPath(imageItems[prevItemIndex].path);
        },

        // === 版本与聚合包 ===

        switchVersion(versionId) {
            const ver = this.activeCard.versions.find(v => v.id === versionId);
            if (!ver) return;

            this.activeCard.image_url = `/cards_file/${encodeURIComponent(ver.id)}`;
            this.activeCard.filename = ver.filename;

            getCardDetail(ver.id).then(res => {
                if (res.success && res.card) {
                    const c = res.card;
                    this.activeCard.import_time = c.import_time || c.last_modified || this.activeCard.import_time;
                    // 更新文件名（Bundle模式下也需要更新）
                    this.editingData.filename = c.filename;

                    this.editingData.id = c.id;
                    this.editingData.char_name = c.char_name;
                    this.editingData.description = c.description;
                    this.editingData.first_mes = c.first_mes;
                    this.editingData.mes_example = c.mes_example;
                    this.editingData.alternate_greetings = c.alternate_greetings || [""];
                    this.editingData.creator_notes = c.creator_notes;
                    this.editingData.character_book = c.character_book;
                    if (!this.editingData.character_book) {
                        this.editingData.character_book = { name: "", entries: [] };
                    }
                    this.editingData.creator = c.creator || "";
                    this.editingData.personality = c.personality || "";
                    this.editingData.scenario = c.scenario || "";
                    this.editingData.system_prompt = c.system_prompt || "";
                    this.editingData.post_history_instructions = c.post_history_instructions || "";
                    this.editingData.tags = c.tags || [];
                    this.editingData.character_version = c.char_version || "";
                    this.editingData.extensions = c.extensions || { regex_scripts: [], tavern_helper: {} };
                    this.altIdx = 0;

                    this.editingData.ui_summary = c.ui_summary || "";
                    this.editingData.source_link = c.source_link || "";
                    this.editingData.resource_folder = c.resource_folder || "";
                    this.editingData.source_revision = c.source_revision || this.editingData.source_revision || "";
                    this.editingData = this._normalizeEditingDataShape(this.editingData);
                    this.syncDialogState();
                }
            });
        },

        setAsBundleCover(versionId) {
            if(!confirm("将此版本设为最新（封面）？\n这将更新其修改时间。")) return;
            
            // 传入完整参数以匹配后端需求
            apiSetAsBundleCover({
                id: versionId,
                bundle_dir: this.activeCard.bundle_dir,
                char_name: this.activeCard.char_name
            }).then(res => {
                if(res.success) {
                    this.$store.global.showToast("已设为封面", 3000, "card-check");
                    if (res.updated_card) {
                        const newBundle = res.updated_card;
                        const ts = new Date().getTime();
                        const oldId = this.activeCard.id;
                        // 确保 URL 带时间戳
                        if (res.new_image_url) {
                            newBundle.image_url = res.new_image_url;
                        } else {
                            newBundle.image_url = `/cards_file/${encodeURIComponent(newBundle.id)}?t=${ts}`;
                        }
                        
                        this.activeCard = newBundle;
                        this.switchVersion(versionId); // 切换视图到新封面
                        
                        // 通知列表更新
                        window.dispatchEvent(new CustomEvent('card-updated', { 
                            detail: { ...newBundle, _old_id: oldId }
                        }));
                    } else {
                        // 兜底刷新
                        window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    }
                } else alert(res.msg);
            });
        },

        renameCurrentVersion() {
            const oldName = this.editingData.filename;
            const ext = oldName.split('.').pop();
            const nameNoExt = oldName.replace('.'+ext, '');
            const newNameNoExt = prompt("重命名当前版本文件 (不含后缀):", nameNoExt);
            
            if (!newNameNoExt || newNameNoExt === nameNoExt) return;
            
            this.editingData.filename = newNameNoExt + '.' + ext;
            this.saveChanges();
        },

        unbundleCard() {
            if (!this.activeCard.is_bundle) return;
            if (!confirm(`确定要取消聚合模式吗？`)) return;
            
            apiToggleBundleMode({ 
                folder_path: this.activeCard.bundle_dir, 
                action: 'disable' 
            }).then(res => {
                alert(res.msg);
                this.showDetail = false;
                window.dispatchEvent(new CustomEvent('refresh-card-list'));
            });
        },

        convertToBundle() {
            if (this.activeCard.is_bundle) return;
            const defaultName = this.activeCard.char_name.replace(/[\\/:*?"<>|]/g, '_').trim();
            const newName = prompt("请输入新的包(文件夹)名称：", defaultName);
            if (!newName) return;

            this.isSaving = true;
            apiConvertToBundle({
                card_id: this.activeCard.id,
                bundle_name: newName
            }).then(res => {
                this.isSaving = false;
                if (res.success) {
                    alert("转换成功！");
                    this.showDetail = false;
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                } else alert(res.msg);
            }).catch(e => { this.isSaving = false; alert(e); });
        },

        renameFolderFromDetail(currentPath) {
            if (!currentPath) return;
            const oldName = currentPath.split('/').pop();
            const newName = prompt("重命名角色包:", oldName);
            if (!newName || newName === oldName) return;

            renameFolder({ old_path: currentPath, new_name: newName })
                .then(res => {
                    if (res.success) {
                        const newPath = res.new_path;
                        this.activeCard.bundle_dir = newPath;
                        this.activeCard.category = newPath.split('/').slice(0, -1).join('/');
                        
                        const newId = `${newPath}/${this.activeCard.filename}`;
                        this.activeCard.id = newId;
                        this.editingData.id = newId;

                        alert("重命名成功！");
                        // 刷新文件夹树和列表
                        window.dispatchEvent(new CustomEvent('refresh-folder-list'));
                        window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    } else alert(res.msg);
                });
        },

        // === 系统与工具 ===

        openResourceFolder() {
            apiOpenResourceFolder({ card_id: this.editingData.id }).then(res => {
                if(!res.success) alert(res.msg);
            });
        },

        setResourceFolder() {
            // 调用 API 保存
            apiSetResourceFolder({ 
                card_id: this.editingData.id, 
                resource_path: this.editingData.resource_folder 
            }).then(res => {
                if (res.success) {
                    // 更新 activeCard 以同步视图
                    this.editingData.resource_folder = res.resource_folder;
                    this.activeCard.resource_folder = res.resource_folder;
                    this.fetchResourceFiles(res.resource_folder);
                    this.$store.global.showToast('资源目录已设置', 1800, 'card-folder');
                } else {
                    alert(res.msg);
                }
            });
        },

        async createResourceFolder(options = {}) {
            try {
                return await this.ensureResourceFolder(options);
            } catch (_) {
                return null;
            }
        },

        sendToST() {
            const btn = document.getElementById('btn-send-st');
            const label = btn?.querySelector('.detail-send-st-label');
            if (label) label.textContent = '发送中...';
            
            sendToSillyTavern(this.activeCard.id)
                .then(res => {
                    if (res.success) {
                        this.activeCard.last_sent_to_st = Number(res.last_sent_to_st || Date.now() / 1000);
                        this.$store.global.showToast("发送成功", 2200, "card-check");
                    }
                    else this.$store.global.showToast("发送失败: " + res.msg, 2600, "context-close");
                })
                .finally(() => {
                    if (label) label.textContent = '发送到 ST';
                });
        },

        applyCharacterBookJson() {
            try {
                const parsed = JSON.parse(this.editingData.character_book_raw);
                this.editingData.character_book = parsed;
                alert('JSON 已应用');
            } catch (e) {
                alert('JSON 格式错误');
            }
        },

        triggerImageUpload() {
            this.$refs.imageInput.click();
        },

        handleImageUpload(e) {
            const file = e.target.files[0];
            if (!file) return;
            const formData = new FormData();
            formData.append('id', this.editingData.id);
            formData.append('image', file);
            
            this.isSaving = true;
            changeCardImage(formData).then(res => {
                this.isSaving = false;
                if (res.success) {
                    const updatedCard = res.updated_card || null;
                    const refreshedRevision = res.updated_card?.source_revision || res.source_revision || "";
                    if (updatedCard) {
                        Object.assign(this.activeCard, updatedCard);
                    }
                    // 处理 ID 变更 (JSON -> PNG)
                    if (res.new_id && res.new_id !== this.editingData.id) {
                        this.activeCard.id = res.new_id;
                        this.editingData.id = res.new_id;
                        this.activeCard.filename = res.new_id.split('/').pop();
                        this.editingData.filename = this.activeCard.filename;
                    }
                    if (updatedCard?.filename) {
                        this.activeCard.filename = updatedCard.filename;
                        this.editingData.filename = updatedCard.filename;
                    }
                    if (res.new_image_url) this.activeCard.image_url = res.new_image_url;
                    if (res.import_time) {
                        this.activeCard.import_time = res.import_time;
                    }
                    this.editingData.source_revision = refreshedRevision || this.editingData.source_revision || "";
                    if (this.editingData.source_revision) {
                        this.activeCard.source_revision = this.editingData.source_revision;
                    }
                    
                    if (updatedCard) {
                        window.dispatchEvent(new CustomEvent('card-updated', { detail: updatedCard }));
                    } else {
                        window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    }
                    e.target.value = '';
                } else alert(res.msg);
            });
        },

        // === 自动保存 ===

        startAutoSave() {
            autoSaver.initBaseline(this.editingData);
            autoSaver.start(
                () => this.editingData,
                () => {
                    const content = getCleanedV3Data(this.editingData);
                    return {
                        id: this.activeCard.id,
                        type: 'card',
                        content: content,
                        file_path: ""
                    };
                }
            );
        },

        stopAutoSave() {
            autoSaver.stop();
        },

        // === 简单 UI 操作 ===

        toggleTag(t) {
            if (!this.editingData.tags) this.editingData.tags = [];
            const i = this.editingData.tags.indexOf(t);
            if (i > -1) this.editingData.tags.splice(i, 1);
            else this.editingData.tags.push(t);
        },

        removeTagAt(index) {
            if (!Array.isArray(this.editingData.tags)) return;
            if (index < 0 || index >= this.editingData.tags.length) return;
            this.editingData.tags.splice(index, 1);
        },

        onDetailTagDragStart(e, index) {
            if (!this.isEditMode) return;
            this.detailTagDragIndex = index;
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', String(index));
        },

        onDetailTagDragOver(e) {
            if (!this.isEditMode || this.detailTagDragIndex === null) return;
            e.preventDefault();
        },

        onDetailTagDrop(e, targetIndex) {
            if (!this.isEditMode) return;
            e.preventDefault();

            const srcRaw = e.dataTransfer.getData('text/plain');
            let fromIndex = this.detailTagDragIndex;
            if ((fromIndex === null || fromIndex === undefined) && srcRaw !== '') {
                fromIndex = parseInt(srcRaw, 10);
            }

            if (!Array.isArray(this.editingData.tags)) return;
            if (fromIndex === null || Number.isNaN(fromIndex)) return;
            if (fromIndex < 0 || fromIndex >= this.editingData.tags.length) return;
            if (targetIndex < 0 || targetIndex >= this.editingData.tags.length) return;
            if (fromIndex === targetIndex) return;

            const list = [...this.editingData.tags];
            const [moved] = list.splice(fromIndex, 1);
            list.splice(targetIndex, 0, moved);
            this.editingData.tags = list;
            this.detailTagDragIndex = null;
        },

        onDetailTagDragEnd() {
            this.detailTagDragIndex = null;
        },

        addTag() {
            const rawInput = this.newTagInput || "";
            
            if (!rawInput.trim()) return;
            // 确保 tags 数组初始化
            if (!this.editingData.tags) {
                this.editingData.tags = [];
            }

            const slashIsSeparator = !!(this.$store?.global?.settingsForm?.automation_slash_is_tag_separator);
            const tagsToAdd = splitTagTokens(rawInput, { slashIsSeparator });

            let changed = false;
            tagsToAdd.forEach(val => {
                // 查重并添加
                if (!this.editingData.tags.includes(val)) {
                    this.editingData.tags.push(val);
                    changed = true;
                }
            });
            
            // 清空输入框
            this.newTagInput = '';

            if (changed) {
                previewMergedTags({
                    id: this.editingData.id,
                    tags: this.editingData.tags
                }).then(res => {
                    if (!res.success || !Array.isArray(res.tags)) return;

                    const before = JSON.stringify(this.editingData.tags || []);
                    const after = JSON.stringify(res.tags || []);
                    if (before !== after) {
                        this.editingData.tags = res.tags;
                        const replacedCount = Array.isArray(res.tag_merge?.replacements)
                            ? res.tag_merge.replacements.length
                            : 0;
                        if (replacedCount > 0) {
                            this.$store.global.showToast(`标签已自动合并（${replacedCount} 项）`, 2200, "detail-tags");
                        }
                    }
                }).catch(() => {});
            }
        },

        handleWheelZoom(e) {
            const delta = e.deltaY > 0 ? -10 : 10;
            this.modifyZoom(delta);
        },

        modifyZoom(amount) {
            let newZoom = this.zoomLevel + amount;
            if (newZoom < 20) newZoom = 20;
            if (newZoom > 500) newZoom = 500;
            this.zoomLevel = newZoom;
        },
        
        // 辅助 Getter (Token 计算)
        get totalTokenCount() {
            if (!this.editingData) return 0;
            // 获取 WI 条目数组
            let wiEntries = [];
            if (this.editingData.character_book) {
                if (Array.isArray(this.editingData.character_book)) wiEntries = this.editingData.character_book;
                else if (this.editingData.character_book.entries) {
                    wiEntries = Array.isArray(this.editingData.character_book.entries) 
                        ? this.editingData.character_book.entries 
                        : Object.values(this.editingData.character_book.entries);
                }
            }
            
            // 聚合文本
            let text = (this.editingData.description || "") + 
                       (this.editingData.first_mes || "") + 
                       (this.editingData.mes_example || "") +
                       (this.editingData.char_name || "");
            
            wiEntries.forEach(e => {
                if (e && e.enabled !== false) {
                    text += (e.content || "") + (Array.isArray(e.keys) ? e.keys.join('') : (e.keys || ""));
                }
            });

            return estimateTokens(text);
        },
        getVersionName,
        openLargeEditor(field, title, isArray = false, index = 0) {
            // 派发事件给 largeEditor 组件
            window.dispatchEvent(new CustomEvent('open-large-editor', {
                detail: {
                    field: field,
                    title: title,
                    isArray: isArray,
                    index: index,
                    editingData: this.editingData
                }
            }));
        },

        openTagPicker() {
            this.showTagLibrary = !this.showTagLibrary;
            if (this.showTagLibrary) {
                this.loadTagViewPrefs();
                this.$nextTick(() => {
                    if (this.$refs.tagLibrarySearchInput) {
                        this.$refs.tagLibrarySearchInput.focus();
                    }
                });
            }
        },

        openAdvancedEditor() {
            this._cleanupPendingAdvancedEditorHandlers();

            const detachedExtensions = JSON.parse(JSON.stringify(this.editingData?.extensions || {}));
            const advancedEditorPayload = {
                ...this.editingData,
                extensions: detachedExtensions,
                editorCommitMode: 'buffered',
                showPersistButton: true,
            };
            const applyHandler = async () => {
                this._cleanupPendingAdvancedEditorHandlers();
                this.editingData.extensions = JSON.parse(JSON.stringify(advancedEditorPayload.extensions || {}));
            };
            const persistHandler = async () => {
                this._cleanupPendingAdvancedEditorHandlers();
                this.editingData.extensions = JSON.parse(JSON.stringify(advancedEditorPayload.extensions || {}));
                const saveSucceeded = await this.saveChanges();
                if (saveSucceeded) {
                    window.dispatchEvent(new CustomEvent('advanced-editor-close'));
                }
            };

            this.pendingAdvancedEditorApplyHandler = applyHandler;
            this.pendingAdvancedEditorPersistHandler = persistHandler;
            window.addEventListener('advanced-editor-apply', applyHandler);
            window.addEventListener('advanced-editor-persist', persistHandler);

            window.dispatchEvent(new CustomEvent('open-advanced-editor', {
                detail: advancedEditorPayload
            }));
        },

        openMarkdownView(content) {
            window.dispatchEvent(new CustomEvent('open-markdown-view', {
                detail: content
            }));
        },

        canCheckSourceUpdate() {
            return canPreviewForumThread(this.editingData?.source_link ?? this.activeCard?.source_link ?? '');
        },

        hasPendingSourceUpdate() {
            const sourceUpdate = this.activeCard?.source_update;
            if (!sourceUpdate || typeof sourceUpdate !== 'object') return false;
            if (Object.prototype.hasOwnProperty.call(sourceUpdate, 'pending_update')) {
                return sourceUpdate.pending_update === true;
            }
            return ['updated', 'title_changed', 'title_and_content_updated', 'first_check_updated']
                .includes(sourceUpdate.last_status);
        },

        getSourceUpdateStateClass() {
            if (this.hasPendingSourceUpdate()) return 'pending_update';
            return this.activeCard?.source_update?.last_status || 'never_checked';
        },

        getSourceUpdateLabel() {
            const status = this.activeCard?.source_update?.last_status || 'never_checked';
            if (this.hasPendingSourceUpdate()) {
                if (status === 'error') return '有尚未处理的来源更新；上次检查失败';
                if (status === 'first_message_unavailable') {
                    return '有尚未处理的来源更新；无法取得首帖编辑时间';
                }
                if (status === 'unchanged') return '有尚未处理的来源更新；来源暂无后续变化';
                return {
                    first_check_updated: '首次检查发现来源首帖晚于本地卡片，尚未处理',
                    updated: '检测到来源首帖更新，尚未处理',
                    title_changed: '检测到来源标题变化，尚未处理',
                    title_and_content_updated: '检测到来源标题和首帖变化，尚未处理',
                }[status] || '有尚未处理的来源更新';
            }
            return {
                title_synced: '来源标题已同步，尚未建立检查基线',
                baseline_established: '已建立基线，下一次才能判断',
                baseline_refreshed: '角色卡更新后，来源标题和首帖基线已刷新',
                first_check_updated: '首次检查发现来源首帖晚于本地角色卡，已标记为待处理更新',
                updated: '检测到来源首帖已更新',
                title_changed: '检测到来源标题已变化',
                title_and_content_updated: '检测到来源标题和首帖都已变化',
                unchanged: '来源未变化',
                first_message_unavailable: '无法取得首帖编辑时间',
                acknowledged: '已确认当前来源更新无需处理',
                error: '上次检查失败',
            }[status] || '尚未检查来源';
        },

        applySourceUpdateResult(result) {
            if (!result?.source_update) return;
            this.activeCard.source_update = result.source_update;
            this.activeCard.source_title = result.source_update.source_title || '';
            this.editingData.source_update = result.source_update;
            this.editingData.source_title = result.source_update.source_title || '';
            window.dispatchEvent(new CustomEvent('card-updated', { detail: this.activeCard }));
        },

        async checkSourceUpdate() {
            if (!this.canCheckSourceUpdate() || this.sourceUpdateChecking || this.sourceUpdateAcknowledging) return;
            this.sourceUpdateChecking = true;
            try {
                const result = await checkCardSourceUpdate(this.activeCard.id);
                this.applySourceUpdateResult(result);
                if (result?.success) {
                    this.$store.global.showToast(result.message || this.getSourceUpdateLabel(), 3200);
                } else {
                    this.$store.global.showToast(result?.error || result?.msg || '检查来源失败', 3200, 'context-close');
                }
            } catch (error) {
                this.$store.global.showToast(error?.message || '检查来源失败', 3200, 'context-close');
            } finally {
                this.sourceUpdateChecking = false;
            }
        },

        async acknowledgeSourceUpdate() {
            if (!this.hasPendingSourceUpdate() || this.sourceUpdateChecking || this.sourceUpdateAcknowledging) return;
            if (!confirm('确认当前已检测到的来源更新无需处理吗？\n\n不会修改角色卡文件；以后只提示该版本之后的新变化。')) {
                return;
            }

            this.sourceUpdateAcknowledging = true;
            try {
                const result = await acknowledgeCardSourceUpdate(this.activeCard.id);
                this.applySourceUpdateResult(result);
                if (result?.success) {
                    this.$store.global.showToast(result.message || '已确认无需更新', 3200);
                } else {
                    this.$store.global.showToast(result?.error || result?.msg || '确认状态失败', 3200, 'context-close');
                }
            } catch (error) {
                this.$store.global.showToast(error?.message || '确认状态失败', 3200, 'context-close');
            } finally {
                this.sourceUpdateAcknowledging = false;
            }
        },

        async handleLocalNotePaste(e) {
            const clipboardData = e.clipboardData || e.originalEvent?.clipboardData;
            const items = clipboardData?.items || [];
            let blob = null;

            for (let i = 0; i < items.length; i++) {
                if (items[i].type.indexOf('image') === 0) {
                    blob = items[i].getAsFile();
                    break;
                }
            }

            if (!blob) return;

            e.preventDefault();

            const placeholder = '\n![Uploading image...]()\n';
            this.editingData.ui_summary = insertAtCursor(e.target, placeholder);

            const formData = new FormData();
            formData.append('file', blob);

            try {
                const res = await uploadNoteImage(formData);
                if (res.success) {
                    const realMarkdown = `\n![image](${res.url})\n`;
                    this.editingData.ui_summary = this.editingData.ui_summary.replace(
                        placeholder,
                        realMarkdown
                    );
                } else {
                    alert('图片上传失败: ' + res.msg);
                    this.editingData.ui_summary = this.editingData.ui_summary.replace(
                        placeholder,
                        ''
                    );
                }
            } catch (err) {
                alert('网络错误: ' + err);
                this.editingData.ui_summary = this.editingData.ui_summary.replace(
                    placeholder,
                    ''
                );
            }
        },
        // 导入函数
        handleWiImport(e) {
            const file = e.target.files[0];
            const inputEl = e.target; // 保存引用以便清理

            this.processWiImportFile(
                file, 
                this.getWorldInfoCount(), // 获取当前条目数用于判断覆盖
                
                // 成功回调
                (importedData) => {
                    // 1. 更新主数据对象
                    this.editingData.character_book = importedData;
                    
                    // 2. 同步更新 Raw JSON 编辑器的字符串
                    this.editingData.character_book_raw = JSON.stringify(importedData, null, 2);
                    
                    // 3. UI 状态重置
                    this.currentWiIndex = 0;
                    inputEl.value = ''; // 清空 input，允许重复导入同名文件
                    
                    // 4. 反馈
                    this.$store.global.showToast(`成功导入: "${importedData.name}"`, 3000, 'card-check');

                },
                
                // 取消/失败回调
                () => {
                    inputEl.value = ''; // 无论如何都要清空 input
                }
            );
        },

        // 2. 导出函数
        exportWorldBookSingle() {
            this.downloadWorldInfoJson(this.editingData.character_book, "World Info");
        },

    }
}
