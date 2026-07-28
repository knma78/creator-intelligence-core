from __future__ import annotations

from pathlib import Path
from typing import Any


def extract_text_from_image(image_path: Path) -> dict[str, Any]:
    rapid = _ocr_with_rapidocr(image_path)
    if rapid["status"] == "ok":
        return rapid
    tesseract = _ocr_with_tesseract(image_path)
    if tesseract["status"] == "ok":
        return tesseract
    return {
        "status": "unavailable",
        "engine": None,
        "text": "",
        "items": [],
        "errors": [rapid.get("reason"), tesseract.get("reason")],
    }


def _ocr_with_rapidocr(image_path: Path) -> dict[str, Any]:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return {"status": "skipped", "engine": "rapidocr", "reason": "rapidocr_onnxruntime is not installed"}

    try:
        ocr = RapidOCR()
        result, _elapsed = ocr(str(image_path))
        items = []
        for item in result or []:
            text = ""
            score = None
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                text = str(item[1])
                score = item[2] if len(item) >= 3 else None
            elif isinstance(item, dict):
                text = str(item.get("text", ""))
                score = item.get("score")
            if text.strip():
                items.append({"text": text.strip(), "score": score})
        return {
            "status": "ok",
            "engine": "rapidocr",
            "text": "\n".join(item["text"] for item in items),
            "items": items,
        }
    except Exception as exc:
        return {"status": "error", "engine": "rapidocr", "reason": str(exc)}


def _ocr_with_tesseract(image_path: Path) -> dict[str, Any]:
    try:
        import pytesseract
    except ImportError:
        return {"status": "skipped", "engine": "tesseract", "reason": "pytesseract is not installed"}

    try:
        text = pytesseract.image_to_string(str(image_path), lang="chi_sim+eng")
        return {
            "status": "ok",
            "engine": "tesseract",
            "text": text.strip(),
            "items": [{"text": line.strip(), "score": None} for line in text.splitlines() if line.strip()],
        }
    except Exception as exc:
        return {"status": "error", "engine": "tesseract", "reason": str(exc)}
