"""Local data protection commands; restore always targets a new isolated folder."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import SETTINGS
from infrastructure.data_cleanup import cleanup_plan, quarantine_indexes, restore_quarantine
from infrastructure.data_inventory import inventory
from infrastructure.data_snapshots import create_snapshot, list_snapshots, restore_drill, selected_snapshot, verify_snapshot
from infrastructure.file_lock import maintenance_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["inventory", "backup", "list", "verify", "restore-drill", "cleanup-plan", "quarantine", "undo-quarantine"])
    parser.add_argument("--snapshot", default="")
    parser.add_argument("--plan-token", default="")
    parser.add_argument("--quarantine-id", default="")
    parser.add_argument("--include-media", action="store_true")
    parser.add_argument("--include-models", action="store_true")
    args = parser.parse_args()
    def progress(current, total, key):
        print(f"[{current}/{total}] {key}", file=sys.stderr, flush=True)
    with maintenance_lock(SETTINGS, exclusive=True):
        if args.action == "inventory":
            result = inventory(SETTINGS)
        elif args.action == "list":
            result = list_snapshots(SETTINGS)
        elif args.action == "backup":
            result = create_snapshot(SETTINGS, include_media=args.include_media, include_models=args.include_models, progress=progress)
        elif args.action == "verify":
            result = verify_snapshot(selected_snapshot(SETTINGS, args.snapshot))
        elif args.action == "restore-drill":
            result = restore_drill(SETTINGS, args.snapshot, progress=progress)
        elif args.action == "cleanup-plan":
            result = cleanup_plan(SETTINGS, args.snapshot)
        elif args.action == "quarantine":
            result = quarantine_indexes(SETTINGS, args.snapshot, args.plan_token)
        else:
            result = restore_quarantine(SETTINGS, args.quarantine_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
