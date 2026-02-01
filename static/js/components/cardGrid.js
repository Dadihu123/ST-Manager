/**
 * static/js/components/cardGrid.js
 * 角色卡网格组件：核心列表视图
 */

import {
    listCards,
    deleteCards,
    checkResourceFolders,
    findCardPage,
    moveCard,
    toggleFavorite
} from '../api/card.js';

import { batchUpdateTags } from '../api/system.js';

export default function cardGrid() {
    return {
        // === 本地状态 ===
        cards: [],
        currentPage: 1,
        totalItems: 0,
        totalPages: 1,
        highlightId: null,

        // 批量标签输入的临时状态
        batchTagInputAdd: "",
        batchTagInputRemove: "",

        // 内部控制
        _fetchCardsAbort: null,
        _fetchCardsTimer: null,
        _suppressAutoFetch: false, // 用于 locateCard 期间暂停自动刷新

        dragOverMain: false,
        dragCounter: 0,

        get selectedIds() { return this.$store.global.viewState.selectedIds; },
        set selectedIds(val) { this.$store.global.viewState.selectedIds = val; return true; },

        get lastSelectedId() { return this.$store.global.viewState.lastSelectedId; },
        set lastSelectedId(val) { this.$store.global.viewState.lastSelectedId = val; return true; },

        get draggedCards() { return this.$store.global.viewState.draggedCards; },
        set draggedCards(val) { this.$store.global.viewState.draggedCards = val; return true; },

        // === 初始化 ===
        init() {
            // 1. 监听全局搜索/筛选变化 (Reactivity Fix)
            // 使用 debounce 防止输入时频繁请求
            this.$watch('$store.global.viewState.searchQuery', () => {
                this.currentPage = 1;
                this.scheduleFetchCards('search');
            });
            this.$watch('$store.global.viewState.searchType', () => { this.currentPage = 1; this.scheduleFetchCards('type'); });
            this.$watch('$store.global.viewState.filterCategory', () => { this.currentPage = 1; this.fetchCards(); });
            this.$watch('$store.global.viewState.filterTags', () => { this.currentPage = 1; this.fetchCards(); });
            this.$watch('$store.global.viewState.excludedTags', () => { this.currentPage = 1; this.fetchCards(); });
            // 监听排除列表变化，触发刷新
            this.$watch('$store.global.viewState.excludedCategories', () => { this.fetchCards(); });
            this.$watch('$store.global.viewState.recursiveFilter', () => { this.fetchCards(); });

            // 监听排序设置变化
            this.$watch('$store.global.settingsForm.default_sort', () => { this.currentPage = 1; this.fetchCards(); });
            this.$watch('$store.global.itemsPerPage', () => { this.currentPage = 1; this.fetchCards(); });

            // 监听收藏过滤变化
            this.$watch('$store.global.viewState.favFilter', () => { this.currentPage = 1; this.fetchCards(); });
            // 监听设置中的收藏前置变化
            this.$watch('$store.global.settingsForm.favorites_first', () => { this.fetchCards(); });

            // 2. 监听刷新事件 (来自 Header, Sidebar, Layout)
            window.addEventListener('refresh-card-list', () => {
                if (!this._suppressAutoFetch) this.fetchCards();
            });

            // 3. 监听重置滚动 (切换分类时)
            window.addEventListener('reset-scroll', () => {
                const el = document.getElementById('main-scroll');
                if (el) el.scrollTop = 0;
                this.currentPage = 1;
            });

            // 4. 监听搜索/高亮 (来自 Header)
            window.addEventListener('highlight-card', (e) => {
                this.highlightId = e.detail;
                setTimeout(() => { this.highlightId = null; }, 2000);
            });

            // 5. 监听文件拖拽放下 (来自 Layout)
            window.addEventListener('handle-files-drop', (e) => {
                const { event, category } = e.detail;
                this.handleFilesDrop(event, category);
            });

            // 6. 监听设置加载完成，初始加载数据
            window.addEventListener('settings-loaded', () => {
                this.fetchCards();
            });

            // 7. 监听设置保存 (可能改变每页数量)
            window.addEventListener('settings-saved', () => {
                this.fetchCards();
            });

            // 8. 监听全选请求事件（返回当前页的卡片ID）
            window.addEventListener('get-all-card-ids', () => {
                // 返回当前页（paginatedCards）的卡片ID
                const cardIds = this.paginatedCards.map(c => c.id);
                window.dispatchEvent(new CustomEvent('all-card-ids-response', {
                    detail: { ids: cardIds }
                }));
            });

            // 9. 监听单卡更新事件
            window.addEventListener('card-updated', (e) => {
                const updatedCard = e.detail;
                if (!updatedCard || !updatedCard.id) return;

                // 1. 优先尝试用 ID 匹配
                let idx = this.cards.findIndex(c => c.id === updatedCard.id);

                // 2. 如果没找到，且存在 old_id，尝试用 old_id 匹配
                if (idx === -1 && updatedCard._old_id) {
                    idx = this.cards.findIndex(c => c.id === updatedCard._old_id);
                }

                // 3. 如果是 Bundle 模式，还可以尝试通过 bundle_dir 匹配 (防止 ID 变化导致丢失)
                if (idx === -1 && updatedCard.is_bundle && updatedCard.bundle_dir) {
                    idx = this.cards.findIndex(c => c.is_bundle && c.bundle_dir === updatedCard.bundle_dir);
                }

                // 移除后重新排序插入
                if (idx !== -1) {
                    // 移除旧对象
                    this.cards.splice(idx, 1);
                }

                this.insertCardSorted(updatedCard);
            });

            // 9. 监听批量导入完成事件 (实现追加模式下的即时显示)
            window.addEventListener('batch-cards-imported', (e) => {
                const { cards } = e.detail;
                if (!cards || cards.length === 0) return;

                const currentViewCat = this.$store.global.viewState.filterCategory;
                const isRecursive = this.$store.global.viewState.recursiveFilter;

                // 逐张卡片判断可见性，因为自动化规则可能把它们分散到了不同目录
                cards.forEach(card => {
                    let shouldShow = false;

                    // 1. 如果当前在根目录视图
                    if (currentViewCat === '') {
                        if (isRecursive) {
                            shouldShow = true; // 递归模式下，根目录显示所有
                        } else {
                            shouldShow = (card.category === ''); // 非递归，只显示根目录卡片
                        }
                    }
                    // 2. 如果当前在子目录视图
                    else {
                        if (card.category === currentViewCat) {
                            shouldShow = true; // 精确匹配
                        } else if (isRecursive && card.category.startsWith(currentViewCat + '/')) {
                            shouldShow = true; // 子目录匹配
                        }
                    }

                    if (shouldShow) {
                        this.handleIncrementalUpdate(card);
                    }
                });
            });

            // 监听 URL 导入的新卡片
            window.addEventListener('card-imported', (e) => {
                const newCard = e.detail;
                if (!newCard) return;

                const currentCat = this.$store.global.viewState.filterCategory;
                const recursive = this.$store.global.viewState.recursiveFilter;

                let shouldShow = false;
                if (currentCat === '') {
                    shouldShow = recursive || newCard.category === '';
                } else {
                    shouldShow = newCard.category === currentCat ||
                        (recursive && newCard.category.startsWith(currentCat + '/'));
                }

                if (shouldShow) {
                    this.handleIncrementalUpdate(newCard);
                }
            });

            window.addEventListener('locate-card', (e) => {
                const card = e.detail;
                this._locateCardLogic(card);
            });

            // 监听标签模态框的批量删除请求
            window.addEventListener('req-batch-remove-current-tags', (e) => {
                const tagsToRemove = e.detail.tags;
                this.handleBatchRemoveTagsFromView(tagsToRemove);
            });

            // 提供给外部（例如侧边栏导入按钮）复用的全局上传入口
            window.stUploadCardFiles = (files, targetCategory = null) => {
                // 使用当前 cardGrid 实例来处理上传，保证行为与拖拽一致
                this._uploadFilesInternal(files, targetCategory);
            };
        },

        // 统一处理增量更新 (插入/排序/去重)
        handleIncrementalUpdate(card) {
            // 1. 如果已存在，先移除 (确保可以重新插入到正确排序位置)
            const idx = this.cards.findIndex(c => c.id === card.id);
            if (idx !== -1) {
                this.cards.splice(idx, 1);
            } else {
                // 如果是全新卡片，总数+1
                this.totalItems++;
            }

            // 2. 按当前排序规则插入
            this.insertCardSorted(card);

            // 3. 更新 Tag 池
            if (card.tags) {
                card.tags.forEach(t => {
                    if (!this.$store.global.allTagsPool.includes(t)) {
                        this.$store.global.allTagsPool.push(t);
                    }
                });
            }
        },

        handleBatchRemoveTagsFromView(tags) {
            // 获取当前视图所有卡片的 ID
            const cardIds = this.cards.map(c => c.id);

            if (cardIds.length === 0) {
                alert("当前视图中没有卡片");
                return;
            }

            const confirmMsg = `确定要从当前视图的 ${cardIds.length} 张卡片中移除以下标签吗？\n\n${tags.join(', ')}\n\n此操作不可撤销！`;
            if (!confirm(confirmMsg)) return;

            batchUpdateTags({
                card_ids: cardIds,
                remove: tags
            }).then(res => {
                if (res.success) {
                    alert(`成功更新 ${res.updated} 张卡片`);
                    // 清空筛选状态
                    this.$store.global.viewState.filterTags = [];
                    // 刷新列表
                    this.fetchCards();
                    // 关闭模态框 (可选，通过事件或 store)
                    this.$store.global.showTagFilterModal = false;
                } else {
                    alert("操作失败: " + res.msg);
                }
            });
        },

        openMarkdownView(content) {
            if (!content) return;
            // 派发事件，由 largeEditor 组件监听并显示
            window.dispatchEvent(new CustomEvent('open-markdown-view', {
                detail: content
            }));
        },

        // === 核心数据加载 ===
        fetchCards() {
            const store = Alpine.store('global');
            // 如果还在初始化，不请求
            if (store.serverStatus.status !== 'ready') return;

            // 取消上一次未完成请求
            try { if (this._fetchCardsAbort) this._fetchCardsAbort.abort(); } catch (e) { console.error(e); }
            this._fetchCardsAbort = new AbortController();

            store.isLoading = true;

            const page = Math.max(1, Math.floor(this.currentPage));
            const pageSize = Math.max(1, Math.floor(store.itemsPerPage));

            const vs = store.viewState;

            const params = {
                page: page.toString(),
                page_size: pageSize.toString(),
                category: vs.filterCategory || '',
                tags: (vs.filterTags || []).join('|||'),
                excluded_tags: (vs.excludedTags || []).join('|||'),
                excluded_cats: (vs.excludedCategories || []).join('|||'),
                search: vs.searchQuery || '',
                search_type: vs.searchType || 'mix',
                sort: store.settingsForm.default_sort || 'date_desc',
                recursive: vs.recursiveFilter,
                fav_filter: vs.favFilter,
                favorites_first: store.settingsForm.favorites_first
            };

            listCards(params) // 调用 API 模块
                .then(data => {
                    this.cards = data.cards || [];

                    // === 更新全局 Store (供 Sidebar 使用) ===
                    store.globalTagsPool = data.global_tags || [];
                    store.sidebarTagsPool = data.sidebar_tags || [];
                    store.allTagsPool = data.sidebar_tags || []; // 默认显示 sidebar tags
                    store.categoryCounts = data.category_counts || {};
                    store.libraryTotal = data.library_total || 0;

                    // 更新文件夹列表 (用于 Sidebar 树生成)
                    const paths = data.all_folders || [];
                    store.allFoldersList = paths.map(p => ({
                        path: p,
                        name: p.split('/').pop(),
                        level: p.split('/').length - 1
                    }));

                    // 更新分页
                    this.totalItems = data.total_count || 0;
                    this.totalPages = Math.ceil(this.totalItems / pageSize) || 1;

                    store.isLoading = false;
                })
                .catch(err => {
                    if (err && err.name !== 'AbortError') console.error(err);
                    store.isLoading = false;
                });
        },

        toggleCardFav(card) {
            // 乐观更新 UI
            card.is_favorite = !card.is_favorite;

            toggleFavorite(card.id).then(res => {
                if (!res.success) {
                    // 如果失败，回滚状态
                    card.is_favorite = !card.is_favorite;
                    alert("操作失败: " + res.msg);
                }
            });
        },

        scheduleFetchCards(reason = '') {
            if (this._suppressAutoFetch) return;
            clearTimeout(this._fetchCardsTimer);
            this._fetchCardsTimer = setTimeout(() => {
                this.fetchCards();
            }, 250);
        },

        changePage(p) {
            if (p >= 1 && p <= this.totalPages) {
                this.currentPage = p;
                const el = document.getElementById('main-scroll');
                if (el) el.scrollTop = 0;
                // 派发分页变化事件，通知 header 更新全选状态
                window.dispatchEvent(new CustomEvent('card-page-changed', { detail: { page: p } }));
                this.fetchCards();
            }
        },

        // === 交互逻辑 ===

        handleCardClick(e, card) {
            // 处理 Ctrl/Meta (多选/反选)
            if (e.ctrlKey || e.metaKey) {
                this.toggleSelection(card);
                return;
            }

            // 处理 Shift (范围选择)
            if (e.shiftKey && this.lastSelectedId) {
                const allCards = this.cards; // 当前页所有卡片
                const startIdx = allCards.findIndex(c => c.id === this.lastSelectedId);
                const endIdx = allCards.findIndex(c => c.id === card.id);

                if (startIdx !== -1 && endIdx !== -1) {
                    const min = Math.min(startIdx, endIdx);
                    const max = Math.max(startIdx, endIdx);

                    // 获取区间内的所有ID
                    const rangeIds = allCards.slice(min, max + 1).map(c => c.id);

                    // 合并到现有 selectedIds (去重)
                    const currentSet = new Set(this.selectedIds);
                    rangeIds.forEach(id => currentSet.add(id));

                    this.selectedIds = Array.from(currentSet); // 写回 Store
                }
                return;
            }

            // 普通左键点击 -> 打开详情页
            window.dispatchEvent(new CustomEvent('open-detail', { detail: card }));
        },

        toggleSelection(card) {
            let ids = [...this.selectedIds];
            if (ids.includes(card.id)) {
                ids = ids.filter(id => id !== card.id);
            } else {
                ids.push(card.id);
                this.lastSelectedId = card.id;
            }
            this.selectedIds = ids;
        },

        // === 批量标签操作 ===

        batchAddTag(tag) {
            const val = (tag || this.batchTagInputAdd || "").trim();
            if (!val) return;

            // selectedIds 继承自 Layout
            if (this.selectedIds.length === 0) {
                alert("请先选择卡片");
                return;
            }

            batchUpdateTags({
                card_ids: this.selectedIds,
                add: [val]
            })
                .then(res => {
                    if (res.success) {
                        alert("成功更新 " + res.updated + " 张卡片");
                        this.batchTagInputAdd = "";
                        this.fetchCards();
                    } else {
                        alert(res.msg);
                    }
                });
        },

        batchRemoveTag(tag) {
            const val = (tag || this.batchTagInputRemove || "").trim();
            if (!val) return;

            if (this.selectedIds.length === 0) {
                alert("请先选择卡片");
                return;
            }

            batchUpdateTags({
                card_ids: this.selectedIds,
                remove: [val]
            })
                .then(res => {
                    if (res.success) {
                        alert("成功更新 " + res.updated + " 张卡片");
                        this.batchTagInputRemove = "";
                        this.fetchCards();
                    } else {
                        alert(res.msg);
                    }
                });
        },

        // === 拖拽逻辑 (Card Drag) ===

        dragStart(e, card) {
            let ids = [...this.selectedIds];
            // 如果当前卡片没被选中，则选中它
            if (!ids.includes(card.id)) {
                ids = [card.id];
                this.selectedIds = ids;
            }
            // 同步拖拽状态到 Store (用于 Layout 接收)
            this.draggedCards = ids;

            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('application/x-st-card', JSON.stringify(ids));
            e.dataTransfer.setData('text/plain', card.id);

            // 视觉反馈
            const cardElement = e.target.closest('.st-card');
            if (cardElement) {
                // 延迟添加样式，避免拖拽的“幽灵图”也变黑白
                requestAnimationFrame(() => {
                    cardElement.classList.add('drag-source');
                });

                // 定义清理函数
                const cleanup = () => {
                    cardElement.classList.remove('drag-source');
                    // 触发全局清理，确保 Store 状态重置
                    window.dispatchEvent(new CustomEvent('global-drag-end'));
                };

                // 绑定一次性 dragend 事件，确保无论成功与否都执行清理
                e.target.addEventListener('dragend', cleanup, { once: true });

                // 自定义拖拽图片 (保持原逻辑)
                if (e.dataTransfer.setDragImage) {
                    const dragImg = document.createElement('img');
                    window.dragImageElement = dragImg;

                    const displayCard = this.draggedCards.length > 1 ?
                        this.cards.find(c => c.id === this.draggedCards[0]) : card;

                    if (displayCard && displayCard.image_url) {
                        dragImg.src = displayCard.image_url;
                        dragImg.style.width = '140px';
                        dragImg.style.height = 'auto';
                        dragImg.style.borderRadius = '8px';
                        dragImg.style.position = 'absolute';
                        dragImg.style.top = '-9999px';
                        dragImg.style.zIndex = '-1';
                        document.body.appendChild(dragImg);
                        e.dataTransfer.setDragImage(dragImg, 70, 70);
                    }
                }
            }
        },

        handleMainDragEnter(e) {
            this.dragCounter++;
            this.dragOverMain = true;
        },
        handleMainDragLeave(e) {
            this.dragCounter--;
            if (this.dragCounter <= 0) {
                this.dragCounter = 0;
                this.dragOverMain = false;
            }
        },

        // 核心文件上传逻辑封装，供拖拽和按钮导入复用
        _uploadFilesInternal(files, targetCategory) {
            if (!files || files.length === 0) return;

            const formData = new FormData();
            let hasFiles = false;
            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                const name = file.name.toLowerCase();
                if (file.type.startsWith('image/') || name.endsWith('.png') || name.endsWith('.json')) {
                    formData.append('files', file);
                    hasFiles = true;
                }
            }

            if (!hasFiles) return;

            const store = this.$store.global;

            // 如果未显式传入分类，则使用当前视图分类
            if (targetCategory === null || targetCategory === undefined) {
                const currentCat = store.viewState.filterCategory || '';
                targetCategory = (currentCat === '' || currentCat === '根目录') ? '' : currentCat;
            }
            if (targetCategory === '根目录') targetCategory = '';

            formData.append('category', targetCategory);
            store.isLoading = true;

            fetch('/api/upload/stage', {
                method: 'POST',
                body: formData
            })
                .then(res => res.json())
                .then(res => {
                    store.isLoading = false;
                    if (res.success) {
                        // 分离有效项和错误项
                        const errors = res.report.filter(item => item.status === 'error');
                        const validReport = res.report.filter(item => item.status !== 'error');
                        // 如果有错误，弹窗提醒
                        if (errors.length > 0) {
                            const errorMsg = errors.map(e => `❌ ${e.filename}: ${e.msg || '格式无效'}`).join('\n');
                            alert(`部分文件导入失败：\n\n${errorMsg}\n\n这些文件将被跳过。`);
                        }
                        // 如果没有有效文件了，终止流程
                        if (validReport.length === 0) {
                            return; // 不打开确认框
                        }// === 单文件无冲突静默导入逻辑 ===
                        // 条件：只有 1 个有效文件，没有报错，且该文件状态不是 conflict
                        if (validReport.length === 1 && errors.length === 0 && validReport[0].status === 'ok') {
                            const item = validReport[0];
                            // 直接构造 commit 请求
                            const decisions = [{
                                filename: item.filename,
                                action: 'import'
                            }];

                            fetch('/api/upload/commit', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                    batch_id: res.batch_id,
                                    category: targetCategory,
                                    decisions: decisions
                                })
                            })
                                .then(cRes => cRes.json())
                                .then(cRes => {
                                    this.$store.global.isLoading = false;
                                    if (cRes.success) {
                                        // 成功提示
                                        const cardName = cRes.new_cards[0] ? cRes.new_cards[0].char_name : item.filename;
                                        this.$store.global.showToast(`✅ 已导入: ${cardName}`);

                                        // 触发事件以更新 UI (复用 batchImportModal 的事件逻辑)
                                        window.dispatchEvent(new CustomEvent('batch-cards-imported', {
                                            detail: { cards: cRes.new_cards }
                                        }));

                                        if (cRes.category_counts) {
                                            this.$store.global.categoryCounts = cRes.category_counts;
                                        }
                                    } else {
                                        alert("导入失败: " + cRes.msg);
                                    }
                                })
                                .catch(err => {
                                    this.$store.global.isLoading = false;
                                    alert("提交失败: " + err);
                                });

                            return;
                        }

                        this.$store.global.isLoading = false;
                        // 打开批量导入确认弹窗 (多文件或有冲突时)
                        window.dispatchEvent(new CustomEvent('open-batch-import-modal', {
                            detail: {
                                batchId: res.batch_id,
                                report: validReport,
                                category: targetCategory
                            }
                        }));
                    } else {
                        alert("准备导入失败: " + res.msg);
                    }
                })
                .catch(err => {
                    store.isLoading = false;
                    alert("上传网络错误: " + err);
                });
        },

        dropCards(targetCat) {
            this.dragCounter = 0;
            this.dragOverMain = false;
            if (this.draggedCards.length === 0) return;

            const targetCatName = targetCat || '根目录';
            if (!confirm(`移动 ${this.draggedCards.length} 张卡片到 "${targetCatName}"?`)) {
                this.draggedCards = [];
                return;
            }
            this.moveCardsToCategory(targetCat);
        },

        moveCardsToCategory(targetCategory) {
            const movingIds = [...this.draggedCards];
            document.body.style.cursor = 'wait';

            moveCard({
                card_ids: movingIds,
                target_category: targetCategory === '根目录' ? '' : targetCategory
            })
                .then(res => {
                    document.body.style.cursor = 'default';
                    if (res.success) {
                        if (res.category_counts) this.$store.global.categoryCounts = res.category_counts;
                        this.fetchCards();
                        this.selectedIds = [];
                        this.draggedCards = [];
                    } else {
                        alert("移动失败: " + res.msg);
                    }
                })
                .catch(err => {
                    document.body.style.cursor = 'default';
                    alert("网络请求错误" + err);
                });
        },

        // === 文件上传 (外部拖拽) ===
        handleFilesDrop(e, targetCategory) {
            this.dragCounter = 0;
            this.dragOverMain = false;
            if (e.dataTransfer.types.includes('application/x-st-card')) return;

            const files = e.dataTransfer.files;
            this._uploadFilesInternal(files, targetCategory);
        },

        insertCardSorted(newCard) {
            const sortMode = this.$store.global.settingsForm.default_sort || 'date_desc';
            let index = -1;

            const compare = (a, b) => {
                if (sortMode === 'date_desc') return b.last_modified - a.last_modified;
                if (sortMode === 'date_asc') return a.last_modified - b.last_modified;
                if (sortMode === 'name_asc') return String(a.char_name).localeCompare(String(b.char_name), 'zh-CN');
                if (sortMode === 'name_desc') return String(b.char_name).localeCompare(String(a.char_name), 'zh-CN');
                if (sortMode === 'token_desc') return (b.token_count || 0) - (a.token_count || 0);
                if (sortMode === 'token_asc') return (a.token_count || 0) - (b.token_count || 0);
                return 0;
            };

            // 寻找插入点：找到第一个"排序后应该在 newCard 后面"的元素
            index = this.cards.findIndex(c => compare(newCard, c) < 0);

            if (index === -1) {
                // 如果没找到比它"小"的，说明它最小（或最大），放在最后
                this.cards.push(newCard);
            } else {
                this.cards.splice(index, 0, newCard);
            }
        },

        // === 删除卡片 ===
        async deleteCards(ids) {
            if (!ids || ids.length === 0) return;

            let hasBundle = false;
            let bundleNames = [];
            this.cards.forEach(c => {
                if (ids.includes(c.id) && c.is_bundle) {
                    hasBundle = true;
                    bundleNames.push(c.char_name);
                }
            });

            let confirmMsg = "";
            if (hasBundle) {
                confirmMsg = `⚠️【操作确认】⚠️\n\n你选中了聚合角色包：\n${bundleNames.join(', ')}\n\n确认将其移至回收站吗？`;
            } else {
                confirmMsg = `🗑️ 确定将选中的 ${ids.length} 张卡片移至回收站吗？`;
            }
            if (!confirm(confirmMsg)) return;

            // 检查是否有资源目录需要确认
            const checkRes = await checkResourceFolders(ids);
            let deleteResources = false;
            
            if (checkRes.success && checkRes.has_resources) {
                const folders = checkRes.resource_folders;
                let resourceMsg = `⚠️ 检测到以下角色卡关联了资源目录：\n\n`;
                
                folders.forEach(item => {
                    resourceMsg += `📁 ${item.card_name}\n   资源目录: ${item.resource_folder}\n\n`;
                });
                
                resourceMsg += `是否连带删除这些资源目录？\n`;
                resourceMsg += `（注意：如果资源目录包含重要文件，建议选择"取消"保留目录）`;
                
                deleteResources = confirm(resourceMsg);
            }

            deleteCards(ids, deleteResources).then(res => {
                if (res.success) {
                    if (res.category_counts) this.$store.global.categoryCounts = res.category_counts;

                    const deletedSet = new Set(ids);
                    const oldLength = this.cards.length;
                    this.cards = this.cards.filter(c => !deletedSet.has(c.id));

                    const deletedCount = oldLength - this.cards.length;
                    this.totalItems -= deletedCount;
                    if (this.filterCategory === '' && !this.searchQuery) {
                        this.$store.global.libraryTotal -= deletedCount;
                    }

                    this.selectedIds = [];

                    if (this.cards.length === 0 && this.currentPage > 1) {
                        this.changePage(this.currentPage - 1);
                    } else if (this.cards.length === 0 && this.totalItems > 0) {
                        this.fetchCards();
                    }

                    if (hasBundle) alert("已将聚合文件夹移至回收站。");
                } else {
                    alert("删除失败: " + res.msg);
                }
            });
        },

        _locateCardLogic(payload) {
            if (!payload || !payload.id) return;

            // 获取是否自动打开详情页的标志，默认为 false
            const shouldOpenDetail = payload.shouldOpenDetail === true;

            const store = Alpine.store('global');
            this._suppressAutoFetch = true;

            // === 在定位前清空所有过滤条件 ===
            this._suppressAutoFetch = true;
            store.viewState.searchQuery = '';      // 清空搜索关键词
            store.viewState.filterTags = [];       // 清空标签筛选
            store.viewState.searchType = 'mix';    // 重置搜索类型
            store.viewState.filterFavorites = false; // 取消仅收藏

            store.isLoading = true;

            let requestCategory = payload.category;
            if (requestCategory === undefined) requestCategory = null;

            findCardPage({
                card_id: payload.id,
                category: requestCategory,
                sort: store.settingsForm.default_sort,
                page_size: store.itemsPerPage
            })
                .then(res => {
                    if (res.success) {
                        // 1. 同步分类
                        if (res.category !== undefined) {
                            store.viewState.filterCategory = res.category;
                        }

                        // 2. 跳转页码
                        this.currentPage = res.page;

                        // 3. 高亮 ID
                        const targetId = res.found_id || payload.id;
                        this.highlightId = targetId;

                        this._suppressAutoFetch = false;

                        // 4. 刷新列表
                        this.fetchCards();

                        // 仅当标志为 true 时才自动打开详情页
                        if (shouldOpenDetail) {
                            setTimeout(() => {
                                const foundCard = this.cards.find(c => c.id === targetId);
                                if (foundCard) {
                                    window.dispatchEvent(new CustomEvent('open-detail', { detail: foundCard }));
                                }
                            }, 500);
                        }

                        setTimeout(() => { this.highlightId = null; }, 5000);
                    } else {
                        alert(res.msg || "定位失败");
                        this.$store.global.isLoading = false;
                        this._suppressAutoFetch = false;
                    }
                })
                .catch(e => {
                    console.error(e);
                    this.$store.global.isLoading = false;
                    this._suppressAutoFetch = false;
                });
        },

        get filteredCards() { return this.cards; },
        get paginatedCards() { return this.cards; }
    }
}