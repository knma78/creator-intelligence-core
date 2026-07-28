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
from rag.knowledge_base import build_knowledge_base, search_knowledge_base

logger = logging.getLogger(__name__)


def generate_research_report(
    query: str,
    settings: Settings = SETTINGS,
    top_k: int = 8,
    rebuild_kb: bool = False,
) -> dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("query is required")

    index_path = settings.knowledge_base_dir / "index.json"
    if rebuild_kb or not index_path.exists():
        build_knowledge_base(settings.output_dir, index_path, settings)

    results = search_knowledge_base(query, index_path, top_k=top_k, settings=settings)
    if not results:
        raise ValueError("知识库里没有找到相关内容，请先分析视频或UP主页并构建知识库。")

    evidence = _load_evidence(results, index_path)
    report_markdown, raw_llm_result = _generate_with_llm(query, evidence, settings)
    if not report_markdown:
        report_markdown = _generate_local_report(query, evidence)

    output_dir = _report_output_dir(settings, query)
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "report.md"
    json_path = output_dir / "report.json"
    markdown_path.write_text(report_markdown, encoding="utf-8")

    payload = {
        "query": query,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "top_k": top_k,
        "index_path": str(index_path),
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "source_count": len(evidence),
        "sources": [_source_summary(item) for item in evidence],
        "raw_llm_result": raw_llm_result,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {**payload, "markdown_path": markdown_path, "json_path": json_path}


def _load_evidence(results: list[dict[str, Any]], index_path: Path) -> list[dict[str, Any]]:
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    documents = {doc.get("chunk_id"): doc for doc in index_payload.get("documents", [])}
    evidence = []
    seen: set[str] = set()
    for result in results:
        chunk_id = result.get("chunk_id")
        doc = documents.get(chunk_id, {})
        source_path = Path(str(result.get("source_path") or doc.get("source_path") or ""))
        analysis = _read_json(source_path / "analysis.json")
        v3 = _read_json(source_path / "v3.json")
        video_id = str(result.get("video_id") or doc.get("video_id") or source_path.name)
        dedupe_key = f"{video_id}:{chunk_id}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        evidence.append(
            {
                "score": result.get("score"),
                "chunk_id": chunk_id,
                "video_id": video_id,
                "title": result.get("title") or analysis.get("title") or doc.get("title") or video_id,
                "source_path": str(source_path),
                "excerpt": result.get("excerpt") or "",
                "chunk_text": doc.get("text") or "",
                "analysis": analysis,
                "v3": v3,
            }
        )
    return evidence


def _generate_with_llm(
    query: str,
    evidence: list[dict[str, Any]],
    settings: Settings,
) -> tuple[str | None, dict[str, Any] | None]:
    if not settings.llm_api_key:
        return None, None
    try:
        from openai import OpenAI
    except ImportError:
        return None, None

    client_kwargs: dict[str, Any] = {
        "api_key": settings.llm_api_key,
        "timeout": settings.llm_timeout,
    }
    if settings.llm_base_url:
        client_kwargs["base_url"] = settings.llm_base_url
    client = OpenAI(**client_kwargs)
    prompt = _build_llm_prompt(query, evidence, settings.llm_max_chars)
    try:
        response = client.chat.completions.create(
            model=settings.llm_model,
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": "你是内容研究分析师。基于给定知识库证据写中文Markdown报告，不要编造证据。",
                },
                {"role": "user", "content": prompt},
            ],
        )
        markdown = response.choices[0].message.content or ""
        return markdown.strip(), {"model": settings.llm_model, "used": True}
    except Exception as exc:  # pragma: no cover - provider/network dependent
        logger.warning("V4 LLM report generation failed, fallback to local report: %s", exc)
        return None, {"model": settings.llm_model, "used": False, "error": str(exc)}


def _build_llm_prompt(query: str, evidence: list[dict[str, Any]], max_chars: int) -> str:
    compact = []
    used = 0
    for index, item in enumerate(evidence, start=1):
        analysis = item.get("analysis") or {}
        v3 = item.get("v3") or {}
        block = "\n".join(
            [
                f"证据 {index}",
                f"视频ID: {item.get('video_id')}",
                f"标题: {item.get('title')}",
                f"匹配分数: {item.get('score')}",
                f"一句话总结: {analysis.get('one_sentence_summary', '')}",
                f"Hook: {json.dumps(analysis.get('hook', {}), ensure_ascii=False)}",
                f"节奏: {json.dumps(analysis.get('rhythm', {}), ensure_ascii=False)}",
                f"高频词: {json.dumps(analysis.get('keywords', [])[:12], ensure_ascii=False)}",
                f"评论分析: {json.dumps(v3.get('comments_analysis', {}), ensure_ascii=False)}",
                f"封面分析: {json.dumps(v3.get('cover_analysis', {}), ensure_ascii=False)[:1000]}",
                f"片段: {item.get('chunk_text', '')[:1600]}",
            ]
        )
        if used + len(block) > max_chars:
            break
        compact.append(block)
        used += len(block)
    return f"""
研究问题：{query}

请只基于下面知识库证据生成一份可执行的中文 Markdown 报告。

报告结构：
# V4 AI研究报告
## 核心结论
## 为什么表现好/问题成立的关键因素
## 内容策略拆解
## Hook与标题规律
## 节奏、结构和情绪规律
## 评论与封面信号
## 可复用方法
## 证据来源
## 下一步建议

要求：
- 每个结论都尽量绑定证据来源的视频标题或视频ID。
- 如果证据不足，明确写“证据不足”。
- 不要编造播放量、作者、平台数据。
- 语言直接，偏策略报告，不要写成泛泛总结。

知识库证据：
{chr(10).join(compact)}
""".strip()


def _generate_local_report(query: str, evidence: list[dict[str, Any]]) -> str:
    hook_counter: Counter[str] = Counter()
    keyword_counter: Counter[str] = Counter()
    title_tokens: Counter[str] = Counter()
    rhythms: list[str] = []
    comment_signals: list[str] = []
    cover_signals: list[str] = []

    for item in evidence:
        analysis = item.get("analysis") or {}
        v3 = item.get("v3") or {}
        hook_style = str((analysis.get("hook") or {}).get("开头方式", "")).strip()
        if hook_style:
            hook_counter[hook_style] += 1
        for keyword in analysis.get("keywords", []):
            word = str(keyword.get("word", "")).strip()
            count = int(keyword.get("count") or 1)
            if word:
                keyword_counter[word] += count
        for token in _simple_title_tokens(str(item.get("title", ""))):
            title_tokens[token] += 1
        rhythm = str((analysis.get("rhythm") or {}).get("节奏变化", "")).strip()
        if rhythm:
            rhythms.append(rhythm)
        comments = v3.get("comments_analysis") or {}
        if comments:
            comment_signals.append(
                f"{item.get('title')}：评论情绪 {comments.get('sentiment', '未知')}，关键词 {_format_keywords(comments.get('keywords', [])[:5])}"
            )
        cover = v3.get("cover_analysis") or {}
        ocr_text = ((cover.get("ocr") or {}).get("text") or "").strip()
        if ocr_text:
            cover_signals.append(f"{item.get('title')}：封面文字“{ocr_text[:80]}”")

    top_keywords = keyword_counter.most_common(12)
    top_title_tokens = title_tokens.most_common(10)
    top_hooks = hook_counter.most_common(6)
    lines = [
        "# V4 AI研究报告",
        "",
        "## 研究问题",
        "",
        query,
        "",
        "## 核心结论",
        "",
        _local_conclusion(top_hooks, top_keywords, top_title_tokens),
        "",
        "## 为什么表现好/问题成立的关键因素",
        "",
        "- 高频内容信号集中在：" + (_format_counter(top_keywords) or "证据不足。"),
        "- 标题常见表达集中在：" + (_format_counter(top_title_tokens) or "证据不足。"),
        "- 常见开头方式集中在：" + (_format_hook_counter(top_hooks) or "证据不足。"),
        "",
        "## 内容策略拆解",
        "",
    ]
    for item in evidence:
        analysis = item.get("analysis") or {}
        lines.extend(
            [
                f"### {item.get('title')}",
                "",
                f"- 匹配分数：{item.get('score')}",
                f"- 一句话总结：{analysis.get('one_sentence_summary', '')}",
                f"- Hook：{json.dumps(analysis.get('hook', {}), ensure_ascii=False)}",
                f"- 高频词：{_format_keywords(analysis.get('keywords', [])[:8])}",
                f"- 证据片段：{item.get('excerpt', '')}",
                "",
            ]
        )
    lines.extend(
        [
            "## Hook与标题规律",
            "",
            "- Hook规律：" + (_format_hook_counter(top_hooks) or "证据不足。"),
            "- 标题词规律：" + (_format_counter(top_title_tokens) or "证据不足。"),
            "",
            "## 节奏、结构和情绪规律",
            "",
        ]
    )
    if rhythms:
        lines.extend(f"- {text}" for text in rhythms[:8])
    else:
        lines.append("- 证据不足。")
    lines.extend(["", "## 评论与封面信号", ""])
    if comment_signals or cover_signals:
        lines.extend(f"- {text}" for text in (comment_signals + cover_signals)[:12])
    else:
        lines.append("- 当前知识库缺少评论或封面分析，建议用 V3 增强重新分析后构建知识库。")
    lines.extend(
        [
            "",
            "## 可复用方法",
            "",
            "- 先用问题、反差或明确收益建立观看理由。",
            "- 在标题和开头重复核心关键词，降低观众理解成本。",
            "- 把内容拆成可识别的结构段落，并在后段做总结收束。",
            "- 用评论关键词反推观众真实关注点，再反哺标题和选题。",
            "",
            "## 证据来源",
            "",
        ]
    )
    for item in evidence:
        lines.append(f"- {item.get('title')}（{item.get('video_id')}，score={item.get('score')}）")
    lines.extend(
        [
            "",
            "## 下一步建议",
            "",
            "- 对高分证据视频补充 V3 增强分析，尤其是评论和封面 OCR。",
            "- 扩大 UP 批量分析数量后重建知识库，再生成第二版报告。",
            "- 将本报告里的 Hook、标题词和节奏规律整理成选题模板。",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def _local_conclusion(
    hooks: list[tuple[str, int]],
    keywords: list[tuple[str, int]],
    title_tokens: list[tuple[str, int]],
) -> str:
    parts = []
    if hooks:
        parts.append(f"样本里最常见的开头方式是“{hooks[0][0]}”。")
    if keywords:
        parts.append(f"内容高频词集中在“{'、'.join(word for word, _ in keywords[:5])}”。")
    if title_tokens:
        parts.append(f"标题表达高频词集中在“{'、'.join(word for word, _ in title_tokens[:5])}”。")
    if not parts:
        return "当前知识库证据不足，无法稳定回答这个问题。"
    return " ".join(parts) + " 这说明答案更可能来自选题表达、开头信息缺口和内容结构的共同作用。"


def _format_counter(items: list[tuple[str, int]]) -> str:
    return "、".join(f"{word}({count})" for word, count in items)


def _format_hook_counter(items: list[tuple[str, int]]) -> str:
    return "、".join(f"{style}({count})" for style, count in items)


def _format_keywords(items: list[dict[str, Any]]) -> str:
    return "、".join(f"{item.get('word')}({item.get('count', 0)})" for item in items if item.get("word")) or "无"


def _simple_title_tokens(title: str) -> list[str]:
    tokens = []
    for item in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_+-]{2,}", title):
        if re.fullmatch(r"[\u4e00-\u9fff]+", item):
            tokens.extend(item[index : index + 2] for index in range(len(item) - 1))
        else:
            tokens.append(item.lower())
    return tokens


def _source_summary(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "video_id": item.get("video_id"),
        "title": item.get("title"),
        "score": item.get("score"),
        "chunk_id": item.get("chunk_id"),
        "source_path": item.get("source_path"),
    }


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _report_output_dir(settings: Settings, query: str) -> Path:
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", query, flags=re.UNICODE).strip("_")
    safe = safe[:40] or "report"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return settings.output_dir / "v4_reports" / f"{stamp}_{safe}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a V4 research report from the local knowledge base.")
    parser.add_argument("query")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--rebuild-kb", action="store_true")
    args = parser.parse_args()
    result = generate_research_report(args.query, SETTINGS, top_k=args.top_k, rebuild_kb=args.rebuild_kb)
    print(result["markdown_path"])


if __name__ == "__main__":
    main()
