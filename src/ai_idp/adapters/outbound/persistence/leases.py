from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_idp.adapters.outbound.persistence.models import JobQueueRow
from ai_idp.domain.errors import JobLeaseLostError

_execution: ContextVar[tuple[str, str] | None] = ContextVar("job_execution", default=None)


@contextmanager
def execution_scope(job_id: str, worker_id: str):
    token = _execution.set((job_id, worker_id))
    try:
        yield
    finally:
        _execution.reset(token)


def require_lease(session: Session, job_id: str) -> JobQueueRow:
    """Lock and fence every job write in the same short database transaction."""
    execution = _execution.get()
    row = session.scalar(select(JobQueueRow).where(JobQueueRow.job_id == job_id).with_for_update())
    until = row.lease_until if row else None
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    if (
        execution is None
        or execution[0] != job_id
        or row is None
        or row.status != "leased"
        or row.lease_owner != execution[1]
        or until is None
        or until <= datetime.now(UTC)
    ):
        raise JobLeaseLostError(f"Execution no longer owns the lease for job '{job_id}'.")
    return row
