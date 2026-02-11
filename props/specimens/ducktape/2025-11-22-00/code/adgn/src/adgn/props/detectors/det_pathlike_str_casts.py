from __future__ import annotations

import ast
from pathlib import Path

from .models import Detection, LineRange
from .registry import DetectorSpec, register
from .utils import make_root_detector, read_snippet

DET_NAME = "pathlike_str_casts"
PROP = "python/pathlike"


KNOWN_FUNCS = {
    ("subprocess", "run"),
    ("subprocess", "check_call"),
    ("subprocess", "check_output"),
    ("subprocess", "Popen"),
    ("shutil", "copy"),
    ("shutil", "copyfile"),
    ("logging", "FileHandler"),
    ("zipfile", "ZipFile"),
    ("tarfile", "open"),
}


def _is_known(attr: ast.Attribute) -> bool:
    # Matches module.attr patterns
    if isinstance(attr.value, ast.Name):
        key = (attr.value.id, attr.attr)
        return key in KNOWN_FUNCS
    return False


def _find_in_file(path: Path) -> list[Detection]:
    out: list[Detection] = []
    try:
        node = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return out
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            func = n.func
            matches = False
            if isinstance(func, ast.Attribute) and _is_known(func):
                matches = True
            if isinstance(func, ast.Name) and func.id == "open":
                matches = True
            if not matches:
                continue

            # Any arg subtree contains str(...)? Handle lists/tuples/dicts/kwargs recursively.
            def has_str_call(node: ast.AST) -> bool:
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "str":
                        return True
                return False

            bad = any(has_str_call(a) for a in (list(n.args) + [kw.value for kw in n.keywords]))
            if bad:
                sl = getattr(n, "lineno", 1)
                el = getattr(n, "end_lineno", sl)
                out.append(
                    Detection(
                        property=PROP,
                        path=str(path),
                        ranges=[LineRange(start_line=int(sl), end_line=int(el))],
                        detector=DET_NAME,
                        confidence=0.9,
                        message="Casting PathLike to str for a PathLike-accepting API; pass Path directly.",
                        snippet=read_snippet(path, sl, el, context=0),
                    )
                )
    return out


find = make_root_detector(_find_in_file)


register(DetectorSpec(name=DET_NAME, target_property=PROP, finder=find))
