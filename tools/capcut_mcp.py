"""Local stdio MCP server / CLI entry for CapCut editable projects."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from production.capcut_bridge import build_draft, health, save_new_draft, validate_name


def make_server():
    from mcp.server.fastmcp import FastMCP
    from ccmcp import server as upstream, session
    mcp = FastMCP('capcut')
    mcp.tool(name='cc_health')(health)
    for name in ('list_drafts', 'list_effects', 'list_filters',
                 'place_clip', 'add_audio', 'add_text', 'add_text_block',
                 'add_captions', 'add_filter', 'add_clip_effect', 'add_animation',
                 'apply_transition', 'add_filter_layer', 'add_effect_layer', 'draft_status'):
        mcp.tool()(getattr(upstream, name))

    @mcp.tool()
    def create_draft(name: str, width: int = 1080, height: int = 1920, fps: int = 30) -> dict:
        """Create a NEW CapCut draft session. Use a unique name for every revision."""
        validate_name(name)
        if width <= 0 or height <= 0 or fps not in (24, 25, 30, 50, 60):
            raise ValueError('Invalid canvas profile.')
        return upstream.create_draft(name, width, height, fps)

    @mcp.tool()
    def save_draft() -> dict:
        """Save as a new editable CapCut project. Close CapCut first. Never overwrites projects.

        Completion means draft_ready, not an exported MP4. Open in CapCut and export there.
        """
        return save_new_draft(session.active())

    @mcp.tool()
    def build_from_plan(plan_path: str, name: str = '') -> dict:
        """Build an editable CapCut project from a local timeline JSON or final storyboard.json.

        Inputs: clips, audios, timed captions (or subtitle_path); alternatively existing
        ContentResearch scenes/narration_path/subtitle_path/render_profile. Assets must exist.
        Close CapCut first. No HTML rendering; no changes to existing drafts; export in CapCut.
        """
        return build_draft(Path(plan_path), name=name or None)
    return mcp


def main() -> int:
    local_config = ROOT / 'config' / 'capcut.local.json'
    if local_config.is_file():
        values = json.loads(local_config.read_text(encoding='utf-8-sig'))
        for key in ('CAPCUT_DRAFT_DIR', 'CAPCUT_CACHE_DIR'):
            if values.get(key):
                os.environ.setdefault(key, values[key])
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('serve')
    sub.add_parser('health')
    build = sub.add_parser('build')
    build.add_argument('plan', type=Path)
    build.add_argument('--name')
    build.add_argument('--draft-dir', type=Path)
    args = parser.parse_args()
    if args.action == 'serve':
        make_server().run()
    elif args.action == 'health':
        print(json.dumps(health(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(build_draft(args.plan, name=args.name, destination=args.draft_dir),
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
