"""Add transcript revision snapshots and dubbing glossary storage.

Revision ID: 0f31c4a982d7
Revises: ab41d620f753
Create Date: 2026-11-12 11:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0f31c4a982d7"
down_revision: str | None = "ab41d620f753"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dubbing_projects",
        sa.Column("glossary", sa.JSON(), server_default="[]", nullable=False),
    )
    op.create_table(
        "transcript_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "transcript_id", "revision_number", name="uq_transcript_revision_number"
        ),
    )
    op.create_index(
        "ix_transcript_revisions_transcript_id",
        "transcript_revisions",
        ["transcript_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_transcript_revisions_transcript_id", table_name="transcript_revisions")
    op.drop_table("transcript_revisions")
    op.drop_column("dubbing_projects", "glossary")
