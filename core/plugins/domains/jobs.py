"""作业域：`api.jobs.*`。

作业按 `plugin_id` 隔离：非本插件的 `run_id` 一律按「不存在」处理，
不透露他人作业是否存在。

`items()` 是补齐裸 SQL 缺口的新增能力（原 `api.db()` 读 `plugin_job_items`
的用法），支持在 `get()` 的条目分页之外取全量条目。
"""

from core.plugins.domains._base import DomainBase


class JobDomain(DomainBase):
    """插件后台作业的注册、提交、查询与生命周期控制。"""

    domain_name = 'jobs'

    def register(self, job_type: str, handler) -> None:
        """注册作业处理器。`job_type` 必须已在 manifest 的 `backend.jobs` 声明。"""
        from core.plugins import jobs

        declared = set(self._api._manifest.backend_jobs or [])
        job_type = str(job_type or '').strip()
        if declared and job_type not in declared:
            raise ValueError(f'job_type {job_type!r} 未在 manifest.backend.jobs 中声明')
        jobs.register_job_handler(self.plugin_id, job_type, handler)

    def submit(self, job_type: str, *, items, payload=None) -> str:
        """提交作业，返回 run_id。

        `payload` 会明文落库，**禁止**写入密钥值；需要密钥时只放
        `{"secret_ref": "key_name"}`，由 worker 运行时解析。
        """
        from core.plugins import jobs

        return jobs.submit_job(self.plugin_id, job_type, items, payload)

    def get(self, run_id: str):
        """读取作业详情（含进度、条目与最近事件）；不存在或**非本插件作业**时返回 None。"""
        from core.plugins import jobs

        return jobs.get_job_detail(run_id, plugin_id=self.plugin_id)

    def items(self, run_id: str, *, status=None, limit: int = 0, offset: int = 0) -> list:
        """读取作业条目（分页取全量，不受 `get()` 的条目上限约束）。

        Args:
            run_id: 作业 id；非本插件作业会抛 `PluginJobNotFoundError`。
            status: 只取该状态的条目（`pending` / `running` / `done` /
                `failed` / `skipped` / `awaiting_review`）；省略表示全部。
            limit: 返回上限；`0` 表示不设上限（仍受单次作业条目数上限约束）。
            offset: 起始偏移。

        Returns:
            `[{'key', 'status', 'payload', 'result', 'error', 'attempt', 'seq', …}, …]`
        """
        from core.plugins import job_store, jobs

        statuses = (str(status).strip(),) if status else None
        conn = job_store.connect(ensure_schema=True)
        try:
            # 归属校验复用 jobs 的唯一实现（越权按「不存在」处理）
            jobs._require_job(conn, run_id, plugin_id=self.plugin_id)
            effective_limit = int(limit) if int(limit or 0) > 0 else jobs.MAX_ITEMS_PER_RUN
            return job_store.list_items(
                conn, run_id,
                statuses=statuses,
                limit=effective_limit,
                offset=max(0, int(offset or 0)),
            )
        finally:
            conn.close()

    def cancel(self, run_id: str) -> bool:
        """请求取消本插件的作业（协作式：处理器下次 `should_cancel()` 时退出）。

        非本插件的 run_id 会抛 `job_not_found`——作业按 `plugin_id` 隔离。
        """
        from core.plugins import jobs

        return jobs.cancel_job(run_id, plugin_id=self.plugin_id)

    def retry(self, run_id: str, *, only_failed: bool = True) -> str:
        """重跑本插件的作业；`only_failed=True` 时只重置失败条目，返回 run_id。"""
        from core.plugins import jobs

        return jobs.retry_job(run_id, only_failed=only_failed, plugin_id=self.plugin_id)

    def pause(self, run_id: str) -> bool:
        """暂停本插件的作业（等待人工处理后由 `resume` 恢复）。"""
        from core.plugins import jobs

        return jobs.pause_job(run_id, plugin_id=self.plugin_id)

    def resume(self, run_id: str) -> bool:
        """恢复本插件被暂停的作业，返回是否成功。"""
        from core.plugins import jobs

        return jobs.resume_job(run_id, plugin_id=self.plugin_id)
