from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

from infrastructure.atomic_io import atomic_write_json, atomic_write_text
from models import Transcript, TranscriptSegment

TIMING_RE = re.compile(
    r"(?P<start>(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}[\.,]\d{3})"
)
TAG_RE = re.compile(r"<[^>]+>")
ASS_TAG_RE = re.compile(r"\{[^}]*\}")


def subtitle_to_transcript(
    subtitle_path: Path,
    output_dir: Path,
    video_id: str,
    source: str = "platform_subtitle",
) -> Transcript:
    suffix = subtitle_path.suffix.lower()
    if suffix == ".srt":
        segments = parse_srt(subtitle_path.read_text(encoding="utf-8", errors="ignore"))
    elif suffix == ".vtt":
        segments = parse_vtt(subtitle_path.read_text(encoding="utf-8", errors="ignore"))
    elif suffix in {".json", ".json3"}:
        segments = parse_json_subtitle(subtitle_path)
    elif suffix == ".ass":
        segments = parse_ass(subtitle_path.read_text(encoding="utf-8", errors="ignore"))
    else:
        text = subtitle_path.read_text(encoding="utf-8", errors="ignore")
        segments = [TranscriptSegment(start=0, end=0, text=clean_subtitle_text(text))]
    return write_transcript_files(segments, output_dir, video_id, source)


def write_transcript_files(
    segments: list[TranscriptSegment],
    output_dir: Path,
    video_id: str,
    source: str,
) -> Transcript:
    output_dir.mkdir(parents=True, exist_ok=True)
    text = "\n".join(segment.text.strip() for segment in segments if segment.text.strip())

    text_path = output_dir / "subtitle.txt"
    srt_path = output_dir / "subtitle.srt"
    json_path = output_dir / "subtitle.json"

    atomic_write_text(text_path, text)
    atomic_write_text(srt_path, segments_to_srt(segments))
    atomic_write_json(
        json_path,
        {
            "schema_version": "1.0",
            "video_id": video_id,
            "source": source,
            "text": text,
            "segments": [segment.to_dict() for segment in segments],
        },
    )

    return Transcript(
        video_id=video_id,
        text=text,
        source=source,
        text_path=text_path,
        srt_path=srt_path,
        json_path=json_path,
        segments=segments,
    )


def parse_srt(content: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        match = TIMING_RE.search(lines[timing_index])
        if not match:
            continue
        text = clean_subtitle_text(" ".join(lines[timing_index + 1 :]))
        if text:
            segments.append(
                TranscriptSegment(
                    start=timestamp_to_seconds(match.group("start")),
                    end=timestamp_to_seconds(match.group("end")),
                    text=text,
                )
            )
    return segments


def parse_vtt(content: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    lines = content.replace("\r\n", "\n").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        match = TIMING_RE.search(line)
        if not match:
            index += 1
            continue

        index += 1
        text_lines: list[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1

        text = clean_subtitle_text(" ".join(text_lines))
        if text:
            segments.append(
                TranscriptSegment(
                    start=timestamp_to_seconds(match.group("start")),
                    end=timestamp_to_seconds(match.group("end")),
                    text=text,
                )
            )
        index += 1
    return segments


def parse_ass(content: str) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line.startswith("Dialogue:"):
            continue
        payload = line.removeprefix("Dialogue:").strip()
        parts = payload.split(",", 9)
        if len(parts) < 10:
            continue
        text = clean_subtitle_text(ASS_TAG_RE.sub("", parts[9]).replace("\\N", " "))
        if text:
            segments.append(
                TranscriptSegment(
                    start=timestamp_to_seconds(parts[1]),
                    end=timestamp_to_seconds(parts[2]),
                    text=text,
                )
            )
    return segments


def parse_json_subtitle(path: Path) -> list[TranscriptSegment]:
    data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    if isinstance(data, dict) and isinstance(data.get("body"), list):
        return [
            TranscriptSegment(
                start=float(item.get("from", 0)),
                end=float(item.get("to", item.get("from", 0))),
                text=clean_subtitle_text(str(item.get("content", ""))),
            )
            for item in data["body"]
            if str(item.get("content", "")).strip()
        ]
    if isinstance(data, dict) and isinstance(data.get("events"), list):
        return _parse_youtube_json3(data["events"])
    if isinstance(data, list):
        return _parse_generic_json_segments(data)
    return []


def _parse_youtube_json3(events: list[dict[str, Any]]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for event in events:
        segs = event.get("segs") or []
        text = clean_subtitle_text("".join(str(seg.get("utf8", "")) for seg in segs))
        if not text:
            continue
        start = float(event.get("tStartMs", 0)) / 1000
        duration = float(event.get("dDurationMs", 0)) / 1000
        segments.append(TranscriptSegment(start=start, end=start + duration, text=text))
    return segments


def _parse_generic_json_segments(items: list[dict[str, Any]]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    for item in items:
        text = clean_subtitle_text(str(item.get("text") or item.get("content") or ""))
        if not text:
            continue
        start = float(item.get("start", item.get("from", 0)))
        end = float(item.get("end", item.get("to", start)))
        segments.append(TranscriptSegment(start=start, end=end, text=text))
    return segments


def clean_subtitle_text(value: str) -> str:
    value = html.unescape(value)
    value = TAG_RE.sub("", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def segments_to_srt(segments: list[TranscriptSegment]) -> str:
    if not segments:
        return ""
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{seconds_to_srt_timestamp(segment.start)} --> {seconds_to_srt_timestamp(segment.end)}",
                    segment.text.strip(),
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def timestamp_to_seconds(value: str) -> float:
    value = value.strip().replace(",", ".")
    parts = value.split(":")
    if len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    return float(value)


def seconds_to_srt_timestamp(value: float) -> str:
    milliseconds = int(round(max(value, 0) * 1000))
    hours, remainder = divmod(milliseconds, 3600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert subtitle file to txt/srt/json transcript files.")
    parser.add_argument("subtitle")
    parser.add_argument("--video-id", default="local")
    parser.add_argument("--output-dir", default="cache/transcripts/local")
    args = parser.parse_args()
    transcript = subtitle_to_transcript(Path(args.subtitle), Path(args.output_dir), args.video_id)
    print(json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2))
