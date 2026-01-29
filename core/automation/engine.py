import re
import logging
from .constants import *

logger = logging.getLogger(__name__)

class AutomationEngine:
    def __init__(self):
        pass

    def _get_field_value(self, card_data, field_key, specific_target=None):
        """从数据中提取值，支持复杂对象扁平化"""
        if not field_key: return None
        if not isinstance(card_data, dict): return None
        
        # === 1. 正则脚本匹配 (Regex Scripts) ===
        if field_key == 'extensions.regex_scripts' or field_key == 'regex_scripts':
            # V2/V3 兼容读取
            ext = card_data.get('extensions') or {}
            scripts = ext.get('regex_scripts')
            if not scripts: scripts = card_data.get('regex_scripts', [])
            
            scripts = scripts or []
            
            if isinstance(scripts, list):
                if specific_target == 'regex_content':
                    # 提取正则内容 regex / findRegex
                    return [str(s.get('findRegex') or s.get('regex') or '') for s in scripts if isinstance(s, dict)]
                else:
                    # 提取名称 scriptName
                    return [str(s.get('scriptName', '')) for s in scripts if isinstance(s, dict)]
            return []

        # === 2. 世界书匹配 (World Info) ===
        if field_key == 'character_book':
            book = card_data.get('character_book') or {}
            # 兼容 V2 数组 和 V3 字典/数组
            entries = book.get('entries') or []
            if isinstance(entries, dict):
                entries = list(entries.values())
                
            if isinstance(entries, list):
                if specific_target == 'wi_content':
                    return [str(e.get('content', '')) for e in entries if isinstance(e, dict)]
                elif specific_target == 'wi_name':
                    # comment 也就是备注/名称
                    return [str(e.get('comment', '')) for e in entries if isinstance(e, dict)]
                else:
                    searchable = []
                    for e in entries:
                        if isinstance(e, dict):
                            searchable.append(str(e.get('content', '')))
                            searchable.append(str(e.get('comment', '')))
                    return searchable
            return []

        # === 3. ST Helper 脚本匹配 (Tavern Helper) ===
        if field_key == 'extensions.tavern_helper':
            # Tavern Helper 数据结构: [ ["scripts", [...]], ["variables", {...}] ]
            ext = card_data.get('extensions') or {}
            helper_data = ext.get('tavern_helper')
            
            scripts_list = []
            
            if isinstance(helper_data, dict):
                # 新版字典结构
                scripts_list = helper_data.get('scripts', [])
            elif isinstance(helper_data, list):
                # 旧版列表结构
                for item in helper_data:
                    # item 应该是 ["scripts", [obj, obj...]]
                    if isinstance(item, list) and len(item) >= 2 and item[0] == 'scripts':
                        if isinstance(item[1], list):
                            scripts_list = item[1]
                        break
            
            if not scripts_list:
                return []

            if specific_target == 'st_script_content':
                # 脚本内容 (Usually 'content')
                return [str(s.get('content', '')) for s in scripts_list if isinstance(s, dict)]
            else:
                # 脚本名称 (Usually 'name')
                return [str(s.get('name', '')) for s in scripts_list if isinstance(s, dict)]

        # === 4. 通用嵌套取值 ===
        if '.' in field_key:
            keys = field_key.split('.')
            value = card_data
            for k in keys:
                if isinstance(value, dict):
                    value = value.get(k)
                else:
                    return None
            return value
            
        return card_data.get(field_key)

    def _check_condition(self, value, operator, target_value, case_sensitive=False):
        """核心判断逻辑"""
        try:
            # 1. 空值检查
            if operator == OP_EXISTS:
                return value is not None and value != "" and value != []
            if operator == OP_NOT_EXISTS:
                return value is None or value == "" or value == []

            if value is None: return False # 其他操作符如果值为 None 默认不匹配

            # 2. 数值比较
            if operator in [OP_GT, OP_LT]:
                try:
                    val_num = float(value)
                    tgt_num = float(target_value)
                    return val_num > tgt_num if operator == OP_GT else val_num < tgt_num
                except:
                    return False

            # 3. 布尔比较
            if operator in [OP_TRUE, OP_FALSE]:
                bool_val = str(value).lower() in ('true', '1', 'yes', 'on')
                return bool_val is True if operator == OP_TRUE else bool_val is False

            # =========================================================
            # 增强型字符串/列表比较 (支持 '|' 分割的 OR 逻辑)
            # =========================================================
            
            # 预处理：是否启用多值匹配模式
            # 条件：操作符不是正则，且 target_value 是字符串并包含 '|'
            enable_multi_match = (
                operator != OP_REGEX and 
                isinstance(target_value, str) and 
                '|' in target_value
            )

            # 获取待匹配的目标列表
            targets = []
            if enable_multi_match:
                # 分割并去空
                targets = [t.strip() for t in target_value.split('|') if t.strip()]
            else:
                targets = [str(target_value)]

            # 辅助函数：单次比较逻辑 (复用原有的比较核心)
            def single_check(val, op, tgt, ignore_case):
                val_str = str(val)
                tgt_str = str(tgt)
                
                if not ignore_case:
                    val_str = val_str.lower()
                    tgt_str = tgt_str.lower()

                if op == OP_EQ:
                    # 如果是列表，EQ 意味着集合相等
                    if isinstance(val, list):
                        target_list = [t.strip().lower() for t in tgt.split(',')] if ',' in tgt else [tgt_str]
                        value_list = [str(v).lower() for v in val]
                        return sorted(value_list) == sorted(target_list)
                    return val_str == tgt_str

                if op == OP_NEQ:
                    return val_str != tgt_str

                if op == OP_CONTAINS:
                    if isinstance(val, list):
                        # 列表包含：只要列表中有任意一项包含/等于目标
                        if not ignore_case:
                            return any(tgt_str in str(v).lower() for v in val)
                        return any(str(tgt) in str(v) for v in val)
                    else:
                        # 字符串包含
                        return tgt_str in val_str

                if op == OP_NOT_CONTAINS:
                    # CONTAINS 的反向
                    if isinstance(val, list):
                        if not ignore_case:
                            return not any(tgt_str in str(v).lower() for v in val)
                        return not any(str(tgt) in str(v) for v in val)
                    else:
                        return tgt_str not in val_str
                
                return False

            # === 执行多值逻辑 ===
            
            # A. 正则模式 (Regex) - 原样保留，正则自带 | 支持
            if operator == OP_REGEX:
                flags = 0 if case_sensitive else re.IGNORECASE
                return bool(re.search(str(target_value), str(value), flags))

            # B. 肯定类操作符 (EQ, CONTAINS) -> OR 逻辑
            # 只要有一个目标匹配成功，则返回 True
            if operator in [OP_EQ, OP_CONTAINS]:
                for tgt in targets:
                    if single_check(value, operator, tgt, not case_sensitive):
                        return True
                return False

            # C. 否定类操作符 (NEQ, NOT_CONTAINS) -> AND 逻辑 (NOR)
            # 必须所有目标都不匹配，才返回 True
            if operator in [OP_NEQ, OP_NOT_CONTAINS]:
                for tgt in targets:
                    # 注意：这里我们调用 single_check 并期望它返回 True (即符合 NEQ/NOT_CONTAINS)
                    # 如果有一个不符合（即实际上相等或包含了），则整体失败
                    if not single_check(value, operator, tgt, not case_sensitive):
                        return False
                return True

            return False
        except Exception as e:
            logger.error(f"Condition check error: {e}")
            return False

    def evaluate(self, card_data, ruleset):
        """
        评估一张卡片，返回执行计划
        """
        plan = {
            "actions": []
        }
        
        # 预处理：将 WI 拼成大字符串方便全文搜索（如果规则里有模糊搜WI的需求）
        if card_data.get('character_book'):
            entries = card_data['character_book'].get('entries', [])
            if isinstance(entries, dict): entries = list(entries.values())
            if isinstance(entries, list):
                combined_wi = " ".join([str(e.get('content', '')) + " " + str(e.get('comment', '')) for e in entries if isinstance(e, dict)])
                card_data['character_book_content'] = combined_wi

        # 遍历规则
        for rule in ruleset.get('rules', []):
            if not rule.get('enabled', True): continue

            # === 数据标准化：统一转为 Groups 结构 ===
            rule_groups = rule.get('groups', [])
            
            # 兼容旧数据：如果是扁平 conditions，包装成一个默认 Group
            if not rule_groups and rule.get('conditions'):
                rule_groups = [{
                    "logic": "AND", # 旧版默认逻辑通常隐含为 AND，或者看 rule.logic (如果前端以前没做 group)
                    "conditions": rule.get('conditions', [])
                }]
            
            # 如果完全没有条件，跳过还是视为匹配？通常跳过。
            if not rule_groups:
                continue
            
            # 规则级逻辑：组与组之间的关系
            # 默认 OR：即只要有一个组满足，规则就触发（适合：情况A 或 情况B）
            # 用户也可设为 AND：必须满足 组A 且 组B
            rule_top_logic = rule.get('logic', 'OR').upper() 
            
            group_results = []

            for group in rule_groups:
                conditions = group.get('conditions', [])
                group_logic = group.get('logic', 'AND').upper()
                
                # 如果组内无条件，视为 False 还是 True？
                # 为了安全，无条件的组视为不匹配
                if not conditions:
                    group_results.append(False)
                    continue

                cond_results = []
                for cond in conditions:
                    raw_field = cond['field']
                    mapped_field = FIELD_MAP.get(raw_field, raw_field)
                    
                    op = cond['operator']
                    val = cond.get('value')
                    case = cond.get('case_sensitive', False)
                    
                    # 取值
                    actual_val = self._get_field_value(card_data, mapped_field, specific_target=raw_field)
                    
                    # 判值
                    res = self._check_condition(actual_val, op, val, case)
                    cond_results.append(res)
                
                # 计算 Group 结果
                if group_logic == 'AND':
                    group_match = all(cond_results)
                else: # OR
                    group_match = any(cond_results)
                
                group_results.append(group_match)
            
            # 计算 Rule 最终结果
            is_rule_match = False
            if rule_top_logic == 'AND':
                is_rule_match = all(group_results)
            else: # OR
                is_rule_match = any(group_results)

            if is_rule_match:
                logger.info(f"Rule matched: {rule.get('name')}")
                # 收集动作
                for action in rule.get('actions', []):
                    plan['actions'].append(action)
                
                # 冲突控制
                if rule.get('stop_on_match'):
                    break
        
        return plan