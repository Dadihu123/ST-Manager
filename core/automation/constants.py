# 字段映射 (前端显示名 -> 内部数据路径)
FIELD_MAP = {
    # 基础元数据
    "char_name": "char_name",
    "description": "description",
    "creator": "creator",
    "char_version": "char_version",
    "first_mes": "first_mes",
    "mes_example": "mes_example",
    
    # 列表/特殊类型
    "tags": "tags", # List
    "alternate_greetings": "alternate_greetings", # List
    
    # 系统/统计
    "ui_summary": "ui_summary", # 来自 ui_data
    "is_favorite": "is_favorite", # Boolean
    "token_count": "token_count", # Int
    "file_size": "file_size", # Int (bytes)
    
    # 高级/扩展
    "wi_name": "character_book",    # 匹配条目名称/备注 (Comment)
    "wi_content": "character_book", # 匹配条目内容 (Content)
    
    # 正则脚本 (Regex)
    "regex_name": "extensions.regex_scripts",    # 匹配脚本名称
    "regex_content": "extensions.regex_scripts", # 匹配脚本正则内容 (findRegex)
    
    # ST Helper 脚本 (Tavern Helper)
    "st_script_name": "extensions.tavern_helper",    # 匹配脚本名称
    "st_script_content": "extensions.tavern_helper", # 匹配脚本内容
}

# 操作符定义
OP_EQ = "eq"                # 等于
OP_NEQ = "neq"              # 不等于
OP_CONTAINS = "contains"    # 包含 (字符串子串 或 列表项)
OP_NOT_CONTAINS = "not_contains" # 不包含
OP_REGEX = "regex"          # 正则匹配
OP_EXISTS = "exists"        # 有值/非空
OP_NOT_EXISTS = "not_exists" # 无值/空
OP_GT = "gt"                # 大于 (数值)
OP_LT = "lt"                # 小于 (数值)
OP_TRUE = "is_true"         # 是 (布尔)
OP_FALSE = "is_false"       # 否 (布尔)

# 动作类型
ACT_MOVE = "move_folder"
ACT_ADD_TAG = "add_tag"
ACT_REMOVE_TAG = "remove_tag"
ACT_SET_FAV = "set_favorite"

# 论坛标签抓取动作
ACT_FETCH_FORUM_TAGS = "fetch_forum_tags"

# URL字段映射
URL_FIELD_MAP = {
    "source_url": "extensions.source_url",  # 来源URL字段
    "character_version": "character_version",  # 版本字段(有时包含URL)
    "creator_notes": "creator_notes",  # 创建者备注
}