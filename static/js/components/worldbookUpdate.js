import { previewWorldInfoUpdate, commitWorldInfoUpdate } from "../api/wi.js";
import { loadWorldbookDiff, readableWorldbook } from "../utils/worldbookDiff.js";

export default function worldbookUpdate() {
  // Keep the editor outside Alpine's reactive proxy; CodeMirror owns its lifecycle.
  let diff = null;
  let opener = null;
  let requestId = 0;
  return {
    show: false,
    target: null,
    step: "source",
    source: "file",
    url: "",
    file: null,
    busy: false,
    error: "",
    stale: false,
    currentText: "",
    sourceText: "",
    revision: "",
    view: "readable",
    previewReady: false,

    init() {
      window.addEventListener("open-worldbook-update", (event) => {
        if (this.busy || !["global", "resource"].includes(event.detail?.type)) return;
        diff?.destroy();
        diff = null;
        opener = document.activeElement;
        this.target = { ...event.detail };
        this.step = "source";
        this.source = "file";
        this.url = "";
        this.file = null;
        this.currentText = this.sourceText = this.revision = this.error = "";
        this.stale = false;
        this.view = "readable";
        this.previewReady = false;
        this.show = true;
        this.$nextTick(() => {
          if (this.$refs.file) this.$refs.file.value = "";
          this.$refs.close.focus();
        });
      });
    },

    close() {
      if (this.busy) return;
      requestId++;
      diff?.destroy();
      diff = null;
      this.show = false;
      this.currentText = this.sourceText = "";
      opener?.focus();
    },

    trapFocus(event) {
      if (!this.show) return;
      const controls = [...this.$refs.dialog.querySelectorAll("button:not(:disabled), input:not(:disabled), [tabindex='0']")].filter((node) => node.getClientRects().length);
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && event.target === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && event.target === last) { event.preventDefault(); first?.focus(); }
    },

    targetPayload() {
      return { file_path: this.target.path, source_type: this.target.type };
    },

    selectFile(file) {
      if (this.busy) return;
      this.file = file || null;
      this.error = "";
    },

    async preview(recompare = false) {
      if (this.busy) return;
      if (!recompare && this.source === "file" && !this.file) {
        this.error = "请选择世界书 JSON 文件";
        return;
      }
      if (!recompare && this.source === "url" && !this.url.trim()) {
        this.error = "请输入世界书 URL";
        return;
      }
      this.busy = true;
      this.error = "";
      const request = ++requestId;
      try {
        let payload = this.targetPayload();
        if (recompare) payload.source_text = this.sourceText;
        else if (this.source === "url") payload.url = this.url.trim();
        else {
          const form = new FormData();
          for (const [key, value] of Object.entries(payload)) form.append(key, value);
          form.append("file", this.file);
          payload = form;
        }
        const result = await previewWorldInfoUpdate(payload);
        if (request !== requestId) return;
        if (!result.success) throw new Error(result.msg || "无法取得世界书，请重试");
        this.currentText = result.current_text;
        this.sourceText = result.source_text;
        this.revision = result.source_revision;
        this.stale = false;
        this.step = "preview";
        await this.$nextTick();
        await this.renderDiff();
      } catch (error) {
        this.error = error.message || "获取失败，请重试";
      } finally {
        if (request === requestId) this.busy = false;
      }
    },

    async renderDiff() {
      this.previewReady = false;
      diff?.destroy();
      diff = null;
      const mount = await loadWorldbookDiff();
      if (!this.show || this.step !== "preview") return;
      const format = this.view === "readable" ? readableWorldbook : (text) => text;
      diff = mount(this.$refs.diff, format(this.currentText), format(this.sourceText));
      this.previewReady = true;
    },

    async switchView(view) {
      if (this.busy || this.view === view) return;
      this.view = view;
      this.busy = true;
      try { await this.renderDiff(); }
      catch (error) { this.error = error.message || "差异视图加载失败"; }
      finally { this.busy = false; }
    },

    changeSource() {
      if (this.busy) return;
      diff?.destroy();
      diff = null;
      this.step = "source";
      this.error = "";
      this.stale = false;
    },

    async commit() {
      if (this.busy || this.stale || !this.previewReady || this.step !== "preview") return;
      this.busy = true;
      this.error = "";
      try {
        const result = await commitWorldInfoUpdate({
          ...this.targetPayload(), source_text: this.sourceText, source_revision: this.revision,
        });
        if (!result.success) {
          if (result.code === "source_changed") this.stale = true;
          throw new Error(result.msg || "更新失败，请检查后重试");
        }
        window.dispatchEvent(new CustomEvent("wi-content-updated", { detail: { path: this.target.path } }));
        window.dispatchEvent(new CustomEvent("refresh-wi-list"));
        this.$store.global.showToast("世界书已更新，原内容已备份", 3000, "success");
        this.busy = false;
        this.close();
      } catch (error) {
        this.error = error.message || "更新失败，请重试";
      } finally { this.busy = false; }
    },
  };
}
