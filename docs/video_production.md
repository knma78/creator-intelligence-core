# Local video production bridge

Explicit narrated PPT tasks are available as a separate opt-in path:
`python tools/video_production.py animation compile ...`.
See [animation task contract and limits](animation_tasks.md). This path does not
replace the cover slideshow or claim arbitrary prose-to-animation generation.

The Web UI video factory now ends in the [CapCut international workflow](capcut_workflow.md):
it creates an editable project from visuals, narration and captions after the
FFmpeg preview has passed automated QA. CapCut is the final authoring stage in
both script and existing-video modes; the user opens the resulting draft and
exports the final MP4 in CapCut.

ContentResearch now keeps research and production as two explicit stages:

```text
research output
  -> production_manifest.json
  -> FFmpeg/NVENC preview and automated QA
  -> editable CapCut International project
  -> user review and CapCut MP4 export
```

The bridge preserves original research files and source media. It does not copy
old episode assets, completed videos, global Codex skills, `node_modules`,
Blender, After Effects, or FFmpeg into this repository.

## Current locations

Reusable project code:

- `production/contracts.py`: stable production-manifest contract.
- `production/packaging.py`: research-to-production hand-off.
- `production/edit_plan.py`: auditable automatic clip selection and subtitle
  retiming.
- `production/ffmpeg_renderer.py`: one-pass normalized render, NVENC preference,
  and libx264 fallback.
- `production/qa.py`: ffprobe metadata, black-frame and silence scans, subtitle
  readability checks.
- `production/capcut_package.py`: safe import package for optional manual polish.
- `production/video_factory.py`: adapter for an external HyperFrames factory.
- `tools/video_production.py`: command-line entry point.

Runtime output:

- `output/video_production/<video-id>/production_manifest.json`
- `output/video_production/<video-id>/research/`
- `output/video_production/<video-id>/work/edit_plan.json`
- `output/video_production/<video-id>/work/edit_subtitles.srt`
- `output/video_production/<video-id>/work/capcut_timeline.json`
- `output/video_production/<video-id>/output/*.mp4`
- `output/video_production/<video-id>/output/capcut_build.json`
- `output/video_production/<video-id>/*.render.json`
- `output/video_production/<video-id>/*.qa.json`
- `output/video_production/<video-id>/capcut_package/`

External tools remain at their installed locations and are connected through
the local, Git-ignored `.env` using `VIDEO_FFMPEG_PATH`, `FFPROBE_PATH`,
`VIDEO_FACTORY_ROOT`, `EDGE_TTS_PATH`, `BLENDER_PATH`, and `AERENDER_PATH`.
`.env.example` documents these portable settings without committing one
workstation's absolute paths.

## Web UI

Open **视频生产** in the left navigation. The workspace:

1. Defaults to **文稿生成 CapCut 工程**: paste a Chinese narration script,
   preview an auditable storyboard, then submit it to the persistent job queue.
   This path does not call an Agent at runtime.
2. The script loop derives shot cadence from existing distilled scene data. Its
   cover resolver weighs title, keywords, summary and cover OCR, then uses stored
   OpenCLIP labels as a visual-type tie-breaker. Every scene records its matched
   terms, reasons, score, confidence and whether the match came from that scene
   or the full script.
3. Covers are verified as decodable before selection. Low-confidence or broken
   covers use a local gradient rather than silently showing unrelated material.
   Selected covers are contained in frame over a blurred fill, so embedded cover
   text is not lost to center cropping.
4. Edge TTS writes narration and VTT to temporary files, validates the audio and
   timeline, and only then atomically publishes the cache. Windows SAPI is a
   probed fallback rather than an assumed fallback. Both paths expose a heartbeat,
   timeout and cooperative cancellation while continuously draining process logs.
5. Also offers an existing-video mode, which lists completed research jobs and
   marks whether source video and timed subtitles are ready.
6. Creates a visible edit plan before rendering. The first clip implementation
   deliberately chooses one high-density continuous interval so automated
   editing does not introduce semantic jumps.
7. Submits preview rendering, QA, and CapCut project generation to the same
   persistent local job queue used by research tasks.
8. Shows FFmpeg/NVENC/CapCut readiness, progress, logs, cancellation, and
   output files in the existing dark theme.
9. Terminates running TTS or FFmpeg processes cooperatively when cancellation is
   requested and removes incomplete temporary narration and render files.
10. Runs black-frame, silence, media-parameter, duration, dimensions, subtitle
    overlap/order/end-time, and subtitle-width QA on the MP4 preview, then
    creates a separate editable CapCut project for final review and export.

The current script loop is intentionally a rough **cover-based narrated
slideshow**, not a semantic source-clip editor. It reuses distilled timing and
metadata now. OpenCLIP currently contributes already-stored visual labels; it
does not load the model during preview or select motion clips. Selecting source
video intervals from `scene_analysis` is a later quality layer and is not implied
by this closed loop.

Script-job output:

- `output/video_production/script_jobs/<job-id>/work/source_script.txt`
- `output/video_production/script_jobs/<job-id>/work/narration.mp3`
- `output/video_production/script_jobs/<job-id>/work/captions.srt`
- `output/video_production/script_jobs/<job-id>/work/storyboard.json`
- `output/video_production/script_jobs/<job-id>/work/capcut_assets/`
- `output/video_production/script_jobs/<job-id>/work/template.json`
- `output/video_production/script_jobs/<job-id>/work/tts.json`
- `output/video_production/script_jobs/<job-id>/output/rough_narrated_video.mp4`
- `output/video_production/script_jobs/<job-id>/output/capcut_build.json`
- sibling render and QA JSON audit records

The production API is local:

- `GET /api/production/sources`
- `GET /api/production/runtime`
- `POST /api/production/plan`
- `POST /api/production/render`
- `POST /api/production/script-plan`
- `POST /api/production/script-render`

## Commands

Inspect the local stack and validate that one-frame NVENC encoding really works:

```powershell
python tools/video_production.py inspect
```

Create a stable production hand-off from a completed research job:

```powershell
python tools/video_production.py package BVxxxxxxxxxx
```

Large source media is referenced in place by default. Copy it only when a
self-contained package is required:

```powershell
python tools/video_production.py package BVxxxxxxxxxx --include-media
```

Render with GPU preference and automatic CPU fallback:

```powershell
python tools/video_production.py render input.mp4 output/final.mp4 `
  --audio narration.wav --subtitle subtitle.srt
```

Render on CPU explicitly:

```powershell
python tools/video_production.py render input.mp4 output/final.mp4 --cpu
```

Run automated QA:

```powershell
python tools/video_production.py qa output/final.mp4 --subtitle subtitle.srt
```

Create a CapCut import folder after the automated master is ready:

```powershell
python tools/video_production.py capcut-pack `
  output/video_production/BVxxxxxxxxxx/production_manifest.json `
  --master output/final.mp4
```

Inspect the existing HyperFrames project without rendering:

```powershell
python tools/video_production.py factory inspect
```

The `factory check`, `factory draft`, and `factory render` actions call scripts
already declared by the selected external project. HyperFrames projects should
still follow their own `lint -> validate -> inspect -> render` checks.

## Design boundaries

### Conditional capabilities now drive visual boundaries

The script preview and final storyboard use the same `production/capability_layout.py`
adapter. The API's `capability_plan` is the plan embedded in the actual storyboard,
not a separately computed suggestion. Each storyboard saves `capability_execution`
and each affected scene saves `capability_decisions`, including rule ID, content
version/fingerprint, evidence IDs, local signal, operation, and boundary changes.

Initial supported templates: `hook_question_task`, `hook_contrast_gap`,
`ending_question_callback`, `ending_logic_closure`, and the four `transition_*`
templates (sequence, turning_point, causal_close, example_bridge). These can keep
a complete opening/ending sentence on screen or introduce a cut at an explicit
connective. They do not rewrite narration, reorder sentences, invent evidence,
or select source-video intervals. Unsupported narrative/climax/workflow abilities
remain suggestions with explicit non-application reasons.

Matching is lexical and execution checks local structural cues, not full semantic
understanding. Same-layer alternatives compete; stale reviews, unknown conditions,
missing local cues, shots shorter than 0.2 seconds or held sentences longer than
12 seconds prevent automatic application. The 12-second bound is an engineering
guard against long static images, not a learned optimum or proof of engagement.
No matched/executable rule means basic segmentation. Candidate rules remain
hypotheses after use; execution does not promote knowledge status.

Segments cover contiguous character ranges of the original text exactly once.
Preview timing is length-weighted. Final timing uses aligned TTS cue interpolation
when the complete normalized text matches, otherwise records an explicit estimated
timing warning. This is not phoneme-accurate forced alignment. Final generation
recomputes using current rules and actual narration duration; preview is not a
locked render contract. JSON records the rule versions actually used.

The preview UI shows actual applied changes, already-satisfied boundaries, and
declined reasons. Adopting a rule does not necessarily change an already suitable
boundary. This first integration does not replace the cover-based visual mode or
establish creative-quality/retention benefits.

- FFmpeg is the repeatable automated production backend.
- HyperFrames is an optional motion-graphics / HTML composition engine.
- CapCut is an optional final manual-polish step, not the source of truth.
- Every automated render writes a sibling `.render.json` audit record.
- QA writes structured JSON; black frames and overly dense subtitles are
  reviewable findings rather than hidden console output.
- A production package copies small reports and captions, but never copies large
  media unless `--include-media` is passed.

Automatic edit plans use schema `2.0`. Selection remains a conservative
continuous-window edit, while scoring consumes research structure, keywords,
scene boundaries, audio-rhythm metrics, and available visual labels. Every
signal and decision reason is recorded in the plan.

QA distinguishes blocking media errors from review warnings. Missing video or
audio streams and failed FFmpeg scans fail the production job; black-frame or
subtitle-readability warnings complete as `review_required`.
