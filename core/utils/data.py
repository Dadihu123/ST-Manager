# ================= 数据标准化工具 =================

def deterministic_sort(obj):
    """
    递归对字典排序。
    V3 标准优先字段放在最前，data 放在中间，其他保留字段按字母序。
    """
    if isinstance(obj, dict):
        # 1. Root 层的优先顺序
        root_priority = [
            'name', 'description', 'personality', 'scenario', 'first_mes', 'mes_example',
            'creatorcomment', 'avatar', 'talkativeness', 'fav', 'tags',
            'spec', 'spec_version', 'data', 'create_date'
        ]
        
        # 2. Data 层的优先顺序
        data_priority = [
            'name', 'description', 'personality', 'scenario', 'first_mes', 'mes_example',
            'creator_notes', 'system_prompt', 'post_history_instructions', 
            'tags', 'creator', 'character_version', 'alternate_greetings', 
            'extensions', 'group_only_greetings', 'character_book'
        ]

        # 3. [关键] 扩展功能的内部字段优先顺序
        # 必须涵盖 regex_scripts 中的所有字段，否则未命中的字段会回退到字母序
        extension_priority = [
            # 基础 ID/Name
            'id', 'scriptName', 'name', 'enabled', 'disabled', 
            # 正则相关
            'findRegex', 'replaceString', 'trimStrings', 'placement',
            # 运行控制
            'runOnEdit', 'markdownOnly', 'promptOnly', 
            # 深度与其他
            'minDepth', 'maxDepth', 'substituteRegex',
            # 兼容其他插件字段
            'type', 'content', 'info', 'button', 'data',
            'top', 'bottom', 'left', 'right'
        ]

        sorted_dict = {}
        
        # 合并所有优先键 (保持顺序去重)
        all_priority = []
        seen = set()
        for k in root_priority + data_priority + extension_priority:
            if k not in seen:
                all_priority.append(k)
                seen.add(k)
        
        # 1. 优先字段 (递归处理)
        for k in all_priority:
            if k in obj:
                sorted_dict[k] = deterministic_sort(obj[k])
        
        # 2. 剩余未知字段 (按字母序)
        for k in sorted(obj.keys()):
            if k not in all_priority:
                sorted_dict[k] = deterministic_sort(obj[k])
                
        return sorted_dict
        
    elif isinstance(obj, list):
        return [deterministic_sort(item) for item in obj]
    else:
        return obj

def normalize_card_v3(card_data):
    """
    将卡片数据强制标准化为 V3 格式。
    保留 V2 的 root 字段以兼容旧软件，但核心数据强制同步到 data 节点。
    """
    if not isinstance(card_data, dict):
        return card_data

    # 1. 确保 data 节点存在
    if 'data' not in card_data or not isinstance(card_data['data'], dict):
        # V2 -> V3 迁移：创建一个包含当前 root 字段的 data
        card_data['data'] = card_data.copy()
        # 清理 data 内部不该有的 root 专用字段
        for k in ['spec', 'spec_version', 'data']:
            if k in card_data['data']:
                del card_data['data'][k]

    # 引用便捷操作
    data_block = card_data['data']

    # 2. 强制 V3 标头
    card_data['spec'] = 'chara_card_v3'
    card_data['spec_version'] = '3.0'

    # 3. 字段同步策略
    # 定义必须在 data 中存在的字段 (Core Fields)
    # 如果 root 有，但 data 没有或为空，则从 root 复制到 data
    core_fields = [
        'name', 'description', 'personality', 'scenario', 'first_mes', 'mes_example',
        'creator_notes', 'system_prompt', 'post_history_instructions', 'tags',
        'creator', 'character_version', 'alternate_greetings', 'extensions', 'character_book'
    ]

    # V2 兼容性映射 (Root Key -> Data Key)
    # 有些字段在 V2 root 叫 creatorcomment，在 V3 data 叫 creator_notes
    key_mapping = {
        'creatorcomment': 'creator_notes',
    }

    for field in core_fields:
        # 尝试从 root 获取 (处理映射)
        root_val = None
        # 反向查找 root 中对应的 key
        root_key = field
        for old_k, new_k in key_mapping.items():
            if new_k == field:
                root_key = old_k
                break
        
        if root_key in card_data:
            root_val = card_data[root_key]
        elif field in card_data:
            root_val = card_data[field]

        # 如果 data 中没有该字段，或者 root 有值但 data 是空的，则同步
        # 注意：这里我们信任 data 中的值优先，除非 data 缺失
        if field not in data_block:
            if root_val is not None:
                data_block[field] = root_val
    
    # 4. 特殊字段处理：character_book
    # V3 标准：character_book 应该只在 data 中。Root 中不需要。
    # 如果 Root 中有且与 data 中重复，删除 Root 中的以减小体积。
    if 'character_book' in card_data:
        # 确保移入了 data
        if 'character_book' not in data_block:
            data_block['character_book'] = card_data['character_book']
        # 删除 Root 中的
        del card_data['character_book']

    # 5. 特殊字段处理：extensions
    # 同上，extensions 应该主要在 data 中
    if 'extensions' in card_data:
        # 确保 extensions 是字典
        if not isinstance(card_data['extensions'], dict):
             card_data['extensions'] = {}
             
        if 'extensions' not in data_block:
            data_block['extensions'] = card_data['extensions']
        
        # 检查 tavern_helper 结构
        # 如果 data_block['extensions'] 中有 tavern_helper
        th = data_block['extensions'].get('tavern_helper')
        if th:
            # 无论是列表(旧版)还是字典(新版)，都保留原样
            # 之前的代码可能强制将其重置，这里确保只做基本的空值处理
            pass
        else:
            # 如果没有，初始化为空列表 (旧版兼容性)
            # data_block['extensions']['tavern_helper'] = [] 
            pass 
            
        del card_data['extensions']

    # 6. 保留 Root 层的兼容字段 (根据你的 test测试用.json 样本)
    # 样本保留了: name, description, personality, scenario, first_mes, mes_example, creatorcomment, avatar, talkativeness, fav, tags
    # 这些字段如果 data 里有，root 里也保留一份副本，用于不支持 V3 的软件预览
    
    # 7. 清理 Data 层可能存在的冗余 Root 字段
    # 例如 spec, spec_version 不应该出现在 data 层
    for k in ['spec', 'spec_version', 'data']:
        if k in data_block:
            del data_block[k]

    return card_data

# --- 从 data_block 提取 WI 信息 ---
def get_wi_meta(data_block):
    has_wi = 0
    wi_name = ""
    cb = data_block.get('character_book')
    if cb:
        # V2 数组检查
        if isinstance(cb, list) and len(cb) > 0:
            has_wi = 1
            wi_name = "Embedded World Info" # V2 数组通常没有顶层名字
        # V3 对象检查
        elif isinstance(cb, dict):
            entries = cb.get('entries')
            # 兼容 entries 是列表或字典的情况
            if isinstance(entries, list) and len(entries) > 0:
                has_wi = 1
            elif isinstance(entries, dict) and len(entries) > 0:
                has_wi = 1
            
            if has_wi:
                wi_name = cb.get('name', 'World Info')
    return has_wi, wi_name

def sanitize_for_utf8(obj, dirty_tracker=None):
    """
    递归清洗对象中的字符串。
    :param obj: 要清洗的对象 (dict, list, str)
    :param dirty_tracker: (可选) 传入一个列表。如果发现并修复了乱码，会向列表 append(True)。
    """
    if isinstance(obj, str):
        try:
            # 尝试严格编码，如果成功则直接返回（性能最好）
            obj.encode('utf-8')
            return obj
        except UnicodeEncodeError:
            # 捕获异常，标记脏数据
            if isinstance(dirty_tracker, list):
                dirty_tracker.append(True)
            # 执行修复：忽略非法字符
            return obj.encode('utf-8', 'ignore').decode('utf-8')
            
    elif isinstance(obj, dict):
        return {k: sanitize_for_utf8(v, dirty_tracker) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_utf8(v, dirty_tracker) for v in obj]
    else:
        return obj