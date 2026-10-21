from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from production.animation_plan import compile_plan
from production.animation_scene import build_scene
from production.animation_pptx import NS, audit_pptx, unlock_generated_shapes

ROOT = Path(__file__).resolve().parents[1]


def element(parent, tag, **attrs):
    prefix, name = tag.split(':')
    return ET.SubElement(parent, '{'+NS[prefix]+'}'+name, {k:str(v) for k,v in attrs.items()})


class NativeTimingAuditTests(unittest.TestCase):
    def setUp(self):
        source = json.loads((ROOT/'tests/fixtures/animation_synthetic.json').read_text(encoding='utf-8'))
        page = compile_plan(source, source_dir=ROOT)['pages'][0]
        self.scene = build_scene(page)
        self.bundle = {'pages': [{'page':page,'scene':self.scene}]}

    def fixture(self, path, *, delay_delta=0, angle_delta=0, centre_delta=0, transition=28000):
        root = ET.Element('{'+NS['p']+'}sld')
        ids = {}
        for i, obj in enumerate(self.scene['objects'], 1):
            ids[obj['name']] = i
            element(root, 'p:cNvPr', id=i, name=obj['name'])
        group = element(root, 'p:grpSp')
        nv = element(group, 'p:nvGrpSpPr')
        element(nv, 'p:cNvPr', id=99, name='orbit_rig')
        ids['orbit_rig'] = 99
        xfrm = element(element(group, 'p:grpSpPr'), 'a:xfrm')
        element(xfrm, 'a:off', x=605*9525+centre_delta, y=90*9525)
        element(xfrm, 'a:ext', cx=520*9525, cy=520*9525)
        for name, intervals in self.scene['visibility'].items():
            for start,end in intervals:
                for frame,value in [(start,'visible'),(end,'hidden')]:
                    if frame == 0 or frame == self.scene['duration_frames']:
                        continue
                    effect = element(root, 'p:cTn', presetClass='entr' if value=='visible' else 'exit')
                    element(element(effect, 'p:stCondLst'), 'p:cond', delay=round(frame*1000/30)+delay_delta)
                    setting = element(effect, 'p:set')
                    element(setting, 'p:spTgt', spid=ids[name])
                    element(element(setting, 'p:to'), 'p:strVal', val=value)
        effect = element(root, 'p:cTn', presetClass='emph')
        element(element(effect, 'p:stCondLst'), 'p:cond', delay=10000)
        rot = element(effect,'p:animRot',by=6000000+angle_delta)
        behaviour = element(rot,'p:cBhvr')
        element(behaviour,'p:cTn',dur=6000)
        element(behaviour,'p:spTgt',spid=99)
        element(root,'p:transition',advClick=0,advTm=transition)
        deck = ET.Element('{'+NS['p']+'}presentation')
        element(element(deck,'p:sldIdLst'),'p:sldId',id=1)
        with ZipFile(path,'w') as archive:
            archive.writestr('ppt/presentation.xml',ET.tostring(deck))
            archive.writestr('ppt/slides/slide1.xml',ET.tostring(root))

    def test_exact_contract_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'fixture.pptx'
            self.fixture(path)
            report=audit_pptx(path,self.bundle)
            self.assertTrue(report['passed'])
            self.assertEqual(report['pages'][0]['verified_rotations'],1)

    def test_saved_timing_rotation_and_centre_regressions_fail(self):
        for change in [{'delay_delta':1000},{'angle_delta':60000},{'centre_delta':9525},{'transition':29000}]:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'fixture.pptx'
                self.fixture(path,**change)
                with self.assertRaises(ValueError):
                    audit_pptx(path,self.bundle)

    def test_unlock_preserves_original_and_unrelated_members(self):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory)/'source.pptx', Path(directory)/'target.pptx'
            with ZipFile(source,'w') as archive:
                archive.writestr('ppt/slides/slide1.xml',b'<a:spLocks noGrp="1" other="x"/>')
                archive.writestr('kept.txt',b'unchanged')
            before = source.read_bytes()
            unlock_generated_shapes(source,target)
            self.assertEqual(source.read_bytes(),before)
            with ZipFile(target) as archive:
                self.assertIn(b'noGrp="0"',archive.read('ppt/slides/slide1.xml'))
                self.assertEqual(archive.read('kept.txt'),b'unchanged')
            with self.assertRaises(FileExistsError):
                unlock_generated_shapes(source,target)
