/**
 * static/js/api/wi.js
 * 世界书与剪切板 API
 */

// 获取世界书列表
export async function listWorldInfo(params) {
    // params: { search, type, page, page_size }
    const searchParams = new URLSearchParams(params);
    const res = await fetch('/api/world_info/list?' + searchParams.toString());
    return res.json();
}

// 获取世界书详情
export async function getWorldInfoDetail(payload) {
    // payload: { id, source_type, file_path, preview_limit?, force_full? }
    const res = await fetch('/api/world_info/detail', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 保存世界书
export async function saveWorldInfo(payload) {
    // payload: { save_mode, file_path, content, compact, name? }
    const res = await fetch('/api/world_info/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 获取世界书条目历史版本
export async function listWiEntryHistory(payload) {
    // payload: { source_type, source_id, file_path, entry_uid, limit? }
    const res = await fetch('/api/world_info/entry_history/list', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 新建全局世界书（ST 兼容格式）
export async function createWorldInfo(payload) {
    // payload: { name }
    const res = await fetch('/api/world_info/create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload || {})
    });
    return res.json();
}

// 上传世界书文件 (FormData)
export async function uploadWorldInfo(formData) {
    const res = await fetch('/api/upload_world_info', {
        method: 'POST',
        body: formData
    });
    return res.json();
}

// 删除世界书
export async function deleteWorldInfo(filePath) {
    const res = await fetch('/api/world_info/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_path: filePath })
    });
    return res.json();
}

// 迁移散乱 Lorebooks
export async function migrateLorebooks() {
    const res = await fetch('/api/tools/migrate_lorebooks', { method: 'POST' });
    return res.json();
}

// === 剪切板相关 ===

export async function clipboardList() {
    const res = await fetch('/api/wi/clipboard/list');
    return res.json();
}

export async function clipboardAdd(entry, overwriteId = null) {
    const res = await fetch('/api/wi/clipboard/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ entry: entry, overwrite_id: overwriteId })
    });
    return res.json();
}

export async function clipboardDelete(dbId) {
    const res = await fetch('/api/wi/clipboard/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ db_id: dbId })
    });
    return res.json();
}

export async function clipboardClear() {
    const res = await fetch('/api/wi/clipboard/clear', { method: 'POST' });
    return res.json();
}

export async function clipboardReorder(orderMap) {
    const res = await fetch('/api/wi/clipboard/reorder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ order_map: orderMap })
    });
    return res.json();
}
