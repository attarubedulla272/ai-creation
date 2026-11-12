"""Provider contracts for optional Smart Clipper visual analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class FaceTrackSample:
    """Normalized face-center position at a source-video timestamp."""

    time_seconds: float
    center_x: float
    center_y: float


class FaceTrackingProvider(Protocol):
    """Optional face-aware crop tracker; no implementation is enabled by default."""

    name: str

    async def track_crop(
        self,
        source_path: Path,
        start_seconds: float,
        end_seconds: float,
        aspect_ratio: str,
    ) -> list[FaceTrackSample]: ...
