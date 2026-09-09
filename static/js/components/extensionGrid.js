/**
 * static/js/components/extensionGrid.js
 * 高级扩展文件工作台：文件列表、筛选、上传与编辑入口。
 */
export default function extensionGrid() {
    return {
        items: [],
        isLoading: false,
        errorMessage: '',
        currentMode: 'regex',
        dragOver: false,
        _itemsRequestId: 0,

        get filterType() {
            return this.$store.global.extensionFilterType;
        },

        get modeLabel() {
            return {
                regex: '正则脚本',
                scripts: 'ST 脚本',
                quick_replies: '快速回复',
            }[this.currentMode] || '高级扩展';
        },

        get modeDescription() {
            return {
                regex: '将文本匹配、清洗和替换拆成可排序的规则集。',
                scripts: '管理 Tavern Helper 脚本、快捷按钮与隔离运行时。',
                quick_replies: '维护可复用的回复动作与自动触发条件。',
            }[this.currentMode] || '浏览和编辑高级扩展文件。';
        },

        get modePath() {
            return {
                regex: 'extensions/regex',
                scripts: 'extensions/tavern_helper',
                quick_replies: 'extensions/quick-replies',
            }[this.currentMode] || 'extensions';
        },

        init() {
            this.$watch('$store.global.currentMode', (val) => {
                if (['regex', 'scripts', 'quick_replies'].includes(val)) {
                    this.currentMode = val;
                    this.fetchItems();
                }
            });

            this.$watch('$store.global.extensionFilterType', () => {
                this.fetchItems();
            });

            this.$watch('$store.global.extensionSearch', () => {
                if (['regex', 'scripts', 'quick_replies'].includes(this.$store.global.currentMode)) {
                    this.fetchItems();
                }
            });

            if (['regex', 'scripts', 'quick_replies'].includes(this.$store.global.currentMode)) {
                this.currentMode = this.$store.global.currentMode;
                this.fetchItems();
            }

            window.stUploadRegexFiles = (files) => {
                this._uploadExtensionsFiles(files, 'regex');
            };
            window.stUploadScriptFiles = (files) => {
                this._uploadExtensionsFiles(files, 'scripts');
            };
            window.stUploadQuickReplyFiles = (files) => {
                this._uploadExtensionsFiles(files, 'quick_replies');
            };
            window.stUploadExtensionFiles = (files, targetType) => {
                this._uploadExtensionsFiles(files, targetType || this.currentMode);
            };
        },

        async uploadInputFiles(event) {
            const files = event?.target?.files;
            await this._uploadExtensionsFiles(files, this.currentMode);
            if (event?.target) event.target.value = '';
        },

        async _uploadExtensionsFiles(files, targetType) {
            const list = files || [];
            if (!list.length) return;

            if (targetType && this.currentMode !== targetType) {
                this.currentMode = targetType;
            }

            const formData = new FormData();
            for (let i = 0; i < list.length; i += 1) {
                formData.append('files', list[i]);
            }
            formData.append('target_type', targetType);

            this.errorMessage = '';
            this.isLoading = true;
            try {
                const resp = await fetch('/api/extensions/upload', {
                    method: 'POST',
                    body: formData,
                });
                const res = await resp.json();
                if (!resp.ok || !res.success) {
                    throw new Error(res.msg || '上传失败');
                }
                this.$store.global.showToast(res.msg || '上传成功', 3200, 'check');
                await this.fetchItems();
            } catch (error) {
                console.error(error);
                this.errorMessage = error?.message || '上传失败，请重试。';
                this.$store.global.showToast(this.errorMessage, 3600, 'close');
            } finally {
                this.isLoading = false;
            }
        },

        async fetchItems() {
            const requestId = ++this._itemsRequestId;
            this.isLoading = true;
            this.errorMessage = '';

            const filterType = this.$store.global.extensionFilterType || 'all';
            const search = this.$store.global.extensionSearch || '';
            let url = `/api/extensions/list?mode=${this.currentMode}&filter_type=${filterType}`;
            if (search) url += `&search=${encodeURIComponent(search)}`;

            try {
                const response = await fetch(url);
                const result = await response.json();
                if (!response.ok || result.success === false) {
                    throw new Error(result.msg || '扩展列表加载失败');
                }
                if (requestId !== this._itemsRequestId) return;
                this.items = Array.isArray(result.items) ? result.items : [];
            } catch (error) {
                if (requestId !== this._itemsRequestId) return;
                console.error(error);
                this.items = [];
                this.errorMessage = '扩展文件加载失败，请重试。';
                this.$store.global.showToast(this.errorMessage, 3600, 'close');
            } finally {
                if (requestId === this._itemsRequestId) this.isLoading = false;
            }
        },

        async handleDrop(event) {
            this.dragOver = false;
            const files = event?.dataTransfer?.files;
            if (!files?.length) return;
            await this._uploadExtensionsFiles(files, this.currentMode);
        },

        handleItemKeydown(event, item) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            event.preventDefault();
            this.openItem(item);
        },

        async openItem(item) {
            let type = 'regex';
            if (this.currentMode === 'scripts') type = 'script';
            if (this.currentMode === 'quick_replies') type = 'quick_reply';

            this.errorMessage = '';
            this.isLoading = true;
            try {
                const response = await fetch('/api/read_file_content', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ path: item.path }),
                });
                const result = await response.json();
                if (!response.ok || !result.success) {
                    throw new Error(result.msg || '读取失败');
                }
                window.dispatchEvent(new CustomEvent('open-script-file-editor', {
                    detail: {
                        fileData: result.data,
                        filePath: item.path,
                        type,
                    },
                }));
            } catch (error) {
                console.error(error);
                this.errorMessage = `读取失败：${error?.message || '无法打开文件'}`;
                this.$store.global.showToast(this.errorMessage, 3600, 'close');
            } finally {
                this.isLoading = false;
            }
        },

        formatDate(timestamp) {
            const date = new Date(Number(timestamp || 0) * 1000);
            return Number.isNaN(date.getTime()) ? '未知时间' : date.toLocaleString();
        },
    };
}
