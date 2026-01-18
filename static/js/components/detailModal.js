/**
 * static/js/components/detailModal.js
 * 角色卡详情模态框组件
 */

import { 
    getCardDetail, 
    updateCard, 
    updateCardFile, 
    updateCardFileFromUrl, 
    checkCardUpdate,
    fetchSourceMetadata,
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
        isCheckingUpdate: false,
        hasUpdate: false,
        updateDownloadUrl: "",
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
                }
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
                bundle_dir: this.activeCard.bundle_dir
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
            rawData.source_title_sync = rawData.source_title_sync || c.source_title_sync || "";
            rawData.resource_folder = rawData.resource_folder || c.resource_folder || "";
            
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
                    this.editingData.ui_summary = safeCard.ui_summary || "";
                    this.editingData.source_link = safeCard.source_link || "";
                    this.editingData.source_title_sync = safeCard.source_title_sync || "";
                    
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
                source_title_sync: this.editingData.source_title_sync,
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
            
            if (!file.name.toLowerCase().endsWith('.png') && !file.name.toLowerCase().endsWith('.json')) {
                alert("请上传 PNG 或 JSON 格式");
                e.target.value = '';
                return;
            }

            let isBundleUpdate = false;
            if (this.activeCard.is_bundle) {
                const choice = confirm(`检测到这是聚合角色包。\n\n[确定] = 添加为新版本 (推荐)\n[取消] = 覆盖当前选中的版本文件`);
                isBundleUpdate = choice;
            } else {
                if (!confirm(`确定要用新文件覆盖 "${this.activeCard.char_name}" 吗？`)) {
                    e.target.value = '';
                    return;
                }
            }

            const formData = new FormData();
            formData.append('new_card', file);
            formData.append('card_id', this.editingData.id);
            formData.append('is_bundle_update', isBundleUpdate);
            formData.append('keep_ui_data', JSON.stringify({
                ui_summary: this.editingData.ui_summary,
                source_link: this.editingData.source_link,
                resource_folder: this.editingData.resource_folder,
                tags: this.editingData.tags
            }));

            this.performUpdate(formData, '/api/update_card_file', e.target);
        },

        triggerUrlUpdate() {
            const url = prompt("请输入新的角色卡图片链接 (PNG/WEBP):\n注意：这仅更新图片和数据，不会更改'来源链接'字段。");
            if (!url) return;

            let isBundleUpdate = false;
            if (this.activeCard.is_bundle) {
                if (confirm(`确认从 URL 更新? (聚合包模式：将自动添加为新版本)`)) isBundleUpdate = true;
                else return;
            } else {
                if (!confirm(`确定从 URL 覆盖当前卡片吗？`)) return;
            }

            this.isSaving = true;
            updateCardFileFromUrl({
                card_id: this.editingData.id,
                url: url,
                is_bundle_update: isBundleUpdate,
                keep_ui_data: {
                    ui_summary: this.editingData.ui_summary,
                    source_link: this.editingData.source_link,
                    resource_folder: this.editingData.resource_folder,
                    tags: this.editingData.tags
                }
            }).then(res => this.handleUpdateResponse(res))
              .catch(err => { this.isSaving = false; alert(err); });
        },

        async syncMetadata() {
            if (!this.editingData.source_link) return;
            this.isCheckingUpdate = true;
            try {
                const res = await fetchSourceMetadata({ source_link: this.editingData.source_link });
                if (res.success) {
                    // 如果本地名称为空或者用户确认，则更新本地名称
                    const remoteName = res.name || '';
                    const remoteVersion = res.version || '';
                    
                    if (remoteName) {
                        this.editingData.source_title_sync = remoteName;
                        this.$store.global.showToast(`✅ 已同步远程标题基准`);
                    }
                    
                    if (remoteVersion) {
                        this.editingData.char_version = remoteVersion;
                        this.$store.global.showToast(`✅ 已同步版本号: ${remoteVersion}`);
                    } else {
                        this.$store.global.showToast(`✅ 已获取远程信息: ${remoteName}`);
                    }
                } else {
                    alert("同步失败: " + res.msg);
                }
            } catch (err) {
                alert("同步请求出错: " + err);
            } finally {
                this.isCheckingUpdate = false;
            }
        },

        async checkUpdate() {
            if (!this.editingData.source_link) {
                alert("请先填写来源链接 (目前支持 Chub.ai 和 Discord)");
                return;
            }
            this.isCheckingUpdate = true;
            this.hasUpdate = false;
            try {
                const res = await checkCardUpdate({
                    card_id: this.activeCard.id,
                    source_link: this.editingData.source_link,
                    source_title_sync: this.editingData.source_title_sync
                });
                if (res.success) {
                    if (res.has_update) {
                        this.hasUpdate = true;
                        this.updateDownloadUrl = res.download_url;
                        const reason = res.update_info.reason || '检测到新内容';
                        alert(`✨ 检测到更新!\n原因: ${reason}\n远程版本: ${res.update_info.remote_version || '未知'}\n最后更新: ${res.update_info.remote_updated_at || '未知'}\n\n请点击来源链接旁边的按钮手动前往下载，然后在此处上传覆盖即可。`);
                    } else {
                        alert("目前已是最新版本");
                    }
                } else {
                    alert("检测失败: " + res.msg);
                }
            } catch (err) {
                alert("检测出错: " + err);
            } finally {
                this.isCheckingUpdate = false;
            }
        },

        async downloadAndApplyUpdate() {
            if (!this.updateDownloadUrl) return;
            
            this.isSaving = true;
            try {
                const res = await updateCardFileFromUrl({
                    card_id: this.editingData.id,
                    url: this.updateDownloadUrl,
                    is_bundle_update: this.activeCard.is_bundle,
                    keep_ui_data: {
                        ui_summary: this.editingData.ui_summary,
                        source_link: this.editingData.source_link,
                        source_title_sync: this.editingData.source_title_sync,
                        resource_folder: this.editingData.resource_folder,
                        tags: this.editingData.tags
                    }
                });
                this.handleUpdateResponse(res);
                this.hasUpdate = false;
            } catch (err) {
                this.isSaving = false;
                alert(err);
            }
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
            // 如果在 Docker 环境下，使用网页版文件管理器
            if (this.$store.global.isDocker) {
                window.dispatchEvent(new CustomEvent('open-resource-manager', {
                    detail: {
                        card_id: this.editingData.id,
                        char_name: this.editingData.char_name
                    }
                }));
                return;
            }

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
            const val = this.newTagInput.trim();
            if (val) {
                if (!this.editingData.tags) this.editingData.tags = [];
                if (!this.editingData.tags.includes(val)) {
                    this.editingData.tags.push(val);

                    // 同步添加到全局标签库
                    const globalStore = Alpine.store('global');
                    if (globalStore && globalStore.globalTagsPool) {
                        if (!globalStore.globalTagsPool.includes(val)) {
                            globalStore.globalTagsPool.push(val);
                            // 保持字母序 (可选)
                            globalStore.globalTagsPool.sort((a, b) => a.localeCompare(b));
                        }
                    }
                }
                this.newTagInput = '';
            }
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