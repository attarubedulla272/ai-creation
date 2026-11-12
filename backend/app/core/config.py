"""Environment-backed application settings."""

from pathlib import Path
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings loaded from environment variables and an optional local .env file."""

    app_name: str = "AI Creator Studio API"
    environment: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3101",
            "http://127.0.0.1:3101",
        ]
    )
    database_url: str | None = None
    jwt_secret_key: SecretStr | None = None
    access_token_expire_minutes: int = Field(default=30, ge=5, le=1440)
    max_upload_size_bytes: int = Field(default=2 * 1024**3, ge=1, le=20 * 1024**3)
    redis_url: str = "redis://localhost:6379/0"
    storage_path: Path = Path("../storage")
    voice_transcription_provider: Literal["auto", "mlx-whisper", "mlx-audio-plus"] = "auto"
    mlx_whisper_model: str = "mlx-community/whisper-tiny"
    mlx_audio_worker_python: Path | None = None
    mlx_audio_model_path: Path | None = None
    mlx_audio_worker_timeout_seconds: int = Field(default=1800, ge=1, le=7200)
    translation_worker_url: AnyHttpUrl | None = None
    translation_worker_api_token: SecretStr | None = None
    translation_worker_timeout_seconds: int = Field(default=1800, ge=1, le=7200)
    enable_mock_scene_preview: bool = False
    generation_worker_url: AnyHttpUrl | None = None
    generation_worker_api_token: SecretStr | None = None
    generation_worker_timeout_seconds: int = Field(default=30, ge=1, le=300)
    generation_worker_max_output_bytes: int = Field(default=2 * 1024**3, ge=1, le=20 * 1024**3)
    generation_model_name: str = "Operator-configured self-hosted model"
    generation_model_version: str = "operator-managed"
    generation_model_repository: str | None = None
    generation_model_license: str = "Not declared; operator must verify the model card and weights."
    generation_model_commercial_use_permitted: bool = False
    generation_model_gpu_requirement: str = (
        "Separate GPU worker required; hardware depends on the selected model and output settings."
    )
    generation_model_supported_languages: list[str] = Field(default_factory=list)
    generation_model_generation_modes: list[Literal["text_to_video", "image_to_video"]] = Field(
        default_factory=lambda: ["text_to_video", "image_to_video"]
    )
    generation_model_installation_instructions: str = (
        "Install weights manually on the external worker after verifying source, license, "
        "commercial-use terms, hardware needs, and attribution. Automatic downloads are disabled."
    )
    public_api_base_url: AnyHttpUrl = "http://localhost:8000"
    youtube_oauth_client_id: str | None = None
    youtube_oauth_client_secret: SecretStr | None = None
    youtube_oauth_redirect_uri: AnyHttpUrl | None = None
    youtube_oauth_frontend_return_url: AnyHttpUrl = "http://localhost:3000/seo-publish"
    youtube_token_encryption_key: SecretStr | None = None

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.jwt_secret_key:
            secret = self.jwt_secret_key.get_secret_value()
            if len(secret) < 32:
                raise ValueError("JWT_SECRET_KEY must contain at least 32 characters.")
            if "replace_with" in secret.lower():
                raise ValueError("Replace the JWT_SECRET_KEY placeholder with a random secret.")
        if self.environment == "production" and not self.jwt_secret_key:
            raise ValueError("JWT_SECRET_KEY is required in production.")
        youtube_oauth_values = (
            self.youtube_oauth_client_id,
            self.youtube_oauth_client_secret,
            self.youtube_oauth_redirect_uri,
        )
        if any(youtube_oauth_values) and not all(youtube_oauth_values):
            raise ValueError(
                "YouTube OAuth client ID, client secret, and redirect URI must all be configured."
            )
        if all(youtube_oauth_values) and not self.youtube_token_encryption_key:
            raise ValueError(
                "YOUTUBE_TOKEN_ENCRYPTION_KEY is required when YouTube OAuth is configured."
            )
        if self.youtube_oauth_redirect_uri:
            redirect_uri = str(self.youtube_oauth_redirect_uri)
            if self.environment == "production" and not redirect_uri.startswith("https://"):
                raise ValueError("YouTube OAuth redirect URI must use HTTPS in production.")
            if self.environment != "production" and not (
                redirect_uri.startswith("https://")
                or "://localhost" in redirect_uri
                or "://127.0.0.1" in redirect_uri
            ):
                raise ValueError(
                    "YouTube OAuth redirect URI must use HTTPS or a loopback host in development."
                )
        if (
            self.environment == "production"
            and all(youtube_oauth_values)
            and not str(self.youtube_oauth_frontend_return_url).startswith("https://")
        ):
            raise ValueError("YouTube OAuth frontend return URL must use HTTPS in production.")
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )
