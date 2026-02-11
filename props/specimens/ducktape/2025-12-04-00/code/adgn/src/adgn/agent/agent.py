"""MiniCodex agent on OpenAI Responses API with MCP tool wiring.

For stateless reasoning/tool replay demo, see :/adgn/examples/openai_api/stateless_two_step_demo.py
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
import copy
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
from fastmcp.client import Client
from mcp import types as mcp_types
from pydantic import TypeAdapter

from adgn.agent.events import AssistantText, GroundTruthUsage, Response, ToolCall, ToolCallOutput, UserText
from adgn.agent.loop_control import (
    Abort,
    AllowAnyToolOrTextMessage,
    Compact,
    ForbidAllTools,
    InjectItems,
    NoAction,
    RequireAnyTool,
    RequireSpecific,
    ToolPolicy,
)
from adgn.mcp._shared.calltool import as_minimal_json, fastmcp_to_mcp_result
from adgn.openai_utils.model import (
    AssistantMessage,
    AssistantMessageOut,
    FunctionCallItem,
    FunctionCallOutputItem,
    FunctionToolParam,
    InputItem,
    OpenAIModelProto,
    ReasoningItem,
    ResponsesRequest,
    SystemMessage,
    ToolChoice,
    ToolChoiceFunction,
    UserMessage,
)
from adgn.openai_utils.types import ReasoningEffort, ReasoningSummary, build_reasoning_params

from .reducer import BaseHandler, Reducer

if TYPE_CHECKING:
    pass


@dataclass
class AgentResult:
    text: str
    # NOTE: We intentionally do NOT return transcript/events in agent result.
    # Tests or callers that need access to the event sequence should register a handler
    # (e.g. a test-only RecordingHandler) and pass it via `handlers` argument to MiniCodex.create().


@dataclass
class CompactionResult:
    """Result of transcript compaction operation."""

    compacted: bool


@dataclass(slots=True)
class ToolCallOutcome:
    """MCP tool invocation result.

    Fields:
    - result: The CallToolResult with isError flag indicating success/failure
    - was_aborted: True if execution was aborted (policy denial), False otherwise
    """

    result: mcp_types.CallToolResult
    was_aborted: bool = False


def _require_call_id(function_call: FunctionCallItem) -> str:
    call_id = function_call.call_id
    if not isinstance(call_id, str) or not call_id:
        raise RuntimeError("FunctionCallItem missing call_id")
    return call_id


def _dump_call_tool_result(res: mcp_types.CallToolResult) -> str:
    """Serialize an MCP CallToolResult for Responses input.

    Dumps a compact JSON representation of the tool result.
    """

    result = json.dumps(as_minimal_json(res), ensure_ascii=False)

    # Safety check: OpenAI has a 10MB limit for input strings
    # Fail fast if tool output is too large to prevent API errors
    if len(result) > MAX_TOOL_RESULT_BYTES:
        raise RuntimeError(
            f"Tool output too large: {len(result) = } > {MAX_TOOL_RESULT_BYTES = }.Check slicing/pagination."
        )

    return result


def _maybe_error_message(res: mcp_types.CallToolResult) -> str | None:
    if not res.isError:
        return None
    structured = res.structuredContent
    if isinstance(structured, dict) and isinstance(err := structured.get("error"), str) and err:
        return err
    for block in res.content or []:
        # Only support plain text blocks for now; surface others explicitly.
        if isinstance(block, mcp_types.TextContent):
            # Do not strip content; return exactly as provided by the server.
            txt = block.text
            if isinstance(txt, str) and txt:
                return txt
        else:
            # TODO(mpokorny): Support non-text content in agent error handling:
            #  - mcp_types.ImageContent: decode or summarize
            #  - mcp_types.AudioContent: transcribe or summarize
            #  - mcp_types.ResourceLink / EmbeddedResource: fetch and summarize safely
            raise NotImplementedError(f"Unsupported CallToolResult content type: {type(block).__name__}")
    return None


def _make_error_result(message: str) -> mcp_types.CallToolResult:
    return mcp_types.CallToolResult(content=[mcp_types.TextContent(type="text", text=message)], isError=True)


DEFAULT_ABORT_ERROR = "tool execution aborted"


def _abort_result(reason: str | None = None) -> mcp_types.CallToolResult:
    return _make_error_result(reason or DEFAULT_ABORT_ERROR)


def _normalize_call_arguments(arguments: str | dict[str, Any] | list[Any] | None) -> str | None:
    """Normalize function call arguments to JSON string."""
    if arguments is None or isinstance(arguments, str):
        return arguments
    try:
        return json.dumps(arguments)
    except TypeError:
        return str(arguments)


# Namespaced tool form: mcp_{server}_{tool}
ToolMap = dict[str, Any]

SYSTEM_INSTRUCTIONS = "You are a code agent. Be concise."

# Size limits (bytes)
MAX_TOOL_RESULT_BYTES = 10 * 1024 * 1024  # 10 MiB


def _tool_choice_from_policy(policy: ToolPolicy) -> ToolChoice:
    """Map a ToolPolicy to Responses API tool_choice value.

    Exhaustive and strict: raises on unknown policy; RequireSpecific supports exactly one name.
    """
    if isinstance(policy, RequireAnyTool):
        return "required"
    if isinstance(policy, AllowAnyToolOrTextMessage):
        return "auto"
    if isinstance(policy, ForbidAllTools):
        return "none"
    if isinstance(policy, RequireSpecific):
        if len(policy.names) == 1:
            return ToolChoiceFunction(name=policy.names[0])
        raise ValueError("RequireSpecific with multiple names is not supported for Responses.tool_choice")
    raise TypeError(f"Unknown ToolPolicy: {type(policy).__name__}")


type Message = UserMessage | AssistantMessage | SystemMessage
type TranscriptItem = Message | FunctionCallItem | ReasoningItem | ToolCallOutput


class MiniCodex:
    def __init__(
        self,
        *,
        system: str | None,
        mcp_client: Client,
        client: OpenAIModelProto,
        reasoning_effort: ReasoningEffort | None = None,
        reasoning_summary: ReasoningSummary | None = None,
        parallel_tool_calls: bool,
        handlers: Iterable[BaseHandler],
        tool_policy: ToolPolicy,
        dynamic_instructions: Callable[[], Awaitable[str]] | None = None,
    ) -> None:
        self._default_system = system or SYSTEM_INSTRUCTIONS
        self._system = self._default_system
        self._dynamic_instructions = dynamic_instructions
        self._mcp_client = mcp_client
        self._client = client
        self._parallel_tool_calls = parallel_tool_calls
        self._tool_policy = tool_policy
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
        if not handlers_list:
            raise ValueError(
                "At least one handler required to control the agent loop. "
                "Without handlers, the agent will loop indefinitely. "
                "Add a handler:\n"
                "  • DisplayEventsHandler() - for console output\n"
                "  • TranscriptHandler(events_path=...) - for logging\n"
                "  • AbortIf(lambda: should_stop) - to abort when condition is met\n"
                "  • SequenceHandler([...]) - for fixed action sequences\n"
                "  • Custom handler - subclass BaseHandler for specialized control"
            )
        self._controller = Reducer(handlers_list)

    def set_system_instructions(self, instructions: str | None) -> None:
        """Override base system instructions for future turns."""
        self._system = (instructions or self._default_system).strip()

    async def _build_effective_instructions(self) -> str:
        # Compose dynamic instructions if a provider is set; append to base system.
        if self._dynamic_instructions is not None:
            dyn = await self._dynamic_instructions()
            base = self._system or ""
            return (base + (dyn or "")).strip()
        return (self._system or "").strip()

    async def compact_transcript(
        self, *, keep_recent_turns: int = 10, summarization_prompt: str | None = None
    ) -> CompactionResult:
        """Compact old conversation by summarizing.

        Preserves:
        - Recent N transcript items

        Compacts:
        - Old UserMessage/AssistantMessage text
        - Old FunctionCallItem/ToolCallOutput (tool call chains)
        - Old ReasoningItem blocks

        Returns summary as a single UserMessage inserted before recent turns.

        Args:
            keep_recent_turns: Number of recent transcript items to preserve
            summarization_prompt: Custom prompt for summarization (default: load from file)

        Returns:
            CompactionResult with statistics about what was compacted
        """

        # Find boundary: keep last N items, compact everything before
        boundary_index = max(0, len(self._transcript) - keep_recent_turns)

        if boundary_index < 1:
            return CompactionResult(compacted=False)

        # Partition transcript in original order
        all_to_compact = self._transcript[:boundary_index]
        recent_region = self._transcript[boundary_index:]

        # Check if we have enough items to make compaction worthwhile
        if len(all_to_compact) < 3:
            return CompactionResult(compacted=False)

        # Generate summary via LLM
        summary_text = await self._generate_summary(all_to_compact, summarization_prompt)

        # Rebuild transcript
        summary_msg = UserMessage.text(summary_text)

        self._transcript = [
            summary_msg,  # Summary of compacted conversation
            *recent_region,  # Recent turns preserved verbatim (no ReasoningItems)
        ]

        return CompactionResult(compacted=True)

    async def _generate_summary(self, items: list[TranscriptItem], custom_prompt: str | None) -> str:
        """Use LLM to summarize transcript items.

        Handles:
        - UserMessage: full text
        - AssistantMessage: full text
        - ReasoningItem: summary only (not full extended thinking)
        - FunctionCallItem: tool name and args
        - ToolCallOutput: result summary
        """

        # Serialize transcript items to JSON using TypeAdapter
        # TODO: Consider stripping/formatting to remove fields without semantic content
        #  (e.g., tool call IDs, encrypted reasoning data, internal metadata)
        adapter = TypeAdapter(list[TranscriptItem])
        conversation = adapter.dump_json(items, exclude_none=True, indent=2).decode()

        # Load default prompt from file if not provided
        if custom_prompt is None:
            prompt_file = Path(__file__).parent / "compaction_prompt.md"
            custom_prompt = prompt_file.read_text()

        # Build summarization request
        req = ResponsesRequest(input=[UserMessage.text(conversation)], instructions=custom_prompt, stream=False)

        resp = await self._client.responses_create(req)

        # Extract text from response
        if resp.output and len(resp.output) > 0:
            first = resp.output[0]
            if isinstance(first, AssistantMessageOut):
                return first.text

        raise RuntimeError("Summary generation failed: LLM response missing assistant message")

    async def run(self, user_text: str) -> AgentResult:
        self._transcript.append(UserMessage.text(user_text))
        self._controller.on_user_text(UserText(text=user_text))
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
            (function_call, _normalize_call_arguments(function_call.arguments)) for function_call in function_calls
        ]

        local_result_map: dict[str, mcp_types.CallToolResult] = {
            evt.call_id: evt.result for evt in self._transcript if isinstance(evt, ToolCallOutput)
        }

        async def _invoke(
            function_call: FunctionCallItem,
            args_json: str | None,
            local_map: dict[str, mcp_types.CallToolResult] = local_result_map,
        ) -> ToolCallOutcome:
            cid = _require_call_id(function_call)
            # No agent-level before-tool gating; Policy Gateway middleware enforces approvals/denials
            if cid in local_map:
                return ToolCallOutcome(result=copy.deepcopy(local_map[cid]))

            # Invoke via Policy Gateway client; do not swallow exceptions.
            # Parse arguments strictly; invalid JSON/object shape is a hard error.
            args: dict[str, Any] = {}
            if args_json:
                val = json.loads(args_json)
                if not isinstance(val, dict):
                    raise ValueError("tool arguments must be a JSON object")
                args = val
            raw = await self._mcp_client.call_tool(function_call.name, args, raise_on_error=False)
            # Convert FastMCP CallToolResult to Pydantic mcp.types.CallToolResult
            return ToolCallOutcome(result=fastmcp_to_mcp_result(raw))

        if self._parallel_tool_calls:
            await self._run_tool_calls_parallel(calls, function_calls, _invoke)
        else:
            await self._run_tool_calls_sequential(calls, function_calls, _invoke)
        self.pending_function_calls.clear()

    async def _run_tool_calls_parallel(
        self, calls: list[tuple[FunctionCallItem, str | None]], function_calls: list[FunctionCallItem], invoker
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
                cid = _require_call_id(fc)
                results[cid] = outcome
                if outcome.was_aborted:
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
                outcome = ToolCallOutcome(result=_abort_result(), was_aborted=True)
            self._emit_tool_result(function_call, outcome.result)
            if outcome.was_aborted:
                had_error = True
        if had_error:
            self.finished = True

    async def _run_tool_calls_sequential(
        self, calls: list[tuple[FunctionCallItem, str | None]], function_calls: list[FunctionCallItem], invoker
    ) -> None:
        for i, (function_call, args_json) in enumerate(calls):
            outcome = await invoker(function_call, args_json)
            self._emit_tool_result(function_call, outcome.result)
            if outcome.was_aborted:
                for remaining in function_calls[i + 1 :]:
                    self._emit_tool_result(remaining, _abort_result())
                self.finished = True
                break

    def _to_openai_input_items(self) -> list[InputItem]:
        """Convert transcript to typed OpenAI Responses input items."""
        items: list[InputItem] = []
        for item in self._transcript:
            if isinstance(item, UserMessage | AssistantMessage | SystemMessage):
                items.append(item.model_copy(deep=True))
                continue
            if isinstance(item, ReasoningItem):
                items.append(item)
                continue
            if isinstance(item, FunctionCallItem):
                items.append(item)
                continue
            if isinstance(item, ToolCallOutput):
                items.append(FunctionCallOutputItem(call_id=item.call_id, output=_dump_call_tool_result(item.result)))
                continue
            raise TypeError(f"Unsupported transcript item for OpenAI input: {type(item)}")
        return items

    async def _run_one_phase(self):
        decision = self._controller.on_before_sample()
        if isinstance(decision, Abort):
            self.finished = True
            return
        if isinstance(decision, Compact):
            await self.compact_transcript(keep_recent_turns=decision.keep_recent_turns)
            return  # Continue to next iteration after compaction

        # Handle InjectItems: append all items to transcript
        if isinstance(decision, InjectItems):
            self._transcript.extend(decision.items)
            # Notify handlers about injected function calls and add to pending
            for item in decision.items:
                if isinstance(item, FunctionCallItem):
                    self._controller.on_tool_call(
                        ToolCall(name=item.name, args_json=item.arguments, call_id=item.call_id)
                    )
                    self.pending_function_calls.append(item)
            # Skip sampling this iteration
            # Main loop will execute any pending function calls, then iterate again
            return

        # Unify resp_output element type across branches for mypy
        resp_output: list[ReasoningItem | FunctionCallItem | FunctionCallOutputItem | AssistantMessageOut] | None = None

        # Determine whether to sample LLM
        should_sample_llm = False

        if isinstance(decision, NoAction):
            should_sample_llm = True
        else:
            raise TypeError(f"Unsupported loop decision: {type(decision).__name__}")

        if should_sample_llm:
            tool_choice = _tool_choice_from_policy(self._tool_policy)
            reasoning_param = build_reasoning_params(self._reasoning_effort, self._reasoning_summary)
            # Build OpenAI Responses tools list via Policy Gateway client (proxy aggregates downstream)
            tools = await self._mcp_client.list_tools()

            req = ResponsesRequest(
                input=self._to_openai_input_items(),
                instructions=await self._build_effective_instructions(),
                stream=False,
                tool_choice=tool_choice,
                store=True,
                parallel_tool_calls=self._parallel_tool_calls,
                tools=[
                    FunctionToolParam(name=t.name, description=t.description, parameters=t.inputSchema) for t in tools
                ],
                reasoning=reasoning_param,
            )
            resp = await self._client.responses_create(req)
            sdk_usage = resp.usage
            usage = (
                GroundTruthUsage(
                    model=self._client.model,
                    input_tokens=sdk_usage.input_tokens,
                    input_tokens_details=sdk_usage.input_tokens_details,
                    output_tokens=sdk_usage.output_tokens,
                    output_tokens_details=sdk_usage.output_tokens_details,
                    total_tokens=sdk_usage.total_tokens,
                )
                if sdk_usage is not None
                else GroundTruthUsage(model=self._client.model)
            )
            self._controller.on_response(Response(response_id=resp.id, usage=usage, model=self._client.model))
            resp_output = resp.output

        if resp_output is not None:
            self._process_resp_output(resp_output)
        if not self.pending_function_calls:
            self.finished = True

    def _process_resp_output(
        self, resp_output: Sequence[ReasoningItem | FunctionCallItem | FunctionCallOutputItem | AssistantMessageOut]
    ) -> None:
        self.pending_function_calls.clear()
        # Skip items that are already present in our transcript (id collision).
        existing_ids: set[str] = set()
        for evt in self._transcript:
            # Only these item types carry optional id fields
            if isinstance(evt, ReasoningItem | FunctionCallItem):
                eid = evt.id
                if isinstance(eid, str) and eid:
                    existing_ids.add(eid)
        handled_cids = {evt.call_id for evt in self._transcript if isinstance(evt, ToolCallOutput)}
        for item in resp_output:
            # If this item has an id and we've already recorded it, skip
            iid = item.id if isinstance(item, ReasoningItem | FunctionCallItem) else None
            if isinstance(iid, str) and iid in existing_ids:
                continue
            if isinstance(item, ReasoningItem):
                self._controller.on_reasoning(item)
                self._transcript.append(item)
            elif isinstance(item, AssistantMessageOut):
                text = item.text
                self.assistant_text_chunks.append(text)
                self._controller.on_assistant_text(AssistantText(text=text))
                # Store assistant as our input item type to avoid secondary translation
                self._transcript.append(item.to_input_item())
            elif isinstance(item, FunctionCallOutputItem):
                if item.output is None:
                    raise ValueError("FunctionCallOutputItem.output is None")
                result = TypeAdapter(mcp_types.CallToolResult).validate_json(item.output)
                ocid = item.call_id
                assert isinstance(ocid, str)
                assert ocid
                event = ToolCallOutput(call_id=ocid, result=result)
                handled_cids.add(ocid)
                self._controller.on_tool_result(event)
                self._transcript.append(event)
                if self.pending_function_calls:
                    self.pending_function_calls = [fc for fc in self.pending_function_calls if fc.call_id != ocid]
            elif isinstance(item, FunctionCallItem):
                # Enforce a proper call_id for indexing/pending management
                cid = _require_call_id(item)
                fc_local = item  # No conversion needed anymore
                self._controller.on_tool_call(ToolCall(name=item.name, args_json=item.arguments, call_id=cid))
                self._transcript.append(fc_local)
                # Store in map for quick lookup when processing outputs
                self._function_call_map[cid] = fc_local
                if cid in handled_cids:
                    continue
                self.pending_function_calls.append(fc_local)
            else:
                # Crash fast on unknown items to surface mismatches early
                raise TypeError(f"Unsupported Responses output item: {type(item)}")

    @classmethod
    async def create(
        cls,
        *,
        mcp_client: Client,
        handlers: Iterable[BaseHandler],
        client: OpenAIModelProto,
        system: str | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        reasoning_summary: ReasoningSummary | None = None,
        parallel_tool_calls: bool = True,
        tool_policy: ToolPolicy,
        dynamic_instructions: Callable[[], Awaitable[str]] | None = None,
    ) -> MiniCodex:
        """Create a MiniCodex agent.

        Tool policy is set once at initialization and remains fixed throughout the agent's lifetime.
        Common values: RequireAnyTool() (typical), AllowAnyToolOrTextMessage(), ForbidAllTools().
        """
        return cls(
            system=system,
            mcp_client=mcp_client,
            client=client,
            reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary,
            parallel_tool_calls=parallel_tool_calls,
            tool_policy=tool_policy,
            handlers=list(handlers),
            dynamic_instructions=dynamic_instructions,
        )

    def _emit_tool_result(self, function_call: FunctionCallItem, result: mcp_types.CallToolResult) -> None:
        """Emit a ToolCallOutput event and notify handlers."""

        call_id = _require_call_id(function_call)
        event = ToolCallOutput(call_id=call_id, result=copy.deepcopy(result))
        self._transcript.append(event)
        self._controller.on_tool_result(event)

    # Exposed for abort flows: synthesize aborted outputs for all pending calls
    def abort_pending_tool_calls(self) -> None:
        if not self.pending_function_calls:
            return
        for fc in list(self.pending_function_calls):
            self._emit_tool_result(fc, _abort_result())
        self.pending_function_calls.clear()

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


logger = logging.getLogger(__name__)
