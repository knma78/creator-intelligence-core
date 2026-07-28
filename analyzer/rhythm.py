from __future__ import annotations

import json
import re
from collections import Counter

from models import Transcript, TranscriptSegment

TRANSITION_WORDS = [
    "首先", "然后", "接下来", "其次", "另外", "但是", "不过", "所以", "因此",
    "最后", "总结", "换句话说", "反过来", "与此同时", "另一方面",
]
POSITIVE_WORDS = ["厉害", "高效", "成功", "喜欢", "值得", "优秀", "增长", "爆火", "好"]
NEGATIVE_WORDS = ["问题", "失败", "痛点", "焦虑", "危险", "困难", "下降", "糟糕", "差"]


def extract_transitions(text: str, limit: int = 12) -> list[str]:
    found = []
    for word in TRANSITION_WORDS:
        if word in text:
            found.append(word)
    return found[:limit]


def analyze_rhythm(transcript: Transcript) -> dict[str, object]:
    if not transcript.segments:
        return {
            "高潮位置": "缺少时间轴，无法精确判断。",
            "转场": "、".join(extract_transitions(transcript.text)) or "未检测到明显转场词。",
            "节奏变化": "根据纯文本长度粗略判断，建议结合时间轴字幕复核。",
            "density_by_window": [],
        }

    windows = _density_windows(transcript.segments)
    peak = max(windows, key=lambda item: item["chars_per_minute"], default=None)
    transition_words = extract_transitions(transcript.text)
    if peak:
        climax = f"{peak['time_range']}，单位时间信息密度最高。"
    else:
        climax = "未检测到明显高潮位置。"

    return {
        "高潮位置": climax,
        "转场": "、".join(transition_words) if transition_words else "未检测到明显转场词。",
        "节奏变化": _describe_density(windows),
        "density_by_window": windows,
    }


def analyze_emotion(text: str) -> dict[str, object]:
    positive = sum(text.count(word) for word in POSITIVE_WORDS)
    negative = sum(text.count(word) for word in NEGATIVE_WORDS)
    exclamation = text.count("！") + text.count("!")
    question = text.count("？") + text.count("?")
    if positive > negative:
        overall = "偏积极/分享型"
    elif negative > positive:
        overall = "偏问题/痛点型"
    else:
        overall = "中性讲解型"
    return {
        "整体情绪": overall,
        "情绪变化": f"感叹 {exclamation} 次，提问 {question} 次，正向词 {positive} 次，负向词 {negative} 次。",
        "signals": {
            "positive_words": positive,
            "negative_words": negative,
            "exclamation": exclamation,
            "question": question,
        },
    }


def _density_windows(segments: list[TranscriptSegment], window_seconds: int = 60) -> list[dict[str, object]]:
    duration = max((segment.end for segment in segments), default=0)
    windows = []
    start = 0
    while start < duration:
        end = min(start + window_seconds, duration)
        text = "".join(
            segment.text
            for segment in segments
            if segment.start < end and segment.end >= start
        )
        windows.append(
            {
                "time_range": f"{_fmt_time(start)} - {_fmt_time(end)}",
                "chars_per_minute": round(len(re.sub(r"\s+", "", text)) * 60 / max(end - start, 1), 2),
            }
        )
        start += window_seconds
    return windows


def _describe_density(windows: list[dict[str, object]]) -> str:
    if len(windows) < 2:
        return "内容较短，节奏变化不明显。"
    values = [float(item["chars_per_minute"]) for item in windows]
    first = sum(values[: max(1, len(values) // 3)]) / max(1, len(values) // 3)
    last = sum(values[-max(1, len(values) // 3) :]) / max(1, len(values) // 3)
    if last > first * 1.2:
        return "后段信息密度上升，呈加速收束。"
    if first > last * 1.2:
        return "前段信息密度更高，后段节奏放缓。"
    return "整体信息密度较均衡。"


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

    parser = argparse.ArgumentParser(description="Analyze rough rhythm and emotion from subtitle text.")
    parser.add_argument("text_file")
    args = parser.parse_args()
    text = Path(args.text_file).read_text(encoding="utf-8")
    transcript = Transcript(video_id="local", text=text, source="local", text_path=Path(args.text_file))
    print(json.dumps({"rhythm": analyze_rhythm(transcript), "emotion": analyze_emotion(text)}, ensure_ascii=False, indent=2))
