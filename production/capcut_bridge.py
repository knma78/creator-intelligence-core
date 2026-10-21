"""Compile editable CapCut projects; optional dependencies live in .venv-capcut.

No FFmpeg/HTML final rendering is performed here. The output is an editable
project with separate video, narration and caption tracks.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any


def is_capcut_running() -> bool:
    # Use PowerShell's process cmdlet because tasklist can be denied in a
    # restricted desktop session, even though the current-user process is visible.
    result = subprocess.run(
        [
            'powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
            "$ErrorActionPreference='Stop'; "
            "if (Get-Process -Name CapCut -ErrorAction SilentlyContinue) "
            "{ 'running' } else { 'stopped' }",
        ],
        capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=10, check=True,
    )
    state = result.stdout.strip().lower()
    if state not in {'running', 'stopped'}:
        raise RuntimeError('Unable to determine whether CapCut is running.')
    return state == 'running'


def health() -> dict[str, Any]:
    from ccmcp import __version__, effects, paths
    return {'version': __version__, 'draftDir': str(paths.draft_dir()),
            'draftDirExists': paths.draft_dir().is_dir(),
            'effectCounts': effects.counts(), 'capcutRunning': is_capcut_running()}


def validate_name(name: str) -> str:
    if (not name or name != name.strip() or len(name) > 100
            or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
            or name.endswith('.') or name in {'.', '..'}
            or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', name, re.I)):
        raise ValueError('Use a single, valid Windows folder name for the draft.')
    return name


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        raise ValueError(f'{label} must be finite and {"positive" if positive else "nonnegative"}.')
    return number


def _asset(value: str, base: Path) -> str:
    p = Path(value).expanduser()
    p = (base / p).resolve() if not p.is_absolute() else p.resolve()
    if not p.is_file():
        raise FileNotFoundError(f'Missing CapCut source asset: {p}')
    return str(p)


def _fallback_visual(source: Path, profile: dict[str, Any]) -> Path:
    """Create a stable still for a storyboard's explicit local-gradient fallback."""
    width = int(profile.get('width') or 1080)
    height = int(profile.get('height') or 1920)
    if not (16 <= width <= 8192 and 16 <= height <= 8192):
        raise ValueError('Fallback visual dimensions are outside the supported range.')
    key = hashlib.sha256(
        f'{source.resolve()}:{width}x{height}'.encode('utf-8')
    ).hexdigest()[:12]
    target_dir = source.parent / 'capcut_assets'
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f'fallback_gradient_{key}.png'
    if target.is_file() and target.stat().st_size:
        return target
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError('Pillow is required to create a CapCut fallback visual.') from exc

    image = Image.new('RGB', (width, height))
    pixels = []
    top = (7, 20, 25)
    bottom = (27, 57, 67)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(round(a + (b - a) * ratio) for a, b in zip(top, bottom))
        pixels.extend([color] * width)
    image.putdata(pixels)
    image.save(target, format='PNG', optimize=True)
    return target


def load_plan(source: Path, name: str | None = None) -> dict[str, Any]:
    """Accept a CapCut timeline plan or an existing script pipeline storyboard."""
    source = Path(source).resolve()
    data = json.loads(source.read_text(encoding='utf-8-sig'))
    draft_name = validate_name(name or data.get('name') or f'Codex_{source.parent.name}')
    base = source.parent
    profile = data.get('render_profile') or {}
    plan = {
        'name': draft_name,
        'width': data.get('width', profile.get('width', 1080)),
        'height': data.get('height', profile.get('height', 1920)),
        'fps': data.get('fps', profile.get('fps', 30)),
        'clips': [], 'audios': [], 'captions': [],
        'source_plan': str(source),
    }
    if 'scenes' in data:
        if data.get('preview'):
            raise ValueError('An estimated preview has no verified narration timing. Use the final storyboard.')
        for scene in data['scenes']:
            visual = scene.get('visual') or {}
            visual_path = visual.get('path')
            if not visual_path:
                if visual.get('type') != 'local_gradient':
                    raise ValueError(f"Scene {scene.get('scene_id')} needs a real image/video before CapCut export.")
                visual_path = str(_fallback_visual(source, profile))
                generated_assets = plan.setdefault('generated_assets', [])
                if visual_path not in generated_assets:
                    generated_assets.append(visual_path)
            plan['clips'].append({
                'path': visual_path, 'start': scene['output_start_seconds'],
                'duration': float(scene['output_end_seconds']) - float(scene['output_start_seconds']),
                'source_start': scene.get('source_start_seconds', 0), 'volume': 0,
            })
        if data.get('narration_path'):
            plan['audios'].append({'path': data['narration_path'], 'start': 0,
                                   'duration': data['output_duration_seconds'], 'volume': 1})
        subtitle = data.get('subtitle_path')
    else:
        plan['clips'] = [dict(c) for c in data.get('clips', [])]
        plan['audios'] = [dict(a) for a in data.get('audios', [])]
        plan['captions'] = [dict(c) for c in data.get('captions', [])]
        subtitle = data.get('subtitle_path')
    if subtitle:
        # Existing parser accepts the same time syntax in SRT and WebVTT.
        from production.captions import parse_vtt
        plan['captions'] = parse_vtt(Path(_asset(subtitle, base)))
        if not plan['captions']:
            raise ValueError('Subtitle file contains no usable timed captions.')
    for kind in ('clips', 'audios'):
        for item in plan[kind]:
            item['path'] = _asset(item['path'], base)
    validate_plan(plan)
    return plan


def validate_plan(plan: dict[str, Any]) -> None:
    validate_name(plan['name'])
    for key in ('width', 'height'):
        if not isinstance(plan[key], int) or not 16 <= plan[key] <= 8192:
            raise ValueError(f'{key} must be an integer from 16 to 8192.')
    if plan['fps'] not in (24, 25, 30, 50, 60):
        raise ValueError('Unsupported frame rate.')
    if not plan.get('clips'):
        raise ValueError('At least one visual clip is required.')
    ends: dict[str, float] = {}
    for kind in ('clips', 'audios'):
        for item in plan.get(kind, []):
            start = _number(item['start'], f'{kind}.start')
            duration = _number(item['duration'], f'{kind}.duration', positive=True)
            _number(item.get('source_start', 0), f'{kind}.source_start')
            _number(item.get('volume', 1), f'{kind}.volume')
            _number(item.get('speed', 1), f'{kind}.speed', positive=True)
            _number(item.get('scale', 1), f'{kind}.scale', positive=True)
            if item.get('track'):
                raise ValueError('This adapter supports one video track and one audio track; omit track.')
            track = f"{kind}:{item.get('track') or kind}"
            if start < ends.get(track, 0) - 0.000001:
                raise ValueError(f'Overlapping or unsorted segments on {track}.')
            ends[track] = start + duration
    video_end = max(float(c['start']) + float(c['duration']) for c in plan['clips'])
    caption_end = 0.0
    for cue in plan.get('captions', []):
        start = _number(cue['start'], 'caption.start')
        end = _number(cue['end'], 'caption.end', positive=True)
        if start < caption_end - 0.000001 or end <= start or end > video_end + 0.05:
            raise ValueError('Captions must be ordered, nonoverlapping, and within the video.')
        if not str(cue['text']).strip():
            raise ValueError('Empty caption text.')
        caption_end = end


def session_from_plan(plan: dict[str, Any]):
    from ccmcp import session
    validate_plan(plan)
    s = session.new(plan['name'], plan['width'], plan['height'], plan['fps'])
    us = lambda value: round(float(value) * session.SEC)
    for c in plan['clips']:
        s.clips.append(session.ClipSpec(
            path=c['path'], start_us=us(c['start']), duration_us=us(c['duration']),
            source_start_us=us(c.get('source_start', 0)), volume=c.get('volume', 0),
            scale=c.get('scale', 1), speed=c.get('speed', 1),
        ))
    for a in plan.get('audios', []):
        s.audios.append(session.AudioSpec(
            path=a['path'], start_us=us(a['start']), duration_us=us(a['duration']),
            source_start_us=us(a.get('source_start', 0)), volume=a.get('volume', 1),
            track=a.get('track'),
        ))
    for c in plan.get('captions', []):
        s.texts.append(session.TextSpec(
            text=c['text'], start_us=us(c['start']), duration_us=us(float(c['end'])-float(c['start'])),
            size=8, align=1, pos_x=0.5, pos_y=0.82,
            border=True, border_width=30, auto_wrap=True, max_line_width=0.86,
            track='captions',
        ))
    return s


def save_new_draft(s, destination: Path | None = None) -> dict[str, Any]:
    """Stage completely before publishing a NEW project; never replace user work.

    Upstream materialize(allow_replace=True) can delete an existing draft folder,
    including its backup. Staging avoids that behaviour entirely. Every revision
    must use a new name. No force-close/restart tool is exposed by our server.
    """
    from ccmcp import draft, paths, session
    validate_name(s.name)
    root = Path(destination or paths.draft_dir()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / s.name
    if target.exists():
        raise FileExistsError(f'Draft already exists: {target}. Use a new name for a revision.')
    if is_capcut_running():
        raise RuntimeError('Close CapCut normally before saving a new draft; no process will be force-closed.')
    for item in [*s.clips, *s.audios]:
        _asset(item.path, Path.cwd())
        if item.start_us < 0 or item.duration_us <= 0:
            raise ValueError('Invalid media timing.')
    # Multiple narration/music tracks are not supported by upstream materialize.
    if any(a.track for a in s.audios):
        raise ValueError('This adapter currently supports one audio track; mix music separately or use CapCut.')
    old_root = os.environ.get('CAPCUT_DRAFT_DIR')
    old_created = s.created
    old_detector = draft.is_capcut_running
    try:
        draft.is_capcut_running = is_capcut_running
        with tempfile.TemporaryDirectory(prefix='.codex-stage-', dir=root) as temp:
            os.environ['CAPCUT_DRAFT_DIR'] = temp
            s.created = False
            report = session.save(s)
            staged = Path(temp) / s.name
            meta_path = staged / 'draft_meta_info.json'
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            meta.update(draft_fold_path=target.as_posix(), draft_root_path=str(root),
                        draft_name=s.name, draft_id=str(uuid.uuid4()).upper(),
                        tm_duration=s.timeline_us())
            meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding='utf-8')
            content = json.loads((staged / 'draft_content.json').read_text(encoding='utf-8'))
            if content.get('duration', 0) <= 0:
                raise ValueError('Generated draft has no duration.')
            (staged / 'codex_build.json').write_text(json.dumps({
                'schema_version': '1.0', 'adapter': 'ContentResearch CapCut',
                'summary': s.summary(), 'export_status': 'awaiting_capcut_export',
                'upstream_commit': '1295a6a85cb5ae8e544ebf97dbe28c326b681981',
            }, ensure_ascii=False, indent=2), encoding='utf-8')
            if is_capcut_running():
                raise RuntimeError('CapCut opened during generation; close it and retry.')
            # Windows rename refuses an existing directory, including a racing writer.
            staged.rename(target)
            report.update(saved=str(target / 'draft_content.json'), backup=None,
                          export_status='awaiting_capcut_export', capcut_running=False)
            return report
    finally:
        draft.is_capcut_running = old_detector
        s.created = old_created
        if old_root is None:
            os.environ.pop('CAPCUT_DRAFT_DIR', None)
        else:
            os.environ['CAPCUT_DRAFT_DIR'] = old_root


def build_draft(source: Path, *, name: str | None = None,
                destination: Path | None = None) -> dict[str, Any]:
    plan = load_plan(source, name)
    report = save_new_draft(session_from_plan(plan), destination)
    report['source_plan'] = str(Path(source).resolve())
    report['generated_assets'] = plan.get('generated_assets', [])
    return report
