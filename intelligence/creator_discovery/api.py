from __future__ import annotations

import argparse
import json
from typing import Any

from config import SETTINGS, Settings

from .services import CreatorDiscoveryService


def discover_creator(ability: str | None = None, settings: Settings = SETTINGS, save: bool = True) -> dict[str, Any]:
    return CreatorDiscoveryService(settings).discover_creator(ability=ability, save=save)


def recommend_creator(ability: str | None = None, settings: Settings = SETTINGS) -> dict[str, Any]:
    return CreatorDiscoveryService(settings).recommend_creator(ability=ability)


def recommend_keyword(ability: str, settings: Settings = SETTINGS) -> dict[str, Any]:
    return CreatorDiscoveryService(settings).recommend_keyword(ability)


def recommend_platform(ability: str, settings: Settings = SETTINGS) -> dict[str, Any]:
    return CreatorDiscoveryService(settings).recommend_platform(ability)


def creator_exists(creator_name: str, platform: str = "bilibili", settings: Settings = SETTINGS) -> bool:
    return CreatorDiscoveryService(settings).creator_exists(creator_name, platform)


def add_candidate(payload: dict[str, Any], settings: Settings = SETTINGS) -> dict[str, Any]:
    return CreatorDiscoveryService(settings).add_candidate(payload)


def approve_candidate(candidate_id: str, settings: Settings = SETTINGS) -> dict[str, Any]:
    return CreatorDiscoveryService(settings).approve_candidate(candidate_id)


def start_analysis(candidate_id: str, settings: Settings = SETTINGS) -> dict[str, Any]:
    return CreatorDiscoveryService(settings).start_analysis(candidate_id)


def finish_analysis(
    candidate_id: str,
    succeeded: bool,
    result: dict[str, Any] | None = None,
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    return CreatorDiscoveryService(settings).finish_analysis(candidate_id, succeeded, result)


def update_creator_score(creator_id: str, ability_result: dict[str, Any], settings: Settings = SETTINGS) -> dict[str, Any]:
    return CreatorDiscoveryService(settings).update_creator_score(creator_id, ability_result)


def get_dashboard(settings: Settings = SETTINGS) -> dict[str, Any]:
    return CreatorDiscoveryService(settings).get_dashboard()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local rule-first Creator Discovery Engine.")
    parser.add_argument("--ability", help="Optional ability key/name.")
    parser.add_argument("--recommend-keyword", action="store_true", help="Print keyword recommendations for --ability.")
    parser.add_argument("--recommend-platform", action="store_true", help="Print platform recommendations for --ability.")
    parser.add_argument("--recommend-creator", action="store_true", help="Print creator recommendations.")
    parser.add_argument("--dashboard", action="store_true", help="Print dashboard payload.")
    parser.add_argument("--approve-candidate", help="Approve a candidate id and move it to Waiting Analyze.")
    parser.add_argument("--no-save", action="store_true", help="Do not write output files for discovery runs.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.approve_candidate:
        payload = approve_candidate(args.approve_candidate)
    elif args.recommend_keyword:
        if not args.ability:
            raise SystemExit("--ability is required with --recommend-keyword")
        payload = recommend_keyword(args.ability)
    elif args.recommend_platform:
        if not args.ability:
            raise SystemExit("--ability is required with --recommend-platform")
        payload = recommend_platform(args.ability)
    elif args.recommend_creator:
        payload = recommend_creator(args.ability)
    elif args.dashboard:
        payload = get_dashboard()
    else:
        payload = discover_creator(args.ability, save=not args.no_save)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
