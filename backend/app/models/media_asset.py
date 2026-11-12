"""User media metadata model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, BigInteger, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models import (
        CharacterReference,
        ClipCandidate,
        Project,
        TimelineClip,
        Transcript,
        User,
    )


class MediaAsset(TimestampMixin, Base):
    """A user-owned media asset; storage_key is application-generated, not a path."""

    __tablename__ = "media_assets"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    media_type: Mapped[str] = mapped_column(String(24), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    duration_seconds: Mapped[float | None]
    metadata_json: Mapped[dict[str, object] | None] = mapped_column("metadata", JSON)

    owner: Mapped[User] = relationship("User", back_populates="media_assets")
    project: Mapped[Project | None] = relationship("Project", back_populates="media_assets")
    timeline_clips: Mapped[list[TimelineClip]] = relationship(
        "TimelineClip", back_populates="media_asset"
    )
    transcripts: Mapped[list[Transcript]] = relationship("Transcript", back_populates="media_asset")
    character_references: Mapped[list[CharacterReference]] = relationship(
        "CharacterReference", back_populates="media_asset"
    )
    clip_candidates: Mapped[list[ClipCandidate]] = relationship(
        "ClipCandidate", back_populates="source_asset"
    )
