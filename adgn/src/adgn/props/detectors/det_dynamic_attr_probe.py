from __future__ import annotations

import ast
from pathlib import Path

from .base import BaseDetector
from .models import Detection, LineRange
from .utils import read_snippet

CALL_FUNCS = {"getattr", "hasattr", "setattr"}


class DynamicAttrProbeDetector(BaseDetector):
    DET_NAME = "dynamic_attr_probe"
    PROP = "python/forbid-dynamic-attrs"

    def find_detections(self, path: Path, tree: ast.AST, source: str) -> list[Detection]:
        out: list[Detection] = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in CALL_FUNCS:
                sl = getattr(n, "lineno", 1)
                el = getattr(n, "end_lineno", sl)
                out.append(
                    Detection(
                        property=self.PROP,
                        path=str(path),
                        ranges=[LineRange(start_line=int(sl), end_line=int(el))],
                        detector=self.DET_NAME,
                        confidence=0.9,
                        message=f"Use of {n.func.id} — prefer explicit types/attributes; avoid dynamic attribute probing.",
                        snippet=read_snippet(path, sl, el, context=0),
                    )
                )
            if isinstance(n, ast.ExceptHandler):
                t = n.type
                caught_attr_error = False
                if isinstance(t, ast.Name) and t.id == "AttributeError":
                    caught_attr_error = True
                elif isinstance(t, ast.Tuple):
                    for elt in t.elts:
                        if isinstance(elt, ast.Name) and elt.id == "AttributeError":
                            caught_attr_error = True
                            break
                if caught_attr_error:
                    sl = getattr(n, "lineno", 1)
                    el = getattr(n, "end_lineno", sl)
                    out.append(
                        Detection(
                            property=self.PROP,
                            path=str(path),
                            ranges=[LineRange(start_line=int(sl), end_line=int(el))],
                            detector=self.DET_NAME,
                            confidence=0.95,
                            message="Catching AttributeError — avoid hiding structural/type errors; design explicit types.",
                            snippet=read_snippet(path, sl, el, context=0),
                        )
                    )
        return out


_detector = DynamicAttrProbeDetector()
find = _detector.get_finder()
_detector.register_detector()
