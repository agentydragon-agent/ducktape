from __future__ import annotations

import ast
from pathlib import Path

from .models import Detection, LineRange
from .registry import DetectorSpec, register
from .utils import make_root_detector, read_snippet

DET_NAME = "optional_string_simplify"
PROP = "boolean-idioms"


def _collect_optional_str(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    names: set[str] = set()
    for st in func.body:
        if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
            ann = st.annotation
            # str | None or Optional[str]
            if isinstance(ann, ast.Name) and ann.id == "str":
                # not optional
                continue
            if isinstance(ann, ast.BinOp) and isinstance(ann.op, ast.BitOr):
                # PEP 604 unions: support "str | None" where None is Constant(None)
                left, right = ann.left, ann.right

                def tag(n: ast.AST) -> str | None:
                    if isinstance(n, ast.Name):
                        return n.id
                    if isinstance(n, ast.Constant) and n.value is None:
                        return "None"
                    return None

                ids = {tag(left), tag(right)}
                if "str" in ids and "None" in ids:
                    names.add(st.target.id)
            if (
                isinstance(ann, ast.Subscript)
                and isinstance(ann.value, ast.Name)
                and ann.value.id in {"Optional", "Union"}
                and "str" in (unparsed := ast.unparse(ann.slice))
                and "None" in unparsed
            ):
                # Optional[str] or Union[str, None]
                names.add(st.target.id)
    return names


def _is_empty_str(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value == ""


def _is_none(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _match_none_or_empty(test: ast.AST) -> str | None:
    # Return variable name when pattern matches: x is None or x == ""
    if not isinstance(test, ast.BoolOp) or not isinstance(test.op, ast.Or):
        return None
    vals = test.values
    if len(vals) != 2:
        return None
    a, b = vals

    def _cmp_name(n: ast.AST) -> tuple[str | None, str | None]:
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and len(n.comparators) == 1:
            left, op, right = n.left, n.ops[0], n.comparators[0]
            # x is None
            if isinstance(op, ast.Is) and isinstance(left, ast.Name) and _is_none(right):
                return left.id, "isNone"
            # x == ""
            if isinstance(op, ast.Eq) and isinstance(left, ast.Name) and _is_empty_str(right):
                return left.id, "eqEmpty"
        return None, None

    n1, k1 = _cmp_name(a)
    n2, k2 = _cmp_name(b)
    if n1 and n2 and n1 == n2 and {k1, k2} == {"isNone", "eqEmpty"}:
        return n1
    return None


def _find_in_file(path: Path) -> list[Detection]:
    out: list[Detection] = []
    try:
        text = path.read_text(encoding="utf-8")
        node = ast.parse(text)
    except Exception:
        return out
    for fn in ast.walk(node):
        if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
            opt_strs = _collect_optional_str(fn)
            for st in fn.body:
                if isinstance(st, ast.If | ast.While):
                    nm = _match_none_or_empty(st.test)
                    if nm and nm in opt_strs:
                        sl = getattr(st, "lineno", 1)
                        out.append(
                            Detection(
                                property=PROP,
                                path=str(path),
                                ranges=[LineRange(start_line=int(sl), end_line=int(sl))],
                                detector=DET_NAME,
                                confidence=0.8,
                                message=(
                                    f"Optional[str] check '{nm} is None or {nm} == \"\"' → prefer 'if not {nm}' (safe-only)"
                                ),
                                snippet=read_snippet(path, sl, sl, context=0),
                            )
                        )
    return out


find = make_root_detector(_find_in_file)


register(DetectorSpec(name=DET_NAME, target_property=PROP, finder=find))
