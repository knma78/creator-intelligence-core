"""Conservative rule-to-edit adapter: change visual boundaries, never narration."""
from __future__ import annotations

import bisect
import math
import re

from intelligence.capability_planner import build_capability_plan
from production.captions import display_units


_SENTENCE_END = re.compile(r'[。！？!?；;](?:[”’"\']*)|\.(?=\s|$)|\n+')
_CONTRAST = re.compile(r'却|但是|然而|竟然|反常|反差|\b(?:but|however|yet|unexpectedly)\b', re.I)
_QUESTION = re.compile(r'[？?]|为什么|如何|\b(?:why|how)\b', re.I)
_CONCLUSION = re.compile(r'因此|所以|结论|意味着|\b(?:therefore|in conclusion|in short)\b', re.I)
_TRANSITIONS = {
    'transition_sequence': re.compile(r'^(?:首先|其次|接着|最后|然后|first\b|next\b|finally\b)', re.I),
    'transition_turning_point': re.compile(r'^(?:但|然而|不过|but\b|however\b)', re.I),
    'transition_causal_close': re.compile(r'^(?:因此|所以|于是|therefore\b|thus\b)', re.I),
    'transition_example_bridge': re.compile(r'^(?:例如|比如|举例|for example\b|for instance\b)', re.I),
}


def _sentences(script):
    ends = sorted({0, len(script), *(m.end() for m in _SENTENCE_END.finditer(script))})
    return [(a, b) for a, b in zip(ends, ends[1:]) if script[a:b].strip()]


def _base_cuts(script, target_count):
    """Cover every character once; prefer word/clause boundaries near each cut."""
    weights = [0]
    for char in script:
        weights.append(weights[-1] + display_units(char))
    natural = [m.end() for m in re.finditer(r'[\s，,。！？!?；;：:]', script)]
    cuts = {0, len(script)}
    for index in range(1, target_count):
        target = weights[-1] * index / target_count
        position = bisect.bisect_left(weights, target)
        nearby = [cut for cut in natural if abs(weights[cut] - target) <= weights[-1] / target_count * .25]
        cuts.add(min(nearby, key=lambda cut: abs(weights[cut] - target)) if nearby else position)
    return sorted(cuts)


def _time_map(script, duration, cues):
    weights = [0]
    counts = [0]
    for char in script:
        weights.append(weights[-1] + display_units(char))
        counts.append(counts[-1] + len(char.casefold()) if char.isalnum() else counts[-1])
    normalized = ''.join(c.casefold() for c in script if c.isalnum())
    cue_text, positions, previous = '', [], 0.0
    valid = bool(cues)
    for cue in cues or []:
        text = ''.join(c.casefold() for c in str(cue.get('text') or '') if c.isalnum())
        start, end = float(cue['start']), float(cue['end'])
        if not (math.isfinite(start) and math.isfinite(end) and previous <= start < end <= duration + .05):
            valid = False
        previous = end
        cue_text += text
        positions.extend(start + (end - start) * (i + 1) / len(text) for i in range(len(text)))
    if valid and normalized and normalized == cue_text:
        def timestamp(offset):
            return 0.0 if offset <= 0 else duration if offset >= len(script) else min(duration, positions[max(0, counts[offset] - 1)])
        return timestamp, 'tts_cue_interpolated', []
    def timestamp(offset):
        return duration * weights[offset] / max(1, weights[-1])
    warnings = ['字幕文字或时序与文稿无法完整对齐，镜头时间按文字长度估算。'] if cues else []
    return timestamp, 'text_weight_estimate', warnings


def _proposal(candidate, script, sentences):
    template = candidate.get('template_id')
    first, last = sentences[0], sentences[-1]
    opening, ending = script[slice(*first)], script[slice(*last)]
    if template == 'hook_question_task' and _QUESTION.search(opening):
        return first, 'hold_opening_question', '开场存在明确提问，保留完整问句的镜头，不在句中切换。'
    if template == 'hook_contrast_gap' and _CONTRAST.search(opening):
        return first, 'hold_opening_contrast', '开场存在显式转折信号，保留这一句的对比表达。'
    if template == 'ending_logic_closure' and _CONCLUSION.search(ending):
        return last, 'hold_conclusion', '末句存在显式收束信号，保留完整结论的镜头。'
    if template == 'ending_question_callback' and _QUESTION.search(opening) and re.search(r'答案|回答|回到.*问题|\banswer\b', ending, re.I):
        return last, 'hold_answer', '首句提问、末句显式回答；保留回答句，不推断回答内容是否正确。'
    if template in _TRANSITIONS:
        for start, end in sentences[1:-1]:
            if _TRANSITIONS[template].search(script[start:end].strip()):
                return (start, start), 'cut_at_connective', '段落有明确连接词，将画面切换边界移到这一句的开头。'
    supported = {'hook_question_task', 'hook_contrast_gap', 'ending_logic_closure', 'ending_question_callback', *_TRANSITIONS}
    return None, '', '当前段落缺少适用的局部信号。' if template in supported else '尚无安全的分镜执行适配器，保留为建议，不自动改写或重排文稿。'


def build_layout(script, *, duration, shot_seconds, title, settings, cues=None):
    path = settings.output_dir / 'creator_knowledge_base/rules/rule_library.json'
    warnings = []
    try:
        plan = build_capability_plan(f'{title}\n{script}', rule_library_path=path) if path.is_file() else None
    except (ValueError, OSError, KeyError, TypeError) as exc:
        plan = None
        warnings.append(f'能力库不可用，使用基础分镜：{exc}')
    timestamp, alignment, timing_warnings = _time_map(script, duration, cues)
    warnings.extend(timing_warnings)
    count = max(2, min(50, math.ceil(duration / shot_seconds)))
    baseline = _base_cuts(script, count)
    cuts = list(baseline)
    applied, declined, occupied = [], [], set()
    sentences = _sentences(script)
    for selection in (plan or {}).get('selections', []):
        candidates = [selection['primary'], *selection.get('secondary', []), *selection.get('alternatives', [])]
        for candidate in candidates:
            record = {key: candidate.get(key) for key in ('rule_id', 'template_id', 'name', 'layer', 'status',
                      'content_revision', 'content_fingerprint', 'evidence_ids', 'matched_signals')}
            span, operation, reason = _proposal(candidate, script, sentences)
            if candidate.get('review_required_reason'):
                reason, span = '复核已过期，暂不自动采用。', None
            elif candidate.get('condition_state') == 'unknown':
                reason, span = '触发条件未知，仅保留低置信度建议。', None
            elif selection['layer'] in occupied:
                reason, span = '同层级已采用另一能力，不无理由叠加。', None
            if span is None:
                declined.append({**record, 'reason': reason})
                continue
            start, end = span
            if end > start and timestamp(end) - timestamp(start) > 12:
                declined.append({**record, 'reason': '完整保留该句会产生超过 12 秒的静帧，暂不自动采用。'})
                continue
            proposed = sorted({*([x for x in cuts if not start < x < end]), start, end})
            if len(proposed) > 51 or any(timestamp(b) - timestamp(a) < .2 for a, b in zip(proposed, proposed[1:])):
                declined.append({**record, 'reason': '会产生过短镜头或超出镜头预算，保留基础切分。'})
                continue
            changed = sorted(set(cuts).symmetric_difference(proposed))
            applied.append({**record, 'operation': operation, 'reason': reason,
                            'script_start': start, 'script_end': end,
                            'changed_boundaries': changed, 'changed': bool(changed),
                            'selection_basis': 'local_structural_signal; not causal_validation'})
            cuts = proposed
            occupied.add(selection['layer'])
    # Remove too-short baseline segments too; the renderer otherwise pads them.
    kept = [0]
    for cut in cuts[1:-1]:
        if timestamp(cut) - timestamp(kept[-1]) >= .2 and duration - timestamp(cut) >= .2:
            kept.append(cut)
    kept.append(len(script))
    segments = []
    for start, end in zip(kept, kept[1:]):
        decisions = [item for item in applied if (item['script_start'] == start if item['operation'] == 'cut_at_connective'
                     else start < item['script_end'] and end > item['script_start'])]
        segments.append({'script_excerpt': script[start:end], 'script_start': start, 'script_end': end,
                         'start': round(timestamp(start), 3), 'end': round(timestamp(end), 3),
                         'capability_decisions': decisions})
    return segments, plan, {'policy_version': 'capability-layout/v1', 'applied': applied,
                           'not_applied': declined, 'warnings': warnings,
                           'baseline_boundaries': baseline, 'final_boundaries': kept,
                           'changed_boundary_count': len(set(baseline).symmetric_difference(kept)),
                           'timing_source': alignment, 'script_rewritten': False,
                           'scope': 'visual_boundaries_only; no semantic_rewrite_or_clip_selection'}
