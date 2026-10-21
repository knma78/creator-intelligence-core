from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any

from config import SETTINGS, Settings
from downloader.bilibili import extract_bv_id, normalize_bilibili_url
from downloader.bilibili_common import create_bilibili_session
from downloader.platform_auth import get_platform_auth_status
from models import (
    AccessAssessment,
    AcquisitionStrategy,
    EntitlementState,
    LoginState,
    MediaAvailability,
)

_EP_RE = re.compile(r"/ep(\d+)", re.IGNORECASE)
_SS_RE = re.compile(r"/ss(\d+)", re.IGNORECASE)
_MD_RE = re.compile(r"/md(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class BilibiliEntitlement:
    source: str
    login_state: LoginState
    account_tier: str | None
    account_valid_until: str | None
    content_id: str | None
    title: str | None
    author: str | None
    duration: float | None
    content_requirement: str
    viewing_eligible: bool | None
    official_subtitle_available: bool | None
    media_stream_available: bool | None
    can_direct_download: bool | None
    recommended_strategy: AcquisitionStrategy
    reason: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "login_state": self.login_state.value,
            "recommended_strategy": self.recommended_strategy.value,
        }

    def to_access_assessment(self) -> AccessAssessment:
        entitlement = EntitlementState.UNKNOWN
        if self.viewing_eligible is True:
            entitlement = EntitlementState.ALLOWED
        elif self.viewing_eligible is False:
            entitlement = EntitlementState.DENIED
        availability = MediaAvailability.UNKNOWN
        if self.media_stream_available is True:
            availability = MediaAvailability.DIRECT_STREAM
        elif self.media_stream_available is False:
            availability = MediaAvailability.UNAVAILABLE
        return AccessAssessment(
            source=self.source,
            platform="bilibili",
            login_state=self.login_state,
            entitlement_state=entitlement,
            media_availability=availability,
            can_attempt=self.viewing_eligible is not False,
            reason=self.reason,
            account_tier=self.account_tier,
            account_valid_until=self.account_valid_until,
            content_requirement=self.content_requirement,
            evidence={
                **self.evidence,
                "viewing_eligible": self.viewing_eligible,
                "official_subtitle_available": self.official_subtitle_available,
                "media_stream_available": self.media_stream_available,
                "can_direct_download": self.can_direct_download,
                "recommended_strategy": self.recommended_strategy.value,
            },
        )

    def with_media_result(
        self,
        available: bool,
        *,
        reason: str,
    ) -> "BilibiliEntitlement":
        if available:
            strategy = AcquisitionStrategy.DIRECT_DOWNLOAD
        elif self.viewing_eligible is True:
            strategy = AcquisitionStrategy.BROWSER_PLAYBACK_CAPTURE
        else:
            strategy = AcquisitionStrategy.MANUAL_IMPORT
        return replace(
            self,
            media_stream_available=available,
            can_direct_download=available,
            recommended_strategy=strategy,
            reason=reason,
        )


class BilibiliEntitlementService:
    def __init__(self, settings: Settings = SETTINGS) -> None:
        self.settings = settings

    def assess(
        self,
        source: str,
        *,
        probe_media: bool = False,
    ) -> BilibiliEntitlement:
        source = normalize_bilibili_url(source)
        auth = get_platform_auth_status("bilibili", self.settings)
        login_state = (
            LoginState.AUTHENTICATED
            if auth.get("ready")
            else LoginState.NOT_CONFIGURED
        )
        account_tier = None
        account_valid_until = None
        account_active = False
        evidence: dict[str, Any] = {
            "auth_state": auth.get("state"),
            "auth_source": auth.get("source"),
        }

        session = create_bilibili_session(self.settings, source)
        try:
            nav = self._get_payload(
                session,
                "https://api.bilibili.com/x/web-interface/nav",
            )
            is_login = bool(nav.get("isLogin"))
            login_state = (
                LoginState.AUTHENTICATED
                if is_login
                else LoginState.NOT_CONFIGURED
            )
            vip_type = int(nav.get("vipType") or 0)
            vip_status = int(nav.get("vipStatus") or 0)
            account_active = is_login and vip_status == 1 and vip_type > 0
            account_tier = _vip_label(vip_type, account_active)
            account_valid_until = _timestamp_date(nav.get("vipDueDate"))
            evidence.update(
                {
                    "nav_login": is_login,
                    "vip_type": vip_type,
                    "vip_status": vip_status,
                }
            )
        except Exception as exc:
            evidence["nav_error"] = str(exc)

        content = self._content_info(session, source)
        requirement = _content_requirement(content)
        user_paid = _user_paid(content)
        if requirement == "public":
            eligible: bool | None = True
        elif requirement == "vip":
            eligible = account_active
        elif requirement == "purchase":
            eligible = True if user_paid is True else None
        else:
            eligible = None

        if eligible is True:
            reason = "账号与作品访问条件预检通过；媒体流仍需单独探测。"
        elif eligible is False:
            reason = "当前账号不满足作品声明的访问条件。"
        else:
            reason = "平台没有返回足够信息确认当前账号是否具备观看资格。"

        evidence.update(
            {
                "content_api": content.get("_api"),
                "content_badge": content.get("_badge"),
                "user_paid": user_paid,
            }
        )
        result = BilibiliEntitlement(
            source=source,
            login_state=login_state,
            account_tier=account_tier,
            account_valid_until=account_valid_until,
            content_id=str(content.get("_content_id") or "") or None,
            title=str(content.get("_title") or "") or None,
            author=str(content.get("_author") or "") or None,
            duration=_duration_seconds(content.get("_duration")),
            content_requirement=requirement,
            viewing_eligible=eligible,
            official_subtitle_available=None,
            media_stream_available=None,
            can_direct_download=None,
            recommended_strategy=AcquisitionStrategy.PLATFORM_AUTO,
            reason=reason,
            evidence=evidence,
        )
        return self.probe_media(result) if probe_media else result

    def probe_media(
        self,
        entitlement: BilibiliEntitlement,
    ) -> BilibiliEntitlement:
        from downloader.bilibili import BilibiliDownloader

        try:
            info = BilibiliDownloader(self.settings).probe(
                entitlement.source
            )
            subtitle = bool(
                BilibiliDownloader._pick_official_subtitle_lang(info)
            )
            formats = bool(info.get("formats"))
            if subtitle:
                strategy = AcquisitionStrategy.PLATFORM_SUBTITLE
                reason = "权限预检通过，平台返回了可处理的官方字幕。"
            elif formats:
                strategy = AcquisitionStrategy.DIRECT_DOWNLOAD
                reason = "权限预检通过，平台返回了可下载媒体流。"
            elif entitlement.viewing_eligible is True:
                strategy = AcquisitionStrategy.BROWSER_PLAYBACK_CAPTURE
                reason = "账号可观看，但平台没有返回官方字幕或可下载媒体流。"
            else:
                strategy = AcquisitionStrategy.MANUAL_IMPORT
                reason = "平台没有返回官方字幕或可下载媒体流。"
            return replace(
                entitlement,
                official_subtitle_available=subtitle,
                media_stream_available=formats,
                can_direct_download=formats,
                recommended_strategy=strategy,
                reason=reason,
            )
        except Exception as exc:
            if is_media_unavailable_error(exc):
                return replace(
                    entitlement.with_media_result(
                        False,
                        reason=(
                            "账号可观看，但平台没有向下载器返回媒体流；"
                            "可在明确授权后使用本地播放采集。"
                            if entitlement.viewing_eligible is True
                            else "平台没有向下载器返回媒体流。"
                        ),
                    ),
                    official_subtitle_available=False,
                )
            return replace(
                entitlement,
                reason=f"媒体探测失败，暂时无法确认直接下载状态：{exc}",
            )

    def _content_info(self, session: Any, source: str) -> dict[str, Any]:
        bvid = extract_bv_id(source)
        if bvid:
            data = self._get_payload(
                session,
                "https://api.bilibili.com/x/web-interface/view",
                {"bvid": bvid},
            )
            owner = data.get("owner") or {}
            return {
                **data,
                "_api": "x/web-interface/view",
                "_content_id": data.get("bvid") or bvid,
                "_title": data.get("title"),
                "_author": owner.get("name"),
                "_duration": data.get("duration"),
                "_badge": "",
            }

        params: dict[str, str] = {}
        identifier = None
        for pattern, key, prefix in (
            (_EP_RE, "ep_id", "ep"),
            (_SS_RE, "season_id", "ss"),
            (_MD_RE, "media_id", "md"),
        ):
            match = pattern.search(source)
            if match:
                params[key] = match.group(1)
                identifier = f"{prefix}{match.group(1)}"
                break
        if not params:
            return {
                "_api": "unresolved",
                "_content_id": None,
                "_title": None,
                "_author": None,
                "_duration": None,
                "_badge": "",
            }

        result = self._get_payload(
            session,
            "https://api.bilibili.com/pgc/view/web/season",
            params,
        )
        episodes = result.get("episodes") or []
        selected = _select_episode(episodes, params.get("ep_id"))
        badge = str(
            selected.get("badge")
            or (selected.get("badge_info") or {}).get("text")
            or ""
        )
        title = str(
            selected.get("long_title")
            or selected.get("title")
            or result.get("season_title")
            or result.get("title")
            or ""
        )
        content_id = selected.get("bvid") or (
            f"ep{selected.get('id')}" if selected.get("id") else identifier
        )
        return {
            **result,
            "_selected_episode": selected,
            "_api": "pgc/view/web/season",
            "_content_id": content_id,
            "_title": title,
            "_author": None,
            "_duration": selected.get("duration"),
            "_badge": badge,
        }

    @staticmethod
    def _get_payload(
        session: Any,
        url: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = session.get(url, params=params, timeout=20)
        response.raise_for_status()
        payload = response.json()
        code = int(payload.get("code") or 0)
        if code != 0:
            raise RuntimeError(
                f"B站权限接口返回 {code}: "
                f"{payload.get('message') or payload.get('msg') or 'unknown'}"
            )
        data = payload.get("data")
        if not isinstance(data, dict):
            data = payload.get("result")
        return data if isinstance(data, dict) else {}


def is_media_unavailable_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "no video formats",
            "requested format is not available",
            "media stream",
            "premium member",
            "premium members",
            "geo restriction",
            "geo-restricted",
            "not available from your location",
            "没有向下载器返回媒体流",
            "没有可下载",
        )
    )


def _vip_label(vip_type: int, active: bool) -> str:
    if not active:
        return "未开通或已失效"
    if vip_type == 2:
        return "年度大会员"
    if vip_type == 1:
        return "大会员"
    return f"会员类型 {vip_type}"


def _timestamp_date(value: Any) -> str | None:
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    if timestamp > 10_000_000_000:
        timestamp /= 1000
    try:
        return datetime.fromtimestamp(
            timestamp,
            timezone.utc,
        ).date().isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _select_episode(
    episodes: list[Any],
    ep_id: str | None,
) -> dict[str, Any]:
    candidates = [item for item in episodes if isinstance(item, dict)]
    if ep_id:
        selected = next(
            (
                item
                for item in candidates
                if str(item.get("id") or "") == str(ep_id)
            ),
            None,
        )
        if selected:
            return selected
    return candidates[0] if candidates else {}


def _content_requirement(content: dict[str, Any]) -> str:
    badge = str(content.get("_badge") or "").lower()
    rights = content.get("rights") or {}
    selected_rights = (content.get("_selected_episode") or {}).get("rights") or {}
    text = " ".join(
        str(value)
        for value in (
            badge,
            rights.get("allow_vip_download"),
            rights.get("pay"),
            selected_rights.get("allow_vip_download"),
            selected_rights.get("pay"),
        )
    ).lower()
    if any(marker in badge for marker in ("会员", "vip")):
        return "vip"
    if any(marker in badge for marker in ("付费", "购买", "券")):
        return "purchase"
    if str(rights.get("pay") or selected_rights.get("pay") or "0") not in {
        "0",
        "false",
        "none",
    }:
        return "purchase"
    if "vip" in text:
        return "vip"
    return "public"


def _user_paid(content: dict[str, Any]) -> bool | None:
    user_status = content.get("user_status") or {}
    if "pay" not in user_status:
        return None
    return bool(user_status.get("pay"))


def _duration_seconds(value: Any) -> float | None:
    try:
        duration = float(value)
    except (TypeError, ValueError):
        return None
    if duration > 100_000:
        duration /= 1000
    return duration if duration > 0 else None
