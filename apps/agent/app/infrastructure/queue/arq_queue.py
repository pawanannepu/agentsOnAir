"""ARQ Redis queue adapter with in memory fallback for offline testing."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.application.ports.task_queue import TaskQueue

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScheduledJobRecord:
    """Recorded queue dispatch metadata for observability and testing."""

    job_name: str
    args: tuple[Any, ...]
    defer_by_seconds: int | None = None
    job_id: str | None = None


class ArqTaskQueue(TaskQueue):
    """ARQ background task queue with graceful fallback when Redis is unreachable."""

    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url
        self._pool: ArqRedis | None = None
        self._redis_disabled = False
        self.scheduled_jobs: list[ScheduledJobRecord] = []

    async def _get_pool(self) -> ArqRedis | None:
        if not self._redis_url or self._redis_disabled:
            return None
        if self._pool is not None:
            return self._pool
        try:
            settings = RedisSettings.from_dsn(self._redis_url)
            settings.conn_timeout = 1
            settings.conn_retries = 0
            pool = await create_pool(settings)
            await pool.ping()
            self._pool = pool
            return self._pool
        except Exception as exc:
            logger.info(
                "ARQ Redis unavailable at %s (%s), recording jobs in memory",
                self._redis_url,
                exc,
            )
            self._redis_disabled = True
            self._pool = None
            return None

    async def enqueue_resume_task(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        task_run_id: uuid.UUID | None = None,
        intervention_id: uuid.UUID | None = None,
        response: str | dict | None = None,
    ) -> str | None:
        args = (
            str(org_id),
            str(task_id),
            str(task_run_id) if task_run_id else None,
            str(intervention_id) if intervention_id else None,
            response,
        )
        job_id = f"resume:{task_id}:{uuid.uuid4().hex[:8]}"
        pool = await self._get_pool()
        if pool is not None:
            try:
                job = await pool.enqueue_job(
                    "resume_task_job",
                    *args,
                    _job_id=job_id,
                )
                job_id = job.job_id if job else job_id
            except Exception as exc:
                logger.warning("Failed to enqueue ARQ resume job: %s", exc)

        self.scheduled_jobs.append(
            ScheduledJobRecord(
                job_name="resume_task_job",
                args=args,
                defer_by_seconds=None,
                job_id=job_id,
            )
        )
        return job_id

    async def schedule_interruption_watchdog(
        self,
        org_id: uuid.UUID,
        task_id: uuid.UUID,
        expires_at: datetime,
        delay_seconds: int = 900,
    ) -> str | None:
        args = (str(org_id), str(task_id), expires_at.isoformat())
        job_id = f"watchdog:{task_id}:{int(expires_at.timestamp())}"
        pool = await self._get_pool()
        if pool is not None:
            try:
                job = await pool.enqueue_job(
                    "interruption_timeout_watchdog",
                    *args,
                    _job_id=job_id,
                    _defer_by=timedelta(seconds=delay_seconds),
                )
                job_id = job.job_id if job else job_id
            except Exception as exc:
                logger.warning("Failed to schedule ARQ watchdog job: %s", exc)

        self.scheduled_jobs.append(
            ScheduledJobRecord(
                job_name="interruption_timeout_watchdog",
                args=args,
                defer_by_seconds=delay_seconds,
                job_id=job_id,
            )
        )
        return job_id

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None


_default_task_queue: ArqTaskQueue | None = None


def get_task_queue() -> ArqTaskQueue:
    """Return the shared ARQ task queue instance."""
    global _default_task_queue
    if _default_task_queue is None:
        from app.core.config import settings

        _default_task_queue = ArqTaskQueue(
            redis_url=getattr(settings, "REDIS_URL", None)
        )
    return _default_task_queue
