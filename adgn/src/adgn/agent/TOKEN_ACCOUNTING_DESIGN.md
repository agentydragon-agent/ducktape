# MiniCodex Ground-Truth Token Accounting (Plan)

Status: design/proposal (do not implement yet)
Owner: mpokorny
Last updated: 2025-09-14

Goals
- Track ground truth usage only (as returned by OpenAI), not dollars.
- Keep cost as a downstream, optional computation from ground-truth usage.
- Tailored to MiniCodex’s current, non‑streaming Responses API usage and tool-calls.
- Modular for embedded‑agent use; minimal surface area; easy to adopt.
- Store only upstream fields (and explicit estimates when upstream absent). No derived totals beyond what the API provides.
- Use a structured, strongly-typed event algebra internally; JSON dicts are only the serialization format.

Out of scope for this iteration
- Streaming.
- Vision/image inputs or image generation.
- Embeddings.
- Audio (STT/TTS).
- Org/Project attribution.

Authoritative source (current API)
- Responses API (non‑streaming): use response.usage directly.
  - usage.input_tokens: int
  - usage.output_tokens: int
  - usage.total_tokens: int
  - usage.reasoning_tokens: int (o‑series/reasoning models; omitted otherwise)
  - usage.cache_creation_input_tokens: int (prompt caching; omitted if 0)
  - usage.cache_read_input_tokens: int (prompt caching; omitted if 0)

Data model (ground truth only)
- GroundTruthUsage (persist exactly what the API gives; optional fields omitted if API omits)
  - model: str
  - input_tokens: int = 0
  - output_tokens: int = 0
  - total_tokens: int | None = None  # upstream total if provided
  - reasoning_tokens: int = 0
  - cache_creation_input_tokens: int = 0
  - cache_read_input_tokens: int = 0
  - request_id: str | None  # HTTP x-request-id if available via client wrapper
  - response_id: str | None  # response.id
  - created_at: datetime | None  # response.created if available
  - idempotency_key: str | None  # if caller provided one
  - estimation: {method: str, notes?: str} | None  # present only if usage was inferred

Structured types (planned)
- Use Pydantic BaseModel with discriminated unions (subclasses); no enums for event kinds. Use Literal[...] for kind and individual subclasses.
- Handlers/logging receive typed Event objects; TranscriptLogger serializes via model_dump(...), yielding JSON lines.

Refinement: no base Event or intrinsic "kind" internally
- Internals use distinct typed classes per event (no base class, no shared discriminator): UserText, AssistantText, ToolCall, FunctionCallOutput.
- "kind" exists only for transcript serialization. The logger infers it by type.

```python
from pydantic import BaseModel
from typing import Any

class UserText(BaseModel):
    text: str

class AssistantText(BaseModel):
    text: str
    usage: GroundTruthUsage | None = None

class ToolCall(BaseModel):
    name: str
    args: dict[str, Any]
    call_id: str
    usage: GroundTruthUsage | None = None

class FunctionCallOutput(BaseModel):
    call_id: str
    output: str

# Transcript logger helper
KIND_MAP = {
    UserText: "user_text",
    AssistantText: "assistant_text",
    ToolCall: "tool_call",
    FunctionCallOutput: "function_call_output",
}

def to_jsonl_record(evt: UserText | AssistantText | ToolCall | FunctionCallOutput) -> dict:
    kind = KIND_MAP[type(evt)]
    return {"kind": kind, **evt.model_dump(exclude_none=True)}
```


```python
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel

# Ground truth usage
class GroundTruthUsage(BaseModel):
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int | None = None
    reasoning_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    request_id: str | None = None
    response_id: str | None = None
    created_at: datetime | None = None
    idempotency_key: str | None = None
    estimation: dict[str, str] | None = None  # e.g., {"method": "tokenizer"}

# Event types (no shared base required at runtime; using BaseModel subclasses)
class Response(BaseModel):
    # Emitted once per OpenAI responses.create call; carries ground-truth usage
    response_id: str | None = None
    usage: GroundTruthUsage
    model: str | None = None
    created_at: datetime | None = None
    idempotency_key: str | None = None

class UserText(BaseModel):
    text: str

class AssistantText(BaseModel):
    text: str

class ToolCall(BaseModel):
    name: str
    args: dict[str, Any]
    call_id: str

class FunctionCallOutput(BaseModel):
    call_id: str
    output: str

# Factory signature (implementation later)
# def build_ground_truth_usage(resp: OpenAIResponse, *, model: str,
#                              request_id: str | None, idempotency_key: str | None) -> GroundTruthUsage: ...
```


Event integration (introduce Response event)
- Emit a Response event immediately after responses.create returns; it carries ground-truth usage and identifiers (response_id, model, created_at, idempotency_key).
- Do not attach usage to assistant/tool events; they represent content/actions only.
- Location in code (for wiring later):
  - Capture resp.usage and build Response in agent.py right after responses.create (~319–331), then forward to handlers/loggers.
  - Proceed to emit assistant_text (342–351), tool_call (595–609), and function_call_output events as usual (without usage).

Extraction logic (MiniCodex today, non‑streaming)
- In _single_turn(), after client.responses.create(...) returns, read resp.id and resp.usage; build GroundTruthUsage.
- Defer attaching GroundTruthUsage until the first event for that turn is emitted; then set the typed Event.usage field on that event. TranscriptLogger will serialize it to JSON (appearing as a "usage" key).
- If response.usage is missing (rare):
  - Estimate input_tokens using the official tokenizer on dump_messages_for_api(self._transcript).
  - Set estimation = {method: "tokenizer", notes: "usage missing"}.
  - Do not fabricate output_tokens if not known; leave 0 or omit.

API surface (for embedders)
- No new sinks or env vars. Usage is attached inside MiniCodex core before emitting the first typed Event of the turn.
- Handlers become strongly typed (event algebra), not bags of dicts or loosely typed args.
  - BaseHandler methods take the event object for that kind (see below). Reducer forwards typed events end‑to‑end.

Planned handler signatures (typed)
```python
class BaseHandler:
    def on_response(self, evt: Response) -> None: ...  # new: once per model call
    def on_user_text(self, evt: UserText) -> None: ...
    def on_assistant_text(self, evt: AssistantText) -> None: ...
    def on_tool_call(self, evt: ToolCall) -> None: ...
    def on_function_call_output(self, evt: FunctionCallOutput) -> None: ...
    def on_reasoning(self, item: Any) -> None: ...  # unchanged for now
    def on_before_sample(self) -> LoopDecision: ...  # unchanged
```

Reducer forwarding (concept)
```python
class Reducer:
    def on_response(self, evt: Response) -> None:
        for h in self._handlers:
            h.on_response(evt)
    def on_user_text(self, evt: UserText) -> None:
        for h in self._handlers:
            h.on_user_text(evt)
    def on_assistant_text(self, evt: AssistantText) -> None:
        for h in self._handlers:
            h.on_assistant_text(evt)
    def on_tool_call(self, evt: ToolCall) -> None:
        for h in self._handlers:
            h.on_tool_call(evt)
    def on_tool_result(self, evt: ToolCallOutput) -> None:
        for h in self._handlers:
            h.on_tool_result_event(evt)
```

DisplayEventsHandler (shape)
```python
class DisplayEventsHandler(BaseHandler):
    def on_user_text(self, evt: UserText) -> None:
        if evt.text:
            self._write(f"user:\n{self._truncate(evt.text)}")
    def on_assistant_text(self, evt: AssistantText) -> None:
        if evt.text:
            self._write(f"assistant:\n{self._truncate(evt.text)}")
    def on_tool_call(self, evt: ToolCall) -> None:
        # access evt.name, evt.args, evt.call_id; usage (if attached) is evt.usage
        ...
    def on_tool_result_event(self, evt: ToolCallOutput) -> None:
        # access evt.call_id, evt.result
        ...
```

TranscriptLogger as a Handler (shape)
```python
class TranscriptHandler(BaseHandler):
    def __init__(self, run_dir: Path) -> None:
        self._path = run_dir / "transcript.jsonl"
    def _emit(self, event: Event) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.model_dump(exclude_none=True), ensure_ascii=False) + "\n")
    def on_user_text(self, evt: UserText) -> None: self._emit(evt)
    def on_assistant_text(self, evt: AssistantText) -> None: self._emit(evt)
    def on_tool_call(self, evt: ToolCall) -> None: self._emit(evt)
    def on_tool_result_event(self, evt: ToolCallOutput) -> None: self._emit(evt)
```

Usage in MiniCodex.create (example)
```python
handlers=[AutoHandler(), DisplayEventsHandler(), TranscriptHandler(dest_dir=run_dir)]
# Logger will receive: Response → AssistantText → [ToolCall]* → [FunctionCallOutput]* (as applicable)
```
Deduplication and retries (minimal)
- If idempotency_key is present, include it in GroundTruthUsage and rely on downstream aggregation to dedupe on (idempotency_key, response_id).
- MiniCodex itself does not drop/merge events; it only annotates the first per‑turn event with usage.

Downstream cost (separate, optional)
- A later CostCalculator(price_table).compute(usage) -> CostBreakdown can consume the recorded usage.
- MiniCodex does not persist any cost numbers.

Examples (JSONL transcript lines)
- Assistant turn with text
  {
    "kind": "assistant_text",
    "text": "Here’s the plan...",
    "usage": {
      "model": "gpt-4o-mini",
      "input_tokens": 1234,
      "output_tokens": 321,
      "total_tokens": 1555,
      "reasoning_tokens": 0,
      "cache_read_input_tokens": 200,
      "response_id": "resp_abc",
      "created_at": "2025-09-14T12:01:02Z"
    }
  }

- Tool‑call only turn
  {
    "kind": "tool_call",
    "name": "resources_list",
    "args": {"server": "local"},
    "call_id": "call_1",
    "usage": {
      "model": "gpt-4o-mini",
      "input_tokens": 980,
      "output_tokens": 44,
      "total_tokens": 1024,
      "response_id": "resp_def"
    }
  }

Testing/acceptance checklist
- Non‑streaming: Response event emitted once with response_id and usage matching response.usage; assistant/tool events have no usage fields.
- Tool‑call loop: one Response event per model round; zero duplication of usage across events.
- Caching fields: when cache_read_input_tokens and/or cache_creation_input_tokens present, they are captured verbatim in the Response event.
- Missing usage: tokenizer estimate sets estimation in Response event; no derived totals beyond upstream.
- Idempotency key passthrough: included in Response when provided by caller.

Event algebra migration plan
- Tighten types without breaking external callers by providing a temporary adapter layer.

```python
# New typed BaseHandler signatures (adapter can still support legacy signatures for a deprecation window)
class BaseHandler:
    def on_user_text(self, evt: UserText) -> None: ...
    def on_assistant_text(self, evt: AssistantText) -> None: ...
    def on_tool_call(self, evt: ToolCall) -> None: ...
    def on_function_call_output(self, evt: FunctionCallOutput) -> None: ...
```

- Reducer updated to call handlers with typed events; equality/conflict logic unchanged.
- MiniCodex._emit_event accepts a typed Event and logs via model_dump(exclude_none=True).

TranscriptLogger as a Handler
- Feasibility: Yes. Logger writes exactly one record per event kind.
- With Response introduced, the logger writes a distinct {kind: "response", ...usage...} line, avoiding duplication across assistant/tool events.
- Required API changes:
  - Add on_response(self, evt: Response) to BaseHandler and Reducer.
  - Ensure system_note and tool_error either get their own event types or remain as raw dicts with a separate simple logger.
- Interim approach: Keep the existing on_event sink until typed events land. Then switch TranscriptLogger to a Handler and remove the on_event path to avoid duplication.

Callsite switch checklist (replace legacy logger with handler)
- Goal: All MiniCodex users wire TranscriptHandler explicitly; remove legacy on_event logger.
- Affected create() callsites (grep):
  - src/adgn_llm/properties/lint_issue.py:364
  - src/adgn_llm/llm_edit.py:55
  - src/adgn_llm/inop/engine/optimizer.py:341
  - src/adgn_llm/properties/grade_runner.py:136
  - src/adgn_llm/properties/prompt_eval/server.py:75
  - src/adgn_llm/properties/cluster_unknowns.py:132
  - src/adgn_llm/properties/cli_app/main.py:277
  - src/adgn_llm/tests/properties/test_lint_issue_bootstrap.py:115
  - src/adgn_llm/properties/cli.py:306, 428
  - src/adgn_llm/tests/mini_codex/test_exec_roundtrip.py:61
  - src/adgn_llm/inop/runners/minicodex_runner.py:79
  - src/adgn_llm/properties/agent_runner.py:37
  - src/adgn_llm/git_commit_ai/minicodex_backend.py:123
  - src/adgn_llm/mini_codex/transcript_handler.py:28
  - src/adgn_llm/mini_codex/cli.py:139
  - src/adgn_llm/mini_codex/agent_progress.py:21

Change pattern per callsite (once typed events are wired):
```python
from adgn.agent.transcript_handler import TranscriptHandler

# existing handlers
handlers = [AutoHandler(), DisplayEventsHandler(), TranscriptHandler(dest_dir=run_dir)]
from fastmcp.client import Client

# Build MiniCodex against the Compositor (no manager)
async with Client(compositor) as mcp_client:
    agent = await MiniCodex.create(
        model=model,
        mcp_client=mcp_client,
        handlers=handlers,
        # remove on_event argument entirely
    )
```

Agent logging init changes (remove legacy on_event logger):
- In src/adgn_llm/mini_codex/agent.py:_init_logging
  - Keep run_dir creation and run.json write.
  - Remove TranscriptLogger + on_event chaining entirely.
  - Rely on TranscriptHandler being present in handlers to produce transcript.jsonl/events.jsonl.

Rollout order (safe):
1) Land typed events + TranscriptHandler.
2) Update Reducer and in-repo handlers to typed signatures.
3) Switch all callsites to pass TranscriptHandler; remove any on_event args.
4) Delete legacy TranscriptLogger and on_event plumbing from MiniCodex._init_logging.

Migration plan (incremental)
1) Implement normalize_usage_from_response(resp) and unit tests with fake responses.
2) Introduce typed Event classes and add TranscriptHandler; provide a temporary adapter for legacy handlers if needed.
3) Wire usage extraction and emit Response event in _single_turn() (non‑streaming only).
4) Update BaseHandler and Reducer to the typed signatures; convert in‑tree handlers (AutoHandler, DisplayEventsHandler); add typed events for system_note and tool_error or a generic Event.
5) Switch callsites to TranscriptHandler and remove on_event usage; then remove legacy logger from MiniCodex._init_logging.
6) Add tests for assistant_text and tool‑call‑only turns; caching and no‑usage paths.
