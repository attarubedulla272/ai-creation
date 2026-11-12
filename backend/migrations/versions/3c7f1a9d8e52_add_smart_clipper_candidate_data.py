"""add explainable Smart Clipper candidate data

Revision ID: 3c7f1a9d8e52
Revises: ab41d620f753
Create Date: 2026-11-12 03:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3c7f1a9d8e52"
down_revision: str | None = "ab41d620f753"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clip_candidates") as batch:
        batch.add_column(sa.Column("scoring_factors", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("scene_ranges", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("transcript_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("caption_data", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("framing_data", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("exported_media_asset_id", sa.Uuid(), nullable=True))
        batch.create_index(
            "ix_clip_candidates_exported_media_asset_id", ["exported_media_asset_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("clip_candidates") as batch:
        batch.drop_index("ix_clip_candidates_exported_media_asset_id")
        batch.drop_column("exported_media_asset_id")
        batch.drop_column("framing_data")
        batch.drop_column("caption_data")
        batch.drop_column("transcript_text")
        batch.drop_column("scoring_factors")
        batch.drop_column("scene_ranges")
