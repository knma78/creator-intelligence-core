from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from exporter.creator_learning import load_creator_specs


logger = logging.getLogger(__name__)


POSITIONING_HINTS = {
    "Storytelling": ["故事", "人物", "国家", "事件", "悬念", "反转", "叙事"],
    "Logical Narrative": ["逻辑", "因果", "论证", "历史", "资料", "时间线"],
    "Historical Narrative": ["历史", "人物", "时代", "王朝", "战争", "制度"],
    "Long Historical Narrative": ["长视频", "历史", "长线", "人物群像", "制度"],
    "International Commentary": ["国际", "局势", "国家", "外交", "时政", "现实议题"],
    "Geopolitical Narrative": ["地缘", "国际关系", "国家关系", "战争", "政策"],
    "Science Explanation": ["科学", "科普", "宇宙", "物理", "技术", "概念"],
    "Business Explanation": ["财经", "商业", "经济", "公司", "市场", "案例"],
    "Cross-cultural Short Explainer": ["文化", "海外", "生活", "差异", "社会观察", "短视频"],
    "Emotion Narrative": ["情绪", "纪录片", "人物", "现实", "共情", "现场"],
    "Visual Teaching": ["教学", "图示", "动画", "视觉化", "实验", "解释"],
    "Visual Production": ["拍摄", "剪辑", "摄影", "影像", "制作", "器材"],
    "Story Analysis": ["影视", "剧情", "解析", "人物", "主题", "作品"],
    "Anime Narrative": ["动漫", "番剧", "漫画", "剧情讲解", "世界观", "角色"],
}


CAPABILITY_HINTS = {
    "Hook": ["开头", "hook", "钩子", "悬念", "点击"],
    "Logic": ["逻辑", "因果", "论证", "事实", "资料"],
    "Emotion": ["情绪", "共情", "沉浸", "纪录片"],
    "Rhythm": ["节奏", "完播", "快慢", "推进"],
    "Transition": ["转场", "衔接", "过渡"],
    "Ending": ["结尾", "收束", "回扣"],
    "Visualization": ["画面", "视觉", "封面", "分镜", "剪辑"],
    "Explanation": ["解释", "科普", "讲解", "降门槛"],
    "World Building": ["世界观", "设定", "背景"],
    "Character": ["人物", "角色", "动机"],
    "Plot Analysis": ["剧情", "解析", "作品"],
    "Historical Narrative": ["历史", "时间线", "时代"],
    "Anime Narrative": ["动漫", "番剧", "漫画"],
    "Science Narrative": ["科学", "宇宙", "技术"],
}


def build_up_advisor_report(
    target: str = "",
    output_root: Path = SETTINGS.output_dir,
    output_dir: Path | None = None,
    min_samples: int = 5,
    settings: Settings = SETTINGS,
    payload: dict[str, Any] | None = None,
) -> dict[str, Path]:
    output_root = output_root.resolve()
    output_dir = (output_dir or output_root / "integrated").resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = payload or advise_next_up_targets(
        target,
        output_root=output_root,
        min_samples=min_samples,
        settings=settings,
    )
    json_path = output_dir / "up_advisor_report.json"
    markdown_path = output_dir / "up_advisor_report.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_build_markdown(payload), encoding="utf-8")
    return {"json": json_path, "markdown": markdown_path}


def advise_next_up_targets(
    target: str = "",
    output_root: Path = SETTINGS.output_dir,
    min_samples: int = 5,
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    output_root = output_root.resolve()
    project = _read_json(output_root / "integrated" / "project_information_integration.json")
    manifest = _read_json(output_root / "creator_knowledge_base" / "manifest.json")
    template_library = _read_json(output_root / "creator_knowledge_base" / "templates" / "template_library.json")
    specs = load_creator_specs()
    creators = list(manifest.get("creators") or project.get("creators") or [])
    target = str(target or "").strip()
    min_samples = max(1, int(min_samples or 5))

    current = _current_state(project, manifest, template_library, creators)
    target_profile = _target_profile(target)
    priorities = _build_priorities(creators, target_profile, specs, min_samples)
    crawl_plan = _build_crawl_plan(priorities, target_profile, min_samples)
    questions = _build_questions(target, target_profile, current)

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "target": target,
        "current_state": current,
        "target_profile": target_profile,
        "recommendations": priorities,
        "candidate_checklist": _candidate_checklist(target_profile),
        "crawl_plan": crawl_plan,
        "decision_questions": questions,
        "seed_search_queries": _seed_queries(target_profile, priorities),
        "output_policy": {
            "goal": "帮助判断下一批要抓取/学习的 UP 类型。",
            "do_not_do": "不直接模仿候选 UP；只判断其是否能补足能力样本。",
        },
    }
    payload["ai_analysis"] = _generate_ai_analysis(payload, settings)
    return payload


def _generate_ai_analysis(payload: dict[str, Any], settings: Settings) -> dict[str, Any]:
    status = {
        "configured": bool(settings.llm_api_key),
        "used": False,
        "model": settings.llm_model,
        "error": None,
    }
    if not settings.llm_api_key:
        status["error"] = "未配置 LLM_API_KEY，当前仅显示本地规则建议。"
        return status

    try:
        from openai import OpenAI
    except ImportError:
        status["error"] = "未安装 openai SDK，无法调用兼容接口。"
        return status

    client_kwargs: dict[str, Any] = {
        "api_key": settings.llm_api_key,
        "timeout": settings.llm_timeout,
    }
    if settings.llm_base_url:
        client_kwargs["base_url"] = settings.llm_base_url

    context = {
        "target": payload.get("target"),
        "current_state": payload.get("current_state"),
        "rule_target_profile": payload.get("target_profile"),
        "rule_recommendations": (payload.get("recommendations") or [])[:8],
        "rule_crawl_plan": (payload.get("crawl_plan") or [])[:6],
    }
    context_json = json.dumps(context, ensure_ascii=False)
    if len(context_json) > settings.llm_max_chars:
        context_json = context_json[: settings.llm_max_chars]
    prompt = f"""
用户希望判断下一批应该寻找和抓取哪类 UP，输入是：{payload.get('target') or '未提供具体方向'}

下面是本地知识库状态和规则分析证据：
{context_json}

请基于证据做独立判断，只输出 JSON 对象，字段必须是：
{{
  "answer": "直接回答用户应该怎么做，2到4句话",
  "judgement": "继续抓取|先补现有样本|暂缓抓取",
  "confidence": 0到100的整数,
  "reasons": ["最多5条关键理由"],
  "recommended_creator_types": [
    {{
      "positioning": "创作者能力类型",
      "priority": "高|中|低",
      "why": "为什么能补当前知识库",
      "selection_criteria": "寻找候选UP时如何判断",
      "sample_count": 5
    }}
  ],
  "avoid": ["不建议继续抓取或应避免的类型"],
  "next_questions": ["为了进一步判断可以追问用户的问题"]
}}

要求：
- 学习可迁移创作能力，不模仿具体措辞、句子、观点或个人口头禅。
- 明确区分知识库证据与推断；证据不足时直接说明。
- 不要虚构具体 UP、播放量或平台数据。
- 推荐 1 到 5 类创作者，并给出可执行筛选标准和建议样本数。
""".strip()

    try:
        client = OpenAI(**client_kwargs)
        response = client.chat.completions.create(
            model=settings.llm_model,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "你是创作者能力知识库研究员。只基于给定证据做判断，并且只输出可解析 JSON。",
                },
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        data = _load_llm_json(content)
        status.update(data)
        status["used"] = True
        status["error"] = None
    except Exception as exc:  # pragma: no cover - provider/network dependent
        logger.warning("UP advisor LLM call failed: %s", exc)
        status["error"] = str(exc)
    return status


def _load_llm_json(content: str) -> dict[str, Any]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            raise ValueError("模型没有返回可解析的 JSON")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("模型返回结果不是 JSON 对象")
    return data


def _current_state(
    project: dict[str, Any],
    manifest: dict[str, Any],
    template_library: dict[str, Any],
    creators: list[dict[str, Any]],
) -> dict[str, Any]:
    scope = project.get("scope", {})
    position_counter = Counter(str(item.get("positioning") or "Unknown") for item in creators)
    low_sample = [
        {
            "author": item.get("author"),
            "positioning": item.get("positioning"),
            "video_count": int(item.get("video_count") or 0),
            "needed_to_min_5": max(0, 5 - int(item.get("video_count") or 0)),
        }
        for item in creators
        if int(item.get("video_count") or 0) < 5
    ]
    return {
        "video_count": scope.get("video_count") or manifest.get("video_count", 0),
        "creator_count": scope.get("author_count") or manifest.get("creator_count", 0),
        "raw_author_count": scope.get("raw_author_count", 0),
        "template_count": scope.get("template_count") or _template_count(template_library),
        "missing_target_creators": scope.get("missing_target_creators", []),
        "positioning_distribution": [
            {"positioning": key, "count": value}
            for key, value in position_counter.most_common()
        ],
        "low_sample_creators": low_sample,
        "remaining_gaps": project.get("gaps", {}),
    }


def _target_profile(target: str) -> dict[str, Any]:
    text = target.lower()
    positioning_scores = []
    for positioning, hints in POSITIONING_HINTS.items():
        score = sum(1 for hint in hints if hint.lower() in text)
        if score:
            positioning_scores.append({"positioning": positioning, "score": score})
    capability_scores = []
    for capability, hints in CAPABILITY_HINTS.items():
        score = sum(1 for hint in hints if hint.lower() in text)
        if score:
            capability_scores.append({"capability": capability, "score": score})
    if _looks_like_video_production_pipeline(text):
        positioning_scores.extend(
            [
                {"positioning": "Visual Production", "score": 3},
                {"positioning": "Visual Teaching", "score": 2},
                {"positioning": "Business Explanation", "score": 1},
                {"positioning": "Science Explanation", "score": 1},
                {"positioning": "Emotion Narrative", "score": 1},
            ]
        )
        capability_scores.extend(
            [
                {"capability": "Visualization", "score": 3},
                {"capability": "Rhythm", "score": 2},
                {"capability": "Explanation", "score": 2},
                {"capability": "Logic", "score": 2},
                {"capability": "Hook", "score": 1},
                {"capability": "Ending", "score": 1},
            ]
        )
    positioning_scores = _merge_score_rows(positioning_scores, "positioning")
    capability_scores = _merge_score_rows(capability_scores, "capability")
    positioning_scores.sort(key=lambda item: (-item["score"], item["positioning"]))
    capability_scores.sort(key=lambda item: (-item["score"], item["capability"]))
    if not positioning_scores:
        positioning_scores = [
            {"positioning": "Visual Production", "score": 1},
            {"positioning": "Business Explanation", "score": 1},
            {"positioning": "Historical Narrative", "score": 1},
            {"positioning": "Story Analysis", "score": 1},
        ]
    if not capability_scores:
        capability_scores = [
            {"capability": "Hook", "score": 1},
            {"capability": "Logic", "score": 1},
            {"capability": "Visualization", "score": 1},
            {"capability": "Rhythm", "score": 1},
        ]
    return {
        "matched_positionings": positioning_scores[:6],
        "matched_capabilities": capability_scores[:8],
        "interpretation": _interpret_target(positioning_scores[:3], capability_scores[:4], bool(target)),
    }


def _looks_like_video_production_pipeline(text: str) -> bool:
    return any(
        keyword in text
        for keyword in ["自动视频", "视频制作器", "自动化视频", "成片", "剪辑", "分镜", "素材匹配", "tts", "旁白"]
    )


def _merge_score_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    merged: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "").strip()
        if not value:
            continue
        merged[value] = merged.get(value, 0) + int(row.get("score") or 0)
    return [{key: value, "score": score} for value, score in merged.items()]


def _interpret_target(positionings: list[dict[str, Any]], capabilities: list[dict[str, Any]], has_target: bool) -> str:
    if not has_target:
        return "未输入具体方向，默认按当前知识库缺口和自动视频制作器需求推荐。"
    pos = "、".join(item["positioning"] for item in positionings) or "通用内容方向"
    caps = "、".join(item["capability"] for item in capabilities) or "通用创作能力"
    return f"当前输入更像是在寻找 {pos} 方向的 UP，优先补 {caps} 能力样本。"


def _build_priorities(
    creators: list[dict[str, Any]],
    target_profile: dict[str, Any],
    specs: dict[str, dict[str, Any]],
    min_samples: int,
) -> list[dict[str, Any]]:
    by_positioning: dict[str, list[dict[str, Any]]] = {}
    for creator in creators:
        by_positioning.setdefault(str(creator.get("positioning") or "Unknown"), []).append(creator)

    priorities = []
    matched_positionings = [item["positioning"] for item in target_profile["matched_positionings"]]
    for positioning in matched_positionings:
        rows = by_positioning.get(positioning, [])
        sample_count = sum(int(item.get("video_count") or 0) for item in rows)
        creator_count = len(rows)
        low_rows = [item for item in rows if int(item.get("video_count") or 0) < min_samples]
        if not rows:
            action = "寻找新UP"
            reason = "当前知识库没有这个定位的样本，适合补一个新的能力方向。"
            needed = min_samples
        elif low_rows:
            action = "补足已有UP样本"
            names = "、".join(f"{item.get('author')}({item.get('video_count')})" for item in low_rows)
            reason = f"该定位已有样本但稳定性不足：{names}。"
            needed = sum(max(0, min_samples - int(item.get("video_count") or 0)) for item in low_rows)
        else:
            action = "寻找对照UP"
            reason = "该定位已有基础样本，下一步适合找同类但节奏/画面/受众不同的对照样本。"
            needed = min_samples
        priorities.append(
            {
                "positioning": positioning,
                "action": action,
                "current_creator_count": creator_count,
                "current_video_count": sample_count,
                "recommended_next_videos": needed,
                "reason": reason,
                "ideal_candidate": _ideal_candidate(positioning, specs),
            }
        )
    priorities.extend(_mandatory_data_priorities(creators, min_samples))
    return _dedupe_priorities(priorities)


def _mandatory_data_priorities(creators: list[dict[str, Any]], min_samples: int) -> list[dict[str, Any]]:
    priorities = []
    low_sample = [
        item for item in creators if int(item.get("video_count") or 0) < min_samples
    ]
    for item in low_sample[:5]:
        needed = max(0, min_samples - int(item.get("video_count") or 0))
        priorities.append(
            {
                "positioning": item.get("positioning"),
                "action": "补足已有UP样本",
                "current_creator_count": 1,
                "current_video_count": int(item.get("video_count") or 0),
                "recommended_next_videos": needed,
                "reason": f"{item.get('author')} 当前只有 {item.get('video_count')} 条，低于稳定画像阈值 {min_samples} 条。",
                "ideal_candidate": f"优先继续抓 {item.get('author')} 的高播放/代表性视频；如果内容定位偏窄，再找同定位对照 UP。",
            }
        )
    return priorities


def _ideal_candidate(positioning: str, specs: dict[str, dict[str, Any]]) -> str:
    matched = [
        author
        for author, spec in specs.items()
        if spec.get("positioning") == positioning
    ]
    if matched:
        return f"可以先从已配置定位里的 {matched[0]} 或同类型 UP 开始。"
    table = {
        "Visual Production": "找能稳定展示拍摄、剪辑、制作过程和结果验证的影像类 UP。",
        "Business Explanation": "找能把商业案例拆成市场变量、商业模式和结果判断的财经/商业 UP。",
        "International Commentary": "找能把现实议题拆成国家关系、利益变量和影响链的 UP。",
        "Story Analysis": "找能稳定拆剧情节点、角色动机和主题表达的影视解析 UP。",
        "Anime Narrative": "找能压缩剧情、解释世界观和制造后续期待的动漫讲解 UP。",
        "Science Explanation": "找能把复杂概念讲清，并能说明证据和边界的科普 UP。",
        "Historical Narrative": "找能用时间线、人物关系和时代变量讲清历史事件的 UP。",
    }
    return table.get(positioning, "找定位清晰、系列稳定、样本可持续抓取的 UP。")


def _build_crawl_plan(
    priorities: list[dict[str, Any]],
    target_profile: dict[str, Any],
    min_samples: int,
) -> list[dict[str, Any]]:
    plan = []
    for index, item in enumerate(priorities[:6], start=1):
        videos = max(3, min(10, int(item.get("recommended_next_videos") or min_samples)))
        plan.append(
            {
                "step": index,
                "target_positioning": item.get("positioning"),
                "crawl_count": videos,
                "selection_rule": "优先选系列内高播放、近一年代表作、标题结构清晰且字幕可用的视频。",
                "acceptance_rule": "抓取后能新增一种能力样本，或把低样本 UP 补到稳定阈值。",
                "command_hint": f"python main.py \"UP主页或mid\" --up --limit {videos} --v3",
            }
        )
    if not plan:
        plan.append(
            {
                "step": 1,
                "target_positioning": target_profile["matched_positionings"][0]["positioning"],
                "crawl_count": min_samples,
                "selection_rule": "先找一个定位清晰、系列稳定的 UP。",
                "acceptance_rule": "至少产出 5 条可分析视频。",
                "command_hint": f"python main.py \"UP主页或mid\" --up --limit {min_samples} --v3",
            }
        )
    return plan


def _build_questions(target: str, target_profile: dict[str, Any], current: dict[str, Any]) -> list[dict[str, str]]:
    if not target:
        return [
            {
                "question": "你下一阶段主要想做哪类内容？",
                "why_it_matters": "决定优先抓剧情解析、知识科普、国际财经、历史叙事还是视觉制作类 UP。",
            },
            {
                "question": "你更缺脚本能力、画面能力、资料核查能力，还是成片节奏能力？",
                "why_it_matters": "决定候选 UP 应该按能力补齐，而不是只按知名度抓取。",
            },
            {
                "question": "你准备先做横屏中长视频，还是短视频切片？",
                "why_it_matters": "不同形态需要抓取的参考 UP 节奏完全不同。",
            },
        ]
    return [
        {
            "question": f"这个方向是否真的对应：{target_profile['interpretation']}",
            "why_it_matters": "如果理解偏了，下一批抓取会补错能力。",
        },
        {
            "question": "候选 UP 是否有稳定系列，而不是偶发爆款？",
            "why_it_matters": "稳定系列更适合抽象成可复用能力。",
        },
        {
            "question": "候选 UP 的优势是否填补当前缺口，而不是重复已有能力？",
            "why_it_matters": f"当前低样本项：{_format_low_sample(current.get('low_sample_creators', []))}",
        },
    ]


def _candidate_checklist(target_profile: dict[str, Any]) -> list[str]:
    capabilities = [item["capability"] for item in target_profile.get("matched_capabilities", [])]
    checklist = [
        "是否有清晰、可连续抓取的系列内容。",
        "是否至少能抓到 5 条可分析样本。",
        "是否有字幕、清晰音频或可转录素材。",
        "是否能补足当前知识库缺口，而不是只重复已有 UP。",
        "是否适合抽象能力，不依赖个人口头禅或独特人设。",
    ]
    if "Visualization" in capabilities:
        checklist.append("画面、封面、分镜或制作过程是否承担了明显信息功能。")
    if "Logic" in capabilities:
        checklist.append("是否有资料来源、因果链和阶段性判断。")
    if "Emotion" in capabilities:
        checklist.append("是否有稳定的人物处境、现场感和情绪回收。")
    return checklist


def _seed_queries(target_profile: dict[str, Any], priorities: list[dict[str, Any]]) -> list[str]:
    seeds = []
    for item in priorities[:5]:
        positioning = item.get("positioning")
        if positioning:
            seeds.append(f"B站 {positioning} UP 系列")
            seeds.append(f"B站 {positioning} 高播放 讲解")
    for item in target_profile.get("matched_capabilities", [])[:4]:
        capability = item.get("capability")
        seeds.append(f"B站 {capability} 能力强 UP")
    return _dedupe(seeds)[:12]


def _build_markdown(payload: dict[str, Any]) -> str:
    current = payload["current_state"]
    target = payload["target_profile"]
    ai = payload.get("ai_analysis") or {}
    lines = [
        "# UP 抓取决策问答",
        "",
        f"生成时间：{payload['generated_at']}",
        "",
        "## 当前知识库状态",
        "",
        f"- 视频样本：{current.get('video_count')}",
        f"- 创作者画像：{current.get('creator_count')}",
        f"- 原始作者名：{current.get('raw_author_count')}",
        f"- 模板数：{current.get('template_count')}",
        "",
        "## AI 判断",
        "",
        f"- 模型：{ai.get('model') or '未配置'}",
        f"- 调用状态：{'成功' if ai.get('used') else '未使用'}",
    ]
    if ai.get("used"):
        lines.extend(
            [
                f"- 结论：{ai.get('judgement') or '未给出'}",
                f"- 置信度：{ai.get('confidence', '-')} / 100",
                f"- 回答：{ai.get('answer') or ''}",
                "",
                "### AI 判断依据",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in ai.get("reasons") or [])
        lines.extend(["", "### AI 推荐创作者类型", ""])
        for item in ai.get("recommended_creator_types") or []:
            lines.extend(
                [
                    f"- **{item.get('positioning') or '未命名类型'}**（{item.get('priority') or '中'}优先级，建议 {item.get('sample_count') or 5} 条）",
                    f"  - 原因：{item.get('why') or ''}",
                    f"  - 筛选标准：{item.get('selection_criteria') or ''}",
                ]
            )
    else:
        lines.extend([f"- 原因：{ai.get('error') or '没有可用的 AI 结果。'}", ""])
    lines.extend(
        [
        "## 目标理解",
        "",
        f"- 输入：{payload.get('target') or '未输入具体方向'}",
        f"- 判断：{target.get('interpretation')}",
        f"- 匹配定位：{_format_rows(target.get('matched_positionings', []), 'positioning')}",
        f"- 匹配能力：{_format_rows(target.get('matched_capabilities', []), 'capability')}",
        "",
        "## 建议抓取方向",
        "",
        ]
    )
    for item in payload["recommendations"]:
        lines.extend(
            [
                f"### {item.get('positioning')}：{item.get('action')}",
                "",
                f"- 当前样本：{item.get('current_creator_count')} 个 UP / {item.get('current_video_count')} 条视频",
                f"- 建议新增：{item.get('recommended_next_videos')} 条",
                f"- 原因：{item.get('reason')}",
                f"- 候选标准：{item.get('ideal_candidate')}",
                "",
            ]
        )
    lines.extend(["## 候选 UP 判断清单", ""])
    lines.extend(f"- {item}" for item in payload["candidate_checklist"])
    lines.extend(["", "## 下一批抓取计划", ""])
    for item in payload["crawl_plan"]:
        lines.extend(
            [
                f"- Step {item['step']}：{item['target_positioning']}，抓 {item['crawl_count']} 条。",
                f"  选择规则：{item['selection_rule']}",
                f"  命令参考：`{item['command_hint']}`",
            ]
        )
    lines.extend(["", "## 需要你回答的问题", ""])
    for item in payload["decision_questions"]:
        lines.append(f"- {item['question']}（{item['why_it_matters']}）")
    lines.extend(["", "## 搜索种子", ""])
    lines.extend(f"- {item}" for item in payload["seed_search_queries"])
    return "\n".join(lines).rstrip() + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _template_count(template_library: dict[str, Any]) -> int:
    return sum(
        len(template_library.get(key, []))
        for key in [
            "hook_templates",
            "script_structure_templates",
            "transition_templates",
            "climax_templates",
            "ending_templates",
            "workflow_templates",
        ]
    )


def _format_rows(rows: list[dict[str, Any]], key: str) -> str:
    return "、".join(f"{item[key]}({item.get('score', 0)})" for item in rows) or "暂无"


def _format_low_sample(rows: list[dict[str, Any]]) -> str:
    return "、".join(f"{item.get('author')}({item.get('video_count')})" for item in rows) or "暂无"


def _dedupe(items: list[str]) -> list[str]:
    result = []
    seen = set()
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _dedupe_priorities(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in items:
        key = (item.get("positioning"), item.get("action"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Advise which UP series to crawl next.")
    parser.add_argument("target", nargs="?", default="")
    parser.add_argument("--output-root", default=str(SETTINGS.output_dir))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--min-samples", type=int, default=5)
    args = parser.parse_args()
    paths = build_up_advisor_report(
        target=args.target,
        output_root=Path(args.output_root),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        min_samples=args.min_samples,
    )
    for kind, path in paths.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
