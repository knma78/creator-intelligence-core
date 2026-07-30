from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from infrastructure.atomic_io import atomic_write_json
from intelligence.gap_analysis.api import run_gap_analysis
from intelligence.gap_analysis.repository import normalize_ability_key

from .models import DiscoveryDataset


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        text = "".join(ch for ch in text if ch in "\r\n\t" or ord(ch) >= 32)
        return json.loads(text)


def write_json(path: Path, payload: Any) -> None:
    atomic_write_json(path, payload)


def stable_id(*parts: str) -> str:
    raw = "|".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class CreatorDiscoveryRepository:
    def __init__(self, settings: Settings = SETTINGS) -> None:
        self.settings = settings
        self.config_dir = settings.base_dir / "config"
        self.output_dir = settings.output_dir / "creator_discovery"
        self.history_dir = self.output_dir / "history"
        self.creator_kb_dir = settings.output_dir / "creator_knowledge_base"

    @property
    def candidates_path(self) -> Path:
        return self.output_dir / "candidates.json"

    @property
    def matrix_path(self) -> Path:
        return self.output_dir / "creator_ability_matrix.json"

    @property
    def approved_creators_path(self) -> Path:
        return self.output_dir / "approved_creators.json"

    @property
    def latest_path(self) -> Path:
        return self.output_dir / "latest.json"

    @property
    def dashboard_path(self) -> Path:
        return self.output_dir / "dashboard.json"

    def load_dataset(self) -> DiscoveryDataset:
        gap_path = self.settings.output_dir / "gap_analysis" / "latest.json"
        gap_analysis = read_json(gap_path, {})
        if not gap_analysis:
            gap_analysis = run_gap_analysis(self.settings, save=True)

        manifest_path = self.creator_kb_dir / "manifest.json"
        integrated_path = self.settings.output_dir / "integrated" / "integrated_summary.json"
        keyword_path = self.config_dir / "AbilityKeyword.json"
        platform_path = self.config_dir / "PlatformWeight.json"
        rule_path = self.config_dir / "DiscoveryRule.json"
        threshold_path = self.config_dir / "CreatorThreshold.json"

        creator_manifest = read_json(manifest_path, {})
        integrated_summary = read_json(integrated_path, {})
        ability_keywords = read_json(keyword_path, {})
        platform_weights = read_json(platform_path, {})
        discovery_rules = read_json(rule_path, {})
        creator_thresholds = read_json(threshold_path, {})
        candidates = read_json(self.candidates_path, [])
        approved_creators = read_json(self.approved_creators_path, [])
        matrix = read_json(self.matrix_path, [])
        if not matrix:
            matrix = self.derive_creator_matrix(gap_analysis, creator_manifest, integrated_summary)
            self.save_matrix(matrix)

        return DiscoveryDataset(
            gap_analysis=gap_analysis,
            creator_manifest=creator_manifest,
            integrated_summary=integrated_summary,
            ability_keywords=ability_keywords,
            platform_weights=platform_weights,
            discovery_rules=discovery_rules,
            creator_thresholds=creator_thresholds,
            candidates=candidates,
            creator_matrix=matrix,
            approved_creators=approved_creators,
            source_paths={
                "gap_analysis": str(gap_path),
                "creator_manifest": str(manifest_path),
                "video_database": str(integrated_path),
                "ability_keyword": str(keyword_path),
                "platform_weight": str(platform_path),
                "discovery_rule": str(rule_path),
                "creator_threshold": str(threshold_path),
                "candidate_pool": str(self.candidates_path),
                "creator_ability_matrix": str(self.matrix_path),
            },
        )

    def derive_creator_matrix(
        self,
        gap_analysis: dict[str, Any],
        creator_manifest: dict[str, Any],
        integrated_summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        videos = integrated_summary.get("videos") or []
        videos_by_author: dict[str, set[str]] = {}
        for video in videos:
            author = str(video.get("author") or "")
            video_id = str(video.get("video_id") or "")
            if author and video_id:
                videos_by_author.setdefault(author, set()).add(video_id)

        creator_meta = {
            str(item.get("author") or ""): item
            for item in creator_manifest.get("creators") or []
            if item.get("author")
        }
        rows: list[dict[str, Any]] = []
        for ability in gap_analysis.get("ability_ranking") or []:
            ability_key = normalize_ability_key(str(ability.get("ability_key") or ability.get("ability_name") or ""))
            related_videos = set(str(video_id) for video_id in ability.get("related_videos") or [])
            related_creators = set(str(name) for name in ability.get("related_creators") or [])
            author_counts: dict[str, int] = {}
            for video in videos:
                video_id = str(video.get("video_id") or "")
                author = str(video.get("author") or "")
                if video_id in related_videos and author:
                    author_counts[author] = author_counts.get(author, 0) + 1
            for creator in related_creators:
                author_counts.setdefault(creator, 0)
            for creator_name, video_count in author_counts.items():
                meta = creator_meta.get(creator_name, {})
                total_videos = int(meta.get("video_count") or len(videos_by_author.get(creator_name, set())) or video_count)
                ref_ratio = min(video_count / max(1, int((ability.get("target") or {}).get("target_reference_count") or 20)), 1.0)
                link_bonus = 0.25 if creator_name in related_creators else 0.0
                sample_bonus = min(total_videos / 10, 1.0) * 0.15
                score = round(min(100.0, (ref_ratio * 0.6 + link_bonus + sample_bonus) * 100), 2)
                rows.append(
                    {
                        "creator_id": stable_id("bilibili", creator_name),
                        "creator_name": creator_name,
                        "platform": "bilibili",
                        "ability": ability_key,
                        "score": score,
                        "confidence": round(0.55 + min(video_count / 10, 0.35) + link_bonus * 0.2, 3),
                        "video_count": total_videos,
                        "last_analyze": ability.get("last_update", ""),
                        "category": str(meta.get("positioning") or ""),
                    }
                )
        return rows

    def save_candidates(self, candidates: list[dict[str, Any]]) -> None:
        write_json(self.candidates_path, candidates)

    def save_matrix(self, matrix: list[dict[str, Any]]) -> None:
        write_json(self.matrix_path, matrix)

    def save_approved_creators(self, creators: list[dict[str, Any]]) -> None:
        write_json(self.approved_creators_path, creators)

    def save_latest(self, payload: dict[str, Any]) -> None:
        write_json(self.latest_path, payload)
        write_json(self.dashboard_path, payload.get("dashboard", {}))
        generated_at = str(payload.get("generated_at") or now_iso()).replace(":", "").replace("-", "").replace("T", "_")
        write_json(self.history_dir / f"{generated_at}.json", payload)
