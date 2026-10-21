from __future__ import annotations

import json
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import Settings


_ENGLISH_STOP_TERMS = {
    "the", "and", "for", "with", "from", "this", "that", "into",
    "your", "you", "are", "was", "were", "will", "can", "how",
    "why", "what", "video", "about", "then", "than", "but",
}
_CHINESE_STOP_TERMS = {
    "这个", "那个", "一个", "我们", "你们", "他们", "可以", "可能",
    "已经", "没有", "不是", "就是", "还是", "以及", "因为", "所以",
    "然后", "如果", "那么", "如何", "为什么", "视频", "文稿", "内容",
    "介绍", "开始", "进行", "需要", "能够", "真的", "来看", "看看",
    "什么", "怎么", "为何", "这些", "那些", "其中", "最后", "说明",
    "分析", "发现", "寻找", "意味", "意味着", "最新", "线索", "证据",
    "探索", "相关", "自然", "环境", "红色", "星球", "存在",
    "事情", "问题",
}
_GENERIC_MATCH_TERMS = {"星上"}
_VISUAL_INTENT_RULES: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (
        re.compile(r"数据|比例|统计|步骤|原理|结构|对比|研究|报告|解释|教程"),
        ("infographic", "tutorial screen", "text-heavy poster"),
    ),
    (
        re.compile(r"人物|他说|她说|采访|观点|创始人|作者|专家|情绪"),
        ("talking head", "emotional face"),
    ),
    (
        re.compile(r"产品|手机|电脑|汽车|设备|商品|品牌"),
        ("product close-up", "tutorial screen"),
    ),
    (
        re.compile(r"宇宙|星球|地球|火星|海洋|山川|城市|自然|风景"),
        ("landscape", "movie scene"),
    ),
    (
        re.compile(r"战争|爆炸|战斗|冲突|灾难|追逐|危险"),
        ("action scene", "movie scene"),
    ),
    (re.compile(r"动漫|动画|漫画|二次元"), ("anime illustration",)),
    (re.compile(r"游戏|玩家|关卡|电竞"), ("gameplay",)),
    (re.compile(r"震惊|离谱|笑|搞笑|梗|荒诞"), ("meme", "emotional face")),
)
_MIN_ASSET_MATCH_SCORE = 12.0


def cover_catalog(
    settings: Settings,
    *,
    load_analysis: bool,
) -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for directory in research_directories(settings):
        cover = next(
            (
                directory / name
                for name in (
                    "cover.jpg",
                    "cover.jpeg",
                    "cover.png",
                    "cover.webp",
                    "thumbnail.jpg",
                )
                if _usable_cover_image(directory / name)
            ),
            None,
        )
        if cover is None:
            continue
        analysis = read_json(directory / "analysis.json") if load_analysis else {}
        enrichment = read_json(directory / "v3.json") if load_analysis else {}
        keywords = []
        for item in analysis.get("keywords") or []:
            if isinstance(item, dict):
                value = str(item.get("word") or item.get("keyword") or "")
            else:
                value = str(item or "")
            if value.strip():
                keywords.append(value.strip())
        cover_analysis = enrichment.get("cover_analysis") or {}
        ocr_text = str((cover_analysis.get("ocr") or {}).get("text") or "")
        visual_semantics = cover_analysis.get("visual_semantics") or {}
        visual_labels = [
            {
                "label": str(item.get("label") or "").strip(),
                "label_zh": str(item.get("label_zh") or "").strip(),
                "score": round(float(item.get("score") or 0), 6),
            }
            for item in visual_semantics.get("top_labels") or []
            if isinstance(item, dict) and str(item.get("label") or "").strip()
        ]
        title = str(analysis.get("title") or directory.name)
        summary = str(analysis.get("one_sentence_summary") or "")
        fields = {
            "title": semantic_terms(title),
            "summary": semantic_terms(summary),
            "keywords": semantic_terms(" ".join(keywords)),
            "ocr": semantic_terms(ocr_text),
        }
        catalog.append(
            {
                "source_id": directory.name,
                "path": str(cover.resolve()),
                "title": title,
                "summary": summary,
                "keywords": keywords,
                "ocr_text": ocr_text,
                "field_terms": fields,
                "visual_labels": visual_labels,
                "openclip_ready": visual_semantics.get("status") == "ok",
                "search_text": " ".join([title, summary, *keywords, ocr_text]),
            }
        )
    return catalog


def rank_assets(
    text: str,
    catalog: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    query = semantic_terms(text)
    if not query or not catalog:
        return []
    documents = [
        set().union(
            *(set(value) for value in (asset.get("field_terms") or {}).values())
        )
        for asset in catalog
    ]
    document_frequency = {
        term: sum(1 for document in documents if term in document)
        for term in query
    }
    visual_intents = _visual_intents(text)
    field_weights = {
        "title": 5.0,
        "keywords": 6.0,
        "summary": 3.0,
        "ocr": 2.0,
    }
    ranked: list[dict[str, Any]] = []
    for asset, document in zip(catalog, documents):
        if not document:
            continue
        best_term_scores: dict[str, float] = {}
        matched_fields: dict[str, list[str]] = {}
        fields = asset.get("field_terms") or {}
        for field, weight in field_weights.items():
            matches = (
                query & set(fields.get(field) or set())
            ) - _GENERIC_MATCH_TERMS
            if matches:
                matched_fields[field] = sorted(matches)
            for term in matches:
                frequency = document_frequency.get(term, 0)
                idf = math.log((1 + len(catalog)) / (1 + frequency)) + 1
                specificity = 1 + min(2, max(0, len(term) - 2)) * 0.35
                contribution = weight * idf * specificity
                best_term_scores[term] = max(
                    contribution,
                    best_term_scores.get(term, 0),
                )
        lexical_score = sum(best_term_scores.values())
        normalized_query = re.sub(r"\s+", "", text.lower())
        exact_keywords = []
        for item in asset.get("keywords") or []:
            normalized_keyword = re.sub(r"\s+", "", item.lower())
            keyword_terms = semantic_terms(item)
            if (
                len(normalized_keyword) >= 2
                and keyword_terms
                and keyword_terms.issubset(query)
                and normalized_keyword in normalized_query
            ):
                exact_keywords.append(item)
        lexical_score += len(exact_keywords) * 8
        if lexical_score <= 0:
            continue

        matched_topics = _collapse_semantic_terms(best_term_scores)
        title_terms = set(fields.get("title") or set())
        strong_single_topic = bool(
            len(matched_topics) == 1
            and matched_topics[0] in title_terms
            and exact_keywords
        )
        if len(matched_topics) < 2 and not strong_single_topic:
            continue

        matching_labels = [
            item
            for item in asset.get("visual_labels") or []
            if item.get("label") in visual_intents
        ]
        visual_score = sum(
            max(0.0, float(item.get("score") or 0)) * 8
            for item in matching_labels[:2]
        )
        score = lexical_score + visual_score
        if score < _MIN_ASSET_MATCH_SCORE:
            continue
        confidence = (
            "high"
            if len(matched_topics) >= 3
            or (len(matched_topics) >= 2 and exact_keywords)
            else "medium"
        )
        reasons = []
        if exact_keywords:
            reasons.append("关键词精确命中：" + "、".join(exact_keywords[:4]))
        for field, label in (
            ("title", "标题"),
            ("summary", "摘要"),
            ("ocr", "封面 OCR"),
        ):
            if matched_fields.get(field):
                reasons.append(
                    f"{label}相关：" + "、".join(matched_fields[field][:4])
                )
        if matching_labels:
            reasons.append(
                "OpenCLIP 视觉类型："
                + "、".join(
                    str(item.get("label_zh") or item.get("label"))
                    for item in matching_labels[:2]
                )
            )
        ranked.append(
            {
                **asset,
                "score": round(score, 2),
                "confidence": confidence,
                "matched_terms": matched_topics[:8],
                "match_reasons": reasons or ["主题词相关"],
                "score_breakdown": {
                    "lexical": round(lexical_score, 2),
                    "visual_style": round(visual_score, 2),
                },
            }
        )
    ranked.sort(
        key=lambda item: (item["score"], item["source_id"]),
        reverse=True,
    )
    return ranked


def semantic_terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = {
        term
        for term in re.findall(r"[a-z0-9_]{3,}", lowered)
        if term not in _ENGLISH_STOP_TERMS
    }
    chinese_text = lowered
    for phrase in sorted(_CHINESE_STOP_TERMS, key=len, reverse=True):
        chinese_text = chinese_text.replace(phrase, " ")
    for segment in re.findall(r"[\u3400-\u9fff]+", chinese_text):
        for size in (2, 3, 4):
            terms.update(
                segment[index : index + size]
                for index in range(max(0, len(segment) - size + 1))
            )
    terms.difference_update(_CHINESE_STOP_TERMS)
    return {term for term in terms if term}


def research_directories(settings: Settings) -> list[Path]:
    if not settings.output_dir.is_dir():
        return []
    directories = [
        item
        for item in settings.output_dir.iterdir()
        if (
            item.is_dir()
            and item.name != "video_production"
            and (item / "analysis.json").is_file()
        )
    ]
    directories.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return directories


def read_json(path: Path) -> dict[str, Any]:
    if not Path(path).is_file():
        return {}
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


@lru_cache(maxsize=2048)
def _verify_cover_image(
    path_value: str,
    file_size: int,
    modified_ns: int,
) -> bool:
    del file_size, modified_ns
    try:
        from PIL import Image
    except ImportError:
        return True
    try:
        with Image.open(path_value) as image:
            image.verify()
        return True
    except (OSError, SyntaxError, ValueError):
        return False


def _usable_cover_image(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size <= 0:
        return False
    try:
        stat = path.stat()
    except OSError:
        return False
    return _verify_cover_image(
        str(path.resolve()),
        stat.st_size,
        stat.st_mtime_ns,
    )


def _collapse_semantic_terms(scores: dict[str, float]) -> list[str]:
    ordered = sorted(
        scores,
        key=lambda term: (scores[term], len(term), term),
        reverse=True,
    )
    collapsed: list[str] = []
    for term in ordered:
        if any(term in existing or existing in term for existing in collapsed):
            continue
        collapsed.append(term)
    return collapsed


def _visual_intents(text: str) -> set[str]:
    labels: set[str] = set()
    for pattern, candidates in _VISUAL_INTENT_RULES:
        if pattern.search(text):
            labels.update(candidates)
    return labels
