"""Scene and shot planning models."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models import EnvironmentReference, MediaAsset, ProcessingJob, Project


class Scene(TimestampMixin, Base):
    """Ordered scene in a project plan."""

    __tablename__ = "scenes"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    visual_style: Mapped[str | None] = mapped_column(String(120))
    scene_prompt: Mapped[str | None] = mapped_column(Text)
    duration_seconds: Mapped[float] = mapped_column(Float, default=5, nullable=False)
    camera_movement: Mapped[str | None] = mapped_column(String(64))
    lighting: Mapped[str | None] = mapped_column(String(120))
    color_palette: Mapped[str | None] = mapped_column(String(160))
    environment_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("environment_references.id", ondelete="SET NULL"), index=True
    )
    character_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    first_frame_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    last_frame_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    generated_media_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    generation_status: Mapped[str] = mapped_column(
        String(24), default="not_started", nullable=False
    )
    generation_job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="SET NULL"), index=True
    )
    generated_preview_label: Mapped[str | None] = mapped_column(String(255))
    generation_provider: Mapped[str | None] = mapped_column(String(100))
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    continuity_notes: Mapped[str | None] = mapped_column(Text)

    project: Mapped[Project] = relationship("Project", back_populates="scenes")
    environment: Mapped[EnvironmentReference | None] = relationship("EnvironmentReference")
    generation_job: Mapped[ProcessingJob | None] = relationship("ProcessingJob")
    first_frame_asset: Mapped[MediaAsset | None] = relationship(
        "MediaAsset", foreign_keys=[first_frame_asset_id]
    )
    last_frame_asset: Mapped[MediaAsset | None] = relationship(
        "MediaAsset", foreign_keys=[last_frame_asset_id]
    )
    generated_media_asset: Mapped[MediaAsset | None] = relationship(
        "MediaAsset", foreign_keys=[generated_media_asset_id]
    )
    shots: Mapped[list[SceneShot]] = relationship(
        "SceneShot",
        back_populates="scene",
        cascade="all, delete-orphan",
        order_by="SceneShot.order_index",
    )


class SceneShot(TimestampMixin, Base):
    """Shot outline belonging to a scene."""

    __tablename__ = "scene_shots"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    scene_id: Mapped[UUID] = mapped_column(ForeignKey("scenes.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    duration_seconds: Mapped[float | None]
    media_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    shot_prompt: Mapped[str | None] = mapped_column(Text)
    camera_movement: Mapped[str | None] = mapped_column(String(64))
    first_frame_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    last_frame_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )

    scene: Mapped[Scene] = relationship("Scene", back_populates="shots")
    media_asset: Mapped[MediaAsset | None] = relationship(
        "MediaAsset", foreign_keys=[media_asset_id]
    )


class EnvironmentReference(TimestampMixin, Base):
    """Project-scoped reusable environment and optional owned image reference."""

    __tablename__ = "environment_references"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    visual_traits: Mapped[dict[str, object] | None] = mapped_column(JSON)
    reference_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )

    project: Mapped[Project] = relationship("Project", back_populates="environments")
    reference_asset: Mapped[MediaAsset | None] = relationship("MediaAsset")
