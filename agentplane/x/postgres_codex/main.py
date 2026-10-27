"""Run one transition per process so checkpoints and restart are directly inspectable."""

import argparse
import asyncio
import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from aiohttp import ClientSession, ClientTimeout
from sqlalchemy.ext.asyncio import create_async_engine

from agentplane.x.postgres_codex.code_mode import code_mode
from agentplane.x.postgres_codex.compaction import compact
from agentplane.x.postgres_codex.executor import Executor
from agentplane.x.postgres_codex.sampler import advance, pending_call
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
            print(await store.create(args.prompt, instructions=args.instructions))
            return
        owner = await store.claim(args.conversation_id, lease=timedelta(seconds=120))
        # The advance operation is bounded below the lease; no silent renewal or takeover retry.
        async with asyncio.timeout(90):
            async with ClientSession(timeout=ClientTimeout(total=80)) as http:
                row = await store.read(owner)
                if args.command == "compact":
                    await compact(
                        store,
                        owner,
                        http,
                        endpoint=args.endpoint,
                        credential=os.environ["SPIKE_MODEL_CREDENTIAL"],
                        model=args.model,
                    )
                    result = "compact"
                elif row.pending is None and pending_call(row.items) is not None:
                    async with http.ws_connect(args.executor_url) as socket:
                        executor = Executor(socket, cwd=args.cwd, codex_path=args.executor_codex)
                        await executor.initialize()
                        async with code_mode(args.code_mode_host, args.logs, store, owner, executor) as runtime:
                            result = await advance(
                                store,
                                owner,
                                runtime,
                                http,
                                endpoint=args.endpoint,
                                credential=os.environ["SPIKE_MODEL_CREDENTIAL"],
                                model=args.model,
                                auto_compact_tokens=args.auto_compact_tokens,
                            )
                else:
                    result = await advance(
                        store,
                        owner,
                        None,
                        http,
                        endpoint=args.endpoint,
                        credential=os.environ["SPIKE_MODEL_CREDENTIAL"],
                        model=args.model,
                        auto_compact_tokens=args.auto_compact_tokens,
                    )
        await store.release(owner)
        print(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("prompt")
    init.add_argument("--instructions", help="Standing developer instructions persisted across compaction")
    compact_step = sub.add_parser("compact")
    compact_step.add_argument("conversation_id", type=UUID)
    compact_step.add_argument("--endpoint", required=True)
    compact_step.add_argument("--model", required=True)
    step = sub.add_parser("advance")
    step.add_argument("conversation_id", type=UUID)
    step.add_argument(
        "--auto-compact-tokens",
        type=int,
        help="Trigger before sampling when last provider total_tokens reaches this threshold",
    )
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
