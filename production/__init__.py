"""Reusable local video-production capabilities.

The package keeps research artifacts and production outputs separate.  It does
not vendor external editors, models, episode assets, or Node dependencies.
"""

from production.contracts import (
    PRODUCTION_MANIFEST_SCHEMA_VERSION,
    ProductionAsset,
    ProductionManifest,
    RenderProfile,
    TimelineSegment,
)
from production.edit_plan import (
    EDIT_PLAN_SCHEMA_VERSION,
    build_auto_edit_plan,
    list_production_sources,
)
from production.packaging import create_research_package
from production.script_video import (
    preview_script_video_plan,
    run_script_video_pipeline,
    script_video_runtime_status,
)

__all__ = [
    "PRODUCTION_MANIFEST_SCHEMA_VERSION",
    "EDIT_PLAN_SCHEMA_VERSION",
    "ProductionAsset",
    "ProductionManifest",
    "RenderProfile",
    "TimelineSegment",
    "build_auto_edit_plan",
    "create_research_package",
    "list_production_sources",
    "preview_script_video_plan",
    "run_script_video_pipeline",
    "script_video_runtime_status",
]
