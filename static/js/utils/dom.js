/**
 * static/js/utils/dom.js
 * DOM 操作与渲染工具 (修复版)
 */

export function updateCssVariable(name, value) {
    document.documentElement.style.setProperty(name, value);
}

export function applyFont(type) {
    let fontVal = 'ui-sans-serif, system-ui, sans-serif';
    if (type === 'serif') fontVal = 'ui-serif, Georgia, Cambria, "Times New Roman", Times, serif';
    if (type === 'mono') fontVal = 'ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace';
    updateCssVariable('--app-font-family', fontVal);
}

export function insertAtCursor(textarea, myValue) {
    if (textarea.selectionStart || textarea.selectionStart == '0') {
        var startPos = textarea.selectionStart;
        var endPos = textarea.selectionEnd;
        return textarea.value.substring(0, startPos)
            + myValue
            + textarea.value.substring(endPos, textarea.value.length);
    } else {
        return textarea.value + myValue;
    }
}


function escapeHtml(text) {
    return String(text || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

export function renderMarkdown(text) {
    if (!text) return '<span class="text-gray-500 italic">空内容</span>';
    let safeText = String(text);
    if (typeof marked !== 'undefined') {
        marked.setOptions({ breaks: true });
        try {
            return marked.parse(safeText);
        } catch (e) {
            console.error("Markdown parse error:", e);
            return safeText;
        }
    }
    return safeText;
}

export function updateInlineRenderContent(el, content, options = {}) {
    if (!el) return;

    const rawContent = String(content || '');
    const trimmed = rawContent.trim();
    const mode = options.mode || 'markdown';
    const isolated = Boolean(options.isolated);
    const emptyHtml = options.emptyHtml || '<span class="text-gray-500 italic">空内容</span>';

    if (!trimmed) {
        if (el.shadowRoot) {
            el.shadowRoot.innerHTML = `<div>${emptyHtml}</div>`;
        } else {
            el.innerHTML = emptyHtml;
        }
        return;
    }

    if (mode === 'html-component') {
        if (!el.shadowRoot) {
            el.attachShadow({ mode: 'open' });
        }
        updateShadowContent(el, rawContent, options);
        return;
    }

    const rendered = mode === 'markdown'
        ? renderMarkdown(rawContent)
        : `<div>${escapeHtml(rawContent).replace(/\n/g, '<br>')}</div>`;

    if (isolated && !el.shadowRoot) {
        el.attachShadow({ mode: 'open' });
    }

    if (el.shadowRoot) {
        el.shadowRoot.innerHTML = `
            <style>
                :host {
                    display: block;
                    color: inherit;
                }
                .inline-render {
                    display: block;
                    color: inherit;
                    min-width: 0;
                    overflow-wrap: anywhere;
                    word-break: break-word;
                }
                .inline-render img {
                    max-width: 100%;
                    height: auto;
                }
                .inline-render pre {
                    white-space: pre-wrap;
                    word-break: break-word;
                }
            </style>
            <div class="inline-render markdown-body">${rendered}</div>
        `;
        return;
    }

    el.innerHTML = rendered;
}

// === [核心修复] 智能渲染内容 ===
export function updateShadowContent(el, content, options = {}) {
    // 确保 Shadow Root 存在
    if (!el.shadowRoot) {
        el.attachShadow({ mode: 'open' });
    }

    const shadow = el.shadowRoot;
    const minHeight = Number.parseInt(options.minHeight, 10);
    const hostMinHeight = Number.isFinite(minHeight) ? `${Math.max(160, minHeight)}px` : '240px';
    const maxHeight = Number.parseInt(options.maxHeight, 10);
    const hostMaxHeight = Number.isFinite(maxHeight) ? `${Math.max(220, maxHeight)}px` : '560px';

    // 修复问题1：如果内容为空或为null（即关闭预览时），清空并返回
    if (content === null || content === undefined) {
        shadow.innerHTML = '';
        return;
    }

    let rawContent = content || "";
    const trimmedContent = rawContent.trim();

    // ============================================================
    // 0. HTML 片段智能前置检测
    // ============================================================
    // 如果内容显然是一个 HTML 组件代码块（以 < 开头，且包含特定标签），
    // 强制绕过 Markdown 解析，防止 parser 将缩进的 <style> 识别为代码块。
    const htmlFragmentRegex = /^\s*<(?:div|style|details|link|table|script|iframe)/i;
    let forceHtmlMode = false;

    // 如果是以 < 开头，并且不是 Markdown 的引用块 (>) 或 HTML 实体 (&)
    if (htmlFragmentRegex.test(trimmedContent)) {
        forceHtmlMode = true;
    }

    // ============================================================
    // 1. 智能提取逻辑 (多块识别增强版)
    // ============================================================

    let htmlPayload = "";
    let markdownCommentary = "";

    // 正则：循环查找有效代码块
    const codeBlockRegex = /```(?:html|xml|text|js|css|json)?\s*([\s\S]*?)```/gi;
    let match;
    let foundPayload = false;

    while ((match = codeBlockRegex.exec(rawContent)) !== null) {
        const blockContent = match[1];
        // 特征识别：如果是HTML结构
        if (blockContent.includes('<!DOCTYPE') ||
            blockContent.includes('<html') ||
            blockContent.includes('<script') ||
            blockContent.includes('export default') ||
            // 新增：识别复杂的 div/style 结构
            (blockContent.includes('<div') && blockContent.includes('<style'))) {

            htmlPayload = blockContent;
            markdownCommentary = rawContent.replace(match[0], "");
            foundPayload = true;
            break;
        }
    }

    // 兜底逻辑：如果没找到代码块标记，尝试直接识别
    if (!foundPayload) {
        // 如果命中了强制 HTML 模式，或者是完整网页结构
        if (forceHtmlMode || rawContent.includes('<!DOCTYPE') || rawContent.includes('<html') || rawContent.includes('<script')) {
            htmlPayload = rawContent;
            markdownCommentary = "";
        } else {
            markdownCommentary = rawContent;
        }
    }

    // 清理 ST 的特殊标签
    markdownCommentary = markdownCommentary.replace(/<open>|<\/open>/gi, "").trim();

    // ============================================================
    // 2. 渲染逻辑 (布局与样式隔离)
    // ============================================================

    const hasPayload = !!htmlPayload;
    shadow.innerHTML = '';

    // --- 2.1 注入宿主样式 ---
    const hostStyle = document.createElement('style');
    hostStyle.textContent = `
                :host {
                    display: block !important;
                    width: 100% !important;
                    min-height: ${hostMinHeight} !important;
                    max-height: ${hostMaxHeight} !important;
                    overflow: hidden !important;
                    background-color: var(--bg-body, #000);
                    border-radius: 6px;
                    position: relative;
                }
                iframe {
                    width: 100%;
                    height: ${hostMaxHeight};
                    border: none;
                    display: block;
                    background-color: transparent; /* 让 iframe 透明以透出背景 */
                }
            `;
    shadow.appendChild(hostStyle);

    if (hasPayload) {
        // --- 2.2 准备 Markdown 内容 ---
        let renderedMd = "";
        if (markdownCommentary) {
            if (typeof marked !== 'undefined') {
                renderedMd = marked.parse(markdownCommentary, { breaks: true });
            } else {
                renderedMd = `<p>${markdownCommentary.replace(/\n/g, "<br>")}</p>`;
            }
        }

        // --- 2.3 构造注入 CSS (核心修复点：解决布局问题) ---
        const injectionStyle = `
                    <style>
                        /* 强制重置 HTML/Body，覆盖用户卡片的 min-height: 100vh 或 overflow: hidden */
                        html, body {
                            height: auto !important;
                            min-height: 100% !important;
                            overflow-y: auto !important;
                            overflow-x: hidden !important;
                            margin: 0 !important;
                            padding: 0 !important;
                            width: 100% !important;
                            /* 适配你的代码背景色，防止白底 */
                            background-color: transparent !important;
                            color: #e5e7eb;
                            font-family: ui-sans-serif, system-ui, sans-serif;
                        }

                        body {
                            display: flex !important;
                            flex-direction: column !important;
                            /*align-items: center !important;*/
                            justify-content: flex-start !important;
                            position: relative !important;
                            padding-bottom: 20px !important;
                        }

                        /* Markdown 容器样式 */
                        #st-manager-note-container {
                            display: block !important;
                            width: 100% !important; 
                            box-sizing: border-box !important;
                            padding: 16px 24px !important;
                            flex-shrink: 0 !important;
                            background: #1e293b; 
                            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
                            color: #e2e8f0;
                            font-size: 14px;
                            line-height: 1.6;
                            z-index: 99999;
                            text-align: left;
                            white-space: pre-wrap !important; 
                        }
                        
                        /* 滚动条美化 (适配你的代码风格) */
                        ::-webkit-scrollbar { width: 8px; height: 8px; }
                        ::-webkit-scrollbar-track { background: transparent; }
                        ::-webkit-scrollbar-thumb { background: #4b5563; border-radius: 4px; }
                        ::-webkit-scrollbar-thumb:hover { background: #6b7280; }
                    </style>
                `;

        // --- 2.4 注入逻辑 ---
        let finalHtml = htmlPayload;

        // 如果有 Markdown 备注，将其包裹在一个 DIV 中插入
        const noteBlock = renderedMd
            ? `<div id="st-manager-note-container">${renderedMd}</div>`
            : "";

        const codeToInject = injectionStyle + noteBlock;

        // 尝试插入到 body 最前面，如果没有 body 则包裹之
        if (finalHtml.includes('<body')) {
            finalHtml = finalHtml.replace(/(<body[^>]*>)/i, `$1\n${codeToInject}`);
        } else if (finalHtml.includes('<html')) {
            finalHtml = finalHtml.replace('<html', `<html\n${codeToInject}`);
        } else {
            // 片段模式：直接拼接
            finalHtml = codeToInject + finalHtml;
        }

        // --- 2.5 Iframe 创建 ---
        const iframe = document.createElement('iframe');
        const blob = new Blob([finalHtml], { type: 'text/html' });
        const blobUrl = URL.createObjectURL(blob);
        iframe.src = blobUrl;

        iframe.onload = () => {
            URL.revokeObjectURL(blobUrl);
        };

        shadow.appendChild(iframe);
        return;
    }

    // 3. 纯文本 Markdown 模式 (保持上下滚动)
    const style = `
                <style>
                    :host {
                        display: block;
                        min-height: ${hostMinHeight};
                        max-height: ${hostMaxHeight};
                        width: 100%;
                        overflow: hidden;
                        background-color: transparent;
                        color: var(--text-main, #e5e7eb);
                        font-family: ui-sans-serif, system-ui, sans-serif;
                        font-size: 0.9rem;
                        line-height: 1.6;
                    }
                    .scroll-wrapper {
                        min-height: ${hostMinHeight};
                        max-height: ${hostMaxHeight};
                        width: 100%;
                        overflow-y: auto;
                        padding: 1rem;
                        box-sizing: border-box;
                    }
                    img { max-width: 100%; border-radius: 4px; }
                    a { color: var(--accent-main, #2563eb); }
                    blockquote { border-left: 4px solid var(--accent-main, #2563eb); padding-left: 1em; margin: 1em 0; opacity: 0.8; }
                    /* 代码块样式修复 */
                    pre { background: rgba(0,0,0,0.3); padding: 1em; border-radius: 6px; overflow-x: auto; }
                    code { font-family: monospace; }
                </style>
            `;

    let renderedHtml = rawContent;
    if (typeof marked !== 'undefined') {
        renderedHtml = marked.parse(rawContent || "", { breaks: true });
    } else {
        renderedHtml = (rawContent || "").replace(/\n/g, "<br>");
    }

    const htmlWrapper = renderedHtml || '<div style="color: gray; font-style: italic;">空内容</div>';
    shadow.innerHTML = style + `<div class="scroll-wrapper markdown-body">${htmlWrapper}</div>`;
}
