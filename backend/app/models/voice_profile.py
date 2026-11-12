"""Voice profile and explicit consent record models."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models import User


class VoiceConsent(TimestampMixin, Base):
    """Record an affirmative authorization for a voice-related operation."""

    __tablename__ = "voice_consents"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    consent_method: Mapped[str] = mapped_column(String(64), nullable=False)
    consent_text_version: Mapped[str] = mapped_column(String(64), nullable=False)
    authorization_basis: Mapped[str] = mapped_column(
        String(32), default="self_attestation", nullable=False
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_reference: Mapped[str | None] = mapped_column(String(512))

    owner: Mapped[User] = relationship("User", back_populates="voice_consents")
    voice_profiles: Mapped[list[VoiceProfile]] = relationship(
        "VoiceProfile", back_populates="consent"
    )


class VoiceProfile(TimestampMixin, Base):
    """User-authorized voice profile metadata; no voice model is implied."""

    __tablename__ = "voice_profiles"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    consent_id: Mapped[UUID] = mapped_column(
        ForeignKey("voice_consents.id", ondelete="RESTRICT"), index=True
    )
    reference_asset_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media_assets.id", ondelete="SET NULL"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    language: Mapped[str | None] = mapped_column(String(32))
    provider: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(24), default="reference_only", nullable=False)

    owner: Mapped[User] = relationship("User", back_populates="voice_profiles")
    consent: Mapped[VoiceConsent] = relationship("VoiceConsent", back_populates="voice_profiles")
