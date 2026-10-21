"""Bind human decisions to semantic rule content, not an accidentally reused ID."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from infrastructure.atomic_io import atomic_write_json


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def content_fingerprint(rule: dict) -> str:
    fields = (
        "template_id", "name", "layer", "definition", "condition",
        "intended_function", "selection_mode", "Claim", "Trigger", "Selection",
        "Goal", "Mechanism", "Action", "Constraints",
    )
    content = {key: deepcopy(rule.get(key)) for key in fields}
    # Whether a pattern is currently observable is evidence, not the instruction.
    if isinstance(content.get("Action"), dict):
        content["Action"].pop("observed_basis", None)
    return digest(content)


def evidence_binding(rule: dict) -> dict:
    evidence = rule.get("Evidence") or rule.get("evidence") or {}
    contents = {f"observation:{key}": value for key, value in
                (evidence.get("observation_content_hashes") or {}).items()}
    for index, example in enumerate(evidence.get("examples") or []):
        identity = example.get("observation_id") or example.get("video_id") or str(index)
        key = f"example:{identity}"
        value = {k: v for k, v in example.items() if k not in {"view_count", "relative_view_index"}}
        # Preserve duplicate observations instead of silently overwriting one.
        contents.setdefault(key, []).append(digest(value))
    contents = {key: sorted(value) if isinstance(value, list) else value for key, value in contents.items()}
    return {
        "binding_version": 2,
        "content_hashes": contents,
        "context_hash": digest({key: evidence.get(key) for key in
                                ("matching_basis", "observation_unit", "evidence_label")}),
        "video_ids": sorted(set(evidence.get("video_ids") or [])),
        "observation_ids": sorted(set(evidence.get("observation_ids") or [])),
        "evidence_type": evidence.get("evidence_type"),
        "counterexamples_hash": digest(rule.get("Counter Examples") or []),
    }


def observation_fingerprint(observation: dict) -> str:
    return digest({key: value for key, value in observation.items()
                   if key not in {"performance_context", "generated_at"}})


def refresh_observation_hashes(library: dict) -> None:
    """Read the actual observation records, not only cached fingerprints."""
    if "observation_library" not in library:
        return
    observations = {item["observation_id"]: item for item in library["observation_library"]}
    for rule in library.get("rules", []):
        evidence = rule.get("Evidence") or rule.get("evidence") or {}
        evidence["observation_content_hashes"] = {
            key: observation_fingerprint(observations[key]) if key in observations else "missing"
            for key in evidence.get("observation_ids") or []
        }


def resolve_review(rule: dict, review: dict) -> tuple[dict, str]:
    """A stale/legacy decision is retained for audit but cannot validate content."""
    if not review or not any(review.get(key) for key in ("reviewed_at", "reviewer", "approved", "status")):
        if rule.get("status") == "validated" or rule.get("human_reviewed"):
            return {"approved": False, "status": "under_review"}, "缺少可核验的版本复核记录，需要重新确认。"
        return {}, ""
    reason = ""
    if not review.get("content_fingerprint"):
        reason = "旧复核未绑定内容版本，需要重新确认。"
    elif review["content_fingerprint"] != content_fingerprint(rule):
        reason = "规则内容已改变，需要重新复核。"
    else:
        before = review.get("evidence_binding") or {}
        after = evidence_binding(rule)
        if not before:
            reason = "复核缺少证据快照，需要重新确认。"
        elif before.get("binding_version") != 2:
            reason = "旧复核未绑定证据内容指纹，需要重新确认。"
        elif (
            not set(before.get("video_ids") or []).issubset(after["video_ids"])
            or not set(before.get("observation_ids") or []).issubset(after["observation_ids"])
            or before.get("evidence_type") != after["evidence_type"]
        ):
            reason = "已复核的证据被移除或证据类型改变，需要重新复核。"
        elif before.get("counterexamples_hash") != after["counterexamples_hash"]:
            reason = "反例记录已改变，需要重新复核。"
        elif (before.get("context_hash") != after["context_hash"] or any(
            after["content_hashes"].get(key) != value
            for key, value in before.get("content_hashes", {}).items()
        )):
            reason = "已复核的证据内容或解释已改变，需要重新复核。"
    effective = dict(review)
    if reason:
        effective.update(approved=False, status="under_review")
    return effective, reason


def review_token(rule: dict) -> str:
    return digest({"content": content_fingerprint(rule), "evidence": evidence_binding(rule)})


def version_rule(rule: dict, previous: dict, review: dict) -> dict:
    fingerprint = content_fingerprint(rule)
    old_revision = int(previous.get("content_revision") or 1)
    rule["content_revision"] = (
        old_revision + int(content_fingerprint(previous) != fingerprint)
        if previous else 1
    )
    rule["content_fingerprint"] = fingerprint
    effective, reason = resolve_review(rule, review)
    rule["review_required_reason"] = reason
    rule["status"] = effective.get("status") or "candidate"
    rule["human_reviewed"] = bool(effective.get("approved")) and not reason
    rule["review"] = deepcopy(review)
    return rule


def archive_versions(directory: Path, rules: list[dict], previous: list[dict]) -> None:
    for rule in [*previous, *rules]:
        fingerprint = content_fingerprint(rule)
        # Hash-derived paths cannot be influenced by a rule's display ID.
        path = directory / "versions" / f"{fingerprint}.json"
        if not path.exists():
            atomic_write_json(path, rule)
