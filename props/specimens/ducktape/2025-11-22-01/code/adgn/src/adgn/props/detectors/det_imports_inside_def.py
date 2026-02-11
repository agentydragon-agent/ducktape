from __future__ import annotations

import ast
from pathlib import Path

from .import_graph import _resolve_from_module, build_import_graph, module_name_for_path, would_introduce_cycle
from .models import Detection, LineRange
from .registry import DetectorSpec, register
from .utils import iter_py_files, read_snippet

DET_NAME = "imports_inside_def"
PROP = "python/imports-top"


def _find_in_file(path: Path, *, graph: dict[str, set[str]], root: Path) -> list[Detection]:
    out: list[Detection] = []
    try:
        node = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return out

    class V(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[ast.AST] = []

        def generic_visit(self, n: ast.AST) -> None:
            self.stack.append(n)
            try:
                super().generic_visit(n)
            finally:
                self.stack.pop()

        def visit_Import(self, n: ast.Import) -> None:
            self._maybe_report(n)
            self.generic_visit(n)

        def visit_ImportFrom(self, n: ast.ImportFrom) -> None:
            self._maybe_report(n)
            self.generic_visit(n)

        def _maybe_report(self, n: ast.AST) -> None:
            # Any import whose parent is not Module is a violation (inside def/class)
            if not self.stack:
                return
            parent = self.stack[-1]
            if not isinstance(parent, ast.Module):
                sl = getattr(n, "lineno", 1)
                el = getattr(n, "end_lineno", sl)
                # Cycle-aware exemption: if moving this import to module top would introduce
                # a cycle in the top-level import graph, do not flag.
                cur_mod = module_name_for_path(root, path)
                target_mod: str | None = None
                if isinstance(n, ast.Import):
                    # pick first name; multi-name imports are rare in local contexts
                    if n.names:
                        target_mod = n.names[0].name
                elif isinstance(n, ast.ImportFrom):
                    base_mod = _resolve_from_module(cur_mod, n.module, int(getattr(n, "level", 0) or 0))
                    if base_mod:
                        if n.names:
                            name0 = n.names[0].name  # may include dotted submodule
                            target_mod = f"{base_mod}.{name0}" if name0 else base_mod
                        else:
                            target_mod = base_mod
                if target_mod and cur_mod and not would_introduce_cycle(graph, cur_mod, target_mod):
                    # Evidence folded into message for agent judgment
                    ev = f"cur={cur_mod}, target={target_mod}, would_cycle=False"
                    out.append(
                        Detection(
                            property=PROP,
                            path=str(path),
                            ranges=[LineRange(start_line=int(sl), end_line=int(el))],
                            detector=DET_NAME,
                            confidence=0.95,
                            message=(
                                "Import inside function/class without cycle justification; move to module top or document a valid exception. "
                                + f"[{ev}]"
                            ),
                            snippet=read_snippet(path, sl, el, context=0),
                        )
                    )
                elif not target_mod:
                    # If we failed to resolve, conservatively report
                    ev = f"cur={cur_mod}, target=?"
                    out.append(
                        Detection(
                            property=PROP,
                            path=str(path),
                            ranges=[LineRange(start_line=int(sl), end_line=int(el))],
                            detector=DET_NAME,
                            confidence=0.8,
                            message=(
                                "Import inside function/class; target unresolved — please verify cycle/hotload justification. "
                                + f"[{ev}]"
                            ),
                            snippet=read_snippet(path, sl, el, context=0),
                        )
                    )

    V().visit(node)
    return out


def find(root: Path) -> list[Detection]:
    out: list[Detection] = []
    graph = build_import_graph(root)
    for p in iter_py_files(root):
        out.extend(_find_in_file(p, graph=graph, root=root))
    return out


register(DetectorSpec(name=DET_NAME, target_property=PROP, finder=find))
