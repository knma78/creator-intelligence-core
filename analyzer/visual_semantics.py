from __future__ import annotations

import logging
import gc
import importlib.util
from importlib.metadata import PackageNotFoundError, version
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from config import SETTINGS, Settings
from infrastructure.cancellation import (
    JobCancelledError,
    raise_if_cancelled,
)
from infrastructure.resources import ResourceKind, get_resource_manager

logger = logging.getLogger(__name__)

LABEL_TRANSLATIONS = {
    "talking head": "人物口播",
    "anime illustration": "动漫插画",
    "movie scene": "影视画面",
    "gameplay": "游戏画面",
    "tutorial screen": "教程录屏",
    "product close-up": "产品特写",
    "text-heavy poster": "大字海报",
    "emotional face": "强情绪人脸",
    "action scene": "动作场面",
    "landscape": "风景画面",
    "infographic": "信息图",
    "meme": "表情包或梗图",
}


def get_openclip_runtime_status(
    settings: Settings = SETTINGS,
) -> dict[str, Any]:
    cache_dir = settings.model_cache_dir / "openclip"
    weights_cached = _weights_cached(cache_dir)
    if not weights_cached and not settings.openclip_allow_download:
        torch_available = importlib.util.find_spec("torch") is not None
        try:
            torch_version = version("torch") if torch_available else None
        except PackageNotFoundError:
            torch_version = None
        return {
            "enabled": settings.openclip_enabled,
            "available": torch_available,
            "configured_device": settings.openclip_device,
            "device": "deferred",
            "cuda_available": None,
            "weights_cached": False,
            "allow_download": False,
            "torch_version": torch_version,
            "model": settings.openclip_model,
            "reason": (
                "OpenCLIP weights are not cached; runtime probing and network "
                "download are skipped."
            ),
        }
    try:
        import torch
    except ImportError:
        return {
            "enabled": settings.openclip_enabled,
            "available": False,
            "configured_device": settings.openclip_device,
            "device": "unavailable",
            "cuda_available": False,
            "weights_cached": weights_cached,
            "reason": "PyTorch is not installed.",
        }
    device = _resolve_device(settings.openclip_device, torch)
    cuda_available = bool(torch.cuda.is_available())
    return {
        "enabled": settings.openclip_enabled,
        "available": True,
        "configured_device": settings.openclip_device,
        "device": device,
        "cuda_available": cuda_available,
        "weights_cached": weights_cached,
        "allow_download": settings.openclip_allow_download,
        "torch_version": str(torch.__version__),
        "model": settings.openclip_model,
        "reason": (
            "OpenCLIP weights are not cached; analysis will fail fast without a network download."
            if not weights_cached and not settings.openclip_allow_download
            else (
                "CUDA PyTorch is available; OpenCLIP prefers GPU."
                if str(device).startswith("cuda")
                else "OpenCLIP is using CPU because CUDA is unavailable to PyTorch."
            )
        ),
    }


def analyze_image_semantics(
    image_path: Path,
    settings: Settings = SETTINGS,
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    raise_if_cancelled(cancel_requested)
    if not settings.openclip_enabled:
        return {"status": "skipped", "reason": "OpenCLIP disabled"}
    if not image_path.exists():
        return {"status": "skipped", "reason": "image file unavailable"}
    cache_dir = settings.model_cache_dir / "openclip"
    if (
        not settings.openclip_allow_download
        and not _weights_cached(cache_dir)
    ):
        return {
            "status": "skipped",
            "reason": "OpenCLIP weights are not cached; network download disabled.",
        }

    try:
        from PIL import Image
        import torch
    except ImportError as exc:
        return {"status": "unavailable", "reason": f"missing dependency: {exc.name}"}

    try:
        device = _resolve_device(settings.openclip_device, torch)
        resource_kind = (
            ResourceKind.GPU_INFERENCE
            if str(device).startswith("cuda")
            else ResourceKind.CPU_HEAVY
        )
        manager = get_resource_manager(settings)
        manager.register_gpu_family("openclip", release_openclip_models)
        with manager.lease(
            resource_kind,
            owner=f"openclip:{image_path.name}",
            family="openclip" if resource_kind is ResourceKind.GPU_INFERENCE else None,
            cancel_requested=cancel_requested,
        ):
            model, preprocess, tokenizer = _load_model_bundle(
                settings.openclip_model,
                settings.openclip_pretrained,
                device,
                str(cache_dir),
            )
            raise_if_cancelled(cancel_requested)
            labels = list(settings.openclip_labels)
            with Image.open(image_path) as image:
                image_tensor = preprocess(image.convert("RGB")).unsqueeze(0).to(device)
            text_tokens = tokenizer(labels).to(device)

            with torch.inference_mode():
                image_features = model.encode_image(image_tensor)
                raise_if_cancelled(cancel_requested)
                text_features = model.encode_text(text_tokens)
                image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)
                scores = (image_features @ text_features.T).squeeze(0)

        ranked = sorted(
            zip(labels, scores.detach().cpu().tolist()),
            key=lambda item: item[1],
            reverse=True,
        )
        result: dict[str, Any] = {
            "status": "ok",
            "engine": "OpenCLIP",
            "model": settings.openclip_model,
            "pretrained": settings.openclip_pretrained,
            "device": device,
            "top_labels": [
                {
                    "label": label,
                    "label_zh": LABEL_TRANSLATIONS.get(label, label),
                    "score": round(float(score), 6),
                }
                for label, score in ranked[: max(1, settings.openclip_top_k)]
            ],
            "embedding_dimension": int(image_features.shape[-1]),
        }
        if settings.openclip_store_embedding:
            result["embedding"] = [
                round(float(value), 6)
                for value in image_features.squeeze(0).detach().cpu().tolist()
            ]
        return result
    except JobCancelledError:
        raise
    except Exception as exc:  # pragma: no cover - backend/model dependent
        logger.warning("OpenCLIP analysis failed for %s: %s", image_path, exc)
        return {"status": "failed", "reason": str(exc)}


def _resolve_device(configured: str, torch_module: Any) -> str:
    value = configured.strip().lower()
    if value != "auto":
        return configured
    return "cuda" if torch_module.cuda.is_available() else "cpu"


def _weights_cached(cache_dir: Path) -> bool:
    return _find_local_weights(cache_dir) is not None


def _find_local_weights(cache_dir: Path) -> Path | None:
    if not cache_dir.exists():
        return None
    preferred = cache_dir / "open_clip_model.safetensors"
    if preferred.is_file() and preferred.stat().st_size > 1_000_000:
        return preferred
    extensions = {".bin", ".pt", ".pth", ".safetensors"}
    return next(
        (
            path
            for path in cache_dir.rglob("*")
            if path.is_file()
            and path.suffix.lower() in extensions
            and path.stat().st_size > 1_000_000
        ),
        None,
    )


def release_openclip_models() -> None:
    _load_model_bundle.cache_clear()
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


@lru_cache(maxsize=4)
def _load_model_bundle(
    model_name: str,
    pretrained: str,
    device: str,
    cache_dir: str,
) -> tuple[Any, Any, Any]:
    try:
        import open_clip
    except ImportError as exc:
        raise RuntimeError("missing dependency: open-clip-torch") from exc

    local_weights = _find_local_weights(Path(cache_dir))
    pretrained_source = str(local_weights) if local_weights else pretrained
    model, _, preprocess = open_clip.create_model_and_transforms(
        model_name,
        pretrained=pretrained_source,
        device=device,
        cache_dir=cache_dir,
    )
    model.eval()
    tokenizer = open_clip.get_tokenizer(model_name)
    return model, preprocess, tokenizer
