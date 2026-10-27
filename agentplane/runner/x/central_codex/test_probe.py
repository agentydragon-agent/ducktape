"""Upstream usage spike; no production Gateway or Pod failure-domain claim."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
import pytest_bazel
from PIL import Image

from agentplane.native.codex.testing import model_catalog, responses_sse
from agentplane.native.codex.testing.model import MODEL
from agentplane.native.codex.testing.requests import InputImage, InputText, ResponsesRequest
from agentplane.native.codex.testing.responses import OpenAIResponses
from agentplane.runner.x.central_codex import probe
from util.bazel.runfiles import get_required_path


def output_text(request: ResponsesRequest) -> str:
    output = request.custom_tool_call_outputs[-1].output
    return output if isinstance(output, str) else "\n".join(part.text for part in output if isinstance(part, InputText))


async def test_remote_code_mode_and_executor_loss(tmp_path: Path, logs: Path, model: OpenAIResponses) -> None:
    model.serve_catalog([model_catalog.bundled("gpt-6-luna", slug=MODEL)])
    binary = str(get_required_path("agentplane_codex_cli_linux_x64/bin/codex"))
    central = tmp_path / "central"
    central.mkdir()
    workspace = tmp_path / "executor"
    workspace.mkdir()
    executor_home = workspace / "home"
    executor_home.mkdir()
    (workspace / "AGENTS.md").write_text("REMOTE_INSTRUCTION_SENTINEL: keep experiment artifacts here.\n")
    (workspace / "editable.txt").write_text("before\n")
    Image.new("RGB", (8, 8), "red").save(workspace / "remote.png")
    executor_env = {"HOME": str(executor_home), "PATH": os.environ["PATH"], "EXECUTOR_SENTINEL": "executor-only"}
    async with asyncio.timeout(60):
        async with probe.executor(binary, workspace, logs, executor_env) as (executor, upstream):
            async with probe.relay(upstream, logs / "executor-rpc.jsonl") as (relay, url):
                async with probe.sampler(binary, central, logs, model, url, "initial") as sampler:
                    thread = await probe.start_thread(sampler, workspace)
                    await probe.start_turn(sampler, thread, "Exercise remote tools, then report the result.")
                    async with await model.await_next_request() as exchange:
                        assert exchange.request.code_mode
                        assert "REMOTE_INSTRUCTION_SENTINEL" in exchange.request.model_dump_json()
                        await exchange.send(
                            *responses_sse.response_stream(
                                [
                                    responses_sse.CustomToolCall(
                                        "remote_shell",
                                        "exec",
                                        'const r = await tools.exec_command({cmd:"env", login:false}); text(r.output);',
                                    )
                                ],
                                model=MODEL,
                            ).events
                        )
                    async with await model.await_next_request() as exchange:
                        result = output_text(exchange.request)
                        assert "executor-only" in result
                        assert "sampler-only-test-key" not in result
                        assert "OPENAI_API_KEY=" not in result
                        patch = (
                            "*** Begin Patch\n*** Update File: "
                            + str(workspace / "editable.txt")
                            + "\n@@\n-before\n+after\n*** End Patch"
                        )
                        script = f"const r = await tools.apply_patch({json.dumps(patch)}); text(r);"
                        await exchange.send(
                            *responses_sse.response_stream(
                                [responses_sse.CustomToolCall("remote_patch", "exec", script)], model=MODEL
                            ).events
                        )
                    async with await model.await_next_request() as exchange:
                        assert (workspace / "editable.txt").read_text() == "after\n", output_text(exchange.request)
                        script = f"image(await tools.view_image({{path:{json.dumps(str(workspace / 'remote.png'))}}}));"
                        await exchange.send(
                            *responses_sse.response_stream(
                                [responses_sse.CustomToolCall("remote_image", "exec", script)], model=MODEL
                            ).events
                        )
                    async with await model.await_next_request() as exchange:
                        output = exchange.request.custom_tool_call_outputs[-1].output
                        assert isinstance(output, list), output
                        images = [part for part in output if isinstance(part, InputImage)]
                        assert len(images) == 1, output
                        assert images[0].image_url.startswith("data:image/png;base64,")
                        (logs / "image-output.json").write_text(exchange.request.model_dump_json(indent=2))
                        cursor = sampler.frames()
                        await exchange.send(
                            *responses_sse.response_stream(
                                [responses_sse.Message("REMOTE_TOOLS_DONE")], model=MODEL
                            ).events
                        )
                    while True:
                        frame = await cursor.next()
                        if frame.get("method") == "turn/completed":
                            assert frame["params"]["turn"]["status"] == "completed"
                            break
                    assert "process/start" in relay.methods
                    assert "fs/readFile" in relay.methods or "fs/open" in relay.methods
                    assert "fs/writeFile" in relay.methods or "fs/writeBlock" in relay.methods
                    reads = [
                        record["frame"]["params"]["path"]
                        for line in (logs / "executor-rpc.jsonl").read_text().splitlines()
                        if (record := json.loads(line))["direction"] == "request"
                        and record["frame"].get("method") == "fs/readFile"
                    ]
                    assert (workspace / "AGENTS.md").as_uri() in reads
                    assert (workspace / "remote.png").as_uri() in reads
                    lost_turn = await probe.start_turn(
                        sampler, thread, "Run one mutating command and report any executor failure without retrying it."
                    )
                    async with await model.await_next_request() as exchange:
                        script = '// @exec: {"yield_time_ms": 30000}\nconst r = await tools.exec_command({cmd:"echo $$ > effect.pid; printf x >> effects; printf EFFECT_COMMITTED; read -r blocked < hold", login:false, yield_time_ms:1000}); text(r);'
                        os.mkfifo(workspace / "hold")
                        await exchange.send(
                            *responses_sse.response_stream(
                                [responses_sse.CustomToolCall("uncertain_effect", "exec", script)], model=MODEL
                            ).events
                        )
                    await relay.effect_observed.wait()
                    executor.kill()
                    await executor.wait()
                    # Persistence is readable while the executor is gone, before answering another model request.
                    retained = await probe.rpc(sampler, "thread/read", threadId=thread, includeTurns=True)
                    assert "REMOTE_TOOLS_DONE" in json.dumps(retained)
                    async with await model.await_next_request() as exchange:
                        yielded = exchange.request.custom_tool_call_outputs[-1].output
                        assert isinstance(yielded, list)
                        assert isinstance(yielded[-1], InputText)
                        result = json.loads(yielded[-1].text)
                        assert result["session_id"] is not None
                        assert "EFFECT_COMMITTED" in result["output"]
                        # Polling an existing command is read-only; never resubmit its shell text.
                        script = (
                            '// @exec: {"yield_time_ms": 30000}\n'
                            + f'const r = await tools.write_stdin({{session_id:{result["session_id"]},chars:"",yield_time_ms:1000}}); text(r);'
                        )
                        await exchange.send(
                            *responses_sse.response_stream(
                                [responses_sse.CustomToolCall("observe_loss", "exec", script)], model=MODEL
                            ).events
                        )
                    async with await model.await_next_request() as exchange:
                        observed = output_text(exchange.request)
                        (logs / "loss-poll-output.txt").write_text(observed)
                        cursor = sampler.frames()
                        receipt = await probe.stop_for_executor_loss(
                            sampler,
                            thread_id=thread,
                            turn_id=lost_turn,
                            tool_call_id="uncertain_effect",
                            environment_id="remote-test",
                            journal=logs / "loss-receipt.json",
                        )
                        assert receipt.effects == "unknown"
                        await exchange.wait_client_closed()
                    while True:
                        frame = await cursor.next()
                        if frame.get("method") == "turn/completed":
                            assert frame["params"]["turn"]["status"] == "interrupted"
                            break
                    assert (workspace / "effects").read_text() == "x"
                    assert sampler.alive()
                    (logs / "retained-thread.json").write_text(
                        json.dumps(
                            await probe.rpc(sampler, "thread/read", threadId=thread, includeTurns=True), indent=2
                        )
                    )
                async with probe.sampler(binary, central, logs, model, url, "recovery") as recovered:
                    retained = await probe.rpc(recovered, "thread/read", threadId=thread, includeTurns=True)
                    assert "REMOTE_TOOLS_DONE" in json.dumps(retained)
                    assert retained["thread"]["turns"][-1]["status"] == "interrupted"
                    assert (
                        probe.LossReceipt.model_validate_json((logs / "loss-receipt.json").read_text()).effects
                        == "unknown"
                    )
                    assert (workspace / "effects").read_text() == "x"
                    with pytest.raises(TimeoutError):
                        async with asyncio.timeout(0.2):
                            await model.await_next_request()
    (logs / "methods.json").write_text(json.dumps(relay.methods, indent=2))


if __name__ == "__main__":
    pytest_bazel.main()
