/**
 * static/js/components/wiGrid.js
 * 世界书网格组件
 */

import { listWorldInfo, uploadWorldInfo, createWorldInfo } from '../api/wi.js';

export default function wiGrid() {
    return {
        // === Store 代理 ===
        get wiList() { return this.$store.global.wiList; },
        set wiList(val) { this.$store.global.wiList = val; },
        get wiCurrentPage() { return this.$store.global.wiCurrentPage; },
        set wiCurrentPage(val) { this.$store.global.wiCurrentPage = val; },
        get wiTotalItems() { return this.$store.global.wiTotalItems; },
        set wiTotalItems(val) { this.$store.global.wiTotalItems = val; },
        get wiTotalPages() { return this.$store.global.wiTotalPages; },
        set wiTotalPages(val) { this.$store.global.wiTotalPages = val; },
        get wiSearchQuery() { return this.$store.global.wiSearchQuery; },
        set wiSearchQuery(val) { this.$store.global.wiSearchQuery = val; },
        get wiFilterType() { return this.$store.global.wiFilterType; },
        set wiFilterType(val) { this.$store.global.wiFilterType = val; },

        // 拖拽状态
        dragOverWi: false,

        init() {
            // === 监听 Store 变化自动刷新 ===
            this.$watch('$store.global.wiSearchQuery', () => {
                this.wiCurrentPage = 1;
                this.fetchWorldInfoList();
            });

            this.$watch('$store.global.wiFilterType', () => {
                this.wiCurrentPage = 1;
                this.fetchWorldInfoList();
            });

            // 监听刷新事件
            window.addEventListener('refresh-wi-list', (e) => {
                if (e.detail && e.detail.resetPage) this.wiCurrentPage = 1;
                this.fetchWorldInfoList();
            });

            // 监听搜索框输入
            window.addEventListener('wi-search-changed', (e) => {
                this.wiSearchQuery = e.detail;
                this.wiCurrentPage = 1;
                this.fetchWorldInfoList();
            });

            // 提供给外部（例如侧边栏导入按钮）复用的全局上传入口
            window.stUploadWorldInfoFiles = (files) => {
                // 使用当前 wiGrid 实例来处理上传，保证行为与拖拽一致
                this._uploadWorldInfoInternal(files);
            };

            // 新建世界书（由 Header / Sidebar 触发）
            window.addEventListener('create-worldinfo', () => {
                this.createNewWorldInfo();
            });
        },

        // === 数据加载 ===
        fetchWorldInfoList() {
            if (Alpine.store('global').serverStatus.status !== 'ready') return;

            Alpine.store('global').isLoading = true;

            const pageSize = Alpine.store('global').settingsForm.items_per_page_wi || 20;

            const params = {
                search: this.wiSearchQuery,
                type: this.wiFilterType,
                page: this.wiCurrentPage,
                page_size: pageSize
            };

            listWorldInfo(params)
                .then(res => {
                    Alpine.store('global').isLoading = false;
                    if (res.success) {
                        // 更新 Store 中的列表
                        this.wiList = res.items;

                        this.wiTotalItems = res.total || 0;
                        this.wiTotalPages = Math.ceil(this.wiTotalItems / pageSize) || 1;
                    }
                })
                .catch(() => Alpine.store('global').isLoading = false);
        },

        changeWiPage(p) {
            if (p >= 1 && p <= this.wiTotalPages) {
                this.wiCurrentPage = p;
                const el = document.getElementById('wi-scroll-area');
                if (el) el.scrollTop = 0;
                this.fetchWorldInfoList();
            }
        },

        // === 交互逻辑 ===

        // 打开详情 (Popup 弹窗)
        openWiDetail(item) {
            // 派发事件，由 detail_wi_popup 组件监听并显示
            window.dispatchEvent(new CustomEvent('open-wi-detail-modal', { detail: item }));
        },

        // 打开编辑器 (全屏)
        openWorldInfoEditor(item) {
            window.dispatchEvent(new CustomEvent('open-wi-editor', { detail: item }));
        },

        // 新建全局世界书（使用 ST 兼容格式）
        async createNewWorldInfo() {
            const name = prompt('请输入新世界书名称:', 'New World Info');
            if (name === null) return;

            const finalName = String(name || '').trim();
            if (!finalName) {
                alert('世界书名称不能为空');
                return;
            }

            this.$store.global.isLoading = true;
            try {
                const res = await createWorldInfo({ name: finalName });
                this.$store.global.isLoading = false;
                if (!res || !res.success) {
                    alert(`创建失败: ${(res && res.msg) ? res.msg : '未知错误'}`);
                    return;
                }

                if (this.$store?.global?.showToast) {
                    this.$store.global.showToast('✅ 已创建世界书（ST 兼容格式）', 1800);
                }

                // 刷新列表并定位到新建条目
                window.dispatchEvent(new CustomEvent('refresh-wi-list', { detail: { resetPage: true } }));
                if (res.item) {
                    // 稍作延迟，避免和列表刷新动画冲突
                    setTimeout(() => {
                        this.openWorldInfoEditor(res.item);
                    }, 60);
                }
            } catch (err) {
                this.$store.global.isLoading = false;
                alert(`创建失败: ${err}`);
            }
        },

        // 从详情页进入编辑器
        // 注意：此函数通常在详情页模态框内调用，传递 item 参数
        enterWiEditorFromDetail(item) {
            // 1. 关闭详情弹窗
            window.dispatchEvent(new CustomEvent('close-wi-detail-modal'));

            // 2. 打开全屏编辑器
            // 使用 setTimeout 确保弹窗关闭动画不冲突（可选）
            setTimeout(() => {
                this.openWorldInfoEditor(item);
            }, 50);
        },

        // 跳转到关联角色卡
        jumpToCardFromWi(cardId) {
            window.dispatchEvent(new CustomEvent('jump-to-card-wi', { detail: cardId }));
        },

        // === 文件上传 ===

        // 核心世界书上传逻辑封装，供拖拽和按钮导入复用
        _uploadWorldInfoInternal(files) {
            if (!files || files.length === 0) return;

            const formData = new FormData();
            let hasJson = false;

            for (let i = 0; i < files.length; i++) {
                if (files[i].name.toLowerCase().endsWith('.json')) {
                    formData.append('files', files[i]);
                    hasJson = true;
                }
            }

            if (!hasJson) {
                alert("请选择 .json 格式的世界书文件");
                return;
            }

            this.$store.global.isLoading = true;
            uploadWorldInfo(formData)
                .then(res => {
                    this.$store.global.isLoading = false;
                    if (res.success) {
                        alert(res.msg);
                        // 如果当前不在 global 视图，提示切换
                        const currentType = this.$store.global.wiFilterType;
                        if (currentType !== 'all' && currentType !== 'global') {
                            if (confirm("上传成功（已存入全局目录）。是否切换到全局视图查看？")) {
                                this.$store.global.wiFilterType = 'global';
                                window.dispatchEvent(new CustomEvent('refresh-wi-list', { detail: { resetPage: true } }));
                            } else {
                                this.fetchWorldInfoList();
                            }
                        } else {
                            this.fetchWorldInfoList();
                        }
                    } else {
                        alert("上传失败: " + res.msg);
                    }
                })
                .catch(err => {
                    this.$store.global.isLoading = false;
                    alert("网络错误: " + err);
                });
        },

        handleWiFilesDrop(e) {
            this.dragOverWi = false;
            const files = e.dataTransfer.files;
            this._uploadWorldInfoInternal(files);
        }
    }
}
