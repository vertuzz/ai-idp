"""Coordinate provider requests across API and worker processes."""

import sqlalchemy as sa
from alembic import op

revision = "0003_model_limits"
down_revision = "0002_steps_and_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "usage_records", sa.Column("call_count", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_table(
        "model_request_leases",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_model_request_leases_model_id", "model_request_leases", ["model_id"])
    op.create_index("ix_model_request_leases_expires_at", "model_request_leases", ["expires_at"])
    op.create_table(
        "model_rate_states",
        sa.Column("model_id", sa.String(128), primary_key=True),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("model_rate_states")
    op.drop_table("model_request_leases")
    op.drop_column("usage_records", "call_count")
