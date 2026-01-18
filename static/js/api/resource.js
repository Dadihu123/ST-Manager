/**
 * static/js/api/resource.js
 * 资源、皮肤与背景 API
 */

// 获取皮肤列表
export async function listSkins(folderName) {
    const res = await fetch('/api/list_resource_skins', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_name: folderName })
    });
    return res.json();
}

// 上传背景图 (FormData)
export async function uploadBackground(formData) {
    const res = await fetch('/api/upload_background', {
        method: 'POST',
        body: formData
    });
    return res.json();
}

// 设置角色资源目录
export async function setResourceFolder(payload) {
    // payload: { card_id, resource_path }
    const res = await fetch('/api/set_resource_folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 打开资源目录
export async function openResourceFolder(payload) {
    // payload: { card_id }
    const res = await fetch('/api/open_resource_folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 创建资源目录
export async function createResourceFolder(payload) {
    // payload: { card_id }
    const res = await fetch('/api/create_resource_folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// === 网页版文件管理器 API ===

export async function listResourceFiles(cardId) {
    const res = await fetch('/api/list_resource_files', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ card_id: cardId })
    });
    return res.json();
}

export async function deleteResourceFile(cardId, filename) {
    const res = await fetch('/api/delete_resource_file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ card_id: cardId, filename })
    });
    return res.json();
}

export async function uploadResourceFile(cardId, file) {
    const formData = new FormData();
    formData.append('card_id', cardId);
    formData.append('file', file);
    const res = await fetch('/api/upload_resource_file', {
        method: 'POST',
        body: formData
    });
    return res.json();
}

// 上传本地备注图片
export async function uploadNoteImage(formData) {
    // 这是一个 POST 请求，body 为 FormData
    const res = await fetch('/api/upload_note_image', {
        method: 'POST',
        body: formData
    });
    return res.json();
}