from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def export_up_profile(profile: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "up_profile.json"
    markdown_path = output_dir / "up_profile.md"
    json_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(build_up_profile_markdown(profile), encoding="utf-8")
    return markdown_path


def build_up_profile_markdown(profile: dict[str, Any]) -> str:
    heading = "YouTube频道画像" if profile.get("platform") == "youtube" else "UP画像"
    lines = [
        f"# {heading}",
        "",
        f"来源：{profile.get('source', '')}",
        f"分析视频数：{profile.get('success_count', 0)} / {profile.get('video_count', 0)}",
        f"失败数：{profile.get('failure_count', 0)}",
        f"平均时长：{_format_duration(profile.get('average_duration'))}",
        "",
        "# 内容关键词",
        "",
    ]
    lines.extend(_bullet_word_counts(profile.get("top_keywords", []), "word"))
    lines.extend(["", "# 标题关键词", ""])
    lines.extend(_bullet_word_counts(profile.get("title_keywords", []), "word"))
    lines.extend(["", "# 常用开头方式", ""])
    lines.extend(_bullet_word_counts(profile.get("hook_styles", []), "style"))
    lines.extend(["", "# 高播放视频", ""])
    for item in profile.get("top_videos_by_view", []):
        view = item.get("view_count")
        view_text = "" if view is None else f"（播放：{view}）"
        lines.append(f"- {item.get('title', '')}{view_text}：{item.get('summary', '')}")
    lines.extend(["", "# 值得学习的共性", ""])
    for item in profile.get("common_learnings", []):
        lines.append(f"- {item.get('learning', '')}（出现 {item.get('count', 0)} 次）")
    if profile.get("failures"):
        lines.extend(["", "# 失败记录", ""])
        for item in profile["failures"]:
            lines.append(f"- {item.get('source_url', '')}：{item.get('error', '')}")
    return "\n".join(lines).rstrip() + "\n"


def _bullet_word_counts(items: list[dict[str, Any]], key: str) -> list[str]:
    if not items:
        return ["暂无。"]
    return [f"- {item.get(key, '')}：{item.get('count', 0)}" for item in items]


def _format_duration(value: Any) -> str:
    if value is None:
        return ""
    seconds = int(float(value))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"
