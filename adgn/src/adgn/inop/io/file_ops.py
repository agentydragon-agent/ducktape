from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import cast

from adgn.inop.config import OptimizerConfig
from adgn.inop.engine.models import FileInfo
from adgn.inop.prompting.truncation_utils import TruncationManager


def gather_agent_files(
    work_dir: Path, cfg: OptimizerConfig, trunc_mgr: TruncationManager | None = None
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
        content = t_mgr.truncate_file_by_bytes(file_path, cfg.truncation.max_file_size_grading)
        files_info.append(FileInfo(path=relative, content=content))
    # Truncate directly on FileInfo objects and return models
    truncated_models = t_mgr.truncate_files_by_tokens(files_info, cfg.tokens.max_files_tokens)
    return cast(list[FileInfo], truncated_models)


def should_exclude_file(relative_path: str, filename: str, cfg: OptimizerConfig) -> bool:
    return any(
        fnmatch.fnmatch(relative_path, pattern) or fnmatch.fnmatch(filename, pattern)
        for pattern in cfg.exclude_patterns
    )
