import re
import logging
import requests
from html.parser import HTMLParser
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def get_discord_config():
    """从配置读取Discord认证信息"""
    try:
        from core.config import load_config
        cfg = load_config()
        return {
            'auth_type': cfg.get('discord_auth_type', 'token'),
            'bot_token': cfg.get('discord_bot_token', '').strip(),
            'user_cookie': cfg.get('discord_user_cookie', '').strip()
        }
    except Exception as e:
        logger.error(f"读取Discord配置失败: {e}")
        return {'auth_type': 'token', 'bot_token': '', 'user_cookie': ''}


class ForumTagFetcher:
    """
    论坛标签获取器
    支持从Discord论坛频道URL抓取标签信息
    """
    
    # Discord域名（类脑论坛是Discord的论坛频道）
    DISCORD_DOMAINS = [
        'discord.com',
        'www.discord.com',
    ]
    
    def __init__(self, timeout=30, discord_token=None, discord_cookie=None):
        self.timeout = timeout
        self.discord_token = discord_token
        self.discord_cookie = discord_cookie
    
    def is_valid_discord_url(self, url):
        """检查是否是有效的Discord论坛URL"""
        if not url:
            return False
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            path_parts = parsed.path.strip('/').split('/')
            
            # 检查是否是Discord域名
            is_discord = any(domain.endswith(d) for d in self.DISCORD_DOMAINS)
            if not is_discord:
                return False
            
            # 检查路径格式: /channels/{guild_id}/{channel_id}/threads/{thread_id}
            if len(path_parts) >= 5 and path_parts[0] == 'channels':
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"URL解析失败: {e}")
            return False
    
    def _parse_discord_thread_url(self, url):
        """
        解析Discord线程URL
        格式: https://discord.com/channels/{guild_id}/{channel_id}/threads/{thread_id}
        返回: (guild_id, channel_id, thread_id) 或 (None, None, None)
        """
        try:
            parsed = urlparse(url)
            path_parts = parsed.path.strip('/').split('/')
            
            if len(path_parts) >= 5 and path_parts[0] == 'channels':
                return path_parts[1], path_parts[2], path_parts[4]
            return None, None, None
        except Exception as e:
            logger.error(f"解析Discord URL失败: {e}")
            return None, None, None
    
    def _fetch_discord_thread_tags(self, guild_id, channel_id, thread_id):
        """
        使用Discord API获取线程的标签信息
        需要Bot Token或User Token认证
        """
        try:
            # Discord API端点
            api_url = f"https://discord.com/api/v10/channels/{thread_id}"
            
            # 构造请求头，模拟浏览器以减少 403 风险
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
            
            # 添加认证信息
            if self.discord_token:
                # 处理Token前缀
                token = self.discord_token
                if token.startswith("Bearer "):
                    token = token.replace("Bearer ", "", 1).strip()
                headers["Authorization"] = token if token.startswith("Bot ") else token
            elif self.discord_cookie:
                # 清理并设置Cookie
                cleaned_cookie = self.discord_cookie.strip().replace('\n', ' ').replace('\r', ' ')
                headers["Cookie"] = cleaned_cookie
                # Cookie认证时添加Referer和其他必要头
                headers["Referer"] = f"https://discord.com/channels/{guild_id}/{channel_id}"
                
                # 添加Discord API所需的额外请求头
                import base64
                import json
                # X-Super-Properties 包含浏览器指纹信息
                super_properties = {
                    "os": "Windows",
                    "browser": "Chrome",
                    "device": "",
                    "system_locale": "zh-CN",
                    "browser_user_agent": headers["User-Agent"],
                    "browser_version": "120.0.0.0",
                    "os_version": "10",
                    "referrer": "",
                    "referring_domain": "",
                    "referrer_current": "",
                    "referring_domain_current": "",
                    "release_channel": "stable",
                    "client_build_number": 9999,
                    "client_event_source": None
                }
                super_props_b64 = base64.b64encode(json.dumps(super_properties).encode()).decode()
                headers["X-Super-Properties"] = super_props_b64
                headers["X-Discord-Locale"] = "zh-CN"
                headers["X-Debug-Options"] = "bugReporterEnabled"
                headers["sec-ch-ua"] = '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"'
                headers["sec-ch-ua-mobile"] = "?0"
                headers["sec-ch-ua-platform"] = '"Windows"'
            
            response = requests.get(api_url, headers=headers, timeout=self.timeout)
            
            if response.status_code == 401:
                error_detail = ''
                try:
                    error_data = response.json()
                    error_detail = f" - {error_data.get('message', '')}"
                    logger.error(f"401错误详情: {error_data}")
                except:
                    error_detail = f" - {response.text[:200]}"
                logger.error(f"Discord认证失败 - 状态码: 401{error_detail}")
                logger.error("可能原因: 1) Cookie已过期 2) Cookie格式错误 3) 缺少必要请求头")
                return None, None, f'Discord认证失败{error_detail}，请检查Cookie是否有效且未过期'
            elif response.status_code == 403:
                error_detail = ''
                try:
                    error_data = response.json()
                    error_detail = f" - {error_data.get('message', '')}"
                    logger.error(f"403错误详情: {error_data}")
                except:
                    pass
                logger.error(f"Discord API 403错误: 请检查Token/Cookie是否已加入服务器并有权限查看频道")
                return None, None, f'Discord API 拒绝访问 (403): 请检查该 Token/Cookie 是否已加入对应的服务器，或是否有权限查看该频道{error_detail}'
            elif response.status_code == 404:
                return None, None, 'Discord线程不存在或已被删除'
            elif response.status_code != 200:
                error_text = response.text[:200]
                logger.error(f"Discord API错误响应: {error_text}")
                return None, None, f'Discord API返回错误: HTTP {response.status_code} - {error_text}'
            
            data = response.json()
            
            # 提取线程标题
            title = data.get('name', '')
            
            # 提取标签ID列表
            applied_tags = data.get('applied_tags', [])
            
            if not applied_tags:
                return [], title, None
            
            # 获取频道可用的标签定义
            parent_api_url = f"https://discord.com/api/v10/channels/{channel_id}"
            parent_response = requests.get(parent_api_url, headers=headers, timeout=self.timeout)
            
            if parent_response.status_code == 200:
                parent_data = parent_response.json()
                available_tags = parent_data.get('available_tags', [])
                
                # 构建标签ID到名称的映射
                tag_map = {tag['id']: tag['name'] for tag in available_tags}
                
                # 将标签ID转换为名称
                tag_names = [tag_map.get(tag_id, f"未知标签_{tag_id}") for tag_id in applied_tags]
                
                return tag_names, title, None
            else:
                # 如果无法获取父频道信息，返回原始标签ID
                logger.warning(f"无法获取父频道标签定义，返回原始标签ID")
                return [f"标签_{tag_id}" for tag_id in applied_tags], title, None
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Discord API请求失败: {e}")
            return None, None, f'网络请求失败: {e}'
        except Exception as e:
            logger.error(f"获取Discord标签时出错: {e}")
            return None, None, str(e)
    
    def fetch_tags(self, url):
        """
        从Discord URL抓取标签
        
        返回: {
            'success': bool,
            'tags': list,  # 标签列表
            'error': str,  # 错误信息(如果失败)
            'title': str   # 帖子标题(可选)
        }
        """
        if not self.is_valid_discord_url(url):
            logger.warning(f"URL验证失败: '{url}' 不是有效的Discord论坛URL")
            return {
                'success': False,
                'tags': [],
                'error': '无效的Discord论坛URL，格式应为: https://discord.com/channels/{guild_id}/{channel_id}/threads/{thread_id}',
                'title': None
            }
        
        # 检查是否有认证信息
        if not self.discord_token and not self.discord_cookie:
            logger.warning("未配置Discord认证信息")
            return {
                'success': False,
                'tags': [],
                'error': '未配置Discord认证，请在设置中配置Bot Token或User Cookie',
                'title': None
            }
        
        # 解析URL获取线程信息
        guild_id, channel_id, thread_id = self._parse_discord_thread_url(url)
        
        if not all([guild_id, channel_id, thread_id]):
            return {
                'success': False,
                'tags': [],
                'error': '无法解析Discord线程URL格式',
                'title': None
            }
        
        # 获取标签
        tags, title, error = self._fetch_discord_thread_tags(guild_id, channel_id, thread_id)
        
        if error:
            logger.warning(f"抓取Discord标签失败: {error}")
            return {
                'success': False,
                'tags': [],
                'error': error,
                'title': title
            }
        
        return {
            'success': True,
            'tags': tags,
            'error': None,
            'title': title
        }


class TagProcessor:
    """
    标签处理器
    支持标签过滤、替换和合并策略
    """
    
    def __init__(self, exclude_tags=None, replace_rules=None):
        """
        初始化处理器
        
        Args:
            exclude_tags: 要排除的标签列表，如 ['其他']
            replace_rules: 替换规则字典，如 {'其他': '杂项'}
        """
        self.exclude_tags = set(exclude_tags or [])
        self.replace_rules = replace_rules or {}
    
    def process(self, tags):
        """
        处理标签列表
        
        返回: 处理后的标签列表
        """
        result = []
        
        for tag in tags:
            # 跳过排除的标签
            if tag in self.exclude_tags:
                logger.debug(f"跳过排除标签: {tag}")
                continue
            
            # 应用替换规则
            processed_tag = self.replace_rules.get(tag, tag)
            
            # 去重添加
            if processed_tag not in result:
                result.append(processed_tag)
        
        return result
    
    def merge_tags(self, existing_tags, new_tags, mode='merge'):
        """
        合并标签
        
        Args:
            existing_tags: 现有标签列表
            new_tags: 新标签列表
            mode: 'merge' 合并(去重), 'replace' 替换(清空后添加)
        
        返回: 合并后的标签列表
        """
        if mode == 'replace':
            return list(new_tags)
        else:  # merge
            merged = list(existing_tags) if existing_tags else []
            for tag in new_tags:
                if tag not in merged:
                    merged.append(tag)
            return merged


# 单例实例
_tag_fetcher = None

def get_tag_fetcher():
    """获取标签获取器单例"""
    global _tag_fetcher
    if _tag_fetcher is None:
        # 从配置读取Discord认证信息
        config = get_discord_config()
        
        auth_type = config['auth_type']
        token = None
        cookie = None
        
        if auth_type == 'token':
            token = config['bot_token']
            if token:
                # 处理Token前缀（参考PR #3的实现）
                # 如果是Bearer开头，去掉Bearer前缀
                if token.startswith("Bearer "):
                    token = token.replace("Bearer ", "", 1).strip()
                # Bot Token需要保留"Bot "前缀，User Token不需要
                # 这里不做自动添加，由用户决定是否加"Bot "
        elif auth_type == 'cookie':
            cookie = config['user_cookie']
        
        _tag_fetcher = ForumTagFetcher(discord_token=token, discord_cookie=cookie)
    
    return _tag_fetcher
