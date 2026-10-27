"""Explicit remote Responses v2 compaction of model context, never audit history."""

import json
from typing import Any

from aiohttp import ClientSession

from agentplane.x.postgres_codex.responses import request_body, sample
from agentplane.x.postgres_codex.store import Owner, Store, UnknownEffectError


def check_pairs(items: list[dict[str, Any]]) -> None:
    pending: set[str] = set()
    seen: set[str] = set()
    for item in items:
        if item["type"] == "custom_tool_call":
            call_id = item["call_id"]
            if call_id in seen:
                raise UnknownEffectError(f"duplicate tool call {call_id}")
            seen.add(call_id)
            pending.add(call_id)
        elif item["type"] == "custom_tool_call_output":
            call_id = item["call_id"]
            if call_id not in pending:
                raise UnknownEffectError(f"orphan tool output {call_id}")
            pending.remove(call_id)
    if pending:
        raise UnknownEffectError(f"unresolved tool calls {sorted(pending)}")


def context_bytes(items: list[dict[str, Any]]) -> int:
    """A deterministic payload-size check, not a tokenizer or context-window estimate."""
    return len(json.dumps(items, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


async def compact(
    store: Store, owner: Owner, http: ClientSession, *, endpoint: str, credential: str, model: str
) -> None:
    execution_state = await store.execution_state(owner)
    if execution_state["cells"]:
        raise UnknownEffectError("cannot compact over live JavaScript cells")
    row = await store.read(owner)
    check_pairs(row.items)
    original = row.context()
    check_pairs(original)
    body = request_body(model, str(row.id), original, instructions=row.instructions, execution_state=execution_state)
    body["input"].append({"type": "compaction_trigger"})
    intent_id = await store.begin_compaction(owner, {"kind": "compaction", "body": body}, original)
    result = await sample(http, endpoint, credential, body, compaction=True)
    if len(result.output) != 1 or result.output[0]["type"] != "compaction":
        raise ValueError("compaction must produce exactly one compaction item and no tools")
    if not isinstance(result.output[0].get("encrypted_content"), str) or not result.output[0]["encrypted_content"]:
        raise ValueError("compaction must include opaque encrypted_content")
    if context_bytes(result.output) >= context_bytes(original):
        raise ValueError("compaction did not reduce serialized model context")
    await store.finish_compaction(owner, intent_id, result.audit(), original, result.output)
