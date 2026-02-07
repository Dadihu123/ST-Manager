import logging
from core.services.card_service import move_card_internal, modify_card_attributes_internal, resolve_ui_key
from core.automation.forum_tag_fetcher import get_tag_fetcher, TagProcessor
from core.data.ui_store import load_ui_data
from core.context import ctx

logger = logging.getLogger(__name__)

class AutomationExecutor:
    def apply_plan(self, card_id, plan, ui_data=None):
        """
        执行计划
        plan 结构: { 'move': 'Target/Path' or None, 'add_tags': set(), 'remove_tags': set(), 'favorite': bool/None }
        返回: 执行结果摘要
        """
        result = {
            "moved_to": None,
            "tags_added": [],
            "tags_removed": [],
            "fav_changed": False,
            "forum_tags_fetched": None  # 论坛标签抓取结果
        }
        
        current_id = card_id
        
        # 0. 执行论坛标签抓取 (如果配置了)
        forum_tags_config = plan.get('fetch_forum_tags')
        if forum_tags_config:
            # 如果没有传入ui_data，则加载
            if ui_data is None:
                ui_data = load_ui_data()
            fetch_result = self._fetch_forum_tags(current_id, forum_tags_config, ui_data)
            result["forum_tags_fetched"] = fetch_result
            # 如果成功抓取到标签，添加到add_tags中
            if fetch_result and fetch_result.get('success') and fetch_result.get('tags'):
                if 'add_tags' not in plan:
                    plan['add_tags'] = set()
                plan['add_tags'].update(fetch_result['tags'])
        
        # 1. 执行属性修改 (标签、收藏)
        # 这些操作不改变 ID，先执行
        add_tags = list(plan.get('add_tags', []))
        remove_tags = list(plan.get('remove_tags', []))
        fav = plan.get('favorite')
        
        if add_tags or remove_tags or fav is not None:
            success = modify_card_attributes_internal(current_id, add_tags, remove_tags, fav)
            if success:
                result["tags_added"] = add_tags
                result["tags_removed"] = remove_tags
                if fav is not None: result["fav_changed"] = True

        # 2. 执行移动 (最后执行，因为会改变 ID)
        target_folder = plan.get('move')
        if target_folder is not None:
            # 如果目标是当前目录，跳过
            # 这需要调用者判断，或者 move_card_internal 会处理
            success, new_id, msg = move_card_internal(current_id, target_folder)
            if success:
                current_id = new_id
                result["moved_to"] = target_folder
            else:
                logger.warning(f"Automation move failed for {card_id}: {msg}")

        result["final_id"] = current_id
        return result
    
    def _fetch_forum_tags(self, card_id, config, ui_data=None):
        """
        从论坛URL抓取标签
        URL从ui_data.json中的link字段获取（用户在界面中设置的超链接）

        config 结构: {
            'exclude_tags': ['其他'],  # 要排除的标签
            'replace_rules': {'其他': '杂项'},  # 替换规则
            'merge_mode': 'merge'  # 'merge' 合并, 'replace' 替换
        }
        """
        try:
            # 获取卡片数据
            card_data = None
            if ctx.cache and card_id in ctx.cache.id_map:
                card_data = ctx.cache.id_map[card_id]

            if not card_data:
                logger.error(f"无法获取卡片数据: {card_id}")
                return {'success': False, 'error': '无法获取卡片数据', 'tags': []}

            # 从ui_data获取URL（用户设置的超链接）
            if ui_data is None:
                ui_data = load_ui_data()

            # 获取ui_key（可能是card_id或bundle_dir）
            ui_key = resolve_ui_key(card_id)
            url = None

            if ui_key and ui_key in ui_data:
                entry = ui_data[ui_key]
                # 从ui_data entry中获取link字段
                url = entry.get('link', '').strip()

            if not url:
                logger.warning(f"卡片 {card_id} (ui_key: {ui_key}) 未配置超链接")
                return {'success': False, 'error': '未配置超链接，请在卡片详情中设置来源链接', 'tags': []}

            # 抓取标签
            fetcher = get_tag_fetcher()
            fetch_result = fetcher.fetch_tags(url)

            if not fetch_result['success']:
                logger.warning(f"抓取标签失败: {fetch_result['error']}")
                return fetch_result

            # 处理标签
            processor = TagProcessor(
                exclude_tags=config.get('exclude_tags', []),
                replace_rules=config.get('replace_rules', {})
            )

            processed_tags = processor.process(fetch_result['tags'])

            # 根据合并模式处理
            merge_mode = config.get('merge_mode', 'merge')
            existing_tags = card_data.get('tags', [])
            final_tags = processor.merge_tags(existing_tags, processed_tags, merge_mode)

            logger.info(f"论坛标签处理完成: {card_id}, 抓取: {fetch_result['tags']}, "
                       f"处理后: {processed_tags}, 最终: {final_tags}")

            return {
                'success': True,
                'tags': final_tags,
                'original_tags': fetch_result['tags'],
                'processed_tags': processed_tags,
                'title': fetch_result.get('title'),
                'merge_mode': merge_mode
            }

        except Exception as e:
            logger.error(f"抓取论坛标签时出错: {e}")
            return {'success': False, 'error': str(e), 'tags': []}