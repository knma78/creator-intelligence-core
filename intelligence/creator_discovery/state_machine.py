from __future__ import annotations

from typing import Any


class CandidateStateMachine:
    def __init__(self, discovery_rules: dict[str, Any]) -> None:
        self.transitions = discovery_rules.get("status_machine") or {}

    def can_transition(self, current: str, target: str) -> bool:
        return target in self.transitions.get(current, [])

    def transition(self, candidate: dict[str, Any], target: str, now: str) -> dict[str, Any]:
        current = str(candidate.get("status") or "discovered")
        if current != target and not self.can_transition(current, target):
            raise ValueError(f"Invalid candidate status transition: {current} -> {target}")
        updated = dict(candidate)
        updated["status"] = target
        updated["last_update"] = now
        if target in {"approved", "waiting_analyze", "analyzing"}:
            updated["need_analyze"] = True
        if target in {"analyzed", "synced_to_knowledge_base", "rejected", "archived"}:
            updated["need_analyze"] = False
        return updated
