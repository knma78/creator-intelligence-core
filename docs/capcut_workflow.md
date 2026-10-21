# CapCut international workflow

The video factory now ends in an editable CapCut International draft:

`video factory -> MP4 preview + automated QA -> editable CapCut draft -> review and export in CapCut`

Both Web UI production modes use this hand-off. Script mode writes separate
visual, narration, and editable caption tracks. Existing-video mode writes the
selected source interval and an editable caption track. The worker creates the
draft through the local CLI; it does not use Computer Use or simulate imports in
the CapCut window. FFmpeg still makes a preview for automated QA, while the
CapCut draft is the final editable project. MP4 export remains a user action in
CapCut because the installed adapter has no native export API.

## Installed components

- Separate Python 3.12 environment: `.venv-capcut/`.
- Upstream: https://github.com/nguyenph88/Media-Editor-MCP,
  commit `1295a6a85cb5ae8e544ebf97dbe28c326b681981`, package `packages/capcut-mcp`.
- Local MCP entry: `tools/capcut_mcp.py serve`, registered as `capcut` in Codex.
- Machine paths: `config/capcut.local.json` (ignored by Git).
- CapCut MCP calls use a local stdio process, with no API key required.

For reinstall, create a Python 3.12 venv, download the pinned upstream source,
and install its `packages/capcut-mcp` package. Copy `config/capcut.example.json`
to `config/capcut.local.json` and set actual local paths. Register the absolute
venv Python path and the absolute `tools/capcut_mcp.py` path with
`codex mcp add capcut -- <python> <script> serve`.

## Usage

Close CapCut normally before saving a draft. Each revision uses a new name.

```powershell
python tools/video_production.py capcut-health
python tools/video_production.py capcut-draft output/capcut_integration_sample/timeline.json --name My_First_CapCut_Project
python tools/video_production.py capcut-draft path/to/storyboard.json --name My_Story_v2
```

The Web UI job result includes a `capcut_build.json` record with the generated
project name, draft path, track summary, and export status. Open that draft in
CapCut, review the tracks, and export the final MP4.
Run the existing QA command against that exported file:

```powershell
python tools/video_production.py qa path/to/export.mp4 --subtitle path/to/captions.srt
```

MCP tools include `cc_health`, `list_drafts`, `create_draft`, `place_clip`,
`add_audio`, `add_text`, `add_captions`, effects/filter/transition tools,
`save_draft`, and `build_from_plan`. The bulk `build_from_plan` tool accepts an
absolute local plan path and an optional unique project name. Start a new Codex
chat/reload the client if an existing chat has not loaded the newly registered MCP.

## Input contract

Timeline JSON uses seconds; media paths can be absolute or relative to the JSON:

```json
{
  "name": "My_CapCut_Draft",
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "clips": [{"path": "picture.png", "start": 0, "duration": 5, "volume": 0}],
  "audios": [{"path": "narration.wav", "start": 0, "duration": 5}],
  "captions": [{"start": 0.1, "end": 4.8, "text": "An editable caption"}]
}
```

Use `subtitle_path` instead of inline captions for SRT/VTT. Subtitle cues must
be nonoverlapping and within the visual timeline. Existing final storyboard
files are supported through `scenes`, `narration_path`, `subtitle_path`, and
`render_profile`. A storyboard scene explicitly marked `local_gradient` gets a
generated still in its job's `capcut_assets` folder; other scenes still need a
valid media path. The current bridge keeps the
upstream single video/audio track model; add/mix music in CapCut when needed.

## Persistence and limits

- The adapter stages a complete new draft, then publishes it to the configured
  draft directory. Existing projects are never overwritten, and failed builds
  do not leave a partial project in the home list.
- Media remains referenced by absolute path. Keep the source folder in place.
- CapCut is never force-killed or silently upgraded by the MCP.
- Built-in CapCut TTS/AI services and automatic GUI export are not MCP tools.
- Effects may require locally cached resources or downloads in CapCut.
- `export_status=awaiting_capcut_export` means an editable draft is ready;
  it does not assert that CapCut has rendered or visually verified it.
- Keep the job's video-production folder in place: the CapCut project references
  generated visuals, narration, and subtitles by absolute path.
- Close CapCut normally before starting a factory job. Runtime status checks
  this requirement, and the draft adapter never force-closes the application.
- Package/draft schema compatibility is version-dependent. Check the local
  verification report before assuming a newer CapCut version is supported.

## Verification

Validate compatibility against the installed CapCut version before production
use. Personal verification records and finished sample projects are not part of
this source distribution. MCP registration is local to the client that uses it;
the Web UI invokes the adapter as its final project-generation step.

```powershell
.venv-capcut/Scripts/python.exe -m unittest discover -s tests -p test_capcut_bridge.py -v
```

Tests exercise actual draft creation, media/text tracks, time conversion,
path validation, running-app checks, and preservation of existing projects.
