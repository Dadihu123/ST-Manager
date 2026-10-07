/**
 * static/js/components/pluginJobPanel.js
 * 插件作业面板（设计文档 1.7）：实时进度、条目结果、日志与四类操作。
 *
 * 打开方式：`api.jobs.open(runId)` 或派发 `open-plugin-job-panel` 事件。
 * 事件流优先走 SSE（`PluginHost` 的 `subscribeJob`，自带轮询降级）；
 * 插件未加载（例如被禁用）时退回 4s 轮询作业详情接口。
 */

import {
  cancelPluginJob,
  getPluginJob,
  listPluginJobs,
  pausePluginJob,
  resumePluginJob,
  retryPluginJob,
} from "../api/plugins.js";
import { PluginHost } from "../pluginHost.js";

const POLL_INTERVAL_MS = 4000;
const MAX_LOG_LINES = 200;
// 终态来自 core/plugins/job_store.py:TERMINAL_STATUSES
const TERMINAL_STATUSES = ["completed", "failed", "cancelled", "aborted"];

// 作业状态标签（core/plugins/job_store.py:JOB_STATUSES）
const JOB_STATUS_LABELS = {
  queued: "排队中",
  running: "运行中",
  paused: "已暂停",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  aborted: "已中断",
};

// 条目状态标签（core/plugins/job_store.py:ITEM_STATUSES）
// 两类状态的取值有重叠（running/failed），但语义不同，故分开维护
const ITEM_STATUS_LABELS = {
  pending: "待处理",
  running: "处理中",
  done: "完成",
  failed: "失败",
  skipped: "跳过",
  awaiting_review: "待审批",
};

export default function pluginJobPanel() {
  return {
    showPluginJobPanel: false,
    pluginId: "",
    runId: "",
    panelTitle: "",
    job: null,
    items: [],
    logs: [],
    recentJobs: [],
    busy: false,
    errorMessage: "",

    init() {
      this._openHandler = (event) => this.open(event.detail || {});
      window.addEventListener("open-plugin-job-panel", this._openHandler);
    },

    destroy() {
      window.removeEventListener("open-plugin-job-panel", this._openHandler);
      this.stopStreaming();
    },

    open(detail = {}) {
      const pluginId = String(detail.pluginId || "");
      const runId = String(detail.runId || "");
      if (!pluginId || !runId) return;

      this.pluginId = pluginId;
      this.runId = runId;
      this.panelTitle = String(detail.title || "");
      this.items = [];
      this.logs = [];
      this.errorMessage = "";
      this.showPluginJobPanel = true;

      this.refresh();
      this.loadRecentJobs();
      this.startStreaming();
    },

    close() {
      this.showPluginJobPanel = false;
      this.stopStreaming();
    },

    // ---------------------------------------------------------------- 数据

    async refresh() {
      if (!this.pluginId || !this.runId) return;
      const data = await getPluginJob(this.pluginId, this.runId, { itemsLimit: 500 });
      if (!data.success) {
        this.errorMessage = data.msg || "读取作业失败";
        return;
      }
      this.job = data.job;
      this.items = data.job.items || [];
      this.errorMessage = "";
    },

    async loadRecentJobs() {
      const data = await listPluginJobs(this.pluginId, { limit: 8 });
      if (data.success) this.recentJobs = data.items || [];
    },

    startStreaming() {
      this.stopStreaming();

      const api = PluginHost.getPluginApi(this.pluginId);
      if (api && typeof api.subscribeJob === "function") {
        this._unsubscribe = api.subscribeJob(this.runId, {
          snapshot: (payload) => {
            if (payload) this.job = Object.assign({}, this.job || {}, payload);
          },
          item: (payload) => {
            if (!payload) return;
            const index = this.items.findIndex((item) => item.key === payload.item_key);
            const next = {
              key: payload.item_key,
              status: payload.status,
              result: payload.result || {},
              error: payload.error || "",
            };
            if (index >= 0) this.items.splice(index, 1, Object.assign({}, this.items[index], next));
            else this.items.push(next);
          },
          log: (payload) => {
            if (!payload) return;
            this.logs.push(payload);
            if (this.logs.length > MAX_LOG_LINES) this.logs.shift();
          },
          done: (payload) => {
            if (payload) this.job = Object.assign({}, this.job || {}, payload);
            this._unsubscribe = null;
            this.loadRecentJobs();
          },
        });
        return;
      }

      // 插件未加载（禁用/纯后端）→ 4s 轮询
      const tick = async () => {
        if (!this.showPluginJobPanel) return;
        await this.refresh();
        this._pollTimer = setTimeout(tick, POLL_INTERVAL_MS);
      };
      this._pollTimer = setTimeout(tick, 0);
    },

    stopStreaming() {
      if (this._unsubscribe) {
        this._unsubscribe();
        this._unsubscribe = null;
      }
      if (this._pollTimer) {
        clearTimeout(this._pollTimer);
        this._pollTimer = null;
      }
    },

    // ---------------------------------------------------------------- 操作

    async runAction(action) {
      if (this.busy || !this.pluginId || !this.runId) return;
      this.busy = true;
      try {
        let data = null;
        if (action === "cancel") data = await cancelPluginJob(this.pluginId, this.runId);
        else if (action === "pause") data = await pausePluginJob(this.pluginId, this.runId);
        else if (action === "resume") data = await resumePluginJob(this.pluginId, this.runId);
        else if (action === "retry_failed") data = await retryPluginJob(this.pluginId, this.runId, true);
        else if (action === "retry_all") data = await retryPluginJob(this.pluginId, this.runId, false);

        if (!data || !data.success) {
          this.errorMessage = (data && data.msg) || "操作失败";
          return;
        }

        if (action.startsWith("retry") && data.run_id) {
          this.runId = data.run_id;
          this.items = [];
        }
        await this.refresh();
      } finally {
        this.busy = false;
      }
    },

    selectJob(runId) {
      if (!runId || runId === this.runId) return;
      this.runId = runId;
      this.items = [];
      this.logs = [];
      this.refresh();
      this.startStreaming();
    },

    // ---------------------------------------------------------------- 渲染辅助

    /** 作业状态标签。 */
    statusLabel(status) {
      const key = String(status || "");
      return JOB_STATUS_LABELS[key] || ITEM_STATUS_LABELS[key] || key || "-";
    },

    /** 条目状态标签（与作业状态分开，避免 done/failed 等重叠值语义混淆）。 */
    itemStatusLabel(status) {
      const key = String(status || "");
      return ITEM_STATUS_LABELS[key] || JOB_STATUS_LABELS[key] || key || "待处理";
    },

    get isTerminal() {
      return TERMINAL_STATUSES.includes(String(this.job && this.job.status));
    },

    get progressPercent() {
      const total = Number((this.job && this.job.total) || 0);
      if (!total) return 0;
      const finished =
        Number(this.job.completed || 0) + Number(this.job.failed || 0) + Number(this.job.skipped || 0);
      return Math.min(100, Math.round((finished / total) * 100));
    },

    get counts() {
      const job = this.job || {};
      return {
        total: Number(job.total || 0),
        completed: Number(job.completed || 0),
        failed: Number(job.failed || 0),
        skipped: Number(job.skipped || 0),
      };
    },

    get failedCount() {
      return this.items.filter((item) => item.status === "failed").length;
    },

    itemSummary(item) {
      if (item.error) return item.error;
      const result = item.result || {};
      if (result && typeof result === "object") {
        const keys = Object.keys(result).filter((key) => key !== '_truncated');
        if (keys.length) return JSON.stringify(result).slice(0, 200);
        if (result._truncated) return '（结果过大已截断）';
      }
      return "";
    },
  };
}
