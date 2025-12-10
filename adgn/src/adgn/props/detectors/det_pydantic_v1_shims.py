from __future__ import annotations

import ast
from pathlib import Path

from .base import BaseDetector
from .models import Detection, LineRange
from .utils import read_snippet


class PydanticV1ShimsDetector(BaseDetector):
    DET_NAME = "pydantic_v1_shims"
    PROP = "python/pydantic-2"

    def find_detections(self, path: Path, tree: ast.AST, source: str) -> list[Detection]:
        out: list[Detection] = []
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("pydantic.v1"):
                sl = getattr(n, "lineno", 1)
                out.append(
                    Detection(
                        property=self.PROP,
                        path=str(path),
                        ranges=[LineRange(start_line=int(sl), end_line=int(sl))],
                        detector=self.DET_NAME,
                        confidence=0.95,
                        message="Import from pydantic.v1 — target Pydantic 2 APIs only.",
                        snippet=read_snippet(path, sl, sl, context=0),
                    )
                )
            if isinstance(n, ast.Import):
                for alias in n.names:
                    if alias.name == "pydantic.v1":
                        sl = getattr(n, "lineno", 1)
                        out.append(
                            Detection(
                                property=self.PROP,
                                path=str(path),
                                ranges=[LineRange(start_line=int(sl), end_line=int(sl))],
                                detector=self.DET_NAME,
                                confidence=0.95,
                                message="Importing pydantic.v1 — target Pydantic 2 APIs only.",
                                snippet=read_snippet(path, sl, sl, context=0),
                            )
                        )
            if isinstance(n, ast.ClassDef):
                # Inner 'Config' class indicates v1 style config
                for inner in n.body:
                    if isinstance(inner, ast.ClassDef) and inner.name == "Config":
                        sl = getattr(inner, "lineno", n.lineno)
                        el = getattr(inner, "end_lineno", sl)
                        out.append(
                            Detection(
                                property=self.PROP,
                                path=str(path),
                                ranges=[LineRange(start_line=int(sl), end_line=int(el))],
                                detector=self.DET_NAME,
                                confidence=0.9,
                                message="Pydantic v1 style `class Config:` — use model_config = ConfigDict(...).",
                                snippet=read_snippet(path, sl, el, context=0),
                            )
                        )
                # Decorators @validator/root_validator
                for _dec in n.decorator_list:
                    # Class decorators are unlikely; we focus on function decorators below
                    pass
            if isinstance(n, ast.FunctionDef):
                for dec in n.decorator_list:
                    if isinstance(dec, ast.Name) and dec.id in {"validator", "root_validator"}:
                        sl = getattr(dec, "lineno", n.lineno)
                        out.append(
                            Detection(
                                property=self.PROP,
                                path=str(path),
                                ranges=[LineRange(start_line=int(sl), end_line=int(sl))],
                                detector=self.DET_NAME,
                                confidence=0.9,
                                message="Pydantic v1 validator decorator — use field_validator/model_validator in v2.",
                                snippet=read_snippet(path, sl, sl, context=0),
                            )
                        )
        return out


_detector = PydanticV1ShimsDetector()
find = _detector.get_finder()
_detector.register_detector()
