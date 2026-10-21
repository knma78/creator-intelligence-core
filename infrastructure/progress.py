from __future__ import annotations


class BatchProgressMessage(str):
    """Progress text carrying structured batch metadata for the web UI."""

    def __new__(
        cls,
        text: str,
        *,
        current: int,
        total: int,
    ) -> "BatchProgressMessage":
        value = str.__new__(cls, text)
        value.progress_meta = {
            "type": "batch",
            "current": max(0, int(current)),
            "total": max(0, int(total)),
            "phase_percent": (
                round((current / total) * 100, 1)
                if total > 0
                else None
            ),
            "heartbeat": True,
        }
        return value


class DownloadProgressMessage(str):
    """yt-dlp progress text with byte, speed, and ETA metadata."""

    def __new__(
        cls,
        text: str,
        *,
        downloaded_bytes: int,
        total_bytes: int,
        speed_bytes_per_second: float | None,
        eta_seconds: float | None,
        status: str,
    ) -> "DownloadProgressMessage":
        downloaded = max(0, int(downloaded_bytes or 0))
        total = max(0, int(total_bytes or 0))
        value = str.__new__(cls, text)
        value.progress_meta = {
            "type": "download",
            "status": str(status or "downloading"),
            "downloaded_bytes": downloaded,
            "total_bytes": total,
            "speed_bytes_per_second": (
                max(0.0, float(speed_bytes_per_second))
                if speed_bytes_per_second is not None
                else None
            ),
            "eta_seconds": (
                max(0.0, float(eta_seconds))
                if eta_seconds is not None
                else None
            ),
            "phase_percent": (
                round((downloaded / total) * 100, 1)
                if total > 0
                else None
            ),
            "heartbeat": True,
        }
        return value


class TextProgressMessage(str):
    """Streaming text-generation progress for cancellable LLM jobs."""

    def __new__(
        cls,
        text: str,
        *,
        generated_units: int,
        target_units: int,
        unit_label: str,
    ) -> "TextProgressMessage":
        generated = max(0, int(generated_units or 0))
        target = max(0, int(target_units or 0))
        value = str.__new__(cls, text)
        value.progress_meta = {
            "type": "text_generation",
            "generated_units": generated,
            "target_units": target,
            "unit_label": str(unit_label or "字"),
            "phase_percent": (
                round((generated / target) * 100, 1)
                if target > 0
                else None
            ),
            "heartbeat": True,
        }
        return value
