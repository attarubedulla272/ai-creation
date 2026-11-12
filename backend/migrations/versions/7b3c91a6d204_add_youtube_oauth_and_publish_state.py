"""add encrypted YouTube channel connections and upload state

Revision ID: 7b3c91a6d204
Revises: 2d9a7c4e6b10
Create Date: 2026-11-12 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b3c91a6d204"
down_revision: str | None = "2d9a7c4e6b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("publications", sa.Column("youtube_status", sa.String(length=32)))
    op.add_column("publications", sa.Column("youtube_privacy_status", sa.String(length=16)))
    op.add_column("publications", sa.Column("youtube_url", sa.String(length=512)))
    op.create_table(
        "youtube_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("channel_id", sa.String(length=128), nullable=False),
        sa.Column("channel_title", sa.String(length=255), nullable=False),
        sa.Column("channel_custom_url", sa.String(length=255), nullable=True),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False),
        sa.Column("granted_scopes", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("last_error", sa.String(length=255), nullable=True),
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
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "channel_id", name="uq_youtube_connection_owner_channel"),
    )
    op.create_index("ix_youtube_connections_owner_id", "youtube_connections", ["owner_id"])
    op.create_table(
        "youtube_oauth_states",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("code_verifier_encrypted", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(length=24), nullable=False),
        sa.Column("expected_channel_id", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_hash", name="uq_youtube_oauth_state_hash"),
    )
    op.create_index("ix_youtube_oauth_states_owner_id", "youtube_oauth_states", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_youtube_oauth_states_owner_id", table_name="youtube_oauth_states")
    op.drop_table("youtube_oauth_states")
    op.drop_index("ix_youtube_connections_owner_id", table_name="youtube_connections")
    op.drop_table("youtube_connections")
    op.drop_column("publications", "youtube_url")
    op.drop_column("publications", "youtube_privacy_status")
    op.drop_column("publications", "youtube_status")
