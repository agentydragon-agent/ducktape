"""MiniCodex agent on OpenAI Responses API with MCP tool wiring.

For stateless reasoning/tool replay demo, see :/adgn/examples/openai_api/stateless_two_step_demo.py
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
from typing import Any, TypeAlias, TYPE_CHECKING, cast
import anyio

from mcp import types as mcp_types
from pydantic import BaseModel
from adgn.llm.openai_utils.model import (
    ResponsesRequest,
    UserMessage,
    AssistantMessage,
    SystemMessage,
    ReasoningItem,
    FunctionCallItem,
    FunctionCallOutputItem,
    FunctionCallOutputOut,
    InputItem,
    ToolChoice,
    ToolChoiceFunction,
    OpenAIModelProto,
    ReasoningEffort,
    ReasoningOut,
    FunctionCallOut,
    AssistantMessageOut,
)

from adgn.llm.mini_codex.approvals import ApprovalPolicyHandler
from adgn.llm.mini_codex.handler import (
    AbortTurnDecision,
    AssistantText,
    BypassToolInjectOutput,
    ContinueDecision,
    GroundTruthUsage,
    Response,
    ToolCall,
    ToolCallOutput,
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
from adgn.llm.openai_utils.types import ReasoningSummary, build_reasoning_params

from .aggregating_handler import Reducer, BaseHandler
from .mcp_manager import McpManager

if TYPE_CHECKING:
    from adgn.llm.mini_codex.approvals import ApprovalPolicyEngine, ApprovalHub


@dataclass
class AgentResult:
    text: str
    # NOTE: We intentionally do NOT return transcript/events in agent result.
    # Tests or callers that need access to the event sequence should register a handler
    # (e.g. a test-only RecordingHandler) and pass it via `handlers` argument to MiniCodex.create().


@dataclass(slots=True)
class ToolCallSuccess:
    """Successful MCP tool invocation."""

    result: mcp_types.CallToolResult


@dataclass(slots=True)
class ToolCallFailure:
    """MCP invocation failed; carries the structured tool result."""

    result: mcp_types.CallToolResult
    reason: str | None = None


@dataclass(slots=True)
class ToolCallAborted:
    """Invocation aborted (policy/UI); embeds synthetic structured error."""

    result: mcp_types.CallToolResult
    reason: str | None = None


ToolCallOutcome = ToolCallSuccess | ToolCallFailure | ToolCallAborted


def _copy_result(res: mcp_types.CallToolResult) -> mcp_types.CallToolResult:
    """Return a deep copy of a CallToolResult to avoid downstream mutation."""

    return res.model_copy(deep=True)


def _require_call_id(function_call: FunctionCallItem) -> str:
    call_id = function_call.call_id
    if not isinstance(call_id, str) or not call_id:
        raise RuntimeError("FunctionCallItem missing call_id")
    return call_id


def _dump_call_tool_result(
    res: mcp_types.CallToolResult, tool_call_info: str | None = None
) -> str:
    """Serialize an MCP CallToolResult to a JSON string for Responses input."""

    data = res.model_dump(mode="json", exclude_none=True)
    result = json.dumps(data)

    # Safety check: OpenAI has a 10MB limit for input strings
    # Fail fast if tool output is too large to prevent API errors
    MAX_SIZE = 10 * 1024 * 1024  # 10MB
    if len(result) > MAX_SIZE:
        error_msg = (
            f"Tool output too large: {len(result) / (1024 * 1024):.1f}MB "
            f"exceeds max {MAX_SIZE / (1024 * 1024):.0f}MB. "
        )
        if tool_call_info:
            error_msg += f" Tool call: {tool_call_info}."
        error_msg += " MCP server returned oversized result - check slicing/pagination."
        raise RuntimeError(error_msg)

    return result


def _maybe_error_message(res: mcp_types.CallToolResult) -> str | None:
    if not res.isError:
        return None
    structured = res.structuredContent
    if isinstance(structured, dict):
        err = structured.get("error")
        if isinstance(err, str) and err:
            return err
    for block in res.content or []:
        text = getattr(block, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return None


def _make_error_result(message: str) -> mcp_types.CallToolResult:
    return mcp_types.CallToolResult(
        content=[], structuredContent={"ok": False, "error": message}, isError=True
    )


DEFAULT_ABORT_ERROR = "tool execution aborted"


def _abort_result(reason: str | None = None) -> mcp_types.CallToolResult:
    return _make_error_result(reason or DEFAULT_ABORT_ERROR)


def _normalize_call_arguments(arguments: Any) -> str | None:
    if arguments is None or isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments)
    except TypeError:
        return str(arguments)


def _call_tool_result_from_json(output: str) -> mcp_types.CallToolResult:
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ValueError("invalid CallToolResult JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("CallToolResult JSON must be an object")
    if data.get("content") is None:
        data["content"] = []
    return mcp_types.CallToolResult.model_validate(data)


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


Message: TypeAlias = UserMessage | AssistantMessage | SystemMessage
TranscriptItem: TypeAlias = Message | FunctionCallItem | ReasoningItem | ToolCallOutput


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
        # Track function calls for debugging
        self._function_call_map: dict[str, FunctionCallItem] = {}
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

    async def _handle_pending_tool_calls(self) -> None:
        function_calls: list[FunctionCallItem] = list(self.pending_function_calls)
        calls: list[tuple[FunctionCallItem, str | None]] = [
            (function_call, _normalize_call_arguments(function_call.arguments))
            for function_call in function_calls
        ]

        local_result_map: dict[str, mcp_types.CallToolResult] = {
            evt.call_id: evt.result
            for evt in self._transcript
            if isinstance(evt, ToolCallOutput)
        }

        async def _invoke(
            function_call: FunctionCallItem,
            args_json: str | None,
            local_map: dict[str, mcp_types.CallToolResult] = local_result_map,
        ) -> ToolCallOutcome:
            cid = _require_call_id(function_call)
            tc = ToolCall(name=function_call.name, args_json=args_json, call_id=cid)
            decision = await self._controller.on_before_tool_call(tc)
            if isinstance(decision, AbortTurnDecision):
                failure = _make_error_result(decision.reason or DEFAULT_ABORT_ERROR)
                return ToolCallAborted(result=failure, reason=decision.reason)
            if isinstance(decision, BypassToolInjectOutput):
                res = _copy_result(decision.result)
                if res.isError:
                    return ToolCallFailure(result=res, reason=_maybe_error_message(res))
                return ToolCallSuccess(result=res)
            if not isinstance(decision, ContinueDecision):
                raise RuntimeError(
                    f"Unknown before-tool decision: {type(decision).__name__}"
                )
            if cid in local_map:
                cached = _copy_result(local_map[cid])
                if cached.isError:
                    return ToolCallFailure(
                        result=cached, reason=_maybe_error_message(cached)
                    )
                return ToolCallSuccess(result=cached)

            raw = await self._mcp.call_tool_namespaced(function_call.name, args_json)
            if not isinstance(raw, mcp_types.CallToolResult):
                raise TypeError(
                    f"Expected CallToolResult from MCP, got {type(raw).__name__}"
                )
            res = _copy_result(raw)
            if res.isError:
                return ToolCallFailure(result=res, reason=_maybe_error_message(res))
            return ToolCallSuccess(result=res)

        if self._parallel_tool_calls:
            await self._run_tool_calls_parallel(calls, function_calls, _invoke)
        else:
            await self._run_tool_calls_sequential(calls, function_calls, _invoke)
        self.pending_function_calls.clear()

    async def _run_tool_calls_parallel(
        self,
        calls: list[tuple[FunctionCallItem, str | None]],
        function_calls: list[FunctionCallItem],
        invoker,
    ) -> None:
        results: dict[str, ToolCallOutcome] = {}
        abort_triggered = False

        async with anyio.create_task_group() as tg:
            cancelled_exc = anyio.get_cancelled_exc_class()

            async def runner(fc: FunctionCallItem, aj: str | None) -> None:
                nonlocal abort_triggered
                try:
                    outcome = await invoker(fc, aj)
                except cancelled_exc:
                    return
                except Exception as exc:
                    cid = _require_call_id(fc)
                    failure = _make_error_result(f"internal error: {exc}")
                    results[cid] = ToolCallFailure(result=failure, reason=str(exc))
                    abort_triggered = True
                    tg.cancel_scope.cancel()
                    return
                cid = _require_call_id(fc)
                results[cid] = outcome
                if isinstance(outcome, ToolCallAborted):
                    abort_triggered = True
                    tg.cancel_scope.cancel()

            for function_call, args_json in calls:
                tg.start_soon(runner, function_call, args_json)

        had_error = False
        for function_call in function_calls:
            cid = _require_call_id(function_call)
            outcome = results.get(cid)
            if outcome is None:
                if not abort_triggered:
                    raise RuntimeError(f"Missing tool output for call_id={cid!r}")
                outcome = ToolCallAborted(result=_abort_result())
            self._emit_tool_result(function_call, outcome.result)
            if isinstance(outcome, (ToolCallFailure, ToolCallAborted)):
                had_error = True
        if had_error:
            self.finished = True

    async def _run_tool_calls_sequential(
        self,
        calls: list[tuple[FunctionCallItem, str | None]],
        function_calls: list[FunctionCallItem],
        invoker,
    ) -> None:
        for i, (function_call, args_json) in enumerate(calls):
            outcome = await invoker(function_call, args_json)
            self._emit_tool_result(function_call, outcome.result)
            if isinstance(outcome, (ToolCallFailure, ToolCallAborted)):
                for remaining in function_calls[i + 1 :]:
                    self._emit_tool_result(remaining, _abort_result())
                self.finished = True
                break

    def _to_openai_input_items(self) -> list[InputItem]:
        """Convert transcript to typed OpenAI Responses input items."""
        items: list[InputItem] = []
        for item in self._transcript:
            if isinstance(item, (UserMessage, AssistantMessage, SystemMessage)):
                items.append(item.model_copy(deep=True))
                continue
            if isinstance(item, ReasoningItem):
                items.append(item)
                continue
            if isinstance(item, FunctionCallItem):
                items.append(item)
                continue
            if isinstance(item, ToolCallOutput):
                # Look up the function call from our map for debugging info
                tool_info = f"call_id={item.call_id}"
                if item.call_id in self._function_call_map:
                    fc = self._function_call_map[item.call_id]
                    tool_info = f"{fc.name}(call_id={item.call_id})"

                items.append(
                    FunctionCallOutputItem(
                        call_id=item.call_id,
                        output=_dump_call_tool_result(item.result, tool_info),
                    )
                )
                continue
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
            out_items: list[ReasoningOut | FunctionCallOut | AssistantMessageOut] = []
            for it in list(decision.inserts_input):
                if isinstance(it, (ReasoningOut, FunctionCallOut, AssistantMessageOut)):
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
                tool_choice_typed: ToolChoice = ToolChoiceFunction(name=raw_tc["name"])
            else:
                tool_choice_typed = cast(ToolChoice, raw_tc)

            reasoning_param = build_reasoning_params(
                self._reasoning_effort, self._reasoning_summary
            )
            req = ResponsesRequest(
                input=self._to_openai_input_items(),
                instructions=await self._build_effective_instructions(),
                stream=False,
                tool_choice=tool_choice_typed,
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
        resp_output: list[ReasoningOut | FunctionCallOut | AssistantMessageOut],
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
            evt.call_id for evt in self._transcript if isinstance(evt, ToolCallOutput)
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
            elif isinstance(item, AssistantMessageOut):
                text = item.text
                self.assistant_text_chunks.append(text)
                self._controller.on_assistant_text(AssistantText(text=text))
                # Store assistant as our input item type to avoid secondary translation
                self._transcript.append(item.to_input_item())
            elif isinstance(item, FunctionCallOutputOut):
                try:
                    result = _call_tool_result_from_json(item.output)
                except Exception as exc:  # pragma: no cover - defensive
                    raise ValueError(
                        f"Failed to parse CallToolResult for call_id={item.call_id}"
                    ) from exc
                event = ToolCallOutput(call_id=item.call_id, result=result)
                handled_cids.add(item.call_id)
                self._controller.on_tool_result(event)
                self._transcript.append(event)
                if self.pending_function_calls:
                    self.pending_function_calls = [
                        fc
                        for fc in self.pending_function_calls
                        if fc.call_id != item.call_id
                    ]
            elif isinstance(item, FunctionCallOut):
                fc_local = item.to_input_item()
                self._controller.on_tool_call(
                    ToolCall(
                        name=item.name, args_json=item.arguments, call_id=item.call_id
                    )
                )
                self._transcript.append(fc_local)
                # Store in map for quick lookup when processing outputs
                self._function_call_map[fc_local.call_id] = fc_local
                if item.call_id in handled_cids:
                    continue
                self.pending_function_calls.append(fc_local)
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
        result: mcp_types.CallToolResult,
    ) -> None:
        """Emit a ToolCallOutput event and notify handlers."""

        call_id = _require_call_id(function_call)
        event = ToolCallOutput(call_id=call_id, result=_copy_result(result))
        self._transcript.append(event)
        self._controller.on_tool_result(event)

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
        return self._to_openai_input_items()

    async def __aenter__(self) -> MiniCodex:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None
