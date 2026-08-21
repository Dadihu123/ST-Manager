"""类脑搜索站相关 API。"""

import logging

from flask import Blueprint, jsonify, request

from core.services.shimmerday_forum_service import fetch_thread_preview

logger = logging.getLogger(__name__)
bp = Blueprint('forum', __name__)


@bp.route('/api/forum/thread_preview', methods=['POST'])
def api_forum_thread_preview():
    """根据角色卡来源链接转发查询类脑搜索站帖子详情。"""
    data = request.get_json(silent=True) or {}
    source_link = data.get('source_link')
    card_id = data.get('card_id')

    if not source_link and not card_id:
        return jsonify({'success': False, 'msg': '请提供 source_link 或 card_id'}), 400

    try:
        result = fetch_thread_preview(source_link=source_link, card_id=card_id)
    except Exception as exc:
        logger.error('类脑搜索站预览失败: %s', exc)
        return jsonify({'success': False, 'msg': f'预览失败: {exc}'}), 500

    status = 200 if result.get('success') else 400
    return jsonify(result), status
