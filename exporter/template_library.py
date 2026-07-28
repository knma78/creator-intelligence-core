from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config import SETTINGS


TEMPLATE_COLLECTIONS = [
    "hook_templates",
    "script_structure_templates",
    "transition_templates",
    "climax_templates",
    "ending_templates",
    "workflow_templates",
]


def build_template_library(
    output_root: Path = SETTINGS.output_dir,
    output_dir: Path | None = None,
    cache_root: Path | None = None,
) -> dict[str, Path]:
    output_root = output_root.resolve()
    output_dir = (output_dir or output_root / "creator_knowledge_base" / "templates").resolve()
    cache_root = (cache_root or output_root.parent / "cache").resolve()
    cache_dir = cache_root / "creator_knowledge_base"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    kb_dir = output_root / "creator_knowledge_base"
    creator_kb = _read_json(kb_dir / "creator_knowledge_base.json")
    cross = _read_json(kb_dir / "cross_creator_analysis.json")
    manifest = _read_json(kb_dir / "manifest.json")
    payload = _build_template_payload(creator_kb, cross, manifest)

    json_path = output_dir / "template_library.json"
    markdown_path = output_dir / "template_library.md"
    index_path = output_dir / "template_index.json"
    cache_index_path = cache_dir / "template_index.json"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_build_markdown(payload), encoding="utf-8")
    index_path.write_text(json.dumps(payload["rag_index"], ensure_ascii=False, indent=2), encoding="utf-8")
    cache_index_path.write_text(json.dumps(payload["rag_index"], ensure_ascii=False, indent=2), encoding="utf-8")

    written = {
        "template_library_json": json_path,
        "template_library_markdown": markdown_path,
        "template_rag_index": index_path,
        "cache_template_rag_index": cache_index_path,
    }
    for collection_name in TEMPLATE_COLLECTIONS:
        path = output_dir / f"{collection_name}.json"
        path.write_text(
            json.dumps(payload.get(collection_name, []), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        written[collection_name] = path
    return written


def _build_template_payload(
    creator_kb: dict[str, Any],
    cross: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, Any]:
    capability_docs = creator_kb.get("capability_documents", [])
    capability_lookup = {
        doc.get("category"): doc
        for doc in capability_docs
        if doc.get("category")
    }
    creators = manifest.get("creators", [])
    positionings = sorted({item.get("positioning") for item in creators if item.get("positioning")})

    hook_templates = _hook_templates(capability_lookup, cross)
    script_templates = _script_structure_templates(positionings, capability_lookup)
    transition_templates = _transition_templates(capability_lookup, cross)
    climax_templates = _climax_templates(capability_lookup)
    ending_templates = _ending_templates(capability_lookup)
    workflow_templates = _workflow_templates(capability_lookup)

    collections = {
        "hook_templates": hook_templates,
        "script_structure_templates": script_templates,
        "transition_templates": transition_templates,
        "climax_templates": climax_templates,
        "ending_templates": ending_templates,
        "workflow_templates": workflow_templates,
    }
    rag_documents = _template_rag_documents(collections)

    return {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": {
            "creator_count": manifest.get("creator_count", 0),
            "video_count": manifest.get("video_count", 0),
            "positionings": positionings,
            "capability_document_count": len(capability_docs),
        },
        "policy": {
            "goal": "把已提取的创作能力转成可调用模板。",
            "can_use": ["结构顺序", "能力功能", "输入槽位", "检查标准", "适用场景"],
            "do_not_use": ["原文句子", "原文段落", "UP口头禅", "个人化语气", "具体观点照搬"],
        },
        **collections,
        "rag_index": {
            "version": 1,
            "document_count": len(rag_documents),
            "documents": rag_documents,
            "usage_policy": [
                "用于检索抽象创作模板和流程。",
                "模板只规定结构与功能，不提供可模仿的原文表达。",
            ],
        },
    }


def _hook_templates(capability_lookup: dict[str, dict[str, Any]], cross: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _template(
            "hook_contrast_gap",
            "反差信息缺口",
            ["Hook", "Storytelling", "Rhythm"],
            capability_lookup,
            "题材里存在反常识、强后果、冲突或异常现象。",
            ["核心对象", "观众默认认知", "反差结果", "本期解释任务"],
            ["点出对象", "呈现反差或风险", "暂不解释完", "转入背景或原因"],
            ["开场是否在 15-30 秒内建立观看理由", "反差是否服务于后文解释", "是否避免夸张但无兑现"],
            cross,
        ),
        _template(
            "hook_question_task",
            "问题任务式开场",
            ["Hook", "Explanation", "Teaching"],
            capability_lookup,
            "内容目标是解释复杂概念、事件因果或作品问题。",
            ["核心问题", "观众已有困惑", "解释边界", "答案路径"],
            ["提出问题", "说明为什么值得理解", "列出解释路径", "进入第一层背景"],
            ["问题是否具体", "后文是否持续回答这个问题", "结尾是否回扣问题"],
            cross,
        ),
        _template(
            "hook_objective_first",
            "对象任务直入",
            ["Hook", "Narration", "Rhythm"],
            capability_lookup,
            "题材本身认知门槛低，观众需要快速知道本期讲什么。",
            ["核心对象", "分析任务", "观看收益", "第一段材料"],
            ["交代对象", "交代分析任务", "说明收益", "直接进入正文"],
            ["是否节省铺垫", "任务是否足够清晰", "正文第一段是否承接开场"],
            cross,
        ),
    ]


def _script_structure_templates(
    positionings: list[str],
    capability_lookup: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    templates = []
    definitions = {
        "Storytelling": (
            "故事叙事结构",
            ["Storytelling", "Character", "Rhythm", "Ending"],
            ["主角/核心对象", "初始处境", "冲突链", "关键选择", "结果回收"],
            ["开场建立冲突任务", "背景铺垫", "冲突升级", "关键选择或反转", "结果与主题回收"],
        ),
        "Logical Narrative": (
            "逻辑叙事结构",
            ["Logic", "Historical Narrative", "Transition", "Ending"],
            ["核心问题", "时间线", "关键变量", "因果链", "阶段结论"],
            ["提出问题", "交代背景变量", "按时间线推进", "汇合因果", "输出阶段判断"],
        ),
        "Historical Narrative": (
            "历史叙事结构",
            ["Historical Narrative", "Storytelling", "Logic", "Character"],
            ["时代背景", "关键人物", "制度/利益变量", "事件链条", "历史后果"],
            ["开场定题", "时代背景", "人物与变量登场", "事件升级", "后果复盘"],
        ),
        "Long Historical Narrative": (
            "长线历史叙事结构",
            ["Historical Narrative", "Storytelling", "Logic", "Ending"],
            ["长时间线", "人物群像", "阶段转折", "制度变量", "最终后果"],
            ["总问题", "阶段一铺垫", "阶段二冲突", "阶段三汇合", "长期影响收束"],
        ),
        "International Commentary": (
            "国际议题解释结构",
            ["Logic", "Historical Narrative", "Narration", "Transition"],
            ["现实议题", "相关国家/组织", "利益变量", "历史背景", "影响判断"],
            ["点出现实争议", "补背景", "拆利益变量", "连接影响链", "给阶段性判断"],
        ),
        "Geopolitical Narrative": (
            "地缘叙事结构",
            ["Logic", "Historical Narrative", "World Building", "Ending"],
            ["地缘对象", "历史背景", "利益冲突", "关键行动", "影响链"],
            ["建立地缘问题", "解释历史背景", "拆冲突变量", "推演影响", "回扣现实判断"],
        ),
        "Science Explanation": (
            "科学解释结构",
            ["Explanation", "Science Narrative", "Teaching", "World Building"],
            ["核心概念", "门槛误区", "机制", "证据", "边界/未知"],
            ["问题导入", "概念降门槛", "机制解释", "证据验证", "边界收束"],
        ),
        "Business Explanation": (
            "商业解释结构",
            ["Explanation", "Logic", "Teaching", "Narration"],
            ["商业问题", "案例对象", "市场变量", "机制", "结果/启示"],
            ["提出商业问题", "放入案例", "拆变量", "解释机制", "回收结果"],
        ),
        "Cross-cultural Short Explainer": (
            "跨文化短解释结构",
            ["Explanation", "Teaching", "Hook", "Rhythm"],
            ["观察差异", "场景", "背景条件", "原因", "可带走解释"],
            ["差异切入", "补场景", "解释背景", "归纳原因", "轻量收束"],
        ),
        "Emotion Narrative": (
            "情绪叙事结构",
            ["Emotion", "Character", "Narration", "Visualization"],
            ["人物处境", "现场细节", "情绪变化", "关键选择", "留白/余味"],
            ["进入现场", "建立人物处境", "推进情绪变化", "集中关键时刻", "留出余味"],
        ),
        "Visual Teaching": (
            "视觉教学结构",
            ["Visualization", "Teaching", "Explanation", "Rhythm"],
            ["概念", "视觉载体", "分层信息", "例子/实验", "结果"],
            ["提出概念问题", "视觉化拆解", "分层推进", "例子验证", "总结理解路径"],
        ),
        "Visual Production": (
            "视觉制作结构",
            ["Visualization", "Teaching", "Explanation", "Rhythm"],
            ["制作问题", "视觉目标", "过程节点", "技术取舍", "结果验证"],
            ["提出制作问题", "展示目标", "拆过程", "解释取舍", "用结果收束"],
        ),
        "Story Analysis": (
            "剧情解析结构",
            ["Plot Analysis", "Character", "World Building", "Emotion"],
            ["作品问题", "剧情节点", "角色动机", "世界观规则", "主题回收"],
            ["提出解析任务", "压缩剧情节点", "解释动机", "连接设定", "主题升华"],
        ),
        "Anime Narrative": (
            "动漫讲解结构",
            ["Anime Narrative", "Plot Analysis", "Character", "World Building"],
            ["主线剧情", "背景设定", "角色动机", "高光节点", "期待点"],
            ["快速进入主线", "补设定", "串动机", "提炼高光", "留下合理期待"],
        ),
    }
    selected = positionings or list(definitions)
    for positioning in selected:
        if positioning not in definitions:
            continue
        name, categories, slots, sequence = definitions[positioning]
        templates.append(
            _template(
                f"structure_{_slug(positioning)}",
                name,
                categories,
                capability_lookup,
                f"内容定位为 {positioning}，需要稳定组织一期完整视频。",
                slots,
                sequence,
                ["开场、正文、高潮、结尾是否服务于同一任务", "每段是否只承担一个主要功能", "结尾是否回收开场承诺"],
                None,
                extra={"positioning": positioning},
            )
        )
    return templates


def _transition_templates(capability_lookup: dict[str, dict[str, Any]], cross: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _template(
            "transition_sequence",
            "顺序推进转场",
            ["Transition", "Logic", "Narration"],
            capability_lookup,
            "正文需要从背景、变量、过程逐步推进。",
            ["上一段结论", "下一段任务", "顺序关系"],
            ["总结上一段功能", "标记下一步", "进入新信息"],
            ["是否降低跳跃感", "是否把段落关系说清楚"],
            cross,
        ),
        _template(
            "transition_turning_point",
            "转折校正转场",
            ["Transition", "Hook", "Logic"],
            capability_lookup,
            "前文结论需要被修正、反驳或补充另一面。",
            ["前文判断", "反向证据", "校正方向"],
            ["承认前文有效范围", "引出相反变量", "说明新判断"],
            ["转折是否有证据支撑", "是否避免为了反转而反转"],
            cross,
        ),
        _template(
            "transition_causal_close",
            "因果收束转场",
            ["Transition", "Logic", "Ending"],
            capability_lookup,
            "多段信息需要汇合成原因、后果或阶段结论。",
            ["原因A", "原因B", "结果", "阶段判断"],
            ["回收变量", "合并因果", "输出阶段结论"],
            ["是否把原因和结果分清", "是否能自然进入下一段或结尾"],
            cross,
        ),
        _template(
            "transition_example_bridge",
            "例子桥接转场",
            ["Transition", "Teaching", "Explanation"],
            capability_lookup,
            "抽象概念或复杂判断需要用例子承接。",
            ["抽象概念", "例子", "例子和概念的对应关系"],
            ["提出抽象点", "放入例子", "指出对应关系", "回到主线"],
            ["例子是否只解释一个重点", "例子结束后是否回到主线"],
            cross,
        ),
    ]


def _climax_templates(capability_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _template(
            "climax_conflict_convergence",
            "冲突汇合高潮",
            ["Storytelling", "Character", "Rhythm"],
            capability_lookup,
            "故事线或历史线有多条冲突需要在中后段汇合。",
            ["主要冲突", "关键选择", "代价", "结果"],
            ["前文铺冲突", "集中关键选择", "展示后果", "进入结果回收"],
            ["高潮是否来自前文铺垫", "选择和后果是否清晰"],
            None,
        ),
        _template(
            "climax_evidence_convergence",
            "证据汇合高潮",
            ["Logic", "Explanation", "Historical Narrative"],
            capability_lookup,
            "前文拆了多条变量，需要在高潮处形成判断。",
            ["变量列表", "关键证据", "判断", "反例边界"],
            ["回收变量", "集中证据", "输出判断", "说明边界"],
            ["证据是否支持判断", "边界是否避免过度推断"],
            None,
        ),
        _template(
            "climax_mechanism_reveal",
            "机制揭示高潮",
            ["Explanation", "Science Narrative", "Teaching"],
            capability_lookup,
            "观众已经知道现象，但还不知道背后机制。",
            ["现象", "核心机制", "验证材料", "边界"],
            ["复述现象", "揭示机制", "用证据验证", "收束未知边界"],
            ["机制是否比现象更清楚", "解释是否有递进层级"],
            None,
        ),
        _template(
            "climax_visual_result",
            "视觉结果高潮",
            ["Visualization", "Teaching", "Rhythm"],
            capability_lookup,
            "视频包含实验、制作、画面验证或视觉结论。",
            ["制作目标", "关键过程", "最终画面/结果", "经验复盘"],
            ["铺设制作目标", "集中展示关键过程", "呈现结果", "复盘取舍"],
            ["结果是否回答开场问题", "视觉信息是否承担解释功能"],
            None,
        ),
    ]


def _ending_templates(capability_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _template(
            "ending_question_callback",
            "问题回扣结尾",
            ["Ending", "Hook", "Explanation"],
            capability_lookup,
            "开场用问题建立任务，结尾需要给观众明确收获。",
            ["开场问题", "核心答案", "边界", "观众带走点"],
            ["复现问题", "给出答案", "说明边界", "压缩成带走点"],
            ["是否回答开场承诺", "是否避免新增未解释信息"],
            None,
        ),
        _template(
            "ending_logic_closure",
            "观点闭环结尾",
            ["Ending", "Logic", "Narration"],
            capability_lookup,
            "正文是因果链、历史链或现实议题判断。",
            ["关键变量", "阶段结论", "现实/作品意义"],
            ["回收变量", "输出阶段判断", "连接意义"],
            ["结论是否来自正文", "是否区分事实、推断和价值判断"],
            None,
        ),
        _template(
            "ending_emotional_aftertaste",
            "情绪余味结尾",
            ["Ending", "Emotion", "Character"],
            capability_lookup,
            "视频以人物处境、纪录片现场或剧情情绪为核心。",
            ["人物处境", "变化", "未说尽之处", "观众情绪落点"],
            ["回到人物", "点出变化", "保留留白", "轻收束"],
            ["情绪是否来自材料本身", "留白是否仍有清晰理解落点"],
            None,
        ),
        _template(
            "ending_expectation_bridge",
            "期待桥接结尾",
            ["Ending", "Anime Narrative", "Plot Analysis"],
            capability_lookup,
            "系列、剧情或专题后续仍有推进空间。",
            ["本期结论", "未解决问题", "下一阶段期待"],
            ["总结本期", "点出未解决张力", "建立后续期待"],
            ["期待是否来自剧情或议题本身", "是否避免空泛吊胃口"],
            None,
        ),
    ]


def _workflow_templates(capability_lookup: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _template(
            "workflow_topic_to_script",
            "选题到脚本工作流",
            ["Hook", "Logic", "Rhythm", "Ending"],
            capability_lookup,
            "已有选题，需要生成可写作、可分镜、可检索的脚本骨架。",
            ["选题", "目标观众", "核心问题", "资料证据", "情绪目标", "结尾带走点"],
            ["确定观看任务", "选择 Hook 模板", "列信息层级", "安排高潮", "设计结尾", "检查禁用项"],
            ["是否有明确观看任务", "是否有证据链", "是否没有模仿具体 UP 措辞"],
            None,
        ),
        _template(
            "workflow_review_before_generation",
            "生成前复核工作流",
            ["Teaching", "Narration", "Visualization"],
            capability_lookup,
            "准备调用知识库生成脚本、分镜或视频方案前。",
            ["目标能力", "适用模板", "素材证据", "禁用表达", "质量检查"],
            ["确认能力类别", "选择模板", "填入素材", "删去可模仿表达", "做结构检查"],
            ["是否只调用能力结构", "是否保留事实复核入口", "是否没有复制原句或口头禅"],
            None,
        ),
    ]


def _template(
    template_id: str,
    name: str,
    categories: list[str],
    capability_lookup: dict[str, dict[str, Any]],
    use_when: str,
    input_slots: list[str],
    sequence: list[str],
    checks: list[str],
    cross: dict[str, Any] | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source_docs = [capability_lookup.get(category, {}) for category in categories]
    source_creators = sorted(
        {
            creator
            for doc in source_docs
            for creator in doc.get("creators", [])
            if creator
        }
    )
    source_video_ids = sorted(
        {
            str(video_id)
            for doc in source_docs
            for video_id in doc.get("source_video_ids", [])
            if video_id
        }
    )
    template = {
        "id": template_id,
        "name": name,
        "related_categories": categories,
        "capability": " / ".join(
            doc.get("capability", category)
            for category, doc in zip(categories, source_docs)
        ),
        "use_when": use_when,
        "input_slots": input_slots,
        "sequence": sequence,
        "quality_checks": checks,
        "evidence": {
            "source_creators": source_creators,
            "source_video_count": len(source_video_ids),
            "source_video_ids": source_video_ids[:50],
        },
        "forbidden": ["复制原文句子", "模仿某位UP口头禅", "套用个人化语气", "照搬具体观点"],
        "rag_text": (
            f"{name}。适用场景：{use_when}。"
            f" 输入槽位：{'、'.join(input_slots)}。"
            f" 执行顺序：{' -> '.join(sequence)}。"
            f" 检查：{'；'.join(checks)}。"
            " 只能调用结构和功能，不能模仿具体创作者表达。"
        ),
    }
    if cross:
        template["cross_signals"] = {
            "common_structure": cross.get("共同结构", []),
            "common_hooks": cross.get("共同Hook", [])[:5],
            "common_transitions": cross.get("共同转场", [])[:5],
        }
    if extra:
        template.update(extra)
    return template


def _template_rag_documents(collections: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    documents = []
    for collection_name, templates in collections.items():
        for template in templates:
            documents.append(
                {
                    "chunk_id": f"template:{template['id']}",
                    "category": "Template",
                    "template_collection": collection_name,
                    "title": template["name"],
                    "capability": template.get("capability", ""),
                    "related_categories": template.get("related_categories", []),
                    "source_video_ids": template.get("evidence", {}).get("source_video_ids", []),
                    "text": template["rag_text"],
                    "metadata": {
                        "do_not_copy": True,
                        "source_type": "creator_template",
                    },
                }
            )
    return documents


def _build_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Creator Template Library",
        "",
        f"生成时间：{payload['generated_at']}",
        "",
        "## 使用规则",
        "",
        "- 这些模板只规定结构、顺序、槽位和检查标准。",
        "- 不输出、不保存、也不建议模仿任何 UP 的原句、口头禅或个人化表达。",
        "",
        "## 来源范围",
        "",
        f"- 创作者画像：{payload['source']['creator_count']} 个",
        f"- 视频样本：{payload['source']['video_count']} 条",
        f"- 已识别定位：{'、'.join(payload['source']['positionings']) or '暂无'}",
        "",
    ]
    titles = {
        "hook_templates": "Hook 模板",
        "script_structure_templates": "脚本结构模板",
        "transition_templates": "转场模板",
        "climax_templates": "高潮模板",
        "ending_templates": "结尾模板",
        "workflow_templates": "工作流模板",
    }
    for collection_name in TEMPLATE_COLLECTIONS:
        lines.extend(["", f"## {titles[collection_name]}", ""])
        for template in payload.get(collection_name, []):
            lines.extend(
                [
                    f"### {template['name']}",
                    "",
                    f"- ID：`{template['id']}`",
                    f"- 适用：{template['use_when']}",
                    f"- 输入槽位：{'、'.join(template['input_slots'])}",
                    f"- 执行顺序：{' -> '.join(template['sequence'])}",
                    f"- 检查标准：{'；'.join(template['quality_checks'])}",
                    f"- 支撑样本：{template['evidence']['source_video_count']} 条",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value)).strip("_") or "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build creator capability template library.")
    parser.add_argument("--output-root", default=str(SETTINGS.output_dir))
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--cache-root", default=str(SETTINGS.cache_dir))
    args = parser.parse_args()

    paths = build_template_library(
        output_root=Path(args.output_root),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        cache_root=Path(args.cache_root),
    )
    for kind, path in paths.items():
        print(f"{kind}: {path}")


if __name__ == "__main__":
    main()
