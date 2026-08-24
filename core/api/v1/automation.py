import logging
import json
import os
from copy import deepcopy
from io import BytesIO
from flask import Blueprint, request, jsonify, send_file
from core.automation.manager import rule_manager
from core.automation.engine import AutomationEngine
from core.automation.executor import AutomationExecutor
from core.automation.constants import (
    ACT_FETCH_FORUM_TAGS,
    ACT_MERGE_TAGS,
    ACT_RENAME_FILE_BY_TEMPLATE,
    ACT_SET_CHAR_NAME_FROM_FILENAME,
    ACT_SET_WI_NAME_FROM_FILENAME,
    ACT_SET_FILENAME_FROM_CHAR_NAME,
    ACT_SET_FILENAME_FROM_WI_NAME,
    TRIGGER_CONTEXT_MANUAL_RUN,
)
from core.automation.normalizer import normalize_actions_for_context
from core.context import ctx
from core.services.card_service import modify_card_attributes_internal
from core.data.ui_store import load_ui_data
from core.data.db_session import get_db
from core.config import load_config
from core.utils.text import calculate_token_count
from core.utils.tag_parser import split_action_tags
from core.automation.tag_merge import apply_merge_actions_to_tags
from core.services import automation_service

logger = logging.getLogger(__name__)
bp = Blueprint('automation', __name__)
engine = AutomationEngine()
executor = AutomationExecutor()


def _is_safe_automation_path(value, allow_empty=False):
    """校验批量目标使用的相对路径，避免把非法路径带入后续执行流程。"""
    if value is None:
        return False
    raw = str(value).strip()
    if not raw:
        return allow_empty

    normalized = raw.replace('\\', '/')
    if os.path.isabs(raw) or os.path.splitdrive(raw)[0]:
        return False
    if normalized.startswith('/'):
        return False

    parts = normalized.split('/')
    return all(part not in ('.', '..') for part in parts)


def _resolve_automation_target_ids(payload):
    """解析并冻结自动化执行目标，供预览和前端逐项执行共用。"""
    raw_card_ids = payload.get('card_ids', [])
    if raw_card_ids is None:
        raw_card_ids = []
    if isinstance(raw_card_ids, str):
        raw_card_ids = [raw_card_ids]
    if not isinstance(raw_card_ids, (list, tuple)):
        raise ValueError('card_ids 必须是列表')

    card_ids = []
    for raw_id in raw_card_ids:
        card_id = str(raw_id or '').strip().replace('\\', '/')
        if card_id and not _is_safe_automation_path(card_id):
            raise ValueError('非法路径')
        if card_id and card_id not in card_ids:
            card_ids.append(card_id)

    category = payload.get('category', None)
    if category is not None:
        category = str(category or '').strip().replace('\\', '/').strip('/')
        if category == '根目录':
            category = ''
        if not _is_safe_automation_path(category, allow_empty=True):
            raise ValueError('非法分类路径')
        conn = get_db()
        cursor = conn.cursor()

        if category == '':
            if payload.get('recursive', True):
                cursor.execute('SELECT id FROM card_metadata ORDER BY id')
            else:
                cursor.execute("SELECT id FROM card_metadata WHERE category = '' ORDER BY id")
        elif payload.get('recursive', True):
            safe_category = category.replace('_', r'\_').replace('%', r'\%')
            cursor.execute(
                "SELECT id FROM card_metadata WHERE category = ? OR id LIKE ? || '/%' ESCAPE '\\' ORDER BY id",
                (category, safe_category),
            )
        else:
            cursor.execute('SELECT id FROM card_metadata WHERE category = ? ORDER BY id', (category,))

        for row in cursor.fetchall():
            card_id = str(row[0] or '').strip().replace('\\', '/')
            if card_id and _is_safe_automation_path(card_id) and card_id not in card_ids:
                card_ids.append(card_id)

    return card_ids


@bp.route('/api/automation/targets', methods=['POST'])
def get_automation_targets():
    """返回分类/选中卡片对应的冻结目标 ID，不执行任何动作。"""
    try:
        payload = request.get_json(silent=True) or {}
        card_ids = _resolve_automation_target_ids(payload)
        return jsonify({'success': True, 'selected': len(card_ids), 'card_ids': card_ids})
    except Exception as exc:
        logger.error('Resolve automation targets error: %s', exc)
        return jsonify({'success': False, 'msg': str(exc)}), 400

@bp.route('/api/automation/rulesets', methods=['GET'])
def list_rulesets():
    return jsonify({"success": True, "items": rule_manager.list_rulesets()})

@bp.route('/api/automation/rulesets/<ruleset_id>', methods=['GET'])
def get_ruleset(ruleset_id):
    data = rule_manager.get_ruleset(ruleset_id)
    if data:
        return jsonify({"success": True, "data": data})
    return jsonify({"success": False, "msg": "Not found"}), 404

@bp.route('/api/automation/rulesets', methods=['POST'])
def save_ruleset():
    try:
        data = request.json
        ruleset_id = data.get('id') # 如果是新建，可能是 None
        saved_id = rule_manager.save_ruleset(ruleset_id, data)
        return jsonify({"success": True, "id": saved_id})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/automation/rulesets/<ruleset_id>', methods=['DELETE'])
def delete_ruleset(ruleset_id):
    if rule_manager.delete_ruleset(ruleset_id):
        return jsonify({"success": True})
    return jsonify({"success": False, "msg": "Delete failed"})

@bp.route('/api/automation/execute', methods=['POST'])
def execute_rules():
    """
    手动触发：对选中的卡片执行指定的规则集
    """
    try:
        data = request.json
        card_ids = data.get('card_ids', [])
        category = data.get('category', None)
        recursive = data.get('recursive', True)
        ruleset_id = data.get('ruleset_id')
        
        if not ruleset_id:
            return jsonify({"success": False, "msg": "未选择规则集"})

        # === ID 解析策略 (Snapshot Generation) ===
        # 如果传入了 category，我们需要先查询出所有目标 ID，生成一个静态列表
        # 这能有效防止"边移动边遍历"导致的重复处理或漏处理问题
        if category is not None:
            # 使用 DB 查询以获取最新最准的列表
            conn = get_db()
            cursor = conn.cursor()
            
            if category == "": # 根目录
                if recursive:
                    cursor.execute("SELECT id FROM card_metadata ORDER BY id")
                else:
                    cursor.execute("SELECT id FROM card_metadata WHERE category = '' ORDER BY id")
            else:
                if recursive:
                    # 转义 SQL 通配符，匹配 category/%
                    safe_cat = category.replace('_', r'\_').replace('%', r'\%')
                    cursor.execute(
                        "SELECT id FROM card_metadata WHERE category = ? OR id LIKE ? || '/%' ESCAPE '\\' ORDER BY id",
                        (category, safe_cat)
                    )
                else:
                    cursor.execute("SELECT id FROM card_metadata WHERE category = ? ORDER BY id", (category,))
            
            rows = cursor.fetchall()
            # 将查询结果合并到 card_ids (去重)
            db_ids = [row[0] for row in rows]
            card_ids = list(dict.fromkeys(card_ids + db_ids))

        selected_count = len(card_ids)

        if not card_ids:
            return jsonify({"success": False, "msg": "未找到需要处理的卡片"})

        ruleset = rule_manager.get_ruleset(ruleset_id)
        if not ruleset:
            return jsonify({"success": False, "msg": "规则集不存在"})

        cfg = load_config()
        slash_as_separator = bool(cfg.get('automation_slash_is_tag_separator', False))

        ui_data = load_ui_data()
        processed_count = 0
        
        # 统计结果
        summary = {
            "moves": 0,
            "tag_changes": 0
        }

        if not ctx.cache.initialized: ctx.cache.reload_from_db()
        
        # =================================================================
        # 2. 执行循环
        # =================================================================
        batch_targets = []
        skipped_details = []
        for cid in card_ids:
            card_obj = ctx.cache.id_map.get(cid)
            if not card_obj:
                skipped_details.append({'card_id': cid, 'reason': 'card_not_in_cache'})
                continue
            batch_targets.append((cid, deepcopy(card_obj)))

        for cid, card_obj in batch_targets:
            
            context_data, ui_data = automation_service._build_rule_context(
                cid,
                card_obj,
                ruleset,
                ui_data=ui_data,
            )

            if 'token_count' not in context_data:
                  # 简单补全，防止报错
                  context_data['token_count'] = 0
            
            # 2. 评估（手动执行时，无条件的规则也视为匹配）
            plan_raw = engine.evaluate(context_data, ruleset, match_if_no_conditions=True)
            normalized_plan = normalize_actions_for_context(
                plan_raw.get('actions', []),
                TRIGGER_CONTEXT_MANUAL_RUN,
                card_snapshot=context_data,
            )
            
            if not normalized_plan['actions']:
                continue

            executable_actions = [
                act for act in normalized_plan.get('actions', [])
                if isinstance(act, dict)
            ]

            exec_plan = automation_service._build_exec_plan_from_actions(
                executable_actions,
                slash_as_separator=slash_as_separator,
            )
            merge_actions = [
                act for act in executable_actions
                if isinstance(act, dict) and act.get('type') == ACT_MERGE_TAGS
            ]
            
            # 4. 执行
            res = executor.apply_plan(cid, exec_plan, ui_data)

            # 5. 执行标签合并（在规则集执行场景下同样生效）
            if merge_actions:
                final_id = res.get('final_id') or cid
                card_after = ctx.cache.id_map.get(final_id) if ctx.cache else None
                current_tags = list((card_after or {}).get('tags') or [])

                merge_result = apply_merge_actions_to_tags(
                    current_tags,
                    merge_actions,
                    slash_as_separator=slash_as_separator
                )

                if merge_result.get('changed'):
                    merged_tags = list(merge_result.get('tags') or [])
                    remove_tags = [t for t in current_tags if t not in merged_tags]
                    add_tags = [t for t in merged_tags if t not in current_tags]
                    if add_tags or remove_tags:
                        modify_card_attributes_internal(final_id, add_tags=add_tags, remove_tags=remove_tags)
                    summary['tag_changes'] += 1
            
            processed_count += 1
            if res['moved_to']: summary['moves'] += 1
            if res['tags_added'] or res['tags_removed']: summary['tag_changes'] += 1

        response = {
            "success": True, 
            "selected": selected_count,
            "processed": processed_count,
            "skipped": len(skipped_details),
            "summary": summary,
            'details': {
                'skipped': skipped_details,
            },
        }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Execution error: {e}")
        import traceback; traceback.print_exc()
        return jsonify({"success": False, "msg": str(e)})
    
# 设置全局默认规则
@bp.route('/api/automation/global_setting', methods=['POST'])
def set_global_ruleset():
    try:
        ruleset_id = request.json.get('ruleset_id') # 可以是 None 表示关闭
        # 保存到 config.json
        from core.config import load_config, save_config
        cfg = load_config()
        cfg['active_automation_ruleset'] = ruleset_id
        save_config(cfg)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/automation/global_setting', methods=['GET'])
def get_global_ruleset():
    from core.config import load_config
    cfg = load_config()
    return jsonify({"success": True, "ruleset_id": cfg.get('active_automation_ruleset')})

@bp.route('/api/automation/rulesets/<ruleset_id>/export', methods=['GET'])
def export_ruleset(ruleset_id):
    try:
        data = rule_manager.get_ruleset(ruleset_id)
        if not data:
            return jsonify({"success": False, "msg": "Not found"}), 404
        
        # 移除 id，因为导入时会重新生成或覆盖
        if 'id' in data: del data['id']
        
        # 生成文件名
        name = data.get('meta', {}).get('name', 'ruleset')
        safe_name = "".join([c for c in name if c.isalnum() or c in (' ', '-', '_')]).strip()
        filename = f"{safe_name}.json"
        
        # 返回文件流
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        mem = BytesIO()
        mem.write(json_str.encode('utf-8'))
        mem.seek(0)
        
        return send_file(
            mem,
            as_attachment=True,
            download_name=filename,
            mimetype='application/json'
        )
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)})

@bp.route('/api/automation/rulesets/import', methods=['POST'])
def import_ruleset():
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "msg": "No file uploaded"})
            
        file = request.files['file']
        if not file.filename.endswith('.json'):
            return jsonify({"success": False, "msg": "Invalid file type"})
            
        content = json.load(file)
        
        # 简单校验
        if 'rules' not in content:
            return jsonify({"success": False, "msg": "Invalid ruleset format (missing 'rules')"})
            
        # 如果导入的数据里没有 meta.name，用文件名代替
        if 'meta' not in content: content['meta'] = {}
        if not content['meta'].get('name'):
            content['meta']['name'] = os.path.splitext(file.filename)[0]
            
        # 保存 (作为新规则集)
        new_id = rule_manager.save_ruleset(None, content)
        
        return jsonify({"success": True, "id": new_id, "name": content['meta']['name']})
        
    except Exception as e:
        logger.error(f"Import ruleset error: {e}")
        return jsonify({"success": False, "msg": str(e)})
