from __future__ import annotations

import os
import json
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from production.assets import cover_catalog
from production.ffmpeg_renderer import inspect_ffmpeg_runtime
from production.qa import probe_media
from production.script_schema import TEMPLATE_NAME


def script_video_runtime_status(
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    edge = Path(settings.edge_tts_path or "")
    edge_status = _command_status(
        (str(edge), "--version")
        if settings.edge_tts_path and edge.is_file()
        else (),
    )
    edge_available = edge_status["available"]
    sapi = _windows_sapi_status(settings.ffprobe_path)
    ffmpeg = inspect_ffmpeg_runtime(
        settings.video_ffmpeg_path,
        validate_nvenc=False,
    )
    ffprobe = _command_status((settings.ffprobe_path, "-version"))
    ffmpeg_available = bool(ffmpeg.get("available"))
    ffprobe_available = ffprobe["available"]
    covers = cover_catalog(settings, load_analysis=False)
    capcut = capcut_runtime_status()
    return {
        "available": bool(
            (edge_available or sapi["available"])
            and ffmpeg_available
            and ffprobe_available
            and capcut["available"]
        ),
        "tts": {
            "engine": "edge-tts" if edge_available else "windows-sapi-com",
            "available": edge_available or sapi["available"],
            "edge_available": edge_available,
            "path": str(edge) if settings.edge_tts_path else None,
            "edge_reason": edge_status.get("reason"),
            "fallback": "windows-sapi-com",
            "fallback_available": sapi["available"],
            "fallback_voice": sapi.get("voice"),
            "fallback_reason": sapi.get("reason"),
        },
        "ffmpeg": {**ffmpeg},
        "capcut": capcut,
        "ffprobe": {
            "available": ffprobe_available,
            "path": settings.ffprobe_path,
            "reason": ffprobe.get("reason"),
        },
        "visuals": {
            "engine": "distilled-cover-resolver",
            "cover_count": len(covers),
            "fallback": "local-gradient",
            "motion_clips": False,
            "mode_label": "cover-based narrated slideshow",
        },
        "template": TEMPLATE_NAME,
        "agent_required": False,
    }


def capcut_runtime_status() -> dict[str, Any]:
    """Report whether the local CapCut draft builder can accept a new project."""
    root = Path(__file__).resolve().parents[1]
    python = root / ".venv-capcut" / "Scripts" / "python.exe"
    entry = root / "tools" / "capcut_mcp.py"
    if not python.is_file() or not entry.is_file():
        return {
            "available": False,
            "reason": "CapCut's local Python environment or adapter is missing.",
            "draft_directory": None,
            "running": False,
        }
    try:
        completed = subprocess.run(
            [str(python), str(entry), "health"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=12,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "available": False,
            "reason": str(exc),
            "draft_directory": None,
            "running": False,
        }
    try:
        health = json.loads(completed.stdout) if completed.returncode == 0 else {}
    except json.JSONDecodeError:
        health = {}
    running = bool(health.get("capcutRunning"))
    draft_directory = health.get("draftDir")
    directory_ready = bool(
        health.get("draftDirExists") and draft_directory
    )
    available = bool(completed.returncode == 0 and directory_ready and not running)
    if running:
        reason = "Close CapCut normally before generating the next draft."
    elif not directory_ready:
        reason = "The configured CapCut draft directory is unavailable."
    elif completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        reason = detail[-500:] or "CapCut health check failed."
    else:
        reason = None
    return {
        "available": available,
        "reason": reason,
        "draft_directory": draft_directory,
        "running": running,
        "version": health.get("version"),
    }


@lru_cache(maxsize=12)
def _command_status(
    command: tuple[str, ...],
    timeout_seconds: float = 8,
) -> dict[str, Any]:
    if not command or not command[0]:
        return {"available": False, "reason": "Executable is not configured."}
    try:
        result = subprocess.run(
            list(command),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "reason": str(exc)}
    output = (result.stdout or result.stderr or "").strip()
    return {
        "available": result.returncode == 0,
        "version": output.splitlines()[0][:240] if output else None,
        "reason": (
            None
            if result.returncode == 0
            else _process_error_summary(output, "Command failed.")
        ),
    }


@lru_cache(maxsize=4)
def _windows_sapi_status(ffprobe_path: str) -> dict[str, Any]:
    if os.name != "nt":
        return {
            "available": False,
            "voice": None,
            "reason": "Windows SAPI is only available on Windows.",
        }
    with tempfile.TemporaryDirectory(prefix="contentresearch-sapi-") as directory:
        wav_path = Path(directory) / "probe.wav"
        escaped_path = str(wav_path).replace("'", "''")
        powershell = (
            "$ErrorActionPreference = 'Stop'; $s = $null; $stream = $null; "
            "try { $s = New-Object -ComObject SAPI.SpVoice; "
            "$tokens = $s.GetVoices(); $selected = $null; "
            "for ($i = 0; $i -lt $tokens.Count; $i++) { "
            "$candidate = $tokens.Item($i); $language = ''; "
            "try { $language = $candidate.GetAttribute('Language') } catch {}; "
            "if ($language -match '(^|;)804(;|$)' -or "
            "$candidate.GetDescription() -match 'Chinese|Huihui|中文') { "
            "$selected = $candidate; break } }; "
            "if (-not $selected) { throw 'No local Chinese SAPI voice.' }; "
            "$s.Voice = $selected; "
            "$stream = New-Object -ComObject SAPI.SpFileStream; "
            f"$stream.Open('{escaped_path}', 3, $false); "
            "$s.AudioOutputStream = $stream; [void]$s.Speak('测试'); "
            "$stream.Close(); $stream = $null; "
            f"if ((Get-Item -LiteralPath '{escaped_path}').Length -le 46) {{ "
            "throw 'SAPI produced an empty WAV.' }; "
            "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
            "$selected.GetDescription(); exit 0 } catch { Write-Error $_; exit 1 } "
            "finally { if ($stream) { try { $stream.Close() } catch {} }; "
            "if ($stream) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($stream) }; "
            "if ($s) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($s) } }"
        )
        command = [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            powershell,
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"available": False, "voice": None, "reason": str(exc)}
        voice = completed.stdout.strip() if completed.returncode == 0 else None
        if voice:
            try:
                media = probe_media(wav_path, ffprobe_path)
                audio_streams = [
                    item
                    for item in media.get("streams") or []
                    if item.get("codec_type") == "audio"
                ]
                duration = float((media.get("format") or {}).get("duration") or 0)
                if not audio_streams or duration <= 0.1:
                    voice = None
                    completed.stderr += " SAPI smoke WAV has no valid audio stream."
            except Exception as exc:
                voice = None
                completed.stderr += f" SAPI smoke validation failed: {exc}"
        return {
            "available": bool(voice),
            "voice": voice,
            "reason": (
                None
                if voice
                else _process_error_summary(
                    completed.stderr,
                    "No usable local Chinese SAPI voice.",
                )
            ),
        }


def _process_error_summary(text: str, fallback: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return lines[-1][:500] if lines else fallback
