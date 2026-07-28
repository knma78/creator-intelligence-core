from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import SETTINGS, Settings
from models import Video
from processor.ocr import extract_text_from_image


def analyze_cover(video: Video, settings: Settings = SETTINGS) -> dict[str, Any]:
    image_path = download_cover(video, settings)
    if not image_path:
        return {"status": "skipped", "reason": "missing cover url or download dependency", "ocr": None}

    analysis: dict[str, Any] = {
        "status": "ok",
        "image_path": str(image_path),
        "cover_url": video.cover,
    }
    analysis.update(_image_stats(image_path))
    analysis["ocr"] = extract_text_from_image(image_path)
    return analysis


def download_cover(video: Video, settings: Settings = SETTINGS) -> Path | None:
    if not video.cover:
        return None
    cover_dir = settings.covers_cache_dir / video.video_id
    cover_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(str(video.cover).split("?")[0]).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        suffix = ".jpg"
    image_path = cover_dir / f"cover{suffix}"
    if image_path.exists() and not settings.overwrite_cache:
        return image_path

    try:
        import requests
    except ImportError:
        return None

    try:
        response = requests.get(
            video.cover,
            headers={"User-Agent": "Mozilla/5.0 ContentResearch/1.0"},
            timeout=20,
        )
        response.raise_for_status()
        image_path.write_bytes(response.content)
        return image_path
    except Exception:
        return None


def _image_stats(image_path: Path) -> dict[str, Any]:
    try:
        from PIL import Image, ImageStat
    except ImportError:
        return {"image_stats_status": "skipped", "reason": "missing dependency: pillow"}

    try:
        with Image.open(image_path) as image:
            rgb = image.convert("RGB")
            gray = image.convert("L")
            stat = ImageStat.Stat(gray)
            dominant_colors = _dominant_colors(rgb)
            return {
                "width": image.width,
                "height": image.height,
                "aspect_ratio": round(image.width / image.height, 4) if image.height else None,
                "brightness": round(stat.mean[0], 2),
                "contrast": round(stat.stddev[0], 2),
                "dominant_colors": dominant_colors,
            }
    except Exception as exc:
        return {"image_stats_status": "error", "reason": str(exc)}


def _dominant_colors(image) -> list[dict[str, Any]]:
    preview = image.copy()
    preview.thumbnail((128, 128))
    quantized = preview.quantize(colors=5)
    palette = quantized.getpalette() or []
    colors = quantized.getcolors() or []
    colors.sort(reverse=True)
    result = []
    for count, index in colors[:5]:
        offset = index * 3
        rgb = tuple(palette[offset : offset + 3])
        result.append({"hex": "#%02x%02x%02x" % rgb, "count": count})
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze a downloaded cover image fixture.")
    parser.add_argument("image")
    args = parser.parse_args()
    dummy = Video(source_url="", platform="local", video_id="local", title="local", cover=None)
    print(json.dumps({"image_path": args.image, **_image_stats(Path(args.image))}, ensure_ascii=False, indent=2))
