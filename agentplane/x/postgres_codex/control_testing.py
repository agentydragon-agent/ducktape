"""Common fixture operations for real process-control integration cases."""

import asyncio
import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from agentplane.x.postgres_codex.store import Store
from util.testing.undeclared_outputs import undeclared_outputs_dir


async def cli(binary: str, database_url: str, *args: str) -> str:
    process = await asyncio.create_subprocess_exec(
        binary,
        "--database-url",
        database_url,
        *args,
        env={**os.environ, "SPIKE_MODEL_CREDENTIAL": "test-key"},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    return stdout.decode().strip()


def options(
    command: str,
    conversation_id: UUID,
    executor_url: str,
    codex_binary: str,
    code_mode_host: str,
    tmp_path: Path,
    endpoint: str,
) -> tuple[str, ...]:
    return (
        command,
        str(conversation_id),
        "--executor-url",
        executor_url,
        "--executor-codex",
        codex_binary,
        "--code-mode-host",
        code_mode_host,
        "--cwd",
        str(tmp_path),
        "--logs",
        str(undeclared_outputs_dir() / "controls-host.log"),
        "--endpoint",
        endpoint,
        "--model",
        "test-model",
    )


async def seed(store: Store, source: str) -> tuple[UUID, dict[str, str]]:
    conversation_id = await store.create("exercise process control")
    owner = await store.claim(conversation_id, lease=timedelta(seconds=30))
    call = {"type": "custom_tool_call", "name": "exec", "call_id": "control-cell", "input": source}
    intent = await store.begin(owner, {"kind": "sampling"})
    await store.finish(owner, intent, {"output": [call]}, [call])
    await store.release(owner)
    return conversation_id, call
