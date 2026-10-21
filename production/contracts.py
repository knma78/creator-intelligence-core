from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


PRODUCTION_MANIFEST_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class RenderProfile:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    video_codec: str = "auto"
    audio_loudness_lufs: float = -16.0
    platform: str = "general"

    def validate(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Render dimensions must be positive.")
        if self.fps not in {24, 25, 30, 50, 60}:
            raise ValueError(f"Unsupported render FPS: {self.fps}")


@dataclass(frozen=True)
class TimelineSegment:
    segment_id: str
    start_seconds: float
    end_seconds: float
    purpose: str = ""
    text: str = ""
    asset_roles: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.segment_id.strip():
            raise ValueError("Timeline segment ID cannot be empty.")
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise ValueError(
                f"Invalid timeline range for {self.segment_id}: "
                f"{self.start_seconds}-{self.end_seconds}"
            )


@dataclass(frozen=True)
class ProductionAsset:
    role: str
    source_path: str
    packaged_path: str | None = None
    media_type: str = "document"
    required: bool = False

    def validate(self) -> None:
        if not self.role.strip():
            raise ValueError("Production asset role cannot be empty.")
        if not self.source_path.strip():
            raise ValueError(f"Source path is missing for asset {self.role}.")


@dataclass(frozen=True)
class ProductionManifest:
    job_id: str
    source_video_id: str
    title: str
    engine: str = "ffmpeg"
    render_profile: RenderProfile = field(default_factory=RenderProfile)
    assets: tuple[ProductionAsset, ...] = ()
    timeline: tuple[TimelineSegment, ...] = ()
    notes: tuple[str, ...] = ()
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    schema_version: str = PRODUCTION_MANIFEST_SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != PRODUCTION_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported production manifest schema: {self.schema_version}"
            )
        if not self.job_id.strip() or not self.source_video_id.strip():
            raise ValueError("Production job and source video IDs are required.")
        if self.engine not in {"ffmpeg", "hyperframes"}:
            raise ValueError(f"Unsupported production engine: {self.engine}")
        self.render_profile.validate()
        for asset in self.assets:
            asset.validate()
        for segment in self.timeline:
            segment.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ProductionManifest":
        manifest = cls(
            schema_version=str(
                payload.get(
                    "schema_version",
                    PRODUCTION_MANIFEST_SCHEMA_VERSION,
                )
            ),
            job_id=str(payload["job_id"]),
            source_video_id=str(payload["source_video_id"]),
            title=str(payload.get("title") or payload["source_video_id"]),
            engine=str(payload.get("engine", "ffmpeg")),
            render_profile=RenderProfile(**payload.get("render_profile", {})),
            assets=tuple(
                ProductionAsset(**asset) for asset in payload.get("assets", [])
            ),
            timeline=tuple(
                TimelineSegment(
                    **{
                        **segment,
                        "asset_roles": tuple(segment.get("asset_roles", ())),
                    }
                )
                for segment in payload.get("timeline", [])
            ),
            notes=tuple(str(note) for note in payload.get("notes", [])),
            created_at=str(
                payload.get("created_at")
                or datetime.now(timezone.utc).isoformat()
            ),
        )
        manifest.validate()
        return manifest
