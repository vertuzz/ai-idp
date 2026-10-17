"""Initial AI-IDP PostgreSQL schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-10-17 13:55:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_documents_checksum", "documents", ["checksum"], unique=False)

    op.create_table(
        "document_units",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("unit_id", sa.String(length=64), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("locator_json", sa.JSON(), nullable=False),
        sa.Column("text_ref", sa.String(length=512), nullable=True),
        sa.Column("image_ref", sa.String(length=512), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "unit_id", name="uq_document_unit"),
    )
    op.create_index(
        "ix_document_units_document_id", "document_units", ["document_id"], unique=False
    )

    op.create_table(
        "extraction_specs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("schema_json", sa.JSON(), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_specs_schema_hash", "extraction_specs", ["schema_hash"], unique=False
    )

    op.create_table(
        "extraction_jobs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("document_id", sa.String(length=64), nullable=False),
        sa.Column("spec_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("configuration_json", sa.JSON(), nullable=False),
        sa.Column("progress_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["spec_id"], ["extraction_specs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_extraction_jobs_document_id", "extraction_jobs", ["document_id"], unique=False
    )
    op.create_index("ix_extraction_jobs_status", "extraction_jobs", ["status"], unique=False)

    op.create_table(
        "job_queue",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["extraction_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_job_queue_status", "job_queue", ["status"], unique=False)
    op.create_index("ix_job_queue_available_at", "job_queue", ["available_at"], unique=False)
    op.create_index("ix_job_queue_lease_until", "job_queue", ["lease_until"], unique=False)

    op.create_table(
        "decisions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("unit_id", sa.String(length=64), nullable=True),
        sa.Column("field_path", sa.String(length=255), nullable=True),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("scores_json", sa.JSON(), nullable=False),
        sa.Column("selected_json", sa.JSON(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["extraction_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_decisions_job_id", "decisions", ["job_id"], unique=False)

    op.create_table(
        "field_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("field_path", sa.String(length=255), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("candidate_json", sa.JSON(), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["extraction_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "field_path", "attempt_number", name="uq_job_field_attempt"),
    )
    op.create_index("ix_field_attempts_job_id", "field_attempts", ["job_id"], unique=False)

    op.create_table(
        "field_results",
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("field_path", sa.String(length=255), nullable=False),
        sa.Column("final_value_json", sa.JSON(), nullable=True),
        sa.Column("field_status", sa.String(length=32), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=True),
        sa.Column("score_json", sa.JSON(), nullable=False),
        sa.Column("sources_json", sa.JSON(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["extraction_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id", "field_path"),
    )

    op.create_table(
        "usage_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=False),
        sa.Column("model_id", sa.String(length=128), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["extraction_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_records_job_id", "usage_records", ["job_id"], unique=False)

    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("dataset_ref", sa.String(length=255), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("metrics_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evaluation_runs_config_hash", "evaluation_runs", ["config_hash"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_runs_config_hash", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
    op.drop_index("ix_usage_records_job_id", table_name="usage_records")
    op.drop_table("usage_records")
    op.drop_table("field_results")
    op.drop_index("ix_field_attempts_job_id", table_name="field_attempts")
    op.drop_table("field_attempts")
    op.drop_index("ix_decisions_job_id", table_name="decisions")
    op.drop_table("decisions")
    op.drop_index("ix_job_queue_lease_until", table_name="job_queue")
    op.drop_index("ix_job_queue_available_at", table_name="job_queue")
    op.drop_index("ix_job_queue_status", table_name="job_queue")
    op.drop_table("job_queue")
    op.drop_index("ix_extraction_jobs_status", table_name="extraction_jobs")
    op.drop_index("ix_extraction_jobs_document_id", table_name="extraction_jobs")
    op.drop_table("extraction_jobs")
    op.drop_index("ix_extraction_specs_schema_hash", table_name="extraction_specs")
    op.drop_table("extraction_specs")
    op.drop_index("ix_document_units_document_id", table_name="document_units")
    op.drop_table("document_units")
    op.drop_index("ix_documents_checksum", table_name="documents")
    op.drop_table("documents")
