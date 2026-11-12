"""Project request and response schemas."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProjectCreate(BaseModel):
    """Project fields accepted from the current user."""

    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=10_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Project name cannot be blank.")
        return normalized


class ProjectPublic(BaseModel):
    """Project response without internal ownership data."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    description: str | None
    status: Literal["draft", "active", "completed"]
    created_at: datetime
    updated_at: datetime
