from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from .base import BaseDetector
from .models import Detection
from .utils import is_broad_exception


def _is_swallow_body(stmts: list[ast.stmt]) -> bool:
    """Consider empty, pass, or single return None as swallowing."""
    if not stmts:
        return True
    if all(isinstance(s, ast.Pass) for s in stmts):
        return True
    return len(stmts) == 1 and isinstance(stmts[0], ast.Return) and stmts[0].value is None


class SwallowErrorsDetector(BaseDetector):
    DET_NAME = "swallow_errors"
    PROP = "python/no-swallowing-errors"

    def find_detections(self, path: Path, tree: ast.AST, source: str) -> Iterable[Detection]:
        for n in ast.walk(tree):
            if not isinstance(n, ast.Try):
                continue
            for h in n.handlers:
                if is_broad_exception(h) and _is_swallow_body(h.body):
                    yield self.detection(
                        path,
                        h.lineno,
                        h.end_lineno,
                        "Blanket except swallows errors (pass/return None); catch specific errors or let them propagate.",
                        confidence=0.95,
                    )


_detector = SwallowErrorsDetector()
find = _detector.get_finder()
_detector.register_detector()
