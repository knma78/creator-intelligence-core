from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure.atomic_io import atomic_write_json
from production.capability_layout import build_layout
from production.script_video import _build_storyboard, preview_script_video_plan
from config import Settings


SCRIPT = '为什么这个问题值得我们认真地去研究和理解？首先观察已有现象，并记录不同情况下发生的变化。然后检查自己的判断是否正确。因此，结论需要证据支持，不能只凭直觉。'


def rule(identity, template, layer, signal, score=.6):
    return {'rule_id': identity, 'template_id': template, 'name': template,
            'layer': layer, 'status': 'candidate', 'Trigger': {'required_signals': [signal]},
            'confidence': {'functional_interpretation': score}, 'condition': [signal]}


@pytest.fixture
def settings(tmp_path):
    return Settings(base_dir=tmp_path, output_dir=tmp_path / 'output', cache_dir=tmp_path / 'cache', logs_dir=tmp_path / 'logs')


def write_rules(settings, rules):
    atomic_write_json(settings.output_dir / 'creator_knowledge_base/rules/rule_library.json', {'rules': rules})


def test_rule_changes_real_boundaries_and_preserves_script(settings):
    baseline, _, _ = build_layout(SCRIPT, duration=30, shot_seconds=3, title='', settings=settings)
    write_rules(settings, [rule('R-1', 'hook_question_task', 'opening', '问题'),
                           rule('R-2', 'ending_logic_closure', 'ending', '结论'),
                           rule('R-3', 'structure_science_explanation', 'narrative_structure', '现象')])
    segments, plan, execution = build_layout(SCRIPT, duration=30, shot_seconds=3, title='', settings=settings)
    assert execution['applied'] and execution['changed_boundary_count'] > 0
    assert len(segments) != len(baseline)
    assert segments[0]['script_excerpt'].endswith('？')
    assert segments[-1]['script_excerpt'].startswith('因此')
    assert ''.join(segment['script_excerpt'] for segment in segments) == SCRIPT
    assert not execution['script_rewritten']
    assert plan['candidate_count'] == 3
    assert execution['not_applied'][0]['rule_id'] == 'R-3'
    assert '适配器' in execution['not_applied'][0]['reason']
    for left, right in zip(segments, segments[1:]):
        assert left['end'] == right['start']
        assert left['script_end'] == right['script_start']
    assert segments[0]['start'] == 0 and segments[-1]['end'] == 30


def test_cannot_apply_question_rule_from_title_only(settings):
    write_rules(settings, [rule('R-1', 'hook_question_task', 'opening', '问题')])
    script = '这是一个普通的陈述句。接下来说明事件的经过，并且展示最后的结果。'
    _, _, execution = build_layout(script, duration=20, shot_seconds=3, title='问题', settings=settings)
    assert not execution['applied']
    assert '局部信号' in execution['not_applied'][0]['reason']


def test_stale_review_and_rejected_rules_cannot_drive_edits(settings):
    stale = rule('R-1', 'hook_question_task', 'opening', '问题')
    stale.update(status='validated', review={'approved': True, 'status': 'validated'})
    rejected = rule('R-2', 'ending_logic_closure', 'ending', '结论')
    rejected['status'] = 'rejected'
    write_rules(settings, [stale, rejected])
    _, plan, execution = build_layout(SCRIPT, duration=30, shot_seconds=3, title='', settings=settings)
    assert not execution['applied']
    assert '过期' in execution['not_applied'][0]['reason']
    assert plan['excluded'][0]['rule_id'] == 'R-2'


def test_same_layer_selects_one_and_records_alternatives(settings):
    script = '为什么这个问题竟然有完全不同的答案？接下来检查实验现象，并且解释每一条证据的来源。'
    write_rules(settings, [rule('R-1', 'hook_question_task', 'opening', '问题', .9),
                           rule('R-2', 'hook_contrast_gap', 'opening', '竟然', .5)])
    _, _, execution = build_layout(script, duration=20, shot_seconds=3, title='', settings=settings)
    assert len(execution['applied']) == 1
    assert '同层级' in execution['not_applied'][0]['reason']


def test_tts_alignment_changes_boundary_times_not_narration(settings):
    write_rules(settings, [rule('R-1', 'hook_question_task', 'opening', '问题')])
    first, remainder = SCRIPT.split('？', 1)
    cues = [{'text': first + '？', 'start': 0, 'end': 4}, {'text': remainder, 'start': 4.5, 'end': 30}]
    segments, _, execution = build_layout(SCRIPT, duration=30, shot_seconds=3, title='', settings=settings, cues=cues)
    assert execution['timing_source'] == 'tts_cue_interpolated'
    assert segments[0]['end'] == 4
    assert segments[-1]['end'] == 30
    _, _, mismatch = build_layout(SCRIPT, duration=30, shot_seconds=3, title='', settings=settings,
                                  cues=[{'text': 'different', 'start': 0, 'end': 30}])
    assert mismatch['timing_source'] == 'text_weight_estimate' and mismatch['warnings']


@pytest.mark.parametrize('script', [SCRIPT, 'One sentence. Another sentence, with spacing. The final conclusion is preserved.', '甲'*400])
def test_no_missing_or_repeated_text_without_rules(settings, script):
    segments, plan, execution = build_layout(script, duration=25, shot_seconds=3, title='', settings=settings)
    assert ''.join(item['script_excerpt'] for item in segments) == script
    assert plan is None and not execution['applied']
    assert all(item['end'] > item['start'] for item in segments)


def test_corrupt_library_has_visible_fallback(settings):
    path = settings.output_dir / 'creator_knowledge_base/rules/rule_library.json'
    path.parent.mkdir(parents=True)
    path.write_text('broken', encoding='utf-8')
    _, _, execution = build_layout(SCRIPT, duration=30, shot_seconds=3, title='', settings=settings)
    assert '能力库不可用' in execution['warnings'][0]


def test_preview_and_final_storyboard_share_execution_path(settings):
    write_rules(settings, [rule('R-1', 'hook_question_task', 'opening', '问题')])
    preview = preview_script_video_plan(SCRIPT, settings=settings)
    duration = preview['output_duration_seconds']
    final = _build_storyboard(SCRIPT, duration_seconds=duration, title='', template={'defaults': {'shot_seconds': 4}},
                              settings=settings, preview=False,
                              cues=[{'text': SCRIPT, 'start': 0, 'end': duration}])
    assert preview['capability_execution']['applied'][0]['rule_id'] == 'R-1'
    assert final['capability_execution']['applied'][0]['rule_id'] == 'R-1'
    assert final['scenes'][0]['capability_decisions'][0]['content_fingerprint']
    assert ''.join(scene['script_excerpt'] for scene in final['scenes']) == SCRIPT
