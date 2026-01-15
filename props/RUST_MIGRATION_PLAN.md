# Props Rust Migration Plan

> Status: **DRAFT - Under Evaluation**
> Last Updated: 2026-01-15

## Executive Summary

This document evaluates options and plans the migration of `//props/{core,backend}` and supporting libraries (`//agent_core`, `//mcp_infra`) from Python to Rust.

---

## Table of Contents

1. [Current Architecture](#current-architecture)
2. [Framework Evaluation: Rig](#framework-evaluation-rig)
3. [Alternative Approaches](#alternative-approaches)
4. [Rust Building Blocks](#rust-building-blocks)
5. [Proposed Architecture](#proposed-architecture)
6. [Migration Strategy](#migration-strategy)
7. [Open Questions](#open-questions)
8. [Decision Log](#decision-log)

---

## Current Architecture

### Components to Port

| Component | Purpose | Key Dependencies |
|-----------|---------|------------------|
| `agent_core` | Low-level agent framework | OpenAI API, event system, handler chain |
| `mcp_infra` | MCP protocol utilities | FastMCP, tool composition |
| `props/core` | Evaluation infrastructure | SQLAlchemy, aiodocker, Alembic |
| `props/backend` | Dashboard REST/WebSocket API | FastAPI, Uvicorn |

### Key Abstractions in Python

```python
# agent_core - Discriminated union events
class Event:
    SystemText | UserText | AssistantText | ToolCall | ToolCallOutput | ApiRequest | Response

# agent_core - Loop control
class LoopDecision:
    NoAction | InjectItems | Abort | Compact

class ToolPolicy:
    Require | Forbid | Allow

# agent_core - Handler pattern
class Handler:
    async def on_response(response) -> None
    async def on_before_sample() -> ContinueDecision
    async def on_tool_call(call) -> ToolCallOutcome
```

---

## Framework Evaluation: Rig

[Rig](https://github.com/0xPlaygrounds/rig) is a Rust LLM framework by 0xPlaygrounds. Evaluated version: 0.27.x

### What Rig Provides

| Feature | Details |
|---------|---------|
| **Multi-provider abstraction** | 20+ providers (OpenAI, Anthropic, Cohere, etc.) via unified traits |
| **Agent abstraction** | `Agent` type with builder pattern |
| **Tool system** | `#[tool]` macro for function-to-tool conversion |
| **Multi-turn conversations** | `.multi_turn(n)` for agentic loops with tool use |
| **Chat history** | `.with_history(&mut chat_history)` for transcript persistence |
| **Hook system** | `PromptHook<M>` trait for observability callbacks |
| **Reasoning support** | `Content::Thinking` variant, maps to `AssistantContent::Reasoning` |
| **Vector stores** | 10+ integrations (MongoDB, LanceDB, Qdrant, etc.) |
| **MCP support** | `rmcp` integration (as of 0.16.0) |
| **Streaming** | Native streaming support |
| **Cancellation** | `CancelSignal` for early termination |

### Hook System Analysis

From [`rig-core/src/agent/prompt_request/mod.rs`](https://github.com/0xPlaygrounds/rig/blob/main/rig/rig-core/src/agent/prompt_request/mod.rs):

```rust
/// PromptHook trait - per-request event callbacks
trait PromptHook<M> {
    fn on_completion_call(&self, message: &Message, history: &[Message]) -> Result<()>;
    fn on_completion_response(&self, response: &Response) -> Result<()>;
    fn on_tool_call(&self, name: &str, call_id: &str, args: &Value) -> Result<()>;
    fn on_tool_result(&self, name: &str, call_id: &str, args: &Value, result: &str) -> Result<()>;
}
```

**Key observations:**
- Hooks receive **immutable references** to history
- Hooks are for **observation only** (logging, metrics)
- **Cannot inject messages** into transcript from hooks
- **Cannot modify** the conversation flow mid-execution

### Extended Thinking / Reasoning Support

From Anthropic provider analysis:

```rust
// Rig's Content enum includes thinking support
enum Content {
    Text { text: String },
    Thinking { thinking: String, signature: Option<String> },  // Extended thinking
    // ...
}
```

**Current state:**
- ✅ Thinking content is **parsed and preserved** in responses
- ✅ Maps to `AssistantContent::Reasoning` internally
- ❌ **No explicit `budget_tokens` parameter** exposed in builder API
- ❌ No way to configure thinking budget at request time
- ⚠️ Thinking treated as standard output within `max_tokens`

**For OpenAI reasoning models:**
- ❓ Need to verify `reasoning_effort` parameter support
- Likely similar situation - parsed but not configurable

### Rig vs Our Requirements

| Requirement | Rig Support | Gap |
|-------------|-------------|-----|
| Event discriminated unions | Partial (Content enum) | Need richer event types |
| Loop control (InjectItems, Compact) | ❌ No | Must build custom |
| Handler chain with mutation | ❌ Hooks are read-only | Must build custom |
| Context compaction | ❌ No | Must build custom |
| MCP-over-HTTP tools | ✅ via rmcp | Good fit |
| Multi-turn with history | ✅ Good | Good fit |
| Reasoning token preservation | ✅ Partial | Missing budget control |
| Provider abstraction | ✅ Excellent | Good fit |
| Docker container management | ❌ Not in scope | Use bollard directly |

### Verdict on Rig

**Suitable for:**
- Provider abstraction layer (if multi-provider needed)
- Tool definition via macros
- Basic agent loops with tool use
- Vector store integration (RAG)

**Not suitable for:**
- Our specific event model
- Fine-grained loop control
- Handler chain with message injection
- Context compaction strategies

**Recommendation:** Use Rig as **optional provider abstraction** but build core agent loop custom.

---

## Alternative Approaches

### Option A: Full Custom Implementation

Build everything from scratch using low-level crates:

```
async-openai + reqwest + bollard + sqlx + axum
```

**Pros:**
- Full control over event model and loop control
- Direct mapping from Python abstractions to Rust enums
- No framework constraints

**Cons:**
- More initial work
- Must implement provider abstraction if needed later

### Option B: Rig + Custom Agent Loop

Use Rig for provider abstraction, build custom agent orchestration:

```
rig-core (providers only) + custom agent loop + bollard + sqlx + axum
```

**Pros:**
- Multi-provider support "for free"
- Tool macro system is nice
- Can still have custom event model

**Cons:**
- May fight Rig's assumptions
- Partial framework adoption can be awkward

### Option C: Rig as Primary Framework

Adapt our design to fit Rig's patterns:

```
rig-core (full) + bollard + sqlx
```

**Pros:**
- Less code to write
- Community support
- Battle-tested patterns

**Cons:**
- Must compromise on event model
- No message injection from hooks
- No context compaction built-in

### Recommendation: **Option A (Full Custom)**

Rationale:
- Python codebase has well-defined algebraic types that map directly to Rust enums
- Loop control semantics (`InjectItems`, `Compact`) are central to our design
- Handler chain with mutation is a core pattern
- Single provider (OpenAI Responses API) simplifies implementation

---

## Rust Building Blocks

### Core Dependencies

| Category | Crate | Purpose |
|----------|-------|---------|
| **Async runtime** | `tokio` | Async execution |
| **Web framework** | `axum` | REST API, WebSocket |
| **Database** | `sqlx` | Compile-time checked PostgreSQL |
| **Migrations** | `sqlx-cli` or `refinery` | Schema migrations |
| **Serialization** | `serde`, `serde_json` | JSON handling |
| **HTTP client** | `reqwest` | API calls |
| **OpenAI** | `async-openai` | OpenAI Responses API |
| **Docker** | `bollard` | Container management |
| **MCP** | `mcp-rust-sdk` | MCP protocol |
| **CLI** | `clap` | Command-line interface |
| **Tracing** | `tracing`, `tracing-subscriber` | Observability |
| **Error handling** | `thiserror`, `anyhow` | Error types |

### Database: SQLx vs SeaORM

| Criteria | SQLx | SeaORM |
|----------|------|--------|
| Compile-time SQL checks | ✅ Yes | Partial |
| Raw SQL support | ✅ Excellent | Good |
| Async | ✅ Native | ✅ Native |
| JSONB handling | ✅ Good | ✅ Good |
| Custom types (composites) | ✅ Excellent | Good |
| Migration tooling | ✅ Built-in | ✅ Built-in |
| Learning curve | Lower | Medium |
| ORM-style queries | ❌ No | ✅ Yes |

**Decision:** SQLx
- Our schema uses PostgreSQL-specific features (RLS, composite types, functions)
- Many queries are complex aggregations better expressed in SQL
- Compile-time checking is valuable for refactoring

### MCP: mcp-rust-sdk Assessment

The official [Anthropic MCP Rust SDK](https://github.com/modelcontextprotocol/rust-sdk) provides:
- Server and client implementations
- Tool definition macros
- Transport abstractions (stdio, HTTP)

**Suitability:** Good for our MCP-over-HTTP tool servers (critic_submit, etc.)

---

## Proposed Architecture

### Crate Structure

```
props-rs/
├── Cargo.toml                      # Workspace
├── crates/
│   ├── agent-core/                 # Port of //agent_core
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── agent.rs            # Agent struct, agentic loop
│   │   │   ├── events.rs           # Event enum (discriminated union)
│   │   │   ├── handler.rs          # Handler trait + chain
│   │   │   ├── loop_control.rs     # LoopDecision, ToolPolicy, ContinueDecision
│   │   │   ├── compaction.rs       # Context compaction strategies
│   │   │   ├── openai.rs           # OpenAI Responses API client
│   │   │   └── transcript.rs       # Transcript management
│   │   └── Cargo.toml
│   │
│   ├── mcp-infra/                  # Port of //mcp_infra
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── server.rs           # MCP server helpers
│   │   │   ├── client.rs           # MCP client wrapper
│   │   │   └── tools.rs            # Tool composition
│   │   └── Cargo.toml
│   │
│   ├── props-core/                 # Port of //props/core
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── db/
│   │   │   │   ├── mod.rs
│   │   │   │   ├── models.rs       # SQLx models
│   │   │   │   ├── queries/        # Query modules by domain
│   │   │   │   └── migrations/     # SQL migrations
│   │   │   ├── agent_types.rs      # AgentType, TypeConfig
│   │   │   ├── registry.rs         # AgentRegistry
│   │   │   ├── handle.rs           # AgentHandle (container lifecycle)
│   │   │   ├── critic/             # Critic agent environment
│   │   │   ├── grader/             # Grader agent environment
│   │   │   └── registry_proxy/     # OCI registry proxy
│   │   └── Cargo.toml
│   │
│   ├── props-backend/              # Port of //props/backend
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── main.rs
│   │   │   ├── app.rs              # Axum router setup
│   │   │   ├── state.rs            # AppState
│   │   │   ├── routes/
│   │   │   │   ├── mod.rs
│   │   │   │   ├── stats.rs
│   │   │   │   ├── runs.rs
│   │   │   │   └── ground_truth.rs
│   │   │   ├── websocket.rs        # WebSocket handlers
│   │   │   └── openapi.rs          # OpenAPI generation
│   │   └── Cargo.toml
│   │
│   └── props-cli/                  # CLI tool
│       ├── src/
│       │   ├── main.rs
│       │   └── commands/
│       └── Cargo.toml
```

### Core Type Definitions

```rust
// agent-core/src/events.rs
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Event {
    SystemText { content: String },
    UserText { content: String },
    AssistantText { content: String },
    Reasoning { content: String },  // Extended thinking
    ToolCall { id: String, name: String, arguments: serde_json::Value },
    ToolCallOutput { id: String, output: String, is_error: bool },
    ApiRequest { request_id: String, model: String },
    Response { request_id: String, usage: Usage },
}

// agent-core/src/loop_control.rs
pub enum LoopDecision {
    NoAction,
    InjectItems(Vec<Item>),
    Abort { reason: String },
    Compact,
}

pub enum ToolPolicy {
    Require(String),
    Forbid(Vec<String>),
    Allow,
}

pub enum ContinueDecision {
    Continue,
    Stop,
}

// agent-core/src/handler.rs
#[async_trait]
pub trait Handler: Send + Sync {
    async fn on_event(&self, event: &Event) -> Result<()> { Ok(()) }
    async fn on_before_sample(&self, transcript: &Transcript) -> Result<ContinueDecision> {
        Ok(ContinueDecision::Continue)
    }
    async fn on_after_sample(&self, response: &Response) -> Result<LoopDecision> {
        Ok(LoopDecision::NoAction)
    }
    async fn on_tool_call(&self, call: &ToolCall) -> Result<ToolCallOutcome>;
}
```

---

## Migration Strategy

### Phase 1: Foundation

1. Set up Rust workspace structure
2. Implement `agent-core` with event types and handler trait
3. Implement OpenAI Responses API client
4. Unit tests for core abstractions

### Phase 2: Database Layer

1. Port SQLx models from SQLAlchemy
2. Migrate existing Alembic migrations to SQLx format
3. Implement query functions
4. Test against existing PostgreSQL database

### Phase 3: MCP Infrastructure

1. Port MCP server utilities using `mcp-rust-sdk`
2. Implement critic/grader tool servers
3. Test MCP-over-HTTP communication

### Phase 4: Agent Orchestration

1. Implement `AgentRegistry` with Docker integration
2. Port `AgentHandle` for container lifecycle
3. Implement critic and grader environments
4. Integration tests with Docker

### Phase 5: Backend API

1. Port FastAPI routes to Axum
2. Implement WebSocket streaming
3. OpenAPI schema generation
4. Frontend compatibility testing

### Phase 6: CLI & Polish

1. Port CLI commands
2. End-to-end testing
3. Performance benchmarking
4. Documentation

### Parallel Running Strategy

- **Shared database:** Both Python and Rust read/write same PostgreSQL
- **Feature flags:** Environment variable to switch implementations
- **Gradual rollout:** Start with read-only endpoints, then writes
- **Comparison testing:** Run both, compare results

---

## Open Questions

### Technical

1. **Reasoning token budget:** How to expose `budget_tokens` for Anthropic extended thinking?
   - Custom request builder needed if not using Rig

2. **OpenAI reasoning preservation:** Does `async-openai` support reasoning token fields?
   - Need to verify Responses API support

3. **Schema migrations:** Keep Alembic or migrate to SQLx?
   - Recommendation: Keep Alembic for Python compatibility during transition

4. **Docker networking:** How to handle container-to-host communication in Rust?
   - `bollard` supports this, need to verify network configuration

### Process

5. **Testing strategy:** How to ensure parity with Python implementation?
   - Snapshot testing? Golden file comparisons?

6. **Rollback plan:** What if Rust implementation has issues?
   - Keep Python running, feature flag switch

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-01-15 | Use SQLx over SeaORM | Better raw SQL support, compile-time checks |
| 2026-01-15 | Build custom agent loop | Rig doesn't support our loop control semantics |
| 2026-01-15 | Use async-openai directly | Single provider, full control |
| | | |

---

## References

- [Rig Framework](https://github.com/0xPlaygrounds/rig) - Rust LLM framework
- [async-openai](https://github.com/64bit/async-openai) - OpenAI Rust client
- [SQLx](https://github.com/launchbadge/sqlx) - Async SQL toolkit
- [Axum](https://github.com/tokio-rs/axum) - Web framework
- [bollard](https://github.com/fussybeaver/bollard) - Docker client
- [mcp-rust-sdk](https://github.com/modelcontextprotocol/rust-sdk) - MCP SDK
- [Anthropic Extended Thinking](https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking)
