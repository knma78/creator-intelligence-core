from __future__ import annotations

from collections import Counter
from statistics import mean
from typing import Any

from analyzer.keywords import extract_keywords
from models import AnalysisResult, Video


def build_up_profile(
    source: str,
    records: list[dict[str, Any]],
    failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    successes = [record for record in records if record.get("video") and record.get("analysis")]
    videos: list[Video] = [record["video"] for record in successes]
    analyses: list[AnalysisResult] = [record["analysis"] for record in successes]

    titles = [video.title for video in videos]
    durations = [video.duration for video in videos if video.duration]
    keyword_counter: Counter[str] = Counter()
    hook_counter: Counter[str] = Counter()
    learnings: Counter[str] = Counter()

    for analysis in analyses:
        for item in analysis.keywords:
            word = str(item.get("word", "")).strip()
            count = int(item.get("count") or 1)
            if word:
                keyword_counter[word] += count
        hook_type = str(analysis.hook.get("开头方式", "")).strip()
        if hook_type:
            hook_counter[hook_type] += 1
        for learning in analysis.learnings:
            learnings[learning] += 1

    title_text = "\n".join(titles)
    return {
        "source": source,
        "video_count": len(records),
        "success_count": len(successes),
        "failure_count": len(failures or []),
        "average_duration": round(mean(durations), 2) if durations else None,
        "top_keywords": [
            {"word": word, "count": count}
            for word, count in keyword_counter.most_common(30)
        ],
        "title_keywords": extract_keywords(title_text, top_n=30) if title_text else [],
        "hook_styles": [
            {"style": style, "count": count}
            for style, count in hook_counter.most_common()
        ],
        "common_learnings": [
            {"learning": learning, "count": count}
            for learning, count in learnings.most_common(20)
        ],
        "top_videos_by_view": _top_videos_by_view(videos, analyses),
        "videos": [
            {
                "video_id": video.video_id,
                "title": video.title,
                "author": video.author,
                "duration": video.duration,
                "publish_time": video.publish_time,
                "stats": video.stats,
                "summary": analysis.one_sentence_summary,
            }
            for video, analysis in zip(videos, analyses)
        ],
        "failures": failures or [],
    }


def _top_videos_by_view(
    videos: list[Video],
    analyses: list[AnalysisResult],
    limit: int = 10,
) -> list[dict[str, Any]]:
    pairs = []
    for video, analysis in zip(videos, analyses):
        view_count = video.stats.get("view_count")
        try:
            views = int(view_count)
        except (TypeError, ValueError):
            views = -1
        pairs.append((views, video, analysis))
    pairs.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "video_id": video.video_id,
            "title": video.title,
            "view_count": None if views < 0 else views,
            "summary": analysis.one_sentence_summary,
        }
        for views, video, analysis in pairs[:limit]
    ]
