from __future__ import annotations

import ast
from pathlib import Path

from .base import BaseDetector
from .models import Detection, LineRange
from .utils import read_snippet


def _is_simple_guard(test: ast.AST, name: str) -> str | None:
    # Returns a short description when test uses only the given name in simple ways
    if isinstance(test, ast.Name) and test.id == name:
        return "truthiness"
    if (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Name)
        and test.operand.id == name
    ):
        return "not name"
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and len(test.comparators) == 1:
        left, op, right = test.left, test.ops[0], test.comparators[0]
        if isinstance(left, ast.Name) and left.id == name:
            if isinstance(op, ast.Is | ast.IsNot) and isinstance(right, ast.Constant) and right.value is None:
                return "is None" if isinstance(op, ast.Is) else "is not None"
            if isinstance(op, ast.Eq | ast.NotEq) and isinstance(right, ast.Constant | ast.Str | ast.Num):
                return "== literal" if isinstance(op, ast.Eq) else "!= literal"
    return None


class WalrusSuggestDetector(BaseDetector):
    DET_NAME = "walrus_suggest"
    PROP = "python/walrus"

    def find_detections(self, path: Path, tree: ast.AST, source: str) -> list[Detection]:
        out: list[Detection] = []
        for parent in ast.walk(tree):
            # Look inside functions only (skip module/class levels)
            if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
                body = parent.body
                for i, stmt in enumerate(body[:-1]):
                    if (
                        isinstance(stmt, ast.Assign)
                        and len(stmt.targets) == 1
                        and isinstance(stmt.targets[0], ast.Name)
                    ):
                        name = stmt.targets[0].id
                        # Next non-empty/non-docstring statement
                        j = i + 1
                        next_stmt = body[j]
                        # Skip standalone string doc/comment statements
                        if isinstance(next_stmt, ast.Expr) and isinstance(next_stmt.value, ast.Str):
                            if j + 1 < len(body):
                                next_stmt = body[j + 1]
                            else:
                                continue
                        if isinstance(next_stmt, ast.If | ast.While):
                            desc = _is_simple_guard(next_stmt.test, name)
                            if desc:
                                sl = getattr(stmt, "lineno", 1)
                                gl = getattr(next_stmt, "lineno", sl + 1)
                                out.append(
                                    Detection(
                                        property=self.PROP,
                                        path=str(path),
                                        ranges=[LineRange(start_line=int(sl), end_line=int(gl))],
                                        detector=self.DET_NAME,
                                        confidence=0.8,
                                        message=(
                                            f"Assign then immediate guard on '{name}' — consider walrus in guard (assign L{sl}, guard L{gl}, test={desc})."
                                        ),
                                        snippet=read_snippet(path, sl, gl, context=0),
                                    )
                                )
        return out


_detector = WalrusSuggestDetector()
find = _detector.get_finder()
_detector.register_detector()
