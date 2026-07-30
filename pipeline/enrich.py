from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from analyzer.comments import analyze_comments
from analyzer.cover import analyze_cover
from analyzer.nlp import analyze_text_nlp
from analyzer.scenes import analyze_video_scenes
from analyzer.title_stats import analyze_title_stats
from config import SETTINGS, Settings
from downloader.comments import fetch_bilibili_comments
from infrastructure.atomic_io import atomic_write_json, atomic_write_text
from models import AnalysisResult, Transcript, Video


def enrich_video(
    video: Video,
    transcript: Transcript,
    analysis: AnalysisResult,
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    output_dir = settings.output_dir / video.video_id
    output_dir.mkdir(parents=True, exist_ok=True)

    comments_payload = _safe_fetch_comments(video, settings)
    comments_analysis = analyze_comments(comments_payload)
    cover_analysis = analyze_cover(video, settings)
    title_stats = analyze_title_stats([video.title])
    nlp_analysis = analyze_text_nlp(transcript.text, settings)
    scene_analysis = analyze_video_scenes(video.video_path, settings)

    payload = {
        "video_id": video.video_id,
        "comments": comments_payload,
        "comments_analysis": comments_analysis,
        "cover_analysis": cover_analysis,
        "title_stats": title_stats,
        "nlp_analysis": nlp_analysis,
        "scene_analysis": scene_analysis,
        "rag_ready_text": _rag_ready_text(
            video,
            transcript,
            analysis,
            comments_analysis,
            cover_analysis,
            nlp_analysis,
            scene_analysis,
        ),
    }

    atomic_write_json(output_dir / "v3.json", payload)
    atomic_write_text(output_dir / "v3.md", _build_v3_markdown(payload))
    _copy_cover_if_exists(cover_analysis, output_dir)
    return payload


def _safe_fetch_comments(video: Video, settings: Settings) -> dict[str, Any]:
    if video.platform != "bilibili":
        return {"video_id": video.video_id, "status": "skipped", "reason": "comments only support bilibili", "comments": []}
    return fetch_bilibili_comments(video, settings)


def _rag_ready_text(
    video: Video,
    transcript: Transcript,
    analysis: AnalysisResult,
    comments_analysis: dict[str, Any],
    cover_analysis: dict[str, Any],
    nlp_analysis: dict[str, Any],
    scene_analysis: dict[str, Any],
) -> str:
    cover_ocr = ((cover_analysis.get("ocr") or {}).get("text")) or ""
    comment_keywords = "、".join(item.get("word", "") for item in comments_analysis.get("keywords", [])[:10])
    entities = "、".join(item.get("text", "") for item in nlp_analysis.get("entities", [])[:15])
    return "\n".join(
        [
            f"标题：{video.title}",
            f"一句话总结：{analysis.one_sentence_summary}",
            f"高频词：{'、'.join(str(item.get('word', '')) for item in analysis.keywords[:10])}",
            f"评论关键词：{comment_keywords}",
            f"封面OCR：{cover_ocr}",
            f"实体：{entities}",
            (
                "镜头节奏："
                f"{scene_analysis.get('scene_count', 0)} 个镜头，"
                f"平均 {scene_analysis.get('average_scene_duration', 0)} 秒，"
                f"节奏 {scene_analysis.get('pace', 'unknown')}"
            ),
            "字幕：",
            transcript.text,
        ]
    )


def _build_v3_markdown(payload: dict[str, Any]) -> str:
    comments = payload["comments_analysis"]
    cover = payload["cover_analysis"]
    title_stats = payload["title_stats"]
    nlp = payload.get("nlp_analysis") or {}
    scenes = payload.get("scene_analysis") or {}
    lines = [
        "# V3增强分析",
        "",
        "# 评论区分析",
        "",
        f"状态：{comments.get('status', '')}",
        f"评论数：{comments.get('comment_count', 0)}",
        f"情绪：{comments.get('sentiment', '')}",
        "关键词：",
    ]
    for item in comments.get("keywords", [])[:20]:
        lines.append(f"- {item.get('word', '')}：{item.get('count', 0)}")
    lines.extend(["", "# 封面分析", ""])
    lines.append(f"状态：{cover.get('status', '')}")
    if cover.get("width"):
        lines.append(f"尺寸：{cover.get('width')} x {cover.get('height')}")
        lines.append(f"亮度：{cover.get('brightness')}")
        lines.append(f"对比度：{cover.get('contrast')}")
    ocr = cover.get("ocr") or {}
    lines.append(f"OCR状态：{ocr.get('status', '')}")
    lines.append(f"OCR文本：{ocr.get('text', '')}")
    lines.extend(["", "# 标题统计", ""])
    lines.append(f"标题长度：{title_stats.get('average_length', 0)}")
    lines.append(f"是否问题式：{title_stats.get('question_title_count', 0)}")
    lines.append(f"是否数字式：{title_stats.get('number_title_count', 0)}")
    lines.extend(["", "# spaCy语义分析", ""])
    lines.append(f"状态：{nlp.get('status', '')}")
    lines.append(f"模型：{nlp.get('model', '')}")
    lines.append(f"句子数：{nlp.get('sentence_count', 0)}")
    lines.append(f"平均句长：{nlp.get('average_sentence_chars', 0)}")
    if nlp.get("entities"):
        lines.append("实体：" + "、".join(item.get("text", "") for item in nlp["entities"][:20]))
    lines.extend(["", "# 镜头节奏分析", ""])
    lines.append(f"状态：{scenes.get('status', '')}")
    lines.append(f"引擎：{scenes.get('engine', '')}")
    lines.append(f"镜头数：{scenes.get('scene_count', 0)}")
    lines.append(f"切点数：{scenes.get('cut_count', 0)}")
    lines.append(f"平均镜头时长：{scenes.get('average_scene_duration', 0)} 秒")
    lines.append(f"镜头节奏：{scenes.get('pace', '')}")
    return "\n".join(lines).rstrip() + "\n"


def _copy_cover_if_exists(cover_analysis: dict[str, Any], output_dir: Path) -> None:
    image_path = cover_analysis.get("image_path")
    if not image_path:
        return
    source = Path(image_path)
    if source.exists():
        shutil.copy2(source, output_dir / source.name)
