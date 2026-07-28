from __future__ import annotations

import logging
from collections import Counter
from functools import lru_cache
from typing import Any

from config import SETTINGS, Settings


logger = logging.getLogger(__name__)


def analyze_text_nlp(text: str, settings: Settings = SETTINGS) -> dict[str, Any]:
    clipped = str(text or "")[: settings.nlp_max_chars]
    if not clipped.strip():
        return {"status": "skipped", "reason": "empty text", "entities": [], "sentences": []}

    try:
        nlp, loaded_model, fallback = _load_pipeline(
            settings.spacy_model,
            settings.nlp_max_chars,
        )
    except ImportError:
        return {
            "status": "unavailable",
            "reason": "spaCy is not installed",
            "model": settings.spacy_model,
            "entities": [],
            "sentences": [],
        }

    try:
        doc = nlp(clipped)
    except ValueError as exc:
        logger.warning("spaCy analysis failed: %s", exc)
        return {
            "status": "failed",
            "reason": str(exc),
            "model": loaded_model,
            "entities": [],
            "sentences": [],
        }

    sentences = [sent.text.strip() for sent in doc.sents if sent.text.strip()]
    entity_counter: Counter[tuple[str, str]] = Counter(
        (ent.text.strip(), ent.label_) for ent in doc.ents if ent.text.strip()
    )
    entities = [
        {"text": entity, "label": label, "count": count}
        for (entity, label), count in entity_counter.most_common(30)
    ]
    token_count = sum(1 for token in doc if not token.is_space)
    return {
        "status": "ok",
        "engine": "spacy",
        "model": loaded_model,
        "fallback_pipeline": fallback,
        "text_chars": len(clipped),
        "token_count": token_count,
        "sentence_count": len(sentences),
        "average_sentence_chars": round(
            sum(len(sentence) for sentence in sentences) / max(1, len(sentences)), 2
        ),
        "entities": entities,
        "sentences": sentences[:12],
    }


@lru_cache(maxsize=4)
def _load_pipeline(model_name: str, max_chars: int):
    import spacy

    try:
        nlp = spacy.load(model_name)
        loaded_model = model_name
        fallback = False
    except OSError:
        language = "zh" if model_name.lower().startswith("zh") else "xx"
        nlp = spacy.blank(language)
        loaded_model = f"blank:{language}"
        fallback = True
        logger.warning("spaCy model %s is unavailable; using %s", model_name, loaded_model)
    if not any(name in nlp.pipe_names for name in ("parser", "senter", "sentencizer")):
        config = {}
        if fallback and loaded_model == "blank:zh":
            config["punct_chars"] = ["。", "！", "？", "!", "?", "；", ";", "…"]
        nlp.add_pipe("sentencizer", config=config)
    nlp.max_length = max(nlp.max_length, max_chars + 1000)
    return nlp, loaded_model, fallback
