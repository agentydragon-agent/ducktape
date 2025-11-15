from __future__ import annotations

import ast
from pathlib import Path

from .models import Detection, LineRange
from .registry import DetectorSpec, register
from .utils import is_broad_exception, make_root_detector, read_snippet

DET_NAME = "swallow_errors"
PROP = "python/no-swallowing-errors"


def _is_swallow_body(stmts: list[ast.stmt]) -> bool:
    # Consider empty, pass, or single return None as swallowing; ignore logging heuristics here
    if not stmts:
        return True
    if all(isinstance(s, ast.Pass) for s in stmts):
        return True
    return bool(len(stmts) == 1 and isinstance(stmts[0], ast.Return) and stmts[0].value is None)


def _find_in_file(path: Path) -> list[Detection]:
    out: list[Detection] = []
    try:
        node = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return out
    for n in ast.walk(node):
        if isinstance(n, ast.Try):
            for h in n.handlers:
                if is_broad_exception(h) and _is_swallow_body(h.body):
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
                        )
                    )
    return out


find = make_root_detector(_find_in_file)


register(DetectorSpec(name=DET_NAME, target_property=PROP, finder=find))
