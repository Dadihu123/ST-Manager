/**
 * static/js/api/card.js
 * 角色卡相关 API 接口
 */

// 获取角色卡列表
export async function listCards(params) {
    // params: { page, page_size, category, tags, search, search_type, sort, recursive }
    const searchParams = new URLSearchParams(params);
    const res = await fetch('/api/list_cards?' + searchParams.toString());
    return res.json();
}

// 获取原始元数据 (JSON)
export async function getCardMetadata(id) {
    const res = await fetch('/api/get_raw_metadata', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
    });
    return res.json();
}

// 获取角色卡详情 (包含 UI 数据)
export async function getCardDetail(id) {
    const res = await fetch('/api/get_card_detail', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
    });
    return res.json();
}

// 更新角色卡 (Save)
export async function updateCard(payload) {
    const res = await fetch('/api/update_card', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 上传/更新角色卡文件 (FormData)
export async function updateCardFile(formData) {
    const res = await fetch('/api/update_card_file', {
        method: 'POST',
        body: formData // FormData 不需要手动设置 Content-Type
    });
    return res.json();
}

// 从 URL 更新角色卡
export async function updateCardFileFromUrl(payload) {
    // payload: { card_id, url, is_bundle_update, keep_ui_data }
    const res = await fetch('/api/update_card_from_url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 获取来源链接的元数据 (标题、版本等)
export async function fetchSourceMetadata(payload) {
    // payload: { source_link }
    const res = await fetch('/api/fetch_source_metadata', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 检查卡片在网络上的更新
export async function checkCardUpdate(payload) {
    // payload: { card_id, source_link }
    const res = await fetch('/api/check_card_update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 批量检查收藏卡片更新
export async function checkFavUpdates() {
    const res = await fetch('/api/check_fav_updates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    });
    return res.json();
}

// 删除角色卡
export async function deleteCards(ids) {
    const res = await fetch('/api/delete_cards', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ card_ids: ids })
    });
    return res.json();
}

// 随机角色卡
export async function getRandomCard(params) {
    // params: { category, tags, search, search_type }
    const res = await fetch('/api/random_card', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
    });
    return res.json();
}

// 发送到 SillyTavern
export async function sendToSillyTavern(cardId) {
    const res = await fetch('/api/send_to_st', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ card_id: cardId })
    });
    return res.json();
}

// 从 URL 导入新卡片
export async function importCardFromUrl(payload) {
    // payload: { url, category }
    const res = await fetch('/api/import_from_url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 批量上传卡片 (FormData)
export async function uploadCards(formData) {
    const res = await fetch('/api/upload_cards', {
        method: 'POST',
        body: formData
    });
    return res.json();
}

// 更换头像 (FormData)
export async function changeCardImage(formData) {
    const res = await fetch('/api/change_image', {
        method: 'POST',
        body: formData
    });
    return res.json();
}

// 转换为聚合包 (Bundle)
export async function convertToBundle(payload) {
    // payload: { card_id, bundle_name }
    const res = await fetch('/api/convert_to_bundle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 切换聚合模式状态 (Check/Enable/Disable)
export async function toggleBundleMode(payload) {
    // payload: { folder_path, action }
    const res = await fetch('/api/toggle_bundle_mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 定位卡片所在页码
export async function findCardPage(payload) {
    // payload: { card_id, category, sort, page_size }
    const res = await fetch('/api/find_card_page', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 移动卡片
export async function moveCard(payload) {
    // payload: { card_ids, target_category }
    const res = await fetch('/api/move_card', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

// 将特定版本设为封面
export async function setAsBundleCover(payload) {
    // payload: { id, bundle_dir, char_name }
    const res = await fetch('/api/update_card', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            id: payload.id,
            set_as_cover: true,
            bundle_dir: payload.bundle_dir,
            char_name: payload.char_name
        })
    });
    return res.json();
}
// 切换收藏
export async function toggleFavorite(cardId) {
    const res = await fetch('/api/toggle_favorite', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id: cardId })
    });
    return res.json();
}