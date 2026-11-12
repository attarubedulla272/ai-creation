"""Background processing job model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models import Project, User


class ProcessingJob(TimestampMixin, Base):
    """Track an asynchronous job without coupling to a specific worker."""

    __tablename__ = "processing_jobs"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    owner_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", nullable=False)
    progress: Mapped[int] = mapped_column(default=0, nullable=False)
    input_data: Mapped[dict[str, object] | None] = mapped_column(JSON)
    output_data: Mapped[dict[str, object] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(String(1000))
    model_name: Mapped[str | None] = mapped_column(String(160))
    model_version: Mapped[str | None] = mapped_column(String(120))
    model_license: Mapped[str | None] = mapped_column(String(255))
    commercial_use_permitted: Mapped[bool | None] = mapped_column(Boolean)
    generation_mode: Mapped[str | None] = mapped_column(String(32))
    generation_settings: Mapped[dict[str, object] | None] = mapped_column(JSON)
    worker_job_id: Mapped[str | None] = mapped_column(String(255))
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    owner: Mapped[User] = relationship("User", back_populates="processing_jobs")
    project: Mapped[Project | None] = relationship("Project", back_populates="processing_jobs")
