# Plan: Agent Loop Inside Container

## Overview

Move the LLM API querying and agent loop from the host scaffold into the Docker container. The container becomes a self-contained agent that talks to an LLM proxy, executes tools via subprocess, and writes results to Postgres.

**Benefit:** Prompt optimizer agents can author entire agentic systems - arbitrary LLM pipelines, workflows, subagents, classifiers, loops, tool calls, analysis, dispatch. Not limited to append-only single-agent patterns.

## Architecture

### Current

```
Host Scaffold                      Container
─────────────                      ─────────
AgentEnvironment
├─ Create temp DB user
├─ Start HTTP MCP server
└─ Create container ─────────────> Container starts
                                   /init → stdout = system prompt
Agent.run() (host-side)
├─ Sample LLM (OpenAI API)  ◄───── Control on host
├─ Route tool calls:
│   ├─ docker_exec ──────────────> props critic-agent ...
│   └─ critic_submit (HTTP MCP)
└─ DatabaseEventHandler
    └─> Write events to DB
```

### Proposed

```
Host Scaffold                      Container
─────────────                      ─────────
AgentEnvironment (simplified)
├─ Create temp DB user
├─ Start LLM proxy (rspcache)
├─ [Subagent spawn endpoint for PO/PI]
└─ Create container ─────────────> Container starts (CMD)
                                   ├─ props snapshot fetch (from Postgres)
                                   ├─ Construct prompt, start agent loop
                                   ├─ Calls LLM via proxy (OPENAI_BASE_URL)
                                   ├─ Tool calls = subprocess (exec)
                                   ├─ Writes to Postgres directly
                                   └─ Exits 0 on success
```

## Decisions

### Container Interface

| Aspect     | Decision                                           |
| ---------- | -------------------------------------------------- |
| Entrypoint | Standard Dockerfile `CMD` (not `/init` convention) |
| Completion | Exit code 0 = success, non-zero = failure          |
| Abort      | Host hard-kills container (`docker kill`)          |
| Logs       | Capture and store container logs (see below)       |

### LLM Proxy

| Aspect            | Decision                                                               |
| ----------------- | ---------------------------------------------------------------------- |
| Env vars          | `OPENAI_BASE_URL`, `OPENAI_API_KEY` (Responses API compatible)         |
| Token             | Same as existing Postgres password (`agent_{uuid}`)                    |
| Token validation  | Via Postgres (lookup agent_runs)                                       |
| Model restriction | One model per run, enforced by proxy                                   |
| Cost budget       | Per-agent, tracked via parent-child in agent_runs                      |
| Streaming         | Not supported (simplifies logging/budgeting)                           |
| Implementation    | Custom proxy (like registry_proxy), queries agent_runs for auth/budget |

### Tool Execution

| Aspect          | Decision                                                                |
| --------------- | ----------------------------------------------------------------------- |
| Mechanism       | Subprocess inside container (no docker_exec from host)                  |
| Tool schema     | Generic `exec` tool taking command array                                |
| Timeouts/limits | Handle output truncation, timeouts - possibly reuse MCP local exec code |
| Critique tools  | Bundle existing `props critic-agent` CLI (insert-issue, submit, etc.)   |

### Agent Loop

| Aspect        | Decision                                                                      |
| ------------- | ----------------------------------------------------------------------------- |
| Location      | Inside container, part of props package                                       |
| API style     | OpenAI Responses API                                                          |
| Max turns     | Don't enforce (cost/timeout are sufficient)                                   |
| Context limit | Container's responsibility; compaction is future work                         |
| Completion    | "submit" tool validates → returns errors (agent retries) or succeeds → exit 0 |
| Code reuse    | Could use `agent_core.Agent` with exec tool, or simpler standalone loop       |

### Grader Daemon Mode

| Aspect        | Decision                                                       |
| ------------- | -------------------------------------------------------------- |
| Lifecycle     | Container keeps running (doesn't exit between grading batches) |
| Wake/sleep    | Internal loop uses pg_notify directly from container           |
| Drift handler | Works as-is - pg_notify is accessible from inside container    |
| Timeout       | No timeout for daemon graders (eternal)                        |

### Subagent Spawning

| Aspect          | Decision                                                            |
| --------------- | ------------------------------------------------------------------- |
| Spawn           | External HTTP endpoints by agent type: `/run_critic`, `/run_grader` |
| Status query    | Direct Postgres query (no external call needed)                     |
| Results/logs    | Direct Postgres query                                               |
| Cost accounting | Counts against parent's budget                                      |
| Limits          | No explicit concurrency/spawn limits; cost + timeout sufficient     |
| Wait helpers    | In-container tools like "wait_until_graded" can poll DB internally  |

**Spawn API sketch:**

```
POST /run_critic
{
  "image": "critic@sha256:...",
  "example": {"snapshot_slug": "...", "example_kind": "...", ...},
  "model": "gpt-4o"
}
→ {"agent_run_id": "..."}  # Returns immediately, agent runs async
```

Only `/run_critic` needed - daemon grader automatically grades all critics.

**Authentication:**

- Part of existing FastAPI backend (`props/backend/`)
- Backend checks source:

  ```
  # Agent (from container network) - must provide credentials
  curl -u "agent_<uuid>:<password>" http://backend:8000/api/run_critic ...

  # Human (from localhost) - no credentials needed
  curl http://localhost:8000/api/run_critic ...
  ```

- FastAPI dependency checks request:
  - From localhost/127.0.0.1 → human mode, `parent_run_id` = NULL
  - From container network → require Basic auth, validate against Postgres, set `parent_run_id`
- Simple IP check is sufficient for personal infra (not exposed to internet)

Spawn is **non-blocking** - returns immediately with agent_run_id. PO can spawn multiple critics in parallel.

**Wait helpers (in-container, not external):**

- `wait_for_agent(agent_run_id)` - polls `agent_runs` until agent completes
- `wait_for_grading(critic_run_id)` - polls until daemon grader has graded this critic
- Implemented as CLI tools: `props agent wait <id>`, `props agent wait-graded <critic_id>`
- No external endpoint needed - just DB polling

**Typical PO workflow:**

1. `POST /run_critic` → critic_run_id (returns immediately)
2. `props agent wait <critic_run_id>` (blocks until critic done)
3. `props agent wait-graded <critic_run_id>` (blocks until daemon grader grades it)
4. Query metrics from DB

### Observability

| Aspect         | Decision                                                     |
| -------------- | ------------------------------------------------------------ |
| LLM calls      | Logged by LLM proxy (all requests/responses)                 |
| Container logs | Capture stdout/stderr, store in agent_runs or separate table |
| Access         | PO/PI agents and humans can query logs from DB               |
| Events table   | Deprecated - LLM proxy logs + container logs replace it      |

### Security

| Aspect            | Decision                                              |
| ----------------- | ----------------------------------------------------- |
| Syscall filtering | None (containers are isolated enough)                 |
| Network           | Only LLM proxy, Postgres, subagent endpoint reachable |
| Registry          | PO/PI can push new images by digest                   |

## Implementation Sketch

### Critic Agent (Container Side)

```python
#!/usr/bin/env python3
"""Critic agent - runs inside container."""
import os
import subprocess
import sys
from openai import OpenAI

def main():
    # 1. Fetch snapshot (uses PG* env vars automatically)
    snapshot_slug = os.environ["SNAPSHOT_SLUG"]
    subprocess.run(["props", "snapshot", "fetch", snapshot_slug], check=True)

    # 2. Construct prompt (reuses existing rendering)
    system_prompt = render_critic_prompt(
        snapshot_slug=snapshot_slug,
        example_kind=os.environ["EXAMPLE_KIND"],
        files_hash=os.environ.get("FILES_HASH"),
    )

    # 3. Define tools
    tools = [{
        "type": "function",
        "function": {
            "name": "exec",
            "description": "Execute a command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["command"]
            }
        }
    }]

    # 4. Agent loop
    client = OpenAI(
        base_url=os.environ["OPENAI_BASE_URL"],
        api_key=os.environ["OPENAI_API_KEY"],
    )

    messages = [{"role": "system", "content": system_prompt}]

    while True:
        response = client.responses.create(
            model=os.environ["MODEL"],
            input=messages,
            tools=tools,
        )

        # Handle response, execute tools via subprocess
        # Submit tool: runs `props critic-agent submit ...`
        #   - Returns validation errors → agent sees output, can fix and retry
        #   - Succeeds → exit 0

    sys.exit(0)

if __name__ == "__main__":
    main()
```

### Host Scaffold (Simplified)

```python
async def run_critic(snapshot_slug: str, example: Example) -> AgentRunResult:
    async with TempDatabaseUser() as db_user:
        # Start container (no volume mount - agent fetches snapshot itself)
        container = await start_container(
            image=example.critic_image,
            env={
                "OPENAI_BASE_URL": rspcache_url,
                "OPENAI_API_KEY": db_user.password,  # Same token as PG
                "PGHOST": ..., "PGUSER": db_user.name, "PGPASSWORD": db_user.password, ...
                "SNAPSHOT_SLUG": snapshot_slug,
                "EXAMPLE_KIND": example.kind,
                "FILES_HASH": example.files_hash,
                "MODEL": "gpt-4o",
            },
        )

        # Wait for completion
        exit_code = await container.wait()
        logs = await container.logs()

        # Store logs in DB, determine status
        return AgentRunResult(
            status="completed" if exit_code == 0 else "failed",
            logs=logs,
        )
```

## Code Changes

### To Remove

| File/Component                                | Reason                                              |
| --------------------------------------------- | --------------------------------------------------- |
| `critic/submit_server.py`                     | `CriticSubmitServer` replaced by CLI + exit 0       |
| `grader/submit_server.py`                     | `GraderSubmitServer` replaced by CLI + exit 0       |
| `prompt_optimize/prompt_optimizer.py`         | `PromptEvalServer` class replaced by spawn endpoint |
| `agent_handle.py`                             | Host-side agent loop no longer needed               |
| `db_event_handler.py`                         | `DatabaseEventHandler` - events table deprecated    |
| Events table                                  | Replaced by LLM proxy logs + container logs         |
| HTTP MCP server startup in `AgentEnvironment` | No longer needed                                    |
| `docker_exec` tool from host                  | Tools run via subprocess inside container           |

### To Simplify

| File/Component                                 | Change                                                                       |
| ---------------------------------------------- | ---------------------------------------------------------------------------- |
| `agent_setup.py` / `AgentEnvironment`          | Remove MCP server, just: create DB user, start container, wait, capture logs |
| `agent_registry.py` / `AgentRegistry`          | Simplified - just calls spawn endpoint                                       |
| `docker_env.py` / `PropertiesDockerCompositor` | Simplify or remove - less orchestration needed                               |
| Container images                               | Change from `/init` producing prompt to `CMD` running full agent             |

### To Add

| Component                   | Purpose                                                                      |
| --------------------------- | ---------------------------------------------------------------------------- |
| **LLM proxy**               | Token validation, request/response logging, cost tracking, model enforcement |
| **Spawn endpoint**          | `/run_critic` HTTP endpoint for PO to spawn critics                          |
| **In-container agent loop** | OpenAI Responses API client, exec tool, submit handling                      |
| **Wait CLI tools**          | `props agent wait <id>`, `props agent wait-graded <critic_id>`               |
| **Log capture**             | Store container stdout/stderr in DB                                          |

### To Keep (unchanged or minor changes)

| Component                 | Notes                                           |
| ------------------------- | ----------------------------------------------- |
| `props critic-agent` CLI  | Already exists, used by agent via subprocess    |
| `props grader-agent` CLI  | Already exists, used by agent via subprocess    |
| `props snapshot fetch`    | Already exists, used by agent to fetch snapshot |
| `grader/daemon.py`        | Keep, but agent loop moves inside container     |
| `grader/drift_handler.py` | Keep, runs inside container now                 |
| `noop_classifier/`        | Keep as-is (specialized utility)                |
| Database models, RLS      | Keep as-is                                      |
| Registry proxy            | Keep as-is                                      |

## Migration Path

### Phase 1: LLM Proxy

1. Build custom LLM proxy (similar to registry_proxy):
   - Token validation via Postgres (agent_runs lookup)
   - Request/response logging to DB
   - Cost tracking per agent_run_id (sum up parent chain)
   - Model enforcement (only allow assigned model)
   - No streaming

### Phase 2: Simple Critic

1. Write minimal agent loop in props package
2. Update critic container image to use `CMD` running agent loop
3. Simplify `AgentEnvironment`:
   - Remove HTTP MCP server startup
   - Start container, wait for exit, capture logs
4. Test with existing critic prompts

### Phase 3: Grader

1. Update grader to run loop internally with pg_notify
2. Daemon mode: container stays running, internal sleep/wake

### Phase 4: Prompt Optimizer

1. Add subagent spawn endpoint
2. Update PO to use new architecture
3. Give PO access to container logs

### Phase 5: Cleanup

1. Remove deprecated code paths
2. Drop events table (or archive)
3. Update dashboard to use LLM proxy logs

## Resolved

### HTTP MCP Servers

| Server                 | Location                              | Tools                                        | Fate                                                |
| ---------------------- | ------------------------------------- | -------------------------------------------- | --------------------------------------------------- |
| **CriticSubmitServer** | `critic/submit_server.py`             | `submit`, `report_failure`                   | **Kill** - replaced by CLI + exit 0                 |
| **GraderSubmitServer** | `grader/submit_server.py`             | `grader_submit`, `report_failure`            | **Kill** - replaced by CLI + exit 0                 |
| **PromptEvalServer**   | `prompt_optimize/prompt_optimizer.py` | `run_critic`, `run_grader`, `report_failure` | **Transform** → external subagent spawn endpoint    |
| **ClassifierServer**   | `noop_classifier/classifier.py`       | `submit_classifications`                     | **Keep** - specialized utility, not core agent flow |

### Snapshot Fetching

**Decision:** Keep `props snapshot fetch` inside container.

- Simpler - no host-side change needed
- Already works
- Agent runs `props snapshot fetch <slug>` as part of init, uses PG\* env vars

### Cost Budget Propagation

**Decision:** LLM proxy queries `agent_runs.parent_id` to compute budget tree.

- Parent spawns child → child's cost counts against parent's budget
- Proxy sums costs up the parent chain on each request
- No special token encoding needed - just query the table

## Open Questions

### 1. Log Capture Guarantee

We want to store container logs for observability.

**Question:** How do we guarantee logs are captured even if container crashes or is killed?

Options:

- Docker logging driver writes to file, host reads after container stops
- Sidecar container tails logs in real-time
- Container writes to mounted volume
- Accept some log loss on hard crashes

Leaning toward: Docker logging driver + read on container stop. Accept that hard crashes may lose final lines.

### 2. Exec Tool Implementation

Need: command array, timeout, output truncation, stderr handling.

**Question:** Reuse existing MCP local exec code, or write simpler standalone?

The MCP local exec in `mcp_infra` handles:

- Output capping (`MAX_BYTES_CAP`)
- Timeout
- Stderr capture
- Working directory

Could extract the subprocess logic without MCP framing.

### 3. Interactive Agents (Future)

Current plan: exit 0 = done.

**Question:** How will interactive agents work later?

Defer for now. Options when needed:

- WebSocket/streaming for bidirectional communication
- Agent polls for user input from DB
- Separate interactive agent mode with different lifecycle
