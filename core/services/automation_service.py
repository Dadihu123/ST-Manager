import logging
from core.config import load_config
from core.automation.manager import rule_manager
from core.automation.engine import AutomationEngine
from core.automation.executor import AutomationExecutor
from core.automation.constants import ACT_FETCH_FORUM_TAGS
from core.context import ctx
from core.data.ui_store import load_ui_data
from core.services.card_service import resolve_ui_key

logger = logging.getLogger(__name__)

engine = AutomationEngine()
executor = AutomationExecutor()

def auto_run_rules_on_card(card_id):
    """
    检查是否有全局激活的规则集，如果有，对指定卡片运行。
    用于上传/导入后的钩子。
    """
    try:
        cfg = load_config()
        active_id = cfg.get('active_automation_ruleset')
        
        if not active_id:
            return None # 未开启自动化
            
        ruleset = rule_manager.get_ruleset(active_id)
        if not ruleset:
            return None
            
        # 获取卡片数据
        # 刚上传的卡片可能还没进缓存（如果是并发情况），但通常 API 也就是串行的
        # 我们尝试从缓存拿，如果没有，尝试等待一下或者重新读 DB (略重)
        # 这里假设调用时，update_card_cache 已经执行，缓存已更新
        
        card_obj = ctx.cache.id_map.get(card_id)
        if not card_obj:
            logger.warning(f"Auto-run: Card {card_id} not found in cache immediately.")
            return None
            
        # 准备数据
        ui_data = load_ui_data()
        context_data = dict(card_obj)
        ui_key = resolve_ui_key(card_id)
        ui_info = ui_data.get(ui_key, {})
        context_data['ui_summary'] = ui_info.get('summary', '')
        
        # 评估（自动执行时，无条件的规则也应执行）
        plan_raw = engine.evaluate(context_data, ruleset, match_if_no_conditions=True)
        
        if not plan_raw['actions']:
            return {"run": True, "actions": 0}
            
        # 转换 Plan
        exec_plan = {
            'move': None,
            'add_tags': set(),
            'remove_tags': set(),
            'favorite': None,
            'fetch_forum_tags': None
        }
        for act in plan_raw['actions']:
            t = act['type']
            v = act['value']
            if t == 'move_folder':
                exec_plan['move'] = v
            elif t == 'add_tag':
                exec_plan['add_tags'].add(v)
            elif t == 'remove_tag':
                exec_plan['remove_tags'].add(v)
            elif t == 'set_favorite':
                exec_plan['favorite'] = (str(v).lower() == 'true')
            elif t == ACT_FETCH_FORUM_TAGS:
                # 导入时跳过论坛标签抓取，因为此时 URL 为空
                # 此动作仅在用户更新来源链接时触发
                continue
            
        # 执行
        res = executor.apply_plan(card_id, exec_plan, ui_data)

        logger.info(f"Auto-run applied on {card_id}: {res}")
        return {"run": True, "result": res}

    except Exception as e:
        logger.error(f"Auto-run error: {e}")
        return None


def auto_run_forum_tags_on_link_update(card_id):
    """
    当卡片超链接更新时，仅执行抓取论坛标签动作。
    用于用户在卡片详情页更新来源链接后的钩子。
    """
    try:
        cfg = load_config()
        active_id = cfg.get('active_automation_ruleset')

        if not active_id:
            return None  # 未开启自动化

        ruleset = rule_manager.get_ruleset(active_id)
        if not ruleset:
            return None

        # 获取卡片数据
        card_obj = ctx.cache.id_map.get(card_id)
        if not card_obj:
            logger.warning(f"Auto-run forum tags: Card {card_id} not found in cache.")
            return None

        # 准备数据
        ui_data = load_ui_data()
        context_data = dict(card_obj)
        ui_key = resolve_ui_key(card_id)
        ui_info = ui_data.get(ui_key, {})
        context_data['ui_summary'] = ui_info.get('summary', '')

        # 评估（自动执行时，无条件的规则也应执行）
        plan_raw = engine.evaluate(context_data, ruleset, match_if_no_conditions=True)

        if not plan_raw['actions']:
            return {"run": True, "actions": 0}

        # 只提取 fetch_forum_tags 动作
        fetch_forum_tags_config = None
        for act in plan_raw['actions']:
            if act['type'] == ACT_FETCH_FORUM_TAGS:
                v = act['value']
                if isinstance(v, dict):
                    fetch_forum_tags_config = v
                else:
                    fetch_forum_tags_config = {}
                break  # 只执行第一个抓取论坛标签动作

        if not fetch_forum_tags_config:
            return {"run": True, "actions": 0, "reason": "no_fetch_forum_tags_action"}

        # 构建只包含 fetch_forum_tags 的执行计划
        exec_plan = {
            'move': None,
            'add_tags': set(),
            'remove_tags': set(),
            'favorite': None,
            'fetch_forum_tags': fetch_forum_tags_config
        }

        # 执行
        res = executor.apply_plan(card_id, exec_plan, ui_data)

        logger.info(f"Auto-run forum tags on link update for {card_id}: {res}")
        return {"run": True, "result": res}

    except Exception as e:
        logger.error(f"Auto-run forum tags error: {e}")
        return None