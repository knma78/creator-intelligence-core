from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import Settings
from infrastructure.atomic_io import atomic_write_json
from infrastructure.file_lock import file_lock, maintenance_lock
from infrastructure.rule_versions import content_fingerprint, evidence_binding, refresh_observation_hashes, resolve_review, review_token


def _rule_library_path(settings: Settings) -> Path:
    return settings.output_dir / "creator_knowledge_base" / "rules" / "rule_library.json"


def _rule_reviews_path(settings: Settings) -> Path:
    return settings.output_dir / "creator_knowledge_base" / "rules" / "rule_reviews.json"


def knowledge_rules(settings: Settings) -> dict[str, Any]:
    library_path = _rule_library_path(settings)
    if not library_path.exists():
        return {"ready": False, "rules": [], "message": "规则库尚未生成。"}
    library = json.loads(library_path.read_text(encoding="utf-8"))
    refresh_observation_hashes(library)
    review_path = _rule_reviews_path(settings)
    reviews_payload = (
        json.loads(review_path.read_text(encoding="utf-8"))
        if review_path.exists()
        else {}
    )
    reviews = reviews_payload.get("reviews") or {}
    rules = []
    for rule in library.get("rules", []):
        rule_id = str(rule.get("rule_id") or "")
        template_id = str(rule.get("template_id") or "")
        review = reviews.get(rule_id) or reviews.get(template_id) or rule.get("review") or {}
        effective, review_reason = resolve_review(rule, review)
        applied_review = rule.get("review") or {}
        # The existing rule-library schema serializes this field as `Evidence`;
        # accept lowercase too for any newer/normalized artifacts.
        evidence = rule.get("Evidence") or rule.get("evidence") or {}
        rules.append(
            {
                "rule_id": rule_id,
                "template_id": template_id,
                "name": rule.get("name") or template_id,
                "layer": rule.get("layer_label") or rule.get("layer") or "",
                "definition": rule.get("definition") or "",
                "condition": rule.get("condition") or [],
                "intended_function": rule.get("intended_function") or [],
                "status": effective.get("status") or rule.get("status") or "candidate",
                "content_revision": rule.get("content_revision") or 1,
                "content_fingerprint": content_fingerprint(rule),
                "review_token": review_token(rule),
                "review_required_reason": review_reason,
                "review_pending": bool(
                    review.get("reviewed_at")
                    and review.get("reviewed_at") != applied_review.get("reviewed_at")
                ),
                "human_reviewed": bool(effective.get("reviewed_at")) and not review_reason,
                "review": {
                    "reviewer": review.get("reviewer") or "",
                    "reviewed_at": review.get("reviewed_at") or "",
                    "notes": review.get("notes") or "",
                },
                "evidence": {
                    "evidence_label": evidence.get("evidence_label") or "",
                    "video_count": evidence.get("video_count", 0),
                    "creator_count": evidence.get("creator_count", 0),
                    "located_observation_count": evidence.get("located_observation_count", 0),
                    "matching_basis": evidence.get("matching_basis") or "",
                    "examples": evidence.get("examples") or [],
                },
                "confidence": rule.get("confidence") or {},
            }
        )
    return {
        "ready": True,
        "generated_at": library.get("generated_at"),
        "source": library.get("source") or {},
        "rules": rules,
    }


def record_rule_review(payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    with maintenance_lock(settings, exclusive=False), file_lock(_rule_reviews_path(settings).with_suffix(".lock")):
        return _record_locked(payload, settings)


def _record_locked(payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    rule_id = str(payload.get("rule_id") or "").strip()
    status = str(payload.get("status") or "").strip()
    reviewer = str(payload.get("reviewer") or "").strip()
    notes = str(payload.get("notes") or "").strip()
    if not rule_id:
        raise ValueError("缺少规则编号。")
    if status not in {"validated", "under_review", "rejected", "deprecated"}:
        raise ValueError("复核状态无效。")
    if not reviewer:
        raise ValueError("请填写复核人。")
    if len(reviewer) > 100 or len(notes) > 2000:
        raise ValueError("复核人或备注过长。")
    library_path = _rule_library_path(settings)
    if not library_path.exists():
        raise ValueError("规则库尚未生成，请先完整更新知识系统。")
    library = json.loads(library_path.read_text(encoding="utf-8"))
    refresh_observation_hashes(library)
    rule = next(
        (item for item in library.get("rules", []) if str(item.get("rule_id") or "") == rule_id),
        None,
    )
    if rule is None:
        raise ValueError("规则编号不存在或已被重建，请刷新规则列表。")
    if payload.get("review_token") != review_token(rule):
        raise ValueError("规则内容或证据版本已变化，请刷新并重新检查后复核。")
    review_path = _rule_reviews_path(settings)
    review_payload = (
        json.loads(review_path.read_text(encoding="utf-8"))
        if review_path.exists()
        else {"version": 1, "reviews": {}}
    )
    reviews = review_payload.setdefault("reviews", {})
    history = review_payload.setdefault("history", [])
    previous = reviews.get(rule_id) or reviews.get(str(rule.get("template_id") or ""))
    if previous and not any(item.get("decision") == previous for item in history):
        history.append({"rule_id": rule_id, "decision": previous, "legacy_import": True})
    reviews[rule_id] = {
        "approved": status == "validated",
        "status": status,
        "reviewer": reviewer,
        "reviewed_at": datetime.now().astimezone().isoformat(timespec="microseconds"),
        "notes": notes,
        "content_revision": rule.get("content_revision") or 1,
        "content_fingerprint": content_fingerprint(rule),
        "evidence_binding": evidence_binding(rule),
    }
    history.append({"rule_id": rule_id, "decision": reviews[rule_id], "rule_snapshot": rule})
    review_payload["version"] = 2
    atomic_write_json(review_path, review_payload, indent=2)
    return {
        "ok": True,
        "rule_id": rule_id,
        "status": status,
        "message": "复核决定已保存；点击“完整更新”后会应用到规则库。",
    }
