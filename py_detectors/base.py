"""Base detector infrastructure to eliminate boilerplate across detector implementations."""

from __future__ import annotations

import ast
from abc import ABC, abstractmethod
from collections.abc import Iterable
from pathlib import Path

from py_detectors.models import Detection, LineRange
from py_detectors.registry import DetectorSpec, register
from py_detectors.utils import make_root_detector, parse_python_file, read_snippet


class BaseDetector(ABC):
    """Base class for AST-based detectors.

    Subclasses should:
    1. Set DET_NAME and PROP as class attributes
    2. Implement find_detections() to yield or return Detection objects
    3. Call register_detector() at module level to register with the detector registry

    The base class handles:
    - File reading and AST parsing with error handling
    - Root detector wrapping
    - Registry registration
    - Detection creation with auto-generated snippets
    """

    DET_NAME: str
    PROP: str

    def detection(
        self, path: Path, start_line: int, end_line: int | None, message: str, confidence: float = 0.9
    ) -> Detection:
        """Create a Detection with auto-generated snippet from the line range."""
        return Detection(
            property=self.PROP,
            path=path,
            ranges=[LineRange(start_line=start_line, end_line=end_line)],
            detector=self.DET_NAME,
            confidence=confidence,
            message=message,
            snippet=read_snippet(path, start_line, end_line, context=0),
        )

    @abstractmethod
    def find_detections(self, path: Path, tree: ast.AST, source: str) -> Iterable[Detection]:
        """Find detections in a parsed AST. Can yield or return a list."""
        ...

    def _find_in_file(self, path: Path) -> list[Detection]:
        """Internal wrapper that handles file reading and AST parsing."""
        if not (parsed := parse_python_file(path)):
            return []
        tree, text = parsed
        return list(self.find_detections(path, tree, text))

    def get_finder(self):
        """Get the root detector function for this detector."""
        return make_root_detector(self._find_in_file)

    def register_detector(self):
        """Register this detector with the detector registry."""
        register(DetectorSpec(name=self.DET_NAME, target_property=self.PROP, finder=self.get_finder()))
