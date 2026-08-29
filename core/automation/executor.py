import logging
from core.services.card_service import (
    move_card_internal,
    modify_card_attributes_internal,
    resolve_ui_key,
    sync_card_names_internal,
)
from core.automation.forum_tag_fetcher import get_tag_fetcher, TagProcessor
from core.automation.constants import (
    ACT_ADD_TAGS_FROM_SOURCE_TITLE,
    ACT_SET_CREATOR_FROM_SOURCE,
)
from core.automation.source_actions import (
    extract_source_title_tags,
    render_source_creator,
)
from core.data.ui_store import load_ui_data
from core.context import ctx
from core.config import load_config
from core.services.tag_management_service import build_governance_feedback, build_known_tag_set, filter_governed_tags
from core.services.forum_update_service import (
    fetch_discord_source,
    refresh_card_source_baseline,
)
from core.services.shimmerday_forum_service import fetch_shimmerday_source

logger = logging.getLogger(__name__)

class AutomationExecutor:
    def apply_plan(self, card_id, plan, ui_data=None):
        """
        执行计划
        plan 结构:
        {
            'move': 'Target/Path' or None,
            'add_tags': set(),
            'remove_tags': set(),
            'favorite': bool/None,
            'set_char_name_from_filename': bool,
            'set_wi_name_from_filename': bool,
            'set_filename_from_char_name': bool,
            'set_filename_from_wi_name': bool,
            'set_creator': str or None,
        }
        返回: 执行结果摘要
        """
        result = {
            "moved_to": None,
            "tags_added": [],
            "tags_removed": [],
            "fav_changed": False,
            "name_sync": None,
            "forum_tags_fetched": None,  # 论坛标签抓取结果
        }
        
        current_id = card_id
        
        # 0. 执行来源链接动作（论坛标签和/或更新基线）
        forum_tags_config = plan.get('fetch_forum_tags')
        baseline_config = plan.get('refresh_source_baseline')
        title_tags_config = plan.get(ACT_ADD_TAGS_FROM_SOURCE_TITLE)
        creator_config = plan.get(ACT_SET_CREATOR_FROM_SOURCE)
        has_source_action = any(
            config is not None
            for config in (
                forum_tags_config,
                baseline_config,
                title_tags_config,
                creator_config,
            )
        )
        if has_source_action:
            if ui_data is None:
                ui_data = load_ui_data()

            # 来源动作同时执行时，共享帖子详情和首帖请求。
            prefetched_source = None
            source_link = self._source_link_for_card(current_id, ui_data)
            creator_provider = (
                str(creator_config.get('provider') or 'auto').strip().lower()
                if isinstance(creator_config, dict) else 'auto'
            )
            needs_discord_source = (
                title_tags_config is not None
                or (creator_config is not None and creator_provider in {'auto', 'discord'})
                or (forum_tags_config is not None and baseline_config is not None)
            )
            if needs_discord_source and source_link:
                prefetched_source = fetch_discord_source(source_link)

            if baseline_config is not None:
                result['source_baseline_refreshed'] = refresh_card_source_baseline(
                    current_id,
                    source_link=source_link,
                    ui_data=ui_data,
                    fetched=prefetched_source,
                )

            if forum_tags_config is None:
                fetch_result = None
            elif prefetched_source is None:
                fetch_result = self._fetch_forum_tags(current_id, forum_tags_config, ui_data)
            else:
                fetch_result = self._fetch_forum_tags(
                    current_id,
                    forum_tags_config,
                    ui_data,
                    prefetched_source=prefetched_source,
                )
            result["forum_tags_fetched"] = fetch_result
            # 如果成功抓取到标签，按 merge/replace 语义折叠为标签增删计划
            if fetch_result and fetch_result.get('success'):
                existing_tags = list(ctx.cache.id_map.get(current_id, {}).get('tags') or []) if ctx.cache else []
                final_tags = list(fetch_result['tags'])
                plan.setdefault('add_tags', set())
                plan.setdefault('remove_tags', set())
                plan['add_tags'].update(tag for tag in final_tags if tag not in existing_tags)
                plan['remove_tags'].update(tag for tag in existing_tags if tag not in final_tags)

            # 标题和作者动作共享同一个来源结果；类脑只在 Discord 没有满足需求时作为补充来源。
            discord_source = {}
            if isinstance(prefetched_source, dict) and prefetched_source.get('success'):
                discord_source = dict(prefetched_source.get('source') or {})
            if source_link:
                discord_source['source_url'] = source_link

            shimmerday_result = None
            shimmerday_source = {}

            def get_shimmerday_source():
                nonlocal shimmerday_result, shimmerday_source
                if shimmerday_result is None:
                    shimmerday_result = fetch_shimmerday_source(
                        source_link=source_link,
                        card_id=current_id,
                    )
                    if not isinstance(shimmerday_result, dict):
                        shimmerday_result = {
                            'success': False,
                            'error': '类脑搜索站接口返回格式异常',
                        }
                    if shimmerday_result.get('success'):
                        shimmerday_source = dict(shimmerday_result.get('source') or {})
                        shimmerday_source['source_url'] = source_link
                return shimmerday_source

            title_source = discord_source
            title_source_provider = 'discord'
            title_source_available = bool(
                isinstance(prefetched_source, dict) and prefetched_source.get('success')
            )
            if title_tags_config is not None and not str(discord_source.get('title') or '').strip():
                title_source = get_shimmerday_source()
                title_source_provider = 'shimmerday'
                title_source_available = bool(
                    isinstance(shimmerday_result, dict) and shimmerday_result.get('success')
                )

            if title_tags_config is not None:
                if not title_source_available:
                    title_result = {
                        'success': False,
                        'title': '',
                        'pattern': title_tags_config.get('pattern')
                        if isinstance(title_tags_config, dict) else None,
                        'capture_groups': [],
                        'split_pattern': '',
                        'matched_values': [],
                        'extracted_tags': [],
                        'match_count': 0,
                        'source': title_source_provider,
                        'skipped_reason': 'source_unavailable',
                        'error': (
                            (shimmerday_result or {}).get('error')
                            or (prefetched_source or {}).get('error')
                            or '未取得来源帖子标题'
                        ),
                    }
                else:
                    title_result = extract_source_title_tags(
                        title_source.get('title', ''),
                        title_tags_config,
                    )
                    title_result['source'] = title_source_provider

                if title_result.get('success'):
                    governed = filter_governed_tags(
                        title_result.get('extracted_tags') or [],
                        ui_data=ui_data,
                        known_tags=build_known_tag_set(ui_data=ui_data),
                    )
                    accepted_tags = governed['accepted']
                    current_tags = list(
                        (ctx.cache.id_map.get(current_id, {}) if ctx.cache else {}).get('tags') or []
                    )
                    plan.setdefault('add_tags', set())
                    plan.setdefault('remove_tags', set())
                    plan['add_tags'].update(accepted_tags)
                    # 标题动作是追加动作，即使论坛标签使用 replace，也不删除标题提取出的标签。
                    plan['remove_tags'].difference_update(accepted_tags)
                    title_result['governed_tags'] = accepted_tags
                    title_result['tags_added'] = [
                        tag for tag in accepted_tags if tag not in current_tags
                    ]
                    title_result.update(build_governance_feedback(governed))
                result['source_title_tags'] = title_result

            if creator_config is not None:
                cfg = creator_config if isinstance(creator_config, dict) else {}
                provider = str(cfg.get('provider') or 'auto').strip().lower()
                if provider not in {'auto', 'discord', 'shimmerday'}:
                    provider = 'auto'

                author_source = discord_source
                if provider == 'shimmerday':
                    author_source = get_shimmerday_source()
                elif provider == 'auto' and not discord_source.get('author'):
                    author_source = get_shimmerday_source()

                author = author_source.get('author') if isinstance(author_source, dict) else None
                current_creator = str(
                    (ctx.cache.id_map.get(current_id, {}) if ctx.cache else {}).get('creator') or ''
                ).strip()
                creator_result = {
                    'success': False,
                    'changed': False,
                    'previous_creator': current_creator,
                    'creator': current_creator,
                    'author_source': author_source.get('author_source') if isinstance(author_source, dict) else None,
                }

                overwrite = cfg.get('overwrite', False)
                if isinstance(overwrite, str):
                    overwrite = overwrite.strip().lower() in {'1', 'true', 'yes', 'on'}
                else:
                    overwrite = bool(overwrite)

                if not author:
                    creator_result['skipped_reason'] = 'author_unavailable'
                    creator_result['error'] = (
                        (shimmerday_result or {}).get('error')
                        or (prefetched_source or {}).get('error')
                        or '未取得来源作者'
                    )
                else:
                    creator_value = render_source_creator(
                        cfg.get('format', '{{author}}'),
                        source=author_source,
                        author=author,
                        author_field=cfg.get('author_field', 'username'),
                    )
                    creator_result['creator'] = creator_value
                    if not creator_value:
                        creator_result['skipped_reason'] = 'formatted_creator_empty'
                    elif current_creator and not overwrite:
                        creator_result['success'] = True
                        creator_result['skipped_reason'] = 'creator_not_empty'
                    elif creator_value == current_creator:
                        creator_result['success'] = True
                        creator_result['skipped_reason'] = 'already_current'
                    else:
                        plan['set_creator'] = creator_value
                        creator_result['success'] = True
                        creator_result['changed'] = True

                result['creator_sync'] = creator_result
        
        # 1. 执行属性修改 (标签、收藏)
        # 这些操作不改变 ID，先执行
        add_tags = list(plan.get('add_tags', []))
        remove_tags = list(plan.get('remove_tags', []))
        fav = plan.get('favorite')
        
        set_creator = plan.get('set_creator')
        if add_tags or remove_tags or fav is not None or set_creator is not None:
            if set_creator is None:
                success = modify_card_attributes_internal(current_id, add_tags, remove_tags, fav)
            else:
                success = modify_card_attributes_internal(
                    current_id,
                    add_tags,
                    remove_tags,
                    fav,
                    set_creator=set_creator,
                )
            if success:
                result["tags_added"] = add_tags
                result["tags_removed"] = remove_tags
                if fav is not None: result["fav_changed"] = True
                if result.get('creator_sync') and result['creator_sync'].get('changed'):
                    result['creator_sync']['creator'] = set_creator
            elif result.get('creator_sync') and result['creator_sync'].get('changed'):
                result['creator_sync']['success'] = False
                result['creator_sync']['changed'] = False
                result['creator_sync']['error'] = '角色卡元数据写入失败'

        # 1.5 同步名称/文件名（可能改变 ID）
        sync_flags = {
            'set_char_name_from_filename': bool(plan.get('set_char_name_from_filename')),
            'set_wi_name_from_filename': bool(plan.get('set_wi_name_from_filename')),
            'set_filename_from_char_name': bool(plan.get('set_filename_from_char_name')),
            'set_filename_from_wi_name': bool(plan.get('set_filename_from_wi_name')),
            'desired_filename_base': None,
            'desired_filename_template': plan.get('rename_file_by_template'),
            'ui_data': ui_data,
        }
        if any([
            sync_flags['set_char_name_from_filename'],
            sync_flags['set_wi_name_from_filename'],
            sync_flags['set_filename_from_char_name'],
            sync_flags['set_filename_from_wi_name'],
            bool(sync_flags['desired_filename_template']),
        ]):
            ok, new_id, msg, sync_details = sync_card_names_internal(current_id, **sync_flags)
            sync_result = dict(sync_details or {})
            sync_result['success'] = bool(ok)
            sync_result['msg'] = msg
            sync_result['new_id'] = new_id
            result['name_sync'] = sync_result

            if ok:
                current_id = new_id
            else:
                logger.warning(f"Automation name sync failed for {card_id}: {msg}")
                result["final_id"] = current_id
                return result

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
    
    def _source_link_for_card(self, card_id, ui_data=None):
        if ui_data is None:
            ui_data = load_ui_data()
        ui_key = resolve_ui_key(card_id)
        entry = ui_data.get(ui_key) if isinstance(ui_data, dict) else None
        return str(entry.get('link') or '').strip() if isinstance(entry, dict) else ''

    def _fetch_forum_tags(self, card_id, config, ui_data=None, prefetched_source=None):
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
            ui_key = resolve_ui_key(card_id)
            url = self._source_link_for_card(card_id, ui_data)

            if not url:
                logger.warning(f"卡片 {card_id} (ui_key: {ui_key}) 未配置超链接")
                return {'success': False, 'error': '未配置超链接，请在卡片详情中设置来源链接', 'tags': []}

            # 抓取标签
            fetcher = get_tag_fetcher()
            if prefetched_source is not None and not prefetched_source.get('success'):
                return {
                    'success': False,
                    'error': prefetched_source.get('error') or '来源帖子请求失败',
                    'tags': [],
                }
            if prefetched_source is None:
                fetch_result = fetcher.fetch_tags(url)
            else:
                fetch_result = fetcher.fetch_tags(
                    url,
                    prefetched_source=prefetched_source.get('source') or {},
                )

            if not fetch_result['success']:
                logger.warning(f"抓取标签失败: {fetch_result['error']}")
                return fetch_result

            # 处理标签
            cfg = load_config()
            slash_as_separator = bool(cfg.get('automation_slash_is_tag_separator', False))
            processor = TagProcessor(
                exclude_tags=config.get('exclude_tags', []),
                replace_rules=config.get('replace_rules', {}),
                slash_as_separator=slash_as_separator
            )

            processed_tags = processor.process(fetch_result['tags'])
            governed = filter_governed_tags(
                processed_tags,
                ui_data=ui_data,
                known_tags=build_known_tag_set(ui_data=ui_data),
            )
            accepted_tags = governed['accepted']

            # 根据合并模式处理
            merge_mode = config.get('merge_mode', 'merge')
            existing_tags = card_data.get('tags', [])
            final_tags = processor.merge_tags(existing_tags, accepted_tags, merge_mode)

            result = {
                'success': True,
                'tags': final_tags,
                'original_tags': fetch_result['tags'],
                'processed_tags': processed_tags,
                'governed_tags': accepted_tags,
                'title': fetch_result.get('title'),
                'merge_mode': merge_mode
            }
            result.update(build_governance_feedback(governed))
            return result

        except Exception as e:
            logger.error(f"抓取论坛标签时出错: {e}")
            return {'success': False, 'error': str(e), 'tags': []}
