"""User-facing Pydantic schemas."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    """Fields accepted when registering an account."""

    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    full_name: str | None = Field(default=None, min_length=1, max_length=120)


class UserPublic(BaseModel):
    """Safe public representation of an account."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    full_name: str | None
    is_active: bool


class TokenResponse(BaseModel):
    """Bearer access token response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginRequest(BaseModel):
    """JSON login request."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
