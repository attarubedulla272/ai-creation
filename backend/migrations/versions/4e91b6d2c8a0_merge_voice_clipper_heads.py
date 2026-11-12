"""Merge the voice-dubbing and Smart Clipper migration branches.

Revision ID: 4e91b6d2c8a0
Revises: 0f31c4a982d7, 3c7f1a9d8e52
Create Date: 2026-11-12 12:00:00.000000
"""

from collections.abc import Sequence

revision: str = "4e91b6d2c8a0"
down_revision: tuple[str, str] = ("0f31c4a982d7", "3c7f1a9d8e52")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge schema histories without changing the database."""


def downgrade() -> None:
    """Leave downgrade behavior to the two parent revisions."""
