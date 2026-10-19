/**
 * static/js/components/largeEditor.js
 * 通用大文本/富文本编辑器组件
 */

import {
  insertAtCursor,
  renderMarkdown,
  renderUnifiedPreviewHost,
  updateShadowContent,
} from "../utils/dom.js";
import { uploadNoteImage } from "../api/resource.js";

/**
 * Markdown 预览弹窗的默认底部提示。
 *
 * 该弹窗最初只服务「本地备注预览」，所以文案默认按本地备注写：备注只在详情页
 * 可编辑，这里提示用户去哪儿改。其它内容来源必须通过 `detail.footerHint`
 * 显式覆盖，否则会把「去详情页编辑」这句无关的话继承过去。
 */
export const MARKDOWN_VIEW_DEFAULT_FOOTER_HINT = "只读模式，如需编辑请进入详情页";

export default function largeEditor() {
  return {
    // === 本地状态 ===
    showLargeEditor: false,
    largeEditorTitle: "",
    largeEditorContent: "",

    // 字段追踪
    largeEditorField: "",
    largeEditorIsArray: false,
    largeEditorIndex: 0,

    // 预览状态
    markdownPreview: false,
    largeRenderMode: "markdown", // 'markdown' | 'html'

    // 独立 Markdown 预览弹窗状态
    showMarkdownModal: false,
    markdownModalContent: "",
    markdownModalTitle: "",
    // 底部只读提示。默认沿用「本地备注」语义（预览弹窗最初只服务本地备注），
    // 其它来源（如插件文档）可通过 detail.footerHint 覆盖成如实的说明。
    markdownModalFooterHint: MARKDOWN_VIEW_DEFAULT_FOOTER_HINT,

    // HTML 预览弹窗状态变量
    showLargePreview: false,
    regexTestResult: "",

    // 数据引用 (从 detailModal 传入)
    editingDataRef: null,

    renderUnifiedPreviewHost,
    renderMarkdown,
    updateShadowContent,

    get editingData() {
      return this.editingDataRef || {};
    },

    init() {
      // 监听打开事件
      window.addEventListener("open-large-editor", (e) => {
        const { field, title, isArray, index, editingData } = e.detail;
        this.openLargeEditor(field, title, isArray, index, editingData);
      });

      // 监听打开纯 Markdown 预览
      window.addEventListener("open-markdown-view", (e) => {
        this.openMarkdownView(e.detail);
      });

      // 监听打开 HTML 预览
      window.addEventListener("open-html-preview", (e) => {
        // 复用逻辑
        this.regexTestResult = e.detail;
        this.showLargePreview = true;
      });
    },

    ensurePreviewState() {
      if (typeof this.markdownPreview !== "boolean") {
        this.markdownPreview = false;
      }
      if (!this.largeRenderMode) {
        this.largeRenderMode = "markdown";
      }
    },

    openLargeEditor(field, title, isArray = false, index = 0, editingData) {
      this.ensurePreviewState();
      this.largeEditorTitle = title;
      this.largeEditorField = field;
      this.largeEditorIsArray = isArray;
      this.largeEditorIndex = index;
      this.editingDataRef = editingData; // 持有引用

      // 获取内容
      if (editingData) {
        if (isArray) {
          this.largeEditorContent = editingData[field][index] || "";
        } else {
          this.largeEditorContent = editingData[field] || "";
        }
      } else {
        this.largeEditorContent = "";
      }

      this.markdownPreview = false;
      this.showLargeEditor = true;

      // 智能设置渲染模式
      if (["first_mes", "mes_example"].includes(field)) {
        this.largeRenderMode = "html";
      } else {
        this.largeRenderMode = "markdown";
      }
    },

    saveLargeEditor(closeModal = true) {
      if (!this.editingDataRef) return;

      if (this.largeEditorIsArray) {
        if (!this.editingDataRef[this.largeEditorField])
          this.editingDataRef[this.largeEditorField] = [];
        this.editingDataRef[this.largeEditorField][this.largeEditorIndex] =
          this.largeEditorContent;
      } else {
        this.editingDataRef[this.largeEditorField] = this.largeEditorContent;
      }

      if (closeModal) {
        this.showLargeEditor = false;
      }
    },

    // === 数组导航 ===

    prevLargeEditorItem() {
      if (!this.largeEditorIsArray || !this.editingDataRef) return;

      this.saveLargeEditor(false); // 保存当前

      let arr = this.editingDataRef[this.largeEditorField];
      if (!arr || arr.length === 0) return;

      let newIndex = this.largeEditorIndex - 1;
      if (newIndex < 0) newIndex = arr.length - 1;

      this.largeEditorIndex = newIndex;
      this.largeEditorContent = arr[newIndex] || "";

      // 动态标题 (针对 Alternate Greetings)
      if (this.largeEditorField === "alternate_greetings") {
        this.largeEditorTitle = `备用开场白 #${newIndex + 1}`;
        // 通知父组件同步索引 (可选，视需求)
      }
    },

    nextLargeEditorItem() {
      if (!this.largeEditorIsArray || !this.editingDataRef) return;

      this.saveLargeEditor(false);

      let arr = this.editingDataRef[this.largeEditorField];
      if (!arr || arr.length === 0) return;

      let newIndex = this.largeEditorIndex + 1;
      if (newIndex >= arr.length) newIndex = 0;

      this.largeEditorIndex = newIndex;
      this.largeEditorContent = arr[newIndex] || "";

      if (this.largeEditorField === "alternate_greetings") {
        this.largeEditorTitle = `备用开场白 #${newIndex + 1}`;
      }
    },

    // === 预览功能 ===

    openMarkdownView(detail) {
      this.ensurePreviewState();

      // 兼容两种 detail 形态：纯字符串（既有调用）与
      // { content, title, footerHint }（插件文档预览）
      const payload = typeof detail === "string" ? { content: detail } : (detail || {});
      const content = payload.content || "";
      if (!content) return;

      this.markdownModalTitle = String(payload.title || "");
      this.markdownModalContent = content;
      // 未显式给出就退回本地备注语义；给空串等于不显示底部提示
      this.markdownModalFooterHint =
        payload.footerHint === undefined
          ? MARKDOWN_VIEW_DEFAULT_FOOTER_HINT
          : String(payload.footerHint || "");
      this.showMarkdownModal = true;
    },

    resolvePreviewOptions() {
      const runtimeOptions = {
        runtimeOwner: "large-editor",
        runtimeLabel: "Large Editor Preview",
        scroll: true,
        minHeight: 220,
        maxHeight: 3200,
        renderMode: this.largeRenderMode,
      };

      if (
        !["first_mes", "mes_example", "alternate_greetings"].includes(
          this.largeEditorField,
        )
      ) {
        return runtimeOptions;
      }

      const regexScripts = Array.isArray(
        this.editingData?.extensions?.regex_scripts,
      )
        ? this.editingData.extensions.regex_scripts
        : [];

      return {
        ...runtimeOptions,
        applyDisplayRules: true,
        config: {
          displayRules: regexScripts,
        },
      };
    },

    // 更新统一预览宿主 (x-effect 调用)
    updatePreview(el) {
      if (this.markdownPreview) {
        renderUnifiedPreviewHost(el, this.largeEditorContent, {
          ...this.resolvePreviewOptions(),
        });
      }
    },

    // === 粘贴处理 (图片上传) ===

    handleNotePaste(e) {
      // 仅在本地备注字段启用
      if (this.largeEditorField !== "ui_summary") return;

      const items = (e.clipboardData || e.originalEvent.clipboardData).items;
      let blob = null;

      for (let i = 0; i < items.length; i++) {
        if (items[i].type.indexOf("image") === 0) {
          blob = items[i].getAsFile();
          break;
        }
      }

      if (blob) {
        e.preventDefault();

        const placeholder = `\n![Uploading image...]()\n`;
        // 更新 Content (同时更新 Textarea)
        this.largeEditorContent = insertAtCursor(e.target, placeholder);

        const formData = new FormData();
        formData.append("file", blob);

        uploadNoteImage(formData)
          .then((res) => {
            if (res.success) {
              const realMarkdown = `\n![image](${res.url})\n`;
              this.largeEditorContent = this.largeEditorContent.replace(
                placeholder,
                realMarkdown,
              );
            } else {
              alert("图片上传失败: " + res.msg);
              this.largeEditorContent = this.largeEditorContent.replace(
                placeholder,
                "",
              );
            }
          })
          .catch((err) => {
            alert("网络错误: " + err);
            this.largeEditorContent = this.largeEditorContent.replace(
              placeholder,
              "",
            );
          });
      }
    },
  };
}
