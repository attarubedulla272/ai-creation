"""add project script film planning and per-scene generation data

Revision ID: 91d2a7f4c630
Revises: 78f4c10a2b91
Create Date: 2026-11-12 02:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "91d2a7f4c630"
down_revision: str | None = "78f4c10a2b91"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("story_idea", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("story_outline", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("script_text", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("visual_settings", sa.JSON(), nullable=True))

    op.add_column("characters", sa.Column("identity_description", sa.Text(), nullable=True))
    op.add_column("characters", sa.Column("outfit_settings", sa.JSON(), nullable=True))

    op.create_table(
        "environment_references",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("visual_traits", sa.JSON(), nullable=True),
        sa.Column("reference_asset_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reference_asset_id"], ["media_assets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_environment_references_project_id", "environment_references", ["project_id"]
    )
    op.create_index(
        "ix_environment_references_reference_asset_id",
        "environment_references",
        ["reference_asset_id"],
    )

    op.add_column("scenes", sa.Column("scene_prompt", sa.Text(), nullable=True))
    op.add_column(
        "scenes", sa.Column("duration_seconds", sa.Float(), server_default="5", nullable=False)
    )
    op.add_column("scenes", sa.Column("camera_movement", sa.String(length=64), nullable=True))
    op.add_column("scenes", sa.Column("lighting", sa.String(length=120), nullable=True))
    op.add_column("scenes", sa.Column("color_palette", sa.String(length=160), nullable=True))
    op.add_column("scenes", sa.Column("environment_id", sa.Uuid(), nullable=True))
    op.add_column(
        "scenes", sa.Column("character_ids", sa.JSON(), server_default="[]", nullable=False)
    )
    op.add_column("scenes", sa.Column("first_frame_asset_id", sa.Uuid(), nullable=True))
    op.add_column("scenes", sa.Column("last_frame_asset_id", sa.Uuid(), nullable=True))
    op.add_column("scenes", sa.Column("generated_media_asset_id", sa.Uuid(), nullable=True))
    op.add_column(
        "scenes",
        sa.Column(
            "generation_status",
            sa.String(length=24),
            server_default="not_started",
            nullable=False,
        ),
    )
    op.add_column("scenes", sa.Column("generation_job_id", sa.Uuid(), nullable=True))
    op.add_column(
        "scenes", sa.Column("generated_preview_label", sa.String(length=255), nullable=True)
    )
    op.add_column("scenes", sa.Column("generation_provider", sa.String(length=100), nullable=True))
    op.add_column(
        "scenes", sa.Column("is_approved", sa.Boolean(), server_default=sa.false(), nullable=False)
    )
    op.add_column("scenes", sa.Column("continuity_notes", sa.Text(), nullable=True))
    op.create_index("ix_scenes_environment_id", "scenes", ["environment_id"])
    op.create_index("ix_scenes_first_frame_asset_id", "scenes", ["first_frame_asset_id"])
    op.create_index("ix_scenes_last_frame_asset_id", "scenes", ["last_frame_asset_id"])
    op.create_index("ix_scenes_generated_media_asset_id", "scenes", ["generated_media_asset_id"])
    op.create_index("ix_scenes_generation_job_id", "scenes", ["generation_job_id"])
    with op.batch_alter_table("scenes") as batch_op:
        batch_op.create_foreign_key(
            "fk_scenes_environment_id_environment_references",
            "environment_references",
            ["environment_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_scenes_first_frame_asset_id_media_assets",
            "media_assets",
            ["first_frame_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_scenes_last_frame_asset_id_media_assets",
            "media_assets",
            ["last_frame_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_scenes_generated_media_asset_id_media_assets",
            "media_assets",
            ["generated_media_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_scenes_generation_job_id_processing_jobs",
            "processing_jobs",
            ["generation_job_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.add_column("scene_shots", sa.Column("shot_prompt", sa.Text(), nullable=True))
    op.add_column("scene_shots", sa.Column("camera_movement", sa.String(length=64), nullable=True))
    op.add_column("scene_shots", sa.Column("first_frame_asset_id", sa.Uuid(), nullable=True))
    op.add_column("scene_shots", sa.Column("last_frame_asset_id", sa.Uuid(), nullable=True))
    op.create_index("ix_scene_shots_first_frame_asset_id", "scene_shots", ["first_frame_asset_id"])
    op.create_index("ix_scene_shots_last_frame_asset_id", "scene_shots", ["last_frame_asset_id"])
    with op.batch_alter_table("scene_shots") as batch_op:
        batch_op.create_foreign_key(
            "fk_scene_shots_first_frame_asset_id_media_assets",
            "media_assets",
            ["first_frame_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_scene_shots_last_frame_asset_id_media_assets",
            "media_assets",
            ["last_frame_asset_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("scene_shots") as batch_op:
        batch_op.drop_constraint(
            "fk_scene_shots_last_frame_asset_id_media_assets", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_scene_shots_first_frame_asset_id_media_assets", type_="foreignkey"
        )
    op.drop_index("ix_scene_shots_last_frame_asset_id", table_name="scene_shots")
    op.drop_index("ix_scene_shots_first_frame_asset_id", table_name="scene_shots")
    op.drop_column("scene_shots", "last_frame_asset_id")
    op.drop_column("scene_shots", "first_frame_asset_id")
    op.drop_column("scene_shots", "camera_movement")
    op.drop_column("scene_shots", "shot_prompt")

    with op.batch_alter_table("scenes") as batch_op:
        batch_op.drop_constraint("fk_scenes_generation_job_id_processing_jobs", type_="foreignkey")
        batch_op.drop_constraint("fk_scenes_last_frame_asset_id_media_assets", type_="foreignkey")
        batch_op.drop_constraint(
            "fk_scenes_generated_media_asset_id_media_assets", type_="foreignkey"
        )
        batch_op.drop_constraint("fk_scenes_first_frame_asset_id_media_assets", type_="foreignkey")
        batch_op.drop_constraint(
            "fk_scenes_environment_id_environment_references", type_="foreignkey"
        )
    op.drop_index("ix_scenes_generation_job_id", table_name="scenes")
    op.drop_index("ix_scenes_last_frame_asset_id", table_name="scenes")
    op.drop_index("ix_scenes_generated_media_asset_id", table_name="scenes")
    op.drop_index("ix_scenes_first_frame_asset_id", table_name="scenes")
    op.drop_index("ix_scenes_environment_id", table_name="scenes")
    for column in (
        "continuity_notes",
        "is_approved",
        "generation_provider",
        "generated_preview_label",
        "generation_job_id",
        "generation_status",
        "last_frame_asset_id",
        "generated_media_asset_id",
        "first_frame_asset_id",
        "character_ids",
        "environment_id",
        "color_palette",
        "lighting",
        "camera_movement",
        "scene_prompt",
        "duration_seconds",
    ):
        op.drop_column("scenes", column)

    op.drop_index(
        "ix_environment_references_reference_asset_id", table_name="environment_references"
    )
    op.drop_index("ix_environment_references_project_id", table_name="environment_references")
    op.drop_table("environment_references")
    op.drop_column("characters", "outfit_settings")
    op.drop_column("characters", "identity_description")
    op.drop_column("projects", "visual_settings")
    op.drop_column("projects", "script_text")
    op.drop_column("projects", "story_outline")
    op.drop_column("projects", "story_idea")
