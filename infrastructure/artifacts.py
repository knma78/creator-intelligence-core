from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def stable_fingerprint(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def files_fingerprint(paths: Iterable[Path]) -> str:
    inputs = []
    for path in sorted((Path(item) for item in paths), key=lambda item: str(item)):
        if not path.is_file():
            continue
        inputs.append(
            {
                "path": str(path.resolve()),
                "size": path.stat().st_size,
                "sha256": file_sha256(path),
            }
        )
    return stable_fingerprint(inputs)
