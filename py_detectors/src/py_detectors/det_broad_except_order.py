from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from .base import BaseDetector
from .models import Detection
from .utils import is_broad_exception


class BroadExceptOrderDetector(BaseDetector):
    DET_NAME = "broad_except_order"
    PROP = "python/scoped-try-except"

    def find_detections(self, path: Path, tree: ast.AST, source: str) -> Iterable[Detection]:
        for n in ast.walk(tree):
            if not isinstance(n, ast.Try):
                continue
            handlers = n.handlers or []
            if (first_broad := next((i for i, h in enumerate(handlers) if is_broad_exception(h)), None)) is None:
                continue
            if any(not is_broad_exception(h) for h in handlers[first_broad + 1 :]):
                broad = handlers[first_broad]
                yield self.detection(
                    path,
                    broad.lineno,
                    broad.end_lineno,
                    "Broad except precedes specific handler; later handler is unreachable.",
                    confidence=0.95,
                )


_detector = BroadExceptOrderDetector()
find = _detector.get_finder()
_detector.register_detector()
