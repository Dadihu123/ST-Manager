import {
  acknowledgeCardSourceUpdate,
  addSourceUpdateMonitorEntries,
  cancelSourceUpdateMonitorRun,
  completeSourceUpdateMonitorRun,
  getSourceUpdateMonitorEntries,
  getSourceUpdateMonitorStatus,
  getSourceUpdateTargets,
  removeSourceUpdateMonitorEntries,
  reportSourceUpdateMonitorProgress,
  saveSourceUpdateMonitorSettings,
  setSourceUpdateMonitorEntryEnabled,
  startSourceUpdateMonitorRun,
} from "../api/card.js";
import {
  isBatchOperationRunning,
  runSourceUpdateBatch,
} from "../utils/batchOperations.js";

function formatDateTime(value) {
  if (!value) return "从未";
  const date = new Date(Number(value) * 1000);
  if (Number.isNaN(date.getTime())) return "未知";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function entryStatusLabel(entry) {
  if (entry?.is_checking) return "检查中";
  if (entry?.invalid_reason) return "来源无效";
  if (entry?.pending_update) return "待处理更新";
  const status = String(entry?.last_run_status || "never_checked");
  return {
    never_checked: "尚未检查",
    updated: "发现变化",
    unchanged: "无新变化",
    card_busy: "卡片忙碌",
    missing: "卡片不存在",
    invalid_source: "来源无效",
    error: "检查失败",
  }[status] || status;
}

export default function sourceUpdateMonitor() {
  return {
    visible: false,
    loading: false,
    savingSettings: false,
    entries: [],
    status: null,
    runId: "",
    pollTimer: null,
    refreshInFlight: false,
    settingsDraftDirty: false,
    _settingsRevision: 0,
    progressRequests: [],
    settingsDraft: {
      enabled: false,
      schedule_mode: "manual",
      daily_time: "09:00",
      timezone: "",
    },

    init() {
      this._openHandler = () => this.open();
      window.addEventListener("open-source-monitor-pool", this._openHandler);
      window.addEventListener("beforeunload", () => this.stopPolling());
    },

    get currentRun() {
      return this.status?.current_run || null;
    },

    get currentRunProgress() {
      const run = this.currentRun;
      if (!run) return "";
      return `${run.completed || 0} / ${run.total || 0}`;
    },

    get lastRunSummary() {
      return this.status?.last_run_summary || {};
    },

    formatDateTime,
    entryStatusLabel,

    _settingsFromPool(pool) {
      const source = pool && typeof pool === "object" ? pool : {};
      return {
        enabled: source.enabled === true || source.enabled === 1,
        schedule_mode: source.schedule_mode || "manual",
        daily_time: source.daily_time || "09:00",
        timezone: source.timezone || "",
      };
    },

    _applySettingsDraft(pool) {
      this.settingsDraft = this._settingsFromPool(pool);
      this.settingsDraftDirty = false;
    },

    markSettingsDraftDirty() {
      this.settingsDraftDirty = true;
      this._settingsRevision += 1;
    },

    open() {
      this.visible = true;
      this.refresh();
      this.startPolling();
      this.$nextTick(() => this.$refs.monitorCloseButton?.focus());
    },

    close() {
      this.visible = false;
      this.stopPolling();
    },

    startPolling() {
      this.stopPolling();
      this.pollTimer = window.setInterval(() => {
        if (this.visible) this.refresh({ quiet: true });
      }, 4000);
    },

    stopPolling() {
      if (this.pollTimer) {
        window.clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },

    async refresh({ quiet = false } = {}) {
      if (this.refreshInFlight) return;
      const settingsRevision = this._settingsRevision;
      this.refreshInFlight = true;
      if (!quiet) this.loading = true;
      try {
        const [statusResponse, entriesResponse] = await Promise.all([
          getSourceUpdateMonitorStatus(),
          getSourceUpdateMonitorEntries(),
        ]);
        if (statusResponse?.success) {
          const serverPool = statusResponse.pool || statusResponse;
          const canSyncSettings =
            !this.settingsDraftDirty &&
            !this.savingSettings &&
            settingsRevision === this._settingsRevision;
          const previousSettings = this._settingsFromPool(this.status);
          this.status = {
            ...(this.status || {}),
            ...serverPool,
          };
          if (!canSyncSettings && this.status) {
            Object.assign(this.status, previousSettings);
          }
          if (canSyncSettings) {
            this._applySettingsDraft(serverPool);
          }
        }
        if (entriesResponse?.success) {
          this.entries = Array.isArray(entriesResponse.entries)
            ? entriesResponse.entries
            : [];
        }
        window.dispatchEvent(new CustomEvent("source-monitor-progress", {
          detail: {
            currentCardId: this.status?.current_run?.current_card_id || "",
          },
        }));
      } catch (error) {
        if (!quiet) {
          this.$store.global.showToast(`无法读取监控池：${error?.message || "网络错误"}`, 3200, "close");
        }
      } finally {
        this.loading = false;
        this.refreshInFlight = false;
      }
    },

    async addSelected() {
      const ids = [...(this.$store.global.viewState.selectedIds || [])];
      if (!ids.length) {
        this.$store.global.showToast("请先选择角色卡", 2200);
        return;
      }
      const response = await addSourceUpdateMonitorEntries(ids);
      const results = response?.results || [];
      const added = results.filter((item) => item.status === "added").length;
      const invalid = results.filter((item) => !item.success);
      const reasons = invalid
        .filter((item) => item.reason)
        .slice(0, 2)
        .map((item) => `${item.card_id}：${item.reason}`)
        .join("；");
      const suffix = invalid.length
        ? `；${invalid.length} 项未加入${reasons ? `：${reasons}` : ""}`
        : "";
      this.$store.global.showToast(`已加入监控池 ${added} 张${suffix}`, reasons ? 5200 : 3000);
      await this.refresh();
    },

    async removeEntry(entry) {
      if (!entry?.card_id) return;
      const response = await removeSourceUpdateMonitorEntries([entry.card_id]);
      if (!response?.success) {
        this.$store.global.showToast(response?.msg || "移出失败", 2600);
        return;
      }
      this.$store.global.showToast("已移出角色卡监控池", 2200);
      await this.refresh();
    },

    async toggleEntry(entry) {
      if (!entry?.card_id) return;
      const response = await setSourceUpdateMonitorEntryEnabled(
        entry.card_id,
        !entry.enabled,
      );
      if (!response?.success) {
        this.$store.global.showToast(response?.msg || "切换监控状态失败", 2600);
        return;
      }
      await this.refresh({ quiet: true });
    },

    openCard(entry) {
      if (!entry?.card_id) return;
      window.dispatchEvent(new CustomEvent("open-detail", {
        detail: {
          id: entry.card_id,
          char_name: entry.char_name,
          source_link: entry.source_url,
          source_title: entry.source_title,
          source_update: entry.source_update,
        },
      }));
      this.close();
    },

    async acknowledge(entry) {
      if (!entry?.pending_update) return;
      const response = await acknowledgeCardSourceUpdate(entry.card_id);
      window.dispatchEvent(new CustomEvent("source-update-result", {
        detail: { card_id: entry.card_id, result: response, item: {} },
      }));
      if (response?.success) {
        this.$store.global.showToast(
          response.acknowledged ? "已确认无需更新" : "当前没有待处理更新",
          2200,
        );
        await this.refresh();
      } else {
        this.$store.global.showToast(response?.error || "确认失败", 2600);
      }
    },

    async startCheck() {
      if (isBatchOperationRunning() || this.currentRun) {
        this.$store.global.showToast("已有检查任务正在进行", 2400);
        return;
      }

      try {
        const targets = await getSourceUpdateTargets({ scope: "monitor_pool" });
        const cardIds = Array.isArray(targets?.card_ids) ? targets.card_ids : [];
        if (!cardIds.length) {
          this.$store.global.showToast("监控池中没有启用的角色卡", 2400);
          return;
        }
        const started = await startSourceUpdateMonitorRun({
          card_ids: cardIds,
          trigger: "manual",
        });
        if (!started?.success) {
          this.$store.global.showToast(started?.error || "无法创建检查任务", 3000);
          return;
        }

        this.runId = started.run?.run_id || "";
        this.progressRequests = [];
        const result = await runSourceUpdateBatch({
          // 目标已经在服务端冻结；后续成员变化不影响本次运行。
          targetPayload: { card_ids: started.card_ids || cardIds },
          title: "检查角色卡监控池",
          onItem: (cardId, response, item) => {
            if (this.runId) {
              this.progressRequests.push(
                reportSourceUpdateMonitorProgress(this.runId, {
                  card_id: cardId,
                  result: response,
                  completed: item?.completed,
                }),
              );
            }
            this.refresh({ quiet: true });
          },
        });
        await Promise.allSettled(this.progressRequests);
        if (this.runId) {
          await completeSourceUpdateMonitorRun(this.runId, {
            summary: result,
            status: result?.cancelled ? "cancelled" : "completed",
          });
        }
        this.$store.global.showToast(
          `监控池检查完成：发现变化 ${result?.updated || 0} 张，待处理 ${result?.pending || 0} 张`,
          3200,
        );
        window.dispatchEvent(new CustomEvent("refresh-card-list"));
        await this.refresh();
      } catch (error) {
        if (this.runId) {
          await completeSourceUpdateMonitorRun(this.runId, {
            status: "failed",
            error: error?.message || "检查失败",
          }).catch(() => {});
        }
        this.$store.global.showToast(`监控池检查失败：${error?.message || "网络错误"}`, 3600, "close");
        await this.refresh({ quiet: true });
      } finally {
        this.runId = "";
        this.progressRequests = [];
      }
    },

    async cancelCheck() {
      if (!this.runId) {
        this.$store.global.requestBatchProgressCancel();
        return;
      }
      await cancelSourceUpdateMonitorRun(this.runId);
      this.$store.global.requestBatchProgressCancel();
      this.$store.global.showToast("已请求停止后续检查", 2200);
    },

    async saveSettings() {
      const payload = { ...this.settingsDraft };
      const saveRevision = ++this._settingsRevision;
      this.savingSettings = true;
      try {
        const response = await saveSourceUpdateMonitorSettings(payload);
        if (!response?.success) {
          this.$store.global.showToast(response?.error || "保存监控设置失败", 2800);
          return;
        }
        this.status = {
          ...(this.status || {}),
          ...this._settingsFromPool(response),
          ...(Object.prototype.hasOwnProperty.call(response, "next_run_at")
            ? { next_run_at: response.next_run_at }
            : {}),
        };
        if (this._settingsRevision === saveRevision) {
          this._applySettingsDraft(response);
        }
        this.$store.global.showToast("监控调度设置已保存", 2200);
        await this.refresh();
      } finally {
        this.savingSettings = false;
      }
    },
  };
}
