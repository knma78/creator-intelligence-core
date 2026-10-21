from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from production.capcut_bridge import load_plan, validate_name, validate_plan


class CapCutPlanTests(unittest.TestCase):
    def test_rejects_path_traversal_and_windows_reserved_names(self):
        for name in ('../draft', '..', 'C:\\draft', 'a/b', 'NUL', 'COM1.txt', 'bad.'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_name(name)

    def test_final_storyboard_converts_timing_and_relative_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'image.png').write_bytes(b'placeholder')
            (root / 'audio.wav').write_bytes(b'placeholder')
            (root / 'captions.srt').write_text('1\n00:00:00,100 --> 00:00:01,800\n测试字幕\n', encoding='utf-8')
            path = root / 'storyboard.json'
            path.write_text(json.dumps({
                'preview': False, 'output_duration_seconds': 2,
                'narration_path': 'audio.wav', 'subtitle_path': 'captions.srt',
                'render_profile': {'width': 720, 'height': 1280, 'fps': 25},
                'scenes': [{'output_start_seconds': 0, 'output_end_seconds': 2,
                            'visual': {'path': 'image.png'}}],
            }), encoding='utf-8')
            p = load_plan(path, 'draft')
            self.assertEqual(p['clips'][0]['duration'], 2)
            self.assertEqual(p['clips'][0]['path'], str(root / 'image.png'))
            self.assertEqual(p['captions'][0], {'start': .1, 'end': 1.8, 'text': '测试字幕'})
            self.assertEqual((p['width'], p['fps']), (720, 25))

    def test_overlapping_captions_and_nonfinite_timing_rejected(self):
        p = {'name': 'draft', 'width': 1080, 'height': 1920, 'fps': 30,
             'clips': [{'start': 0, 'duration': 3}], 'audios': [],
             'captions': [{'start': 0, 'end': 2, 'text': 'one'}, {'start': 1, 'end': 3, 'text': 'two'}]}
        with self.assertRaises(ValueError):
            validate_plan(p)
        p['captions'] = []
        p['clips'][0]['duration'] = float('nan')
        with self.assertRaises(ValueError):
            validate_plan(p)


class CapCutDraftTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import ccmcp
        except ImportError:
            raise unittest.SkipTest('Run with .venv-capcut for real draft integration tests.')

    def test_real_draft_preserves_media_tracks_and_rejects_overwrite(self):
        from PIL import Image
        import wave
        from production.capcut_bridge import build_draft
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new('RGB', (64, 64), 'blue').save(root / 'frame.png')
            with wave.open(str(root / 'voice.wav'), 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b'\x00\x00' * 32000)
            plan = root / 'timeline.json'
            plan.write_text(json.dumps({
                'name': 'unit-draft', 'clips': [{'path': 'frame.png', 'start': 0, 'duration': 2}],
                'audios': [{'path': 'voice.wav', 'start': 0, 'duration': 2}],
                'captions': [{'start': 0, 'end': 2, 'text': 'Editable captions'}],
            }), encoding='utf-8')
            dest = root / 'drafts'
            with patch('production.capcut_bridge.is_capcut_running', return_value=False):
                report = build_draft(plan, destination=dest)
                content = Path(report['saved'])
                before = content.read_bytes()
                payload = json.loads(before)
                self.assertEqual(payload['platform']['app_source'], 'cc')
                self.assertEqual({t['type'] for t in payload['tracks']}, {'video', 'audio', 'text'})
                self.assertEqual(payload['duration'], 2_000_000)
                self.assertIn('Editable captions', payload['materials']['texts'][0]['content'])
                meta = json.loads(content.with_name('draft_meta_info.json').read_text(encoding='utf-8'))
                self.assertEqual(meta['draft_fold_path'], content.parent.as_posix())
                with self.assertRaises(FileExistsError):
                    build_draft(plan, destination=dest)
                self.assertEqual(content.read_bytes(), before)

    def test_refuses_write_while_capcut_running(self):
        from ccmcp import session
        from production.capcut_bridge import save_new_draft
        with tempfile.TemporaryDirectory() as tmp, patch('production.capcut_bridge.is_capcut_running', return_value=True):
            with self.assertRaises(RuntimeError):
                save_new_draft(session.new('busy'), Path(tmp))
            self.assertFalse((Path(tmp) / 'busy').exists())


if __name__ == '__main__':
    unittest.main()
