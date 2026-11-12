"""User account model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models import (
        MediaAsset,
        ProcessingJob,
        Project,
        Publication,
        VoiceConsent,
        VoiceProfile,
    )


class User(TimestampMixin, Base):
    """Registered studio account."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    projects: Mapped[list[Project]] = relationship(
        "Project", back_populates="owner", cascade="all, delete-orphan"
    )
    media_assets: Mapped[list[MediaAsset]] = relationship(
        "MediaAsset", back_populates="owner", cascade="all, delete-orphan"
    )
    processing_jobs: Mapped[list[ProcessingJob]] = relationship(
        "ProcessingJob", back_populates="owner", cascade="all, delete-orphan"
    )
    voice_profiles: Mapped[list[VoiceProfile]] = relationship(
        "VoiceProfile", back_populates="owner", cascade="all, delete-orphan"
    )
    voice_consents: Mapped[list[VoiceConsent]] = relationship(
        "VoiceConsent", back_populates="owner", cascade="all, delete-orphan"
    )
    publications: Mapped[list[Publication]] = relationship(
        "Publication", back_populates="owner", cascade="all, delete-orphan"
    )
