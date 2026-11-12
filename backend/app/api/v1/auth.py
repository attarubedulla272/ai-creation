"""Registration, login, and current-user endpoints."""

from argon2 import PasswordHasher
from fastapi import APIRouter, HTTPException, Request, status
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentUser, SessionDependency
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user import LoginRequest, TokenResponse, UserCreate, UserPublic

router = APIRouter(prefix="/auth", tags=["authentication"])
dummy_password_hash = PasswordHasher().hash("not-a-real-user-password")


def require_signing_key(request: Request) -> SecretStr:
    """Return the configured JWT signing key or fail explicitly."""

    secret = request.app.state.settings.jwt_secret_key
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication is not configured. Set JWT_SECRET_KEY.",
        )
    return secret


@router.post("/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, request: Request, session: SessionDependency) -> User:
    """Create an account without ever storing the supplied plaintext password."""

    require_signing_key(request)
    email = str(payload.email).strip().lower()
    existing_user = await session.scalar(select(User.id).where(User.email == email))
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email is already registered."
        )

    user = User(
        email=email,
        full_name=payload.full_name.strip() if payload.full_name else None,
        password_hash=hash_password(payload.password),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email is already registered."
        ) from None
    await session.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    session: SessionDependency,
) -> TokenResponse:
    """Verify credentials and issue a short-lived signed bearer token."""

    settings = request.app.state.settings
    secret = require_signing_key(request)
    email = str(payload.email).strip().lower()
    user = await session.scalar(select(User).where(User.email == email))
    stored_hash = user.password_hash if user is not None else dummy_password_hash
    password_is_valid = verify_password(payload.password, stored_hash)

    if user is None or not password_is_valid or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token, expires_in = create_access_token(
        user.id,
        secret,
        settings.access_token_expire_minutes,
    )
    return TokenResponse(access_token=access_token, expires_in=expires_in)


@router.get("/me", response_model=UserPublic)
async def read_current_user(user: CurrentUser) -> User:
    """Return the identity associated with a valid access token."""

    return user
