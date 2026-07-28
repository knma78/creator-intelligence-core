from __future__ import annotations

import json

from models import AnalysisResult, Video


def build_markdown(video: Video, analysis: AnalysisResult) -> str:
    return "\n\n".join(
        [
            _video_info(video),
            _summary(analysis),
            _structure(analysis),
            _hook(analysis),
            _rhythm(analysis),
            _emotion(analysis),
            _keywords(analysis),
            _learnings(analysis),
        ]
    ) + "\n"


def _video_info(video: Video) -> str:
    return "\n".join(
        [
            "# 视频信息",
            "",
            f"标题：{video.title}",
            f"作者：{video.author or ''}",
            f"发布时间：{video.publish_time or ''}",
            f"时长：{_format_duration(video.duration)}",
            f"来源：{video.source_url}",
        ]
    )


def _summary(analysis: AnalysisResult) -> str:
    return "\n".join(["# 一句话总结", "", analysis.one_sentence_summary])


def _structure(analysis: AnalysisResult) -> str:
    lines = ["# 内容结构", ""]
    if not analysis.structure:
        lines.append("暂无结构分析。")
        return "\n".join(lines)
    for item in analysis.structure:
        part = item.get("part", "部分")
        time_range = item.get("time_range")
        prefix = f"{part}（{time_range}）" if time_range else str(part)
        lines.append(f"{prefix}：")
        lines.append(str(item.get("summary", "")))
        lines.append("")
    return "\n".join(lines).rstrip()


def _hook(analysis: AnalysisResult) -> str:
    hook = analysis.hook
    return "\n".join(
        [
            "# Hook分析",
            "",
            f"开头方式：{hook.get('开头方式', '')}",
            f"作用：{hook.get('作用', '')}",
            f"评分：{hook.get('评分', '')}",
            f"证据：{hook.get('证据', '')}",
        ]
    )


def _rhythm(analysis: AnalysisResult) -> str:
    rhythm = analysis.rhythm
    return "\n".join(
        [
            "# 节奏分析",
            "",
            f"高潮位置：{rhythm.get('高潮位置', '')}",
            f"转场：{rhythm.get('转场', '')}",
            f"节奏变化：{rhythm.get('节奏变化', '')}",
        ]
    )


def _emotion(analysis: AnalysisResult) -> str:
    emotion = analysis.emotion
    return "\n".join(
        [
            "# 情绪分析",
            "",
            f"整体情绪：{emotion.get('整体情绪', '')}",
            f"情绪变化：{emotion.get('情绪变化', '')}",
        ]
    )


def _keywords(analysis: AnalysisResult) -> str:
    lines = ["# 高频词", ""]
    if not analysis.keywords:
        lines.append("暂无高频词。")
        return "\n".join(lines)
    for item in analysis.keywords:
        lines.append(f"- {item.get('word', '')}：{item.get('count', '')}")
    return "\n".join(lines)


def _learnings(analysis: AnalysisResult) -> str:
    lines = ["# 值得学习", ""]
    if not analysis.learnings:
        lines.append("暂无。")
        return "\n".join(lines)
    for item in analysis.learnings:
        lines.append(f"- {item}")
    return "\n".join(lines)


def _format_duration(value: float | None) -> str:
    if value is None:
        return ""
    seconds = int(value)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Render analysis JSON into Markdown.")
    parser.add_argument("analysis_json")
    parser.add_argument("--title", default="local")
    parser.add_argument("--video-id", default="local")
    args = parser.parse_args()
    analysis = AnalysisResult.from_dict(json.loads(Path(args.analysis_json).read_text(encoding="utf-8")))
    video = Video(source_url="", platform="local", video_id=args.video_id, title=args.title)
    print(build_markdown(video, analysis))
