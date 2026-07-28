from __future__ import annotations

import json
import logging

from analyzer.analyze import run_analysis
from config import SETTINGS, Settings
from models import AnalysisResult, Transcript, Video

logger = logging.getLogger(__name__)


def analyze_transcript(
    video: Video,
    transcript: Transcript,
    settings: Settings = SETTINGS,
) -> AnalysisResult:
    analysis_dir = settings.analysis_cache_dir / video.video_id
    analysis_path = analysis_dir / "analysis.json"
    if analysis_path.exists() and not settings.overwrite_cache:
        logger.info("Using cached analysis: %s", analysis_path)
        return AnalysisResult.from_dict(json.loads(analysis_path.read_text(encoding="utf-8")))

    analysis_dir.mkdir(parents=True, exist_ok=True)
    result = run_analysis(video, transcript, settings)
    analysis_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Analyze transcript text and cache analysis.json.")
    parser.add_argument("text_file")
    parser.add_argument("--video-id", default="local")
    parser.add_argument("--title", default="local")
    args = parser.parse_args()
    text_path = Path(args.text_file)
    video = Video(source_url=str(text_path), platform="local", video_id=args.video_id, title=args.title)
    transcript = Transcript(video_id=args.video_id, text=text_path.read_text(encoding="utf-8"), source="local", text_path=text_path)
    print(json.dumps(analyze_transcript(video, transcript).to_dict(), ensure_ascii=False, indent=2))
