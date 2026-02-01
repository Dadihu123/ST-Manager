"""
ST Client - SillyTavern 资源读取服务

支持两种读取模式：
1. 本地文件系统读取 - 直接读取 SillyTavern 的数据目录
2. API 读取 - 通过 st-api-wrapper 接口读取（需要 SillyTavern 运行）

@module st_client
@version 1.0.0
"""

import os
import json
import base64
import struct
import zlib
import logging
import requests
from typing import Optional, Dict, List, Any, Tuple
from core.config import load_config, BASE_DIR
from core.utils.regex import extract_regex_from_preset_data, extract_global_regex_from_settings

logger = logging.getLogger(__name__)

# SillyTavern 常见安装路径候选
ST_PATH_CANDIDATES = [
    # Windows 常见路径
    r"D:\SillyTavern",
    r"E:\SillyTavern",
    r"C:\SillyTavern",
    r"D:\Programs\SillyTavern",
    r"E:\Programs\SillyTavern",
    r"C:\Users\{user}\SillyTavern",
    # Linux/macOS 常见路径
    "/opt/SillyTavern",
    "~/SillyTavern",
    "/home/{user}/SillyTavern",
]

# SillyTavern 数据目录结构
ST_DATA_STRUCTURE = {
    "characters": "data/default-user/characters",
    "worlds": "data/default-user/worlds", 
    "presets": "data/default-user/OpenAI Settings",
    "regex": "data/default-user/regex",
    "scripts": "data/default-user/scripts",
    "quick_replies": "data/default-user/QuickReplies",
    "settings": "data/default-user/settings.json",
}


class STClient:
    """SillyTavern 资源客户端"""
    
    def __init__(self, st_data_dir: Optional[str] = None, st_url: Optional[str] = None):
        """
        初始化 ST 客户端
        
        Args:
            st_data_dir: SillyTavern 安装目录路径（本地模式）
            st_url: SillyTavern API URL（API 模式）
        """
        config = load_config()
        self.st_data_dir = st_data_dir or config.get('st_data_dir', '')
        self.st_url = st_url or config.get('st_url', 'http://127.0.0.1:8000')
        self.st_username = config.get('st_username', '')
        self.st_password = config.get('st_password', '')
        self.timeout = 30
        self.cache = {}
        self.cache_ttl = 60  # 缓存60秒
        
    # ==================== 路径探测 ====================
    
    def detect_st_path(self) -> Optional[str]:
        """
        自动探测 SillyTavern 安装路径
        
        Returns:
            探测到的路径，未找到返回 None
        """
        # 如果已配置，先验证
        if self.st_data_dir and os.path.exists(self.st_data_dir):
            if self._validate_st_path(self.st_data_dir):
                return self.st_data_dir
                
        # 获取当前用户名用于路径替换
        username = os.environ.get('USERNAME', os.environ.get('USER', ''))
        
        # 遍历候选路径
        for candidate in ST_PATH_CANDIDATES:
            path = candidate.replace('{user}', username)
            path = os.path.expanduser(path)
            
            if os.path.exists(path) and self._validate_st_path(path):
                logger.info(f"探测到 SillyTavern 路径: {path}")
                return path
                
        logger.warning("未能自动探测到 SillyTavern 安装路径")
        return None
    
    def _validate_st_path(self, path: str) -> bool:
        """验证路径是否为有效的 SillyTavern 安装目录"""
        if not path or not os.path.exists(path):
            return False

        # 允许传入根目录 / data / default-user
        normalized = os.path.normpath(path)
        indicators = [
            os.path.join(normalized, "data"),
            os.path.join(normalized, "data", "default-user"),
            os.path.join(normalized, "public"),
            os.path.join(normalized, "server.js"),
            os.path.join(normalized, "start.sh"),
            os.path.join(normalized, "Start.bat"),
            os.path.join(normalized, "package.json"),
            os.path.join(normalized, "config.yaml"),
            os.path.join(normalized, "settings.json"),
            os.path.join(normalized, "characters"),
            os.path.join(normalized, "worlds"),
        ]
        if any(os.path.exists(p) for p in indicators):
            return True

        # 允许传入 default-user 直接目录
        try:
            if os.path.basename(normalized).lower() == "default-user":
                return True
        except Exception:
            pass

        # 允许传入 data 目录或安装根目录，但用户目录非 default-user
        data_dir = normalized
        if os.path.basename(normalized).lower() != "data":
            data_dir = os.path.join(normalized, "data")
        if os.path.exists(data_dir) and os.path.isdir(data_dir):
            try:
                for entry in os.listdir(data_dir):
                    entry_path = os.path.join(data_dir, entry)
                    if not os.path.isdir(entry_path):
                        continue
                    if os.path.exists(os.path.join(entry_path, "settings.json")):
                        return True
                    if os.path.exists(os.path.join(entry_path, "characters")) or os.path.exists(os.path.join(entry_path, "worlds")):
                        return True
            except Exception:
                pass
        return False

    def _first_existing_path(self, candidates: List[str], want_dir: bool = True) -> Optional[str]:
        """返回第一个存在的路径（目录/文件）"""
        if not candidates:
            return None
        username = os.environ.get('USERNAME', os.environ.get('USER', ''))
        seen = set()
        for raw in candidates:
            if not raw:
                continue
            path = os.path.expanduser(raw.replace('{user}', username))
            path = os.path.normpath(path)
            if path in seen:
                continue
            seen.add(path)
            if os.path.exists(path):
                if want_dir and os.path.isdir(path):
                    return path
                if not want_dir and os.path.isfile(path):
                    return path
        return None

    def _candidate_roots(self) -> List[str]:
        roots = []
        if self.st_data_dir:
            roots.append(self.st_data_dir)
        # 已手动指定路径时，不再触发自动探测以避免误报日志
        if not self.st_data_dir:
            detected = self.detect_st_path()
            if detected:
                roots.append(detected)
        return roots

    def _find_user_dir_from_data_dir(self, data_dir: str) -> Optional[str]:
        if not data_dir or not os.path.exists(data_dir) or not os.path.isdir(data_dir):
            return None
        try:
            default_user = os.path.join(data_dir, "default-user")
            if os.path.exists(default_user) and os.path.isdir(default_user):
                return default_user
            # 选择最可能的用户目录：优先 settings.json，其次资源子目录数量
            candidates = []
            for name in os.listdir(data_dir):
                user_path = os.path.join(data_dir, name)
                if not os.path.isdir(user_path):
                    continue
                score = 0
                if os.path.exists(os.path.join(user_path, "settings.json")):
                    score += 5
                for sub in ["characters", "worlds", "OpenAI Settings", "presets", "regex", "QuickReplies", "scripts"]:
                    if os.path.exists(os.path.join(user_path, sub)):
                        score += 1
                if score > 0:
                    candidates.append((score, user_path))
            if candidates:
                candidates.sort(key=lambda x: (-x[0], x[1]))
                return candidates[0][1]
        except Exception:
            return None
        return None

    def _normalize_default_user_dir(self, path: str) -> Optional[str]:
        if not path:
            return None
        try:
            normalized = os.path.normpath(path)
            parts = normalized.split(os.sep)
            if "default-user" in parts:
                idx = parts.index("default-user")
                return os.sep.join(parts[: idx + 1])
            base = os.path.basename(normalized).lower()
            if base == "default-user":
                return normalized
            # 已是用户目录（自定义用户名）
            if os.path.exists(os.path.join(normalized, "settings.json")):
                return normalized
            if os.path.exists(os.path.join(normalized, "characters")) or os.path.exists(os.path.join(normalized, "worlds")):
                return normalized
            if base == "data":
                detected_user = self._find_user_dir_from_data_dir(normalized)
                return detected_user or os.path.join(normalized, "default-user")
            # 视为根目录
            data_dir = os.path.join(normalized, "data")
            if not os.path.exists(data_dir):
                parent = os.path.dirname(normalized)
                parent_data = os.path.join(parent, "data")
                if os.path.exists(parent_data):
                    data_dir = parent_data
            detected_user = self._find_user_dir_from_data_dir(data_dir)
            return detected_user or os.path.join(data_dir, "default-user")
        except Exception:
            return None

    def _candidate_user_dirs(self) -> List[str]:
        candidates = []
        for root in self._candidate_roots():
            user_dir = self._normalize_default_user_dir(root)
            if user_dir:
                candidates.append(user_dir)
        candidates.extend([
            os.path.join(os.getcwd(), "data", "default-user"),
            os.path.join(os.getcwd(), "..", "data", "default-user"),
            r"D:\SillyTavern\data\default-user",
            r"E:\SillyTavern\data\default-user",
            r"C:\SillyTavern\data\default-user",
        ])
        return candidates
    
    def get_st_subdir(self, resource_type: str) -> Optional[str]:
        """
        获取 SillyTavern 资源子目录的完整路径
        
        Args:
            resource_type: 资源类型 (characters/worlds/presets/regex/scripts/quick_replies)
            
        Returns:
            完整路径，未找到返回 None
        """
        if resource_type == "presets":
            return self.get_presets_dir()
        if resource_type == "regex":
            return self.get_regex_dir()
        if resource_type == "settings":
            return self.get_settings_path()

        st_path = self.st_data_dir or self.detect_st_path()
        if not st_path:
            return None

        subdir = ST_DATA_STRUCTURE.get(resource_type)
        if not subdir:
            return None

        # 允许 st_path 指向 data/default-user 或 data
        user_dir = self._normalize_default_user_dir(st_path)
        if user_dir:
            try:
                prefix = os.path.normpath(os.path.join("data", "default-user"))
                norm_subdir = os.path.normpath(subdir)
                rel = os.path.relpath(norm_subdir, prefix) if norm_subdir.startswith(prefix) else subdir
                full_path = os.path.join(user_dir, rel)
            except Exception:
                full_path = os.path.join(user_dir, subdir)
        else:
            full_path = os.path.join(st_path, subdir)

        if os.path.exists(full_path):
            return full_path
        return None

    def get_settings_path(self, custom_path: Optional[str] = None) -> Optional[str]:
        """获取 SillyTavern settings.json 路径"""
        if custom_path and os.path.exists(custom_path):
            return custom_path

        candidates = []
        for user_dir in self._candidate_user_dirs():
            candidates.append(os.path.join(user_dir, "settings.json"))

        for root in self._candidate_roots():
            candidates.append(os.path.join(root, "settings.json"))

        return self._first_existing_path(candidates, want_dir=False)

    def get_presets_dir(self, custom_path: Optional[str] = None) -> Optional[str]:
        """获取 SillyTavern 预设目录路径"""
        if custom_path and os.path.exists(custom_path):
            return custom_path

        candidates = []
        for user_dir in self._candidate_user_dirs():
            candidates.extend([
                os.path.join(user_dir, "OpenAI Settings"),
                os.path.join(user_dir, "presets"),
            ])

        for root in self._candidate_roots():
            candidates.extend([
                os.path.join(root, "OpenAI Settings"),
                os.path.join(root, "presets"),
                os.path.join(root, "public", "presets"),
            ])

        return self._first_existing_path(candidates, want_dir=True)

    def get_regex_dir(self, custom_path: Optional[str] = None) -> Optional[str]:
        """获取 SillyTavern 正则脚本目录路径"""
        if custom_path and os.path.exists(custom_path):
            return custom_path

        candidates = []
        for user_dir in self._candidate_user_dirs():
            candidates.append(os.path.join(user_dir, "regex"))

        for root in self._candidate_roots():
            candidates.extend([
                os.path.join(root, "regex"),
                os.path.join(root, "public", "scripts", "regex"),
            ])

        return self._first_existing_path(candidates, want_dir=True)
    
    # ==================== 连接测试 ====================
    
    def test_connection(self) -> Dict[str, Any]:
        """
        测试与 SillyTavern 的连接
        
        Returns:
            连接状态信息
        """
        result = {
            "local": {"available": False, "path": None, "resources": {}},
            "api": {"available": False, "url": self.st_url, "version": None}
        }
        
        # 测试本地路径
        st_path = self.st_data_dir or self.detect_st_path()
        if st_path:
            result["local"]["available"] = True
            result["local"]["path"] = st_path
            # 检查各资源目录
            for res_type in ST_DATA_STRUCTURE.keys():
                if res_type == "settings":
                    continue
                if res_type == "presets":
                    subdir = self.get_presets_dir()
                elif res_type == "regex":
                    subdir = self.get_regex_dir()
                else:
                    subdir = self.get_st_subdir(res_type)
                if subdir:
                    try:
                        count = len([f for f in os.listdir(subdir) 
                                   if f.endswith('.json') or f.endswith('.png')])
                        result["local"]["resources"][res_type] = count
                    except:
                        result["local"]["resources"][res_type] = 0
        
        # 测试 API 连接
        try:
            resp = requests.get(
                f"{self.st_url}/api/plugins/st-external-bridge/health",
                timeout=5,
                auth=(self.st_username, self.st_password) if self.st_username else None
            )
            if resp.ok:
                data = resp.json()
                result["api"]["available"] = True
                result["api"]["version"] = data.get("version", "unknown")
        except Exception as e:
            logger.debug(f"API 连接测试失败: {e}")
            
        # 尝试原生 ST API
        if not result["api"]["available"]:
            try:
                resp = requests.get(f"{self.st_url}/api/status", timeout=5)
                if resp.ok:
                    result["api"]["available"] = True
                    result["api"]["version"] = "native"
            except:
                pass
                
        return result
    
    # ==================== 角色卡读取 ====================
    
    def list_characters(self, use_api: bool = False) -> List[Dict[str, Any]]:
        """
        列出所有角色卡
        
        Args:
            use_api: 是否使用 API 模式
            
        Returns:
            角色卡列表
        """
        if use_api:
            return self._list_characters_api()
        return self._list_characters_local()
    
    def _list_characters_local(self) -> List[Dict[str, Any]]:
        """从本地文件系统读取角色卡列表"""
        chars_dir = self.get_st_subdir("characters")
        if not chars_dir:
            logger.warning("未找到角色卡目录")
            return []
            
        characters = []
        for filename in os.listdir(chars_dir):
            if not filename.endswith('.png'):
                continue
                
            try:
                filepath = os.path.join(chars_dir, filename)
                char_data = self._read_character_card(filepath)
                if char_data:
                    characters.append({
                        "id": filename.replace('.png', ''),
                        "filename": filename,
                        "name": char_data.get("name", filename),
                        "description": (char_data.get("description", "") or "")[:200],
                        "creator": char_data.get("creator", ""),
                        "tags": char_data.get("tags", []),
                        "create_date": char_data.get("create_date"),
                        "filepath": filepath,
                    })
            except Exception as e:
                logger.warning(f"读取角色卡 {filename} 失败: {e}")
                
        logger.info(f"从本地读取 {len(characters)} 个角色卡")
        return characters
    
    def _read_character_card(self, filepath: str) -> Optional[Dict[str, Any]]:
        """从 PNG 文件读取角色卡数据"""
        try:
            with open(filepath, 'rb') as f:
                # 验证 PNG 签名
                signature = f.read(8)
                if signature != b'\x89PNG\r\n\x1a\n':
                    return None
                    
                while True:
                    # 读取 chunk
                    length_bytes = f.read(4)
                    if len(length_bytes) < 4:
                        break
                        
                    length = struct.unpack('>I', length_bytes)[0]
                    chunk_type = f.read(4).decode('ascii', errors='ignore')
                    chunk_data = f.read(length)
                    f.read(4)  # CRC
                    
                    if chunk_type == 'tEXt':
                        # 解析 tEXt chunk
                        null_pos = chunk_data.find(b'\x00')
                        if null_pos != -1:
                            keyword = chunk_data[:null_pos].decode('latin-1')
                            text = chunk_data[null_pos + 1:]
                            
                            if keyword in ('chara', 'ccv3'):
                                try:
                                    decoded = base64.b64decode(text)
                                    data = json.loads(decoded.decode('utf-8'))
                                    # V2 格式
                                    if 'data' in data:
                                        return data['data']
                                    return data
                                except:
                                    pass
                                    
                    elif chunk_type == 'IEND':
                        break
                        
        except Exception as e:
            logger.error(f"解析角色卡失败 {filepath}: {e}")
            
        return None
    
    def _list_characters_api(self) -> List[Dict[str, Any]]:
        """通过 API 读取角色卡列表"""
        try:
            # 尝试 st-api-wrapper
            resp = requests.post(
                f"{self.st_url}/api/st-api/character/list",
                json={"full": False},
                timeout=self.timeout,
                auth=(self.st_username, self.st_password) if self.st_username else None
            )
            if resp.ok:
                data = resp.json()
                return data.get("characters", [])
        except Exception as e:
            logger.debug(f"st-api-wrapper 调用失败: {e}")
            
        return []
    
    def get_character(self, char_id: str, use_api: bool = False) -> Optional[Dict[str, Any]]:
        """获取单个角色卡详情"""
        if use_api:
            return self._get_character_api(char_id)
        return self._get_character_local(char_id)
    
    def _get_character_local(self, char_id: str) -> Optional[Dict[str, Any]]:
        """从本地读取角色卡详情"""
        chars_dir = self.get_st_subdir("characters")
        if not chars_dir:
            return None
            
        filename = char_id if char_id.endswith('.png') else f"{char_id}.png"
        filepath = os.path.join(chars_dir, filename)
        
        if os.path.exists(filepath):
            return self._read_character_card(filepath)
        return None
    
    def _get_character_api(self, char_id: str) -> Optional[Dict[str, Any]]:
        """通过 API 读取角色卡详情"""
        try:
            resp = requests.post(
                f"{self.st_url}/api/st-api/character/get",
                json={"name": char_id},
                timeout=self.timeout,
                auth=(self.st_username, self.st_password) if self.st_username else None
            )
            if resp.ok:
                data = resp.json()
                return data.get("character")
        except Exception as e:
            logger.debug(f"获取角色卡失败: {e}")
        return None
    
    # ==================== 世界书读取 ====================
    
    def list_world_books(self, use_api: bool = False) -> List[Dict[str, Any]]:
        """列出所有世界书"""
        if use_api:
            return self._list_world_books_api()
        return self._list_world_books_local()
    
    def _list_world_books_local(self) -> List[Dict[str, Any]]:
        """从本地文件系统读取世界书列表"""
        worlds_dir = self.get_st_subdir("worlds")
        if not worlds_dir:
            logger.warning("未找到世界书目录")
            return []
            
        world_books = []
        for entry in os.listdir(worlds_dir):
            entry_path = os.path.join(worlds_dir, entry)
            
            try:
                if entry.startswith('.'):
                    continue
                    
                if os.path.isfile(entry_path) and entry.endswith('.json'):
                    # 直接的 JSON 文件
                    wb_data = self._read_world_book_file(entry_path)
                    if wb_data:
                        world_books.append({
                            "id": entry.replace('.json', ''),
                            "filename": entry,
                            "name": wb_data.get("name", entry),
                            "description": wb_data.get("description", ""),
                            "entries_count": len(wb_data.get("entries", {})),
                            "filepath": entry_path,
                        })
                        
                elif os.path.isdir(entry_path):
                    # 目录形式，查找 world_info.json
                    wi_file = os.path.join(entry_path, "world_info.json")
                    if os.path.exists(wi_file):
                        wb_data = self._read_world_book_file(wi_file)
                        if wb_data:
                            world_books.append({
                                "id": entry,
                                "filename": entry,
                                "name": wb_data.get("name", entry),
                                "description": wb_data.get("description", ""),
                                "entries_count": len(wb_data.get("entries", {})),
                                "filepath": wi_file,
                            })
                            
            except Exception as e:
                logger.warning(f"读取世界书 {entry} 失败: {e}")
                
        logger.info(f"从本地读取 {len(world_books)} 本世界书")
        return world_books
    
    def _read_world_book_file(self, filepath: str) -> Optional[Dict[str, Any]]:
        """读取世界书 JSON 文件"""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"解析世界书失败 {filepath}: {e}")
        return None
    
    def _list_world_books_api(self) -> List[Dict[str, Any]]:
        """通过 API 读取世界书列表"""
        try:
            resp = requests.post(
                f"{self.st_url}/api/st-api/worldbook/list",
                json={},
                timeout=self.timeout,
                auth=(self.st_username, self.st_password) if self.st_username else None
            )
            if resp.ok:
                data = resp.json()
                return data.get("worldBooks", [])
        except Exception as e:
            logger.debug(f"获取世界书列表失败: {e}")
        return []
    
    # ==================== 预设读取 ====================
    
    def list_presets(self, use_api: bool = False) -> List[Dict[str, Any]]:
        """列出所有预设"""
        if use_api:
            return self._list_presets_api()
        return self._list_presets_local()
    
    def _list_presets_local(self) -> List[Dict[str, Any]]:
        """从本地文件系统读取预设列表"""
        presets_dir = self.get_presets_dir()
        if not presets_dir:
            logger.warning("未找到预设目录")
            return []
            
        presets = []
        for filename in os.listdir(presets_dir):
            if not filename.endswith('.json'):
                continue
                
            try:
                filepath = os.path.join(presets_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                regexes = extract_regex_from_preset_data(data)
                    
                preset_id = filename.replace('.json', '')
                presets.append({
                    "id": preset_id,
                    "filename": filename,
                    "name": data.get("name", data.get("title", preset_id)),
                    "description": data.get("description", data.get("note", "")),
                    "temperature": data.get("temperature"),
                    "max_tokens": data.get("max_tokens", data.get("openai_max_tokens")),
                    "regex_count": len(regexes),
                    "regexes": regexes,
                    "filepath": filepath,
                })
            except Exception as e:
                logger.warning(f"读取预设 {filename} 失败: {e}")
                
        logger.info(f"从本地读取 {len(presets)} 个预设")
        return presets
    
    def _list_presets_api(self) -> List[Dict[str, Any]]:
        """通过 API 读取预设列表"""
        try:
            resp = requests.post(
                f"{self.st_url}/api/st-api/preset/list",
                json={},
                timeout=self.timeout,
                auth=(self.st_username, self.st_password) if self.st_username else None
            )
            if resp.ok:
                data = resp.json()
                return data.get("presets", [])
        except Exception as e:
            logger.debug(f"获取预设列表失败: {e}")
        return []
    
    # ==================== 正则脚本读取 ====================
    
    def list_regex_scripts(self, use_api: bool = False) -> List[Dict[str, Any]]:
        """列出所有正则脚本"""
        if use_api:
            return self._list_regex_scripts_api()
        return self._list_regex_scripts_local()

    def _list_regex_scripts_api(self) -> List[Dict[str, Any]]:
        """通过 API 读取正则脚本列表（若支持 st-api-wrapper）"""
        try:
            resp = requests.post(
                f"{self.st_url}/api/st-api/regex/list",
                json={},
                timeout=self.timeout,
                auth=(self.st_username, self.st_password) if self.st_username else None
            )
            if resp.ok:
                data = resp.json()
                return data.get("scripts", []) or data.get("regexScripts", []) or []
        except Exception as e:
            logger.debug(f"获取正则脚本列表失败(API): {e}")
        return []
    
    def _list_regex_scripts_local(self) -> List[Dict[str, Any]]:
        """从本地文件系统读取正则脚本列表"""
        regex_dir = self.get_regex_dir()
        if not regex_dir:
            logger.warning("未找到正则脚本目录")
            return []
            
        scripts = []
        for filename in os.listdir(regex_dir):
            if not filename.endswith('.json'):
                continue
                
            try:
                filepath = os.path.join(regex_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                script_id = filename.replace('.json', '')
                scripts.append({
                    "id": script_id,
                    "filename": filename,
                    "name": data.get("scriptName", script_id),
                    "enabled": data.get("enabled", True),
                    "find_regex": data.get("findRegex", ""),
                    "replace_string": data.get("replaceString", ""),
                    "filepath": filepath,
                    "data": data,
                })
            except Exception as e:
                logger.warning(f"读取正则脚本 {filename} 失败: {e}")
                
        logger.info(f"从本地读取 {len(scripts)} 个正则脚本")
        return scripts
    
    # ==================== 快速回复读取 ====================
    
    def list_quick_replies(self, use_api: bool = False) -> List[Dict[str, Any]]:
        """列出所有快速回复"""
        return self._list_quick_replies_local()

    # ==================== 全局正则读取 ====================

    def get_global_regex(self, settings_path: Optional[str] = None) -> Dict[str, Any]:
        """
        读取 settings.json 中的全局 regex 规则
        Returns: { path, regexes, count, error? }
        """
        path = self.get_settings_path(settings_path)
        if not path:
            return {"path": None, "regexes": [], "count": 0}

        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            regexes = extract_global_regex_from_settings(raw)
            return {"path": path, "regexes": regexes, "count": len(regexes)}
        except Exception as e:
            logger.warning(f"读取全局正则失败: {e}")
            return {"path": path, "regexes": [], "count": 0, "error": str(e)}

    def aggregate_regex(self, presets_path: Optional[str] = None, settings_path: Optional[str] = None) -> Dict[str, Any]:
        """
        汇总全局正则 + 预设绑定正则
        Returns: { global, presets, stats }
        """
        presets_dir = presets_path or self.get_presets_dir()
        preset_sets = []

        if presets_dir and os.path.exists(presets_dir):
            for filename in os.listdir(presets_dir):
                if not filename.lower().endswith('.json'):
                    continue
                file_path = os.path.join(presets_dir, filename)
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        raw = json.load(f)
                    regexes = extract_regex_from_preset_data(raw)
                    if regexes:
                        preset_id = os.path.splitext(filename)[0]
                        preset_sets.append({
                            "presetId": preset_id,
                            "presetName": raw.get("name") or raw.get("title") or preset_id,
                            "regexes": regexes,
                            "regexCount": len(regexes)
                        })
                except Exception as e:
                    logger.warning(f"读取预设正则失败 {filename}: {e}")

        global_regex = self.get_global_regex(settings_path)
        preset_rule_count = sum(p.get("regexCount", 0) for p in preset_sets)

        return {
            "global": global_regex,
            "presets": preset_sets,
            "stats": {
                "presetGroups": len(preset_sets),
                "presetRules": preset_rule_count,
                "total": (global_regex.get("count") or 0) + preset_rule_count
            }
        }
    
    def _list_quick_replies_local(self) -> List[Dict[str, Any]]:
        """从本地文件系统读取快速回复列表"""
        qr_dir = self.get_st_subdir("quick_replies")
        if not qr_dir:
            logger.warning("未找到快速回复目录")
            return []
            
        quick_replies = []
        for filename in os.listdir(qr_dir):
            if not filename.endswith('.json'):
                continue
                
            try:
                filepath = os.path.join(qr_dir, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                qr_id = filename.replace('.json', '')
                quick_replies.append({
                    "id": qr_id,
                    "filename": filename,
                    "name": data.get("name", qr_id),
                    "entries_count": len(data.get("qrList", [])),
                    "filepath": filepath,
                    "data": data,
                })
            except Exception as e:
                logger.warning(f"读取快速回复 {filename} 失败: {e}")
                
        logger.info(f"从本地读取 {len(quick_replies)} 个快速回复集")
        return quick_replies
    
    # ==================== 资源同步 ====================
    
    def sync_resource(self, resource_type: str, resource_id: str, 
                      target_dir: str, use_api: bool = False) -> Tuple[bool, str]:
        """
        同步单个资源到目标目录
        
        Args:
            resource_type: 资源类型
            resource_id: 资源 ID
            target_dir: 目标目录
            use_api: 是否使用 API
            
        Returns:
            (成功标志, 消息或目标路径)
        """
        try:
            source_dir = self.get_st_subdir(resource_type)
            if not source_dir:
                return False, f"未找到 {resource_type} 源目录"
            
            # 确定源文件
            if resource_type == "characters":
                filename = f"{resource_id}.png" if not resource_id.endswith('.png') else resource_id
            else:
                filename = f"{resource_id}.json" if not resource_id.endswith('.json') else resource_id
                
            source_path = os.path.join(source_dir, filename)
            if not os.path.exists(source_path):
                return False, f"源文件不存在: {source_path}"
                
            # 确保目标目录存在
            os.makedirs(target_dir, exist_ok=True)
            
            # 复制文件
            target_path = os.path.join(target_dir, filename)
            import shutil
            shutil.copy2(source_path, target_path)
            
            logger.info(f"同步资源成功: {source_path} -> {target_path}")
            return True, target_path
            
        except Exception as e:
            logger.error(f"同步资源失败: {e}")
            return False, str(e)
    
    def sync_all_resources(self, resource_type: str, target_dir: str,
                          use_api: bool = False) -> Dict[str, Any]:
        """
        同步指定类型的所有资源
        
        Args:
            resource_type: 资源类型
            target_dir: 目标目录
            use_api: 是否使用 API
            
        Returns:
            同步结果统计
        """
        result = {
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
        }
        
        # 获取资源列表
        if resource_type == "characters":
            resources = self.list_characters(use_api)
        elif resource_type == "worlds":
            resources = self.list_world_books(use_api)
        elif resource_type == "presets":
            resources = self.list_presets(use_api)
        elif resource_type == "regex":
            resources = self.list_regex_scripts(use_api)
        elif resource_type == "quick_replies":
            resources = self.list_quick_replies(use_api)
        else:
            result["errors"].append(f"未知资源类型: {resource_type}")
            return result
            
        for res in resources:
            res_id = res.get("id") or res.get("filename", "").replace('.json', '').replace('.png', '')
            success, msg = self.sync_resource(resource_type, res_id, target_dir, use_api)
            
            if success:
                result["success"] += 1
            else:
                result["failed"] += 1
                result["errors"].append(f"{res_id}: {msg}")
                
        return result


# 全局客户端实例
_client: Optional[STClient] = None

def get_st_client() -> STClient:
    """获取全局 ST 客户端实例"""
    global _client
    if _client is None:
        _client = STClient()
    return _client

def refresh_st_client():
    """刷新 ST 客户端配置"""
    global _client
    _client = STClient()
    return _client
