"""Compile explicit narration/storyboard tasks; opt-in native PPT build.

The compiler is dependency-light. Building requires the locally configured
Artifact Tool runtime and Windows PowerPoint, never an implicit download.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from infrastructure.atomic_io import atomic_write_json
from production.animation_plan import compile_plan, save_compilation
from production.animation_scene import build_scene, visible_objects
from production.animation_pptx import audit_pptx, unlock_generated_shapes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['compile', 'build'])
    parser.add_argument('plan', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['preview', 'production'], default='preview')
    parser.add_argument('--node', type=Path)
    parser.add_argument('--modules', type=Path)
    args = parser.parse_args(argv)
    source = json.loads(args.plan.read_text(encoding='utf-8-sig'))
    plan = compile_plan(source, source_dir=args.plan.parent, mode=args.mode)
    if args.command == 'build':
        if args.output.exists():
            parser.error('build 输出目录必须为新目录，避免覆盖已有制作结果')
        if not args.node or not args.modules or not args.node.is_file():
            parser.error('build 必须显式提供 --node 与 --modules 本机运行环境')
        if not (args.modules / '@oai/artifact-tool/dist/artifact_tool.mjs').is_file():
            parser.error('Artifact Tool 未就绪，不会自动下载替代依赖')
    report = save_compilation(plan, args.output)
    records = []
    for page in plan['pages']:
        scene = build_scene(page)
        previews = [{'frame': f, 'objects': visible_objects(scene, f)} for f in scene['preview_frames']]
        records.append({'page': page, 'scene': scene, 'previews': previews})
    bundle = {'schema_version': '1.0', 'mode': args.mode, 'pages': records}
    bundle_path = atomic_write_json(args.output / 'execution.json', bundle)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if args.command == 'build':
        subprocess.run([str(args.node), str(ROOT/'tools/animation_deck.mjs'),
                        str(bundle_path.resolve()), str((args.output/'work').resolve()),
                        str(args.modules.resolve())], check=True, timeout=180)
        candidate = args.output / 'animated.pptx'
        groupable = args.output / 'work' / 'groupable.pptx'
        unlock_generated_shapes(args.output/'work/static.pptx', groupable)
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                        '-File', str(ROOT/'tools/Build-AnimationDeck.ps1'),
                        '-Bundle', str(bundle_path.resolve()),
                        '-Draft', str(groupable.resolve()),
                        '-Output', str(candidate.resolve())], check=True, timeout=180)
        atomic_write_json(args.output / 'pptx_audit.json', audit_pptx(candidate, bundle))
        subprocess.run(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                        '-File', str(ROOT/'tools/Inspect-AnimationDeck.ps1'),
                        '-Bundle', str(bundle_path.resolve()), '-Deck', str(candidate.resolve()),
                        '-OutputDirectory', str((args.output/'native_previews').resolve())],
                       check=True, timeout=120)
        print(f'PPT candidate: {candidate.resolve()}', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f'Animation task failed: {exc}', file=sys.stderr)
        raise SystemExit(2)
