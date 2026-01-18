import requests
import re
import logging
import unicodedata
from datetime import datetime
from core.data.db_session import get_db

logger = logging.getLogger(__name__)

def normalize_text(text):
    """
    极度鲁棒的文本归一化，用于比对标题。
    1. Unicode 规范化 (NFKC: 统一全角半角等)
    2. 转小写
    3. 统一连字符、下划线为空格
    4. 去除首尾空格
    """
    if not text: return ""
    try:
        # 1. Unicode 规范化
        text = unicodedata.normalize('NFKC', str(text))
        # 2. 统一分隔符并转小写
        text = re.sub(r'[\s_\-]+', ' ', text).lower()
        return text.strip()
    except:
        return str(text).strip().lower()

def fetch_remote_metadata(source_link):
    """
    仅获取远程元数据 (名称, 版本, 日期等) 而不进行比对。
    用于导入或首次同步。
    """
    if 'chub.ai' in source_link:
        match = re.search(r'chub\.ai/characters/([^/]+/[^/?#]+)', source_link)
        if not match: return {"success": False, "msg": "无效链接"}
        full_path = match.group(1)
        api_url = f"https://api.chub.ai/api/characters/{full_path}"
        try:
            headers = {'User-Agent': 'Mozilla/5.0...'}
            resp = requests.get(api_url, headers=headers, timeout=10)
            if resp.status_code != 200: return {"success": False, "msg": f"API 状态码: {resp.status_code}"}
            data = resp.json()
            node = data.get('node', data)
            return {
                "success": True,
                "name": node.get('name', ''),
                "version": node.get('version', ''),
                "updated_at": node.get('updated_at', '')
            }
        except Exception as e: return {"success": False, "msg": str(e)}
        
    elif 'discord.com' in source_link:
        from core.config import current_config
        token = str(current_config.get('discord_token', '')).strip()
        if not token: return {"success": False, "msg": "未配置 Discord Token"}
        
        match = re.search(r'discord\.com/channels/(\d+)/(\d+)(?:/(\d+))?', source_link)
        if not match: return {"success": False, "msg": "无效链接"}
        _, ch_id, msg_id = match.groups()
        headers = {"Authorization": token if token.startswith("Bot ") else token}
        
        try:
            # 1. 获取帖子标题
            name = ""
            ch_resp = requests.get(f"https://discord.com/api/v10/channels/{ch_id}", headers=headers, timeout=5)
            if ch_resp.status_code == 200:
                name = ch_resp.json().get('name', '')
            
            # 2. 获取最新消息日期
            updated_at = ""
            api_url = f"https://discord.com/api/v10/channels/{ch_id}/messages"
            if msg_id: api_url += f"/{msg_id}"
            else: api_url += "?limit=1"
            
            m_resp = requests.get(api_url, headers=headers, timeout=5)
            if m_resp.status_code == 200:
                m_data = m_resp.json()
                if isinstance(m_data, list) and m_data: m_data = m_data[0]
                updated_at = m_data.get('edited_timestamp') or m_data.get('timestamp') or ""
                
            return {
                "success": True,
                "name": name,
                "version": "", # Discord 通常不在 API 字段里写版本，而是在标题
                "updated_at": updated_at
            }
        except Exception as e: return {"success": False, "msg": str(e)}
        
    return {"success": False, "msg": "不支持的来源类型"}

def check_chub_update(card_id, source_link, synced_title=None):
    # ... (原有代码)
    try:
        # 1. 提取 Chub 路径
        match = re.search(r'chub\.ai/characters/([^/]+/[^/?#]+)', source_link)
        if not match:
            return {"success": False, "msg": "不是有效的 Chub.ai 链接"}

        full_path = match.group(1)
        api_url = f"https://api.chub.ai/api/characters/{full_path}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        }
        
        resp = requests.get(api_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {"success": False, "msg": f"API请求失败: {resp.status_code}"}
            
        data = resp.json()
        # Chub API 响应可能直接是对象，也可能包装在 node 中
        node = data.get('node', data)
        if not node or not isinstance(node, dict):
            return {"success": False, "msg": "API 响应格式异常"}
            
        remote_name = node.get('name', '')
        remote_version = node.get('version', '')
        remote_updated_at_str = node.get('updated_at', '') 
        
        # 2. 获取本地数据
        db = get_db()
        row = db.execute("SELECT char_version, last_modified FROM card_metadata WHERE id = ?", (card_id,)).fetchone()
        if not row:
            return {"success": False, "msg": "本地卡片不存在"}
            
        local_version = str(row['char_version'] or '').strip()
        local_mtime = row['last_modified']
        
        has_update = False
        update_info = {
            "remote_version": str(remote_version).strip(),
            "remote_updated_at": remote_updated_at_str,
            "local_version": local_version,
            "reason": ""
        }
        
        # 判定 1: 论坛标题比对 (优先)
        if synced_title and remote_name:
            s_title = normalize_text(synced_title)
            r_title = normalize_text(remote_name)
            
            if s_title != r_title:
                has_update = True
                update_info["reason"] = f"论坛标题变动: {s_title} -> {r_title}"
            else:
                # 关键修复：如果标题匹配且已同步，则不再检测时间戳和版本号
                # 这样可以避免因为远程元数据微调导致的频繁误报
                return {
                    "success": True,
                    "has_update": False,
                    "update_info": update_info,
                    "download_url": f"https://chub.ai/api/characters/{full_path}/download"
                }

        # 判定 2: 版本号比对
        if not has_update:
            rv_str = str(remote_version).strip()
            if rv_str:
                clean_rv = re.sub(r'^[vV]', '', rv_str)
                clean_lv = re.sub(r'^[vV]', '', local_version)
                if clean_rv != clean_lv:
                    has_update = True
                    update_info["reason"] = f"版本号更新: {local_version} -> {remote_version}"
        
        # 判定 3: 修改时间 (即便没有版本号也能检测)
        if not has_update and remote_updated_at_str:
            try:
                # 处理 ISO 时间 (适配 Z)
                clean_ts = remote_updated_at_str.replace('Z', '+00:00')
                remote_dt = datetime.fromisoformat(clean_ts)
                remote_ts = remote_dt.timestamp()
                
                # 如果远程更新时间晚于本地文件修改时间 (允许 10 分钟误差/延迟)
                if remote_ts > local_mtime + 600:
                    has_update = True
                    update_info["reason"] = f"远程有更晚的更新记录 ({remote_updated_at_str})"
            except Exception as e:
                logger.warning(f"Chub date parse error: {e}")

        return {
            "success": True, 
            "has_update": has_update,
            "update_info": update_info,
            "download_url": f"https://chub.ai/api/characters/{full_path}/download"
        }
    except Exception as e:
        logger.error(f"Check update error: {e}")
        return {"success": False, "msg": str(e)}

def check_discord_update(card_id, source_link, synced_title=None):
    """
    检查 Discord 消息是否有更新。
    需要用户在 config.json 中配置 'discord_token'。
    """
    from core.config import current_config
    token = current_config.get('discord_token', '')
    
    # 容错处理：确保 token 是字符串
    if isinstance(token, dict):
        token = token.get('token', '') or token.get('value', '') or ""
    
    token = str(token).strip()
    if token.startswith("Bearer "):
        token = token.replace("Bearer ", "", 1).strip()

    if not token or token == "" or token.startswith("{"):
        return {
            "success": False, 
            "msg": "未配置有效的 Discord Token 或 Token 格式错误。\n"
                   "请在设置中重新添加 discord_token (支持 Bot Token 或 User Token)。"
        }

    try:
        match = re.search(r'discord\.com/channels/(\d+)/(\d+)(?:/(\d+))?', source_link)
        if not match:
            return {"success": False, "msg": "无效的 Discord 链接格式"}
            
        guild_id, channel_id, message_id = match.groups()
        
        # 构造请求头，模拟浏览器以减少 403 风险 (尤其是 User Token)
        headers = {
            "Authorization": token if token.startswith("Bot ") else token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Content-Type": "application/json"
        }
        
        # 1. 获取频道/帖子信息 (用于获取帖子名称)
        channel_name = ""
        try:
            ch_resp = requests.get(f"https://discord.com/api/v10/channels/{channel_id}", headers=headers, timeout=5)
            if ch_resp.status_code == 200:
                ch_data = ch_resp.json()
                channel_name = ch_data.get('name', '') # 这就是“帖子名称”
        except:
            pass

        api_url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
        if message_id:
            api_url = f"https://discord.com/api/v10/channels/{channel_id}/messages/{message_id}"
            params = {}
        else:
            # 如果没有指定消息 ID，尝试获取该频道最近的几条消息，寻找有附件的那条
            params = {"limit": 10}
            
        resp = requests.get(api_url, headers=headers, params=params, timeout=10)
        if resp.status_code == 401:
            return {"success": False, "msg": "Discord Token 无效或已过期"}
        if resp.status_code == 403:
            return {"success": False, "msg": "Discord API 拒绝访问 (403): 请检查该 Token 是否已加入对应的服务器，或者是否有权限查看该频道。"}
        if resp.status_code != 200:
            return {"success": False, "msg": f"Discord API 请求失败: {resp.status_code}"}
            
        msg_list = resp.json()
        target_msg = None
        
        if message_id:
            target_msg = msg_list
        else:
            # 遍历最近 10 条消息，找到第一条包含 PNG 的消息
            for m in msg_list:
                if any(att.get('filename', '').lower().endswith('.png') for att in m.get('attachments', [])):
                    target_msg = m
                    break
            if not target_msg and msg_list:
                target_msg = msg_list[0] # 回退到最新一条
        
        if not target_msg:
            return {"success": False, "msg": "未找到有效的 Discord 消息内容"}
            
        # 3. 查找附件
        attachments = target_msg.get('attachments', [])
        png_attachments = [a for a in attachments if a.get('filename', '').lower().endswith('.png')]
        
        latest_att = png_attachments[0] if png_attachments else None
        remote_url = latest_att.get('url') if latest_att else ""
        
        # 4. 获取本地数据对比
        db = get_db()
        row = db.execute("SELECT char_name, char_version, last_modified, file_size FROM card_metadata WHERE id = ?", (card_id,)).fetchone()
        if not row:
            return {"success": False, "msg": "本地卡片不存在"}
            
        local_mtime = row['last_modified']
        local_size = row['file_size']
        local_name = row['char_name']

        # 5. 更新判定逻辑
        has_update = False
        reason = ""
        
        # 判定 A: 论坛标题/频道名称比对 (最高优先级)
        # 只要同步过标题，就以标题是否变动为第一准则
        if synced_title and channel_name:
            s_title = normalize_text(synced_title)
            r_title = normalize_text(channel_name)
            
            if s_title != r_title:
                has_update = True
                reason = f"论坛标题变动: {s_title} -> {r_title}"
            else:
                # 关键修复：如果标题完全匹配，则不再向下执行模糊检测（大小、时间戳等）
                # 这样可以确保只要发帖人没改帖子标题，就不会产生骚扰式更新提醒
                return {
                    "success": True,
                    "has_update": False,
                    "update_info": {
                        "remote_version": channel_name or "Discord 帖子",
                        "remote_updated_at": target_msg.get('edited_timestamp') or target_msg.get('timestamp'),
                        "reason": ""
                    },
                    "download_url": remote_url
                }

        # 判定 B: 帖子标题内部提取的版本/日期标记 (回退方案)
        if not has_update:
            # 1. 尝试匹配 1.17 或 v1.1
            remote_ver_match = re.search(r'[vV]?(\d+\.\d+(?:\.\d+)?)', channel_name)
            # 2. 尝试匹配 1月17日
            remote_date_match = re.search(r'(\d{1,2})月(\d{1,2})日?', channel_name)
            
            rv = None
            rv_is_date = False
            if remote_ver_match: 
                rv = remote_ver_match.group(1)
            elif remote_date_match: 
                rv = f"{remote_date_match.group(1)}.{remote_date_match.group(2)}"
                rv_is_date = True
            
            # 提取本地版本或日期标识
            local_ver_match = re.search(r'[vV]?(\d+\.\d+(?:\.\d+)?)', local_name)
            local_date_match = re.search(r'(\d{1,2})月(\d{1,2})日?', local_name)
            
            lv = None
            lv_is_date = False
            if local_ver_match: 
                lv = local_ver_match.group(1)
            elif local_date_match: 
                lv = f"{local_date_match.group(1)}.{local_date_match.group(2)}"
                lv_is_date = True
            
            # 只有当两者类型一致（都是日期或都不是日期）时，才直接比对
            # 或者当远程版本确实存在且不同于本地时触发
            if rv and lv != rv:
                # 额外保护：如果一个是日期一个是三段式版本号，通常不具有可比性，跳过
                if rv_is_date and lv and lv.count('.') >= 1 and not lv_is_date:
                    pass 
                else:
                    has_update = True
                    reason = f"帖子内容显示新动态: {channel_name}"

        # 判定 C: 消息最后修改时间
        if not has_update:
            remote_ts_str = target_msg.get('edited_timestamp') or target_msg.get('timestamp')
            if remote_ts_str:
                remote_dt = datetime.fromisoformat(remote_ts_str.replace('Z', '+00:00'))
                if remote_dt.timestamp() > local_mtime + 600:
                    has_update = True
                    reason = f"内容于 {remote_ts_str} 发生变动"

        # 判定 C: 文件大小变化
        if not has_update and latest_att and latest_att.get('size') != local_size:
            has_update = True
            reason = "卡片附件大小已改变"
                
        return {
            "success": True,
            "has_update": has_update,
            "update_info": {
                "remote_version": channel_name or "Discord 帖子",
                "remote_updated_at": target_msg.get('edited_timestamp') or target_msg.get('timestamp'),
                "reason": reason
            },
            "download_url": remote_url
        }

    except Exception as e:
        logger.error(f"Discord check error: {e}")
        return {"success": False, "msg": str(e)}
