"""插件通用作业系统（设计文档第 6 部分）。

- Worker：单 daemon 线程 + 30s 兜底唤醒，认领 `plugin_jobs` 中 `queued` 的作业。
- 协作式取消：每处理一项前检查作业状态，非 `running` 立即退出。
- 崩溃恢复：启动时把 `running` / `queued` 作业置为 `aborted`。
- 并发控制：`MAX_JOBS_PER_PLUGIN` 限制单插件同时占用的作业槽位，避免饿死其他插件。
- SSE：`plugin_job_events` 按作业内自增 `seq` 增量推送，`snapshot` 不落表。
- **归属隔离**：所有按 `run_id` 的操作都可选传 `plugin_id` 校验作业归属，
  越权一律按「作业不存在」处理——不透露他人作业是否存在，也不消耗 SSE 配额。
"""

import json
import logging
import threading
import time

from flask import Response

from core.plugins import job_store
from core.plugins.errors import (
    PluginJobDuplicateError,
    PluginJobError,
    PluginJobNotFoundError,
    PluginJobStateError,
    PluginSseLimitError,
)

logger = logging.getLogger(__name__)

WAKEUP_INTERVAL_SECONDS = 30
CLAIM_BATCH_LIMIT = 4
MAX_JOBS_PER_PLUGIN = 2

SSE_POLL_INTERVAL_SECONDS = 1.0
SSE_HEARTBEAT_INTERVAL_SECONDS = 15
SSE_MAX_CONNECTIONS_PER_RUN = 4
SSE_MAX_CONNECTIONS_TOTAL = 32

MAX_ITEMS_PER_RUN = 20000

_worker_lock = threading.Lock()
_worker_started = False
_worker_thread = None
_wakeup = threading.Event()
_shutdown = threading.Event()

_handlers_lock = threading.RLock()
_job_handlers = {}

_sse_lock = threading.Lock()
_sse_per_run = {}
_sse_total = 0


# ------------------------------------------------------------------ 处理器注册


def register_job_handler(plugin_id: str, job_type: str, handler) -> None:
    """注册作业处理器（`(plugin_id, job_type)` 唯一）。"""
    plugin_id = str(plugin_id or '').strip()
    job_type = str(job_type or '').strip()
    if not plugin_id or not job_type:
        raise PluginJobError('plugin_id 与 job_type 不能为空')
    if not callable(handler):
        raise PluginJobError('作业处理器必须可调用')

    with _handlers_lock:
        key = (plugin_id, job_type)
        if key in _job_handlers and _job_handlers[key] is not handler:
            logger.warning('插件 %s 的作业类型 %s 处理器被覆盖注册', plugin_id, job_type)
        _job_handlers[key] = handler


def get_job_handler(plugin_id: str, job_type: str):
    with _handlers_lock:
        return _job_handlers.get((str(plugin_id or ''), str(job_type or '')))


def unregister_plugin_handlers(plugin_id: str) -> int:
    plugin_id = str(plugin_id or '')
    with _handlers_lock:
        keys = [key for key in _job_handlers if key[0] == plugin_id]
        for key in keys:
            _job_handlers.pop(key, None)
    return len(keys)


# ------------------------------------------------------------------ 作业上下文


class JobContext:
    """传给作业处理器的执行上下文（契约见 6.2）。"""

    def __init__(self, conn, job: dict, items: list, api=None):
        self._conn = conn
        self._api = api
        self.run_id = job.get('run_id', '')
        self.plugin_id = job.get('plugin_id', '')
        self.job_type = job.get('job_type', '')
        self.payload = job.get('payload') or {}
        self.items = items
        self._summary = {}

    # ---- 状态检查 ----

    def _status(self) -> str:
        row = self._conn.execute(
            'SELECT status FROM plugin_jobs WHERE run_id = ?', (self.run_id,),
        ).fetchone()
        return str(row['status']) if row else ''

    def should_cancel(self) -> bool:
        """协作式取消/暂停检查：作业不再是 `running` 时返回 True。"""
        return self._status() != 'running'

    @property
    def status(self) -> str:
        return self._status()

    # ---- 结果上报 ----

    def report(self, item_key, *, status: str, result=None, error: str = '') -> None:
        """上报单项结果：更新条目、作业计数，并追加 SSE 事件。"""
        if status not in job_store.ITEM_STATUSES:
            raise PluginJobError(f'非法的条目状态: {status}')

        key = str(item_key)
        job_store.update_item(
            self._conn, self.run_id, key,
            status=status, result=result, error=error, bump_attempt=True,
        )

        payload = {'item_key': key, 'status': status}
        if status == 'done':
            payload['result'] = result if result is not None else {}
        elif status in ('failed', 'skipped'):
            payload['error'] = error
        elif status == 'awaiting_review':
            payload['result'] = result if result is not None else {}

        job_store.append_event(self._conn, self.run_id, 'item', payload)

        counters = self._counter_patch()
        job_store.update_job(
            self._conn, self.run_id,
            current_item=key, message=f'已完成 {counters["completed"] + counters["failed"] + counters["skipped"]}',
            **counters,
        )

    def _counter_patch(self) -> dict:
        rows = self._conn.execute(
            '''
            SELECT status, COUNT(*) AS total FROM plugin_job_items
            WHERE run_id = ? GROUP BY status
            ''',
            (self.run_id,),
        ).fetchall()
        counts = {row['status']: int(row['total']) for row in rows}
        return {
            'completed': counts.get('done', 0),
            'failed': counts.get('failed', 0),
            'skipped': counts.get('skipped', 0),
        }

    def set_message(self, text: str) -> None:
        job_store.update_job(self._conn, self.run_id, message=str(text or ''))

    def set_total(self, total: int) -> None:
        try:
            value = max(0, int(total))
        except (TypeError, ValueError):
            return
        job_store.update_job(self._conn, self.run_id, total=value)

    # ---- 断点续跑 ----

    def save_state(self, state: dict) -> None:
        """把自定义状态写入作业 summary（重启后可读取）。"""
        if not isinstance(state, dict):
            return
        self._summary['state'] = state
        job_store.update_job(
            self._conn, self.run_id,
            summary_json=json.dumps(self._summary, ensure_ascii=False),
        )

    def load_state(self) -> dict:
        row = self._conn.execute(
            'SELECT summary_json FROM plugin_jobs WHERE run_id = ?', (self.run_id,),
        ).fetchone()
        if not row:
            return {}
        try:
            payload = json.loads(row['summary_json'] or '{}')
        except (TypeError, ValueError):
            return {}
        state = payload.get('state') if isinstance(payload, dict) else None
        return state if isinstance(state, dict) else {}

    def set_summary(self, summary: dict) -> None:
        """写入作业级汇总（`done` 事件与作业详情都会带上）。"""
        if isinstance(summary, dict):
            self._summary.update(summary)

    def api(self):
        """当前插件的 PluginAPI（用于 `get_secret` 等运行时解析）。"""
        return self._api

    def resolve_secret(self, key: str):
        """按 `secret_ref` 解析密钥值（密钥不落 `plugin_jobs.payload_json`）。"""
        if self._api is None:
            return None
        return self._api.secrets.get(key)

    def log(self, level: str, message: str) -> None:
        if self._api is not None:
            self._api._write_log(level, message)
        else:
            logger.log(getattr(logging, str(level or 'info').upper(), logging.INFO), message)


# ------------------------------------------------------------------ 提交与查询


def submit_job(plugin_id: str, job_type: str, items, payload: dict | None = None) -> str:
    """创建作业并唤醒 worker，返回 run_id。"""
    plugin_id = str(plugin_id or '').strip()
    job_type = str(job_type or '').strip()
    if not plugin_id or not job_type:
        raise PluginJobError('plugin_id 与 job_type 不能为空')
    if get_job_handler(plugin_id, job_type) is None:
        raise PluginJobError(f'未注册的作业类型: {job_type}')

    normalized = job_store.normalize_items(items)
    if not normalized:
        raise PluginJobError('items 不能为空')
    if len(normalized) > MAX_ITEMS_PER_RUN:
        raise PluginJobError(f'单次作业条目数超过上限 {MAX_ITEMS_PER_RUN}')

    conn = job_store.connect(ensure_schema=True)
    try:
        placeholders = ','.join('?' for _ in job_store.ACTIVE_STATUSES)
        existing = conn.execute(
            f'''
            SELECT run_id FROM plugin_jobs
            WHERE plugin_id = ? AND job_type = ? AND status IN ({placeholders})
            LIMIT 1
            ''',
            (plugin_id, job_type, *job_store.ACTIVE_STATUSES),
        ).fetchone()
        if existing:
            raise PluginJobDuplicateError(f'同类型作业已在运行: {existing["run_id"]}')

        run_id = job_store.create_job(conn, plugin_id, job_type, items, payload or {})
    finally:
        conn.close()

    _wakeup.set()
    return run_id


def get_job_detail(
    run_id: str, *, items_limit: int = 200, items_offset: int = 0, plugin_id: str = '',
):
    """作业状态 + 条目（分页）；`plugin_id` 非空时校验归属（越权按不存在处理）。"""
    conn = job_store.connect(ensure_schema=True)
    try:
        job = job_store.get_job(conn, run_id)
        if not job:
            return None

        owner = str(plugin_id or '').strip()
        if owner and str(job.get('plugin_id') or '') != owner:
            logger.warning(
                '插件 %s 尝试读取非本插件作业 %s（归属 %s），已拒绝',
                owner, run_id, job.get('plugin_id'),
            )
            return None

        items = job_store.list_items(conn, run_id, limit=items_limit, offset=items_offset)
        job['items'] = items
        job['items_total'] = job_store.count_items(conn, run_id)
        return job
    finally:
        conn.close()


def list_plugin_jobs(plugin_id: str, *, limit: int = 50, offset: int = 0, statuses=None) -> dict:
    conn = job_store.connect(ensure_schema=True)
    try:
        return {
            'items': job_store.list_jobs(conn, plugin_id, statuses=statuses, limit=limit, offset=offset),
            'total': job_store.count_jobs(conn, plugin_id, statuses=statuses),
        }
    finally:
        conn.close()


def _require_job(conn, run_id: str, *, plugin_id: str = '') -> dict:
    """取作业；不存在时抛错。

    `plugin_id` 非空时**同时校验归属**——插件只能操作自己的作业。
    作业 id 由主程序生成（32 位十六进制），但仅靠「不可猜测」不构成隔离：
    run_id 会出现在 SSE 事件、日志与前端 URL 中，属于可泄漏信息。
    """
    job = job_store.get_job(conn, run_id)
    if not job:
        raise PluginJobNotFoundError(f'作业不存在: {run_id}')

    owner = str(plugin_id or '').strip()
    if owner and str(job.get('plugin_id') or '') != owner:
        # 不透露目标作业是否存在，统一按「不存在」处理，避免探测
        logger.warning(
            '插件 %s 尝试访问非本插件作业 %s（归属 %s），已拒绝',
            owner, run_id, job.get('plugin_id'),
        )
        raise PluginJobNotFoundError(f'作业不存在: {run_id}')
    return job


def cancel_job(run_id: str, *, plugin_id: str = '') -> bool:
    """协作式取消：把作业置为 `cancelled`，worker 在下一个条目边界退出。"""
    conn = job_store.connect(ensure_schema=True)
    try:
        job = _require_job(conn, run_id, plugin_id=plugin_id)
        if job['status'] not in job_store.ACTIVE_STATUSES:
            raise PluginJobStateError(f'作业当前状态无法取消: {job["status"]}')

        job_store.update_job(conn, run_id, status='cancelled', finished_at=time.time())
        job_store.append_event(conn, run_id, 'log', {'level': 'warning', 'message': '已请求取消'})
        _finalize_if_idle(conn, run_id)
        return True
    finally:
        conn.close()


def pause_job(run_id: str, *, plugin_id: str = '') -> bool:
    """暂停作业（D6 逐条审批流的落点）。"""
    conn = job_store.connect(ensure_schema=True)
    try:
        job = _require_job(conn, run_id, plugin_id=plugin_id)
        if job['status'] not in ('queued', 'running'):
            raise PluginJobStateError(f'作业当前状态无法暂停: {job["status"]}')
        job_store.update_job(conn, run_id, status='paused', message='已暂停，等待确认')
        job_store.append_event(conn, run_id, 'log', {'level': 'info', 'message': '作业已暂停'})
        return True
    finally:
        conn.close()


def resume_job(run_id: str, *, plugin_id: str = '') -> bool:
    conn = job_store.connect(ensure_schema=True)
    try:
        job = _require_job(conn, run_id, plugin_id=plugin_id)
        if job['status'] != 'paused':
            raise PluginJobStateError(f'作业当前状态无法恢复: {job["status"]}')
        job_store.update_job(conn, run_id, status='queued')
        job_store.append_event(conn, run_id, 'log', {'level': 'info', 'message': '作业已恢复'})
    finally:
        conn.close()

    _wakeup.set()
    return True


def retry_job(run_id: str, *, only_failed: bool = True, plugin_id: str = '') -> str:
    """重跑失败项：把 `failed` / `awaiting_review` 条目重置为 `pending` 后重新入队。"""
    conn = job_store.connect(ensure_schema=True)
    try:
        job = _require_job(conn, run_id, plugin_id=plugin_id)
        if job['status'] in ('queued', 'running'):
            raise PluginJobStateError(f'作业仍在运行，无法重跑: {job["status"]}')

        if not only_failed:
            conn.execute(
                '''
                UPDATE plugin_job_items
                SET status = 'pending', error = '', result_json = '{}'
                WHERE run_id = ?
                ''',
                (run_id,),
            )
            conn.commit()
        else:
            job_store.reset_failed_items(conn, run_id)

        counters = conn.execute(
            '''
            SELECT
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_count,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count
            FROM plugin_job_items WHERE run_id = ?
            ''',
            (run_id,),
        ).fetchone()

        job_store.update_job(
            conn, run_id,
            status='queued',
            completed=int(counters['done_count'] or 0),
            failed=int(counters['failed_count'] or 0),
            finished_at=0,
            error='',
            message='已重新入队',
        )
    finally:
        conn.close()

    _wakeup.set()
    return run_id


def review_item(
    run_id: str, item_key: str, *, status: str, result=None, error: str = '', plugin_id: str = '',
) -> bool:
    """逐条审批（D6）：把 `awaiting_review` 条目改为 `done` / `failed` / `skipped`。"""
    if status not in job_store.ITEM_STATUSES:
        raise PluginJobError(f'非法的条目状态: {status}')

    conn = job_store.connect(ensure_schema=True)
    try:
        _require_job(conn, run_id, plugin_id=plugin_id)
        item = job_store.get_item(conn, run_id, item_key)
        if not item:
            raise PluginJobNotFoundError(f'条目不存在: {item_key}')

        # 前端只发 `{status}` 时 result 为 None：沿用条目原有的 result，
        # 不能交给 `update_item` 的 `None → {}` 语义清空候选（后续 apply 会变成空操作）。
        effective_result = result if result is not None else item.get('result')
        job_store.update_item(
            conn, run_id, item_key, status=status, result=effective_result, error=error,
        )
        job_store.append_event(
            conn, run_id, 'item',
            {'item_key': str(item_key), 'status': status,
             'result': effective_result or {}, 'error': error},
        )

        counters = conn.execute(
            '''
            SELECT
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_count,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped_count
            FROM plugin_job_items WHERE run_id = ?
            ''',
            (run_id,),
        ).fetchone()
        job_store.update_job(
            conn, run_id,
            completed=int(counters['done_count'] or 0),
            failed=int(counters['failed_count'] or 0),
            skipped=int(counters['skipped_count'] or 0),
        )
        return True
    finally:
        conn.close()


def append_log_event(run_id: str, level: str, message: str) -> None:
    """追加一条 `log` 事件（供 `PluginAPI.log()` 使用）。"""
    conn = job_store.connect(ensure_schema=True)
    try:
        if not job_store.get_job(conn, run_id):
            return
        job_store.append_event(
            conn, run_id, 'log',
            {'level': str(level or 'info'), 'message': str(message or '')},
        )
    finally:
        conn.close()


# ------------------------------------------------------------------ Worker


def _finish_job(conn, run_id: str, status: str, *, error: str = '', summary: dict | None = None) -> None:
    """把作业置为终态，追加 `done` 事件并清理历史事件。"""
    finished_at = time.time()
    job = job_store.get_job(conn, run_id) or {}

    counters = conn.execute(
        '''
        SELECT
            SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_count,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
            SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped_count
        FROM plugin_job_items WHERE run_id = ?
        ''',
        (run_id,),
    ).fetchone()

    completed = int(counters['done_count'] or 0)
    failed = int(counters['failed_count'] or 0)
    skipped = int(counters['skipped_count'] or 0)

    payload_summary = job.get('summary') if isinstance(job.get('summary'), dict) else {}
    if summary:
        payload_summary.update(summary)

    job_store.update_job(
        conn, run_id,
        status=status,
        error=str(error or ''),
        completed=completed,
        failed=failed,
        skipped=skipped,
        finished_at=finished_at,
        summary_json=json.dumps(payload_summary, ensure_ascii=False),
        current_item='',
        claim_token='',
    )
    job_store.append_event(conn, run_id, 'done', {
        'status': status,
        'completed': completed,
        'failed': failed,
        'skipped': skipped,
        'summary': payload_summary,
        'error': str(error or ''),
    })
    job_store.prune_terminal_jobs(conn)


def _finalize_if_idle(conn, run_id: str) -> None:
    """作业被外部置为终态时，补一条 `done` 事件（避免 SSE 端等待超时）。"""
    job = job_store.get_job(conn, run_id)
    if not job or job['status'] not in job_store.TERMINAL_STATUSES:
        return
    last_seq = job_store.latest_event_seq(conn, run_id)
    events = job_store.read_events(conn, run_id, after_seq=max(0, last_seq - 1))
    if events and events[-1]['type'] == 'done':
        return
    _finish_job(conn, run_id, job['status'], error=job.get('error', ''))


def _run_job(job: dict) -> None:
    """执行单个作业（worker 线程内串行调用）。"""
    run_id = job.get('run_id', '')
    plugin_id = job.get('plugin_id', '')
    job_type = job.get('job_type', '')

    conn = job_store.connect(ensure_schema=True)
    try:
        handler = get_job_handler(plugin_id, job_type)
        if handler is None:
            _finish_job(conn, run_id, 'failed', error=f'未注册的作业类型: {job_type}')
            return

        items = job_store.list_items(conn, run_id, statuses=('pending',), limit=MAX_ITEMS_PER_RUN)
        if not items:
            _finish_job(conn, run_id, 'completed', summary={'message': '没有待处理项'})
            return

        api = _resolve_plugin_api(plugin_id)
        if api is not None:
            api.bind_job(run_id)

        context = JobContext(conn, job, items, api)
        job_store.append_event(conn, run_id, 'log', {
            'level': 'info', 'message': f'作业开始，共 {len(items)} 项',
        })

        try:
            handler(context)
        finally:
            if api is not None:
                api.bind_job(None)

        current = job_store.get_job(conn, run_id) or {}
        status = current.get('status', '')
        if status == 'running':
            _finish_job(conn, run_id, 'completed', summary=context._summary)
        else:
            logger.info('作业 %s 以非 running 状态结束（%s），保留原状态', run_id, status or 'unknown')
            job_store.update_job(conn, run_id, claim_token='')
    except Exception as exc:  # noqa: BLE001 - 作业异常必须落库，不能让 worker 线程退出
        logger.exception('插件作业执行失败: %s', run_id)
        try:
            _finish_job(conn, run_id, 'failed', error=str(exc))
        except Exception:  # noqa: BLE001
            logger.error('作业 %s 失败状态写入异常', run_id, exc_info=True)
    finally:
        conn.close()


def _resolve_plugin_api(plugin_id: str):
    try:
        from core.plugins import registry

        return registry.get_api(plugin_id)
    except Exception:  # noqa: BLE001 - registry 不可用时作业仍可运行
        logger.debug('无法获取插件 %s 的 API 实例', plugin_id, exc_info=True)
        return None


def _process_pending_jobs() -> int:
    conn = job_store.connect(ensure_schema=True)
    try:
        rows = job_store.claim_runnable_jobs(
            conn, limit=CLAIM_BATCH_LIMIT, max_per_plugin=MAX_JOBS_PER_PLUGIN,
        )
    finally:
        conn.close()

    for job in rows:
        _run_job(job)
    return len(rows)


def worker_loop() -> None:
    """worker 主循环：30s 兜底唤醒 + 显式 `_wakeup` 触发，收到停机信号即退出。"""
    while True:
        _wakeup.wait(WAKEUP_INTERVAL_SECONDS)
        _wakeup.clear()

        if _shutdown.is_set():
            logger.info('插件作业 worker 收到停机信号，退出循环')
            return

        try:
            _process_pending_jobs()
        except Exception:  # noqa: BLE001 - 循环必须存活
            logger.exception('插件作业 worker 轮询异常')


def start_plugin_job_worker() -> bool:
    """启动 worker（幂等）。启动时顺带做崩溃恢复。"""
    global _worker_started, _worker_thread
    with _worker_lock:
        if _worker_started:
            return False

        conn = job_store.connect(ensure_schema=True)
        try:
            aborted = job_store.abort_stale_jobs(conn)
            if aborted:
                logger.info('插件作业崩溃恢复：%s 个作业标记为 aborted', aborted)
        finally:
            conn.close()

        _shutdown.clear()
        _worker_started = True
        _worker_thread = threading.Thread(
            target=worker_loop, name='plugin-job-worker', daemon=True,
        )
        _worker_thread.start()
        return True


def stop_plugin_job_worker(*, timeout: float = 3.0) -> bool:
    """请求 worker 退出并等待其结束（幂等）。

    生产路径不需要调用（线程是 daemon），主要用于进程内重启/测试隔离。
    """
    global _worker_started, _worker_thread
    with _worker_lock:
        thread = _worker_thread
        if not _worker_started or thread is None:
            _worker_started = False
            _worker_thread = None
            return True
        _shutdown.set()
        _wakeup.set()

    if thread is not threading.current_thread():
        thread.join(timeout=timeout)

    stopped = not thread.is_alive()
    with _worker_lock:
        _worker_started = False
        _worker_thread = None
    return stopped


def is_worker_started() -> bool:
    return _worker_started


def wake_worker() -> None:
    _wakeup.set()


# ------------------------------------------------------------------ SSE


def _sse_frame(event: str, data: dict, *, seq=None) -> str:
    """SSE 帧：`id: <seq>` + `event:` + 多行 `data:`。

    公开给 `core.plugins.routes` 的核心事件流复用（`sse_frame` 是同一实现的公开别名），
    避免第二份帧构造逻辑漂移。
    """
    lines = []
    if seq is not None:
        lines.append(f'id: {int(seq)}')
    lines.append(f'event: {event}')
    text = json.dumps(data, ensure_ascii=False)
    for line in text.split('\n'):
        lines.append(f'data: {line}')
    return '\n'.join(lines) + '\n\n'


#: 公开别名：核心事件流与作业流共用同一份帧构造（设计文档 6.7.1）。
sse_frame = _sse_frame


def _acquire_sse_slot(run_id: str) -> bool:
    global _sse_total
    with _sse_lock:
        current = _sse_per_run.get(run_id, 0)
        if current >= SSE_MAX_CONNECTIONS_PER_RUN or _sse_total >= SSE_MAX_CONNECTIONS_TOTAL:
            return False
        _sse_per_run[run_id] = current + 1
        _sse_total += 1
        return True


def _release_sse_slot(run_id: str) -> None:
    global _sse_total
    with _sse_lock:
        current = _sse_per_run.get(run_id, 0)
        if current <= 1:
            _sse_per_run.pop(run_id, None)
        else:
            _sse_per_run[run_id] = current - 1
        _sse_total = max(0, _sse_total - 1)


def sse_connection_stats() -> dict:
    with _sse_lock:
        return {'total': _sse_total, 'per_run': dict(_sse_per_run)}


def _find_active_run(plugin_id: str) -> str:
    """同一插件正在运行/排队的作业（SSE 订阅用）。"""
    conn = job_store.connect(ensure_schema=True)
    try:
        placeholders = ','.join('?' for _ in job_store.ACTIVE_STATUSES)
        row = conn.execute(
            f'''
            SELECT run_id FROM plugin_jobs
            WHERE plugin_id = ? AND status IN ({placeholders})
            ORDER BY created_at DESC LIMIT 1
            ''',
            (str(plugin_id), *job_store.ACTIVE_STATUSES),
        ).fetchone()
        return str(row['run_id']) if row else ''
    finally:
        conn.close()


def build_snapshot(conn, run_id: str) -> dict:
    job = job_store.get_job(conn, run_id) or {}
    return {
        'run_id': run_id,
        'plugin_id': job.get('plugin_id', ''),
        'job_type': job.get('job_type', ''),
        'status': job.get('status', ''),
        'total': int(job.get('total') or 0),
        'completed': int(job.get('completed') or 0),
        'failed': int(job.get('failed') or 0),
        'skipped': int(job.get('skipped') or 0),
        'current_item': job.get('current_item', ''),
        'message': job.get('message', ''),
        'created_at': float(job.get('created_at') or 0),
        'started_at': float(job.get('started_at') or 0),
        'finished_at': float(job.get('finished_at') or 0),
    }


def stream_job_events(run_id: str, *, last_event_id: int = 0, plugin_id: str = '') -> Response:
    """构造 SSE 响应；`snapshot` 由端点现场合成，不落表。

    `plugin_id` 非空时校验归属：越权请求返回 `job_not_found` 的 `done` 帧，
    与「作业真不存在」表现一致（不透露他人作业是否存在）。
    """
    # 归属校验放在占用 SSE 槽位之前，避免越权请求消耗连接配额
    owner = str(plugin_id or '').strip()
    if owner:
        conn = job_store.connect(ensure_schema=True)
        try:
            job = job_store.get_job(conn, run_id)
        finally:
            conn.close()

        if not job or str(job.get('plugin_id') or '') != owner:
            if job:
                logger.warning(
                    '插件 %s 尝试订阅非本插件作业 %s（归属 %s），已拒绝',
                    owner, run_id, job.get('plugin_id'),
                )

            def _denied():
                yield _sse_frame('done', {'status': 'not_found', 'error': 'job_not_found'}, seq=0)

            return Response(_denied(), mimetype='text/event-stream')

    if not _acquire_sse_slot(run_id):
        raise PluginSseLimitError('SSE 连接数已达上限')

    try:
        start_seq = max(0, int(last_event_id or 0))
    except (TypeError, ValueError):
        start_seq = 0

    def generate():
        conn = job_store.connect(ensure_schema=True)
        try:
            job = job_store.get_job(conn, run_id)
            if not job:
                yield _sse_frame('done', {'status': 'not_found', 'error': 'job_not_found'}, seq=0)
                return

            snapshot = build_snapshot(conn, run_id)
            yield _sse_frame('snapshot', snapshot, seq=0)

            last_seq = start_seq
            last_heartbeat = time.monotonic()

            while True:
                events = job_store.read_events(conn, run_id, after_seq=last_seq, limit=500)
                for event in events:
                    last_seq = event['seq']
                    yield _sse_frame(event['type'], event['data'], seq=event['seq'])

                current = job_store.get_job(conn, run_id) or {}
                status = current.get('status', '')
                if status in job_store.TERMINAL_STATUSES and not events:
                    yield _sse_frame('done', {
                        'status': status,
                        'completed': int(current.get('completed') or 0),
                        'failed': int(current.get('failed') or 0),
                        'skipped': int(current.get('skipped') or 0),
                        'summary': current.get('summary') or {},
                        'error': current.get('error') or '',
                    }, seq=last_seq + 1)
                    return

                now = time.monotonic()
                if now - last_heartbeat >= SSE_HEARTBEAT_INTERVAL_SECONDS:
                    last_heartbeat = now
                    yield ': heartbeat\n\n'

                time.sleep(SSE_POLL_INTERVAL_SECONDS)
        except GeneratorExit:  # 客户端断开
            raise
        except Exception:  # noqa: BLE001 - 流内异常不能让响应挂死
            logger.exception('作业 SSE 流异常: %s', run_id)
        finally:
            conn.close()
            _release_sse_slot(run_id)

    return Response(generate(), mimetype='text/event-stream', headers={
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
        'Connection': 'keep-alive',
    })


def reset_for_tests() -> None:
    """清空处理器注册、SSE 计数并停掉后台 worker（仅测试用）。"""
    global _sse_total
    stop_plugin_job_worker()
    with _handlers_lock:
        _job_handlers.clear()
    with _sse_lock:
        _sse_per_run.clear()
        _sse_total = 0
    _wakeup.clear()
    _shutdown.clear()
