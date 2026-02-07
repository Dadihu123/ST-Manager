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
        
        # 评估
        plan_raw = engine.evaluate(context_data, ruleset)
        
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
                # 论坛标签抓取动作
                # v 应该是包含配置的字典
                if isinstance(v, dict):
                    exec_plan['fetch_forum_tags'] = v
                else:
                    # 如果没有提供配置，使用默认空配置
                    # URL将从ui_data.link自动获取
                    exec_plan['fetch_forum_tags'] = {}
            
        # 执行
        res = executor.apply_plan(card_id, exec_plan, ui_data)

        logger.info(f"Auto-run applied on {card_id}: {res}")
        return {"run": True, "result": res}
        
    except Exception as e:
        logger.error(f"Auto-run error: {e}")
        return None