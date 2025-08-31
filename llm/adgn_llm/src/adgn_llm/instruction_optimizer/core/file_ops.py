from __future__ import annotations

import asyncio
import fnmatch
from pathlib import Path

from adgn_llm.instruction_optimizer.config import OptimizerConfig
from adgn_llm.instruction_optimizer.core.models import FileInfo
from adgn_llm.instruction_optimizer.core.truncation_utils import TruncationManager


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
            fnmatch.fnmatch(relative_path, pattern)
            or fnmatch.fnmatch(file_path.name, pattern)
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


async def copy_files_from_container(
    container_id: str,
    container_workdir: str,
    host_workdir: Path,
    task_logger,
    cfg: OptimizerConfig,
) -> None:
    list_cmd = [
        "docker",
        "exec",
        container_id,
        "find",
        container_workdir,
        "-type",
        "f",
    ]
    result = await asyncio.create_subprocess_exec(
        *list_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await result.communicate()
    if result.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")
        task_logger.error("Failed to list container files", error=error_msg)
        raise RuntimeError(f"Failed to list container files: {error_msg}")
    container_files = stdout.decode("utf-8", errors="replace").strip().split("\n")
    copied_count = 0
    excluded_count = 0
    for container_file_path in container_files:
        if not container_file_path.strip():
            continue
        if not container_file_path.startswith(container_workdir):
            continue
        relative_path = container_file_path[len(container_workdir) :].lstrip("/")
        filename = Path(container_file_path).name
        if should_exclude_file(relative_path, filename, cfg):
            excluded_count += 1
            continue
        host_file_path = host_workdir / relative_path
        host_file_path.parent.mkdir(parents=True, exist_ok=True)
        copy_cmd = [
            "docker",
            "cp",
            f"{container_id}:{container_file_path}",
            str(host_file_path),
        ]
        copy_result = await asyncio.create_subprocess_exec(
            *copy_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await copy_result.wait()
        if copy_result.returncode == 0:
            copied_count += 1
        else:
            copy_stderr = await copy_result.stderr.read() if copy_result.stderr else b""
            error_msg = copy_stderr.decode("utf-8", errors="replace")
            task_logger.error(
                "Failed to copy file",
                container_path=container_file_path,
                host_path=str(host_file_path),
                error=error_msg,
            )
            raise RuntimeError(
                f"Failed to copy file {container_file_path}: {error_msg}",
            )
    task_logger.info(
        "Container files copied",
        copied_files=copied_count,
        excluded_files=excluded_count,
    )
