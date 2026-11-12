"""API, authentication, and ownership tests."""

import asyncio
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.core.config import Settings
from app.core.security import verify_password
from app.main import create_app
from app.models.user import User


def register(client: TestClient, email: str, password: str = "correct-horse-battery-41") -> dict:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Studio User"},
    )
    assert response.status_code == 201
    return response.json()


def login(client: TestClient, email: str, password: str = "correct-horse-battery-41") -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    return body["access_token"]


def test_health_and_openapi_are_available(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/v1/health").json() == {"status": "ok"}

    docs = client.get("/docs")
    openapi = client.get("/openapi.json").json()

    assert docs.status_code == 200
    assert "/api/v1/auth/register" in openapi["paths"]
    assert "/api/v1/projects/{project_id}" in openapi["paths"]


def test_registration_hashes_password_and_login_returns_bearer_token(client: TestClient) -> None:
    email = "creator@example.com"
    password = "correct-horse-battery-41"
    user_body = register(client, email, password)

    assert "password" not in user_body
    assert "password_hash" not in user_body
    assert UUID(user_body["id"])

    session_factory = client.app.state.session_factory

    async def read_user() -> User:
        async with session_factory() as session:
            return await session.scalar(select(User).where(User.email == email))

    user = asyncio.run(read_user())
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")
    assert password not in user.password_hash
    assert verify_password(password, user.password_hash)

    token = login(client, email, password)
    current_user = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert current_user.status_code == 200
    assert current_user.json()["email"] == email


def test_login_rejects_wrong_password_and_protected_route_requires_token(
    client: TestClient,
) -> None:
    register(client, "private@example.com")

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": "private@example.com", "password": "incorrect-password-123"},
    )
    unauthenticated = client.get("/api/v1/projects")

    assert wrong_password.status_code == 401
    assert wrong_password.json()["error"]["message"] == "Incorrect email or password."
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["www-authenticate"] == "Bearer"


def test_projects_are_scoped_to_the_authenticated_owner(client: TestClient) -> None:
    owner_email = "owner@example.com"
    other_email = "other@example.com"
    register(client, owner_email)
    owner_token = login(client, owner_email)
    created = client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"name": "  A local project  ", "description": "First draft"},
    )
    assert created.status_code == 201
    assert created.json()["name"] == "A local project"
    assert "owner_id" not in created.json()

    project_id = created.json()["id"]
    listed = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {owner_token}"})
    retrieved = client.get(
        f"/api/v1/projects/{project_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert [project["id"] for project in listed.json()] == [project_id]
    assert retrieved.status_code == 200

    register(client, other_email)
    other_token = login(client, other_email)
    hidden = client.get(
        f"/api/v1/projects/{project_id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    other_list = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {other_token}"})

    assert hidden.status_code == 404
    assert other_list.json() == []


def test_request_validation_errors_are_structured_and_do_not_echo_password(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "secret-too-short-77"},
    )

    assert response.status_code == 422
    assert response.headers["x-request-id"]
    body = response.json()
    assert body["error"]["code"] == "validation_error"
    assert body["error"]["request_id"] == response.headers["x-request-id"]
    assert "details" in body["error"]
    assert "secret-too-short-77" not in response.text


def test_duplicate_registration_conflicts_and_missing_database_is_explicit(
    client: TestClient,
) -> None:
    register(client, "duplicate@example.com")
    duplicate = client.post(
        "/api/v1/auth/register",
        json={"email": "duplicate@example.com", "password": "another-correct-password-31"},
    )

    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "http_error"

    unconfigured = TestClient(
        create_app(Settings(environment="test", database_url=None, jwt_secret_key=None))
    )
    unavailable = unconfigured.post(
        "/api/v1/auth/register",
        json={"email": "offline@example.com", "password": "correct-horse-battery-41"},
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "database_not_configured"

    missing_key = TestClient(
        create_app(
            Settings(
                database_url=f"sqlite+aiosqlite:///{client.app.state.engine.url.database}",
                environment="test",
                jwt_secret_key=None,
            )
        )
    )
    not_configured = missing_key.post(
        "/api/v1/auth/register",
        json={"email": "no-key@example.com", "password": "correct-horse-battery-41"},
    )
    assert not_configured.status_code == 503
    assert not_configured.json()["error"]["message"].startswith("Authentication is not configured.")


def test_cors_is_restricted_to_configured_frontend_origin(client: TestClient) -> None:
    allowed = client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    denied = client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": "https://example.test",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "access-control-allow-origin" not in denied.headers


def test_jwt_placeholder_secret_is_rejected() -> None:
    try:
        Settings(
            jwt_secret_key=SecretStr("replace_with_a_random_secret_at_least_32_characters_long"),
            environment="test",
        )
    except ValueError as error:
        assert "placeholder" in str(error)
    else:
        raise AssertionError("JWT placeholder secret should not be accepted")
