"""Copy strategies for worktree operations."""

import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path


def _get_copyable_entries(src: Path) -> list[str]:
    return [str(src / p.name) for p in src.iterdir() if p.name not in (".worktrees", ".git")]


class StrategyType(Enum):
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
            cmd = ["cp", "-c", "-R", *entries, str(dst)]
            subprocess.run(cmd, check=True)

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
            cmd = ["cp", "--archive", "--reflink=auto", *entries, str(dst)]
            subprocess.run(cmd, check=True)

    @property
    def method_name(self) -> str:
        return "CoW reflink"
    
    @property
    def strategy_type(self) -> StrategyType:
        return StrategyType.REFLINK


class RsyncCopyStrategy(CopyStrategy):
    def copy(self, src: Path, dst: Path) -> None:
        cmd = [
            "rsync",
            "-a",
            "--delete",
            "--exclude=.git/",
            "--exclude=.worktrees/",
            f"{src}/",
            f"{dst}/",
        ]
        subprocess.run(cmd, check=True)

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
                ["cp", "--reflink=auto", str(test_file), str(test_copy)],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False


def get_copy_strategy(cow_method=None) -> CopyStrategy:
    """Get copy strategy based on cow_method preference or auto-detection."""
    from ..shared.configuration import CowMethod
    
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
    from ..shared.configuration import CowMethod
    
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
