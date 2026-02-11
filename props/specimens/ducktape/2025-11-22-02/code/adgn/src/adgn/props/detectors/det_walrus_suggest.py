from __future__ import annotations

import ast
from pathlib import Path

from .models import Detection, LineRange
from .registry import DetectorSpec, register
from .utils import make_root_detector, read_snippet

DET_NAME = "walrus_suggest"
PROP = "python/walrus"


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


def _find_in_file(path: Path) -> list[Detection]:
    out: list[Detection] = []
    try:
        text = path.read_text(encoding="utf-8")
        node = ast.parse(text)
    except Exception:
        return out

    for parent in ast.walk(node):
        # Look inside functions only (skip module/class levels)
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef):
            body = parent.body
            for i, stmt in enumerate(body[:-1]):
                if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
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
                                    property=PROP,
                                    path=str(path),
                                    ranges=[LineRange(start_line=int(sl), end_line=int(gl))],
                                    detector=DET_NAME,
                                    confidence=0.8,
                                    message=(
                                        f"Assign then immediate guard on '{name}' — consider walrus in guard (assign L{sl}, guard L{gl}, test={desc})."
                                    ),
                                    snippet=read_snippet(path, sl, gl, context=0),
                                )
                            )
    return out


find = make_root_detector(_find_in_file)


register(DetectorSpec(name=DET_NAME, target_property=PROP, finder=find))
