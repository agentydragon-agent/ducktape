"""Write JSONL (one JSON object per line) — a tiny shared test helper for round-tripping
JSONL artifacts (price observations, PE trajectories) through the readers under test."""

from __future__ import annotations

import json
from pathlib import Path


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> Path:
    """Write `rows` as JSONL to `path` and return it."""
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path
