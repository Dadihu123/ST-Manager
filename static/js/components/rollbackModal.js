/**
 * static/js/components/rollbackModal.js
 * 时光机组件：版本回滚与差异对比
 */

import {
  listBackups,
  restoreBackup,
  readFileContent,
  normalizeCardData,
  openPath,
} from "../api/system.js";

import { getCardMetadata } from "../api/card.js";
import { generateSideBySideDiff } from "../utils/diff.js";
import {
  getCleanedV3Data,
  normalizeWiEntry,
  toStV3Worldbook,
} from "../utils/data.js";

export default function rollbackModal() {
  return {
    // === 本地状态 ===
    showRollbackModal: false,
    isLoading: false,
    isDiffLoading: false,

    backupList: [], // 历史备份列表
    rollbackVersions: [], // 包含 Current 的完整列表

    // 目标信息
    rollbackTargetType: "", // 'card' | 'lorebook' | 'preset'
    rollbackTargetId: "",
    rollbackTargetPath: "",
    rollbackLiveContent: null, // 当前编辑器中的实时内容
    rollbackEmbeddedWiContext: false,
    diffRenderMode: "raw", // 'raw' | 'wi_entries' | 'fields'

    // Diff 状态
    diffSelection: { left: null, right: null },
    diffData: { left: "", right: "", fields: "", currentObj: null },
    diffSummary: {
      added: 0,
      removed: 0,
      changed: 0,
      same: 0,
      total: 0,
      categories: [],
    },

    init() {
      // 监听打开事件 (由 detailModal 或 wiEditor 触发)
      window.addEventListener("open-rollback", (e) => {
        const { type, id, path, editingData, editingWiFile } = e.detail;
        this.openRollback(type, id, path, editingData, editingWiFile);
      });
    },

    get rollbackTargetTypeLabel() {
      return (
        {
          preset: "预设",
          card: "角色卡",
          lorebook: "世界书",
        }[this.rollbackTargetType] || "内容"
      );
    },

    get diffModeLabel() {
      if (this._isLorebookComparison()) {
        return this.diffRenderMode === "raw" ? "原始 JSON" : "按条目对比";
      }
      if (this.rollbackTargetType === "card") {
        return this.diffRenderMode === "raw" ? "原始 JSON" : "按字段对比";
      }
      return "原始 JSON";
    },

    get diffModeDescription() {
      if (this._isLorebookComparison()) {
        return this.diffRenderMode === "raw"
          ? "显示快照文件的原始 JSON 行级差异。"
          : "按稳定条目标识匹配，只统计真实的新增、删除和字段修改。";
      }
      if (this.rollbackTargetType === "card" && this.diffRenderMode !== "raw") {
        return "按角色卡业务字段汇总差异，展开即可查看旧值与新值。";
      }
      return "显示快照文件的原始 JSON 行级差异。";
    },

    get diffSummaryItems() {
      return [
        { key: "added", label: "新增", value: this.diffSummary.added, tone: "is-added" },
        { key: "removed", label: "删除", value: this.diffSummary.removed, tone: "is-removed" },
        { key: "changed", label: "修改", value: this.diffSummary.changed, tone: "is-changed" },
        { key: "same", label: "未变化", value: this.diffSummary.same, tone: "is-same" },
      ];
    },

    getDiffStatusLabel(status) {
      return { added: "新增", removed: "删除", changed: "修改", same: "未变化" }[
        status
      ] || "未变化";
    },

    getVersionLabel(version) {
      if (!version) return "未选择";
      if (version.is_current) return "当前编辑内容";
      return version.label && version.is_key
        ? version.label
        : new Date(Number(version.mtime || 0) * 1000).toLocaleString();
    },

    getVersionMeta(version) {
      if (!version) return "";
      if (version.is_current) return "当前编辑器状态";
      const size = Number(version.size || 0);
      const sizeLabel = size ? `${(size / 1024).toFixed(1)} KB` : "大小未知";
      if (version.is_auto) return `自动快照 · ${sizeLabel}`;
      if (version.is_key) return `关键快照 · ${sizeLabel}`;
      return `手动快照 · ${sizeLabel}`;
    },

    // === 打开时光机 ===
    openRollback(type, targetId, targetPath, editingData, editingWiFile) {
      this.rollbackTargetType = type;
      this.rollbackTargetId = targetId;
      this.rollbackTargetPath = targetPath;
      this.rollbackLiveContent = null;
      this.rollbackEmbeddedWiContext = !!(
        editingWiFile && editingWiFile.type === "embedded"
      );
      this.diffRenderMode =
        type === "lorebook" || this.rollbackEmbeddedWiContext
          ? "wi_entries"
          : type === "card"
            ? "fields"
            : "raw";

      // 1. 捕获实时内容 (Live Content)
      if (type === "card") {
        // 内嵌世界书上下文：只比较世界书
        if (
          this.rollbackEmbeddedWiContext &&
          editingData &&
          editingData.character_book
        ) {
          const name = editingData.character_book.name || "World Info";
          this.rollbackLiveContent = toStV3Worldbook(
            editingData.character_book,
            name,
          );
        } else if (editingData && editingData.id === targetId) {
          // 如果传入了 editingData 且 ID 匹配，说明正在编辑
          this.rollbackLiveContent = getCleanedV3Data(editingData);
        }
      } else if (type === "lorebook") {
        // 如果正在编辑该世界书
        let isEditingThis = false;
        if (editingWiFile) {
          if (editingWiFile.id === targetId) isEditingThis = true;
        }

        if (isEditingThis && editingData && editingData.character_book) {
          const name = editingData.character_book.name || "World Info";
          this.rollbackLiveContent = toStV3Worldbook(
            editingData.character_book,
            name,
          );
        }
      }

      this.isLoading = true;
      listBackups({ id: targetId, type: type, file_path: targetPath })
        .then(async (res) => {
          if (res.success) {
            // 构造版本列表
            const currentVer = {
              filename: "Current (当前编辑器版本)",
              path: null, // null 表示需要读取 Live 或 Disk Current
              mtime: new Date().getTime() / 1000,
              size: 0,
              is_current: true,
              label: "LIVE",
            };

            const pruneResult = await this._pruneBackupsRepresentedByCurrent(
              currentVer,
              res.backups || [],
            );
            this.backupList = pruneResult.backups;
            this.rollbackVersions = [currentVer, ...this.backupList];

            // 默认选中：左=最近备份，右=当前
            this.diffSelection = {
              left: this.backupList.length > 0 ? this.backupList[0] : null,
              right: currentVer,
            };

            this.showRollbackModal = true;

            if (pruneResult.hidden > 0 && this.$store?.global?.showToast) {
              this.$store.global.showToast(
                `已折叠 ${pruneResult.hidden} 个与 Current 重合的最新快照`,
                2000,
              );
            }

            // 立即加载 Diff
            this.updateDiffView();
          } else {
            alert(res.msg);
          }
        })
        .catch((err) => {
          alert("加载备份失败: " + err);
        })
        .finally(() => {
          this.isLoading = false;
        });
    },

    // === Diff 逻辑 ===

    setDiffSide(side, version) {
      this.diffSelection[side] = version;
      // 手动切换时不自动跳转，尊重用户选择
      this.updateDiffView(false);
    },

    setDiffRenderMode(mode) {
      const allowedModes = new Set(["raw", "wi_entries", "fields"]);
      if (!allowedModes.has(mode)) return;
      this.diffRenderMode = mode;
      this.updateDiffView(false);
    },

    _isLorebookComparison() {
      return (
        this.rollbackTargetType === "lorebook" ||
        this.rollbackEmbeddedWiContext ||
        String(this.rollbackTargetId || "").startsWith("embedded::")
      );
    },

    _isEmbeddedWorldbookTarget() {
      return (
        this.rollbackEmbeddedWiContext ||
        String(this.rollbackTargetId || "").startsWith("embedded::")
      );
    },

    _escapeHtml(text) {
      return String(text ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    },

    _stableStringify(value) {
      if (Array.isArray(value)) {
        return `[${value.map((v) => this._stableStringify(v)).join(",")}]`;
      }
      if (value && typeof value === "object") {
        const keys = Object.keys(value).sort();
        return `{${keys.map((k) => `${JSON.stringify(k)}:${this._stableStringify(value[k])}`).join(",")}}`;
      }
      return JSON.stringify(value);
    },

    _getRawCategoryLabel(key) {
      return (
        {
          prompts: "提示词内容",
          prompt_order: "提示词顺序",
          extensions: "扩展配置",
          name: "预设名称",
          x_st_manager: "管理元数据",
        }[key] || key
      );
    },

    _summarizeRawDiff(leftData, rightData) {
      const left = leftData && typeof leftData === "object" ? leftData : {};
      const right = rightData && typeof rightData === "object" ? rightData : {};
      const keys = new Set([...Object.keys(left), ...Object.keys(right)]);
      const summary = {
        added: 0,
        removed: 0,
        changed: 0,
        same: 0,
        total: keys.size,
        categories: [],
      };

      [...keys].sort().forEach((key) => {
        const inLeft = Object.prototype.hasOwnProperty.call(left, key);
        const inRight = Object.prototype.hasOwnProperty.call(right, key);
        let status = "same";
        if (!inLeft) {
          summary.added += 1;
          status = "added";
        } else if (!inRight) {
          summary.removed += 1;
          status = "removed";
        } else if (!this._isDataEqual(left[key], right[key])) {
          summary.changed += 1;
          status = "changed";
        } else {
          summary.same += 1;
        }
        summary.categories.push({
          key,
          label: this._getRawCategoryLabel(key),
          status,
        });
      });
      return summary;
    },

    _getCardFieldDefinitions() {
      return [
        { key: "name", label: "角色名", kind: "text" },
        { key: "description", label: "描述", kind: "text" },
        { key: "personality", label: "性格", kind: "text" },
        { key: "scenario", label: "场景", kind: "text" },
        { key: "first_mes", label: "首条消息", kind: "text" },
        { key: "mes_example", label: "对话示例", kind: "text" },
        { key: "creator_notes", label: "创作者备注", kind: "text" },
        { key: "system_prompt", label: "系统提示词", kind: "text" },
        {
          key: "post_history_instructions",
          label: "历史消息后指令",
          kind: "text",
        },
        { key: "alternate_greetings", label: "备用开场白", kind: "json" },
        { key: "tags", label: "标签", kind: "json" },
        { key: "creator", label: "作者", kind: "text" },
        { key: "character_version", label: "卡片版本", kind: "text" },
        { key: "character_book", label: "嵌入式世界书", kind: "json" },
        { key: "extensions", label: "扩展数据", kind: "json" },
      ];
    },

    _extractCardPayload(raw) {
      const root = raw && typeof raw === "object" ? raw : {};
      const data = root.data && typeof root.data === "object" ? root.data : {};
      const payload = { ...root, ...data };
      const aliases = {
        name: ["name", "char_name"],
        creator_notes: ["creator_notes", "creatorcomment"],
        character_version: ["character_version", "char_version"],
      };

      Object.entries(aliases).forEach(([key, keys]) => {
        const value = keys
          .map((candidate) => payload[candidate] ?? root[candidate])
          .find((candidate) => candidate !== undefined && candidate !== null);
        if (value !== undefined) payload[key] = value;
      });

      return payload;
    },

    _normalizeCardBookValue(value) {
      const book = this._extractLorebookBook(value);
      if (!book) return null;

      const entries = this._extractLorebookEntries(book).map((entry, index) => {
        return this._normalizeLorebookEntry(entry, index).compareObj;
      });
      const name = String(book.name || "").trim();
      if (entries.length === 0 && (!name || name === "World Info")) return null;
      if (!name && entries.length === 0) return null;
      return { name, entries };
    },

    _normalizeCardFieldValue(key, value) {
      if (key === "character_book") return this._normalizeCardBookValue(value);
      if (key === "extensions") {
        const extensions =
          value && typeof value === "object" && !Array.isArray(value)
            ? { ...value }
            : {};
        if (
          Array.isArray(extensions.regex_scripts) &&
          extensions.regex_scripts.length === 0
        ) {
          delete extensions.regex_scripts;
        }
        if (
          Array.isArray(extensions.tavern_helper) &&
          extensions.tavern_helper.length === 0
        ) {
          delete extensions.tavern_helper;
        }
        return extensions;
      }
      if (key === "tags" || key === "alternate_greetings") {
        return Array.isArray(value)
          ? value.filter((item) => String(item ?? "").trim() !== "")
          : [];
      }
      return value === undefined || value === null ? "" : value;
    },

    _summarizeCardDiff(leftData, rightData) {
      const left = this._extractCardPayload(leftData);
      const right = this._extractCardPayload(rightData);
      const fields = this._getCardFieldDefinitions().map((definition) => {
        const leftValue = this._normalizeCardFieldValue(
          definition.key,
          left[definition.key],
        );
        const rightValue = this._normalizeCardFieldValue(
          definition.key,
          right[definition.key],
        );
        return {
          ...definition,
          leftValue,
          rightValue,
          status: this._isDataEqual(leftValue, rightValue) ? "same" : "changed",
        };
      });

      const changedFields = fields.filter((field) => field.status !== "same");
      return {
        added: 0,
        removed: 0,
        changed: changedFields.length,
        same: fields.length - changedFields.length,
        total: fields.length,
        categories: changedFields.map((field) => ({
          key: field.key,
          label: field.label,
          status: field.status,
        })),
        fields,
      };
    },

    _formatCardFieldValue(value) {
      if (value === null || value === undefined || value === "") {
        return '<span class="preset-rollback-field-empty">（未设置）</span>';
      }
      if (typeof value === "string") return this._escapeHtml(value);
      try {
        return this._escapeHtml(JSON.stringify(value, null, 2));
      } catch (e) {
        return this._escapeHtml(String(value));
      }
    },

    _renderCardFieldValue(field, side) {
      const leftValue = field.leftValue;
      const rightValue = field.rightValue;
      const value = side === "left" ? leftValue : rightValue;
      const opposite = side === "left" ? rightValue : leftValue;
      const bothText =
        typeof value === "string" && typeof opposite === "string";

      if (field.status === "changed" && bothText) {
        return `<div class="preset-rollback-field-value">${this._renderLineDiffHtml(
          leftValue,
          rightValue,
          side,
        )}</div>`;
      }

      return `<pre class="preset-rollback-field-value">${this._formatCardFieldValue(value)}</pre>`;
    },

    _renderCardFieldDiff(leftData, rightData) {
      const summary = this._summarizeCardDiff(leftData, rightData);
      const changedFields = summary.fields.filter((field) => field.status !== "same");
      let html = `
        <div class="preset-rollback-card-fields-head">
          <div>
            <strong>字段变更清单</strong>
            <span>只显示有差异的业务字段，展开原始 JSON 可检查完整结构。</span>
          </div>
          <span>${changedFields.length} / ${summary.total} 个字段</span>
        </div>
      `;

      if (!changedFields.length) {
        html += '<div class="preset-rollback-card-fields-empty">两个版本的角色卡字段一致。</div>';
        return { html, summary };
      }

      html += '<div class="preset-rollback-card-fields-list">';
      changedFields.forEach((field) => {
        const statusLabel = field.status === "changed" ? "修改" : field.status;
        html += `
          <article class="preset-rollback-field-diff-card is-${field.status}">
            <header class="preset-rollback-field-diff-head">
              <div>
                <span class="preset-rollback-field-status">${statusLabel}</span>
                <strong>${this._escapeHtml(field.label)}</strong>
                <code>${this._escapeHtml(field.key)}</code>
              </div>
            </header>
            <div class="preset-rollback-field-diff-values">
              <section class="preset-rollback-field-value-pane is-old">
                <div class="preset-rollback-field-value-label">旧版本</div>
                ${this._renderCardFieldValue(field, "left")}
              </section>
              <section class="preset-rollback-field-value-pane is-new">
                <div class="preset-rollback-field-value-label">新版本</div>
                ${this._renderCardFieldValue(field, "right")}
              </section>
            </div>
          </article>
        `;
      });
      html += "</div>";
      return { html, summary };
    },

    _toArray(val) {
      if (Array.isArray(val)) {
        return val.map((v) => String(v ?? "").trim()).filter(Boolean);
      }
      if (typeof val === "string") {
        return val
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      }
      return [];
    },

    _extractLorebookBook(raw) {
      if (!raw || typeof raw !== "object") return null;

      if (Array.isArray(raw)) return raw;
      if (raw?.data?.character_book) return raw.data.character_book;
      if (raw?.character_book) return raw.character_book;
      if (raw?.data?.entries) return raw.data;
      if (raw?.entries) return raw;
      return null;
    },

    _extractLorebookEntries(raw) {
      const book = this._extractLorebookBook(raw);
      if (!book) return [];

      if (Array.isArray(book)) {
        return book.filter((e) => e && typeof e === "object");
      }

      if (book && typeof book === "object") {
        const entries = book.entries;
        if (Array.isArray(entries))
          return entries.filter((e) => e && typeof e === "object");
        if (entries && typeof entries === "object") {
          return Object.values(entries).filter(
            (e) => e && typeof e === "object",
          );
        }
      }
      return [];
    },

    _normalizeLorebookEntry(entry, index) {
      const raw = entry || {};
      const normalized = normalizeWiEntry(raw, index);
      const keys = this._toArray(normalized.keys);
      const secondaryKeys = this._toArray(normalized.secondary_keys);
      const comment = String(normalized.comment ?? "").trim();
      const content = String(normalized.content ?? "");
      const uid = String(raw.st_manager_uid ?? "").trim();
      const legacyUid = String(
        raw.st_source_id ?? raw.uid ?? raw.id ?? normalized.st_source_id ?? "",
      ).trim();

      // Normalize legacy/ST/editor aliases before comparing. Runtime indexes and
      // generated defaults are deliberately excluded from the semantic signature.
      const runtimeKeys = new Set([
        "id",
        "displayIndex",
        "st_source_id",
        "st_manager_uid",
        "uid",
      ]);
      const compareObj = {};
      Object.keys(normalized).forEach((key) => {
        if (!runtimeKeys.has(key) && key !== "extensions") {
          compareObj[key] = normalized[key];
        }
      });
      if (normalized.extensions && typeof normalized.extensions === "object") {
        const extensions = { ...normalized.extensions };
        [
          "position",
          "depth",
          "role",
          "display_index",
          "probability",
          "selectiveLogic",
          "delay_until_recursion",
          "vectorized",
          "exclude_recursion",
          "prevent_recursion",
          "ignore_budget",
          "match_whole_words",
          "case_sensitive",
          "useProbability",
          "outlet_name",
          "group",
          "group_override",
          "group_weight",
          "scan_depth",
          "use_group_scoring",
          "automation_id",
          "sticky",
          "cooldown",
          "delay",
          "triggers",
          "match_persona_description",
          "match_character_description",
          "match_character_personality",
          "match_character_depth_prompt",
          "match_scenario",
          "match_creator_notes",
        ].forEach((key) => delete extensions[key]);
        if (Object.keys(extensions).length) compareObj.extensions = extensions;
      }
      Object.assign(compareObj, {
        enabled: !!normalized.enabled,
        constant: !!normalized.constant,
        selective: !!normalized.selective,
        position: Number(normalized.position || 0),
        depth: Number(normalized.depth || 0),
        role: Number(normalized.role || 0),
        probability: Number(normalized.probability ?? 100),
        group: String(normalized.group || ""),
        keys: [...keys].map((value) => value.toLowerCase()).sort(),
        secondary_keys: [...secondaryKeys]
          .map((value) => value.toLowerCase())
          .sort(),
        comment,
        content,
      });

      const keySig = keys
        .map((k) => k.toLowerCase())
        .sort()
        .join("|");
      const secSig = secondaryKeys
        .map((k) => k.toLowerCase())
        .sort()
        .join("|");
      const quickSig = `${comment.toLowerCase()}|${keySig}|${secSig}`;
      const stableSig = this._stableStringify(compareObj);

      return {
        raw,
        normalized,
        index,
        uid,
        legacyUid,
        comment,
        content,
        keys,
        secondaryKeys,
        compareObj,
        quickSig,
        stableSig,
        title: comment || `(无备注 #${index + 1})`,
      };
    },

    _buildLorebookPairs(leftEntries, rightEntries) {
      const left = leftEntries.map((e, i) =>
        this._normalizeLorebookEntry(e, i),
      );
      const right = rightEntries.map((e, i) =>
        this._normalizeLorebookEntry(e, i),
      );

      const rightUsed = new Set();
      const rightUidMap = new Map();
      const rightLegacyUidMap = new Map();
      const rightStableMap = new Map();
      const rightQuickMap = new Map();

      const pushMap = (map, key, idx) => {
        if (!key) return;
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(idx);
      };

      right.forEach((item, idx) => {
        pushMap(rightUidMap, item.uid, idx);
        pushMap(rightLegacyUidMap, item.legacyUid, idx);
        pushMap(rightStableMap, item.stableSig, idx);
        pushMap(rightQuickMap, item.quickSig, idx);
      });

      const pickUnique = (map, key) => {
        const arr = map.get(key);
        if (!arr || arr.length !== 1) return -1;
        const idx = arr[0];
        if (rightUsed.has(idx)) return -1;
        return idx;
      };

      const pairs = [];
      left.forEach((item) => {
        let rightIdx = -1;
        if (item.uid) rightIdx = pickUnique(rightUidMap, item.uid);
        if (rightIdx < 0 && item.legacyUid)
          rightIdx = pickUnique(rightLegacyUidMap, item.legacyUid);
        if (rightIdx < 0) rightIdx = pickUnique(rightStableMap, item.stableSig);
        if (rightIdx < 0) rightIdx = pickUnique(rightQuickMap, item.quickSig);

        if (rightIdx >= 0) {
          rightUsed.add(rightIdx);
          pairs.push({ left: item, right: right[rightIdx] });
        } else {
          pairs.push({ left: item, right: null, _needsFallback: true });
        }
      });

      // 二次兜底：当 UID/签名无法匹配（常见于旧版本无 UID，且条目内容变化较大），
      // 按剩余顺序配对，避免“修改被误判为删除+新增”造成可读性差和“条目丢失”错觉。
      const fallbackLeftPairs = pairs.filter((p) => p._needsFallback);
      const unmatchedRight = [];
      right.forEach((item, idx) => {
        if (!rightUsed.has(idx)) unmatchedRight.push(item);
      });

      const fallbackCount = Math.min(
        fallbackLeftPairs.length,
        unmatchedRight.length,
      );
      for (let i = 0; i < fallbackCount; i++) {
        fallbackLeftPairs[i].right = unmatchedRight[i];
        delete fallbackLeftPairs[i]._needsFallback;
      }
      for (let i = fallbackCount; i < fallbackLeftPairs.length; i++) {
        delete fallbackLeftPairs[i]._needsFallback;
      }
      for (let i = fallbackCount; i < unmatchedRight.length; i++) {
        pairs.push({ left: null, right: unmatchedRight[i] });
      }

      // 清理临时标记
      pairs.forEach((p) => {
        if (p._needsFallback) {
          delete p._needsFallback;
        }
      });

      return pairs;
    },

    _getPairMeta(pair) {
      if (pair.left && pair.right) {
        const leftStr = this._stableStringify(pair.left.compareObj);
        const rightStr = this._stableStringify(pair.right.compareObj);
        const isSame = leftStr === rightStr;
        const visibleChanged = {
          comment: pair.left.comment !== pair.right.comment,
          keys:
            pair.left.keys
              .map((value) => value.toLowerCase())
              .sort()
              .join("|") !==
              pair.right.keys
                .map((value) => value.toLowerCase())
                .sort()
                .join("|") ||
            pair.left.secondaryKeys
              .map((value) => value.toLowerCase())
              .sort()
              .join("|") !==
              pair.right.secondaryKeys
                .map((value) => value.toLowerCase())
                .sort()
                .join("|"),
          content: pair.left.content !== pair.right.content,
        };
        return {
          status: isSame ? "same" : "changed",
          changed: {
            ...visibleChanged,
            other: !isSame && !Object.values(visibleChanged).some(Boolean),
          },
        };
      }
      if (pair.left && !pair.right) {
        return {
          status: "removed",
          changed: { comment: true, keys: true, content: true, other: true },
        };
      }
      return {
        status: "added",
        changed: { comment: true, keys: true, content: true, other: true },
      };
    },

    _previewContent(text, maxLen = 800) {
      const raw = String(text ?? "");
      if (raw.length <= maxLen) return raw;
      return `${raw.slice(0, maxLen)}\n...(已省略 ${raw.length - maxLen} 字)`;
    },

    _splitLinesWithLimit(text, maxLines = 240, maxChars = 16000) {
      const raw = String(text ?? "")
        .replace(/\r\n/g, "\n")
        .replace(/\r/g, "\n");
      let limited = raw;
      let truncatedByChars = false;
      if (limited.length > maxChars) {
        limited = limited.slice(0, maxChars);
        truncatedByChars = true;
      }
      let lines = limited.split("\n");
      let truncatedByLines = false;
      if (lines.length > maxLines) {
        lines = lines.slice(0, maxLines);
        truncatedByLines = true;
      }
      if (truncatedByChars || truncatedByLines) {
        lines.push(`...(内容过长，已截断显示)`);
      }
      return lines;
    },

    _buildLineOps(leftLines, rightLines, maxCells = 70000) {
      const n = leftLines.length;
      const m = rightLines.length;

      // 兜底：内容过大时使用按索引近似对齐，避免 O(n*m) 过重
      if (n * m > maxCells) {
        const approx = [];
        const len = Math.max(n, m);
        for (let i = 0; i < len; i++) {
          const l = i < n ? leftLines[i] : null;
          const r = i < m ? rightLines[i] : null;
          if (l !== null && r !== null) {
            approx.push({ t: l === r ? "same" : "changed", left: l, right: r });
          } else if (l !== null) {
            approx.push({ t: "removed", left: l, right: null });
          } else {
            approx.push({ t: "added", left: null, right: r });
          }
        }
        return approx;
      }

      const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
      for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
          if (leftLines[i] === rightLines[j]) {
            dp[i][j] = dp[i + 1][j + 1] + 1;
          } else {
            dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
          }
        }
      }

      const rawOps = [];
      let i = 0;
      let j = 0;
      while (i < n && j < m) {
        if (leftLines[i] === rightLines[j]) {
          rawOps.push({ t: "same", text: leftLines[i] });
          i += 1;
          j += 1;
        } else if (dp[i + 1][j] >= dp[i][j + 1]) {
          rawOps.push({ t: "remove", text: leftLines[i] });
          i += 1;
        } else {
          rawOps.push({ t: "add", text: rightLines[j] });
          j += 1;
        }
      }
      while (i < n) {
        rawOps.push({ t: "remove", text: leftLines[i] });
        i += 1;
      }
      while (j < m) {
        rawOps.push({ t: "add", text: rightLines[j] });
        j += 1;
      }

      // 将连续 add/remove 片段折叠为 changed / added / removed 行
      const aligned = [];
      let k = 0;
      while (k < rawOps.length) {
        const op = rawOps[k];
        if (op.t === "same") {
          aligned.push({ t: "same", left: op.text, right: op.text });
          k += 1;
          continue;
        }

        const removes = [];
        const adds = [];
        while (k < rawOps.length && rawOps[k].t !== "same") {
          if (rawOps[k].t === "remove") removes.push(rawOps[k].text);
          if (rawOps[k].t === "add") adds.push(rawOps[k].text);
          k += 1;
        }

        const pairCount = Math.min(removes.length, adds.length);
        for (let x = 0; x < pairCount; x++) {
          aligned.push({ t: "changed", left: removes[x], right: adds[x] });
        }
        for (let x = pairCount; x < removes.length; x++) {
          aligned.push({ t: "removed", left: removes[x], right: null });
        }
        for (let x = pairCount; x < adds.length; x++) {
          aligned.push({ t: "added", left: null, right: adds[x] });
        }
      }

      return aligned;
    },

    _lineClassByType(type, side) {
      if (type === "changed")
        return "color-status-warning";
      if (type === "added" && side === "right")
        return "color-status-success";
      if (type === "removed" && side === "left")
        return "color-status-danger";
      if (type === "added" && side === "left")
        return "color-status-success";
      if (type === "removed" && side === "right")
        return "color-status-danger";
      return "color-surface-container";
    },

    _renderLineDiffHtml(leftText, rightText, side) {
      const leftLines = this._splitLinesWithLimit(leftText);
      const rightLines = this._splitLinesWithLimit(rightText);
      const rows = this._buildLineOps(leftLines, rightLines);

      let leftNo = 0;
      let rightNo = 0;
      let html = "";
      rows.forEach((row) => {
        const isLeft = side === "left";
        const text = isLeft ? row.left : row.right;
        const cls = this._lineClassByType(row.t, side);

        if (row.left !== null) leftNo += 1;
        if (row.right !== null) rightNo += 1;
        const lineNo = isLeft
          ? row.left !== null
            ? leftNo
            : ""
          : row.right !== null
            ? rightNo
            : "";
        const lineText = text === null ? "(空值)" : this._escapeHtml(text);
        const lineTextClass =
          text === null
            ? "text-[var(--content-muted)] italic"
            : "text-[var(--content-primary)]";

        html += `
                    <div class="preset-rollback-line-diff-row px-2 py-0.5 rounded ${cls}">
                        <span class="preset-rollback-line-diff-number inline-block w-8 mr-2 text-[10px] text-[var(--content-muted)] text-right select-none">${lineNo || " "}</span>
                        <span class="preset-rollback-line-diff-text text-[11px] whitespace-pre-wrap break-words ${lineTextClass}">${lineText || " "}</span>
                    </div>
                `;
      });
      return html;
    },

    _fieldDiffClass(meta, side, fieldChanged) {
      const isLeft = side === "left";
      const isRight = side === "right";

      // 整条新增：右侧字段全部绿底
      if (meta.status === "added" && isRight) {
        return "color-status-success";
      }
      // 整条删除：左侧字段全部红底
      if (meta.status === "removed" && isLeft) {
        return "color-status-danger";
      }
      // 双侧都存在时，仅变化字段黄底
      if (meta.status === "changed" && fieldChanged) {
        return "color-status-warning";
      }
      return "color-surface-container";
    },

    _renderLorebookEntry(entry, oppositeEntry, meta, side, orderNo) {
      if (!entry) {
        return `
                    <div class="m-2 p-3 rounded border border-dashed border-[var(--border-default)] text-[11px] text-[var(--content-muted)] opacity-70">
                        <div>（此侧无对应条目）</div>
                    </div>
                `;
      }

      const isLeft = side === "left";
      const markClass =
        isLeft && (meta.status === "removed" || meta.status === "changed")
          ? "status-danger-text"
          : !isLeft && (meta.status === "added" || meta.status === "changed")
            ? "status-success-text"
            : "text-[var(--content-primary)]";
      const comment = this._escapeHtml(entry.title);
      const keys = this._escapeHtml(entry.keys.join(", ") || "(空)");
      const sec = this._escapeHtml(entry.secondaryKeys.join(", ") || "(空)");
      const idx = entry.index + 1;

      const commentCls = meta.changed.comment
        ? markClass
        : "text-[var(--content-primary)]";
      const keyCls = meta.changed.keys ? markClass : "text-[var(--content-primary)]";
      const contentCls = meta.changed.content
        ? markClass
        : "text-[var(--content-primary)]";

      const commentBgCls = this._fieldDiffClass(
        meta,
        side,
        meta.changed.comment,
      );
      const keysBgCls = this._fieldDiffClass(meta, side, meta.changed.keys);
      const leftContent =
        side === "left" ? entry.content || "" : oppositeEntry?.content || "";
      const rightContent =
        side === "right" ? entry.content || "" : oppositeEntry?.content || "";
      const lineDiffHtml = this._renderLineDiffHtml(
        leftContent,
        rightContent,
        side,
      );
      const otherChangedHtml = meta.changed.other
        ? `<div class="mt-2 text-[10px] status-warning-text">其他行为设置已修改（原始 JSON 模式可查看完整字段）</div>`
        : "";

      return `
                <div class="m-2 p-3 rounded border bg-[var(--surface-container-raised)] border-[var(--border-default)]">
                    <div class="text-[10px] uppercase tracking-wide text-[var(--content-muted)]">Entry ${orderNo} · Source #${idx}</div>
                    <div class="mt-1 p-1.5 rounded ${commentBgCls}">
                        <div class="text-sm font-bold ${commentCls}">${comment}</div>
                    </div>
                    <div class="mt-2 p-1.5 rounded ${keysBgCls}">
                        <div class="text-[11px] ${keyCls}">关键词: ${keys}</div>
                        <div class="mt-1 text-[11px] ${keyCls}">次级词: ${sec}</div>
                    </div>
                    ${otherChangedHtml}
                    <div class="mt-2 p-1.5 rounded color-surface-sunken border border-[var(--border-default)]">
                        <div class="text-[11px] text-[var(--content-muted)]">内容预览</div>
                        <div class="mt-1 p-2 rounded color-surface-container max-h-56 overflow-auto">${lineDiffHtml}</div>
                        <div class="mt-1 text-[10px] ${contentCls}">行级高亮：绿=新增，黄=修改，红=删除</div>
                    </div>
                </div>
            `;
    },

    _renderLorebookDiff(leftData, rightData) {
      const leftEntries = this._extractLorebookEntries(leftData);
      const rightEntries = this._extractLorebookEntries(rightData);
      const pairs = this._buildLorebookPairs(leftEntries, rightEntries);
      const withMeta = pairs.map((pair) => ({
        pair,
        meta: this._getPairMeta(pair),
      }));

      const changed = withMeta.filter((x) => x.meta.status !== "same");
      const hiddenCount = withMeta.length - changed.length;
      const displayList = changed.length > 0 ? changed : withMeta.slice(0, 20);

      const counts = { added: 0, removed: 0, changed: 0, same: 0 };
      withMeta.forEach((x) => {
        counts[x.meta.status] += 1;
      });

      const summary = `
                <div class="sticky top-0 z-10 px-3 py-2 border-b border-[var(--border-default)] bg-[var(--surface-container)] text-[11px]">
                    <span class="status-success-text mr-3">新增 ${counts.added}</span>
                    <span class="status-danger-text mr-3">删除 ${counts.removed}</span>
                    <span class="status-warning-text mr-3">修改 ${counts.changed}</span>
                    <span class="text-[var(--content-muted)]">未变化 ${counts.same}</span>
                    <span class="ml-3 text-[var(--content-muted)]">行级底色: <span class="status-success-text">绿=新增</span> / <span class="status-warning-text">黄=修改</span> / <span class="status-danger-text">红=删除</span></span>
                    ${hiddenCount > 0 ? `<span class="ml-3 text-[var(--content-muted)]">（已隐藏 ${hiddenCount} 条未变化）</span>` : ""}
                </div>
            `;

      let leftHtml = summary;
      let rightHtml = summary;
      displayList.forEach((item, idx) => {
        leftHtml += this._renderLorebookEntry(
          item.pair.left,
          item.pair.right,
          item.meta,
          "left",
          idx + 1,
        );
        rightHtml += this._renderLorebookEntry(
          item.pair.right,
          item.pair.left,
          item.meta,
          "right",
          idx + 1,
        );
      });

      if (displayList.length === 0) {
        leftHtml +=
          '<div class="p-6 text-center text-[var(--content-muted)] text-xs">无可展示条目</div>';
        rightHtml +=
          '<div class="p-6 text-center text-[var(--content-muted)] text-xs">无可展示条目</div>';
      }

      return { left: leftHtml, right: rightHtml };
    },

    _isDataEqual(a, b) {
      try {
        return this._stableStringify(a) === this._stableStringify(b);
      } catch (e) {
        try {
          return JSON.stringify(a) === JSON.stringify(b);
        } catch {
          return false;
        }
      }
    },

    _hasLorebookDiff(leftData, rightData) {
      const leftEntries = this._extractLorebookEntries(leftData);
      const rightEntries = this._extractLorebookEntries(rightData);
      const pairs = this._buildLorebookPairs(leftEntries, rightEntries);
      if (!pairs.length) return false;
      for (const pair of pairs) {
        const meta = this._getPairMeta(pair);
        if (meta.status !== "same") return true;
      }
      return false;
    },

    _hasLorebookVisibleDiff(leftData, rightData) {
      const leftEntries = this._extractLorebookEntries(leftData);
      const rightEntries = this._extractLorebookEntries(rightData);
      const pairs = this._buildLorebookPairs(leftEntries, rightEntries);
      if (!pairs.length) return false;

      const entryKeySignature = (values) =>
        values
          .map((value) => String(value).toLowerCase())
          .sort()
          .join("|");

      for (const pair of pairs) {
        // 一侧有一侧无：可视上一定是新增/删除
        if (!pair.left || !pair.right) return true;

        // 按当前 UI 真正展示的字段判定可视差异
        if (pair.left.comment !== pair.right.comment) return true;
        if (pair.left.content !== pair.right.content) return true;

        const leftKeys = entryKeySignature(pair.left.keys);
        const rightKeys = entryKeySignature(pair.right.keys);
        if (leftKeys !== rightKeys) return true;

        const leftSec = entryKeySignature(pair.left.secondaryKeys);
        const rightSec = entryKeySignature(pair.right.secondaryKeys);
        if (leftSec !== rightSec) return true;
      }
      return false;
    },

    _isSameForAutoPick(leftData, rightData) {
      if (this._isLorebookComparison()) {
        return !this._hasLorebookVisibleDiff(leftData, rightData);
      }
      if (this.rollbackTargetType === "card" && this.diffRenderMode !== "raw") {
        return this._summarizeCardDiff(leftData, rightData).changed === 0;
      }
      return this._isDataEqual(leftData, rightData);
    },

    async _pruneBackupsRepresentedByCurrent(currentVer, backups) {
      const ordered = Array.isArray(backups) ? backups : [];
      if (!ordered.length) {
        return { backups: [], hidden: 0 };
      }

      let currentData;
      try {
        currentData = await this._loadVersionData(currentVer);
      } catch (e) {
        console.warn("Load current version for backup pruning failed:", e);
        return { backups: ordered, hidden: 0 };
      }

      let hidden = 0;
      for (const backup of ordered) {
        try {
          const backupData = await this._loadVersionData(backup);
          if (this._isSameForAutoPick(backupData, currentData)) {
            hidden += 1;
          } else {
            break;
          }
        } catch (e) {
          console.warn("Load backup for pruning failed:", e);
          break;
        }
      }

      return {
        backups: ordered.slice(hidden),
        hidden,
      };
    },

    async _loadVersionData(ver) {
      let data;

      // 场景 A: 当前版本 (Current)
      if (ver.is_current) {
        let rawContent = this.rollbackLiveContent;

        // 如果没有实时内容，从 API 读取
        if (!rawContent) {
          if (this.rollbackTargetType === "card") {
            // 读取角色卡元数据
            const cardId = this._isEmbeddedWorldbookTarget()
              ? String(this.rollbackTargetId || "").replace(/^embedded::/, "")
              : this.rollbackTargetId;
            const res = await getCardMetadata(cardId);
            rawContent = res.success === true && res.data ? res.data : res;
          } else if (this.rollbackTargetType === "lorebook") {
            // 读取世界书
            if (this._isEmbeddedWorldbookTarget()) {
              // 内嵌：读取宿主卡片
              const realId = String(this.rollbackTargetId || "").replace(
                /^embedded::/,
                "",
              );
              const res = await getCardMetadata(realId);
              rawContent = res.success === true && res.data ? res.data : res;
            } else {
              // 独立文件
              const res = await readFileContent({
                path: this.rollbackTargetPath,
              });
              rawContent = res.data;
            }
          } else if (this.rollbackTargetType === "preset") {
            const res = await readFileContent({
              path: this.rollbackTargetPath,
            });
            rawContent = res.data;
          }
        }

        // 角色卡走标准化，世界书保持原结构以做条目级匹配
        if (this._isLorebookComparison()) {
          data = rawContent;
        } else if (this.rollbackTargetType === "preset") {
          data = rawContent;
        } else {
          const cleanRes = await normalizeCardData(rawContent);
          if (cleanRes.success) {
            data = cleanRes.data;
          } else {
            console.warn("清洗失败，使用原始数据", cleanRes.msg);
            data = rawContent;
          }
        }
      }
      // 场景 B: 历史备份 (Backup)
      else {
        const res = await readFileContent({ path: ver.path });
        data = res.data;
      }

      // 世界书对比模式：统一提取 character_book
      if (this._isLorebookComparison()) {
        const book = this._extractLorebookBook(data);
        if (book !== null) data = book;
      }

      return data;
    },

    async updateDiffView(autoAdjustLeft = true) {
      const leftVer = this.diffSelection.left;
      const rightVer = this.diffSelection.right;

      if (!leftVer || !rightVer) {
        this.diffData = {
          left: '<div class="p-8 text-center color-text-muted">请在左侧列表选择版本进行比对</div>',
          right: "",
          fields: "",
        };
        this.diffSummary = {
          added: 0,
          removed: 0,
          changed: 0,
          same: 0,
          total: 0,
          categories: [],
        };
        return;
      }

      this.isDiffLoading = true;
      try {
        const [leftData, rightData] = await Promise.all([
          this._loadVersionData(leftVer),
          this._loadVersionData(rightVer),
        ]);

        // 默认打开时：若“最新快照”与 Current 完全一致，自动切到下一个有差异的版本
        if (
          autoAdjustLeft &&
          rightVer.is_current &&
          leftVer &&
          !leftVer.is_current
        ) {
          const isSameAsCurrent = this._isSameForAutoPick(leftData, rightData);
          if (isSameAsCurrent && this.backupList.length > 1) {
            const currentIdx = this.backupList.findIndex(
              (b) => b.path === leftVer.path,
            );
            for (let i = currentIdx + 1; i < this.backupList.length; i++) {
              const candidate = this.backupList[i];
              const candidateData = await this._loadVersionData(candidate);
              if (!this._isSameForAutoPick(candidateData, rightData)) {
                this.diffSelection.left = candidate;
                await this.updateDiffView(false);
                return;
              }
            }
          }
        }

        if (this._isLorebookComparison() && this.diffRenderMode !== "raw") {
          const leftEntries = this._extractLorebookEntries(leftData);
          const rightEntries = this._extractLorebookEntries(rightData);
          const pairs = this._buildLorebookPairs(leftEntries, rightEntries);
          const counts = { added: 0, removed: 0, changed: 0, same: 0 };
          pairs.forEach((pair) => {
            counts[this._getPairMeta(pair).status] += 1;
          });
          const entryStatusLabels = {
            added: "新增条目",
            removed: "删除条目",
            changed: "修改条目",
          };
          this.diffSummary = {
            ...counts,
            total: pairs.length,
            categories: Object.keys(entryStatusLabels)
              .filter((status) => counts[status] > 0)
              .map((status) => ({
                key: `entries-${status}`,
                label: entryStatusLabels[status],
                status,
              })),
          };
          const result = this._renderLorebookDiff(leftData, rightData);
          this.diffData.left = result.left;
          this.diffData.right = result.right;
          this.diffData.fields = "";
        } else if (
          this.rollbackTargetType === "card" &&
          this.diffRenderMode === "fields"
        ) {
          const result = this._renderCardFieldDiff(leftData, rightData);
          this.diffSummary = result.summary;
          this.diffData.left = "";
          this.diffData.right = "";
          this.diffData.fields = result.html;
        } else {
          this.diffSummary = this._summarizeRawDiff(leftData, rightData);
          const result = generateSideBySideDiff(leftData, rightData);
          this.diffData.left = result.left;
          this.diffData.right = result.right;
          this.diffData.fields = "";
        }
      } catch (e) {
        console.error(e);
        this.diffSummary = {
          added: 0,
          removed: 0,
          changed: 0,
          same: 0,
          total: 0,
          categories: [],
        };
        this.diffData.left = `<div class="p-4 status-danger-text">Error: ${e.message}</div>`;
        this.diffData.right = "";
        this.diffData.fields = "";
      } finally {
        this.isDiffLoading = false;
      }
    },

    // === 恢复逻辑 ===

    performRestore() {
      const targetVer = this.diffSelection.left;

      if (!targetVer || targetVer.is_current) {
        alert("请在左侧选择一个历史备份版本进行恢复");
        return;
      }
      if (
        !confirm(
          `确定回滚到 ${new Date(targetVer.mtime * 1000).toLocaleString()} 的版本吗？`,
        )
      )
        return;

      this.isLoading = true;
      restoreBackup({
        backup_path: targetVer.path,
        target_id: this.rollbackTargetId,
        type: this.rollbackTargetType,
        target_file_path: this.rollbackTargetPath,
        is_embedded_wi_only: this._isEmbeddedWorldbookTarget(),
      }).then((res) => {
        if (res.success) {
          alert("回滚成功！页面将刷新数据。");
          this.showRollbackModal = false;

          window.dispatchEvent(
            new CustomEvent("wi-restore-applied", {
              detail: {
                targetType: this.rollbackTargetType,
                targetId: this.rollbackTargetId,
                targetFilePath: this.rollbackTargetPath,
                restoredBackupPath: targetVer.path,
                restoredBackupLabel: targetVer.label || "",
                restoredBackupMtime: targetVer.mtime || 0,
              },
            }),
          );

          // 刷新父级数据
          if (this.rollbackTargetType === "card") {
            // 通知详情页刷新
            // 注意：这里需要 Card ID，如果是内嵌WI，ID需要处理
            let refreshId = this.rollbackTargetId;
            if (refreshId.startsWith("embedded::"))
              refreshId = refreshId.replace("embedded::", "");

            // 由于 detailModal 可能不在作用域内，通过事件通知
            // detailModal 需要监听 'refresh-card-detail'
            // 但在原 app.js 逻辑中，是直接调用 refreshActiveCardDetail
            // 这里我们派发通用刷新事件
            window.dispatchEvent(
              new CustomEvent("card-updated", { detail: { id: refreshId } }),
            ); // 触发重载
            window.dispatchEvent(new CustomEvent("refresh-card-list"));
          } else if (this.rollbackTargetType === "lorebook") {
            window.dispatchEvent(new CustomEvent("refresh-wi-list"));
            // 如果在编辑器中，也应该刷新编辑器，这里简单处理为刷新列表
          } else if (this.rollbackTargetType === "preset") {
            window.dispatchEvent(new CustomEvent("refresh-preset-list"));
            window.dispatchEvent(
              new CustomEvent("preset-restore-applied", {
                detail: {
                  id: this.rollbackTargetId,
                  path: this.rollbackTargetPath,
                  backup_path: targetVer.path,
                },
              }),
            );
          }
        } else {
          alert("回滚失败: " + res.msg);
        }
      }).catch((error) => {
        console.error("Restore backup failed:", error);
        alert("回滚失败: " + (error?.message || "网络或服务异常"));
      }).finally(() => {
        this.isLoading = false;
      });
    },

    // 打开备份文件夹
    openBackupFolder() {
      const type = this.rollbackTargetType; // 'card' | 'lorebook' | 'preset'
      const id = this.rollbackTargetId; // e.g. "group/name.png" or "embedded::group/name.png"
      const path = this.rollbackTargetPath; // e.g. "data/..." (only for standalone WI)

      // 1. 预判逻辑
      let isEmbedded = false;
      let targetName = "";
      let base = "";

      // 辅助：从 ID 或路径中提取纯文件名 (无后缀)
      const extractName = (str) => {
        if (!str) return "";
        // 取文件名部分 -> 去后缀 -> 替换非法字符
        return str
          .split("/")
          .pop()
          .replace(/\.[^/.]+$/, "")
          .replace(/[\\/:*?"<>|]/g, "_")
          .trim();
      };

      if (type === "preset") {
        base = `data/system/backups/presets`;
        targetName = extractName(path || id);
      } else if (type === "lorebook") {
        if (id && id.startsWith("embedded::")) {
          isEmbedded = true;
          // embedded::card_id -> 提取 card_id 部分
          const realCardId = id.replace("embedded::", "");
          targetName = extractName(realCardId);
        } else {
          // 独立世界书，使用文件路径提取名字
          targetName = extractName(path);
        }
      } else {
        // 角色卡
        targetName = extractName(id);
      }

      // 2. 构造路径
      if (isEmbedded || type === "card") {
        base = `data/system/backups/cards`;
      } else {
        base = `data/system/backups/lorebooks`;
      }

      let specific = "";
      if (targetName) {
        specific = `${base}/${targetName}`;
      } else {
        specific = base;
      }

      // 3. 执行打开请求
      openPath({
        path: specific,
        relative_to_base: true,
      }).then((res) => {
        if (!res.success) {
          // 如果特定目录不存在 (比如还没备份过)，尝试打开上一级基础目录
          openPath({ path: base, relative_to_base: true });
        }
      });
    },
  };
}
