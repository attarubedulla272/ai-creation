"""Password hashing and short-lived bearer-token helpers."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from pydantic import SecretStr

password_hasher = PasswordHasher()
TOKEN_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """Hash a plaintext password using the Argon2id defaults."""

    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Compare a supplied password to its Argon2 hash."""

    try:
        return password_hasher.verify(password_hash, password)
    except VerificationError:
        return False


def create_access_token(
    subject: UUID,
    secret: SecretStr,
    expires_in_minutes: int,
) -> tuple[str, int]:
    """Create a signed access token with a bounded lifetime."""

    expires_in = int(timedelta(minutes=expires_in_minutes).total_seconds())
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(subject),
            "iat": now,
            "exp": now + timedelta(seconds=expires_in),
            "jti": str(uuid4()),
        },
        secret.get_secret_value(),
        algorithm=TOKEN_ALGORITHM,
    )
    return token, expires_in


def decode_access_token(token: str, secret: SecretStr) -> UUID:
    """Validate a bearer token and return its user identifier."""

    payload = jwt.decode(
        token,
        secret.get_secret_value(),
        algorithms=[TOKEN_ALGORITHM],
        options={"require": ["sub", "exp", "iat", "jti"]},
    )
    return UUID(payload["sub"])
