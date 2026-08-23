import logging
import os
from core.automation.normalizer import (
    TRIGGER_CONTEXT_AUTO_IMPORT,
    TRIGGER_CONTEXT_MANUAL_RUN,
    TRIGGER_CONTEXT_CARD_UPDATE,
    TRIGGER_CONTEXT_LINK_UPDATE,
    TRIGGER_CONTEXT_TAG_EDIT,
    normalize_actions_for_context,
)
from core.config import CARDS_FOLDER, load_config
from core.automation.template_runtime import build_snapshot_template_fields
from core.automation.manager import rule_manager
from core.automation.engine import AutomationEngine
from core.automation.executor import AutomationExecutor
from core.automation.constants import (
    FIELD_MAP,
    ACT_FETCH_FORUM_TAGS,
    ACT_REFRESH_SOURCE_BASELINE,
    ACT_MERGE_TAGS,
    ACT_RENAME_FILE_BY_TEMPLATE,
    ACT_SET_CHAR_NAME_FROM_FILENAME,
    ACT_SET_WI_NAME_FROM_FILENAME,
    ACT_SET_FILENAME_FROM_CHAR_NAME,
    ACT_SET_FILENAME_FROM_WI_NAME,
)
from core.automation.tag_merge import apply_merge_actions_to_tags
from core.context import ctx
from core.data.ui_store import load_ui_data
from core.services.card_service import modify_card_attributes_internal, resolve_ui_key
from core.services.tag_management_service import build_governance_feedback
from core.utils.tag_parser import split_action_tags
from core.utils.image import extract_card_info

logger = logging.getLogger(__name__)

engine = AutomationEngine()
executor = AutomationExecutor()


DEEP_AUTOMATION_FIELDS = {
    'character_book', 'extensions',
    'wi_name', 'wi_content',
    'regex_name', 'regex_content',
    'st_script_name', 'st_script_content',
    'description', 'first_mes', 'mes_example', 'alternate_greetings',
    'personality', 'scenario', 'creator_notes',
    'system_prompt', 'post_history_instructions',
    'char_version'
}

FILE_STAT_FIELDS = {'file_size'}


def _ruleset_uses_fields(ruleset, target_fields):
    if not isinstance(ruleset, dict):
        return False

    for rule in ruleset.get('rules', []):
        if not rule.get('enabled', True):
            continue

        groups = rule.get('groups', [])
        if not groups and rule.get('conditions'):
            groups = [{'conditions': rule.get('conditions', [])}]

        for group in groups:
            for cond in group.get('conditions', []):
                field_key = cond.get('field', '')
                mapped_key = FIELD_MAP.get(field_key, field_key)
                if field_key in target_fields or mapped_key in target_fields:
                    return True
        
    return False


def _build_rule_context(card_id, card_obj, ruleset, ui_data=None, tags=None):
    context_data = dict(card_obj or {})

    if ui_data is None:
        ui_data = load_ui_data()

    context_data.update(build_snapshot_template_fields(card_id, card_obj, ui_data=ui_data))

    if tags is not None:
        context_data['tags'] = list(tags or [])

    ui_key = resolve_ui_key(card_id)
    ui_info = ui_data.get(ui_key, {})
    context_data['ui_summary'] = ui_info.get('summary', '')
    context_data['source_link'] = ui_info.get('link', '')

    if _ruleset_uses_fields(ruleset, FILE_STAT_FIELDS) and 'file_size' not in context_data:
        try:
            card_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
            context_data['file_size'] = os.path.getsize(card_path) if os.path.exists(card_path) else 0
        except OSError:
            context_data['file_size'] = 0

    if not _ruleset_uses_fields(ruleset, DEEP_AUTOMATION_FIELDS):
        return context_data, ui_data

    try:
        card_path = os.path.join(CARDS_FOLDER, card_id.replace('/', os.sep))
        if not os.path.exists(card_path):
            return context_data, ui_data

        info = extract_card_info(card_path)
        if not info:
            return context_data, ui_data

        data_block = info.get('data', info) if isinstance(info, dict) else {}
        if not isinstance(data_block, dict):
            return context_data, ui_data

        fields_to_patch = [
            'character_book', 'extensions',
            'description', 'first_mes', 'mes_example',
            'alternate_greetings', 'personality', 'scenario',
            'creator_notes', 'system_prompt', 'post_history_instructions'
        ]

        for field in fields_to_patch:
            if field not in context_data or not context_data[field]:
                context_data[field] = data_block.get(field)

        if 'char_version' not in context_data or not context_data['char_version']:
            context_data['char_version'] = data_block.get('character_version', '')

        return context_data, ui_data
    except Exception as e:
        logger.warning(f"Automation deep field load failed for {card_id}: {e}")
        return context_data, ui_data


def _build_runtime_from_active_ruleset():
    cfg = load_config()
    active_id = cfg.get('active_automation_ruleset')

    if not active_id:
        return None

    ruleset = rule_manager.get_ruleset(active_id)
    if not ruleset:
        return None

    return {
        'ruleset_id': active_id,
        'ruleset': ruleset,
        'slash_as_separator': bool(cfg.get('automation_slash_is_tag_separator', False))
    }


def _normalize_rule_trigger_contexts(rule):
    trigger_contexts = rule.get('trigger_contexts') if isinstance(rule, dict) else None
    if not trigger_contexts:
        legacy_contexts = [TRIGGER_CONTEXT_MANUAL_RUN, TRIGGER_CONTEXT_AUTO_IMPORT]
        actions = rule.get('actions', []) if isinstance(rule, dict) else []

        for action in actions:
            if not isinstance(action, dict):
                continue

            action_type = action.get('type')
            if action_type in {ACT_FETCH_FORUM_TAGS, ACT_REFRESH_SOURCE_BASELINE} and TRIGGER_CONTEXT_LINK_UPDATE not in legacy_contexts:
                legacy_contexts.append(TRIGGER_CONTEXT_LINK_UPDATE)
            elif action_type == ACT_MERGE_TAGS and TRIGGER_CONTEXT_TAG_EDIT not in legacy_contexts:
                legacy_contexts.append(TRIGGER_CONTEXT_TAG_EDIT)

        return legacy_contexts

    if isinstance(trigger_contexts, str):
        trigger_contexts = [trigger_contexts.strip()]

    normalized = []
    for trigger_context in trigger_contexts:
        if not isinstance(trigger_context, str):
            continue

        trigger_context = trigger_context.strip()
        if trigger_context and trigger_context not in normalized:
            normalized.append(trigger_context)

    return normalized or [TRIGGER_CONTEXT_MANUAL_RUN, TRIGGER_CONTEXT_AUTO_IMPORT]


def _filter_ruleset_by_trigger_context(ruleset, trigger_context):
    if not isinstance(ruleset, dict):
        return {'rules': []}

    filtered_rules = []
    for rule in ruleset.get('rules', []):
        if not isinstance(rule, dict) or not rule.get('enabled', True):
            continue
        if trigger_context in _normalize_rule_trigger_contexts(rule):
            filtered_rules.append(rule)

    filtered_ruleset = dict(ruleset)
    filtered_ruleset['rules'] = filtered_rules
    return filtered_ruleset


def _empty_exec_plan():
    return {
        'move': None,
        'add_tags': set(),
        'remove_tags': set(),
        'favorite': None,
        'fetch_forum_tags': None,
        'refresh_source_baseline': None,
        'rename_file_by_template': None,
        'set_char_name_from_filename': False,
        'set_wi_name_from_filename': False,
        'set_filename_from_char_name': False,
        'set_filename_from_wi_name': False,
    }


def _build_exec_plan_from_actions(actions, slash_as_separator=False):
    exec_plan = _empty_exec_plan()

    for act in actions or []:
        if not isinstance(act, dict):
            continue

        action_type = act.get('type')
        action_value = act.get('value')

        if action_type == 'move_folder':
            exec_plan['move'] = action_value
        elif action_type == 'add_tag':
            exec_plan['add_tags'].update(
                split_action_tags(action_value, slash_as_separator=slash_as_separator)
            )
        elif action_type == 'remove_tag':
            exec_plan['remove_tags'].update(
                split_action_tags(action_value, slash_as_separator=slash_as_separator)
            )
        elif action_type == 'set_favorite':
            exec_plan['favorite'] = (str(action_value).lower() == 'true')
        elif action_type == ACT_SET_CHAR_NAME_FROM_FILENAME:
            exec_plan['set_char_name_from_filename'] = True
        elif action_type == ACT_SET_WI_NAME_FROM_FILENAME:
            exec_plan['set_wi_name_from_filename'] = True
        elif action_type == ACT_SET_FILENAME_FROM_CHAR_NAME:
            exec_plan['set_filename_from_char_name'] = True
        elif action_type == ACT_SET_FILENAME_FROM_WI_NAME:
            exec_plan['set_filename_from_wi_name'] = True
        elif action_type == ACT_RENAME_FILE_BY_TEMPLATE:
            exec_plan['rename_file_by_template'] = action_value
        elif action_type == ACT_FETCH_FORUM_TAGS:
            exec_plan['fetch_forum_tags'] = action_value if isinstance(action_value, dict) else {}
        elif action_type == ACT_REFRESH_SOURCE_BASELINE:
            exec_plan['refresh_source_baseline'] = action_value if isinstance(action_value, dict) else {}

    return exec_plan


def get_global_tag_merge_runtime():
    """
    获取全局规则集中的标签合并运行时上下文。
    返回 None 表示未启用全局规则集或规则集不存在。
    """
    try:
        return _build_runtime_from_active_ruleset()
    except Exception as e:
        logger.error(f"Build global tag merge runtime error: {e}")
        return None


def auto_run_tag_merge_on_tagging(card_id, tags, ui_data=None, runtime=None):
    """
    在“手动打标”场景下应用全局规则集里的 merge_tags 动作。
    典型触发点：批量标签管理、详情页编辑标签并保存。
    """
    try:
        rt = runtime or _build_runtime_from_active_ruleset()
        if not rt:
            return None

        ruleset = rt.get('ruleset')
        if not ruleset:
            return None

        slash_as_separator = bool(rt.get('slash_as_separator', False))
        filtered_ruleset = _filter_ruleset_by_trigger_context(ruleset, TRIGGER_CONTEXT_TAG_EDIT)

        card_obj = ctx.cache.id_map.get(card_id)
        if not card_obj:
            parent_dir = os.path.dirname(card_id).replace('\\', '/')
            bundle_main_id = ctx.cache.bundle_map.get(parent_dir)
            if bundle_main_id:
                card_obj = ctx.cache.id_map.get(bundle_main_id)

        if not card_obj:
            logger.debug(f"Tag merge skipped, card not found in cache: {card_id}")
            return None

        context_data, ui_data = _build_rule_context(
            card_id,
            card_obj,
            filtered_ruleset,
            ui_data=ui_data,
            tags=tags,
        )

        plan_raw = engine.evaluate(context_data, filtered_ruleset, match_if_no_conditions=True)
        normalized_plan = normalize_actions_for_context(
            plan_raw.get('actions', []),
            TRIGGER_CONTEXT_TAG_EDIT,
            card_snapshot=context_data,
        )
        merge_actions = normalized_plan.get('actions', [])

        if not merge_actions:
            return {
                'run': True,
                'actions': 0,
                'result': {
                    'tags': list(tags or []),
                    'changed': False,
                    'replacements': [],
                    'replace_rules': {}
                }
            }

        merge_result = apply_merge_actions_to_tags(
            tags,
            merge_actions,
            slash_as_separator=slash_as_separator
        )

        return {
            'run': True,
            'actions': len(merge_actions),
            'result': merge_result
        }
    except Exception as e:
        logger.error(f"Auto-run tag merge error: {e}")
        return None

def auto_run_rules_on_card(card_id):
    """
    检查是否有全局激活的规则集，如果有，对指定卡片运行。
    用于上传/导入后的钩子。
    """
    return auto_run_rules_for_trigger(card_id, TRIGGER_CONTEXT_AUTO_IMPORT)


def auto_run_rules_for_trigger(card_id, trigger_context):
    """对指定卡片按触发上下文执行自动化规则。"""
    try:
        cfg = load_config()
        active_id = cfg.get('active_automation_ruleset')

        if not active_id:
            return None  # 未开启自动化

        ruleset = rule_manager.get_ruleset(active_id)
        if not ruleset:
            return None

        slash_as_separator = bool(cfg.get('automation_slash_is_tag_separator', False))

        # 获取卡片数据
        # 刚上传的卡片可能还没进缓存（如果是并发情况），但通常 API 也就是串行的
        # 我们尝试从缓存拿，如果没有，尝试等待一下或者重新读 DB (略重)
        # 这里假设调用时，update_card_cache 已经执行，缓存已更新

        card_obj = ctx.cache.id_map.get(card_id)
        if not card_obj:
            logger.warning(f"Auto-run: Card {card_id} not found in cache immediately.")
            return None

        filtered_ruleset = _filter_ruleset_by_trigger_context(ruleset, trigger_context)

        # 准备数据
        context_data, ui_data = _build_rule_context(card_id, card_obj, filtered_ruleset)

        # 评估（自动执行时，无条件的规则也应执行）
        plan_raw = engine.evaluate(context_data, filtered_ruleset, match_if_no_conditions=True)
        normalized_plan = normalize_actions_for_context(
            plan_raw.get('actions', []),
            trigger_context,
            card_snapshot=context_data,
        )

        if not normalized_plan['actions']:
            return {"run": True, "actions": 0}

        exec_plan = _build_exec_plan_from_actions(
            normalized_plan.get('actions', []),
            slash_as_separator=slash_as_separator,
        )

        # 执行
        res = executor.apply_plan(card_id, exec_plan, ui_data)

        logger.info(f"Auto-run applied on {card_id}: {res}")
        return {"run": True, "result": res}

    except Exception as e:
        logger.error(f"Auto-run error: {e}")
        return {'run': False, 'error': str(e)}


def auto_run_forum_tags_on_link_update(card_id):
    """
    当卡片超链接更新时，执行来源链接专用动作。
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

        filtered_ruleset = _filter_ruleset_by_trigger_context(ruleset, TRIGGER_CONTEXT_LINK_UPDATE)

        # 获取卡片数据
        card_obj = ctx.cache.id_map.get(card_id)
        if not card_obj:
            logger.warning(f"Auto-run forum tags: Card {card_id} not found in cache.")
            return None

        # 准备数据
        context_data, ui_data = _build_rule_context(card_id, card_obj, filtered_ruleset)

        # 评估（自动执行时，无条件的规则也应执行）
        plan_raw = engine.evaluate(context_data, filtered_ruleset, match_if_no_conditions=True)
        normalized_plan = normalize_actions_for_context(
            plan_raw.get('actions', []),
            TRIGGER_CONTEXT_LINK_UPDATE,
            card_snapshot=context_data,
        )

        if not normalized_plan['actions']:
            return {"run": True, "actions": 0}

        exec_plan = _build_exec_plan_from_actions(normalized_plan.get('actions', []))

        has_fetch_action = exec_plan.get('fetch_forum_tags') is not None
        has_baseline_action = exec_plan.get('refresh_source_baseline') is not None
        if not has_fetch_action and not has_baseline_action:
            return {"run": True, "actions": 0, "reason": "no_fetch_forum_tags_action"}

        # 执行
        res = executor.apply_plan(card_id, exec_plan, ui_data)

        # 抓取论坛标签后，联动执行标签合并（如果全局规则中配置了 merge_tags）
        current_card = ctx.cache.id_map.get(card_id)
        fetch_payload = res.get('forum_tags_fetched') or {}
        has_fetched_tags = 'tags' in fetch_payload
        fetched_tags = fetch_payload.get('tags') or []
        final_tags = list(fetched_tags if has_fetched_tags else ((current_card or {}).get('tags') or []))
        tag_merge = None

        if has_fetch_action and final_tags:
            merge_res = auto_run_tag_merge_on_tagging(card_id, final_tags, ui_data=ui_data, runtime={
                'ruleset_id': active_id,
                'ruleset': ruleset,
                'slash_as_separator': bool(cfg.get('automation_slash_is_tag_separator', False))
            })
            merge_payload = (merge_res or {}).get('result') or {}

            if merge_payload.get('changed'):
                merged_tags = merge_payload.get('tags') or final_tags
                if merged_tags != final_tags:
                    remove_tags = [t for t in final_tags if t not in merged_tags]
                    add_tags = [t for t in merged_tags if t not in final_tags]
                    if add_tags or remove_tags:
                        ok = modify_card_attributes_internal(card_id, add_tags=add_tags, remove_tags=remove_tags)
                        if ok:
                            final_tags = list(merged_tags)

            if merge_res and int(merge_res.get('actions') or 0) > 0:
                tag_merge = {
                    'triggered': True,
                    'changed': bool(merge_payload.get('changed')),
                    'replacements': merge_payload.get('replacements', []) or [],
                    'replace_rules': merge_payload.get('replace_rules', {}) or {},
                    'actions': int(merge_res.get('actions') or 0)
                }
                governance_feedback = build_governance_feedback(merge_payload)
                if governance_feedback['skipped_unknown']:
                    tag_merge['skipped_unknown'] = governance_feedback['skipped_unknown']
                if governance_feedback['skipped_blacklist']:
                    tag_merge['skipped_blacklist'] = governance_feedback['skipped_blacklist']

        res['final_tags'] = final_tags
        if tag_merge:
            res['tag_merge'] = tag_merge

        logger.info(f"Auto-run forum tags on link update for {card_id}: {res}")
        return {"run": True, "result": res}

    except Exception as e:
        logger.error(f"Auto-run forum tags error: {e}")
        return None
