"""Character consistency and source-reference models."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models import MediaAsset, Project


class Character(TimestampMixin, Base):
    """Character description scoped to a project."""

    __tablename__ = "characters"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    identity_description: Mapped[str | None] = mapped_column(Text)
    outfit_settings: Mapped[dict[str, object] | None] = mapped_column(JSON)
    visual_traits: Mapped[dict[str, object] | None] = mapped_column(JSON)

    project: Mapped[Project] = relationship("Project", back_populates="characters")
    references: Mapped[list[CharacterReference]] = relationship(
        "CharacterReference", back_populates="character", cascade="all, delete-orphan"
    )


class CharacterReference(TimestampMixin, Base):
    """Reference image or note linked to a project character."""

    __tablename__ = "character_references"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    character_id: Mapped[UUID] = mapped_column(
        ForeignKey("characters.id", ondelete="CASCADE"), index=True
    )
    media_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    reference_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    character: Mapped[Character] = relationship("Character", back_populates="references")
    media_asset: Mapped[MediaAsset | None] = relationship(
        "MediaAsset", back_populates="character_references"
    )
