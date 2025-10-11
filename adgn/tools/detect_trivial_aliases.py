#!/usr/bin/env python3
"""Detect trivial fixture aliases in tests (report-only).

Flags assignments inside test functions of the form:
    alias = fixture_param
where:
  - fixture_param is a function parameter (likely a pytest fixture)
  - alias is not reassigned/annotated/augassigned later in the function
  - RHS is a Name (not a Call), so factory usage like wtcli(env) is ignored

Outputs lines in the form:
  path:line:col TRIVIAL_ALIAS alias -> param message

Exit code: 1 if any issues found, else 0.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set


@dataclass
class AliasAssign:
    alias: str
    param: str
    line: int
    col: int


@dataclass
class FuncAnalysis:
    params: Set[str] = field(default_factory=set)
    alias_assigns: Dict[str, AliasAssign] = field(default_factory=dict)  # alias -> record
    # All store sites for names in the function (name -> min line of a later store)
    later_stores: Dict[str, int] = field(default_factory=dict)


class FuncScanner(ast.NodeVisitor):
    def __init__(self) -> None:
        self.stack: List[FuncAnalysis] = []

    def current(self) -> FuncAnalysis | None:
        return self.stack[-1] if self.stack else None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(self, node: ast.AST) -> None:
        # Collect parameter names
        params: Set[str] = set()
        fn = node  # type: ignore
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = fn.args
            for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
                params.add(a.arg)
            if args.vararg is not None:
                params.add(args.vararg.arg)
            if args.kwarg is not None:
                params.add(args.kwarg.arg)

        fa = FuncAnalysis(params=params)
        self.stack.append(fa)

        # Walk the body to find alias assignments
        self.generic_visit(node)

        # Pop when done
        self.stack.pop()

    def visit_Assign(self, node: ast.Assign) -> None:
        cur = self.current()
        if cur is None:
            return
        # Record stores for reassign detection
        for tgt in node.targets:
            self._record_store_targets(tgt, node)

        # Only consider simple form: one target, Name = Name
        if len(node.targets) != 1:
            return
        t = node.targets[0]
        v = node.value
        if isinstance(t, ast.Name) and isinstance(v, ast.Name):
            alias = t.id
            param = v.id
            # RHS must be a parameter name; avoid aliasing self or non-params
            if param in cur.params and alias != param:
                cur.alias_assigns.setdefault(
                    alias,
                    AliasAssign(alias=alias, param=param, line=node.lineno, col=node.col_offset),
                )

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        cur = self.current()
        if cur is None:
            return
        self._record_store_targets(node.target, node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        cur = self.current()
        if cur is None:
            return
        self._record_store_targets(node.target, node)

    def visit_For(self, node: ast.For) -> None:
        # Loop target stores
        self._record_store_targets(node.target, node)
        self.generic_visit(node)

    def _record_store_targets(self, target: ast.AST, node: ast.AST) -> None:
        cur = self.current()
        if cur is None:
            return

        # Record Name stores for later reassign detection
        # We only care about reassignments AFTER an alias line, so keep min line per name
        def _collect_names(t: ast.AST, acc: List[ast.Name]) -> None:
            if isinstance(t, ast.Name):
                acc.append(t)
                return
            for child in ast.iter_child_nodes(t):
                _collect_names(child, acc)

        names: List[ast.Name] = []
        _collect_names(target, names)
        for n in names:
            line = getattr(node, "lineno", None)
            if not isinstance(line, int):
                continue
            prev = cur.later_stores.get(n.id)
            if prev is None or line < prev:
                cur.later_stores[n.id] = line


def detect_file(path: Path) -> List[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return []

    findings: List[str] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._analyze_function(node)

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._analyze_function(node)

        def _analyze_function(self, node: ast.AST) -> None:
            scanner = FuncScanner()
            scanner.visit(node)
            if not scanner.stack:  # after visit, stack popped
                # results are inside the temporary FuncScanner - replicate with second pass
                # Workaround: directly analyze node body using helper
                pass

            # We need results produced in the visit — reconstruct by running again and capturing top of stack
            # Simpler: re-run and return last FuncAnalysis from internal method
            # Instead, re-implement quick analysis inline:
            fa = FuncAnalysis()
            # Re-collect params
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args  # type: ignore[attr-defined]
                for a in list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs):
                    fa.params.add(a.arg)
                if args.vararg is not None:
                    fa.params.add(args.vararg.arg)
                if args.kwarg is not None:
                    fa.params.add(args.kwarg.arg)

                # Single pass to collect alias assigns and stores
                class BodyScan(ast.NodeVisitor):
                    def visit_Assign(self, n: ast.Assign) -> None:
                        for tgt in n.targets:
                            self._record_store_targets(tgt, n)
                        if (
                            len(n.targets) == 1
                            and isinstance(n.targets[0], ast.Name)
                            and isinstance(n.value, ast.Name)
                        ):
                            alias = n.targets[0].id
                            param = n.value.id
                            if param in fa.params and alias != param:
                                fa.alias_assigns.setdefault(
                                    alias,
                                    AliasAssign(
                                        alias=alias, param=param, line=n.lineno, col=n.col_offset
                                    ),
                                )

                    def visit_AnnAssign(self, n: ast.AnnAssign) -> None:
                        self._record_store_targets(n.target, n)

                    def visit_AugAssign(self, n: ast.AugAssign) -> None:
                        self._record_store_targets(n.target, n)

                    def visit_For(self, n: ast.For) -> None:
                        self._record_store_targets(n.target, n)
                        self.generic_visit(n)

                    def _record_store_targets(self, target: ast.AST, n: ast.AST) -> None:
                        def _collect_names(t: ast.AST, acc: List[ast.Name]) -> None:
                            if isinstance(t, ast.Name):
                                acc.append(t)
                                return
                            for child in ast.iter_child_nodes(t):
                                _collect_names(child, acc)

                        names: List[ast.Name] = []
                        _collect_names(target, names)
                        for nm in names:
                            line = getattr(n, "lineno", None)
                            if isinstance(line, int):
                                prev = fa.later_stores.get(nm.id)
                                if prev is None or line < prev:
                                    fa.later_stores[nm.id] = line

                BodyScan().visit(node)

                # Filter trivial aliases: no later store to alias after the alias line
                for alias, rec in fa.alias_assigns.items():
                    # any store to alias after rec.line?
                    store_line = fa.later_stores.get(alias)
                    if store_line is not None and store_line > rec.line:
                        continue  # alias is reassigned later; skip
                    findings.append(
                        f"{path}:{rec.line}:{rec.col} TRIVIAL_ALIAS {alias} -> {rec.param} Trivial alias to fixture/param; use '{rec.param}' directly."
                    )

    Visitor().visit(tree)
    return findings


def main() -> None:
    ap = argparse.ArgumentParser(description="Detect trivial fixture aliases (report-only)")
    ap.add_argument("paths", nargs="+", help="Files or directories to scan (e.g. tests/)")
    args = ap.parse_args()

    files: List[Path] = []
    for p in args.paths:
        pp = Path(p)
        if pp.is_dir():
            files.extend(pp.rglob("*.py"))
        elif pp.suffix == ".py":
            files.append(pp)

    results: List[str] = []
    for f in files:
        s = str(f)
        # Default scope to tests only; adjust here if needed
        if "tests" not in s:
            continue
        # Ignore detector-fixture samples which intentionally include aliases
        if "tests/detectors/fixtures/" in s or "tests\\detectors\\fixtures\\" in s:
            continue
        results.extend(detect_file(f))

    for line in results:
        print(line)

    raise SystemExit(1 if results else 0)


if __name__ == "__main__":
    main()
