from __future__ import annotations

import json
import re

from config import SETTINGS, Settings
from models import AnalysisResult, Transcript, Video

from .hook import analyze_hook
from .keywords import extract_keywords
from .llm import analyze_with_llm
from .rhythm import analyze_emotion, analyze_rhythm, extract_transitions
from .structure import build_structure


def run_analysis(
    video: Video,
    transcript: Transcript,
    settings: Settings = SETTINGS,
) -> AnalysisResult:
    baseline = _local_analysis(video, transcript)
    llm_result = analyze_with_llm(video, transcript, baseline, settings)
    return llm_result or baseline


def _local_analysis(video: Video, transcript: Transcript) -> AnalysisResult:
    text = transcript.text
    structure = build_structure(transcript)
    keywords = extract_keywords(text)
    hook = analyze_hook(transcript)
    rhythm = analyze_rhythm(transcript)
    transitions = extract_transitions(text)
    return AnalysisResult(
        video_id=video.video_id,
        title=video.title,
        one_sentence_summary=_one_sentence_summary(text, video.title),
        hook=hook,
        structure=structure,
        transitions=transitions,
        emotion=analyze_emotion(text),
        rhythm=rhythm,
        keywords=keywords,
        learnings=_learning_points(hook, structure, rhythm, keywords),
        raw_llm_result=None,
    )


def _one_sentence_summary(text: str, title: str) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    if not clean:
        return f"视频《{title}》暂无可分析字幕。"
    sentence = re.split(r"(?<=[。！？!?])", clean)[0].strip()
    if len(sentence) < 12 and len(clean) > len(sentence):
        sentence = clean[:100]
    return sentence[:120]


def _learning_points(
    hook: dict,
    structure: list[dict],
    rhythm: dict,
    keywords: list[dict],
) -> list[str]:
    points = [
        f"开头采用“{hook.get('开头方式', '未知')}”，可作为同类选题的前 30 秒参考。",
        "内容被拆成清晰段落，适合复用为选题拆解模板。" if structure else "字幕结构不明显，后续可人工补充分段。",
        f"节奏观察：{rhythm.get('节奏变化', '暂无')}",
    ]
    if keywords:
        top_words = "、".join(str(item["word"]) for item in keywords[:5])
        points.append(f"高频表达集中在：{top_words}。")
    return points


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Run local/LLM analysis from subtitle text.")
    parser.add_argument("text_file")
    parser.add_argument("--title", default="local")
    parser.add_argument("--video-id", default="local")
    args = parser.parse_args()
    text_path = Path(args.text_file)
    video = Video(source_url=str(text_path), platform="local", video_id=args.video_id, title=args.title)
    transcript = Transcript(video_id=args.video_id, text=text_path.read_text(encoding="utf-8"), source="local", text_path=text_path)
    print(json.dumps(run_analysis(video, transcript).to_dict(), ensure_ascii=False, indent=2))
