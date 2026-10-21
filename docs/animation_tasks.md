# Explicit narrated animation tasks

This opt-in CLI compiles a structured task into an editable native PowerPoint
diagram and timing model. It does not infer arbitrary animation from Word
documents or generate a finished video from a topic.

## Current scope

- Versioned `newton_orbit@1` component with a fixed 1280 by 720 canvas at 30 fps.
- Four operations: reveal velocity, reveal gravity, orbit, and conclude.
- Narration hashes, character spans, exact quoted anchors, and explicit timing.
- Strict field validation, page-local fingerprints and compilation caching.
- Saved PPT timing, rotation angle/centre and automatic transition verification.
- Optional PowerPoint key-state PNG previews, not actual slideshow capture.

The public repository contains only a synthetic contract fixture in
`tests/fixtures/animation_synthetic.json`. Its repeated letters and reserved
example URL are test data, not narration or factual evidence. No finished deck,
validated storyboard, personal voice recording or creative sample is included.

## CLI

Pure compilation needs Python but not Office or model weights:

```powershell
python tools/animation_tasks.py compile tests/fixtures/animation_synthetic.json --output output/animation_test
```

For a real project, author your own task in an ignored local directory. Build
requires Windows PowerPoint and an installed compatible Artifact Tool runtime.
Set the following environment variables to your own installation paths:

```powershell
python tools/animation_tasks.py build private/my_plan.json `
  --output output/my_animation_build `
  --node "$env:ANIMATION_NODE" `
  --modules "$env:ANIMATION_NODE_MODULES"
```

The CLI does not install those dependencies. The output directory must be new.
An alternative entry is `python tools/video_production.py animation ...`.

## Contract and limits

`schema_version` is `1.0`. Each page defines a unique ID, title, component,
narration, four ordered actions and source URLs. Anchors use half-open character
spans and millisecond start/end times. Text changes invalidate the old hash.
Actions reference existing anchor IDs; rotation has an explicit duration.

Preview mode permits draft timing and no audio. Production mode requires a real
PCM WAV relative to the task directory, a matching hash/duration, reviewed timing
and a reviewer name. Validation does not prove the reviewer actually checked the
alignment. This path does not perform automatic TTS or speech alignment.

Outputs include `compiled.json`, cached page tasks, `compile_report.json`,
`execution.json`, `animated.pptx`, `pptx_audit.json` and `native_previews`.
Every PPT package is rebuilt; page-task caching is not binary slide rendering
caching. File-level checks do not replace viewing the actual slideshow.

There is no dedicated Web UI entry or arbitrary science animation engine.
Additional components need parameter validation, layout/timing logic, an Office
mapping and tests. Keep resulting files local as described in
[the publication boundary](publication_boundary.md).
