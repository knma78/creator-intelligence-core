from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from infrastructure.atomic_io import atomic_write_json


logger = logging.getLogger(__name__)
COLLECTION_NAME = "content_research"


def build_vector_knowledge_base(
    lexical_index_path: Path | None = None,
    settings: Settings = SETTINGS,
) -> Path:
    lexical_index_path = lexical_index_path or (settings.knowledge_base_dir / "index.json")
    payload = json.loads(lexical_index_path.read_text(encoding="utf-8"))
    documents = list(payload.get("documents") or [])
    if not documents:
        raise ValueError("Lexical knowledge base has no documents")

    chromadb, model = _load_dependencies(settings)
    persist_dir = settings.vector_knowledge_base_dir
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(persist_dir))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(
        COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )

    batch_size = max(1, settings.sentence_transformer_batch_size)
    for start in range(0, len(documents), batch_size):
        batch = documents[start : start + batch_size]
        texts = [str(item.get("text") or "") for item in batch]
        embeddings = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        ).tolist()
        collection.upsert(
            ids=[str(item["chunk_id"]) for item in batch],
            documents=texts,
            embeddings=embeddings,
            metadatas=[
                {
                    "video_id": str(item.get("video_id") or ""),
                    "title": str(item.get("title") or ""),
                    "source_path": str(item.get("source_path") or ""),
                    "learning_subjects": json.dumps(
                        item.get("learning_subjects") or [],
                        ensure_ascii=False,
                    ),
                }
                for item in batch
            ],
        )

    manifest_path = persist_dir / "manifest.json"
    manifest = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "collection": COLLECTION_NAME,
        "document_count": len(documents),
        "embedding_model": settings.sentence_transformer_model,
        "lexical_index_path": str(lexical_index_path.resolve()),
    }
    atomic_write_json(manifest_path, manifest)
    return manifest_path


def search_vector_knowledge_base(
    query: str,
    top_k: int = 5,
    settings: Settings = SETTINGS,
) -> list[dict[str, Any]]:
    manifest_path = settings.vector_knowledge_base_dir / "manifest.json"
    if not manifest_path.exists():
        return []
    chromadb, model = _load_dependencies(settings)
    client = chromadb.PersistentClient(path=str(settings.vector_knowledge_base_dir))
    collection = client.get_collection(COLLECTION_NAME)
    embedding = model.encode([query], normalize_embeddings=True, show_progress_bar=False)[0].tolist()
    result = collection.query(
        query_embeddings=[embedding],
        n_results=max(1, top_k),
        include=["documents", "metadatas", "distances"],
    )
    ids = (result.get("ids") or [[]])[0]
    texts = (result.get("documents") or [[]])[0]
    metadatas = (result.get("metadatas") or [[]])[0]
    distances = (result.get("distances") or [[]])[0]
    rows = []
    for chunk_id, text, metadata, distance in zip(ids, texts, metadatas, distances):
        metadata = metadata or {}
        rows.append(
            {
                "score": round(max(0.0, 1.0 - float(distance)), 4),
                "backend": "vector",
                "video_id": metadata.get("video_id"),
                "title": metadata.get("title"),
                "chunk_id": chunk_id,
                "excerpt": str(text or "")[:240],
                "source_path": metadata.get("source_path"),
                "learning_subjects": _decode_learning_subjects(
                    metadata.get("learning_subjects")
                ),
            }
        )
    return rows


def vector_backend_ready(settings: Settings = SETTINGS) -> bool:
    return (settings.vector_knowledge_base_dir / "manifest.json").exists()


def _decode_learning_subjects(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    try:
        payload = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return [item for item in payload if isinstance(item, dict)]


@lru_cache(maxsize=2)
def _load_dependencies(settings: Settings):
    if settings.sentence_transformer_local_only:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "Vector RAG requires chromadb and sentence-transformers. Install advanced requirements first."
        ) from exc
    model = SentenceTransformer(
        settings.sentence_transformer_model,
        cache_folder=str(settings.model_cache_dir / "sentence_transformers"),
        local_files_only=settings.sentence_transformer_local_only,
    )
    return chromadb, model
