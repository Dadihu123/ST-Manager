"""流式上传/下载与后台备份作业；不接受任意文件路径或下载 URL。"""
import os
import json

from flask import Blueprint, jsonify, request, send_file

from core.services.data_migration_service import DataMigrationService

bp = Blueprint('migration', __name__)
_service = None


def service():
    global _service
    if _service is None:
        _service = DataMigrationService()
    return _service


@bp.errorhandler(Exception)
def migration_error(error):
    return jsonify(success=False, msg=str(error)), 400


@bp.post('/api/migration/export')
def export():
    job = service().new_job('export')
    service().run(job, service().export)
    return jsonify(success=True, id=job)


@bp.get('/api/migration/sources')
def sources():
    return jsonify(success=True, authorization=service().required_source_authorizations())


@bp.post('/api/migration/import')
def begin_import():
    return jsonify(success=True, id=service().new_job('import'))


@bp.put('/api/migration/jobs/<job>/upload')
def upload(job):
    if service().status(job)['state'] != 'queued':
        raise ValueError('任务已使用，请重新选择备份')
    try:
        service().receive(job, request.stream)
    except Exception as exc:
        service().update(job, state='failed', error=str(exc))
        raise
    service().run(job, service().validate)
    return jsonify(success=True)


@bp.get('/api/migration/jobs/<job>')
def status(job):
    return jsonify(success=True, **service().status(job))


@bp.get('/api/migration/jobs/<job>/download')
def download(job):
    state = service().status(job)
    if state['kind'] != 'export' or state['state'] not in ('ready', 'saved', 'save_failed', 'saving'):
        raise ValueError('备份尚未完成')
    return send_file(service().path(job, 'backup.zip'), as_attachment=True,
                     download_name=state['filename'], mimetype='application/zip')


@bp.post('/api/migration/jobs/<job>/transfer')
def transfer(job):
    state = service().status(job)
    data = request.get_json()
    if state['kind'] == 'export' and state['state'] in ('ready', 'saved', 'save_failed', 'saving'):
        service().update(job, state='saved' if data.get('success') is True else 'save_failed',
                         phase=str(data.get('message', '保存失败'))[:1000])
    elif state['kind'] == 'import' and data.get('success') is not True:
        service().update(job, state='failed', error=str(data.get('message', '选择文件失败'))[:1000])
    return jsonify(success=True)


@bp.post('/api/migration/jobs/<job>/restore')
def restore(job):
    if request.get_json().get('confirm') is not True:
        raise ValueError('需要确认覆盖范围')
    service().request_restore(job)
    return jsonify(success=True)


@bp.post('/api/migration/jobs/<job>/save')
def begin_save(job):
    state = service().status(job)
    if state['kind'] != 'export' or state['state'] not in ('ready', 'saved', 'save_failed'):
        raise ValueError('无法开始保存')
    service().update(job, state='saving', phase='等待系统选择位置并写入文件', done=0, total=0)
    return jsonify(success=True)


@bp.get('/api/migration/recovery')
def recovery():
    root = service().root
    for name in ('pending.json', 'last-restore.json'):
        path = os.path.join(root, name)
        if os.path.exists(path):
            with open(path, encoding='utf-8') as handle:
                return jsonify(success=True, recovery=json.load(handle))
    return jsonify(success=True, recovery=None)


@bp.post('/api/migration/legacy-ui')
def legacy_ui():
    if os.path.exists(os.path.join(service().root, 'pending.json')):
        raise ValueError('恢复已准备好，业务写入已暂停，请完全退出并重启应用')
    return jsonify(success=True, imported=service().import_legacy_ui(request.get_json()))
