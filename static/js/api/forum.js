/**
 * 类脑搜索站相关 API
 */

/** 按来源链接或卡片 ID 拉取帖子预览 */
export async function fetchForumThreadPreview(payload) {
  const res = await fetch('/api/forum/thread_preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });
  let data = null;
  try {
    data = await res.json();
  } catch (_) {
    data = { success: false, msg: '响应解析失败' };
  }
  if (!res.ok && data && !data.msg) {
    data.msg = `请求失败 (${res.status})`;
  }
  return data;
}
