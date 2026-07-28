from __future__ import annotations

import json
import re
from collections import Counter

STOPWORDS = {
    "一个", "这个", "那个", "我们", "你们", "他们", "就是", "然后", "所以", "因为",
    "但是", "如果", "可以", "不是", "没有", "还是", "什么", "怎么", "为什么",
    "其实", "可能", "现在", "时候", "自己", "大家", "这些", "那些", "进行",
    "视频", "内容", "今天", "本期", "这样", "这里", "一下", "一种", "问题",
}


def extract_keywords(text: str, top_n: int = 20) -> list[dict[str, int | str]]:
    words = _tokenize(text)
    counter = Counter(word for word in words if _keep_word(word))
    return [
        {"word": word, "count": count}
        for word, count in counter.most_common(top_n)
    ]


def _tokenize(text: str) -> list[str]:
    try:
        import jieba

        return [word.strip() for word in jieba.cut(text) if word.strip()]
    except ImportError:
        return _fallback_tokenize(text)


def _fallback_tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for item in re.findall(r"[\u4e00-\u9fff]+|[A-Za-z][A-Za-z0-9_+-]{2,}", text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", item):
            if len(item) <= 4:
                tokens.append(item)
            else:
                tokens.extend(item[i : i + 2] for i in range(len(item) - 1))
                tokens.extend(item[i : i + 3] for i in range(len(item) - 2))
        else:
            tokens.append(item.lower())
    return tokens


def _keep_word(word: str) -> bool:
    if len(word) < 2:
        return False
    if word in STOPWORDS:
        return False
    if word.isdigit():
        return False
    if re.fullmatch(r"\W+", word):
        return False
    return True


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Extract high-frequency keywords from text.")
    parser.add_argument("text_file")
    parser.add_argument("--top-n", type=int, default=20)
    args = parser.parse_args()
    text = Path(args.text_file).read_text(encoding="utf-8")
    print(json.dumps(extract_keywords(text, args.top_n), ensure_ascii=False, indent=2))
