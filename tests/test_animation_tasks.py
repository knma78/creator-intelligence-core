from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
import wave
from pathlib import Path

from production.animation_plan import (
    AnimationPlanError, compile_plan, file_hash, orbit_state, save_compilation, text_hash,
)
from production.animation_scene import build_scene, visible_objects

ROOT = Path(__file__).resolve().parents[1]


class AnimationTaskTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads((ROOT/'tests/fixtures/animation_synthetic.json').read_text(encoding='utf-8'))

    def compile(self, source=None, **kwargs):
        return compile_plan(source or self.source, source_dir=ROOT, **kwargs)

    def test_deterministic_frames(self):
        self.assertEqual(self.compile(), self.compile())
        page = self.compile()['pages'][0]
        self.assertEqual(page['duration_frames'], 840)
        self.assertEqual([a['start_frame'] for a in page['actions']], [30,150,300,600])
        self.assertEqual(page['actions'][2]['end_frame'], 480)
        self.assertIn('未配音', self.compile()['warnings'][0])

    def test_changes_invalidate_text_and_anchors(self):
        n = self.source['pages'][0]['narration']
        n['text'] = '错误' + n['text']
        with self.assertRaisesRegex(AnimationPlanError, '指纹'):
            self.compile()
        n['sha256'] = text_hash(n['text'])
        with self.assertRaisesRegex(AnimationPlanError, '锚点文字'):
            self.compile()

    def test_invalid_inputs_fail_closed(self):
        mutations = [
            lambda s: s.update(schema_version='future'),
            lambda s: s.update(extra='silently ignored?'),
            lambda s: s['canvas'].update(fps=60),
            lambda s: s['pages'][0]['component'].update(name='anything'),
            lambda s: s['pages'][0]['component'].update(start_angle_deg=float('nan')),
            lambda s: s['pages'][0]['component'].update(sweep_deg=True),
            lambda s: s['pages'][0]['actions'][0].update(op='generate_video'),
            lambda s: s['pages'][0]['actions'][0].update(anchor='missing'),
            lambda s: s['pages'][0]['actions'][0].update(anchor=[]),
            lambda s: s['pages'][0]['narration'].update(timing_kind=[]),
            lambda s: s['pages'][0]['actions'][0].update(duration_ms=100),
            lambda s: s['pages'][0]['actions'][2].update(offset_ms=9000),
            lambda s: s['pages'][0]['narration']['anchors'][1].update(start_ms=0),
            lambda s: s['pages'][0]['narration']['anchors'][1].update(id='velocity'),
            lambda s: s['pages'].append(copy.deepcopy(s['pages'][0])),
            lambda s: s['pages'][0].update(id='../outside'),
            lambda s: s['pages'][0].update(title='超长标题'*30),
            lambda s: s['pages'][0].update(sources=[]),
        ]
        for mutate in mutations:
            source = copy.deepcopy(self.source)
            mutate(source)
            with self.subTest(source=source), self.assertRaises(AnimationPlanError):
                self.compile(source)

    def test_production_requires_audio_and_review(self):
        with self.assertRaisesRegex(AnimationPlanError, '真实音频'):
            self.compile(mode='production')

    def test_audio_integrity_duration_and_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            wav_path = root/'voice.wav'
            # Silent PCM is solely a test fixture, never delivered as narration.
            with wave.open(str(wav_path), 'wb') as wav:
                wav.setparams((1,2,8000,0,'NONE','not compressed'))
                wav.writeframes(b'\x00\x00'*8000*28)
            n = self.source['pages'][0]['narration']
            n.update(audio={'path':'voice.wav','sha256':file_hash(wav_path)}, timing_kind='reviewed', reviewer='test')
            result = compile_plan(self.source, source_dir=root, mode='production')
            self.assertEqual(result['warnings'], [])
            n['duration_ms'] = 29000
            with self.assertRaisesRegex(AnimationPlanError, '时长'):
                compile_plan(self.source, source_dir=root, mode='production')
            n['duration_ms'] = 28000
            n['audio']['sha256'] = 'bad'
            with self.assertRaisesRegex(AnimationPlanError, '指纹'):
                compile_plan(self.source, source_dir=root)
            n['audio']['path'] = '../voice.wav'
            with self.assertRaisesRegex(AnimationPlanError, '相对路径'):
                compile_plan(self.source, source_dir=root)

    def test_page_local_cache_and_later_offsets(self):
        second = copy.deepcopy(self.source['pages'][0])
        second['id'] = 'page-two'
        self.source['pages'].append(second)
        first = self.compile()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(save_compilation(first, root)['changed_pages'], ['newton-01','page-two'])
            self.assertEqual(save_compilation(first, root)['reused_pages'], ['newton-01','page-two'])
            self.source['pages'][0]['narration']['duration_ms'] = 30000
            changed = self.compile()
            self.assertNotEqual(first['pages'][0]['fingerprint'], changed['pages'][0]['fingerprint'])
            self.assertEqual(first['pages'][1]['fingerprint'], changed['pages'][1]['fingerprint'])
            self.assertEqual(changed['pages'][1]['global_start_frame'], 900)
            report = save_compilation(changed, root)
            self.assertEqual(report['changed_pages'], ['newton-01'])
            self.assertEqual(report['reused_pages'], ['page-two'])
            cache = next((root/'pages').glob('page-two-*.json'))
            cache.write_text('{}', encoding='utf-8')
            self.assertEqual(save_compilation(changed, root)['changed_pages'], ['page-two'])

    def test_existing_production_cli_exposes_animation(self):
        from tools.video_production import build_parser
        args = build_parser().parse_args(['animation','compile','plan.json','--output','out'])
        self.assertEqual(args.arguments, ['compile','plan.json','--output','out'])

    def test_orbit_geometry_and_arrow_directions(self):
        component = self.source['pages'][0]['component']
        for i in range(101):
            state = orbit_state(component, i/100)
            x,y = state['moon']; gx,gy = state['gravity']; vx,vy = state['velocity']
            self.assertAlmostEqual(math.hypot(x-865,y-350),150)
            self.assertAlmostEqual(gx*vx+gy*vy,0)
            self.assertLess((x-865)*gx+(y-350)*gy,0)

    def test_scene_has_single_moon_and_synchronized_arrows_at_every_frame(self):
        scene = build_scene(self.compile()['pages'][0])
        names = [x['name'] for x in scene['objects']]
        self.assertEqual(len(names),len(set(names)))
        for frame in range(840):
            current = [x['name'] for x in visible_objects(scene, frame)]
            self.assertEqual(sum(x.endswith('_moon') for x in current),1)
            self.assertEqual(sum(x.endswith('_velocity') for x in current),int(frame >= 30))
            self.assertEqual(sum(x.endswith('_gravity') for x in current),int(frame >= 150))
            self.assertEqual('conclusion' in current, frame >= 600)
        for item in scene['objects']:
            pos = item['position']
            self.assertGreaterEqual(pos['left'],0)
            self.assertGreaterEqual(pos['top'],0)
            self.assertLessEqual(pos['left']+pos['width'],1280)
            self.assertLessEqual(pos['top']+pos['height'],720)


if __name__ == '__main__':
    unittest.main()
