from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any

from config import SETTINGS
from exporter.integrated import _load_up_profiles, _load_videos


CAPABILITY_CATEGORIES = [
    "Storytelling",
    "Logic",
    "Emotion",
    "Hook",
    "Rhythm",
    "Transition",
    "Ending",
    "Visualization",
    "World Building",
    "Character",
    "Explanation",
    "Teaching",
    "Plot Analysis",
    "Anime Narrative",
    "Science Narrative",
    "Historical Narrative",
    "Narration",
]


CREATOR_SPECS_PATH = SETTINGS.base_dir / "tools" / "creator_specs.json"


DEFAULT_CREATOR_SPECS: dict[str, dict[str, Any]] = {
    "小约翰可汗": {
        "required": True,
        "positioning": "Storytelling",
        "profile_name": "Storytelling Profile",
        "target_audience": "喜欢人物、国家和事件故事的知识型观众",
        "primary_categories": ["Storytelling", "Hook", "Rhythm", "Character", "Ending", "Transition"],
    },
    "历史调研室": {
        "required": True,
        "positioning": "Logical Narrative",
        "profile_name": "Logical Narrative Profile",
        "target_audience": "希望理解历史事件因果链和背景结构的观众",
        "primary_categories": ["Logic", "Historical Narrative", "Narration", "Transition", "Ending"],
    },
    "Linvo说宇宙": {
        "required": True,
        "aliases": ["Liovo讲宇宙", "Linvo说宇宙"],
        "positioning": "Science Explanation",
        "profile_name": "Science Explanation Profile",
        "target_audience": "对宇宙、科学概念和新研究感兴趣的泛知识观众",
        "primary_categories": ["Explanation", "Science Narrative", "Hook", "Teaching", "World Building"],
    },
    "食贫道": {
        "required": True,
        "positioning": "Emotion Narrative",
        "profile_name": "Emotion Narrative Profile",
        "target_audience": "关注现实人物、社会现场和纪录片表达的观众",
        "primary_categories": ["Emotion", "Narration", "Character", "Visualization", "Ending"],
    },
    "毕导": {
        "required": True,
        "positioning": "Visual Teaching",
        "profile_name": "Visual Teaching Profile",
        "target_audience": "喜欢用视觉化、实验化方式理解知识的观众",
        "primary_categories": ["Visualization", "Teaching", "Explanation", "Rhythm", "Hook"],
    },
    "木鱼水心": {
        "required": True,
        "positioning": "Story Analysis",
        "profile_name": "Story Analysis Profile",
        "target_audience": "希望理解影视剧情、人物和主题表达的观众",
        "primary_categories": ["Plot Analysis", "Character", "World Building", "Emotion", "Ending"],
    },
    "五个光": {
        "required": True,
        "positioning": "Anime Narrative",
        "profile_name": "Anime Narrative Profile",
        "target_audience": "希望快速进入动漫剧情、人物动机和世界观的观众",
        "primary_categories": ["Anime Narrative", "Plot Analysis", "World Building", "Character", "Hook", "Rhythm"],
    },
}


CREATOR_SPECS = DEFAULT_CREATOR_SPECS


HOOK_CAPABILITIES = {
    "冲突/反差式开头": "用反差、风险或异常现象制造信息缺口",
    "问题式开头": "用明确问题建立观看任务",
    "直接抛出主题": "快速交代对象和分析任务",
}


TRANSITION_FUNCTIONS = {
    "首先": "顺序启动",
    "其次": "并列递进",
    "然后": "过程推进",
    "但是": "转折校正",
    "不过": "转折校正",
    "所以": "因果收束",
    "因此": "因果收束",
    "比如": "举例说明",
    "然而": "反向推进",
    "最后": "结尾收束",
    "总之": "结论归纳",
}


def build_creator_knowledge_base(
    output_root: Path = SETTINGS.output_dir,
    cache_root: Path | None = None,
    output_dir: Path | None = None,
    cache_kb_dir: Path | None = None,
    creator_specs_path: Path | None = None,
) -> dict[str, Path]:
    output_root = output_root.resolve()
    cache_root = (cache_root or output_root.parent / "cache").resolve()
    output_dir = (output_dir or output_root / "creator_knowledge_base").resolve()
    cache_kb_dir = (cache_kb_dir or cache_root / "creator_knowledge_base").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_kb_dir.mkdir(parents=True, exist_ok=True)

    creator_specs = load_creator_specs(creator_specs_path)
    up_profiles, video_context = _load_up_profiles(output_root)
    videos = _load_videos(output_root, cache_root, video_context)
    video_records = [_build_video_record(video, creator_specs) for video in videos]
    creator_profiles = _build_creator_profiles(video_records, up_profiles, creator_specs)
    cross_analysis = _build_cross_creator_analysis(creator_profiles, video_records, creator_specs)
    knowledge_base = _build_capability_knowledge_base(video_records, creator_profiles, cross_analysis)

    video_root = output_dir / "videos"
    creator_root = output_dir / "creators"
    _write_video_outputs(video_root, video_records)
    creator_paths = _write_creator_outputs(creator_root, creator_profiles)

    cross_json = output_dir / "cross_creator_analysis.json"
    cross_md = output_dir / "cross_creator_analysis.md"
    kb_json = output_dir / "creator_knowledge_base.json"
    kb_md = output_dir / "creator_knowledge_base.md"
    kb_index = output_dir / "knowledge_base" / "index.json"
    cache_index = cache_kb_dir / "index.json"
    manifest_path = output_dir / "manifest.json"

    cross_json.write_text(json.dumps(cross_analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    cross_md.write_text(_build_cross_markdown(cross_analysis), encoding="utf-8")
    kb_json.write_text(json.dumps(knowledge_base, ensure_ascii=False, indent=2), encoding="utf-8")
    kb_md.write_text(_build_knowledge_base_markdown(knowledge_base), encoding="utf-8")
    kb_index.parent.mkdir(parents=True, exist_ok=True)
    kb_index.write_text(json.dumps(knowledge_base["rag_index"], ensure_ascii=False, indent=2), encoding="utf-8")
    cache_index.write_text(json.dumps(knowledge_base["rag_index"], ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "spec_version": "Creator Learning Specification V1.0",
        "rule": "能力抽象知识库；不复制字幕原文、原句、原段落或可模仿措辞。",
        "video_count": len(video_records),
        "creator_count": len(creator_profiles),
        "creators": [
            {
                "author": profile["基本信息"]["作者"],
                "aliases": profile["基本信息"].get("别名", []),
                "source_authors": profile["基本信息"].get("原始作者", []),
                "positioning": profile["内容定位"],
                "video_count": profile["基本信息"]["样本数"],
                "creator_dir": str(creator_paths.get(profile["基本信息"]["作者"], "")),
            }
            for profile in creator_profiles
        ],
        "paths": {
            "creator_specs": str((creator_specs_path or CREATOR_SPECS_PATH).resolve()),
            "videos": str(video_root),
            "creators": str(creator_root),
            "cross_creator_analysis_json": str(cross_json),
            "cross_creator_analysis_md": str(cross_md),
            "creator_knowledge_base_json": str(kb_json),
            "creator_knowledge_base_md": str(kb_md),
            "rag_index": str(kb_index),
            "cache_rag_index": str(cache_index),
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "manifest": manifest_path,
        "cross_markdown": cross_md,
        "knowledge_markdown": kb_md,
        "rag_index": kb_index,
        "cache_rag_index": cache_index,
    }


def search_creator_knowledge_base(
    query: str,
    index_path: Path | None = None,
    top_k: int = 8,
    include_templates: bool = True,
) -> list[dict[str, Any]]:
    index_path = index_path or (SETTINGS.cache_dir / "creator_knowledge_base" / "index.json")
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    documents = list(payload.get("documents", []))
    if include_templates:
        documents.extend(_load_template_documents(index_path))
        documents = _dedupe_documents(documents)
    if not query.strip() or not documents:
        return []
    query_tokens = Counter(_tokenize(query))
    doc_tokens = [Counter(_tokenize(doc.get("text", ""))) for doc in documents]
    df: Counter[str] = Counter()
    for tokens in doc_tokens:
        df.update(tokens.keys())
    total = len(documents)
    scored = []
    for doc, tokens in zip(documents, doc_tokens):
        score = _cosine_tfidf(query_tokens, tokens, df, total)
        score += _category_query_boost(query, doc)
        if score > 0:
            scored.append((score, doc))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "score": round(score, 4),
            "category": doc.get("category"),
            "title": doc.get("title"),
            "capability": doc.get("capability"),
            "creators": doc.get("creators", []),
            "template_collection": doc.get("template_collection", ""),
            "source_video_ids": doc.get("source_video_ids", []),
            "excerpt": doc.get("text", "")[:260],
        }
        for score, doc in scored[:top_k]
    ]


def _load_template_documents(index_path: Path) -> list[dict[str, Any]]:
    candidates = [
        index_path.with_name("template_index.json"),
        SETTINGS.cache_dir / "creator_knowledge_base" / "template_index.json",
        SETTINGS.output_dir / "creator_knowledge_base" / "templates" / "template_index.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        payload = _read_json(candidate)
        documents = payload.get("documents", [])
        if isinstance(documents, list):
            return documents
    return []


def _dedupe_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for doc in documents:
        chunk_id = doc.get("chunk_id")
        key = chunk_id or json.dumps(doc, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        result.append(doc)
    return result


def _build_video_record(video: dict[str, Any], creator_specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
    raw_author = video.get("author") or "未知作者"
    author, spec = _creator_identity(raw_author, creator_specs)
    structure = _content_structure(video, spec)
    expression = _expression_profile(video, spec)
    techniques = _creative_techniques(video, spec, structure, expression)
    capability_summary = _video_capability_summary(video, spec, techniques)
    return {
        "video_id": video.get("video_id"),
        "video_info": {
            "标题": video.get("title", ""),
            "作者": author,
            "原始作者": raw_author,
            "发布时间": video.get("publish_time", ""),
            "时长": video.get("duration_text") or _format_duration(video.get("duration")),
            "播放量": video.get("view_count"),
            "点赞量": video.get("like_count"),
            "评论量": video.get("comment_count"),
            "标签": video.get("tags", []),
            "来源": video.get("source_url", ""),
        },
        "creator_positioning": spec["positioning"],
        "profile_name": spec["profile_name"],
        "content_structure": structure,
        "expression": expression,
        "creative_techniques": techniques,
        "summary": capability_summary,
        "source_files": {
            "analysis_path": video.get("analysis_path", ""),
            "v3_path": video.get("v3_path", ""),
            "original_video_markdown_path": video.get("video_markdown_path", ""),
        },
        "compliance": _compliance_note(),
    }


def _content_structure(video: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    hook_style = video.get("hook_style") or "未识别"
    structure_count = int(video.get("structure_count") or 0)
    duration_seconds = _float_or_none(video.get("duration")) or 0
    return {
        "Hook": {
            "style": hook_style,
            "capability": HOOK_CAPABILITIES.get(hook_style, "建立开场识别点"),
            "learning_focus": "学习开场功能，不学习具体话术。",
        },
        "正文": {
            "organization": _body_organization(spec["positioning"], structure_count, duration_seconds),
            "section_count": structure_count,
            "information_release": _information_release(spec["positioning"], duration_seconds),
        },
        "高潮": {
            "position": _abstract_peak(video.get("rhythm_peak")),
            "design": _climax_design(spec["positioning"], video.get("rhythm_change", "")),
        },
        "结尾": {
            "design": _ending_design(spec["positioning"], duration_seconds),
            "transferable_goal": "完成观点、情绪或知识闭环，让观众知道本期收获。",
        },
    }


def _expression_profile(video: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    transition_functions = _transition_functions(video.get("transitions", []))
    return {
        "叙事方式": _narrative_method(spec["positioning"]),
        "逻辑方式": _logic_method(spec["positioning"]),
        "节奏": _rhythm_method(video),
        "情绪": _emotion_method(video),
        "语言风格": _language_style(spec["positioning"]),
        "转场": transition_functions,
        "高频词": {
            "raw_terms_exported": False,
            "reason": "能力库不保存可模仿的高频原词；保留为功能类别。",
            "functional_groups": _keyword_function_groups(video, spec),
        },
        "口头禅": {
            "raw_phrases_exported": False,
            "functional_observation": "不抽取口头禅原句，只记录其承担的连接、解释、强调或收束功能。",
        },
        "句式": {
            "raw_sentence_patterns_exported": False,
            "functional_patterns": _sentence_function_patterns(video, spec, transition_functions),
        },
    }


def _creative_techniques(
    video: dict[str, Any],
    spec: dict[str, Any],
    structure: dict[str, Any],
    expression: dict[str, Any],
) -> dict[str, Any]:
    positioning = spec["positioning"]
    capabilities = _transferable_capabilities(positioning, structure, expression)
    return {
        "值得学习": capabilities[:5],
        "创新点": _innovation_points(positioning, video),
        "亮点": _strengths(positioning, video, structure),
        "不足": _limitations(video),
        "可迁移能力": capabilities,
        "不建议模仿内容": [
            "不要照搬标题、字幕、段落、口头禅或具体观点。",
            "不要复刻个人化人设、语气和标志性表达。",
            "不要把单个视频的事件判断当成通用结论。",
        ],
    }


def _video_capability_summary(
    video: dict[str, Any],
    spec: dict[str, Any],
    techniques: dict[str, Any],
) -> dict[str, Any]:
    return {
        "capability_summary": (
            f"该样本主要用于学习 {spec['positioning']}："
            f"{'；'.join(techniques['可迁移能力'][:3])}。"
        ),
        "best_used_for": spec.get("primary_categories", []),
        "not_used_for": "不用于模仿作者措辞、句子、段落或具体观点。",
    }


def _build_creator_profiles(
    video_records: list[dict[str, Any]],
    up_profiles: list[dict[str, Any]],
    creator_specs: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    by_author: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in video_records:
        by_author[record["video_info"]["作者"]].append(record)

    profile_by_author: dict[str, dict[str, Any]] = {}
    for profile in up_profiles:
        raw_author = profile.get("author")
        if not raw_author:
            continue
        canonical_author, _ = _creator_identity(raw_author, creator_specs)
        if canonical_author not in profile_by_author:
            profile_by_author[canonical_author] = dict(profile)
        else:
            profile_by_author[canonical_author] = _merge_up_profile(
                profile_by_author[canonical_author],
                profile,
            )

    profiles = []
    for author, records in sorted(by_author.items(), key=lambda item: (-len(item[1]), item[0])):
        spec = _creator_spec(author, creator_specs)
        up_profile = profile_by_author.get(author, {})
        profile = _creator_profile(author, spec, records, up_profile)
        profiles.append(profile)
    return profiles


def _creator_profile(
    author: str,
    spec: dict[str, Any],
    records: list[dict[str, Any]],
    up_profile: dict[str, Any],
) -> dict[str, Any]:
    hook_counter = Counter(record["content_structure"]["Hook"]["style"] for record in records)
    transition_counter = Counter()
    structure_counter = Counter()
    capability_counter = Counter()
    durations = []
    views = []
    for record in records:
        structure_counter[record["content_structure"]["正文"]["organization"]] += 1
        for item in record["expression"]["转场"]:
            transition_counter[item] += 1
        for capability in record["creative_techniques"]["可迁移能力"]:
            capability_counter[capability] += 1
        duration = _duration_seconds(record["video_info"].get("时长"))
        if duration is not None:
            durations.append(duration)
        view_count = _int_or_none(record["video_info"].get("播放量"))
        if view_count is not None:
            views.append(view_count)

    scores = _creator_scores(spec, records, hook_counter, capability_counter)
    source_authors = sorted(
        {
            str(record["video_info"].get("原始作者") or record["video_info"].get("作者") or "").strip()
            for record in records
            if record["video_info"].get("原始作者") or record["video_info"].get("作者")
        }
    )
    return {
        "基本信息": {
            "作者": author,
            "别名": spec.get("aliases", []),
            "原始作者": source_authors,
            "样本数": len(records),
            "平均时长": _format_duration(mean(durations)) if durations else "",
            "平均播放": round(mean(views), 2) if views else None,
            "UP来源": up_profile.get("source", ""),
        },
        "内容定位": spec["positioning"],
        "目标受众": spec["target_audience"],
        "主要能力": spec["primary_categories"],
        "Hook风格": _counter_payload(hook_counter),
        "叙事能力": _capability_statement(spec["positioning"], "叙事"),
        "逻辑能力": _capability_statement(spec["positioning"], "逻辑"),
        "节奏能力": _capability_statement(spec["positioning"], "节奏"),
        "情绪能力": _capability_statement(spec["positioning"], "情绪"),
        "人物塑造": _capability_statement(spec["positioning"], "人物"),
        "世界观讲解": _capability_statement(spec["positioning"], "世界观"),
        "类比能力": _capability_statement(spec["positioning"], "类比"),
        "知识组织": _capability_statement(spec["positioning"], "知识组织"),
        "高潮设计": _capability_statement(spec["positioning"], "高潮"),
        "结尾设计": _capability_statement(spec["positioning"], "结尾"),
        "转场设计": _counter_payload(transition_counter) or [{"item": "功能转场", "count": 0}],
        "高级技巧": _advanced_techniques(spec["positioning"]),
        "代表性表达方式": _representative_expression_modes(spec["positioning"]),
        "高频结构": _counter_payload(structure_counter),
        "可迁移能力": _counter_payload(capability_counter),
        "不建议模仿内容": [
            "个人化措辞、口头禅、标题句式和字幕文本。",
            "具体事件观点和未经复核的判断。",
            "独属于作者身份、经历和语气的表达。",
        ],
        "综合评分": scores,
        "style_summary": {
            "profile_name": spec["profile_name"],
            "positioning": spec["positioning"],
            "sample_count": len(records),
            "hook_distribution": _counter_payload(hook_counter),
            "transition_functions": _counter_payload(transition_counter),
            "structure_distribution": _counter_payload(structure_counter),
            "capability_distribution": _counter_payload(capability_counter),
            "raw_expression_policy": "不输出可模仿原文，只输出能力功能。",
        },
        "source_video_ids": [record["video_id"] for record in records],
        "compliance": _compliance_note(),
    }


def _merge_up_profile(primary: dict[str, Any], secondary: dict[str, Any]) -> dict[str, Any]:
    merged = dict(primary)
    merged["video_count"] = _int_or_zero(primary.get("video_count")) + _int_or_zero(secondary.get("video_count"))
    merged["success_count"] = _int_or_zero(primary.get("success_count")) + _int_or_zero(secondary.get("success_count"))
    merged["failure_count"] = _int_or_zero(primary.get("failure_count")) + _int_or_zero(secondary.get("failure_count"))
    sources = _dedupe([str(primary.get("source", "")).strip(), str(secondary.get("source", "")).strip()])
    merged["source"] = "；".join(item for item in sources if item)
    for key in ("top_keywords", "title_keywords", "hook_styles", "top_videos_by_view", "common_learnings"):
        merged[key] = list(primary.get(key, [])) + list(secondary.get(key, []))
    return merged


def _build_cross_creator_analysis(
    creator_profiles: list[dict[str, Any]],
    video_records: list[dict[str, Any]],
    creator_specs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    present = {profile["基本信息"]["作者"] for profile in creator_profiles}
    missing = [name for name, spec in creator_specs.items() if spec.get("required") and name not in present]
    hook_counter = Counter()
    transition_counter = Counter()
    capability_counter = Counter()
    for profile in creator_profiles:
        for item in profile.get("Hook风格", []):
            hook_counter[item["item"]] += item["count"]
        for item in profile.get("转场设计", []):
            transition_counter[item["item"]] += item["count"]
        for item in profile.get("可迁移能力", []):
            capability_counter[item["item"]] += item["count"]

    final_capabilities = _final_capability_synthesis(creator_profiles)
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sample": {
            "creator_count": len(creator_profiles),
            "video_count": len(video_records),
            "present_creators": sorted(present),
            "missing_creators": missing,
        },
        "共同特点": [
            "都需要在开场快速建立观看理由。",
            "都依赖分段组织来控制理解成本。",
            "都把信息释放顺序设计成从低门槛到高信息密度。",
            "都需要在结尾完成知识、情绪或观点闭环。",
        ],
        "不同特点": _creator_differences(creator_profiles),
        "共同结构": ["开场任务", "背景铺垫", "核心推进", "高潮解释", "结尾收束"],
        "不同节奏": _rhythm_differences(creator_profiles),
        "共同Hook": _counter_payload(hook_counter),
        "共同高潮": [
            "把关键冲突、关键证据或关键解释放在中后段集中释放。",
            "高潮不只靠情绪强度，也靠信息拼图完成感。",
        ],
        "共同结尾": [
            "回扣开场问题或核心矛盾。",
            "给出可被观众带走的结论、判断框架或情绪余味。",
        ],
        "共同语言特点": [
            "有效表达来自功能设计，而不是固定话术。",
            "可迁移的是问题框定、因果连接、对比、归纳和收束功能。",
        ],
        "共同转场": _counter_payload(transition_counter),
        "共同创作习惯": [
            "先确定观众的理解门槛，再安排信息顺序。",
            "用结构降低复杂度，用节奏维持注意力。",
            "把标题、开场、正文高潮和结尾设计成同一个任务链。",
        ],
        "最终提炼": final_capabilities,
        "capability_distribution": _counter_payload(capability_counter),
        "compliance": _compliance_note(),
    }


def _build_capability_knowledge_base(
    video_records: list[dict[str, Any]],
    creator_profiles: list[dict[str, Any]],
    cross_analysis: dict[str, Any],
) -> dict[str, Any]:
    category_docs = []
    for category in CAPABILITY_CATEGORIES:
        related_profiles = [
            profile for profile in creator_profiles if category in profile.get("主要能力", [])
        ]
        related_records = [
            record
            for record in video_records
            if category in record["summary"].get("best_used_for", [])
            or category in _category_inferred_from_positioning(record["creator_positioning"])
            or _record_supports_category(record, category)
        ]
        if not related_profiles and not related_records:
            continue
        doc = _capability_document(category, related_profiles, related_records)
        category_docs.append(doc)

    rag_documents = []
    for doc in category_docs:
        rag_documents.append(
            {
                "chunk_id": f"capability:{_slug(doc['category'])}",
                "category": doc["category"],
                "title": doc["title"],
                "capability": doc["capability"],
                "creators": doc["creators"],
                "source_video_ids": doc["source_video_ids"],
                "text": doc["rag_text"],
                "metadata": {
                    "do_not_copy": True,
                    "source_type": "creator_capability",
                },
            }
        )
    for profile in creator_profiles:
        author = profile["基本信息"]["作者"]
        rag_documents.append(
            {
                "chunk_id": f"creator:{_slug(author)}",
                "category": profile["内容定位"],
                "title": f"{author} capability profile",
                "capability": "Creator capability profile",
                "creators": [author],
                "source_video_ids": profile.get("source_video_ids", []),
                "text": _profile_rag_text(profile),
                "metadata": {
                    "do_not_copy": True,
                    "source_type": "creator_profile",
                },
            }
        )

    return {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rule": "建立能力知识库，而不是UP知识库；只保存可迁移能力。",
        "categories": CAPABILITY_CATEGORIES,
        "capability_documents": category_docs,
        "cross_creator_analysis": cross_analysis,
        "rag_index": {
            "version": 1,
            "document_count": len(rag_documents),
            "documents": rag_documents,
            "usage_policy": [
                "用于检索创作能力、结构模板和抽象方法。",
                "禁止用来模仿某位创作者的措辞、句子、段落或个人风格。",
            ],
        },
    }


def _write_video_outputs(video_root: Path, records: list[dict[str, Any]]) -> None:
    for record in records:
        out = video_root / str(record["video_id"])
        out.mkdir(parents=True, exist_ok=True)
        (out / "analysis.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "structure.json").write_text(json.dumps(record["content_structure"], ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "keywords.json").write_text(json.dumps(record["expression"]["高频词"], ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "summary.json").write_text(json.dumps(record["summary"], ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "video.md").write_text(_build_video_markdown(record), encoding="utf-8")


def _write_creator_outputs(creator_root: Path, profiles: list[dict[str, Any]]) -> dict[str, Path]:
    paths = {}
    for profile in profiles:
        author = profile["基本信息"]["作者"]
        out = creator_root / _slug(author)
        out.mkdir(parents=True, exist_ok=True)
        (out / "creator_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "style_summary.json").write_text(json.dumps(profile["style_summary"], ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "creator_profile.md").write_text(_build_creator_markdown(profile), encoding="utf-8")
        paths[author] = out
    return paths


def _build_video_markdown(record: dict[str, Any]) -> str:
    info = record["video_info"]
    structure = record["content_structure"]
    expression = record["expression"]
    techniques = record["creative_techniques"]
    lines = [
        "# Creator Learning Video Analysis",
        "",
        "## 一、视频信息",
        "",
        f"- 标题：{info.get('标题', '')}",
        f"- 作者：{info.get('作者', '')}",
        f"- 发布时间：{info.get('发布时间', '')}",
        f"- 时长：{info.get('时长', '')}",
        f"- 播放量：{info.get('播放量', '')}",
        f"- 标签：{'、'.join(str(item) for item in info.get('标签', []))}",
        "",
        "## 二、内容结构",
        "",
        f"- Hook：{structure['Hook']['capability']}（{structure['Hook']['style']}）",
        f"- 正文：{structure['正文']['organization']}",
        f"- 高潮：{structure['高潮']['design']}；位置判断：{structure['高潮']['position']}",
        f"- 结尾：{structure['结尾']['design']}",
        "",
        "## 三、表达方式",
        "",
        f"- 叙事方式：{expression['叙事方式']}",
        f"- 逻辑方式：{expression['逻辑方式']}",
        f"- 节奏：{expression['节奏']}",
        f"- 情绪：{expression['情绪']}",
        f"- 语言风格：{expression['语言风格']}",
        f"- 转场功能：{'、'.join(expression['转场']) or '未识别'}",
        f"- 高频词处理：{expression['高频词']['reason']}",
        f"- 句式功能：{'、'.join(expression['句式']['functional_patterns'])}",
        "",
        "## 四、创作技巧",
        "",
        f"- 值得学习：{'；'.join(techniques['值得学习'])}",
        f"- 创新点：{'；'.join(techniques['创新点'])}",
        f"- 亮点：{'；'.join(techniques['亮点'])}",
        f"- 不足：{'；'.join(techniques['不足'])}",
        f"- 可迁移能力：{'；'.join(techniques['可迁移能力'])}",
        "",
        "## 合规说明",
        "",
        "- 本文件只输出能力抽象，不输出字幕原文、原句、原段落或可模仿口头禅。",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _build_creator_markdown(profile: dict[str, Any]) -> str:
    info = profile["基本信息"]
    lines = [
        f"# {info['作者']} - {profile['内容定位']}",
        "",
        "## 基本信息",
        "",
        f"- 样本数：{info['样本数']}",
        f"- 平均时长：{info['平均时长']}",
        f"- 平均播放：{info['平均播放']}",
        f"- 目标受众：{profile['目标受众']}",
        "",
        "## 主要能力",
        "",
    ]
    lines.extend(f"- {item}" for item in profile["主要能力"])
    lines.extend(
        [
            "",
            "## Creator Profile字段",
            "",
            f"- Hook风格：{_format_counter_payload(profile['Hook风格'])}",
            f"- 叙事能力：{profile['叙事能力']}",
            f"- 逻辑能力：{profile['逻辑能力']}",
            f"- 节奏能力：{profile['节奏能力']}",
            f"- 情绪能力：{profile['情绪能力']}",
            f"- 人物塑造：{profile['人物塑造']}",
            f"- 世界观讲解：{profile['世界观讲解']}",
            f"- 类比能力：{profile['类比能力']}",
            f"- 知识组织：{profile['知识组织']}",
            f"- 高潮设计：{profile['高潮设计']}",
            f"- 结尾设计：{profile['结尾设计']}",
            f"- 转场设计：{_format_counter_payload(profile['转场设计'])}",
            f"- 高频结构：{_format_counter_payload(profile['高频结构'])}",
            "",
            "## 高级技巧",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in profile["高级技巧"])
    lines.extend(["", "## 可迁移能力", ""])
    lines.extend(f"- {item['item']}（样本支持：{item['count']}）" for item in profile["可迁移能力"])
    lines.extend(["", "## 不建议模仿内容", ""])
    lines.extend(f"- {item}" for item in profile["不建议模仿内容"])
    lines.extend(["", "## 综合评分", ""])
    for key, value in profile["综合评分"].items():
        lines.append(f"- {key}：{value}")
    return "\n".join(lines).rstrip() + "\n"


def _build_cross_markdown(cross: dict[str, Any]) -> str:
    lines = [
        "# Cross Creator Analysis",
        "",
        f"生成时间：{cross['generated_at']}",
        "",
        "## 样本",
        "",
        f"- 创作者数：{cross['sample']['creator_count']}",
        f"- 视频数：{cross['sample']['video_count']}",
        f"- 已覆盖：{'、'.join(cross['sample']['present_creators'])}",
        f"- 暂未覆盖：{'、'.join(cross['sample']['missing_creators']) or '无'}",
    ]
    for key in ["共同特点", "不同特点", "共同结构", "不同节奏", "共同高潮", "共同结尾", "共同语言特点", "共同创作习惯"]:
        lines.extend(["", f"## {key}", ""])
        values = cross.get(key, [])
        if isinstance(values, list):
            lines.extend(f"- {item}" for item in values)
    lines.extend(["", "## 共同Hook", "", _format_counter_payload(cross["共同Hook"])])
    lines.extend(["", "## 共同转场", "", _format_counter_payload(cross["共同转场"])])
    lines.extend(["", "## 最终提炼", ""])
    for key, value in cross["最终提炼"].items():
        lines.append(f"- {key}：{value}")
    return "\n".join(lines).rstrip() + "\n"


def _build_knowledge_base_markdown(kb: dict[str, Any]) -> str:
    lines = [
        "# Creator Knowledge Base",
        "",
        f"生成时间：{kb['generated_at']}",
        "",
        "## 使用规则",
        "",
        "- 只用于学习可迁移创作能力。",
        "- 禁止模仿某位UP的措辞、句子、段落、标题模板或个人化表达。",
        "",
        "## 能力分类",
        "",
    ]
    for doc in kb["capability_documents"]:
        lines.extend(
            [
                f"### {doc['category']}",
                "",
                f"- 能力：{doc['capability']}",
                f"- 可迁移做法：{'；'.join(doc['transferable_methods'])}",
                f"- 适用创作者：{'、'.join(doc['creators'])}",
                f"- 样本视频数：{len(doc['source_video_ids'])}",
                f"- 禁止事项：{'；'.join(doc['do_not_copy'])}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _capability_document(
    category: str,
    profiles: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    creators = sorted({profile["基本信息"]["作者"] for profile in profiles} | {record["video_info"]["作者"] for record in records})
    source_video_ids = sorted({str(record["video_id"]) for record in records})
    methods = _category_methods(category)
    text = (
        f"{category} 能力：{_category_capability(category)}。"
        f" 可迁移做法：{'；'.join(methods)}。"
        f" 适用创作者：{'、'.join(creators) if creators else '通用'}。"
        " 使用时只能调用结构、顺序和功能，不得复刻具体措辞。"
    )
    return {
        "category": category,
        "title": f"{category} Capability",
        "capability": _category_capability(category),
        "transferable_methods": methods,
        "creators": creators,
        "source_video_ids": source_video_ids,
        "do_not_copy": [
            "不要复制字幕、原句、段落或标题措辞。",
            "不要模仿创作者个人口头禅。",
            "不要把具体观点当成可迁移方法。",
        ],
        "rag_text": text,
    }


def _profile_rag_text(profile: dict[str, Any]) -> str:
    author = profile["基本信息"]["作者"]
    abilities = "；".join(item["item"] for item in profile.get("可迁移能力", [])[:8])
    hooks = _format_counter_payload(profile.get("Hook风格", []))
    structures = _format_counter_payload(profile.get("高频结构", []))
    return (
        f"{author} 的能力定位是 {profile['内容定位']}。"
        f" 主要能力：{'、'.join(profile['主要能力'])}。"
        f" 可迁移能力：{abilities}。"
        f" Hook功能分布：{hooks}。"
        f" 高频结构：{structures}。"
        " 该文本只用于能力检索，不用于风格模仿。"
    )


def load_creator_specs(path: Path | None = None) -> dict[str, dict[str, Any]]:
    specs = {
        author: _normalize_creator_spec(author, spec)
        for author, spec in DEFAULT_CREATOR_SPECS.items()
    }
    spec_path = path or CREATOR_SPECS_PATH
    if spec_path.exists():
        payload = _read_json(spec_path)
        for author, spec in _iter_creator_spec_entries(payload):
            merged = {**specs.get(author, {}), **spec}
            specs[author] = _normalize_creator_spec(author, merged)
    return specs


def _iter_creator_spec_entries(payload: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(payload, dict) and isinstance(payload.get("creators"), list):
        result = []
        for item in payload["creators"]:
            if not isinstance(item, dict):
                continue
            author = str(item.get("author") or item.get("canonical_author") or "").strip()
            if author:
                result.append((author, item))
        return result
    if isinstance(payload, dict):
        result = []
        for author, spec in payload.items():
            if isinstance(spec, dict):
                result.append((str(author).strip(), spec))
        return result
    return []


def _normalize_creator_spec(author: str, spec: dict[str, Any]) -> dict[str, Any]:
    normalized = {**_general_creator_spec(), **dict(spec)}
    aliases = [
        str(alias).strip()
        for alias in normalized.get("aliases", [])
        if str(alias).strip() and str(alias).strip() != author
    ]
    normalized["aliases"] = _dedupe(aliases)
    normalized["canonical_author"] = author
    normalized["required"] = bool(normalized.get("required", False))
    return normalized


def _creator_identity(author: str, creator_specs: dict[str, dict[str, Any]] | None = None) -> tuple[str, dict[str, Any]]:
    creator_specs = creator_specs or load_creator_specs()
    clean_author = str(author or "未知作者").strip() or "未知作者"
    if clean_author in creator_specs:
        return clean_author, creator_specs[clean_author]
    for spec_author, spec in creator_specs.items():
        if clean_author in spec.get("aliases", []):
            return spec_author, {**spec, "canonical_author": spec_author}
    return clean_author, _general_creator_spec(clean_author)


def _creator_spec(author: str, creator_specs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    return _creator_identity(author, creator_specs)[1]


def _general_creator_spec(author: str = "") -> dict[str, Any]:
    return {
        "canonical_author": author,
        "aliases": [],
        "required": False,
        "positioning": "General Creator",
        "profile_name": "General Creator Profile",
        "target_audience": "泛内容观众",
        "primary_categories": ["Narration", "Hook", "Rhythm"],
    }


def _body_organization(positioning: str, structure_count: int, duration_seconds: float) -> str:
    if positioning == "Storytelling":
        return "以人物、地点或事件冲突为线索，逐步释放背景和转折"
    if positioning == "Logical Narrative":
        return "以时间线和因果链组织材料，分段解释事件演化"
    if positioning in {"Historical Narrative", "Long Historical Narrative"}:
        return "以长时间线、人物关系和时代变量组织材料，逐段推进事件链条"
    if positioning in {"International Commentary", "Geopolitical Narrative"}:
        return "以现实议题、国家关系和利益变量组织材料，先交代争议再解释影响"
    if positioning == "Business Explanation":
        return "以商业问题、市场变量和案例机制组织解释"
    if positioning == "Cross-cultural Short Explainer":
        return "以文化差异或生活观察切入，快速解释背景、机制和结论"
    if positioning == "Visual Production":
        return "以视觉问题、制作过程和结果验证组织信息"
    if positioning == "Science Explanation":
        return "先降低概念门槛，再递进到机制、证据和边界条件"
    if positioning == "Emotion Narrative":
        return "以现场、人物和情绪线索推动沉浸感"
    if positioning == "Visual Teaching":
        return "用视觉分层承载抽象信息，配合节奏切换降低理解难度"
    if positioning == "Story Analysis":
        return "按剧情节点、人物动机和主题含义拆解作品"
    if positioning == "Anime Narrative":
        return "压缩剧情主线，串联背景、动机、冲突和高光节点"
    if duration_seconds > 1800 or structure_count >= 3:
        return "长结构分段推进"
    return "短中结构集中解释"


def _information_release(positioning: str, duration_seconds: float) -> str:
    if positioning in {"Storytelling", "Anime Narrative", "Story Analysis"}:
        return "先给观看任务，再逐步揭示人物动机、冲突升级和结果"
    if positioning in {"Logical Narrative", "Historical Narrative", "Long Historical Narrative", "International Commentary", "Geopolitical Narrative"}:
        return "先交代背景变量，再展开因果链和阶段性结论"
    if positioning in {"Science Explanation", "Business Explanation"}:
        return "先处理概念门槛，再解释机制，最后补充争议和边界"
    if positioning == "Cross-cultural Short Explainer":
        return "先抛出差异或观察，再补背景，最后给出可理解的解释框架"
    if positioning == "Visual Production":
        return "先提出视觉或制作问题，再展示过程，最后用结果验证"
    if duration_seconds > 1800:
        return "长线铺垫，中后段集中解释或情绪释放"
    return "开场即明确任务，正文快速进入核心信息"


def _abstract_peak(value: Any) -> str:
    text = str(value or "")
    match = re.search(r"(\d{2}:\d{2})", text)
    if not match:
        return "未识别具体位置"
    minute = int(match.group(1).split(":")[0])
    if minute <= 2:
        return "前段高密度"
    if minute <= 8:
        return "中段高密度"
    return "中后段高密度"


def _climax_design(positioning: str, rhythm_change: str) -> str:
    if positioning == "Science Explanation":
        return "把关键机制、证据或反常识点集中释放"
    if positioning in {"Logical Narrative", "International Commentary", "Geopolitical Narrative", "Business Explanation"}:
        return "把多条因果线汇合到关键判断"
    if positioning in {"Historical Narrative", "Long Historical Narrative"}:
        return "把人物选择、时代变量和事件后果汇合到关键转折"
    if positioning == "Cross-cultural Short Explainer":
        return "把表层差异背后的原因集中解释清楚"
    if positioning == "Visual Production":
        return "把制作过程的关键验证、视觉结果或技术取舍集中展示"
    if positioning == "Storytelling":
        return "把冲突、反转或人物选择推到最清晰的位置"
    if positioning in {"Story Analysis", "Anime Narrative"}:
        return "集中处理角色选择、剧情转折和主题升维"
    if "后段" in str(rhythm_change):
        return "后段加速收束"
    return "稳定推进中的局部信息峰值"


def _ending_design(positioning: str, duration_seconds: float) -> str:
    if positioning in {"Storytelling", "Emotion Narrative"}:
        return "用结果、余味或价值判断完成故事闭环"
    if positioning in {"Logical Narrative", "International Commentary", "Geopolitical Narrative", "Business Explanation", "Historical Narrative", "Long Historical Narrative"}:
        return "回收因果链，给出阶段性判断"
    if positioning == "Science Explanation":
        return "回到问题本身，标明结论、边界和未解之处"
    if positioning == "Cross-cultural Short Explainer":
        return "回扣开场差异，形成可被观众带走的解释"
    if positioning == "Visual Production":
        return "回到制作问题，用结果、经验或取舍完成收束"
    if positioning in {"Story Analysis", "Anime Narrative"}:
        return "用主题、人物成长或后续期待完成收束"
    if duration_seconds > 1800:
        return "长线总结收束"
    return "简洁回扣主题"


def _narrative_method(positioning: str) -> str:
    mapping = {
        "Storytelling": "故事驱动：用冲突、人物选择和事件后果推进",
        "Logical Narrative": "逻辑驱动：用时间线、变量和因果关系推进",
        "Historical Narrative": "历史叙事驱动：用时代背景、人物关系和事件链条推进",
        "Long Historical Narrative": "长线历史驱动：用人物群像、制度变量和阶段转折推进",
        "International Commentary": "议题驱动：用现实争议、利益变量和影响判断推进",
        "Geopolitical Narrative": "地缘叙事驱动：用国家关系、历史背景和利益冲突推进",
        "Business Explanation": "商业解释驱动：用问题、案例和机制拆解推进",
        "Cross-cultural Short Explainer": "观察解释驱动：用差异、背景和原因归纳推进",
        "Visual Production": "制作验证驱动：用问题、过程和视觉结果推进",
        "Science Explanation": "解释驱动：用概念递进和证据边界推进",
        "Emotion Narrative": "情绪驱动：用现场感、人物处境和留白推进",
        "Visual Teaching": "视觉驱动：用图示、动画和镜头层级推进理解",
        "Story Analysis": "解析驱动：用剧情节点、人物动机和主题关系推进",
        "Anime Narrative": "剧情压缩驱动：用主线、动机和高光节点推进",
    }
    return mapping.get(positioning, "任务驱动：围绕一个明确内容目标推进")


def _logic_method(positioning: str) -> str:
    mapping = {
        "Storytelling": "用因果链解释人物选择与事件后果",
        "Logical Narrative": "用时间线、背景变量和多因一果建立论证",
        "Historical Narrative": "用时代背景、关键人物和事件结果建立历史因果",
        "Long Historical Narrative": "用长周期变量、人物网络和阶段复盘建立论证",
        "International Commentary": "用现实变量、国家关系和影响链建立判断",
        "Geopolitical Narrative": "用历史背景、地缘利益和政策后果建立解释",
        "Business Explanation": "用商业模式、市场变量和案例结果建立解释",
        "Cross-cultural Short Explainer": "用观察差异、背景条件和原因归纳建立理解",
        "Visual Production": "用制作目标、技术路径和结果验证建立解释",
        "Science Explanation": "用定义、机制、证据和边界逐层解释",
        "Emotion Narrative": "用处境变化和情绪因果建立共情",
        "Visual Teaching": "用视觉分层和例子验证概念",
        "Story Analysis": "用剧情因果、角色动机和主题回扣建立解释",
        "Anime Narrative": "用世界设定、角色动机和剧情衔接建立连续性",
    }
    return mapping.get(positioning, "用分段结构建立理解顺序")


def _rhythm_method(video: dict[str, Any]) -> str:
    duration = _float_or_none(video.get("duration")) or 0
    change = str(video.get("rhythm_change", "")).strip()
    if duration > 1800:
        base = "长视频节奏：铺垫、推进、集中释放、总结"
    elif duration > 600:
        base = "中视频节奏：快速建立任务，分段解释"
    else:
        base = "短中视频节奏：高密度解释，少量铺垫"
    return f"{base}；{change or '节奏变化未识别'}"


def _emotion_method(video: dict[str, Any]) -> str:
    emotion = str(video.get("emotion", "")).strip()
    if not emotion:
        return "情绪信号未充分识别"
    return f"以{emotion}为主，服务于理解、悬念或共情"


def _language_style(positioning: str) -> str:
    mapping = {
        "Storytelling": "故事化、场景化、强调冲突功能",
        "Logical Narrative": "解释型、论证型、强调因果功能",
        "Historical Narrative": "历史型、复盘型、强调人物与时代连接",
        "Long Historical Narrative": "长线叙事型、阶段复盘型、强调历史变量累积",
        "International Commentary": "议题解释型、判断型、强调变量和影响",
        "Geopolitical Narrative": "背景解释型、关系分析型、强调历史和利益连接",
        "Business Explanation": "案例解释型、机制型、强调复杂问题拆解",
        "Cross-cultural Short Explainer": "短解释型、观察型、强调差异背后的原因",
        "Visual Production": "制作说明型、体验型、强调视觉证据和过程",
        "Science Explanation": "科普型、降门槛、强调概念清晰度",
        "Emotion Narrative": "沉浸型、克制型、强调共情和现场感",
        "Visual Teaching": "轻教学型、视觉提示型、强调理解效率",
        "Story Analysis": "解析型、归纳型、强调主题和人物关系",
        "Anime Narrative": "剧情型、期待型、强调连续性和高光提炼",
    }
    return mapping.get(positioning, "清晰解释型")


def _transition_functions(transitions: list[Any]) -> list[str]:
    functions = []
    for item in transitions:
        text = str(item)
        matched = False
        for marker, function in TRANSITION_FUNCTIONS.items():
            if marker in text:
                functions.append(function)
                matched = True
        if not matched and text.strip():
            functions.append("段落连接")
    return sorted(set(functions))


def _keyword_function_groups(video: dict[str, Any], spec: dict[str, Any]) -> list[str]:
    groups = ["主题实体聚焦", "解释性连接"]
    positioning = spec["positioning"]
    if positioning in {"Storytelling", "Logical Narrative", "Historical Narrative", "Long Historical Narrative", "International Commentary", "Geopolitical Narrative"}:
        groups.extend(["人物/组织关系", "事件因果"])
    if positioning in {"Science Explanation", "Business Explanation", "Cross-cultural Short Explainer"}:
        groups.extend(["概念定义", "机制解释", "边界说明"])
    if positioning == "Visual Production":
        groups.extend(["视觉目标", "制作流程", "结果验证"])
    if positioning in {"Story Analysis", "Anime Narrative"}:
        groups.extend(["角色动机", "剧情节点", "世界观设定"])
    if video.get("hook_style") in {"问题式开头", "冲突/反差式开头"}:
        groups.append("问题或反差提示")
    return sorted(set(groups))


def _sentence_function_patterns(video: dict[str, Any], spec: dict[str, Any], transitions: list[str]) -> list[str]:
    patterns = ["开场任务句", "背景铺垫句", "因果解释句", "阶段总结句"]
    if "转折校正" in transitions:
        patterns.append("转折校正句")
    if spec["positioning"] in {"Science Explanation", "Business Explanation", "Cross-cultural Short Explainer"}:
        patterns.extend(["概念定义句", "类比说明句", "边界提示句"])
    if spec["positioning"] == "Visual Production":
        patterns.extend(["过程说明句", "结果验证句", "取舍解释句"])
    if spec["positioning"] in {"Historical Narrative", "Long Historical Narrative", "International Commentary", "Geopolitical Narrative"}:
        patterns.extend(["变量拆解句", "阶段判断句", "后果回收句"])
    if spec["positioning"] in {"Story Analysis", "Anime Narrative"}:
        patterns.extend(["剧情承接句", "动机解释句", "期待推进句"])
    return sorted(set(patterns))


def _transferable_capabilities(
    positioning: str,
    structure: dict[str, Any],
    expression: dict[str, Any],
) -> list[str]:
    base = [
        structure["Hook"]["capability"],
        structure["正文"]["information_release"],
        structure["高潮"]["design"],
        structure["结尾"]["design"],
        "用功能转场维持理解连续性",
    ]
    if positioning == "Storytelling":
        base.extend(["用人物选择承载事件冲突", "按悬念强弱安排信息释放顺序"])
    elif positioning == "Logical Narrative":
        base.extend(["用时间线组织复杂事件", "把背景变量拆成因果树"])
    elif positioning in {"Historical Narrative", "Long Historical Narrative"}:
        base.extend(["用长时间线组织历史变化", "把人物选择放回时代变量中解释"])
    elif positioning in {"International Commentary", "Geopolitical Narrative"}:
        base.extend(["用现实变量拆解议题", "把国家关系转成影响链和阶段判断"])
    elif positioning == "Business Explanation":
        base.extend(["用案例拆解商业机制", "把市场变量转成可理解因果链"])
    elif positioning == "Cross-cultural Short Explainer":
        base.extend(["用差异观察降低进入门槛", "把文化背景转成短解释框架"])
    elif positioning == "Visual Production":
        base.extend(["用制作过程解释视觉判断", "用结果验证支撑观点"])
    elif positioning == "Science Explanation":
        base.extend(["先定义概念再解释机制", "用例子和边界降低误解概率"])
    elif positioning == "Emotion Narrative":
        base.extend(["用人物处境推进情绪", "用留白制造共情空间"])
    elif positioning == "Visual Teaching":
        base.extend(["用视觉层级拆解抽象概念", "用节奏切换保持注意力"])
    elif positioning == "Story Analysis":
        base.extend(["用剧情节点拆解主题", "用人物成长线解释作品表达"])
    elif positioning == "Anime Narrative":
        base.extend(["压缩剧情但保留动机链", "用高光节点制造期待感"])
    return _dedupe(base)


def _innovation_points(positioning: str, video: dict[str, Any]) -> list[str]:
    points = {
        "Storytelling": ["把知识内容包装成可追踪的故事任务"],
        "Logical Narrative": ["把历史材料转成可复盘的因果结构"],
        "Historical Narrative": ["把历史事件转成可追踪的人物和时代链条"],
        "Long Historical Narrative": ["把长周期历史材料压成阶段清晰的叙事链"],
        "International Commentary": ["把现实议题拆成变量、关系和影响判断"],
        "Geopolitical Narrative": ["把地缘议题转成历史背景和利益链条"],
        "Business Explanation": ["把商业案例拆成机制、变量和结果"],
        "Cross-cultural Short Explainer": ["把文化差异转成短路径解释"],
        "Visual Production": ["把制作过程转成可验证的视觉表达经验"],
        "Science Explanation": ["把陌生概念转成逐层理解路径"],
        "Emotion Narrative": ["把现场信息转成情绪推进"],
        "Visual Teaching": ["把抽象关系转成可视化理解动作"],
        "Story Analysis": ["把剧情复述转成角色和主题分析"],
        "Anime Narrative": ["把长剧情压缩成连续动机链"],
    }
    result = points.get(positioning, ["把信息组织成可迁移结构"])
    if video.get("cover_path"):
        result.append("封面承担题眼压缩功能")
    return result


def _strengths(positioning: str, video: dict[str, Any], structure: dict[str, Any]) -> list[str]:
    strengths = [structure["Hook"]["capability"], structure["正文"]["organization"]]
    if _int_or_none(video.get("view_count")) and (_int_or_none(video.get("view_count")) or 0) > 1_000_000:
        strengths.append("样本播放表现较强，可优先观察结构能力")
    if positioning == "Science Explanation":
        strengths.append("适合学习复杂知识降门槛")
    if positioning in {"Business Explanation", "Cross-cultural Short Explainer"}:
        strengths.append("适合学习解释框架和门槛控制")
    if positioning == "Visual Production":
        strengths.append("适合学习画面证据和视觉流程组织")
    if positioning in {"Historical Narrative", "Long Historical Narrative", "International Commentary", "Geopolitical Narrative"}:
        strengths.append("适合学习因果链和现实/历史变量组织")
    if positioning in {"Story Analysis", "Anime Narrative"}:
        strengths.append("适合学习剧情压缩和代入设计")
    return _dedupe(strengths)


def _limitations(video: dict[str, Any]) -> list[str]:
    limitations = []
    if video.get("comments_status") == "skipped":
        limitations.append("评论正文缺失，观众反馈只能参考评论数，不能做深层情绪归因")
    if not video.get("cover_path"):
        limitations.append("封面信息缺失，视觉策略判断有限")
    limitations.append("当前分析基于本地结构化结果，不能替代人工复核")
    return limitations


def _creator_scores(
    spec: dict[str, Any],
    records: list[dict[str, Any]],
    hook_counter: Counter[str],
    capability_counter: Counter[str],
) -> dict[str, Any]:
    sample = len(records)
    hook_score = min(10.0, 6.0 + len(hook_counter) * 0.8 + sample * 0.08)
    capability_score = min(10.0, 5.5 + len(capability_counter) * 0.18)
    positioning = spec["positioning"]
    narrative_score = 8.5 if positioning in {"Storytelling", "Anime Narrative", "Story Analysis", "Emotion Narrative", "Historical Narrative", "Long Historical Narrative"} else 7.2
    logic_score = 8.5 if positioning in {"Logical Narrative", "Science Explanation", "International Commentary", "Geopolitical Narrative", "Business Explanation", "Historical Narrative", "Long Historical Narrative"} else 7.0
    rhythm_score = min(10.0, 6.5 + sample * 0.12)
    emotion_score = 8.3 if positioning in {"Emotion Narrative", "Storytelling", "Anime Narrative", "Story Analysis", "Historical Narrative", "Long Historical Narrative"} else 6.8
    overall = mean([hook_score, capability_score, narrative_score, logic_score, rhythm_score, emotion_score])
    return {
        "Hook": round(hook_score, 1),
        "叙事": round(narrative_score, 1),
        "逻辑": round(logic_score, 1),
        "节奏": round(rhythm_score, 1),
        "情绪": round(emotion_score, 1),
        "能力可迁移性": round(capability_score, 1),
        "综合": round(overall, 1),
        "说明": "评分为结构化样本启发式评分，用于排序和检索，不代表创作者绝对水平。",
    }


def _capability_statement(positioning: str, field: str) -> str:
    table = {
        ("Storytelling", "叙事"): "强项是把人物、国家或事件组织成可追踪故事线。",
        ("Storytelling", "逻辑"): "逻辑服务于故事推进，重点是选择、冲突和后果的因果关系。",
        ("Storytelling", "节奏"): "适合学习铺垫、转折、高潮和回扣的长线节奏。",
        ("Storytelling", "情绪"): "情绪来自人物处境、反差和结果回收。",
        ("Logical Narrative", "逻辑"): "强项是时间线、背景变量和因果树。",
        ("Logical Narrative", "叙事"): "叙事服务于论证，重点是事件如何一步步形成。",
        ("Historical Narrative", "叙事"): "强项是把人物、时代背景和事件后果组织成长线叙事。",
        ("Historical Narrative", "逻辑"): "逻辑重点是时代变量、人物选择和结果之间的因果链。",
        ("Long Historical Narrative", "叙事"): "强项是长时间线压缩、人物群像和阶段性转折。",
        ("Long Historical Narrative", "逻辑"): "逻辑重点是把制度、利益和人物行动拆成长期变量。",
        ("International Commentary", "逻辑"): "强项是把现实议题拆成变量、关系和影响链。",
        ("Geopolitical Narrative", "逻辑"): "强项是用历史背景和利益结构解释现实判断。",
        ("Business Explanation", "逻辑"): "强项是用案例、商业机制和市场变量建立解释。",
        ("Cross-cultural Short Explainer", "知识组织"): "强项是从表层差异切入，快速补齐背景和原因。",
        ("Visual Production", "知识组织"): "强项是让画面、过程和结果共同承担解释功能。",
        ("Visual Production", "类比"): "重点是用可观察的画面和实验过程承接抽象判断。",
        ("Science Explanation", "类比"): "重点是把陌生概念放进观众已有认知框架。",
        ("Science Explanation", "知识组织"): "强项是概念、机制、证据和边界的递进顺序。",
        ("Anime Narrative", "人物"): "重点是角色动机、成长线和高光节点。",
        ("Story Analysis", "世界观"): "重点是设定、人物关系和主题表达之间的连接。",
    }
    if (positioning, field) in table:
        return table[(positioning, field)]
    generic = {
        "叙事": "通过任务、结构和信息释放顺序组织内容。",
        "逻辑": "通过分段和因果连接降低理解成本。",
        "节奏": "通过铺垫、推进和收束维持注意力。",
        "情绪": "通过冲突、处境或结果制造情绪落点。",
        "人物": "通过动机、选择和后果建立人物理解。",
        "世界观": "通过背景、规则和关系解释复杂设定。",
        "类比": "用熟悉对象承接陌生概念。",
        "知识组织": "先解决门槛，再推进细节和边界。",
        "高潮": "把关键冲突、证据或解释集中释放。",
        "结尾": "回扣开场任务，完成理解闭环。",
    }
    return generic.get(field, "该能力以结构功能为主。")


def _advanced_techniques(positioning: str) -> list[str]:
    table = {
        "Storytelling": ["悬念延迟释放", "人物选择驱动冲突", "结尾回扣前文任务"],
        "Logical Narrative": ["时间线压缩", "多因一果拆解", "阶段性结论复盘"],
        "Historical Narrative": ["时代背景铺垫", "人物关系串联", "事件后果复盘"],
        "Long Historical Narrative": ["长时间线压缩", "人物群像组织", "阶段转折回收"],
        "International Commentary": ["现实变量拆解", "利益关系对照", "阶段判断收束"],
        "Geopolitical Narrative": ["历史背景嵌入", "地缘变量拆解", "影响链回收"],
        "Business Explanation": ["案例机制拆解", "变量分层", "结果反推"],
        "Cross-cultural Short Explainer": ["差异切入", "背景快补", "原因归纳"],
        "Visual Production": ["过程可视化", "结果验证", "取舍复盘"],
        "Science Explanation": ["概念降维", "类比桥接", "证据边界说明"],
        "Emotion Narrative": ["第一视角沉浸", "留白和现场感", "人物处境递进"],
        "Visual Teaching": ["图示分层", "镜头节奏引导", "视觉化类比"],
        "Story Analysis": ["剧情拆分", "人物成长线", "主题升华"],
        "Anime Narrative": ["剧情浓缩", "期待感制造", "世界观快速铺垫"],
    }
    return table.get(positioning, ["任务框定", "结构递进", "结尾收束"])


def _representative_expression_modes(positioning: str) -> list[str]:
    base = ["问题框定", "因果连接", "反差提示", "阶段总结"]
    if positioning == "Science Explanation":
        base.extend(["概念定义", "类比说明", "边界提示"])
    if positioning in {"Business Explanation", "Cross-cultural Short Explainer"}:
        base.extend(["机制拆解", "案例解释", "边界提示"])
    if positioning == "Visual Production":
        base.extend(["过程说明", "结果验证", "取舍复盘"])
    if positioning in {"Storytelling", "Anime Narrative", "Story Analysis"}:
        base.extend(["冲突推进", "动机解释", "高光回收"])
    if positioning in {"Logical Narrative", "Historical Narrative", "Long Historical Narrative", "International Commentary", "Geopolitical Narrative"}:
        base.extend(["时间线标记", "变量拆解", "结论回扣"])
    return _dedupe(base)


def _final_capability_synthesis(creator_profiles: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "Storytelling": "从人物、冲突、选择和后果中抽出故事线。",
        "Logic": "把事实拆成时间线、变量、因果链和阶段结论。",
        "Emotion": "用处境、反差、现场感和结果回收设计情绪。",
        "Rhythm": "用铺垫、推进、峰值和收束管理注意力。",
        "Explanation": "先降低门槛，再解释机制、证据和边界。",
        "Visualization": "让封面、图示或画面承担题眼压缩和理解引导。",
        "World Building": "先交代规则和关系，再展开事件或剧情。",
        "Character": "用动机、选择、代价和成长线塑造人物。",
        "Narration": "让叙事、逻辑和情绪服务于同一个观看任务。",
        "Hook": "用问题、反差、风险或异常建立信息缺口。",
        "Ending": "回扣开场任务，给出理解闭环或情绪余味。",
        "Transition": "用顺序、转折、因果、举例和总结功能连接段落。",
    }


def _creator_differences(profiles: list[dict[str, Any]]) -> list[str]:
    lines = []
    for profile in profiles:
        author = profile["基本信息"]["作者"]
        positioning = profile["内容定位"]
        abilities = "、".join(profile["主要能力"][:3])
        lines.append(f"{author}：定位为 {positioning}，主要贡献能力是 {abilities}。")
    return lines


def _rhythm_differences(profiles: list[dict[str, Any]]) -> list[str]:
    lines = []
    for profile in profiles:
        author = profile["基本信息"]["作者"]
        avg = profile["基本信息"].get("平均时长", "")
        positioning = profile["内容定位"]
        if positioning in {"Storytelling", "Logical Narrative", "Historical Narrative", "Long Historical Narrative", "International Commentary", "Geopolitical Narrative"}:
            pattern = "偏长线铺垫和阶段推进"
        elif positioning in {"Science Explanation", "Anime Narrative", "Business Explanation", "Cross-cultural Short Explainer"}:
            pattern = "偏快速建立任务和高密度解释"
        elif positioning == "Visual Production":
            pattern = "偏过程展示、视觉验证和结果收束"
        else:
            pattern = "根据主题组织节奏"
        lines.append(f"{author}：平均时长 {avg}，{pattern}。")
    return lines


def _category_inferred_from_positioning(positioning: str) -> list[str]:
    mapping = {
        "Storytelling": ["Storytelling", "Hook", "Rhythm", "Character", "Narration"],
        "Logical Narrative": ["Logic", "Historical Narrative", "Narration", "Transition"],
        "Historical Narrative": ["Historical Narrative", "Storytelling", "Logic", "Narration", "Transition", "Ending"],
        "Long Historical Narrative": ["Historical Narrative", "Storytelling", "Logic", "Narration", "Character", "Ending"],
        "International Commentary": ["Logic", "Historical Narrative", "Narration", "Hook", "Transition", "Ending"],
        "Geopolitical Narrative": ["Logic", "Historical Narrative", "Narration", "Hook", "Transition", "Ending"],
        "Business Explanation": ["Explanation", "Logic", "Teaching", "Narration", "Hook"],
        "Cross-cultural Short Explainer": ["Explanation", "Teaching", "Hook", "Rhythm", "Narration"],
        "Visual Production": ["Visualization", "Teaching", "Explanation", "Rhythm", "Narration"],
        "Science Explanation": ["Explanation", "Science Narrative", "Teaching", "Hook"],
        "Emotion Narrative": ["Emotion", "Character", "Narration"],
        "Visual Teaching": ["Visualization", "Teaching", "Explanation"],
        "Story Analysis": ["Plot Analysis", "Character", "World Building"],
        "Anime Narrative": ["Anime Narrative", "Plot Analysis", "World Building", "Character"],
    }
    return mapping.get(positioning, ["Narration", "Hook"])


def _record_supports_category(record: dict[str, Any], category: str) -> bool:
    if category == "Transition":
        return bool(record.get("expression", {}).get("转场"))
    if category == "Hook":
        return bool(record.get("content_structure", {}).get("Hook", {}).get("style"))
    if category == "Ending":
        return bool(record.get("content_structure", {}).get("结尾", {}).get("design"))
    return False


def _category_capability(category: str) -> str:
    table = {
        "Storytelling": "把信息组织成有冲突、有推进、有结果的故事任务",
        "Logic": "把复杂事实拆成变量、因果和阶段结论",
        "Emotion": "设计观众的情绪进入、递进和回收",
        "Hook": "在开场建立观看理由和信息缺口",
        "Rhythm": "管理铺垫、推进、峰值和收束的时间分配",
        "Transition": "让段落之间形成顺序、转折、因果或举例关系",
        "Ending": "回扣开场任务并完成理解闭环",
        "Visualization": "用画面、封面或图示压缩信息和引导理解",
        "World Building": "解释规则、关系和背景，让复杂设定可进入",
        "Character": "用动机、选择、代价和成长线理解人物",
        "Explanation": "把陌生概念变成可递进理解的知识路径",
        "Teaching": "降低理解门槛并维持学习兴趣",
        "Plot Analysis": "拆解剧情节点、人物关系和主题表达",
        "Anime Narrative": "压缩动漫剧情并保留动机、设定和期待感",
        "Science Narrative": "用科普叙事处理概念、证据和未解问题",
        "Historical Narrative": "用历史叙事连接人物、时代和因果链",
        "Narration": "把叙事、逻辑和情绪整合成连续表达",
    }
    return table.get(category, "可迁移创作能力")


def _category_methods(category: str) -> list[str]:
    table = {
        "Hook": ["提出明确问题", "制造反差或异常", "说明观看任务"],
        "Logic": ["按时间线排序", "拆解背景变量", "把原因和结果分层"],
        "Storytelling": ["确定主角或核心对象", "设计冲突链", "在结尾回收结果"],
        "Explanation": ["先定义概念", "再解释机制", "最后说明边界"],
        "Rhythm": ["前段建立任务", "中段推进信息", "后段集中收束"],
        "Transition": ["顺序推进", "转折校正", "因果收束", "举例说明"],
        "Ending": ["回扣开场", "归纳收获", "留下合理余味"],
        "Character": ["提炼动机", "展示选择", "说明代价和变化"],
        "World Building": ["先讲规则", "再讲关系", "最后讲冲突影响"],
        "Visualization": ["压缩题眼", "分层呈现信息", "用视觉提示理解路径"],
        "Teaching": ["降低门槛", "控制信息密度", "用例子承接抽象概念"],
        "Plot Analysis": ["拆剧情节点", "拆人物动机", "拆主题回扣"],
        "Anime Narrative": ["保留主线", "压缩支线", "提炼高光和期待"],
        "Science Narrative": ["概念导入", "证据解释", "争议或未知边界"],
        "Historical Narrative": ["时代背景", "关键变量", "事件链条", "结果复盘"],
        "Emotion": ["建立处境", "递进情绪", "控制留白", "完成回收"],
        "Narration": ["统一任务", "组织段落", "连接信息", "结尾闭环"],
    }
    return table.get(category, ["抽象能力", "结构化应用", "避免措辞模仿"])


def _counter_payload(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"item": key, "count": value} for key, value in counter.most_common() if key]


def _format_counter_payload(items: list[dict[str, Any]]) -> str:
    if not items:
        return "暂无"
    return "、".join(f"{item.get('item')}({item.get('count')})" for item in items if item.get("item"))


def _compliance_note() -> dict[str, Any]:
    return {
        "learns": "结构、顺序、功能、能力和抽象方法",
        "does_not_learn": "原文措辞、原句、原段落、个人口头禅或具体观点照搬",
        "raw_text_policy": "原始字幕只作为上游证据，不写入 Creator Knowledge Base。",
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _slug(value: str) -> str:
    safe = re.sub(r'[\\/:*?"<>|\s]+', "_", str(value)).strip("_")
    return safe[:80] or "unknown"


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


def _duration_seconds(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "")
    parts = text.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return None
    return None


TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9_+-]+")


def _tokenize(text: str) -> list[str]:
    tokens = []
    for item in TOKEN_RE.findall(text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", item):
            tokens.extend(item)
            tokens.extend(item[index : index + 2] for index in range(max(0, len(item) - 1)))
        else:
            tokens.append(item)
    return [token for token in tokens if token.strip()]


def _cosine_tfidf(
    query: Counter[str],
    doc: Counter[str],
    df: Counter[str],
    total_docs: int,
) -> float:
    q_vec = _tfidf(query, df, total_docs)
    d_vec = _tfidf(doc, df, total_docs)
    numerator = sum(q_vec[token] * d_vec.get(token, 0.0) for token in q_vec)
    q_norm = math.sqrt(sum(value * value for value in q_vec.values()))
    d_norm = math.sqrt(sum(value * value for value in d_vec.values()))
    if not q_norm or not d_norm:
        return 0.0
    return numerator / (q_norm * d_norm)


def _category_query_boost(query: str, doc: dict[str, Any]) -> float:
    q = query.lower()
    category = str(doc.get("category", ""))
    aliases = {
        "Storytelling": ["storytelling", "故事", "叙事"],
        "Logic": ["logic", "逻辑", "因果", "论证"],
        "Emotion": ["emotion", "情绪", "共情"],
        "Hook": ["hook", "钩子", "开头", "开场", "悬念"],
        "Rhythm": ["rhythm", "节奏"],
        "Transition": ["transition", "转场", "衔接", "过渡"],
        "Ending": ["ending", "结尾", "收束"],
        "Visualization": ["visual", "视觉", "图示", "画面"],
        "World Building": ["world", "世界观", "设定"],
        "Character": ["character", "人物", "角色", "动机"],
        "Explanation": ["explanation", "解释", "讲解", "概念"],
        "Teaching": ["teaching", "教学", "降低理解"],
        "Plot Analysis": ["plot", "剧情", "解析"],
        "Anime Narrative": ["anime", "动漫", "番剧"],
        "Science Narrative": ["science", "科学", "科普"],
        "Historical Narrative": ["history", "历史"],
        "Narration": ["narration", "叙述", "表达"],
        "Template": ["template", "模板", "脚本", "开头", "转场", "结尾", "高潮", "工作流"],
    }
    boost = 0.0
    category_aliases = aliases.get(category, [])
    for alias in category_aliases:
        if alias in q:
            boost += 0.25
    title = str(doc.get("title", "")).lower()
    capability = str(doc.get("capability", "")).lower()
    for token in _tokenize(query):
        if token.lower() in title:
            boost += 0.05
        if token in capability:
            boost += 0.03
    return min(boost, 0.45)


def _tfidf(tokens: Counter[str], df: Counter[str], total_docs: int) -> dict[str, float]:
    total_terms = sum(tokens.values()) or 1
    return {
        token: (count / total_terms) * (math.log((1 + total_docs) / (1 + df.get(token, 0))) + 1)
        for token, count in tokens.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or search the Creator Knowledge Base.")
    parser.add_argument("--output-root", default=str(SETTINGS.output_dir))
    parser.add_argument("--cache-root", default=str(SETTINGS.cache_dir))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--creator-specs", default=str(CREATOR_SPECS_PATH))
    parser.add_argument("--search", default="")
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()

    if args.search:
        results = search_creator_knowledge_base(args.search, top_k=args.top_k)
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    paths = build_creator_knowledge_base(
        output_root=Path(args.output_root),
        cache_root=Path(args.cache_root),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        creator_specs_path=Path(args.creator_specs) if args.creator_specs else None,
    )
    for kind, path in paths.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
