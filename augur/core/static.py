from __future__ import annotations

from pathlib import Path


def static_path_for_dist(dist_dir: Path, full_path: str) -> Path:
    rel = "index.html" if full_path in ("", "/") else full_path.lstrip("/")
    relative = Path(rel)
    if relative.is_absolute() or ".." in relative.parts:
        return dist_dir / "__forbidden__"
    candidate = dist_dir / relative
    if candidate.exists():
        return candidate
    if candidate.suffix:
        return candidate
    return dist_dir / "index.html"
