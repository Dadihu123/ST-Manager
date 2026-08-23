/**
 * static/js/components/extensionGrid.js
 */
export default function extensionGrid() {
    return {
        items: [],
        isLoading: false,
        currentMode: 'regex', // 'regex' or 'scripts'
        dragOver: false,

        get filterType() { return this.$store.global.extensionFilterType; },

        init() {
            // 监听模式切换
            this.$watch('$store.global.currentMode', (val) => {
                if (['regex', 'scripts', 'quick_replies'].includes(val)) {
                    this.currentMode = val;
                    this.fetchItems();
                }
            });

            // 监听侧边栏筛选变化
            this.$watch('$store.global.extensionFilterType', () => {
                this.fetchItems();
            });

            // 监听搜索关键词变化
            this.$watch('$store.global.extensionSearch', () => {
                if (['regex', 'scripts', 'quick_replies'].includes(this.$store.global.currentMode)) {
                    this.fetchItems();
                }
            });
            
            // 初始加载
            if (['regex', 'scripts', 'quick_replies'].includes(this.$store.global.currentMode)) {
                this.currentMode = this.$store.global.currentMode;
                this.fetchItems();
            }

            // 提供给移动端/外部（如 Sidebar 导入按钮）复用的全局上传入口
            window.stUploadRegexFiles = (files) => { this._uploadExtensionsFiles(files, 'regex'); };
            window.stUploadScriptFiles = (files) => { this._uploadExtensionsFiles(files, 'scripts'); };
            window.stUploadQuickReplyFiles = (files) => { this._uploadExtensionsFiles(files, 'quick_replies'); };
            window.stUploadExtensionFiles = (files, targetType) => {
                this._uploadExtensionsFiles(files, targetType || this.currentMode);
            };
        },

        async _uploadExtensionsFiles(files, targetType) {
            const list = files || [];
            if (!list || list.length === 0) return;

            if (targetType && this.currentMode !== targetType) {
                // 确保上传后刷新列表使用正确的 mode
                this.currentMode = targetType;
            }

            const formData = new FormData();
            for (let i = 0; i < list.length; i++) {
                formData.append('files', list[i]);
            }
            formData.append('target_type', targetType);

            this.isLoading = true;
            try {
                const resp = await fetch('/api/extensions/upload', {
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

        fetchItems() {
            this.isLoading = true;
            const filterType = this.$store.global.extensionFilterType || 'all';
            const search = this.$store.global.extensionSearch || '';
            let url = `/api/extensions/list?mode=${this.currentMode}&filter_type=${filterType}`;
            if (search) {
                url += `&search=${encodeURIComponent(search)}`;
            }
            fetch(url)
                .then(res => res.json())
                .then(res => {
                    this.items = res.items || [];
                    this.isLoading = false;
                })
                .catch(() => { this.isLoading = false; });
        },

        async handleDrop(e) {
            this.dragOver = false;
            const files = e.dataTransfer.files;
            if (!files.length) return;
            this._uploadExtensionsFiles(files, this.currentMode);
        },

        openItem(item) {
            // 调用 System API 读取文件
            // 然后触发 open-script-file-editor 事件 (复用 advancedEditor)
            let type = 'regex';
            if (this.currentMode === 'scripts') type = 'script';
            if (this.currentMode === 'quick_replies') type = 'quick_reply';
            
            this.isLoading = true;
            fetch('/api/read_file_content', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ path: item.path }) // item.path 是相对路径
            })
            .then(res => res.json())
            .then(res => {
                this.isLoading = false;
                if (res.success) {
                    window.dispatchEvent(new CustomEvent('open-script-file-editor', {
                        detail: {
                            fileData: res.data,
                            filePath: item.path,
                            type: type
                        }
                    }));
                } else {
                    alert("读取失败: " + res.msg);
                }
            });
        },
        
        formatDate(ts) {
            return new Date(ts * 1000).toLocaleString();
        }
    }
}
