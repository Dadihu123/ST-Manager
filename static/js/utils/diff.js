/**
 * static/js/utils/diff.js
 * 文本比对工具 (依赖 recursiveSort)
 */

import { recursiveSort } from './data.js';

// 生成左右分栏的 HTML Diff
export function generateSideBySideDiff(oldObj, newObj) {
    if (!window.Diff) return { left: 'Diff lib missing', right: '' };

    try {
        // === 关键步骤：先排序，再序列化 ===
        // 使用 indent=2 统一格式
        const oldStr = JSON.stringify(recursiveSort(oldObj), null, 2);
        const newStr = JSON.stringify(recursiveSort(newObj), null, 2);

        // 使用 jsdiff 生成基于行的差异
        const diff = Diff.diffLines(oldStr, newStr);
        
        let leftHtml = '';
        let rightHtml = '';

        // 遍历 diff 块，尝试对齐
        diff.forEach(part => {
            // 转义 HTML
            const escape = (str) => str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            
            // 将文本按行分割，过滤掉最后的空行
            const lines = part.value.split('\n');
            if (lines[lines.length - 1] === '') lines.pop();

            lines.forEach(line => {
                const escapedLine = escape(line) || '&nbsp;'; // 空行显示为空格占位
                
                if (part.added) {
                    // 新增：右侧显示绿，左侧显示空占位
                    rightHtml += `<div class="diff-row add">${escapedLine}</div>`;
                    leftHtml  += `<div class="diff-row empty">&nbsp;</div>`; 
                } else if (part.removed) {
                    // 删除：左侧显示红，右侧显示空占位
                    leftHtml  += `<div class="diff-row del">${escapedLine}</div>`;
                    rightHtml += `<div class="diff-row empty">&nbsp;</div>`;
                } else {
                    // 未变：两侧都显示
                    leftHtml  += `<div class="diff-row">${escapedLine}</div>`;
                    rightHtml += `<div class="diff-row">${escapedLine}</div>`;
                }
            });
        });

        return { left: leftHtml, right: rightHtml };

    } catch (e) {
        console.error(e);
        return { left: `<div class="p-4 status-danger-text">Diff 生成失败: ${e.message}</div>`, right: '' };
    }
}

// 生成 HTML Diff 字符串 (单列模式)
export function generateHtmlDiff(oldObj, newObj) {
    if (!window.Diff) {
        return '<div class="p-4 status-danger-text">错误：Diff 库未加载，请检查网络或刷新页面。</div>';
    }

    try {
        const oldStr = JSON.stringify(oldObj, null, 2);
        const newStr = newObj ? JSON.stringify(newObj, null, 2) : "";

        const diff = Diff.diffLines(oldStr, newStr);
        
        let html = '';
        
        diff.forEach(part => {
            const colorClass = part.added ? 'diff-added' :
                            part.removed ? 'diff-removed' : 'opacity-60';
            
            const escapedValue = part.value
                .replace(/&/g, "&amp;")
                .replace(/</g, "&lt;")
                .replace(/>/g, "&gt;");

            html += `<span class="block whitespace-pre-wrap ${colorClass}">${escapedValue}</span>`;
        });

        return html;
    } catch (e) {
        console.error(e);
        return `<div class="p-4 status-danger-text">Diff 生成失败: ${e.message}</div>`;
    }
}
