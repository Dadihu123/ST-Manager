/**
 * static/js/components/cardGrid.js
 * 角色卡网格组件：核心列表视图
 */

import { 
    listCards, 
    deleteCards, 
    findCardPage, 
    moveCard, 
    uploadCards,
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
        set selectedIds(val) { this.$store.global.viewState.selectedIds = val; return true;},
        
        get lastSelectedId() { return this.$store.global.viewState.lastSelectedId; },
        set lastSelectedId(val) { this.$store.global.viewState.lastSelectedId = val; return true;},

        get draggedCards() { return this.$store.global.viewState.draggedCards; },
        set draggedCards(val) { this.$store.global.viewState.draggedCards = val; return true;},

        // === 初始化 ===
        init() {
            // 1. 监听全局搜索/筛选变化 (Reactivity Fix)
            // 使用 debounce 防止输入时频繁请求
            this.$watch('$store.global.viewState.searchQuery', () => this.scheduleFetchCards('search'));
            this.$watch('$store.global.viewState.searchType', () => { this.currentPage=1; this.scheduleFetchCards('type'); });
            this.$watch('$store.global.viewState.filterCategory', () => { this.currentPage=1; this.fetchCards(); });
            this.$watch('$store.global.viewState.filterTags', () => { this.currentPage=1; this.fetchCards(); });
            this.$watch('$store.global.viewState.recursiveFilter', () => { this.fetchCards(); });
            
            // 监听排序设置变化
            this.$watch('$store.global.settingsForm.default_sort', () => { this.currentPage=1; this.fetchCards(); });
            this.$watch('$store.global.itemsPerPage', () => { this.currentPage=1; this.fetchCards(); });

            // 监听收藏过滤变化
            this.$watch('$store.global.viewState.filterFavorites', () => { this.currentPage=1; this.fetchCards(); });
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

            // 8. 监听单卡更新事件
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

                if (idx !== -1) {
                    // 原地替换
                    this.cards[idx] = updatedCard;
                } else {
                    // 如果完全没找到（可能是新增），插入开头
                    this.cards.unshift(updatedCard);
                }
            });

            // 9. 监听批量导入完成事件 (实现追加模式下的即时显示)
            window.addEventListener('batch-cards-imported', (e) => {
                const { cards, category } = e.detail;
                if (!cards || cards.length === 0) return;

                const currentViewCat = this.$store.global.viewState.filterCategory;
                const isRecursive = this.$store.global.viewState.recursiveFilter;

                // 可见性检查
                let shouldShow = false;
                if (currentViewCat === '') {
                    // 根目录视图：如果开启递归，或者是直接上传到根目录，则显示
                    shouldShow = (category === '') || isRecursive;
                } else {
                    // 子目录视图：必须匹配当前目录
                    // 注意：如果上传到 currentViewCat/SubDir 且开启递归，也应该显示，这里做简化处理
                    shouldShow = (category === currentViewCat) || (isRecursive && category.startsWith(currentViewCat + '/'));
                }

                if (shouldShow) {
                    cards.forEach(card => {
                        this.handleIncrementalUpdate(card);
                    });
                }
            });

            // 监听 URL 导入的新卡片
            window.addEventListener('card-imported', (e) => {
                const newCard = e.detail;
                if (!newCard) return;

                // 判断是否应该在当前视图显示 (逻辑同 handleFilesDrop)
                let shouldShow = false;
                // 获取当前的筛选分类 (直接读 store 或者 local prop)
                const currentCat = this.$store.global.viewState.filterCategory;
                const recursive = this.$store.global.viewState.recursiveFilter;

                if (currentCat === '') {
                    // 根目录视图：如果是递归，全显示；如果不递归，只显示根目录卡片
                    shouldShow = recursive || newCard.category === '';
                } else {
                    // 特定目录视图
                    shouldShow = newCard.category === currentCat || 
                        (recursive && newCard.category.startsWith(currentCat + '/'));
                }

                // 如果符合当前视图，插入列表
                if (shouldShow) {
                    this.insertCardSorted(newCard);
                    this.totalItems++;
                }
                
                // 更新标签池
                if (newCard.tags) {
                    newCard.tags.forEach(t => {
                        if (!this.$store.global.allTagsPool.includes(t)) {
                            this.$store.global.allTagsPool.push(t);
                        }
                    });
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
            try { if (this._fetchCardsAbort) this._fetchCardsAbort.abort(); } catch(e) { console.error(e); }
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
                search: vs.searchQuery || '',
                search_type: vs.searchType || 'mix',
                sort: store.settingsForm.default_sort || 'date_desc',
                recursive: vs.recursiveFilter,
                favorites_only: vs.filterFavorites,
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

        scheduleFetchCards(reason='') {
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
            if (!files || files.length === 0) return;

            const formData = new FormData();
            let hasFiles = false;
            for (let i = 0; i < files.length; i++) {
                const name = files[i].name.toLowerCase();
                if (files[i].type.startsWith('image/') || name.endsWith('.png') || name.endsWith('.json')) {
                    formData.append('files', files[i]);
                    hasFiles = true;
                }
            }

            if (!hasFiles) return;

            if (targetCategory === null || targetCategory === undefined) {
                targetCategory = (this.filterCategory === '' || this.filterCategory === '根目录') ? '' : this.filterCategory;
            }
            if (targetCategory === '根目录') targetCategory = '';

            formData.append('category', targetCategory);
            this.$store.global.isLoading = true;

            fetch('/api/upload/stage', {
                method: 'POST',
                body: formData
            })
                .then(res => res.json())
                .then(res => {
                    this.$store.global.isLoading = false;
                    if (res.success) {
                        // 打开批量导入确认弹窗
                        window.dispatchEvent(new CustomEvent('open-batch-import-modal', {
                            detail: {
                                batchId: res.batch_id,
                                report: res.report,
                                category: targetCategory
                            }
                        }));
                    } else {
                        alert("准备导入失败: " + res.msg);
                    }
                })
                .catch(err => {
                    this.$store.global.isLoading = false;
                    alert("上传网络错误: " + err);
                });
        },

        insertCardSorted(newCard) {
            const sortMode = this.$store.global.settingsForm.default_sort || 'date_desc';
            let index = -1;

            if (sortMode === 'date_desc') {
                index = this.cards.findIndex(c => c.last_modified < newCard.last_modified);
            } else if (sortMode === 'date_asc') {
                index = this.cards.findIndex(c => c.last_modified > newCard.last_modified);
            } else if (sortMode === 'name_asc') {
                index = this.cards.findIndex(c => String(c.char_name).localeCompare(String(newCard.char_name), 'zh-CN') > 0);
            } else if (sortMode === 'name_desc') {
                index = this.cards.findIndex(c => String(newCard.char_name).localeCompare(String(c.char_name), 'zh-CN') > 0);
            }

            if (index === -1) {
                this.cards.push(newCard);
            } else {
                this.cards.splice(index, 0, newCard);
            }
        },

        // === 删除卡片 ===
        deleteCards(ids) {
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

            deleteCards(ids).then(res => {
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

                    if(hasBundle) alert("已将聚合文件夹移至回收站。");
                } else {
                    alert("删除失败: " + res.msg);
                }
            });
        },

        _locateCardLogic(card) {
            if (!card) return;
            
            let targetCategory = card.category;
            if (card.is_bundle || (card.id.split('/').length > 1 && !targetCategory)) {   
                // 如果 targetCategory 等于 activeCard.bundle_dir，则向上取一级
                if (card.bundle_dir && targetCategory === card.bundle_dir) {
                    const parentParts = targetCategory.split('/');
                    parentParts.pop(); // 移除 Bundle 名
                    targetCategory = parentParts.join('/');
                }
            }
            if (targetCategory === undefined || targetCategory === null) {
                targetCategory = card.id.includes('/') ? card.id.split('/').slice(0, -1).join('/') : '';
            }

            const store = Alpine.store('global');

            this._suppressAutoFetch = true;

            // === 在定位前清空所有过滤条件 ===
            this._suppressAutoFetch = true;
            store.viewState.searchQuery = '';      // 清空搜索关键词
            store.viewState.filterTags = [];       // 清空标签筛选
            store.viewState.searchType = 'mix';    // 重置搜索类型
            store.viewState.filterFavorites = false; // 取消仅收藏

            store.isLoading = true;

            findCardPage({
                card_id: card.id,
                category: targetCategory,
                sort: store.settingsForm.default_sort,
                page_size: store.itemsPerPage
            })
            .then(res => {
                if (res.success) {
                    this.currentPage = res.page;
                    this.highlightId = card.id;
                    
                    this._suppressAutoFetch = false;
                    this.fetchCards();
                    
                    setTimeout(() => { this.highlightId = null; }, 3000);
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