"""add voice studio provider and dubbing data

Revision ID: 78f4c10a2b91
Revises: 2c87f31d9a4e
Create Date: 2026-11-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "78f4c10a2b91"
down_revision: str | None = "2c87f31d9a4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "voice_consents",
        sa.Column(
            "authorization_basis",
            sa.String(length=32),
            server_default="self_attestation",
            nullable=False,
        ),
    )
    op.add_column("voice_profiles", sa.Column("reference_asset_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_voice_profiles_reference_asset_id",
        "voice_profiles",
        ["reference_asset_id"],
    )
    with op.batch_alter_table("voice_profiles") as batch_op:
        batch_op.create_foreign_key(
            "fk_voice_profiles_reference_asset_id_media_assets",
            "media_assets",
            ["reference_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.add_column("transcript_segments", sa.Column("translated_text", sa.Text(), nullable=True))
    op.add_column("transcript_segments", sa.Column("voice_profile_id", sa.Uuid(), nullable=True))
    op.add_column(
        "transcript_segments",
        sa.Column("speech_rate", sa.Float(), server_default="1.0", nullable=False),
    )
    op.create_index(
        "ix_transcript_segments_voice_profile_id",
        "transcript_segments",
        ["voice_profile_id"],
    )
    with op.batch_alter_table("transcript_segments") as batch_op:
        batch_op.create_foreign_key(
            "fk_transcript_segments_voice_profile_id_voice_profiles",
            "voice_profiles",
            ["voice_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_table(
        "dubbing_projects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("transcript_id", sa.Uuid(), nullable=False),
        sa.Column("target_language", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="draft", nullable=False),
        sa.Column("segments_data", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["transcript_id"], ["transcripts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dubbing_projects_owner_id", "dubbing_projects", ["owner_id"])
    op.create_index("ix_dubbing_projects_project_id", "dubbing_projects", ["project_id"])
    op.create_index("ix_dubbing_projects_transcript_id", "dubbing_projects", ["transcript_id"])


def downgrade() -> None:
    op.drop_index("ix_dubbing_projects_transcript_id", table_name="dubbing_projects")
    op.drop_index("ix_dubbing_projects_project_id", table_name="dubbing_projects")
    op.drop_index("ix_dubbing_projects_owner_id", table_name="dubbing_projects")
    op.drop_table("dubbing_projects")
    with op.batch_alter_table("transcript_segments") as batch_op:
        batch_op.drop_constraint(
            "fk_transcript_segments_voice_profile_id_voice_profiles",
            type_="foreignkey",
        )
    op.drop_index("ix_transcript_segments_voice_profile_id", table_name="transcript_segments")
    op.drop_column("transcript_segments", "speech_rate")
    op.drop_column("transcript_segments", "voice_profile_id")
    op.drop_column("transcript_segments", "translated_text")
    with op.batch_alter_table("voice_profiles") as batch_op:
        batch_op.drop_constraint(
            "fk_voice_profiles_reference_asset_id_media_assets",
            type_="foreignkey",
        )
    op.drop_index("ix_voice_profiles_reference_asset_id", table_name="voice_profiles")
    op.drop_column("voice_profiles", "reference_asset_id")
    op.drop_column("voice_consents", "authorization_basis")
