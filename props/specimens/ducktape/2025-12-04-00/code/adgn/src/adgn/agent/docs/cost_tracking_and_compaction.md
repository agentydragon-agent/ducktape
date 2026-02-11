# Cost Tracking and Compaction Design

## Overview

MiniCodex agents need to:
1. **Track cumulative token usage and cost** across a session
2. **Compact transcripts** when approaching context limits to stay within model constraints

This document defines the architecture for both concerns based on OpenAI's pricing model and context window constraints.

## Cost Tracking

### Requirements

- Track token usage from OpenAI API responses (`CompletionUsage`)
- Calculate cost accounting for:
  - Regular input tokens (full price)
  - Cached input tokens (10% of input price = 90% discount)
  - Output tokens (includes reasoning tokens for O-series models)
- Support querying total cost and token breakdown at any point during a session
- Memory-efficient (O(1) space, not O(n) for n responses)

### Implementation

#### Data Model

**Usage tracking** (from OpenAI SDK):
```python
# OpenAI SDK structure (openai-python/src/openai/types/completion_usage.py)
class CompletionUsage(BaseModel):
    completion_tokens: int          # Output tokens
    prompt_tokens: int              # Input tokens
    total_tokens: int               # prompt + completion

    completion_tokens_details: Optional[CompletionTokensDetails] = None
    prompt_tokens_details: Optional[PromptTokensDetails] = None

class PromptTokensDetails(BaseModel):
    cached_tokens: Optional[int] = None    # 90% discount
    audio_tokens: Optional[int] = None

class CompletionTokensDetails(BaseModel):
    reasoning_tokens: Optional[int] = None  # Already in completion_tokens
    audio_tokens: Optional[int] = None
```

**Our mapping** (adgn/src/adgn/agent/handler.py):
```python
class GroundTruthUsage(BaseModel):
    """Maps to OpenAI's CompletionUsage."""
    model: str
    input_tokens: int | None = None
    input_tokens_details: InputTokensDetails | None = None
    output_tokens: int | None = None
    output_tokens_details: OutputTokensDetails | None = None
    total_tokens: int | None = None

class Response(BaseModel):
    """One OpenAI responses.create result with usage.

    Emitted once per model call to avoid duplicating usage across events.
    """
    response_id: str | None = None
    usage: GroundTruthUsage
    model: str | None = None
    created_at: datetime | None = None
```

**Cost summary** (typed aggregation):
```python
class SessionCostSummary(BaseModel):
    """Summary of costs and token usage for an agent session."""

    total_input_tokens: int
    total_cached_tokens: int
    total_output_tokens: int
    total_reasoning_tokens: int

    @property
    def regular_input_tokens(self) -> int:
        """Input tokens billed at full rate (excludes cached)."""
        return self.total_input_tokens - self.total_cached_tokens
```

#### Handler Pattern

**Incremental aggregation** (O(1) space):
```python
from adgn.openai_utils.model_metadata import ModelMetadata

class CostTrackingHandler(BaseHandler):
    """Handler that tracks cumulative token usage and cost."""

    def __init__(self, meta: ModelMetadata) -> None:
        """Initialize with model metadata.

        Args:
            meta: Model metadata containing pricing info
        """
        self._meta = meta
        self._total_input_tokens = 0
        self._total_cached_tokens = 0
        self._total_output_tokens = 0
        self._total_reasoning_tokens = 0

    def on_response(self, evt: Response) -> None:
        """Accumulate token counts from each response."""
        if evt.usage.input_tokens:
            self._total_input_tokens += evt.usage.input_tokens

        if evt.usage.input_tokens_details and evt.usage.input_tokens_details.cached_tokens:
            self._total_cached_tokens += evt.usage.input_tokens_details.cached_tokens

        if evt.usage.output_tokens:
            self._total_output_tokens += evt.usage.output_tokens

        if evt.usage.output_tokens_details and evt.usage.output_tokens_details.reasoning_tokens:
            self._total_reasoning_tokens += evt.usage.output_tokens_details.reasoning_tokens

    @property
    def summary(self) -> SessionCostSummary:
        """Current token usage summary."""
        return SessionCostSummary(
            total_input_tokens=self._total_input_tokens,
            total_cached_tokens=self._total_cached_tokens,
            total_output_tokens=self._total_output_tokens,
            total_reasoning_tokens=self._total_reasoning_tokens,
        )

    @property
    def total_cost_usd(self) -> float:
        """Total cost in USD, computed from token counts and model pricing."""
        cost = 0.0

        # Regular input tokens at full rate
        regular_input = self._total_input_tokens - self._total_cached_tokens
        cost += (regular_input / 1_000_000) * self._meta.input_usd_per_1m_tokens

        # Cached input tokens at discounted rate
        cost += (self._total_cached_tokens / 1_000_000) * self._meta.cached_input_usd_per_1m_tokens

        # Output tokens (reasoning tokens already included)
        cost += (self._total_output_tokens / 1_000_000) * self._meta.output_usd_per_1m_tokens

        return cost
```

**Usage**:
```python
cost_handler = CostTrackingHandler(model="gpt-5")

agent = MiniCodex.create(
    client=openai_client,
    handlers=[cost_handler],
)

await agent.run("Do something")

# Query at any point
print(f"Total cost: ${cost_handler.total_cost_usd:.4f}")
print(f"Tokens: {cost_handler.summary.total_input_tokens:,} in, "
      f"{cost_handler.summary.total_output_tokens:,} out")
```

### Key Design Decisions

1. **Incremental aggregation**: Handler accumulates token counts on each `on_response()` event, not storing full Response list (O(1) vs O(n) memory)
2. **Cost as computed property**: `total_cost_usd` is derived from token counts + model metadata, not stored redundantly
3. **Typed summaries**: `SessionCostSummary` is a Pydantic model (not raw dict)
4. **Model stored once**: Handler holds model ID; summary doesn't duplicate it
5. **Direct field access**: Use `evt.usage.input_tokens` directly (typed), not `dict.get()`

## Compaction (Transcript Summarization)

### Requirements

- Compact transcript when approaching context limits
- Preserve recent conversation turns for context continuity
- Summarize older conversation via LLM to reduce token count
- Trigger compaction based on model-specific context windows and max output limits

### Context Window Strategy

**Formula**: Compact when `current_input_tokens + max_output_reserve > context_window * safety_margin`

```python
def should_compact(model_id: str, current_transcript_tokens: int,
                   safety_margin_pct: float = 0.20) -> bool:
    """Determine if transcript should be compacted.

    Args:
        model_id: OpenAI model identifier
        current_transcript_tokens: Current token count in transcript
        safety_margin_pct: Safety margin as percentage (0.20 = 20%)

    Returns:
        True if compaction recommended
    """
    meta = get_model_metadata(model_id)

    # Reserve space for maximum possible output
    output_reserve = meta.max_output_tokens

    # Available space for input
    available_for_input = meta.context_window_tokens - output_reserve

    # Apply safety margin
    safe_input_limit = available_for_input * (1 - safety_margin_pct)

    return current_transcript_tokens > safe_input_limit
```

### Compaction Thresholds (20% safety margin)

| Model | Context | Max Output | Available Input | Safe Limit (80%) |
|-------|---------|------------|-----------------|------------------|
| **GPT-5** | 400k | 128k | 272k | **217,600** |
| **GPT-5-mini** | 400k | 128k | 272k | **217,600** |
| **GPT-5-nano** | 400k | 128k | 272k | **217,600** |
| **O1** | 200k | 100k | 100k | **80,000** |
| **O3** | 128k | 100k | 28k | **22,400** |
| **O3-mini** | 200k | 100k | 100k | **80,000** |
| **O4-mini** | 128k | 100k | 28k | **22,400** |
| **GPT-4.1** | 128k | 16k | 112k | **89,600** |
| **GPT-4.1-mini** | 128k | 16k | 112k | **89,600** |
| **GPT-4o** | 128k | 16k | 112k | **89,600** |
| **GPT-4o-mini** | 128k | 16k | 112k | **89,600** |

**Note**: O-series reasoning models have much less available input space because they reserve 100k tokens for output (including reasoning).

### Implementation

**Loop control decision** (adgn/src/adgn/agent/loop_control.py):
```python
@dataclass(frozen=True)
class Compact:
    """Signal that transcript should be compacted before continuing.

    The agent will compact the transcript (keeping keep_recent_turns items),
    then continue with the agent's configured tool_policy.

    Note: ReasoningItem blocks are never preserved in the recent region,
    as they cannot be reused outside their original response context.
    """

    keep_recent_turns: int = 10
```

**Proposed handler signature** (would update adgn/src/adgn/agent/compaction.py):
```python
from adgn.openai_utils.model_metadata import ModelMetadata

class CompactionHandler(BaseHandler):
    """Automatically compact transcript when approaching token limits.

    Monitors cumulative token usage from API responses and returns a Compact
    decision when threshold is exceeded. Only triggers compaction once per session.
    """

    def __init__(
        self,
        meta: ModelMetadata,
        safety_margin: float = 0.20,
        keep_recent_turns: int = 10
    ):
        """Initialize compaction handler.

        Args:
            meta: Model metadata containing context window and max output limits
            safety_margin: Safety margin as fraction (0.20 = 20% buffer)
            keep_recent_turns: Number of recent transcript items to preserve (default 10)
        """
        # Calculate threshold from metadata
        available_input = meta.context_window_tokens - meta.max_output_tokens
        self._threshold = int(available_input * (1 - safety_margin))
        self._keep_recent = keep_recent_turns
        self._cumulative_tokens = 0
        self._compacted = False

    def on_response(self, evt: Response) -> None:
        """Track cumulative token usage from OpenAI API."""
        if evt.usage.total_tokens:
            self._cumulative_tokens += evt.usage.total_tokens

    def on_before_sample(self) -> LoopDecision:
        """Return Compact decision when threshold exceeded."""
        if self._cumulative_tokens > self._threshold and not self._compacted:
            logger.info(
                "Token threshold exceeded (%d > %d), triggering compaction",
                self._cumulative_tokens, self._threshold
            )
            self._compacted = True  # Only compact once per session
            return Compact(keep_recent_turns=self._keep_recent)

        return NoLoopDecision()  # Defer to other handlers
```

**Compaction execution** (adgn/src/adgn/agent/agent.py):
```python
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
        *recent_region,  # Recent turns preserved verbatim
    ]

    return CompactionResult(compacted=True)
```

### Summarization Prompt

Default prompt at `adgn/src/adgn/agent/compaction_prompt.md`:
```markdown
This conversation will be summarized and handed off to a successor agent to complete.
The agent will start with the same state of tools as the conversation ended in, but will not be able to read the conversation - only the summary.
Produce the conversation summary, aiming to give the successor information needed to complete the task successfully.

Guidelines:
- Extract important facts, decisions made, and goals established
- Preserve specific details (file paths, issue IDs, tool outputs that informed decisions)
- Omit redundant exchanges and verbose explanations
- Format as a concise narrative in past tense
- Keep it under 2000 words
```

### Key Design Decisions

1. **Trigger on cumulative tokens**: Current implementation tracks `total_tokens` across all responses
2. **One-time compaction**: Only compact once per session (flag `_compacted`)
3. **Model-aware thresholds**: Default 150k is ~75% of O1's 200k context, but should be model-specific
4. **Preserve recent turns**: Keep last N items (default 10) for conversation continuity
5. **LLM summarization**: Use same model to summarize old conversation into single message
6. **Reasoning items excluded**: ReasoningItem blocks are never preserved in recent region (can't be reused)

### Future Improvements

1. **Model-specific thresholds**: Replace fixed 150k with dynamic calculation based on `get_model_metadata(model).context_window_tokens`
2. **Track input tokens only**: Current implementation tracks `total_tokens` (input+output), but should track only input for more precise threshold
3. **Multi-stage compaction**: Allow compacting multiple times when needed (remove `_compacted` flag)
4. **Configurable safety margins**: Make 20% safety margin configurable per model/use-case
5. **Cost-aware compaction**: Consider compaction cost vs. hitting context limit mid-generation

## Usage Examples

### Simple REPL with Cost Tracking and Auto-Compaction

```python
#!/usr/bin/env python3
"""Simple REPL with cost tracking and auto-compaction."""

import asyncio
from adgn.agent.agent import MiniCodex
from adgn.agent.compaction import CompactionHandler
from adgn.agent.loop_control import RequireAnyTool
from adgn.mcp.compositor import Compositor
from adgn.openai_utils.model_client import build_client
from fastmcp.client import Client

# TODO: Implement CostTrackingHandler
# from adgn.agent.cost_tracking import CostTrackingHandler


async def main():
    model = "gpt-5"

    # Get model metadata once (DRY - single source of truth)
    from adgn.openai_utils.model_metadata import get_model_metadata
    meta = get_model_metadata(model)

    # Create handlers (both consume same metadata)
    cost_handler = CostTrackingHandler(meta=meta)
    compaction_handler = CompactionHandler(
        meta=meta,
        safety_margin=0.20,  # 20% buffer (relative threshold)
        keep_recent_turns=10
    )

    # Build MCP compositor and client
    compositor = Compositor("compositor")
    # Add your MCP servers here:
    # await compositor.mount_server("runtime", runtime_spec)

    async with Client(compositor) as mcp_client:
        # Build OpenAI client
        client = build_client(model)

        # Create agent with handlers
        agent = await MiniCodex.create(
            mcp_client=mcp_client,
            client=client,
            handlers=[cost_handler, compaction_handler],
            tool_policy=RequireAnyTool(),
        )

        async with agent:
            print("Agent ready. Type your task:")
            user_input = input("> ")

            result = await agent.run(user_text=user_input)
            print(result.text)

            # Query metrics
            # print(f"\nCost: ${cost_handler.total_cost_usd:.4f}")
            # print(f"Tokens: {cost_handler.summary.total_input_tokens:,} in, "
            #       f"{cost_handler.summary.total_output_tokens:,} out")


if __name__ == "__main__":
    asyncio.run(main())
```

### Integrating into Existing Handler Builder (DRY Pattern)

The canonical pattern is to extend `build_handlers()` with model as single source of truth:

```python
# In src/adgn/agent/runtime/handlers.py

def build_handlers(
    *,
    poll_notifications: Callable[[], NotificationsBatch],
    manager: ConnectionManager,
    persistence: Persistence,
    agent_id: AgentID,
    ui_bus: ServerBus | None = None,
    model: str,  # Single source of truth for model
) -> tuple[list[BaseHandler], RunPersistenceHandler]:
    """Build standard handler list for MiniCodex agents.

    Args:
        model: Model ID - used to derive pricing and context limits for handlers
    """

    # Get model metadata once (DRY - single source of truth)
    meta = get_model_metadata(model)

    persist_handler = RunPersistenceHandler(persistence=persistence, agent_id=agent_id)

    # Core handlers
    handlers: list[BaseHandler] = [
        manager,
        persist_handler,
    ]

    # Add cost tracking (consumes metadata for pricing)
    cost_handler = CostTrackingHandler(meta=meta)
    handlers.append(cost_handler)

    # Add auto-compaction (consumes metadata + relative threshold)
    compaction_handler = CompactionHandler(
        meta=meta,
        safety_margin=0.20,  # 20% buffer
        keep_recent_turns=10
    )
    handlers.append(compaction_handler)

    # UI/notifications handlers
    if ui_bus is not None:
        handlers.extend([
            ServerModeHandler(bus=ui_bus, poll_notifications=poll_notifications),
            DisplayEventsHandler()
        ])
    else:
        handlers.append(NotificationsHandler(poll_notifications))

    return handlers, persist_handler
```

**Key DRY principles**:
1. **Model ID is parameter**: Pass `model: str` to `build_handlers()`
2. **Metadata fetched once**: `meta = get_model_metadata(model)` at top
3. **Thread metadata to handlers**: Both handlers receive `meta` (not derived values)
4. **Relative thresholds**: `CompactionHandler` takes `safety_margin=0.20` (not absolute tokens)
5. **No duplication**: Pricing and context limits live in `meta`, used by handlers

### Querying Metrics from Agent Session

For UI/monitoring, expose cost metrics via the handler:

```python
# In src/adgn/agent/runtime/container.py or session management

class AgentContainer:
    def __init__(self, ...):
        self._cost_handler: CostTrackingHandler | None = None
        self._compaction_handler: CompactionHandler | None = None

    async def _build_agent_phase(self, ...):
        # Build handlers
        handlers, persist_handler = build_handlers(
            poll_notifications=notifications.poll,
            manager=manager,
            persistence=self.persistence,
            agent_id=self.agent_id,
            ui_bus=self._ui_bus if self.with_ui else None,
            model=self.model,
        )

        # Extract specific handlers for metrics access
        for h in handlers:
            if isinstance(h, CostTrackingHandler):
                self._cost_handler = h
            elif isinstance(h, CompactionHandler):
                self._compaction_handler = h

        # Create agent
        agent = await MiniCodex.create(...)
        ...

    @property
    def cost_summary(self) -> SessionCostSummary | None:
        """Current cost summary, or None if not tracking."""
        return self._cost_handler.summary if self._cost_handler else None

    @property
    def total_cost_usd(self) -> float | None:
        """Total cost in USD, or None if not tracking."""
        return self._cost_handler.total_cost_usd if self._cost_handler else None
```

### CLI Display

For CLI tools, print cost summary after each run:

```python
# In adgn-mini-codex run command

async with agent:
    for line in sys.stdin:
        user = line.rstrip("\n")
        if not user:
            continue

        res = await agent.run(user_text=user)
        if res.text:
            print(res.text)

        # Print cost summary after each turn
        if hasattr(agent, '_cost_handler') and agent._cost_handler:
            summary = agent._cost_handler.summary
            cost = agent._cost_handler.total_cost_usd
            print(f"\n[Tokens: {summary.total_input_tokens:,} in "
                  f"({summary.total_cached_tokens:,} cached), "
                  f"{summary.total_output_tokens:,} out | "
                  f"Cost: ${cost:.4f}]")
```

### MCP Resource for Cost Metrics

Expose cost data via MCP for UI consumption:

```python
# New MCP server: src/adgn/agent/mcp_bridge/metrics.py

from fastmcp.server import FastMCP

mcp = FastMCP("metrics")

@mcp.resource("metrics://cost")
async def get_cost_metrics() -> str:
    """Current session cost metrics as JSON."""
    if not cost_handler:
        return json.dumps({"error": "cost tracking not enabled"})

    summary = cost_handler.summary
    return json.dumps({
        "total_cost_usd": cost_handler.total_cost_usd,
        "total_input_tokens": summary.total_input_tokens,
        "total_cached_tokens": summary.total_cached_tokens,
        "total_output_tokens": summary.total_output_tokens,
        "total_reasoning_tokens": summary.total_reasoning_tokens,
        "regular_input_tokens": summary.regular_input_tokens,
    })
```

### Props Flows (Critic, Grader, Prompt Optimizer)

Props workflows use `build_props_handlers()` which returns standard handlers. Extend it to include cost tracking and compaction:

```python
# In src/adgn/props/agent_setup.py

from adgn.openai_utils.model_metadata import get_model_metadata
from adgn.agent.compaction import CompactionHandler

def build_props_handlers(
    *,
    transcript_id: UUID,
    verbose_prefix: str | None,
    servers: dict,
    model: str,  # Add model parameter
) -> list[BaseHandler]:
    """Build standard handlers for props agent workflows.

    Always includes DatabaseEventHandler for transcript persistence.
    Conditionally includes display handler if verbose_prefix is provided.
    Includes cost tracking and auto-compaction based on model.

    Args:
        transcript_id: Transcript ID for database event tracking
        verbose_prefix: Optional prefix for verbose display
        servers: Server dict for display handler
        model: Model ID for cost tracking and compaction thresholds
    """
    # Get model metadata once
    meta = get_model_metadata(model)

    handlers: list[BaseHandler] = [
        DatabaseEventHandler(transcript_id=transcript_id),
    ]

    # Add cost tracking
    handlers.append(CostTrackingHandler(meta=meta))

    # Add auto-compaction
    handlers.append(CompactionHandler(meta=meta, safety_margin=0.20))

    # Add display handler if verbose
    if verbose_prefix is not None:
        handlers.append(CompactDisplayHandler(max_lines=10, prefix=verbose_prefix, servers=servers))

    return handlers
```

**Update call sites** in critic.py, grader.py, prompt_optimizer.py:

```python
# Before (critic.py:520)
handlers: list = [
    bootstrap,
    *build_props_handlers(
        transcript_id=transcript_id,
        verbose_prefix=f"[CRITIC {input_data.specimen_slug}] " if verbose else None,
        servers=servers,
    ),
    GateUntil(_ready_state, defer_when=lambda: not bootstrap._done),
    *extra_handlers,
]

# After (add model parameter)
handlers: list = [
    bootstrap,
    *build_props_handlers(
        transcript_id=transcript_id,
        verbose_prefix=f"[CRITIC {input_data.specimen_slug}] " if verbose else None,
        servers=servers,
        model=client.model,  # Thread model from client
    ),
    GateUntil(_ready_state, defer_when=lambda: not bootstrap._done),
    *extra_handlers,
]
```

**Same pattern for grader.py:650 and prompt_optimizer.py:425**:
```python
*build_props_handlers(..., model=client.model),
```

**Benefits**:
- ✅ All props workflows (critic, grader, optimizer) get cost tracking + auto-compaction automatically
- ✅ Model-specific thresholds computed once in `build_props_handlers()`
- ✅ Single line change per call site: add `model=client.model`
- ✅ No per-workflow handler duplication

### Querying Cost in Props Flows

After extending `build_props_handlers()`, cost data is tracked but not exposed. To query it:

**Option 1**: Return cost handler from builder:
```python
def build_props_handlers(...) -> tuple[list[BaseHandler], CostTrackingHandler]:
    handlers = [...]
    cost_handler = CostTrackingHandler(meta=meta)
    handlers.append(cost_handler)
    return handlers, cost_handler

# In critic.py
handlers_list, cost_handler = build_props_handlers(...)
handlers = [bootstrap, *handlers_list, ...]

# After agent.run()
print(f"Critic cost: ${cost_handler.total_cost_usd:.4f}")
```

**Option 2**: Store in database (DBCriticRun, DBGraderRun):
```python
# In critic.py:563 (after updating run)
found_run.cost_usd = cost_handler.total_cost_usd
found_run.total_input_tokens = cost_handler.summary.total_input_tokens
found_run.total_output_tokens = cost_handler.summary.total_output_tokens
session.commit()
```

## Summary: Clean DRY Pattern

Both handlers consume `ModelMetadata` directly:

```python
# Single source of truth
model = "gpt-5"
meta = get_model_metadata(model)

# Both handlers consume metadata
cost_handler = CostTrackingHandler(
    meta=meta  # Uses pricing fields
)

compaction_handler = CompactionHandler(
    meta=meta,  # Uses context_window_tokens and max_output_tokens
    safety_margin=0.20  # Relative threshold (20% buffer)
)
```

**What gets passed**:
- ✅ `ModelMetadata` object (contains all pricing + context info)
- ✅ Relative safety margin (0.20 = 20%)
- ❌ NOT hardcoded thresholds like 217,600
- ❌ NOT duplicate model ID strings

**What handlers compute internally**:
- `CostTrackingHandler`: Uses `meta.input_usd_per_1m_tokens`, `meta.cached_input_usd_per_1m_tokens`, `meta.output_usd_per_1m_tokens`
- `CompactionHandler`: Computes `threshold = (meta.context_window_tokens - meta.max_output_tokens) * (1 - safety_margin)`

## References

- OpenAI pricing: https://openai.com/api/pricing/
- Model metadata: `src/adgn/openai_utils/model_metadata.py`
- Cost calculation: `src/adgn/openai_utils/cost.py`
- Compaction handler: `src/adgn/agent/compaction.py`
- Loop control: `src/adgn/agent/loop_control.py`
- OpenAI SDK types: `/code/github.com/openai/openai-python/src/openai/types/completion_usage.py`
