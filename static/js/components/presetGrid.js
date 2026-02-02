/**
 * static/js/components/presetGrid.js
 * 预设网格组件 - 对齐 extensionGrid.js 风格
 */
export default function presetGrid() {
    return {
        items: [],
        isLoading: false,
        dragOver: false,
        selectedPreset: null,
        showDetailModal: false,

        // 新三栏阅览界面状态
        activePresetDetail: null,
        showPresetDetailModal: false,
        activePresetItem: null,
        activePresetItemType: null,
        uiPresetFilter: null,
        showMobileSidebar: false,

        get filterType() { return this.$store.global.presetFilterType || 'all'; },

        init() {
            // 监听模式切换
            this.$watch('$store.global.currentMode', (val) => {
                if (val === 'presets') {
                    this.fetchItems();
                }
            });

            // 监听侧边栏筛选变化
            this.$watch('$store.global.presetFilterType', () => {
                if (this.$store.global.currentMode === 'presets') {
                    this.fetchItems();
                }
            });

            // 监听搜索关键词变化
            this.$watch('$store.global.presetSearch', () => {
                if (this.$store.global.currentMode === 'presets') {
                    this.fetchItems();
                }
            });

            // 初始加载
            if (this.$store.global.currentMode === 'presets') {
                this.fetchItems();
            }

            // 监听从资源目录打开预设的事件
            window.addEventListener('open-preset-reader', (e) => {
                this.openPresetDetail(e.detail);
            });
        },

        fetchItems() {
            this.isLoading = true;
            const filterType = this.$store.global.presetFilterType || 'all';
            const search = this.$store.global.presetSearch || '';

            let url = `/api/presets/list?filter_type=${filterType}`;
            if (search) {
                url += `&search=${encodeURIComponent(search)}`;
            }

            fetch(url)
                .then(res => res.json())
                .then(res => {
                    this.items = res.items || [];
                    this.isLoading = false;
                })
                .catch((err) => {
                    console.error('Failed to fetch presets:', err);
                    this.isLoading = false;
                });
        },

        async handleDrop(e) {
            this.dragOver = false;
            const files = e.dataTransfer.files;
            if (!files.length) return;

            const formData = new FormData();
            for (let i = 0; i < files.length; i++) {
                formData.append('files', files[i]);
            }

            this.isLoading = true;
            try {
                const resp = await fetch('/api/presets/upload', {
                    method: 'POST',
                    body: formData
                });
                const res = await resp.json();
                if (res.success) {
                    this.$store.global.showToast(res.msg);
                    this.fetchItems();
                } else {
                    this.$store.global.showToast(res.msg, 'error');
                }
            } catch (e) {
                this.$store.global.showToast('上传失败', 'error');
            } finally {
                this.isLoading = false;
            }
        },

        async openPreset(item) {
            // 获取详情并打开编辑器
            this.isLoading = true;
            try {
                const resp = await fetch(`/api/presets/detail/${encodeURIComponent(item.id)}`);
                const res = await resp.json();

                if (res.success) {
                    this.selectedPreset = res.preset;
                    this.showDetailModal = true;
                } else {
                    this.$store.global.showToast(res.msg || '获取详情失败', 'error');
                }
            } catch (e) {
                this.$store.global.showToast('获取详情失败', 'error');
            } finally {
                this.isLoading = false;
            }
        },

        closeDetailModal() {
            this.showDetailModal = false;
            this.selectedPreset = null;
        },

        // 新三栏阅览界面方法
        async openPresetDetail(item) {
            // 触发全局预设阅读器事件
            window.dispatchEvent(new CustomEvent('open-preset-reader', {
                detail: item
            }));
        },

        closePresetDetailModal() {
            this.showPresetDetailModal = false;
            this.activePresetDetail = null;
            this.activePresetItem = null;
            this.activePresetItemType = null;
            this.uiPresetFilter = null;
        },

        selectPresetItem(item, type, shouldScroll = false) {
            this.activePresetItem = item;
            this.activePresetItemType = type;

            if (shouldScroll && item) {
                this.$nextTick(() => {
                    const domId = type === 'prompt' ? `preset-prompt-${item.key}` : `preset-regex-${item.key || 'unknown'}`;
                    if (item.key) {
                        const el = document.getElementById(`preset-prompt-${item.key}`);
                        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }
                });
            }
        },

        get filteredPresetItems() {
            if (!this.activePresetDetail) return [];
            const prompts = this.activePresetDetail.prompts || [];
            
            if (this.uiPresetFilter === 'enabled') return prompts.filter(p => p.enabled);
            if (this.uiPresetFilter === 'disabled') return prompts.filter(p => !p.enabled);
            
            return prompts;
        },

        get totalPresetItems() {
            if (!this.activePresetDetail) return [];
            // 只返回prompts，不再混合regexes
            return this.activePresetDetail.prompts || [];
        },

        // 打开高级扩展编辑器（正则脚本 + ST脚本）
        openAdvancedExtensions() {
            if (!this.activePresetDetail) return;
            
            // 准备extensions数据结构
            const extensions = this.activePresetDetail.extensions || {};
            const regex_scripts = extensions.regex_scripts || [];
            const tavern_helper = extensions.tavern_helper || { scripts: [] };
            
            // 构造editingData，与角色卡详情页保持一致
            const editingData = {
                extensions: {
                    regex_scripts: regex_scripts,
                    tavern_helper: tavern_helper
                }
            };
            
            // 触发高级编辑器事件
            window.dispatchEvent(new CustomEvent('open-advanced-editor', {
                detail: editingData
            }));
            
            // 监听保存事件，将修改后的extensions保存回预设
            const saveHandler = (e) => {
                if (e.detail && e.detail.extensions) {
                    this.savePresetExtensions(e.detail.extensions);
                }
                window.removeEventListener('advanced-editor-save', saveHandler);
            };
            window.addEventListener('advanced-editor-save', saveHandler);
        },

        // 保存extensions到预设文件
        async savePresetExtensions(extensions) {
            if (!this.activePresetDetail) return;
            
            try {
                const resp = await fetch('/api/presets/save-extensions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        id: this.activePresetDetail.id,
                        extensions: extensions
                    })
                });
                
                const res = await resp.json();
                if (res.success) {
                    this.$store.global.showToast('扩展已保存');
                    // 刷新详情
                    this.openPresetDetail({ id: this.activePresetDetail.id });
                } else {
                    this.$store.global.showToast(res.msg || '保存失败', 'error');
                }
            } catch (e) {
                console.error('Failed to save preset extensions:', e);
                this.$store.global.showToast('保存失败', 'error');
            }
        },

        createSnapshot(type) {
            // 触发快照功能
            window.dispatchEvent(new CustomEvent('create-snapshot', {
                detail: { type, path: this.activePresetDetail?.path }
            }));
        },

        openRollback() {
            // 触发回滚界面
            window.dispatchEvent(new CustomEvent('open-rollback', {
                detail: { path: this.activePresetDetail?.path }
            }));
        },

        openBackupFolder(type) {
            // 打开备份文件夹
            window.dispatchEvent(new CustomEvent('open-backup-folder', {
                detail: { type }
            }));
        },

        deleteCurrentPreset() {
            if (!this.activePresetDetail) return;
            if (!confirm(`确定要删除预设 "${this.activePresetDetail.name}" 吗？`)) {
                return;
            }

            fetch('/api/presets/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: this.activePresetDetail.id })
            })
                .then(res => res.json())
                .then(res => {
                    if (res.success) {
                        this.$store.global.showToast(res.msg);
                        this.closePresetDetailModal();
                        this.fetchItems();
                    } else {
                        this.$store.global.showToast(res.msg, 'error');
                    }
                })
                .catch(() => {
                    this.$store.global.showToast('删除失败', 'error');
                });
        },

        editPresetRawFromDetail() {
            if (!this.activePresetDetail) return;

            window.dispatchEvent(new CustomEvent('open-script-file-editor', {
                detail: {
                    fileData: this.activePresetDetail.raw_data,
                    filePath: this.activePresetDetail.path,
                    type: 'preset'
                }
            }));

            this.closePresetDetailModal();
        },

        async deletePreset(item, e) {
            e.stopPropagation();

            if (!confirm(`确定要删除预设 "${item.name}" 吗？`)) {
                return;
            }

            try {
                const resp = await fetch('/api/presets/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: item.id })
                });
                const res = await resp.json();

                if (res.success) {
                    this.$store.global.showToast(res.msg);
                    this.fetchItems();
                } else {
                    this.$store.global.showToast(res.msg, 'error');
                }
            } catch (e) {
                this.$store.global.showToast('删除失败', 'error');
            }
        },

        editPresetRaw() {
            if (!this.selectedPreset) return;

            // 触发高级编辑器
            window.dispatchEvent(new CustomEvent('open-script-file-editor', {
                detail: {
                    fileData: this.selectedPreset.raw_data,
                    filePath: this.selectedPreset.path,
                    type: 'preset'
                }
            }));

            this.closeDetailModal();
        },

        formatDate(ts) {
            if (!ts) return '-';
            return new Date(ts * 1000).toLocaleString();
        },

        formatSize(bytes) {
            if (!bytes) return '-';
            if (bytes < 1024) return bytes + ' B';
            if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
            return (bytes / 1024 / 1024).toFixed(1) + ' MB';
        },

        formatParam(val) {
            if (val === null || val === undefined) return '-';
            if (typeof val === 'number') {
                return Number.isInteger(val) ? val : val.toFixed(2);
            }
            return val;
        },

        formatPromptContent(val) {
            if (val === null || val === undefined) return '';
            if (typeof val === 'string') return val;
            try {
                return JSON.stringify(val, null, 2);
            } catch (e) {
                return String(val);
            }
        },

        pickPromptContent(prompt) {
            const candidates = [
                'content', 'prompt', 'text', 'value', 'system_prompt', 'system',
                'message', 'injection', 'body', 'template'
            ];
            for (const key of candidates) {
                if (prompt && Object.prototype.hasOwnProperty.call(prompt, key)) {
                    const val = prompt[key];
                    if (val !== null && val !== undefined && val !== '') {
                        return val;
                    }
                }
            }
            return '';
        },

        collectPromptMeta(prompt) {
            const meta = [];
            const pushMeta = (label, value) => {
                if (value === null || value === undefined || value === '') return;
                meta.push(`${label}: ${value}`);
            };

            if (!prompt || typeof prompt !== 'object') return meta;

            pushMeta('role', prompt.role);
            pushMeta('type', prompt.type || prompt.kind || prompt.mode);
            pushMeta('position', prompt.position || prompt.insertion_position || prompt.insert_position);
            pushMeta('depth', prompt.depth);
            pushMeta('priority', prompt.priority);
            pushMeta('order', prompt.order);

            return meta;
        },

        normalizePrompts(list) {
            if (!Array.isArray(list)) return [];

            return list.map((prompt, idx) => {
                const defaultName = `Prompt ${idx + 1}`;

                if (prompt === null || prompt === undefined) {
                    return {
                        key: `prompt-${idx}`,
                        name: defaultName,
                        content: '',
                        enabled: true,
                        meta: [],
                        isReference: true
                    };
                }

                if (typeof prompt === 'string' || typeof prompt === 'number') {
                    return {
                        key: `prompt-${idx}-${prompt}`,
                        name: String(prompt),
                        content: '',
                        enabled: true,
                        meta: [],
                        isReference: true
                    };
                }

                if (typeof prompt !== 'object') {
                    return {
                        key: `prompt-${idx}`,
                        name: String(prompt),
                        content: '',
                        enabled: true,
                        meta: [],
                        isReference: true
                    };
                }

                const name = prompt.name || prompt.title || prompt.id || prompt.identifier || prompt.key || prompt.role || defaultName;
                const contentRaw = this.pickPromptContent(prompt);
                const content = this.formatPromptContent(contentRaw);
                const toBool = (val) => {
                    if (typeof val === 'boolean') return val;
                    if (typeof val === 'number') return val !== 0;
                    if (typeof val === 'string') {
                        const lowered = val.toLowerCase();
                        if (['false', '0', 'no', 'off', 'disabled'].includes(lowered)) return false;
                        if (['true', '1', 'yes', 'on', 'enabled'].includes(lowered)) return true;
                        return Boolean(val);
                    }
                    return Boolean(val);
                };

                const enabledRaw = prompt.enabled ?? prompt.isEnabled ?? prompt.active ?? prompt.isActive;
                const disabledRaw = prompt.disabled ?? prompt.isDisabled;

                let enabled = true;
                if (disabledRaw !== undefined && disabledRaw !== null) {
                    enabled = !toBool(disabledRaw);
                } else if (enabledRaw !== undefined && enabledRaw !== null && !(typeof enabledRaw === 'string' && enabledRaw.trim() === '')) {
                    enabled = toBool(enabledRaw);
                }

                return {
                    key: prompt.id || prompt.identifier || prompt.name || `prompt-${idx}`,
                    name,
                    content,
                    enabled,
                    meta: this.collectPromptMeta(prompt),
                    isReference: !content
                };
            });
        }
    }
}
