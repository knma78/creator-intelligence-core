from __future__ import annotations

import json
import hashlib
import re
from dataclasses import replace
from pathlib import Path
from typing import Callable

from config import SETTINGS, Settings, ensure_directories
from infrastructure.cancellation import (
    JobCancelledError,
    cancellation_scope,
    raise_if_cancelled,
)
from downloader.bilibili import BilibiliDownloader, is_bilibili_url
from downloader.bilibili_entitlement import (
    BilibiliEntitlement,
    BilibiliEntitlementService,
    is_media_unavailable_error,
)
from downloader.local import LocalDownloader, is_local_path
from downloader.platform_auth import get_platform_auth_status
from downloader.social import SocialVideoDownloader, detect_social_platform
from downloader.youtube import YoutubeDownloader, is_youtube_url
from infrastructure.atomic_io import atomic_write_json
from infrastructure.resources import ResourceKind, get_resource_manager
from infrastructure.progress import DownloadProgressMessage
from models import (
    AccessAssessment,
    AcquisitionPlan,
    AcquisitionResult,
    AcquisitionStrategy,
    EntitlementState,
    LoginState,
    MediaArtifact,
    MediaAvailability,
    Video,
)
from pipeline.registry import SourceHandler, SourceRegistry, UnsupportedSourceError
from processor.system_audio import (
    capture_system_audio,
    open_playback_source,
)

_VIDEO_SOURCE_REGISTRY: SourceRegistry[Settings, Video] | None = None


def get_video_source_registry() -> SourceRegistry[Settings, Video]:
    global _VIDEO_SOURCE_REGISTRY
    if _VIDEO_SOURCE_REGISTRY is None:
        registry: SourceRegistry[Settings, Video] = SourceRegistry("video")
        registry.register(
            SourceHandler(
                "local",
                is_local_path,
                lambda source, settings: LocalDownloader(settings).download(source),
            )
        )
        registry.register(
            SourceHandler(
                "bilibili",
                is_bilibili_url,
                lambda source, settings: BilibiliDownloader(settings).download(source),
            )
        )
        registry.register(
            SourceHandler(
                "youtube",
                is_youtube_url,
                lambda source, settings: YoutubeDownloader(settings).download(source),
            )
        )
        registry.register(
            SourceHandler(
                "social",
                lambda source: bool(detect_social_platform(source)),
                lambda source, settings: SocialVideoDownloader(
                    str(detect_social_platform(source)),
                    settings,
                ).download(source),
            )
        )
        _VIDEO_SOURCE_REGISTRY = registry
    return _VIDEO_SOURCE_REGISTRY


def register_video_source_handler(
    handler: SourceHandler[Settings, Video],
    *,
    prepend: bool = True,
    replace: bool = False,
) -> None:
    get_video_source_registry().register(
        handler,
        prepend=prepend,
        replace=replace,
    )


def acquire_video(source: str, settings: Settings = SETTINGS) -> Video:
    return acquire_video_details(source, settings).video


def acquire_video_details(
    source: str,
    settings: Settings = SETTINGS,
    *,
    allow_playback_capture: bool = False,
    capture_duration_seconds: float | None = None,
    progress_callback: Callable[[str, int, str], None] | None = None,
    capture_stop_requested: Callable[[], bool] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
) -> AcquisitionResult:
    raise_if_cancelled(cancel_requested)
    ensure_directories(settings)
    platform = _detect_platform(source)
    entitlement: BilibiliEntitlement | None = None
    entitlement_error: Exception | None = None
    manager = get_resource_manager(settings)
    if platform == "bilibili":
        try:
            with manager.lease(
                ResourceKind.NETWORK_IO,
                owner="bilibili:entitlement",
                cancel_requested=cancel_requested,
            ):
                entitlement = BilibiliEntitlementService(settings).assess(
                    source
                )
            initial_assessment = entitlement.to_access_assessment()
            if progress_callback:
                progress_callback(
                    "权限预检",
                    18,
                    _entitlement_progress_message(entitlement),
                )
        except JobCancelledError:
            raise
        except Exception as exc:
            entitlement_error = exc
            initial_assessment = assess_source_access(
                source,
                platform,
                settings,
            )
            if progress_callback:
                progress_callback(
                    "权限预检降级",
                    18,
                    f"权限预检暂时不可用，将继续尝试普通字幕和媒体采集：{exc}",
                )
    else:
        initial_assessment = assess_source_access(source, platform, settings)
    plan = plan_acquisition(initial_assessment)
    try:
        if platform == "local":
            video = get_video_source_registry().resolve(source, settings)
        else:
            with manager.lease(
                ResourceKind.NETWORK_IO,
                owner=f"acquire:{platform}",
                cancel_requested=cancel_requested,
            ):
                with cancellation_scope(
                    cancel_requested,
                    yt_dlp_progress=(
                        lambda status: _report_download_progress(
                            status,
                            progress_callback,
                        )
                    ),
                ):
                    video = get_video_source_registry().resolve(
                        source,
                        settings,
                    )
    except UnsupportedSourceError as exc:
        raise ValueError(
            "Unsupported source. Supports Bilibili, YouTube, Douyin, "
            f"Xiaohongshu, and local video files: {source}"
        ) from exc
    except JobCancelledError:
        raise
    except Exception as exc:
        if (
            platform == "bilibili"
            and entitlement is not None
            and is_media_unavailable_error(exc)
        ):
            entitlement = entitlement.with_media_result(
                False,
                reason=(
                    "账号具备观看资格，但平台没有向下载器提供可下载媒体流。"
                    if entitlement.viewing_eligible is True
                    else "平台没有提供可下载媒体流，且观看资格未通过预检。"
                ),
            )
            initial_assessment = entitlement.to_access_assessment()
            plan = AcquisitionPlan(
                primary_strategy=(
                    AcquisitionStrategy.BROWSER_PLAYBACK_CAPTURE
                    if entitlement.viewing_eligible is True
                    else AcquisitionStrategy.MANUAL_IMPORT
                ),
                fallback_strategies=(AcquisitionStrategy.MANUAL_IMPORT,),
                requires_browser=entitlement.viewing_eligible is True,
            )
            if not allow_playback_capture:
                raise RuntimeError(
                    f"{exc}\n权限预检：{entitlement.reason}"
                    "\n如你有权在本机正常播放，可在 Web UI 明确勾选"
                    "“允许本地播放采集”后重试。"
                ) from exc
            if entitlement.viewing_eligible is not True:
                raise RuntimeError(
                    f"{exc}\n本地播放采集未启动：当前账号的观看资格"
                    "没有得到明确确认。"
                ) from exc
            video = _capture_bilibili_playback(
                source,
                entitlement,
                settings,
                capture_duration_seconds,
                progress_callback,
                capture_stop_requested,
                cancel_requested,
            )
        else:
            if (
                platform == "bilibili"
                and allow_playback_capture
                and is_media_unavailable_error(exc)
                and entitlement_error is not None
            ):
                raise RuntimeError(
                    f"{exc}\n本地播放采集未启动：权限预检失败，"
                    f"无法安全确认观看资格（{entitlement_error}）。"
                ) from exc
            raise
    if entitlement is not None and not video.extra_metadata.get(
        "playback_audio_path"
    ):
        entitlement = entitlement.with_media_result(
            True,
            reason="权限预检通过，平台已返回可直接处理的字幕或媒体。",
        )
        initial_assessment = entitlement.to_access_assessment()
    return acquisition_from_video(
        video,
        settings,
        source=source,
        assessment=initial_assessment,
        plan=plan,
        persist=True,
    )


def assess_source_access(
    source: str,
    platform: str,
    settings: Settings = SETTINGS,
) -> AccessAssessment:
    if platform == "local":
        return AccessAssessment(
            source=source,
            platform=platform,
            login_state=LoginState.NOT_REQUIRED,
            entitlement_state=EntitlementState.NOT_REQUIRED,
            media_availability=MediaAvailability.LOCAL_MEDIA,
            can_attempt=True,
            reason="Local media does not require platform authorization.",
            evidence={"path_exists": Path(source).expanduser().exists()},
        )

    auth_evidence: dict[str, object] = {}
    if platform in {"bilibili", "youtube"}:
        status = get_platform_auth_status(platform, settings)
        auth_evidence = {
            "state": status.get("state"),
            "source": status.get("source"),
            "ready": bool(status.get("ready")),
        }
        login_state = (
            LoginState.AUTHENTICATED
            if status.get("ready")
            else LoginState.NOT_CONFIGURED
        )
    else:
        cookie_file = getattr(settings, f"{platform}_cookie_file", None)
        browser = getattr(settings, f"{platform}_cookies_from_browser", None)
        ready = bool(cookie_file or browser)
        login_state = (
            LoginState.AUTHENTICATED
            if ready
            else LoginState.UNKNOWN
        )
        auth_evidence = {
            "cookie_configured": bool(cookie_file),
            "browser_cookie_configured": bool(browser),
        }

    return AccessAssessment(
        source=source,
        platform=platform,
        login_state=login_state,
        entitlement_state=EntitlementState.UNKNOWN,
        media_availability=MediaAvailability.UNKNOWN,
        can_attempt=True,
        reason=(
            "Authorization state is known, but content entitlement and media "
            "availability are confirmed only by the platform acquisition result."
        ),
        evidence=auth_evidence,
    )


def plan_acquisition(assessment: AccessAssessment) -> AcquisitionPlan:
    if assessment.platform == "local":
        return AcquisitionPlan(AcquisitionStrategy.LOCAL_FILE)
    return AcquisitionPlan(
        primary_strategy=AcquisitionStrategy.PLATFORM_AUTO,
        fallback_strategies=(
            AcquisitionStrategy.BROWSER_PLAYBACK_CAPTURE,
            AcquisitionStrategy.MANUAL_IMPORT,
        ),
    )


def acquisition_from_video(
    video: Video,
    settings: Settings = SETTINGS,
    *,
    source: str | None = None,
    assessment: AccessAssessment | None = None,
    plan: AcquisitionPlan | None = None,
    persist: bool = True,
) -> AcquisitionResult:
    source = source or video.source_url
    platform = video.platform or _detect_platform(source)
    assessment = assessment or assess_source_access(source, platform, settings)
    plan = plan or plan_acquisition(assessment)

    playback_audio = _playback_audio_path(video)
    if playback_audio and playback_audio.exists():
        strategy = AcquisitionStrategy.BROWSER_PLAYBACK_CAPTURE
        availability = MediaAvailability.PLAYBACK_AUDIO
    elif platform == "local":
        strategy = AcquisitionStrategy.LOCAL_FILE
        availability = MediaAvailability.LOCAL_MEDIA
    elif (
        video.subtitle_path
        and video.subtitle_path.exists()
        and not video.video_path
    ):
        strategy = AcquisitionStrategy.PLATFORM_SUBTITLE
        availability = MediaAvailability.PLATFORM_SUBTITLE
    elif video.video_path and video.video_path.exists():
        strategy = AcquisitionStrategy.DIRECT_DOWNLOAD
        availability = MediaAvailability.DIRECT_STREAM
    else:
        strategy = plan.primary_strategy
        availability = MediaAvailability.UNAVAILABLE

    successful = availability is not MediaAvailability.UNAVAILABLE
    final_assessment = replace(
        assessment,
        entitlement_state=(
            EntitlementState.ALLOWED
            if successful and platform != "local"
            else assessment.entitlement_state
        ),
        media_availability=availability,
        can_attempt=successful,
        reason=(
            f"Acquisition produced {availability.value}."
            if successful
            else "Acquisition returned metadata without usable media or subtitles."
        ),
        evidence={
            **assessment.evidence,
            "video_path": str(video.video_path) if video.video_path else None,
            "subtitle_path": (
                str(video.subtitle_path) if video.subtitle_path else None
            ),
        },
    )
    artifacts = _media_artifacts(video, strategy)
    manifest_path = (
        settings.acquisition_cache_dir
        / _safe_component(platform)
        / f"{_safe_component(video.video_id)}.json"
    )
    result = AcquisitionResult(
        video=video,
        assessment=final_assessment,
        plan=plan,
        selected_strategy=strategy,
        artifacts=artifacts,
        manifest_path=manifest_path,
    )
    if persist:
        atomic_write_json(manifest_path, result.to_dict())
    return result


def _report_download_progress(
    status: dict,
    progress_callback: Callable[[str, int, str], None] | None,
) -> None:
    if progress_callback is None:
        return
    state = str(status.get("status") or "downloading")
    downloaded = int(status.get("downloaded_bytes") or 0)
    total = int(
        status.get("total_bytes")
        or status.get("total_bytes_estimate")
        or 0
    )
    speed = status.get("speed")
    eta = status.get("eta")
    phase = (
        min(100.0, (downloaded / total) * 100)
        if total > 0
        else (100.0 if state == "finished" else 0.0)
    )
    overall = min(34, 20 + int((phase / 100) * 14))
    if total > 0:
        text = (
            f"正在下载媒体：{downloaded / 1048576:.1f}/"
            f"{total / 1048576:.1f} MB"
        )
    else:
        text = f"正在下载媒体：已接收 {downloaded / 1048576:.1f} MB"
    progress_callback(
        "媒体下载",
        overall,
        DownloadProgressMessage(
            text,
            downloaded_bytes=downloaded,
            total_bytes=total,
            speed_bytes_per_second=(
                float(speed) if speed is not None else None
            ),
            eta_seconds=float(eta) if eta is not None else None,
            status=state,
        ),
    )


def _detect_platform(source: str) -> str:
    if is_local_path(source):
        return "local"
    if is_bilibili_url(source):
        return "bilibili"
    if is_youtube_url(source):
        return "youtube"
    return detect_social_platform(source) or "unknown"


def _media_artifacts(
    video: Video,
    strategy: AcquisitionStrategy,
) -> tuple[MediaArtifact, ...]:
    artifacts: list[MediaArtifact] = []
    for kind, path in (
        ("video", video.video_path),
        ("subtitle", video.subtitle_path),
        ("metadata", video.metadata_path),
        ("audio", _playback_audio_path(video)),
    ):
        if path:
            artifacts.append(
                MediaArtifact(
                    kind=kind,
                    path=path,
                    origin=strategy.value,
                    available=path.exists(),
                )
            )
    return tuple(artifacts)


def _safe_component(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return normalized[:120] or "unknown"


def _capture_bilibili_playback(
    source: str,
    entitlement: BilibiliEntitlement,
    settings: Settings,
    capture_duration_seconds: float | None,
    progress_callback: Callable[[str, int, str], None] | None,
    capture_stop_requested: Callable[[], bool] | None,
    cancel_requested: Callable[[], bool] | None,
) -> Video:
    identifier = entitlement.content_id or (
        "capture_"
        + hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]
    )
    video_id = _safe_component(identifier)
    audio_path = (
        settings.playback_capture_dir / video_id / "playback_audio.wav"
    )
    duration = capture_duration_seconds or entitlement.duration
    duration = duration or settings.playback_capture_default_seconds
    if (
        not _valid_wave_file(audio_path)
        or settings.overwrite_cache
    ):
        open_playback_source(
            source,
            settings,
            progress_callback,
            cancel_requested=cancel_requested,
        )
        capture_result = capture_system_audio(
            audio_path,
            duration,
            settings,
            progress_callback,
            stop_requested=capture_stop_requested,
            cancel_requested=cancel_requested,
        )
        if capture_result.likely_silent:
            silent_path = audio_path.with_name("playback_audio.silent.wav")
            silent_path.unlink(missing_ok=True)
            audio_path.replace(silent_path)
            raise RuntimeError(
                "本地播放采集完成，但整段音频接近静音。"
                "请确认网页已开始播放、系统输出设备正确，然后重试。"
            )
        capture_metadata = capture_result.to_dict()
    else:
        capture_metadata = {
            "audio_path": str(audio_path),
            "cached": True,
        }

    metadata_path = settings.video_cache_dir / video_id / "metadata.json"
    video = Video(
        source_url=source,
        platform="bilibili",
        video_id=video_id,
        title=entitlement.title or video_id,
        author=entitlement.author,
        duration=entitlement.duration or float(duration),
        metadata_path=metadata_path,
        extra_metadata={
            "playback_audio_path": str(audio_path),
            "playback_capture": capture_metadata,
            "bilibili_entitlement": entitlement.to_dict(),
        },
    )
    atomic_write_json(metadata_path, video.to_dict())
    return video


def _playback_audio_path(video: Video) -> Path | None:
    value = video.extra_metadata.get("playback_audio_path")
    return Path(str(value)) if value else None


def _valid_wave_file(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 44:
        return False
    try:
        import wave

        with wave.open(str(path), "rb") as stream:
            return (
                stream.getnframes() > 0
                and stream.getnchannels() > 0
                and stream.getframerate() > 0
            )
    except (OSError, EOFError, wave.Error):
        return False


def _entitlement_progress_message(
    entitlement: BilibiliEntitlement,
) -> str:
    account = entitlement.account_tier or "状态未知"
    requirement = {
        "public": "公开内容",
        "vip": "大会员内容",
        "purchase": "需购买内容",
    }.get(entitlement.content_requirement, entitlement.content_requirement)
    eligible = {
        True: "已通过",
        False: "未通过",
        None: "无法确认",
    }[entitlement.viewing_eligible]
    return (
        f"账号权限：{account}；内容要求：{requirement}；"
        f"观看资格：{eligible}；正在探测字幕和媒体流。"
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Acquire a video from URL or local path.")
    parser.add_argument("source")
    args = parser.parse_args()
    result = acquire_video_details(args.source)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
