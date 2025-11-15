from __future__ import annotations

from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
from pathlib import Path

from .models import Detection


@dataclass(frozen=True)
class DetectorSpec:
    name: str
    target_property: str
    finder: Callable[[Path], list[Detection]]


_REGISTRY: list[DetectorSpec] = []


def register(spec: DetectorSpec) -> None:
    _REGISTRY.append(spec)


def all_detectors() -> list[DetectorSpec]:
    return list(_REGISTRY)


def run_all(root: Path, detector_names: Iterable[str] | None = None, *, workers: int | None = None) -> list[Detection]:
    """Run all (or selected) detectors.

    Concurrency is controlled by a single flag:
    - workers is None: choose a default pool size = min(len(selected), cpu_count).
    - workers <= 1: run sequentially.
    - workers > 1: run with a thread pool of given size.
    """
    root = root.resolve()
    wanted = set(detector_names) if detector_names is not None else set()
    selected = [spec for spec in _REGISTRY if (not wanted or spec.name in wanted)]
    if not selected:
        return []

    def _run(spec: DetectorSpec) -> list[Detection]:
        try:
            return spec.finder(root)
        except Exception as e:
            return [
                Detection(
                    property=spec.target_property,
                    path=str(root),
                    ranges=[],
                    detector=spec.name,
                    confidence=0.1,
                    message=f"detector error: {e}",
                )
            ]

    # Determine execution mode based on workers
    auto_workers = min(len(selected), os.cpu_count() or 1) if workers is None else int(workers)

    if auto_workers <= 1:
        out: list[Detection] = []
        for spec in selected:
            out.extend(_run(spec))
        return out

    # Parallel execution: use map to preserve the order of `selected` while executing concurrently.
    # `_run` already catches exceptions and returns a synthetic Detection on failure, so no try/except needed here.
    results: list[Detection] = []
    with ThreadPoolExecutor(max_workers=auto_workers) as ex:
        for detections in ex.map(_run, selected):
            results.extend(detections)
    return results
