"""Advance a checkpoint, or retain a host for model-facing cell wait and interrupts."""

import argparse
import asyncio
import json
import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from aiohttp import ClientSession, ClientTimeout
from sqlalchemy.ext.asyncio import create_async_engine

from agentplane.x.postgres_codex.code_mode import code_mode
from agentplane.x.postgres_codex.control import controlled_advance
from agentplane.x.postgres_codex.executor import Executor
from agentplane.x.postgres_codex.sampler import pending_call
from agentplane.x.postgres_codex.store import Base, Store
from util.testing.sqlalchemy_engines import managed_async_engine

# SQLAlchemy loads this dialect dynamically from the explicit database URL.
# gazelle:include_dep @pypi//asyncpg


async def run(args: argparse.Namespace) -> None:
    async with managed_async_engine(create_async_engine(args.database_url)) as engine:
        store = Store(engine)
        if args.command == "init":
            async with engine.begin() as db:
                await db.run_sync(Base.metadata.create_all)
            print(await store.create(args.prompt))
            return
        if args.command == "status":
            print(json.dumps(await store.status(args.conversation_id)))
            return
        if args.command == "interrupt":
            print(await store.request_interrupt(args.conversation_id, args.generation))
            return
        owner = await store.claim(args.conversation_id, lease=timedelta(seconds=120))
        if args.command == "input":
            await store.append_input(owner, args.prompt)
            await store.release(owner)
            print("input")
            return
        # The advance operation is bounded below the lease; no silent renewal or takeover retry.
        async with asyncio.timeout(90):
            async with ClientSession(timeout=ClientTimeout(total=80)) as http:
                row = await store.read(owner)
                state = await store.execution_state(owner)
                if args.command == "run" or (
                    not row.stopped
                    and row.pending is None
                    and (pending_call(row.items) is not None or state["processes"])
                ):
                    async with http.ws_connect(args.executor_url) as socket:
                        executor = Executor(socket, cwd=args.cwd, codex_path=args.executor_codex)
                        executor.bind(store, owner)
                        await executor.initialize()
                        async with code_mode(args.code_mode_host, args.logs, store, owner, executor) as runtime:
                            while True:
                                result = await controlled_advance(
                                    store,
                                    owner,
                                    runtime,
                                    executor,
                                    http,
                                    endpoint=args.endpoint,
                                    credential=os.environ["SPIKE_MODEL_CREDENTIAL"],
                                    model=args.model,
                                )
                                if args.command != "run" or result in {"done", "interrupted", "effects_unknown"}:
                                    break
                else:
                    result = await controlled_advance(
                        store,
                        owner,
                        None,
                        None,
                        http,
                        endpoint=args.endpoint,
                        credential=os.environ["SPIKE_MODEL_CREDENTIAL"],
                        model=args.model,
                    )
        await store.release(owner)
        print(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("prompt")
    status = sub.add_parser("status")
    status.add_argument("conversation_id", type=UUID)
    interrupt = sub.add_parser("interrupt")
    interrupt.add_argument("conversation_id", type=UUID)
    interrupt.add_argument("--generation", type=int, required=True)
    new_input = sub.add_parser("input")
    new_input.add_argument("conversation_id", type=UUID)
    new_input.add_argument("prompt")
    for command in ("advance", "run"):
        step = sub.add_parser(command)
        step.add_argument("conversation_id", type=UUID)
        step.add_argument("--executor-url", required=True)
        step.add_argument("--executor-codex", required=True, help="Absolute codex binary path on the executor")
        step.add_argument("--code-mode-host", required=True)
        step.add_argument("--cwd", type=Path, required=True)
        step.add_argument("--logs", type=Path, required=True)
        step.add_argument("--endpoint", required=True, help="Full Responses endpoint URL")
        step.add_argument("--model", required=True)
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
