import logging
import json
import os
from io import BytesIO
from flask import Blueprint, request, jsonify, send_file, make_response
from core.automation.manager import rule_manager
from core.automation.engine import AutomationEngine
from core.automation.executor import AutomationExecutor
from core.automation.constants import FIELD_MAP
from core.context import ctx
from core.services.card_service import resolve_ui_key
from core.data.ui_store import load_ui_data
from core.data.db_session import get_db
from core.config import CARDS_FOLDER
from core.utils.image import extract_card_info
from core.utils.text import calculate_token_count

logger = logging.getLogger(__name__)
bp = Blueprint('automation', __name__)
engine = AutomationEngine()
executor = AutomationExecutor()

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
                    cursor.execute("SELECT id FROM card_metadata")
                else:
                    cursor.execute("SELECT id FROM card_metadata WHERE category = ''")
            else:
                if recursive:
                    # 转义 SQL 通配符，匹配 category/%
                    safe_cat = category.replace('_', r'\_').replace('%', r'\%')
                    cursor.execute(f"SELECT id FROM card_metadata WHERE category = ? OR id LIKE ? || '/%' ESCAPE '\\'", (category, safe_cat))
                else:
                    cursor.execute("SELECT id FROM card_metadata WHERE category = ?", (category,))
            
            rows = cursor.fetchall()
            # 将查询结果合并到 card_ids (去重)
            db_ids = [row[0] for row in rows]
            card_ids = list(set(card_ids + db_ids))

        if not card_ids:
            return jsonify({"success": False, "msg": "未找到需要处理的卡片"})

        ruleset = rule_manager.get_ruleset(ruleset_id)
        if not ruleset:
            return jsonify({"success": False, "msg": "规则集不存在"})

        ui_data = load_ui_data()
        processed_count = 0
        
        # 统计结果
        summary = {
            "moves": 0,
            "tag_changes": 0
        }

        if not ctx.cache.initialized: ctx.cache.reload_from_db()
        
        # 定义所有属于"深层数据"的字段名 (包含 UI 字段名 和 内部数据字段名)
        deep_trigger_keys = {
            'character_book', 'extensions', # 内部对象名
            'wi_name', 'wi_content',        # 世界书
            'regex_name', 'regex_content',  # 正则脚本
            'st_script_name', 'st_script_content', # ST脚本
            'description', 'first_mes', 'mes_example', 'alternate_greetings',
            'personality', 'scenario', 'creator_notes', 
            'system_prompt', 'post_history_instructions',
            'char_version'
        }
        
        needs_deep_scan = False

        for r_idx, r in enumerate(ruleset.get('rules', [])):
            if not r.get('enabled', True): continue
            
            # 兼容处理：确保有 groups
            groups = r.get('groups', [])
            if not groups and r.get('conditions'):
                groups = [{'conditions': r.get('conditions')}]
            
            for g_idx, g in enumerate(groups):
                for c_idx, cond in enumerate(g.get('conditions', [])):
                    field_key = cond.get('field', '')
                    mapped_key = FIELD_MAP.get(field_key, '')

                    # 核心判断：只要字段名包含在触发列表中，或者其映射名在列表中
                    if (field_key in deep_trigger_keys) or (mapped_key in deep_trigger_keys):
                        needs_deep_scan = True
                        break
                if needs_deep_scan: break
            if needs_deep_scan: break

        # =================================================================
        # 2. 执行循环
        # =================================================================
        for cid in card_ids:
            # 查找基础数据
            card_obj = ctx.cache.id_map.get(cid)
            if not card_obj: 
                continue
            
            context_data = dict(card_obj)
            
            ui_key = resolve_ui_key(cid)
            ui_info = ui_data.get(ui_key, {})
            
            context_data['ui_summary'] = ui_info.get('summary', '')
            context_data['source_link'] = ui_info.get('link', '')
            
            # file_size 可能不在缓存里，如果规则需要，实时获取
            if 'file_size' not in context_data:
                try:
                    full_path = os.path.join(CARDS_FOLDER, cid.replace('/', os.sep))
                    if os.path.exists(full_path):
                        context_data['file_size'] = os.path.getsize(full_path)
                    else:
                        context_data['file_size'] = 0
                except:
                    context_data['file_size'] = 0
            
            # === 如果需要深层扫描，强制读取文件 ===
            if needs_deep_scan:
                try:
                    full_path = os.path.join(CARDS_FOLDER, cid.replace('/', os.sep))
                    if os.path.exists(full_path):
                        info = extract_card_info(full_path)
                        if info:
                            data_block = info.get('data', info) if 'data' in info else info
                            
                            # 待注入的字段列表
                            fields_to_patch = [
                                'character_book', 'extensions',
                                'description', 'first_mes', 'mes_example', 
                                'alternate_greetings', 'personality', 'scenario',
                                'creator_notes', 'system_prompt', 'post_history_instructions'
                            ]
                            
                            for f in fields_to_patch:
                                if f not in context_data or not context_data[f]:
                                    context_data[f] = data_block.get(f)
                            
                            # 特殊映射: character_version -> char_version
                            if 'char_version' not in context_data or not context_data['char_version']:
                                context_data['char_version'] = data_block.get('character_version', '')

                except Exception as e:
                    logger.warning(f"Deep scan failed for {cid}: {e}")
                        
            if 'token_count' not in context_data:
                 # 简单补全，防止报错
                 context_data['token_count'] = 0
            
            ui_key = resolve_ui_key(cid)
            ui_info = ui_data.get(ui_key, {})
            context_data['ui_summary'] = ui_info.get('summary', '')
            
            # 2. 评估
            plan_raw = engine.evaluate(context_data, ruleset)
            
            # 3. 整理 Plan (engine 返回的是 actions 列表，需转换为 Executor 需要的格式)
            # Engine 返回: { 'actions': [ {'type':'move_folder', 'value':'...'}, ... ] }
            # Executor 需要: { 'move': ..., 'add_tags': ..., ... }
            
            if not plan_raw['actions']: continue
            
            exec_plan = {
                'move': None,
                'add_tags': set(),
                'remove_tags': set(),
                'favorite': None
            }
            
            for act in plan_raw['actions']:
                t = act['type']
                v = act['value']
                if t == 'move_folder': exec_plan['move'] = v
                elif t == 'add_tag': exec_plan['add_tags'].add(v)
                elif t == 'remove_tag': exec_plan['remove_tags'].add(v)
                elif t == 'set_favorite': exec_plan['favorite'] = (str(v).lower() == 'true')
            
            # 4. 执行
            res = executor.apply_plan(cid, exec_plan)
            
            processed_count += 1
            if res['moved_to']: summary['moves'] += 1
            if res['tags_added'] or res['tags_removed']: summary['tag_changes'] += 1

        return jsonify({
            "success": True, 
            "processed": processed_count,
            "summary": summary
        })

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