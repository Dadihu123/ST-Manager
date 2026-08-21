/**
 * Discord channels URL → 类脑帖子 ID
 * 与后端 core/utils/discord_url.py 规则保持一致
 */

/**
 * @param {string} url
 * @returns {string|null}
 */
export function extractDiscordThreadId(url) {
  if (!url || typeof url !== 'string') return null;

  try {
    const parsed = new URL(url.trim());
    const host = (parsed.hostname || '').toLowerCase();
    if (host !== 'discord.com' && host !== 'www.discord.com') return null;

    const parts = parsed.pathname.replace(/^\/+|\/+$/g, '').split('/').filter(Boolean);
    if (parts.length < 3 || parts[0] !== 'channels') return null;

    // /channels/{guild}/{channel}/threads/{thread}
    if (parts.length >= 5 && parts[3] === 'threads') {
      return /^\d+$/.test(parts[4]) ? parts[4] : null;
    }

    // /channels/{guild}/{thread}[/0]
    if (parts.length === 3 || (parts.length >= 4 && /^[0-9]$/.test(parts[3]))) {
      return /^\d+$/.test(parts[2]) ? parts[2] : null;
    }

    // /channels/{guild}/{channel}/{message} → 中间段
    if (parts.length >= 4) {
      return /^\d+$/.test(parts[2]) ? parts[2] : null;
    }

    return null;
  } catch (_) {
    return null;
  }
}

/** 是否可展示类脑搜索按钮 */
export function canPreviewForumThread(sourceLink) {
  return !!extractDiscordThreadId(sourceLink);
}
