/**
 * static/js/components/detailModal.js
 * 角色卡详情模态框组件
 */

import { 
    getCardDetail, 
    updateCard, 
    updateCardFile, 
    updateCardFileFromUrl, 
    changeCardImage,
    getCardMetadata,
    sendToSillyTavern,
    setAsBundleCover as apiSetAsBundleCover,
    convertToBundle as apiConvertToBundle,
    toggleBundleMode as apiToggleBundleMode
} from '../api/card.js';

import { 
    renameFolder, 
    performSystemAction
} from '../api/system.js';

import { 
    listSkins,
    setSkinAsCover,
    deleteResourceFile,
    uploadCardResource,
    setResourceFolder as apiSetResourceFolder, 
    openResourceFolder as apiOpenResourceFolder, 
    createResourceFolder as apiCreateResourceFolder 
} from '../api/resource.js';

import { getCleanedV3Data, updateWiKeys } from '../utils/data.js';
import { formatDate, getVersionName, estimateTokens, formatWiKeys } from '../utils/format.js';
import { updateShadowContent } from '../utils/dom.js';
import { createAutoSaver } from '../utils/autoSave.js'; 
import { wiHelpers } from '../utils/wiHelpers.js';

export default function detailModal() {
    const autoSaver = createAutoSaver();
    return {
        // === 本地状态 ===
        showDetail: false,
        activeCard: {}, // 当前查看的卡片对象 (原始引用或副本)
        newTagInput: '',
        tab: 'basic', 
        lastTab: 'basic',
        showFirstPreview: false,
        updateImagePolicy: 'overwrite', // 默认策略
        saveOldCoverOnSwap: false,      // 皮肤换封时是否保留旧图
        dragOverUpdate: false,
        dragOverResource: false,
        showHelpModal: false, 
        
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
            extensions: { regex_scripts: [], tavern_helper: [] },
            character_book: { name: "", entries: [] },
            // UI 字段
            filename: "",
            ui_summary: "",
            source_link: "",
            resource_folder: "",
            character_book_raw: "" // 用于 JSON 编辑
        },

        // 界面控制
        isSaving: false,
        isCardFlipped: false,
        zoomLevel: 100,
        altIdx: 0,
        rawMetadataContent: 'Loading...',
        
        // 皮肤与版本
        skinImages: [],
        currentSkinIndex: -1,

        // 自动保存
        originalDataJson: '', // 基准快照

        showSetResourceFolderModal: false,

        formatDate,
        estimateTokens,
        updateShadowContent,
        formatWiKeys,
        updateWiKeys,
        ...wiHelpers,

        get hasPersonaFields() {
            const d = this.editingData;
            return !!(
                (d.personality && d.personality.trim()) || 
                (d.scenario && d.scenario.trim()) || 
                (d.creator_notes && d.creator_notes.trim()) || 
                (d.system_prompt && d.system_prompt.trim()) || 
                (d.post_history_instructions && d.post_history_instructions.trim())
            );
        },

        // === 初始化 ===
        init() {
            // 监听打开详情页事件
            window.addEventListener('open-detail', (e) => {
                this.openDetail(e.detail);
            });

            // 监听关闭信号
            this.$watch('showDetail', (val) => {
                if (!val) {
                    this.stopAutoSave();
                    this.currentSkinIndex = -1;
                    this.zoomLevel = 100;
                    this.isCardFlipped = false;
                    this.skinImages = [];
                    this.updateImagePolicy = 'overwrite';
                    this.saveOldCoverOnSwap = false;
                }
            });
        },

        // === 新增：处理资源 Tab 的文件拖拽 ===
        handleResourceDrop(e) {
            this.dragOverResource = false;
            const files = e.dataTransfer.files;
            if (!files || files.length === 0) return;

            // 检查是否已设置资源目录
            if (!this.editingData.resource_folder) {
                alert("请先在'管理'页签或顶部栏创建/设置资源目录，才能上传资源文件。");
                return;
            }

            // 逐个上传
            Array.from(files).forEach(file => {
                this.uploadSingleResource(file);
            });
        },

        uploadSingleResource(file) {
            const formData = new FormData();
            formData.append('card_id', this.editingData.id);
            formData.append('file', file);

            // 显示简单的 Loading 状态
            this.$store.global.showToast(`⏳ 正在上传: ${file.name}...`, 2000);

            uploadCardResource(formData).then(res => {
                if (res.success) {
                    this.$store.global.showToast(`✅ ${file.name} 上传成功 (${res.msg})`);
                    
                    // 如果是图片，刷新皮肤列表
                    const ext = file.name.split('.').pop().toLowerCase();
                    if (['png', 'jpg', 'jpeg', 'webp', 'gif'].includes(ext)) {
                        this.fetchSkins(this.editingData.resource_folder);
                    }
                    
                    if (res.is_lorebook) {
                        window.dispatchEvent(new CustomEvent('refresh-wi-list'));
                    }
                } else {
                    alert(`上传 ${file.name} 失败: ${res.msg}`);
                }
            }).catch(e => {
                alert(`网络错误: ${e}`);
            });
        },

        // 删除当前选中的皮肤
        deleteCurrentSkin() {
            if (this.currentSkinIndex === -1) return;
            const skinName = this.skinImages[this.currentSkinIndex];
            
            if (!confirm(`确定要删除皮肤文件 "${skinName}" 吗？\n文件将被移至回收站。`)) return;
            
            this.isSaving = true; // 借用 loading 状态
            
            deleteResourceFile({
                card_id: this.activeCard.id,
                filename: skinName
            }).then(res => {
                this.isSaving = false;
                if (res.success) {
                    this.$store.global.showToast("🗑️ 皮肤已删除");
                    
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
            // 构造一个临时 item 对象，告诉编辑器这是“内嵌”模式
            const item = {
                type: 'embedded',
                card_id: this.activeCard.id,
                name: this.editingData.character_book?.name || "World Info"
            };
            // 派发事件，由 wiEditor.js 监听处理
            window.dispatchEvent(new CustomEvent('open-wi-editor', { detail: item }));
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
        deleteCards(ids) {
            if (!ids || ids.length === 0) return;
            
            let confirmMsg = "";
            if (this.activeCard.is_bundle) {
                confirmMsg = `⚠️【操作确认】⚠️\n\n你选中了聚合角色包：\n${this.activeCard.char_name}\n\n确认将其移至回收站吗？\n(这会将整个文件夹及内部所有版本图片移走)`;
            } else {
                confirmMsg = `🗑️ 确定要将角色卡 "${this.activeCard.char_name}" 移至回收站吗？`;
            }
                
            if (!confirm(confirmMsg)) return;

            import('../api/card.js').then(module => {
                module.deleteCards(ids).then(res => {
                    if (res.success) {
                        this.$store.global.showToast("🗑️ 已移至回收站");
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
            this.originalDataJson = null;
            this.activeCard = c;
            this.skinImages = [];
            this.currentSkinIndex = -1;
            this.isCardFlipped = false;
            this.showFirstPreview = false;
            this.lastTab = this.tab; 
            this.tab = 'basic';

            // 深拷贝并清洗数据 (Flatten & Sanitize)
            let rawData = JSON.parse(JSON.stringify(c));

            // 1. 解包嵌套 data (Tavern V3)
            if (rawData.data && typeof rawData.data === 'object') {
                Object.assign(rawData, rawData.data);
                delete rawData.data;
            }

            // 2. 确保扩展字段存在
            if (!rawData.extensions || typeof rawData.extensions !== 'object') rawData.extensions = {};
            if (!Array.isArray(rawData.extensions.tavern_helper)) rawData.extensions.tavern_helper = [];
            if (!Array.isArray(rawData.extensions.regex_scripts)) rawData.extensions.regex_scripts = [];

            // 3. 确保备用开场白
            if (!Array.isArray(rawData.alternate_greetings)) rawData.alternate_greetings = [];
            rawData.alternate_greetings = rawData.alternate_greetings.filter(g => typeof g === 'string');
            if (rawData.alternate_greetings.length === 0) rawData.alternate_greetings = [""];

            // 4. 补全 UI 字段
            rawData.ui_summary = rawData.ui_summary || c.ui_summary || "";
            rawData.source_link = rawData.source_link || c.source_link || "";
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

            // 赋值给编辑器
            this.editingData = rawData;
            this.altIdx = 0;

            // 6. 处理世界书
            if (!this.editingData.character_book) {
                this.editingData.character_book = { name: "World Info", entries: [] };
            } else if (Array.isArray(this.editingData.character_book)) {
                // 兼容 V2 数组
                this.editingData.character_book = {
                    name: this.editingData.char_name || "World Info",
                    entries: this.editingData.character_book
                };
            }
            if (!this.editingData.character_book.name) this.editingData.character_book.name = "World Info";
            
            // 生成 Raw JSON 字符串
            this.editingData.character_book_raw = JSON.stringify(this.editingData.character_book, null, 2);
            this.editingData.filename = c.filename;

            // 显示模态框
            this.showDetail = true;

            // 加载资源
            if (c.resource_folder) this.fetchSkins(c.resource_folder);

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

                    this.editingData.character_version = safeCard.char_version || safeCard.character_version || "";
                    
                    this.editingData.alternate_greetings = safeCard.alternate_greetings || [];
                    if (this.editingData.alternate_greetings.length === 0) this.editingData.alternate_greetings = [""];
                    this.altIdx = 0;

                    if (safeCard.character_book) {
                        let book = safeCard.character_book;
                        if (Array.isArray(book)) book = { name: safeCard.char_name, entries: book };
                        this.editingData.character_book = book;
                        this.editingData.character_book_raw = JSON.stringify(book, null, 2);
                    }

                    if (safeCard.extensions) {
                        this.editingData.extensions = JSON.parse(JSON.stringify(safeCard.extensions));
                        if (!this.editingData.extensions.regex_scripts) this.editingData.extensions.regex_scripts = [];
                        if (!this.editingData.extensions.tavern_helper) this.editingData.extensions.tavern_helper = [];
                    }

                    if (res.card.image_url) this.activeCard.image_url = res.card.image_url;

                    if (this.lastTab === 'persona' && this.hasPersonaFields) {
                        this.tab = 'persona';
                    }

                    // 启动自动保存
                    this.$nextTick(() => {
                        // 1. 记录当前状态为“原始基准”
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
            // 同步 Raw JSON 到对象 (如果用户修改了 Textarea)
            if (this.editingData.character_book) {
                this.editingData.character_book_raw = JSON.stringify(this.editingData.character_book, null, 2);
            }

            this._internalSaveCard(false);
        },

        _internalSaveCard(isBundleRenamed) {
            // 1. 获取清洗后的 V3 数据 (使用 Utils)
            const cleanData = getCleanedV3Data(this.editingData);

            // 2. 同步回 editingData (UI 反馈)
            if (this.editingData.alternate_greetings && cleanData.alternate_greetings) {
                this.editingData.alternate_greetings = cleanData.alternate_greetings;
                if (this.editingData.alternate_greetings.length === 0) this.editingData.alternate_greetings = [""];
            }

            // 3. 构建 Payload
            const payload = {
                id: this.activeCard.id,
                new_filename: this.editingData.filename,
                
                // 核心数据 (Spread Clean Data)
                ...cleanData, // 包含 name, description, first_mes, tags 等所有 V3 字段

                // UI 专用字段
                ui_summary: this.editingData.ui_summary,
                source_link: this.editingData.source_link,
                resource_folder: this.editingData.resource_folder,
                
                // Bundle 标记
                save_ui_to_bundle: this.activeCard.is_bundle,
                bundle_dir: this.activeCard.is_bundle ? this.activeCard.bundle_dir : undefined
            };

            // 兼容性映射：getCleanedV3Data 返回的是 name，但 updateCard 需要 char_name
            payload.char_name = cleanData.name;

            updateCard(payload).then(res => {
                this.isSaving = false;
                if (res.success) {
                    // 更新基准
                    this.originalDataJson = JSON.stringify(this.editingData);
                    const ts = new Date().getTime();

                    // 更新 ID/Filename
                    if (res.new_id) {
                        this.activeCard.id = res.new_id;
                        this.editingData.id = res.new_id;
                        this.activeCard.filename = res.new_filename;
                        this.editingData.filename = res.new_filename;
                    }
                    if (res.new_image_url) this.activeCard.image_url = res.new_image_url;

                    // 通知列表更新 (通过事件总线)
                    if (res.updated_card) {
                        // 补充 UI 数据到返回对象
                        res.updated_card.ui_summary = this.editingData.ui_summary;
                        
                        // 强制刷新缩略图
                        if (res.file_modified) {
                            res.updated_card.thumb_url = `/api/thumbnail/${encodeURIComponent(res.updated_card.id)}?t=${ts}`;
                        }
                        
                        // 发送更新事件给 cardGrid
                        window.dispatchEvent(new CustomEvent('card-updated', { 
                            detail: res.updated_card 
                        }));
                        
                        // 更新本地 activeCard
                        Object.assign(this.activeCard, res.updated_card);
                    } else {
                        // 兜底刷新
                        window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    }

                    this.$store.global.showToast("💾 保存成功", 2000);
                    
                    // 刷新详情
                    const idToRefresh = (res.new_id || (res.updated_card && res.updated_card.id) || this.editingData.id);
                    this.refreshActiveCardDetail(idToRefresh);
                    autoSaver.initBaseline(this.editingData); // 手动保存后，重置自动保存
                } else {
                    alert("保存失败: " + res.msg);
                }
            }).catch(e => {
                this.isSaving = false;
                alert("请求错误: " + e);
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
            formData.append('keep_ui_data', JSON.stringify({
                ui_summary: this.editingData.ui_summary,
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
                    this.$store.global.showToast("✅ 封面已切换");
                    
                    // 强制刷新图片显示
                    const ts = new Date().getTime();
                    this.activeCard.image_url += (this.activeCard.image_url.includes('?') ? '&' : '?') + `t=${ts}`;
                    
                    // 刷新列表
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
                    
                    // 刷新皮肤列表 (如果保存了旧图，皮肤列表会增加)
                    if (this.saveOldCoverOnSwap) {
                        this.fetchSkins(this.editingData.resource_folder);
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
            updateCardFileFromUrl({
                card_id: this.editingData.id,
                url: url,
                is_bundle_update: isBundleUpdate,
                image_policy: finalPolicy,
                keep_ui_data: {
                    ui_summary: this.editingData.ui_summary,
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
                this.$store.global.showToast("✅ 更新成功", 2000);
                const updatedCard = res.updated_card;
                if (updatedCard) {
                    const ts = new Date().getTime();
                    if (updatedCard.image_url) updatedCard.image_url += `?t=${ts}`;
                    
                    this.activeCard = updatedCard;
                    this.editingData = JSON.parse(JSON.stringify(updatedCard));
                    
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

        get displayImageUrl() {
            if (this.currentSkinIndex === -1 || this.skinImages.length === 0) {
                return this.activeCard.image_url;
            }
            const folder = this.activeCard.resource_folder || this.editingData.resource_folder;
            const file = this.skinImages[this.currentSkinIndex];
            return `/resources_file/${encodeURIComponent(folder)}/${encodeURIComponent(file)}`;
        },

        getSkinUrl(skinName) {
            const folder = this.activeCard.resource_folder || this.editingData.resource_folder;
            if (!folder || !skinName) return '';
            return `/resources_file/${encodeURIComponent(folder)}/${encodeURIComponent(skinName)}`;
        },

        fetchSkins(folderName) {
            this.skinImages = [];
            this.currentSkinIndex = -1;
            if (!folderName) return;
            listSkins(folderName).then(res => {
                if (res.success) this.skinImages = res.skins || [];
            });
        },

        nextSkin() {
            if (this.skinImages.length === 0) return;
            this.currentSkinIndex++;
            if (this.currentSkinIndex >= this.skinImages.length) this.currentSkinIndex = -1;
        },

        prevSkin() {
            if (this.skinImages.length === 0) return;
            this.currentSkinIndex--;
            if (this.currentSkinIndex < -1) this.currentSkinIndex = this.skinImages.length - 1;
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
                    if (!this.activeCard.is_bundle) this.editingData.filename = c.filename;
                    
                    this.editingData.id = c.id;
                    this.editingData.char_name = c.char_name;
                    this.editingData.description = c.description;
                    this.editingData.first_mes = c.first_mes;
                    this.editingData.mes_example = c.mes_example;
                    this.editingData.alternate_greetings = c.alternate_greetings || [""];
                    this.editingData.creator_notes = c.creator_notes;
                    this.editingData.character_book = c.character_book;
                    this.altIdx = 0;
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
                    this.$store.global.showToast("✅ 已设为封面");
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
            if (!confirm(`⚠️ 确定要取消聚合模式吗？`)) return;
            
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
                    this.activeCard.resource_folder = res.resource_folder;
                    alert("设置成功");
                } else {
                    alert(res.msg);
                }
            });
        },

        createResourceFolder() {
            apiCreateResourceFolder({ card_id: this.editingData.id })
                .then(res => {
                    if (res.success) {
                        this.editingData.resource_folder = res.resource_folder;
                        this.activeCard.resource_folder = res.resource_folder;
                        alert("创建成功");
                    } else alert(res.msg);
                });
        },

        sendToST() {
            const btn = document.getElementById('btn-send-st');
            if (btn) btn.innerText = '发送中...';
            
            sendToSillyTavern(this.activeCard.id)
                .then(res => {
                    if (res.success) alert("✅ 发送成功");
                    else alert("❌ 发送失败: " + res.msg);
                })
                .finally(() => {
                    if (btn) btn.innerText = '🚀 发送到 ST';
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
                    const ts = new Date().getTime();
                    // 处理 ID 变更 (JSON -> PNG)
                    if (res.new_id && res.new_id !== this.editingData.id) {
                        this.activeCard.id = res.new_id;
                        this.editingData.id = res.new_id;
                        this.activeCard.filename = res.new_id.split('/').pop();
                        this.editingData.filename = this.activeCard.filename;
                    }
                    this.activeCard.image_url = res.new_image_url;
                    
                    window.dispatchEvent(new CustomEvent('refresh-card-list'));
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

        addTag() {
            const val = (this.newTagInput || "").trim();
            
            if (!val) return;

            // 确保 tags 数组初始化
            if (!this.editingData.tags) {
                this.editingData.tags = [];
            }

            // 查重并添加
            if (!this.editingData.tags.includes(val)) {
                this.editingData.tags.push(val);
            }
            
            // 清空输入框
            this.newTagInput = '';
        },

        prevAlt() {
            if (this.altIdx > 0) this.altIdx--;
            else this.altIdx = this.editingData.alternate_greetings.length - 1;
        },
        nextAlt() {
            if (this.altIdx < this.editingData.alternate_greetings.length - 1) this.altIdx++;
            else this.altIdx = 0;
        },
        addAlt() {
            this.editingData.alternate_greetings.push("");
            this.altIdx = this.editingData.alternate_greetings.length - 1;
        },
        removeAlt() {
            if (this.editingData.alternate_greetings.length <= 1) {
                this.editingData.alternate_greetings = [""];
            } else {
                this.editingData.alternate_greetings.splice(this.altIdx, 1);
                if (this.altIdx >= this.editingData.alternate_greetings.length) {
                    this.altIdx = this.editingData.alternate_greetings.length - 1;
                }
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
            window.dispatchEvent(new CustomEvent('open-tag-picker', {
                detail: this.editingData.tags // 传递 tags 数组引用
            }));
        },

        openAdvancedEditor() {
            // 派发事件，将完整的 editingData 引用传过去
            window.dispatchEvent(new CustomEvent('open-advanced-editor', {
                detail: this.editingData 
            }));
        },

        openMarkdownView(content) {
            window.dispatchEvent(new CustomEvent('open-markdown-view', {
                detail: content
            }));
        }

    }
}