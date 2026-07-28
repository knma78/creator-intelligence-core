from __future__ import annotations

from typing import Any

from analyzer.keywords import extract_keywords

POSITIVE_WORDS = ["好看", "喜欢", "支持", "厉害", "优秀", "学到了", "牛", "赞", "舒服"]
NEGATIVE_WORDS = ["不好", "垃圾", "失望", "难受", "错误", "离谱", "尴尬", "反感"]


def analyze_comments(comments_payload: dict[str, Any]) -> dict[str, Any]:
    comments = comments_payload.get("comments") or []
    messages = [str(item.get("message", "")) for item in comments if item.get("message")]
    text = "\n".join(messages)
    positive = sum(text.count(word) for word in POSITIVE_WORDS)
    negative = sum(text.count(word) for word in NEGATIVE_WORDS)
    return {
        "status": comments_payload.get("status"),
        "comment_count": len(messages),
        "keywords": extract_keywords(text, top_n=20) if text else [],
        "sentiment": _sentiment_label(positive, negative),
        "signals": {
            "positive_words": positive,
            "negative_words": negative,
            "question_marks": text.count("?") + text.count("？"),
            "exclamation_marks": text.count("!") + text.count("！"),
        },
        "hot_comments": sorted(
            comments,
            key=lambda item: int(item.get("like") or 0),
            reverse=True,
        )[:10],
        "reason": comments_payload.get("reason"),
    }


def _sentiment_label(positive: int, negative: int) -> str:
    if positive > negative:
        return "偏正向"
    if negative > positive:
        return "偏负向"
    return "中性/混合"
