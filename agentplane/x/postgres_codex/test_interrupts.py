"""Real host/executor control paths with independent PostgreSQL checkpoints."""

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
import pytest_bazel
from aiohttp import ClientSession, web
from sqlalchemy import select

from agentplane.native.codex.testing.responses import OpenAIResponses
from agentplane.native.codex.testing.responses_sse import CustomToolCall, response_stream
from agentplane.x.postgres_codex.code_mode import code_mode
from agentplane.x.postgres_codex.control import controlled_advance
from agentplane.x.postgres_codex.control_testing import cli, options, seed
from agentplane.x.postgres_codex.executor import Executor
from agentplane.x.postgres_codex.sampler import pending_call
from agentplane.x.postgres_codex.store import (
    Base,
    Intent,
    InterruptPendingError,
    InterruptRequest,
    LostOwnershipError,
    Owner,
    Store,
)
from util.testing.sqlalchemy_engines import postgres_async_engine
from util.testing.undeclared_outputs import undeclared_outputs_dir


async def test_external_interrupt_sampling_and_explicit_new_input(
    database_url: str, sampler_binary: str, tmp_path: Path
) -> None:
    conversation_id = UUID(await cli(sampler_binary, database_url, "init", "interrupt sampling"))
    async with OpenAIResponses() as endpoint:
        command = options(
            "advance",
            conversation_id,
            "ws://127.0.0.1:1",
            "/unused",
            "/unused",
            tmp_path,
            endpoint.origin + "/v1/responses",
        )
        task = asyncio.create_task(cli(sampler_binary, database_url, *command))
        async with await endpoint.await_next_request():
            status = json.loads(await cli(sampler_binary, database_url, "status", str(conversation_id)))
            await cli(
                sampler_binary,
                database_url,
                "interrupt",
                str(conversation_id),
                "--generation",
                str(status["generation"]),
            )
            assert await task == "interrupted"
        assert await cli(sampler_binary, database_url, *command) == "interrupted"
    async with postgres_async_engine(database_url) as engine:
        store = Store(engine)
        status = await store.status(conversation_id)
        assert status["stopped"]
        assert status["pending"] is None
        with pytest.raises(LostOwnershipError, match="active owner generation"):
            await store.request_interrupt(conversation_id, status["generation"] - 1)
        async with store.sessions() as db:
            (request,) = (await db.scalars(select(InterruptRequest))).all()
            assert request.result is not None
            assert request.result["provider_cancelled"]
            assert request.result["provider_completion_unknown"]
            assert request.result["cleanup_complete"]
    assert await cli(sampler_binary, database_url, "input", str(conversation_id), "continue deliberately") == "input"


async def test_external_interrupt_running_cell_stops_known_process_group(
    database_url: str, sampler_binary: str, codex_binary: str, code_mode_host: str, executor_url: str, tmp_path: Path
) -> None:
    conversation_id = UUID(await cli(sampler_binary, database_url, "init", "interrupt running shell"))
    async with OpenAIResponses() as endpoint:
        task = asyncio.create_task(
            cli(
                sampler_binary,
                database_url,
                *options(
                    "run",
                    conversation_id,
                    executor_url,
                    codex_binary,
                    code_mode_host,
                    tmp_path,
                    endpoint.origin + "/v1/responses",
                ),
            )
        )
        async with await endpoint.await_next_request() as exchange:
            await exchange.send(
                *response_stream(
                    [
                        CustomToolCall(
                            "interrupt-js",
                            "exec",
                            'text(await tools.exec_command({cmd: "sleep 60 & child=$!; printf \\"%s %s\\" $$ \\"$child\\" > pids; wait"}));',
                        ),
                        CustomToolCall(
                            "undispatched-sibling",
                            "exec",
                            'text(await tools.exec_command({cmd: "touch forbidden-sibling"}));',
                        ),
                    ],
                    model="test-model",
                ).events
            )
        async with asyncio.timeout(10):
            while not (tmp_path / "pids").exists():  # noqa: ASYNC110 — external process file readiness
                await asyncio.sleep(0.01)
        pids = [int(pid) for pid in (tmp_path / "pids").read_text().split()]
        status = json.loads(await cli(sampler_binary, database_url, "status", str(conversation_id)))
        await cli(
            sampler_binary, database_url, "interrupt", str(conversation_id), "--generation", str(status["generation"])
        )
        async with asyncio.timeout(10):
            assert await task == "interrupted"
        for pid in pids:
            stat = Path(f"/proc/{pid}/stat")
            assert (
                not await asyncio.to_thread(stat.exists) or (await asyncio.to_thread(stat.read_text)).split()[2] == "Z"
            ), f"known fixture descendant {pid} is live"
    async with postgres_async_engine(database_url) as engine:
        store = Store(engine)
        owner = await store.claim(conversation_id, lease=timedelta(seconds=30))
        row = await store.read(owner)
        assert row.pending is None
        assert row.stopped
        assert "Interrupted by user" in str(row.items[-2])
        assert "Not started" in str(row.items[-1])
        assert not (tmp_path / "forbidden-sibling").exists()
        await store.append_input(owner, "continue explicitly")
        assert pending_call((await store.read(owner)).items) is None
        assert await store.execution_state(owner) == {"cells": [], "processes": []}
        async with store.sessions() as db:
            (request,) = (await db.scalars(select(InterruptRequest))).all()
            assert request.result is not None
            assert request.result["cleanup_complete"]
            assert all(p["exit_observed"] for p in request.result["processes"].values())


@pytest.mark.parametrize("has_call", [False, True])
async def test_prequeued_interrupt_prevents_next_dispatch(database_url: str, has_call: bool) -> None:
    requests = []

    async def reject(request: web.Request) -> web.Response:
        requests.append(await request.read())
        return web.Response(status=500)

    app = web.Application()
    app.router.add_post("/", reject)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        await web.TCPSite(runner, "127.0.0.1", 0).start()
        async with postgres_async_engine(database_url) as engine:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            store = Store(engine)
            if has_call:
                conversation_id, _ = await seed(store, 'text(await tools.exec_command({cmd:"touch forbidden"}));')
            else:
                conversation_id = await store.create("do not sample")
            owner = await store.claim(conversation_id, lease=timedelta(seconds=30))
            await store.request_interrupt(conversation_id, owner.generation)
            with pytest.raises(InterruptPendingError):
                await store.begin(owner, {"kind": "sampling"})
            async with ClientSession() as http:
                assert (
                    await controlled_advance(
                        store,
                        owner,
                        None,
                        None,
                        http,
                        endpoint=f"http://127.0.0.1:{runner.addresses[0][1]}/",
                        credential="test",
                        model="test",
                    )
                    == "interrupted"
                )
            assert not requests
            assert await store.execution_state(owner) == {"cells": [], "processes": []}
            async with store.sessions() as db:
                intents = (await db.scalars(select(Intent))).all()
                assert all(intent.request["kind"] == "sampling" for intent in intents)
            row = await store.read(owner)
            assert row.pending is None
            assert row.stopped
            assert pending_call(row.items) is None
    finally:
        await runner.cleanup()


async def test_interrupt_after_host_start_before_cell_registry_commit(
    database_url: str, codex_binary: str, code_mode_host: str, executor_url: str, tmp_path: Path
) -> None:
    started = asyncio.Event()
    never = asyncio.Event()

    class GatedStore(Store):
        async def cell_result(self, owner: Owner, cell_id: str, status: str) -> None:
            if status == "live":
                started.set()
                await never.wait()
            await super().cell_result(owner, cell_id, status)

    async with postgres_async_engine(database_url) as engine:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        store = GatedStore(engine)
        conversation_id, _ = await seed(store, "await new Promise(() => {});")
        owner = await store.claim(conversation_id, lease=timedelta(seconds=30))
        async with ClientSession() as http, http.ws_connect(executor_url) as socket:
            executor = Executor(socket, cwd=tmp_path, codex_path=codex_binary)
            executor.bind(store, owner)
            await executor.initialize()
            async with code_mode(
                code_mode_host, undeclared_outputs_dir() / "interrupt-start-boundary.log", store, owner, executor
            ) as runtime:
                task = asyncio.create_task(
                    controlled_advance(
                        store,
                        owner,
                        runtime,
                        executor,
                        http,
                        endpoint="http://unused.invalid",
                        credential="test",
                        model="test",
                    )
                )
                async with asyncio.timeout(10):
                    await started.wait()
                    assert not (await store.execution_state(owner))["cells"]
                    await store.request_interrupt(conversation_id, owner.generation)
                    assert await task == "interrupted"
                assert runtime.process.returncode is not None
                assert (await store.read(owner)).stopped
                assert (await store.read(owner)).pending is None
                async with store.sessions() as session:
                    (request,) = (await session.scalars(select(InterruptRequest))).all()
                    assert request.result is not None
                    assert request.result["cells"]["host"]["stopped"]
                    assert request.result["cleanup_complete"]


if __name__ == "__main__":
    pytest_bazel.main()
