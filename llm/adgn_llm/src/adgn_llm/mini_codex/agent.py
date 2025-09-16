"""MiniCodex agent on OpenAI Responses API with MCP tool wiring."""
# Example demos: see examples/stateless_two_step_demo.py for a concise stateless reasoning/tool replay demo

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from adgn_llm.mini_codex.approvals import TurnAbortRequested
from adgn_llm.mini_codex.handler import (
    AbortTurnDecision,
    AssistantText,
    BeforeToolCallDecision,
    BypassToolInjectOutput,
    ContinueDecision,
    FunctionCallOutput,
    GroundTruthUsage,
    Response,
    ToolCall,
    UserText,
)
from adgn_llm.mini_codex.loop_control import Abort
from adgn_llm.mini_codex.loop_control import Auto as TP_Auto
from adgn_llm.mini_codex.loop_control import Continue
from adgn_llm.mini_codex.loop_control import Forbid as TP_Forbid
from adgn_llm.mini_codex.loop_control import RequireAny as TP_RequireAny
from adgn_llm.mini_codex.loop_control import RequireSpecific as TP_RequireSpecific
from adgn_llm.mini_codex.loop_control import SyntheticAction
from adgn_llm.mini_codex.loop_control import ToolPolicy as TP_Base
from adgn_llm.openai_retry import retry_decorator
from adgn_llm.openai_utils import ReasoningSummary
from mcp import types as mcp_types
from openai.resources.responses import AsyncResponses
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
)
from openai.types.shared_params import Reasoning as ReasoningParams
from openai.types.shared_params import ReasoningEffort
from pydantic import BaseModel

from .aggregating_handler import AggregatingController, BaseHandler
from .mcp_manager import McpManager


@dataclass
class AgentResult:
    text: str
    # NOTE: We intentionally do NOT return transcript/events in agent result.
    # Tests or callers that need access to the event sequence should register a handler
    # (e.g. a test-only RecordingHandler) and pass it via `handlers` argument to MiniCodex.create().


def _responses_output_from_calltool(res: Any) -> str:
    assert isinstance(res, mcp_types.CallToolResult), f"Unsupported tool result: {type(res)!r}"
    if res.structuredContent:
        return json.dumps(res.structuredContent)
    return json.dumps({"content": [b.model_dump(by_alias=True) for b in (res.content or [])]})


# Namespaced tool form: mcp__{server}__{tool}
ToolMap = dict[str, Any]

SYSTEM_INSTRUCTIONS = "You are a code agent. Be concise."


def _tool_choice_from_policy(policy: TP_Base) -> str | dict[str, Any]:
    """Map a ToolPolicy to Responses API tool_choice value.

    Exhaustive and strict: raises on unknown policy; RequireSpecific supports exactly one name.
    """
    if isinstance(policy, TP_RequireAny):
        return "required"
    if isinstance(policy, TP_Auto):
        return "auto"
    if isinstance(policy, TP_Forbid):
        return "none"
    if isinstance(policy, TP_RequireSpecific):
        if len(policy.names) == 1:
            return {"type": "function", "name": policy.names[0]}
        raise ValueError("RequireSpecific with multiple names is not supported for Responses.tool_choice")
    raise TypeError(f"Unknown ToolPolicy: {type(policy).__name__}")


class ResponsesClient(Protocol):
    @property
    def responses(self) -> AsyncResponses:  # pragma: no cover - structural protocol
        ...


@retry_decorator()
async def _responses_create_with_retry(client: ResponsesClient, **kwargs: Any):
    """Wrapper around client.responses.create with retry for transient errors.

    Instrumentation: append a compact summary of the outgoing kwargs to
    ./scratch/responses_payload_debug.json to aid debugging of invalid Requests
    returned by the upstream OpenAI Responses API. The summary focuses on the
    'input' list and reasoning/tool metadata and uses json.dumps(default=str)
    to avoid serialization failures.
    """
    dump = {
        "ts": time.time(),
        "model": kwargs.get("model"),
        "instructions": kwargs.get("instructions"),
        "tool_choice": kwargs.get("tool_choice"),
        "parallel_tool_calls": kwargs.get("parallel_tool_calls"),
        "reasoning": kwargs.get("reasoning"),
    }
    # Attempt to capture the 'input' payload (usually a list of dicts)
    try:
        dump["input"] = kwargs.get("input")
    except Exception:
        dump["input"] = repr(kwargs.get("input"))
    # Summarize tools list if present
    tools = kwargs.get("tools")
    if isinstance(tools, (list, tuple)):
        dump["tools"] = [t.get("name") if isinstance(t, dict) else str(t) for t in tools]
    else:
        dump["tools"] = str(tools)

    p = Path("./scratch/responses_payload_debug.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(dump, default=str) + "\n")

    return await client.responses.create(**kwargs)


class UserMessage(BaseModel):
    role: Literal["user"]
    content: str


class AssistantMessage(BaseModel):
    role: Literal["assistant"]
    content: str


Message = UserMessage | AssistantMessage | FunctionCallOutput
TranscriptItem = Message | ResponseFunctionToolCall | ResponseReasoningItem


class MiniCodex:
    def __init__(  # noqa: PLR0913
        self,
        *,
        model: str,
        system: str | None,
        mcp: McpManager,
        client: ResponsesClient,
        reasoning_effort: ReasoningEffort | None = None,
        reasoning_summary: ReasoningSummary | None = None,
        parallel_tool_calls: bool,
        handlers: Iterable[BaseHandler],
    ) -> None:
        self._model = model
        self._default_system = system or SYSTEM_INSTRUCTIONS
        self._system = self._default_system
        self._mcp = mcp
        self._client = client
        self._parallel_tool_calls = parallel_tool_calls
        self._transcript: list[TranscriptItem] = []
        self._reasoning_effort = reasoning_effort
        self._reasoning_summary = reasoning_summary
        # Aggregating controller (owns handlers and loop-decision semantics)
        handlers_list = list(handlers)
        if not handlers_list:
            raise ValueError("MiniCodex requires at least one handler; add AutoHandler() or a control handler")
        self._controller = AggregatingController(handlers_list)

    def set_system_instructions(self, instructions: str | None) -> None:
        """Override base system instructions for future turns."""
        self._system = (instructions or self._default_system).strip()

    async def _build_effective_instructions(self) -> str:
        """Compose effective system instructions with an MCP banner.

        - Summarizes available resources per server (first 5 URIs per server)
        - Appends per-server initialize instructions when available
        """
        instructions = self._system
        if banner := await self._mcp.render_banner():
            instructions += f"\n\n{banner}"
        return instructions

    async def run(self, user_text: str) -> AgentResult:
        self._transcript.append(UserMessage(role="user", content=user_text))
        self._controller.on_user_text(UserText(text=user_text))

        assistant_text_chunks: list[str] = []
        # Use the agent-owned aggregating controller (handlers provide loop control)
        controller = self._controller

        while True:
            input_payload = self.messages

            reasoning_kwargs: dict[str, Any] = {}
            if self._reasoning_effort is not None or self._reasoning_summary is not None:
                reasoning_kwargs = {
                    "reasoning": cast(
                        ReasoningParams,
                        {
                            "effort": self._reasoning_effort,
                            "summary": self._reasoning_summary,
                        },
                    ),
                }

            # Determine tool choice via controller
            decision = controller.on_before_sample()
            if isinstance(decision, Abort):
                break
            if isinstance(decision, SyntheticAction):
                # SyntheticAction path: use controller-provided outputs and skip LLM
                resp_output = decision.outputs
            elif isinstance(decision, Continue):
                resp = await _responses_create_with_retry(
                    self._client,
                    model=self._model,
                    input=input_payload,
                    instructions=await self._build_effective_instructions(),
                    stream=False,
                    tool_choice=_tool_choice_from_policy(decision.tool_policy),
                    store=True,
                    parallel_tool_calls=self._parallel_tool_calls,
                    tools=(await self._mcp.list_tools()),
                    **reasoning_kwargs,
                )
                # Emit a typed Response event with ground-truth usage (tests must populate usage)
                # DEBUG DUMP: write a compact summary of resp.output to aid troubleshooting
                try:
                    out_items = []
                    for it in getattr(resp, "output", []) or []:
                        try:
                            dump = it.model_dump(exclude_none=True)
                        except Exception:
                            dump = repr(it)
                        out_items.append({"type": type(it).__name__, "dump": dump})
                    p = Path("./scratch/last_resp_debug.json")
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(json.dumps({"output": out_items}, default=str), encoding="utf-8")
                except Exception:
                    pass
                u = resp.usage
                self._controller.on_response(
                    Response(
                        response_id=resp.id,
                        usage=GroundTruthUsage(
                            model=self._model,
                            input_tokens=u.input_tokens,
                            output_tokens=u.output_tokens,
                            total_tokens=u.total_tokens,
                        ),
                        model=self._model,
                    )
                )
                resp_output = resp.output
            else:
                raise TypeError(f"Unsupported loop decision: {type(decision).__name__}")

            function_calls: list[ResponseFunctionToolCall] = []
            for item in resp_output:
                if isinstance(item, ResponseReasoningItem):
                    # Store typed SDK reasoning item (output-only); include it in the
                    # transcript so the next turn's `input` contains the reasoning
                    # items the Responses API requires when function_call items are
                    # present.
                    self._transcript.append(item)
                    self._controller.on_reasoning(item)
                    continue
                elif isinstance(item, ResponseOutputMessage):
                    parts = [part.text for part in item.content if isinstance(part, ResponseOutputText) and part.text]
                    combined = "\n".join(parts)
                    assistant_text_chunks.append(combined)
                    msg = AssistantMessage(role="assistant", content=combined)
                    self._transcript.append(msg)
                    self._controller.on_assistant_text(AssistantText(text=combined))
                elif isinstance(item, ResponseFunctionToolCall):
                    function_calls.append(item)
                    # Persist typed SDK tool call for next-turn input serialization
                    self._transcript.append(item)
                    try:
                        args = json.loads(item.arguments) if item.arguments else {}
                    except Exception:
                        args = {"_raw": item.arguments} if item.arguments is not None else {}
                    self._controller.on_tool_call(
                        ToolCall(
                            name=item.name or "",
                            args=args if isinstance(args, dict) else {},
                            call_id=item.call_id or "",
                        )
                    )

            if not function_calls:
                break

            calls: list[tuple[ResponseFunctionToolCall, dict[str, Any]]] = []
            for function_call in function_calls:
                args = json.loads(function_call.arguments) if function_call.arguments else {}
                if not isinstance(args, dict):
                    args = {}
                calls.append((function_call, args))

            # Build a per-turn map of locally-produced function_call_output by call_id
            local_fco_map: dict[str, str] = {
                evt.call_id: evt.output for evt in self._transcript if isinstance(evt, FunctionCallOutput)
            }

            async def _invoke(function_call: ResponseFunctionToolCall, args: dict[str, Any]) -> tuple[str, str | None]:
                # Pre-invocation handler: allow controllers/handlers to intercept the call
                # Build a ToolCall event for handlers
                tc = ToolCall(
                    name=function_call.name or "",
                    args=args if isinstance(args, dict) else {},
                    call_id=function_call.call_id or "",
                )

                # Ask handlers for a before-tool-call decision (may be None)
                decision: BeforeToolCallDecision | None = await self._controller.on_before_tool_call(tc)

                # Handlers MUST return a BeforeToolCallDecision (no None). Act on it directly.

                # Abort the turn explicitly
                if isinstance(decision, AbortTurnDecision):
                    raise TurnAbortRequested(
                        call_id=function_call.call_id or "",
                        reason=decision.reason or "handler_requested_abort",
                    )

                # Inject a provided CallToolResult without executing the real tool
                if isinstance(decision, BypassToolInjectOutput):
                    res = decision.result
                    # Enforce non-nullability at runtime (paranoid check)
                    if res is None:
                        raise TypeError("BypassToolInjectOutput.result must be a CallToolResult instance")
                    out_str = _responses_output_from_calltool(res)
                    parsed_error = None
                    try:
                        data = json.loads(out_str)
                        if isinstance(data, dict) and data.get("ok") is False and isinstance(data.get("error"), str):
                            parsed_error = data.get("error")
                    except Exception:
                        parsed_error = None
                    return out_str, parsed_error

                if not isinstance(decision, ContinueDecision):
                    # Unknown decision type -> crash
                    raise RuntimeError(f"Unknown before-tool-call decision type: {type(decision).__name__}")

                # If we already executed this tool locally and have a FunctionCallOutput,
                # prefer the local output rather than calling the MCP session (avoids unknown server slots).
                cid = function_call.call_id
                if cid and cid in local_fco_map:
                    out_str = local_fco_map[cid]
                    parsed_error = None
                    try:
                        data = json.loads(out_str)
                        if isinstance(data, dict) and data.get("ok") is False and isinstance(data.get("error"), str):
                            parsed_error = data.get("error")
                    except Exception:
                        parsed_error = None
                    return out_str, parsed_error

                # Execute the real tool
                res = await self._mcp.call_tool(function_call.name, args)
                out_str = _responses_output_from_calltool(res)
                parsed_error = None
                try:
                    data = json.loads(out_str)
                    if isinstance(data, dict) and data.get("ok") is False and isinstance(data.get("error"), str):
                        parsed_error = data.get("error")
                except Exception:
                    parsed_error = None
                return out_str, parsed_error

            # Branch behavior based on parallel_tool_calls
            if self._parallel_tool_calls:
                # Parallel execution: create tasks for each _invoke so we can react to
                # control-plane exceptions (TurnAbortRequested) immediately.
                task_to_call: dict[asyncio.Task, ResponseFunctionToolCall] = {}
                for function_call, args in calls:
                    t = asyncio.create_task(_invoke(function_call, args))
                    task_to_call[t] = function_call

                # Wait until either all complete or the first exception is raised
                done, pending = await asyncio.wait(task_to_call.keys(), return_when=asyncio.FIRST_EXCEPTION)

                # Check for exception among completed
                first_exc: BaseException | None = None
                for t in done:
                    if t.cancelled():
                        continue
                    if exc := t.exception():
                        first_exc = exc
                        break

                if first_exc is None:
                    # All tasks completed successfully; emit outputs in original order
                    results = [t.result() for t in task_to_call.keys()]
                    out_map: dict[str, tuple[str, str | None]] = {
                        function_call.call_id: res for (function_call, _), res in zip(calls, results)
                    }
                    for function_call in function_calls:
                        out_str, parsed_error = out_map.get(
                            function_call.call_id,
                            (
                                json.dumps({"ok": False, "error": "missing tool output"}),
                                None,
                            ),
                        )
                        self._emit_tool_result(function_call, out_str)
                    # Continue to next loop iteration
                else:
                    # An exception occurred in one of the tasks
                    # Cancel pending tasks first
                    for t in pending:
                        t.cancel()
                    # Gather pending to silence cancellation
                    await asyncio.gather(*pending, return_exceptions=True)

                    # If it's a TurnAbortRequested, synthesize outputs accordingly
                    if isinstance(first_exc, TurnAbortRequested):
                        denied_call_id = first_exc.call_id
                        # Build a map of completed task results
                        completed_results: dict[str, tuple[str, str | None]] = {}
                        for t in done:
                            if t is None or t.cancelled():
                                continue
                            if t is t and t.exception() is first_exc:
                                # skip the task that raised
                                continue
                            try:
                                res = t.result()
                            except Exception:
                                continue
                            fc = task_to_call.get(t)
                            if fc:
                                completed_results[fc.call_id] = res

                        # Emit outputs in original order: completed -> real outputs; denied -> user-denied; pending -> turn aborted
                        for function_call in function_calls:
                            if function_call.call_id in completed_results:
                                out_str, parsed_error = completed_results[function_call.call_id]
                                self._emit_tool_result(function_call, out_str)
                                continue
                            if function_call.call_id == denied_call_id:
                                deny_payload = json.dumps(
                                    {
                                        "ok": False,
                                        "error": f"User denied: {denied_call_id}",
                                    }
                                )
                                self._emit_tool_result(function_call, deny_payload)
                                continue
                            # remaining calls were not run
                            abort_payload = json.dumps({"ok": False, "error": "turn aborted"})
                            self._emit_tool_result(function_call, abort_payload)

                        # End the turn after synthetic emissions
                        break
                    else:
                        # Unexpected exception: re-raise to surface the bug
                        raise first_exc
            else:
                # Sequential execution: call tools one by one via the same per-call invoker
                # so handlers' before_tool_call decisions are applied consistently.
                for i, function_call in enumerate(function_calls):
                    args = json.loads(function_call.arguments) if function_call.arguments else {}
                    if not isinstance(args, dict):
                        args = {}

                    # Use the common _invoke coroutine (applies before_tool_call) to get output
                    out_str, seq_error = await _invoke(function_call, args)

                    self._emit_tool_result(function_call, out_str)

                    # If this call was explicitly denied (by handler raising TurnAbortRequested
                    # or by injected/structured error), synthesize abort outputs for remaining calls
                    if seq_error and "User denied" in seq_error:
                        for remaining in function_calls[i + 1 :]:
                            abort_payload = json.dumps({"ok": False, "error": "turn aborted"})
                            self._emit_tool_result(remaining, abort_payload)
                        break

        text = "\n".join(assistant_text_chunks)

        # Do not return transcript/events from AgentResult. Tests needing the
        # event sequence should register a RecordingHandler and pass it via
        # `handlers` to MiniCodex.create().
        return AgentResult(text=text)

    @classmethod
    async def create(
        cls,
        *,
        model: str,
        mcp: McpManager,
        handlers: Iterable[BaseHandler],
        client: ResponsesClient,
        system: str | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        reasoning_summary: ReasoningSummary | None = None,
        parallel_tool_calls: bool = True,
    ) -> MiniCodex:
        return cls(
            model=model,
            system=system,
            mcp=mcp,
            client=client,
            reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary,
            parallel_tool_calls=parallel_tool_calls,
            handlers=handlers,
        )

    def _emit_tool_result(self, function_call: ResponseFunctionToolCall, out_str: str) -> None:
        """Emit a single typed function_call_output event (no duplicates)."""
        fco = FunctionCallOutput(call_id=function_call.call_id, output=out_str)
        self._transcript.append(fco)
        self._controller.on_function_call_output(fco)

    def _emit_aborted_outputs(
        self,
        denied_call_id: str | None,
        completed_results: dict[str, tuple[str, str | None]],
        function_calls: list[ResponseFunctionToolCall],
    ) -> None:
        """Emit outputs for a batch when an abort/denial occurs.

        - completed_results: mapping call_id -> (out_str, parsed_error) for calls that already completed
        - denied_call_id: the call_id that was explicitly denied (may be None)
        - function_calls: original ordered list to preserve emission order
        """
        for function_call in function_calls:
            cid = function_call.call_id
            if cid in completed_results:
                out_str, _ = completed_results[cid]
                self._emit_tool_result(function_call, out_str)
                continue
            if denied_call_id is not None and cid == denied_call_id:
                deny_payload = json.dumps({"ok": False, "error": f"User denied: {denied_call_id}"})
                self._emit_tool_result(function_call, deny_payload)
                continue
            # remaining calls were not executed
            abort_payload = json.dumps({"ok": False, "error": "turn aborted"})
            self._emit_tool_result(function_call, abort_payload)

    @property
    def messages(self) -> list[dict[str, Any]]:
        """Format transcript for OpenAI Responses API.

        Summary of our reasoning handling (stateless, full-input):
        - We forward the exact ResponseReasoningItem objects returned by the model
          in-order as part of the transcript when continuing the model's chain-of-thought.
        - We do NOT synthesize or mutate reasoning items or ids; always forward the
          SDK-returned objects (model_dump(exclude_none=True)).
        - We avoid previous_response_id / stateful Responses API usage by design and
          therefore reproduce the full input sequence (user/assistant/reasoning/
          function_call/function_call_output) on each stateless request.
        - Reasoning forwarding is orthogonal to tool execution: include reasoning
          items where they were produced to allow the model to continue reasoning.

        Recommended/required practices:
        - Preserve ordering and structure exactly as returned by the SDK/API.
        - Do not fabricate rs_/fc_ ids; prefer omission over synthesis if originals
          are missing.

        Canonical references:
        - OpenAI Responses API reference: https://platform.openai.com/docs/api-reference/responses
        - OpenAI Cookbook examples (reasoning items & function-call orchestration):
          https://github.com/openai/openai-cookbook/blob/main/examples/responses_api/reasoning_items.ipynb
          https://github.com/openai/openai-cookbook/blob/main/examples/reasoning_function_calls.ipynb

        Implementation note: this agent intentionally uses the stateless full-input
        approach to preserve reproducibility and avoid server-side state. Keep this
        behavior in mind when modifying messages()/transcript serialization.
        """
        # Build a map of locally-emitted function_call_output by call_id (these are produced by local tool execution)
        fco_map: dict[str, str] = {}
        for evt in self._transcript:
            if isinstance(evt, FunctionCallOutput):
                fco_map[evt.call_id] = evt.output

        out: list[dict[str, Any]] = []

        # Only include reasoning items when there exists at least one function_call
        # in the transcript that does NOT yet have a corresponding function_call_output.
        include_reasoning = any(
            isinstance(evt, ResponseFunctionToolCall) and getattr(evt, "call_id", None) and evt.call_id not in fco_map
            for evt in self._transcript
        )

        for item in self._transcript:
            if not isinstance(item, BaseModel):
                raise TypeError(f"Unsupported transcript item type: {type(item)!r}")

            # Include reasoning items only when they are still relevant for pending function_call handling
            if isinstance(item, ResponseReasoningItem):
                if include_reasoning:
                    out.append(item.model_dump(exclude_none=True))
                continue

            # If this is a function_call and we have a locally-produced function_call_output
            # for the same call_id, include both in the input so the server sees the function_call
            # and its tool output produced by us (local execution).
            if isinstance(item, ResponseFunctionToolCall):
                fc_dict = item.model_dump(exclude_none=True)
                # Ensure a corresponding reasoning item is present when replaying
                # a function_call into the next request. The Responses API expects a
                # 'reasoning' item with id 'rs_<hex>' paired with a function_call
                # id 'fc_<hex>'. If missing, synthesize a minimal SDK reasoning
                # item so the API accepts the input.
                try:
                    fc_id = fc_dict.get("id") or fc_dict.get("call_id")
                    if isinstance(fc_id, str) and fc_id.startswith("fc_"):
                        rs_id = "rs_" + fc_id[len("fc_") :]
                        has_rs = any(
                            isinstance(evt, ResponseReasoningItem) and getattr(evt, "id", None) == rs_id
                            for evt in self._transcript
                        )
                        if not has_rs:
                            # Construct a minimal SDK reasoning item and include it
                            rs_item = ResponseReasoningItem(id=rs_id, summary=[], type="reasoning", content=[])
                            out.append(rs_item.model_dump(exclude_none=True))
                except Exception:
                    # Best-effort only; fall back to sending the function_call as-is
                    pass

                out.append(fc_dict)
                cid = fc_dict.get("call_id")
                if cid and cid in fco_map:
                    # Append function_call_output object for the same call_id
                    out.append(
                        {
                            "type": "function_call_output",
                            "call_id": cid,
                            "output": fco_map[cid],
                        }
                    )
                continue

            # Default: user/assistant and other message types
            out.append(item.model_dump(exclude_none=True))

        return out

    async def __aenter__(self) -> "MiniCodex":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None
