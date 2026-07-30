from __future__ import annotations

from pathlib import Path
from typing import Any

from infrastructure.atomic_io import atomic_write_json, atomic_write_text


def export_content_profile(
    profile: dict[str, Any],
    output_dir: Path,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "content_profile.json"
    markdown_path = output_dir / "content_profile.md"
    atomic_write_json(json_path, profile)
    atomic_write_text(markdown_path, build_content_profile_markdown(profile))
    return markdown_path


def build_content_profile_markdown(profile: dict[str, Any]) -> str:
    lines = [
        f"# 内容作品画像：{profile.get('subject_name', '未命名作品')}",
        "",
        f"内容类型：{profile.get('content_category_label', '其他内容')}",
        f"平台：{profile.get('platform', 'bilibili')}",
        f"分析视频数：{profile.get('success_count', 0)} / {profile.get('video_count', 0)}",
        f"失败数：{profile.get('failure_count', 0)}",
        f"平均时长：{_format_duration(profile.get('average_duration'))}",
        "",
        "# 内容关键词",
        "",
    ]
    lines.extend(_word_counts(profile.get("top_keywords", []), "word"))
    lines.extend(["", "# 标题关键词", ""])
    lines.extend(_word_counts(profile.get("title_keywords", []), "word"))
    lines.extend(["", "# 常用开头方式", ""])
    lines.extend(_word_counts(profile.get("hook_styles", []), "style"))
    lines.extend(["", "# 值得学习的共性", ""])
    learnings = profile.get("common_learnings", [])
    if learnings:
        for item in learnings:
            lines.append(
                f"- {item.get('learning', '')}（出现 {item.get('count', 0)} 次）"
            )
    else:
        lines.append("暂无。")
    lines.extend(["", "# 已分析内容", ""])
    videos = profile.get("videos", [])
    if videos:
        for item in videos:
            author = f" · {item.get('author')}" if item.get("author") else ""
            lines.append(
                f"- {item.get('title', '')}{author}：{item.get('summary', '')}"
            )
    else:
        lines.append("暂无成功分析的视频。")
    if profile.get("failures"):
        lines.extend(["", "# 失败记录", ""])
        for item in profile["failures"]:
            lines.append(
                f"- {item.get('source_url', '')}：{item.get('error', '')}"
            )
    return "\n".join(lines).rstrip() + "\n"


def _word_counts(items: list[dict[str, Any]], key: str) -> list[str]:
    if not items:
        return ["暂无。"]
    return [
        f"- {item.get(key, '')}：{item.get('count', 0)}"
        for item in items
    ]


def _format_duration(value: Any) -> str:
    if value is None:
        return ""
    seconds = int(float(value))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"
