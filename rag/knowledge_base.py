from __future__ import annotations

import argparse
import json
import logging
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings

TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[A-Za-z0-9_+-]+")
logger = logging.getLogger(__name__)


def build_knowledge_base(
    output_root: Path,
    index_path: Path | None = None,
    settings: Settings = SETTINGS,
) -> Path:
    index_path = index_path or (settings.knowledge_base_dir / "index.json")
    documents = []
    for video_dir in sorted(path for path in output_root.iterdir() if path.is_dir()):
        analysis_path = video_dir / "analysis.json"
        subtitle_path = video_dir / "subtitle.txt"
        v3_path = video_dir / "v3.json"
        if not analysis_path.exists():
            continue
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
        subtitle = subtitle_path.read_text(encoding="utf-8") if subtitle_path.exists() else ""
        v3_text = _read_v3_text(v3_path)
        base_text = "\n".join(
            [
                f"标题：{analysis.get('title', video_dir.name)}",
                f"一句话总结：{analysis.get('one_sentence_summary', '')}",
                f"值得学习：{'；'.join(analysis.get('learnings', []))}",
                v3_text,
                subtitle,
            ]
        )
        for chunk_index, chunk in enumerate(_chunk_text(base_text, settings.rag_chunk_chars)):
            documents.append(
                {
                    "chunk_id": f"{video_dir.name}:{chunk_index}",
                    "video_id": video_dir.name,
                    "title": analysis.get("title", video_dir.name),
                    "source_path": str(video_dir),
                    "text": chunk,
                }
            )

    payload = {"version": 1, "document_count": len(documents), "documents": documents}
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return index_path


def search_knowledge_base(
    query: str,
    index_path: Path | None = None,
    top_k: int = 5,
    settings: Settings = SETTINGS,
) -> list[dict[str, Any]]:
    backend = settings.rag_search_backend.strip().lower()
    lexical = _search_lexical_knowledge_base(
        query,
        index_path=index_path,
        top_k=max(top_k * 3, top_k),
        settings=settings,
    )
    if backend == "lexical":
        return lexical[:top_k]

    vector = []
    try:
        from rag.vector_store import search_vector_knowledge_base, vector_backend_ready

        if vector_backend_ready(settings):
            vector = search_vector_knowledge_base(query, top_k=max(top_k * 3, top_k), settings=settings)
    except Exception as exc:
        logger.warning("Vector search unavailable, using lexical fallback: %s", exc)

    if backend == "vector":
        return vector[:top_k] if vector else [dict(item, backend="lexical_fallback") for item in lexical[:top_k]]
    if vector:
        return _merge_hybrid_results(lexical, vector, top_k)
    return [dict(item, backend="lexical") for item in lexical[:top_k]]


def _search_lexical_knowledge_base(
    query: str,
    index_path: Path | None = None,
    top_k: int = 5,
    settings: Settings = SETTINGS,
) -> list[dict[str, Any]]:
    index_path = index_path or (settings.knowledge_base_dir / "index.json")
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    documents = payload.get("documents", [])
    if not documents:
        return []

    doc_tokens = [Counter(_tokenize(doc.get("text", ""))) for doc in documents]
    df: Counter[str] = Counter()
    for tokens in doc_tokens:
        df.update(tokens.keys())
    query_tokens = Counter(_tokenize(query))
    total = len(documents)
    scores = []
    for doc, tokens in zip(documents, doc_tokens):
        score = _cosine_tfidf(query_tokens, tokens, df, total)
        if score > 0:
            scores.append((score, doc))
    scores.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "score": round(score, 4),
            "backend": "lexical",
            "video_id": doc.get("video_id"),
            "title": doc.get("title"),
            "chunk_id": doc.get("chunk_id"),
            "excerpt": _excerpt(doc.get("text", ""), query),
            "source_path": doc.get("source_path"),
        }
        for score, doc in scores[:top_k]
    ]


def _merge_hybrid_results(
    lexical: list[dict[str, Any]],
    vector: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    scores: Counter[str] = Counter()
    for source, weight in ((lexical, 1.0), (vector, 1.25)):
        for rank, item in enumerate(source, start=1):
            key = str(item.get("chunk_id") or f"{item.get('video_id')}:{rank}")
            scores[key] += weight / (60 + rank)
            combined.setdefault(key, dict(item))
    ordered = sorted(scores, key=scores.get, reverse=True)[:top_k]
    if not ordered:
        return []
    maximum = max(scores[key] for key in ordered) or 1.0
    results = []
    for key in ordered:
        item = dict(combined[key])
        item["score"] = round(scores[key] / maximum, 4)
        item["backend"] = "hybrid"
        results.append(item)
    return results


def _read_v3_text(v3_path: Path) -> str:
    if not v3_path.exists():
        return ""
    try:
        payload = json.loads(v3_path.read_text(encoding="utf-8"))
        return payload.get("rag_ready_text", "")
    except Exception:
        return ""


def _chunk_text(text: str, chunk_chars: int) -> list[str]:
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    return [text[index : index + chunk_chars] for index in range(0, len(text), chunk_chars)]


def _tokenize(text: str) -> list[str]:
    tokens = []
    for item in TOKEN_RE.findall(text.lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", item):
            tokens.extend(item)
            tokens.extend(item[index : index + 2] for index in range(len(item) - 1))
        else:
            tokens.append(item)
    return [token for token in tokens if token.strip()]


def _cosine_tfidf(
    query: Counter[str],
    doc: Counter[str],
    df: Counter[str],
    total_docs: int,
) -> float:
    q_vec = _tfidf(query, df, total_docs)
    d_vec = _tfidf(doc, df, total_docs)
    numerator = sum(q_vec[token] * d_vec.get(token, 0.0) for token in q_vec)
    q_norm = math.sqrt(sum(value * value for value in q_vec.values()))
    d_norm = math.sqrt(sum(value * value for value in d_vec.values()))
    if not q_norm or not d_norm:
        return 0.0
    return numerator / (q_norm * d_norm)


def _tfidf(tokens: Counter[str], df: Counter[str], total_docs: int) -> dict[str, float]:
    total_terms = sum(tokens.values()) or 1
    return {
        token: (count / total_terms) * (math.log((1 + total_docs) / (1 + df.get(token, 0))) + 1)
        for token, count in tokens.items()
    }


def _excerpt(text: str, query: str, size: int = 180) -> str:
    query_tokens = _tokenize(query)
    position = 0
    for token in query_tokens:
        found = text.find(token)
        if found >= 0:
            position = found
            break
    start = max(0, position - size // 3)
    return text[start : start + size]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build or search the local RAG knowledge base.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--output-root", default=str(SETTINGS.output_dir))
    build_parser.add_argument("--index", default=str(SETTINGS.knowledge_base_dir / "index.json"))
    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")
    search_parser.add_argument("--index", default=str(SETTINGS.knowledge_base_dir / "index.json"))
    search_parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    if args.command == "build":
        print(build_knowledge_base(Path(args.output_root), Path(args.index)))
    else:
        print(json.dumps(search_knowledge_base(args.query, Path(args.index), args.top_k), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
