from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from config import SETTINGS
from infrastructure.rule_versions import content_fingerprint, refresh_observation_hashes, resolve_review


LAYER_ORDER = [
    "opening",
    "narrative_structure",
    "transition",
    "climax",
    "ending",
    "workflow",
]

ALLOWED_STATUSES = {"candidate", "under_review", "validated"}


def build_capability_plan(
    context: str,
    *,
    rule_library_path: Path | None = None,
    condition_states: dict[str, bool | None] | None = None,
    max_secondary_per_layer: int = 1,
) -> dict[str, Any]:
    """Match conditional rules into a candidate pool, then select by layer."""
    path = rule_library_path or (
        SETTINGS.output_dir
        / "creator_knowledge_base"
        / "rules"
        / "rule_library.json"
    )
    library = json.loads(path.read_text(encoding="utf-8"))
    refresh_observation_hashes(library)
    states = condition_states or {}
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []

    for rule in library.get("rules", []):
        rule_id = str(rule.get("rule_id") or "")
        status = str(rule.get("status") or "candidate")
        effective, review_reason = resolve_review(rule, rule.get("review") or {})
        if review_reason:
            status = effective["status"]
        if status not in ALLOWED_STATUSES:
            excluded.append({"rule_id": rule_id, "reason": f"status={status}"})
            continue

        explicit_state = states.get(rule_id, "not_provided")
        if explicit_state is False:
            excluded.append({"rule_id": rule_id, "reason": "condition_false"})
            continue
        matched_signals = _matched_signals(context, rule)
        if explicit_state is not True and not matched_signals:
            continue

        condition_state = "true" if explicit_state is True else "unknown" if explicit_state is None else "inferred_true"
        base_confidence = _confidence_score(rule)
        signal_score = min(1.0, len(matched_signals) / 3)
        selection_score = round(
            min(1.0, 0.65 * base_confidence + 0.35 * signal_score),
            4,
        )
        candidates.append(
            {
                "rule_id": rule_id,
                "template_id": rule.get("template_id") or "",
                "content_fingerprint": content_fingerprint(rule),
                "content_revision": rule.get("content_revision") or 1,
                "condition": rule.get("condition") or [],
                "evidence_ids": (rule.get("Evidence") or rule.get("evidence") or {}).get("observation_ids") or [],
                "name": rule.get("name", ""),
                "layer": rule.get("layer") or _legacy_layer(rule),
                "status": status,
                "review_required_reason": review_reason,
                "selection_mode": "candidate",
                "condition_state": condition_state,
                "matched_signals": matched_signals,
                "intended_function": rule.get("intended_function")
                or [(rule.get("Goal") or {}).get("communication_goal", "")],
                "selection_score": selection_score,
                "confidence": rule.get("confidence") or {},
            }
        )

    by_layer: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_layer.setdefault(str(candidate["layer"]), []).append(candidate)
    for items in by_layer.values():
        items.sort(
            key=lambda item: (
                -float(item["selection_score"]),
                str(item["rule_id"]),
            )
        )

    selections = []
    for layer in LAYER_ORDER + sorted(set(by_layer) - set(LAYER_ORDER)):
        items = by_layer.get(layer, [])
        if not items:
            continue
        selections.append(
            {
                "layer": layer,
                "primary": items[0],
                "secondary": items[1 : 1 + max(0, max_secondary_per_layer)],
                "alternatives": items[1 + max(0, max_secondary_per_layer) :],
                "selection_policy": "same_layer_competition",
            }
        )

    return {
        "schema_version": "creator-capability-plan/v1",
        "context": context,
        "rule_semantics": "conditional_capability_proposal",
        "candidate_count": len(candidates),
        "candidate_pool": by_layer,
        "selections": selections,
        "composition": [
            item["primary"]["rule_id"] for item in selections if item.get("primary")
        ],
        "excluded": excluded,
        "planner_policy": {
            "rule_matching": "propose_candidates_only",
            "same_layer": "select_primary_and_optional_secondary",
            "cross_layer": "compose_selected_abilities",
            "must_use": False,
        },
    }


def _matched_signals(context: str, rule: dict[str, Any]) -> list[str]:
    normalized = _normalize(context)
    signals = [
        str(item).strip()
        for item in (rule.get("Trigger") or {}).get("required_signals", [])
        if str(item).strip()
    ]
    name = str(rule.get("name") or "").strip()
    related = [
        str(item).strip()
        for item in rule.get("related_categories", [])
        if str(item).strip()
    ]
    matches = [item for item in [*signals, name, *related] if _normalize(item) in normalized]
    return list(dict.fromkeys(matches))


def _confidence_score(rule: dict[str, Any]) -> float:
    confidence = rule.get("confidence") or {}
    value = confidence.get("functional_interpretation")
    if isinstance(value, dict):
        value = value.get("score")
    if value is None:
        value = ((rule.get("Confidence") or {}).get("functional_interpretation") or {}).get("score")
    if value is None:
        value = ((rule.get("Confidence") or {}).get("pattern_confidence") or {}).get("score")
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _legacy_layer(rule: dict[str, Any]) -> str:
    return {
        "hook_templates": "opening",
        "script_structure_templates": "narrative_structure",
        "transition_templates": "transition",
        "climax_templates": "climax",
        "ending_templates": "ending",
        "workflow_templates": "workflow",
    }.get(str(rule.get("collection") or ""), "unknown")


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()
