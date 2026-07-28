from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _path_to_str(value: Path | None) -> str | None:
    return str(value) if value else None


def _path_from_str(value: str | None) -> Path | None:
    return Path(value) if value else None


@dataclass
class Video:
    source_url: str
    platform: str
    video_id: str
    title: str
    author: str | None = None
    cover: str | None = None
    publish_time: str | None = None
    duration: float | None = None
    video_path: Path | None = None
    subtitle_path: Path | None = None
    metadata_path: Path | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["video_path"] = _path_to_str(self.video_path)
        data["subtitle_path"] = _path_to_str(self.subtitle_path)
        data["metadata_path"] = _path_to_str(self.metadata_path)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Video":
        payload = dict(data)
        payload["video_path"] = _path_from_str(payload.get("video_path"))
        payload["subtitle_path"] = _path_from_str(payload.get("subtitle_path"))
        payload["metadata_path"] = _path_from_str(payload.get("metadata_path"))
        payload.setdefault("stats", {})
        payload.setdefault("extra_metadata", {})
        allowed = set(cls.__dataclass_fields__)
        payload = {key: value for key, value in payload.items() if key in allowed}
        return cls(**payload)


@dataclass
class TranscriptSegment:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptSegment":
        return cls(
            start=float(data.get("start", 0)),
            end=float(data.get("end", 0)),
            text=str(data.get("text", "")),
        )


@dataclass
class Transcript:
    video_id: str
    text: str
    source: str
    text_path: Path
    srt_path: Path | None = None
    json_path: Path | None = None
    segments: list[TranscriptSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "text": self.text,
            "source": self.source,
            "text_path": str(self.text_path),
            "srt_path": _path_to_str(self.srt_path),
            "json_path": _path_to_str(self.json_path),
            "segments": [segment.to_dict() for segment in self.segments],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transcript":
        return cls(
            video_id=data["video_id"],
            text=data.get("text", ""),
            source=data.get("source", "unknown"),
            text_path=Path(data["text_path"]),
            srt_path=_path_from_str(data.get("srt_path")),
            json_path=_path_from_str(data.get("json_path")),
            segments=[
                TranscriptSegment.from_dict(item)
                for item in data.get("segments", [])
            ],
        )


@dataclass
class AnalysisResult:
    video_id: str
    title: str
    one_sentence_summary: str
    hook: dict[str, Any]
    structure: list[dict[str, Any]]
    transitions: list[str]
    emotion: dict[str, Any]
    rhythm: dict[str, Any]
    keywords: list[dict[str, Any]]
    learnings: list[str]
    raw_llm_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnalysisResult":
        return cls(
            video_id=data["video_id"],
            title=data.get("title", ""),
            one_sentence_summary=data.get("one_sentence_summary", ""),
            hook=data.get("hook", {}),
            structure=data.get("structure", []),
            transitions=data.get("transitions", []),
            emotion=data.get("emotion", {}),
            rhythm=data.get("rhythm", {}),
            keywords=data.get("keywords", []),
            learnings=data.get("learnings", []),
            raw_llm_result=data.get("raw_llm_result"),
        )
