"""One durable sampling or code-cell transition; no rollout files or Runner journal."""

import json
from typing import Any

from aiohttp import ClientSession

from agentplane.x.postgres_codex.code_mode import CodeMode, tool_definitions
from agentplane.x.postgres_codex.store import Owner, Store, UnknownEffectError


def request_body(model: str, conversation_id: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    description = (
        "Run raw JavaScript as an async module in a fresh V8 isolate. Call tools.exec_command({cmd, workdir?}) "
        "or tools.apply_patch(patch). Emit results with text(value). No Node, filesystem, network or console. "
        "exec_command supports tty and yield_time_ms; a running process returns session_id. "
        "Use tools.write_stdin({session_id, chars?, eof?, yield_time_ms?}) to send input or poll. "
        'An exec first-line // @exec: {"yield_time_ms": 10} yields an active JS cell; '
        "call wait with JSON {cell_id, yield_time_ms?, terminate?} to observe it. "
        "Process session_id and JavaScript cell_id are distinct. No notify or persistent JS store. Await all tool calls. "
        + json.dumps(tool_definitions())
    )
    return {
        "model": model,
        "input": [
            {
                "type": "additional_tools",
                "role": "developer",
                "tools": [
                    {"type": "custom", "name": "exec", "description": description, "format": {"type": "text"}},
                    {
                        "type": "custom",
                        "name": "wait",
                        "description": "Observe a yielded JavaScript cell. Input JSON: {cell_id, yield_time_ms?, terminate?}.",
                        "format": {"type": "text"},
                    },
                ],
            },
            *items,
        ],
        "stream": True,
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "prompt_cache_key": conversation_id,
        "client_metadata": {"session_id": conversation_id, "thread_id": conversation_id, "turn_id": conversation_id},
    }


async def sample(http: ClientSession, endpoint: str, credential: str, body: dict[str, Any]) -> dict[str, Any]:
    """Require the provider terminal event; never continue from partially streamed items."""
    async with http.post(
        endpoint,
        json=body,
        headers={"Authorization": f"Bearer {credential}", "x-openai-internal-codex-responses-lite": "true"},
    ) as response:
        response.raise_for_status()
        data: list[str] = []
        async for line_bytes in response.content:
            line = line_bytes.decode().rstrip("\r\n")
            if line.startswith("data:"):
                data.append(line[5:].lstrip())
            elif not line and data:
                event = json.loads("\n".join(data))
                data.clear()
                if event["type"] == "response.completed":
                    terminal: dict[str, Any] = event["response"]
                    if terminal["status"] != "completed":
                        raise ValueError(f"unexpected terminal status: {terminal['status']}")
                    return terminal
                if event["type"] in {"response.failed", "response.incomplete", "error"}:
                    raise RuntimeError(event)
    raise ConnectionError("provider stream ended without response.completed; sampling outcome unknown")


def pending_call(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    completed = {item["call_id"] for item in items if item["type"] == "custom_tool_call_output"}
    return next(
        (item for item in items if item["type"] == "custom_tool_call" and item["call_id"] not in completed), None
    )


async def advance(
    store: Store,
    owner: Owner,
    runtime: CodeMode | None,
    http: ClientSession,
    *,
    endpoint: str,
    credential: str,
    model: str,
) -> str:
    row = await store.read(owner)
    if row.pending is not None:
        raise UnknownEffectError(f"unresolved {row.pending['kind']} intent {row.pending['id']}; no automatic replay")
    if row.stopped:
        return "interrupted"
    await store.check_live_cells(owner, runtime_available=runtime is not None)
    if runtime is not None and runtime.error is not None:
        raise runtime.error
    if (call := pending_call(row.items)) is not None:
        if call["name"] not in {"exec", "wait"}:
            raise ValueError(f"unsupported model tool: {call['name']}")
        if runtime is None:
            raise ValueError("a pending cell requires a code-mode runtime")
        intent_id = await store.begin(owner, {"kind": "cell", "call": call})
        output = await runtime.execute(call)
        result = {"type": "custom_tool_call_output", "call_id": call["call_id"], "output": output}
        await store.finish(owner, intent_id, result, [result])
        return "cell"
    if row.items[-1]["type"] == "message" and row.items[-1]["role"] == "assistant":
        return "done"
    state = await store.execution_state(owner)
    context = row.items
    if state["processes"] or state["cells"]:
        context = [
            *context,
            {"type": "message", "role": "developer", "content": "Current execution state: " + json.dumps(state)},
        ]
    body = request_body(model, str(row.id), context)
    intent_id = await store.begin(owner, {"kind": "sampling", "body": body})
    result = await sample(http, endpoint, credential, body)
    for item in result["output"]:
        if item["type"] not in {"message", "reasoning", "custom_tool_call"}:
            raise ValueError(f"unsupported provider output type: {item['type']}")
    # Provider items, including opaque reasoning and unknown fields, remain intact in JSONB.
    await store.finish(owner, intent_id, result, result["output"])
    return "sample"
