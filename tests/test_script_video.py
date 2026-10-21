from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from config import Settings
from production.contracts import RenderProfile
from production.script_video import (
    compact_caption_cues,
    derive_rough_template,
    estimate_caption_cues,
    normalize_caption_cues,
    parse_vtt,
    preview_script_video_plan,
    script_video_runtime_status,
    split_script,
    write_srt,
    _render_storyboard,
    _run_cancellable_process,
)


class ScriptVideoTests(unittest.TestCase):
    def _write_test_cover(self, path: Path) -> None:
        Image.new("RGB", (2, 2), (24, 48, 96)).save(path, format="PNG")

    def _settings(self, root: Path) -> Settings:
        return Settings(
            base_dir=root,
            output_dir=root / "output",
            cache_dir=root / "cache",
            logs_dir=root / "logs",
            edge_tts_path=str(root / "edge-tts.exe"),
            video_ffmpeg_path=str(root / "ffmpeg.exe"),
            ffprobe_path=str(root / "ffprobe.exe"),
        )

    def test_template_and_storyboard_use_existing_distillation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self._settings(root)
            research = settings.output_dir / "video-1"
            research.mkdir(parents=True)
            self._write_test_cover(research / "cover.jpg")
            (research / "analysis.json").write_text(
                json.dumps(
                    {
                        "title": "火星生命",
                        "one_sentence_summary": "水熊虫能否在火星生存",
                        "keywords": [{"word": "火星"}, {"word": "生命"}],
                        "structure": [{"part": "hook"}],
                    }
                ),
                encoding="utf-8",
            )
            (research / "v3.json").write_text(
                json.dumps(
                    {
                        "scene_analysis": {
                            "scenes": [
                                {"start": 0, "end": 3},
                                {"start": 3, "end": 7},
                            ]
                        },
                        "audio_rhythm_analysis": {"tempo_bpm": 110},
                    }
                ),
                encoding="utf-8",
            )

            template = derive_rough_template(settings)
            plan = preview_script_video_plan(
                "水熊虫真的能在火星活下来吗？这个问题需要从火星环境说起。",
                title="火星生命测试",
                settings=settings,
            )

            self.assertEqual(
                template["derived_from"]["research_directories"],
                1,
            )
            self.assertEqual(template["derived_from"]["scene_samples"], 2)
            self.assertEqual(
                plan["strategy"],
                "distilled_rules_narrated_storyboard",
            )
            self.assertFalse(plan["decision_inputs"]["agent_required"])
            self.assertEqual(
                plan["scenes"][0]["visual"]["source_id"],
                "video-1",
            )

    def test_vtt_is_compacted_and_written_as_nonempty_srt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            vtt = root / "narration.vtt"
            vtt.write_text(
                "WEBVTT\n\n"
                "00:00:00.000 --> 00:00:01.000\n水熊虫\n\n"
                "00:00:01.050 --> 00:00:02.000\n真的能活吗？\n\n"
                "00:00:04.000 --> 00:00:05.000\n答案并不简单。\n",
                encoding="utf-8",
            )

            cues = parse_vtt(vtt)
            compacted = compact_caption_cues(cues)
            output = write_srt(compacted, root / "captions.srt")
            text = output.read_text(encoding="utf-8")

            self.assertEqual(len(cues), 3)
            self.assertEqual(len(compacted), 2)
            self.assertIn("水熊虫真的能活吗？", text)
            self.assertGreater(output.stat().st_size, 0)

    def test_vtt_keeps_english_line_spacing_and_skips_reverse_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            vtt = Path(directory) / "mixed.vtt"
            vtt.write_text(
                "WEBVTT\n\n"
                "cue-1\n00:00:00,000 --> 00:00:01,000\n"
                "<b>Hello</b>\nworld\n\n"
                "00:00:03.000 --> 00:00:02.000\ninvalid\n",
                encoding="utf-8-sig",
            )

            cues = parse_vtt(vtt)

            self.assertEqual(len(cues), 1)
            self.assertEqual(cues[0]["text"], "Hello world")

    def test_estimated_captions_span_exact_audio_duration(self) -> None:
        cues = estimate_caption_cues(
            "第一句介绍问题。第二句解释背景。第三句给出结论。",
            12.5,
        )

        self.assertEqual(cues[0]["start"], 0)
        self.assertEqual(cues[-1]["end"], 12.5)
        self.assertTrue(
            all(
                current["end"] == following["start"]
                for current, following in zip(cues, cues[1:])
            )
        )

    def test_normalized_captions_are_bounded_and_monotonic(self) -> None:
        cues = [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "这是一条明显超过单条字幕显示上限的中文旁白，需要拆成多条短字幕。",
            },
            {
                "start": 1.5,
                "end": 3.0,
                "text": "重叠的下一条字幕也必须顺延。",
            },
        ]

        normalized = normalize_caption_cues(
            cues,
            max_display_units=24,
        )

        def display_units(text: str) -> int:
            return sum(
                2 if "\u3400" <= character <= "\u9fff" else 1
                for character in text
            )

        self.assertGreater(len(normalized), len(cues))
        self.assertTrue(
            all(display_units(cue["text"]) <= 24 for cue in normalized)
        )
        self.assertTrue(
            all(float(cue["end"]) > float(cue["start"]) for cue in normalized)
        )
        self.assertTrue(
            all(
                float(current["end"]) <= float(following["start"])
                for current, following in zip(normalized, normalized[1:])
            )
        )

    def test_storyboard_uses_gradient_when_no_asset_terms_match(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self._settings(root)
            research = settings.output_dir / "video-1"
            research.mkdir(parents=True)
            self._write_test_cover(research / "cover.jpg")
            (research / "analysis.json").write_text(
                json.dumps(
                    {
                        "title": "深海珊瑚纪录片",
                        "one_sentence_summary": "观察海底生态",
                        "keywords": [{"word": "珊瑚"}, {"word": "海洋"}],
                    }
                ),
                encoding="utf-8",
            )

            plan = preview_script_video_plan(
                "量子计算机如何帮助破解复杂问题？我们从量子比特的基本原理开始说明。",
                settings=settings,
            )

            self.assertGreater(plan["decision_inputs"]["asset_catalog_count"], 0)
            self.assertTrue(
                all(
                    scene["visual"]["type"] == "local_gradient"
                    for scene in plan["scenes"]
                )
            )

    def test_storyboard_recognizes_douyin_cover_jpeg(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self._settings(root)
            research = settings.output_dir / "douyin-video-1"
            research.mkdir(parents=True)
            cover = research / "cover.jpeg"
            self._write_test_cover(cover)
            (research / "analysis.json").write_text(
                json.dumps(
                    {
                        "title": "火星探索",
                        "one_sentence_summary": "寻找火星生命",
                        "keywords": [{"word": "火星"}, {"word": "生命"}],
                    }
                ),
                encoding="utf-8",
            )

            plan = preview_script_video_plan(
                "火星上是否存在生命？这段视频将介绍最新的火星探索线索。",
                settings=settings,
            )

            self.assertEqual(plan["decision_inputs"]["asset_catalog_count"], 1)
            self.assertEqual(
                plan["scenes"][0]["visual"]["source_id"],
                "douyin-video-1",
            )
            self.assertEqual(
                Path(plan["scenes"][0]["visual"]["path"]),
                cover.resolve(),
            )

    def test_script_split_and_runtime_fallback_are_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self._settings(root)
            chunks = split_script(
                "第一句介绍问题。第二句解释背景。第三句给出答案。",
                target_units=14,
            )
            status = script_video_runtime_status(settings)

            self.assertGreaterEqual(len(chunks), 2)
            self.assertFalse(status["available"])
            self.assertEqual(status["visuals"]["fallback"], "local-gradient")
            self.assertFalse(status["agent_required"])

    def test_storyboard_uses_ocr_and_openclip_as_auditable_signals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self._settings(root)
            for source_id, label, label_zh in (
                ("landscape", "landscape", "风景画面"),
                ("gameplay", "gameplay", "游戏画面"),
            ):
                research = settings.output_dir / source_id
                research.mkdir(parents=True)
                self._write_test_cover(research / "cover.jpg")
                (research / "analysis.json").write_text(
                    json.dumps(
                        {
                            "title": "红色星球探索",
                            "keywords": [{"word": "火星"}],
                        }
                    ),
                    encoding="utf-8",
                )
                (research / "v3.json").write_text(
                    json.dumps(
                        {
                            "cover_analysis": {
                                "ocr": {"status": "ok", "text": "火星生命线索"},
                                "visual_semantics": {
                                    "status": "ok",
                                    "top_labels": [
                                        {
                                            "label": label,
                                            "label_zh": label_zh,
                                            "score": 0.9,
                                        }
                                    ],
                                },
                            }
                        }
                    ),
                    encoding="utf-8",
                )

            plan = preview_script_video_plan(
                "火星上的生命是否存在？我们从红色星球的自然环境开始分析。",
                settings=settings,
            )
            visual = plan["scenes"][0]["visual"]

            self.assertEqual(visual["source_id"], "landscape")
            self.assertEqual(plan["decision_inputs"]["openclip_asset_count"], 2)
            self.assertIn("火星", visual["matched_terms"])
            self.assertTrue(
                any("OpenCLIP" in reason for reason in visual["match_reasons"])
            )
            self.assertEqual(visual["fit_mode"], "contain_blurred_background")

    def test_generic_words_do_not_force_unrelated_cover(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self._settings(root)
            research = settings.output_dir / "generic-video"
            research.mkdir(parents=True)
            self._write_test_cover(research / "cover.jpg")
            (research / "analysis.json").write_text(
                json.dumps(
                    {
                        "title": "这个视频开始介绍一个内容",
                        "one_sentence_summary": "看看这个内容如何进行",
                    }
                ),
                encoding="utf-8",
            )

            plan = preview_script_video_plan(
                "火星生命与红色星球辐射之间有什么关系？我们只讨论太空环境中的生存条件。",
                settings=settings,
            )

            self.assertTrue(
                all(
                    scene["visual"]["type"] == "local_gradient"
                    for scene in plan["scenes"]
                )
            )
            self.assertEqual(plan["decision_inputs"]["fallback_scene_count"], len(plan["scenes"]))
            self.assertEqual(plan["scenes"][0]["narrative_role"], "hook")
            self.assertEqual(plan["scenes"][-1]["narrative_role"], "payoff")

    def test_single_generic_keyword_is_not_counted_as_relevant_material(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self._settings(root)
            relevant = settings.output_dir / "mars-life"
            weak = settings.output_dir / "red-device"
            for research in (relevant, weak):
                research.mkdir(parents=True)
                self._write_test_cover(research / "cover.jpg")
            (relevant / "analysis.json").write_text(
                json.dumps(
                    {
                        "title": "火星生命和液态水",
                        "keywords": [
                            {"word": "火星"},
                            {"word": "生命"},
                            {"word": "液态水"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (weak / "analysis.json").write_text(
                json.dumps(
                    {
                        "title": "红色手机外观测试",
                        "keywords": [{"word": "红色"}],
                    }
                ),
                encoding="utf-8",
            )

            plan = preview_script_video_plan(
                "火星上是否存在生命？我们检查液态水与辐射留下的线索。",
                settings=settings,
            )
            selected_ids = {
                scene["visual"].get("source_id")
                for scene in plan["scenes"]
                if scene["visual"]["type"] == "distilled_cover"
            }

            self.assertNotIn("red-device", selected_ids)
            self.assertIn("mars-life", selected_ids)
            self.assertEqual(
                plan["decision_inputs"]["unique_matched_asset_count"],
                1,
            )

    def test_broken_cover_is_skipped_before_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self._settings(root)
            research = settings.output_dir / "broken-source"
            research.mkdir(parents=True)
            (research / "cover.jpg").write_bytes(b"not-an-image")
            (research / "analysis.json").write_text(
                json.dumps(
                    {
                        "title": "Mars science",
                        "keywords": [{"word": "Mars"}],
                    }
                ),
                encoding="utf-8",
            )

            plan = preview_script_video_plan(
                "Mars science needs a usable visual before it can be selected.",
                settings=settings,
            )

            self.assertEqual(plan["decision_inputs"]["asset_catalog_count"], 0)
            self.assertTrue(
                all(
                    scene["visual"]["type"] == "local_gradient"
                    for scene in plan["scenes"]
                )
            )

    def test_english_caption_splitting_preserves_whole_words(self) -> None:
        cues = normalize_caption_cues(
            [
                {
                    "start": 0,
                    "end": 4,
                    "text": "Native listeners should understand every sentence without awkward word breaks.",
                }
            ],
            max_display_units=24,
        )

        joined = " ".join(cue["text"] for cue in cues)
        self.assertEqual(
            joined,
            "Native listeners should understand every sentence without awkward word breaks.",
        )
        self.assertNotIn("listener s", joined)

    def test_cancellable_process_drains_large_stderr_without_hanging(self) -> None:
        return_code, _stdout, stderr = _run_cancellable_process(
            [
                sys.executable,
                "-c",
                "import sys; [print('x' * 200, file=sys.stderr) for _ in range(10000)]",
            ],
            cancel_requested=None,
            cancel_message="cancelled",
            timeout_seconds=15,
            timeout_message="timed out",
        )

        self.assertEqual(return_code, 0)
        self.assertGreater(len(stderr), 0)
        self.assertLess(len(stderr), 60_000)

    def test_storyboard_render_command_preserves_full_cover_without_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self._settings(root)
            cover = root / "cover.png"
            narration = root / "narration.mp3"
            subtitle = root / "captions.srt"
            output = root / "output" / "rough.mp4"
            output.parent.mkdir(parents=True)
            self._write_test_cover(cover)
            narration.write_bytes(b"mock-audio")
            subtitle.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nTest\n",
                encoding="utf-8",
            )
            storyboard = {
                "strategy": "test",
                "output_duration_seconds": 2.0,
                "scenes": [
                    {
                        "duration_seconds": 2.0,
                        "visual": {
                            "type": "research_cover",
                            "path": str(cover),
                        },
                    }
                ],
            }
            captured: list[str] = []

            def fake_render(
                command: list[str],
                **_kwargs: object,
            ) -> tuple[int, str]:
                captured.extend(command)
                Path(command[-1]).write_bytes(b"simulated-render-artifact")
                return 0, ""

            with (
                patch(
                    "production.script_video.inspect_ffmpeg_runtime",
                    return_value={"available": True, "nvenc_validated": False},
                ),
                patch(
                    "production.script_video._run_ffmpeg_cancellable",
                    side_effect=fake_render,
                ),
            ):
                result = _render_storyboard(
                    storyboard,
                    narration_path=narration,
                    subtitle_path=subtitle,
                    output_path=output,
                    profile=RenderProfile(width=360, height=640, fps=24),
                    cancel_requested=None,
                    progress_callback=None,
                    settings=settings,
                )

            filter_graph = captured[captured.index("-filter_complex") + 1]
            self.assertEqual(result, output)
            self.assertIn("boxblur", filter_graph)
            self.assertIn("force_original_aspect_ratio=decrease", filter_graph)
            self.assertIn("overlay=(W-w)/2:(H-h)/2", filter_graph)


if __name__ == "__main__":
    unittest.main()
