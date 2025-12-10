from __future__ import annotations

import ast
from pathlib import Path

from .base import BaseDetector
from .models import Detection, LineRange
from .utils import read_snippet


def _collect_indices(body: list[ast.stmt], name: str) -> set[int]:
    idx: set[int] = set()
    for n in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == name:
            sl = n.slice
            if isinstance(sl, ast.Constant) and isinstance(sl.value, int):
                idx.add(int(sl.value))
            elif isinstance(sl, ast.Index):  # py<3.9 compatibility, harmless here
                inner = getattr(sl, "value", None)
                if isinstance(inner, ast.Constant) and isinstance(inner.value, int):
                    idx.add(int(inner.value))
    return idx


class MagicTupleIndicesDetector(BaseDetector):
    DET_NAME = "magic_tuple_indices"
    PROP = "avoid-magic-tuple-indices"

    def find_detections(self, path: Path, tree: ast.AST, source: str) -> list[Detection]:
        out: list[Detection] = []
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                body = fn.body if fn.body is not None else []
                for st in body:
                    if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
                        nm = st.targets[0].id
                        if isinstance(st.value, ast.Call):
                            # Gather indices used for this binding within function body
                            indices = _collect_indices(body, nm)
                            if indices and (max(indices) >= 3 or len(indices) >= 3):
                                sl = getattr(st, "lineno", 1)
                                out.append(
                                    Detection(
                                        property=self.PROP,
                                        path=str(path),
                                        ranges=[LineRange(start_line=int(sl), end_line=int(sl))],
                                        detector=self.DET_NAME,
                                        confidence=0.8,
                                        message=(
                                            f"Multiple magic tuple indices on '{nm}': {sorted(indices)} — prefer a named model or fewer positional fields."
                                        ),
                                        snippet=read_snippet(path, sl, sl, context=0),
                                    )
                                )
        return out


_detector = MagicTupleIndicesDetector()
find = _detector.get_finder()
_detector.register_detector()
