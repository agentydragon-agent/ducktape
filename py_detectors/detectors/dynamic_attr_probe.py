from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from py_detectors.base import BaseDetector
from py_detectors.models import Detection

CALL_FUNCS = {"getattr", "hasattr", "setattr"}


def _catches_attr_error(handler: ast.ExceptHandler) -> bool:
    t = handler.type
    if isinstance(t, ast.Name) and t.id == "AttributeError":
        return True
    if isinstance(t, ast.Tuple):
        return any(isinstance(elt, ast.Name) and elt.id == "AttributeError" for elt in t.elts)
    return False


class DynamicAttrProbeDetector(BaseDetector):
    DET_NAME = "dynamic_attr_probe"
    PROP = "python/forbid-dynamic-attrs"

    def find_detections(self, path: Path, tree: ast.AST, source: str) -> Iterable[Detection]:
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in CALL_FUNCS:
                yield self.detection(
                    path,
                    n.lineno,
                    n.end_lineno,
                    f"Use of {n.func.id} — prefer explicit types/attributes; avoid dynamic attribute probing.",
                )
            elif isinstance(n, ast.ExceptHandler) and _catches_attr_error(n):
                yield self.detection(
                    path,
                    n.lineno,
                    n.end_lineno,
                    "Catching AttributeError — avoid hiding structural/type errors; design explicit types.",
                    confidence=0.95,
                )


_detector = DynamicAttrProbeDetector()
find = _detector.get_finder()
_detector.register_detector()
