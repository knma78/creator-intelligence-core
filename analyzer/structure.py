from __future__ import annotations

import json
import math
import re

from models import Transcript, TranscriptSegment

PART_NAMES = ["第一部分", "第二部分", "第三部分", "第四部分", "第五部分"]


def build_structure(transcript: Transcript, max_parts: int = 5) -> list[dict[str, str]]:
    if transcript.segments:
        return _structure_from_segments(transcript.segments, max_parts=max_parts)
    return _structure_from_text(transcript.text, max_parts=3)


def _structure_from_segments(
    segments: list[TranscriptSegment],
    max_parts: int,
) -> list[dict[str, str]]:
    duration = max((segment.end for segment in segments), default=0)
    if duration <= 0:
        return _structure_from_text(" ".join(segment.text for segment in segments), max_parts=3)

    part_count = min(max_parts, max(3, math.ceil(duration / 600)))
    part_length = duration / part_count
    structure: list[dict[str, str]] = []
    for index in range(part_count):
        start = index * part_length
        end = duration if index == part_count - 1 else (index + 1) * part_length
        part_segments = [
            segment for segment in segments
            if segment.start < end and segment.end >= start
        ]
        text = " ".join(segment.text for segment in part_segments)
        if not text.strip():
            continue
        structure.append(
            {
                "part": PART_NAMES[index],
                "time_range": f"{_fmt_time(start)} - {_fmt_time(end)}",
                "summary": _summarize_chunk(text),
            }
        )
    return structure


def _structure_from_text(text: str, max_parts: int) -> list[dict[str, str]]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunk_size = max(1, math.ceil(len(text) / max_parts))
    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
    return [
        {
            "part": PART_NAMES[index],
            "time_range": "",
            "summary": _summarize_chunk(chunk),
        }
        for index, chunk in enumerate(chunks[:max_parts])
    ]


def _summarize_chunk(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[。！？!?])", text)
    summary = "".join(sentences[:2]).strip() or text[:120]
    return summary[:180]


def _fmt_time(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Build rough content structure from subtitle text.")
    parser.add_argument("text_file")
    args = parser.parse_args()
    transcript = Transcript(
        video_id="local",
        text=Path(args.text_file).read_text(encoding="utf-8"),
        source="local",
        text_path=Path(args.text_file),
    )
    print(json.dumps(build_structure(transcript), ensure_ascii=False, indent=2))
