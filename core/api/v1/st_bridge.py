"""ST Bridge API —— 让 SillyTavern 直接浏览并装载 ST-Manager 的角色卡。

流程：浏览（只读）→ 装载（复制进酒馆角色目录）→ 在酒馆里改 → 提交回原卡（带备份与冲突检测）。

接口只服务本机：CORS 仅对 ``127.0.0.1`` / ``localhost`` 来源放行，避免任意网页读写你的卡库。
"""

import logging
import re

from flask import Blueprint, jsonify, request

from core.services import st_bridge_service
from core.services.st_bridge_service import StBridgeError

logger = logging.getLogger(__name__)

bp = Blueprint('st_bridge', __name__, url_prefix='/api/st_bridge')

LOCAL_ORIGIN_PATTERN = re.compile(
    r'^https?://(127\.0\.0\.1|localhost|\[::1\])(:\d+)?$',
    re.IGNORECASE,
)


@bp.after_request
def _allow_local_origin(response):
    """酒馆页面跑在 127.0.0.1:8000，需要跨端口直接调用这些接口。"""
    origin = request.headers.get('Origin', '')
    if origin and LOCAL_ORIGIN_PATTERN.match(origin):
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
        response.headers['Access-Control-Max-Age'] = '600'
        response.headers.setdefault('Vary', 'Origin')
    return response


def _json_payload():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _respond(handler):
    """统一把业务异常转成 JSON 错误，不向客户端暴露堆栈。"""
    try:
        return jsonify(handler())
    except StBridgeError as exc:
        payload = {'success': False, 'error': exc.message}
        payload.update(exc.extra)
        return jsonify(payload), exc.status_code
    except Exception as exc:  # noqa: BLE001 - 兜底，保证接口永远返回 JSON
        logger.error('st_bridge 操作失败: %s', exc, exc_info=True)
        return jsonify({'success': False, 'error': '服务端处理失败'}), 500


@bp.route('/status', methods=['GET'])
def api_status():
    """待定清单概览。``?verify=1`` 会逐张比对原卡哈希（慢，按需用）。"""
    verify = str(request.args.get('verify', '')).lower() in ('1', 'true', 'yes')
    return _respond(lambda: st_bridge_service.status(verify=verify))


@bp.route('/public_tree', methods=['GET'])
def api_public_tree():
    """库目录树，供酒馆的分类栏渲染。"""
    return _respond(st_bridge_service.public_tree)


@bp.route('/checkout', methods=['POST'])
def api_checkout():
    """把一张库卡复制进酒馆角色目录（不修改原卡）。"""
    card_id = str(_json_payload().get('card_id') or '').strip()
    if not card_id:
        return jsonify({'success': False, 'error': '缺少 card_id'}), 400
    return _respond(lambda: st_bridge_service.checkout(card_id))


@bp.route('/commit', methods=['POST'])
def api_commit():
    """把待定副本写回原卡；``force=true`` 可覆盖装载后被改过的原卡。"""
    payload = _json_payload()
    staged_name = str(payload.get('staged_name') or payload.get('card_id') or '').strip()
    if not staged_name:
        return jsonify({'success': False, 'error': '缺少 staged_name'}), 400
    force = bool(payload.get('force')) or str(request.args.get('force', '')).lower() in ('1', 'true', 'yes')
    return _respond(lambda: st_bridge_service.commit(staged_name, force=force))


@bp.route('/discard', methods=['POST'])
def api_discard():
    """丢弃待定副本，原卡不受影响。"""
    payload = _json_payload()
    staged_name = str(payload.get('staged_name') or payload.get('card_id') or '').strip()
    if not staged_name:
        return jsonify({'success': False, 'error': '缺少 staged_name'}), 400
    return _respond(lambda: st_bridge_service.discard(staged_name))
