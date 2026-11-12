"""add persistent SEO and publishing preparation data

Revision ID: 2d9a7c4e6b10
Revises: 4e91b6d2c8a0
Create Date: 2026-11-12 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2d9a7c4e6b10"
down_revision: str | None = "4e91b6d2c8a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("publications", sa.Column("metadata", sa.JSON(), nullable=True))
    op.add_column("publications", sa.Column("media_asset_id", sa.Uuid(), nullable=True))
    op.add_column("publications", sa.Column("clip_candidate_id", sa.Uuid(), nullable=True))
    op.add_column("publications", sa.Column("thumbnail_asset_id", sa.Uuid(), nullable=True))
    op.add_column(
        "publications",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    op.create_index("ix_publications_media_asset_id", "publications", ["media_asset_id"])
    op.create_index("ix_publications_clip_candidate_id", "publications", ["clip_candidate_id"])
    op.create_index("ix_publications_thumbnail_asset_id", "publications", ["thumbnail_asset_id"])
    with op.batch_alter_table("publications") as batch_op:
        batch_op.create_foreign_key(
            "fk_publications_media_asset_id_media_assets",
            "media_assets",
            ["media_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_publications_clip_candidate_id_clip_candidates",
            "clip_candidates",
            ["clip_candidate_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_publications_thumbnail_asset_id_media_assets",
            "media_assets",
            ["thumbnail_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_table(
        "publication_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("publication_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["publication_id"], ["publications.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publication_id", "version", name="uq_publication_revision_version"),
    )
    op.create_index(
        "ix_publication_revisions_publication_id",
        "publication_revisions",
        ["publication_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_publication_revisions_publication_id", table_name="publication_revisions")
    op.drop_table("publication_revisions")
    with op.batch_alter_table("publications") as batch_op:
        batch_op.drop_constraint(
            "fk_publications_thumbnail_asset_id_media_assets", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_publications_clip_candidate_id_clip_candidates", type_="foreignkey"
        )
        batch_op.drop_constraint("fk_publications_media_asset_id_media_assets", type_="foreignkey")
    op.drop_index("ix_publications_thumbnail_asset_id", table_name="publications")
    op.drop_index("ix_publications_clip_candidate_id", table_name="publications")
    op.drop_index("ix_publications_media_asset_id", table_name="publications")
    op.drop_column("publications", "version")
    op.drop_column("publications", "thumbnail_asset_id")
    op.drop_column("publications", "clip_candidate_id")
    op.drop_column("publications", "media_asset_id")
    op.drop_column("publications", "metadata")
