/**
 * static/js/utils/format.js
 * 格式化与计算工具函数
 */

// 格式化时间戳 (秒)
export function formatDate(ts, options = {}) {
    if (!ts) return '-';
    let dateValue = null;
    const includeYear = Boolean(options && options.includeYear);

    if (typeof ts === 'number') {
        dateValue = new Date(ts * 1000);
    } else if (typeof ts === 'string') {
        const trimmed = ts.trim();
        if (!trimmed) return '-';

        if (/^\d+(\.\d+)?$/.test(trimmed)) {
            dateValue = new Date(parseFloat(trimmed) * 1000);
        } else {
            const parsed = Date.parse(trimmed);
            if (!Number.isNaN(parsed)) {
                dateValue = new Date(parsed);
            }
        }
    }

    if (!dateValue || Number.isNaN(dateValue.getTime())) {
        return String(ts);
    }

    const formatOptions = {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    };

    if (includeYear) {
        formatOptions.year = 'numeric';
    }

    return dateValue.toLocaleString('zh-CN', formatOptions);
}

// 获取版本显示名称 (去掉后缀)
export function getVersionName(filename) {
    if (!filename) return "Unknown";
    // 移除 .png, .json 等后缀
    return filename.replace(/\.[^/.]+$/, "");
}

// 格式化 WI Keys 显示 (Array -> String)
export function formatWiKeys(keys) {
    if (Array.isArray(keys)) return keys.join(', ');
    return keys || "";
}

// Token 估算算法
export function estimateTokens(text) {
    if (!text) return 0;
    // 混合估算策略 (针对 2024/2025 主流模型 Llama3/Claude/GPT-4)：
    // 1. 中文字符 (CJK) 通常 1 字符 ≈ 1 Token
    // 2. 英文/数字/符号 通常 3~4 字符 ≈ 1 Token
    
    // 匹配中文字符范围
    const cjkCount = (text.match(/[\u4e00-\u9fa5]/g) || []).length;
    const otherCount = text.length - cjkCount;
    
    // 计算公式：中文数 + (其他字符数 / 3.5)
    return Math.ceil(cjkCount + (otherCount / 3.5));
}

export const TOKEN_THRESHOLDS = Object.freeze({
    CARD_WARN: 5000,
    CARD_DANGER: 20000,
    WI_DANGER: 10000,
    EXTREME: 100000
});

export function getTokenLevel(tokenCount, thresholds = {}) {
    const value = Number(tokenCount) || 0;
    const warn = Number(thresholds.warn || 0);
    const danger = Number(thresholds.danger || 0);
    const extreme = Number(thresholds.extreme || TOKEN_THRESHOLDS.EXTREME);

    if (value > extreme) return 'extreme';
    if (danger > 0 && value > danger) return 'danger';
    if (warn > 0 && value > warn) return 'warn';
    return 'ok';
}

export function getDetailMobileTokenClass(tokenCount) {
    const level = getTokenLevel(tokenCount, {
        warn: TOKEN_THRESHOLDS.CARD_WARN,
        danger: TOKEN_THRESHOLDS.CARD_DANGER,
        extreme: TOKEN_THRESHOLDS.EXTREME
    });

    if (level === 'extreme') return 'status-danger-text';
    if (level === 'danger') return 'status-warning-text';
    if (level === 'warn') return 'status-warning-text';
    return 'status-success-text';
}

export function getTopbarTokenLevelClass(tokenCount) {
    return getTokenLevel(tokenCount, {
        warn: TOKEN_THRESHOLDS.CARD_WARN,
        danger: TOKEN_THRESHOLDS.CARD_DANGER,
        extreme: TOKEN_THRESHOLDS.EXTREME
    });
}

export function getCardGridTokenBadgeClass(tokenCount) {
    const level = getTokenLevel(tokenCount, {
        warn: TOKEN_THRESHOLDS.CARD_WARN,
        danger: TOKEN_THRESHOLDS.CARD_DANGER,
        extreme: TOKEN_THRESHOLDS.EXTREME
    });

    if (level === 'extreme') return 'card-token-level-extreme';
    if (level === 'danger') return 'card-token-level-danger';
    if (level === 'warn') return 'card-token-level-warn';
    return 'card-token-level-ok';
}

export function getWiTokenClass(tokenCount, lowClass = 'status-success-text') {
    const level = getTokenLevel(tokenCount, {
        danger: TOKEN_THRESHOLDS.WI_DANGER,
        extreme: TOKEN_THRESHOLDS.EXTREME
    });

    if (level === 'extreme') return 'status-danger-text';
    if (level === 'danger') return 'status-warning-text';
    return lowClass;
}

// 计算世界书总 Token
export function getTotalWiTokens(entries) {
    if (!entries || !Array.isArray(entries)) return 0;
    let total = 0;
    entries.forEach(e => {
        // 只统计启用的
        if (e && e.enabled !== false) {
            total += estimateTokens(e.content);
        }
    });
    return total;
}

// 计算当前卡片总 Token (原 get totalTokenCount)
// 需要传入 cardData (editingData) 和 wiEntries (世界书条目数组)
export function calculateTotalTokens(cardData, wiEntries) {
    if (!cardData) return 0;

    // 聚合核心字段
    let text = (cardData.description || "") + 
               (cardData.first_mes || "") + 
               (cardData.mes_example || "");
    
    // 加上角色名
    text += (cardData.char_name || "");

    // 加上世界书 (只计算启用的条目)
    if (wiEntries && wiEntries.length > 0) {
        wiEntries.forEach(e => {
            if (!e) return; 
            // 如果 enabled 字段不存在，默认为 true；如果明确为 false 则跳过
            if (e.enabled !== false) {
                text += (e.content || "") + (Array.isArray(e.keys) ? e.keys.join('') : (e.keys || ""));
            }
        });
    }

    return estimateTokens(text);
}
