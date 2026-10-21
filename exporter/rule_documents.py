from __future__ import annotations

import json
from pathlib import Path
from typing import Any

def _rule_rag_document(rule: dict[str, Any]) -> dict[str, Any]:
    evidence = rule["Evidence"]
    confidence = rule["Confidence"]
    action = rule["Action"]
    counter_patterns = [
        item["alternative_pattern"] for item in rule["Counter Examples"]
    ]
    text = (
        f"规则 {rule['rule_id']}：{rule['name']}。"
        f"能力层级：{rule['layer_label']}，选择模式：{rule['selection_mode']}。"
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
        f"功能解释置信度：{confidence['functional_interpretation']['score']}；"
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
        "layer": rule["layer"],
        "selection_mode": rule["selection_mode"],
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
            "agent_permission": "propose_only",
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
        "规则是条件性能力候选建议，不是命令或因果定律；"
        "所有文件均不写入字幕原句。",
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
        f"layer: {rule['layer']}",
        f"selection_mode: {rule['selection_mode']}",
        f"category: {json.dumps(rule['category'], ensure_ascii=False)}",
        "---",
        "",
        f"# Rule ID: {rule['rule_id']}",
        "",
        f"**规则名称：{rule['name']}**",
        "",
        "## Capability Node（能力节点）",
        "",
        f"- Layer：`{rule['layer']}`（{rule['layer_label']}）",
        f"- Definition：{rule['definition']}",
        f"- Selection Mode：`{rule['selection_mode']}`",
        f"- Intended Function：{'、'.join(rule['intended_function'])}",
        f"- Status：`{rule['status']}`",
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
        f"- 条件成立：`{rule['Selection']['condition_true']}`",
        f"- 条件不成立：`{rule['Selection']['condition_false']}`",
        f"- 条件未知：`{rule['Selection']['condition_unknown']}`",
        f"- 同层级选择：`{rule['Selection']['same_layer_policy']}`",
        f"- 跨层级组合：`{rule['Selection']['cross_layer_policy']}`",
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
            f"- 功能解释：{confidence['functional_interpretation']['score']}（{confidence['functional_interpretation']['level']}）",
            f"- 传播效果：{confidence['effect_confidence']['score']}（{confidence['effect_confidence']['level']}）",
            f"- 因果效果：`{rule['confidence']['causal_effect']}`",
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



def _format_mapping(mapping: dict[str, Any]) -> str:
    return "、".join(
        f"{key}({value})" for key, value in mapping.items()
    ) or "暂无"


def _safe_filename(value: str) -> str:
    import re

    return re.sub(r'[<>:"/\\|?*]+', "_", value).strip(". ") or "unknown"
