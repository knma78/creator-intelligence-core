from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, median
from typing import Any

from config import SETTINGS


RULE_COLLECTIONS = [
    "hook_templates",
    "script_structure_templates",
    "transition_templates",
    "climax_templates",
    "ending_templates",
    "workflow_templates",
]

COLLECTION_LABELS = {
    "hook_templates": "Hook",
    "script_structure_templates": "脚本结构",
    "transition_templates": "转场",
    "climax_templates": "高潮",
    "ending_templates": "结尾",
    "workflow_templates": "工作流",
}

TRANSITION_SIGNALS = {
    "transition_sequence": {"顺序启动", "过程推进", "段落连接", "并列递进"},
    "transition_turning_point": {"转折校正", "反向推进"},
    "transition_causal_close": {"因果收束", "结尾收束"},
    "transition_example_bridge": {"举例说明"},
}

KEYWORD_SIGNALS = {
    "hook_contrast_gap": {"反常识", "反差", "冲突", "风险", "异常", "悬念", "规则", "对比"},
    "hook_question_task": {"问题", "提问", "设问", "疑问"},
    "hook_objective_first": {"直接", "主题", "对象", "任务", "快速交代"},
    "climax_conflict_convergence": {"冲突", "选择", "反转", "后果", "代价"},
    "climax_evidence_convergence": {"证据", "判断", "因果", "变量", "结论"},
    "climax_mechanism_reveal": {"机制", "解释", "原理", "揭示", "验证"},
    "climax_visual_result": {"视觉", "画面", "实验", "制作", "结果"},
    "ending_question_callback": {"问题", "回扣", "答案", "闭环"},
    "ending_logic_closure": {"结论", "判断", "因果", "观点", "结果"},
    "ending_emotional_aftertaste": {"余味", "情绪", "人物", "留白", "共情"},
    "ending_expectation_bridge": {"期待", "后续", "下一", "悬念", "未完"},
}


def build_rule_library(
    template_payload: dict[str, Any],
    output_root: Path = SETTINGS.output_dir,
    output_dir: Path | None = None,
    cache_root: Path | None = None,
) -> dict[str, Path]:
    output_root = output_root.resolve()
    output_dir = (
        output_dir or output_root / "creator_knowledge_base" / "rules"
    ).resolve()
    cache_root = (cache_root or output_root.parent / "cache").resolve()
    cache_dir = cache_root / "creator_knowledge_base"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    library_path = output_dir / "rule_library.json"
    generated_at = datetime.now().isoformat(timespec="seconds")
    previous = _read_json(library_path)
    prior_ids = {
        str(rule.get("template_id")): str(rule.get("rule_id"))
        for rule in previous.get("rules", [])
        if rule.get("template_id") and _valid_rule_id(rule.get("rule_id"))
    }
    templates = _collect_templates(template_payload)
    rule_ids = _assign_rule_ids(templates, prior_ids)
    samples = _load_samples(output_root)
    previous_rules = {
        str(rule.get("template_id")): rule
        for rule in previous.get("rules", [])
        if rule.get("template_id")
    }
    review_path = output_dir / "rule_reviews.json"
    if not review_path.exists():
        review_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "description": "人工复核登记表。键可以使用 rule_id 或 template_id。",
                    "reviews": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    reviews = (_read_json(review_path).get("reviews") or {})
    bundles = [
        _build_knowledge_bundle(
            template,
            collection,
            rule_ids[template["id"]],
            samples,
            previous_rules.get(str(template["id"]), {}),
            reviews.get(rule_ids[template["id"]])
            or reviews.get(str(template["id"]))
            or {},
            generated_at,
        )
        for collection, template in templates
    ]
    rules = [bundle["rule"] for bundle in bundles]
    patterns = [
        bundle["pattern"]
        for bundle in bundles
        if bundle.get("pattern")
    ]
    observations = [
        observation
        for bundle in bundles
        for observation in bundle.get("observations", [])
    ]
    rag_documents = [
        *[_rule_rag_document(rule) for rule in rules],
        *[_pattern_rag_document(pattern) for pattern in patterns],
        *[_observation_rag_document(observation) for observation in observations],
    ]
    payload = {
        "schema_version": "creator-knowledge-library/v2",
        "version": 2,
        "generated_at": generated_at,
        "source": {
            "template_count": len(templates),
            "analyzed_video_count": len(samples),
            "creator_count": len({sample["author"] for sample in samples if sample["author"]}),
        },
        "policy": {
            "goal": "把视频观察、跨样本模式和可调用规则分层保存。",
            "knowledge_layers": {
                "Observation": "单条视频中由结构化分析检测到的信号。",
                "Pattern": "多个 Observation 的聚合，不包含因果结论。",
                "Rule": "基于 Pattern 形成的条件性创作假设。",
            },
            "evidence_policy": (
                "模式存在与传播效果分开评估；没有留存或完播数据时，"
                "不得把播放量当作因果证明。"
            ),
            "counterexample_policy": (
                "反例必须尽量匹配内容定位和时长区间，"
                "仅说明存在替代机制，不否定规则。"
            ),
            "do_not_use": ["原文句子", "原文段落", "口头禅", "个人化语气", "具体观点照搬"],
        },
        "rule_count": len(rules),
        "pattern_count": len(patterns),
        "observation_count": len(observations),
        "rules": rules,
        "pattern_library": patterns,
        "observation_library": observations,
        "rag_index": {
            "version": 2,
            "document_count": len(rag_documents),
            "documents": rag_documents,
        },
    }

    markdown_path = output_dir / "rule_library.md"
    observation_dir = output_dir / "observations"
    pattern_dir = output_dir / "patterns"
    observation_dir.mkdir(parents=True, exist_ok=True)
    pattern_dir.mkdir(parents=True, exist_ok=True)
    observation_json_path = observation_dir / "observation_library.json"
    pattern_json_path = pattern_dir / "pattern_library.json"
    pattern_markdown_path = pattern_dir / "pattern_library.md"
    index_path = output_dir / "rule_index.json"
    cache_index_path = cache_dir / "rule_index.json"
    library_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_build_library_markdown(payload), encoding="utf-8")
    observation_json_path.write_text(
        json.dumps(
            {
                "schema_version": "creator-knowledge-observation/v2",
                "generated_at": generated_at,
                "observation_count": len(observations),
                "observations": observations,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    pattern_json_path.write_text(
        json.dumps(
            {
                "schema_version": "creator-knowledge-pattern/v2",
                "generated_at": generated_at,
                "pattern_count": len(patterns),
                "patterns": patterns,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    pattern_markdown_path.write_text(
        _build_pattern_library_markdown(patterns, generated_at),
        encoding="utf-8",
    )
    index_payload = payload["rag_index"]
    index_path.write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    cache_index_path.write_text(
        json.dumps(index_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for rule in rules:
        (output_dir / f"{rule['rule_id']}.md").write_text(
            _build_rule_markdown(rule),
            encoding="utf-8",
        )
    _write_observation_markdown(observation_dir, observations, generated_at)
    for pattern in patterns:
        (pattern_dir / f"{pattern['pattern_id']}.md").write_text(
            _build_pattern_markdown(pattern),
            encoding="utf-8",
        )
    return {
        "rule_library_json": library_path,
        "rule_library_markdown": markdown_path,
        "rule_rag_index": index_path,
        "cache_rule_rag_index": cache_index_path,
        "observation_library_json": observation_json_path,
        "pattern_library_json": pattern_json_path,
        "pattern_library_markdown": pattern_markdown_path,
        "rule_reviews": review_path,
    }


def _collect_templates(
    template_payload: dict[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    return [
        (collection, template)
        for collection in RULE_COLLECTIONS
        for template in template_payload.get(collection, [])
        if template.get("id")
    ]


def _assign_rule_ids(
    templates: list[tuple[str, dict[str, Any]]],
    prior_ids: dict[str, str],
) -> dict[str, str]:
    assigned = {}
    used = {rule_id for rule_id in prior_ids.values() if _valid_rule_id(rule_id)}
    next_number = max(
        [int(rule_id.split("-")[1]) for rule_id in used] or [0]
    ) + 1
    for _, template in templates:
        template_id = str(template["id"])
        if template_id in prior_ids:
            assigned[template_id] = prior_ids[template_id]
            continue
        while f"R-{next_number:03d}" in used:
            next_number += 1
        rule_id = f"R-{next_number:03d}"
        assigned[template_id] = rule_id
        used.add(rule_id)
        next_number += 1
    return assigned


def _valid_rule_id(value: Any) -> bool:
    return bool(re.fullmatch(r"R-\d{3,}", str(value or "")))


def _load_samples(output_root: Path) -> list[dict[str, Any]]:
    integrated = _read_json(output_root / "integrated" / "integrated_summary.json")
    metadata = {
        str(video.get("video_id")): video
        for video in integrated.get("videos", [])
        if video.get("video_id")
    }
    samples = []
    analysis_root = output_root / "creator_knowledge_base" / "videos"
    if not analysis_root.exists():
        return samples
    for path in sorted(analysis_root.glob("*/analysis.json")):
        analysis = _read_json(path)
        video_id = str(analysis.get("video_id") or path.parent.name)
        if not video_id:
            continue
        info = analysis.get("video_info") or {}
        structure = analysis.get("content_structure") or {}
        expression = analysis.get("expression") or {}
        meta = metadata.get(video_id, {})
        raw_analysis_path = Path(str(meta.get("analysis_path") or ""))
        raw_analysis = _read_json(raw_analysis_path) if raw_analysis_path.is_file() else {}
        raw_structure = raw_analysis.get("structure") or []
        coverage = _analysis_coverage(raw_structure, meta.get("duration"))
        samples.append(
            {
                "video_id": video_id,
                "author": str(info.get("作者") or meta.get("author") or ""),
                "positioning": str(analysis.get("creator_positioning") or ""),
                "view_count": _as_int(info.get("播放量") or meta.get("view_count")),
                "like_rate": _as_float(meta.get("like_rate")),
                "comment_rate": _as_float(meta.get("comment_rate")),
                "duration": _as_float(meta.get("duration")),
                "duration_bucket": _duration_bucket(meta.get("duration")),
                "hook_style": str((structure.get("Hook") or {}).get("style") or ""),
                "hook_capability": str(
                    (structure.get("Hook") or {}).get("capability") or ""
                ),
                "transitions": [
                    str(item)
                    for item in expression.get("转场", [])
                    if str(item).strip()
                ],
                "climax_design": str(
                    (structure.get("高潮") or {}).get("design") or ""
                ),
                "ending_design": str(
                    (structure.get("结尾") or {}).get("design") or ""
                ),
                "locations": {
                    "Hook": _bounded_time_range(
                        _first_time_range(raw_structure),
                        maximum_span_seconds=60,
                    ),
                    "脚本结构": coverage.get("time_range", ""),
                    "转场": "",
                    "高潮": _extract_time_range(
                        str((raw_analysis.get("rhythm") or {}).get("高潮位置") or "")
                    ),
                    "结尾": (
                        _last_time_range(raw_structure)
                        if coverage.get("coverage_ratio", 0) >= 0.8
                        else ""
                    ),
                },
                "analysis_coverage": coverage,
                "source_paths": {
                    "capability_analysis": _portable_path(path, output_root),
                    "upstream_analysis": _portable_path(raw_analysis_path, output_root)
                    if raw_analysis_path.is_file()
                    else "",
                },
            }
        )
    author_views: dict[str, list[int]] = {}
    for sample in samples:
        if sample["author"] and sample["view_count"] > 0:
            author_views.setdefault(sample["author"], []).append(sample["view_count"])
    author_average_views = {
        author: mean(values)
        for author, values in author_views.items()
        if values
    }
    for sample in samples:
        average_views = author_average_views.get(sample["author"], 0)
        sample["relative_view_index"] = round(
            sample["view_count"] / average_views,
            4,
        ) if average_views else None
    return samples


def _build_knowledge_bundle(
    template: dict[str, Any],
    collection: str,
    rule_id: str,
    samples: list[dict[str, Any]],
    previous_rule: dict[str, Any],
    review: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    template_id = str(template["id"])
    direct_matches = [
        sample for sample in samples if _matches_template(template, collection, sample)
    ]
    observable = collection != "workflow_templates"
    evidence_type = "direct_pattern_observation"
    selected = direct_matches
    if not observable:
        evidence_type = "synthesized_workflow"
        selected = _indirect_samples(template, samples)
    elif not selected:
        evidence_type = "indirect_capability_support"
        selected = _indirect_samples(template, samples)

    selected = sorted(
        _dedupe_samples(selected),
        key=lambda sample: (-sample["view_count"], sample["video_id"]),
    )
    observations = (
        [
            _build_observation(
                rule_id,
                template,
                collection,
                sample,
            )
            for sample in selected
        ]
        if evidence_type == "direct_pattern_observation"
        else []
    )
    representatives = _representative_samples(selected, limit=12)
    creators = sorted({sample["author"] for sample in selected if sample["author"]})
    location_count = sum(
        1
        for observation in observations
        if observation["location"]["time_range"]
    )
    effect_evidence = _effect_evidence(selected, samples)
    evidence = {
        "evidence_type": evidence_type,
        "evidence_label": {
            "direct_pattern_observation": "逐视频结构化标签直接匹配",
            "indirect_capability_support": "能力文档间接支撑",
            "synthesized_workflow": "跨能力规则综合",
        }[evidence_type],
        "matching_basis": _matching_basis(template, collection),
        "video_count": len(selected),
        "creator_count": len(creators),
        "sample_ratio": round(len(selected) / max(len(samples), 1), 4),
        "observation_unit": "每条视频最多计为一次规则观测",
        "creators": creators,
        "video_ids": [sample["video_id"] for sample in selected],
        "observation_ids": [
            observation["observation_id"] for observation in observations
        ],
        "located_observation_count": location_count,
        "examples": [
            {
                "video_id": sample["video_id"],
                "author": sample["author"],
                "view_count": sample["view_count"],
                "matched_signal": _sample_signal(template, collection, sample),
                "relative_view_index": sample.get("relative_view_index"),
                "observation_id": (
                    f"O-{rule_id}-{sample['video_id']}"
                    if observations
                    else ""
                ),
            }
            for sample in representatives
        ],
    }
    counterexamples = _counterexamples(
        template,
        collection,
        samples,
        direct_matches,
        evidence_type,
    )
    confidence = _confidence_v2(
        evidence_type,
        selected,
        samples,
        location_count,
        effect_evidence,
        bool(review.get("approved")),
    )
    pattern = (
        _build_pattern(
            rule_id,
            template,
            collection,
            observations,
            selected,
            counterexamples,
            confidence,
        )
        if observations
        else None
    )
    human_reviewed = bool(review.get("approved"))
    status = str(review.get("status") or ("validated" if human_reviewed else "candidate"))
    if status not in {"candidate", "validated", "deprecated", "rejected"}:
        status = "candidate"
    action = _action(template, collection)
    action["knowledge_origin"] = {
        "materials": "inferred",
        "editing_sequence": "inferred",
        "editing_guidance": "recommended",
        "quality_checks": "recommended",
    }
    action["observed_basis"] = (
        pattern["pattern_id"] if pattern else "没有直接 Pattern，仅为综合工作流假设"
    )
    rule = {
        "schema_version": "creator-knowledge-rule/v2",
        "knowledge_type": "transferable_rule",
        "rule_id": rule_id,
        "template_id": template_id,
        "version": "2.0",
        "status": status,
        "human_reviewed": human_reviewed,
        "review": {
            "reviewer": review.get("reviewer", ""),
            "reviewed_at": review.get("reviewed_at", ""),
            "notes": review.get("notes", ""),
        },
        "name": template.get("name", template_id),
        "collection": collection,
        "category": COLLECTION_LABELS.get(collection, collection),
        "related_categories": template.get("related_categories", []),
        "Claim": (
            f"当“{template.get('use_when', '')}”成立时，可以测试"
            f"“{template.get('name', template_id)}”来实现"
            f"“{_communication_goal(template, collection)}”。"
            "该声明是条件性创作假设，不是已证实的因果定律。"
        ),
        "Trigger": {
            "description": template.get("use_when", ""),
            "required_signals": _required_signals(template, collection),
        },
        "Goal": {
            "communication_goal": _communication_goal(template, collection),
            "capability": template.get("capability", ""),
        },
        "Mechanism": {
            "hypothesis": _mechanism_hypothesis(collection),
            "causal_status": "unverified",
            "what_is_not_proven": "当前数据不能证明该机制直接导致播放、留存或完播提升。",
        },
        "Knowledge Origin": {
            "observed": (
                f"{len(observations)} 条逐视频结构化观察"
                if observations
                else "没有可直接观测的逐视频动作"
            ),
            "inferred": ["触发条件", "素材槽位", "组织顺序"],
            "recommended": ["剪辑建议", "质量检查", "停用条件"],
        },
        "Action": action,
        "Constraints": _constraints(template, collection),
        "Evidence": evidence,
        "Effect Evidence": effect_evidence,
        "Confidence": confidence,
        "Counter Examples": counterexamples,
        "Provenance": {
            "generator": "exporter.rule_library",
            "source_layers": (
                ["Observation", "Pattern", "Rule"]
                if observations
                else ["capability_template", "Rule"]
            ),
            "source_analysis_paths": sorted(
                {
                    source_path
                    for sample in selected
                    for source_path in sample.get("source_paths", {}).values()
                    if source_path
                }
            ),
            "raw_text_included": False,
            "generated_at": generated_at,
        },
        "Revision History": _revision_history(previous_rule, generated_at),
    }
    return {
        "rule": rule,
        "pattern": pattern,
        "observations": observations,
    }


def _build_observation(
    rule_id: str,
    template: dict[str, Any],
    collection: str,
    sample: dict[str, Any],
) -> dict[str, Any]:
    category = COLLECTION_LABELS.get(collection, collection)
    time_range = str((sample.get("locations") or {}).get(category) or "")
    signal = _sample_signal(template, collection, sample)
    confidence_score = 0.68 if time_range else 0.56
    return {
        "schema_version": "creator-knowledge-observation/v2",
        "knowledge_type": "observation",
        "observation_id": f"O-{rule_id}-{sample['video_id']}",
        "rule_id": rule_id,
        "video_id": sample["video_id"],
        "creator": sample["author"],
        "positioning": sample["positioning"],
        "claim": (
            f"自动结构化分析在该视频的{category}中检测到"
            f"与“{template.get('name', template['id'])}”相符的功能信号。"
        ),
        "detected_signal": signal,
        "location": {
            "section": category,
            "time_range": time_range,
            "precision": "estimated_from_upstream_structure" if time_range else "unknown",
        },
        "analysis_coverage": sample.get("analysis_coverage", {}),
        "performance_context": {
            "view_count": sample["view_count"],
            "relative_view_index": sample.get("relative_view_index"),
            "like_rate": sample.get("like_rate"),
            "comment_rate": sample.get("comment_rate"),
            "retention_available": False,
            "causal_interpretation_allowed": False,
        },
        "confidence": {
            "score": confidence_score,
            "level": _confidence_level(confidence_score),
            "basis": (
                "结构化标签与规则信号匹配；"
                + ("同时存在估算时间位置。" if time_range else "没有可靠时间位置。")
            ),
            "human_reviewed": False,
        },
        "provenance": {
            "source_paths": sample.get("source_paths", {}),
            "extractor": "exporter.rule_library",
            "raw_text_included": False,
        },
    }


def _build_pattern(
    rule_id: str,
    template: dict[str, Any],
    collection: str,
    observations: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    counterexamples: list[dict[str, Any]],
    confidence: dict[str, Any],
) -> dict[str, Any]:
    positioning_counts = Counter(
        sample["positioning"] or "未知定位" for sample in samples
    )
    duration_counts = Counter(
        sample["duration_bucket"] or "未知时长" for sample in samples
    )
    located_count = sum(
        1 for observation in observations if observation["location"]["time_range"]
    )
    return {
        "schema_version": "creator-knowledge-pattern/v2",
        "knowledge_type": "pattern",
        "pattern_id": f"P-{rule_id}",
        "rule_id": rule_id,
        "template_id": template["id"],
        "name": template.get("name", template["id"]),
        "category": COLLECTION_LABELS.get(collection, collection),
        "claim": (
            f"在 {len(observations)} 条视频的自动结构化分析中，"
            f"反复检测到与“{template.get('name', template['id'])}”相符的功能信号。"
        ),
        "frequency": {
            "observation_count": len(observations),
            "creator_count": len(
                {observation["creator"] for observation in observations if observation["creator"]}
            ),
            "located_observation_count": located_count,
        },
        "distribution": {
            "positionings": dict(positioning_counts.most_common()),
            "duration_buckets": dict(duration_counts.most_common()),
        },
        "observation_ids": [
            observation["observation_id"] for observation in observations
        ],
        "video_ids": [observation["video_id"] for observation in observations],
        "performance_summary": _performance_summary(samples),
        "counter_evidence": counterexamples,
        "causal_status": "correlation_only",
        "confidence": confidence["pattern_confidence"],
        "limitations": [
            "模式来自自动结构化标签，尚未逐条人工复核。",
            "模式出现频率不能证明它导致更高播放、留存或完播。",
            "上游分析可能只覆盖视频的一部分，时间位置可能缺失。",
        ],
    }


def _effect_evidence(
    selected: list[dict[str, Any]],
    all_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    relative_views = [
        float(sample["relative_view_index"])
        for sample in selected
        if sample.get("relative_view_index") is not None
    ]
    like_rates = [
        float(sample["like_rate"])
        for sample in selected
        if sample.get("like_rate") is not None
    ]
    comment_rates = [
        float(sample["comment_rate"])
        for sample in selected
        if sample.get("comment_rate") is not None
    ]
    metric_ratio = (
        len(relative_views) / max(len(selected), 1)
        if selected
        else 0.0
    )
    score = min(
        0.35,
        0.08
        + 0.12 * metric_ratio
        + 0.05 * int(bool(like_rates))
        + 0.05 * int(bool(comment_rates)),
    ) if selected else 0.05
    return {
        "status": "proxy_only",
        "sample_count": len(selected),
        "available_metrics": {
            "relative_view_index": len(relative_views),
            "like_rate": len(like_rates),
            "comment_rate": len(comment_rates),
            "retention": 0,
            "completion_rate": 0,
        },
        "summary": {
            "median_relative_view_index": _round_median(relative_views),
            "median_like_rate": _round_median(like_rates, 6),
            "median_comment_rate": _round_median(comment_rates, 6),
            "total_project_sample_count": len(all_samples),
        },
        "confidence_score": round(score, 2),
        "causal_status": "not_established",
        "interpretation": (
            "播放、点赞和评论只能作为结果代理变量；"
            "缺少留存、完播和受控对照，不能用于证明规则有效。"
        ),
    }


def _performance_summary(samples: list[dict[str, Any]]) -> dict[str, Any]:
    relative_views = [
        float(sample["relative_view_index"])
        for sample in samples
        if sample.get("relative_view_index") is not None
    ]
    return {
        "median_relative_view_index": _round_median(relative_views),
        "above_creator_average_count": sum(value >= 1 for value in relative_views),
        "sample_with_relative_view_count": len(relative_views),
        "causal_status": "not_established",
    }


def _confidence_v2(
    evidence_type: str,
    selected: list[dict[str, Any]],
    all_samples: list[dict[str, Any]],
    located_count: int,
    effect_evidence: dict[str, Any],
    human_reviewed: bool,
) -> dict[str, Any]:
    video_count = len(selected)
    creator_count = len({sample["author"] for sample in selected if sample["author"]})
    count_score = min(1.0, video_count / 15)
    creator_score = min(1.0, creator_count / 4)
    ratio_score = min(
        1.0,
        (video_count / max(len(all_samples), 1)) / 0.2,
    )
    pattern_score = 0.5 * count_score + 0.3 * creator_score + 0.2 * ratio_score
    if evidence_type == "indirect_capability_support":
        pattern_score = min(pattern_score, 0.35)
    elif evidence_type == "synthesized_workflow":
        pattern_score = min(pattern_score, 0.25)
    else:
        pattern_score = min(pattern_score, 0.9)

    location_ratio = located_count / max(video_count, 1)
    metric_ratio = (
        effect_evidence["available_metrics"]["relative_view_index"]
        / max(video_count, 1)
    )
    quality_score = min(
        0.68,
        0.28
        + 0.18 * location_ratio
        + 0.12 * metric_ratio
        + 0.10 * min(1.0, creator_count / 4),
    )
    if evidence_type != "direct_pattern_observation":
        quality_score = min(quality_score, 0.38)

    effect_score = float(effect_evidence.get("confidence_score") or 0)
    overall = 0.55 * pattern_score + 0.25 * quality_score + 0.20 * effect_score
    if human_reviewed:
        overall = min(0.9, overall + 0.1)
    else:
        overall = min(0.74, overall)

    pattern_score = round(pattern_score, 2)
    quality_score = round(quality_score, 2)
    overall = round(overall, 2)
    return {
        "score": overall,
        "level": _confidence_level(overall),
        "pattern_confidence": {
            "score": pattern_score,
            "level": _confidence_level(pattern_score),
            "meaning": "该结构信号在样本中稳定出现的确定程度。",
        },
        "effect_confidence": {
            "score": effect_score,
            "level": _confidence_level(effect_score),
            "meaning": "该模式能提升传播结果的确定程度。",
        },
        "evidence_quality": {
            "score": quality_score,
            "level": _confidence_level(quality_score),
            "located_observation_ratio": round(location_ratio, 4),
            "metric_coverage_ratio": round(metric_ratio, 4),
            "human_reviewed": human_reviewed,
        },
        "rationale": (
            f"模式证据来自 {video_count} 条视频、{creator_count} 个创作者；"
            "效果证据只有播放、点赞和评论代理指标，没有留存或完播数据。"
            + ("已登记人工复核。" if human_reviewed else "尚未登记人工复核。")
        ),
        "limitations": [
            "自动标签可能存在误判。",
            "播放指标受题材、发布时间、账号规模和平台分发影响。",
            "没有受控实验，不能作因果推断。",
        ],
    }


def _confidence_level(score: float) -> str:
    return "高" if score >= 0.75 else "中" if score >= 0.5 else "低"


def _mechanism_hypothesis(collection: str) -> str:
    return {
        "hook_templates": "通过尽早建立信息任务，减少观众判断内容价值所需的时间。",
        "script_structure_templates": "通过明确的信息层级降低工作记忆负担并维持理解连续性。",
        "transition_templates": "通过显式标记段落关系，减少信息跳跃造成的理解中断。",
        "climax_templates": "通过集中兑现前文铺垫，提高关键结果的感知强度。",
        "ending_templates": "通过回收开场任务，帮助观众形成完整记忆单元。",
        "workflow_templates": "通过生成前约束减少证据遗漏和结构冲突。",
    }.get(collection, "通过结构化信息组织降低理解成本。")


def _revision_history(
    previous_rule: dict[str, Any],
    generated_at: str,
) -> list[dict[str, Any]]:
    history = list(previous_rule.get("Revision History") or [])
    if not history and previous_rule:
        history.append(
            {
                "version": str(previous_rule.get("version") or "1.0"),
                "date": str(
                    (previous_rule.get("Provenance") or {}).get("generated_at")
                    or generated_at
                ),
                "change": "旧版单层规则结构。",
            }
        )
    if not any(str(item.get("version")) == "2.0" for item in history):
        history.append(
            {
                "version": "2.0",
                "date": generated_at,
                "change": (
                    "迁移为 Observation、Pattern、Rule 三级知识结构；"
                    "拆分模式置信度与效果置信度。"
                ),
            }
        )
    return history


def _matches_template(
    template: dict[str, Any],
    collection: str,
    sample: dict[str, Any],
) -> bool:
    template_id = str(template["id"])
    if collection == "script_structure_templates":
        return bool(
            template.get("positioning")
            and sample["positioning"] == template.get("positioning")
        )
    if collection == "transition_templates":
        return bool(
            set(sample["transitions"]) & TRANSITION_SIGNALS.get(template_id, set())
        )
    if collection == "hook_templates":
        text = f"{sample['hook_style']} {sample['hook_capability']}"
    elif collection == "climax_templates":
        text = sample["climax_design"]
    elif collection == "ending_templates":
        text = sample["ending_design"]
    else:
        return False
    if template_id == "ending_question_callback":
        return _contains_any(text, {"问题", "答案"}) and _contains_any(
            text,
            {"回扣", "闭环"},
        )
    return _contains_any(text, KEYWORD_SIGNALS.get(template_id, set()))


def _contains_any(text: str, keywords: set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _indirect_samples(
    template: dict[str, Any],
    samples: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_ids = {
        str(video_id)
        for video_id in (template.get("evidence") or {}).get("source_video_ids", [])
    }
    return [sample for sample in samples if sample["video_id"] in source_ids]


def _dedupe_samples(samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return list({sample["video_id"]: sample for sample in samples}.values())


def _representative_samples(
    samples: list[dict[str, Any]],
    limit: int,
) -> list[dict[str, Any]]:
    best_by_creator: dict[str, dict[str, Any]] = {}
    for sample in samples:
        creator_key = sample["author"] or sample["video_id"]
        best_by_creator.setdefault(creator_key, sample)
    representatives = sorted(
        best_by_creator.values(),
        key=lambda sample: (-sample["view_count"], sample["video_id"]),
    )[:limit]
    if len(representatives) >= limit:
        return representatives
    selected_ids = {sample["video_id"] for sample in representatives}
    representatives.extend(
        sample
        for sample in samples
        if sample["video_id"] not in selected_ids
    )
    return representatives[:limit]


def _matching_basis(template: dict[str, Any], collection: str) -> str:
    template_id = str(template["id"])
    if collection == "script_structure_templates":
        return f"创作者定位等于 {template.get('positioning', '未知定位')}"
    if collection == "transition_templates":
        return "转场功能包含：" + "、".join(
            sorted(TRANSITION_SIGNALS.get(template_id, set()))
        )
    if collection == "workflow_templates":
        return "该规则属于工作流综合，不能从单条成片标签直接观测"
    return "结构化分析信号包含：" + "、".join(
        sorted(KEYWORD_SIGNALS.get(template_id, set()))
    )


def _sample_signal(
    template: dict[str, Any],
    collection: str,
    sample: dict[str, Any],
) -> str:
    if collection == "script_structure_templates":
        return sample["positioning"]
    if collection == "transition_templates":
        signals = set(sample["transitions"]) & TRANSITION_SIGNALS.get(
            str(template["id"]), set()
        )
        return "、".join(sorted(signals)) or "间接支撑"
    if collection == "hook_templates":
        source_text = f"{sample['hook_style']} {sample['hook_capability']}"
    elif collection == "climax_templates":
        source_text = sample["climax_design"]
    elif collection == "ending_templates":
        source_text = sample["ending_design"]
    else:
        return "跨能力流程支撑"
    matched = [
        keyword
        for keyword in sorted(KEYWORD_SIGNALS.get(str(template["id"]), set()))
        if keyword in source_text
    ]
    return "、".join(matched) or "间接支撑"


def _required_signals(
    template: dict[str, Any],
    collection: str,
) -> list[str]:
    template_id = str(template["id"])
    if collection == "script_structure_templates":
        return [f"内容任务属于 {template.get('positioning', '对应定位')}"]
    if collection == "transition_templates":
        return sorted(TRANSITION_SIGNALS.get(template_id, set()))
    if collection == "workflow_templates":
        return ["输入槽位完整", "资料来源可复核", "创作目标明确"]
    return sorted(KEYWORD_SIGNALS.get(template_id, set()))


def _communication_goal(
    template: dict[str, Any],
    collection: str,
) -> str:
    goals = {
        "hook_templates": "尽快建立观看理由，并明确正文需要兑现的信息任务。",
        "script_structure_templates": "让信息按观众可理解的顺序推进，并在结尾完成任务闭环。",
        "transition_templates": "说明相邻段落的逻辑关系，降低理解跳跃。",
        "climax_templates": "让前文铺设的冲突、证据、机制或视觉结果集中兑现。",
        "ending_templates": "回收开场承诺，留下清晰结论、判断框架或情绪余味。",
        "workflow_templates": "在生成前把任务、证据、能力模块和质量边界组织完整。",
    }
    return goals.get(collection, template.get("use_when", ""))


def _action(template: dict[str, Any], collection: str) -> dict[str, Any]:
    materials = list(template.get("input_slots", []))
    sequence = list(template.get("sequence", []))
    edit_guides = {
        "hook_templates": [
            "优先展示能直接证明问题、反差或任务的画面，不先铺完整背景。",
            "将触发信息放在前 15-30 秒；每个镜头只承担对象、异常、结果预告或任务中的一个功能。",
            "在给出足够观看理由后立即进入第一层背景或证据。",
        ],
        "script_structure_templates": [
            "按执行顺序拆成章节，每章只解决一个主要问题。",
            "保留必要背景，重复信息和不能推进任务的素材应压缩或删除。",
            "在关键判断前集中相关证据，结尾回收开场任务。",
        ],
        "transition_templates": [
            "先保留上一段结论，再用下一段的首个证据或画面建立关系。",
            "只有关系不清楚时才增加桥接镜头、字幕标签或旁白说明。",
            "转场完成后立刻进入新信息，避免重复总结。",
        ],
        "climax_templates": [
            "集中展示关键选择、核心证据、机制揭示或最终结果。",
            "适度缩短高潮前后的镜头间隔，但不能牺牲因果和概念理解。",
            "高潮后保留结果解释或边界说明，不连续堆叠新高潮。",
        ],
        "ending_templates": [
            "回用开场提出的问题、任务或结果素材，不引入未展开的新主线。",
            "降低信息密度，保留结论、边界或情绪落点。",
            "在闭环完成后结束，删除重复总结和无功能口播。",
        ],
        "workflow_templates": [
            "先填齐输入槽位并标记每项资料来源，再执行生成步骤。",
            "每个阶段输出可复核中间结果，缺少证据时停止写成确定结论。",
            "生成后按质量检查逐项复核，并移除可模仿表达。",
        ],
    }
    return {
        "materials": materials,
        "editing_sequence": sequence,
        "editing_guidance": edit_guides.get(collection, []),
        "quality_checks": list(template.get("quality_checks", [])),
    }


def _constraints(template: dict[str, Any], collection: str) -> list[str]:
    base = {
        "hook_templates": "没有真实问题、反差、任务或后文兑现材料时不要使用。",
        "script_structure_templates": "内容任务与该结构定位不一致时不要强行套用。",
        "transition_templates": "相邻段落不存在该逻辑关系时不要添加形式化转场。",
        "climax_templates": "前文没有铺垫或证据不足时不要制造虚假高潮。",
        "ending_templates": "正文没有完成对应任务时不要用结尾措辞伪造闭环。",
        "workflow_templates": "输入槽位或事实证据缺失时不要进入自动生成。",
    }
    constraints = [base.get(collection, "缺少适用信号时不要使用。")]
    constraints.extend(
        f"检查未通过时停用：{item}"
        for item in template.get("quality_checks", [])
    )
    constraints.extend(
        f"禁止：{item}"
        for item in template.get("forbidden", [])
    )
    return list(dict.fromkeys(item for item in constraints if item))


def _counterexamples(
    template: dict[str, Any],
    collection: str,
    samples: list[dict[str, Any]],
    direct_matches: list[dict[str, Any]],
    evidence_type: str,
) -> list[dict[str, Any]]:
    if (
        evidence_type != "direct_pattern_observation"
        or not direct_matches
        or collection == "script_structure_templates"
    ):
        return []
    matched_ids = {sample["video_id"] for sample in direct_matches}
    comparable_positionings = {
        sample["positioning"] for sample in direct_matches if sample["positioning"]
    }
    comparable_durations = {
        sample["duration_bucket"] for sample in direct_matches if sample["duration_bucket"]
    }
    candidates = [
        sample
        for sample in samples
        if sample["video_id"] not in matched_ids
        and sample["view_count"] > 0
        and sample.get("relative_view_index") is not None
        and sample["relative_view_index"] >= 1
        and sample["positioning"] in comparable_positionings
        and sample["duration_bucket"] in comparable_durations
        and _alternative_pattern(collection, sample) != "未识别"
    ]
    candidates.sort(
        key=lambda sample: (
            -float(sample.get("relative_view_index") or 0),
            -sample["view_count"],
            sample["video_id"],
        )
    )
    return [
        {
            "video_id": sample["video_id"],
            "author": sample["author"],
            "view_count": sample["view_count"],
            "relative_view_index": sample["relative_view_index"],
            "alternative_pattern": _alternative_pattern(collection, sample),
            "comparison_basis": {
                "same_positioning": sample["positioning"],
                "same_duration_bucket": sample["duration_bucket"],
                "creator_relative_views_at_least_average": True,
            },
            "reason": (
                "该样本与规则证据具有相同内容定位和时长区间，"
                "且播放量不低于该创作者当前样本均值，但采用了另一种结构机制。"
                "它只证明存在替代方案，不证明哪一种机制更优。"
            ),
        }
        for sample in candidates[:3]
    ]


def _alternative_pattern(collection: str, sample: dict[str, Any]) -> str:
    if collection == "hook_templates":
        return _hook_family(sample)
    if collection == "script_structure_templates":
        return sample["positioning"] or "未识别"
    if collection == "transition_templates":
        return "、".join(sample["transitions"][:3]) or "未识别"
    if collection == "climax_templates":
        return _climax_family(sample)
    if collection == "ending_templates":
        return _ending_family(sample)
    return "未识别"


def _hook_family(sample: dict[str, Any]) -> str:
    text = f"{sample['hook_style']} {sample['hook_capability']}"
    families = [
        ("反差/异常", KEYWORD_SIGNALS["hook_contrast_gap"]),
        ("问题任务", KEYWORD_SIGNALS["hook_question_task"]),
        ("对象直入", KEYWORD_SIGNALS["hook_objective_first"]),
    ]
    return next((name for name, words in families if _contains_any(text, words)), "未识别")


def _climax_family(sample: dict[str, Any]) -> str:
    text = sample["climax_design"]
    families = [
        ("冲突汇合", KEYWORD_SIGNALS["climax_conflict_convergence"]),
        ("证据汇合", KEYWORD_SIGNALS["climax_evidence_convergence"]),
        ("机制揭示", KEYWORD_SIGNALS["climax_mechanism_reveal"]),
        ("视觉结果", KEYWORD_SIGNALS["climax_visual_result"]),
    ]
    return next((name for name, words in families if _contains_any(text, words)), "未识别")


def _ending_family(sample: dict[str, Any]) -> str:
    text = sample["ending_design"]
    families = [
        ("问题回扣", KEYWORD_SIGNALS["ending_question_callback"]),
        ("逻辑收束", KEYWORD_SIGNALS["ending_logic_closure"]),
        ("情绪余味", KEYWORD_SIGNALS["ending_emotional_aftertaste"]),
        ("期待桥接", KEYWORD_SIGNALS["ending_expectation_bridge"]),
    ]
    return next((name for name, words in families if _contains_any(text, words)), "未识别")


def _rule_rag_document(rule: dict[str, Any]) -> dict[str, Any]:
    evidence = rule["Evidence"]
    confidence = rule["Confidence"]
    action = rule["Action"]
    counter_patterns = [
        item["alternative_pattern"] for item in rule["Counter Examples"]
    ]
    text = (
        f"规则 {rule['rule_id']}：{rule['name']}。"
        f"状态：{rule['status']}，人工复核：{rule['human_reviewed']}。"
        f"声明：{rule['Claim']}。"
        f"触发：{rule['Trigger']['description']}。"
        f"目标：{rule['Goal']['communication_goal']}。"
        f"素材：{'、'.join(action['materials'])}。"
        f"动作：{' -> '.join(action['editing_sequence'])}。"
        f"约束：{'；'.join(rule['Constraints'][:4])}。"
        f"证据：{evidence['video_count']} 条视频、{evidence['creator_count']} 个创作者，"
        f"{evidence['evidence_label']}。"
        f"模式置信度：{confidence['pattern_confidence']['score']}；"
        f"效果置信度：{confidence['effect_confidence']['score']}；"
        f"综合置信度：{confidence['score']}（{confidence['level']}）。"
        f"替代机制：{'、'.join(counter_patterns) or '暂无可验证反例'}。"
    )
    return {
        "chunk_id": f"rule:{rule['rule_id']}",
        "category": "Rule",
        "rule_id": rule["rule_id"],
        "knowledge_type": rule["knowledge_type"],
        "status": rule["status"],
        "template_id": rule["template_id"],
        "template_collection": rule["collection"],
        "title": rule["name"],
        "capability": rule["Goal"]["capability"],
        "related_categories": rule["related_categories"],
        "creators": evidence["creators"],
        "source_video_ids": evidence["video_ids"],
        "confidence": confidence,
        "text": text,
        "metadata": {
            "do_not_copy": True,
            "source_type": "creator_rule",
            "evidence_type": evidence["evidence_type"],
            "causal_status": rule["Mechanism"]["causal_status"],
        },
    }


def _pattern_rag_document(pattern: dict[str, Any]) -> dict[str, Any]:
    text = (
        f"模式 {pattern['pattern_id']}：{pattern['name']}。"
        f"{pattern['claim']}。"
        f"创作者数：{pattern['frequency']['creator_count']}；"
        f"可定位观察：{pattern['frequency']['located_observation_count']}。"
        f"模式置信度：{pattern['confidence']['score']}。"
        "该模式只表示相关观察重复出现，不构成传播效果的因果证明。"
    )
    return {
        "chunk_id": f"pattern:{pattern['pattern_id']}",
        "category": "Pattern",
        "knowledge_type": "pattern",
        "pattern_id": pattern["pattern_id"],
        "rule_id": pattern["rule_id"],
        "title": pattern["name"],
        "capability": pattern["category"],
        "source_video_ids": pattern["video_ids"],
        "confidence": pattern["confidence"],
        "text": text,
        "metadata": {
            "do_not_copy": True,
            "source_type": "creator_pattern",
            "causal_status": pattern["causal_status"],
        },
    }


def _observation_rag_document(observation: dict[str, Any]) -> dict[str, Any]:
    text = (
        f"观察 {observation['observation_id']}。"
        f"视频 {observation['video_id']}，创作者 {observation['creator']}。"
        f"{observation['claim']}。"
        f"检测信号：{observation['detected_signal']}。"
        f"位置：{observation['location']['section']} "
        f"{observation['location']['time_range'] or '未知'}。"
        "不包含字幕原句，不允许作因果推断。"
    )
    return {
        "chunk_id": f"observation:{observation['observation_id']}",
        "category": "Observation",
        "knowledge_type": "observation",
        "observation_id": observation["observation_id"],
        "rule_id": observation["rule_id"],
        "title": observation["detected_signal"],
        "capability": observation["location"]["section"],
        "creators": [observation["creator"]] if observation["creator"] else [],
        "source_video_ids": [observation["video_id"]],
        "confidence": observation["confidence"],
        "text": text,
        "metadata": {
            "do_not_copy": True,
            "source_type": "creator_observation",
            "causal_status": "not_established",
        },
    }


def _build_library_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Creator Rule Library",
        "",
        f"生成时间：{payload['generated_at']}",
        "",
        f"- Rule：{payload['rule_count']} 条",
        f"- Pattern：{payload['pattern_count']} 条",
        f"- Observation：{payload['observation_count']} 条",
        "",
        "知识按 Observation → Pattern → Rule 分层保存。"
        "规则是条件性创作假设，不是因果定律；所有文件均不写入字幕原句。",
        "",
    ]
    for rule in payload["rules"]:
        lines.extend([_build_rule_markdown(rule).rstrip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def _build_rule_markdown(rule: dict[str, Any]) -> str:
    trigger = rule["Trigger"]
    goal = rule["Goal"]
    action = rule["Action"]
    evidence = rule["Evidence"]
    effect = rule["Effect Evidence"]
    confidence = rule["Confidence"]
    lines = [
        "---",
        f"schema_version: {rule['schema_version']}",
        f"knowledge_type: {rule['knowledge_type']}",
        f"rule_id: {rule['rule_id']}",
        f"status: {rule['status']}",
        f"version: {rule['version']}",
        f"human_reviewed: {str(rule['human_reviewed']).lower()}",
        f"category: {json.dumps(rule['category'], ensure_ascii=False)}",
        "---",
        "",
        f"# Rule ID: {rule['rule_id']}",
        "",
        f"**规则名称：{rule['name']}**",
        "",
        "## Claim（知识声明）",
        "",
        rule["Claim"],
        "",
        "## Trigger（触发条件）",
        "",
        trigger["description"],
        "",
        f"- 可观测信号：{'、'.join(trigger['required_signals']) or '暂无'}",
        "",
        "## Goal（传播目标）",
        "",
        goal["communication_goal"],
        "",
        f"- 对应能力：{goal['capability']}",
        "",
        "## Mechanism（机制假设）",
        "",
        f"- 假设：{rule['Mechanism']['hypothesis']}",
        f"- 因果状态：`{rule['Mechanism']['causal_status']}`",
        f"- 尚未证明：{rule['Mechanism']['what_is_not_proven']}",
        "",
        "## Knowledge Origin（知识来源类型）",
        "",
        f"- Observed：{rule['Knowledge Origin']['observed']}",
        f"- Inferred：{'、'.join(rule['Knowledge Origin']['inferred'])}",
        f"- Recommended：{'、'.join(rule['Knowledge Origin']['recommended'])}",
        "",
        "## Action（执行动作）",
        "",
        f"- Pattern 依据：`{action['observed_basis']}`",
        f"- 素材槽位来源：`{action['knowledge_origin']['materials']}`",
        f"- 组织顺序来源：`{action['knowledge_origin']['editing_sequence']}`",
        f"- 剪辑建议来源：`{action['knowledge_origin']['editing_guidance']}`",
        "",
        "### 应展示的素材",
        "",
    ]
    lines.extend(f"- {item}" for item in action["materials"])
    lines.extend(["", "### 剪辑顺序", ""])
    lines.extend(
        f"{index}. {item}"
        for index, item in enumerate(action["editing_sequence"], start=1)
    )
    lines.extend(["", "### 剪辑要求", ""])
    lines.extend(f"- {item}" for item in action["editing_guidance"])
    lines.extend(["", "### 质量检查", ""])
    lines.extend(f"- {item}" for item in action["quality_checks"])
    lines.extend(["", "## Constraints（约束）", ""])
    lines.extend(f"- {item}" for item in rule["Constraints"])
    lines.extend(
        [
            "",
            "## Evidence（证据）",
            "",
            f"- 证据类型：{evidence['evidence_label']}（`{evidence['evidence_type']}`）",
            f"- 匹配依据：{evidence['matching_basis']}",
            f"- 视频数：{evidence['video_count']}",
            f"- 创作者数：{evidence['creator_count']}",
            f"- 样本覆盖率：{evidence['sample_ratio']:.1%}",
            f"- 计数单位：{evidence['observation_unit']}",
            f"- 可定位 Observation：{evidence['located_observation_count']}",
            f"- 创作者：{'、'.join(evidence['creators']) or '暂无'}",
            (
                f"- 完整 Observation：见 `observations/observation_library.json` "
                f"中 `rule_id = {rule['rule_id']}` 的记录"
            ),
            "",
            "代表证据：",
            "",
        ]
    )
    if evidence["examples"]:
        lines.extend(
            (
                f"- `{item['video_id']}` | {item['author']} | "
                f"Observation `{item['observation_id'] or '无直接观察'}` | "
                f"信号：{item['matched_signal']} | "
                f"创作者相对播放指数：{item['relative_view_index']}"
            )
            for item in evidence["examples"]
        )
    else:
        lines.append("- 暂无可验证的逐视频证据。")
    lines.extend(
        [
            "",
            "## Effect Evidence（效果证据）",
            "",
            f"- 状态：`{effect['status']}`",
            f"- 相对播放指标样本：{effect['available_metrics']['relative_view_index']}",
            f"- 留存数据：{effect['available_metrics']['retention']}",
            f"- 完播数据：{effect['available_metrics']['completion_rate']}",
            f"- 相对播放指数中位数：{effect['summary']['median_relative_view_index']}",
            f"- 效果置信度：{effect['confidence_score']}",
            f"- 因果状态：`{effect['causal_status']}`",
            f"- 解释：{effect['interpretation']}",
            "",
            "## Confidence（置信度）",
            "",
            f"- 综合：{confidence['score']}（{confidence['level']}）",
            f"- 模式存在：{confidence['pattern_confidence']['score']}（{confidence['pattern_confidence']['level']}）",
            f"- 传播效果：{confidence['effect_confidence']['score']}（{confidence['effect_confidence']['level']}）",
            f"- 证据质量：{confidence['evidence_quality']['score']}（{confidence['evidence_quality']['level']}）",
            f"- 人工复核：{confidence['evidence_quality']['human_reviewed']}",
            f"- 依据：{confidence['rationale']}",
            "",
            "## Counter Evidence（反证与替代机制）",
            "",
        ]
    )
    if rule["Counter Examples"]:
        lines.extend(
            (
                f"- `{item['video_id']}` | {item['author']} | "
                f"相对播放指数 {item['relative_view_index']} | "
                f"替代机制：{item['alternative_pattern']}。"
                f"{item['reason']}"
            )
            for item in rule["Counter Examples"]
        )
    else:
        lines.append(
            "- 当前没有满足“相同定位、相同时长区间、相对表现不低于创作者均值”"
            "的可靠替代样本；"
            "这不代表规则没有反例。"
        )
    provenance = rule["Provenance"]
    lines.extend(
        [
            "",
            "## Provenance（来源追踪）",
            "",
            f"- 生成器：`{provenance['generator']}`",
            f"- 来源层：{' → '.join(provenance['source_layers'])}",
            f"- 是否写入原文：{provenance['raw_text_included']}",
            f"- 生成时间：{provenance['generated_at']}",
            "- 代表来源文件：",
        ]
    )
    lines.extend(
        f"  - `{path}`" for path in provenance["source_analysis_paths"][:12]
    )
    if len(provenance["source_analysis_paths"]) > 12:
        lines.append(
            f"  - 其余 {len(provenance['source_analysis_paths']) - 12} 个来源见 JSON。"
        )
    lines.extend(["", "## Revision History（修订记录）", ""])
    lines.extend(
        f"- v{item['version']} | {item['date']} | {item['change']}"
        for item in rule["Revision History"]
    )
    return "\n".join(lines).rstrip() + "\n"


def _build_pattern_library_markdown(
    patterns: list[dict[str, Any]],
    generated_at: str,
) -> str:
    lines = [
        "# Creator Pattern Library",
        "",
        f"生成时间：{generated_at}",
        "",
        "Pattern 只表示跨样本重复出现的观察，不代表传播效果因果关系。",
        "",
    ]
    for pattern in patterns:
        lines.extend([_build_pattern_markdown(pattern).rstrip(), ""])
    return "\n".join(lines).rstrip() + "\n"


def _build_pattern_markdown(pattern: dict[str, Any]) -> str:
    frequency = pattern["frequency"]
    performance = pattern["performance_summary"]
    lines = [
        "---",
        f"schema_version: {pattern['schema_version']}",
        f"knowledge_type: {pattern['knowledge_type']}",
        f"pattern_id: {pattern['pattern_id']}",
        f"rule_id: {pattern['rule_id']}",
        f"category: {json.dumps(pattern['category'], ensure_ascii=False)}",
        "---",
        "",
        f"# Pattern ID: {pattern['pattern_id']}",
        "",
        f"**模式名称：{pattern['name']}**",
        "",
        "## Claim（观察归纳）",
        "",
        pattern["claim"],
        "",
        "## Frequency（频率）",
        "",
        f"- Observation：{frequency['observation_count']}",
        f"- 创作者：{frequency['creator_count']}",
        f"- 可定位 Observation：{frequency['located_observation_count']}",
        "",
        "## Distribution（分布）",
        "",
        f"- 内容定位：{_format_mapping(pattern['distribution']['positionings'])}",
        f"- 时长区间：{_format_mapping(pattern['distribution']['duration_buckets'])}",
        "",
        "## Performance Context（表现背景）",
        "",
        f"- 相对播放指数中位数：{performance['median_relative_view_index']}",
        f"- 高于创作者样本均值：{performance['above_creator_average_count']}",
        f"- 因果状态：`{performance['causal_status']}`",
        "",
        "## Confidence（模式置信度）",
        "",
        f"- 分数：{pattern['confidence']['score']}",
        f"- 等级：{pattern['confidence']['level']}",
        "",
        "## Limitations（限制）",
        "",
    ]
    lines.extend(f"- {item}" for item in pattern["limitations"])
    return "\n".join(lines).rstrip() + "\n"


def _write_observation_markdown(
    observation_dir: Path,
    observations: list[dict[str, Any]],
    generated_at: str,
) -> None:
    by_video: dict[str, list[dict[str, Any]]] = {}
    for observation in observations:
        by_video.setdefault(observation["video_id"], []).append(observation)
    for video_id, items in by_video.items():
        lines = [
            "---",
            "schema_version: creator-knowledge-observation/v2",
            "knowledge_type: observation_collection",
            f"video_id: {json.dumps(video_id, ensure_ascii=False)}",
            "raw_text_included: false",
            "---",
            "",
            f"# Video Observations: {video_id}",
            "",
            f"生成时间：{generated_at}",
            "",
            "本文件只记录抽象功能信号，不包含字幕原句。",
            "",
        ]
        for observation in items:
            lines.extend(
                [
                    f"## {observation['observation_id']}",
                    "",
                    f"- Rule：`{observation['rule_id']}`",
                    f"- 创作者：{observation['creator']}",
                    f"- 定位：{observation['positioning']}",
                    f"- 声明：{observation['claim']}",
                    f"- 信号：{observation['detected_signal']}",
                    f"- 位置：{observation['location']['section']} / "
                    f"{observation['location']['time_range'] or '未知'}",
                    f"- 位置精度：`{observation['location']['precision']}`",
                    f"- 置信度：{observation['confidence']['score']}（"
                    f"{observation['confidence']['level']}）",
                    f"- 因果解释：不允许",
                    "",
                ]
            )
        (observation_dir / f"{_safe_filename(video_id)}.md").write_text(
            "\n".join(lines).rstrip() + "\n",
            encoding="utf-8",
        )


def _analysis_coverage(
    structure: list[dict[str, Any]],
    duration: Any,
) -> dict[str, Any]:
    first_range = _first_time_range(structure)
    last_range = _last_time_range(structure)
    start_seconds = _time_range_seconds(first_range)[0]
    end_seconds = _time_range_seconds(last_range)[1]
    duration_seconds = _as_float(duration) or 0.0
    coverage_ratio = (
        min(1.0, end_seconds / duration_seconds)
        if duration_seconds and end_seconds
        else 0.0
    )
    return {
        "time_range": (
            f"{_seconds_to_time(start_seconds)} - {_seconds_to_time(end_seconds)}"
            if end_seconds
            else ""
        ),
        "coverage_ratio": round(coverage_ratio, 4),
        "coverage_status": (
            "full_or_near_full"
            if coverage_ratio >= 0.8
            else "partial"
            if coverage_ratio > 0
            else "unknown"
        ),
    }


def _first_time_range(structure: list[dict[str, Any]]) -> str:
    for item in structure:
        value = _extract_time_range(str(item.get("time_range") or ""))
        if value:
            return value
    return ""


def _last_time_range(structure: list[dict[str, Any]]) -> str:
    for item in reversed(structure):
        value = _extract_time_range(str(item.get("time_range") or ""))
        if value:
            return value
    return ""


def _extract_time_range(value: str) -> str:
    match = re.search(
        r"(\d{1,2}:\d{2}(?::\d{2})?)\s*[-~至]\s*(\d{1,2}:\d{2}(?::\d{2})?)",
        value,
    )
    return f"{match.group(1)} - {match.group(2)}" if match else ""


def _time_range_seconds(value: str) -> tuple[float, float]:
    match = re.search(
        r"(\d{1,2}:\d{2}(?::\d{2})?)\s*-\s*(\d{1,2}:\d{2}(?::\d{2})?)",
        value,
    )
    if not match:
        return 0.0, 0.0
    return _time_to_seconds(match.group(1)), _time_to_seconds(match.group(2))


def _bounded_time_range(
    value: str,
    maximum_span_seconds: float,
) -> str:
    start, end = _time_range_seconds(value)
    if end <= start or end - start > maximum_span_seconds:
        return ""
    return value


def _time_to_seconds(value: str) -> float:
    try:
        parts = [int(part) for part in value.split(":")]
    except ValueError:
        return 0.0
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    if len(parts) == 3:
        return float(parts[0] * 3600 + parts[1] * 60 + parts[2])
    return 0.0


def _seconds_to_time(value: float) -> str:
    seconds = max(0, int(value))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02}:{minutes:02}:{seconds:02}"
    return f"{minutes:02}:{seconds:02}"


def _duration_bucket(value: Any) -> str:
    seconds = _as_float(value) or 0.0
    if seconds <= 0:
        return "未知时长"
    if seconds <= 180:
        return "短视频（≤3分钟）"
    if seconds <= 900:
        return "中视频（3-15分钟）"
    return "长视频（>15分钟）"


def _portable_path(path: Path, output_root: Path) -> str:
    try:
        relative = path.resolve().relative_to(output_root.resolve())
        return str(Path("output") / relative)
    except (OSError, ValueError):
        return str(path)


def _round_median(values: list[float], digits: int = 4) -> float | None:
    return round(float(median(values)), digits) if values else None


def _format_mapping(mapping: dict[str, Any]) -> str:
    return "、".join(
        f"{key}({value})" for key, value in mapping.items()
    ) or "暂无"


def _safe_filename(value: str) -> str:
    return re.sub(r'[<>:"/\\|?*]+', "_", value).strip(". ") or "unknown"


def _as_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
