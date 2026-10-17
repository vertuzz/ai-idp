"""Persist model step checkpoints and all source images.

Revision ID: 0002_steps_and_images
Revises: 0001_initial_schema
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_steps_and_images"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "document_units",
        sa.Column("image_refs_json", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "job_steps",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column("step_key", sa.String(128), primary_key=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["extraction_jobs.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("job_steps")
    op.drop_column("document_units", "image_refs_json")
