from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable

from config import SETTINGS, Settings
from models import Transcript, TranscriptSegment, Video
from processor.ffmpeg import extract_audio
from processor.subtitle import subtitle_to_transcript
from processor.whisper import transcribe_audio

logger = logging.getLogger(__name__)


def process_video(
    video: Video,
    settings: Settings = SETTINGS,
    progress_callback: Callable[[str, int, str], None] | None = None,
) -> Transcript:
    transcript_dir = settings.transcript_cache_dir / video.video_id
    cached = _load_cached_transcript(video.video_id, transcript_dir)
    if cached and not settings.overwrite_cache:
        logger.info("Using cached transcript: %s", video.video_id)
        if progress_callback:
            progress_callback("字幕缓存", 75, "检测到已有字幕缓存，跳过音频提取和 Whisper。")
        return cached

    transcript_dir.mkdir(parents=True, exist_ok=True)
    if video.subtitle_path and video.subtitle_path.exists():
        logger.info("Using platform subtitle: %s", video.subtitle_path)
        if progress_callback:
            progress_callback("官方字幕", 55, "正在转换官方字幕为统一文本、SRT 和 JSON。")
        return subtitle_to_transcript(
            video.subtitle_path,
            transcript_dir,
            video.video_id,
            source="platform_subtitle",
        )

    if not video.video_path or not video.video_path.exists():
        raise FileNotFoundError(f"Video file is missing for {video.video_id}")

    audio_path = transcript_dir / "audio.wav"
    if progress_callback:
        progress_callback("提取音频", 48, "没有官方字幕，正在用 FFmpeg 提取音频。")
    extract_audio(video.video_path, audio_path, settings)
    whisper_language = _whisper_language_for_video(video, settings)
    if progress_callback:
        language_label = whisper_language or "自动检测"
        progress_callback(
            "Whisper识别",
            55,
            f"音频已就绪，正在启动 Whisper；识别语言：{language_label}。",
        )
    return transcribe_audio(
        audio_path,
        transcript_dir,
        video.video_id,
        settings,
        progress_callback=progress_callback,
        language=whisper_language,
    )


def _whisper_language_for_video(
    video: Video,
    settings: Settings,
) -> str | None:
    if video.platform == "youtube":
        return settings.youtube_whisper_language
    if video.platform == "douyin":
        return settings.douyin_whisper_language
    return settings.whisper_language


def _load_cached_transcript(video_id: str, transcript_dir: Path) -> Transcript | None:
    text_path = transcript_dir / "subtitle.txt"
    srt_path = transcript_dir / "subtitle.srt"
    json_path = transcript_dir / "subtitle.json"
    if not text_path.exists() or not json_path.exists():
        return None

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    segments = [
        TranscriptSegment.from_dict(item)
        for item in payload.get("segments", [])
    ]
    return Transcript(
        video_id=video_id,
        text=text_path.read_text(encoding="utf-8"),
        source=payload.get("source", "cache"),
        text_path=text_path,
        srt_path=srt_path if srt_path.exists() else None,
        json_path=json_path,
        segments=segments,
    )


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Process a local video or subtitle into transcript files.")
    parser.add_argument("--video-id", default="local")
    parser.add_argument("--video-path")
    parser.add_argument("--subtitle-path")
    parser.add_argument("--title", default="local")
    args = parser.parse_args()
    video = Video(
        source_url=args.video_path or args.subtitle_path or "",
        platform="local",
        video_id=args.video_id,
        title=args.title,
        video_path=Path(args.video_path) if args.video_path else None,
        subtitle_path=Path(args.subtitle_path) if args.subtitle_path else None,
    )
    transcript = process_video(video)
    print(json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2))
