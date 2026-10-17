from __future__ import annotations

import asyncio
import contextlib
import uuid

from ai_idp.adapters.inbound.http.dependencies import AppContainer, build_container
from ai_idp.domain.enums import JobStatus


class WorkerRunner:
    """Polls PostgreSQL job_queue with SKIP LOCKED, renews leases, and executes jobs."""

    def __init__(
        self,
        container: AppContainer,
        *,
        worker_id: str | None = None,
    ) -> None:
        self._container = container
        self._worker_id = worker_id or f"worker_{uuid.uuid4().hex[:8]}"
        self._lease_seconds = container.settings.worker_lease_seconds
        self._poll_seconds = container.settings.worker_poll_seconds
        self._max_concurrent = container.settings.max_concurrent_jobs
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        self._stop_event.set()

    async def process_one_if_available(self) -> str | None:
        job = self._container.job_repo.lease_next_job(
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )
        if job is None:
            return None

        heartbeat_task = asyncio.create_task(self._heartbeat_loop(job.job_id))
        try:
            result = await self._container.pipeline_service.execute_job(job.job_id)
            self._container.job_repo.complete_queue_item(job.job_id, result.status)
            return job.job_id
        except Exception as exc:
            self._container.job_repo.complete_queue_item(
                job.job_id,
                JobStatus.FAILED,
                error=str(exc)[:1000],
            )
            return job.job_id
        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _heartbeat_loop(self, job_id: str) -> None:
        interval = max(1.0, self._lease_seconds / 3.0)
        while not self._stop_event.is_set():
            await asyncio.sleep(interval)
            self._container.job_repo.heartbeat_job(
                job_id=job_id,
                worker_id=self._worker_id,
                lease_seconds=self._lease_seconds,
            )

    async def run_forever(self) -> None:
        active_tasks: set[asyncio.Task[str | None]] = set()
        while not self._stop_event.is_set():
            done = {t for t in active_tasks if t.done()}
            active_tasks -= done

            while len(active_tasks) < self._max_concurrent:
                job_id = await self.process_one_if_available()
                if job_id is None:
                    break
            await asyncio.sleep(self._poll_seconds)


async def _main() -> None:
    container = build_container()
    runner = WorkerRunner(container)
    await runner.run_forever()


if __name__ == "__main__":
    asyncio.run(_main())
