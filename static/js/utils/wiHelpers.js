/**
 * static/js/utils/wiHelpers.js
 * 世界书通用操作逻辑 (Mixin)
 */

import {
  createSnapshot as apiCreateSnapshot,
  openPath,
} from "../api/system.js";
import { getCleanedV3Data, toStV3Worldbook } from "./data.js";

export const wiHelpers = {
  // 获取 WI 数组引用 (兼容 V2/V3)
  getWIArrayRef() {
    // 确保 character_book 对象存在
    if (!this.editingData.character_book) {
      this.editingData.character_book = { entries: [], name: "World Info" };
    }

    let cb = this.editingData.character_book;

    // 兼容 V2 数组格式 -> 转为对象
    if (Array.isArray(cb)) {
      const oldEntries = cb;
      this.editingData.character_book = {
        entries: oldEntries,
        name: this.editingData.char_name || "World Info",
      };
      cb = this.editingData.character_book;
    }

    // 兼容 V3 对象格式 (entries 可能是 dict) -> 转为数组
    if (cb.entries && !Array.isArray(cb.entries)) {
      cb.entries = Object.values(cb.entries);
    }
    if (!cb.entries) cb.entries = [];
    // 过滤掉 null 或 undefined 的条目，防止崩坏
    cb.entries = cb.entries.filter(
      (e) => e !== null && e !== undefined && typeof e === "object",
    );
    return cb.entries;
  },

  getWorldInfoCount() {
    return this.getWIArrayRef().length;
  },

  getWiStatusClass(entry) {
    if (!entry.enabled) return "wi-status-disabled";
    if (entry.constant) return "wi-status-constant";
    if (entry.vectorized) return "wi-status-vector";
    return "wi-status-normal";
  },

  // 基础 CRUD
  addWiEntry() {
    const arr = this.getWIArrayRef();
    const entryUid =
      typeof this._generateEntryUid === "function"
        ? this._generateEntryUid()
        : `wi-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
    // 创建新条目（不预先设置 id，稍后统一分配）
    arr.push({
      st_manager_uid: entryUid,
      comment: "新条目",
      content: "",
      keys: ["关键词"],
      secondary_keys: [],
      enabled: true,
      constant: false,
      vectorized: false,
      insertion_order: 100,
      position: 0,
      role: 0,
      depth: 4,
      selective: true,
      selectiveLogic: 0,
      preventRecursion: false,
      excludeRecursion: false,
      delayUntilRecursion: 0,
      ignoreBudget: false,
      matchPersonaDescription: false,
      matchCharacterDescription: false,
      matchCharacterPersonality: false,
      matchCharacterDepthPrompt: false,
      matchScenario: false,
      matchCreatorNotes: false,
      group: "",
      groupOverride: false,
      groupWeight: 100,
      useGroupScoring: null,
      triggers: [],
      automationId: "",
      sticky: null,
      cooldown: null,
      delay: null,
      probability: 100,
      useProbability: true,
    });

    // 重新分配 id，确保 id 等于索引号
    arr.forEach((entry, idx) => {
      if (entry) entry.id = idx;
    });

    // 滚动并选中
    this.$nextTick(() => {
      const container = document.querySelector(".wi-list-container");
      if (container) container.scrollTop = container.scrollHeight;
      this.currentWiIndex = arr.length - 1;
      this.isEditingClipboard = false;
    });
  },

  removeWiEntry(index) {
    if (index === undefined || index === null || index < 0) return;
    if (!confirm("确定要删除这条世界书内容吗？")) return;

    const arr = this.getWIArrayRef();
    arr.splice(index, 1);

    // 防止溢出
    if (this.currentWiIndex >= arr.length) {
      this.currentWiIndex = Math.max(0, arr.length - 1);
    }

    // 重新分配 id，确保 id 等于索引号
    arr.forEach((entry, idx) => {
      if (entry) entry.id = idx;
    });
  },

  moveWiEntry(index, direction) {
    const arr = this.getWIArrayRef();
    const newIndex = index + direction;
    if (newIndex < 0 || newIndex >= arr.length) return;

    const temp = arr[index];
    arr[index] = arr[newIndex];
    arr[newIndex] = temp;

    // 跟随选中
    if (this.currentWiIndex === index) this.currentWiIndex = newIndex;

    // 重新分配 id，确保 id 等于索引号
    arr.forEach((entry, idx) => {
      if (entry) entry.id = idx;
    });
  },

  createSnapshot(forceType = null) {
    let type, targetId, path, content, name;

    // 场景 A: 角色卡详情页 (detailModal)
    if (this.activeCard && this.activeCard.id && !this.showFullScreenWI) {
      type = "card";
      targetId = this.activeCard.id;
      path = "";
      name = this.activeCard.char_name || this.activeCard.filename;
      // 实时获取编辑器中的数据
      if (this.editingData) {
        content = getCleanedV3Data(this.editingData);
      }
    }
    // 场景 B: 世界书编辑器/弹窗 (wiEditor, wiDetailPopup)
    else {
      const contextItem = this.editingWiFile || this.activeWiDetail;
      if (!contextItem) {
        console.error("createSnapshot: No context item found.");
        return;
      }
      type = contextItem.type === "embedded" ? "embedded" : "lorebook";
      // 如果是 embedded，快照目标是宿主卡片
      targetId = type === "embedded" ? contextItem.card_id : contextItem.id;
      path = contextItem.path || "";
      name = contextItem.name || "World Info";

      // 如果当前处于阅览模式(wiDetailPopup) 且数据被截断(isTruncated)
      // 则禁止从前端构建 content，强制 content=null，让后端执行文件级复制
      if (this.isTruncated || this.isContentTruncated) {
        console.log(
          "[Snapshot] Detected truncation, forcing file-level backup.",
        );
        content = null;
      } else {
        // 1. 如果在编辑器中，且有 _getAutoSavePayload 方法
        if (typeof this._getAutoSavePayload === "function") {
          const payload = this._getAutoSavePayload();
          content = payload.content;
        }
        // 2. 如果在阅览室 (DetailPopup) 中，且已经加载了 wiData
        else if (this.wiData) {
          content = {
            ...this.wiData,
            entries: this.wiEntries,
          };
        }
      }
    }

    if (!targetId) {
      alert("无法确定快照目标 ID");
      return;
    }

    // 配置项
    const isSilent = this.$store.global.settingsForm.silent_snapshot;
    const label = ""; // 默认无标签

    if (!isSilent) {
      if (!confirm(`确定为 "${name}" 创建备份快照吗？`)) return;
      this.$store.global.isLoading = true;
    }

    apiCreateSnapshot({
      id: targetId,
      type: type === "card" || type === "embedded" ? "card" : "lorebook",
      file_path: path,
      label: label,
      content: content, // 传递实时内容
      compact: type === "lorebook", // 只有纯世界书才压缩 JSON，卡片通常不压缩
    })
      .then((res) => {
        if (!isSilent) this.$store.global.isLoading = false;
        if (res.success) {
          this.$store.global.showToast("📸 快照已保存", 2000);
        } else {
          alert("备份失败: " + res.msg);
        }
      })
      .catch((e) => {
        if (!isSilent) this.$store.global.isLoading = false;
        alert("请求错误: " + e);
      });
  },

  // 关键快照 (带标签)
  createKeySnapshot(forceType) {
    const label = prompt("请输入关键节点名称 (例如: 'v1.0'):");
    if (label === null) return;

    let type, targetId, path, content;

    if (this.activeCard && this.activeCard.id && !this.showFullScreenWI) {
      type = "card";
      targetId = this.activeCard.id;
      path = "";
      if (this.editingData) content = getCleanedV3Data(this.editingData);
    } else {
      const contextItem = this.editingWiFile || this.activeWiDetail;
      if (!contextItem) return;
      type = contextItem.type === "embedded" ? "embedded" : "lorebook";
      targetId = type === "embedded" ? contextItem.card_id : contextItem.id;
      path = contextItem.path || "";
      if (this.isTruncated || this.isContentTruncated) {
        content = null;
      } else if (
        this.showFullScreenWI &&
        typeof this._getAutoSavePayload === "function"
      ) {
        content = this._getAutoSavePayload().content;
      } else if (this.wiData) {
        content = { ...this.wiData, entries: this.wiEntries };
      }
    }

    this.$store.global.isLoading = true;
    apiCreateSnapshot({
      id: targetId,
      type: type === "card" || type === "embedded" ? "card" : "lorebook",
      file_path: path,
      label: label,
      content: content,
      compact: type === "lorebook",
    })
      .then((res) => {
        this.$store.global.isLoading = false;
        if (res.success) this.$store.global.showToast("📸 关键快照已保存");
        else alert(res.msg);
      })
      .catch((e) => {
        this.$store.global.isLoading = false;
        alert(e);
      });
  },

  // 通用打开备份目录
  openBackupFolder() {
    let isEmbedded = false;
    let isCard = false;
    let targetName = "";

    // 辅助：提取文件名
    const extractName = (str) => {
      if (!str) return "";
      return str
        .split("/")
        .pop()
        .replace(/\.[^/.]+$/, "")
        .replace(/[\\/:*?"<>|]/g, "_")
        .trim();
    };

    if (this.activeCard && this.activeCard.id && !this.showFullScreenWI) {
      // 角色卡模式
      isCard = true;
      targetName = extractName(this.activeCard.filename);
    } else {
      // 世界书模式
      const item = this.editingWiFile || this.activeWiDetail;
      if (!item) return;

      if (item.type === "embedded") {
        isEmbedded = true;
        // 内嵌：从 ID (embedded::card/path) 中提取
        targetName = extractName(item.card_id);
      } else {
        targetName = extractName(item.path || item.name);
      }
    }

    let base =
      isCard || isEmbedded
        ? `data/system/backups/cards`
        : `data/system/backups/lorebooks`;
    let specific = targetName ? `${base}/${targetName}` : base;

    openPath({ path: specific, relative_to_base: true }).then((res) => {
      if (!res.success) {
        // 如果特定目录不存在，尝试打开上一级
        openPath({ path: base, relative_to_base: true });
      }
    });
  },
  // 统一的时光机打开函数
  handleOpenRollback(contextItem, currentData = null) {
    let type, targetId, targetPath;

    // 1. 判断上下文来源
    if (contextItem) {
      if (contextItem.type === "embedded") {
        // 情况 1 & 3: 嵌入式 (Embedded)
        // 备份存储在角色卡 (card) 目录下，ID 为宿主角色 ID
        type = "card";
        targetId = contextItem.card_id;
        targetPath = "";
      } else {
        // 情况 2: 独立文件 (Global / Resource)
        type = "lorebook";
        targetId = contextItem.id;
        // 优先使用 file_path (wiEditor), 其次 path (wiList item)
        targetPath = contextItem.file_path || contextItem.path || "";
      }
    } else {
      // 兜底：如果没有上下文对象，尝试直接使用当前编辑数据的 ID
      console.warn("Rollback: Missing context item, inferring from data...");
      type = "lorebook";
      targetId = currentData ? currentData.id : null;
      targetPath = "";
    }

    if (!targetId) {
      alert("无法确定目标 ID，无法打开时光机。");
      return;
    }

    // 2. 触发全局事件
    window.dispatchEvent(
      new CustomEvent("open-rollback", {
        detail: {
          type: type,
          id: targetId,
          path: targetPath,
          // 传入当前数据用于"Current"版本实时Diff
          editingData: currentData,
          // 传入文件上下文用于 rollbackModal 内部判断
          editingWiFile: contextItem,
        },
      }),
    );
  },
  // 1. 公共导出函数
  downloadWorldInfoJson(bookData, fallbackName = "World Info") {
    const finalExportData = toStV3Worldbook(
      bookData,
      bookData.name || fallbackName,
    );
    const filename =
      (finalExportData.name || fallbackName).replace(/[\\/:*?"<>|]/g, "_") +
      ".json";

    try {
      const jsonStr = JSON.stringify(finalExportData); // 紧凑格式
      const blob = new Blob([jsonStr], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      alert("导出失败: " + e.message);
    }
  },

  // 2. 公共导入解析逻辑
  processWiImportFile(file, existingCount, onSuccess, onCancel) {
    if (!file) {
      if (onCancel) onCancel();
      return;
    }

    // 1. 覆盖警告
    if (existingCount > 0) {
      if (!confirm("⚠️ 警告：导入将【覆盖】当前世界书内容。\n是否继续？")) {
        if (onCancel) onCancel();
        return;
      }
    }

    const fileNameNoExt = file.name.replace(/\.[^/.]+$/, "");
    const reader = new FileReader();

    reader.onload = (event) => {
      try {
        const json = JSON.parse(event.target.result);
        let rawEntries = [];
        let newName = fileNameNoExt;

        // 2. 格式识别逻辑 (兼容 V2/V3/导出格式)
        if (Array.isArray(json)) {
          // 纯数组 (V2)
          rawEntries = json;
        } else if (json && (json.entries || json.data)) {
          // 对象结构 (V3 或 包装器)
          const dataRoot = json.entries ? json : json.data || {}; // 兼容 data.entries 结构

          if (Array.isArray(dataRoot.entries)) {
            rawEntries = dataRoot.entries;
          } else if (
            typeof dataRoot.entries === "object" &&
            dataRoot.entries !== null
          ) {
            rawEntries = Object.values(dataRoot.entries);
          }

          // 尝试获取内部名称
          const internalName = json.name || (json.data && json.data.name);
          if (
            internalName &&
            typeof internalName === "string" &&
            internalName.trim() !== ""
          ) {
            newName = internalName;
          }
        }

        if (!rawEntries || (rawEntries.length === 0 && !json.entries)) {
          throw new Error("未能识别有效的世界书 JSON 结构");
        }

        // 3. 数据清洗与规范化
        const normalizedEntries = rawEntries.map((entry) => {
          // 定义核心字段的标准值
          const coreData = {
            // ID: 优先用原有的，没有则生成
            id: entry.id || entry.uid || Math.floor(Math.random() * 1000000),
            st_manager_uid:
              entry.st_manager_uid ||
              `wi-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`,

            // 键名映射 (ST use 'key', we use 'keys')
            keys: Array.isArray(entry.keys)
              ? entry.keys
              : Array.isArray(entry.key)
                ? entry.key
                : [],
            secondary_keys: Array.isArray(entry.secondary_keys)
              ? entry.secondary_keys
              : Array.isArray(entry.keysecondary)
                ? entry.keysecondary
                : [],

            // 启用状态 (ST use 'disable', we use 'enabled')
            enabled:
              entry.enabled !== undefined
                ? !!entry.enabled
                : entry.disable === undefined
                  ? true
                  : !entry.disable,

            // 数值类型安全
            insertion_order: Number(
              entry.insertion_order || entry.order || 100,
            ),
            position: Number(entry.position !== undefined ? entry.position : 1), // 默认 Character
            depth: Number(entry.depth !== undefined ? entry.depth : 4),
            probability: Number(
              entry.probability !== undefined ? entry.probability : 100,
            ),
            selectiveLogic: Number(entry.selectiveLogic || 0),
            role: entry.role !== undefined ? Number(entry.role) : null,

            // 布尔值类型安全
            constant: !!entry.constant,
            vectorized: !!entry.vectorized,
            selective: entry.selective !== undefined ? !!entry.selective : true,
            useProbability:
              entry.useProbability !== undefined
                ? !!entry.useProbability
                : true,
            preventRecursion: !!entry.preventRecursion,
            excludeRecursion: !!entry.excludeRecursion,
            matchWholeWords: !!entry.matchWholeWords,
            use_regex: !!entry.use_regex,
            caseSensitive: !!entry.caseSensitive,

            // 文本内容
            content: String(entry.content || ""),
            comment: String(entry.comment || ""),
          };

          // 【关键】先展开原始 entry 保留所有未知字段 (如 extensions, displayIndex等)
          // 后展开 coreData 覆盖并修正核心逻辑字段
          return { ...entry, ...coreData };
        });

        // 4. 按权重排序 (可选)
        normalizedEntries.sort((a, b) => b.insertion_order - a.insertion_order);

        // 成功回调
        if (onSuccess) {
          onSuccess({
            name: newName,
            entries: normalizedEntries,
          });
        }
      } catch (err) {
        console.error("[WI Import Error]", err);
        alert("❌ 导入失败: " + err.message);
        if (onCancel) onCancel();
      }
    };

    reader.onerror = () => {
      alert("❌ 读取文件出错");
      if (onCancel) onCancel();
    };

    reader.readAsText(file);
  },
};
