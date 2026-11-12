"""Immutable snapshots of transcript edits."""

from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TranscriptRevision(TimestampMixin, Base):
    """A complete pre-edit snapshot, preserving source and translated text."""

    __tablename__ = "transcript_revisions"
    __table_args__ = (
        UniqueConstraint("transcript_id", "revision_number", name="uq_transcript_revision_number"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transcript_id: Mapped[UUID] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"), index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
