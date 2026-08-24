/**
 * static/js/api/automation.js
 */

export async function listRuleSets() {
    const res = await fetch('/api/automation/rulesets');
    return res.json();
}

export async function getRuleSet(id) {
    const res = await fetch(`/api/automation/rulesets/${id}`);
    return res.json();
}

export async function saveRuleSet(payload) {
    // payload: { id, meta, rules, ... }
    const res = await fetch('/api/automation/rulesets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

export async function deleteRuleSet(id) {
    const res = await fetch(`/api/automation/rulesets/${id}`, {
        method: 'DELETE'
    });
    return res.json();
}

export async function executeRules(payload) {
    // payload: { card_ids: [], ruleset_id: "..." }
    const res = await fetch('/api/automation/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

export async function getAutomationTargets(payload = {}) {
    const res = await fetch('/api/automation/targets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

export async function setGlobalRuleset(id) {
    const res = await fetch('/api/automation/global_setting', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ruleset_id: id })
    });
    return res.json();
}

export async function getGlobalRuleset() {
    const res = await fetch('/api/automation/global_setting');
    return res.json();
}

export async function importRuleSet(formData) {
    const res = await fetch('/api/automation/rulesets/import', {
        method: 'POST',
        body: formData
    });
    return res.json();
}

// 导出通常直接通过 window.open 或 a 标签触发 GET 请求，不需要 fetch 封装，
// 但为了统一，可以提供一个 helper 生成 URL
export function getExportRuleSetUrl(id) {
    return `/api/automation/rulesets/${id}/export`;
}
