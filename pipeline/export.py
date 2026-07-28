from __future__ import annotations

import json
import shutil
from pathlib import Path

from config import SETTINGS, Settings
from exporter.markdown import build_markdown
from models import AnalysisResult, Transcript, Video


def export_results(
    video: Video,
    transcript: Transcript,
    analysis: AnalysisResult,
    settings: Settings = SETTINGS,
) -> Path:
    output_dir = settings.output_dir / video.video_id
    output_dir.mkdir(parents=True, exist_ok=True)

    _copy_if_exists(transcript.text_path, output_dir / "subtitle.txt")
    if transcript.srt_path:
        _copy_if_exists(transcript.srt_path, output_dir / "subtitle.srt")

    analysis_path = output_dir / "analysis.json"
    analysis_path.write_text(
        json.dumps(analysis.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    markdown_path = output_dir / "video.md"
    markdown_path.write_text(build_markdown(video, analysis), encoding="utf-8")
    return markdown_path


def _copy_if_exists(source: Path, target: Path) -> None:
    if source.exists() and source.resolve() != target.resolve():
        shutil.copy2(source, target)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Export analysis fixture to Markdown.")
    parser.add_argument("analysis_json")
    parser.add_argument("--video-id", default="local")
    parser.add_argument("--title", default="local")
    parser.add_argument("--subtitle", default=None)
    args = parser.parse_args()
    analysis = AnalysisResult.from_dict(json.loads(Path(args.analysis_json).read_text(encoding="utf-8")))
    subtitle_path = Path(args.subtitle) if args.subtitle else Path(args.analysis_json)
    video = Video(source_url="", platform="local", video_id=args.video_id, title=args.title)
    transcript = Transcript(video_id=args.video_id, text="", source="local", text_path=subtitle_path)
    print(export_results(video, transcript, analysis))
