from __future__ import annotations

import ast
from pathlib import Path

from .base import BaseDetector
from .models import Detection, LineRange
from .utils import read_snippet


def _simple_test(n: ast.AST) -> bool:
    # Heuristic: allow Name, Attribute, UnaryOp(not Name), simple Compare(Name op Const)
    if isinstance(n, ast.Name | ast.Attribute):
        return True
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not) and isinstance(n.operand, ast.Name | ast.Attribute):
        return True
    return bool(
        isinstance(n, ast.Compare)
        and isinstance(n.left, ast.Name | ast.Attribute)
        and len(n.ops) == 1
        and len(n.comparators) == 1
        and isinstance(n.comparators[0], ast.Constant | ast.Name | ast.Attribute)
    )


class FlattenNestedGuardsDetector(BaseDetector):
    DET_NAME = "flatten_nested_guards"
    PROP = "minimize-nesting"

    def find_detections(self, path: Path, tree: ast.AST, source: str) -> list[Detection]:
        out: list[Detection] = []
        for fn in ast.walk(tree):
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                for st in fn.body:
                    if (
                        isinstance(st, ast.If)
                        and not st.orelse
                        and len(st.body) == 1
                        and isinstance(st.body[0], ast.If)
                    ):
                        inner = st.body[0]
                        if not inner.orelse and _simple_test(st.test) and _simple_test(inner.test):
                            sl = getattr(st, "lineno", 1)
                            il = getattr(inner, "lineno", sl + 1)
                            out.append(
                                Detection(
                                    property=self.PROP,
                                    path=str(path),
                                    ranges=[LineRange(start_line=int(sl), end_line=int(il))],
                                    detector=self.DET_NAME,
                                    confidence=0.8,
                                    message=("Nested trivial guards — consider 'if A and B:' to flatten nesting"),
                                    snippet=read_snippet(path, sl, il, context=0),
                                )
                            )
        return out


_detector = FlattenNestedGuardsDetector()
find = _detector.get_finder()
_detector.register_detector()
