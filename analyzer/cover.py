from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from config import SETTINGS, Settings
from infrastructure.cancellation import (
    JobCancelledError,
    raise_if_cancelled,
)
from models import Video
from processor.ocr import extract_text_from_image
from .visual_semantics import analyze_image_semantics


def analyze_cover(
    video: Video,
    settings: Settings = SETTINGS,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    raise_if_cancelled(cancel_requested)
    image_path = download_cover(
        video,
        settings,
        cancel_requested=cancel_requested,
    )
    if not image_path:
        return {"status": "skipped", "reason": "missing cover url or download dependency", "ocr": None}

    analysis: dict[str, Any] = {
        "status": "ok",
        "image_path": str(image_path),
        "cover_url": video.cover,
    }
    analysis.update(_image_stats(image_path))
    raise_if_cancelled(cancel_requested)
    analysis["ocr"] = extract_text_from_image(image_path)
    raise_if_cancelled(cancel_requested)
    analysis["visual_semantics"] = analyze_image_semantics(
        image_path,
        settings,
        cancel_requested=cancel_requested,
    )
    return analysis


def download_cover(
    video: Video,
    settings: Settings = SETTINGS,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> Path | None:
    raise_if_cancelled(cancel_requested)
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

    partial_path = image_path.with_suffix(image_path.suffix + ".part")
    partial_path.unlink(missing_ok=True)
    response = None
    try:
        response = requests.get(
            video.cover,
            headers={"User-Agent": "Mozilla/5.0 ContentResearch/1.0"},
            timeout=20,
            stream=True,
        )
        response.raise_for_status()
        with partial_path.open("wb") as target:
            for chunk in response.iter_content(chunk_size=256 * 1024):
                raise_if_cancelled(cancel_requested)
                if chunk:
                    target.write(chunk)
        raise_if_cancelled(cancel_requested)
        partial_path.replace(image_path)
        return image_path
    except JobCancelledError:
        partial_path.unlink(missing_ok=True)
        raise
    except Exception:
        partial_path.unlink(missing_ok=True)
        return None
    finally:
        if response is not None:
            response.close()


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
