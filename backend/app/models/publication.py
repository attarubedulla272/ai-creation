"""Publication preparation metadata model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models import ClipCandidate, MediaAsset, Project, User


class Publication(TimestampMixin, Base):
    """A versioned, owner-scoped release package and calendar entry."""

    __tablename__ = "publications"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str | None] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_id: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, object] | None] = mapped_column("metadata", JSON)
    media_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    clip_candidate_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("clip_candidates.id", ondelete="SET NULL"), index=True
    )
    thumbnail_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    youtube_status: Mapped[str | None] = mapped_column(String(32))
    youtube_privacy_status: Mapped[str | None] = mapped_column(String(16))
    youtube_url: Mapped[str | None] = mapped_column(String(512))

    owner: Mapped[User] = relationship("User", back_populates="publications")
    project: Mapped[Project] = relationship("Project", back_populates="publications")
    media_asset: Mapped[MediaAsset | None] = relationship(
        "MediaAsset", foreign_keys=[media_asset_id]
    )
    thumbnail_asset: Mapped[MediaAsset | None] = relationship(
        "MediaAsset", foreign_keys=[thumbnail_asset_id]
    )
    clip_candidate: Mapped[ClipCandidate | None] = relationship("ClipCandidate")
    revisions: Mapped[list[PublicationRevision]] = relationship(
        "PublicationRevision",
        back_populates="publication",
        cascade="all, delete-orphan",
        order_by="PublicationRevision.version",
    )


class PublicationRevision(TimestampMixin, Base):
    """Immutable metadata snapshot created when a publication draft is changed."""

    __tablename__ = "publication_revisions"
    __table_args__ = (
        UniqueConstraint("publication_id", "version", name="uq_publication_revision_version"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    publication_id: Mapped[UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)

    publication: Mapped[Publication] = relationship("Publication", back_populates="revisions")
