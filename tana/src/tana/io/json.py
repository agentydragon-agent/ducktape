from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tana.graph.workspace import TanaGraph


def load_workspace(path: Path) -> TanaGraph:
    """Load a Tana export JSON file into a :class:`TanaGraph`."""

    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)

    documents = data.get("docs", [])
    return TanaGraph.from_documents(documents)


__all__ = ["load_workspace"]
