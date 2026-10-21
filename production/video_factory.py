from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings


class VideoFactoryAdapter:
    """Thin adapter around an external HyperFrames video-factory project."""

    def __init__(
        self,
        project_root: Path | None = None,
        *,
        settings: Settings = SETTINGS,
    ) -> None:
        self.settings = settings
        self.project_root = Path(
            project_root or settings.video_factory_root
        ).resolve()

    def _package(self) -> dict[str, Any]:
        path = self.project_root / "package.json"
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def inspect(self) -> dict[str, Any]:
        package = self._package()
        scripts = package.get("scripts")
        if not isinstance(scripts, dict):
            scripts = {}
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        node = shutil.which("node.exe") or shutil.which("node")
        local_cli = next(
            (
                path
                for path in (
                    self.project_root
                    / "node_modules"
                    / ".bin"
                    / "hyperframes.cmd",
                    self.project_root
                    / "node_modules"
                    / ".bin"
                    / "hyperframes",
                )
                if path.is_file()
            ),
            None,
        )
        return {
            "project_root": str(self.project_root),
            "available": bool(package and npm),
            "package_name": package.get("name"),
            "npm_path": npm,
            "node_path": node,
            "local_hyperframes_cli": str(local_cli) if local_cli else None,
            "scripts": sorted(str(key) for key in scripts),
            "has_check": "check" in scripts,
            "has_draft_render": "render:draft" in scripts,
            "has_final_render": "render" in scripts,
        }

    def command(self, script: str) -> list[str]:
        state = self.inspect()
        if not state["available"]:
            raise RuntimeError(
                f"Video factory is not ready: {self.project_root}"
            )
        if script not in state["scripts"]:
            raise ValueError(
                f"Video factory script is not defined: {script}"
            )
        return [str(state["npm_path"]), "run", script]

    def run(self, script: str) -> subprocess.CompletedProcess[str]:
        """Run an existing factory script; callers decide when rendering is safe."""

        return subprocess.run(
            self.command(script),
            cwd=self.project_root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
