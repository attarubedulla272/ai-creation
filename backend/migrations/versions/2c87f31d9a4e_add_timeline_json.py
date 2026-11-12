"""add structured timeline data

Revision ID: 2c87f31d9a4e
Revises: fa0b41bc4e10
Create Date: 2026-11-11 20:15:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2c87f31d9a4e"
down_revision: str | None = "fa0b41bc4e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "timelines",
        sa.Column("timeline_data", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("timelines", "timeline_data")
