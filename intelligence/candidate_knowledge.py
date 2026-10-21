from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import SETTINGS
from infrastructure.atomic_io import atomic_write_json


REQUIRED_FIELDS = {
    "name",
    "proposed_layer",
    "observation",
    "evidence",
    "source",
    "reasoning",
    "possible_function",
    "alternative_interpretation",
    "confidence",
}

FINAL_STATUSES = {"validated", "deprecated", "rejected"}


def propose_candidate_knowledge(
    proposal: dict[str, Any],
    *,
    path: Path | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """Store an Agent proposal without modifying validated knowledge."""
    missing = sorted(field for field in REQUIRED_FIELDS if not proposal.get(field))
    if missing:
        raise ValueError(f"Candidate Knowledge 缺少字段：{', '.join(missing)}")

    destination = path or (
        SETTINGS.output_dir
        / "creator_knowledge_base"
        / "rules"
        / "candidate_knowledge.json"
    )
    payload = _read_candidate_file(destination)
    created_at = timestamp or datetime.now().isoformat(timespec="seconds")
    fingerprint = hashlib.sha1(
        json.dumps(
            {
                "name": proposal["name"],
                "layer": proposal["proposed_layer"],
                "source": proposal["source"],
                "observation": proposal["observation"],
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:12]
    candidate_id = str(proposal.get("candidate_id") or f"CK-{fingerprint}")

    existing = next(
        (
            item
            for item in payload["candidates"]
            if str(item.get("candidate_id")) == candidate_id
        ),
        None,
    )
    if existing:
        return existing

    candidate = {
        "schema_version": "creator-candidate-knowledge/v1",
        "candidate_id": candidate_id,
        "name": proposal["name"],
        "proposed_layer": proposal["proposed_layer"],
        "observation": proposal["observation"],
        "evidence": proposal["evidence"],
        "source": proposal["source"],
        "timestamp": created_at,
        "reasoning": proposal["reasoning"],
        "possible_function": proposal["possible_function"],
        "alternative_interpretation": proposal["alternative_interpretation"],
        "confidence": proposal["confidence"],
        "status": "candidate",
        "agent_permission": "propose_only",
        "validation": {
            "reviewer": "",
            "reviewed_at": "",
            "notes": "",
        },
    }
    payload["candidates"].append(candidate)
    atomic_write_json(destination, payload)
    return candidate


def review_candidate_knowledge(
    candidate_id: str,
    *,
    status: str,
    reviewer: str,
    notes: str = "",
    path: Path | None = None,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    """Record a human validation decision; it does not create a formal Rule."""
    if status not in {"under_review", *FINAL_STATUSES}:
        raise ValueError(f"不支持的知识状态：{status}")
    if not reviewer.strip():
        raise ValueError("知识验证必须记录 reviewer")

    destination = path or (
        SETTINGS.output_dir
        / "creator_knowledge_base"
        / "rules"
        / "candidate_knowledge.json"
    )
    payload = _read_candidate_file(destination)
    candidate = next(
        (
            item
            for item in payload["candidates"]
            if str(item.get("candidate_id")) == candidate_id
        ),
        None,
    )
    if candidate is None:
        raise KeyError(f"未找到 Candidate Knowledge：{candidate_id}")
    candidate["status"] = status
    candidate["validation"] = {
        "reviewer": reviewer.strip(),
        "reviewed_at": reviewed_at or datetime.now().isoformat(timespec="seconds"),
        "notes": notes,
    }
    atomic_write_json(destination, payload)
    return candidate


def _read_candidate_file(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
    else:
        payload = {}
    candidates = payload.get("candidates")
    return {
        "schema_version": "creator-candidate-knowledge/v1",
        "version": 1,
        "policy": {
            "agent_permission": "propose_only",
            "validated_knowledge_write": "validation_pipeline_only",
        },
        "candidates": candidates if isinstance(candidates, list) else [],
    }
