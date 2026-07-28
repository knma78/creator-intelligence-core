from __future__ import annotations

from typing import Any


class PlatformRegistry:
    def __init__(self, platform_config: dict[str, Any]) -> None:
        self.platform_config = platform_config

    def enabled_platforms(self) -> dict[str, dict[str, Any]]:
        return {
            key: value
            for key, value in (self.platform_config.get("platforms") or {}).items()
            if value.get("enabled", False)
        }

    def rank_platforms(self, ability: str) -> list[dict[str, Any]]:
        ability = ability.lower()
        ranked: list[dict[str, Any]] = []
        for platform, config in self.enabled_platforms().items():
            base = float(config.get("weight", 1.0))
            best_for = {str(item).lower() for item in config.get("best_for") or []}
            ability_bonus = 0.25 if ability in best_for else 0.0
            ranked.append(
                {
                    "platform": platform,
                    "display_name": config.get("display_name", platform),
                    "score": round(min(1.0, base + ability_bonus), 3),
                    "supports_auto_fetch": bool(config.get("supports_auto_fetch", False)),
                    "auto_fetch_scope": config.get("auto_fetch_scope", "none"),
                    "supports_creator_batch": bool(config.get("supports_creator_batch", False)),
                    "search_modes": config.get("search_modes", []),
                    "reason": "ability_match" if ability in best_for else "general_platform_weight",
                }
            )
        return sorted(ranked, key=lambda item: (-item["score"], item["platform"]))
