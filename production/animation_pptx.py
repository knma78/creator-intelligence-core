"""Read back native PowerPoint timing instead of assuming API calls worked."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
      'a': 'http://schemas.openxmlformats.org/drawingml/2006/main'}


def unlock_generated_shapes(source: Path, output: Path) -> None:
    """Artifact export marks native shapes noGrp; our own diagram needs grouping.
    Never apply this repair to arbitrary user decks or overwrite the source.
    """
    with ZipFile(source) as before, ZipFile(output, 'x') as after:
        for info in before.infolist():
            data = before.read(info.filename)
            if info.filename.startswith('ppt/slides/slide') and info.filename.endswith('.xml'):
                # Preserve namespace declarations used by MC Requires attributes.
                import re
                data = re.sub(rb'(?<= )noGrp="1"', b'noGrp="0"', data)
            after.writestr(info, data)


def audit_pptx(path: Path, bundle: dict) -> dict:
    reports = []
    with ZipFile(path) as archive:
        presentation = ET.fromstring(archive.read('ppt/presentation.xml'))
        count = len(presentation.findall('p:sldIdLst/p:sldId', NS))
        if count != len(bundle['pages']):
            raise ValueError('PPT 页数与任务不一致')
        for number, record in enumerate(bundle['pages'], 1):
            root = ET.fromstring(archive.read(f'ppt/slides/slide{number}.xml'))
            scene = record['scene']
            names = {node.attrib['id']: node.attrib['name'] for node in root.findall('.//p:cNvPr', NS)}
            expected_names = {obj['name'] for obj in scene['objects']}
            if not expected_names.issubset(names.values()):
                raise ValueError('PPT 原生对象缺失或名称改变')
            expected = []
            for name, intervals in scene['visibility'].items():
                for start, end in intervals:
                    if start > 0:
                        expected.append((name, 'visible', round(start * 1000 / scene['fps'])))
                    if end < scene['duration_frames']:
                        expected.append((name, 'hidden', round(end * 1000 / scene['fps'])))
            actual = []
            for effect in root.findall('.//p:cTn', NS):
                if effect.get('presetClass') not in {'entr', 'exit'}:
                    continue
                condition = effect.find('p:stCondLst/p:cond', NS)
                target = effect.find('.//p:spTgt', NS)
                value = effect.find('.//p:set/p:to/p:strVal', NS)
                if condition is None or target is None or value is None:
                    raise ValueError('不支持的 PPT 动画结构')
                actual.append((names[target.get('spid')], value.get('val'), int(condition.get('delay'))))
            if Counter(actual) != Counter(expected):
                raise ValueError('PPT 保存后的可见性或动画时序与任务不一致')
            rotations = []
            for effect in root.findall('.//p:cTn', NS):
                if effect.get('presetClass') != 'emph':
                    continue
                motion = effect.find('.//p:animRot', NS)
                if motion is None:
                    raise ValueError('出现任务未定义的强调动画')
                target = motion.find('.//p:spTgt', NS)
                timing = motion.find('p:cBhvr/p:cTn', NS)
                condition = effect.find('p:stCondLst/p:cond', NS)
                if target is None or timing is None or condition is None:
                    raise ValueError('旋转动画缺少时间或目标')
                if timing.get('accel', '0') != '0' or timing.get('decel', '0') != '0':
                    raise ValueError('旋转速率不能被隐式改变')
                rotations.append((names[target.get('spid')], int(condition.get('delay')),
                                  int(timing.get('dur')), int(motion.get('by'))))
            expected_rotations = [(r['target'], round(r['start_frame']*1000/scene['fps']),
                                   round((r['end_frame']-r['start_frame'])*1000/scene['fps']),
                                   round(r['degrees']*60000)) for r in scene['rotations']]
            if Counter(rotations) != Counter(expected_rotations):
                raise ValueError('PPT 旋转角度或时长与任务不一致')
            for group in scene['groups']:
                match = next((g for g in root.findall('.//p:grpSp', NS)
                              if g.find('p:nvGrpSpPr/p:cNvPr', NS).get('name') == group['name']), None)
                if match is None:
                    raise ValueError('旋转组件没有保持原生组合')
                off = match.find('p:grpSpPr/a:xfrm/a:off', NS)
                ext = match.find('p:grpSpPr/a:xfrm/a:ext', NS)
                if off is None or ext is None or abs((int(off.get('x'))+int(ext.get('cx'))/2)/9525-865) > .1 or abs((int(off.get('y'))+int(ext.get('cy'))/2)/9525-350) > .1:
                    raise ValueError('旋转中心偏离地球中心')
            # This adapter must use one automatic click group with zero-delay
            # ancestors. Reject extra click sequences that invalidate absolute time.
            parent = {child: node for node in root.iter() for child in node}
            for effect in root.findall('.//p:cTn', NS):
                if effect.get('presetClass') not in {'entr', 'exit', 'emph'}:
                    continue
                node = parent.get(effect)
                while node is not None:
                    if node.tag == f"{{{NS['p']}}}cTn":
                        conditions = node.findall('p:stCondLst/p:cond', NS)
                        for condition in conditions:
                            delay = condition.get('delay')
                            if delay not in {'0', 'indefinite'}:
                                raise ValueError('动画组存在未计入的起始延迟')
                            if delay == 'indefinite' and not any(c.get('evt') == 'onBegin' for c in conditions):
                                raise ValueError('动画意外需要点击触发')
                    node = parent.get(node)
            transitions = root.findall('.//p:transition', NS)
            expected_ms = round(scene['duration_frames'] * 1000 / scene['fps'])
            if not transitions or any(t.get('advClick') != '0' or int(t.get('advTm', '-1')) != expected_ms for t in transitions):
                raise ValueError('PPT 自动换页时长不一致')
            reports.append({'id': record['page']['id'], 'native_objects': len(expected_names),
                            'verified_visibility_events': len(actual), 'verified_rotations': len(rotations),
                            'duration_ms': expected_ms})
    return {'passed': True, 'pages': reports,
            'scope': '原生对象、动画时间和自动换页的文件级验证；不替代实际放映审片'}
