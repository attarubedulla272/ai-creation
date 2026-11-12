"""Persisted dubbing plans and their manually editable segment data."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class DubbingProject(TimestampMixin, Base):
    """A target-language plan; it does not imply generated speech."""

    __tablename__ = "dubbing_projects"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    transcript_id: Mapped[UUID] = mapped_column(
        ForeignKey("transcripts.id", ondelete="CASCADE"), index=True
    )
    target_language: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="draft", nullable=False)
    segments_data: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    glossary: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False, default=list)
