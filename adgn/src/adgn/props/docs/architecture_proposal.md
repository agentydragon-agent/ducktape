# Props Architecture (Implemented 2025-11-28)

This document describes the current architecture after domain-driven refactoring completed on 2025-11-28.

## Current Architecture (Implemented)

### Overview

The architecture follows a **domain-driven design** where each domain (critic, grader) owns:
- Models (input/output schemas, state containers)
- Tool definitions (`build_*_submit_tools()`)
- Execution functions (`run_critic()`, `run_grader()`)

**Key principles:**
- ✅ Functions not classes (no unnecessary OOP)
- ✅ DB writes internal to run functions (can't forget to persist)
- ✅ Two-phase DB writes (initial run BEFORE agent for FK, update AFTER)
- ✅ All dependencies explicit (no hidden state)
- ✅ Tool definitions pure (no side effects)
- ✅ Composable via MCP (easy to wrap in tools for nested agents)

### File Organization

| File | Purpose | Contains |
|------|---------|----------|
| **`critic.py`** | Critic domain | Models (`CriticScope`, `CriticInput`, `CriticSuccess`, `CriticFailure`, `CriticOutput`), state (`CriticSubmitState`), tools (`build_critic_submit_tools()`), runner (`run_critic()`) |
| **`grader.py`** | Grader domain | Models (`GraderInput`, `GraderOutput`), state (`GradeSubmitState`), tools (`build_grader_submit_tools()`), runners (`run_grader()`, `grade_critique_by_id()`) |
| **`prompt_eval/server.py`** | MCP evaluation server | Provides `run_critic()` and `run_grader()` tools that return DB IDs for nested agent pattern |
| **`cluster_unknowns.py`** | Clustering workflow | Discovery and clustering of unknown issues from grader runs |
| ~~`run_models.py`~~ | **DELETED** | Models moved to domain homes (critic.py, grader.py) |
| ~~`run_managers.py`~~ | **DELETED** | Classes replaced by domain functions |
| ~~`grade_runner.py`~~ | **DELETED** | Functions moved to grader.py |

### Core Pattern: `run_critic()` / `run_grader()`

**Signature:**
```python
async def run_critic(
    input_data: CriticInput,
    *,
    client: OpenAIModelProto,
    system_prompt: str,
    user_prompt: str,
    content_root: Path,
    mount_properties: bool = False,
    extra_handlers: tuple[BaseHandler, ...] = (),
) -> tuple[CriticSuccess, DBCriticRun]:
    """Run critic agent and persist to DB. Returns (output, db_record)."""
```

**Lifecycle (9 phases):**
1. Generate `transcript_id = uuid4()`
2. **Phase 1 DB write**: Create initial run in database (output=None) - BEFORE agent runs
3. Setup compositor and mount servers
4. Create handlers including `DatabaseEventHandler(agent_run_id=transcript_id)`
5. Run MiniCodex agent
6. Extract result from state
7. Build typed output (`CriticSuccess` or `CriticFailure`)
8. **Phase 2 DB write**: Update run with output, create critique if successful
9. Return tuple of (output, db_record)

**Why two-phase DB writes?**
- Initial run MUST exist before agent starts (FK constraint: events table references run)
- `DatabaseEventHandler` writes events during execution, needs valid FK
- Output only known after agent completes

**Implementation choice:** Inline all logic (no helper functions) - ~17 identical lines per function. This keeps code explicit and easy to modify per-agent.

### Database Integration

All evaluation runs write to database:

**Tables:**
- `critic_runs`: transcript_id (PK), prompt_sha256, specimen_slug, model, files, output (JSONB), critique_id (FK)
- `critiques`: specimen_slug, payload (JSONB with CriticSubmitPayload)
- `grader_runs`: transcript_id (PK), critique_id (FK), model, output (JSONB)
- `events`: agent_run_id (FK to transcript_id), event_type, content, timestamp

**MCP pattern (prompt_eval server):**
```python
# Server returns DB IDs only
@mcp.tool()
async def run_critic(payload: RunCriticInput) -> RunCriticOutput:
    critic_success, db_model = await run_critic(...)
    return RunCriticOutput(
        critic_run_id=db_model.id,
        critique_id=db_model.critique_id
    )
```

**Benefits:**
- Agent queries database for results/metrics/costs
- No file I/O for evaluation results
- Queryable history across runs

### Nested Agent Pattern

The prompt optimizer is itself an agent that calls other agents via MCP:

```
prompt_optimizer agent
  ↓ calls MCP tools from prompt_eval server
  ↓ which internally call:
    run_critic()   → writes to critic_runs table
    run_grader()   → writes to grader_runs table
```

This requires runner functions to be:
- Simple to call (just function call, no OOP)
- Self-contained (handle their own DB writes)
- Composable (easy to wrap in MCP tools)

Functions are ideal for this - no state to manage, explicit dependencies.

## Design Decisions

### Functions vs Classes

**Decision:** Use functions, not classes
**Rationale:**
- No shared behavior in base class
- No polymorphism needed
- State is just 2 fields (input_data, transcript_id) passed through
- Simpler to understand and test
- Better for MCP wrapping (no OOP ceremony)

### Inline vs Helpers

**Decision:** Inline all logic (~17 identical lines per function)
**Rationale:**
- Clear and explicit - no hidden behavior
- Easy to modify per-agent
- Can refactor to helpers later if needed
- Explicit is better than clever for initial implementation

**When to revisit:**
- Adding 5+ more agents
- Same bug appears in multiple agents
- Global pattern change needed

### DB Writes Placement

**Decision:** Inline ORM operations in run functions (no helper functions)
**Rationale:**
- Only ~4 lines per phase (initial + update)
- Agent-specific fields (critique_id, etc.)
- Clear sequencing with agent execution
- No abstraction needed for simple ORM calls

## Rejected Alternatives

<details>
<summary><b>Option A: Keep classes with better layering (rejected)</b></summary>

Keep `CriticRun`/`GraderRun` classes but fix the abstractions:
- Move DB writes into `execute()` method
- Return tuple `(output, db_record)`

**Rejected because:**
- Still unnecessary OOP for simple linear flow
- No actual shared behavior to justify base class
- Functions are simpler and more composable
</details>

<details>
<summary><b>Option B: Separate runner files (rejected)</b></summary>

Create `critic_runner.py` and `grader_runner.py` separate from model files.

**Rejected because:**
- Unnecessary file fragmentation
- Domain should own everything (models + execution)
- One file per domain is clearer
</details>

<details>
<summary><b>Option C: Helper functions for setup (rejected)</b></summary>

Extract helpers like `init_agent_run_db()`, `finalize_agent_run_db()`, `setup_compositor()`, etc.

**Rejected because:**
- Only ~17 truly identical lines (not enough pain)
- Adds indirection for marginal DRY benefit
- Harder to customize per-agent
- Can add later if pattern stabilizes and we add more agents
</details>

<details>
<summary><b>Option D: Context manager (rejected)</b></summary>

Full `AgentRunContext` context manager handling DB writes, compositor setup, handlers:

```python
async with AgentRunContext(input_data, client) as ctx:
    # Mount agent-specific servers
    # Run agent
    # Return output
```

**Rejected because:**
- Most complex abstraction
- Harder to understand control flow
- Harder to customize per-agent
- Overkill for simple linear execution
- Only ~17 lines of duplication to save
</details>

## Key Principles (Summary)

1. **Domain-driven**: One file per domain (critic.py, grader.py) owns models + execution
2. **Functions not classes**: No unnecessary OOP, all dependencies explicit
3. **Two-phase DB writes**: Initial run BEFORE agent (FK), update AFTER
4. **DB writes internal**: Can't forget to persist
5. **Tool definitions pure**: No side effects in model/tool builders
6. **Composable via MCP**: Easy to wrap in tools for nested agents
7. **Inline over helpers**: Explicit ~17 lines per function (can DRY later if needed)
8. **Clear sequencing**: Setup → execute → persist in one function
