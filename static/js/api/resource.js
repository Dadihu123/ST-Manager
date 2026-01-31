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

// 上传本地备注图片
export async function uploadNoteImage(formData) {
    // 这是一个 POST 请求，body 为 FormData
    const res = await fetch('/api/upload_note_image', {
        method: 'POST',
        body: formData
    });
    return res.json();
}

// 将皮肤设为封面
export async function setSkinAsCover(payload) {
    // payload: { card_id, skin_filename, save_old }
    const res = await fetch('/api/set_skin_cover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 删除资源文件 (皮肤)
export async function deleteResourceFile(payload) {
    // payload: { card_id, filename }
    const res = await fetch('/api/delete_resource_file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 上传角色资源文件 (智能分流)
export async function uploadCardResource(formData) {
    const res = await fetch('/api/upload_card_resource', {
        method: 'POST',
        body: formData
    });
    return res.json();
}

// 保存独立脚本文件 (Regex / ST Script)
export async function saveScriptFile(payload) {
    const res = await fetch('/api/scripts/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 获取资源目录下的全量文件列表
export async function listResourceFiles(folderName) {
    const res = await fetch('/api/list_resource_files', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder_name: folderName })
    });
    return res.json();
}