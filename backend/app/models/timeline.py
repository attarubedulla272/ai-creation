"""Timeline, track, and clip models."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models import MediaAsset, Project


class Timeline(TimestampMixin, Base):
    """Project editing timeline."""

    __tablename__ = "timelines"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), unique=True
    )
    name: Mapped[str] = mapped_column(String(160), default="Main timeline", nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    frame_rate: Mapped[float] = mapped_column(Float, default=24, nullable=False)
    width: Mapped[int] = mapped_column(Integer, default=1920, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=1080, nullable=False)
    timeline_data: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)

    project: Mapped[Project] = relationship("Project", back_populates="timeline")
    tracks: Mapped[list[TimelineTrack]] = relationship(
        "TimelineTrack", back_populates="timeline", cascade="all, delete-orphan"
    )


class TimelineTrack(TimestampMixin, Base):
    """Ordered audio or video lane in a timeline."""

    __tablename__ = "timeline_tracks"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    timeline_id: Mapped[UUID] = mapped_column(
        ForeignKey("timelines.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    track_type: Mapped[str] = mapped_column(String(24), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    volume: Mapped[float] = mapped_column(Float, default=1, nullable=False)

    timeline: Mapped[Timeline] = relationship("Timeline", back_populates="tracks")
    clips: Mapped[list[TimelineClip]] = relationship(
        "TimelineClip", back_populates="track", cascade="all, delete-orphan"
    )


class TimelineClip(TimestampMixin, Base):
    """A media clip placed on a timeline track."""

    __tablename__ = "timeline_clips"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    track_id: Mapped[UUID] = mapped_column(
        ForeignKey("timeline_tracks.id", ondelete="CASCADE"), index=True
    )
    media_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    source_start_seconds: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    source_end_seconds: Mapped[float | None] = mapped_column(Float)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    track: Mapped[TimelineTrack] = relationship("TimelineTrack", back_populates="clips")
    media_asset: Mapped[MediaAsset | None] = relationship(
        "MediaAsset", back_populates="timeline_clips"
    )
