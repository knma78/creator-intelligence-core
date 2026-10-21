from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import SETTINGS
from pipeline.openclip_backfill import backfill_openclip_from_outputs


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill cached covers with OpenCLIP without rerunning downloads, "
            "Whisper, scene analysis, or other V3 analyzers."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reanalyze covers that already have a successful OpenCLIP result.",
    )
    parser.add_argument(
        "--no-analytics",
        action="store_true",
        help="Do not refresh DuckDB after updating V3 outputs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process at most this many covers, for short resumable batches.",
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")

    def progress(
        current: int,
        total: int,
        video_id: str,
        status: str,
        elapsed: float,
    ) -> None:
        print(
            f"[{current}/{total}] {video_id}: {status} ({elapsed:.2f}s)",
            flush=True,
        )

    try:
        result = backfill_openclip_from_outputs(
            SETTINGS,
            force=args.force,
            limit=args.limit,
            refresh_analytics=not args.no_analytics,
            progress_callback=progress,
        )
    except KeyboardInterrupt:
        print(
            "OpenCLIP backfill stopped. Completed files were retained and the "
            "same command can resume them.",
            file=sys.stderr,
            flush=True,
        )
        return 130

    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
