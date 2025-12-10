"""Base detector infrastructure to eliminate boilerplate across detector implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
import ast
from pathlib import Path

from .models import Detection
from .registry import DetectorSpec, register
from .utils import make_root_detector


class BaseDetector(ABC):
    """Base class for AST-based detectors.

    Subclasses should:
    1. Set DET_NAME and PROP as class attributes
    2. Implement find_detections() to return list of Detection objects
    3. Call register_detector() at module level to register with the detector registry

    The base class handles:
    - File reading and AST parsing with error handling
    - Root detector wrapping
    - Registry registration
    """

    DET_NAME: str
    PROP: str

    @abstractmethod
    def find_detections(self, path: Path, tree: ast.AST, source: str) -> list[Detection]:
        """Find detections in a parsed AST.

        Args:
            path: Path to the file being analyzed
            tree: Parsed AST of the file
            source: Original source code text

        Returns:
            List of Detection objects found in this file
        """
        ...

    def _find_in_file(self, path: Path) -> list[Detection]:
        """Internal wrapper that handles file reading and AST parsing."""
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except Exception:
            return []

        return self.find_detections(path, tree, text)

    def get_finder(self):
        """Get the root detector function for this detector."""
        return make_root_detector(self._find_in_file)

    def register_detector(self):
        """Register this detector with the detector registry."""
        register(DetectorSpec(name=self.DET_NAME, target_property=self.PROP, finder=self.get_finder()))
