from __future__ import annotations

import ast
from pathlib import Path

from .base import BaseDetector
from .models import Detection, LineRange
from .utils import read_snippet

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


class PathlikeStrCastsDetector(BaseDetector):
    DET_NAME = "pathlike_str_casts"
    PROP = "python/pathlike"

    def find_detections(self, path: Path, tree: ast.AST, source: str) -> list[Detection]:
        out: list[Detection] = []
        for n in ast.walk(tree):
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
                            property=self.PROP,
                            path=str(path),
                            ranges=[LineRange(start_line=int(sl), end_line=int(el))],
                            detector=self.DET_NAME,
                            confidence=0.9,
                            message="Casting PathLike to str for a PathLike-accepting API; pass Path directly.",
                            snippet=read_snippet(path, sl, el, context=0),
                        )
                    )
        return out


_detector = PathlikeStrCastsDetector()
find = _detector.get_finder()
_detector.register_detector()
