import logging
import os
import tempfile
import json
import time
from copy import deepcopy

from flask import Blueprint, jsonify, request, send_file
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from core.config import load_config
from core.data.ui_store import (
    load_ui_data,
    save_ui_data,
    set_last_sent_to_st,
    set_last_sent_to_tt,
)
from core.api.v1.system import _format_st_auth_error, _format_st_response_error
from core.services.beautify_service import BeautifyService
from core.services.st_auth import STAuthError, build_st_http_client
from core.services.tavern_theme import activate_sent_theme
from core.services.tauri_tavern_client import (
    build_tauri_tavern_client,
    is_tauri_tavern_target,
)


logger = logging.getLogger(__name__)
bp = Blueprint('beautify', __name__, url_prefix='/api/beautify')


_service = None


def get_beautify_service():
    global _service
    if _service is None:
        _service = BeautifyService()
    return _service


def _error(message, status=400):
    return jsonify({'success': False, 'error': message}), status


def _save_upload_to_temp(upload):
    suffix = os.path.splitext(upload.filename or '')[1]
    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    upload.save(temp_path)
    return temp_path


def _remove_temp_file(temp_path):
    try:
        os.remove(temp_path)
    except OSError:
        pass


def _extract_settings_update_payload(payload):
    source = payload if isinstance(payload, dict) else {}
    extracted = {
        'clear_wallpaper': source.get('clear_wallpaper') is True,
        'clear_character_avatar': source.get('clear_character_avatar') is True,
        'clear_user_avatar': source.get('clear_user_avatar') is True,
    }
    if 'character_name' in source:
        extracted['character_name'] = source.get('character_name')
    if 'user_name' in source:
        extracted['user_name'] = source.get('user_name')
    return extracted


def _extract_package_identity_update_payload(payload):
    source = payload if isinstance(payload, dict) else {}
    extracted = {
        'clear_character_avatar': source.get('clear_character_avatar') is True,
        'clear_user_avatar': source.get('clear_user_avatar') is True,
    }
    if 'character_name' in source:
        extracted['character_name'] = source.get('character_name')
    if 'user_name' in source:
        extracted['user_name'] = source.get('user_name')
    return extracted


def _reject_unsupported_keys(payload, allowed_keys):
    extra_keys = set(payload.keys()) - set(allowed_keys)
    if extra_keys:
        raise ValueError('请求体包含不支持的字段')


def _get_json_object_payload():
    try:
        payload = request.get_json(silent=False)
    except (BadRequest, UnsupportedMediaType):
        return None, _error('请求体必须是 JSON 对象')

    if not isinstance(payload, dict):
        return None, _error('请求体必须是 JSON 对象')
    return payload, None


def _parse_st_settings_payload(response):
    try:
        outer_payload = response.json()
    except (ValueError, TypeError):
        raise ValueError('远程设置数据无效')

    settings_raw = outer_payload.get('settings') if isinstance(outer_payload, dict) else None
    if not isinstance(settings_raw, str):
        raise ValueError('远程设置数据无效')

    try:
        settings_payload = json.loads(settings_raw)
    except (TypeError, ValueError):
        raise ValueError('远程设置数据无效')

    if not isinstance(settings_payload, dict):
        raise ValueError('远程设置数据无效')

    power_user = settings_payload.get('power_user')
    if not isinstance(power_user, dict):
        raise ValueError('远程设置数据无效')

    return settings_payload


def _parse_st_success_response(response):
    if not response.content:
        return 'OK'

    try:
        return response.json()
    except (ValueError, TypeError):
        return response.text or 'OK'


def _json_object(response):
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _restore_st_theme_state(st_client, auth_type, theme_name, previous_theme, previous_settings):
    state_errors = []
    apply_errors = []
    state_failed = False
    state_unknown = False

    def post(path, payload, accepted_statuses=(200,), errors=None):
        nonlocal state_failed, state_unknown
        errors = errors if errors is not None else state_errors
        try:
            response = st_client.post(path, json=payload, timeout=10)
        except STAuthError as error:
            errors.append(_format_st_auth_error(error))
            if errors is state_errors:
                state_unknown = True
            return None
        if response.status_code not in accepted_statuses:
            errors.append(_format_st_response_error(response, auth_type))
            if errors is state_errors:
                state_failed = True
            return None
        return response

    if previous_theme is None:
        post('/api/themes/delete', {'name': theme_name}, accepted_statuses=(200, 404))
    else:
        post('/api/themes/save', previous_theme)

    post('/api/settings/save', previous_settings)

    previous_power_user = previous_settings.get('power_user', {})
    selected_theme = str(previous_power_user.get('theme') or '').strip()
    rollback_theme = previous_theme if selected_theme == theme_name else None
    rollback_response = post('/api/themes/apply', {
        'theme': rollback_theme,
        'power_user': previous_power_user,
        'select_theme': False,
        'remove_theme_name': '' if previous_theme is not None else theme_name,
    }, accepted_statuses=(200, 409), errors=apply_errors)
    rollback_payload = _json_object(rollback_response) if rollback_response is not None else None
    if (rollback_response is not None and rollback_response.status_code == 200
            and rollback_payload and rollback_payload.get('applied') is True):
        rollback_page_state = 'confirmed'
    elif rollback_payload and rollback_payload.get('applied') is False:
        rollback_page_state = 'not_confirmed'
    else:
        rollback_page_state = 'unknown'
    if rollback_page_state != 'confirmed':
        reason = rollback_payload.get('reason') if isinstance(rollback_payload, dict) else ''
        if reason:
            apply_errors.append(f'页面恢复响应：{reason}')
    rollback_state = 'unknown' if state_unknown else ('not_confirmed' if state_failed else 'confirmed')
    return rollback_state, rollback_page_state, state_errors + apply_errors


@bp.route('/list', methods=['GET'])
def list_beautify_packages():
    service = get_beautify_service()
    return jsonify({'success': True, 'items': service.list_packages()})


@bp.route('/<package_id>', methods=['GET'])
def get_beautify_package(package_id):
    service = get_beautify_service()
    package = service.get_package(package_id)
    if not package:
        return _error('美化包不存在', status=404)
    return jsonify({'success': True, 'item': package})


@bp.route('/settings', methods=['GET'])
def get_beautify_settings():
    settings = get_beautify_service().get_global_settings()
    return jsonify({'success': True, 'item': settings})


@bp.route('/update-settings', methods=['POST'])
def update_beautify_settings():
    payload, error_response = _get_json_object_payload()
    if error_response:
        return error_response
    try:
        _reject_unsupported_keys(
            payload,
            {'character_name', 'user_name', 'clear_wallpaper', 'clear_character_avatar', 'clear_user_avatar'},
        )
        settings = get_beautify_service().update_global_settings(_extract_settings_update_payload(payload))
        return jsonify({'success': True, 'item': settings})
    except ValueError as exc:
        return _error(str(exc))


@bp.route('/import-theme', methods=['POST'])
def import_theme():
    upload = request.files.get('file')
    if not upload or not (upload.filename or '').lower().endswith('.json'):
        return _error('请上传 theme JSON 文件')

    temp_path = _save_upload_to_temp(upload)
    try:
        service = get_beautify_service()
        result = service.import_theme(
            temp_path,
            package_id=str(request.form.get('package_id') or '').strip() or None,
            platform=str(request.form.get('platform') or '').strip() or None,
            source_name=upload.filename,
        )
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return _error(str(exc))
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


@bp.route('/import-wallpaper', methods=['POST'])
def import_wallpaper():
    package_id = str(request.form.get('package_id') or '').strip()
    variant_id = str(request.form.get('variant_id') or '').strip()
    upload = request.files.get('file')
    if not package_id or not variant_id:
        return _error('缺少 package_id 或 variant_id')
    if not upload:
        return _error('请上传壁纸文件')

    temp_path = _save_upload_to_temp(upload)
    try:
        service = get_beautify_service()
        result = service.import_wallpaper(package_id, variant_id, temp_path, source_name=upload.filename)
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return _error(str(exc))
    finally:
        _remove_temp_file(temp_path)


@bp.route('/import-global-wallpaper', methods=['POST'])
def import_global_wallpaper():
    upload = request.files.get('file')
    if not upload:
        return _error('请上传壁纸文件')

    temp_path = _save_upload_to_temp(upload)
    try:
        result = get_beautify_service().import_global_wallpaper(temp_path, source_name=upload.filename)
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return _error(str(exc))
    finally:
        _remove_temp_file(temp_path)


@bp.route('/import-global-avatar', methods=['POST'])
def import_global_avatar():
    target = str(request.form.get('target') or '').strip()
    upload = request.files.get('file')
    if not target:
        return _error('缺少 target')
    if target not in ('character', 'user'):
        return _error('无效的头像目标')
    if not upload:
        return _error('请上传头像文件')

    temp_path = _save_upload_to_temp(upload)
    try:
        result = get_beautify_service().import_global_avatar(target, temp_path, source_name=upload.filename)
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return _error(str(exc))
    finally:
        _remove_temp_file(temp_path)


@bp.route('/import-screenshot', methods=['POST'])
def import_screenshot():
    package_id = str(request.form.get('package_id') or '').strip()
    upload = request.files.get('file')
    if not package_id:
        return _error('缺少 package_id')
    if not upload:
        return _error('请上传截图文件')

    temp_path = _save_upload_to_temp(upload)
    try:
        result = get_beautify_service().import_screenshot(package_id, temp_path, source_name=upload.filename)
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return _error(str(exc))
    finally:
        _remove_temp_file(temp_path)


@bp.route('/update-package-identities', methods=['POST'])
def update_package_identities():
    payload, error_response = _get_json_object_payload()
    if error_response:
        return error_response
    package_id = str(payload.get('package_id') or '').strip()
    if not package_id:
        return _error('缺少 package_id')

    try:
        _reject_unsupported_keys(
            payload,
            {'package_id', 'character_name', 'user_name', 'clear_character_avatar', 'clear_user_avatar'},
        )
        item = get_beautify_service().update_package_identities(
            package_id,
            _extract_package_identity_update_payload(payload),
        )
        return jsonify({'success': True, 'item': item})
    except ValueError as exc:
        return _error(str(exc))


@bp.route('/import-package-avatar', methods=['POST'])
def import_package_avatar():
    package_id = str(request.form.get('package_id') or '').strip()
    target = str(request.form.get('target') or '').strip()
    upload = request.files.get('file')
    if not package_id or not target:
        return _error('缺少 package_id 或 target')
    if target not in ('character', 'user'):
        return _error('无效的头像目标')
    if not upload:
        return _error('请上传头像文件')

    temp_path = _save_upload_to_temp(upload)
    try:
        result = get_beautify_service().import_package_avatar(
            package_id,
            target,
            temp_path,
            source_name=upload.filename,
        )
        return jsonify({'success': True, **result})
    except ValueError as exc:
        return _error(str(exc))
    finally:
        _remove_temp_file(temp_path)


@bp.route('/update-variant', methods=['POST'])
def update_variant():
    payload, error_response = _get_json_object_payload()
    if error_response:
        return error_response
    package_id = str(payload.get('package_id') or '').strip()
    variant_id = str(payload.get('variant_id') or '').strip()
    platform = str(payload.get('platform') or '').strip().lower()
    selected_wallpaper_id = str(payload.get('selected_wallpaper_id') or '').strip()
    if not package_id or not variant_id:
        return _error('缺少 package_id 或 variant_id')
    if platform and platform not in ('pc', 'mobile', 'dual'):
        return _error('无效的端类型')
    if not platform and 'selected_wallpaper_id' not in payload:
        return _error('缺少更新内容')

    try:
        item = get_beautify_service().update_variant(
            package_id,
            variant_id,
            platform=platform or None,
            selected_wallpaper_id=selected_wallpaper_id,
        )
        return jsonify({'success': True, 'item': item})
    except ValueError as exc:
        return _error(str(exc))


@bp.route('/send-theme-to-st', methods=['POST'])
def send_theme_to_st():
    payload, error_response = _get_json_object_payload()
    if error_response:
        return error_response

    package_id = str(payload.get('package_id') or '').strip()
    variant_id = str(payload.get('variant_id') or '').strip()
    if not package_id or not variant_id:
        return _error('缺少 package_id 或 variant_id')

    try:
        _reject_unsupported_keys(payload, {'package_id', 'variant_id'})
        service = get_beautify_service()
        theme_bundle = service.build_sendable_theme_bundle(package_id, variant_id)
    except LookupError as exc:
        return _error(str(exc), status=404)
    except ValueError as exc:
        return _error(str(exc))

    cfg = load_config()
    if is_tauri_tavern_target(cfg):
        theme_payload = theme_bundle.get('theme_data') if isinstance(theme_bundle.get('theme_data'), dict) else {}
        try:
            result = build_tauri_tavern_client(cfg).send_theme(theme_payload)
        except (OSError, ValueError) as error:
            return _error(str(error), status=400)

        theme_name = str(theme_payload.get('name') or '').strip()
        ui_data = load_ui_data()
        ui_key = service.get_variant_send_state_key(package_id, variant_id)
        _, last_sent_to_tt = set_last_sent_to_tt(ui_data, ui_key, time.time())
        if not save_ui_data(ui_data):
            return _error('保存发送时间失败', status=500)
        return jsonify({
            'success': True,
            'target': 'tauritavern',
            'theme_name': theme_name,
            'target_path': result['path'],
            'settings_path': result['settings_path'],
            'theme_applied': result.get('theme_applied') is True,
            'last_sent_to_tt': last_sent_to_tt,
        })

    auth_type = str(cfg.get('st_auth_type') or 'basic').strip().lower()
    st_client = build_st_http_client(cfg, timeout=10)
    theme_payload = theme_bundle.get('theme_data') if isinstance(theme_bundle.get('theme_data'), dict) else {}
    theme_name = str(theme_payload.get('name') or '').strip()

    try:
        capability_response = st_client.post('/api/themes/apply-capabilities', json={}, timeout=10)
    except STAuthError as error:
        return _error(_format_st_auth_error(error))

    capabilities = _json_object(capability_response) if capability_response.status_code == 200 else None
    capability_flags = capabilities.get('capabilities') if isinstance(capabilities, dict) else None
    if not isinstance(capability_flags, dict) or not all(
        capability_flags.get(name) is True for name in ('theme_apply_v1', 'theme_rollback_v1')
    ):
        return jsonify({
            'success': False,
            'theme_imported': False,
            'theme_applied': False,
            'error': '连接的 ST 不支持安全主题回滚和即时应用，主题未写入；请更新 ST 后重试。',
        }), 409

    active_clients = capabilities.get('active_clients')
    if type(active_clients) is not int or active_clients < 1:
        return jsonify({
            'success': False,
            'theme_imported': False,
            'theme_applied': False,
            'error': 'ST 当前没有已连接的页面可确认主题应用，请保持 ST 页面打开后重试。',
        }), 409

    try:
        settings_response = st_client.post('/api/settings/get', json={}, timeout=10)
        if settings_response.status_code != 200:
            raise ValueError(_format_st_response_error(settings_response, auth_type))

        settings_payload = _parse_st_settings_payload(settings_response)
        previous_settings = deepcopy(settings_payload)

        theme_response = st_client.post('/api/themes/get', json={'name': theme_name}, timeout=10)
        if theme_response.status_code == 404:
            previous_theme = None
        elif theme_response.status_code != 200:
            raise ValueError(_format_st_response_error(theme_response, auth_type))
        else:
            previous_theme = _json_object(theme_response)
            if not previous_theme or previous_theme.get('name') != theme_name:
                raise ValueError('远程同名主题数据无效，主题未写入')
    except STAuthError as error:
        return _error(_format_st_auth_error(error))
    except ValueError as error:
        return _error(str(error))

    try:
        save_response = st_client.post('/api/themes/save', json=theme_payload, timeout=10)
        if save_response.status_code != 200:
            raise ValueError(_format_st_response_error(save_response, auth_type))

        activate_sent_theme(settings_payload['power_user'], theme_payload)

        settings_save_response = st_client.post('/api/settings/save', json=settings_payload, timeout=10)
        if settings_save_response.status_code != 200:
            raise ValueError(_format_st_response_error(settings_save_response, auth_type))

        apply_response = st_client.post('/api/themes/apply', json={
            'theme': theme_payload,
            'power_user': settings_payload['power_user'],
        }, timeout=10)
        apply_result = _json_object(apply_response)
        if apply_response.status_code != 200 or not apply_result or apply_result.get('applied') is not True:
            reason = apply_result.get('reason') if isinstance(apply_result, dict) else ''
            raise ValueError(f'ST 页面未确认主题应用{f"：{reason}" if reason else ""}')
    except (STAuthError, ValueError) as error:
        detail = _format_st_auth_error(error) if isinstance(error, STAuthError) else str(error)
        rollback_state, rollback_page_state, rollback_errors = _restore_st_theme_state(
            st_client, auth_type, theme_name, previous_theme, previous_settings,
        )
        rollback_confirmed = rollback_state == 'confirmed' and rollback_page_state == 'confirmed'
        rollback_applied = rollback_page_state == 'confirmed'
        rollback_detail = {
            'confirmed': '已确认远端设置和主题恢复',
            'not_confirmed': '远端设置和主题恢复未确认',
            'unknown': '远端设置和主题恢复结果未知',
        }[rollback_state]
        page_detail = {
            'confirmed': '已连接页面已确认恢复旧主题',
            'not_confirmed': '已连接页面未确认恢复旧主题',
            'unknown': '无法确认已连接页面是否恢复旧主题',
        }[rollback_page_state]
        if rollback_errors:
            rollback_detail += '；' + '；'.join(rollback_errors)
        return jsonify({
            'success': False,
            'theme_imported': False if rollback_state == 'confirmed' else None,
            'theme_applied': False,
            'rollback_confirmed': rollback_confirmed,
            'rollback_state': rollback_state,
            'rollback_page_state': rollback_page_state,
            'rollback_applied': rollback_applied,
            'error': f'主题应用失败：{detail}；{rollback_detail}；{page_detail}',
        }), 409

    st_response = _parse_st_success_response(save_response)
    ui_data = load_ui_data()
    ui_key = service.get_variant_send_state_key(package_id, variant_id)
    _, last_sent_to_st = set_last_sent_to_st(ui_data, ui_key, time.time())
    if not save_ui_data(ui_data):
        return _error('保存发送时间失败', status=500)

    return jsonify({
        'success': True,
        'theme_imported': True,
        'theme_applied': True,
        'theme_name': theme_name,
        'st_response': st_response,
        'last_sent_to_st': last_sent_to_st,
    })


@bp.route('/delete-package', methods=['POST'])
def delete_package():
    payload, error_response = _get_json_object_payload()
    if error_response:
        return error_response
    package_id = str(payload.get('package_id') or '').strip()
    if not package_id:
        return _error('缺少 package_id')

    try:
        deleted = get_beautify_service().delete_package(package_id)
    except OSError:
        logger.warning('删除美化包文件失败，资源可能仍被占用: %s', package_id, exc_info=True)
        return _error('美化包文件仍被占用，请关闭预览后重试', status=409)
    except Exception:
        logger.error('删除美化包失败: %s', package_id, exc_info=True)
        return _error('删除美化包失败，请稍后重试', status=500)
    if not deleted:
        return _error('美化包不存在', status=404)
    return jsonify({'success': True})


@bp.route('/preview-asset/<path:subpath>', methods=['GET'])
def preview_asset(subpath):
    asset_path = get_beautify_service().get_preview_asset_path(subpath)
    if not asset_path:
        return _error('资源不存在', status=404)
    return send_file(asset_path)
