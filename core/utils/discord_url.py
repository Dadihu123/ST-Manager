"""Discord 频道 / 帖子 URL 解析工具。"""

from urllib.parse import urlparse

# 类脑论坛使用的 Discord 域名
DISCORD_DOMAINS = (
    'discord.com',
    'www.discord.com',
)


def extract_discord_thread_id(url):
    """从 Discord channels URL 解析类脑帖子 ID。

    支持格式:
    1. /channels/{guild}/{thread_id}
    2. /channels/{guild}/{channel_id}/{message_id} → 取中间 channel_id
    3. /channels/{guild}/{channel_id}/threads/{thread_id}
    4. 以上格式末尾可带 /0 等回顶参数

    Returns:
        str | None: 帖子 ID；无法解析时返回 None
    """
    if not url or not isinstance(url, str):
        return None

    try:
        parsed = urlparse(url.strip())
        domain = (parsed.netloc or '').lower()
        if not any(domain == d or domain.endswith('.' + d) for d in DISCORD_DOMAINS):
            return None

        path_parts = [p for p in parsed.path.strip('/').split('/') if p]
        if len(path_parts) < 3 or path_parts[0] != 'channels':
            return None

        # /channels/{guild}/{channel}/threads/{thread}[/0]
        if len(path_parts) >= 5 and path_parts[3] == 'threads':
            thread_id = path_parts[4]
            return thread_id if thread_id.isdigit() else None

        # /channels/{guild}/{thread}[/0]
        # 第 4 段为单数字回顶参数时仍取第 3 段
        if len(path_parts) == 3 or (
            len(path_parts) >= 4 and path_parts[3] in set('0123456789')
        ):
            thread_id = path_parts[2]
            return thread_id if thread_id.isdigit() else None

        # /channels/{guild}/{channel}/{message}[/...] → 中间段
        if len(path_parts) >= 4:
            thread_id = path_parts[2]
            return thread_id if thread_id.isdigit() else None

        return None
    except Exception:
        return None
