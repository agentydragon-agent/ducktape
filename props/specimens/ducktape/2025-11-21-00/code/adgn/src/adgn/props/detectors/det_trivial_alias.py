from __future__ import annotations

import ast
from pathlib import Path

from .models import Detection, LineRange
from .registry import DetectorSpec, register
from .utils import make_root_detector, read_snippet

DET_NAME = "trivial_alias"
PROP = "no-oneoff-vars-and-trivial-wrappers"


class _UseCounter(ast.NodeVisitor):
    def __init__(self, target: str) -> None:
        self.target = target
        self.loads = 0
        self.stores = 0

    def visit_Name(self, node: ast.Name):
        if node.id == self.target:
            if isinstance(node.ctx, ast.Load):
                self.loads += 1
            elif isinstance(node.ctx, ast.Store):
                self.stores += 1
        self.generic_visit(node)


def _count_uses_in_body(body: list[ast.stmt], start_index: int, name: str) -> tuple[int, int]:
    sub = body[start_index + 1 :]
    mod = ast.Module(body=sub, type_ignores=[])
    c = _UseCounter(name)
    c.visit(mod)
    return c.loads, c.stores


def _find_in_file(path: Path) -> list[Detection]:
    out: list[Detection] = []
    try:
        text = path.read_text(encoding="utf-8")
        node = ast.parse(text)
    except Exception:
        return out

    for fn in ast.walk(node):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            body = fn.body
            for i, st in enumerate(body):
                if (
                    isinstance(st, ast.Assign)
                    and len(st.targets) == 1
                    and isinstance(st.targets[0], ast.Name)
                    and isinstance(st.value, ast.Name)
                ):
                    lhs = st.targets[0].id
                    rhs = st.value.id
                    # Count uses of lhs and future stores to rhs after this assignment
                    lhs_loads, _ = _count_uses_in_body(body, i, lhs)
                    _, rhs_stores = _count_uses_in_body(body, i, rhs)
                    if lhs_loads == 1 and rhs_stores == 0:
                        sl = getattr(st, "lineno", 1)
                        out.append(
                            Detection(
                                property=PROP,
                                path=str(path),
                                ranges=[LineRange(start_line=int(sl), end_line=int(sl))],
                                detector=DET_NAME,
                                confidence=0.85,
                                message=(
                                    f"Trivial alias '{lhs} = {rhs}' used once; consider inlining '{rhs}' at use site."
                                ),
                                snippet=read_snippet(path, sl, sl, context=0),
                            )
                        )
    return out


find = make_root_detector(_find_in_file)


register(DetectorSpec(name=DET_NAME, target_property=PROP, finder=find))
