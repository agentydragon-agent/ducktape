from __future__ import annotations

import ast
from pathlib import Path

from .base import BaseDetector
from .models import Detection, LineRange
from .utils import is_broad_exception, read_snippet


class BroadExceptOrderDetector(BaseDetector):
    DET_NAME = "broad_except_order"
    PROP = "python/scoped-try-except"

    def find_detections(self, path: Path, tree: ast.AST, source: str) -> list[Detection]:
        out: list[Detection] = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Try):
                handlers = n.handlers if n.handlers is not None else []
                # Find first broad handler index
                first_broad = None
                for i, h in enumerate(handlers):
                    if is_broad_exception(h):
                        first_broad = i
                        break
                if first_broad is None:
                    continue
                # If any later handler is specific, report unreachable ordering
                for j in range(first_broad + 1, len(handlers)):
                    h = handlers[j]
                    if not is_broad_exception(h):
                        sl = getattr(handlers[first_broad], "lineno", getattr(n, "lineno", 1))
                        el = getattr(handlers[first_broad], "end_lineno", sl)
                        out.append(
                            Detection(
                                property=self.PROP,
                                path=str(path),
                                ranges=[LineRange(start_line=int(sl), end_line=int(el))],
                                detector=self.DET_NAME,
                                confidence=0.95,
                                message="Broad except precedes specific handler; later handler is unreachable.",
                                snippet=read_snippet(path, sl, el, context=0),
                            )
                        )
                        break
        return out


_detector = BroadExceptOrderDetector()
find = _detector.get_finder()
_detector.register_detector()
