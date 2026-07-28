from __future__ import annotations

import json
import re

from models import Transcript


def analyze_hook(transcript: Transcript) -> dict[str, str | int]:
    opening = _opening_text(transcript)
    opening_type = "直接抛出主题"
    effect = "快速告诉观众本期要讲什么，降低理解成本。"
    score = 6

    if re.search(r"为什么|怎么|如何|\?", opening):
        opening_type = "问题式开头"
        effect = "用问题制造信息缺口，推动观众继续观看。"
        score += 2
    if re.search(r"但是|然而|却|反转|真相|没想到|不是", opening):
        opening_type = "冲突/反差式开头"
        effect = "通过反差或悬念制造期待，提高前段留存。"
        score += 2
    if re.search(r"\d+|三个|五个|第一|第二", opening):
        score += 1
    if len(opening) < 30:
        score -= 1

    return {
        "开头方式": opening_type,
        "作用": effect,
        "评分": max(1, min(score, 10)),
        "证据": opening[:180],
    }


def _opening_text(transcript: Transcript) -> str:
    if transcript.segments:
        texts = [
            segment.text
            for segment in transcript.segments
            if segment.start <= 90 or len("".join(segment.text for segment in transcript.segments[:3])) < 300
        ]
        text = " ".join(texts)
        return text[:600]
    return transcript.text[:600]


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Analyze video hook from subtitle text.")
    parser.add_argument("text_file")
    args = parser.parse_args()
    transcript = Transcript(
        video_id="local",
        text=Path(args.text_file).read_text(encoding="utf-8"),
        source="local",
        text_path=Path(args.text_file),
    )
    print(json.dumps(analyze_hook(transcript), ensure_ascii=False, indent=2))
