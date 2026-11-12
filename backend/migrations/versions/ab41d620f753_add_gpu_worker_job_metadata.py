"""add independent GPU worker job metadata and cancellation

Revision ID: ab41d620f753
Revises: 91d2a7f4c630
Create Date: 2026-11-12 03:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ab41d620f753"
down_revision: str | None = "91d2a7f4c630"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("processing_jobs", sa.Column("model_name", sa.String(length=160), nullable=True))
    op.add_column(
        "processing_jobs", sa.Column("model_version", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "processing_jobs", sa.Column("model_license", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "processing_jobs", sa.Column("commercial_use_permitted", sa.Boolean(), nullable=True)
    )
    op.add_column(
        "processing_jobs", sa.Column("generation_mode", sa.String(length=32), nullable=True)
    )
    op.add_column("processing_jobs", sa.Column("generation_settings", sa.JSON(), nullable=True))
    op.add_column(
        "processing_jobs", sa.Column("worker_job_id", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "processing_jobs",
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("max_retries", sa.Integer(), server_default="2", nullable=False),
    )
    op.add_column(
        "processing_jobs",
        sa.Column(
            "cancellation_requested", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )
    op.create_index("ix_processing_jobs_worker_job_id", "processing_jobs", ["worker_job_id"])


def downgrade() -> None:
    op.drop_index("ix_processing_jobs_worker_job_id", table_name="processing_jobs")
    op.drop_column("processing_jobs", "cancellation_requested")
    op.drop_column("processing_jobs", "max_retries")
    op.drop_column("processing_jobs", "retry_count")
    op.drop_column("processing_jobs", "worker_job_id")
    op.drop_column("processing_jobs", "generation_settings")
    op.drop_column("processing_jobs", "generation_mode")
    op.drop_column("processing_jobs", "commercial_use_permitted")
    op.drop_column("processing_jobs", "model_license")
    op.drop_column("processing_jobs", "model_version")
    op.drop_column("processing_jobs", "model_name")
