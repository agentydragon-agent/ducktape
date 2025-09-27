"""MiniCodex agent on OpenAI Responses API with MCP tool wiring.

For stateless reasoning/tool replay demo, see :/adgn/examples/openai_api/stateless_two_step_demo.py
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
from typing import Any, TypeAlias, cast
import anyio

from mcp import types as mcp_types
from openai.types.shared_params import Reasoning as ReasoningParams, ReasoningEffort
from pydantic import BaseModel
from adgn.llm.openai_utils.model import (
    ResponsesRequest,
    InputTextPart,
    UserMessage,
    AssistantMessage,
    SystemMessage,
    ReasoningItem,
    FunctionCallItem,
    FunctionCallOutputItem,
    InputItem,
    ToolChoiceFunction,
    OpenAIModelProto,
)

from adgn.llm.mini_codex.approvals import TurnAbortRequested, ApprovalPolicyHandler
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
from adgn.llm.openai_utils.types import ReasoningSummary
from adgn.llm.openai_utils.model import (
    ReasoningOut,
    FunctionCallOut,
    AssistantResponseMessage,
)

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


Message: TypeAlias = UserMessage | AssistantMessage | SystemMessage | FunctionCallOutput
TranscriptItem: TypeAlias = Message | FunctionCallItem | ReasoningItem


class MiniCodex:
    def __init__(
        self,
        *,
        model: str,
        system: str | None,
        mcp: McpManager,
        client: OpenAIModelProto,
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
        self.pending_function_calls: list[FunctionCallItem] = []
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
        self._transcript.append(UserMessage.text(user_text))
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
        calls: list[tuple[FunctionCallItem, str | None]] = []
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
            # Detect FastMCP tool errors (server-side exceptions) explicitly
            is_err = bool(getattr(res, "isError", False))
            out_str = _responses_output_from_calltool(res)
            err = _extract_error_from_out_str(out_str)
            if is_err and not err:
                err = "MCP tool error"
            return out_str, err

        if self._parallel_tool_calls:
            await self._run_tool_calls_parallel(calls, function_calls, _invoke)
        else:
            await self._run_tool_calls_sequential(calls, function_calls, _invoke)
        self.pending_function_calls.clear()

    async def _run_tool_calls_parallel(self, calls, function_calls, invoker):
        results: dict[str, tuple[str, object] | str] = {}

        async def runner(fc: FunctionCallItem, aj: str | None):
            res = await invoker(fc, aj)
            results[fc.call_id] = res

        try:
            async with anyio.create_task_group() as tg:
                for function_call, args_json in calls:
                    tg.start_soon(runner, function_call, args_json)
        except TurnAbortRequested as e:
            # Task group cancelled siblings; emit completed tool outputs and
            # mark the denied call. Finish the turn.
            completed = {cid: results[cid] for cid in results}
            self._emit_batch_aborted_outputs(e.call_id, completed, function_calls)
            self.finished = True
            return

        # Success path: all tool calls completed and results collected
        out_map = results
        had_error = False
        for function_call in function_calls:
            out_str, err = out_map.get(
                function_call.call_id, (MISSING_OUTPUT_PAYLOAD, None)
            )
            self._emit_tool_result(function_call, out_str)
            if err:
                had_error = True
        if had_error:
            # Abort the turn when any MCP tool error occurs
            self.finished = True

    async def _run_tool_calls_sequential(self, calls, function_calls, invoker):
        for i, (function_call, args_json) in enumerate(calls):
            out_str, seq_error = await invoker(function_call, args_json)
            self._emit_tool_result(function_call, out_str)
            if seq_error:
                for remaining in function_calls[i + 1 :]:
                    self._emit_tool_result(remaining, ABORT_PAYLOAD)
                self.finished = True
                break

    def _to_openai_input_items(self) -> list[BaseModel]:
        """Convert transcript to typed OpenAI Responses input items."""
        items: list[BaseModel] = []
        for item in self._transcript:
            if isinstance(item, (UserMessage, AssistantMessage, SystemMessage)):
                items.append(item.model_copy(deep=True))
                continue
            if isinstance(item, ReasoningItem):
                items.append(item.model_copy(deep=True))
                continue
            if isinstance(item, FunctionCallItem):
                items.append(item.model_copy(deep=True))
                continue
            if isinstance(item, FunctionCallOutput):
                items.append(
                    FunctionCallOutputItem(call_id=item.call_id, output=item.output)
                )
                continue
            # Fallback: handle SDK input message items by duck-typing via model_dump
            if hasattr(item, "model_dump"):
                try:
                    d = item.model_dump(exclude_none=True)  # type: ignore[attr-defined]
                except Exception:
                    d = None
                if isinstance(d, dict):
                    role = d.get("role")
                    content = d.get("content")
                    if role in {"user", "assistant", "system"} and isinstance(
                        content, list
                    ):
                        parts: list[InputTextPart] = []
                        for p in content:
                            if isinstance(p, dict):
                                t = p.get("type")
                                text = p.get("text")
                                if t in {
                                    "input_text",
                                    "output_text",
                                    "text",
                                } and isinstance(text, str):
                                    parts.append(InputTextPart(text=text))
                        if role == "user":
                            items.append(UserMessage(content=parts))
                        elif role == "assistant":
                            items.append(AssistantMessage(content=parts))
                        else:
                            items.append(SystemMessage(content=parts))
                        continue
            # If we get here, it's an unsupported type
            raise TypeError(
                f"Unsupported transcript item for OpenAI input: {type(item)}"
            )
        return items

    async def _run_one_phase(self):
        decision = self._controller.on_before_sample()
        if isinstance(decision, Abort):
            self.finished = True
            return
        if isinstance(decision, Continue) and decision.skip_sampling:
            # Skip sampling: treat handler-provided inserts_input as if they were
            # model output items for this phase and process them via the normal
            # output path (adds assistant text, enqueues tool calls, etc.).
            out_items: list[
                ReasoningOut | FunctionCallOut | AssistantResponseMessage
            ] = []
            for it in list(decision.inserts_input):
                if isinstance(
                    it, (ReasoningOut, FunctionCallOut, AssistantResponseMessage)
                ):
                    out_items.append(it)
                elif isinstance(it, FunctionCallItem):
                    out_items.append(FunctionCallOut.from_input_item(it))
                else:
                    raise TypeError(
                        f"Unsupported skip_sampling inserts_input item type: {type(it).__name__}"
                    )
            resp_output = out_items
        elif isinstance(decision, Continue):
            # Inject any handler-provided pre-sample inserts into transcript
            self._transcript.extend(decision.inserts_input)
            snap = await self._mcp.sampling_snapshot()
            raw_tc = _tool_choice_from_policy(decision.tool_policy)
            if (
                isinstance(raw_tc, dict)
                and raw_tc.get("type") == "function"
                and isinstance(raw_tc.get("name"), str)
            ):
                tool_choice_typed: str | ToolChoiceFunction = ToolChoiceFunction(
                    name=raw_tc["name"]
                )  # type: ignore[assignment]
            else:
                tool_choice_typed = cast(str, raw_tc)
            reasoning_param: ReasoningParams | None = None
            if self._reasoning_effort or self._reasoning_summary:
                reasoning_param = cast(
                    ReasoningParams,
                    {
                        "effort": self._reasoning_effort,
                        "summary": self._reasoning_summary,
                    },
                )
            req = ResponsesRequest(
                input=self._to_openai_input_items(),
                instructions=await self._build_effective_instructions(),
                stream=False,
                tool_choice=tool_choice_typed,  # type: ignore[arg-type]
                store=True,
                parallel_tool_calls=self._parallel_tool_calls,
                tools=[t.model_dump(exclude_none=True) for t in snap.tools],
                reasoning=reasoning_param,
            )
            resp = await self._client.responses_create(req)
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
        if resp_output is not None:
            self._process_resp_output(resp_output)
        if not self.pending_function_calls:
            self.finished = True

    def _process_resp_output(
        self,
        resp_output: list[ReasoningOut | FunctionCallOut | AssistantResponseMessage],
    ) -> None:
        self.pending_function_calls.clear()
        # Skip items that are already present in our transcript (id collision).
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
            iid = getattr(item, "id", None)
            if isinstance(iid, str) and iid in existing_ids:
                continue
            if isinstance(item, ReasoningOut):
                ri = item.to_input_item()
                self._controller.on_reasoning(item)
                self._transcript.append(ri)
            elif isinstance(item, AssistantResponseMessage):
                text = item.text
                self.assistant_text_chunks.append(text)
                self._controller.on_assistant_text(AssistantText(text=text))  # type: ignore[arg-type]
                # Store assistant as our input item type to avoid secondary translation
                self._transcript.append(item.to_input_item())
            elif isinstance(item, FunctionCallOut):
                # If we already produced a local output for this call_id, this is an invalid state — fail loud
                if item.call_id in handled_cids:
                    raise AssertionError(f"Duplicate {item.call_id = }")
                fc_local = item.to_input_item()
                self.pending_function_calls.append(fc_local)
                self._controller.on_tool_call(
                    ToolCall(
                        name=item.name, args_json=item.arguments, call_id=item.call_id
                    )
                )
                self._transcript.append(fc_local)
            else:
                # Crash fast on unknown items to surface mismatches early
                raise TypeError(f"Unsupported Responses output item: {type(item)}")

    @classmethod
    async def create(
        cls,
        *,
        model: str,
        mcp: McpManager,
        handlers: Iterable[BaseHandler],
        client: OpenAIModelProto,
        system: str | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        reasoning_summary: ReasoningSummary | None = None,
        parallel_tool_calls: bool = True,
        # Optional approval plumbing: when provided, we will prepend an ApprovalPolicyHandler
        approval_engine: "ApprovalPolicyEngine | None" = None,
        approval_hub: "ApprovalHub | None" = None,
    ) -> MiniCodex:
        print(f"[MiniCodex.create] client_type={type(client)}")
        # Optionally inject ApprovalPolicyHandler at the front of the handlers chain
        handlers_list = list(handlers)
        if approval_engine is not None and approval_hub is not None:
            handlers_list = [
                ApprovalPolicyHandler(approval_engine, approval_hub),
                *handlers_list,
            ]
        return cls(
            model=model,
            system=system,
            mcp=mcp,
            client=client,
            reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary,
            parallel_tool_calls=parallel_tool_calls,
            handlers=handlers_list,
        )

    def _emit_tool_result(
        self,
        function_call: FunctionCallItem,
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
        function_calls: list[FunctionCallItem],
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
    def messages(self) -> list[InputItem]:
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
        fco_map: dict[str, str] = {
            evt.call_id: evt.output
            for evt in self._transcript
            if isinstance(evt, FunctionCallOutput)
        }
        out: list[InputItem] = []
        for item in self._transcript:
            if isinstance(item, FunctionCallItem):
                out.append(item)
                cid = item.call_id
                if cid and cid in fco_map:
                    out.append(FunctionCallOutputItem(call_id=cid, output=fco_map[cid]))
            elif isinstance(item, (UserMessage, AssistantMessage, SystemMessage)):
                out.append(item.model_copy(deep=True))
            elif isinstance(item, ReasoningItem):
                out.append(item)
            elif isinstance(item, FunctionCallOutput):
                # already emitted alongside its function_call
                continue
            else:
                raise TypeError(f"Unsupported transcript item type: {type(item)!r}")
        return out

    async def __aenter__(self) -> MiniCodex:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None
