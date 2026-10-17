"""Short transactions coordinate model concurrency and pacing across processes."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text

from ai_idp.adapters.outbound.persistence.models import ModelRateStateRow, ModelRequestLeaseRow


class DatabaseModelLimiter:
    def __init__(
        self,
        session_factory,
        *,
        global_limit: int,
        per_model: dict[str, int],
        requests_per_minute: dict[str, int],
        lease_seconds: float = 180,
    ) -> None:
        self._sessions = session_factory
        self._global = global_limit
        self._per_model = per_model
        self._rpm = requests_per_minute
        self._lease_seconds = lease_seconds

    def try_acquire(self, model_id: str, lease_id: str) -> bool:
        now = datetime.now(UTC)
        with self._sessions() as db:
            if db.bind.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(42691021)"))
            # A write also serializes SQLite's test transactions.
            db.execute(delete(ModelRequestLeaseRow).where(ModelRequestLeaseRow.expires_at <= now))
            total = db.scalar(select(func.count()).select_from(ModelRequestLeaseRow))
            active = db.scalar(
                select(func.count())
                .select_from(ModelRequestLeaseRow)
                .where(ModelRequestLeaseRow.model_id == model_id)
            )
            limit = self._per_model.get(model_id, self._per_model.get("*", self._global))
            state = db.get(ModelRateStateRow, model_id)
            next_at = now
            if state:
                next_at = (
                    state.next_at.astimezone(UTC)
                    if state.next_at.tzinfo
                    else state.next_at.replace(tzinfo=UTC)
                )
            if total >= self._global or active >= limit or next_at > now:
                db.commit()
                return False
            rpm = self._rpm.get(model_id, self._rpm.get("*", 60))
            next_at = now + timedelta(seconds=60 / rpm)
            if state:
                state.next_at = next_at
            else:
                db.add(ModelRateStateRow(model_id=model_id, next_at=next_at))
            db.add(
                ModelRequestLeaseRow(
                    id=lease_id,
                    model_id=model_id,
                    expires_at=now + timedelta(seconds=self._lease_seconds),
                )
            )
            db.commit()
            return True

    def release(self, lease_id: str) -> None:
        with self._sessions() as db:
            db.execute(delete(ModelRequestLeaseRow).where(ModelRequestLeaseRow.id == lease_id))
            db.commit()

    @asynccontextmanager
    async def request(self, model_id: str):
        lease_id = uuid.uuid4().hex
        acquired = False
        try:
            while not acquired:
                # Keep acquisition on the event loop: cancellation must not orphan a
                # successful acquisition in an abandoned background thread.
                acquired = self.try_acquire(model_id, lease_id)
                if not acquired:
                    await asyncio.sleep(0.05)
            yield
        finally:
            if acquired:
                self.release(lease_id)
