from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
import wave
import webbrowser
from array import array
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from config import SETTINGS, Settings
from infrastructure.cancellation import (
    JobCancelledError,
    raise_if_cancelled,
    sleep_with_cancellation,
)
from infrastructure.resources import ResourceKind, get_resource_manager


@dataclass(frozen=True)
class SystemAudioDevice:
    index: int
    name: str
    channels: int
    sample_rate: int


@dataclass(frozen=True)
class PlaybackCaptureResult:
    audio_path: Path
    duration_seconds: float
    device: SystemAudioDevice
    peak_level: float
    rms_level: float
    likely_silent: bool
    stopped_early: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "audio_path": str(self.audio_path),
            "device": asdict(self.device),
        }


class PlaybackCaptureProgressMessage(str):
    def __new__(
        cls,
        text: str,
        *,
        state: str,
        phase_percent: float,
        elapsed_seconds: float,
        duration_seconds: float,
        level: float,
        device_name: str,
    ):
        value = str.__new__(cls, text)
        value.progress_meta = {
            "type": "playback_capture",
            "state": state,
            "phase_percent": round(phase_percent, 1),
            "elapsed_seconds": round(elapsed_seconds, 2),
            "duration_seconds": round(duration_seconds, 2),
            "level": round(level, 6),
            "device_name": device_name,
        }
        return value


def get_system_audio_status(
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    if os.name != "nt":
        return {
            "enabled": settings.playback_capture_enabled,
            "available": False,
            "reason": "System playback capture currently supports Windows only.",
        }
    backend = _probe_system_audio_backend_isolated()
    result = {
        "enabled": settings.playback_capture_enabled,
        "default_seconds": settings.playback_capture_default_seconds,
        "max_seconds": settings.playback_capture_max_seconds,
        "captures_all_system_audio": True,
    }
    result.update(backend)
    return result


@lru_cache(maxsize=1)
def _probe_system_audio_backend_isolated() -> dict[str, Any]:
    command = (
        "import json; "
        "from processor.system_audio import _probe_system_audio_backend_in_process as probe; "
        "print(json.dumps(probe(), ensure_ascii=False))"
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=str(SETTINGS.base_dir),
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=creation_flags,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "available": False,
            "reason": "PyAudioWPatch device probe timed out in an isolated process.",
        }
    except OSError as exc:
        return {
            "available": False,
            "reason": f"Unable to start isolated audio probe: {exc}",
        }
    if completed.returncode != 0:
        unsigned_code = completed.returncode & 0xFFFFFFFF
        detail = completed.stderr.strip().splitlines()
        suffix = f" Last error: {detail[-1]}" if detail else ""
        return {
            "available": False,
            "reason": (
                "PyAudioWPatch native probe failed safely in an isolated process "
                f"(exit code 0x{unsigned_code:08X}).{suffix}"
            ),
        }
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return {
            "available": False,
            "reason": "Isolated audio probe returned no status.",
        }
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return {
            "available": False,
            "reason": f"Isolated audio probe returned invalid JSON: {exc}",
        }
    if not isinstance(payload, dict):
        return {
            "available": False,
            "reason": "Isolated audio probe returned an invalid status object.",
        }
    return payload


def _probe_system_audio_backend_in_process() -> dict[str, Any]:
    try:
        import pyaudiowpatch as pyaudio
    except ImportError:
        return {
            "available": False,
            "reason": "PyAudioWPatch is not installed.",
        }
    try:
        device = _default_loopback_device(pyaudio)
    except Exception as exc:
        return {
            "available": False,
            "reason": str(exc),
        }
    return {
        "available": True,
        "backend": "PyAudioWPatch/WASAPI loopback",
        "device": asdict(device),
    }


def open_playback_source(
    source: str,
    settings: Settings = SETTINGS,
    progress_callback: Callable[[str, int, str], None] | None = None,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> None:
    raise_if_cancelled(cancel_requested)
    if settings.playback_capture_open_browser:
        opened = webbrowser.open(source, new=2, autoraise=True)
        if not opened:
            raise RuntimeError(
                "无法自动打开浏览器。请先在已登录的浏览器中打开并播放目标内容。"
            )
    warmup = max(0, settings.playback_capture_warmup_seconds)
    for elapsed in range(warmup):
        remaining = warmup - elapsed
        if progress_callback:
            progress_callback(
                "等待播放",
                24,
                PlaybackCaptureProgressMessage(
                    f"请确认浏览器已开始播放；{remaining} 秒后开始录制系统音频。",
                    state="warmup",
                    phase_percent=0,
                    elapsed_seconds=elapsed,
                    duration_seconds=warmup,
                    level=0,
                    device_name="",
                ),
            )
        sleep_with_cancellation(1, cancel_requested)


def capture_system_audio(
    output_path: Path,
    duration_seconds: float,
    settings: Settings = SETTINGS,
    progress_callback: Callable[[str, int, str], None] | None = None,
    *,
    stop_requested: Callable[[], bool] | None = None,
    cancel_requested: Callable[[], bool] | None = None,
    pyaudio_module: Any | None = None,
) -> PlaybackCaptureResult:
    if not settings.playback_capture_enabled:
        raise RuntimeError("本地播放采集已被 PLAYBACK_CAPTURE_ENABLED 禁用。")
    if os.name != "nt" and pyaudio_module is None:
        raise RuntimeError("本地播放采集目前只支持 Windows WASAPI。")
    if pyaudio_module is None:
        backend = _probe_system_audio_backend_isolated()
        if not backend.get("available"):
            raise RuntimeError(
                str(backend.get("reason") or "System audio capture is unavailable.")
            )
        try:
            import pyaudiowpatch as pyaudio_module
        except ImportError as exc:
            raise RuntimeError(
                "缺少 PyAudioWPatch，无法采集 Windows 系统播放音频。"
            ) from exc

    maximum = max(1, settings.playback_capture_max_seconds)
    requested = max(1.0, min(float(duration_seconds), float(maximum)))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".part")
    temporary_path.unlink(missing_ok=True)

    audio = pyaudio_module.PyAudio()
    stream = None
    started = time.monotonic()
    peak_level = 0.0
    sum_squares = 0.0
    sample_count = 0
    stopped_early = False
    try:
        device = _default_loopback_device(pyaudio_module, audio)
        chunk = 1024
        sample_format = pyaudio_module.paInt16
        stream = audio.open(
            format=sample_format,
            channels=device.channels,
            rate=device.sample_rate,
            input=True,
            input_device_index=device.index,
            frames_per_buffer=chunk,
        )
        with get_resource_manager(settings).lease(
            ResourceKind.REALTIME_AUDIO,
            owner=f"playback_capture:{output_path.name}",
            cancel_requested=cancel_requested,
        ):
            with wave.open(str(temporary_path), "wb") as target:
                target.setnchannels(device.channels)
                target.setsampwidth(
                    pyaudio_module.get_sample_size(sample_format)
                )
                target.setframerate(device.sample_rate)
                next_report = 0.0
                while True:
                    raise_if_cancelled(cancel_requested)
                    elapsed = time.monotonic() - started
                    if elapsed >= requested:
                        break
                    if stop_requested and stop_requested():
                        stopped_early = True
                        break
                    payload = stream.read(
                        chunk,
                        exception_on_overflow=False,
                    )
                    target.writeframes(payload)
                    level, squares, count = _pcm16_level(payload)
                    peak_level = max(peak_level, level)
                    sum_squares += squares
                    sample_count += count
                    if progress_callback and elapsed >= next_report:
                        phase = min(100.0, elapsed * 100 / requested)
                        overall = 25 + int(phase * 0.3)
                        progress_callback(
                            "本地播放采集",
                            overall,
                            PlaybackCaptureProgressMessage(
                                (
                                    f"正在录制系统播放音频："
                                    f"{elapsed:.0f}/{requested:.0f} 秒，"
                                    f"当前音量 {level * 100:.1f}%"
                                ),
                                state="recording",
                                phase_percent=phase,
                                elapsed_seconds=elapsed,
                                duration_seconds=requested,
                                level=level,
                                device_name=device.name,
                            ),
                        )
                        next_report = elapsed + 1.0
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        if stream is not None:
            try:
                stream.stop_stream()
            finally:
                stream.close()
        audio.terminate()

    elapsed = max(0.0, time.monotonic() - started)
    try:
        raise_if_cancelled(cancel_requested)
    except JobCancelledError:
        temporary_path.unlink(missing_ok=True)
        raise
    if not temporary_path.exists() or temporary_path.stat().st_size <= 44:
        temporary_path.unlink(missing_ok=True)
        raise RuntimeError("系统音频采集没有产生可用的 WAV 数据。")
    os.replace(temporary_path, output_path)
    rms_level = (
        math.sqrt(sum_squares / sample_count) / 32768.0
        if sample_count
        else 0.0
    )
    likely_silent = (
        peak_level < settings.playback_capture_silence_threshold
    )
    if progress_callback:
        warning = "；检测到音频接近静音，请确认网页确实在播放" if likely_silent else ""
        progress_callback(
            "本地播放采集",
            55,
            PlaybackCaptureProgressMessage(
                f"系统音频录制完成，共 {elapsed:.1f} 秒{warning}。",
                state="finished",
                phase_percent=100,
                elapsed_seconds=elapsed,
                duration_seconds=requested,
                level=peak_level,
                device_name=device.name,
            ),
        )
    return PlaybackCaptureResult(
        audio_path=output_path,
        duration_seconds=elapsed,
        device=device,
        peak_level=peak_level,
        rms_level=rms_level,
        likely_silent=likely_silent,
        stopped_early=stopped_early,
    )


def _default_loopback_device(
    pyaudio_module: Any,
    audio: Any | None = None,
) -> SystemAudioDevice:
    owns_audio = audio is None
    audio = audio or pyaudio_module.PyAudio()
    try:
        info = audio.get_default_wasapi_loopback()
        channels = max(1, int(info.get("maxInputChannels") or 0))
        sample_rate = max(8_000, int(info.get("defaultSampleRate") or 48_000))
        return SystemAudioDevice(
            index=int(info["index"]),
            name=str(info.get("name") or "Default WASAPI loopback"),
            channels=channels,
            sample_rate=sample_rate,
        )
    finally:
        if owns_audio:
            audio.terminate()


def _pcm16_level(payload: bytes) -> tuple[float, float, int]:
    samples = array("h")
    samples.frombytes(payload)
    if not samples:
        return 0.0, 0.0, 0
    peak = max(abs(sample) for sample in samples) / 32768.0
    squares = sum(float(sample) * float(sample) for sample in samples)
    return peak, squares, len(samples)
