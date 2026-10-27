import asyncio
import os
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
import pytest_bazel
from aiohttp import ClientSession
from sqlalchemy import select, update

from agentplane.native.codex import wire
from agentplane.native.codex.testing.harness import CodexHarness
from agentplane.native.codex.testing.responses import OpenAIResponses
from agentplane.native.codex.testing.responses_sse import CustomToolCall, Message, Reasoning, response_stream
from agentplane.x.postgres_codex.code_mode import code_mode
from agentplane.x.postgres_codex.executor import Executor
from agentplane.x.postgres_codex.sampler import advance
from agentplane.x.postgres_codex.store import Base, Conversation, Intent, LostOwnershipError, Store, UnknownEffectError
from agentplane.x.postgres_codex.testing import ExecutorServer, ObservingExecutor, drop_completed_process_reply
from util.testing.sqlalchemy_engines import postgres_async_engine
from util.testing.undeclared_outputs import undeclared_outputs_dir


async def test_same_wire_fixture_drives_pinned_codex(codex_binary: str, tmp_path: Path) -> None:
    """An independent upstream consumer validates the scripted provider conversation shape."""
    logs = undeclared_outputs_dir() / "native-baseline"
    logs.mkdir()
    (tmp_path / "native-home").mkdir()
    harness = CodexHarness(
        workspace=tmp_path,
        logs=logs,
        codex_home=tmp_path / "native-home",
        binary=codex_binary,
        base_environment=dict(os.environ),
    )
    async with OpenAIResponses() as endpoint, harness.start(endpoint) as native:
        turn = await native.start_turn("Run a tool and report.", model="gpt-6-luna")
        async with await endpoint.await_next_request() as exchange:
            assert exchange.request.code_mode
            await exchange.send(
                *response_stream(
                    [
                        Reasoning("opaque provider state", "opaque-test-reasoning"),
                        CustomToolCall(
                            "native-baseline-call",
                            "exec",
                            'text((await tools.exec_command({cmd: "printf native-wire-ok"})).output);',
                        ),
                    ],
                    model="gpt-6-luna",
                ).events
            )
        async with await endpoint.await_next_request() as exchange:
            assert exchange.request.reasoning[0].encrypted_content == "opaque-test-reasoning"
            (output,) = exchange.request.custom_tool_call_outputs
            assert output.call_id == "native-baseline-call"
            assert "native-wire-ok" in str(output.output)
            await exchange.send(*response_stream([Message("DONE")], model="gpt-6-luna").events)
        assert (await turn.completed()).params.turn.status is wire.TurnStatus.COMPLETED


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


async def test_upstream_cell_and_postgres_resume(
    database_url: str, sampler_binary: str, codex_binary: str, code_mode_host: str, executor_url: str, tmp_path: Path
) -> None:
    conversation_id = UUID(
        await run(sampler_binary, database_url, "init", "Write a file, patch it, and report the result.")
    )
    async with OpenAIResponses() as endpoint:
        command = (
            "advance",
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
            str(undeclared_outputs_dir() / "code-mode.log"),
            "--endpoint",
            endpoint.origin + "/v1/responses",
            "--model",
            "test-model",
        )
        first = asyncio.create_task(run(sampler_binary, database_url, *command))
        async with await endpoint.await_next_request() as exchange:
            assert exchange.request.code_mode
            await exchange.send(
                *response_stream(
                    [
                        Reasoning("opaque provider state", "opaque-test-reasoning"),
                        CustomToolCall(
                            "cell-test-1",
                            "exec",
                            'const shell = await tools.exec_command({cmd: "printf before > artifact.txt"}); text(shell); text(await tools.apply_patch("*** Begin Patch\\n*** Update File: artifact.txt\\n@@\\n-before\\n+after\\n*** End Patch")); text(await tools.exec_command({cmd: "cat artifact.txt"}));',
                        ),
                    ],
                    model="test-model",
                ).events
            )
        assert await first == "sample"
        # Each transition is a fresh OS process with a fresh upstream JS host, reading only Postgres.
        assert await run(sampler_binary, database_url, *command) == "cell"
        assert (tmp_path / "artifact.txt").read_text() == "after\n"
        third = asyncio.create_task(run(sampler_binary, database_url, *command))
        async with await endpoint.await_next_request() as exchange:
            assert exchange.request.reasoning[0].encrypted_content == "opaque-test-reasoning"
            (output,) = exchange.request.custom_tool_call_outputs
            assert output.call_id == "cell-test-1"
            assert "after" in str(output.output)
            await exchange.send(*response_stream([Message("PATCH_DONE")], model="test-model").events)
        assert await third == "sample"
        assert await run(sampler_binary, database_url, *command) == "done"
    async with postgres_async_engine(database_url) as engine:
        store = Store(engine)
        owner = await store.claim(conversation_id, lease=timedelta(seconds=30))
        row = await store.read(owner)
        assert row.pending is None
        assert row.items[-1]["content"][0]["text"] == "PATCH_DONE"
        async with store.sessions() as db:
            intents = (await db.scalars(select(Intent))).all()
            assert [intent.request["kind"] for intent in intents].count("tool") == 3
            assert all(intent.result is not None for intent in intents)


async def test_owner_fencing_and_unknown_intents(database_url: str) -> None:
    async with postgres_async_engine(database_url) as engine:
        async with engine.begin() as db:
            await db.run_sync(Base.metadata.create_all)
        first_store = Store(engine)
        conversation_id = await first_store.create("test")
        first = await first_store.claim(conversation_id, lease=timedelta(seconds=30))
        with pytest.raises(LostOwnershipError, match="live sampler"):
            await Store(engine).claim(conversation_id, lease=timedelta(seconds=30))
        intent_id = await first_store.begin(first, {"kind": "cell", "source": "mutating tool"})
        # Simulate lease expiry after a sampler crash, without sleeping through a production lease.
        async with first_store.sessions.begin() as db:
            await db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(lease_until=Conversation.lease_until - timedelta(minutes=1))
            )
        restarted = Store(engine)
        second = await restarted.claim(conversation_id, lease=timedelta(seconds=30))
        with pytest.raises(LostOwnershipError):
            await first_store.finish(first, intent_id, {}, [])
        with pytest.raises(LostOwnershipError):
            await first_store.record_nested(first, {"kind": "tool"})
        with pytest.raises(UnknownEffectError, match="unresolved cell"):
            await restarted.begin(second, {"kind": "sampling"})
        assert (await restarted.read(second)).pending == {"kind": "cell", "id": str(intent_id)}


async def test_real_effect_with_lost_reply_is_not_replayed(
    database_url: str, codex_binary: str, code_mode_host: str, executor_url: str, tmp_path: Path
) -> None:
    async with postgres_async_engine(database_url) as engine:
        async with engine.begin() as db:
            await db.run_sync(Base.metadata.create_all)
        store = Store(engine)
        conversation_id = await store.create("append one marker")
        owner = await store.claim(conversation_id, lease=timedelta(seconds=30))
        intent_id = await store.begin(owner, {"kind": "sampling"})
        call = {
            "type": "custom_tool_call",
            "name": "exec",
            "call_id": "lost-reply",
            "input": 'text(await tools.exec_command({cmd: "printf effect >> effect.txt"}));',
        }
        await store.finish(owner, intent_id, {"output": [call]}, [call])
        async with (
            drop_completed_process_reply(executor_url) as (proxy_url, dropped),
            ClientSession() as http,
            http.ws_connect(proxy_url) as socket,
        ):
            executor = Executor(socket, cwd=tmp_path, codex_path=codex_binary)
            executor.bind(store, owner)
            await executor.initialize()
            async with code_mode(
                code_mode_host, undeclared_outputs_dir() / "lost-reply.log", store, owner, executor
            ) as runtime:
                with pytest.raises(ConnectionError, match="remote effects may have occurred"):
                    await advance(
                        store,
                        owner,
                        runtime,
                        http,
                        endpoint="http://unused.invalid",
                        credential="test-key",
                        model="test-model",
                    )
            assert dropped.is_set()
        assert (tmp_path / "effect.txt").read_text() == "effect"
        await store.release(owner)
        restarted = Store(engine)
        successor = await restarted.claim(conversation_id, lease=timedelta(seconds=30))
        async with ClientSession() as http:
            with pytest.raises(UnknownEffectError, match="unresolved cell"):
                await advance(
                    restarted,
                    successor,
                    None,
                    http,
                    endpoint="http://unused.invalid",
                    credential="test-key",
                    model="test-model",
                )
        assert (tmp_path / "effect.txt").read_text() == "effect"
        async with restarted.sessions() as db:
            (nested,) = (
                await db.scalars(select(Intent).where(Intent.result.is_(None), Intent.request["kind"].astext == "tool"))
            ).all()
            assert nested.request["tool_name"]["name"] == "exec_command"


async def test_partial_provider_stream_never_dispatches_a_cell(database_url: str, tmp_path: Path) -> None:
    async with postgres_async_engine(database_url) as engine:
        async with engine.begin() as db:
            await db.run_sync(Base.metadata.create_all)
        store = Store(engine)
        conversation_id = await store.create("provider may disappear")
        owner = await store.claim(conversation_id, lease=timedelta(seconds=30))
        async with OpenAIResponses() as endpoint, ClientSession() as http:
            task = asyncio.create_task(
                advance(
                    store,
                    owner,
                    None,
                    http,
                    endpoint=endpoint.origin + "/v1/responses",
                    credential="test-key",
                    model="test-model",
                )
            )
            async with await endpoint.await_next_request() as exchange:
                await exchange.send(
                    *response_stream(
                        [
                            CustomToolCall(
                                "partial-call", "exec", 'text(await tools.exec_command({cmd: "touch forbidden"}));'
                            )
                        ],
                        model="test-model",
                    )
                    .through("response.output_item.done")
                    .events
                )
            with pytest.raises(ConnectionError, match="sampling outcome unknown"):
                await task
        row = await store.read(owner)
        assert row.pending is not None
        assert row.pending["kind"] == "sampling"
        assert len(row.items) == 1
        assert not (tmp_path / "forbidden").exists()


async def test_executor_death_preserves_pending_cell(
    database_url: str, codex_binary: str, code_mode_host: str, executor_server: ExecutorServer, tmp_path: Path
) -> None:
    async with postgres_async_engine(database_url) as engine:
        async with engine.begin() as db:
            await db.run_sync(Base.metadata.create_all)
        store = Store(engine)
        conversation_id = await store.create("executor may disappear")
        owner = await store.claim(conversation_id, lease=timedelta(seconds=30))
        intent_id = await store.begin(owner, {"kind": "sampling"})
        call = {
            "type": "custom_tool_call",
            "name": "exec",
            "call_id": "executor-death",
            "input": 'text(await tools.exec_command({cmd: "printf started; sleep 60"}));',
        }
        await store.finish(owner, intent_id, {"output": [call]}, [call])
        async with ClientSession() as http, http.ws_connect(executor_server.url) as socket:
            executor = ObservingExecutor(socket, cwd=tmp_path, codex_path=codex_binary)
            output = asyncio.Event()
            executor.observe_output(output)
            executor.bind(store, owner)
            await executor.initialize()
            async with code_mode(
                code_mode_host, undeclared_outputs_dir() / "executor-death.log", store, owner, executor
            ) as runtime:
                task = asyncio.create_task(
                    advance(
                        store,
                        owner,
                        runtime,
                        http,
                        endpoint="http://unused.invalid",
                        credential="test-key",
                        model="test-model",
                    )
                )
                async with asyncio.timeout(10):
                    await output.wait()
                executor_server.process.kill()
                await executor_server.process.wait()
                with pytest.raises(ConnectionError, match="remote effects may have occurred"):
                    await task
        # The sampler's DB connection and conversation survive the executor process's death.
        row = await store.read(owner)
        assert row.items[-1] == call
        assert row.pending is not None
        assert row.pending["kind"] == "cell"


async def test_sampler_sigkill_leaves_sampling_intent(database_url: str, sampler_binary: str, tmp_path: Path) -> None:
    conversation_id = UUID(await run(sampler_binary, database_url, "init", "sampler may disappear"))
    async with OpenAIResponses() as endpoint:
        process = await asyncio.create_subprocess_exec(
            sampler_binary,
            "--database-url",
            database_url,
            "advance",
            str(conversation_id),
            "--executor-url",
            "ws://127.0.0.1:1",
            "--executor-codex",
            "/unused/codex",
            "--code-mode-host",
            "/unused/host",
            "--cwd",
            str(tmp_path),
            "--logs",
            str(undeclared_outputs_dir() / "sigkill.log"),
            "--endpoint",
            endpoint.origin + "/v1/responses",
            "--model",
            "test-model",
            env={**os.environ, "SPIKE_MODEL_CREDENTIAL": "test-key"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        async with await endpoint.await_next_request():
            process.kill()
            await process.communicate()
        assert process.returncode == -9
    async with postgres_async_engine(database_url) as engine:
        store = Store(engine)
        async with store.sessions.begin() as db:
            await db.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id)
                .values(lease_until=Conversation.lease_until - timedelta(minutes=3))
            )
        successor = await store.claim(conversation_id, lease=timedelta(seconds=30))
        row = await store.read(successor)
        assert row.pending is not None
        assert row.pending["kind"] == "sampling"
        async with ClientSession() as http:
            with pytest.raises(UnknownEffectError, match="unresolved sampling"):
                await advance(
                    store,
                    successor,
                    None,
                    http,
                    endpoint="http://unused.invalid",
                    credential="test-key",
                    model="test-model",
                )


if __name__ == "__main__":
    pytest_bazel.main()
