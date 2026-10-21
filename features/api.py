"""Stable app-shell facade for optional product domains.

The Web layer imports this module instead of reaching into novel or video
production implementations directly. Domain internals remain replaceable.
"""

from analyzer.english_fiction_quality import get_english_review_runtime_status
from features.video_production.jobs import production_profile
from integrations.local_skills import (
    get_native_english_review_skill_status,
    get_novel_writing_skill_status,
)
from production.edit_plan import (
    build_auto_edit_plan,
    list_production_sources,
)
from production.ffmpeg_renderer import inspect_ffmpeg_runtime
from production.script_video import (
    preview_script_video_plan,
    script_video_runtime_status,
)
from production.video_factory import VideoFactoryAdapter

__all__ = [
    "get_english_review_runtime_status",
    "get_native_english_review_skill_status",
    "get_novel_writing_skill_status",
    "build_auto_edit_plan",
    "inspect_ffmpeg_runtime",
    "list_production_sources",
    "preview_script_video_plan",
    "production_profile",
    "script_video_runtime_status",
    "VideoFactoryAdapter",
]
