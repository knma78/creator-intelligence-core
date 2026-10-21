from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from config import Settings
from production.capcut_package import create_capcut_package
from production.contracts import ProductionManifest, RenderProfile
from production.edit_plan import (
    build_auto_edit_plan,
    list_production_sources,
)
from production.ffmpeg_renderer import (
    build_render_command,
    build_timeline_render_command,
)
from production.packaging import create_research_package
from production.qa import subtitle_metrics
from production.video_factory import VideoFactoryAdapter


class ProductionPackagingTests(unittest.TestCase):
    def test_package_copies_small_artifacts_and_references_source_media(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            cache = root / "cache"
            research = output / "video-1"
            video_cache = cache / "videos" / "video-1"
            research.mkdir(parents=True)
            video_cache.mkdir(parents=True)
            (research / "analysis.json").write_text(
                json.dumps(
                    {
                        "video_id": "video-1",
                        "title": "Demo",
                        "structure": [
                            {
                                "part": "hook",
                                "time_range": "00:00 - 00:12",
                                "summary": "Opening",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (research / "subtitle.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nDemo\n",
                encoding="utf-8",
            )
            source_video = video_cache / "video-1.mp4"
            source_video.write_bytes(b"not-a-real-video")
            (video_cache / "metadata.json").write_text(
                json.dumps({"video_path": str(source_video)}),
                encoding="utf-8",
            )
            settings = Settings(
                base_dir=root,
                output_dir=output,
                cache_dir=cache,
                logs_dir=root / "logs",
            )

            manifest_path = create_research_package(
                "video-1",
                settings=settings,
            )
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = ProductionManifest.from_dict(payload)

            self.assertEqual(manifest.title, "Demo")
            self.assertEqual(len(manifest.timeline), 1)
            source_asset = next(
                asset
                for asset in manifest.assets
                if asset.role == "source_video"
            )
            self.assertIsNone(source_asset.packaged_path)
            self.assertTrue(
                (manifest_path.parent / "research" / "analysis.json").is_file()
            )
            self.assertFalse((manifest_path.parent / "media").exists())

    def test_capcut_package_exports_only_editing_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            research = root / "research"
            research.mkdir()
            subtitle = research / "subtitle.srt"
            subtitle.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nDemo\n",
                encoding="utf-8",
            )
            manifest = ProductionManifest(
                job_id="demo",
                source_video_id="demo",
                title="Demo",
                assets=(),
            )
            payload = manifest.to_dict()
            payload["assets"] = [
                {
                    "role": "subtitles",
                    "source_path": str(subtitle),
                    "packaged_path": "research/subtitle.srt",
                    "media_type": "application/x-subrip",
                    "required": False,
                }
            ]
            manifest_path = root / "production_manifest.json"
            manifest_path.write_text(json.dumps(payload), encoding="utf-8")

            destination = create_capcut_package(manifest_path)

            self.assertTrue((destination / "subtitles.srt").is_file())
            self.assertTrue((destination / "capcut_package.json").is_file())
            self.assertTrue((destination / "README.txt").is_file())


class ProductionUtilityTests(unittest.TestCase):
    def test_auto_edit_plan_selects_timed_window_and_retimes_subtitles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            cache = root / "cache"
            research = output / "video-1"
            video_cache = cache / "videos" / "video-1"
            research.mkdir(parents=True)
            video_cache.mkdir(parents=True)
            source_video = video_cache / "video-1.mp4"
            source_video.write_bytes(b"source")
            (research / "analysis.json").write_text(
                json.dumps(
                    {
                        "title": "Plan demo",
                        "keywords": [{"word": "真相"}],
                        "structure": [
                            {
                                "part": "Hook",
                                "time_range": "00:10 - 00:18",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (research / "v3.json").write_text(
                json.dumps(
                    {
                        "scene_analysis": {
                            "status": "ok",
                            "scenes": [
                                {"start": 10, "end": 18},
                                {"start": 18, "end": 30},
                            ],
                        },
                        "audio_rhythm_analysis": {
                            "status": "ok",
                            "tempo_bpm": 120,
                            "silence_ratio": 0.05,
                        },
                    }
                ),
                encoding="utf-8",
            )
            blocks = []
            for index in range(20):
                start = index * 2
                end = start + 2
                text = (
                    "为什么真相竟然如此？"
                    if index == 5
                    else f"连续内容第{index}段"
                )
                blocks.append(
                    f"{index + 1}\n"
                    f"00:00:{start:02d},000 --> 00:00:{end:02d},000\n"
                    f"{text}"
                )
            (research / "subtitle.srt").write_text(
                "\n\n".join(blocks) + "\n",
                encoding="utf-8",
            )
            (video_cache / "metadata.json").write_text(
                json.dumps(
                    {
                        "video_path": str(source_video),
                        "duration": 40,
                    }
                ),
                encoding="utf-8",
            )
            settings = Settings(
                base_dir=root,
                output_dir=output,
                cache_dir=cache,
                logs_dir=root / "logs",
            )

            plan_path = build_auto_edit_plan(
                "video-1",
                target_seconds=16,
                settings=settings,
            )
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            sources = list_production_sources(settings)
            retimed = Path(plan["edit_subtitle_path"]).read_text(
                encoding="utf-8"
            )

            self.assertEqual(
                plan["strategy"],
                "research_guided_contiguous_window",
            )
            self.assertEqual(len(plan["segments"]), 1)
            self.assertGreater(plan["output_duration_seconds"], 10)
            self.assertTrue(plan["decision_inputs"]["analysis_ready"])
            self.assertTrue(plan["decision_inputs"]["enrichment_ready"])
            self.assertEqual(
                plan["decision_inputs"]["audio_rhythm"]["tempo_bpm"],
                120,
            )
            self.assertIn("00:00:00,000 -->", retimed)
            self.assertTrue(sources[0]["source_video_ready"])
            self.assertTrue(sources[0]["subtitle_ready"])

    def test_subtitle_metrics_detect_readability_limits(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            subtitle = Path(directory) / "subtitle.srt"
            subtitle.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n"
                "First line\nSecond line\nThird line\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\nShort\n",
                encoding="utf-8",
            )

            metrics = subtitle_metrics(subtitle)

            self.assertEqual(metrics["block_count"], 2)
            self.assertEqual(metrics["max_lines_per_block"], 3)
            self.assertEqual(metrics["max_chars_per_line"], 11)

    def test_subtitle_metrics_detect_invalid_and_overlapping_timing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            subtitle = Path(directory) / "subtitle.srt"
            subtitle.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nFirst\n\n"
                "2\n00:00:00,800 --> 00:00:01,400\nOverlap\n\n"
                "3\n00:00:02,000 --> 00:00:01,900\nInvalid\n",
                encoding="utf-8",
            )

            metrics = subtitle_metrics(subtitle)

            self.assertEqual(metrics["overlap_count"], 1)
            self.assertEqual(metrics["invalid_timing_count"], 1)
            self.assertEqual(metrics["last_end_seconds"], 1.4)

    def test_render_command_selects_nvenc_and_preserves_one_pass(self) -> None:
        command = build_render_command(
            ffmpeg_path="ffmpeg",
            source_video=Path("input.mp4"),
            output_path=Path("output.mp4"),
            profile=RenderProfile(width=1080, height=1920, fps=30),
            subtitle_path=Path("subtitle.srt"),
            use_nvenc=True,
        )

        self.assertIn("h264_nvenc", command)
        self.assertIn("+faststart", command)
        self.assertEqual(command.count("-i"), 1)
        self.assertTrue(any("subtitles=filename=" in value for value in command))

    def test_timeline_render_command_keeps_cut_decisions_in_filter(self) -> None:
        command = build_timeline_render_command(
            ffmpeg_path="ffmpeg",
            source_video=Path("input.mp4"),
            output_path=Path("output.mp4"),
            segments=[
                {
                    "source_start_seconds": 10,
                    "source_end_seconds": 25,
                },
                {
                    "source_start_seconds": 40,
                    "source_end_seconds": 55,
                },
            ],
            profile=RenderProfile(width=1080, height=1920, fps=30),
            subtitle_path=Path("subtitle.srt"),
            use_nvenc=True,
        )
        filter_graph = command[command.index("-filter_complex") + 1]

        self.assertIn("trim=start=10.000:end=25.000", filter_graph)
        self.assertIn("trim=start=40.000:end=55.000", filter_graph)
        self.assertIn("concat=n=2:v=1:a=1", filter_graph)
        self.assertIn("subtitles=filename=", filter_graph)

    def test_factory_adapter_reads_declared_scripts_without_running_npm(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "package.json").write_text(
                json.dumps(
                    {
                        "name": "factory-test",
                        "scripts": {
                            "check": "hyperframes lint",
                            "render": "hyperframes render",
                        },
                    }
                ),
                encoding="utf-8",
            )

            state = VideoFactoryAdapter(root).inspect()

            self.assertEqual(state["package_name"], "factory-test")
            self.assertTrue(state["has_check"])
            self.assertTrue(state["has_final_render"])


if __name__ == "__main__":
    unittest.main()
