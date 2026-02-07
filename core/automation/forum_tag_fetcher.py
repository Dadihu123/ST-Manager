import re
import logging
import requests
from html.parser import HTMLParser
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class NaobaijinTagParser(HTMLParser):
    """
    类脑论坛HTML标签解析器
    支持抓取主帖子的标签（tags_e5a45e 容器）
    忽略侧边栏推荐帖子的标签（tags__08166 等）
    """

    def __init__(self):
        super().__init__()
        self.tags = []
        self.in_tag_pill = False
        self.current_tag_text = []
        # 支持多种标签格式
        # 格式1: pill_a2c9e8 small_a2c9e8 tagPill__9a337 (有侧边栏)
        # 格式2: pill_a2c9e8 small_a2c9e8 (无侧边栏)
        self.tag_class_pattern = re.compile(r'pill_a2c9e8\s+small_a2c9e8')
        self.div_depth = 0
        self.expecting_text = False
        self.in_main_tags_container = False  # 是否进入主帖子标签容器
        self.main_container_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)

        if tag == 'div':
            class_attr = attrs_dict.get('class', '')

            # 只抓取主帖子的标签容器 tags_e5a45e
            # 忽略推荐帖子的 tags__08166（双下划线+数字）
            if 'tags_e5a45e' in class_attr:
                self.in_main_tags_container = True
                self.main_container_depth = 1
            elif self.in_main_tags_container:
                self.main_container_depth += 1

            # 只有在主帖子标签容器内才处理标签pill
            if self.in_main_tags_container:
                # 检查是否进入标签pill div
                # 匹配 pill_a2c9e8 small_a2c9e8 类的div
                if self.tag_class_pattern.search(class_attr):
                    # 排除带 +N 计数的pill (如 "+1")
                    # 这些通常包含 defaultColor__4bd52 类
                    if 'defaultColor__4bd52' not in class_attr:
                        self.in_tag_pill = True
                        self.div_depth = 1
                        self.expecting_text = True
                        self.current_tag_text = []
                elif self.in_tag_pill:
                    self.div_depth += 1
                    # 如果是内部的文字div，准备接收文本
                    if self.expecting_text and 'lineClamp1__4bd52' in class_attr:
                        self.expecting_text = False

    def handle_endtag(self, tag):
        if tag == 'div':
            # 处理主帖子标签容器结束
            if self.in_main_tags_container:
                self.main_container_depth -= 1
                if self.main_container_depth == 0:
                    self.in_main_tags_container = False

            # 处理标签pill结束
            if self.in_tag_pill:
                self.div_depth -= 1
                if self.div_depth == 0:
                    # 完成一个标签的解析
                    tag_text = ''.join(self.current_tag_text).strip()
                    # 排除 +N 计数标签和重复标签
                    if tag_text and not tag_text.startswith('+') and tag_text not in self.tags:
                        self.tags.append(tag_text)
                    self.in_tag_pill = False
                    self.current_tag_text = []

    def handle_data(self, data):
        if self.in_tag_pill:
            self.current_tag_text.append(data)


class ForumTagFetcher:
    """
    论坛标签获取器
    支持从类脑论坛帖子URL抓取标签信息
    """
    
    # 类脑论坛域名列表
    NAOBAIJIN_DOMAINS = [
        'naobaijin.app',
        'www.naobaijin.app',
    ]
    
    def __init__(self, timeout=30):
        self.timeout = timeout
        self.session = requests.Session()
        # 设置User-Agent模拟浏览器
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
    
    def is_valid_naobaijin_url(self, url):
        """检查是否是有效的类脑论坛URL"""
        if not url:
            return False
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            return any(domain.endswith(d) for d in self.NAOBAIJIN_DOMAINS)
        except:
            return False
    
    def _try_fetch(self, url):
        """
        尝试从URL抓取标签的内部方法
        返回: (tags, title, error) 元组，成功时error为None
        """
        try:
            logger.info(f"尝试抓取: {url}")
            response = self.session.get(url, timeout=self.timeout)
            response.raise_for_status()
            
            # 解析HTML
            parser = NaobaijinTagParser()
            parser.feed(response.text)
            parser.close()
            
            tags = parser.tags
            title = self._extract_title(response.text)
            
            if not tags:
                return None, title, '未找到标签'
            
            return tags, title, None
            
        except requests.exceptions.RequestException as e:
            return None, None, str(e)
        except Exception as e:
            return None, None, str(e)
    
    def fetch_tags(self, url):
        """
        从URL抓取标签
        策略：先尝试 /0 获取第一页，如果失败再尝试原始URL
        
        返回: {
            'success': bool,
            'tags': list,  # 标签列表
            'error': str,  # 错误信息(如果失败)
            'title': str   # 帖子标题(可选)
        }
        """
        if not self.is_valid_naobaijin_url(url):
            return {
                'success': False,
                'tags': [],
                'error': '无效的类脑论坛URL',
                'title': None
            }
        
        # 规范化URL：去除末尾斜杠
        url = url.rstrip('/')
        
        # 第一步：尝试 /0 获取第一页
        first_page_url = url + '/0'
        tags, title, error = self._try_fetch(first_page_url)
        
        if tags:
            logger.info(f"从第一页成功抓取到 {len(tags)} 个标签: {tags}")
            return {
                'success': True,
                'tags': tags,
                'error': None,
                'title': title
            }
        
        logger.info(f"第一页未找到标签，尝试原始URL: {url}")
        
        # 第二步：尝试原始URL
        tags, title2, error2 = self._try_fetch(url)
        
        if tags:
            logger.info(f"从原始URL成功抓取到 {len(tags)} 个标签: {tags}")
            return {
                'success': True,
                'tags': tags,
                'error': None,
                'title': title2 or title
            }
        
        # 都失败了
        logger.warning(f"无法从URL抓取标签: {url}")
        return {
            'success': False,
            'tags': [],
            'error': '未找到标签信息，帖子可能需要登录或页面格式不符',
            'title': title or title2
        }
    
    def _extract_title(self, html):
        """从HTML中提取帖子标题"""
        # 尝试多种方式提取标题
        patterns = [
            r'<title[^>]*>(.*?)</title>',
            r'<meta[^>]*property="og:title"[^>]*content="([^"]*)"',
            r'<h1[^>]*>(.*?)</h1>',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                title = match.group(1).strip()
                # 清理HTML实体
                title = re.sub(r'<[^>]+>', '', title)
                title = title.replace('&quot;', '"').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
                if title:
                    return title
        return None


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
        _tag_fetcher = ForumTagFetcher()
    return _tag_fetcher
