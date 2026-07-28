from __future__ import annotations

import json
import logging
import re
from typing import Any

from config import Settings
from models import AnalysisResult, Transcript, Video

logger = logging.getLogger(__name__)


def analyze_with_llm(
    video: Video,
    transcript: Transcript,
    baseline: AnalysisResult,
    settings: Settings,
) -> AnalysisResult | None:
    if not settings.llm_api_key:
        return None

    try:
        from openai import OpenAI
    except ImportError as exc:
        logger.warning("OpenAI SDK is not installed, fallback to local analysis: %s", exc)
        return None

    client_kwargs: dict[str, Any] = {
        "api_key": settings.llm_api_key,
        "timeout": settings.llm_timeout,
    }
    if settings.llm_base_url:
        client_kwargs["base_url"] = settings.llm_base_url
    client = OpenAI(**client_kwargs)

    prompt = _build_prompt(video, transcript, baseline, settings.llm_max_chars)
    try:
        response = client.chat.completions.create(
            model=settings.llm_model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "你是一个短视频内容研究分析师。只输出可解析的 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = _loads_json(content)
        return _result_from_llm_dict(video.video_id, video.title, data, baseline)
    except Exception as exc:  # pragma: no cover - network/API behavior
        logger.warning("LLM analysis failed, fallback to local analysis: %s", exc)
        return None


def _build_prompt(
    video: Video,
    transcript: Transcript,
    baseline: AnalysisResult,
    max_chars: int,
) -> str:
    clipped = transcript.text[:max_chars]
    return f"""
请分析下面这个视频字幕，并输出 JSON。不要输出 Markdown。

字段必须包含：
title: 视频标题
one_sentence_summary: 一句话总结
hook: {{"开头方式": "...", "作用": "...", "评分": 1-10, "证据": "..."}}
structure: [{{"part": "第一部分", "time_range": "00:00 - 01:00", "summary": "..."}}]
transitions: ["..."]
emotion: {{"整体情绪": "...", "情绪变化": "..."}}
rhythm: {{"高潮位置": "...", "转场": "...", "节奏变化": "..."}}
keywords: [{{"word": "...", "count": 1}}]
learnings: ["值得学习点"]

视频信息：
标题：{video.title}
作者：{video.author or ""}
发布时间：{video.publish_time or ""}
时长：{video.duration or ""}

本地初步分析：
{json.dumps(baseline.to_dict(), ensure_ascii=False)}

字幕：
{clipped}
""".strip()


def _loads_json(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def _result_from_llm_dict(
    video_id: str,
    fallback_title: str,
    data: dict[str, Any],
    baseline: AnalysisResult,
) -> AnalysisResult:
    return AnalysisResult(
        video_id=video_id,
        title=str(data.get("title") or fallback_title),
        one_sentence_summary=str(
            data.get("one_sentence_summary") or baseline.one_sentence_summary
        ),
        hook=data.get("hook") or baseline.hook,
        structure=data.get("structure") or baseline.structure,
        transitions=data.get("transitions") or baseline.transitions,
        emotion=data.get("emotion") or baseline.emotion,
        rhythm=data.get("rhythm") or baseline.rhythm,
        keywords=data.get("keywords") or baseline.keywords,
        learnings=data.get("learnings") or baseline.learnings,
        raw_llm_result=data,
    )
