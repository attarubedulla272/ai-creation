"""Smart clip candidate metadata model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, Float, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models import MediaAsset, Project


class ClipCandidate(TimestampMixin, Base):
    """Proposed clip boundaries with explainable criteria, not an AI result."""

    __tablename__ = "clip_candidates"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(160))
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    scoring_factors: Mapped[dict[str, object] | None] = mapped_column(JSON)
    scene_ranges: Mapped[list[dict[str, object]] | None] = mapped_column(JSON)
    explanation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="candidate", nullable=False)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    caption_data: Mapped[list[dict[str, object]] | None] = mapped_column(JSON)
    framing_data: Mapped[dict[str, object] | None] = mapped_column(JSON)
    exported_media_asset_id: Mapped[UUID | None] = mapped_column(Uuid(as_uuid=True), index=True)

    project: Mapped[Project] = relationship("Project", back_populates="clip_candidates")
    source_asset: Mapped[MediaAsset | None] = relationship(
        "MediaAsset", back_populates="clip_candidates"
    )
