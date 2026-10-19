from __future__ import annotations

import asyncio
import signal
import uuid

from ai_idp.adapters.inbound.http.dependencies import AppContainer, build_container


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
        self._prefer_suggestions = True

    def stop(self) -> None:
        self._stop_event.set()

    async def process_one_if_available(self) -> str | None:
        if self._prefer_suggestions:
            suggestion_id = await self._container.suggestion_service.process_one_if_available()
            if suggestion_id is not None:
                self._prefer_suggestions = False
                return suggestion_id
        owner = f"{self._worker_id}:{uuid.uuid4().hex}"
        job = self._container.job_repo.lease_next_job(
            worker_id=owner,
            lease_seconds=self._lease_seconds,
        )
        if job is None:
            if not self._prefer_suggestions:
                return await self._container.suggestion_service.process_one_if_available()
            return None

        self._prefer_suggestions = True
        try:
            await self._container.pipeline_service.execute_job(job.job_id, lease_owner=owner)
            return job.job_id
        except Exception:
            # The executor persists failures and retries while still owning the lease.
            return job.job_id

    async def run_forever(self) -> None:
        async def slot() -> None:
            while not self._stop_event.is_set():
                processed = await self.process_one_if_available()
                if processed is None:
                    try:
                        await asyncio.wait_for(self._stop_event.wait(), self._poll_seconds)
                    except TimeoutError:
                        pass

        active_tasks = {asyncio.create_task(slot()) for _ in range(self._max_concurrent)}
        stopping = asyncio.create_task(self._stop_event.wait())
        try:
            done, _ = await asyncio.wait(
                active_tasks | {stopping}, return_when=asyncio.FIRST_COMPLETED
            )
            if stopping in done:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*active_tasks),
                        self._container.settings.worker_shutdown_seconds,
                    )
                except TimeoutError:
                    pass
            else:
                await asyncio.gather(*done)
        finally:
            stopping.cancel()
            for task in active_tasks:
                task.cancel()
            await asyncio.gather(*active_tasks, stopping, return_exceptions=True)


async def _main() -> None:
    container = build_container()
    runner = WorkerRunner(container)
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: runner.stop())
    await runner.run_forever()


if __name__ == "__main__":
    asyncio.run(_main())
