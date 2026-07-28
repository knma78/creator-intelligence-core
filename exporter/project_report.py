from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import SETTINGS


def build_project_information_report(
    output_root: Path = SETTINGS.output_dir,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    output_root = output_root.resolve()
    output_dir = (output_dir or output_root / "integrated").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    integrated = _read_json(output_root / "integrated" / "integrated_summary.json")
    creator_manifest = _read_json(output_root / "creator_knowledge_base" / "manifest.json")
    creator_kb = _read_json(output_root / "creator_knowledge_base" / "creator_knowledge_base.json")
    cross = _read_json(output_root / "creator_knowledge_base" / "cross_creator_analysis.json")
    template_library = _read_json(output_root / "creator_knowledge_base" / "templates" / "template_library.json")

    payload = _build_payload(integrated, creator_manifest, creator_kb, cross, template_library, output_root)
    json_path = output_dir / "project_information_integration.json"
    markdown_path = output_dir / "project_information_integration.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_build_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def _build_payload(
    integrated: dict[str, Any],
    creator_manifest: dict[str, Any],
    creator_kb: dict[str, Any],
    cross: dict[str, Any],
    template_library: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    summary = integrated.get("summary", {})
    creators = creator_manifest.get("creators", [])
    creator_by_name = {item.get("author"): item for item in creators}
    alias_to_canonical = _alias_to_canonical(creators)
    author_stats = _merge_author_stats(summary.get("authors", []), alias_to_canonical)
    enriched_creators = []
    for author in author_stats:
        name = author.get("author", "")
        manifest_row = creator_by_name.get(name, {})
        enriched_creators.append(
            {
                "author": name,
                "positioning": manifest_row.get("positioning", "General Creator"),
                "video_count": author.get("video_count", manifest_row.get("video_count", 0)),
                "total_views": author.get("total_views"),
                "average_views": author.get("average_views"),
                "average_duration": author.get("average_duration"),
                "top_video": author.get("top_video", {}),
                "top_keywords": author.get("top_keywords", []),
                "hook_styles": author.get("hook_styles", []),
                "creator_dir": manifest_row.get("creator_dir", ""),
            }
        )

    capability_docs = creator_kb.get("capability_documents", [])
    template_summary = _template_summary(template_library)
    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_generated_at": {
            "integrated": integrated.get("generated_at"),
            "creator_knowledge_base": creator_manifest.get("generated_at"),
        },
        "scope": {
            "video_count": summary.get("video_count", creator_manifest.get("video_count", 0)),
            "up_profile_count": summary.get("up_profile_count"),
            "raw_author_count": summary.get("author_count", creator_manifest.get("creator_count", 0)),
            "author_count": len(enriched_creators) if enriched_creators else summary.get("author_count", creator_manifest.get("creator_count", 0)),
            "creator_profile_count": creator_manifest.get("creator_count", 0),
            "capability_count": len(capability_docs),
            "rag_document_count": (creator_kb.get("rag_index") or {}).get("document_count", 0),
            "template_count": template_summary["template_count"],
            "template_rag_document_count": template_summary["rag_document_count"],
            "date_range": summary.get("date_range", {}),
            "total_views": summary.get("total_views"),
            "total_likes": summary.get("total_likes"),
            "total_comments": summary.get("total_comments"),
            "average_duration": summary.get("average_duration"),
            "cover_ocr_count": summary.get("cover_ocr_count"),
            "missing_target_creators": (cross.get("sample") or {}).get("missing_creators", []),
        },
        "creators": enriched_creators,
        "top_videos_by_view": summary.get("top_videos_by_view", [])[:15],
        "global_signals": {
            "top_keywords": summary.get("top_keywords", [])[:20],
            "title_keywords": summary.get("title_keywords", [])[:20],
            "top_tags": summary.get("top_tags", [])[:20],
            "hook_styles": summary.get("hook_styles", []),
            "rhythm_patterns": summary.get("rhythm_patterns", []),
            "comment_statuses": summary.get("comment_statuses", []),
        },
        "cross_creator": {
            "common_traits": cross.get("共同特点", []),
            "common_structure": cross.get("共同结构", []),
            "common_hooks": cross.get("共同Hook", []),
            "common_transitions": cross.get("共同转场", []),
            "common_climax": cross.get("共同高潮", []),
            "common_endings": cross.get("共同结尾", []),
            "creator_habits": cross.get("共同创作习惯", []),
            "final_synthesis": cross.get("最终提炼", {}),
            "capability_distribution": cross.get("capability_distribution", [])[:20],
        },
        "capability_documents": [
            {
                "category": doc.get("category"),
                "capability": doc.get("capability"),
                "transferable_methods": doc.get("transferable_methods", []),
                "creators": doc.get("creators", []),
                "source_video_count": len(doc.get("source_video_ids", [])),
            }
            for doc in capability_docs
        ],
        "template_library": template_summary,
        "paths": {
            "project_report": str(output_root / "integrated" / "project_information_integration.md"),
            "integrated_report": str(output_root / "integrated" / "integrated_report.md"),
            "video_index_csv": str(output_root / "integrated" / "video_index.csv"),
            "creator_knowledge_base": str(output_root / "creator_knowledge_base" / "creator_knowledge_base.md"),
            "cross_creator_analysis": str(output_root / "creator_knowledge_base" / "cross_creator_analysis.md"),
            "creator_profiles": str(output_root / "creator_knowledge_base" / "creators"),
            "video_capability_reports": str(output_root / "creator_knowledge_base" / "videos"),
            "rag_index": str(output_root / "creator_knowledge_base" / "knowledge_base" / "index.json"),
            "template_library": str(output_root / "creator_knowledge_base" / "templates" / "template_library.md"),
            "template_rag_index": str(output_root / "creator_knowledge_base" / "templates" / "template_index.json"),
        },
        "policy": {
            "can_use": ["能力", "结构", "顺序", "功能", "适用场景", "抽象方法"],
            "do_not_use": ["原文句子", "原文段落", "口头禅", "标题套壳", "具体观点照搬", "个人化语气模仿"],
        },
    }
    payload["gaps"] = _build_gaps(payload, output_root)
    return payload


def _alias_to_canonical(creators: list[dict[str, Any]]) -> dict[str, str]:
    mapping = {}
    for creator in creators:
        author = str(creator.get("author") or "").strip()
        if not author:
            continue
        mapping[author] = author
        for alias in creator.get("aliases", []) + creator.get("source_authors", []):
            alias = str(alias or "").strip()
            if alias:
                mapping[alias] = author
    return mapping


def _merge_author_stats(author_stats: list[dict[str, Any]], alias_to_canonical: dict[str, str]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    duration_weight: dict[str, float] = {}
    for row in author_stats:
        raw_author = str(row.get("author") or "").strip()
        author = alias_to_canonical.get(raw_author, raw_author)
        if author not in merged:
            merged[author] = {
                "author": author,
                "source_authors": [],
                "video_count": 0,
                "total_views": 0,
                "total_likes": 0,
                "total_comments": 0,
                "average_duration": None,
                "top_video": {},
                "top_keywords": [],
                "hook_styles": [],
            }
            duration_weight[author] = 0.0
        bucket = merged[author]
        video_count = int(row.get("video_count") or 0)
        bucket["video_count"] += video_count
        bucket["total_views"] += int(row.get("total_views") or 0)
        bucket["total_likes"] += int(row.get("total_likes") or 0)
        bucket["total_comments"] += int(row.get("total_comments") or 0)
        if raw_author and raw_author not in bucket["source_authors"]:
            bucket["source_authors"].append(raw_author)
        average_duration = row.get("average_duration")
        if average_duration not in (None, "") and video_count:
            duration_weight[author] += float(average_duration) * video_count
        top_video = row.get("top_video") or {}
        if int(top_video.get("view_count") or 0) > int((bucket.get("top_video") or {}).get("view_count") or 0):
            bucket["top_video"] = top_video
        bucket["top_keywords"] = _merge_count_rows(bucket.get("top_keywords", []), row.get("top_keywords", []))
        bucket["hook_styles"] = _merge_count_rows(bucket.get("hook_styles", []), row.get("hook_styles", []))

    for author, bucket in merged.items():
        video_count = int(bucket.get("video_count") or 0)
        bucket["average_views"] = round(bucket["total_views"] / video_count, 2) if video_count else 0
        bucket["average_duration"] = round(duration_weight[author] / video_count, 2) if video_count and duration_weight[author] else None
    return sorted(merged.values(), key=lambda item: item.get("total_views") or 0, reverse=True)


def _merge_count_rows(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter: dict[str, int] = {}
    for item in list(left or []) + list(right or []):
        key = str(item.get("word") or item.get("item") or "").strip()
        if not key:
            continue
        counter[key] = counter.get(key, 0) + int(item.get("count") or 0)
    return [
        {"word": key, "count": count}
        for key, count in sorted(counter.items(), key=lambda item: item[1], reverse=True)
    ]


def _template_summary(template_library: dict[str, Any]) -> dict[str, Any]:
    collections = {}
    template_count = 0
    for key, title in [
        ("hook_templates", "Hook"),
        ("script_structure_templates", "Script Structure"),
        ("transition_templates", "Transition"),
        ("climax_templates", "Climax"),
        ("ending_templates", "Ending"),
        ("workflow_templates", "Workflow"),
    ]:
        count = len(template_library.get(key, []))
        collections[key] = {"title": title, "count": count}
        template_count += count
    return {
        "generated_at": template_library.get("generated_at", ""),
        "template_count": template_count,
        "rag_document_count": (template_library.get("rag_index") or {}).get("document_count", 0),
        "collections": collections,
    }


def _build_markdown(payload: dict[str, Any]) -> str:
    scope = payload["scope"]
    lines = [
        "# 项目提取信息总整合",
        "",
        f"生成时间：{payload['generated_at']}",
        "",
        "## 1. 当前范围",
        "",
        f"- 视频样本：{scope.get('video_count')} 条",
        f"- UP 汇总：{scope.get('up_profile_count')} 个",
        f"- 创作者/作者：{scope.get('author_count')} 个",
        f"- 原始作者名：{scope.get('raw_author_count')} 个",
        f"- Creator Profile：{scope.get('creator_profile_count')} 个",
        f"- 能力分类：{scope.get('capability_count')} 类",
        f"- RAG 文档块：{scope.get('rag_document_count')} 个",
        f"- 可调用模板：{scope.get('template_count')} 个",
        f"- 模板 RAG 文档块：{scope.get('template_rag_document_count')} 个",
        f"- 发布时间范围：{(scope.get('date_range') or {}).get('start', '')} 至 {(scope.get('date_range') or {}).get('end', '')}",
        f"- 总播放：{_format_number(scope.get('total_views'))}",
        f"- 总点赞：{_format_number(scope.get('total_likes'))}",
        f"- 总评论：{_format_number(scope.get('total_comments'))}",
        f"- 平均时长：{_format_duration(scope.get('average_duration'))}",
        f"- 封面 OCR：{scope.get('cover_ocr_count')} / {scope.get('video_count')}",
    ]
    missing = scope.get("missing_target_creators", [])
    if missing:
        lines.append(f"- 指定目标中暂缺：{'、'.join(missing)}")

    lines.extend(
        [
            "",
            "## 2. 创作者地图",
            "",
            "| 创作者 | 定位 | 样本 | 总播放 | 均播 | 平均时长 | 常用开头 | 代表性高频能力线索 |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for creator in payload["creators"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(creator.get("author")),
                    _cell(creator.get("positioning")),
                    str(creator.get("video_count", "")),
                    _format_number(creator.get("total_views")),
                    _format_number(round(creator.get("average_views", 0))),
                    _format_duration(creator.get("average_duration")),
                    _cell(_format_items(creator.get("hook_styles", []), "word", 3)),
                    _cell(_format_items(creator.get("top_keywords", []), "word", 5)),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 3. 样本表现",
            "",
            "| 排名 | 视频 | 作者 | 播放 | 点赞 | 评论 | 开头 |",
            "| ---: | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for index, video in enumerate(payload["top_videos_by_view"][:12], start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _cell(video.get("title")),
                    _cell(video.get("author")),
                    _format_number(video.get("view_count")),
                    _format_number(video.get("like_count")),
                    _format_number(video.get("comment_count")),
                    _cell(video.get("hook_style")),
                ]
            )
            + " |"
        )

    signals = payload["global_signals"]
    lines.extend(
        [
            "",
            "## 4. 全局信号",
            "",
            f"- 高频内容词：{_format_items(signals.get('top_keywords', []), 'word', 12)}",
            f"- 高频标题词：{_format_items(signals.get('title_keywords', []), 'word', 12)}",
            f"- 高频标签：{_format_items(signals.get('top_tags', []), 'word', 12)}",
            f"- Hook 分布：{_format_items(signals.get('hook_styles', []), 'word', 8)}",
            f"- 节奏判断：{_format_items(signals.get('rhythm_patterns', []), 'word', 5)}",
            f"- 评论数据状态：{_format_items(signals.get('comment_statuses', []), 'word', 5)}",
        ]
    )

    cross = payload["cross_creator"]
    lines.extend(["", "## 5. 跨创作者共性", ""])
    for item in cross.get("common_traits", []):
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            f"- 共同结构：{' -> '.join(cross.get('common_structure', []))}",
            f"- 共同 Hook：{_format_items(cross.get('common_hooks', []), 'item', 5)}",
            f"- 共同转场：{_format_items(cross.get('common_transitions', []), 'item', 7)}",
        ]
    )
    for item in cross.get("common_climax", []):
        lines.append(f"- 高潮规律：{item}")
    for item in cross.get("common_endings", []):
        lines.append(f"- 结尾规律：{item}")

    lines.extend(["", "## 6. 能力知识库", ""])
    for doc in payload["capability_documents"]:
        lines.append(
            f"- {doc.get('category')}：{doc.get('capability')}。"
            f" 方法：{'；'.join(doc.get('transferable_methods', []))}。"
            f" 样本：{doc.get('source_video_count')} 条。"
        )

    lines.extend(["", "## 7. 当前最强可迁移能力", ""])
    for item in cross.get("capability_distribution", [])[:15]:
        lines.append(f"- {item.get('item')}（{item.get('count')}）")

    final_synthesis = cross.get("final_synthesis", {})
    lines.extend(["", "## 8. 调用方式", ""])
    for category, value in final_synthesis.items():
        lines.append(f"- {category}：{value}")

    templates = payload.get("template_library", {})
    lines.extend(["", "## 9. 可调用模板库", ""])
    lines.append(f"- 模板总数：{templates.get('template_count', 0)}")
    lines.append(f"- 模板 RAG 文档块：{templates.get('rag_document_count', 0)}")
    for key, value in (templates.get("collections") or {}).items():
        lines.append(f"- {value.get('title', key)}：{value.get('count', 0)} 个")

    gaps = payload.get("gaps", {})
    lines.extend(["", "## 10. 欠缺项与补强优先级", ""])
    for section, title in [
        ("data_gaps", "数据层"),
        ("capability_gaps", "能力层"),
        ("workflow_gaps", "流程层"),
        ("priority_actions", "优先补强"),
    ]:
        items = gaps.get(section, [])
        if not items:
            continue
        lines.extend([f"### {title}", ""])
        for item in items:
            lines.append(f"- {item}")
        lines.append("")

    paths = payload["paths"]
    lines.extend(
        [
            "## 11. 文件入口",
            "",
            f"- 视频/UP基础整合：`{paths['integrated_report']}`",
            f"- 视频索引 CSV：`{paths['video_index_csv']}`",
            f"- 能力知识库：`{paths['creator_knowledge_base']}`",
            f"- 跨创作者分析：`{paths['cross_creator_analysis']}`",
            f"- 创作者画像目录：`{paths['creator_profiles']}`",
            f"- 单视频能力分析目录：`{paths['video_capability_reports']}`",
            f"- RAG 索引：`{paths['rag_index']}`",
            f"- 可调用模板库：`{paths['template_library']}`",
            f"- 模板 RAG 索引：`{paths['template_rag_index']}`",
            "",
            "## 12. 使用边界",
            "",
            f"- 可以调用：{'、'.join(payload['policy']['can_use'])}",
            f"- 不要调用：{'、'.join(payload['policy']['do_not_use'])}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _build_gaps(payload: dict[str, Any], output_root: Path) -> dict[str, list[str]]:
    scope = payload.get("scope", {})
    signals = payload.get("global_signals", {})
    creators = payload.get("creators", [])
    capabilities = payload.get("capability_documents", [])
    templates = payload.get("template_library", {})
    video_count = int(scope.get("video_count") or 0)
    cover_count = int(scope.get("cover_ocr_count") or 0)
    comment_statuses = {
        str(item.get("word") or item.get("item")): int(item.get("count") or 0)
        for item in signals.get("comment_statuses", [])
    }
    skipped_comments = comment_statuses.get("skipped", 0)
    unknown_comments = comment_statuses.get("unknown", 0)
    general_creators = [item for item in creators if item.get("positioning") == "General Creator"]
    low_sample_creators = [
        item for item in creators if int(item.get("video_count") or 0) < 5
    ]
    low_capability_docs = [
        item for item in capabilities if int(item.get("source_video_count") or 0) < 10
    ]
    cache_root = output_root.parent / "cache"
    media_count = _count_files(cache_root / "videos", {".mp4", ".mkv", ".webm", ".wav", ".mp3", ".m4a"})
    transcript_count = _count_files(cache_root / "transcripts", None)
    output_subtitles = 0
    if output_root.exists():
        for child in output_root.iterdir():
            if child.is_dir() and child.name.startswith("BV"):
                output_subtitles += sum(1 for name in ("subtitle.txt", "subtitle.srt") if (child / name).exists())

    data_gaps = []
    if skipped_comments or unknown_comments:
        data_gaps.append(
            f"评论正文分析不足：{skipped_comments} 条 skipped，{unknown_comments} 条 unknown；目前只能较可靠地使用评论数，不能稳定分析观众情绪和反馈动机。"
        )
    if video_count and cover_count < video_count:
        data_gaps.append(
            f"封面 OCR 未完全覆盖：{cover_count} / {video_count}；仍有 {video_count - cover_count} 条缺少可用封面文字信号。"
        )
    if media_count or transcript_count or output_subtitles:
        data_gaps.append(
            f"原始/中间文件状态不统一：仍有 {media_count} 个媒体文件、{transcript_count} 个 transcript 缓存文件、{output_subtitles} 个 output 字幕文件；后续要么统一保留用于复核，要么按你的指令继续清理。"
        )

    capability_gaps = []
    if general_creators:
        capability_gaps.append(
            "仍有创作者停留在 General Creator："
            + "、".join(f"{item.get('author')}({item.get('video_count')})" for item in general_creators)
            + "；需要补充更细的 Creator Spec，才能形成更准确的专项能力画像。"
        )
    if low_sample_creators:
        capability_gaps.append(
            "低样本创作者画像稳定性不足："
            + "、".join(f"{item.get('author')}({item.get('video_count')})" for item in low_sample_creators)
            + "；建议至少补到 5-10 条。"
        )
    if low_capability_docs:
        capability_gaps.append(
            "低样本能力类："
            + "、".join(f"{item.get('category')}({item.get('source_video_count')})" for item in low_capability_docs)
            + "；这些能力目前只能作为初步参考。"
        )
    if "Transition" in {item.get("category") for item in capabilities}:
        transition_docs = [item for item in capabilities if item.get("category") == "Transition"]
        if transition_docs and transition_docs[0].get("source_video_count", 0) < video_count // 2:
            capability_gaps.append(
                "Transition 能力文档关联样本偏少，但跨创作者统计显示转场功能普遍存在；应扩展各细分定位的转场检测和段落功能标注。"
            )

    workflow_gaps = [
        "当前 Creator Knowledge Base 是结构化/启发式抽象，仍缺少人工复核后的代表样本标注。",
    ]
    if int(templates.get("template_count") or 0) <= 0:
        workflow_gaps.append(
            "RAG 索引已有能力文档，但还没有按具体创作任务生成模板库，例如选题模板、脚本模板、分镜模板、封面模板。"
        )
    else:
        workflow_gaps.append(
            "模板库已生成，但仍需要用真实选题做调用测试，验证每类模板的输入槽位、节奏长度和检查标准是否足够稳定。"
        )
    if int(scope.get("raw_author_count") or 0) > int(scope.get("author_count") or 0):
        workflow_gaps.append(
            f"作者别名已启用归一：原始作者名 {scope.get('raw_author_count')} 个，归一后 {scope.get('author_count')} 个；后续新增 UP 时仍应维护 `tools/creator_specs.json`。"
        )

    priority_actions = []
    if general_creators:
        priority_actions.append(
            "先补齐 General Creator 的细分定位，把它们归入财经解释、国际观察、影视工业、历史长叙事、短科普等更精确类别。"
        )
    else:
        priority_actions.append(
            "继续维护 `tools/creator_specs.json`，新增 UP 时先确定定位、别名和主要能力，避免画像再次分裂。"
        )
    priority_actions.extend(
        [
            "补评论抓取或评论摘要，建立观众反馈知识层。",
            "补封面/画面层分析，尤其是毕导、影视飓风、食贫道这类视觉权重较高的样本。",
            "用真实选题跑一轮模板调用测试，优先验证 Hook、转场、高潮、结尾和脚本结构模板。",
        ]
    )

    return {
        "data_gaps": data_gaps,
        "capability_gaps": capability_gaps,
        "workflow_gaps": workflow_gaps,
        "priority_actions": priority_actions,
    }


def _count_files(root: Path, suffixes: set[str] | None) -> int:
    if not root.exists():
        return 0
    count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if suffixes is None or path.suffix.lower() in suffixes:
            count += 1
    return count


def _format_items(items: list[dict[str, Any]], key: str, limit: int) -> str:
    selected = items[:limit]
    return "、".join(
        f"{item.get(key) or item.get('item') or item.get('word')}({item.get('count')})"
        for item in selected
        if item.get(key) or item.get("item") or item.get("word")
    ) or "暂无"


def _format_number(value: Any) -> str:
    try:
        if value in (None, ""):
            return ""
        return f"{int(float(value)):,}"
    except (TypeError, ValueError):
        return str(value)


def _format_duration(value: Any) -> str:
    try:
        if value in (None, ""):
            return ""
        seconds = int(float(value))
    except (TypeError, ValueError):
        return str(value)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\r", " ").replace("\n", "<br>").replace("|", "\\|")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the project-level information integration report.")
    parser.add_argument("--output-root", default=str(SETTINGS.output_dir))
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()
    result = build_project_information_report(
        Path(args.output_root),
        Path(args.output_dir) if args.output_dir else None,
    )
    for kind, path in result.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
