"""私有数据域与作业域测试（方案 §0-3）。

重点覆盖 §0-3 的验收：
- `api.private.query('DELETE …')` 被拒（只读校验）；
- `api.jobs.items(run_id)` 能取到 `get()` 分页之外的全部条目。
"""

import os
import sqlite3
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core.plugins import api as api_module
from core.plugins import job_store, jobs
from core.plugins.api import PluginAPI
from core.plugins.errors import PluginJobNotFoundError
from core.plugins.manifest import PluginManifest
from tests.plugins_test_support import clear_plugin_ui_namespace, write_plugin


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    plugin_id = 'demo-plugin'
    monkeypatch.setattr(job_store, 'DEFAULT_DB_PATH', str(tmp_path / 'jobs.db'))
    clear_plugin_ui_namespace()
    jobs.reset_for_tests()
    yield
    clear_plugin_ui_namespace()
    jobs.reset_for_tests()


@pytest.fixture
def env(tmp_path, monkeypatch):
    plugin_dir = write_plugin(tmp_path, 'demo-plugin')
    db_path = tmp_path / 'jobs.db'

    monkeypatch.setattr(api_module, 'DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setattr(api_module, 'CARDS_FOLDER', str(tmp_path / 'cards'))

    return {
        'api': PluginAPI(PluginManifest.load(plugin_dir)),
        'root': tmp_path,
        'db': db_path,
    }


# ================================================================ 只读查询


def test_query_can_read_internal_tables(env):
    """能力面：插件可以查任意表（含主程序内部表），不受域方法形状限制。"""
    jobs.register_job_handler('demo-plugin', 'demo.run', lambda ctx: None)
    run_id = jobs.submit_job('demo-plugin', 'demo.run', ['a', 'b'])

    rows = env['api'].private.query('SELECT run_id, status FROM plugin_jobs')

    assert len(rows) == 1
    assert rows[0]['run_id'] == run_id


@pytest.mark.parametrize('statement', [
    'DELETE FROM plugin_jobs',
    'UPDATE plugin_jobs SET status = ?',
    'INSERT INTO plugin_jobs (run_id) VALUES (1)',
    'DROP TABLE plugin_jobs',
    'ALTER TABLE plugin_jobs ADD COLUMN x TEXT',
    'CREATE TABLE hack (id INTEGER)',
    'REPLACE INTO plugin_jobs (run_id) VALUES (1)',
    'TRUNCATE plugin_jobs',
    'PRAGMA journal_mode = DELETE',
    'VACUUM',
    'ATTACH DATABASE \'evil.db\' AS evil',
    'BEGIN',
])
def test_query_rejects_writes_and_ddl(env, statement):
    """方案 §0-3 的验收：`api.private.query('DELETE …')` 被拒。"""
    with pytest.raises(ValueError):
        env['api'].private.query(statement)


def test_query_rejects_cte_write_smuggling(env):
    with pytest.raises(ValueError):
        env['api'].private.query('WITH x AS (SELECT 1) DELETE FROM plugin_jobs')


def test_query_allows_cte_select(env):
    assert env['api'].private.query('WITH x AS (SELECT 1 AS n) SELECT n FROM x') == [{'n': 1}]


def test_query_rejects_multiple_statements(env):
    with pytest.raises(ValueError):
        env['api'].private.query('SELECT 1; SELECT 2')


def test_query_rejects_empty(env):
    with pytest.raises(ValueError):
        env['api'].private.query('')
    with pytest.raises(ValueError):
        env['api'].private.query('   ')


def test_query_accepts_positional_params(env):
    assert env['api'].private.query('SELECT ? AS a, ? AS b', (1, 'x')) == [{'a': 1, 'b': 'x'}]


def test_query_accepts_named_params(env):
    assert env['api'].private.query('SELECT :n AS n', {'n': 5}) == [{'n': 5}]


def test_query_does_not_write(env):
    """只读校验不只是关键字检查：真的跑一次 DELETE 应该没有任何行被动过。"""
    jobs.register_job_handler('demo-plugin', 'demo.run', lambda ctx: None)
    jobs.submit_job('demo-plugin', 'demo.run', ['a'])

    with pytest.raises(ValueError):
        env['api'].private.query('DELETE FROM plugin_jobs')

    assert len(env['api'].private.query('SELECT run_id FROM plugin_jobs')) == 1


# ================================================================ 私有 namespace / 目录 / 表


def test_private_read_update_roundtrip(env):
    api = env['api']

    assert api.private.update(lambda entry: entry.update({'n': 1})) is True
    assert api.private.read() == {'n': 1}


def test_private_update_supports_returning_new_dict(env):
    env['api'].private.update(lambda entry: {'replaced': True})

    assert env['api'].private.read() == {'replaced': True}


def test_private_dir_is_inside_plugin_dir(env):
    target = env['api'].private.dir()

    assert os.path.isdir(target)
    assert os.path.basename(target) == 'data'


def test_private_table_prefix(env):
    assert env['api'].private.table_prefix() == 'plugin_demo_plugin_'


def test_private_migrate_enforces_prefix(env):
    api = env['api']

    api.private.migrate(['CREATE TABLE plugin_demo_plugin_logs (id INTEGER PRIMARY KEY)'])

    conn = sqlite3.connect(str(env['db']))
    try:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()

    assert 'plugin_demo_plugin_logs' in names


def test_private_migrate_rejects_foreign_table(env):
    with pytest.raises(ValueError):
        env['api'].private.migrate(['CREATE TABLE card_metadata (id INTEGER)'])


# ================================================================ 作业条目


def _completed_run(env, keys):
    records = []

    def _handler(ctx):
        for item in ctx.items:
            records.append(item['key'])
            ctx.report(item['key'], status='done', result={'k': item['key']})

    jobs.register_job_handler('demo-plugin', 'demo.run', _handler)
    run_id = jobs.submit_job('demo-plugin', 'demo.run', keys)
    jobs._process_pending_jobs()
    return run_id, records


def test_jobs_items_returns_all_items(env):
    """方案 §0-3 的验收：`items()` 能取到 `get()` 分页之外的全部条目。"""
    run_id, _ = _completed_run(env, [f'k{i}' for i in range(250)])

    detail = env['api'].jobs.get(run_id)
    items = env['api'].jobs.items(run_id)

    # `get()` 默认只带 200 条，`items()` 不设上限
    assert len(detail['items']) == 200
    assert detail['items_total'] == 250
    assert len(items) == 250
    assert [item['key'] for item in items] == [f'k{i}' for i in range(250)]


def test_jobs_items_filters_by_status(env):
    def _handler(ctx):
        ctx.report(ctx.items[0]['key'], status='done')
        ctx.report(ctx.items[1]['key'], status='failed', error='boom')

    jobs.register_job_handler('demo-plugin', 'demo.run', _handler)
    run_id = jobs.submit_job('demo-plugin', 'demo.run', ['ok', 'bad'])
    jobs._process_pending_jobs()

    failed = env['api'].jobs.items(run_id, status='failed')

    assert [item['key'] for item in failed] == ['bad']
    assert failed[0]['error'] == 'boom'


def test_jobs_items_paginates(env):
    run_id, _ = _completed_run(env, [f'k{i}' for i in range(10)])

    page = env['api'].jobs.items(run_id, limit=3, offset=4)

    assert [item['key'] for item in page] == ['k4', 'k5', 'k6']


def test_jobs_items_rejects_cross_plugin_run(env):
    jobs.register_job_handler('other-plugin', 'other.run', lambda ctx: None)
    other_run = jobs.submit_job('other-plugin', 'other.run', ['x'])

    with pytest.raises(PluginJobNotFoundError):
        env['api'].jobs.items(other_run)


def test_jobs_items_rejects_missing_run(env):
    with pytest.raises(PluginJobNotFoundError):
        env['api'].jobs.items('nonexistent-run')


def test_jobs_items_replaces_the_db_escape_hatch(env):
    """旧绕行是 `api.db()` + `SELECT … FROM plugin_job_items`；
    现在 `private.query` 仍能只读查，但 `jobs.items()` 是正规入口。"""
    run_id, _ = _completed_run(env, ['a', 'b'])

    via_domain = env['api'].jobs.items(run_id)
    via_sql = env['api'].private.query(
        'SELECT item_key FROM plugin_job_items WHERE run_id = ?', (run_id,),
    )

    assert [item['key'] for item in via_domain] == [row['item_key'] for row in via_sql]


# ================================================================ 作业其它入口


def test_jobs_register_rejects_undeclared_type(env):
    """`job_type` 必须已在 manifest 的 `backend.jobs` 声明。"""
    with pytest.raises(ValueError):
        env['api'].jobs.register('not-declared', lambda ctx: None)


def test_jobs_register_accepts_declared_type(env):
    env['api'].jobs.register('demo.run', lambda ctx: None)

    assert jobs.get_job_handler('demo-plugin', 'demo.run') is not None


def test_jobs_submit_and_get_roundtrip(env):
    env['api'].jobs.register('demo.run', lambda ctx: None)

    run_id = env['api'].jobs.submit('demo.run', items=['a'], payload={'secret_ref': 'api_key'})

    detail = env['api'].jobs.get(run_id)
    assert detail['run_id'] == run_id
    assert detail['payload'] == {'secret_ref': 'api_key'}


def test_jobs_get_returns_none_for_foreign_run(env):
    jobs.register_job_handler('other-plugin', 'other.run', lambda ctx: None)
    other_run = jobs.submit_job('other-plugin', 'other.run', ['x'])

    assert env['api'].jobs.get(other_run) is None
