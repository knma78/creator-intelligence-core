from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from config import SETTINGS


def integrate_outputs(
    output_root: Path = SETTINGS.output_dir,
    cache_root: Path | None = None,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    output_root = output_root.resolve()
    cache_root = (cache_root or output_root.parent / "cache").resolve()
    output_dir = (output_dir or output_root / "integrated").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    up_profiles, video_context = _load_up_profiles(output_root)
    videos = _load_videos(output_root, cache_root, video_context)
    summary = _build_summary(videos, up_profiles)

    json_path = output_dir / "integrated_summary.json"
    csv_path = output_dir / "video_index.csv"
    markdown_path = output_dir / "integrated_report.md"

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "output_root": str(output_root),
        "cache_root": str(cache_root),
        "summary": summary,
        "up_profiles": up_profiles,
        "videos": videos,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_video_csv(csv_path, videos)
    markdown_path.write_text(_build_markdown_report(payload), encoding="utf-8")
    return {"json": json_path, "csv": csv_path, "markdown": markdown_path}


def _load_up_profiles(output_root: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    profiles: list[dict[str, Any]] = []
    video_context: dict[str, dict[str, Any]] = {}
    for profile_path in sorted(output_root.glob("up_*/up_profile.json")):
        profile = _read_json(profile_path)
        up_id = profile_path.parent.name.removeprefix("up_")
        videos = profile.get("videos", [])
        authors = Counter(str(video.get("author", "")).strip() for video in videos if video.get("author"))
        author = authors.most_common(1)[0][0] if authors else ""
        profile_summary = {
            "up_id": up_id,
            "source": profile.get("source", ""),
            "author": author,
            "video_count": profile.get("video_count", 0),
            "success_count": profile.get("success_count", 0),
            "failure_count": profile.get("failure_count", 0),
            "average_duration": profile.get("average_duration"),
            "top_keywords": profile.get("top_keywords", [])[:20],
            "title_keywords": profile.get("title_keywords", [])[:20],
            "hook_styles": profile.get("hook_styles", []),
            "top_videos_by_view": profile.get("top_videos_by_view", [])[:10],
            "common_learnings": profile.get("common_learnings", [])[:12],
            "profile_path": str(profile_path),
        }
        profiles.append(profile_summary)
        for video in videos:
            video_id = str(video.get("video_id", "")).strip()
            if not video_id:
                continue
            video_context[video_id] = {
                "up_id": up_id,
                "up_source": profile.get("source", ""),
                "profile_author": author,
                "profile_title": video.get("title", ""),
                "profile_summary": video.get("summary", ""),
                "profile_publish_time": video.get("publish_time"),
                "profile_duration": video.get("duration"),
                "profile_stats": video.get("stats", {}),
            }
    return profiles, video_context


def _load_videos(
    output_root: Path,
    cache_root: Path,
    video_context: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    for video_dir in sorted(path for path in output_root.iterdir() if path.is_dir()):
        analysis_path = video_dir / "analysis.json"
        if not analysis_path.exists():
            continue
        video_id = video_dir.name
        analysis = _read_json(analysis_path)
        v3 = _read_json(video_dir / "v3.json")
        metadata = _read_json(cache_root / "videos" / video_id / "metadata.json")
        context = video_context.get(video_id, {})
        stats = _merge_dicts(
            metadata.get("stats", {}),
            context.get("profile_stats", {}),
        )
        extra_metadata = metadata.get("extra_metadata", {})
        title = (
            analysis.get("title")
            or context.get("profile_title")
            or metadata.get("title")
            or video_id
        )
        author = (
            metadata.get("author")
            or context.get("profile_author")
            or ""
        )
        duration = _first_present(
            metadata.get("duration"),
            context.get("profile_duration"),
            stats.get("duration"),
        )
        comments_analysis = v3.get("comments_analysis", {})
        cover_analysis = v3.get("cover_analysis", {})
        ocr = cover_analysis.get("ocr", {}) if isinstance(cover_analysis, dict) else {}
        title_stats = v3.get("title_stats", {})
        keywords = analysis.get("keywords", [])
        top_keywords = [item.get("word", "") for item in keywords[:8] if item.get("word")]
        row = {
            "video_id": video_id,
            "title": title,
            "author": author,
            "up_id": context.get("up_id", "unassigned"),
            "up_source": context.get("up_source", ""),
            "source_url": metadata.get("source_url", extra_metadata.get("webpage_url", "")),
            "publish_time": _first_present(metadata.get("publish_time"), context.get("profile_publish_time"), ""),
            "duration": duration,
            "duration_text": _format_duration(duration),
            "view_count": _int_or_none(stats.get("view_count")),
            "like_count": _int_or_none(stats.get("like_count")),
            "comment_count": _int_or_none(stats.get("comment_count")),
            "like_rate": _rate(stats.get("like_count"), stats.get("view_count")),
            "comment_rate": _rate(stats.get("comment_count"), stats.get("view_count")),
            "summary": analysis.get("one_sentence_summary") or context.get("profile_summary", ""),
            "hook_style": (analysis.get("hook") or {}).get("开头方式", ""),
            "hook_score": (analysis.get("hook") or {}).get("评分"),
            "rhythm_peak": (analysis.get("rhythm") or {}).get("高潮位置", ""),
            "rhythm_change": (analysis.get("rhythm") or {}).get("节奏变化", ""),
            "emotion": (analysis.get("emotion") or {}).get("整体情绪", ""),
            "top_keywords": top_keywords,
            "keyword_counts": keywords[:12],
            "transitions": analysis.get("transitions", []),
            "structure_count": len(analysis.get("structure", [])),
            "learnings": analysis.get("learnings", []),
            "cover_ocr": str(ocr.get("text", "")).strip(),
            "cover_brightness": cover_analysis.get("brightness") if isinstance(cover_analysis, dict) else None,
            "cover_contrast": cover_analysis.get("contrast") if isinstance(cover_analysis, dict) else None,
            "cover_dominant_colors": cover_analysis.get("dominant_colors", [])[:5] if isinstance(cover_analysis, dict) else [],
            "comments_status": comments_analysis.get("status", ""),
            "comments_fetched": comments_analysis.get("comment_count", 0),
            "comments_sentiment": comments_analysis.get("sentiment", ""),
            "title_length": title_stats.get("average_length"),
            "title_patterns": title_stats.get("patterns", []),
            "tags": extra_metadata.get("tags", []),
            "analysis_path": str(analysis_path),
            "v3_path": str(video_dir / "v3.json") if (video_dir / "v3.json").exists() else "",
            "video_markdown_path": str(video_dir / "video.md") if (video_dir / "video.md").exists() else "",
            "subtitle_path": str(video_dir / "subtitle.txt") if (video_dir / "subtitle.txt").exists() else "",
            "cover_path": str(video_dir / "cover.jpg") if (video_dir / "cover.jpg").exists() else "",
        }
        rows.append(row)
    rows.sort(key=lambda item: (_date_key(item.get("publish_time")), item.get("video_id", "")), reverse=True)
    return rows


def _build_summary(videos: list[dict[str, Any]], up_profiles: list[dict[str, Any]]) -> dict[str, Any]:
    view_counts = [_int for video in videos if (_int := _int_or_none(video.get("view_count"))) is not None]
    durations = [_float for video in videos if (_float := _float_or_none(video.get("duration"))) is not None]
    publish_dates = [str(video.get("publish_time")) for video in videos if video.get("publish_time")]
    keyword_counter: Counter[str] = Counter()
    title_keyword_counter: Counter[str] = Counter()
    hook_counter: Counter[str] = Counter()
    tag_counter: Counter[str] = Counter()
    author_counter: Counter[str] = Counter()
    comment_status_counter: Counter[str] = Counter()
    rhythm_counter: Counter[str] = Counter()
    by_author: dict[str, dict[str, Any]] = defaultdict(lambda: {"video_count": 0, "views": 0, "likes": 0, "comments": 0, "durations": []})

    for video in videos:
        author = video.get("author") or "未知作者"
        author_counter[author] += 1
        stats = by_author[author]
        stats["video_count"] += 1
        stats["views"] += _int_or_zero(video.get("view_count"))
        stats["likes"] += _int_or_zero(video.get("like_count"))
        stats["comments"] += _int_or_zero(video.get("comment_count"))
        duration = _float_or_none(video.get("duration"))
        if duration is not None:
            stats["durations"].append(duration)
        hook_style = str(video.get("hook_style", "")).strip()
        if hook_style:
            hook_counter[hook_style] += 1
        rhythm = str(video.get("rhythm_change", "")).strip()
        if rhythm:
            rhythm_counter[rhythm] += 1
        status = str(video.get("comments_status", "")).strip() or "unknown"
        comment_status_counter[status] += 1
        for item in video.get("keyword_counts", []):
            word = str(item.get("word", "")).strip()
            count = _int_or_zero(item.get("count")) or 1
            if word:
                keyword_counter[word] += count
        for token in _title_tokens(str(video.get("title", ""))):
            title_keyword_counter[token] += 1
        for tag in video.get("tags", []):
            tag = str(tag).strip()
            if tag:
                tag_counter[tag] += 1

    author_summary = []
    for author, stats in by_author.items():
        author_videos = [video for video in videos if (video.get("author") or "未知作者") == author]
        top_video = max(author_videos, key=lambda item: _int_or_zero(item.get("view_count")), default={})
        author_summary.append(
            {
                "author": author,
                "video_count": stats["video_count"],
                "total_views": stats["views"],
                "average_views": round(stats["views"] / stats["video_count"], 2) if stats["video_count"] else 0,
                "total_likes": stats["likes"],
                "total_comments": stats["comments"],
                "average_duration": round(mean(stats["durations"]), 2) if stats["durations"] else None,
                "top_video": {
                    "video_id": top_video.get("video_id", ""),
                    "title": top_video.get("title", ""),
                    "view_count": top_video.get("view_count"),
                },
                "top_keywords": _top_keywords_for_videos(author_videos, 8),
                "hook_styles": _counter_for(author_videos, "hook_style", 5),
            }
        )
    author_summary.sort(key=lambda item: item["total_views"], reverse=True)

    unassigned = [video.get("video_id") for video in videos if video.get("up_id") == "unassigned"]
    return {
        "video_count": len(videos),
        "up_profile_count": len(up_profiles),
        "author_count": len(author_counter),
        "date_range": {
            "start": min(publish_dates) if publish_dates else "",
            "end": max(publish_dates) if publish_dates else "",
        },
        "total_views": sum(view_counts),
        "average_views": round(mean(view_counts), 2) if view_counts else 0,
        "median_views": round(median(view_counts), 2) if view_counts else 0,
        "total_likes": sum(_int_or_zero(video.get("like_count")) for video in videos),
        "total_comments": sum(_int_or_zero(video.get("comment_count")) for video in videos),
        "average_duration": round(mean(durations), 2) if durations else None,
        "top_keywords": _counter_items(keyword_counter, 30),
        "title_keywords": _counter_items(title_keyword_counter, 25),
        "top_tags": _counter_items(tag_counter, 25),
        "hook_styles": _counter_items(hook_counter, 10),
        "rhythm_patterns": _counter_items(rhythm_counter, 10),
        "comment_statuses": _counter_items(comment_status_counter, 10),
        "cover_ocr_count": sum(1 for video in videos if video.get("cover_ocr")),
        "unassigned_videos": unassigned,
        "authors": author_summary,
        "top_videos_by_view": _top_videos(videos, "view_count", 12),
        "top_videos_by_like_rate": _top_videos(videos, "like_rate", 8),
        "top_videos_by_comment_rate": _top_videos(videos, "comment_rate", 8),
    }


def _write_video_csv(path: Path, videos: list[dict[str, Any]]) -> None:
    columns = [
        ("video_id", "视频ID"),
        ("up_id", "UP_ID"),
        ("author", "作者"),
        ("publish_time", "发布时间"),
        ("title", "标题"),
        ("duration_text", "时长"),
        ("view_count", "播放"),
        ("like_count", "点赞"),
        ("comment_count", "评论"),
        ("like_rate", "点赞率"),
        ("comment_rate", "评论率"),
        ("hook_style", "开头方式"),
        ("rhythm_peak", "高潮位置"),
        ("rhythm_change", "节奏变化"),
        ("emotion", "整体情绪"),
        ("top_keywords", "高频词"),
        ("cover_ocr", "封面OCR"),
        ("comments_status", "评论抓取状态"),
        ("summary", "一句话总结"),
        ("tags", "标签"),
        ("source_url", "来源"),
        ("video_markdown_path", "Markdown路径"),
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[label for _, label in columns])
        writer.writeheader()
        for video in videos:
            writer.writerow(
                {
                    label: _csv_value(video.get(key))
                    for key, label in columns
                }
            )


def _build_markdown_report(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    videos = payload["videos"]
    up_profiles = payload["up_profiles"]
    lines = [
        "# 项目提取信息整合",
        "",
        f"生成时间：{payload['generated_at']}",
        f"输出目录：{payload['output_root']}",
        "",
        "## 样本概览",
        "",
        f"- 视频输出：{summary['video_count']} 条",
        f"- UP 汇总：{summary['up_profile_count']} 个",
        f"- 作者/频道：{summary['author_count']} 个",
        f"- 发布时间范围：{summary['date_range']['start']} 至 {summary['date_range']['end']}",
        f"- 总播放：{_format_number(summary['total_views'])}",
        f"- 总点赞：{_format_number(summary['total_likes'])}",
        f"- 总评论：{_format_number(summary['total_comments'])}",
        f"- 平均时长：{_format_duration(summary['average_duration'])}",
        f"- 已识别封面 OCR：{summary['cover_ocr_count']} / {summary['video_count']}",
    ]
    if summary["unassigned_videos"]:
        lines.append(f"- 未归属到 UP 批量汇总的视频：{', '.join(summary['unassigned_videos'])}")
    lines.extend(
        [
            "",
            "## 作者与UP概览",
            "",
            "| 作者 | 样本数 | 总播放 | 均播 | 平均时长 | 最高播放视频 | 高频内容词 | 常用开头 |",
            "| --- | ---: | ---: | ---: | ---: | --- | --- | --- |",
        ]
    )
    for author in summary["authors"]:
        top_video = author.get("top_video", {})
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(author.get("author")),
                    str(author.get("video_count", 0)),
                    _format_number(author.get("total_views")),
                    _format_number(round(author.get("average_views", 0))),
                    _format_duration(author.get("average_duration")),
                    _md_cell(f"{top_video.get('title', '')}（{_format_number(top_video.get('view_count'))}）"),
                    _md_cell(_format_word_counts(author.get("top_keywords", []), 6)),
                    _md_cell(_format_word_counts(author.get("hook_styles", []), 3)),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 全局信号",
            "",
            f"- 高频内容词：{_format_word_counts(summary['top_keywords'], 20)}",
            f"- 高频标题词：{_format_word_counts(summary['title_keywords'], 18)}",
            f"- 高频标签：{_format_word_counts(summary['top_tags'], 18)}",
            f"- 开头方式：{_format_word_counts(summary['hook_styles'], 8)}",
            f"- 节奏判断：{_format_word_counts(summary['rhythm_patterns'], 5)}",
            f"- 评论抓取状态：{_format_word_counts(summary['comment_statuses'], 5)}",
            "",
            "## 播放表现Top",
            "",
            "| 排名 | 视频 | 作者 | 发布时间 | 播放 | 点赞 | 评论 | 开头方式 | 高频词 |",
            "| ---: | --- | --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for index, video in enumerate(summary["top_videos_by_view"], start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _video_link_cell(video),
                    _md_cell(video.get("author")),
                    _md_cell(video.get("publish_time")),
                    _format_number(video.get("view_count")),
                    _format_number(video.get("like_count")),
                    _format_number(video.get("comment_count")),
                    _md_cell(video.get("hook_style")),
                    _md_cell("、".join(video.get("top_keywords", [])[:5])),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 可复用结论",
            "",
        ]
    )
    lines.extend(_build_strategy_lines(summary, up_profiles))
    lines.extend(
        [
            "",
            "## 封面OCR摘录",
            "",
        ]
    )
    cover_rows = [video for video in videos if video.get("cover_ocr")]
    for video in cover_rows[:20]:
        lines.append(f"- {video['title']}：{_inline(video['cover_ocr'])}")
    if len(cover_rows) > 20:
        lines.append(f"- 其余 {len(cover_rows) - 20} 条见 JSON 明细。")
    lines.extend(
        [
            "",
            "## 全量视频索引",
            "",
            "| 视频ID | 作者 | 发布时间 | 标题 | 播放 | 时长 | 开头方式 | 高频词 | 文件 |",
            "| --- | --- | --- | --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for video in videos:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(video.get("video_id")),
                    _md_cell(video.get("author")),
                    _md_cell(video.get("publish_time")),
                    _md_cell(video.get("title")),
                    _format_number(video.get("view_count")),
                    _format_duration(video.get("duration")),
                    _md_cell(video.get("hook_style")),
                    _md_cell("、".join(video.get("top_keywords", [])[:5])),
                    _md_cell(video.get("video_markdown_path")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 数据质量说明",
            "",
            "- 本报告只整合本地已生成的 output/cache 文件，没有重新抓取网络数据。",
            "- 评论区正文抓取多为 skipped，当前更可靠的是视频元数据里的评论数，而不是评论内容分析。",
            "- `BV19V411s7tZ` 是单独视频输出，不属于当前 3 个 UP 批量 manifest，但已纳入全局统计。",
            "- CSV 适合筛选排序；JSON 保留了更多结构化字段；Markdown 用于快速阅读。",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _build_strategy_lines(summary: dict[str, Any], up_profiles: list[dict[str, Any]]) -> list[str]:
    hooks = summary.get("hook_styles", [])
    top_hook = hooks[0]["word"] if hooks else "冲突/反差式开头"
    lines = [
        f"- 样本最稳定的开头套路是“{top_hook}”：先抛出反常识、强后果或悬念，再回到解释链路。",
        "- 历史类长视频依赖人物/国家/危机事件做主线，适合用“败局、囚、危机、强拆、逆袭”这类高冲突词承载题眼。",
        "- 宇宙科普类短中视频更适合“奇葩天体、最新研究、能否存在生命、另一个太阳系”等问题型或反差型题眼。",
        "- 标题常见组合是“强对象 + 强结果/强疑问 + 系列名”，系列名既做栏目识别，也降低用户理解成本。",
        "- 节奏分析里“整体信息密度较均衡”占主导，说明这些样本不是靠短促爆点堆叠，而是靠连续解释和结构分段维持完播。",
        "- 封面 OCR 基本都能读到核心题眼，封面文字应继续保持短句化，优先复述标题里最强的那组名词或冲突。",
    ]
    for profile in up_profiles:
        author = profile.get("author") or profile.get("up_id")
        keywords = _format_word_counts(profile.get("top_keywords", []), 8)
        title_keywords = _format_word_counts(profile.get("title_keywords", []), 6)
        lines.append(f"- {author}：内容词集中在 {keywords}；标题词集中在 {title_keywords}。")
    return lines


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _merge_dicts(primary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(fallback or {})
    merged.update({key: value for key, value in (primary or {}).items() if value is not None})
    return merged


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _int_or_zero(value: Any) -> int:
    return _int_or_none(value) or 0


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _rate(numerator: Any, denominator: Any) -> float | None:
    numerator_value = _float_or_none(numerator)
    denominator_value = _float_or_none(denominator)
    if numerator_value is None or not denominator_value:
        return None
    return round(numerator_value / denominator_value, 6)


def _date_key(value: Any) -> str:
    return str(value or "0000-00-00")


def _title_tokens(title: str) -> list[str]:
    tokens = []
    for item in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_+-]{2,}", title):
        if re.fullmatch(r"[\u4e00-\u9fff]+", item):
            tokens.extend(item[index : index + 2] for index in range(max(0, len(item) - 1)))
        else:
            tokens.append(item.lower())
    return [token for token in tokens if token.strip()]


def _counter_items(counter: Counter[str], limit: int) -> list[dict[str, Any]]:
    return [{"word": word, "count": count} for word, count in counter.most_common(limit)]


def _counter_for(videos: list[dict[str, Any]], field: str, limit: int) -> list[dict[str, Any]]:
    counter = Counter(str(video.get(field, "")).strip() for video in videos if video.get(field))
    return _counter_items(counter, limit)


def _top_keywords_for_videos(videos: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for video in videos:
        for item in video.get("keyword_counts", []):
            word = str(item.get("word", "")).strip()
            count = _int_or_zero(item.get("count")) or 1
            if word:
                counter[word] += count
    return _counter_items(counter, limit)


def _top_videos(videos: list[dict[str, Any]], key: str, limit: int) -> list[dict[str, Any]]:
    def value(video: dict[str, Any]) -> float:
        return _float_or_none(video.get(key)) or 0

    fields = [
        "video_id",
        "title",
        "author",
        "publish_time",
        "duration_text",
        "view_count",
        "like_count",
        "comment_count",
        "like_rate",
        "comment_rate",
        "hook_style",
        "top_keywords",
        "video_markdown_path",
        "source_url",
    ]
    return [
        {field: video.get(field) for field in fields}
        for video in sorted(videos, key=value, reverse=True)[:limit]
    ]


def _format_duration(value: Any) -> str:
    seconds_float = _float_or_none(value)
    if seconds_float is None:
        return ""
    seconds = int(seconds_float)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


def _format_number(value: Any) -> str:
    number = _int_or_none(value)
    if number is None:
        return ""
    return f"{number:,}"


def _format_word_counts(items: list[dict[str, Any]], limit: int) -> str:
    selected = items[:limit]
    return "、".join(f"{item.get('word')}({item.get('count')})" for item in selected if item.get("word")) or "暂无"


def _csv_value(value: Any) -> Any:
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            return "；".join(
                f"{item.get('word') or item.get('style') or item.get('text') or ''}:{item.get('count', '')}"
                for item in value
            )
        return "、".join(str(item) for item in value)
    if value is None:
        return ""
    return value


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", " ").replace("\n", "<br>")
    return text.replace("|", "\\|")


def _video_link_cell(video: dict[str, Any]) -> str:
    title = _md_cell(video.get("title", ""))
    path = video.get("video_markdown_path")
    if path:
        return f"[{title}]({path})"
    return title


def _inline(value: Any) -> str:
    return str(value).replace("\r", " ").replace("\n", " / ").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Integrate local content research outputs.")
    parser.add_argument("--output-root", default=str(SETTINGS.output_dir))
    parser.add_argument("--cache-root", default=str(SETTINGS.cache_dir))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()

    paths = integrate_outputs(
        output_root=Path(args.output_root),
        cache_root=Path(args.cache_root),
        output_dir=Path(args.output_dir) if args.output_dir else None,
    )
    for kind, path in paths.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
