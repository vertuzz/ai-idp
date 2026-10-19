"""Durable, fenced suggestion jobs and checkpoints with atomic request reservations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Integer, String, Text, case, func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from ai_idp.adapters.outbound.persistence.models import Base, JobQueueRow
from ai_idp.domain.errors import BudgetExhaustedError, DomainError
from ai_idp.domain.schema_suggestion import SuggestionJob


class SuggestionRow(Base):
    __tablename__ = "schema_suggestion_jobs"
    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[str] = mapped_column(Text)
    requests: Mapped[int] = mapped_column(Integer, default=0)
    owner: Mapped[str | None] = mapped_column(String(128))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SqlAlchemySuggestionRepository:
    def __init__(self, sessions, max_concurrent_jobs=2):
        self.sessions = sessions
        self.max_concurrent_jobs = max_concurrent_jobs

    def create(self, job, key=None):
        try:
            with self.sessions.begin() as db:
                db.add(
                    SuggestionRow(
                        job_id=job.job_id,
                        idempotency_key=key,
                        status=job.status,
                        payload=job.model_dump_json(),
                        created_at=datetime.now(UTC),
                        requests=0,
                    )
                )
            return job
        except IntegrityError:
            if key is None:
                raise
            with self.sessions() as db:
                row = db.scalar(select(SuggestionRow).where(SuggestionRow.idempotency_key == key))
                if row is None:
                    raise
                existing = SuggestionJob.model_validate_json(row.payload)
                if existing.document_ids != job.document_ids or existing.config != job.config:
                    raise DomainError(
                        "Idempotency key already belongs to a different suggestion request.",
                        code="idempotency_conflict",
                        http_status=409,
                    ) from None
                return self._decode(row)

    @staticmethod
    def _decode(row):
        job = SuggestionJob.model_validate_json(row.payload)
        job.status = row.status
        if row.status == "cancelled":
            job.stage = "cancelled"
        job.attempts = row.requests
        expires = row.lease_until
        if expires and expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        job.execution_active = bool(row.owner and expires and expires > datetime.now(UTC))
        return job

    def get(self, job_id):
        with self.sessions() as db:
            row = db.get(SuggestionRow, job_id)
            return self._decode(row) if row else None

    def claim(self, owner, lease_seconds):
        now = datetime.now(UTC)
        eligible = or_(
            SuggestionRow.status == "queued",
            (SuggestionRow.status == "running") & (SuggestionRow.lease_until < now),
        )
        with self.sessions.begin() as db:
            if db.bind.dialect.name == "postgresql":
                db.execute(text("SELECT pg_advisory_xact_lock(42691022)"))
            elif db.bind.dialect.name == "sqlite":
                db.execute(text("BEGIN IMMEDIATE"))
            active = db.scalar(
                select(func.count())
                .select_from(SuggestionRow)
                .where(
                    SuggestionRow.status == "running",
                    SuggestionRow.lease_until > now,
                )
            ) + db.scalar(
                select(func.count())
                .select_from(JobQueueRow)
                .where(
                    JobQueueRow.status == "leased",
                    JobQueueRow.lease_until > now,
                )
            )
            if active >= self.max_concurrent_jobs:
                return None
            candidate = (
                select(SuggestionRow.job_id)
                .where(eligible)
                .order_by(SuggestionRow.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
                .scalar_subquery()
            )
            row = db.execute(
                update(SuggestionRow)
                .where(SuggestionRow.job_id == candidate, eligible)
                .values(
                    status="running",
                    owner=owner,
                    lease_until=now + timedelta(seconds=lease_seconds),
                )
                .returning(SuggestionRow)
            ).scalar_one_or_none()
            return self._decode(row) if row else None

    def heartbeat(self, job_id, owner, lease_seconds):
        with self.sessions.begin() as db:
            return (
                db.execute(
                    update(SuggestionRow)
                    .where(
                        SuggestionRow.job_id == job_id,
                        SuggestionRow.owner == owner,
                        SuggestionRow.status == "running",
                        SuggestionRow.lease_until > datetime.now(UTC),
                    )
                    .values(lease_until=datetime.now(UTC) + timedelta(seconds=lease_seconds))
                ).rowcount
                == 1
            )

    def save(self, job, owner):
        values = {
            "payload": job.model_dump_json(),
            "status": case(
                (SuggestionRow.status == "cancelled", "cancelled"),
                else_=job.status,
            ),
        }
        if job.status != "running":
            values.update(owner=None, lease_until=None)
        with self.sessions.begin() as db:
            changed = db.execute(
                update(SuggestionRow)
                .where(
                    SuggestionRow.job_id == job.job_id,
                    SuggestionRow.owner == owner,
                    SuggestionRow.status.in_(["running", "cancelled"]),
                    SuggestionRow.lease_until > datetime.now(UTC),
                )
                .values(**values)
            ).rowcount
            if changed != 1:
                raise DomainError("Suggestion execution lease was lost.", code="lease_lost")

    def reserve_request(self, job_id, owner, limit):
        with self.sessions.begin() as db:
            changed = db.execute(
                update(SuggestionRow)
                .where(
                    SuggestionRow.job_id == job_id,
                    SuggestionRow.owner == owner,
                    SuggestionRow.status == "running",
                    SuggestionRow.requests < limit,
                    SuggestionRow.lease_until > datetime.now(UTC),
                )
                .values(requests=SuggestionRow.requests + 1)
            ).rowcount
            if changed != 1:
                raise BudgetExhaustedError("Suggestion request limit reached or execution ended.")

    def cancel(self, job_id):
        with self.sessions.begin() as db:
            db.execute(
                update(SuggestionRow)
                .where(
                    SuggestionRow.job_id == job_id, SuggestionRow.status.in_(["queued", "running"])
                )
                .values(status="cancelled")
            )
