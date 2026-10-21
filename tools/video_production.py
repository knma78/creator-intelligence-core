from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_settings
from production.capcut_package import create_capcut_package
from production.contracts import RenderProfile
from production.ffmpeg_renderer import (
    inspect_ffmpeg_runtime,
    render_master,
)
from production.packaging import create_research_package
from production.qa import qa_video
from production.video_factory import VideoFactoryAdapter


def _tool_state(path: str | None) -> dict[str, Any]:
    if not path:
        return {"path": None, "available": False}
    candidate = Path(path)
    available = candidate.is_file() if candidate.is_absolute() else bool(
        shutil.which(path)
    )
    return {"path": path, "available": available}


def inspect_local_stack(*, validate_gpu: bool = True) -> dict[str, Any]:
    settings = load_settings(reload_env=True)
    ffmpeg = inspect_ffmpeg_runtime(
        settings.video_ffmpeg_path,
        validate_nvenc=validate_gpu,
    )
    return {
        "schema_version": "1.0",
        "production_directory": str(settings.video_production_dir),
        "ffmpeg": ffmpeg,
        "ffprobe": _tool_state(settings.ffprobe_path),
        "edge_tts": _tool_state(settings.edge_tts_path),
        "blender": _tool_state(settings.blender_path),
        "after_effects_renderer": _tool_state(settings.aerender_path),
        "video_factory": VideoFactoryAdapter(settings=settings).inspect(),
    }


def _profile_from_args(args: argparse.Namespace) -> RenderProfile:
    return RenderProfile(
        width=args.width,
        height=args.height,
        fps=args.fps,
        platform=args.platform,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local research-to-video production bridge."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    animation_parser = subparsers.add_parser("animation", help="Compile or build explicit narrated PPT animation tasks.")
    animation_parser.add_argument("arguments", nargs=argparse.REMAINDER)

    inspect_parser = subparsers.add_parser(
        "inspect",
        help="Inspect local production tools and validate NVENC.",
    )
    inspect_parser.add_argument(
        "--skip-gpu-test",
        action="store_true",
        help="Only list the NVENC encoder without performing a one-frame test.",
    )

    package_parser = subparsers.add_parser(
        "package",
        help="Create an auditable production package from research output.",
    )
    package_parser.add_argument("video_id")
    package_parser.add_argument(
        "--include-media",
        action="store_true",
        help="Copy large source media instead of referencing it in place.",
    )
    package_parser.add_argument(
        "--engine",
        choices=("ffmpeg", "hyperframes"),
        default="ffmpeg",
    )
    package_parser.add_argument("--width", type=int, default=1920)
    package_parser.add_argument("--height", type=int, default=1080)
    package_parser.add_argument("--fps", type=int, default=30)
    package_parser.add_argument("--platform", default="general")

    qa_parser = subparsers.add_parser(
        "qa",
        help="Probe a rendered video and scan black frames, silence, captions.",
    )
    qa_parser.add_argument("video", type=Path)
    qa_parser.add_argument("--subtitle", type=Path)
    qa_parser.add_argument("--report", type=Path)

    render_parser = subparsers.add_parser(
        "render",
        help="Render a normalized MP4 with NVENC preference and CPU fallback.",
    )
    render_parser.add_argument("source", type=Path)
    render_parser.add_argument("output", type=Path)
    render_parser.add_argument("--audio", type=Path)
    render_parser.add_argument("--subtitle", type=Path)
    render_parser.add_argument("--cpu", action="store_true")
    render_parser.add_argument("--no-source-audio", action="store_true")
    render_parser.add_argument("--width", type=int, default=1920)
    render_parser.add_argument("--height", type=int, default=1080)
    render_parser.add_argument("--fps", type=int, default=30)
    render_parser.add_argument("--platform", default="general")

    capcut_parser = subparsers.add_parser(
        "capcut-pack",
        help="Export a safe import folder for optional CapCut polish.",
    )
    capcut_parser.add_argument("manifest", type=Path)
    capcut_parser.add_argument("--master", type=Path)
    capcut_parser.add_argument("--output", type=Path)

    draft_parser = subparsers.add_parser(
        "capcut-draft", help="Build an editable CapCut project from a timeline or final storyboard JSON."
    )
    draft_parser.add_argument("plan", type=Path)
    draft_parser.add_argument("--name")
    draft_parser.add_argument("--draft-dir", type=Path)
    subparsers.add_parser("capcut-health", help="Inspect the local CapCut MCP integration.")

    factory_parser = subparsers.add_parser(
        "factory",
        help="Inspect or invoke an existing HyperFrames video factory.",
    )
    factory_parser.add_argument(
        "action",
        choices=("inspect", "check", "draft", "render"),
    )
    factory_parser.add_argument("--project-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "animation":
        from tools.animation_tasks import main as animation_main
        return animation_main(args.arguments)
    if args.command in {"capcut-draft", "capcut-health"}:
        interpreter = PROJECT_ROOT / ".venv-capcut" / "Scripts" / "python.exe"
        if not interpreter.is_file():
            raise RuntimeError("CapCut environment missing. See docs/capcut_workflow.md.")
        command = [str(interpreter), str(PROJECT_ROOT / "tools" / "capcut_mcp.py")]
        if args.command == "capcut-health":
            command.append("health")
        else:
            command.extend(["build", str(args.plan.resolve())])
            if args.name:
                command.extend(["--name", args.name])
            if args.draft_dir:
                command.extend(["--draft-dir", str(args.draft_dir.resolve())])
        return subprocess.run(command, check=False).returncode
    settings = load_settings(reload_env=True)

    if args.command == "inspect":
        result = inspect_local_stack(validate_gpu=not args.skip_gpu_test)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ffmpeg"]["available"] else 1

    if args.command == "package":
        path = create_research_package(
            args.video_id,
            settings=settings,
            include_media=args.include_media,
            engine=args.engine,
            render_profile=_profile_from_args(args),
        )
        print(path)
        return 0

    if args.command == "qa":
        report_path = args.report or args.video.with_suffix(
            args.video.suffix + ".qa.json"
        )
        report = qa_video(
            args.video,
            ffmpeg_path=settings.video_ffmpeg_path,
            ffprobe_path=settings.ffprobe_path,
            subtitle_path=args.subtitle,
            report_path=report_path,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["passed"] else 2

    if args.command == "render":
        output = render_master(
            args.source,
            args.output,
            profile=_profile_from_args(args),
            narration_audio=args.audio,
            subtitle_path=args.subtitle,
            prefer_gpu=not args.cpu,
            has_source_audio=not args.no_source_audio,
            settings=settings,
        )
        print(output)
        return 0

    if args.command == "capcut-pack":
        output = create_capcut_package(
            args.manifest,
            master_video=args.master,
            output_dir=args.output,
        )
        print(output)
        return 0

    if args.command == "factory":
        adapter = VideoFactoryAdapter(args.project_root, settings=settings)
        if args.action == "inspect":
            print(json.dumps(adapter.inspect(), ensure_ascii=False, indent=2))
            return 0
        script = {
            "check": "check",
            "draft": "render:draft",
            "render": "render",
        }[args.action]
        result = adapter.run(script)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return result.returncode

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
