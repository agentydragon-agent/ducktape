"""Real Postgres checkpoints against scripted pinned remote-v2 Responses wire."""

import asyncio
import json
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

import pytest
import pytest_bazel
from aiohttp import ClientSession, web
from sqlalchemy import select, update

from agentplane.native.codex.testing.responses_sse import CustomToolCall, Message, response_stream
from agentplane.native.testing.model_endpoint import ModelEndpoint, ModelExchange, SseEvent
from agentplane.x.postgres_codex.compaction import compact, context_bytes
from agentplane.x.postgres_codex.executor import Executor
from agentplane.x.postgres_codex.sampler import advance
from agentplane.x.postgres_codex.store import (
    Base,
    Conversation,
    Intent,
    LostOwnershipError,
    Owner,
    Store,
    UnknownEffectError,
)
from util.testing.sqlalchemy_engines import postgres_async_engine
from util.testing.undeclared_outputs import undeclared_outputs_dir

STANDING = "COMPACTION_STANDING_ORDER: preserve current instructions and execution handles."
OPAQUE = {"type": "compaction", "id": "cmp-1", "encrypted_content": "opaque+/=\\n", "unknown": {"retain": [1, None]}}


@dataclass
class CompactionRequest:
    body: dict[str, Any]
    stream: bool


class CompactionEndpoint(ModelEndpoint[CompactionRequest]):
    """Same queued model-exchange fixture, preserving opaque/unrecognized wire items."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[str, str | None]] = []

    def _parse_request(self, value: Any) -> CompactionRequest:
        return CompactionRequest(value, value["stream"])

    async def serve(self, request: web.Request) -> web.StreamResponse:
        self.requests.append((request.path, request.headers.get("x-codex-beta-features")))
        return await super().serve(request)

    async def await_next_request(self) -> ModelExchange[CompactionRequest]:
        return await asyncio.wait_for(self._next_exchange(), 10)

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()


def event(kind: str, **data: Any) -> SseEvent:
    return SseEvent(kind, ("data: " + json.dumps({"type": kind, **data}) + "\n\n").encode())


def compact_events(item: dict[str, Any] = OPAQUE) -> tuple[SseEvent, ...]:
    # Pinned Rust tests send the item in output_item.done, with no terminal output list.
    return (
        event("response.output_item.done", item=item),
        event(
            "response.completed",
            response={
                "id": "compact-response",
                "usage": {"input_tokens": 900, "output_tokens": 20, "total_tokens": 920},
            },
        ),
    )


@pytest.fixture
async def owned_store(database_url: str) -> AsyncIterator[tuple[Store, Owner]]:
    async with postgres_async_engine(database_url) as engine:
        async with engine.begin() as db:
            await db.run_sync(Base.metadata.create_all)
        store = Store(engine)
        conversation_id = await store.create("Continue working. " * 200, instructions=STANDING)
        owner = await store.claim(conversation_id, lease=timedelta(seconds=60))
        yield store, owner


async def run(binary: str, database_url: str, *args: str) -> str:
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


async def test_compact_restart_and_execute_next_tool(
    owned_store: tuple[Store, Owner],
    database_url: str,
    sampler_binary: str,
    codex_binary: str,
    code_mode_host: str,
    executor_url: str,
    tmp_path: Path,
) -> None:
    store, owner = owned_store
    original = (await store.read(owner)).items
    await store.release(owner)
    async with CompactionEndpoint() as endpoint:
        options = ("--endpoint", endpoint.origin + "/v1/responses", "--model", "test-model")
        task = asyncio.create_task(run(sampler_binary, database_url, "compact", str(owner.conversation_id), *options))
        async with await endpoint.await_next_request() as exchange:
            body = exchange.request.body
            assert body["input"][0]["type"] == "additional_tools"
            assert body["input"][1]["content"] == STANDING
            assert body["input"][-1] == {"type": "compaction_trigger"}
            # Intent is committed before the provider sees the request.
            async with store.sessions() as db:
                row = (await db.scalars(select(Conversation))).one()
                assert row.pending is not None
                assert row.pending["kind"] == "compaction"
                assert row.items == original
                assert row.context_items is None
            await exchange.send(*compact_events())
        assert await task == "compact"
        assert endpoint.requests == [("/v1/responses", "remote_compaction_v2")]
        step = (
            "advance",
            str(owner.conversation_id),
            "--executor-url",
            executor_url,
            "--executor-codex",
            codex_binary,
            "--code-mode-host",
            code_mode_host,
            "--cwd",
            str(tmp_path),
            "--logs",
            str(undeclared_outputs_dir() / "post-compact-cell.log"),
            *options,
        )
        task = asyncio.create_task(run(sampler_binary, database_url, *step))
        async with await endpoint.await_next_request() as exchange:
            body = exchange.request.body
            assert body["input"][0]["type"] == "additional_tools"
            assert [
                item for item in body["input"] if item.get("role") == "developer" and item["type"] == "message"
            ] == [{"type": "message", "role": "developer", "content": STANDING}]
            assert body["input"][-1] == OPAQUE
            assert original[0] not in body["input"]
            await exchange.send(
                *response_stream(
                    [
                        CustomToolCall(
                            "after-compact",
                            "exec",
                            'text((await tools.exec_command({cmd:"printf continued"})).output);',
                        )
                    ],
                    model="test-model",
                ).events
            )
        assert await task == "sample"
        assert await run(sampler_binary, database_url, *step) == "cell"
        task = asyncio.create_task(run(sampler_binary, database_url, *step))
        async with await endpoint.await_next_request() as exchange:
            body = exchange.request.body
            assert OPAQUE in body["input"]
            assert "continued" in str(body["input"][-1])
            await exchange.send(*response_stream([Message("DONE")], model="test-model").events)
        assert await task == "sample"
        assert await run(sampler_binary, database_url, *step, "--auto-compact-tokens", "1") == "done"
    owner = await store.claim(owner.conversation_id, lease=timedelta(seconds=30))
    row = await store.read(owner)
    assert row.items[: len(original)] == original
    assert len(row.items) == len(original) + 3
    assert row.context_items is not None
    assert row.context_items[0] == OPAQUE
    assert context_bytes(row.context_items) < context_bytes(row.items)
    await store.append_input(owner, "A new user turn.")
    resumed = await store.read(owner)
    assert (
        resumed.context()[-1] == resumed.items[-1] == {"type": "message", "role": "user", "content": "A new user turn."}
    )
    async with store.sessions() as db:
        intent = (await db.scalars(select(Intent).where(Intent.request["kind"].astext == "compaction"))).one()
        assert intent.result is not None
        assert intent.result["events"][0]["item"] == OPAQUE


@pytest.mark.parametrize("failure", ["partial", "failed", "tool", "growing", "duplicate", "cancel", "ownership"])
async def test_compaction_does_not_replace_on_failure(owned_store: tuple[Store, Owner], failure: str) -> None:
    store, owner = owned_store
    original = (await store.read(owner)).items
    async with CompactionEndpoint() as endpoint, ClientSession() as http:
        task = asyncio.create_task(
            compact(store, owner, http, endpoint=endpoint.origin + "/v1/responses", credential="test", model="test")
        )
        async with await endpoint.await_next_request() as exchange:
            if failure == "cancel":
                task.cancel()
            elif failure == "partial":
                await exchange.send(compact_events()[0])
            elif failure == "failed":
                await exchange.send(event("response.failed", response={"status": "failed"}))
            else:
                if failure == "ownership":
                    async with store.sessions.begin() as db:
                        await db.execute(
                            update(Conversation)
                            .where(Conversation.id == owner.conversation_id)
                            .values(lease_until=Conversation.lease_until - timedelta(minutes=5))
                        )
                if failure == "tool":
                    await exchange.send(
                        *compact_events(
                            {
                                "type": "custom_tool_call",
                                "call_id": "forbidden",
                                "name": "exec",
                                "input": 'text(await tools.exec_command({cmd:"touch unwanted"}));',
                            }
                        )
                    )
                elif failure == "growing":
                    await exchange.send(*compact_events({"type": "compaction", "encrypted_content": "large" * 2000}))
                elif failure == "duplicate":
                    await exchange.send(compact_events()[0], *compact_events())
                else:
                    await exchange.send(*compact_events())
        with pytest.raises((ConnectionError, RuntimeError, ValueError, asyncio.CancelledError, LostOwnershipError)):
            await task
    async with store.sessions() as db:
        row = (await db.scalars(select(Conversation))).one()
        assert row.items == original
        assert row.context_items is None
        assert row.pending is not None
        assert row.pending["kind"] == "compaction"
        intent = (await db.scalars(select(Intent))).one()
        assert intent.result is None
    if failure != "ownership":
        async with ClientSession() as http:
            with pytest.raises(UnknownEffectError, match="unresolved"):
                await advance(store, owner, None, http, endpoint="http://unused", credential="test", model="test")


@pytest.mark.parametrize("guard", ["call", "orphan", "nested", "pending", "live_cell"])
async def test_compaction_preflight_guards(owned_store: tuple[Store, Owner], guard: str) -> None:
    store, owner = owned_store
    if guard == "live_cell":
        await store.cell_result(owner, "in-flight-js", "live")
    elif guard == "nested":
        await store.record_nested(owner, {"kind": "tool"})
    elif guard == "pending":
        await store.begin(owner, {"kind": "cell"})
    else:
        item = (
            {"type": "custom_tool_call", "call_id": "call", "name": "exec", "input": "text(1);"}
            if guard == "call"
            else {"type": "custom_tool_call_output", "call_id": "missing", "output": "x"}
        )
        intent = await store.begin(owner, {"kind": "sampling"})
        await store.finish(owner, intent, {"response": {}}, [item])
    async with ClientSession() as http:
        with pytest.raises(UnknownEffectError):
            await compact(store, owner, http, endpoint="http://unused", credential="test", model="test")


async def test_automatic_threshold_and_no_repeat(owned_store: tuple[Store, Owner]) -> None:
    store, owner = owned_store
    intent = await store.begin(owner, {"kind": "sampling"})
    await store.finish(owner, intent, {"response": {"usage": {"total_tokens": 100}}}, [], context_tokens=100)
    async with CompactionEndpoint() as endpoint, ClientSession() as http:
        options: dict[str, Any] = {
            "endpoint": endpoint.origin + "/v1/responses",
            "credential": "test",
            "model": "test",
            "auto_compact_tokens": 100,
        }
        task = asyncio.create_task(advance(store, owner, None, http, **options))
        async with await endpoint.await_next_request() as exchange:
            assert exchange.request.body["input"][-1] == {"type": "compaction_trigger"}
            await exchange.send(*compact_events())
        assert await task == "compact"
        assert (await store.read(owner)).context_tokens is None
        task = asyncio.create_task(advance(store, owner, None, http, **options))
        async with await endpoint.await_next_request() as exchange:
            assert exchange.request.body["input"][-1] == OPAQUE
            await exchange.send(*response_stream([Message("DONE")], model="test").events)
        assert await task == "sample"
        assert await advance(store, owner, None, http, **options) == "done"


async def test_live_process_handle_survives_compaction_and_fresh_sampler(
    owned_store: tuple[Store, Owner],
    database_url: str,
    sampler_binary: str,
    codex_binary: str,
    executor_url: str,
    tmp_path: Path,
) -> None:
    store, owner = owned_store
    process_id = str(uuid4())
    async with ClientSession() as http, http.ws_connect(executor_url) as socket, CompactionEndpoint() as endpoint:
        executor = Executor(socket, cwd=tmp_path, codex_path=codex_binary)
        await executor.initialize()
        await store.register_process(owner, process_id, tty=False)
        await executor.rpc(
            "process/start",
            {
                "processId": process_id,
                "argv": ["/bin/sh", "-c", "sleep 60"],
                "cwd": tmp_path.as_uri(),
                "env": {},
                "tty": False,
                "pipeStdin": False,
                "arg0": None,
            },
        )
        await store.process_result(owner, process_id, None, "running")
        await store.release(owner)
        options = ("--endpoint", endpoint.origin + "/v1/responses", "--model", "test")
        try:
            task = asyncio.create_task(
                run(sampler_binary, database_url, "compact", str(owner.conversation_id), *options)
            )
            async with await endpoint.await_next_request() as exchange:
                handle_message = next(
                    item for item in exchange.request.body["input"] if "Active execution handles:" in str(item)
                )
                assert process_id in handle_message["content"]
                await exchange.send(*compact_events())
            assert await task == "compact"
            # Sampling needs no executor connection; its independent process rebuilds handle state from Postgres.
            task = asyncio.create_task(
                run(
                    sampler_binary,
                    database_url,
                    "advance",
                    str(owner.conversation_id),
                    "--executor-url",
                    "ws://unused",
                    "--executor-codex",
                    codex_binary,
                    "--code-mode-host",
                    "unused",
                    "--cwd",
                    str(tmp_path),
                    "--logs",
                    str(tmp_path / "unused.log"),
                    *options,
                )
            )
            async with await endpoint.await_next_request() as exchange:
                assert handle_message in exchange.request.body["input"]
                assert OPAQUE in exchange.request.body["input"]
                await exchange.send(*response_stream([Message("DONE")], model="test").events)
            assert await task == "sample"
            process = await executor.rpc(
                "process/read", {"processId": process_id, "afterSeq": None, "maxBytes": 1024, "waitMs": 0}
            )
            assert not process["exited"]
        finally:
            await executor.rpc("process/signal", {"processId": process_id, "signal": "interrupt"})


if __name__ == "__main__":
    pytest_bazel.main()
