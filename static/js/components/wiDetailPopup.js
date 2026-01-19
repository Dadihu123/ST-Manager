/**
 * static/js/components/wiDetailPopup.js
 * 世界书详情弹窗组件 (对应 detail_wi_popup.html)
 */

import { wiHelpers } from '../utils/wiHelpers.js';
import { deleteWorldInfo, getWorldInfoDetail } from '../api/wi.js';
import { getCardDetail } from '../api/card.js';
import { normalizeWiBook } from '../utils/data.js';
import { formatWiKeys, estimateTokens, getTotalWiTokens } from '../utils/format.js';

export default function wiDetailPopup() {
    return {
        // === 本地状态 ===
        showMobileSidebar: false,
        showWiDetailModal: false,
        activeWiDetail: null, // 当前查看的 WI 对象 (包含 id, name, type, path 等)

        // 阅览室数据
        isLoading: false,
        wiData: null,         // 完整的 WI 对象
        wiEntries: [],        // 归一化后的条目数组
        description: "",      // 世界书描述

        // 搜索过滤
        searchTerm: "",
        activeEntry: null,

        highlightEntryKey: null,   // 用于滚动定位后的短暂高亮
        highlightTimer: null,

        uiFilter: null,    // 'enabled' | 'disabled' | null
        uiStrategy: null,  // 'constant' | 'vector' | 'normal' | null

        // 引入工具函数
        formatWiKeys,
        estimateTokens,
        ...wiHelpers,

        init() {
            // 监听打开事件 (通常由 wiGrid 触发)
            window.addEventListener('open-wi-detail-modal', (e) => {
                this.activeWiDetail = e.detail;
                this.showWiDetailModal = true;
                this.searchTerm = "";
                this.activeEntry = null;
                this.uiFilter = null;
                this.uiStrategy = null;
                this.loadContent();
            });

            // 监听关闭事件 (如果其他组件需要强制关闭它)
            window.addEventListener('close-wi-detail-modal', () => {
                this.showWiDetailModal = false;
                this.highlightEntryKey = null;
                if (this.highlightTimer) clearTimeout(this.highlightTimer);
            });
        },

        // === 计算属性 ===

        get filteredEntries() {
            if (!this.searchTerm) return this.wiEntries;
            const lower = this.searchTerm.toLowerCase();
            return this.wiEntries.filter(e => {
                const keys = Array.isArray(e.keys) ? e.keys.join(' ') : (e.keys || '');
                const content = e.content || '';
                const comment = e.comment || '';
                return keys.toLowerCase().includes(lower) ||
                    content.toLowerCase().includes(lower) ||
                    comment.toLowerCase().includes(lower);
            });
        },

        get uiFilteredEntries() {
            let arr = this.filteredEntries || [];

            // 1) Enabled / Disabled
            if (this.uiFilter === 'enabled') arr = arr.filter(e => !!e.enabled);
            if (this.uiFilter === 'disabled') arr = arr.filter(e => !e.enabled);

            // 2) Strategy
            if (this.uiStrategy === 'constant') arr = arr.filter(e => !!e.constant);
            if (this.uiStrategy === 'vector') arr = arr.filter(e => !e.constant && !!e.vectorized);
            if (this.uiStrategy === 'normal') arr = arr.filter(e => !e.constant && !e.vectorized);

            return arr;
        },

        // 格式化时间戳
        formatDate(timestamp) {
            if (!timestamp) return '';
            return new Date(timestamp * 1000).toLocaleString();
        },

        get totalTokens() {
            return getTotalWiTokens(this.wiEntries);
        },

        // 选中某个条目查看详情
        selectEntry(entry, shouldScroll = false) {
            this.activeEntry = entry;
            if (shouldScroll) {
                this.$nextTick(() => this.scrollToEntry(entry));
            }
        },

        scrollToEntry(entry) {
            if (!entry) return;

            // 1) 计算条目的 DOM id（要与 HTML :id 拼接规则一致）
            // entry.id 优先；否则用 insertion_order + 在 uiFilteredEntries 中的 idx
            let idx = -1;
            if (this.uiFilteredEntries && this.uiFilteredEntries.length) {
                idx = this.uiFilteredEntries.indexOf(entry);
                if (idx === -1 && entry.id) {
                    idx = this.uiFilteredEntries.findIndex(e => e.id === entry.id);
                }
            }

            const keyPart = entry.id || ((entry.insertion_order ?? 'x') + '-' + (idx !== -1 ? idx : 0));
            const domId = `wi-reader-entry-${keyPart}`;

            // 2) 找到滚动容器：中间阅读流的绝对定位滚动层
            // 你当前结构是 .wi-reader-main > .absolute.inset-0(overflow-y-auto)
            const scrollContainer = document.querySelector('.wi-reader-main .custom-scrollbar');
            const el = document.getElementById(domId);

            if (!el) return;

            // 3) 滚动：优先对容器滚动（避免整个页面滚）
            // 使用 scrollIntoView 在大多数情况下就够了，它会找到最近可滚动祖先
            try {
                el.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
            } catch {
                // 旧浏览器兜底
                el.scrollIntoView();
            }

            // 4) 短暂高亮（不改变 active 样式，只做“定位闪一下”）
            this.highlightEntryKey = keyPart;
            if (this.highlightTimer) clearTimeout(this.highlightTimer);
            this.highlightTimer = setTimeout(() => {
                this.highlightEntryKey = null;
            }, 900);
        },

        async loadContent() {
            if (!this.activeWiDetail) return;
            this.isLoading = true;
            this.wiEntries = [];
            this.description = "";
            this.activeEntry = null;
            if (this.highlightTimer) clearTimeout(this.highlightTimer);
            this.highlightEntryKey = null;

            try {
                let rawData = null;

                // 1. 如果是嵌入式，读取角色卡
                if (this.activeWiDetail.type === 'embedded') {
                    const res = await getCardDetail(this.activeWiDetail.card_id);
                    if (res.success && res.card) {
                        rawData = res.card.character_book;
                        this.description = res.card.description || ""; // 嵌入式可能显示角色描述? 或者不显示
                    }
                }
                // 2. 如果是独立文件 (Global/Resource)
                else {
                    const res = await getWorldInfoDetail({
                        id: this.activeWiDetail.id,
                        source_type: this.activeWiDetail.type,
                        file_path: this.activeWiDetail.path
                    });
                    if (res.success) {
                        rawData = res.data;
                    }
                }

                if (rawData) {
                    // 归一化处理 (复用 utils/data.js)
                    const book = normalizeWiBook(rawData, this.activeWiDetail.name);
                    this.wiData = book;
                    // 确保是数组
                    this.wiEntries = Array.isArray(book.entries) ? book.entries : Object.values(book.entries || {});
                    // 尝试提取描述字段 (V3 标准可能有 description)
                    if (book.description) this.description = book.description;
                }

            } catch (err) {
                console.error("Failed to load WI detail:", err);
            } finally {
                this.isLoading = false;
            }
        },

        // === 交互逻辑 ===

        // 删除当前世界书
        deleteCurrentWi() {
            if (!this.activeWiDetail) return;

            // 双重保险：如果是嵌入式，直接返回
            if (this.activeWiDetail.type === 'embedded') {
                alert("无法直接删除内嵌世界书，请去角色卡编辑界面操作。");
                return;
            }

            const name = this.activeWiDetail.name || "该世界书";
            if (!confirm(`⚠️ 确定要删除 "${name}" 吗？\n文件将被移至回收站。`)) return;

            deleteWorldInfo(this.activeWiDetail.path)
                .then(res => {
                    if (res.success) {
                        this.showWiDetailModal = false;
                        // 刷新列表
                        window.dispatchEvent(new CustomEvent('refresh-wi-list'));
                        // 可选：显示 Toast
                        // this.$store.global.showToast("🗑️ 已删除"); 
                    } else {
                        alert("删除失败: " + res.msg);
                    }
                })
                .catch(err => alert("请求错误: " + err));
        },

        // 联动跳转编辑器
        enterWiEditorFromDetail(specificEntry = null) {
            const targetEntry = specificEntry || this.activeEntry;

            let jumpToIndex = 0;
            if (targetEntry && this.wiEntries.length > 0) {
                // 1. 优先尝试直接对象引用匹配 (最准确)
                let idx = this.wiEntries.indexOf(targetEntry);

                // 2. 如果引用匹配失败 (极少见，防Proxy问题)，尝试 ID 匹配
                if (idx === -1 && targetEntry.id) {
                    idx = this.wiEntries.findIndex(e => e.id === targetEntry.id);
                }

                // 3. 如果 ID 也没有或匹配失败，尝试 "指纹" 匹配 (内容+备注+关键词)
                if (idx === -1) {
                    idx = this.wiEntries.findIndex(e =>
                        e.content === targetEntry.content &&
                        e.comment === targetEntry.comment &&
                        JSON.stringify(e.keys) === JSON.stringify(targetEntry.keys)
                    );
                }

                if (idx !== -1) {
                    jumpToIndex = idx;
                }
            }

            this.showWiDetailModal = false;

            // 构造事件数据
            const detailData = {
                ...this.activeWiDetail,
                jumpToIndex: jumpToIndex
            };

            window.dispatchEvent(new CustomEvent('open-wi-editor', {
                detail: detailData
            }));
        },

        // 打开时光机 (Rollback)
        openRollback() {
            this.showWiDetailModal = false; // 关闭当前小弹窗

            this.handleOpenRollback(this.activeWiDetail, null);
        }
    }
}