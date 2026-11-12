"""Creative project model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models import (
        Character,
        ClipCandidate,
        EnvironmentReference,
        MediaAsset,
        ProcessingJob,
        Publication,
        Scene,
        Timeline,
        Transcript,
        User,
    )


class Project(TimestampMixin, Base):
    """User-owned creative project."""

    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    story_idea: Mapped[str | None] = mapped_column(Text)
    story_outline: Mapped[str | None] = mapped_column(Text)
    script_text: Mapped[str | None] = mapped_column(Text)
    visual_settings: Mapped[dict[str, object] | None] = mapped_column(JSON)

    owner: Mapped[User] = relationship("User", back_populates="projects")
    media_assets: Mapped[list[MediaAsset]] = relationship("MediaAsset", back_populates="project")
    processing_jobs: Mapped[list[ProcessingJob]] = relationship(
        "ProcessingJob", back_populates="project"
    )
    timeline: Mapped[Timeline | None] = relationship(
        "Timeline", back_populates="project", cascade="all, delete-orphan", uselist=False
    )
    transcripts: Mapped[list[Transcript]] = relationship(
        "Transcript", back_populates="project", cascade="all, delete-orphan"
    )
    characters: Mapped[list[Character]] = relationship(
        "Character", back_populates="project", cascade="all, delete-orphan"
    )
    scenes: Mapped[list[Scene]] = relationship(
        "Scene", back_populates="project", cascade="all, delete-orphan"
    )
    environments: Mapped[list[EnvironmentReference]] = relationship(
        "EnvironmentReference", back_populates="project", cascade="all, delete-orphan"
    )
    clip_candidates: Mapped[list[ClipCandidate]] = relationship(
        "ClipCandidate", back_populates="project", cascade="all, delete-orphan"
    )
    publications: Mapped[list[Publication]] = relationship(
        "Publication", back_populates="project", cascade="all, delete-orphan"
    )
