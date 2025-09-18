"""MiniCodex agent on OpenAI Responses API with MCP tool wiring."""

# Example demos: see :/adgn/examples/openai_api/stateless_two_step_demo.py for a concise stateless reasoning/tool replay demo

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
import json
from typing import Any, Literal, Protocol, TypeAlias, cast

from mcp import types as mcp_types
from openai.resources.responses import AsyncResponses
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseReasoningItem,
)
from openai.types.shared_params import Reasoning as ReasoningParams, ReasoningEffort
from pydantic import BaseModel

from adgn.llm.mini_codex.approvals import TurnAbortRequested
from adgn.llm.mini_codex.handler import (
    AbortTurnDecision,
    AssistantText,
    BypassToolInjectOutput,
    ContinueDecision,
    FunctionCallOutput,
    GroundTruthUsage,
    Response,
    ToolCall,
    UserText,
)
from adgn.llm.mini_codex.loop_control import (
    Abort,
    Auto as TP_Auto,
    Continue,
    Forbid as TP_Forbid,
    RequireAny as TP_RequireAny,
    RequireSpecific as TP_RequireSpecific,
    ToolPolicy as TP_Base,
)
from adgn.llm.openai_retry import retry_decorator
from adgn.llm.openai_utils.types import ReasoningSummary

from .aggregating_handler import Reducer, BaseHandler
from .mcp_manager import McpManager


@dataclass
class AgentResult:
    text: str
    # NOTE: We intentionally do NOT return transcript/events in agent result.
    # Tests or callers that need access to the event sequence should register a handler
    # (e.g. a test-only RecordingHandler) and pass it via `handlers` argument to MiniCodex.create().


def _responses_output_from_calltool(res: mcp_types.CallToolResult) -> str:
    assert isinstance(res, mcp_types.CallToolResult)
    # 1) Preferred: servers return structuredContent; pass it through as JSON string
    if res.structuredContent:
        return json.dumps(res.structuredContent)
    # 2) If there is exactly one TextContent block, emit its text directly (no duck typing on dicts)
    content = res.content or []
    if len(content) == 1 and isinstance(content[0], mcp_types.TextContent):  # type: ignore[attr-defined]
        txt = content[0].text  # type: ignore[union-attr]
        if isinstance(txt, str):
            return txt
    # 3) Otherwise, fall back to a JSON object that preserves the blocks
    return json.dumps({"content": [c.model_dump(by_alias=True) for c in content]})


def _extract_error_from_out_str(out_str: str) -> str | None:
    """Parse a tool output string and return error message if ok==False.

    Expects JSON object with keys {"ok": bool, "error": str}. Returns the
    error string when found; otherwise None. Safe on non-JSON inputs.
    """
    try:
        data = json.loads(out_str)
    except Exception:
        return None
    if isinstance(data, dict) and data.get("ok") is False:
        err = data.get("error")
        if isinstance(err, str):
            return err
    return None


# Common payload helpers
ABORT_PAYLOAD = json.dumps({"ok": False, "error": "turn aborted"})
MISSING_OUTPUT_PAYLOAD = json.dumps({"ok": False, "error": "missing tool output"})


def _deny_payload(call_id: str) -> str:
    return json.dumps({"ok": False, "error": f"User denied: {call_id}"})


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
        raise ValueError(
            "RequireSpecific with multiple names is not supported for Responses.tool_choice",
        )
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


class SystemMessage(BaseModel):
    role: Literal["system"]
    content: str


Message: TypeAlias = UserMessage | AssistantMessage | SystemMessage | FunctionCallOutput
TranscriptItem: TypeAlias = Message | ResponseFunctionToolCall | ResponseReasoningItem


class MiniCodex:
    def __init__(
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
        # Agent state fields
        self.assistant_text_chunks: list[str] = []
        self.pending_function_calls: list[ResponseFunctionToolCall] = []
        self.finished: bool = False
        # Aggregating controller (owns handlers and loop-decision semantics)
        handlers_list = list(handlers)
        assert handlers_list, (
            "At least one handler required; add AutoHandler() or a control handler"
        )
        self._controller = Reducer(handlers_list)

    def set_system_instructions(self, instructions: str | None) -> None:
        """Override base system instructions for future turns."""
        self._system = (instructions or self._default_system).strip()

    async def _build_effective_instructions(self) -> str:
        """Compose effective system instructions with an MCP banner derived from structured snapshot.

        View/prompt rendering remains here; McpManager only returns structured data.
        """
        instructions = self._system
        snap = await self._mcp.sampling_snapshot()  # structured (servers, tools)
        lines: list[str] = []
        for s in snap.servers:
            if s.state != "running":
                continue
            name = s.name
            init = s.initialize
            desc = init.instructions if init else None
            entry = f"server={name}"
            if desc:
                # Keep brief; avoid flooding the header
                snippet = desc.strip().splitlines()
                if snippet:
                    entry += f"\n  <{name} server desc>\n{snippet[0]}\n  </{name} server desc>"
            lines.append(entry)
        if lines:
            banner = "FYI: MCP servers:\n- " + "\n- ".join(lines)
            instructions += f"\n\n{banner}"
        return instructions

    async def run(self, user_text: str) -> AgentResult:
        self._transcript.append(UserMessage(role="user", content=user_text))
        self._controller.on_user_text(UserText(text=user_text))  # type: ignore[arg-type]
        self.assistant_text_chunks.clear()
        self.pending_function_calls.clear()
        self.finished = False
        try:
            while not self.finished:
                # Pre-phase inserts now handled by handlers via Continue.inserts_input
                await self._run_one_phase()
                if self.pending_function_calls:
                    await self._handle_pending_tool_calls()
            return AgentResult(text="\n".join(self.assistant_text_chunks))
        except Exception as exc:
            self._controller.on_error(exc)
            raise

    async def _handle_pending_tool_calls(self):
        function_calls = self.pending_function_calls
        calls: list[tuple[ResponseFunctionToolCall, str | None]] = []
        for function_call in function_calls:
            calls.append((function_call, function_call.arguments))

        local_fco_map = {
            evt.call_id: evt.output
            for evt in self._transcript
            if isinstance(evt, FunctionCallOutput)
        }

        async def _invoke(function_call, args_json, local_fco_map=local_fco_map):
            tc = ToolCall(
                name=function_call.name,
                args_json=args_json,
                call_id=function_call.call_id,
            )
            decision = await self._controller.on_before_tool_call(tc)
            if isinstance(decision, AbortTurnDecision):
                raise TurnAbortRequested(
                    call_id=function_call.call_id,
                    reason=decision.reason or "handler_requested_abort",
                )
            if isinstance(decision, BypassToolInjectOutput):
                out_str = _responses_output_from_calltool(decision.result)
                return out_str, _extract_error_from_out_str(out_str)
            if not isinstance(decision, ContinueDecision):
                raise RuntimeError(
                    f"Unknown before-tool decision: {type(decision).__name__}"
                )
            cid = function_call.call_id
            if cid in local_fco_map:
                out_str = local_fco_map[cid]
                return out_str, _extract_error_from_out_str(out_str)
            res = await self._mcp.call_tool_namespaced(function_call.name, args_json)
            out_str = _responses_output_from_calltool(res)
            return out_str, _extract_error_from_out_str(out_str)

        if self._parallel_tool_calls:
            await self._run_tool_calls_parallel(calls, function_calls, _invoke)
        else:
            await self._run_tool_calls_sequential(calls, function_calls, _invoke)
        self.pending_function_calls.clear()

    async def _run_tool_calls_parallel(self, calls, function_calls, invoker):
        task_to_call = {}
        for function_call, args_json in calls:
            t = asyncio.create_task(invoker(function_call, args_json))
            task_to_call[t] = function_call
        done, pending = await asyncio.wait(
            task_to_call.keys(), return_when=asyncio.FIRST_EXCEPTION
        )
        first_exc = None
        for t in done:
            if t.cancelled():
                continue
            if exc := t.exception():
                first_exc = exc
                break
        if not first_exc:
            results = [t.result() for t in task_to_call]
            out_map = {
                function_call.call_id: res
                for (function_call, _), res in zip(calls, results, strict=False)
            }
            for function_call in function_calls:
                out_str, _ = out_map.get(
                    function_call.call_id,
                    (MISSING_OUTPUT_PAYLOAD, None),
                )
                self._emit_tool_result(function_call, out_str)
            return
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if not isinstance(first_exc, TurnAbortRequested):
            raise first_exc
        denied_call_id = first_exc.call_id
        completed_results = {}
        for t in done:
            if not t or t.cancelled() or t.exception() is first_exc:
                continue
            if (fc := task_to_call.get(t)) is not None:
                completed_results[fc.call_id] = t.result()
        self._emit_batch_aborted_outputs(
            denied_call_id, completed_results, function_calls
        )
        self.finished = True

    async def _run_tool_calls_sequential(self, calls, function_calls, invoker):
        for i, (function_call, args_json) in enumerate(calls):
            out_str, seq_error = await invoker(function_call, args_json)
            self._emit_tool_result(function_call, out_str)
            if seq_error and "User denied" in seq_error:
                for remaining in function_calls[i + 1 :]:
                    self._emit_tool_result(remaining, ABORT_PAYLOAD)
                self.finished = True
                break

    async def _run_one_phase(self):
        reasoning_kwargs = {}
        if self._reasoning_effort or self._reasoning_summary:
            reasoning_kwargs["reasoning"] = cast(
                ReasoningParams,
                {"effort": self._reasoning_effort, "summary": self._reasoning_summary},
            )
        decision = self._controller.on_before_sample()
        if isinstance(decision, Abort):
            self.finished = True
            return
        if isinstance(decision, Continue) and getattr(decision, "skip_sampling", False):
            # Treat inserts_input as the model's output for this phase
            resp_output = list(getattr(decision, "inserts_input", ()))
        elif isinstance(decision, Continue):
            # Inject any handler-provided pre-sample inserts into transcript
            self._transcript.extend(decision.inserts_input)
            snap = await self._mcp.sampling_snapshot()
            resp = await _responses_create_with_retry(
                self._client,
                model=self._model,
                input=self.messages,
                instructions=await self._build_effective_instructions(),
                stream=False,
                tool_choice=_tool_choice_from_policy(decision.tool_policy),
                store=True,
                parallel_tool_calls=self._parallel_tool_calls,
                tools=[t.model_dump(exclude_none=True) for t in snap.tools],
                **reasoning_kwargs,
            )
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
                ),
            )  # type: ignore[arg-type]
            resp_output = resp.output
        else:
            raise TypeError(f"Unsupported loop decision: {type(decision).__name__}")
        self._process_resp_output(resp_output)
        if not self.pending_function_calls:
            self.finished = True

    def _process_resp_output(self, resp_output: list[TranscriptItem]) -> None:
        self.pending_function_calls.clear()
        # Skip items that are already present in our transcript (id collision).
        # Some mocks or servers may reuse ids across calls; prefer idempotent processing.
        existing_ids: set[str] = set()
        for evt in self._transcript:
            if isinstance(evt, BaseModel):
                eid = getattr(evt, "id", None)
                if isinstance(eid, str) and eid:
                    existing_ids.add(eid)
        handled_cids = {
            evt.call_id
            for evt in self._transcript
            if isinstance(evt, FunctionCallOutput)
        }
        for item in resp_output:
            # If this item has an id and we've already recorded it, skip
            if isinstance(item, BaseModel):
                iid = getattr(item, "id", None)
                if isinstance(iid, str) and iid in existing_ids:
                    continue
            if isinstance(item, ResponseReasoningItem):
                self._controller.on_reasoning(item)  # type: ignore[arg-type]
            elif isinstance(item, ResponseOutputMessage):
                text = "\n".join(
                    part.text
                    for part in item.content
                    if isinstance(part, ResponseOutputText)
                )
                self.assistant_text_chunks.append(text)
                self._controller.on_assistant_text(AssistantText(text=text))  # type: ignore[arg-type]
            elif isinstance(item, ResponseFunctionToolCall):
                # If we already produced a local output for this call_id, this is an invalid state — fail loud
                if item.call_id in handled_cids:
                    raise AssertionError(f"Duplicate {item.call_id = }")
                self.pending_function_calls.append(item)
                self._controller.on_tool_call(
                    ToolCall(
                        name=item.name, args_json=item.arguments, call_id=item.call_id
                    )
                )
            else:
                raise TypeError(f"Unsupported Responses output item: {type(item)}")
            self._transcript.append(item)

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

    def _emit_tool_result(
        self,
        function_call: ResponseFunctionToolCall,
        out_str: str,
    ) -> None:
        """Emit a single typed function_call_output event (no duplicates)."""
        fco = FunctionCallOutput(call_id=function_call.call_id, output=out_str)
        self._transcript.append(fco)
        self._controller.on_function_call_output(fco)  # type: ignore[arg-type]

    def _emit_batch_aborted_outputs(
        self,
        denied_call_id: str | None,
        completed_results: dict[str, tuple[str, object] | str],
        function_calls: list[ResponseFunctionToolCall],
    ) -> None:
        for function_call in function_calls:
            cid = function_call.call_id
            if cid in completed_results:
                res = completed_results[cid]
                out_str = res[0] if isinstance(res, tuple) else str(res)
                self._emit_tool_result(function_call, out_str)
                continue
            if denied_call_id and cid == denied_call_id:
                self._emit_tool_result(function_call, _deny_payload(denied_call_id))
                continue
            self._emit_tool_result(function_call, ABORT_PAYLOAD)

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

        # Always forward reasoning items and the full transcript in-order. The Responses
        # API requires that reasoning items be replayed in the exact local context the
        # model produced them in; we preserve ordering and do NOT synthesize missing items.
        for item in self._transcript:
            if not isinstance(item, BaseModel):
                raise TypeError(f"Unsupported transcript item type: {type(item)!r}")

            # If this is a function_call, include it; if we have a locally produced
            # function_call_output for the same call_id, append it immediately after.
            if isinstance(item, ResponseFunctionToolCall):
                fc_dict = item.model_dump(exclude_none=True)
                out.append(fc_dict)
                cid = fc_dict.get("call_id")
                if cid and cid in fco_map:
                    out.append(
                        {
                            "type": "function_call_output",
                            "call_id": cid,
                            "output": fco_map[cid],
                        },
                    )
                continue

            # Default: user/assistant and other message types
            # Forward reasoning items as-is (do not gate or synthesize)
            out.append(item.model_dump(exclude_none=True))

        return out

    async def __aenter__(self) -> MiniCodex:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None
