"""Provider contracts and adapters for an independent self-hosted GPU worker."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.schemas.content import (
    GenerationModelRegistryEntry,
    SceneProviderRequest,
    SceneWorkerJobStatus,
)

MOCK_MODEL_ID = "mock-preview"
OPERATOR_MODEL_ID = "operator-configured"


class SceneGenerationProvider(Protocol):
    """Control-plane contract implemented by any separate scene GPU worker."""

    name: str
    preview_only: bool

    async def submit_scene(self, job_id: str, request: SceneProviderRequest) -> str: ...

    async def get_job_status(self, worker_job_id: str) -> SceneWorkerJobStatus: ...

    async def cancel_job(self, worker_job_id: str) -> None: ...

    def download_output(self, worker_job_id: str) -> AsyncIterable[bytes]: ...


def generation_model_registry(
    settings: Settings | None = None,
) -> list[GenerationModelRegistryEntry]:
    """Return model metadata without downloading or installing any weights."""

    return [
        GenerationModelRegistryEntry(
            id=OPERATOR_MODEL_ID,
            model_name=(
                settings.generation_model_name
                if settings
                else "Operator-configured self-hosted model"
            ),
            model_version=settings.generation_model_version if settings else "operator-managed",
            repository=settings.generation_model_repository if settings else None,
            model_license=(
                settings.generation_model_license
                if settings
                else "Not declared; operator must verify the model card and weights."
            ),
            commercial_use_permitted=(
                settings.generation_model_commercial_use_permitted if settings else False
            ),
            gpu_requirement=settings.generation_model_gpu_requirement
            if settings
            else "External GPU worker; requirements depend on the chosen model.",
            supported_languages=settings.generation_model_supported_languages if settings else [],
            generation_modes=settings.generation_model_generation_modes
            if settings
            else ["text_to_video", "image_to_video"],
            installation_instructions=settings.generation_model_installation_instructions
            if settings
            else "Install model weights manually on the external worker after verifying its terms.",
            availability="operator_configured",
        ),
        GenerationModelRegistryEntry(
            id=MOCK_MODEL_ID,
            model_name="Mock text-only worker",
            model_version="n/a",
            repository=None,
            model_license="No model weights; development adapter only.",
            commercial_use_permitted=None,
            gpu_requirement="None; returns job lifecycle metadata only.",
            supported_languages=[],
            generation_modes=["text_to_video", "image_to_video"],
            installation_instructions=(
                "Enable ENABLE_MOCK_SCENE_PREVIEW in development. It creates no image or video."
            ),
            availability="mock",
        ),
    ]


@dataclass
class MockSceneGenerationProvider:
    """Simulate the worker lifecycle without producing image or video media."""

    name: str = "mock-preview"
    preview_only: bool = True
    _titles: dict[str, str] = field(default_factory=dict)
    requests: dict[str, SceneProviderRequest] = field(default_factory=dict)

    async def submit_scene(self, job_id: str, request: SceneProviderRequest) -> str:
        await asyncio.sleep(0)
        self._titles[job_id] = request.title
        self.requests[job_id] = request
        return job_id

    async def get_job_status(self, worker_job_id: str) -> SceneWorkerJobStatus:
        title = self._titles.get(worker_job_id)
        if title is None:
            return SceneWorkerJobStatus(
                status="failed", progress=0, error_message="Mock job not found."
            )
        return SceneWorkerJobStatus(
            status="completed",
            progress=100,
            preview_only=True,
            preview_label=(
                f"MOCK GENERATED PREVIEW ONLY — {title}. No image or video was generated."
            ),
            output_metadata={"worker": self.name, "media_generated": False},
        )

    async def cancel_job(self, worker_job_id: str) -> None:
        self._titles.pop(worker_job_id, None)
        self.requests.pop(worker_job_id, None)

    async def download_output(self, worker_job_id: str) -> AsyncIterable[bytes]:
        if False:
            yield b""
        raise RuntimeError(f"Mock worker job {worker_job_id} has no generated output.")


@dataclass(frozen=True)
class SelfHostedHTTPSceneGenerationProvider:
    """HTTP control-plane adapter for a separately deployed GPU worker."""

    base_url: str
    api_token: str | None = None
    timeout_seconds: int = 30
    max_output_bytes: int = 2 * 1024**3
    transport: httpx.AsyncBaseTransport | None = field(default=None, repr=False, compare=False)
    name: str = "self-hosted-gpu-worker"
    preview_only: bool = False

    def _client(self) -> httpx.AsyncClient:
        headers = {"Authorization": f"Bearer {self.api_token}"} if self.api_token else {}
        return httpx.AsyncClient(
            base_url=self.base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(self.timeout_seconds),
            transport=self.transport,
        )

    @staticmethod
    def _job_path(worker_job_id: str) -> str:
        return f"/api/v1/jobs/{quote(worker_job_id, safe='')}"

    async def submit_scene(self, job_id: str, request: SceneProviderRequest) -> str:
        async with self._client() as client:
            response = await client.post(
                "/api/v1/jobs",
                json={"client_job_id": job_id, "scene": request.model_dump(mode="json")},
            )
            response.raise_for_status()
            payload = response.json()
        worker_job_id = payload.get("job_id")
        if not isinstance(worker_job_id, str) or not worker_job_id:
            raise RuntimeError("GPU worker returned an invalid job ID.")
        return worker_job_id

    async def get_job_status(self, worker_job_id: str) -> SceneWorkerJobStatus:
        async with self._client() as client:
            response = await client.get(self._job_path(worker_job_id))
            response.raise_for_status()
            return SceneWorkerJobStatus.model_validate(response.json())

    async def cancel_job(self, worker_job_id: str) -> None:
        async with self._client() as client:
            response = await client.post(f"{self._job_path(worker_job_id)}/cancel")
            response.raise_for_status()

    async def download_output(self, worker_job_id: str) -> AsyncIterable[bytes]:
        async with (
            self._client() as client,
            client.stream("GET", f"{self._job_path(worker_job_id)}/output") as response,
        ):
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type != "video/mp4":
                raise RuntimeError("GPU worker output must be an MP4 video.")
            total = 0
            async for chunk in response.aiter_bytes(1024 * 1024):
                total += len(chunk)
                if total > self.max_output_bytes:
                    raise RuntimeError("GPU worker output exceeds the configured size limit.")
                yield chunk


def create_scene_generation_provider(settings: Settings) -> SceneGenerationProvider | None:
    """Use a configured self-hosted worker, or an explicitly enabled development mock."""

    if settings.generation_worker_url:
        token = (
            settings.generation_worker_api_token.get_secret_value()
            if settings.generation_worker_api_token
            else None
        )
        return SelfHostedHTTPSceneGenerationProvider(
            base_url=str(settings.generation_worker_url),
            api_token=token,
            timeout_seconds=settings.generation_worker_timeout_seconds,
            max_output_bytes=settings.generation_worker_max_output_bytes,
        )
    if settings.environment == "development" and settings.enable_mock_scene_preview:
        return MockSceneGenerationProvider()
    return None
