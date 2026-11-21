import sys, os, runpy, json, sqlite3, subprocess, tempfile
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
runpy.run_path('tests/conftest.py')
from flask import Flask
from PIL import Image
from core import config
from core.context import ctx
from core.data import local_state_repository as s, db_session, ui_store, chat_store
from core.data.cache import GlobalMetadataCache
from core.services import card_service, index_build_service, index_job_worker, cache_service
from core.api.v1 import cards
from core.utils.png_metadata import build_card_pnginfo
from core.utils.image import extract_card_info

def bind(root):
    cfg={'cards_dir':str(root/'cards'),'resources_dir':str(root/'resources'),'world_info_dir':str(root/'worlds'), 'chats_dir':str(root/'chats')}
    for x in ('cards','resources','worlds','chats'): (root/x).mkdir(exist_ok=True)
    for module in list(sys.modules.values()):
        if not getattr(module,'__name__','').startswith('core'): continue
        for name,value in [('DEFAULT_DB_PATH',str(root/'db.sqlite')),('CARDS_FOLDER',str(root/'cards')),('UI_DATA_FILE',str(root/'ui.json')),('CHAT_DATA_FILE',str(root/'chat.json')),('CONFIG_FILE',str(root/'config.json'))]:
            if hasattr(module,name):setattr(module,name,value)
        if hasattr(module,'load_config'):setattr(module,'load_config',lambda:dict(cfg))
    s._ready.clear()

def child(root,mode):
    bind(root)
    scan_first = mode.endswith('_scan_first')
    if scan_first:
        mode = mode.removesuffix('_scan_first')
    if mode.endswith('_early_worker'):
        import threading
        prepare = index_job_worker.prepare_card_file_intent
        def prepare_and_claim(*args, **kwargs):
            job_id = prepare(*args, **kwargs)
            claimed = threading.Event()
            errors = []
            def process():
                try:
                    rows, _ = index_job_worker._claim_pending_jobs(50)
                    row = next(row for row in rows if row['id'] == job_id)
                    claimed.set()
                    index_job_worker.process_card_job(row, json.loads(row['payload_json']))
                except BaseException as exc:
                    errors.append(exc)
                    claimed.set()
            thread = threading.Thread(target=process, daemon=True)
            thread.start()
            assert claimed.wait(5), 'worker did not claim the actual durable intent'
            thread.join(0.2)
            assert not errors, errors
            assert thread.is_alive(), 'worker consumed intent before file replace'
            with sqlite3.connect(root/'db.sqlite') as conn:
                assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (job_id,)).fetchone()[0] == 'running'
            return job_id
        index_job_worker.prepare_card_file_intent = prepare_and_claim
        mode = mode.removesuffix('_early_worker')
    with sqlite3.connect(root/'db.sqlite') as c:db_session._initialize_database(c,is_existing_db=True,schema_only=True)
    s.initialize(); s.Repository().replace_snapshot({'hero.png':{'summary':'keep me'}})
    for path,description in [(root/'cards/hero.png','old body'),(root/'upload.png','NEW BODY')]:
        Image.new('RGB',(8,8),'blue').save(path,pnginfo=build_card_pnginfo(json.dumps({'data':{'name':'Hero','description':description}})))
    ctx.cache=GlobalMetadataCache();ctx.cache.id_map={'hero.png':{'id':'hero.png','char_name':'Hero','tags':[],'source_update':{'last_status':'unchecked'}}}
    with Flask(__name__).app_context():cache_service.update_card_cache('hero.png',str(root/'cards/hero.png'))
    with sqlite3.connect(root/'db.sqlite') as conn:
        conn.execute("UPDATE card_metadata SET is_favorite=1 WHERE id='hero.png'")
        uid = conn.execute("SELECT card_uid FROM card_metadata WHERE id='hero.png'").fetchone()[0]
    (root/'original-identity').write_text(uid)
    with sqlite3.connect(root/'db.sqlite') as c:
        c.row_factory=sqlite3.Row;c.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='cards'"); c.commit()
        index_build_service.apply_card_increment(c,'hero.png',str(root/'cards/hero.png'));c.execute('DELETE FROM index_jobs');c.commit()
    if mode == 'world_ack':
        from core.utils.image import write_card_metadata
        path = root/'cards/hero.png'
        info = extract_card_info(str(path))
        info['data']['character_book'] = {'name': 'OldBook', 'entries': [{'content': 'OLD'}]}
        assert write_card_metadata(str(path), info, prepare_intent=False)
        with Flask(__name__).app_context():
            cache_service.update_card_cache('hero.png', str(path))
        with sqlite3.connect(root/'db.sqlite') as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='worldinfo'")
            conn.commit()
            index_build_service.apply_worldinfo_embedded_increment(conn, 'hero.png', str(path))
            conn.execute('DELETE FROM index_jobs')
        cards.sync_card_index_jobs = lambda **kwargs: os._exit(75)
        app = Flask(__name__)
        app.register_blueprint(cards.bp)
        app.teardown_appcontext(db_session.close_connection)
        app.test_client().post('/api/update_card', json={'id': 'hero.png', 'char_name': 'Hero',
            'description': 'new body', 'character_book': {'name': 'NewBook', 'entries': [{'content': 'NEW'}]}})
    elif mode.startswith('upload'):
        original=os.replace
        def die(src,dst):
            result=original(src,dst)
            if str(src).endswith('.png.tmp') and str(dst)==str(root/'cards/hero.png'):os._exit(73)
            return result
        os.replace=die
        with Flask(__name__).app_context():card_service.update_card_content('hero.png',str(root/'upload.png'),False,{},'.png')
    elif mode == 'change_image' or mode.startswith('convert'):
        import io
        card_id = 'hero.png'
        if mode.startswith('convert'):
            card_id = 'hero.json'
            from core.utils.data import normalize_card_v3
            (root/'cards/hero.json').write_text(json.dumps(normalize_card_v3({'data': {'name': 'Hero', 'description': 'old body'}})))
            if mode == 'convert_before_plain':
                Image.new('RGB', (8, 8), 'blue').save(root/'cards/hero.png')
            (root/'original-json').write_bytes((root/'cards/hero.json').read_bytes())
            (root/'original-png').write_bytes((root/'cards/hero.png').read_bytes())
            s.Repository().replace_snapshot({'hero.json': {'summary': 'keep me', 'chat_ids': ['chat']}})
            with sqlite3.connect(root/'db.sqlite') as c:
                c.execute("UPDATE card_metadata SET id='hero.json' WHERE id='hero.png'")
        original = os.replace
        if scan_first:
            original_remove = os.remove
            def remove_and_exit(path):
                result = original_remove(path)
                if str(path) == str(root/'cards/hero.json'):
                    os._exit(76)
                return result
            os.remove = remove_and_exit
        def die(src, dst):
            if (mode.startswith('convert_before') and str(src).endswith('.png.tmp')
                    and str(dst) == str(root/'cards/hero.png')):
                os._exit(74)
            result = original(src, dst)
            if not scan_first and str(src).endswith('.png.tmp') and str(dst) == str(root/'cards/hero.png'):
                os._exit(73)
            return result
        os.replace = die
        uploaded = io.BytesIO()
        Image.new('RGB', (8,8), 'red').save(uploaded, 'PNG')
        uploaded.seek(0)
        app = Flask(__name__)
        app.register_blueprint(cards.bp)
        app.test_client().post('/api/change_image', data={'id': card_id, 'image': (uploaded, 'new.png')})
    elif mode in ('folder', 'folder_legacy'):
        pack = root/'cards/pack'
        pack.mkdir()
        (pack/'.bundle').write_text('')
        os.rename(root/'cards/hero.png', pack/'hero.png')
        entry = {'summary': 'keep me', 'chat_ids': ['chat']}
        if mode == 'folder':
            entry['_version_remarks'] = {'pack/hero.png': {'summary': 'version note'}}
        s.Repository().replace_snapshot({'pack': entry})
        with sqlite3.connect(root/'db.sqlite') as conn:
            conn.execute("UPDATE card_metadata SET id='pack/hero.png' WHERE id='hero.png'")
            conn.row_factory = sqlite3.Row
            index_build_service.apply_card_increment(conn, 'pack/hero.png', str(pack/'hero.png'), remove_entity_ids=['hero.png'])
            conn.execute('DELETE FROM index_jobs')
            conn.commit()
        original = os.rename
        def die(src, dst):
            result = original(src, dst)
            if str(dst) == str(root/'cards/renamedpack'):
                os._exit(73)
            return result
        os.rename = die
        app = Flask(__name__)
        app.register_blueprint(cards.bp)
        response = app.test_client().post('/api/rename_folder', json={'old_path': 'pack', 'new_name': 'renamedpack'})
        raise RuntimeError(response.get_json())
    else:
        original=os.rename
        def die(src,dst):
            result=original(src,dst)
            if str(dst)==str(root/'cards/renamed.png'):os._exit(73)
            return result
        os.rename=die
        app=Flask(__name__);app.register_blueprint(cards.bp)
        if mode == 'automation':
            from core.automation.executor import AutomationExecutor
            with app.app_context():
                AutomationExecutor().apply_plan('hero.png', {'rename_file_by_template': 'renamed'})
        else:
            app.test_client().post('/api/update_card',json={'id':'hero.png','new_filename':'renamed.png','ui_only':True})
    raise RuntimeError('crash point was not reached')



def recover(root, mode):
    bind(root)
    scan_first = mode.endswith('_scan_first')
    mode = mode.removesuffix('_scan_first')
    mode = mode.removesuffix('_early_worker')
    with sqlite3.connect(root/'db.sqlite') as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM index_jobs WHERE status IN ('pending','running','failed')").fetchall()
    assert rows
    if mode == 'world_ack':
        assert any(row['job_type'] == 'upsert_world_embedded' for row in rows)
        assert all(row['job_type'] != 'upsert_card' for row in rows)
        for row in rows:
            with index_job_worker._connect() as conn:
                index_job_worker.process_worldinfo_job(conn, row)
        with sqlite3.connect(root/'db.sqlite') as conn:
            assert conn.execute('SELECT character_book_name FROM card_metadata').fetchone()[0] == 'NewBook'
            assert conn.execute("SELECT name FROM index_entities_v2 WHERE entity_id='world::embedded::hero.png'").fetchone()[0] == 'NewBook'
        assert extract_card_info(str(root/'cards/hero.png'))['data']['character_book']['name'] == 'NewBook'
        return
    from core.services import wi_entry_history_service as history
    uid = (root/'original-identity').read_text()
    if scan_first or mode in ('rename', 'automation') or mode.startswith('folder'):
        assert history.append_entry_history_records('embedded', uid, '', [
            {'entry_uid': 'row-1', 'snapshot': {'content': 'previous version'}}], limit=10) == 1
    if scan_first:
        from core.services import scan_service
        for status in ('pending', 'running', 'failed'):
            with sqlite3.connect(root/'db.sqlite') as conn:
                conn.execute('UPDATE index_jobs SET status=? WHERE id=?', (status, rows[0]['id']))
            scan_service._perform_scan_logic_inner(str(root/'db.sqlite'), str(root/'cards'))
            with sqlite3.connect(root/'db.sqlite') as conn:
                assert conn.execute('SELECT id,is_favorite,card_uid FROM card_metadata').fetchall() == [('hero.json', 1, uid)]
                assert conn.execute('SELECT COUNT(*) FROM wi_entry_history').fetchone()[0] == 1
    if mode.startswith('upload_note'):
        ctx.cache = GlobalMetadataCache()
        ctx.cache.initialized = True
        ctx.cache.id_map = {'hero.png': {'id': 'hero.png', 'tags': [],
                                        'source_update': {'last_status': 'unchecked'}}}
        if mode.endswith('running'):
            with sqlite3.connect(root/'db.sqlite') as conn:
                conn.execute("UPDATE index_jobs SET status='running' WHERE id=?", (rows[0]['id'],))
        app = Flask(__name__)
        app.register_blueprint(cards.bp)
        app.teardown_appcontext(db_session.close_connection)
        response = app.test_client().post('/api/update_card', json={
            'id': 'hero.png', 'ui_only': True, 'ui_only_fields': ['ui_summary'],
            'ui_summary': 'note after crash',
        }).get_json()
        assert response['success'], response
        with sqlite3.connect(root/'db.sqlite') as conn:
            status = conn.execute('SELECT status FROM index_jobs WHERE id=?', (rows[0]['id'],)).fetchone()[0]
            assert status == ('running' if mode.endswith('running') else 'pending')
            assert conn.execute("SELECT description FROM card_metadata WHERE id='hero.png'").fetchone()[0] == 'old body'
    for row in rows:
        assert not row['entity_id'].endswith('.tmp')
        index_job_worker.process_card_job(row, json.loads(row['payload_json']))
    if mode.startswith('convert_before'):
        assert (root/'cards/hero.json').read_bytes() == (root/'original-json').read_bytes()
        assert (root/'cards/hero.png').read_bytes() == (root/'original-png').read_bytes()
        assert s.Repository().get('hero.json')['summary'] == 'keep me'
        assert s.Repository().get('hero.png') is None
        with sqlite3.connect(root/'db.sqlite') as conn:
            assert conn.execute('SELECT id,description FROM card_metadata').fetchall() == [('hero.json', 'old body')]
            assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE status!='done'").fetchone()[0] == 0
        return
    target_id = ('renamedpack/hero.png' if mode.startswith('folder') else
                 'renamed.png' if mode in ('rename', 'automation') else 'hero.png')
    expected_body = 'NEW BODY' if mode.startswith('upload') else 'old body'
    with sqlite3.connect(root/'db.sqlite') as conn:
        assert conn.execute('SELECT id,description FROM card_metadata').fetchall() == [(target_id, expected_body)]
        assert conn.execute('SELECT is_favorite,card_uid FROM card_metadata WHERE id=?', (target_id,)).fetchone() == (1, uid)
        assert conn.execute('SELECT favorite FROM index_entities_v2 WHERE entity_id=?', ('card::' + target_id,)).fetchone()[0] == 1
        entity = conn.execute('SELECT entity_id FROM index_entities_v2 WHERE entity_type=?', ('card',)).fetchall()
        assert entity == [('card::' + target_id,)]
        assert conn.execute("SELECT COUNT(*) FROM index_jobs WHERE job_type='upsert_card' AND status!='done'").fetchone()[0] == 0
    snapshot = s.Repository().export_snapshot()
    ui_key = 'renamedpack' if mode.startswith('folder') else target_id
    assert snapshot[ui_key]['summary'] == ('note after crash' if mode.startswith('upload_note') else 'keep me')
    if mode.startswith('folder'):
        assert 'pack' not in snapshot
        assert snapshot[ui_key]['chat_ids'] == ['chat']
        expected_note = 'version note' if mode == 'folder' else 'keep me'
        with sqlite3.connect(root/'db.sqlite') as conn:
            assert conn.execute('SELECT summary_preview FROM index_entities_v2 WHERE entity_id=?',
                                ('card::' + target_id,)).fetchone()[0] == expected_note
    if mode == 'convert':
        assert snapshot[target_id]['chat_ids'] == ['chat']
        assert 'hero.json' not in snapshot
        assert not (root/'cards/hero.json').exists()
    assert extract_card_info(str(root/'cards'/target_id))['data']['description'] == expected_body
    if mode in ('change_image', 'convert'):
        assert Image.open(root/'cards'/target_id).getpixel((0,0)) == (255,0,0)
    if scan_first or mode in ('rename', 'automation') or mode.startswith('folder'):
        assert history.purge_orphaned_entry_history(cards_root=root/'cards', world_info_root=root/'worlds',
            resources_root=root/'resources', db_path=root/'db.sqlite') == 0


def rename_hook(root):
    """Actual request / worker / synchronous v3 plugin, with deterministic scheduling."""
    import threading
    from core.plugins.api import PluginAPI
    from core.plugins.manifest import PluginManifest
    from tests.plugins_test_support import write_plugin
    from core.services import card_operation_lock as locks

    crash = subprocess.run([sys.executable, '-X', 'utf8', __file__, str(root), 'upload', 'crash'],
                           capture_output=True, timeout=60)
    assert crash.returncode == 73, crash.stdout + crash.stderr
    recover(root, 'upload')
    ctx.cache = GlobalMetadataCache()
    ctx.cache.initialized = True
    ctx.cache.id_map = {'hero.png': {'id': 'hero.png', 'filename': 'hero.png', 'tags': [],
                                    'source_update': {'last_status': 'unchecked'}}}
    with sqlite3.connect(root/'db.sqlite') as conn:
        conn.execute('DELETE FROM index_jobs')
    attempted = threading.Event()
    hook_entered = threading.Event()
    acquire, prepare = locks.try_acquire_card_lock, index_job_worker.prepare_card_file_intent
    threads, responses, errors = [], [], []
    def observe(card_id, **kwargs):
        if threading.current_thread().name == 'rename-worker' and card_id == '0hero.png':
            attempted.set()
        return acquire(card_id, **kwargs)
    locks.try_acquire_card_lock = observe
    def prepare_and_start(*args, **kwargs):
        job_id = prepare(*args, **kwargs)
        if kwargs.get('operation_kind') == 'rename':
            def process():
                try:
                    rows, _ = index_job_worker._claim_pending_jobs(50)
                    row = next(row for row in rows if row['id'] == job_id)
                    index_job_worker.process_card_job(row, json.loads(row['payload_json']))
                except BaseException as exc:
                    errors.append(repr(exc))
            thread = threading.Thread(target=process, name='rename-worker', daemon=True)
            threads.append(thread)
            thread.start()
            assert attempted.wait(5), 'worker did not attempt the published intent'
        return job_id
    index_job_worker.prepare_card_file_intent = prepare_and_start
    api = PluginAPI(PluginManifest.load(write_plugin(root, 'sync-rename')))
    def on_update(payload):
        hook_entered.set()
        assert api.cards.write_fields(payload['card_id'], {'description': 'synchronous plugin body'})
    api.on('card.updated', on_update)
    app = Flask(__name__)
    app.register_blueprint(cards.bp)
    app.teardown_appcontext(db_session.close_connection)
    def request():
        try:
            responses.append(app.test_client().post('/api/update_card', json={
                'id': 'hero.png', 'new_filename': '0hero.png', 'ui_only': True}).get_json())
        except BaseException as exc:
            errors.append(repr(exc))
    request_thread = threading.Thread(target=request, daemon=True)
    request_thread.start()
    request_thread.join(10)
    assert not request_thread.is_alive(), 'rename request and worker deadlocked'
    for thread in threads:
        thread.join(10)
        assert not thread.is_alive(), 'worker did not release rename locks'
    assert hook_entered.is_set() and not errors, errors
    assert responses and responses[0]['success'], responses
    with sqlite3.connect(root/'db.sqlite') as conn:
        assert conn.execute("SELECT description FROM card_metadata WHERE id='0hero.png'").fetchone()[0] == 'synchronous plugin body'
        assert conn.execute('SELECT is_favorite,card_uid FROM card_metadata').fetchone() == (1, (root/'original-identity').read_text())
    assert extract_card_info(str(root/'cards/0hero.png'))['data']['description'] == 'synchronous plugin body'


def move_chain(root, operation):
    from core.automation.executor import AutomationExecutor
    from core.services import scan_service

    crash = subprocess.run([sys.executable, '-X', 'utf8', __file__, str(root), 'upload', 'crash'],
                           capture_output=True, timeout=60)
    assert crash.returncode == 73, crash.stdout + crash.stderr
    recover(root, 'upload')
    uid = (root/'original-identity').read_text()
    ctx.cache = GlobalMetadataCache()
    ctx.cache.initialized = True
    ctx.cache.id_map = {'hero.png': {'id': 'hero.png', 'filename': 'hero.png', 'tags': [],
                                    'source_update': {'last_status': 'unchecked'}}}
    s.Repository().update_fields('_worldinfo_notes_v1', {'embedded::hero.png': {'summary': 'owner note'}})
    with sqlite3.connect(root/'db.sqlite') as conn:
        conn.execute('DELETE FROM index_jobs')
        conn.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='worldinfo'")
        if operation == 'without_generation':
            conn.execute("UPDATE index_build_state SET active_generation=0 WHERE scope='cards'")
    app = Flask(__name__)
    app.register_blueprint(cards.bp)
    app.teardown_appcontext(db_session.close_connection)
    client = app.test_client()
    current = 'hero.png'
    vacated = [current]
    for target in ('first', 'second'):
        if operation == 'automation':
            with app.app_context():
                result = AutomationExecutor().apply_plan(current, {'rename_file_by_template': target})
            assert result['name_sync']['success'], result
            new_id = result['final_id']
        elif operation == 'move':
            result = client.post('/api/move_card', json={'card_id': current, 'target_category': target}).get_json()
            assert result['success'], result
            new_id = result['moved_details'][0]['new_id']
        elif operation == 'folder':
            if '/' not in current:
                result = client.post('/api/move_card', json={'card_id': current, 'target_category': 'pack'}).get_json()
                assert result['success'], result
                current = result['moved_details'][0]['new_id']
                vacated.append(current)
            result = client.post('/api/rename_folder', json={'old_path': current.rpartition('/')[0],
                                                           'new_name': target}).get_json()
            assert result['success'], result
            new_id = result['new_path'] + '/hero.png'
        else:
            payload = {'id': current, 'new_filename': target + '.png', 'ui_only': operation != 'body',
                       'ui_summary': 'keep me'}
            if operation == 'body':
                payload.update(char_name='Hero', description=target + ' body')
            result = client.post('/api/update_card', json=payload).get_json()
            assert result['success'], result
            new_id = result['new_id']
        current = new_id
        vacated.append(current)
        with sqlite3.connect(root/'db.sqlite') as conn:
            assert not index_job_worker.pending_card_file_ids(conn)
            assert conn.execute('SELECT id,is_favorite,card_uid FROM card_metadata').fetchall() == [(current, 1, uid)]
        assert s.Repository().get(current)['summary'] == 'keep me'
        assert s.Repository().get('_worldinfo_notes_v1')['embedded::' + current]['summary'] == 'owner note'

    if operation == 'deleted':
        cards.TRASH_FOLDER = str(root/'trash')
        result = client.post('/api/delete_cards', json={'card_ids': [current]}).get_json()
        assert result['success'], result
    for card_id in vacated[:-1]:
        path = root/'cards'/card_id
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (8, 8), 'green').save(path, pnginfo=build_card_pnginfo(json.dumps({
            'data': {'name': 'Independent ' + card_id, 'description': 'independent body'}})))
    if operation == 'without_generation':
        from core.services.index_upgrade_service import rebuild_scope_generation
        rebuild_scope_generation('cards', reason='test_startup')
    class OneIteration:
        def __init__(self): self.calls = 0
        def wait(self, *_args):
            self.calls += 1
            if self.calls > 1: raise StopIteration()
            return True
        def set(self): pass
        def clear(self): pass
    for _ in range(2):
        ctx.index_wakeup = OneIteration()
        with sqlite3.connect(root/'db.sqlite') as conn:
            conn.execute("UPDATE index_jobs SET finished_at=0 WHERE status='failed'")
        try: index_job_worker.worker_loop()
        except StopIteration: pass
        scan_service._perform_scan_logic_inner(str(root/'db.sqlite'), str(root/'cards'))
    scan_service._perform_scan_logic_inner(str(root/'db.sqlite'), str(root/'cards'))
    with sqlite3.connect(root/'db.sqlite') as conn:
        discovered = dict(conn.execute('SELECT id,char_name FROM card_metadata'))
        for card_id in vacated[:-1]:
            assert discovered[card_id] == 'Independent ' + card_id
        assert not index_job_worker.pending_card_file_ids(conn)
        assert conn.execute("SELECT entity_id,error_msg FROM index_jobs WHERE status!='done'").fetchall() == []
        if operation == 'deleted':
            assert current not in discovered
        else:
            assert conn.execute('SELECT is_favorite,card_uid FROM card_metadata WHERE id=?', (current,)).fetchone() == (1, uid)


def move_ack_failure(root, failure):
    from core.automation.executor import AutomationExecutor
    crash = subprocess.run([sys.executable, '-X', 'utf8', __file__, str(root), 'upload', 'crash'],
                           capture_output=True, timeout=60)
    assert crash.returncode == 73, crash.stdout + crash.stderr
    recover(root, 'upload')
    with sqlite3.connect(root/'db.sqlite') as conn:
        conn.execute('DELETE FROM index_jobs')
    ctx.cache = GlobalMetadataCache()
    ctx.cache.initialized = True
    ctx.cache.id_map = {'hero.png': {'id': 'hero.png', 'filename': 'hero.png', 'tags': [],
                                    'source_update': {'last_status': 'unchecked'}}}
    app = Flask(__name__)
    app.register_blueprint(cards.bp)
    app.teardown_appcontext(db_session.close_connection)
    enqueue, complete, save = index_job_worker.enqueue_index_job, index_job_worker.complete_card_file_move, card_service.save_ui_data
    unrelated = None
    if failure == 'world':
        def fail(job_type, **kwargs):
            if job_type == 'upsert_world_owner' and kwargs.get('conn') is not None:
                raise OSError('world intent unavailable')
            return enqueue(job_type, **kwargs)
        index_job_worker.enqueue_index_job = fail
    elif failure == 'revision':
        def fail(*args, **kwargs):
            kwargs['source_revision'] = 'unapplied revision'
            return complete(*args, **kwargs)
        index_job_worker.complete_card_file_move = fail
    elif failure == 'ui':
        card_service.save_ui_data = lambda *_args, **_kwargs: False
    elif failure == 'unrelated_receipt':
        unrelated = index_job_worker.prepare_card_file_intent(str(root/'cards/renamed.png'),
            old_path=str(root/'cards/hero.png'), operation_kind='rename')
    if failure == 'ui':
        with app.app_context():
            result = AutomationExecutor().apply_plan('hero.png', {'rename_file_by_template': 'renamed'})
        assert not result['name_sync']['success'], result
    else:
        result = app.test_client().post('/api/update_card', json={
            'id': 'hero.png', 'new_filename': 'renamed.png', 'ui_only': True,
            'ui_summary': 'keep me'}).get_json()
        assert result['success'] == (unrelated is not None), result
    index_job_worker.enqueue_index_job, index_job_worker.complete_card_file_move, card_service.save_ui_data = enqueue, complete, save
    assert (root/'cards/renamed.png').is_file() and not (root/'cards/hero.png').exists()
    with index_job_worker._connect() as conn:
        rows = conn.execute("SELECT * FROM index_jobs WHERE job_type='upsert_card' AND status!='done'").fetchall()
        file_rows = [row for row in rows if json.loads(row['payload_json']).get('refresh_file')]
        assert file_rows, 'failed or unrelated work was incorrectly acknowledged'
        if unrelated:
            assert [row['id'] for row in file_rows] == [unrelated]
    for row in file_rows:
        index_job_worker.process_card_job(row, json.loads(row['payload_json']))
    with sqlite3.connect(root/'db.sqlite') as conn:
        assert conn.execute('SELECT id,is_favorite,card_uid FROM card_metadata').fetchall() == [
            ('renamed.png', 1, (root/'original-identity').read_text())]
        assert not index_job_worker.pending_card_file_ids(conn)
    assert s.Repository().get('renamed.png')['summary'] == 'keep me'
    assert s.Repository().get('hero.png') is None


def conversion_ui_migration(root, operation, failure):
    """Exercise authoritative UI failure and recovery through the real APIs/worker."""
    import io
    import threading

    crash = subprocess.run([sys.executable, '-X', 'utf8', __file__, str(root), 'upload', 'crash'],
                           capture_output=True, timeout=60)
    assert crash.returncode == 73, crash.stdout + crash.stderr
    recover(root, 'upload')
    old_id = 'hero.png' if operation == 'image' else 'hero.json'
    target_id = 'Pack/hero.json' if operation == 'bundle' else 'hero.png'
    ui_key = 'Pack' if operation == 'bundle' else target_id
    info = extract_card_info(str(root/'cards/hero.png'))
    info['data']['character_book'] = {'name': 'Hero book', 'entries': [{'content': 'embedded entry'}]}
    if old_id.endswith('.json'):
        (root/'cards/hero.json').write_text(json.dumps(info), encoding='utf-8')
        (root/'cards/hero.png').unlink()
    else:
        from core.utils.image import write_card_metadata
        assert write_card_metadata(str(root/'cards/hero.png'), info, prepare_intent=False)
    s.Repository().replace_snapshot({old_id: {'summary': 'precious note', 'chat_ids': ['chat-one'],
                                            'resource_folder': 'assets-for-hero', 'link': 'https://example.com'},
        '_worldinfo_notes_v1': {'embedded::' + old_id: {'summary': 'embedded world note'}}})
    with index_job_worker._connect() as conn:
        conn.execute('UPDATE card_metadata SET id=?', (old_id,))
        conn.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='worldinfo'")
        conn.commit()
        index_build_service.apply_card_increment(conn, old_id, str(root/'cards'/old_id),
                                                remove_entity_ids=['hero.png'] if old_id != 'hero.png' else [])
        conn.execute('DELETE FROM index_jobs')
        if failure == 'sqlite':
            conn.execute("CREATE TRIGGER ui_move_failure BEFORE DELETE ON ui_records "
                         "WHEN OLD.key='hero.json' BEGIN SELECT RAISE(ABORT, 'UI migration unavailable'); END")
    ctx.cache = GlobalMetadataCache()
    ctx.cache.initialized = True
    if failure != 'cold':
        ctx.cache.id_map = {old_id: {'id': old_id, 'filename': old_id, 'tags': [],
                                    'source_update': {'last_status': 'unchecked'}}}
    save = cards.save_ui_data
    injected = []
    def interleaved_save(snapshot, **kwargs):
        if not injected:
            injected.append(True)
            if failure == 'false':
                return False
            if failure in ('binding', 'note'):
                errors = []
                def change_ui():
                    try:
                        if failure == 'binding':
                            s.Repository().update_fields(old_id, {'chat_ids': ['chat-one', 'chat-two']})
                        else:
                            s.NamespaceRepository('_worldinfo_notes_v1').update_fields(
                                'embedded::' + old_id, {'summary': 'concurrent world note'})
                    except BaseException as exc:
                        errors.append(repr(exc))
                thread = threading.Thread(target=change_ui, daemon=True)
                thread.start()
                thread.join(5)
                assert not thread.is_alive() and not errors, errors
        return save(snapshot, **kwargs)
    cards.save_ui_data = interleaved_save
    app = Flask(__name__)
    app.register_blueprint(cards.bp)
    app.teardown_appcontext(db_session.close_connection)
    client = app.test_client()
    remove, replace, rename, move = os.remove, os.replace, os.rename, cards.shutil.move
    if failure.startswith('sidecar_'):
        from core.consts import SIDECAR_EXTENSIONS
        for extension in SIDECAR_EXTENSIONS:
            cover = root/'cards'/('hero' + extension)
            Image.new('RGB', (8, 8), 'green').save(cover, 'JPEG' if extension == '.jfif' else None)
            (root/('original' + extension)).write_bytes(cover.read_bytes())
        def move_then_exit(source, target, *args, **kwargs):
            result = move(source, target, *args, **kwargs)
            if str(source) == str(root/'cards/hero.json') and failure not in (
                    'sidecar_normal', 'sidecar_middle', 'sidecar_last', 'sidecar_ack'):
                os._exit(73)
            return result
        def rename_then_exit(source, target, *args, **kwargs):
            result = rename(source, target, *args, **kwargs)
            if (failure == 'sidecar_middle' and str(source).endswith('hero.webp')
                    or failure == 'sidecar_last' and str(source).endswith('hero.jfif')):
                os._exit(73)
            return result
        cards.shutil.move, os.rename = move_then_exit, rename_then_exit
        if failure == 'sidecar_ack':
            index_job_worker.complete_card_path_companions = lambda *_args, **_kwargs: None
    if failure == 'readonly':
        import stat
        (root/'cards'/old_id).chmod(stat.S_IREAD)
    if failure == 'cleanup':
        def fail_cleanup(path, *args, **kwargs):
            if str(path) == str(root/'cards'/old_id):
                raise PermissionError('source cleanup unavailable')
            return remove(path, *args, **kwargs)
        os.remove = fail_cleanup
    if failure == 'replace':
        def fail_replace(source, target, *args, **kwargs):
            if str(target) == str(root/'cards'/target_id):
                raise PermissionError('target replace unavailable')
            return replace(source, target, *args, **kwargs)
        os.replace = fail_replace
    if failure == 'marker':
        def fail_marker(*args, **kwargs):
            raise OSError('bundle marker unavailable')
        cards.open = fail_marker
    if operation == 'bundle':
        result = client.post('/api/convert_to_bundle', json={'card_id': old_id, 'bundle_name': 'Pack'}).get_json()
    else:
        image = io.BytesIO()
        Image.new('RGB', (8, 8), 'red').save(image, 'PNG')
        image.seek(0)
        result = client.post('/api/change_image', data={'id': old_id, 'image': (image, 'new.png')}).get_json()
    if failure == 'marker':
        del cards.open
    os.remove, os.replace, os.rename, cards.shutil.move = remove, replace, rename, move
    cards.save_ui_data = save
    if failure.startswith('sidecar_'):
        if failure == 'sidecar_ack':
            assert result['success'] is False and result['retryable'], result
            with index_job_worker._connect() as conn:
                assert target_id in index_job_worker.pending_card_file_ids(conn)
            os._exit(73)
        assert result['success'], result
        return
    if failure == 'replace':
        assert not result['success'] and not (root/'cards'/target_id).exists(), result
        for field in ('file_modified', 'source_cleanup_pending', 'index_sync_pending',
                      'retryable', 'detail_reload_required', 'ui_data_saved'):
            assert result[field] is False, result
        with index_job_worker._connect() as conn:
            rows = conn.execute("SELECT * FROM index_jobs WHERE status!='done'").fetchall()
        for row in rows:
            index_job_worker.process_card_job(row, json.loads(row['payload_json']))
        assert s.Repository().get(old_id)['summary'] == 'precious note'
        with index_job_worker._connect() as conn:
            assert not index_job_worker.pending_card_file_ids(conn)
            assert conn.execute('SELECT id,is_favorite FROM card_metadata').fetchall()[0][:] == (old_id, 1)
        return
    assert (root/'cards'/target_id).is_file()
    failed = failure not in ('normal', 'cold')
    assert result['success'] == (not failed), result
    with index_job_worker._connect() as conn:
        protected = index_job_worker.pending_card_file_ids(conn)
        if failed:
            assert result['file_modified'] and not result['ui_data_saved'], result
            assert result['retryable'] and result['index_sync_pending'] and result['detail_reload_required'], result
            assert result['new_id'] == target_id, result
            assert target_id in protected, 'UI failure incorrectly acknowledged the file intent'
            assert s.Repository().get(old_id)['summary'] == 'precious note'
            if failure in ('readonly', 'cleanup'):
                assert result['source_cleanup_pending'] is True, result
                assert (root/'cards'/old_id).is_file()
                assert extract_card_info(str(root/'cards'/target_id))['data'] == info['data']
                if failure == 'readonly':
                    row = conn.execute("SELECT * FROM index_jobs WHERE json_extract(payload_json,'$.refresh_file')=1").fetchone()
                    try:
                        index_job_worker.process_card_job(row, json.loads(row['payload_json']))
                    except PermissionError:
                        pass
                    else:
                        raise AssertionError('readonly source cleanup unexpectedly succeeded')
                    assert target_id in index_job_worker.pending_card_file_ids(conn)
                    import stat
                    (root/'cards'/old_id).chmod(stat.S_IREAD | stat.S_IWRITE)
        else:
            assert not protected, protected
        conn.execute('DROP TRIGGER IF EXISTS ui_move_failure')
    ctx.cache = GlobalMetadataCache()
    if failure == 'readonly':
        # Exercise real retry selection without waiting for the production backoff.
        index_job_worker.INDEX_JOB_RETRY_SECONDS = 0
    class OneIteration:
        def __init__(self):
            self.calls = 0
        def wait(self, *_args):
            self.calls += 1
            if self.calls > 1:
                raise StopIteration()
            return True
        def clear(self):
            pass
        def set(self):
            pass
    for _ in range(3):
        ctx.index_wakeup = OneIteration()
        try:
            index_job_worker.worker_loop()
        except StopIteration:
            pass
    snapshot = s.Repository().export_snapshot()
    entry = snapshot[ui_key]
    assert entry['chat_ids'] == (['chat-one', 'chat-two'] if failure == 'binding' else ['chat-one'])
    assert entry['resource_folder'] == 'assets-for-hero' and entry['link'] == 'https://example.com'
    remark = entry['_version_remarks'][target_id] if operation == 'bundle' else entry
    assert remark['summary'] == 'precious note', snapshot
    note = snapshot['_worldinfo_notes_v1']['embedded::' + target_id]
    assert note['summary'] == ('concurrent world note' if failure == 'note' else 'embedded world note')
    if old_id != target_id:
        assert old_id not in snapshot and 'embedded::' + old_id not in snapshot['_worldinfo_notes_v1']
    if operation == 'bundle':
        assert target_id not in snapshot, 'bundle UI was recovered under a version file key'
        assert (root/'cards/Pack/.bundle').is_file()
    with sqlite3.connect(root/'db.sqlite') as conn:
        assert conn.execute('SELECT id,is_favorite,card_uid FROM card_metadata').fetchall() == [
            (target_id, 1, (root/'original-identity').read_text())]
        assert not index_job_worker.pending_card_file_ids(conn)
        assert not conn.execute("SELECT id,status FROM index_jobs WHERE status!='done'").fetchall()
        assert conn.execute("SELECT name FROM index_entities_v2 WHERE entity_type='world_embedded'").fetchall() == [('Hero book',)]


def recover_bundle_companions(root, mode):
    from core.consts import SIDECAR_EXTENSIONS
    from core.utils.image import find_sidecar_image
    bind(root)
    ctx.cache = GlobalMetadataCache()
    with index_job_worker._connect() as conn:
        row = conn.execute("SELECT * FROM index_jobs WHERE json_extract(payload_json,'$.bundle_conversion')=1").fetchone()
        payload = json.loads(row['payload_json'])
        assert len(payload['companions']) == len(SIDECAR_EXTENSIONS)
        assert all(not item.get('refresh_file') for item in payload['companions'])
        assert not conn.execute("SELECT id FROM index_jobs WHERE entity_id IN ('hero.png','Pack/hero.png')").fetchall()
    source, target = root/'cards/hero.png', root/'cards/Pack/hero.png'
    if mode == 'recovery_middle':
        rename = os.rename
        def rename_and_exit(original, destination):
            rename(original, destination)
            if str(destination).endswith('hero.webp'):
                os._exit(74)
        os.rename = rename_and_exit
    original_bytes = source.read_bytes() if source.exists() else None
    if mode == 'changed':
        source.write_bytes(b'changed companion')
    elif mode == 'collision':
        Image.new('RGB', (8, 8), 'red').save(target)
    elif mode == 'missing':
        source.unlink()
    elif mode == 'access':
        evidence = index_job_worker._file_commit_evidence
        def inaccessible(path):
            if str(path) == str(source):
                raise PermissionError('companion unavailable')
            return evidence(path)
        index_job_worker._file_commit_evidence = inaccessible
    if mode in ('changed', 'collision', 'missing', 'access'):
        before_source = source.read_bytes() if source.exists() else None
        before_target = target.read_bytes() if target.exists() else None
        try:
            index_job_worker.process_card_job(row, payload)
        except OSError:
            pass
        else:
            raise AssertionError('incomplete companion move was acknowledged')
        assert (source.read_bytes() if source.exists() else None) == before_source
        assert (target.read_bytes() if target.exists() else None) == before_target
        with index_job_worker._connect() as conn:
            assert {'hero.json', 'Pack/hero.json', 'hero.png', 'Pack/hero.png'} <= index_job_worker.pending_card_file_ids(conn)
            assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (row['id'],)).fetchone()[0] != 'done'
        if mode == 'changed':
            # Restoring bytes alone changes identity; retain the true original for the next retry.
            source.write_bytes(original_bytes)
            expected = payload['companions'][0]['evidence']
            os.utime(source, ns=(os.stat(source).st_atime_ns, expected['mtime_ns']))
        elif mode == 'collision':
            target.unlink()
        elif mode == 'missing':
            # Missing source cannot be safely recreated with a different inode; test preserves retry.
            return
        elif mode == 'access':
            index_job_worker._file_commit_evidence = evidence
    if mode != 'normal':
        index_job_worker.process_card_job(row, payload)
        index_job_worker.process_card_job(row, payload)
    for extension in SIDECAR_EXTENSIONS:
        assert not (root/'cards'/('hero' + extension)).exists()
        assert (root/'cards/Pack'/('hero' + extension)).read_bytes() == (root/('original' + extension)).read_bytes()
    assert find_sidecar_image(str(root/'cards/Pack/hero.json')) == str(root/'cards/Pack/hero.png')
    snapshot = s.Repository().export_snapshot()
    assert snapshot['Pack']['_version_remarks']['Pack/hero.json']['summary'] == 'precious note'
    assert snapshot['Pack']['chat_ids'] == ['chat-one']
    assert snapshot['_worldinfo_notes_v1']['embedded::Pack/hero.json']['summary'] == 'embedded world note'
    class OneIteration:
        def __init__(self):
            self.calls = 0
        def wait(self, *_args):
            self.calls += 1
            if self.calls > 1:
                raise StopIteration()
            return True
        def clear(self):
            pass
        def set(self):
            pass
    for _ in range(3):
        ctx.index_wakeup = OneIteration()
        try:
            index_job_worker.worker_loop()
        except StopIteration:
            pass
    with index_job_worker._connect() as conn:
        assert not index_job_worker.pending_card_file_ids(conn)
        assert not conn.execute("SELECT id,status,error_msg FROM index_jobs WHERE status!='done'").fetchall()
        assert conn.execute('SELECT id,is_favorite,card_uid FROM card_metadata').fetchall()[0][:] == (
            'Pack/hero.json', 1, (root/'original-identity').read_text())


def seed_binding_runtime(root):
    crash = subprocess.run([sys.executable, '-X', 'utf8', __file__, str(root), 'upload', 'crash'],
                           capture_output=True, timeout=60)
    assert crash.returncode == 73, crash.stdout + crash.stderr
    recover(root, 'upload')
    bind(root)


def drain_binding_jobs():
    class OneIteration:
        def __init__(self):
            self.calls = 0
        def wait(self, *_args):
            self.calls += 1
            if self.calls > 1:
                raise StopIteration()
            return True
        def clear(self):
            pass
        def set(self):
            pass
    for _ in range(3):
        ctx.index_wakeup = OneIteration()
        try:
            index_job_worker.worker_loop()
        except StopIteration:
            pass
    with index_job_worker._connect() as conn:
        assert not conn.execute("SELECT id,status,error_msg FROM index_jobs WHERE status!='done'").fetchall()


def underscore_binding(root, kind, operation):
    seed_binding_runtime(root)
    card_id = {'card': '_hero.png', 'folder': '_folder/hero.png',
               'bundle': '_bundle/hero.png'}[kind]
    ui_key = '_bundle' if kind == 'bundle' else card_id
    path = root/'cards'/card_id
    path.parent.mkdir(exist_ok=True)
    (root/'cards/hero.png').rename(path)
    if kind == 'bundle':
        (path.parent/'.bundle').write_text('1')
    with index_job_worker._connect() as conn:
        conn.execute('UPDATE card_metadata SET id=?,category=?', (card_id, card_id.rpartition('/')[0]))
        conn.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='worldinfo'")
        conn.commit()
        index_build_service.apply_card_increment(conn, card_id, str(path), remove_entity_ids=['hero.png'])
        card = dict(conn.execute('SELECT * FROM card_metadata WHERE id=?', (card_id,)).fetchone())
    repository = s.Repository()
    repository.replace_snapshot({ui_key: {'resource_folder': 'old-assets', 'summary': 'keep note',
                                          'chat_ids': ['Hero/test.jsonl']},
                                  '_custom_namespace': {'plugin': {'enabled': True}, 'other': [1, 2]}})
    ctx.cache.initialized = True
    ctx.cache.id_map = {card_id: {**card, 'char_name': 'Hero', 'tags': [],
                                'source_update': {'last_status': 'unchecked'},
                                **({'is_bundle': True, 'bundle_dir': ui_key, 'versions': [{'id': card_id}]}
                                   if kind == 'bundle' else {})}}
    ctx.cache.bundle_map = {ui_key: card_id} if kind == 'bundle' else {}
    book = root/'resources/new-assets/lorebooks/book.json'
    book.parent.mkdir(parents=True)
    book.write_text(json.dumps({'name': 'New Book', 'entries': {'0': {'content': 'entry'}}}), encoding='utf-8')
    app = Flask(__name__)
    app.register_blueprint(cards.bp)
    app.teardown_appcontext(db_session.close_connection)
    request = {'id': card_id, 'ui_only': True, 'ui_only_fields': ['resource_folder'],
               'resource_folder': 'new-assets', **({'bundle_dir': ui_key} if kind == 'bundle' else {})}
    if operation == 'delete':
        s.NamespaceRepository(ui_key).delete('resource_folder')
        assert not repository.get(ui_key).get('resource_folder')
        with index_job_worker._connect() as conn:
            assert not conn.execute('SELECT * FROM card_resource_bindings WHERE card_ui_key=?', (ui_key,)).fetchall()
            assert conn.execute("SELECT id FROM index_jobs WHERE job_type='upsert_world_owner' AND entity_id=? AND status='pending'",
                                (card_id,)).fetchone()
    elif operation == 'update':
        repository.update_fields(ui_key, {'resource_folder': 'new-assets', 'chat_ids': ['Hero/new.jsonl']})
        assert s.binding_keys() == [(ui_key, 'Hero/new.jsonl')]
    elif operation == 'concurrent':
        first, second = ui_store.load_ui_data(), ui_store.load_ui_data()
        first[ui_key]['resource_folder'] = 'new-assets'
        second[ui_key]['summary'] = 'concurrent note'
        assert repository.save(second) and repository.save(first)
        assert repository.get(ui_key)['summary'] == 'concurrent note'
    else:
        if operation == 'rollback':
            snapshot = ui_store.load_ui_data()
            snapshot[ui_key]['resource_folder'] = 'new-assets'
            with index_job_worker._connect() as conn:
                before_jobs = conn.execute('SELECT id,status FROM index_jobs').fetchall()
                conn.execute('BEGIN')
                assert repository.save(snapshot, conn=conn)
                assert conn.execute('SELECT resource_folder FROM card_resource_bindings WHERE card_ui_key=?',
                                    (ui_key,)).fetchone()[0] == 'new-assets'
                conn.rollback()
                assert conn.execute('SELECT resource_folder FROM card_resource_bindings WHERE card_ui_key=?',
                                    (ui_key,)).fetchone()[0] == 'old-assets'
                assert conn.execute('SELECT id,status FROM index_jobs').fetchall() == before_jobs
            assert repository.get(ui_key)['resource_folder'] == 'old-assets'
            assert repository.save(snapshot)
        else:
            if operation == 'failure':
                with index_job_worker._connect() as conn:
                    conn.execute("CREATE TRIGGER binding_unavailable BEFORE INSERT ON card_resource_bindings "
                                 "WHEN NEW.resource_folder='new-assets' BEGIN SELECT RAISE(ABORT, 'binding unavailable'); END")
                result = app.test_client().post('/api/update_card', json=request).get_json()
                assert result['success'] is False, result
                assert repository.get(ui_key)['resource_folder'] == 'old-assets'
                with index_job_worker._connect() as conn:
                    assert conn.execute('SELECT resource_folder FROM card_resource_bindings WHERE card_ui_key=?',
                                        (ui_key,)).fetchone()[0] == 'old-assets'
                    conn.execute('DROP TRIGGER binding_unavailable')
            result = app.test_client().post('/api/update_card', json=request).get_json()
            assert result['success'] and result['canonical_ui']['resource_folder'] == 'new-assets', result
    if operation != 'delete':
        assert repository.get(ui_key)['resource_folder'] == 'new-assets'
        with index_job_worker._connect() as conn:
            assert conn.execute('SELECT resource_folder FROM card_resource_bindings WHERE card_ui_key=?',
                                (ui_key,)).fetchone()[0] == 'new-assets'
        assert index_build_service.resolve_resource_worldinfo_owner_card_ids(str(book)) == [card_id]
    drain_binding_jobs()
    if operation != 'delete':
        book.write_text(json.dumps({'name': 'Updated Book', 'entries': {'0': {'content': 'updated entry'}}}), encoding='utf-8')
        job = index_job_worker.enqueue_index_job('upsert_worldinfo_path', source_path=str(book))
        drain_binding_jobs()
        with index_job_worker._connect() as conn:
            assert conn.execute('SELECT status FROM index_jobs WHERE id=?', (job,)).fetchone()[0] == 'done'
            assert conn.execute("SELECT name FROM index_entities_v2 WHERE entity_type='world_resource'").fetchall()[0][0] == 'Updated Book'
    # Unknown namespaces retain their member semantics and do not acquire card projections.
    namespace = s.NamespaceRepository('_custom_namespace')
    namespace.update_fields('plugin', {'enabled': False, 'new': 'value'})
    namespace.delete('other')
    assert s.plain(repository.get('_custom_namespace')) == {'plugin': {'enabled': False, 'new': 'value'}}
    with index_job_worker._connect() as conn:
        assert not conn.execute("SELECT id FROM index_jobs WHERE entity_id='_custom_namespace'").fetchall()
        assert conn.execute('SELECT is_favorite,card_uid FROM card_metadata WHERE id=?', (card_id,)).fetchone()[:] == (
            1, (root/'original-identity').read_text())


def chat_binding_response(root, operation):
    from core.api.v1 import chats
    seed_binding_runtime(root)
    ctx.cache.initialized = True
    ctx.cache.id_map = {name: {'id': name, 'char_name': label, 'tags': []}
                        for name, label in [('hero.png', 'Hero'), ('other.png', 'Other')]}
    path = root/'chats/Hero/test.jsonl'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({'user_name': 'User', 'character_name': 'Hero'}) + '\n' +
                    json.dumps({'name': 'Hero', 'is_user': False, 'mes': 'hello'}) + '\n', encoding='utf-8')
    app = Flask(__name__)
    app.register_blueprint(chats.bp)
    app.teardown_appcontext(db_session.close_connection)
    client = app.test_client()
    repository = s.Repository()
    if operation in ('unbind', 'rebind', 'repeat'):
        repository.update_fields('hero.png', {'chat_ids': ['Hero/test.jsonl']})
    if operation == 'failure':
        with index_job_worker._connect() as conn:
            conn.execute("CREATE TRIGGER chat_binding_unavailable BEFORE INSERT ON chat_card_bindings "
                         "BEGIN SELECT RAISE(ABORT, 'binding unavailable'); END")
    request = {'id': 'Hero/test.jsonl', 'card_id': 'other.png' if operation == 'rebind' else 'hero.png',
               'unbind': operation == 'unbind'}
    result = client.post('/api/chats/bind', json=request).get_json()
    if operation == 'failure':
        assert result['success'] is False, result
        assert not s.binding_keys()
        with index_job_worker._connect() as conn:
            conn.execute('DROP TRIGGER chat_binding_unavailable')
        result = client.post('/api/chats/bind', json=request).get_json()
    assert result['success'], result
    expected = [] if operation == 'unbind' else [request['card_id']]
    assert result['bound_cards'] == result['chat']['bound_cards'], result
    assert result['bound_card_count'] == result['chat']['bound_card_count'] == len(expected), result
    assert [item['card_id'] for item in result['bound_cards']] == expected, result
    assert s.binding_keys() == [(card_id, result['id']) for card_id in expected]
    if operation == 'rebind':
        assert result['moved'] and result['id'] == 'Other/test.jsonl', result
        assert (root/'chats/Other/test.jsonl').is_file() and not path.exists()


def namespace_recovery(root, kind, phase):
    old_id = 'hero.png' if kind == 'card' else 'pack/hero.png'
    new_id = {'card': '_renamed.png', 'folder': '_renamed/hero.png',
              'bundle': '_renamed/hero.png'}[kind]
    old_key = 'pack' if kind == 'bundle' else old_id
    new_key = '_renamed' if kind == 'bundle' else new_id
    note = 'unique precious namespace note'
    if phase == 'crash':
        seed_binding_runtime(root)
        if kind != 'card':
            pack = root/'cards/pack'
            pack.mkdir()
            (root/'cards/hero.png').rename(pack/'hero.png')
            if kind == 'bundle':
                (pack/'.bundle').write_text('1')
            with index_job_worker._connect() as conn:
                conn.execute("UPDATE card_metadata SET id=?,category='pack' WHERE id='hero.png'", (old_id,))
                conn.commit()
                index_build_service.apply_card_increment(conn, old_id, str(pack/'hero.png'),
                                                         remove_entity_ids=['hero.png'])
        s.Repository().replace_snapshot({old_key: {'summary': note, 'link': '', 'resource_folder': '',
            'chat_ids': ['Hero/test.jsonl'], 'import_time': (root/'cards'/old_id).stat().st_mtime}})
        with index_job_worker._connect() as conn:
            card = dict(conn.execute('SELECT * FROM card_metadata WHERE id=?', (old_id,)).fetchone())
        ctx.cache.initialized = True
        ctx.cache.id_map = {old_id: {**card, 'tags': [], 'source_update': {'last_status': 'unchecked'},
            **({'is_bundle': True, 'bundle_dir': old_key, 'versions': [{'id': old_id}]}
               if kind == 'bundle' else {})}}
        ctx.cache.bundle_map = {old_key: old_id} if kind == 'bundle' else {}
        rename = os.rename
        def rename_then_exit(source, target, *args, **kwargs):
            result = rename(source, target, *args, **kwargs)
            destination = root/'cards'/('_renamed.png' if kind == 'card' else '_renamed')
            if str(target) == str(destination):
                os._exit(73)
            return result
        os.rename = rename_then_exit
        app = Flask(__name__)
        app.register_blueprint(cards.bp)
        app.teardown_appcontext(db_session.close_connection)
        route, payload = ('/api/update_card', {'id': old_id, 'new_filename': new_id, 'ui_only': True,
                                              'ui_summary': note}) if kind == 'card' else (
            '/api/rename_folder', {'old_path': 'pack', 'new_name': '_renamed'})
        raise AssertionError(app.test_client().post(route, json=payload).get_json())
    bind(root)
    drain_binding_jobs()
    # Cold cache and same-value retry must not mask a projection of an empty namespace.
    for retry in (False, True):
        if retry:
            app = Flask(__name__)
            app.register_blueprint(cards.bp)
            app.teardown_appcontext(db_session.close_connection)
            reply = app.test_client().post('/api/update_card', json={'id': new_id, 'ui_only': True,
                'ui_only_fields': ['ui_summary'], 'ui_summary': note,
                **({'bundle_dir': new_key} if kind == 'bundle' else {})}).get_json()
            assert reply['success'], reply
            drain_binding_jobs()
        assert s.Repository().get(new_key)['summary'] == note
        assert s.binding_keys() == [(new_key, 'Hero/test.jsonl')]
        with index_job_worker._connect() as conn:
            assert conn.execute('SELECT summary_preview FROM index_entities_v2 WHERE entity_id=?',
                                ('card::' + new_id,)).fetchone()[0] == note
            assert note in conn.execute('SELECT content FROM index_search_fast_v2 WHERE entity_id=?',
                                        ('card::' + new_id,)).fetchone()[0]
            revisions = conn.execute('SELECT r.revision,p.ui_revision FROM ui_records r JOIN card_ui_projections p '
                                     'ON p.ui_key=r.key WHERE p.card_id=?', (new_id,)).fetchone()
            assert revisions[0] == revisions[1]
            assert tuple(conn.execute('SELECT is_favorite,card_uid FROM card_metadata WHERE id=?',
                                      (new_id,)).fetchone()) == (1, (root/'original-identity').read_text())


def chat_concurrent_save(root, operation):
    import threading
    from core.api.v1 import chats
    seed_binding_runtime(root)
    path = root/'chats/Hero/test.jsonl'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({'user_name': 'User', 'character_name': 'Hero'}) + '\n' +
                    json.dumps({'name': 'Hero', 'is_user': False, 'mes': 'hello'}) + '\n', encoding='utf-8')
    app = Flask(__name__)
    app.register_blueprint(chats.bp)
    app.teardown_appcontext(db_session.close_connection)
    client = app.test_client()
    chat_id = 'Hero/test.jsonl'
    assert client.post('/api/chats/update_meta', json={'id': chat_id, 'notes': 'original',
                                                      'last_view_floor': 0}).get_json()['success']
    save = chats.save_chat_data
    interleaved = []
    def save_with_concurrent_request(snapshot, **kwargs):
        if not interleaved:
            interleaved.append(True)
            results = []
            def update():
                results.append(app.test_client().post('/api/chats/update_meta', json={
                    'id': chat_id, **({'notes': 'concurrent'} if operation == 'conflict'
                                     else {'last_view_floor': 1})}).get_json())
            thread = threading.Thread(target=update, daemon=True)
            thread.start()
            thread.join(10)
            assert not thread.is_alive() and results[0]['success'], results
        return save(snapshot, **kwargs)
    chats.save_chat_data = save_with_concurrent_request
    reply = client.post('/api/chats/update_meta', json={'id': chat_id, 'notes': 'requested'}).get_json()
    stored = s.Repository('chat').get(chat_id)
    if operation == 'conflict':
        assert reply['success'] is False and 'requested' not in str(reply), reply
        assert stored['notes'] == 'concurrent'
        chats.save_chat_data = save
        retry = client.post('/api/chats/update_meta', json={'id': chat_id, 'notes': 'requested'}).get_json()
        assert retry['success'] and s.Repository('chat').get(chat_id)['notes'] == 'requested'
    else:
        assert reply['success'], reply
        assert reply['chat']['notes'] == stored['notes'] == 'requested'
        assert reply['chat']['last_view_floor'] == stored['last_view_floor'] == 1


def rebuild_activation_recovery(root, mode):
    from contextlib import closing
    from core.data import index_runtime_store as runtime
    from core.services import index_upgrade_service as upgrade
    from core.services.worldinfo_index_query_service import query_worldinfo_index

    bind(root)
    db = root / 'db.sqlite'
    def check_generation():
        with closing(index_job_worker._connect()) as conn:
            assert runtime.get_active_generation(conn, 'worldinfo') == 3
        for search_mode in ('fast', 'fulltext'):
            assert query_worldinfo_index({
                'db_path': str(db), 'search': 'crashrebuildmarker', 'search_mode': search_mode,
            })['total'] == 205

    if mode == 'crash':
        with closing(index_job_worker._connect()) as conn, conn:
            db_session._initialize_database(conn, is_existing_db=True, schema_only=True)
            conn.execute("UPDATE index_build_state SET active_generation=1 WHERE scope='worldinfo'")
        s.initialize()
        books = [root / 'worlds' / f'book-{number}.json' for number in range(205)]
        for book in books:
            book.write_text('{"name":"oldmarker","entries":{}}', encoding='utf-8')
        upgrade.rebuild_scope_generation('worldinfo')
        for book in books:
            book.write_text('{"name":"crashrebuildmarker","entries":{}}', encoding='utf-8')
        job = index_job_worker.enqueue_index_job('rebuild_scope', payload={'scope': 'worldinfo'})
        def exit_before_cleanup(_conn, scope, generation, *, pending_job_id):
            assert (scope, generation) == ('worldinfo', 2)
            check_generation()
            with closing(index_job_worker._connect()) as conn:
                assert [tuple(row) for row in conn.execute(
                    'SELECT id, status FROM index_jobs ORDER BY id',
                )] == [(job, 'done'), (pending_job_id, 'pending')]
            os._exit(77)

        runtime.cleanup_obsolete_generation = exit_before_cleanup
        index_job_worker.worker_loop()
    else:
        reads = []
        def count_read(path, *args, **kwargs):
            reads.append(path)
            return open(path, *args, **kwargs)

        class QueueDrained(Exception):
            pass

        def wait(_timeout):
            if not ctx.index_wakeup.is_set():
                raise QueueDrained()
            return True

        index_build_service.open = count_read
        ctx.index_wakeup.set()
        ctx.index_wakeup.wait = wait
        try:
            index_job_worker.worker_loop(recover_running=True)
        except QueueDrained:
            pass
        assert not reads, reads
        check_generation()
        with closing(index_job_worker._connect()) as conn:
            assert [tuple(row) for row in conn.execute(
                'SELECT job_type, status FROM index_jobs ORDER BY id',
            )] == [('rebuild_scope', 'done'), ('cleanup_generation', 'done')]
            assert [row[0] for row in conn.execute('SELECT DISTINCT generation FROM index_entities_v2')] == [3]


if __name__ == '__main__':
    if sys.argv[2] == 'rebuild_activation_recovery':
        rebuild_activation_recovery(Path(sys.argv[1]), sys.argv[3])
    elif sys.argv[2] == 'underscore_binding':
        underscore_binding(Path(sys.argv[1]), *sys.argv[3].split(':'))
    elif sys.argv[2] == 'chat_binding_response':
        chat_binding_response(Path(sys.argv[1]), sys.argv[3])
    elif sys.argv[2] == 'namespace_recovery':
        namespace_recovery(Path(sys.argv[1]), *sys.argv[3].split(':'))
    elif sys.argv[2] == 'chat_concurrent_save':
        chat_concurrent_save(Path(sys.argv[1]), sys.argv[3])
    elif sys.argv[2] == 'bundle_companions':
        recover_bundle_companions(Path(sys.argv[1]), sys.argv[3])
    elif sys.argv[2] == 'conversion_ui':
        conversion_ui_migration(Path(sys.argv[1]), *sys.argv[3].split(':'))
    elif sys.argv[2] == 'rename_hook':
        if sys.argv[3] != 'recover':
            rename_hook(Path(sys.argv[1]))
    elif sys.argv[2].startswith('chain_'):
        if sys.argv[3] != 'recover':
            move_chain(Path(sys.argv[1]), sys.argv[2].removeprefix('chain_'))
    elif sys.argv[2].startswith('move_ack_'):
        if sys.argv[3] != 'recover':
            move_ack_failure(Path(sys.argv[1]), sys.argv[2].removeprefix('move_ack_'))
    else:
        (recover if sys.argv[3] == 'recover' else child)(Path(sys.argv[1]), sys.argv[2])
