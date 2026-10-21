from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from PIL import Image
import torch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from analyzer.visual_semantics import analyze_image_semantics, get_openclip_runtime_status
from config import SETTINGS


def main() -> int:
    smoke_path = SETTINGS.cache_dir / "openclip-gpu-smoke.png"
    Image.new("RGB", (224, 224), (32, 96, 160)).save(smoke_path)
    try:
        started = time.perf_counter()
        result = analyze_image_semantics(smoke_path)
        elapsed = time.perf_counter() - started
        runtime = get_openclip_runtime_status()
        payload = {
            "status": result.get("status"),
            "device": result.get("device"),
            "model": result.get("model"),
            "elapsed_seconds": round(elapsed, 3),
            "torch_version": torch.__version__,
            "torch_cuda_build": torch.version.cuda,
            "cuda_available": torch.cuda.is_available(),
            "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
            "gpu_capability": (
                list(torch.cuda.get_device_capability(0))
                if torch.cuda.is_available()
                else None
            ),
            "runtime": runtime,
            "reason": result.get("reason"),
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0 if result.get("status") == "ok" and str(result.get("device", "")).startswith("cuda") else 1
    finally:
        Path(smoke_path).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
