/**
 * static/js/api/chat.js
 * SillyTavern 聊天记录相关 API
 */

export async function listChats(params = {}, options = {}) {
    const searchParams = new URLSearchParams(params);
    const res = await fetch('/api/chats/list?' + searchParams.toString(), { signal: options.signal });
    return res.json();
}

export async function getChatDetail(id, options = {}) {
    const res = await fetch('/api/chats/detail', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, ...options })
    });
    return res.json();
}

export async function getChatRange(id, options = {}) {
    const res = await fetch('/api/chats/range', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, ...options })
    });
    return res.json();
}

export async function updateChatMeta(payload) {
    const res = await fetch('/api/chats/update_meta', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

export async function bindChatToCard(payload) {
    const res = await fetch('/api/chats/bind', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

export async function saveChat(payload) {
    const res = await fetch('/api/chats/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

export async function deleteChat(id) {
    const res = await fetch('/api/chats/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id })
    });
    return res.json();
}

export async function searchChats(payload) {
    const res = await fetch('/api/chats/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    });
    return res.json();
}

export async function importChats(formData) {
    const res = await fetch('/api/chats/import', {
        method: 'POST',
        body: formData
    });
    return res.json();
}
