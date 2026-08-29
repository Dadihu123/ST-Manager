/**
 * static/js/components/presetGrid.js
 * 预设网格组件 - 对齐 extensionGrid.js 风格
 */
import {
  sendPresetToSillyTavern,
  isPresetSendToStPending,
  setPresetSendToStPending,
} from "../api/presets.js";
import { downloadFileFromApi } from "../utils/download.js";
import { createMarqueeSelection } from "../utils/marqueeSelection.js";

export default function presetGrid() {
  return {
    items: [],
    isLoading: false,
    dragOver: false,
    sendingPresetToStIds: {},

    ...createMarqueeSelection({
      mode: "presets",
      rootId: "preset-scroll-area",
      itemSelector: ".preset-grid-card[data-preset-id]",
      getId: (element, component) => {
        const rawId = element.dataset.presetId;
        const item = (component.items || []).find(
          (currentItem) => String(currentItem.id) === rawId,
        );
        return item?.id ?? rawId;
      },
      canSelectElement: (element, component) => {
        const rawId = element.dataset.presetId;
        const item = (component.items || []).find(
          (currentItem) => String(currentItem.id) === rawId,
        );
        return !!item && component.canSelectPresetItem(item);
      },
      isDisabled: (component) => component.dragOver,
    }),
    get selectedIds() {
      return this.$store.global.viewState.selectedIds;
    },
    set selectedIds(val) {
      this.$store.global.viewState.selectedIds = val;
      return true;
    },
    get lastSelectedId() {
      return this.$store.global.viewState.lastSelectedId;
    },
    set lastSelectedId(val) {
      this.$store.global.viewState.lastSelectedId = val;
      return true;
    },
    get draggedCards() {
      return this.$store.global.viewState.draggedCards;
    },
    set draggedCards(val) {
      this.$store.global.viewState.draggedCards = val;
      return true;
    },

    get filterType() {
      return this.$store.global.presetFilterType || "all";
    },
    get filterCategory() {
      return this.$store.global.presetFilterCategory || "";
    },

    get presetUploadHintText() {
      if (this.isGlobalCategoryContext()) {
        return `将存入全局分类 ${this.filterCategory}`;
      }
      if (this.filterType !== "all" && this.filterType !== "global") {
        return "当前不在全局分类上下文，上传到全局目录需要明确确认";
      }
      return "将存入全局预设目录";
    },

    isGlobalCategoryContext() {
      if (!this.filterCategory) return false;
      const capabilities = this.$store.global.presetFolderCapabilities || {};
      const selected = capabilities[this.filterCategory] || {};
      return (
        (this.filterType === "global" || this.filterType === "all") &&
        selected.has_physical_folder
      );
    },

    getMovablePresetCategories() {
      const capabilities = this.$store.global.presetFolderCapabilities || {};
      return (this.$store.global.presetAllFolders || []).filter(
        (path) => capabilities[path]?.has_physical_folder,
      );
    },

    getPresetSourceBadge(item) {
      const source_type = item?.source_type || item?.type;
      if (source_type === "global") return "GLOBAL / 物理分类";
      if (item?.category_mode === "override")
        return "RESOURCE / 已覆盖管理器分类";
      return "RESOURCE / 跟随角色卡";
    },

    getPresetOwnerName(item) {
      return item?.owner_card_name || item?.source_folder || "";
    },

    getPresetOwnerId(item) {
      return item?.owner_card_id || "";
    },

    setPresetSendingState(itemId, sending) {
      const key = String(itemId || "").trim();
      if (!key) return;
      if (sending) {
        this.sendingPresetToStIds = {
          ...this.sendingPresetToStIds,
          [key]: true,
        };
        return;
      }

      const next = { ...this.sendingPresetToStIds };
      delete next[key];
      this.sendingPresetToStIds = next;
    },

    canSendPresetToST(item) {
      const source_folder = String(item?.source_folder || "").trim();
      const root_scope_key = String(item?.root_scope_key || "").trim();
      const targetId = String(this.getPresetActionTargetId(item) || "").trim();
      if (
        source_folder.includes("global-alt::") ||
        source_folder === "st_openai_preset_dir" ||
        root_scope_key === "st_openai_preset_dir" ||
        String(item?.id || "").startsWith("global-alt::") ||
        targetId.startsWith("global-alt::")
      ) {
        return false;
      }
      return item?.preset_kind === "openai";
    },

    isSendingPresetToST(itemId) {
      return (
        !!this.sendingPresetToStIds[String(itemId)] ||
        isPresetSendToStPending(itemId)
      );
    },

    getPresetSendToSTTitle(item) {
      const targetId = this.getPresetActionTargetId(item);
      if (!this.canSendPresetToST(item)) {
        return "仅 OpenAI/对话补全预设可发送到 ST";
      }
      if (this.isSendingPresetToST(targetId)) return "正在发送到 ST";
      if (Number(item?.last_sent_to_st || 0) > 0) {
        return `已发送到 ST：${new Date(item.last_sent_to_st * 1000).toLocaleString()}`;
      }
      return "发送到 ST（对话补全预设，同名将直接覆盖 ST 中现有预设）";
    },

    applyPresetSentState(detail) {
      if (!detail?.id) return;
      const sentAt = Number(detail.last_sent_to_st || 0);
      const patchItems = (items) => {
        if (!Array.isArray(items)) return items;
        let changed = false;
        const nextItems = items.map((item) => {
          const targetId = this.getPresetActionTargetId(item);
          if (
            !item ||
            (item.id !== detail.id && targetId !== detail.id)
          ) {
            return item;
          }
          changed = true;
          return {
            ...item,
            last_sent_to_st: sentAt,
          };
        });
        return changed ? nextItems : items;
      };

      this.items = patchItems(this.items);
      this.$store.global.presetList = patchItems(this.$store.global.presetList);
    },

    getPresetItemById(id) {
      return (this.items || []).find((item) => item.id === id) || null;
    },

    getPresetOpenId(item) {
      if (!item) return "";
      if (item.entry_type === "family" && item.default_version_id) {
        return item.default_version_id;
      }
      return item.id || "";
    },

    getPresetActionTargetId(item) {
      return this.getPresetOpenId(item);
    },

    selectedPresetItems() {
      return this.selectedIds
        .map((id) => this.getPresetItemById(id))
        .filter(Boolean);
    },

    canSelectPresetItem(item) {
      return !!item;
    },

    isPresetMovable(item) {
      return !!item && (item.source_type || item.type) === "global";
    },

    canDeletePresetSelection() {
      const items = this.selectedPresetItems();
      return (
        items.length > 0 &&
        items.every((item) => this.canSelectPresetItem(item))
      );
    },

    canMovePresetSelection() {
      const items = this.selectedPresetItems();
      return (
        items.length > 0 && items.every((item) => this.isPresetMovable(item))
      );
    },

    canMergePresetSelection() {
      const items = this.selectedPresetItems();
      if (items.length < 2) return false;
      const scopeKeys = new Set(items.map((item) => String(item.root_scope_key || "")));
      return (
        scopeKeys.size === 1 &&
        items.every((item) => String(item.preset_kind || "").trim() === "openai")
      );
    },

    openPresetVersionMergeModal() {
      if (!this.canMergePresetSelection()) return;
      const items = this.selectedPresetItems();
      if (items.length < 2) return;
      window.dispatchEvent(
        new CustomEvent("open-preset-version-merge", {
          detail: { items },
        }),
      );
    },

    toggleSelection(item) {
      if (!this.canSelectPresetItem(item)) return;

      let ids = [...this.selectedIds];
      if (ids.includes(item.id)) {
        ids = ids.filter((id) => id !== item.id);
      } else {
        ids.push(item.id);
        this.lastSelectedId = item.id;
      }
      this.selectedIds = ids;
    },

    handlePresetClick(e, item) {
      if (e.ctrlKey || e.metaKey) {
        this.toggleSelection(item);
        return;
      }

      if (e.shiftKey && this.lastSelectedId) {
        const selectableItems = this.items || [];
        const startIdx = selectableItems.findIndex(
          (currentItem) => currentItem.id === this.lastSelectedId,
        );
        const endIdx = selectableItems.findIndex(
          (currentItem) => currentItem.id === item.id,
        );

        if (startIdx !== -1 && endIdx !== -1) {
          const min = Math.min(startIdx, endIdx);
          const max = Math.max(startIdx, endIdx);
          const rangeIds = selectableItems
            .slice(min, max + 1)
            .map((currentItem) => currentItem.id);
          const currentSet = new Set(this.selectedIds);
          rangeIds.forEach((id) => currentSet.add(id));
          this.selectedIds = Array.from(currentSet);
        }
        return;
      }

      this.openPresetDetail(item);
    },

    dragStart(e, item) {
      if (!this.canSelectPresetItem(item)) {
        e.preventDefault();
        return;
      }

      const ids = this.selectedIds.includes(item.id)
        ? [...this.selectedIds]
        : Array.of(item.id, ...this.selectedIds);

      const selectedItems = ids
        .map((id) => this.getPresetItemById(id))
        .filter(Boolean);

      if (
        selectedItems.length === 0 ||
        !selectedItems.every((currentItem) => this.isPresetMovable(currentItem))
      ) {
        e.preventDefault();
        alert("当前选中的预设包含资源绑定项，不能移动分类");
        return;
      }

      if (!this.selectedIds.includes(item.id)) {
        this.selectedIds = ids;
      }

      this.draggedCards = ids;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("application/x-st-preset", JSON.stringify(ids));
      e.dataTransfer.setData("text/plain", item.id);

      const cardElement = e.target.closest("[data-preset-id]");
      if (cardElement) {
        requestAnimationFrame(() => {
          cardElement.classList.add("drag-source");
        });

        const cleanup = () => {
          cardElement.classList.remove("drag-source");
          window.dispatchEvent(new CustomEvent("global-drag-end"));
        };

        e.target.addEventListener("dragend", cleanup, { once: true });
      }
    },

    locatePresetOwnerCard(item) {
      const owner_card_id = this.getPresetOwnerId(item);
      if (!owner_card_id) return;
      window.dispatchEvent(
        new CustomEvent("jump-to-card-wi", { detail: owner_card_id }),
      );
    },

    init() {
      this.initMarqueeSelection();

      // 监听模式切换
      this.$watch("$store.global.currentMode", (val) => {
        if (val === "presets") {
          this.fetchItems();
        }
      });

      // 监听侧边栏筛选变化
      this.$watch("$store.global.presetFilterType", () => {
        if (this.$store.global.currentMode === "presets") {
          this.fetchItems();
        }
      });

      this.$watch("$store.global.presetFilterCategory", () => {
        if (this.$store.global.currentMode === "presets") {
          this.fetchItems();
        }
      });

      // 监听搜索关键词变化
      this.$watch("$store.global.presetSearch", () => {
        if (this.$store.global.currentMode === "presets") {
          this.fetchItems();
        }
      });

      window.addEventListener("refresh-preset-list", () => {
        if (this.$store.global.currentMode === "presets") {
          this.fetchItems();
        }
      });

      window.addEventListener("delete-selected-presets", () => {
        this.deleteSelectedPresets();
      });

      window.addEventListener("move-selected-presets", (e) => {
        this.moveSelectedPresets(e.detail?.target_category || "");
      });

      window.addEventListener("merge-selected-presets", () => {
        this.openPresetVersionMergeModal();
      });

      window.addEventListener("preset-sent-to-st", (e) => {
        this.applyPresetSentState(e.detail || {});
      });

      window.addEventListener("preset-send-to-st-pending", (e) => {
        setPresetSendToStPending(e.detail?.id, true);
        this.setPresetSendingState(e.detail?.id, true);
      });

      window.addEventListener("preset-send-to-st-finished", (e) => {
        setPresetSendToStPending(e.detail?.id, false);
        this.setPresetSendingState(e.detail?.id, false);
      });

      // 初始加载
      if (this.$store.global.currentMode === "presets") {
        this.fetchItems();
      }

      // presetDetailReader.js 会处理 open-preset-reader 事件
      // 本组件只负责触发事件，不监听

      // 提供给移动端/外部（如 Sidebar 导入按钮）复用的全局上传入口
      window.stUploadPresetFiles = (files) => {
        this._uploadPresetsFiles(files);
      };
    },

    async _uploadPresetsFiles(files) {
      const list = files || [];
      if (!list || list.length === 0) return;

      const buildFormData = (allowGlobalFallback = false) => {
        const formData = new FormData();
        for (let i = 0; i < list.length; i++) {
          formData.append("files", list[i]);
        }
        formData.append("source_context", this.filterType);
        formData.append(
          "target_category",
          this.isGlobalCategoryContext() ? this.filterCategory : "",
        );
        if (allowGlobalFallback) {
          formData.append("allow_global_fallback", "true");
        }
        return formData;
      };

      this.isLoading = true;
      try {
        const resp = await fetch("/api/presets/upload", {
          method: "POST",
          body: buildFormData(),
        });
        let res = await resp.json();
        if (res?.requires_global_fallback_confirmation) {
          if (
            !confirm("当前不在全局分类上下文。确认继续上传到全局根目录吗？")
          ) {
            this.isLoading = false;
            return;
          }
          const retryResp = await fetch("/api/presets/upload", {
            method: "POST",
            body: buildFormData(true),
          });
          res = await retryResp.json();
        }
        if (res.success) {
          this.$store.global.showToast(res.msg);
          this.fetchItems();
        } else {
          this.$store.global.showToast(res.msg, "error");
        }
      } catch (e) {
        this.$store.global.showToast("上传失败", "error");
      } finally {
        this.isLoading = false;
      }
    },

    fetchItems() {
      this.isLoading = true;
      const filterType = this.$store.global.presetFilterType || "all";
      const search = this.$store.global.presetSearch || "";
      const category = this.$store.global.presetFilterCategory || "";

      let url = `/api/presets/list?filter_type=${filterType}`;
      if (search) {
        url += `&search=${encodeURIComponent(search)}`;
      }
      if (category) {
        url += `&category=${encodeURIComponent(category)}`;
      }

      fetch(url)
        .then((res) => res.json())
        .then((res) => {
          this.items = res.items || [];
          this.$store.global.presetList = this.items;
          this.$store.global.presetAllFolders = res.all_folders || [];
          this.$store.global.presetCategoryCounts = res.category_counts || {};
          this.$store.global.presetFolderCapabilities =
            res.folder_capabilities || {};
          this.isLoading = false;
        })
        .catch((err) => {
          console.error("Failed to fetch presets:", err);
          this.isLoading = false;
        });
    },

    async handleDrop(e) {
      this.dragOver = false;
      const files = e.dataTransfer.files;
      if (!files.length) return;
      this._uploadPresetsFiles(files);
    },

    getCategoryModeHint(item) {
      if (item?.category_mode === "override")
        return "已更新管理器分类，未移动实际文件";
      if (item?.category_mode === "inherited") return "跟随角色卡";
      return "";
    },

    getPresetSourceHint(item) {
      if ((item?.source_type || item?.type) === "global") {
        return "GLOBAL / 物理分类";
      }
      if (item?.category_mode === "override") {
        return "RESOURCE / 已覆盖管理器分类";
      }
      return "RESOURCE / 跟随角色卡";
    },

    // 新三栏阅览界面方法
    openPresetDetail(item) {
      const openId = this.getPresetOpenId(item);
      if (!openId) return;

      // 触发事件让 presetDetailReader.js 处理详情显示
      window.dispatchEvent(
        new CustomEvent("open-preset-reader", {
          detail: {
            ...item,
            id: openId,
          },
        }),
      );
    },

    async exportPresetItem(item, event = null) {
      event?.stopPropagation?.();
      const targetId = this.getPresetActionTargetId(item);
      if (!targetId) return;

      try {
        await downloadFileFromApi({
          url: "/api/presets/export",
          body: {
            id: targetId,
          },
          defaultFilename: item.filename || `${item.name || "preset"}.json`,
          showToast: this.$store?.global?.showToast,
        });
      } catch (err) {
        this.$store.global.showToast(err.message || "导出失败", "error");
      }
    },

    async sendPresetToST(item, event = null) {
      event?.stopPropagation?.();
      const targetId = this.getPresetActionTargetId(item);
      if (!targetId) return;
      if (!this.canSendPresetToST(item)) return;
      if (isPresetSendToStPending(targetId)) return;

      const key = String(targetId);
      setPresetSendToStPending(key, true);
      window.dispatchEvent(new CustomEvent("preset-send-to-st-pending", {
        detail: { id: key, sending: true },
      }));

      try {
        const res = await sendPresetToSillyTavern({ id: targetId });
        if (res?.success) {
          const sentDetail = {
            id: key,
            last_sent_to_st: Number(res.last_sent_to_st || Date.now() / 1000),
          };
          this.applyPresetSentState(sentDetail);
          window.dispatchEvent(new CustomEvent("preset-sent-to-st", {
            detail: sentDetail,
          }));
          this.$store.global.showToast("已发送到 ST", 1800, "send");
        } else {
          this.$store.global.showToast(res?.msg || "发送失败", 2600, "close");
        }
      } catch (error) {
        this.$store.global.showToast(error?.message || "发送失败", 2600, "close");
      } finally {
        setPresetSendToStPending(key, false);
        window.dispatchEvent(new CustomEvent("preset-send-to-st-finished", {
          detail: { id: key, sending: false },
        }));
      }
    },

    async deletePreset(item, e) {
      e.stopPropagation();
      const targetId = this.getPresetActionTargetId(item);
      if (!targetId) return;

      if (!confirm(`确定要删除预设 "${item.name}" 吗？`)) {
        return;
      }

      try {
        const resp = await fetch("/api/presets/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: targetId }),
        });
        const res = await resp.json();

        if (res.success) {
          this.$store.global.showToast(res.msg);
          this.fetchItems();
        } else {
          this.$store.global.showToast(res.msg, "error");
        }
      } catch (e) {
        this.$store.global.showToast("删除失败", "error");
      }
    },

    async deleteSelectedPresets() {
      if (!this.canDeletePresetSelection()) return;

      const items = this.selectedPresetItems();
      const count = items.length;
      if (!confirm(`确定要删除选中的 ${count} 个预设吗？`)) return;

      for (const item of items) {
        const targetId = this.getPresetActionTargetId(item);
        if (!targetId) {
          this.$store.global.showToast("删除失败", "error");
          return;
        }
        const resp = await fetch("/api/presets/delete", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id: targetId }),
        });
        const res = await resp.json();
        if (!res?.success) {
          this.$store.global.showToast(res?.msg || "删除失败", "error");
          return;
        }
      }

      this.$store.global.showToast(`已删除 ${count} 个预设`, 3000, "trash");
      this.selectedIds = [];
      this.fetchItems();
    },

    async moveSelectedPresets(targetCategory = this.filterCategory || "") {
      if (!this.canMovePresetSelection()) {
        alert("当前选中的预设包含资源绑定项，不能移动分类");
        return;
      }

      const items = this.selectedPresetItems();
      const count = items.length;
      const label = targetCategory || "根目录";
      if (!confirm(`移动 ${count} 个预设到 "${label}"?`)) return;

      for (const item of items) {
        const targetId = this.getPresetActionTargetId(item);
        if (!targetId) {
          alert("移动失败");
          return;
        }
        const resp = await fetch("/api/presets/category/move", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            id: targetId,
            source_type: item.source_type || item.type,
            file_path: item.path,
            target_category: targetCategory,
          }),
        });
        const res = await resp.json();
        if (!res?.success) {
          alert(res?.msg || "移动失败");
          return;
        }
      }

      this.$store.global.showToast(`已移动 ${count} 个预设`, 3000, "check");
      this.selectedIds = [];
      this.fetchItems();
    },

    formatDate(ts) {
      if (!ts) return "-";
      return new Date(ts * 1000).toLocaleString();
    },
  };
}
