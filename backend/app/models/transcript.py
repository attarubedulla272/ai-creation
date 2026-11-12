"""Transcript and timed transcript segment models."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models import MediaAsset, Project


class Transcript(TimestampMixin, Base):
    """Transcript associated with a project and optional source asset."""

    __tablename__ = "transcripts"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    media_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    language: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)

    project: Mapped[Project] = relationship("Project", back_populates="transcripts")
    media_asset: Mapped[MediaAsset | None] = relationship(
        "MediaAsset", back_populates="transcripts"
    )
    segments: Mapped[list[TranscriptSegment]] = relationship(
        "TranscriptSegment",
        back_populates="transcript",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.order_index",
    )


class TranscriptSegment(TimestampMixin, Base):
    """One timed transcript segment."""

    __tablename__ = "transcript_segments"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    transcript_id: Mapped[UUID] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker_label: Mapped[str | None] = mapped_column(String(120))
    translated_text: Mapped[str | None] = mapped_column(Text)
    voice_profile_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("voice_profiles.id", ondelete="SET NULL"), index=True
    )
    speech_rate: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    transcript: Mapped[Transcript] = relationship("Transcript", back_populates="segments")
