"""Add durable schema discovery jobs without changing extraction state."""

import sqlalchemy as sa
from alembic import op

revision = "0004_schema_suggestions"
down_revision = "0003_model_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "schema_suggestion_jobs",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("idempotency_key", sa.String(128), nullable=True, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("owner", sa.String(128), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_schema_suggestion_jobs_status", "schema_suggestion_jobs", ["status"])


def downgrade() -> None:
    op.drop_table("schema_suggestion_jobs")
