from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from infrastructure.atomic_io import atomic_write_json, atomic_write_text
from production.packaging import find_source_video


EDIT_PLAN_SCHEMA_VERSION = "2.0"
_SRT_TIME = re.compile(
    r"(?P<h1>\d{1,2}):(?P<m1>\d{2}):(?P<s1>\d{2})[,.](?P<ms1>\d{3})"
    r"\s*-->\s*"
    r"(?P<h2>\d{1,2}):(?P<m2>\d{2}):(?P<s2>\d{2})[,.](?P<ms2>\d{3})"
)
_HOOK_TERMS = (
    "为什么",
    "如何",
    "真相",
    "秘密",
    "竟然",
    "没想到",
    "但是",
    "却",
    "问题",
    "?",
    "？",
)
_PAYOFF_TERMS = (
    "所以",
    "因此",
    "结果",
    "最终",
    "这意味着",
    "关键",
    "答案",
)
_TIME_RANGE = re.compile(
    r"(?P<start>\d{1,2}:\d{2}(?::\d{2})?)"
    r"\s*[-–—至]\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?)"
)


@dataclass(frozen=True)
class CaptionCue:
    index: int
    start_seconds: float
    end_seconds: float
    text: str

    @property
    def duration_seconds(self) -> float:
        return max(0.0, self.end_seconds - self.start_seconds)


def _timestamp_seconds(match: re.Match[str], suffix: str) -> float:
    return (
        int(match.group(f"h{suffix}")) * 3600
        + int(match.group(f"m{suffix}")) * 60
        + int(match.group(f"s{suffix}"))
        + int(match.group(f"ms{suffix}")) / 1000
    )


def parse_srt(path: Path) -> tuple[CaptionCue, ...]:
    text = Path(path).read_text(encoding="utf-8-sig").strip()
    if not text:
        return ()
    cues: list[CaptionCue] = []
    for block in re.split(r"\r?\n\s*\r?\n", text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timestamp_index = next(
            (index for index, line in enumerate(lines) if "-->" in line),
            None,
        )
        if timestamp_index is None:
            continue
        match = _SRT_TIME.search(lines[timestamp_index])
        if not match:
            continue
        start = _timestamp_seconds(match, "1")
        end = _timestamp_seconds(match, "2")
        caption = " ".join(lines[timestamp_index + 1 :]).strip()
        if not caption or end <= start:
            continue
        cues.append(
            CaptionCue(
                index=len(cues) + 1,
                start_seconds=start,
                end_seconds=end,
                text=caption,
            )
        )
    return tuple(cues)


def _format_srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def write_retimed_subtitles(
    cues: tuple[CaptionCue, ...],
    *,
    source_start: float,
    output_path: Path,
) -> Path:
    blocks = []
    for index, cue in enumerate(cues, start=1):
        start = max(0.0, cue.start_seconds - source_start)
        end = max(start + 0.04, cue.end_seconds - source_start)
        blocks.append(
            f"{index}\n"
            f"{_format_srt_time(start)} --> {_format_srt_time(end)}\n"
            f"{cue.text}"
        )
    atomic_write_text(Path(output_path), "\n\n".join(blocks) + "\n")
    return Path(output_path)


def _window_score(
    cues: tuple[CaptionCue, ...],
    start_index: int,
    end_index: int,
    target_seconds: float,
    decision_context: dict[str, Any] | None = None,
) -> tuple[float, list[str]]:
    selected = cues[start_index:end_index]
    duration = selected[-1].end_seconds - selected[0].start_seconds
    text = "".join(cue.text for cue in selected)
    opening_text = "".join(cue.text for cue in selected[:4])
    closing_text = "".join(cue.text for cue in selected[-4:])
    density = len(text) / max(duration, 1.0)
    hook_hits = sum(term in opening_text for term in _HOOK_TERMS)
    payoff_hits = sum(term in closing_text for term in _PAYOFF_TERMS)
    duration_fit = max(
        0.0,
        1.0 - abs(duration - target_seconds) / max(target_seconds, 1.0),
    )
    score = density * 2.2 + hook_hits * 4.0 + payoff_hits * 2.0 + duration_fit * 8.0
    reasons = [
        f"信息密度 {density:.1f} 字/秒",
        f"目标时长匹配度 {duration_fit:.0%}",
    ]
    if hook_hits:
        reasons.append(f"开头包含 {hook_hits} 个钩子信号")
    if payoff_hits:
        reasons.append(f"结尾包含 {payoff_hits} 个收束信号")
    context = decision_context or {}
    structure_hits = []
    for item in context.get("structure_ranges") or []:
        overlap = max(
            0.0,
            min(selected[-1].end_seconds, float(item["end"]))
            - max(selected[0].start_seconds, float(item["start"])),
        )
        if overlap <= 0:
            continue
        ratio = overlap / max(
            0.1,
            float(item["end"]) - float(item["start"]),
        )
        weight = 2.5 if item.get("role") in {"hook", "payoff"} else 1.2
        score += min(1.0, ratio) * weight
        structure_hits.append(str(item.get("label") or item.get("role") or "结构段"))
    if structure_hits:
        reasons.append(
            "覆盖研究结构：" + "、".join(dict.fromkeys(structure_hits[:4]))
        )

    boundaries = [
        float(value)
        for value in context.get("scene_boundaries") or []
        if isinstance(value, (int, float))
    ]
    if boundaries:
        start_distance = min(
            abs(selected[0].start_seconds - value) for value in boundaries
        )
        end_distance = min(
            abs(selected[-1].end_seconds - value) for value in boundaries
        )
        alignment = max(0.0, 1.0 - start_distance / 3.0) + max(
            0.0,
            1.0 - end_distance / 3.0,
        )
        score += alignment * 1.5
        if start_distance <= 1.5 and end_distance <= 1.5:
            reasons.append("起止点贴近场景边界，减少突兀切断")

    keywords = [
        str(value)
        for value in context.get("keywords") or []
        if str(value).strip()
    ]
    keyword_hits = sum(value in text for value in keywords[:20])
    if keyword_hits:
        score += min(keyword_hits, 6) * 0.35
        reasons.append(f"命中 {keyword_hits} 个研究关键词")
    return score, reasons


def choose_contiguous_window(
    cues: tuple[CaptionCue, ...],
    target_seconds: float,
    decision_context: dict[str, Any] | None = None,
) -> tuple[int, int, float, list[str]]:
    if not cues:
        raise ValueError("Timed subtitles are required for automatic editing.")
    full_duration = cues[-1].end_seconds - cues[0].start_seconds
    if full_duration <= target_seconds * 1.08:
        return 0, len(cues), 100.0, ["原内容时长已接近目标，保留完整内容"]

    best: tuple[float, int, int, list[str]] | None = None
    minimum = max(8.0, target_seconds * 0.72)
    maximum = target_seconds * 1.08
    for start_index in range(len(cues)):
        for end_index in range(start_index + 1, len(cues) + 1):
            duration = (
                cues[end_index - 1].end_seconds
                - cues[start_index].start_seconds
            )
            if duration < minimum:
                continue
            if duration > maximum:
                break
            score, reasons = _window_score(
                cues,
                start_index,
                end_index,
                target_seconds,
                decision_context,
            )
            candidate = (score, start_index, end_index, reasons)
            if best is None or candidate[0] > best[0]:
                best = candidate
    if best is None:
        end_index = next(
            (
                index
                for index, cue in enumerate(cues, start=1)
                if cue.end_seconds - cues[0].start_seconds >= target_seconds
            ),
            len(cues),
        )
        return 0, end_index, 0.0, ["字幕时间较稀疏，使用最接近目标时长的连续区间"]
    return best[1], best[2], best[0], best[3]


def _timecode_seconds(value: str) -> float | None:
    parts = value.split(":")
    try:
        numbers = [int(item) for item in parts]
    except ValueError:
        return None
    if len(numbers) == 2:
        return float(numbers[0] * 60 + numbers[1])
    if len(numbers) == 3:
        return float(numbers[0] * 3600 + numbers[1] * 60 + numbers[2])
    return None


def _decision_context(
    video_id: str,
    settings: Settings,
) -> dict[str, Any]:
    research_dir = settings.output_dir / video_id
    analysis = _read_json(research_dir / "analysis.json")
    enrichment = _read_json(research_dir / "v3.json")
    structure_ranges = []
    for item in analysis.get("structure") or []:
        if not isinstance(item, dict):
            continue
        match = _TIME_RANGE.search(str(item.get("time_range") or ""))
        if not match:
            continue
        start = _timecode_seconds(match.group("start"))
        end = _timecode_seconds(match.group("end"))
        if start is None or end is None or end <= start:
            continue
        raw_role = str(item.get("part") or "").lower()
        role = (
            "hook"
            if any(term in raw_role for term in ("hook", "开头", "钩子"))
            else (
                "payoff"
                if any(
                    term in raw_role
                    for term in ("结尾", "结论", "总结", "答案", "收束")
                )
                else "body"
            )
        )
        structure_ranges.append(
            {
                "start": start,
                "end": end,
                "role": role,
                "label": str(
                    item.get("part")
                    or item.get("summary")
                    or role
                ),
            }
        )

    scene_analysis = enrichment.get("scene_analysis") or {}
    scene_boundaries = sorted(
        {
            float(value)
            for scene in scene_analysis.get("scenes") or []
            if isinstance(scene, dict)
            for value in (scene.get("start"), scene.get("end"))
            if isinstance(value, (int, float))
        }
    )
    audio = enrichment.get("audio_rhythm_analysis") or {}
    visual = (
        (enrichment.get("cover_analysis") or {}).get("visual_semantics")
        or {}
    )
    keywords = [
        str(item.get("word") or "")
        for item in analysis.get("keywords") or []
        if isinstance(item, dict) and item.get("word")
    ]
    return {
        "analysis_ready": bool(analysis),
        "enrichment_ready": bool(enrichment),
        "structure_ranges": structure_ranges,
        "scene_boundaries": scene_boundaries,
        "keywords": keywords,
        "audio_rhythm": {
            key: audio.get(key)
            for key in (
                "tempo_bpm",
                "onsets_per_minute",
                "silence_ratio",
                "dynamic_range_db",
            )
            if audio.get(key) is not None
        },
        "visual_labels": [
            item.get("label_zh") or item.get("label")
            for item in visual.get("top_labels") or []
            if isinstance(item, dict)
        ][:5],
        "sources": {
            "analysis": str(research_dir / "analysis.json"),
            "enrichment": (
                str(research_dir / "v3.json")
                if enrichment
                else None
            ),
        },
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _subtitle_path(video_id: str, settings: Settings) -> Path | None:
    candidates = (
        settings.output_dir / video_id / "subtitle.srt",
        settings.transcript_cache_dir / video_id / "subtitle.srt",
    )
    return next(
        (
            candidate
            for candidate in candidates
            if candidate.is_file() and candidate.stat().st_size > 0
        ),
        None,
    )


def list_production_sources(
    settings: Settings = SETTINGS,
) -> list[dict[str, Any]]:
    if not settings.output_dir.is_dir():
        return []
    sources: list[dict[str, Any]] = []
    for directory in settings.output_dir.iterdir():
        if not directory.is_dir() or directory.name == "video_production":
            continue
        analysis_path = directory / "analysis.json"
        if not analysis_path.is_file():
            continue
        video_id = directory.name
        analysis = _read_json(analysis_path)
        metadata_path = settings.video_cache_dir / video_id / "metadata.json"
        metadata = _read_json(metadata_path)
        video = find_source_video(video_id, metadata, settings)
        subtitles = _subtitle_path(video_id, settings)
        sources.append(
            {
                "video_id": video_id,
                "title": str(
                    analysis.get("title")
                    or metadata.get("title")
                    or video_id
                ),
                "duration_seconds": float(metadata.get("duration") or 0),
                "source_video_path": str(video) if video else None,
                "source_video_ready": video is not None,
                "subtitle_path": str(subtitles) if subtitles else None,
                "subtitle_ready": subtitles is not None,
                "updated_at": analysis_path.stat().st_mtime,
            }
        )
    sources.sort(key=lambda item: item["updated_at"], reverse=True)
    return sources


def build_auto_edit_plan(
    video_id: str,
    *,
    target_seconds: float = 60.0,
    platform: str = "douyin",
    settings: Settings = SETTINGS,
) -> Path:
    target_seconds = min(1800.0, max(15.0, float(target_seconds)))
    metadata_path = settings.video_cache_dir / video_id / "metadata.json"
    metadata = _read_json(metadata_path)
    source_video = find_source_video(video_id, metadata, settings)
    if source_video is None:
        raise FileNotFoundError(
            f"没有找到 {video_id} 的本地源视频；请先完成下载或本地导入。"
        )
    subtitle_path = _subtitle_path(video_id, settings)
    if subtitle_path is None:
        raise FileNotFoundError(
            f"没有找到 {video_id} 的有效时间轴字幕；请先完成转录。"
        )
    cues = parse_srt(subtitle_path)
    if not cues:
        raise ValueError(f"{subtitle_path} 不包含可用字幕时间轴。")

    decision_context = _decision_context(video_id, settings)
    start_index, end_index, score, reasons = choose_contiguous_window(
        cues,
        target_seconds,
        decision_context,
    )
    selected = cues[start_index:end_index]
    source_start = selected[0].start_seconds
    source_end = selected[-1].end_seconds
    output_duration = source_end - source_start
    package_dir = settings.video_production_dir / video_id
    work_dir = package_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)
    edit_subtitle_path = write_retimed_subtitles(
        selected,
        source_start=source_start,
        output_path=work_dir / "edit_subtitles.srt",
    )
    plan_path = work_dir / "edit_plan.json"
    plan = {
        "schema_version": EDIT_PLAN_SCHEMA_VERSION,
        "video_id": video_id,
        "strategy": "research_guided_contiguous_window",
        "platform": platform,
        "target_seconds": target_seconds,
        "source_video_path": str(source_video),
        "source_subtitle_path": str(subtitle_path.resolve()),
        "edit_subtitle_path": str(edit_subtitle_path.resolve()),
        "source_duration_seconds": (
            float(metadata.get("duration"))
            if metadata.get("duration") is not None
            else cues[-1].end_seconds
        ),
        "output_duration_seconds": output_duration,
        "selection_score": round(score, 3),
        "decision_inputs": decision_context,
        "segments": [
            {
                "segment_id": "primary-001",
                "source_start_seconds": source_start,
                "source_end_seconds": source_end,
                "output_start_seconds": 0.0,
                "output_end_seconds": output_duration,
                "purpose": "信息密度与叙事完整性最佳的连续片段",
                "reasons": reasons,
                "caption_count": len(selected),
                "text_preview": "".join(cue.text for cue in selected)[:240],
            }
        ],
        "captions": [asdict(cue) for cue in selected],
        "excluded_caption_count": len(cues) - len(selected),
        "audit": {
            "decision_visible": True,
            "source_media_preserved": True,
            "rewrite_applied": False,
            "selection_note": (
                "研究结构、关键词和场景边界参与评分；当前版本仍优先选择"
                "连续区间，避免自动拼接造成语义跳跃。"
            ),
        },
    }
    if not math.isfinite(output_duration) or output_duration <= 0:
        raise ValueError("Automatic edit plan produced an invalid duration.")
    atomic_write_json(plan_path, plan)
    return plan_path
