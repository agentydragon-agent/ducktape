from __future__ import annotations

import fnmatch
from pathlib import Path

from adgn_llm.inop.config import OptimizerConfig
from adgn_llm.inop.engine.models import FileInfo
from adgn_llm.inop.prompting.truncation_utils import TruncationManager


def gather_agent_files(
    work_dir: Path,
    cfg: OptimizerConfig,
    trunc_mgr: TruncationManager | None = None,
) -> list[FileInfo]:
    files_info: list[FileInfo] = []
    t_mgr = trunc_mgr or TruncationManager(cfg)
    for file_path in work_dir.rglob("*"):
        if not file_path.is_file():
            continue
        relative_path = file_path.relative_to(work_dir).as_posix()
        if any(
            fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(file_path.name, pattern)
            for pattern in cfg.exclude_patterns
        ):
            continue
        relative = file_path.relative_to(work_dir).as_posix()
        content = t_mgr.truncate_file_by_bytes(
            file_path,
            cfg.truncation.max_file_size_grading,
        )
        files_info.append(FileInfo(path=relative, content=content))
    # Convert FileInfo to dicts for token counting, then map back
    truncated = t_mgr.truncate_files_by_tokens(
        [fi.model_dump() for fi in files_info],
        cfg.tokens.max_files_tokens,
    )
    return [FileInfo(**d) for d in truncated]


def should_exclude_file(
    relative_path: str,
    filename: str,
    cfg: OptimizerConfig,
) -> bool:
    return any(
        fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(filename, pattern)
        for pattern in cfg.exclude_patterns
    )
