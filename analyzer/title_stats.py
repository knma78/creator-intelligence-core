from __future__ import annotations

import re
from statistics import mean
from typing import Any

from analyzer.keywords import extract_keywords


def analyze_title_stats(titles: list[str]) -> dict[str, Any]:
    clean_titles = [title.strip() for title in titles if title and title.strip()]
    lengths = [len(title) for title in clean_titles]
    return {
        "count": len(clean_titles),
        "average_length": round(mean(lengths), 2) if lengths else 0,
        "max_length": max(lengths) if lengths else 0,
        "min_length": min(lengths) if lengths else 0,
        "question_title_count": sum(1 for title in clean_titles if "?" in title or "？" in title),
        "number_title_count": sum(1 for title in clean_titles if re.search(r"\d+", title)),
        "exclamation_title_count": sum(1 for title in clean_titles if "!" in title or "！" in title),
        "bracket_title_count": sum(1 for title in clean_titles if re.search(r"[【\[].+[】\]]", title)),
        "top_keywords": extract_keywords("\n".join(clean_titles), top_n=30) if clean_titles else [],
        "patterns": _detect_title_patterns(clean_titles),
    }


def _detect_title_patterns(titles: list[str]) -> list[dict[str, Any]]:
    checks = {
        "问题式": lambda title: "?" in title or "？" in title or title.startswith(("为什么", "如何", "怎么")),
        "数字清单式": lambda title: bool(re.search(r"\d+|三|四|五|十", title)) and any(word in title for word in ["个", "条", "点", "种", "分钟"]),
        "强结果式": lambda title: any(word in title for word in ["爆", "涨", "翻倍", "高播放", "赚钱", "逆袭"]),
        "冲突反差式": lambda title: any(word in title for word in ["但是", "却", "反而", "没想到", "真相"]),
    }
    result = []
    for name, matcher in checks.items():
        matched = [title for title in titles if matcher(title)]
        result.append({"pattern": name, "count": len(matched), "examples": matched[:5]})
    return result
