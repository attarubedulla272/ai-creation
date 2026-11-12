"""OAuth state and encrypted YouTube channel connection records."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class YouTubeConnection(TimestampMixin, Base):
    """A user's YouTube channel connection; provider tokens remain encrypted."""

    __tablename__ = "youtube_connections"
    __table_args__ = (
        UniqueConstraint("owner_id", "channel_id", name="uq_youtube_connection_owner_channel"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[str] = mapped_column(String(128), nullable=False)
    channel_title: Mapped[str] = mapped_column(String(255), nullable=False)
    channel_custom_url: Mapped[str | None] = mapped_column(String(255))
    refresh_token_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    granted_scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="connected", nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(255))


class YouTubeOAuthState(TimestampMixin, Base):
    """Single-use OAuth CSRF state and PKCE verifier bound to an owner."""

    __tablename__ = "youtube_oauth_states"
    __table_args__ = (
        UniqueConstraint("state_hash", name="uq_youtube_oauth_state_hash"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_verifier_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    expected_channel_id: Mapped[str | None] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
