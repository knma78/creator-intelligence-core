from __future__ import annotations

import argparse
import json
from typing import Any

from config import SETTINGS, Settings

from .services import GapAnalysisService


def run_gap_analysis(settings: Settings = SETTINGS, save: bool = True) -> dict[str, Any]:
    return GapAnalysisService(settings).run(save=save)


def get_gap(ability_key: str | None = None, settings: Settings = SETTINGS) -> dict[str, Any]:
    return GapAnalysisService(settings).get_gap(ability_key)


def recommend_creator(ability_key: str | None = None, settings: Settings = SETTINGS) -> dict[str, Any]:
    return GapAnalysisService(settings).recommend_creator(ability_key)


def recommend_video(ability_key: str | None = None, settings: Settings = SETTINGS) -> dict[str, Any]:
    return GapAnalysisService(settings).recommend_video(ability_key)


def predict_growth(plan: list[dict[str, Any]] | None = None, settings: Settings = SETTINGS) -> dict[str, Any]:
    return GapAnalysisService(settings).predict_growth(plan)


def get_health(settings: Settings = SETTINGS) -> dict[str, Any]:
    return GapAnalysisService(settings).get_health()


def get_dashboard(settings: Settings = SETTINGS) -> dict[str, Any]:
    return GapAnalysisService(settings).get_dashboard()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local rule-first Knowledge Gap Analysis.")
    parser.add_argument("--ability", help="Optional ability key/name for focused gap or recommendation.")
    parser.add_argument("--health", action="store_true", help="Print only Knowledge Health.")
    parser.add_argument("--recommend-creator", action="store_true", help="Print creator recommendation.")
    parser.add_argument("--recommend-video", action="store_true", help="Print video-count recommendation.")
    parser.add_argument("--dashboard", action="store_true", help="Print dashboard payload.")
    parser.add_argument("--no-save", action="store_true", help="Do not write output/gap_analysis files.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.health:
        payload = get_health()
    elif args.recommend_creator:
        payload = recommend_creator(args.ability)
    elif args.recommend_video:
        payload = recommend_video(args.ability)
    elif args.dashboard:
        payload = get_dashboard()
    elif args.ability:
        payload = get_gap(args.ability)
    else:
        payload = run_gap_analysis(save=not args.no_save)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
