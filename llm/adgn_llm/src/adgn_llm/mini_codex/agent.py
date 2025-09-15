"""MiniCodex agent on OpenAI Responses API with MCP tool wiring."""

from __future__ import annotations
import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast
from mcp import types as mcp_types
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
)
import asyncio
from openai.types.shared_params import Reasoning as ReasoningParams, ReasoningEffort
from pydantic import BaseModel
from openai.resources.responses import AsyncResponses
from adgn_llm.openai_retry import retry_decorator
from adgn_llm.openai_utils import ReasoningSummary
from .mcp_manager import McpManager
from .approvals import TurnAbortRequested
from adgn_llm.mini_codex.loop_control import (
    Auto as TP_Auto,
    RequireAny as TP_RequireAny,
    Forbid as TP_Forbid,
    RequireSpecific as TP_RequireSpecific,
    ToolPolicy as TP_Base,
    Continue,
    Abort,
    SyntheticAction,
)
from .aggregating_handler import AggregatingController, BaseHandler
from adgn_llm.mini_codex.handler import (
    UserText,
    AssistantText,
    ToolCall,
    FunctionCallOutput,
    Response,
    GroundTruthUsage,
)


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
    """Wrapper around client.responses.create with retry for transient errors."""
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
                    # Store typed SDK reasoning item (output-only; filtered from next-turn input)
                    self._transcript.append(item)
                    self._controller.on_reasoning(item)
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

            async def _invoke(function_call: ResponseFunctionToolCall, args: dict[str, Any]) -> tuple[str, str | None]:
                # Namespaced MCP tool
                out_str = _responses_output_from_calltool(await self._mcp.call_tool(function_call.name, args))
                parsed_error: str | None = None
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
                    exc = t.exception()
                    if exc is not None:
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
                            function_call.call_id, (json.dumps({"ok": False, "error": "missing tool output"}), None)
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
                                deny_payload = json.dumps({"ok": False, "error": f"User denied: {denied_call_id}"})
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
                # Sequential execution: call tools one by one. If a denial/error occurs for
                # a call (e.g., approvals wrapper returns structured error with "User denied"),
                # emit that call's output then synthesize "turn aborted" outputs for remaining
                # call_ids in the batch, and end the turn.
                for i, function_call in enumerate(function_calls):
                    args = json.loads(function_call.arguments) if function_call.arguments else {}
                    if not isinstance(args, dict):
                        args = {}

                    # Execute the call sequentially and get its output/result
                    res = await self._mcp.call_tool(function_call.name, args)
                    out_str = _responses_output_from_calltool(res)

                    seq_error: str | None = None
                    try:
                        data = json.loads(out_str)
                        if isinstance(data, dict) and data.get("ok") is False and isinstance(data.get("error"), str):
                            seq_error = data.get("error")
                    except Exception:
                        seq_error = None

                    self._emit_tool_result(function_call, out_str)

                    # If this call was explicitly denied, synthesize abort outputs for remaining calls
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

        Accepts a mixed list of:
        - message dicts {"role": "user"|"assistant", "content": str}
        - function_call (typed SDK item) and function_call_output items
        Note: Reasoning items are output-only and are NOT included in input. We always send
        the full transcript each turn; do not send deltas.
        """
        out: list[dict[str, Any]] = []
        for item in self._transcript:
            # Filter out reasoning items (output-only)
            if isinstance(item, ResponseReasoningItem):
                continue
            # Include function_call items so the API can match subsequent
            # function_call_output by call_id (required for bootstrap and parallel tools).
            # The service ignores them as content; they establish the tool call context.
            # See Responses API tool orchestration examples in the OpenAI Cookbook.
            # (We still filter out reasoning items above.)
            # if isinstance(item, ResponseFunctionToolCall):
            #     continue
            if not isinstance(item, BaseModel):
                # We only persist typed SDK objects (BaseModel) in the transcript
                raise TypeError(f"Unsupported transcript item type: {type(item)!r}")
            out.append(item.model_dump(exclude_none=True))
        return out

    async def __aenter__(self) -> "MiniCodex":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None
