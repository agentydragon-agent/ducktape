from __future__ import annotations

import ast
from pathlib import Path

from .models import Detection, LineRange
from .registry import DetectorSpec, register
from .utils import iter_py_files, read_snippet

DET_NAME = "swallow_errors"
PROP = "python/no-swallowing-errors"


def _is_swallow_body(stmts: list[ast.stmt]) -> bool:
    # Consider empty, pass, or single return None as swallowing; ignore logging heuristics here
    if not stmts:
        return True
    if all(isinstance(s, ast.Pass) for s in stmts):
        return True
    if len(stmts) == 1 and isinstance(stmts[0], ast.Return) and stmts[0].value is None:
        return True
    return False


def _is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    if isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"}:
        return True
    return False


def _find_in_file(path: Path) -> list[Detection]:
    out: list[Detection] = []
    try:
        node = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return out
    for n in ast.walk(node):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                if _is_broad(h) and _is_swallow_body(h.body):
                    sl = getattr(h, "lineno", getattr(n, "lineno", 1))
                    el = getattr(h, "end_lineno", sl)
                    out.append(
                        Detection(
                            property=PROP,
                            path=str(path),
                            ranges=[LineRange(start_line=int(sl), end_line=int(el))],
                            detector=DET_NAME,
                            confidence=0.95,
                            message="Blanket except swallows errors (pass/return None); catch specific errors or let them propagate.",
                            snippet=read_snippet(path, sl, el, context=0),
                        ),
                    )
    return out


def find(root: Path) -> list[Detection]:
    out: list[Detection] = []
    for p in iter_py_files(root):
        out.extend(_find_in_file(p))
    return out


register(DetectorSpec(name=DET_NAME, target_property=PROP, finder=find))
