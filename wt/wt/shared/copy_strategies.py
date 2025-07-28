"""Copy strategies for worktree operations."""

import shutil
import subprocess
import sys
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path


def _get_copyable_entries(src: Path) -> list[str]:
    return [str(src / p.name) for p in src.iterdir() if p.name not in (".worktrees", ".git")]


class CopyStrategy(ABC):
    @abstractmethod
    def copy(self, src: Path, dst: Path) -> None:
        pass

    @property
    @abstractmethod
    def method_name(self) -> str:
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


class ReflinkCopyStrategy(CopyStrategy):
    def copy(self, src: Path, dst: Path) -> None:
        entries = _get_copyable_entries(src)
        if entries:
            cmd = ["cp", "--archive", "--reflink=auto", *entries, str(dst)]
            subprocess.run(cmd, check=True)

    @property
    def method_name(self) -> str:
        return "CoW reflink"


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


def get_copy_strategy() -> CopyStrategy:
    if sys.platform == "darwin" and shutil.which("cp"):
        return ClonefileCopyStrategy()
    if _test_reflink_support():
        return ReflinkCopyStrategy()
    return RsyncCopyStrategy()
