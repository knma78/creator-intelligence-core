from __future__ import annotations

from collections import Counter
from typing import Any

from config import SETTINGS, Settings
from downloader.bilibili import is_bilibili_url
from downloader.bilibili_up import is_bilibili_up_source
from downloader.social import (
    is_douyin_profile_url,
    is_douyin_video_url,
    is_xiaohongshu_video_url,
)
from downloader.youtube import is_youtube_channel_url, is_youtube_url
from intelligence.gap_analysis.repository import normalize_ability_key

from .platform_registry import PlatformRegistry
from .repository import CreatorDiscoveryRepository, now_iso, stable_id
from .state_machine import CandidateStateMachine


class CreatorDiscoveryService:
    def __init__(self, settings: Settings = SETTINGS, repository: CreatorDiscoveryRepository | None = None) -> None:
        self.settings = settings
        self.repository = repository or CreatorDiscoveryRepository(settings)

    def discover_creator(self, ability: str | None = None, save: bool = True) -> dict[str, Any]:
        dataset = self.repository.load_dataset()
        generated_at = now_iso()
        gaps = self._target_gaps(dataset.gap_analysis, ability)
        platform_registry = PlatformRegistry(dataset.platform_weights)
        existing_candidates = list(dataset.candidates)
        all_candidates = list(existing_candidates)
        ability_results: list[dict[str, Any]] = []
        search_plans: list[dict[str, Any]] = []

        for gap in gaps:
            ability_key = normalize_ability_key(str(gap.get("ability_key") or gap.get("ability_name") or ""))
            threshold = self._threshold_for(ability_key, dataset.creator_thresholds)
            excellent_creators = self._excellent_creators(dataset.creator_matrix, ability_key, threshold)
            platforms = platform_registry.rank_platforms(ability_key)
            keywords = self.recommend_keyword(ability_key, dataset=dataset)["keywords"]
            search_plan = self._build_search_plan(ability_key, platforms, keywords, dataset)
            search_plans.append(search_plan)
            needs_discovery = len(excellent_creators) < int(threshold["target_creator_count"])

            new_candidates: list[dict[str, Any]] = []
            if needs_discovery:
                new_candidates = self._build_candidates(
                    ability_key=ability_key,
                    gap=gap,
                    dataset=dataset,
                    platforms=platforms,
                    keywords=keywords,
                    generated_at=generated_at,
                )
                all_candidates = self._merge_candidates(all_candidates, new_candidates, dataset.discovery_rules)

            ability_results.append(
                {
                    "ability_key": ability_key,
                    "ability_name": gap.get("ability_name") or ability_key,
                    "score": gap.get("score", 0),
                    "target_score": (gap.get("target") or {}).get("target_score", 0),
                    "gap": (gap.get("gap") or {}).get("score_gap", 0),
                    "current_excellent_creator_count": len(excellent_creators),
                    "target_creator_count": threshold["target_creator_count"],
                    "mode": "discovery" if needs_discovery else "recommend_existing",
                    "existing_recommendations": excellent_creators,
                    "new_candidate_count": len(new_candidates),
                    "keyword_count": len(keywords),
                    "platform_count": len(platforms),
                }
            )

        if save:
            self.repository.save_candidates(all_candidates)

        ai_status = self._ai_status(dataset.discovery_rules, all_candidates, ability_results)
        dashboard = self._build_dashboard(dataset, ability_results, all_candidates, search_plans)
        payload = {
            "schema_version": "Creator Discovery V1",
            "generated_at": generated_at,
            "rule_first": True,
            "database_first": True,
            "ai_used": False,
            "ai_discovery": ai_status,
            "data_sources": dataset.source_paths,
            "ability_gap": ability_results,
            "platform_recommendation": self._flatten_platforms(search_plans),
            "keyword_recommendation": self._flatten_keywords(search_plans),
            "creator_candidates": all_candidates,
            "search_plan": search_plans,
            "dashboard": dashboard,
            "next_actions": self._next_actions(ability_results, all_candidates),
        }
        if save:
            self.repository.save_latest(payload)
        return payload

    def recommend_creator(self, ability: str | None = None) -> dict[str, Any]:
        payload = self.discover_creator(ability=ability, save=True)
        key = normalize_ability_key(ability or "")
        candidates = payload["creator_candidates"]
        if key:
            candidates = [item for item in candidates if item.get("ability") == key]
        return {
            "generated_at": payload["generated_at"],
            "ability": key or None,
            "recommendations": candidates,
        }

    def recommend_keyword(self, ability: str, dataset: Any | None = None) -> dict[str, Any]:
        dataset = dataset or self.repository.load_dataset()
        key = normalize_ability_key(ability)
        raw_keywords = (dataset.ability_keywords.get("abilities") or {}).get(key) or []
        keywords = [
            {
                "ability": key,
                "keyword": str(item.get("keyword") or ""),
                "weight": float(item.get("weight", 1.0)),
                "platform": str(item.get("platform") or "all"),
                "language": str(item.get("language") or dataset.ability_keywords.get("default_language") or "zh"),
                "priority": int(item.get("priority") or 100),
            }
            for item in raw_keywords
            if item.get("keyword")
        ]
        keywords.sort(key=lambda item: (item["priority"], -item["weight"], item["keyword"]))
        return {"ability": key, "keywords": keywords}

    def recommend_platform(self, ability: str) -> dict[str, Any]:
        dataset = self.repository.load_dataset()
        return {
            "ability": normalize_ability_key(ability),
            "platforms": PlatformRegistry(dataset.platform_weights).rank_platforms(normalize_ability_key(ability)),
        }

    def creator_exists(self, creator_name: str, platform: str = "bilibili") -> bool:
        dataset = self.repository.load_dataset()
        target = self._candidate_identity(creator_name, platform)
        for item in dataset.creator_manifest.get("creators") or []:
            if self._candidate_identity(str(item.get("author") or ""), platform) == target:
                return True
        for item in dataset.candidates:
            if self._candidate_identity(item.get("creator_name", ""), item.get("platform", "")) == target:
                return True
        for item in dataset.approved_creators:
            if self._candidate_identity(item.get("creator_name", ""), item.get("platform", "")) == target:
                return True
        return False

    def add_candidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset = self.repository.load_dataset()
        generated_at = now_iso()
        ability = normalize_ability_key(str(payload.get("ability") or ""))
        platform = str(payload.get("platform") or "bilibili").lower()
        creator_name = str(payload.get("creator_name") or payload.get("name") or "").strip()
        if not creator_name:
            raise ValueError("creator_name is required")
        enabled_platforms = PlatformRegistry(dataset.platform_weights).enabled_platforms()
        if platform not in enabled_platforms:
            raise ValueError(f"platform is not enabled: {platform}")
        candidate = {
            "candidate_id": stable_id(platform, creator_name, ability),
            "creator_id": payload.get("creator_id") or None,
            "creator_name": creator_name,
            "platform": platform,
            "category": str(payload.get("category") or ""),
            "recommend_source": str(payload.get("recommend_source") or "manual"),
            "recommend_reason": str(payload.get("recommend_reason") or "Manually added candidate."),
            "confidence": float(payload.get("confidence", 0.75)),
            "ability": ability,
            "keyword": str(payload.get("keyword") or ""),
            "status": str(payload.get("status") or (dataset.discovery_rules.get("candidate") or {}).get("manual_candidate_status") or "pending_review"),
            "need_analyze": bool(payload.get("need_analyze", True)),
            "create_time": generated_at,
            "last_update": generated_at,
            "source_url": str(payload.get("source_url") or ""),
            "metadata": dict(payload.get("metadata") or {}),
        }
        existing = next(
            (
                item
                for item in dataset.candidates
                if item.get("candidate_id") == candidate["candidate_id"]
            ),
            None,
        )
        if existing:
            candidate = {
                **existing,
                **candidate,
                "create_time": existing.get("create_time") or generated_at,
                "status": str(payload.get("status") or existing.get("status") or "pending_review"),
                "source_url": str(payload.get("source_url") or existing.get("source_url") or ""),
                "metadata": {
                    **dict(existing.get("metadata") or {}),
                    **dict(payload.get("metadata") or {}),
                },
            }
            candidates = [
                candidate if item.get("candidate_id") == candidate["candidate_id"] else item
                for item in dataset.candidates
            ]
        else:
            candidates = self._merge_candidates(
                list(dataset.candidates),
                [candidate],
                dataset.discovery_rules,
            )
        self.repository.save_candidates(candidates)
        return {"candidate": candidate, "candidate_count": len(candidates)}

    def approve_candidate(self, candidate_id: str) -> dict[str, Any]:
        dataset = self.repository.load_dataset()
        state_machine = CandidateStateMachine(dataset.discovery_rules)
        generated_at = now_iso()
        candidates: list[dict[str, Any]] = []
        approved: dict[str, Any] | None = None
        for candidate in dataset.candidates:
            if candidate.get("candidate_id") == candidate_id:
                approved = state_machine.transition(candidate, "approved", generated_at)
                approved = state_machine.transition(approved, "waiting_analyze", generated_at)
                candidates.append(approved)
            else:
                candidates.append(candidate)
        if not approved:
            raise ValueError(f"candidate not found: {candidate_id}")
        approved_creators = self._merge_approved_creators(dataset.approved_creators, approved)
        self.repository.save_candidates(candidates)
        self.repository.save_approved_creators(approved_creators)
        return {"candidate": approved, "approved_creators": approved_creators}

    def start_analysis(self, candidate_id: str) -> dict[str, Any]:
        dataset = self.repository.load_dataset()
        state_machine = CandidateStateMachine(dataset.discovery_rules)
        generated_at = now_iso()
        original = next(
            (
                candidate
                for candidate in dataset.candidates
                if candidate.get("candidate_id") == candidate_id
            ),
            None,
        )
        if not original:
            raise ValueError(f"candidate not found: {candidate_id}")

        analysis_request = self._build_analysis_request(original)
        if not analysis_request["ready"]:
            return {"candidate": original, "analysis_request": analysis_request}

        candidates: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        for candidate in dataset.candidates:
            if candidate.get("candidate_id") == candidate_id:
                if candidate.get("status") in {"approved", "failed"}:
                    candidate = state_machine.transition(candidate, "waiting_analyze", generated_at)
                selected = (
                    candidate
                    if candidate.get("status") == "analyzing"
                    else state_machine.transition(candidate, "analyzing", generated_at)
                )
                candidates.append(selected)
            else:
                candidates.append(candidate)
        self.repository.save_candidates(candidates)
        return {
            "candidate": selected,
            "analysis_request": analysis_request,
        }

    def finish_analysis(
        self,
        candidate_id: str,
        succeeded: bool,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        dataset = self.repository.load_dataset()
        state_machine = CandidateStateMachine(dataset.discovery_rules)
        generated_at = now_iso()
        target = "analyzed" if succeeded else "failed"
        candidates: list[dict[str, Any]] = []
        selected: dict[str, Any] | None = None
        for candidate in dataset.candidates:
            if candidate.get("candidate_id") != candidate_id:
                candidates.append(candidate)
                continue
            selected = (
                candidate
                if candidate.get("status") == target
                else state_machine.transition(candidate, target, generated_at)
            )
            selected = dict(selected)
            metadata = dict(selected.get("metadata") or {})
            metadata["last_analysis"] = {
                "succeeded": succeeded,
                "finished_at": generated_at,
                **(result or {}),
            }
            selected["metadata"] = metadata
            candidates.append(selected)
        if not selected:
            raise ValueError(f"candidate not found: {candidate_id}")
        self.repository.save_candidates(candidates)
        return {"candidate": selected}

    def update_creator_score(self, creator_id: str, ability_result: dict[str, Any]) -> dict[str, Any]:
        dataset = self.repository.load_dataset()
        ability = normalize_ability_key(str(ability_result.get("ability") or ability_result.get("ability_key") or ""))
        if not ability:
            raise ValueError("ability is required")
        generated_at = now_iso()
        matrix = [
            item
            for item in dataset.creator_matrix
            if not (item.get("creator_id") == creator_id and item.get("ability") == ability)
        ]
        row = {
            "creator_id": creator_id,
            "creator_name": str(ability_result.get("creator_name") or ""),
            "platform": str(ability_result.get("platform") or "bilibili"),
            "ability": ability,
            "score": float(ability_result.get("score", 0)),
            "confidence": float(ability_result.get("confidence", 0.7)),
            "video_count": int(ability_result.get("video_count", 0)),
            "last_analyze": generated_at,
            "category": str(ability_result.get("category") or ""),
        }
        matrix.append(row)
        self.repository.save_matrix(matrix)
        return {"updated": row, "matrix_count": len(matrix)}

    def get_dashboard(self) -> dict[str, Any]:
        return self.discover_creator(save=True)["dashboard"]

    def _target_gaps(self, gap_analysis: dict[str, Any], ability: str | None) -> list[dict[str, Any]]:
        gaps = gap_analysis.get("gap_ranking") or []
        if ability:
            key = normalize_ability_key(ability)
            matching = [item for item in gaps if normalize_ability_key(str(item.get("ability_key") or item.get("ability_name") or "")) == key]
            if matching:
                return matching
            for item in gap_analysis.get("ability_ranking") or []:
                if normalize_ability_key(str(item.get("ability_key") or item.get("ability_name") or "")) == key:
                    return [item]
            return [{"ability_key": key, "ability_name": key, "score": 0, "target": {}, "gap": {"score_gap": 0}}]
        return gaps[:12]

    @staticmethod
    def _build_analysis_request(candidate: dict[str, Any]) -> dict[str, Any]:
        platform = str(candidate.get("platform") or "").strip().lower()
        source = str(candidate.get("source_url") or "").strip()
        mode = ""
        note = ""

        if platform == "bilibili":
            if not source:
                source = str(candidate.get("creator_name") or "").strip()
                mode = "up"
                note = "未保存主页链接，将通过 B站 UP 名解析。"
            elif is_bilibili_up_source(source):
                mode = "up"
            elif is_bilibili_url(source):
                mode = "video"
            else:
                note = "请填写 B站 UP 主页或公开视频链接。"
        elif platform == "youtube":
            if is_youtube_channel_url(source):
                mode = "up"
            elif is_youtube_url(source):
                mode = "video"
            else:
                note = "请填写 YouTube 单视频链接或频道主页链接。"
        elif platform == "douyin":
            if is_douyin_profile_url(source):
                mode = "up"
            elif is_douyin_video_url(source):
                mode = "video"
            else:
                note = "请填写抖音创作者主页或公开视频分享链接。"
        elif platform == "xiaohongshu":
            if is_xiaohongshu_video_url(source):
                mode = "video"
            else:
                note = "当前支持小红书视频笔记分享链接，创作者主页批量分析尚未接入。"
        else:
            note = f"平台 {platform or 'unknown'} 尚未接入自动分析。"

        return {
            "platform": platform,
            "source_url": source,
            "creator_name": candidate.get("creator_name"),
            "ability": candidate.get("ability"),
            "mode": mode,
            "ready": bool(source and mode),
            "note": note,
        }

    def _threshold_for(self, ability: str, thresholds: dict[str, Any]) -> dict[str, Any]:
        default = thresholds.get("default") or {}
        ability_threshold = (thresholds.get("abilities") or {}).get(ability) or {}
        return {
            "target_creator_count": int(ability_threshold.get("target_creator_count", default.get("target_creator_count", 5))),
            "excellent_creator_score": float(ability_threshold.get("excellent_creator_score", default.get("excellent_creator_score", 75))),
            "min_video_count": int(ability_threshold.get("min_video_count", default.get("min_video_count", 3))),
            "min_confidence": float(ability_threshold.get("min_confidence", default.get("min_confidence", 0.6))),
        }

    def _excellent_creators(self, matrix: list[dict[str, Any]], ability: str, threshold: dict[str, Any]) -> list[dict[str, Any]]:
        rows = []
        for row in matrix:
            if normalize_ability_key(str(row.get("ability") or "")) != ability:
                continue
            if float(row.get("score") or 0) < float(threshold["excellent_creator_score"]):
                continue
            if float(row.get("confidence") or 0) < float(threshold["min_confidence"]):
                continue
            if int(row.get("video_count") or 0) < int(threshold["min_video_count"]):
                continue
            rows.append(row)
        return sorted(rows, key=lambda item: (-float(item.get("score", 0)), -int(item.get("video_count", 0)), item.get("creator_name", "")))

    def _build_search_plan(
        self,
        ability: str,
        platforms: list[dict[str, Any]],
        keywords: list[dict[str, Any]],
        dataset: Any,
    ) -> dict[str, Any]:
        rules = dataset.discovery_rules.get("search_plan") or {}
        max_platforms = int(rules.get("max_platforms_per_ability", 4))
        max_keywords = int(rules.get("max_keywords_per_platform", 6))
        items = []
        for platform in platforms[:max_platforms]:
            platform_key = platform["platform"]
            platform_keywords = [
                item for item in keywords if item["platform"] in {"all", platform_key}
            ][:max_keywords]
            items.append(
                {
                    "platform": platform_key,
                    "platform_score": platform["score"],
                    "supports_auto_fetch": platform["supports_auto_fetch"],
                    "auto_fetch_scope": platform.get("auto_fetch_scope", "none"),
                    "supports_creator_batch": platform.get("supports_creator_batch", False),
                    "keywords": platform_keywords,
                    "search_modes": platform.get("search_modes", []),
                }
            )
        return {"ability": ability, "platforms": items}

    def _build_candidates(
        self,
        ability_key: str,
        gap: dict[str, Any],
        dataset: Any,
        platforms: list[dict[str, Any]],
        keywords: list[dict[str, Any]],
        generated_at: str,
    ) -> list[dict[str, Any]]:
        rules = dataset.discovery_rules
        candidate_rules = rules.get("candidate") or {}
        max_candidates = int(candidate_rules.get("max_candidates_per_ability", 20))
        min_confidence = float(candidate_rules.get("min_confidence", 0.55))
        matches = [value.lower() for value in (rules.get("ability_category_matches") or {}).get(ability_key, [])]
        platform_score = platforms[0]["score"] if platforms else 0.6
        keyword = keywords[0]["keyword"] if keywords else ""
        keyword_weight = keywords[0]["weight"] if keywords else 0.5
        candidates: list[dict[str, Any]] = []

        for creator in dataset.creator_manifest.get("creators") or []:
            name = str(creator.get("author") or "").strip()
            if not name:
                continue
            category = str(creator.get("positioning") or "")
            category_lower = category.lower()
            matched_category = any(term in category_lower for term in matches)
            if not matched_category:
                continue
            video_count = int(creator.get("video_count") or 0)
            confidence = min(0.95, 0.45 + platform_score * 0.2 + keyword_weight * 0.15 + min(video_count / 20, 0.15))
            if confidence < min_confidence:
                continue
            candidates.append(
                {
                    "candidate_id": stable_id("bilibili", name, ability_key),
                    "creator_id": stable_id("bilibili", name),
                    "creator_name": name,
                    "platform": "bilibili",
                    "category": category,
                    "recommend_source": "database_category_match",
                    "recommend_reason": f"Creator category '{category}' matches discovery rule for {ability_key}.",
                    "confidence": round(confidence, 3),
                    "ability": ability_key,
                    "keyword": keyword,
                    "status": candidate_rules.get("default_status", "pending_review"),
                    "need_analyze": True,
                    "create_time": generated_at,
                    "last_update": generated_at,
                    "source_url": "",
                    "metadata": {
                        "gap_priority": (gap.get("gap") or {}).get("priority_score", 0),
                        "source_video_count": video_count,
                    },
                }
            )

        for approved in dataset.approved_creators:
            if normalize_ability_key(str(approved.get("ability") or "")) != ability_key:
                continue
            candidates.append({**approved, "recommend_source": "approved_creator_pool"})

        return sorted(candidates, key=lambda item: (-float(item.get("confidence", 0)), item["creator_name"]))[:max_candidates]

    def _merge_candidates(
        self,
        existing: list[dict[str, Any]],
        new_items: list[dict[str, Any]],
        discovery_rules: dict[str, Any],
    ) -> list[dict[str, Any]]:
        dedupe = bool((discovery_rules.get("candidate") or {}).get("dedupe_by_name_platform_ability", True))
        merged = list(existing)
        seen = {
            (self._candidate_identity(item.get("creator_name", ""), item.get("platform", "")), item.get("ability", ""))
            for item in merged
        }
        for item in new_items:
            key = (self._candidate_identity(item.get("creator_name", ""), item.get("platform", "")), item.get("ability", ""))
            if dedupe and key in seen:
                continue
            merged.append(item)
            seen.add(key)
        return merged

    def _merge_approved_creators(self, approved_creators: list[dict[str, Any]], candidate: dict[str, Any]) -> list[dict[str, Any]]:
        identity = self._candidate_identity(candidate.get("creator_name", ""), candidate.get("platform", ""))
        rows = [
            item for item in approved_creators
            if self._candidate_identity(item.get("creator_name", ""), item.get("platform", "")) != identity
        ]
        rows.append(
            {
                "creator_id": candidate.get("creator_id") or stable_id(candidate.get("platform", ""), candidate.get("creator_name", "")),
                "creator_name": candidate.get("creator_name", ""),
                "platform": candidate.get("platform", ""),
                "category": candidate.get("category", ""),
                "ability": candidate.get("ability", ""),
                "status": "waiting_analyze",
                "source_url": candidate.get("source_url", ""),
                "last_update": candidate.get("last_update", ""),
            }
        )
        return rows

    def _candidate_identity(self, creator_name: str, platform: str) -> str:
        return f"{str(platform).strip().lower()}::{str(creator_name).strip().lower()}"

    def _ai_status(self, discovery_rules: dict[str, Any], candidates: list[dict[str, Any]], ability_results: list[dict[str, Any]]) -> dict[str, Any]:
        config = discovery_rules.get("ai_discovery") or {}
        unresolved = [item for item in ability_results if item["mode"] == "discovery" and item["new_candidate_count"] == 0]
        return {
            "enabled": bool(config.get("enabled", False)),
            "allowed": bool(config.get("enabled", False) and unresolved),
            "used": False,
            "reason": "AI Discovery is disabled by config." if not config.get("enabled", False) else "No AI call was made in this run.",
            "unresolved_ability_count": len(unresolved),
        }

    def _flatten_platforms(self, search_plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for plan in search_plans:
            for platform in plan.get("platforms") or []:
                rows.append({"ability": plan["ability"], **{k: v for k, v in platform.items() if k != "keywords"}})
        return rows

    def _flatten_keywords(self, search_plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for plan in search_plans:
            for platform in plan.get("platforms") or []:
                for keyword in platform.get("keywords") or []:
                    rows.append({**keyword, "selected_platform": platform["platform"]})
        return rows

    def _next_actions(self, ability_results: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        waiting = [item for item in candidates if item.get("status") == "waiting_analyze"]
        pending = [item for item in candidates if item.get("status") == "pending_review"]
        return [
            {
                "action": "review_candidates",
                "count": len(pending),
                "reason": "Candidates must be manually approved before analysis.",
            },
            {
                "action": "analyze_approved_creators",
                "count": len(waiting),
                "reason": "Approved creators are waiting for the existing analysis pipeline.",
            },
            {
                "action": "expand_search",
                "count": sum(1 for item in ability_results if item["mode"] == "discovery"),
                "reason": "Abilities below creator threshold need additional platform search.",
            },
        ]

    def _build_dashboard(
        self,
        dataset: Any,
        ability_results: list[dict[str, Any]],
        candidates: list[dict[str, Any]],
        search_plans: list[dict[str, Any]],
    ) -> dict[str, Any]:
        platform_distribution = Counter(item.get("platform", "unknown") for item in candidates)
        status_distribution = Counter(item.get("status", "unknown") for item in candidates)
        ability_distribution = Counter(item.get("ability", "unknown") for item in candidates)
        matrix_coverage = Counter(item.get("ability", "unknown") for item in dataset.creator_matrix)
        history = sorted(candidates, key=lambda item: item.get("last_update", ""), reverse=True)[:20]
        return {
            "ability_gap": ability_results,
            "creator_pool": candidates,
            "waiting_analyze": [item for item in candidates if item.get("status") == "waiting_analyze"],
            "pending_review": [item for item in candidates if item.get("status") == "pending_review"],
            "platform_distribution": dict(platform_distribution),
            "status_distribution": dict(status_distribution),
            "discovery_history": history,
            "ability_coverage": [
                {
                    "ability": ability,
                    "matrix_creator_count": matrix_coverage.get(ability, 0),
                    "candidate_count": ability_distribution.get(ability, 0),
                }
                for ability in sorted(set(matrix_coverage) | set(ability_distribution))
            ],
            "growth_trend": self._growth_trend(),
            "search_plan": search_plans,
        }

    def _growth_trend(self) -> list[dict[str, Any]]:
        if not self.repository.history_dir.exists():
            return []
        rows = []
        for path in sorted(self.repository.history_dir.glob("*.json"), reverse=True)[:12]:
            try:
                import json

                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            dashboard = payload.get("dashboard") or {}
            rows.append(
                {
                    "generated_at": payload.get("generated_at", path.stem),
                    "candidate_count": len(dashboard.get("creator_pool") or []),
                    "waiting_analyze_count": len(dashboard.get("waiting_analyze") or []),
                    "pending_review_count": len(dashboard.get("pending_review") or []),
                }
            )
        return rows
