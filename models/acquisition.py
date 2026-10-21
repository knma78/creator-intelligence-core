from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .core import Video

ACQUISITION_SCHEMA_VERSION = "1.0"


class LoginState(str, Enum):
    NOT_REQUIRED = "not_required"
    AUTHENTICATED = "authenticated"
    NOT_CONFIGURED = "not_configured"
    UNKNOWN = "unknown"


class EntitlementState(str, Enum):
    NOT_REQUIRED = "not_required"
    ALLOWED = "allowed"
    DENIED = "denied"
    UNKNOWN = "unknown"


class MediaAvailability(str, Enum):
    LOCAL_MEDIA = "local_media"
    PLATFORM_SUBTITLE = "platform_subtitle"
    DIRECT_STREAM = "direct_stream"
    PLAYBACK_AUDIO = "playback_audio"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class AcquisitionStrategy(str, Enum):
    LOCAL_FILE = "local_file"
    PLATFORM_SUBTITLE = "platform_subtitle"
    DIRECT_DOWNLOAD = "direct_download"
    BROWSER_PLAYBACK_CAPTURE = "browser_playback_capture"
    MANUAL_IMPORT = "manual_import"
    PLATFORM_AUTO = "platform_auto"


@dataclass(frozen=True)
class AccessAssessment:
    source: str
    platform: str
    login_state: LoginState
    entitlement_state: EntitlementState
    media_availability: MediaAvailability
    can_attempt: bool
    reason: str
    account_tier: str | None = None
    account_valid_until: str | None = None
    content_requirement: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    assessed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "login_state": self.login_state.value,
            "entitlement_state": self.entitlement_state.value,
            "media_availability": self.media_availability.value,
        }


@dataclass(frozen=True)
class AcquisitionPlan:
    primary_strategy: AcquisitionStrategy
    fallback_strategies: tuple[AcquisitionStrategy, ...] = ()
    requires_browser: bool = False
    respects_platform_controls: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_strategy": self.primary_strategy.value,
            "fallback_strategies": [
                strategy.value for strategy in self.fallback_strategies
            ],
            "requires_browser": self.requires_browser,
            "respects_platform_controls": self.respects_platform_controls,
        }


@dataclass(frozen=True)
class MediaArtifact:
    kind: str
    path: Path
    origin: str
    available: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "origin": self.origin,
            "available": self.available,
        }


@dataclass(frozen=True)
class AcquisitionResult:
    video: Video
    assessment: AccessAssessment
    plan: AcquisitionPlan
    selected_strategy: AcquisitionStrategy
    artifacts: tuple[MediaArtifact, ...] = ()
    manifest_path: Path | None = None
    schema_version: str = ACQUISITION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "video": self.video.to_dict(),
            "assessment": self.assessment.to_dict(),
            "plan": self.plan.to_dict(),
            "selected_strategy": self.selected_strategy.value,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "manifest_path": (
                str(self.manifest_path) if self.manifest_path else None
            ),
        }
