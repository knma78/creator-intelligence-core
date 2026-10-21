from __future__ import annotations

import importlib.util
import json
import math
import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest.mock import patch

from analyzer.audio_rhythm import analyze_audio_rhythm
from analyzer.visual_semantics import analyze_image_semantics
from config import Settings
from infrastructure.analytics_store import (
    backfill_analytics_from_outputs,
    load_analytics_evidence,
    persist_video_analysis,
)
from models import AnalysisResult, Transcript, Video
from rag.knowledge_base import (
    _merge_hybrid_results,
    build_knowledge_base,
    search_knowledge_base,
)
from rag.vector_store import vector_backend_status


class DuckDBAnalyticsStoreTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("duckdb"), "duckdb not installed")
    def test_backfills_existing_outputs_incrementally(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            research = root / "output" / "video-legacy"
            metadata_dir = root / "cache" / "videos" / "video-legacy"
            research.mkdir(parents=True)
            metadata_dir.mkdir(parents=True)
            (research / "analysis.json").write_text(
                json.dumps(
                    {
                        "video_id": "video-legacy",
                        "title": "Legacy",
                        "one_sentence_summary": "summary",
                        "hook": {},
                        "structure": [],
                        "transitions": [],
                        "emotion": {},
                        "rhythm": {},
                        "keywords": [],
                        "learnings": [],
                    }
                ),
                encoding="utf-8",
            )
            (research / "subtitle.txt").write_text(
                "legacy transcript",
                encoding="utf-8",
            )
            (research / "v3.json").write_text(
                json.dumps(
                    {
                        "audio_rhythm_analysis": {
                            "status": "ok",
                            "tempo_bpm": 110,
                        }
                    }
                ),
                encoding="utf-8",
            )
            (metadata_dir / "metadata.json").write_text(
                json.dumps(
                    {
                        "video_id": "video-legacy",
                        "source_url": "local.mp4",
                        "platform": "local",
                        "title": "Legacy",
                    }
                ),
                encoding="utf-8",
            )
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )

            first = backfill_analytics_from_outputs(settings)
            second = backfill_analytics_from_outputs(settings)

            self.assertEqual(first["updated"], 1)
            self.assertEqual(second["updated"], 0)
            self.assertEqual(second["skipped"], 1)
            self.assertEqual(
                load_analytics_evidence(settings)["summary"]["video_count"],
                1,
            )

    @unittest.skipUnless(importlib.util.find_spec("duckdb"), "duckdb not installed")
    def test_persists_joinable_video_intelligence(self) -> None:
        import duckdb

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
            video = Video(
                source_url="local.mp4",
                platform="local",
                video_id="video-1",
                title="Test video",
                author="Tester",
                duration=12.5,
            )
            transcript = Transcript(
                video_id="video-1",
                text="test transcript",
                source="local",
                text_path=root / "subtitle.txt",
            )
            analysis = AnalysisResult(
                video_id="video-1",
                title="Test video",
                one_sentence_summary="summary",
                hook={"type": "question"},
                structure=[],
                transitions=[],
                emotion={},
                rhythm={"density": 1},
                keywords=[{"word": "test", "count": 1}],
                learnings=["learning"],
            )
            enrichment = {
                "cover_analysis": {
                    "visual_semantics": {"status": "ok", "embedding": [0.1, 0.2]}
                },
                "scene_analysis": {
                    "status": "ok",
                    "scene_count": 4,
                    "average_scene_duration": 3.1,
                    "sample_count": 8,
                },
                "audio_rhythm_analysis": {"status": "ok", "tempo_bpm": 120.0},
            }

            status = persist_video_analysis(
                video,
                transcript,
                analysis,
                enrichment,
                settings,
            )

            self.assertEqual(status["status"], "ok")
            connection = duckdb.connect(str(settings.analytics_database_path))
            try:
                row = connection.execute(
                    """
                    SELECT title, transcript_chars, summary, audio_rhythm_json
                    FROM video_intelligence
                    WHERE video_id = ?
                    """,
                    ["video-1"],
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(row[:3], ("Test video", 15, "summary"))
            self.assertIn('"tempo_bpm": 120.0', str(row[3]))
            evidence = load_analytics_evidence(settings)
            self.assertEqual(evidence["status"], "ok")
            self.assertEqual(evidence["summary"]["video_count"], 1)
            self.assertEqual(evidence["summary"]["audio_coverage"], 1.0)
            self.assertEqual(evidence["summary"]["scene_coverage"], 1.0)
            ability_keys = {
                key
                for capability in evidence["records"][0]["capabilities"]
                for key in capability["ability_keys"]
            }
            self.assertEqual(
                ability_keys,
                {"audio", "editing", "camera", "visual", "thumbnail"},
            )

    def test_structured_analytics_enters_lexical_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "output"
            output.mkdir()
            settings = Settings(
                base_dir=root,
                output_dir=output,
                cache_dir=root / "cache",
                logs_dir=root / "logs",
                rag_search_backend="lexical",
            )
            analytics = {
                "status": "ok",
                "database_path": str(root / "analytics.duckdb"),
                "records": [
                    {
                        "video_id": "video-1",
                        "title": "节奏样本",
                        "author": "Tester",
                        "capabilities": [
                            {
                                "ability_keys": ["audio"],
                                "category": "structured_audio_rhythm",
                                "metrics": {"tempo_bpm": 120.0},
                            }
                        ],
                    }
                ],
            }
            index_path = root / "index.json"
            with patch(
                "rag.knowledge_base.load_analytics_evidence",
                return_value=analytics,
            ):
                build_knowledge_base(output, index_path, settings)

            payload = json.loads(index_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["analytics_document_count"], 1)
            results = search_knowledge_base(
                "tempo_bpm",
                index_path,
                settings=settings,
            )
            self.assertEqual(results[0]["video_id"], "video-1")

    def test_hybrid_search_keeps_exact_structured_evidence_visible(self) -> None:
        lexical = [
            {
                "chunk_id": "video-1:analytics",
                "video_id": "video-1",
                "document_type": "structured_analytics",
                "score": 0.1,
            }
        ]
        vector = [
            {
                "chunk_id": "video-2:0",
                "video_id": "video-2",
                "document_type": "video_text",
                "score": 0.8,
            }
        ]

        results = _merge_hybrid_results(lexical, vector, 2)

        self.assertEqual(results[0]["video_id"], "video-1")

    def test_vector_manifest_becomes_stale_when_lexical_index_changes(self) -> None:
        from infrastructure.artifacts import file_sha256

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
            )
            lexical = settings.knowledge_base_dir / "index.json"
            manifest = settings.vector_knowledge_base_dir / "manifest.json"
            lexical.parent.mkdir(parents=True)
            manifest.parent.mkdir(parents=True)
            lexical.write_text('{"documents":[]}', encoding="utf-8")
            manifest.write_text(
                json.dumps(
                    {
                        "version": 2,
                        "embedding_model": settings.sentence_transformer_model,
                        "lexical_index_sha256": file_sha256(lexical),
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(vector_backend_status(settings)["ready"])

            lexical.write_text('{"documents":[{"id":"new"}]}', encoding="utf-8")

            status = vector_backend_status(settings)
            self.assertFalse(status["ready"])
            self.assertTrue(status["stale"])


class OpenCLIPAnalysisTests(unittest.TestCase):
    def test_disabled_backend_is_fail_soft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
                openclip_enabled=False,
            )
            result = analyze_image_semantics(root / "missing.jpg", settings)
        self.assertEqual(result["status"], "skipped")

    def test_missing_local_weights_skips_without_loading_model(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "cover.png"
            Image.new("RGB", (8, 8), "red").save(image_path)
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
                openclip_allow_download=False,
            )
            with patch(
                "analyzer.visual_semantics._load_model_bundle",
            ) as load_model:
                result = analyze_image_semantics(image_path, settings)

        self.assertEqual(result["status"], "skipped")
        self.assertIn("not cached", result["reason"])
        load_model.assert_not_called()

    @unittest.skipUnless(importlib.util.find_spec("torch"), "torch not installed")
    def test_returns_ranked_labels_and_normalized_embedding(self) -> None:
        import torch
        from PIL import Image

        class FakeModel:
            def encode_image(self, _image):
                return torch.tensor([[3.0, 4.0]])

            def encode_text(self, tokens):
                return torch.tensor([[1.0, 0.0], [0.0, 1.0]])[: len(tokens)]

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = root / "cover.png"
            Image.new("RGB", (8, 8), "red").save(image_path)
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
                openclip_labels=("talking head", "anime illustration"),
                openclip_top_k=2,
                openclip_allow_download=True,
            )
            bundle = (
                FakeModel(),
                lambda _image: torch.ones((3, 2, 2)),
                lambda labels: torch.ones((len(labels), 1), dtype=torch.long),
            )
            with patch(
                "analyzer.visual_semantics._load_model_bundle",
                return_value=bundle,
            ):
                result = analyze_image_semantics(image_path, settings)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["top_labels"][0]["label"], "anime illustration")
        self.assertAlmostEqual(
            math.sqrt(sum(value * value for value in result["embedding"])),
            1.0,
            places=5,
        )


class LibrosaRhythmTests(unittest.TestCase):
    def test_disabled_backend_is_fail_soft(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
                audio_rhythm_enabled=False,
            )
            result = analyze_audio_rhythm(root / "missing.mp4", "video-1", settings)
        self.assertEqual(result["status"], "skipped")

    @unittest.skipUnless(importlib.util.find_spec("librosa"), "librosa not installed")
    def test_extracts_acoustic_metrics_from_waveform(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wave_path = root / "tone.wav"
            sample_rate = 16000
            samples = array(
                "h",
                (
                    int(10000 * math.sin(2 * math.pi * 440 * index / sample_rate))
                    for index in range(sample_rate * 2)
                ),
            )
            with wave.open(str(wave_path), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(sample_rate)
                stream.writeframes(samples.tobytes())
            settings = Settings(
                base_dir=root,
                output_dir=root / "output",
                cache_dir=root / "cache",
                logs_dir=root / "logs",
                audio_rhythm_sample_rate=sample_rate,
                audio_rhythm_max_seconds=10,
            )
            with patch(
                "analyzer.audio_rhythm.extract_audio",
                return_value=wave_path,
            ):
                result = analyze_audio_rhythm(wave_path, "video-1", settings)

        self.assertEqual(result["status"], "ok")
        self.assertGreater(result["mean_rms"], 0)
        self.assertGreater(result["spectral_centroid_hz"], 0)


if __name__ == "__main__":
    unittest.main()
