from __future__ import annotations

from features.contracts import FeatureJobServices, FeatureRegistry


def register_feature_job_modes(
    registry: FeatureRegistry,
    services: FeatureJobServices,
) -> None:
    """Compose optional domains without exposing them to the Web dispatcher."""

    from features.novel.jobs import build_novel_job_handler
    from features.video_production.jobs import (
        build_script_video_job_handler,
        build_video_production_job_handler,
    )

    registry.register("novel", build_novel_job_handler(services))
    registry.register(
        "video_production",
        build_video_production_job_handler(services),
    )
    registry.register(
        "script_video",
        build_script_video_job_handler(services),
    )
