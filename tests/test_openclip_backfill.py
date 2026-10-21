from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from config import SETTINGS
from pipeline.openclip_backfill import backfill_openclip_from_outputs


def test_openclip_backfill_updates_only_cover_semantics(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    video_id = "BV_TEST"
    research_dir = output_dir / video_id
    cover_dir = cache_dir / "covers" / video_id
    research_dir.mkdir(parents=True)
    cover_dir.mkdir(parents=True)
    cover_path = cover_dir / "cover.jpg"
    cover_path.write_bytes(b"fixture")
    payload = {
        "video_id": video_id,
        "comments_analysis": {"status": "ok", "comment_count": 7},
        "cover_analysis": {
            "status": "ok",
            "image_path": str(cover_path),
            "ocr": {"status": "ok", "text": "标题"},
        },
        "title_stats": {"average_length": 4},
        "nlp_analysis": {"status": "ok"},
        "scene_analysis": {"status": "ok", "scene_count": 8},
        "audio_rhythm_analysis": {"status": "ok", "tempo_bpm": 120},
        "rag_ready_text": "标题：测试\n封面语义：\n实体：测试",
    }
    (research_dir / "v3.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    settings = replace(
        SETTINGS,
        output_dir=output_dir,
        cache_dir=cache_dir,
    )
    calls: list[Path] = []

    def fake_analyze(path: Path, _settings) -> dict:
        calls.append(path)
        return {
            "status": "ok",
            "device": "cuda",
            "top_labels": [
                {"label": "movie scene", "label_zh": "影视画面", "score": 0.9}
            ],
        }

    result = backfill_openclip_from_outputs(
        settings,
        refresh_analytics=False,
        analyze=fake_analyze,
    )

    updated = json.loads(
        (research_dir / "v3.json").read_text(encoding="utf-8")
    )
    assert calls == [cover_path]
    assert result["updated"] == 1
    assert updated["cover_analysis"]["visual_semantics"]["device"] == "cuda"
    assert "封面语义：影视画面" in updated["rag_ready_text"]
    assert updated["scene_analysis"] == payload["scene_analysis"]
    assert updated["audio_rhythm_analysis"] == payload["audio_rhythm_analysis"]
    assert "OpenCLIP状态：ok" in (
        research_dir / "v3.md"
    ).read_text(encoding="utf-8")


def test_openclip_backfill_resumes_successful_items(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    video_id = "BV_READY"
    research_dir = output_dir / video_id
    cover_dir = cache_dir / "covers" / video_id
    research_dir.mkdir(parents=True)
    cover_dir.mkdir(parents=True)
    (cover_dir / "cover.jpg").write_bytes(b"fixture")
    payload = {
        "video_id": video_id,
        "cover_analysis": {
            "visual_semantics": {"status": "ok", "device": "cuda"},
        },
    }
    (research_dir / "v3.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )
    settings = replace(
        SETTINGS,
        output_dir=output_dir,
        cache_dir=cache_dir,
    )

    def should_not_run(_path: Path, _settings) -> dict:
        raise AssertionError("successful item should be skipped")

    result = backfill_openclip_from_outputs(
        settings,
        refresh_analytics=False,
        analyze=should_not_run,
    )

    assert result["already_ready"] == 1
    assert result["processed"] == 0


def test_openclip_backfill_limit_keeps_run_resumable(tmp_path: Path) -> None:
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    for index in range(3):
        video_id = f"BV_{index}"
        research_dir = output_dir / video_id
        cover_dir = cache_dir / "covers" / video_id
        research_dir.mkdir(parents=True)
        cover_dir.mkdir(parents=True)
        cover_path = cover_dir / "cover.jpg"
        cover_path.write_bytes(b"fixture")
        (research_dir / "v3.json").write_text(
            json.dumps(
                {
                    "video_id": video_id,
                    "comments_analysis": {},
                    "cover_analysis": {"image_path": str(cover_path)},
                    "title_stats": {},
                    "nlp_analysis": {},
                    "scene_analysis": {},
                    "audio_rhythm_analysis": {},
                }
            ),
            encoding="utf-8",
        )
    settings = replace(
        SETTINGS,
        output_dir=output_dir,
        cache_dir=cache_dir,
    )

    result = backfill_openclip_from_outputs(
        settings,
        limit=2,
        refresh_analytics=False,
        analyze=lambda _path, _settings: {"status": "ok", "top_labels": []},
    )

    assert result["processed"] == 2
    statuses = [
        json.loads(path.read_text(encoding="utf-8"))
        .get("cover_analysis", {})
        .get("visual_semantics", {})
        .get("status")
        for path in sorted(output_dir.rglob("v3.json"))
    ]
    assert statuses == ["ok", "ok", None]
