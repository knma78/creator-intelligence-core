from __future__ import annotations

import gc
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

from config import SETTINGS, Settings
from models import Transcript
from processor.subtitle import write_transcript_files

logger = logging.getLogger(__name__)

_CUDA_DLLS = (
    "cublas64_12.dll",
    "cublasLt64_12.dll",
    "cudnn64_9.dll",
    "cudnn_ops64_9.dll",
)
_MODEL_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_TRANSCRIPTION_LOCK = threading.RLock()
_SESSION_LOCK = threading.Lock()
_SESSION_COUNT = 0
_DLL_DIRECTORY_HANDLES: list[Any] = []
_CONFIGURED_DLL_DIRECTORIES: set[str] = set()
_LANGUAGE_FROM_SETTINGS = object()
_PROGRESS_HEARTBEAT_SECONDS = 1.0


@dataclass(frozen=True)
class WhisperExecution:
    requested_device: str
    device: str
    compute_type: str
    batch_size: int
    cpu_threads: int
    num_workers: int
    reason: str
    gpu_name: str = ""
    gpu_total_memory_mb: int = 0
    gpu_free_memory_mb: int = 0
    gpu_utilization: int = 0


class WhisperProgressMessage(str):
    def __new__(
        cls,
        text: str,
        *,
        phase_percent: float | None,
        state: str,
        execution: WhisperExecution | None = None,
        detected_language: str = "",
        processed_seconds: float | None = None,
        duration_seconds: float | None = None,
        elapsed_seconds: float | None = None,
        heartbeat: bool = False,
    ):
        value = str.__new__(cls, text)
        value.progress_meta = {
            "type": "whisper",
            "state": state,
            "phase_percent": (
                round(max(0.0, min(100.0, phase_percent)), 1)
                if phase_percent is not None
                else None
            ),
            "device": execution.device if execution else "unknown",
            "requested_device": (
                execution.requested_device if execution else "unknown"
            ),
            "compute_type": execution.compute_type if execution else "",
            "batch_size": execution.batch_size if execution else 1,
            "reason": execution.reason if execution else "",
            "gpu_name": execution.gpu_name if execution else "",
            "detected_language": detected_language,
            "processed_seconds": processed_seconds,
            "duration_seconds": duration_seconds,
            "elapsed_seconds": elapsed_seconds,
            "heartbeat": heartbeat,
        }
        return value


def transcribe_audio(
    audio_path: Path,
    output_dir: Path,
    video_id: str,
    settings: Settings = SETTINGS,
    progress_callback: Callable[[str, int, str], None] | None = None,
    language: str | None | object = _LANGUAGE_FROM_SETTINGS,
) -> Transcript:
    selected_language = (
        settings.whisper_language
        if language is _LANGUAGE_FROM_SETTINGS
        else language
    )
    engine = settings.whisper_engine.strip().lower()
    if engine in {"faster-whisper", "faster_whisper"}:
        return _transcribe_with_faster_whisper(
            audio_path,
            output_dir,
            video_id,
            settings,
            progress_callback,
            selected_language,
        )
    if engine in {"openai-whisper", "whisper"}:
        return _transcribe_with_openai_whisper(
            audio_path,
            output_dir,
            video_id,
            settings,
            progress_callback,
            selected_language,
        )
    raise ValueError(f"Unsupported WHISPER_ENGINE: {settings.whisper_engine}")


@contextmanager
def whisper_model_session(settings: Settings = SETTINGS) -> Iterator[None]:
    global _SESSION_COUNT
    with _SESSION_LOCK:
        _SESSION_COUNT += 1
    try:
        yield
    finally:
        should_release = False
        with _SESSION_LOCK:
            _SESSION_COUNT = max(0, _SESSION_COUNT - 1)
            should_release = _SESSION_COUNT == 0 and settings.whisper_release_after_job
        if should_release:
            release_whisper_models()


def release_whisper_models() -> None:
    with _TRANSCRIPTION_LOCK:
        if not _MODEL_CACHE:
            return
        count = len(_MODEL_CACHE)
        _MODEL_CACHE.clear()
        gc.collect()
        logger.info("Released %s cached Whisper model runtime(s)", count)


def get_whisper_runtime_status(settings: Settings = SETTINGS) -> dict[str, Any]:
    execution, diagnostics = _resolve_execution(settings)
    return {
        **asdict(execution),
        "cuda_ready": diagnostics["cuda_ready"],
        "missing_cuda_dlls": diagnostics["missing_cuda_dlls"],
        "cuda_path": diagnostics["cuda_path"],
        "gpu_model_cached": diagnostics["gpu_model_cached"],
        "fallback_enabled": settings.whisper_gpu_fallback,
        "release_after_job": settings.whisper_release_after_job,
        "default_language": settings.whisper_language or "auto",
        "youtube_language": settings.youtube_whisper_language or "auto",
        "douyin_language": settings.douyin_whisper_language or "auto",
    }


def _transcribe_with_faster_whisper(
    audio_path: Path,
    output_dir: Path,
    video_id: str,
    settings: Settings,
    progress_callback: Callable[[str, int, str], None] | None = None,
    language: str | None = None,
) -> Transcript:
    with _TRANSCRIPTION_LOCK:
        execution, _diagnostics = _resolve_execution(settings)
        active_execution = execution
        _report_execution(execution, settings, progress_callback)
        try:
            segments = _run_faster_whisper(
                audio_path,
                settings,
                execution,
                progress_callback,
                language,
            )
        except Exception as exc:
            if execution.device != "cuda" or not settings.whisper_gpu_fallback:
                raise
            logger.warning("GPU Whisper failed; retrying on CPU: %s", exc)
            _drop_cached_execution(settings, execution)
            fallback = _cpu_execution(settings, f"GPU运行失败，已回退CPU：{exc}")
            active_execution = fallback
            if progress_callback:
                progress_callback(
                    "Whisper回退",
                    57,
                    WhisperProgressMessage(
                        "GPU识别不可用或显存不足，正在自动切换到CPU模式。",
                        phase_percent=0,
                        state="fallback",
                        execution=fallback,
                    ),
                )
            segments = _run_faster_whisper(
                audio_path,
                settings,
                fallback,
                progress_callback,
                language,
            )

    if progress_callback:
        progress_callback(
            "字幕写入",
            80,
            WhisperProgressMessage(
                "Whisper 识别完成，正在写入字幕文件。",
                phase_percent=100,
                state="writing",
                execution=active_execution,
            ),
        )
    return write_transcript_files(segments, output_dir, video_id, "whisper")


def _run_faster_whisper(
    audio_path: Path,
    settings: Settings,
    execution: WhisperExecution,
    progress_callback: Callable[[str, int, str], None] | None,
    language: str | None,
):
    runtime = _get_or_load_runtime(settings, execution)
    batch_sizes = _batch_candidates(execution.batch_size)
    last_error: Exception | None = None
    for batch_size in batch_sizes:
        try:
            return _transcribe_attempt(
                audio_path,
                settings,
                execution,
                runtime,
                batch_size,
                progress_callback,
                language,
            )
        except Exception as exc:
            last_error = exc
            if execution.device != "cuda" or batch_size <= 1 or not _is_memory_error(exc):
                raise
            next_batch = max(1, batch_size // 2)
            logger.warning(
                "Whisper GPU batch %s failed due to memory pressure; retrying with batch %s: %s",
                batch_size,
                next_batch,
                exc,
            )
            if progress_callback:
                progress_callback(
                    "Whisper显存保护",
                    57,
                    WhisperProgressMessage(
                        f"显存不足，批量大小从 {batch_size} 自动降低到 {next_batch}。",
                        phase_percent=None,
                        state="retrying",
                        execution=execution,
                    ),
                )
    if last_error:
        raise last_error
    raise RuntimeError("Whisper did not produce a transcription attempt")


def _transcribe_attempt(
    audio_path: Path,
    settings: Settings,
    execution: WhisperExecution,
    runtime: dict[str, Any],
    batch_size: int,
    progress_callback: Callable[[str, int, str], None] | None,
    language: str | None,
):
    transcriber = runtime["batched"] if batch_size > 1 else runtime["model"]
    kwargs: dict[str, Any] = {
        "beam_size": max(1, settings.whisper_beam_size),
        "vad_filter": True,
        "vad_parameters": {
            "min_silence_duration_ms": max(100, settings.whisper_vad_min_silence_ms),
        },
    }
    if language:
        kwargs["language"] = language
    if batch_size > 1:
        kwargs["batch_size"] = batch_size

    segments_iter, info = transcriber.transcribe(str(audio_path), **kwargs)
    detected_language = str(getattr(info, "language", "") or language or "auto")
    duration = float(getattr(info, "duration", 0) or 0)
    logger.info("Whisper language: requested=%s detected=%s", language or "auto", detected_language)
    segments = []
    last_reported = 56
    with _whisper_progress_heartbeat(
        progress_callback,
        execution,
        detected_language,
        duration,
    ) as report_progress:
        for segment in segments_iter:
            end = float(segment.end)
            segments.append(_segment_from_values(float(segment.start), end, segment.text))
            if duration > 0:
                percent = min(78, 56 + int((end / duration) * 22))
                if percent >= last_reported + 2:
                    last_reported = percent
                    report_progress(end)
    return segments


@contextmanager
def _whisper_progress_heartbeat(
    progress_callback: Callable[[str, int, str], None] | None,
    execution: WhisperExecution,
    detected_language: str,
    duration_seconds: float,
) -> Iterator[Callable[[float], None]]:
    if not progress_callback:
        yield lambda _processed_seconds: None
        return

    stop_event = threading.Event()
    state_lock = threading.Lock()
    started_at = time.monotonic()
    state = {"processed_seconds": 0.0}

    def emit(*, heartbeat: bool) -> None:
        with state_lock:
            processed = float(state["processed_seconds"])
        elapsed = max(0.0, time.monotonic() - started_at)
        phase_percent = (
            min(100.0, (processed / duration_seconds) * 100)
            if duration_seconds > 0 and processed > 0
            else 0.0
        )
        overall_percent = min(78, 56 + int((phase_percent / 100) * 22))
        if processed > 0 and duration_seconds > 0:
            text = (
                f"Whisper 识别中：{processed:.0f}/{duration_seconds:.0f} 秒"
            )
        else:
            text = f"Whisper 正在识别音频，已运行 {elapsed:.0f} 秒。"
        progress_callback(
            "Whisper识别",
            max(57, overall_percent),
            WhisperProgressMessage(
                text,
                phase_percent=phase_percent if processed > 0 else None,
                state="transcribing",
                execution=execution,
                detected_language=detected_language,
                processed_seconds=processed if processed > 0 else None,
                duration_seconds=duration_seconds if duration_seconds > 0 else None,
                elapsed_seconds=elapsed,
                heartbeat=heartbeat,
            ),
        )

    def heartbeat_loop() -> None:
        while not stop_event.wait(_PROGRESS_HEARTBEAT_SECONDS):
            try:
                emit(heartbeat=True)
            except Exception:
                logger.exception("Whisper progress heartbeat callback failed")

    def report(processed_seconds: float) -> None:
        with state_lock:
            state["processed_seconds"] = max(
                float(state["processed_seconds"]),
                processed_seconds,
            )
        emit(heartbeat=False)

    emit(heartbeat=False)
    thread = threading.Thread(
        target=heartbeat_loop,
        name="whisper-progress-heartbeat",
        daemon=True,
    )
    thread.start()
    try:
        yield report
    finally:
        stop_event.set()
        thread.join(timeout=max(0.2, _PROGRESS_HEARTBEAT_SECONDS * 2))


def _get_or_load_runtime(
    settings: Settings,
    execution: WhisperExecution,
) -> dict[str, Any]:
    key = _runtime_key(settings, execution)
    cached = _MODEL_CACHE.get(key)
    if cached:
        return cached

    try:
        from faster_whisper import BatchedInferencePipeline, WhisperModel
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: install faster-whisper or set WHISPER_ENGINE=openai-whisper."
        ) from exc

    logger.info(
        "Loading faster-whisper model=%s device=%s compute=%s batch=%s",
        settings.whisper_model,
        execution.device,
        execution.compute_type,
        execution.batch_size,
    )
    model = WhisperModel(
        settings.whisper_model,
        device=execution.device,
        compute_type=execution.compute_type,
        cpu_threads=execution.cpu_threads,
        num_workers=execution.num_workers,
    )
    runtime = {
        "model": model,
        "batched": BatchedInferencePipeline(model=model),
    }
    _MODEL_CACHE[key] = runtime
    return runtime


def _resolve_execution(settings: Settings) -> tuple[WhisperExecution, dict[str, Any]]:
    cuda_paths = _configure_cuda_paths(settings)
    gpu = _query_nvidia_gpu()
    missing_dlls = [name for name in _CUDA_DLLS if not _find_cuda_dll(name, cuda_paths)]
    cuda_ready = bool(gpu) and not missing_dlls
    requested = settings.whisper_device.strip().lower() or "auto"
    gpu_model_cached = _has_cached_gpu_model(settings)
    reason = ""
    use_cuda = requested in {"auto", "cuda"}

    if requested == "cpu":
        use_cuda = False
        reason = "配置指定使用CPU"
    elif not gpu:
        use_cuda = False
        reason = "未检测到可用NVIDIA GPU"
    elif missing_dlls:
        use_cuda = False
        reason = "缺少CUDA 12/cuDNN 9运行库：" + "、".join(missing_dlls)
    elif not gpu_model_cached and int(gpu["free_memory_mb"]) < settings.whisper_min_free_vram_mb:
        use_cuda = False
        reason = (
            f"空闲显存 {gpu['free_memory_mb']}MB 低于保护线 "
            f"{settings.whisper_min_free_vram_mb}MB"
        )
    elif not gpu_model_cached and int(gpu["utilization"]) > settings.whisper_gpu_max_utilization:
        use_cuda = False
        reason = (
            f"GPU占用 {gpu['utilization']}% 高于保护线 "
            f"{settings.whisper_gpu_max_utilization}%"
        )
    else:
        reason = "GPU运行库与资源检查通过"

    force_cuda = requested == "cuda" and not settings.whisper_gpu_fallback
    if force_cuda and not use_cuda:
        use_cuda = True
        reason = "配置强制使用CUDA，自动回退已关闭"

    device = "cuda" if use_cuda and (cuda_ready or force_cuda) else "cpu"
    compute_type = _compute_type(settings.whisper_compute_type, device)
    batch_size = max(1, settings.whisper_batch_size) if device == "cuda" else 1
    execution = WhisperExecution(
        requested_device=requested,
        device=device,
        compute_type=compute_type,
        batch_size=batch_size,
        cpu_threads=_cpu_threads(settings),
        num_workers=max(1, settings.whisper_num_workers),
        reason=reason,
        gpu_name=str(gpu.get("name") or "") if gpu else "",
        gpu_total_memory_mb=int(gpu.get("total_memory_mb") or 0) if gpu else 0,
        gpu_free_memory_mb=int(gpu.get("free_memory_mb") or 0) if gpu else 0,
        gpu_utilization=int(gpu.get("utilization") or 0) if gpu else 0,
    )
    diagnostics = {
        "cuda_ready": cuda_ready,
        "missing_cuda_dlls": missing_dlls,
        "cuda_path": os.pathsep.join(str(path) for path in cuda_paths),
        "gpu_model_cached": gpu_model_cached,
    }
    return execution, diagnostics


def _cpu_execution(settings: Settings, reason: str) -> WhisperExecution:
    gpu = _query_nvidia_gpu() or {}
    return WhisperExecution(
        requested_device=settings.whisper_device,
        device="cpu",
        compute_type="int8",
        batch_size=1,
        cpu_threads=_cpu_threads(settings),
        num_workers=max(1, settings.whisper_num_workers),
        reason=reason,
        gpu_name=str(gpu.get("name") or ""),
        gpu_total_memory_mb=int(gpu.get("total_memory_mb") or 0),
        gpu_free_memory_mb=int(gpu.get("free_memory_mb") or 0),
        gpu_utilization=int(gpu.get("utilization") or 0),
    )


def _configure_cuda_paths(settings: Settings) -> list[Path]:
    candidates: list[Path] = []
    if settings.whisper_cuda_path:
        candidates.extend(
            Path(item).expanduser()
            for item in settings.whisper_cuda_path.split(os.pathsep)
            if item.strip()
        )
    candidates.append(settings.base_dir / "runtime" / "nvidia")

    for module_name in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, ModuleNotFoundError, ValueError):
            spec = None
        if not spec or not spec.submodule_search_locations:
            continue
        for location in spec.submodule_search_locations:
            candidates.append(Path(location) / "bin")

    configured: list[Path] = []
    for candidate in candidates:
        if not candidate.exists() or not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        key = str(resolved).lower()
        if key not in _CONFIGURED_DLL_DIRECTORIES:
            os.environ["PATH"] = str(resolved) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(resolved)))
            _CONFIGURED_DLL_DIRECTORIES.add(key)
        if resolved not in configured:
            configured.append(resolved)
    return configured


def _find_cuda_dll(name: str, cuda_paths: list[Path]) -> Path | None:
    for cuda_path in cuda_paths:
        direct = cuda_path / name
        if direct.exists():
            return direct
    found = shutil.which(name)
    return Path(found) if found else None


def _query_nvidia_gpu() -> dict[str, Any] | None:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None
    command = [
        executable,
        "--query-gpu=name,memory.total,memory.free,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=True,
            creationflags=creation_flags,
        )
        line = next((item.strip() for item in result.stdout.splitlines() if item.strip()), "")
        parts = [item.strip() for item in line.split(",")]
        if len(parts) < 4:
            return None
        return {
            "name": parts[0],
            "total_memory_mb": int(parts[1]),
            "free_memory_mb": int(parts[2]),
            "utilization": int(parts[3]),
        }
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _compute_type(configured: str, device: str) -> str:
    value = configured.strip().lower()
    if not value or value == "auto":
        return "float16" if device == "cuda" else "int8"
    if device == "cpu" and value in {"float16", "int8_float16"}:
        return "int8"
    return value


def _cpu_threads(settings: Settings) -> int:
    if settings.whisper_cpu_threads > 0:
        return settings.whisper_cpu_threads
    logical = os.cpu_count() or 4
    return max(1, min(8, logical // 2))


def _runtime_key(settings: Settings, execution: WhisperExecution) -> tuple[Any, ...]:
    return (
        settings.whisper_model,
        execution.device,
        execution.compute_type,
        execution.cpu_threads,
        execution.num_workers,
    )


def _has_cached_gpu_model(settings: Settings) -> bool:
    return any(
        key[0] == settings.whisper_model and key[1] == "cuda"
        for key in _MODEL_CACHE
    )


def _drop_cached_execution(settings: Settings, execution: WhisperExecution) -> None:
    _MODEL_CACHE.pop(_runtime_key(settings, execution), None)
    gc.collect()


def _batch_candidates(configured: int) -> list[int]:
    values = []
    current = max(1, configured)
    while current >= 1:
        if current not in values:
            values.append(current)
        if current == 1:
            break
        current = max(1, current // 2)
    return values


def _is_memory_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "out of memory",
            "failed to allocate",
            "cuda_error_out_of_memory",
            "cublas_status_alloc_failed",
            "not enough memory",
        )
    )


def _report_execution(
    execution: WhisperExecution,
    settings: Settings,
    progress_callback: Callable[[str, int, str], None] | None,
) -> None:
    logger.info(
        "Transcribing with faster-whisper model=%s device=%s compute=%s batch=%s reason=%s",
        settings.whisper_model,
        execution.device,
        execution.compute_type,
        execution.batch_size,
        execution.reason,
    )
    if not progress_callback:
        return
    if execution.device == "cuda":
        message = (
            f"正在使用 {execution.gpu_name or 'NVIDIA GPU'} 加载 {settings.whisper_model} 模型；"
            f"精度 {execution.compute_type}，批量 {execution.batch_size}。"
        )
    else:
        message = (
            f"正在使用CPU加载 {settings.whisper_model} 模型；"
            f"{execution.reason}。"
        )
    progress_callback(
        "Whisper识别",
        56,
        WhisperProgressMessage(
            message,
            phase_percent=None,
            state="loading",
            execution=execution,
        ),
    )


def _transcribe_with_openai_whisper(
    audio_path: Path,
    output_dir: Path,
    video_id: str,
    settings: Settings,
    progress_callback: Callable[[str, int, str], None] | None = None,
    language: str | None = None,
) -> Transcript:
    try:
        import whisper
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: install openai-whisper or set WHISPER_ENGINE=faster-whisper."
        ) from exc

    logger.info("Transcribing with openai-whisper model=%s", settings.whisper_model)
    if progress_callback:
        progress_callback(
            "Whisper识别",
            56,
            WhisperProgressMessage(
                f"正在加载 openai-whisper 模型：{settings.whisper_model}",
                phase_percent=None,
                state="loading",
            ),
        )
    model = whisper.load_model(settings.whisper_model)
    if progress_callback:
        progress_callback(
            "Whisper识别",
            60,
            WhisperProgressMessage(
                "模型加载完成，正在识别音频。",
                phase_percent=None,
                state="transcribing",
            ),
        )
    transcribe_options: dict[str, Any] = {}
    if language:
        transcribe_options["language"] = language
    result = model.transcribe(str(audio_path), **transcribe_options)
    segments = [
        _segment_from_values(float(item["start"]), float(item["end"]), item["text"])
        for item in result.get("segments", [])
    ]
    if progress_callback:
        progress_callback(
            "字幕写入",
            80,
            WhisperProgressMessage(
                "Whisper 识别完成，正在写入字幕文件。",
                phase_percent=100,
                state="writing",
            ),
        )
    return write_transcript_files(segments, output_dir, video_id, "whisper")


def _segment_from_values(start: float, end: float, text: str):
    from models import TranscriptSegment

    return TranscriptSegment(start=start, end=end, text=text.strip())


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Transcribe an audio file with Whisper.")
    parser.add_argument("audio", nargs="?")
    parser.add_argument("--video-id", default="local")
    parser.add_argument("--output-dir", default="cache/transcripts/local")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.status:
        print(json.dumps(get_whisper_runtime_status(), ensure_ascii=False, indent=2))
    else:
        if not args.audio:
            parser.error("audio is required unless --status is used")
        with whisper_model_session():
            transcript = transcribe_audio(
                Path(args.audio),
                Path(args.output_dir),
                args.video_id,
            )
        print(json.dumps(transcript.to_dict(), ensure_ascii=False, indent=2))
