from __future__ import annotations

import argparse
import json

from config import SETTINGS
from infrastructure.analytics_store import backfill_analytics_from_outputs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill existing research outputs into DuckDB.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reimport outputs even when their fingerprint is unchanged.",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            backfill_analytics_from_outputs(
                SETTINGS,
                force=args.force,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
