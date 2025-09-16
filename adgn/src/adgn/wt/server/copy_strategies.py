"""Copy strategies for worktree operations."""

import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from enum import StrEnum
from pathlib import Path

from ..shared.configuration import CowMethod


def _get_copyable_entries(src: Path) -> list[Path]:
    return [src / p.name for p in src.iterdir() if p.name != ".git"]


class StrategyType(StrEnum):
    """Copy strategy types."""

    CLONEFILE = "clonefile"
    REFLINK = "reflink"
    RSYNC = "rsync"


class CopyStrategy(ABC):
    @abstractmethod
    def copy(self, src: Path, dst: Path) -> None:
        pass

    @property
    @abstractmethod
    def method_name(self) -> str:
        pass

    @property
    @abstractmethod
    def strategy_type(self) -> StrategyType:
        pass


class ClonefileCopyStrategy(CopyStrategy):
    def copy(self, src: Path, dst: Path) -> None:
        entries = _get_copyable_entries(src)
        if entries:
            subprocess.run(["cp", "-c", "-R", *entries, dst], check=True)

    @property
    def method_name(self) -> str:
        return "CoW clonefile"

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.CLONEFILE


class ReflinkCopyStrategy(CopyStrategy):
    def copy(self, src: Path, dst: Path) -> None:
        entries = _get_copyable_entries(src)
        if entries:
            subprocess.run(
                ["cp", "--archive", "--reflink=auto", *entries, dst],
                check=True,
            )

    @property
    def method_name(self) -> str:
        return "CoW reflink"

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.REFLINK


class RsyncCopyStrategy(CopyStrategy):
    def copy(self, src: Path, dst: Path) -> None:
        subprocess.run(
            [
                "rsync",
                "-a",
                "--delete",
                "--exclude=.git/",
                "--exclude=.worktrees/",
                f"{src}/",
                f"{dst}/",
            ],
            check=True,
        )

    @property
    def method_name(self) -> str:
        return "rsync copy"

    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.RSYNC


def _test_reflink_support() -> bool:
    if not shutil.which("cp"):
        return False

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        test_file = tmpdir_path / "test_src.txt"
        test_copy = tmpdir_path / "test_dst.txt"

        # Create a test file
        test_file.write_text("test content")

        # Try to copy with reflink
        try:
            subprocess.run(
                ["cp", "--reflink=auto", test_file, test_copy],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False


def get_copy_strategy(cow_method=None) -> CopyStrategy:
    """Get copy strategy based on cow_method preference or auto-detection."""

    # If cow_method is specified and not AUTO, try to use it
    if cow_method and cow_method != CowMethod.AUTO:
        return _get_strategy_for_method(cow_method)

    # Auto-detection logic (default behavior)
    if sys.platform == "darwin" and shutil.which("cp"):
        return ClonefileCopyStrategy()
    if _test_reflink_support():
        return ReflinkCopyStrategy()
    return RsyncCopyStrategy()


def _get_strategy_for_method(cow_method) -> CopyStrategy:
    """Get strategy for specific CowMethod, with availability validation."""
    if cow_method == CowMethod.REFLINK:
        if _test_reflink_support():
            return ReflinkCopyStrategy()
        raise RuntimeError("Reflink copy is not supported on this system")

    if cow_method == CowMethod.COPY:
        # "copy" maps to clonefile on macOS, reflink elsewhere
        if sys.platform == "darwin" and shutil.which("cp"):
            return ClonefileCopyStrategy()
        if _test_reflink_support():
            return ReflinkCopyStrategy()
        return RsyncCopyStrategy()

    if cow_method == CowMethod.RSYNC:
        if not shutil.which("rsync"):
            raise RuntimeError("rsync is not available on this system")
        return RsyncCopyStrategy()

    raise RuntimeError(f"Unknown copy method: {cow_method}")
