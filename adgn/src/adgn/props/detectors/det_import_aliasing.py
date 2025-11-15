from __future__ import annotations

import ast
from pathlib import Path

from .models import Detection, LineRange
from .registry import DetectorSpec, register
from .utils import make_root_detector, read_snippet

DET_NAME = "import_aliasing"
PROP = "no-random-renames"

# Conventional aliases to allow (heuristic, non-exhaustive)
ALLOWED_IMPORT_ALIASES: set[tuple[str, str]] = {
    ("numpy", "np"),
    ("pandas", "pd"),
    ("matplotlib", "mpl"),
    ("matplotlib.pyplot", "plt"),
    ("seaborn", "sns"),
    ("networkx", "nx"),
    ("tensorflow", "tf"),
    ("sqlalchemy", "sa"),
    ("jax.numpy", "jnp"),
    ("numpy.random", "npr"),
    ("torch.nn", "nn"),
    ("torch.nn.functional", "F"),
    ("plotly.express", "px"),
}


def _collect_top_level_names(mod: ast.Module) -> set[str]:
    names: set[str] = set()
    for stmt in mod.body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        # ignore imports here to avoid self-influence; we care about collisions with local defs
    return names


def _find_in_file(path: Path) -> list[Detection]:
    out: list[Detection] = []
    try:
        text = path.read_text(encoding="utf-8")
        node = ast.parse(text)
    except Exception:
        return out

    top_names = _collect_top_level_names(node)

    for stmt in node.body:
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.asname:
                    full = (alias.name or "").strip()
                    base = (full.split(".")[0] if full else "").strip()
                    alias_name = alias.asname
                    allowed = (full, alias_name) in ALLOWED_IMPORT_ALIASES or (
                        base,
                        alias_name,
                    ) in ALLOWED_IMPORT_ALIASES
                    if base and alias_name != base and base not in top_names and not allowed:
                        sl = getattr(stmt, "lineno", 1)
                        out.append(
                            Detection(
                                property=PROP,
                                path=str(path),
                                ranges=[LineRange(start_line=int(sl), end_line=int(sl))],
                                detector=DET_NAME,
                                confidence=0.7,
                                message=(
                                    f"Import alias without local collision: 'import {alias.name} as {alias_name}' — prefer direct name unless disambiguation/collision."
                                ),
                                snippet=read_snippet(path, sl, sl, context=0),
                            )
                        )
        elif isinstance(stmt, ast.ImportFrom):
            for alias in stmt.names:
                if alias.asname and alias.name:
                    original = alias.name
                    alias_name = alias.asname
                    full_mod = stmt.module or ""
                    allowed = (full_mod, original) in {("torch.nn", "functional")} and alias_name in {"F"}
                    if original != alias_name and original not in top_names and not allowed:
                        sl = getattr(stmt, "lineno", 1)
                        modname = full_mod
                        out.append(
                            Detection(
                                property=PROP,
                                path=str(path),
                                ranges=[LineRange(start_line=int(sl), end_line=int(sl))],
                                detector=DET_NAME,
                                confidence=0.7,
                                message=(
                                    f"Import alias without local collision: 'from {modname} import {original} as {alias_name}' — prefer direct name unless disambiguation/collision."
                                ),
                                snippet=read_snippet(path, sl, sl, context=0),
                            )
                        )
    return out


find = make_root_detector(_find_in_file)


register(DetectorSpec(name=DET_NAME, target_property=PROP, finder=find))
