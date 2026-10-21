from __future__ import annotations

import logging
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Callable

from config import SETTINGS, Settings
from infrastructure.cancellation import (
    JobCancelledError,
    raise_if_cancelled,
)
from infrastructure.resources import ResourceKind, get_resource_manager
from processor.ffmpeg import extract_audio

logger = logging.getLogger(__name__)


def analyze_audio_rhythm(
    video_path: Path | None,
    video_id: str,
    settings: Settings = SETTINGS,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    raise_if_cancelled(cancel_requested)
    if not settings.audio_rhythm_enabled:
        return {"status": "skipped", "reason": "audio rhythm analysis disabled"}
    if not video_path or not video_path.exists():
        return {"status": "skipped", "reason": "video file unavailable"}

    try:
        import numpy as np
        import soundfile as sf
    except ImportError as exc:
        return {"status": "unavailable", "reason": f"missing dependency: {exc.name}"}

    audio_path = settings.transcript_cache_dir / video_id / "audio.wav"
    try:
        with get_resource_manager(settings).lease(
            ResourceKind.CPU_HEAVY,
            owner=f"audio_rhythm:{video_id}",
            cancel_requested=cancel_requested,
        ):
            audio_path = extract_audio(
                video_path,
                audio_path,
                settings,
                cancel_requested=cancel_requested,
            )
            raise_if_cancelled(cancel_requested)
            signal, sample_rate, loader = _load_audio(
                audio_path,
                settings,
                np,
                sf,
            )
            if signal.size == 0:
                return {"status": "failed", "reason": "decoded audio is empty"}

            raise_if_cancelled(cancel_requested)
            metrics = _lightweight_features(signal, sample_rate, np)
            raise_if_cancelled(cancel_requested)
            duration = float(signal.size / sample_rate)
            return {
                "status": "ok",
                "engine": f"librosa-compatible+numpy ({loader})",
                "librosa_version": _package_version("librosa"),
                "audio_path": str(audio_path),
                "sample_rate": int(sample_rate),
                "analyzed_duration": round(duration, 3),
                "truncated": bool(
                    settings.audio_rhythm_max_seconds > 0
                    and duration >= settings.audio_rhythm_max_seconds - 0.1
                ),
                **metrics,
            }
    except JobCancelledError:
        raise
    except Exception as exc:  # pragma: no cover - codec/backend dependent
        logger.warning("librosa analysis failed for %s: %s", video_path, exc)
        return {"status": "failed", "reason": str(exc)}


def _load_audio(
    audio_path: Path,
    settings: Settings,
    np: Any,
    soundfile_module: Any,
) -> tuple[Any, int, str]:
    backend = settings.audio_rhythm_backend.strip().lower()
    use_native_librosa = backend == "librosa" or (
        backend == "auto" and sys.version_info < (3, 13)
    )
    if use_native_librosa:
        import librosa

        signal, sample_rate = librosa.load(
            str(audio_path),
            sr=settings.audio_rhythm_sample_rate,
            mono=True,
            duration=max(1, settings.audio_rhythm_max_seconds),
        )
        return signal, int(sample_rate), "librosa"

    with soundfile_module.SoundFile(str(audio_path)) as stream:
        native_rate = int(stream.samplerate)
        maximum_frames = max(1, settings.audio_rhythm_max_seconds) * native_rate
        signal = stream.read(
            frames=maximum_frames,
            dtype="float32",
            always_2d=False,
        )
    if getattr(signal, "ndim", 1) > 1:
        signal = np.mean(signal, axis=1)
    target_rate = settings.audio_rhythm_sample_rate
    if target_rate > 0 and native_rate != target_rate and signal.size:
        target_size = max(1, int(round(signal.size * target_rate / native_rate)))
        source_positions = np.linspace(0.0, 1.0, signal.size, endpoint=False)
        target_positions = np.linspace(0.0, 1.0, target_size, endpoint=False)
        signal = np.interp(target_positions, source_positions, signal).astype(
            np.float32
        )
        native_rate = target_rate
    return signal, native_rate, "soundfile"


def _package_version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def _lightweight_features(signal: Any, sample_rate: int, np: Any) -> dict[str, Any]:
    """Compute speech-oriented features without librosa's first-run JIT cost."""
    frame_length = 1024
    hop_length = 512
    if signal.size < frame_length:
        signal = np.pad(signal, (0, frame_length - signal.size))

    starts = np.arange(0, signal.size - frame_length + 1, hop_length)
    power = signal.astype(np.float64) ** 2
    power_sum = np.concatenate(([0.0], np.cumsum(power)))
    rms = np.sqrt(
        np.maximum(
            (
                power_sum[starts + frame_length]
                - power_sum[starts]
            )
            / frame_length,
            1e-12,
        )
    )
    peak_rms = max(float(np.max(rms)), 1e-10)
    rms_db = 20.0 * np.log10(np.maximum(rms, 1e-10) / peak_rms)

    crossings = (signal[1:] * signal[:-1] < 0).astype(np.float64)
    crossing_sum = np.concatenate(([0.0], np.cumsum(crossings)))
    crossing_end = np.minimum(starts + frame_length - 1, crossings.size)
    zero_crossing = (
        crossing_sum[crossing_end] - crossing_sum[starts]
    ) / max(frame_length - 1, 1)

    onset_envelope = np.maximum(np.diff(rms, prepend=rms[0]), 0.0)
    onset_threshold = float(
        np.median(onset_envelope) + 1.5 * np.std(onset_envelope)
    )
    onset_mask = onset_envelope > max(onset_threshold, 1e-8)
    if onset_mask.size >= 3:
        onset_mask[1:-1] &= (
            (onset_envelope[1:-1] >= onset_envelope[:-2])
            & (onset_envelope[1:-1] >= onset_envelope[2:])
        )
    onset_count = int(np.count_nonzero(onset_mask))
    tempo_bpm = _estimate_tempo(
        onset_envelope,
        sample_rate,
        hop_length,
        np,
    )

    sampled_starts = starts[
        :: max(1, int(np.ceil(max(len(starts), 1) / 2000)))
    ]
    indices = sampled_starts[:, None] + np.arange(frame_length)[None, :]
    frames = signal[indices] * np.hanning(frame_length)[None, :]
    spectrum = np.abs(np.fft.rfft(frames, axis=1))
    frequencies = np.fft.rfftfreq(frame_length, 1.0 / sample_rate)
    centroid = np.sum(spectrum * frequencies[None, :], axis=1) / np.maximum(
        np.sum(spectrum, axis=1),
        1e-10,
    )

    duration = float(signal.size / sample_rate)
    return {
        "tempo_bpm": round(tempo_bpm, 3),
        "beat_count": int(round(duration * tempo_bpm / 60)) if tempo_bpm else 0,
        "onset_count": onset_count,
        "onsets_per_minute": round(onset_count * 60 / max(duration, 1), 3),
        "mean_rms": round(float(np.mean(rms)), 6),
        "rms_variation": round(float(np.std(rms)), 6),
        "dynamic_range_db": round(
            float(np.percentile(rms_db, 95) - np.percentile(rms_db, 10)),
            3,
        ),
        "silence_ratio": round(float(np.mean(rms_db < -40.0)), 6),
        "spectral_centroid_hz": round(float(np.mean(centroid)), 3),
        "zero_crossing_rate": round(float(np.mean(zero_crossing)), 6),
    }


def _estimate_tempo(
    onset_envelope: Any,
    sample_rate: int,
    hop_length: int,
    np: Any,
) -> float:
    if onset_envelope.size < 4 or not np.any(onset_envelope):
        return 0.0
    centered = onset_envelope - np.mean(onset_envelope)
    fft_size = 1 << (2 * centered.size - 1).bit_length()
    spectrum = np.fft.rfft(centered, n=fft_size)
    autocorrelation = np.fft.irfft(
        spectrum * np.conjugate(spectrum),
        n=fft_size,
    )[: centered.size]
    minimum_lag = max(1, int(60 * sample_rate / (hop_length * 240)))
    maximum_lag = min(
        centered.size - 1,
        int(60 * sample_rate / (hop_length * 40)),
    )
    if maximum_lag <= minimum_lag:
        return 0.0
    lag = minimum_lag + int(
        np.argmax(autocorrelation[minimum_lag : maximum_lag + 1])
    )
    return float(60 * sample_rate / (hop_length * lag))
