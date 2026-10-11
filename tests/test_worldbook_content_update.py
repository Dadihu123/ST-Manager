import hashlib
import io
import json
import os
import socketserver
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.api.v1 import world_info as api
from core.api.v1 import system as system_api
from core.services import worldbook_content_update as updates
from core.utils.source_revision import build_file_source_revision


def book(content='旧内容', **extra):
    return {'entries': {'0': {'uid': 0, 'key': ['灯塔'], 'content': content}}, **extra}


@pytest.fixture
def fixture(monkeypatch, tmp_path):
    lore = tmp_path / 'lorebooks'
    resources = tmp_path / 'resources'
    cards = tmp_path / 'characters'
    for folder in (lore, resources, cards):
        folder.mkdir()
    path = lore / '保留名字.json'
    path.write_text(json.dumps(book(), ensure_ascii=False), encoding='utf-8')
    cfg = {'world_info_dir': str(lore), 'resources_dir': str(resources), 'snapshot_limit_manual': 5}
    for module in (api, system_api):
        monkeypatch.setattr(module, 'BASE_DIR', str(tmp_path))
        monkeypatch.setattr(module, 'DATA_DIR', str(tmp_path / 'data'))
        monkeypatch.setattr(module, 'CARDS_FOLDER', str(cards))
        monkeypatch.setattr(module, 'load_config', lambda: cfg)
        monkeypatch.setattr(module, 'suppress_fs_events', lambda *_: None)
        monkeypatch.setattr(module, 'invalidate_wi_list_cache', lambda: None)
    monkeypatch.setattr(api, '_enqueue_worldinfo_file_refresh', lambda *_: None)
    monkeypatch.setattr(api, 'reconcile_entry_history_scope', lambda **_: None)
    monkeypatch.setattr(api, 'move_entry_history_scope', lambda **_: None)
    monkeypatch.setattr(api, 'append_entry_history_records', lambda **_: None)
    monkeypatch.setattr(api, 'load_ui_data', lambda: {'notes': '用户本地备注'})
    monkeypatch.setattr(api, 'save_ui_data', lambda *_: pytest.fail('更新不能改写本地备注'))
    app = Flask(__name__)
    app.register_blueprint(api.bp)
    app.register_blueprint(system_api.bp)
    return app, path, cfg, tmp_path


def preview(client, path, text=None, source_type='global'):
    return client.post('/api/world_info/update/preview', json={
        'file_path': str(path), 'source_type': source_type,
        'source_text': text or json.dumps(book('新内容'), ensure_ascii=False),
    })


def commit(client, path, result, source_type='global'):
    return client.post('/api/world_info/update/commit', json={
        'file_path': str(path), 'source_type': source_type,
        'source_text': result['source_text'], 'source_revision': result['source_revision'],
    })


def test_file_update_keeps_target_notes_unknown_fields_numbers_and_supports_existing_rollback(fixture):
    app, path, cfg, root = fixture
    client = app.test_client()
    original = path.read_bytes()
    other = path.with_name('来源名字.json')
    other.write_bytes(original)
    incoming = json.dumps(book('新内容', name='来源名字', plugin={'counter': 9223372036854775807123}), ensure_ascii=False)
    response = client.post('/api/world_info/update/preview', data={
        'file_path': str(path), 'source_type': 'global',
        'file': (io.BytesIO(incoming.encode()), '任意文件名.txt'),
    })
    assert response.status_code == 200
    result = response.get_json()
    assert result['target_name'] == path.name
    assert result['source_revision'] == hashlib.sha256(original).hexdigest()
    assert path.read_bytes() == original
    response = commit(client, path, result)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload['new_path'] == str(path)
    assert payload['source_revision'] == build_file_source_revision(str(path))
    assert path.read_text() == result['source_text']
    assert 'name' not in json.loads(path.read_text())
    assert json.loads(path.read_text())['plugin']['counter'] == 9223372036854775807123
    assert other.read_bytes() == original
    assert Path(payload['backup_path']).read_bytes() == original
    listed = client.post('/api/list_backups', json={'id': 'global::' + str(path), 'type': 'lorebook', 'file_path': str(path)}).get_json()
    assert payload['backup_path'] in [item['path'] for item in listed['backups']]
    restored = client.post('/api/restore_backup', json={'backup_path': payload['backup_path'], 'target_id': 'global::' + str(path), 'type': 'lorebook', 'target_file_path': str(path)})
    assert restored.get_json()['success']
    assert path.read_bytes() == original


def test_resource_book_and_array_entries_are_supported(fixture):
    app, _, cfg, _ = fixture
    path = Path(cfg['resources_dir']) / '角色' / 'lorebooks' / '资源.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(book()))
    result = preview(app.test_client(), path, json.dumps({'entries': [{'content': '数组条目', 'keys': ['测试']}]}), 'resource').get_json()
    assert result['success']
    assert commit(app.test_client(), path, result, 'resource').get_json()['success']


@pytest.mark.parametrize('source', [
    '<html>登录页面</html>', '{"entries": null}', '{"entries": {"0": "bad"}}',
    '{"entries":{"0":{"content":12}}}', '{"entries":{"0":{"content":"ok","key":"bad"}}}',
    '{"entries":{}, "bad": NaN}', '{"entries":{}, "entries":{}}', '[]',
])
def test_invalid_sources_do_not_mutate_target_or_make_backups(fixture, source):
    app, path, _, root = fixture
    original = path.read_bytes()
    response = preview(app.test_client(), path, source)
    assert response.status_code == 400
    assert not response.get_json()['success']
    assert path.read_bytes() == original
    assert not (root / 'data' / 'system' / 'backups').exists()


def test_stale_hash_detects_same_size_same_mtime_edit_and_can_recompare(fixture):
    app, path, _, _ = fixture
    client = app.test_client()
    initial = preview(client, path).get_json()
    before = path.stat()
    changed = path.read_bytes().replace('旧'.encode(), '改'.encode())
    path.write_bytes(changed)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert commit(client, path, initial).status_code == 409
    assert path.read_bytes() == changed
    updated = preview(client, path, initial['source_text']).get_json()
    assert updated['source_revision'] != initial['source_revision']
    assert commit(client, path, updated).get_json()['success']


def test_target_deleted_after_preview_is_not_recreated(fixture):
    app, path, _, _ = fixture
    result = preview(app.test_client(), path).get_json()
    path.unlink()
    response = commit(app.test_client(), path, result)
    assert response.status_code == 404
    assert not path.exists()


def test_backup_failure_blocks_replacement(fixture, monkeypatch):
    app, path, _, _ = fixture
    result = preview(app.test_client(), path).get_json()
    original = path.read_bytes()
    monkeypatch.setattr(updates, 'write_update_backup', lambda *_: (_ for _ in ()).throw(OSError('磁盘满')))
    response = commit(app.test_client(), path, result)
    assert response.status_code == 500
    assert response.get_json()['code'] == 'backup_failed'
    assert path.read_bytes() == original


def test_edit_during_backup_is_detected(fixture, monkeypatch):
    app, path, _, _ = fixture
    result = preview(app.test_client(), path).get_json()
    write_backup = updates.write_update_backup
    changed = json.dumps(book('外部新编辑')).encode()
    def write_and_edit(*args):
        backup = write_backup(*args)
        path.write_bytes(changed)
        return backup
    monkeypatch.setattr(updates, 'write_update_backup', write_and_edit)
    response = commit(app.test_client(), path, result)
    assert response.status_code == 409
    assert path.read_bytes() == changed


def test_atomic_failure_keeps_original_and_removes_temporary_file(fixture, monkeypatch):
    app, path, _, _ = fixture
    result = preview(app.test_client(), path).get_json()
    original = path.read_bytes()
    replace = updates.os.replace
    def fail_selected(src, dst):
        if dst == str(path):
            raise OSError('写入失败')
        return replace(src, dst)
    monkeypatch.setattr(updates.os, 'replace', fail_selected)
    assert commit(app.test_client(), path, result).status_code == 500
    assert path.read_bytes() == original
    assert not list(path.parent.glob('*.tmp'))


@pytest.mark.parametrize('source_type', ['embedded', 'unknown', ''])
def test_non_independent_targets_are_rejected(fixture, source_type):
    app, path, _, _ = fixture
    assert preview(app.test_client(), path, source_type=source_type).status_code == 400


def test_outside_card_and_symlink_targets_are_rejected(fixture):
    app, path, cfg, root = fixture
    client = app.test_client()
    outside = root / 'outside.json'
    outside.write_text(json.dumps(book()))
    card = root / 'characters' / 'card.json'
    card.write_text(json.dumps(book()))
    link = path.with_name('symlink.json')
    link.symlink_to(outside)
    for target in (outside, card, link):
        assert preview(client, target).status_code == 400
    wrong_resource = Path(cfg['resources_dir']) / 'direct.json'
    wrong_resource.write_text(json.dumps(book()))
    assert preview(client, wrong_resource, source_type='resource').status_code == 400


def test_concurrent_commit_accepts_only_one_candidate(fixture):
    app, path, _, _ = fixture
    first = preview(app.test_client(), path).get_json()
    second = dict(first, source_text=json.dumps(book('另一个候选')))
    barrier = threading.Barrier(2)
    def execute(result):
        barrier.wait()
        return commit(app.test_client(), path, result).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(execute, [first, second]))
    assert sorted(statuses) == [200, 409]


def test_existing_editor_save_serializes_with_update_lock(fixture):
    app, path, _, _ = fixture
    started = threading.Event()
    def save():
        started.set()
        return app.test_client().post('/api/world_info/save', json={
            'save_mode': 'overwrite', 'file_path': str(path), 'content': book('编辑器新编辑'),
            'source_revision': build_file_source_revision(str(path)),
        })
    with ThreadPoolExecutor(max_workers=1) as pool:
        with updates.worldbook_target_lock(str(path)):
            future = pool.submit(save)
            assert started.wait(1)
            assert not future.done()
        assert future.result(timeout=3).get_json()['success']
    assert json.loads(path.read_text())['entries']['0']['content'] == '编辑器新编辑'


def test_source_size_limit_applies_before_any_mutation(fixture, monkeypatch):
    app, path, _, _ = fixture
    monkeypatch.setattr(updates, 'MAX_SOURCE_BYTES', 80)
    original = path.read_bytes()
    result = preview(app.test_client(), path, json.dumps(book('长' * 100)))
    assert result.status_code == 413
    assert path.read_bytes() == original


@pytest.fixture
def source_server():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            if self.path in ('/redirect', '/loop', '/badredirect'):
                self.send_response(302)
                self.send_header('Location', {'/redirect': '/book', '/loop': '/loop', '/badredirect': 'file:///etc/passwd'}[self.path])
                self.end_headers()
                return
            if self.path == '/missing':
                self.send_error(404)
                return
            self.send_response(200)
            self.end_headers()
            payload = '<html>not a book</html>' if self.path == '/html' else json.dumps(book('URL 内容'), ensure_ascii=False)
            self.wfile.write(payload.encode())
    class LocalServer(ThreadingHTTPServer):
        def server_bind(self):
            socketserver.TCPServer.server_bind(self)
            self.server_name, self.server_port = self.server_address
    server = LocalServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.mark.parametrize('suffix,status', [('/book', 200), ('/redirect', 200), ('/loop', 502), ('/badredirect', 400), ('/missing', 502), ('/html', 400)])
def test_real_url_fetch_validates_redirects_status_and_content(fixture, source_server, suffix, status):
    app, path, _, _ = fixture
    original = path.read_bytes()
    response = app.test_client().post('/api/world_info/update/preview', json={
        'file_path': str(path), 'source_type': 'global', 'url': source_server + suffix,
    })
    assert response.status_code == status
    assert path.read_bytes() == original
    if status == 200:
        assert 'URL 内容' in response.get_json()['source_text']


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'ftp://example.org/book', 'http://user:secret@localhost/book', 'http://localhost:bad/book'])
def test_unsafe_protocol_and_userinfo_are_rejected(fixture, url):
    app, path, _, _ = fixture
    response = app.test_client().post('/api/world_info/update/preview', json={'file_path': str(path), 'source_type': 'global', 'url': url})
    assert response.status_code == 400
    assert 'secret' not in response.get_data(as_text=True)


def test_url_timeout_error_does_not_echo_private_url(fixture, monkeypatch):
    app, path, _, _ = fixture
    def timeout(*_, **__):
        raise updates.requests.Timeout('secret-token')
    monkeypatch.setattr(updates.requests.Session, 'get', timeout)
    response = app.test_client().post('/api/world_info/update/preview', json={'file_path': str(path), 'source_type': 'global', 'url': 'http://localhost/book?secret-token'})
    assert response.status_code == 502
    assert 'secret-token' not in response.get_data(as_text=True)


def test_existing_root_name_is_preserved_in_preview_and_revalidated_at_commit(fixture):
    app, path, _, _ = fixture
    path.write_text(json.dumps(book(name='保持显示名称'), ensure_ascii=False))
    result = preview(app.test_client(), path, json.dumps(book('新版', name='来源名称'), ensure_ascii=False)).get_json()
    assert json.loads(result['source_text'])['name'] == '保持显示名称'
    result['source_text'] = json.dumps(book('新版', name='手动修改请求'), ensure_ascii=False)
    assert commit(app.test_client(), path, result).get_json()['success']
    assert json.loads(path.read_text())['name'] == '保持显示名称'


def test_single_book_move_waits_for_update_lock(fixture, monkeypatch):
    app, path, _, _ = fixture
    monkeypatch.setattr(api, '_remap_global_worldinfo_note_path', lambda *_: None)
    started = threading.Event()
    def move():
        started.set()
        return app.test_client().post('/api/world_info/category/move', json={
            'source_type': 'global', 'file_path': str(path), 'target_category': '新分类',
        })
    with ThreadPoolExecutor(max_workers=1) as pool:
        with updates.worldbook_target_lock(str(path)):
            future = pool.submit(move)
            assert started.wait(1)
            assert not future.done()
        response = future.result(timeout=3).get_json()
        assert response['success']
    assert not path.exists()
    assert Path(response['path']).exists()


def test_url_stream_size_is_rejected_before_target_read(fixture, source_server, monkeypatch):
    app, path, _, _ = fixture
    original = path.read_bytes()
    monkeypatch.setattr(updates, 'MAX_SOURCE_BYTES', 60)
    monkeypatch.setattr(api, 'read_target', lambda *_: pytest.fail('超限来源不能继续读写目标'))
    response = app.test_client().post('/api/world_info/update/preview', json={
        'file_path': str(path), 'source_type': 'global', 'url': source_server + '/book',
    })
    assert response.status_code == 413
    assert response.get_json()['code'] == 'source_too_large'
    assert path.read_bytes() == original


def test_commit_revalidates_source_and_requires_preview_revision(fixture):
    app, path, _, root = fixture
    client = app.test_client()
    original = path.read_bytes()
    result = preview(client, path).get_json()
    invalid = dict(result, source_text='{"entries": {"0": {"content": 42}}}')
    assert commit(client, path, invalid).status_code == 400
    missing = dict(result, source_revision='')
    assert commit(client, path, missing).status_code == 409
    assert path.read_bytes() == original
    assert not (root / 'data' / 'system' / 'backups').exists()


def test_configured_root_symlink_is_allowed_without_allowing_escape(fixture):
    app, path, cfg, root = fixture
    alias = root / 'configured-alias'
    alias.symlink_to(path.parent, target_is_directory=True)
    cfg['world_info_dir'] = str(alias)
    selected = alias / path.name
    result = preview(app.test_client(), selected).get_json()
    assert result['success']
    response = commit(app.test_client(), selected, result)
    assert response.get_json()['success']
    assert json.loads(path.read_text())['entries']['0']['content'] == '新内容'


def test_ordinary_save_keeps_in_root_file_symlink_and_updates_real_book(fixture):
    app, path, _, _ = fixture
    linked_path = path.with_name('链接入口.json')
    linked_path.symlink_to(path)
    old_revision = build_file_source_revision(str(linked_path))
    response = app.test_client().post('/api/world_info/save', json={
        'save_mode': 'overwrite', 'file_path': str(linked_path),
        'content': book('从现有符号链接编辑'), 'source_revision': old_revision,
    })
    assert response.status_code == 200
    result = response.get_json()
    assert result['success']
    assert linked_path.is_symlink()
    assert linked_path.resolve() == path
    assert json.loads(path.read_text())['entries']['0']['content'] == '从现有符号链接编辑'
    assert linked_path.read_bytes() == path.read_bytes()
    assert result['source_revision'] == build_file_source_revision(str(path))
    assert result['source_revision'] != old_revision


def test_update_does_not_follow_file_symlink_inserted_at_write_boundary(fixture, monkeypatch):
    app, path, _, root = fixture
    result = preview(app.test_client(), path).get_json()
    outside = root / 'outside.json'
    outside.write_bytes(path.read_bytes())
    original = outside.read_bytes()
    atomic = updates.atomic_write_bytes
    def insert_link(target, raw, expected_revision=None):
        if target == str(path) and expected_revision is not None:
            path.unlink()
            path.symlink_to(outside)
        return atomic(target, raw, expected_revision=expected_revision)
    monkeypatch.setattr(updates, 'atomic_write_bytes', insert_link)
    response = commit(app.test_client(), path, result)
    assert response.status_code == 400
    assert response.get_json()['code'] == 'invalid_target'
    assert outside.read_bytes() == original


@pytest.mark.parametrize('content_type', ['multipart/form-data', 'application/x-www-form-urlencoded'])
def test_commit_rejects_cross_site_form_even_for_known_target_revision(fixture, content_type):
    from core.auth import init_auth

    app, path, _, _ = fixture
    app.secret_key = 'worldbook-update-test-only'
    init_auth(app)
    original = path.read_bytes()
    response = app.test_client().post('/api/world_info/update/commit', data={
        'file_path': str(path), 'source_type': 'global',
        'source_text': json.dumps(book('跨站覆盖')),
        'source_revision': hashlib.sha256(original).hexdigest(),
    }, content_type=content_type, headers={'Origin': 'https://foreign.example'},
        environ_overrides={'REMOTE_ADDR': '127.0.0.1'})
    assert response.status_code == 415
    assert path.read_bytes() == original


@pytest.mark.parametrize('source', ['url', 'source_text'])
def test_preview_requires_json_for_non_file_sources(fixture, monkeypatch, source):
    app, path, _, _ = fixture
    calls = []
    def fetch(url):
        calls.append(url)
        return json.dumps(book('来源内容')).encode()
    monkeypatch.setattr(api, 'fetch_source', fetch)
    original = path.read_bytes()
    response = app.test_client().post('/api/world_info/update/preview', data={
        'file_path': str(path), 'source_type': 'global',
        source: 'https://example.com/book.json' if source == 'url' else json.dumps(book('来源内容')),
    }, content_type='multipart/form-data')
    assert response.status_code == 415
    assert calls == []
    assert path.read_bytes() == original


@pytest.mark.parametrize('has_target_name', [True, False])
def test_name_preservation_keeps_dense_preview_within_commit_limit(fixture, monkeypatch, has_target_name):
    app, path, _, _ = fixture
    current = book(name='目标世界书') if has_target_name else book()
    path.write_text(json.dumps(current, ensure_ascii=False), encoding='utf-8')
    monkeypatch.setattr(updates, 'MAX_SOURCE_BYTES', 800)
    source = json.dumps(book(name='来源名称', plugin=[0] * 200), ensure_ascii=False, separators=(',', ':'))
    assert len(source.encode('utf-8')) < updates.MAX_SOURCE_BYTES
    client = app.test_client()
    response = preview(client, path, source)
    assert response.status_code == 200
    candidate = response.get_json()
    assert len(candidate['source_text'].encode('utf-8')) <= updates.MAX_SOURCE_BYTES
    assert commit(client, path, candidate).get_json()['success']
    saved = json.loads(path.read_text())
    assert saved['plugin'] == [0] * 200
    assert saved.get('name') == current.get('name')


@pytest.mark.parametrize('has_target_name', [True, False])
def test_name_preservation_does_not_roundtrip_unknown_numbers(fixture, has_target_name):
    app, path, _, _ = fixture
    current = book(name='保留书名') if has_target_name else book()
    path.write_text(json.dumps(current, ensure_ascii=False), encoding='utf-8')
    source = '{"name":"来源", "entries":{}, "plugin":{"precise":0.1234567890123456789012345,"tiny":1e-400}}'
    candidate = preview(app.test_client(), path, source).get_json()
    assert '0.1234567890123456789012345' in candidate['source_text']
    assert '1e-400' in candidate['source_text']
    assert commit(app.test_client(), path, candidate).get_json()['success']
    assert '0.1234567890123456789012345' in path.read_text()
    assert '1e-400' in path.read_text()


@pytest.mark.parametrize('stem', ['x' * 237, '长' * 79])
def test_long_file_name_save_update_list_and_restore(fixture, stem):
    app, path, _, _ = fixture
    long_path = path.with_name(stem + '.json')
    path.rename(long_path)
    client = app.test_client()
    response = client.post('/api/world_info/save', json={
        'save_mode': 'overwrite', 'file_path': str(long_path), 'content': book('游玩修改'),
        'source_revision': build_file_source_revision(str(long_path)),
    })
    assert response.get_json()['success']
    original = long_path.read_bytes()
    candidate = preview(client, long_path).get_json()
    result = commit(client, long_path, candidate).get_json()
    assert result['success']
    backups = client.post('/api/list_backups', json={
        'type': 'lorebook', 'file_path': str(long_path),
    }).get_json()['backups']
    assert result['backup_path'] in [item['path'] for item in backups]
    restored = client.post('/api/restore_backup', json={
        'type': 'lorebook', 'backup_path': result['backup_path'], 'target_file_path': str(long_path),
    })
    assert restored.get_json()['success']
    assert long_path.read_bytes() == original


def test_retention_keeps_current_pre_update_backup_despite_future_snapshot_mtime(fixture):
    import time

    app, path, cfg, root = fixture
    cfg['snapshot_limit_manual'] = 1
    original = path.read_bytes()
    folder = root / 'data/system/backups/lorebooks' / path.stem
    folder.mkdir(parents=True)
    old = folder / f'{path.stem}_old.json'
    old.write_text(json.dumps(book('另一份旧快照')), encoding='utf-8')
    future = time.time() + 3600
    os.utime(old, (future, future))
    client = app.test_client()
    result = commit(client, path, preview(client, path).get_json()).get_json()
    assert result['success']
    assert Path(result['backup_path']).read_bytes() == original
    assert len(list(folder.glob('*.json'))) == 1
