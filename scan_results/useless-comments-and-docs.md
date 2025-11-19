# Useless Comments and Documentation Scan Report

## Executive Summary

- **Total Python Files Scanned**: 730
- **Total Comments Found**: 10048
- **Potentially Useless Comments**: 241
- **Uselessness Rate**: 2.4%

## Breakdown by Category

- **DUPLICATE**: 27 comments
- **OBVIOUS**: 214 comments

---

## Detailed Findings

### adgn/src/adgn/agent/agent.py

**1 issues found**

#### Issue 1: Line 284 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Parse arguments strictly; invalid JSON/object shape is a hard error.
```

**Context Before:**
```python

            # Invoke via Policy Gateway client; do not swallow exceptions.
```

**Context After:**
```python
            args: dict[str, Any] = {}
            if args_json:
                val = json.loads(args_json)
```

---

### adgn/src/adgn/agent/cli.py

**3 issues found**

#### Issue 1: Line 103 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set root logger level to DEBUG
```

**Context Before:**
```python
    """Configure logging with DEBUG level on console for UI commands to show OpenAI traffic."""
    configure_logging()
```

**Context After:**
```python
    logging.getLogger().setLevel(logging.DEBUG)
    # Set console handler to DEBUG
    for h in logging.getLogger().handlers:
```

---

#### Issue 2: Line 105 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set console handler to DEBUG
```

**Context Before:**
```python
    # Set root logger level to DEBUG
    logging.getLogger().setLevel(logging.DEBUG)
```

**Context After:**
```python
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler):
            h.setLevel(logging.DEBUG)
```

---

#### Issue 3: Line 72 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the first available TCP port >= start on host.

Best-effort check by binding a socket briefly; race is acceptable in dev.
```

**Context After:**
```python
    """Return the first available TCP port >= start on host.

    Best-effort check by binding a socket briefly; race is acceptable in dev.
    """
    for p in range(start, start + max_tries):
```

---

### adgn/src/adgn/agent/mcp_bridge/server.py

**3 issues found**

#### Issue 1: Line 215 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: close statement

**Comment:**
```
Close the infrastructure
```

**Context Before:**
```python
        agent = self._agents[agent_id].agent
        if agent is not None:
```

**Context After:**
```python
            await agent.running.close()

        # Remove from registry
```

---

#### Issue 2: Line 260 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the response
```

**Context Before:**
```python
            await compositor_app(request.scope, request.receive, send)
```

**Context After:**
```python
            response_headers = {k.decode(): v.decode() for k, v in headers}
            body = b"".join(body_parts)
            return Response(content=body, status_code=status_code, headers=response_headers)
```

---

#### Issue 3: Line 92 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set notifier callback for registry changes.

The notifier is called with a resource URI when agents are created/deleted.
```

**Context Before:**
```python
        self._notifier: Callable[[str], Awaitable[None]] | None = None
```

**Context After:**
```python
        """Set notifier callback for registry changes.

        The notifier is called with a resource URI when agents are created/deleted.
        """
        self._notifier = notifier
```

---

### adgn/src/adgn/agent/mcp_bridge/servers/agents.py

**3 issues found**

#### Issue 1: Line 801 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return agent brief with the created agent's ID
```

**Context Before:**
```python
        await registry.create_agent(agent_id)
```

**Context After:**
```python
        return AgentBrief(id=agent_id)

    @server.tool()
```

---

#### Issue 2: Line 395 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Each approval is a separate MCP TextResourceContents block.

Crashes if any agent fails (no exception swallowing).
```

**Context Before:**
```python
        description="Global mailbox: all pending approvals across all agents (returns multiple content blocks)",
    )
```

**Context After:**
```python
        """Each approval is a separate MCP TextResourceContents block.

        Crashes if any agent fails (no exception swallowing).
        """
        content_blocks: list[mcp_types.TextResourceContents] = []
```

---

#### Issue 3: Line 737 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set the active policy text for an agent.

Directly sets the policy source code after validation via the
approval policy admin server. The policy is se
```

**Context Before:**
```python

    @server.tool()
```

**Context After:**
```python
        """Set the active policy text for an agent.

        Directly sets the policy source code after validation via the
        approval policy admin server. The policy is self-checked before
        activation to ensure it's valid Python and can execute properly.
```

---

### adgn/src/adgn/agent/persist/sqlite.py

**2 issues found**

#### Issue 1: Line 250 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a mapping of agent_id -> last activity timestamp (UTC) or None.

Activity considers any of: event ts, run finished_at, run started_at, or
agent
```

**Context Before:**
```python
            )
```

**Context After:**
```python
        """Return a mapping of agent_id -> last activity timestamp (UTC) or None.

        Activity considers any of: event ts, run finished_at, run started_at, or
        agent created_at as a fallback, taking the maximum.
        """
```

---

#### Issue 2: Line 293 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return (content, id) of the latest approval policy for the agent, or None.
```

**Context Before:**
```python

    # ---- Approval policy (per-agent) ---------------------------------------
```

**Context After:**
```python
        """Return (content, id) of the latest approval policy for the agent, or None."""
        async with (
            self._db_connection() as db,
            db.execute(
                """
```

---

### adgn/src/adgn/agent/presets.py

**1 issues found**

#### Issue 1: Line 12 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the default XDG-compliant presets directory.

Uses platformdirs to resolve the user configuration directory for app "adgn",
then appends the "p
```

**Context After:**
```python
    """Return the default XDG-compliant presets directory.

    Uses platformdirs to resolve the user configuration directory for app "adgn",
    then appends the "presets" subfolder.
    """
```

---

### adgn/src/adgn/agent/reducer.py

**1 issues found**

#### Issue 1: Line 95 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Anything that is not one of the concrete decision classes is a programming error
```

**Context Before:**
```python
                elif skip_value != dec.skip_sampling:
                    raise RuntimeError(f"Conflicting skip_sampling flags in Continue decisions: {decisions!r}")
```

**Context After:**
```python
            if not isinstance(dec, Continue | Abort):
                raise TypeError(f"Handler {h!r} returned invalid decision type: {type(dec).__name__} ({dec!r})")
            decisions.append(dec)
```

---

### adgn/src/adgn/agent/runtime/auto_attach.py

**1 issues found**

#### Issue 1: Line 30 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a shallow copy of cfg without the default auto-attached servers.

Only user-configured servers remain. This avoids persisting ephemeral/runtime
```

**Context After:**
```python
    """Return a shallow copy of cfg without the default auto-attached servers.

    Only user-configured servers remain. This avoids persisting ephemeral/runtime
    infrastructure servers like UI, approval policy, runtime exec, or resources.
    """
```

---

### adgn/src/adgn/agent/runtime/images.py

**1 issues found**

#### Issue 1: Line 9 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the Docker image tag used for runtime + policy evaluation flows.
```

**Context After:**
```python
    """Return the Docker image tag used for runtime + policy evaluation flows."""
    img = os.getenv("ADGN_RUNTIME_IMAGE")
    if img:
        return img
    return fallback
```

---

### adgn/src/adgn/agent/runtime/local_runtime.py

**1 issues found**

#### Issue 1: Line 125 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set persist handler on session
```

**Context Before:**
```python
        all_handlers = list(handlers) + self._extra_handlers
```

**Context After:**
```python
        sess.set_persist_handler(persist_handler)

        # Compose base system text and dynamic instruction provider
```

---

### adgn/src/adgn/agent/runtime/registry.py

**1 issues found**

#### Issue 1: Line 83 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set UI components for backward compatibility
```

**Context Before:**
```python

        agent_runtime = AgentRuntime(agent_id=agent_id, running=running, runtime=runtime)
```

**Context After:**
```python
        agent_runtime._ui_manager = conn_mgr_out
        agent_runtime._ui_bus = ui_bus_out
        self._items[agent_id] = agent_runtime
```

---

### adgn/src/adgn/agent/server/app.py

**1 issues found**

#### Issue 1: Line 218 [DOCSTRING]

**Assessment**: OBVIOUS: get statement

**Comment:**
```
Get session from container, raising AgentSessionNotReadyError if not initialized.
```

**Context Before:**
```python
            raise AgentNotFoundError(agent_id) from e
```

**Context After:**
```python
        """Get session from container, raising AgentSessionNotReadyError if not initialized."""
        if container.runtime.session is None:
            raise AgentSessionNotReadyError(agent_id)
        return container.runtime.session
```

---

### adgn/src/adgn/agent/server/history.py

**1 issues found**

#### Issue 1: Line 59 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
If structured is a mapping, strictly parse the tagged union. If it is
```

**Context Before:**
```python
            if isinstance(structured, BaseModel):
                structured = structured.model_dump(mode="json")
```

**Context After:**
```python
            # not a tagged UI payload, this will raise; we do not auto-heal or try to
            # coerce non-conformant shapes here.
            if isinstance(structured, dict):
```

---

### adgn/src/adgn/agent/server/mcp_routing.py

**1 issues found**

#### Issue 1: Line 139 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the response
```

**Context Before:**
```python
            await backend_app(request.scope, request.receive, send)
```

**Context After:**
```python
            response_headers = {k.decode(): v.decode() for k, v in headers}
            body = b"".join(body_parts)
            return Response(content=body, status_code=status_code, headers=response_headers)
```

---

### adgn/src/adgn/agent/server/mode_handler.py

**1 issues found**

#### Issue 1: Line 38 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return Continue with RequireAny policy AND the notification message
```

**Context Before:**
```python

        if msg is not None:
```

**Context After:**
```python
            return Continue(RequireAny(), inserts_input=(msg,))

        # No notifications - just require tool use
```

---

### adgn/src/adgn/agent/server/runtime.py

**2 issues found**

#### Issue 1: Line 204 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set notifier callback for session state changes (for MCP resource updates).
```

**Context Before:**
```python
            self._session_state_notifier()
```

**Context After:**
```python
        """Set notifier callback for session state changes (for MCP resource updates)."""
        self._session_state_notifier = notifier

    async def broadcast_status(self, live: bool, active_run_id) -> None:
        # No-op: WebSocket status broadcasts removed
```

---

#### Issue 2: Line 310 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set notifier callback for UI state changes (for MCP resource updates).
```

**Context Before:**
```python
        self._persist_handler = handler
```

**Context After:**
```python
        """Set notifier callback for UI state changes (for MCP resource updates)."""
        self._ui_state_notifier = notifier

    async def _apply_ui_event(self, evt: ServerMessage) -> None:
        self.ui_state = reduce_ui_state(self.ui_state, evt)
```

---

### adgn/src/adgn/agent/server/system_message.py

**1 issues found**

#### Issue 1: Line 50 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return composed system message for HTML UI agent.

Pure function; no environment or storage reads. Update constants above to
change behavior.
```

**Context After:**
```python
    """Return composed system message for HTML UI agent.

    Pure function; no environment or storage reads. Update constants above to
    change behavior.
    """
```

---

### adgn/src/adgn/git_commit_ai/cli.py

**2 issues found**

#### Issue 1: Line 508 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return passthru args excluding staging flags that should not be forwarded to final commit.
```

**Context After:**
```python
    """Return passthru args excluding staging flags that should not be forwarded to final commit."""
    return [arg for arg in passthru if arg not in ("-a", "--all")]


def _validate_no_message_flag(passthru: list[str]) -> None:
```

---

#### Issue 2: Line 631 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return (message, cached). Runs MiniCodex and pre-commit where applicable.
```

**Context After:**
```python
    """Return (message, cached). Runs MiniCodex and pre-commit where applicable."""
    if (msg := inp.cache.get(inp.key)) is not None:
        return msg, True

    ai_task: asyncio.Task[str] = asyncio.create_task(
```

---

### adgn/src/adgn/git_commit_ai/core.py

**3 issues found**

#### Issue 1: Line 61 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return True if '-a' or '--all' flags are present.
```

**Context After:**
```python
    """Return True if '-a' or '--all' flags are present."""
    return ("-a" in passthru) or ("--all" in passthru)


# Unified mapping for status letters to human text (commit template rendering)
```

---

#### Issue 2: Line 80 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a minimal porcelain-like status using pygit2 flags.

Prints lines of the form 'XY path' and '?? path' for untracked.
```

**Context After:**
```python
    """Return a minimal porcelain-like status using pygit2 flags.

    Prints lines of the form 'XY path' and '?? path' for untracked.
    """
    out: list[str] = []
```

---

#### Issue 3: Line 125 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return up to n raw commit log entries (short hash + full message).
```

**Context After:**
```python
    """Return up to n raw commit log entries (short hash + full message)."""
    walker = repo.walk(repo.head.target)
    walker.simplify_first_parent()

    out: list[str] = []
```

---

### adgn/src/adgn/inop/engine/models.py

**1 issues found**

#### Issue 1: Line 131 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Validate that commit is a full 40-character SHA hash.
```

**Context Before:**
```python
    @field_validator("commit")
    @classmethod
```

**Context After:**
```python
        """Validate that commit is a full 40-character SHA hash."""
        if len(v) != COMMIT_SHA_LEN:
            raise ValueError(f"Commit must be a full {COMMIT_SHA_LEN}-character SHA hash, got {len(v)} characters: {v}")
        if not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError(f"Commit must be a valid hex SHA hash: {v}")
```

---

### adgn/src/adgn/inop/prompting/prompt_engineer.py

**1 issues found**

#### Issue 1: Line 29 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a human-language description of the feedback provider.
```

**Context Before:**
```python
        ...
```

**Context After:**
```python
        """Return a human-language description of the feedback provider."""
        ...


class FullRolloutsFeedbackProvider(FeedbackProvider):
```

---

### adgn/src/adgn/inop/runners/base.py

**1 issues found**

#### Issue 1: Line 31 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up the runner for a specific task.

Args:
    task: Task to execute
    task_type_config: Configuration from task type (setup, grading, etc.)
```

**Context Before:**
```python

    @abstractmethod
```

**Context After:**
```python
        """Set up the runner for a specific task.

        Args:
            task: Task to execute
            task_type_config: Configuration from task type (setup, grading, etc.)
```

---

### adgn/src/adgn/inop/runners/claude_runner.py

**1 issues found**

#### Issue 1: Line 66 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up workspace for task execution.

Args:
    task: Task to execute
    task_type_config: Configuration from task type
```

**Context Before:**
```python
        # necessary for most use cases.
```

**Context After:**
```python
        """Set up workspace for task execution.

        Args:
            task: Task to execute
            task_type_config: Configuration from task type
```

---

### adgn/src/adgn/inop/runners/containerized_claude.py

**2 issues found**

#### Issue 1: Line 239 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up environment variables for wrapper script execution
```

**Context Before:**
```python
        self._ensure_container_ready()
```

**Context After:**
```python
        c = self._container_or_raise()
        wrapper_env: dict[str, str] = {"CLAUDE_CONTAINER_ID": str(c.id), "DOCKER_BINARY": self._docker_path}
```

---

#### Issue 2: Line 578 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up or refresh any container-dependent wrapper state.

Currently a no-op: we use a committed host-side wrapper script that only
needs the container
```

**Context Before:**
```python
        self._logger.info("Remounted container running", container_id=c.id, status=c.status)
```

**Context After:**
```python
        """Set up or refresh any container-dependent wrapper state.

        Currently a no-op: we use a committed host-side wrapper script that only
        needs the container ID and docker binary provided via environment in
        receive_messages(). This hook is kept for future extensibility.
```

---

### adgn/src/adgn/llm/sysrw/extract_common.py

**3 issues found**

#### Issue 1: Line 35 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return True if system text (string or list-of-parts) contains tools header.
```

**Context After:**
```python
    """Return True if system text (string or list-of-parts) contains tools header."""
    if isinstance(system, str):
        return TOOLS_HEADER in system
    if system is None:
        return False
```

---

#### Issue 2: Line 82 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return embedded provider payload dict when present (Crush wire logs).
```

**Context After:**
```python
    """Return embedded provider payload dict when present (Crush wire logs)."""
    p = obj.get("payload")
    return p if isinstance(p, dict) else None
```

---

#### Issue 3: Line 93 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Write a 2D list of JSON-serializable dicts to a JSONL file and emit a summary.

- results: list of batches (each batch is a list of dict records)
- ou
```

**Context After:**
```python
    """Write a 2D list of JSON-serializable dicts to a JSONL file and emit a summary.

    - results: list of batches (each batch is a list of dict records)
    - output_path: destination file path
    - event: event name to include in the summary line printed to stdout
```

---

### adgn/src/adgn/llm/sysrw/leaderboard.py

**2 issues found**

#### Issue 1: Line 364 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return (ci95_halfwidth, lcb, ucb) from a typed summary.

Accepts legacy numeric ci95 or a dict with lcb/ucb. If only bounds are
available, derives the
```

**Context After:**
```python
    """Return (ci95_halfwidth, lcb, ucb) from a typed summary.

    Accepts legacy numeric ci95 or a dict with lcb/ucb. If only bounds are
    available, derives the half-width as max(|mean-lcb|, |ucb-mean|). Falls back
    to 0.0 when nothing usable is present.
```

---

#### Issue 2: Line 394 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return concrete (lcb, ucb), using mean±ci95 if bounds are missing.
```

**Context After:**
```python
    """Return concrete (lcb, ucb), using mean±ci95 if bounds are missing."""
    lcb_val = lcb if lcb is not None else (mean - ci95)
    ucb_val = ucb if ucb is not None else (mean + ci95)
    return (lcb_val, ucb_val)
```

---

### adgn/src/adgn/llm/sysrw/run_eval.py

**1 issues found**

#### Issue 1: Line 628 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return combined records for saving
```

**Context Before:**
```python
                return None, None
```

**Context After:**
```python
            sample_record = EvalSampleRecord(
                request=sample_request,
                response=sample.model_dump(),
```

---

### adgn/src/adgn/llm/sysrw/templates/__init__.py

**1 issues found**

#### Issue 1: Line 77 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return mapping of template content (full text) -> relative template name.

Values look like "current_effective_template.txt" or "proposals/foo.txt".
```

**Context After:**
```python
    """Return mapping of template content (full text) -> relative template name.

    Values look like "current_effective_template.txt" or "proposals/foo.txt".
    """
    mapping: dict[str, str] = {}
```

---

### adgn/src/adgn/mcp/_shared/calltool.py

**1 issues found**

#### Issue 1: Line 10 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return JSON-serializable structured content.

Keep BaseModel instances intact so downstream typed adapters can consume them.
```

**Context After:**
```python
    """Return JSON-serializable structured content.

    Keep BaseModel instances intact so downstream typed adapters can consume them.
    """
    return sc
```

---

### adgn/src/adgn/mcp/_shared/container_session.py

**1 issues found**

#### Issue 1: Line 95 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return dict format to match expected API
```

**Context Before:**
```python
    container = await client.containers.create(container_config)
    await container.start()
```

**Context After:**
```python
    return {"Id": container._id, "Name": getattr(container, "_name", "")}
```

---

### adgn/src/adgn/mcp/_shared/json_helpers.py

**1 issues found**

#### Issue 1: Line 9 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Async read a line of JSON from a stream and return as dict or None.

Ensures type safety by validating the parsed result is a dict.
```

**Context After:**
```python
    reader: asyncio.StreamReader, read_timeout: float | None = None
) -> dict[str, Any] | None:
    """Async read a line of JSON from a stream and return as dict or None.

    Ensures type safety by validating the parsed result is a dict.
```

---

### adgn/src/adgn/mcp/_shared/naming.py

**5 issues found**

#### Issue 1: Line 12 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the fully-qualified tool name for the aggregated compositor surface.
```

**Context After:**
```python
    """Return the fully-qualified tool name for the aggregated compositor surface."""
    if not server:
        raise ValueError(f"Invalid MCP server name: {server!r}")
    if not tool:
        raise ValueError("Tool name must be non-empty")
```

---

#### Issue 2: Line 21 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the namespaced prefix for all tools exposed by ``server``.
```

**Context After:**
```python
    """Return the namespaced prefix for all tools exposed by ``server``."""
    if not server:
        raise ValueError("Server name must be non-empty")
    return f"{server}_"
```

---

#### Issue 3: Line 28 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return True when ``name`` refers to the specified server/tool.
```

**Context After:**
```python
    """Return True when ``name`` refers to the specified server/tool."""
    return name == build_mcp_function(server, tool)


def server_matches(name: str, *, server: str) -> bool:
```

---

#### Issue 4: Line 33 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return True when ``name`` belongs to the specified server.
```

**Context After:**
```python
    """Return True when ``name`` belongs to the specified server."""
    return name.startswith(tool_prefix(server))


def resource_prefix(server: str) -> str:
```

---

#### Issue 5: Line 38 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the namespaced prefix (without trailing underscore) for resources.
```

**Context After:**
```python
    """Return the namespaced prefix (without trailing underscore) for resources."""
    if not server:
        raise ValueError("Server name must be non-empty")
    return server
```

---

### adgn/src/adgn/mcp/_shared/resources.py

**1 issues found**

#### Issue 1: Line 12 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the single text part from a ReadResourceResult or raise.

- Requires exactly one TextResourceContents part.
- Raises RuntimeError if zero or mu
```

**Context After:**
```python
    """Return the single text part from a ReadResourceResult or raise.

    - Requires exactly one TextResourceContents part.
    - Raises RuntimeError if zero or multiple text parts are present, or if any
      non-text part is present.
```

---

### adgn/src/adgn/mcp/approval_policy/server.py

**1 issues found**

#### Issue 1: Line 158 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return subscription set for current session context.
```

**Context Before:**
```python
        mcp_server = self._mcp_server
```

**Context After:**
```python
            """Return subscription set for current session context."""
            return self._session_subscriptions[mcp_server.request_context.session]

        @mcp_server.subscribe_resource()
        async def _subscribe(uri: AnyUrl):
```

---

### adgn/src/adgn/mcp/compositor/server.py

**4 issues found**

#### Issue 1: Line 157 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return per-child status entries keyed by child name.

Entries are discriminated-union ServerEntry values keyed by mount name.
```

**Context Before:**
```python
    # No child_* helpers; callers should use server_entries()/sampling_snapshot()
```

**Context After:**
```python
        """Return per-child status entries keyed by child name.

        Entries are discriminated-union ServerEntry values keyed by mount name.
        """
        # Phase 1: capture init results and schedule tool enumeration concurrently
```

---

#### Issue 2: Line 209 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a SamplingSnapshot mirroring the manager's shape, aggregated over children.
```

**Context Before:**
```python
        return per_name
```

**Context After:**
```python
        """Return a SamplingSnapshot mirroring the manager's shape, aggregated over children."""
        entries_map = await self.server_entries()
        return SamplingSnapshot(ts=datetime.now(UTC).isoformat(), servers=entries_map)

    async def mount_specs(self) -> dict[str, MCPServerTypes]:
```

---

#### Issue 3: Line 214 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a snapshot of current mount specs keyed by name.

Only includes spec-based mounts; in-process mounts (spec=None) are excluded.
```

**Context Before:**
```python
        return SamplingSnapshot(ts=datetime.now(UTC).isoformat(), servers=entries_map)
```

**Context After:**
```python
        """Return a snapshot of current mount specs keyed by name.

        Only includes spec-based mounts; in-process mounts (spec=None) are excluded.
        """
        async with self._lock:
```

---

#### Issue 4: Line 355 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the persistent child client for a mounted server.

The returned client maintains a long-lived session. Callers MAY use
`async with client:` to 
```

**Context Before:**
```python
    # No URI decoding helpers needed; rely on FastMCP mount semantics
```

**Context After:**
```python
        """Return the persistent child client for a mounted server.

        The returned client maintains a long-lived session. Callers MAY use
        `async with client:` to temporarily borrow the session; exiting the
        context will not close the underlying persistent session.
```

---

### adgn/src/adgn/mcp/editor_server.py

**2 issues found**

#### Issue 1: Line 156 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return basic info about the current file.
```

**Context Before:**
```python
def _build_editor_tools(mcp: NotifyingFastMCP, state: EditorState) -> None:
    @mcp.flat_model()
```

**Context After:**
```python
        """Return basic info about the current file."""
        return ReadInfoResult(ok=True, path=state.file_path, lines=len(state.content.splitlines()))

    @mcp.flat_model()
    def read_line_range(input: ReadLineRangeArgs) -> ReadLineRangeResult:
```

---

#### Issue 2: Line 161 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return lines in the given [start,end] (1-based).
```

**Context Before:**
```python

    @mcp.flat_model()
```

**Context After:**
```python
        """Return lines in the given [start,end] (1-based)."""
        lines = state.content.splitlines()
        end = input.start if input.end is None else input.end
        start_idx = max(1, input.start) - 1
        end_idx = min(len(lines), end) - 1
```

---

### adgn/src/adgn/mcp/git_ro/server.py

**4 issues found**

#### Issue 1: Line 69 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return object id (pygit2 >=1.18 provides .id consistently).
```

**Context After:**
```python
    """Return object id (pygit2 >=1.18 provides .id consistently)."""
    return obj.id


# -------------------------- inputs ------------------------------------------
```

---

#### Issue 2: Line 242 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return compact status entries similar to porcelain v1 (no headers).
```

**Context Before:**
```python

    @mcp.flat_model()
```

**Context After:**
```python
        """Return compact status entries similar to porcelain v1 (no headers)."""
        root = state.git_repo
        repo = _open_repo(root)
        st = repo.status()
        entries: list[StatusEntry] = []
```

---

#### Issue 3: Line 298 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return recent commits as oneline entries or multi-line blocks, with pagination.
```

**Context Before:**
```python

    @mcp.flat_model()
```

**Context After:**
```python
        """Return recent commits as oneline entries or multi-line blocks, with pagination."""
        root = state.git_repo
        repo = _open_repo(root)
        if repo.head_is_unborn:
            return apply_text_slice("", input.slice)
```

---

#### Issue 4: Line 325 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return structured commit entries with offset/limit pagination (preferred for programmatic use).
```

**Context Before:**
```python

    @mcp.flat_model()
```

**Context After:**
```python
        """Return structured commit entries with offset/limit pagination (preferred for programmatic use)."""
        root = state.git_repo
        repo = _open_repo(root)
        if repo.head_is_unborn:
            return LogEntriesPage(entries=[], truncated=False, next_offset=None)
```

---

### adgn/src/adgn/mcp/matrix/server.py

**1 issues found**

#### Issue 1: Line 280 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return and clear queued inbound messages.
```

**Context Before:**
```python

    @mcp.flat_model()
```

**Context After:**
```python
        """Return and clear queued inbound messages."""
        return inbox.drain()

    @mcp.flat_model()
    def do_yield(input: YieldInput) -> UiEndTurn:
```

---

### adgn/src/adgn/mcp/ui/server.py

**1 issues found**

#### Issue 1: Line 64 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the server; callers keep their own reference to the bus.
```

**Context Before:**
```python
        return UiEndTurn()
```

**Context After:**
```python
    return mcp
```

---

### adgn/src/adgn/openai_utils/client_factory.py

**1 issues found**

#### Issue 1: Line 25 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a cached AsyncOpenAI client (optionally with HTTP logging).

Cache key is the logging path (None vs specific path). This ensures we avoid
const
```

**Context After:**
```python
    """Return a cached AsyncOpenAI client (optionally with HTTP logging).

    Cache key is the logging path (None vs specific path). This ensures we avoid
    constructing many clients per process while still allowing an opt-in logging
    variant when explicitly requested.
```

---

### adgn/src/adgn/openai_utils/retry.py

**1 issues found**

#### Issue 1: Line 37 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a tenacity.retry decorator with our standard settings.
```

**Context After:**
```python
    attempts: int = _DEFAULT_ATTEMPTS,
    initial: float = _DEFAULT_INITIAL,
    maximum: float = _DEFAULT_MAX,
    retry_exceptions: Iterable[type[BaseException]] = _RETRY_ON,
):
```

---

### adgn/src/adgn/props/cli_app/main.py

**2 issues found**

#### Issue 1: Line 657 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return (scope_text, label) without requiring Docker/hydration.

Used by --dry-run to avoid side effects while still rendering prompts consistently.
```

**Context After:**
```python
    """Return (scope_text, label) without requiring Docker/hydration.

    Used by --dry-run to avoid side effects while still rendering prompts consistently.
    """
    if specimen is not None:
```

---

#### Issue 2: Line 670 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the directory path to save a structured critique JSON.

origin: "specimen" or "path" (other callers may pass "run" to keep folder structure sta
```

**Context After:**
```python
    """Return the directory path to save a structured critique JSON.

    origin: "specimen" or "path" (other callers may pass "run" to keep folder structure stable)
    """
    kind = "specimen" if origin == "specimen" else "run"
```

---

### adgn/src/adgn/props/cli_shared.py

**1 issues found**

#### Issue 1: Line 63 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a filesystem-friendly timestamp string (YYYYMMDD_HHMMSS).
```

**Context After:**
```python
    """Return a filesystem-friendly timestamp string (YYYYMMDD_HHMMSS)."""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def save_prompt_to_tmp(stem: str, text: str) -> Path:
```

---

### adgn/src/adgn/props/critic.py

**1 issues found**

#### Issue 1: Line 118 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Add one occurrence for an issue.

ranges is a list of either integers (single-line) or 2-element lists [start,end].
Example: [123, [140,150]]
```

**Context After:**
```python
    """Add one occurrence for an issue.

    ranges is a list of either integers (single-line) or 2-element lists [start,end].
    Example: [123, [140,150]]
    """
```

---

### adgn/src/adgn/props/detectors/det_imports_inside_def.py

**1 issues found**

#### Issue 1: Line 42 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Any import whose parent is not Module is a violation (inside def/class)
```

**Context Before:**
```python

        def _maybe_report(self, n: ast.AST) -> None:
```

**Context After:**
```python
            if not self.stack:
                return
            parent = self.stack[-1]
```

---

### adgn/src/adgn/props/detectors/det_optional_string_simplify.py

**1 issues found**

#### Issue 1: Line 58 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return variable name when pattern matches: x is None or x == ""
```

**Context Before:**
```python

def _match_none_or_empty(test: ast.AST) -> str | None:
```

**Context After:**
```python
    if not isinstance(test, ast.BoolOp) or not isinstance(test.op, ast.Or):
        return None
    vals = test.values
```

---

### adgn/src/adgn/props/detectors/import_graph.py

**1 issues found**

#### Issue 1: Line 96 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return True if adding edge a->b would create a cycle (i.e., b reaches a).
```

**Context After:**
```python
    """Return True if adding edge a->b would create a cycle (i.e., b reaches a)."""
    return _has_path(graph, b, a)
```

---

### adgn/src/adgn/props/detectors/utils.py

**1 issues found**

#### Issue 1: Line 39 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return True for blanket except handlers (None, Exception, BaseException).
```

**Context After:**
```python
    """Return True for blanket except handlers (None, Exception, BaseException)."""
    if handler.type is None:
        return True
    return isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"}
```

---

### adgn/src/adgn/props/docker_env.py

**1 issues found**

#### Issue 1: Line 93 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return wiring for the properties critic container.

Ensures the default critic image exists (raises if missing). Always mounts
`workspace_root` read-o
```

**Context After:**
```python
    workspace_root: Path,
    *,
    mount_properties: bool = True,
    extra_volumes: dict[str, dict[str, str]] | None = None,
    ephemeral: bool = True,
```

---

### adgn/src/adgn/props/prompts/util.py

**1 issues found**

#### Issue 1: Line 28 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return {ModelName: model_json_schema()} for all given Pydantic models.

This is passed wholesale to Jinja; templates choose which to render.
```

**Context After:**
```python
    """Return {ModelName: model_json_schema()} for all given Pydantic models.

    This is passed wholesale to Jinja; templates choose which to render.
    """
    out: dict[str, dict] = {}
```

---

### adgn/src/adgn/rspcache/responses_db.py

**1 issues found**

#### Issue 1: Line 103 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the frame as a typed ResponseStreamEvent.
```

**Context Before:**
```python

    @property
```

**Context After:**
```python
        """Return the frame as a typed ResponseStreamEvent."""
        return ResponseStreamEvent.model_validate(self.frame)


class Response(Base):
```

---

### adgn/src/adgn/third_party/openai_cookbook/apply_patch.py

**2 issues found**

#### Issue 1: Line 160 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
def str is a skip ahead operator
```

**Context Before:**
```python
                found = False
                if not [s for s in lines[:index] if s == def_str]:
```

**Context After:**
```python
                    for i, s in enumerate(lines[index:], index):
                        if s == def_str:
                            # print(f"Jump ahead @@: {index} -> {i}: {def_str}")
```

---

#### Issue 2: Line 168 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
def str is a skip ahead operator
```

**Context Before:**
```python
                            break
                if not found and not [s for s in lines[:index] if s.strip() == def_str.strip()]:
```

**Context After:**
```python
                    for i, s in enumerate(lines[index:], index):
                        if s.strip() == def_str.strip():
                            # print(f"Jump ahead @@: {index} -> {i}: {def_str}")
```

---

### adgn/src/adgn/util/net.py

**1 issues found**

#### Issue 1: Line 29 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return an available TCP port on host by briefly binding a socket.

Best-effort and race-tolerant for test usage.
```

**Context After:**
```python
    """Return an available TCP port on host by briefly binding a socket.

    Best-effort and race-tolerant for test usage.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
```

---

### adgn/tests/agent/conftest.py

**2 issues found**

#### Issue 1: Line 133 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the text of the approve-all policy from packaged resources.
```

**Context Before:**
```python

@pytest.fixture
```

**Context After:**
```python
    """Return the text of the approve-all policy from packaged resources."""
    return approve_all_policy_text()


@pytest.fixture
```

---

#### Issue 2: Line 286 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a function to patch container.build_client to a provided fake client.

Keeps model patching independent from agent creation, so tests can opt-i
```

**Context Before:**
```python

@pytest.fixture
```

**Context After:**
```python
    """Return a function to patch container.build_client to a provided fake client.

    Keeps model patching independent from agent creation, so tests can opt-in.
    """
```

---

### adgn/tests/agent/e2e/test_approvals.py

**1 issues found**

#### Issue 1: Line 21 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Agent attempts a tool call → policy asks → UI shows pending → user approves → tool runs.

Flow:
  - Attach in-proc echo MCP server via HTTP (inproc fa
```

**Context After:**
```python
    """Agent attempts a tool call → policy asks → UI shows pending → user approves → tool runs.

    Flow:
      - Attach in-proc echo MCP server via HTTP (inproc factory spec)
      - Model first response is a tool call to echo; second response is ui.end_turn
```

---

### adgn/tests/agent/e2e/test_mcp_errors.py

**2 issues found**

#### Issue 1: Line 342 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return something that will break JSON parsing downstream
```

**Context Before:**
```python
        @self.tool()
        async def broken_tool(input: _BrokenResourceInput, ctx: Context) -> _BrokenResourceOutput:
```

**Context After:**
```python
            return _BrokenResourceOutput(result="This tool works fine")

        @self.resource("resource://broken/data")
```

---

#### Issue 2: Line 347 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return intentionally malformed content
```

**Context Before:**
```python
        @self.resource("resource://broken/data")
        async def broken_resource() -> str:
```

**Context After:**
```python
            # Note: FastMCP may validate this, so this tests the boundary
            return "not valid json at all {{{{"
```

---

### adgn/tests/agent/e2e/test_mcp_performance.py

**4 issues found**

#### Issue 1: Line 137 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set approval policy to auto-approve for this test
```

**Context Before:**
```python
    assert patch.ok, patch.text
```

**Context After:**
```python
    policy_src = """
from adgn.agent.policies.models import PolicyDecision
```

---

#### Issue 2: Line 212 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set auto-approve policy for all agents
```

**Context Before:**
```python
        assert patch.ok, patch.text
```

**Context After:**
```python
    policy_src = """
from adgn.agent.policies.models import PolicyDecision
```

---

#### Issue 3: Line 267 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a large message
```

**Context Before:**
```python
        state["i"] = i + 1
        if i == 0:
```

**Context After:**
```python
            return responses_factory.make_assistant_message(large_text)
        return responses_factory.make_tool_call(
            build_mcp_function("ui", "end_turn"), {}, call_id="call_ui_end"
```

---

#### Issue 4: Line 336 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set auto-approve policy
```

**Context Before:**
```python
    assert patch.ok, patch.text
```

**Context After:**
```python
    policy_src = """
from adgn.agent.policies.models import PolicyDecision
```

---

### adgn/tests/agent/helpers.py

**1 issues found**

#### Issue 1: Line 120 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a matcher ensuring an error message contains ``fragment``.
```

**Context After:**
```python
    """Return a matcher ensuring an error message contains ``fragment``."""

    return has_properties(message=contains_string(fragment))
```

---

### adgn/tests/agent/mcp_bridge/test_ui_auth.py

**1 issues found**

#### Issue 1: Line 158 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set a fixed token for testing
```

**Context Before:**
```python
async def test_management_ui_app_requires_token(infrastructure_registry: InfrastructureRegistry, monkeypatch):
    """Test that create_management_ui_app applies token authentication."""
```

**Context After:**
```python
    test_token = "test-management-ui-token"
    monkeypatch.setenv("ADGN_UI_TOKEN", test_token)
```

---

### adgn/tests/agent/test_notifications_handler.py

**1 issues found**

#### Issue 1: Line 21 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return once, then empty
```

**Context Before:**
```python
    def poll(self) -> NotificationsBatch:
        b = self._batch
```

**Context After:**
```python
        self._batch = NotificationsBatch()
        return b
```

---

### adgn/tests/agent/test_parallel_calls.py

**2 issues found**

#### Issue 1: Line 91 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up event-driven completion notification
```

**Context Before:**
```python

        # Wait for recording handler to observe expected events (tool_call + function_call_output)
```

**Context After:**
```python
        completion_event = asyncio.Event()
        target_records = 4  # 2 tools x 2 events each
```

---

#### Issue 2: Line 45 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a FastMCP server implementing two slow tools.

The tools are async and sleep for per_call_secs to simulate latency. This
exercises the real inp
```

**Context After:**
```python
    """Return a FastMCP server implementing two slow tools.

    The tools are async and sleep for per_call_secs to simulate latency. This
    exercises the real inproc FastMCP transport in tests (higher fidelity).
    """
```

---

### adgn/tests/agent/test_policy_proposal_validations.py

**1 issues found**

#### Issue 1: Line 24 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set policy via HTTP; expect ok=false due to failing tests
```

**Context Before:**
```python

    with agent_ws_box(client, specs={}) as box:
```

**Context After:**
```python
        r = box.http.set_policy(policy_failing_tests)
        assert r.status_code == 200, r.text
        body = r.json() or {}
```

---

### adgn/tests/agent/testdata/approval_policy/__init__.py

**1 issues found**

#### Issue 1: Line 13 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return policy Python source from a file named "<name>.py" in this package.
```

**Context After:**
```python
    """Return policy Python source from a file named "<name>.py" in this package."""
    return files(__name__).joinpath(f"{name}.py").read_text(encoding="utf-8").strip()


def make_policy(
```

---

### adgn/tests/agent/ws_helpers.py

**1 issues found**

#### Issue 1: Line 378 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Matcher: payload is a function_call_output with optional call_id and structuredContent entries.

Example: is_function_call_output(call_id="call_x", ok
```

**Context After:**
```python
    """Matcher: payload is a function_call_output with optional call_id and structuredContent entries.

    Example: is_function_call_output(call_id="call_x", ok=True, echo="hello")
    """
    props: dict[str, object] = {
```

---

### adgn/tests/conftest.py

**1 issues found**

#### Issue 1: Line 422 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a factory that produces in-proc FastMCP servers for echo tests.
```

**Context Before:**
```python

@pytest.fixture
```

**Context After:**
```python
    """Return a factory that produces in-proc FastMCP servers for echo tests."""

    def _spec() -> McpServerSpecs:
        return {"echo": make_backend_server("echo")}
```

---

### adgn/tests/llm/sysrw/test_loader_min.py

**1 issues found**

#### Issue 1: Line 23 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a matcher that finds a text content block containing ``fragment``.
```

**Context After:**
```python
    """Return a matcher that finds a text content block containing ``fragment``."""

    return has_item(has_entries(type="text", text=contains_string(fragment)))
```

---

### adgn/tests/mcp/policy_gateway/test_middleware_lifecycle.py

**1 issues found**

#### Issue 1: Line 431 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Test that timestamps are properly ordered: created < decided < completed.

This is a more detailed verification of timestamp logic.
```

**Context Before:**
```python

@pytest.mark.asyncio
```

**Context After:**
```python
    persistence: SQLitePersistence,
    approval_hub: ApprovalHub,
    run_id: UUID | None,
    test_agent: str,
):
```

---

### adgn/tests/mcp/resources/test_notifications.py

**1 issues found**

#### Issue 1: Line 16 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return empty typed ReadResourceResult for compatibility
```

**Context Before:**
```python

    async def read_resource(self, server: str, uri: str):
```

**Context After:**
```python
        return types.ReadResourceResult(contents=[])
```

---

### adgn/tests/props/test_eval_lint_issue_wt.py

**1 issues found**

#### Issue 1: Line 31 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Runs the lint-issue agent for iss-014 on the wt specimen per occurrence and
asserts the corrected anchors fall within allowed inclusive windows.

This
```

**Context Before:**
```python
    ],
)
```

**Context After:**
```python
    initial_range: tuple[int, int], allowed_window: tuple[tuple[int, int], tuple[int, int]], entity: str
):
    """Runs the lint-issue agent for iss-014 on the wt specimen per occurrence and
    asserts the corrected anchors fall within allowed inclusive windows.
```

---

### adgn/tests/props/test_lint_issue_bootstrap.py

**1 issues found**

#### Issue 1: Line 114 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
assistant message content is a list of InputTextPart blocks in our typed interface
```

**Context Before:**
```python
    # Ensure we saw a final assistant emission with text "FINAL"
    def _is_final(msg) -> bool:
```

**Context After:**
```python
        if isinstance(msg, AssistantMessage):
            for block in msg.content or []:
                if isinstance(block, InputTextPart) and block.text.strip() == "FINAL":
```

---

### ansible/action_plugins/dconf_array_edit.py

**1 issues found**

#### Issue 1: Line 58 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return textual representation of *lst* for ansible.dconf.

ansible.builtin.dconf expects the *printed* form of a GLib variant that
itself contains a v
```

**Context After:**
```python
    """Return textual representation of *lst* for ansible.dconf.

    ansible.builtin.dconf expects the *printed* form of a GLib variant that
    itself contains a variant of type ``as`` (array of strings).
    """
```

---

### ansible/action_plugins/install_handler.py

**1 issues found**

#### Issue 1: Line 160 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the argument dict for *community.general.flatpak*.
```

**Context Before:**
```python
                raise AnsibleError("Invalid flatpak value")
```

**Context After:**
```python
        """Return the argument dict for *community.general.flatpak*."""

        args = {"name": self.name}

        if installed:
```

---

### ansible/library/autostart_entry.py

**1 issues found**

#### Issue 1: Line 53 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Prefer the explicitly provided file name when it is a non-empty string,
```

**Context Before:**
```python
    # and calling ``lower()`` on that would raise an ``AttributeError``.
```

**Context After:**
```python
    # otherwise fall back to the (required) ``name`` parameter.
    desktop_file_name: str | None = params.get("desktop_file_name")
```

---

### ansible/module_utils/github_release.py

**3 issues found**

#### Issue 1: Line 134 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return GitHub API URL for the release.
```

**Context Before:**
```python
        return {"asset_url": url}
```

**Context After:**
```python
        """Return GitHub API URL for the release."""
        url = f"https://api.github.com/repos/{self.repo}/releases"
        if self.version != "latest":
            url += f"/tags/{self.version}"
        else:
```

---

#### Issue 2: Line 186 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return arguments for installing the binary.
```

**Context Before:**
```python
        return "ansible.builtin.get_url"
```

**Context After:**
```python
        """Return arguments for installing the binary."""
        return {"url": asset_url, "dest": self.dest_path, "mode": "0755"}

    def validate(self) -> None:
        super().validate()
```

---

#### Issue 3: Line 214 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return arguments for extracting and installing the archive.
```

**Context Before:**
```python
        return "ansible.builtin.unarchive"
```

**Context After:**
```python
        """Return arguments for extracting and installing the archive."""
        if self.extract_file:
            # For single file extraction, we'll handle this in the action plugin
            return {"asset_url": asset_url, "extract_file": self.extract_file, "dest_path": self.dest_path}
```

---

### ansible/roles/legacy_claude_mcp/files/apply-mcp-config.py

**1 issues found**

#### Issue 1: Line 232 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set result data
```

**Context Before:**
```python
            print("\nNote: You may need to restart Claude Code for changes to take effect.")
```

**Context After:**
```python
    result["changed"] = modified
    result["msg"] = (
        f"Added {len(result['servers_added'])} servers, updated {len(result['servers_updated'])} servers"
```

---

### claude/claude_hooks/claude_hooks/actions.py

**4 issues found**

#### Issue 1: Line 116 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return empty dict - no decision field at all
```

**Context Before:**
```python

    def to_protocol(self) -> HookOutput:
```

**Context After:**
```python
        return {}
```

---

#### Issue 2: Line 169 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return empty dict - no decision field at all
```

**Context Before:**
```python

    def to_protocol(self) -> HookOutput:
```

**Context After:**
```python
        return {}
```

---

#### Issue 3: Line 203 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return empty dict - no decision field at all
```

**Context Before:**
```python

    def to_protocol(self) -> HookOutput:
```

**Context After:**
```python
        return {}
```

---

#### Issue 4: Line 235 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return empty dict - no decision field at all
```

**Context Before:**
```python

    def to_protocol(self) -> HookOutput:
```

**Context After:**
```python
        return {}
```

---

### claude/claude_hooks/claude_hooks/base.py

**1 issues found**

#### Issue 1: Line 113 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set logging context for automatic injection into all log messages
```

**Context Before:**
```python
            )
```

**Context After:**
```python
            set_hook_context(invocation_id=context.invocation_id, name=self.hook_name, session_id=context.session_id)

            action = self.execute(hook_input, context)
```

---

### claude/claude_hooks/claude_hooks/inputs.py

**2 issues found**

#### Issue 1: Line 62 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: get statement

**Comment:**
```
Get tool_name from the data being validated
```

**Context Before:**
```python
    def parse_tool_input_based_on_tool_name(cls, v: Any, info: ValidationInfo) -> Any:
        """Parse tool_input with the correct class based on tool_name."""
```

**Context After:**
```python
        tool_name = info.data.get("tool_name")
        if not tool_name:
            return v
```

---

#### Issue 2: Line 89 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: get statement

**Comment:**
```
Get tool_name from the data being validated
```

**Context Before:**
```python
    def parse_tool_input_based_on_tool_name(cls, v: Any, info: ValidationInfo) -> Any:
        """Parse tool_input with the correct class based on tool_name."""
```

**Context After:**
```python
        tool_name = info.data.get("tool_name")
        if not tool_name:
            return v
```

---

### claude/claude_hooks/claude_hooks/logging_context.py

**2 issues found**

#### Issue 1: Line 31 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set the current hook execution context.
```

**Context After:**
```python
    """Set the current hook execution context."""
    hook_invocation_id.set(invocation_id)
    hook_name.set(name)
    hook_session_id.set(session_id)
```

---

#### Issue 2: Line 50 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up logging with hook context support.
```

**Context After:**
```python
    """Set up logging with hook context support."""
    # Get root logger and add our context filter
    root_logger = logging.getLogger()

    # Remove any existing HookContextFilter to avoid duplicates
```

---

### claude/claude_hooks/tests/conftest.py

**2 issues found**

#### Issue 1: Line 207 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up XDG config to point to our claude_config_dir
```

**Context Before:**
```python
def integration_env(precommit_repo, claude_config_dir, xdg_env, monkeypatch):
    """Full integration test environment with all components."""
```

**Context After:**
```python
    monkeypatch.setenv("XDG_CONFIG_HOME", str(claude_config_dir.parent))

    class IntegrationEnv:
```

---

#### Issue 2: Line 130 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up isolated XDG environment variables for all tests automatically.
```

**Context Before:**
```python

@pytest.fixture(autouse=True)
```

**Context After:**
```python
    """Set up isolated XDG environment variables for all tests automatically."""
    xdg_dirs = {
        "XDG_CONFIG_HOME": tmp_path / ".config",
        "XDG_DATA_HOME": tmp_path / ".local" / "share",
        "XDG_CACHE_HOME": tmp_path / ".cache",
```

---

### claude/claude_optimizer/tests/test_full_e2e_workflow.py

**1 issues found**

#### Issue 1: Line 189 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return reasonable fallback response
```

**Context Before:**
```python
                return await response.json()
        except aiohttp.ClientError as e:
```

**Context After:**
```python
            return {\"status\": \"partial_success\", \"error\": str(e), \"data\": data}
""",
                                },
```

---

### difftree/src/difftree/__main__.py

**1 issues found**

#### Issue 1: Line 81 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Use os.fstat to check if stdin is a regular file or pipe with data
```

**Context Before:**
```python
            # Try to peek at stdin to see if there's real data
            try:
```

**Context After:**
```python
                mode = os.fstat(sys.stdin.fileno()).st_mode
                if (stat.S_ISFIFO(mode) or stat.S_ISREG(mode)) and select.select([sys.stdin], [], [], 0.0)[0]:
                    # Data is available, but it might just be EOF
```

---

### difftree/src/difftree/diff_tree.py

**3 issues found**

#### Issue 1: Line 33 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: get statement

**Comment:**
```
Get totals from root (which has aggregated stats from all children)
```

**Context Before:**
```python
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        """Render as a Table with aligned tree structure and statistics."""
```

**Context After:**
```python
        total_additions = self.root.additions
        total_deletions = self.root.deletions
        total_changes = total_additions + total_deletions if (total_additions + total_deletions) > 0 else 1
```

---

#### Issue 2: Line 200 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return empty progress bars for binary files
```

**Context Before:**
```python
        """Create bar cells (green and red progress bars)."""
        if node.is_binary:
```

**Context After:**
```python
            empty_green = ProgressBar(
                value=0,
                max_value=1,
```

---

#### Issue 3: Line 113 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Check if we should recurse into a node's children.

Returns False if:
- Node is a file
- Node has no children
- We've exceeded max_depth
```

**Context Before:**
```python
        yield table
```

**Context After:**
```python
        """Check if we should recurse into a node's children.

        Returns False if:
        - Node is a file
        - Node has no children
```

---

### difftree/src/difftree/tree.py

**2 issues found**

#### Issue 1: Line 140 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return new node with sorted children
```

**Context Before:**
```python
    sorted_children = dict(sorted_items)
```

**Context After:**
```python
    return TreeNode(
        name=node.name,
        is_file=node.is_file,
```

---

#### Issue 2: Line 121 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a new tree with nodes sorted according to the specified mode.

Since TreeNode is immutable, this creates a new tree with sorted children.
```

**Context After:**
```python
    """Return a new tree with nodes sorted according to the specified mode.

    Since TreeNode is immutable, this creates a new tree with sorted children.
    """
    if not node.children:
```

---

### dotfiles/local/bin/login_event_webhook_reporter.py

**1 issues found**

#### Issue 1: Line 55 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return JSON body bytes for *events* batch.
```

**Context Before:**
```python

# - helpers ----------------------------------------------------------------------
```

**Context After:**
```python
    """Return JSON body bytes for *events* batch."""
    return json.dumps({"host": socket.gethostname(), "events": events}, separators=(",", ":")).encode()


def _post(body: bytes) -> bool:
```

---

### ember/src/ember/secrets.py

**1 issues found**

#### Issue 1: Line 24 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the current value, raising if required and missing.
```

**Context Before:**
```python
        self._strip = strip
```

**Context After:**
```python
        """Return the current value, raising if required and missing."""

        value = self._read_raw()
        if required and not value:
            raise RuntimeError(f"{self._file_name} is not configured")
```

---

### experimental/cotrl/llm_rl_experiment.py

**3 issues found**

#### Issue 1: Line 453 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set labels and title
```

**Context Before:**
```python
                ax.fill_between(timesteps, ci_lower, ci_upper, alpha=0.3, color="blue")
```

**Context After:**
```python
            if i == 0:
                ax.set_title(env.replace("-v", " v"))
            if j == 0:
```

---

#### Issue 2: Line 223 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the log directory path.
```

**Context Before:**
```python
            await f.write(summary.model_dump_json(indent=2))
```

**Context After:**
```python
        """Return the log directory path."""
        return self.log_dir


class LLMRLAgent:
```

---

#### Issue 3: Line 265 [DOCSTRING]

**Assessment**: OBVIOUS: get statement

**Comment:**
```
Get action from LLM based on raw state data.
```

**Context Before:**
```python
Choose action:"""
```

**Context After:**
```python
        self, state: np.ndarray, reward: float, action_space_size: int, first_step: bool = False
    ) -> int:
        """Get action from LLM based on raw state data."""
        if not self.conversation_history:
            self.conversation_history.append(Message(role="system", content=self._create_initial_prompt()))
```

---

### experimental/webhook_inbox/test_webhook_inbox.py

**1 issues found**

#### Issue 1: Line 12 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return (app_module, client) wired to test database.
```

**Context Before:**
```python

@pytest.fixture
```

**Context After:**
```python
    """Return (app_module, client) wired to test database."""

    webhook_inbox.configure_db(tmp_path / "test.db")

    client = TestClient(webhook_inbox.app)
```

---

### experimental/webhook_inbox/webhook_inbox.py

**3 issues found**

#### Issue 1: Line 112 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return json.dumps(events, separators=(',', ':')).encode()  # Compact JSON
```

**Context Before:**
```python

    def plain_encode(self, events):
```

**Context After:**
```python
        # return json.dumps(events, indent=2)  # pretty JSON
        return Formatter(indent_spaces=2, max_inline_length=70, max_inline_complexity=10).serialize(events)
```

---

#### Issue 2: Line 113 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return json.dumps(events, indent=2)  # pretty JSON
```

**Context Before:**
```python
    def plain_encode(self, events):
        # return json.dumps(events, separators=(',', ':')).encode()  # Compact JSON
```

**Context After:**
```python
        return Formatter(indent_spaces=2, max_inline_length=70, max_inline_complexity=10).serialize(events)

    # ------------------------------------------------------------------
```

---

#### Issue 3: Line 119 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return a *dict* with encoded representation of *events*.

Return type is a mapping for unpacking into Jinja context.

Behaviour:

* No key configured 
```

**Context Before:**
```python
    # Public API
    # ------------------------------------------------------------------
```

**Context After:**
```python
        """Return a *dict* with encoded representation of *events*.

        Return type is a mapping for unpacking into Jinja context.

        Behaviour:
```

---

### gatelet/gatelet/aw_summary.py

**1 issues found**

#### Issue 1: Line 18 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return lists of window, web, and afk bucket IDs.
```

**Context After:**
```python
    """Return lists of window, web, and afk bucket IDs."""
    buckets = client.get_buckets()
    window_bk = [b for b in buckets if b.startswith("aw-watcher-window")]
    web_bk = [b for b in buckets if b.startswith("aw-watcher-web")]
    afk_bk = [b for b in buckets if b.startswith("aw-watcher-afk")]
```

---

### gatelet/gatelet/manage.py

**1 issues found**

#### Issue 1: Line 26 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return row counts for all tables.
```

**Context After:**
```python
    """Return row counts for all tables."""
    counts = []
    for table in Base.metadata.sorted_tables:
        result = await session.execute(select(func.count()).select_from(table))
        cnt = result.scalar()
```

---

### gatelet/gatelet/server/endpoints/webhook_view.py

**1 issues found**

#### Issue 1: Line 82 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set default page size from settings if not provided
```

**Context Before:**
```python
        Dict with template context variables
    """
```

**Context After:**
```python
    if page_size is None:
        if settings is None:
            raise ValueError("settings must be provided when page_size is None")
```

---

### gatelet/gatelet/server/migrations/env.py

**1 issues found**

#### Issue 1: Line 13 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up Python loggers based on config file.
```

**Context Before:**
```python
config = context.config
```

**Context After:**
```python
if config.config_file_name:
    fileConfig(config.config_file_name)
```

---

### gatelet/gatelet/server/security.py

**1 issues found**

#### Issue 1: Line 6 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return Argon2 hash of ``password``.
```

**Context After:**
```python
    """Return Argon2 hash of ``password``."""

    return argon2.hash(password)
```

---

### gnome-terminal-profile-switcher/src/gnome_terminal_profile_switcher/__init__.py

**3 issues found**

#### Issue 1: Line 152 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set profile name
```

**Context Before:**
```python
    gsettings_profiles.profile_uuids = gsettings_profiles.profile_uuids | {auto_uuid}
```

**Context After:**
```python
    auto_dconf = ProfileDConf(auto_uuid)
    auto_dconf.visible_name = AUTO_PROFILE_NAME
    return auto_uuid
```

---

#### Issue 2: Line 211 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set as default
```

**Context Before:**
```python
    # Create or update the auto profile with colors from the profile
    auto_uuid = create_or_update_auto_profile(_PROFILE.value)
```

**Context After:**
```python
    gsettings_set_default_profile_uuid(auto_uuid)
```

---

#### Issue 3: Line 33 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set the profile UUIDs in gsettings.
```

**Context Before:**
```python

    @profile_uuids.setter
```

**Context After:**
```python
        """Set the profile UUIDs in gsettings."""
        self.settings.set_strv("list", [str(uuid) for uuid in uuids])

    @property
    def default_profile_uuid(self) -> UUID:
```

---

### homeassistant/iaqi/custom_components/indoor_aqi/sensor.py

**1 issues found**

#### Issue 1: Line 213 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set of sensors with errors in previous update
```

**Context Before:**
```python

        # For tracking partial data logging
```

**Context After:**
```python
        self._previous_error_sensors: set[str] = set()
        # Last time we logged partial data
        self._last_log_time = datetime.now(UTC)
```

---

### homeassistant/iaqi/tests/conftest.py

**1 issues found**

#### Issue 1: Line 39 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return an empty iterator instead of raising *FileNotFoundError*.
```

**Context Before:**
```python

    if str(self).startswith(_SENTINEL_PREFIX):
```

**Context After:**
```python
        return iter(())

    return _orig_iterdir(self)
```

---

### homeassistant/iaqi/tests/test_init.py

**1 issues found**

#### Issue 1: Line 32 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up the component
```

**Context Before:**
```python
    hass.states.async_set("sensor.test_pm25", "30")
```

**Context After:**
```python
    assert await async_setup_component(hass, DOMAIN, config)
    await hass.async_block_till_done()
```

---

### homeassistant/iaqi/tests/test_sensor.py

**1 issues found**

#### Issue 1: Line 252 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set last log time back by an hour to simulate passage of time
```

**Context Before:**
```python

    # Instead of patching datetime, just manually adjust the timestamp
```

**Context After:**
```python
    sensor._last_log_time = now - timedelta(hours=1, minutes=1)

    # Update again - should log since it's been over an hour
```

---

### inventree_utils/beautifier/assign_jellybean.py

**1 issues found**

#### Issue 1: Line 20 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return parts missing the given parameter.
```

**Context After:**
```python
    """Return parts missing the given parameter."""
    part_pks_with_param = {param.part for param in Parameter.list(api, template=template.pk)}
    return [p for p in Part.list(api) if p.pk not in part_pks_with_param]
```

---

### inventree_utils/beautifier/fix_lcsc_links.py

**1 issues found**

#### Issue 1: Line 9 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
If url is a recognized LCSC link, rewrite it to short form:
  e.g. https://www.lcsc.com/product-detail/C12345.html
Otherwise returns the original url.
```

**Context After:**
```python
    """
    If url is a recognized LCSC link, rewrite it to short form:
      e.g. https://www.lcsc.com/product-detail/C12345.html
    Otherwise returns the original url.
    """
```

---

### inventree_utils/labels/mixin.py

**1 issues found**

#### Issue 1: Line 27 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return wp.render_to_response(context, **kwargs)
```

**Context Before:**
```python
    #     **kwargs,
    # )
```

**Context After:**
```python

    # report snippets: https://docs.inventree.org/en/0.17.1/report/templates/#report-snippets
    #   allows calling sub-templates
```

---

### inventree_utils/rai_plugin/templatetags/custom_tags.py

**10 issues found**

#### Issue 1: Line 265 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return ""
```

**Context Before:**
```python
#            items = self.list_var.resolve(context)
#        except template.VariableDoesNotExist:
```

**Context After:**
```python
#
#        # Group items by the chosen field
#        groups = {}
```

---

#### Issue 2: Line 283 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return "".join(output)
```

**Context Before:**
```python
#            context.pop()
#
```

**Context After:**
```python
#
#
# @register.tag
```

---

#### Issue 3: Line 306 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return GroupByFieldNode(nodelist, list_var, field_name, group_var, items_var)
```

**Context Before:**
```python
#    parser.delete_first_token()
#
```

**Context After:**
```python
#
#
########
```

---

#### Issue 4: Line 328 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return f"{greet}, {profile.user.username}!"
```

**Context Before:**
```python
#        profile = UserProfile.objects.get(pk=user_id)
#        greet = random.choice(greetings)
```

**Context After:**
```python
#    except UserProfile.DoesNotExist:
#        return "User not found."
#
```

---

#### Issue 5: Line 330 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return "User not found."
```

**Context Before:**
```python
#        return f"{greet}, {profile.user.username}!"
#    except UserProfile.DoesNotExist:
```

**Context After:**
```python
#
######
#
```

---

#### Issue 6: Line 356 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return {
```

**Context Before:**
```python
#
#    # Returns a dict of context used by components/user_panel.html
```

**Context After:**
```python
#        'profile': profile,
#        'request': context['request']  # pass request if subtemplate needs it
#    }
```

---

#### Issue 7: Line 366 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return f"Welcome back, {user.username}!" if user.is_authenticated else "Hello, guest!"
```

**Context Before:**
```python
# def user_message(context):
#    user = context['request'].user
```

**Context After:**
```python


# @register.filter
```

---

#### Issue 8: Line 374 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return s
```

**Context Before:**
```python
#    s = str(value)
#    if len(s) <= 4:
```

**Context After:**
```python
#    # Replace leading characters with '*', keep last 4
#    masked = "*" * (len(s) - 4) + s[-4:]
#    return masked
```

---

#### Issue 9: Line 377 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return masked
```

**Context Before:**
```python
#    # Replace leading characters with '*', keep last 4
#    masked = "*" * (len(s) - 4) + s[-4:]
```

**Context After:**
```python
# @register.simple_tag
# def generate_qr(data):
#    """Generate a QR code image (PNG format) for the given data and return as data URI."""
```

---

#### Issue 10: Line 387 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return f"data:image/png;base64,{img_b64}"
```

**Context Before:**
```python
#    img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
#    # Return an inline image (data URI)
```

---

### inventree_utils/samplebooks_import/import_samplebooks2.py

**3 issues found**

#### Issue 1: Line 270 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set parameters
```

**Context Before:**
```python
    }
    newp = InvPart.create(api, data)
```

**Context After:**
```python
    pkg_str = get_package_string(p.package)
    set_part_parameter(newp, param_templates[PACKAGE_PT_NAME], pkg_str)
```

---

#### Issue 2: Line 50 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the human-friendly quantity string (e.g. "4.7 nF" or "10 kΩ").
```

**Context After:**
```python
    """
    Return the human-friendly quantity string (e.g. "4.7 nF" or "10 kΩ").
    """
    if isinstance(part, Resistor):
        q = part.resistance.to_compact()
```

---

#### Issue 3: Line 187 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Compare name, category, description, param fields, etc.
Return True if it exactly matches what we'd create now.
Instead of re-querying the server, we 
```

**Context After:**
```python
    invpart: InvPart,
    p: BasePart,
    param_templates: dict[str, ParameterTemplate],
    existing_params_for_part: list[Parameter],
) -> bool:
```

---

### inventree_utils/samplebooks_import/samplebooks_parts_data.py

**2 issues found**

#### Issue 1: Line 207 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return f"{value.to_compact():~P}"  # Auto-scale to nF, µF ...
```

**Context Before:**
```python
    # Reconstruct the Quantity with rounded magnitude
    return f"{rounded_value:g} {value.units:~P}"
```

**Context After:**
```python


def part_key(part):
```

---

#### Issue 2: Line 312 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
set the quantity for parts according to these rules:
```

**Context Before:**
```python
# create a stock item for every part you add. set its location to the
# corresponding LOC_* location id, e.g. LOC_0201 = 1 for 0201 parts.
```

**Context After:**
```python
# R0201: everything has count 50, except 200R, 220R - those are 35
# C0201: everything has count 50, except 100nF - those are 40
# R0402: everything has count 50, except 10R, 10k - those are 40
```

---

### llm/ducktape_llm_common/ducktape_llm_common/claude_hook.py

**1 issues found**

#### Issue 1: Line 130 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up logger for this session/invocation
```

**Context Before:**
```python
            invocation_id = InvocationID(uuid.uuid4())
```

**Context After:**
```python
            logger = get_session_logger(hook_instance.hook_name, request.session_id, invocation_id)
            hook_instance.logger = logger
```

---

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter/cli.py

**2 issues found**

#### Issue 1: Line 18 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return empty response to let normal permission flow continue
```

**Context Before:**
```python
    # Pre-write hook evaluation - early bailout
    if req.tool_name != "Write":
```

**Context After:**
```python
        return HookResponse()

    inp = req.tool_input
```

---

#### Issue 2: Line 23 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return empty response to let normal permission flow continue
```

**Context Before:**
```python
    inp = req.tool_input
    if not inp.file_path or inp.content is None:
```

**Context After:**
```python
        return HookResponse()

    # Run hooks on temp file
```

---

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/access/evaluator.py

**1 issues found**

#### Issue 1: Line 74 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the function
```

**Context Before:**
```python
        exec(predicate_code, namespace)
```

**Context After:**
```python
        func_name = func_node.name
        if func_name not in namespace:
            raise ValueError(f"Function '{func_name}' not found after execution")
```

---

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/hooks/handler.py

**5 issues found**

#### Issue 1: Line 90 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up root logger
```

**Context Before:**
```python
        config = self.config_loader.config
```

**Context After:**
```python
        root_logger = logging.getLogger()

        # Clear any existing handlers to avoid duplicates
```

---

#### Issue 2: Line 110 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set log level from config
```

**Context Before:**
```python
            file_handler = logging.FileHandler(log_file)
```

**Context After:**
```python
            log_level = config.log_level
            try:
                level_value = logging._nameToLevel.get(log_level.upper(), logging.INFO)
```

---

#### Issue 3: Line 125 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set root logger to the lowest level to let handlers filter
```

**Context Before:**
```python
            root_logger.addHandler(file_handler)
```

**Context After:**
```python
            root_logger.setLevel(logging.DEBUG)

            logger.info(f"Logging configured: level={log_level}, file={log_file}")
```

---

#### Issue 4: Line 420 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return appropriate outcome
```

**Context Before:**
```python
        )
```

**Context After:**
```python
        if not messages:
            return PostToolSuccess()
```

---

#### Issue 5: Line 80 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up session-based logging.
```

**Context Before:**
```python
        self._setup_logging()
```

**Context After:**
```python
        """Set up session-based logging."""
        # Create logs directory
        log_dir = Path.home() / ".claude-linter" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir = log_dir
```

---

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/llm_analyzer.py

**1 issues found**

#### Issue 1: Line 119 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Call the LLM API and return the result.

This is a placeholder - actual implementation would use OpenAI/Anthropic API.
```

**Context Before:**
```python
        return self.config.prompts.full_file_analysis.format(file_path=file_path, content=full_content)
```

**Context After:**
```python
        """Call the LLM API and return the result.

        This is a placeholder - actual implementation would use OpenAI/Anthropic API.
        """
        # TODO: Implement actual LLM API call
```

---

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/session/manager.py

**1 issues found**

#### Issue 1: Line 75 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return default session data
```

**Context Before:**
```python
                logger.error(f"Failed to load session {session_id}: {e}")
```

**Context After:**
```python
        return SessionData(id=session_id, created=datetime.now())

    def _save_session(self, session_id: SessionID, session_data: SessionData) -> None:
```

---

### llm/ducktape_llm_common/ducktape_llm_common/claude_linter_v2/session/state.py

**1 issues found**

#### Issue 1: Line 74 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set the current notification ID.
```

**Context Before:**
```python
        self.last_seen = datetime.now()
```

**Context After:**
```python
        """Set the current notification ID."""
        self.notification_id = notification_id
        self.last_seen = datetime.now()

    def clear_notification_id(self) -> None:
```

---

### llm/ducktape_llm_common/ducktape_llm_common/hook_logging.py

**1 issues found**

#### Issue 1: Line 109 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up file logging to session directory
```

**Context Before:**
```python
        logger.propagate = False
```

**Context After:**
```python
        session_dir = get_session_dir(hook_name, session_id)
        log_file = session_dir / "hook.log"
```

---

### llm/ducktape_llm_common/ducktape_llm_common/prompts/helpers.py

**1 issues found**

#### Issue 1: Line 120 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up default values for common variables
```

**Context Before:**
```python
) -> str:
    """Raises PromptVariableError if required variables are missing."""
```

**Context After:**
```python
    defaults = {
        "timestamp": datetime.now().isoformat(),
        "working_directory": str(Path.cwd()),
```

---

### llm/ducktape_llm_common/tests/claude_linter/test_claude_linter.py

**2 issues found**

#### Issue 1: Line 63 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up a fake cache directory
```

**Context Before:**
```python
        """Test that debug logs are not created by default."""
```

**Context After:**
```python
        cache_dir = tmp_path / ".cache" / "claude-linter"
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
```

---

#### Issue 2: Line 85 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up a fake cache directory
```

**Context Before:**
```python
        """Test that debug logs ARE created when CLAUDE_LINTER_DEBUG is set."""
```

**Context After:**
```python
        cache_dir = tmp_path / ".cache" / "claude-linter"
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
```

---

### llm/html/llm_html/server.py

**2 issues found**

#### Issue 1: Line 163 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: get statement

**Comment:**
```
Get title from frontmatter (required)
```

**Context Before:**
```python
            content = md.convert(text)
```

**Context After:**
```python
            if not hasattr(md, "Meta") or "title" not in md.Meta:
                raise ValueError(f"Missing required 'title' in frontmatter for {page}.md")
            title = md.Meta["title"][0]
```

---

#### Issue 2: Line 213 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return statistics about all served pages as JSON.
```

**Context Before:**
```python

@app.get("/api/stats")
```

**Context After:**
```python
    """Return statistics about all served pages as JSON."""
    # Check cache
    now = datetime.now(TIMEZONE)
    if (
        STATS_CACHE.data is not None
```

---

### llm/mcp/habitify/examples/test_mcp_dev.py

**1 issues found**

#### Issue 1: Line 47 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up the server
```

**Context Before:**
```python
logger = logging.getLogger("habitify-mcp-dev-server")
```

**Context After:**
```python
server = create_habitify_mcp_server()

# Print available tools for reference
```

---

### llm/mcp/habitify/habitify_api_reference/collect_references.py

**6 issues found**

#### Issue 1: Line 131 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return primitive values unchanged
```

**Context Before:**
```python
            # Process lists recursively
            return [self._mask_sensitive_data(item) for item in data]
```

**Context After:**
```python
        return data

    def _make_request_and_save(
```

---

#### Issue 2: Line 244 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set habit status with +00:00 format (mark as completed)
```

**Context Before:**
```python
        )
```

**Context After:**
```python
        self._make_request_and_save(
            name="Set Habit Status (Completed)",
            method="PUT",
```

---

#### Issue 3: Line 258 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set habit status with +00:00 format (mark as skipped)
```

**Context Before:**
```python
        )
```

**Context After:**
```python
        self._make_request_and_save(
            name="Set Habit Status (Skipped)",
            method="PUT",
```

---

#### Issue 4: Line 267 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set habit status with +00:00 format (mark as failed)
```

**Context Before:**
```python
        )
```

**Context After:**
```python
        self._make_request_and_save(
            name="Set Habit Status (Failed)",
            method="PUT",
```

---

#### Issue 5: Line 276 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set habit status with +00:00 format (mark as completed without value)
```

**Context Before:**
```python
        )
```

**Context After:**
```python
        # This is for habits that don't have a value, just a status
        self._make_request_and_save(
            name="Set Habit Status (No Value)",
```

---

#### Issue 6: Line 40 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return headers with API key properly masked.
```

**Context Before:**
```python

    @property
```

**Context After:**
```python
        """Return headers with API key properly masked."""
        return {"Authorization": "API_KEY_MASKED", "Content-Type": "application/json"}

    @cached_property
    def client(self) -> httpx.Client:
```

---

### llm/mcp/habitify/habitify_mcp_server/cli.py

**3 issues found**

#### Issue 1: Line 30 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up logging to stderr
```

**Context Before:**
```python
load_dotenv()
```

**Context After:**
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
```

---

#### Issue 2: Line 85 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up signal handlers
```

**Context Before:**
```python
        raise typer.Exit(code=1)
```

**Context After:**
```python
    setup_signal_handlers()

    # Configure logging level for the server
```

---

#### Issue 3: Line 46 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up signal handlers for graceful shutdown.
```

**Context Before:**
```python

# Signal handling for graceful shutdown
```

**Context After:**
```python
    """Set up signal handlers for graceful shutdown."""

    def signal_handler(sig, frame):
        logger.info("Received signal to terminate. Shutting down...")
        sys.exit(0)
```

---

### llm/mcp/habitify/habitify_mcp_server/config.py

**1 issues found**

#### Issue 1: Line 31 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set API key from override if provided
```

**Context Before:**
```python
    load_dotenv()
```

**Context After:**
```python
    if api_key_override:
        os.environ["HABITIFY_API_KEY"] = api_key_override
```

---

### llm/mcp/habitify/habitify_mcp_server/habitify_client.py

**2 issues found**

#### Issue 1: Line 258 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Check a habit's status for a range of dates.

This is a client-side implementation that fetches individual status records
for each date in the range c
```

**Context Before:**
```python
            raise self._handle_error(e)
```

**Context After:**
```python
        self,
        habit_id: str,
        start_date: str | datetime.date | None = None,
        end_date: str | datetime.date | None = None,
        days: int | None = None,
```

---

#### Issue 2: Line 313 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set a habit's status for a specific date.

Endpoint: PUT /status/{habit_id}

Args:
    habit_id: The habit ID
    status: Status to set ('completed', 
```

**Context Before:**
```python
    # All methods are async-only now
```

**Context After:**
```python
        self,
        habit_id: str,
        status: Literal["completed", "skipped", "failed", "none"],
        date: str | datetime.date | None = None,
        note: str | None = None,
```

---

### llm/mcp/habitify/habitify_mcp_server/tests/conftest.py

**1 issues found**

#### Issue 1: Line 52 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set response content
```

**Context Before:**
```python
        mock_resp.headers = ref_data.response.headers
```

**Context After:**
```python
        if ref_data.response.json is not None:
            mock_resp.json.return_value = ref_data.response.json
        elif ref_data.response.text is not None:
```

---

### llm/mcp/habitify/habitify_mcp_server/tools.py

**2 issues found**

#### Issue 1: Line 70 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return habits with count, using Pydantic model
```

**Context Before:**
```python
        habits = [habit for habit in habits if not habit.archived]
```

**Context After:**
```python
    return HabitsResult(habits=habits, count=len(habits))
```

---

#### Issue 2: Line 225 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set a habit's status for a specific date.

Args:
    client: HabitifyClient instance (injected by decorator)
    id: ID of the habit to update
    nam
```

**Context Before:**
```python

@with_client
```

**Context After:**
```python
    client: HabitifyClient,
    id: str | None = None,
    name: str | None = None,
    status: Status = Status.COMPLETED,
    date: str | None = None,
```

---

### llm/mcp/habitify/habitify_mcp_server/types.py

**2 issues found**

#### Issue 1: Line 129 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return whether the habit is archived based on is_archived field.
```

**Context Before:**
```python

    @property
```

**Context After:**
```python
        """Return whether the habit is archived based on is_archived field."""
        return self.is_archived

    @property
    def category(self) -> str | None:
```

---

#### Issue 2: Line 134 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the category/area name for compatibility.
```

**Context Before:**
```python

    @property
```

**Context After:**
```python
        """Return the category/area name for compatibility."""
        if self.area:
            return self.area.name
        return None
```

---

### llm/ultra-long-cot/ultra_long_cot_o4.py

**1 issues found**

#### Issue 1: Line 123 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return content, tokens used, and full usage for analysis
```

**Context Before:**
```python
    tracker.add_usage(response.usage)
```

**Context After:**
```python
    return content, response.usage.completion_tokens, response.usage.model_dump()
```

---

### mcp_starter/manual_test_sdk.py

**3 issues found**

#### Issue 1: Line 60 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up logging with Rich handler for pretty output
```

**Context Before:**
```python
console = Console()
```

**Context After:**
```python
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
```

---

#### Issue 2: Line 153 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up logging
```

**Context Before:**
```python
    sse_port = find_unused_port()
```

**Context After:**
```python
    sse_log_file = Path(tempfile.gettempdir()) / "mcp_starter_sse_server.log"

    logger.info(f"[blue]Starting SSE server on port {sse_port}. Logs: {sse_log_file}[/blue]")
```

---

#### Issue 3: Line 158 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up clean isolated environment
```

**Context Before:**
```python
    logger.info(f"[blue]Starting SSE server on port {sse_port}. Logs: {sse_log_file}[/blue]")
```

**Context After:**
```python
    server_env = {}
    for var in ["PATH", "PYTHONPATH", "HOME", "USER"]:
        if var in os.environ:
```

---

### tana/src/tana/domain/nodes.py

**2 issues found**

#### Issue 1: Line 67 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return children as node instances.
```

**Context Before:**
```python

    @property
```

**Context After:**
```python
        """Return children as node instances."""
        if not self._graph:
            raise RuntimeError("Node not attached to a graph")
        return [self._graph[cid] for cid in self.children if cid in self._graph]
```

---

#### Issue 2: Line 74 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return all supertag names associated with this node.
```

**Context Before:**
```python

    @property
```

**Context After:**
```python
        """Return all supertag names associated with this node."""
        if not self._graph:
            return []
        return self._graph.get_supertags(self.id)
```

---

### tana/src/tana/export/convert.py

**1 issues found**

#### Issue 1: Line 63 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Check if the node itself is a checkbox value
```

**Context Before:**
```python
    # ──────────────────────────────────────────────────────────────
    def _scalar_text(self, node: BaseNode) -> str | None:
```

**Context After:**
```python
        if node.id == CHECKBOX_CHECKED_ID:
            return "[X] "  # Note: trailing space for consistency with expected output
        if node.id == CHECKBOX_UNCHECKED_ID:
```

---

### tana/src/tana/export/export_node_subset.py

**1 issues found**

#### Issue 1: Line 139 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the export and all accessed nodes
```

**Context Before:**
```python
    all_accessed = export_nodes | supertag_deps
```

**Context After:**
```python
    return tanapaste, all_accessed
```

---

### tana/src/tana/graph/wrappers.py

**1 issues found**

#### Issue 1: Line 8 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return True when the node represents a structural wrapper.
```

**Context After:**
```python
    """Return True when the node represents a structural wrapper."""
    return node.props.doc_type in _WRAPPER_DOC_TYPES
```

---

### tana/src/tana/query/core.py

**3 issues found**

#### Issue 1: Line 33 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Case 1: node itself is a tuple — check its key
```

**Context Before:**
```python
    children = list(node.children)
```

**Context After:**
```python
    if children:
        first = children[0]
        if str(first) == key_str:
```

---

#### Issue 2: Line 37 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return first value if present and resolvable via store
```

**Context Before:**
```python
        first = children[0]
        if str(first) == key_str:
```

**Context After:**
```python
            store = node._graph
            if store is not None and len(children) >= 2:
                return store.get(children[1])
```

---

#### Issue 3: Line 17 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the first value node from a tuple keyed by `key`.

Supports two shapes:
- node is a tuple node: children[0] is the key id, children[1:] are val
```

**Context After:**
```python
    """Return the first value node from a tuple keyed by `key`.

    Supports two shapes:
    - node is a tuple node: children[0] is the key id, children[1:] are values
    - node is a container: search its child tuple nodes for one where
```

---

### trilium/search_hack.py

**1 issues found**

#### Issue 1: Line 189 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
```

**Context Before:**
```python
    )
```

**Context After:**
```python
    import numpy as np

    results_df["similarities"] = results_df.embedding.apply(
```

---

### wt/src/wt/client/wt_client.py

**2 issues found**

#### Issue 1: Line 178 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set read end to non-blocking for asyncio compatibility
```

**Context Before:**
```python
        read_fd, write_fd = os.pipe()
```

**Context After:**
```python
        flags = fcntl.fcntl(read_fd, fcntl.F_GETFL)
        fcntl.fcntl(read_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
```

---

#### Issue 2: Line 264 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return immediately on terminal condition
```

**Context Before:**
```python
                    continue
```

**Context After:**
```python
                if not msg.success or msg.ready:
                    return msg
        finally:
```

---

### wt/src/wt/plugins.py

**1 issues found**

#### Issue 1: Line 17 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return mapping of subcommand name -> callable
Signatures supported:
- async def run(args: list[str], client, config, io) -> int | None
- def run(args:
```

**Context Before:**
```python
class _Spec:
    @pluggy.HookspecMarker(PROJECT_NAME)
```

**Context After:**
```python
        """
        Return mapping of subcommand name -> callable
        Signatures supported:
        - async def run(args: list[str], client, config, io) -> int | None
        - def run(args: list[str], client, config, io) -> int | None
```

---

### wt/src/wt/shared/env.py

**1 issues found**

#### Issue 1: Line 9 [DOCSTRING]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return True when running in test mode.

Accepts common truthy values to avoid brittle string equality checks.
Values considered true: "1", "true", "ye
```

**Context After:**
```python
    """Return True when running in test mode.

    Accepts common truthy values to avoid brittle string equality checks.
    Values considered true: "1", "true", "yes", "on" (case-insensitive).
    """
```

---

### wt/tests/config_factory.py

**10 issues found**

#### Issue 1: Line 35 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up WT_DIR
```

**Context Before:**
```python
            raise ValueError(f"Unknown preset: {preset}. Available: {self._available_presets()}")
```

**Context After:**
```python
        if wt_dir is None:
            wt_dir = self.temp_base_dir / TestData.Paths.TEST_WT_DIR_PARENT / TestData.Paths.WT_DIR_NAME
```

---

#### Issue 2: Line 23 [DOCSTRING]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
preset is a name from ConfigPresets class or a dict.
```

**Context Before:**
```python
        self.temp_base_dir = temp_base_dir or repo_path.parent
```

**Context After:**
```python
        self, preset: str | Mapping[str, Any] = "MINIMAL", *, wt_dir: Path | None = None, **config_overrides
    ) -> Configuration:
        """preset is a name from ConfigPresets class or a dict."""
        # Get base configuration from preset (by value or by name)
        if isinstance(preset, Mapping):
```

---

#### Issue 3: Line 125 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set the configuration preset.
```

**Context Before:**
```python
        self._preset = "MINIMAL"
```

**Context After:**
```python
        """Set the configuration preset."""
        self._preset = preset
        return self

    def with_github(self, repo: str = "test-user/test-repo", enabled: bool = True):
```

---

#### Issue 4: Line 135 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set custom worktrees directory.
```

**Context Before:**
```python
        return self
```

**Context After:**
```python
        """Set custom worktrees directory."""
        self._overrides["worktrees_dir"] = str(path)
        return self

    def with_branch_prefix(self, prefix: str):
```

---

#### Issue 5: Line 140 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set custom branch prefix.
```

**Context Before:**
```python
        return self
```

**Context After:**
```python
        """Set custom branch prefix."""
        self._overrides["branch_prefix"] = prefix
        return self

    def with_upstream_branch(self, branch: str):
```

---

#### Issue 6: Line 145 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set custom upstream branch.
```

**Context Before:**
```python
        return self
```

**Context After:**
```python
        """Set custom upstream branch."""
        self._overrides["upstream_branch"] = branch
        return self

    def with_cow_method(self, method: str):
```

---

#### Issue 7: Line 150 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set copy-on-write method.
```

**Context Before:**
```python
        return self
```

**Context After:**
```python
        """Set copy-on-write method."""
        self._overrides["cow_method"] = method
        return self

    def with_gitstatusd_path(self, path: str | Path):
```

---

#### Issue 8: Line 155 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set gitstatusd binary path.
```

**Context Before:**
```python
        return self
```

**Context After:**
```python
        """Set gitstatusd binary path."""
        self._overrides["gitstatusd_path"] = str(path)
        return self

    def with_post_creation_script(self, script_path: str | Path):
```

---

#### Issue 9: Line 160 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set post-creation script path.
```

**Context Before:**
```python
        return self
```

**Context After:**
```python
        """Set post-creation script path."""
        self._overrides["post_creation_script"] = str(script_path)
        return self

    def with_custom_field(self, field_name: str, value: Any):
```

---

#### Issue 10: Line 165 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set any custom configuration field.
```

**Context Before:**
```python
        return self
```

**Context After:**
```python
        """Set any custom configuration field."""
        self._overrides[field_name] = value
        return self

    def build(self, wt_dir: Path | None = None) -> Configuration:
```

---

### wt/tests/conftest.py

**7 issues found**

#### Issue 1: Line 151 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: return statement

**Comment:**
```
Return the WT_DIR path (the .wt directory)
```

**Context Before:**
```python
    config = factory.minimal()
```

**Context After:**
```python
    return config.wt_dir
```

---

#### Issue 2: Line 317 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up environment
```

**Context Before:**
```python
    kill_daemon_at_wt_dir(config.wt_dir)
```

**Context After:**
```python
    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)
```

---

#### Issue 3: Line 400 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up environment
```

**Context Before:**
```python
    worktree_service.create_worktree(config, "existing-2")
```

**Context After:**
```python
    env = os.environ.copy()
    env["WT_DIR"] = str(config.wt_dir)
```

---

#### Issue 4: Line 37 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set a global test-mode env var for the WT suite without monkeypatch.

Session-scoped fixtures cannot depend on the function-scoped monkeypatch fixture
```

**Context Before:**
```python

@pytest.fixture(scope="session", autouse=True)
```

**Context After:**
```python
    """Set a global test-mode env var for the WT suite without monkeypatch.

    Session-scoped fixtures cannot depend on the function-scoped monkeypatch fixture.
    Use direct os.environ mutation with a restore on teardown instead.
    """
```

---

#### Issue 5: Line 161 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set WT_DIR to the per-test cli_test_env path and return it.

Use in CLI tests to avoid repeating monkeypatch code.
```

**Context Before:**
```python

@pytest.fixture
```

**Context After:**
```python
    """Set WT_DIR to the per-test cli_test_env path and return it.

    Use in CLI tests to avoid repeating monkeypatch code.
    """
    monkeypatch.setenv("WT_DIR", str(cli_test_env))
```

---

#### Issue 6: Line 302 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up real environment for integration tests with proper cleanup.

Creates real configuration and environment setup for tests that need
to interact w
```

**Context Before:**
```python

@pytest.fixture
```

**Context After:**
```python
    """Set up real environment for integration tests with proper cleanup.

    Creates real configuration and environment setup for tests that need
    to interact with actual daemon processes and gitstatusd.
```

---

#### Issue 7: Line 381 [DOCSTRING]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set up real environment with pre-created worktrees for complex tests.
```

**Context Before:**
```python

@pytest.fixture
```

**Context After:**
```python
    """Set up real environment with pre-created worktrees for complex tests."""
    # Create config using factory pattern
    factory = config_factory(real_temp_repo)
    config = factory.integration(github_enabled=False)
```

---

### wt/tests/e2e/test_post_creation_python_script.py

**1 issues found**

#### Issue 1: Line 79 [BLOCK_COMMENT]

**Assessment**: DUPLICATE: repeats type annotation

**Comment:**
```
Using /dev/null for stdin is a valid fd (not truly "closed").
```

**Context Before:**
```python
        )
    else:
```

**Context After:**
```python
        # Current behavior: hook inherits a valid stdin, so it should succeed too.
        assert result.returncode == 0, (
            "expected success with stdin=/dev/null; got rc="
```

---

### wt/tests/mock_factory.py

**2 issues found**

#### Issue 1: Line 31 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set default behaviors
```

**Context Before:**
```python
        mock = Mock(spec=GitHubInterface)
```

**Context After:**
```python
        mock.pr_list.return_value = pr_list_returns or MockBehaviors.GitHub.empty_pr_list()
        mock.pr_search.return_value = pr_search_returns or MockBehaviors.GitHub.empty_pr_list()
        mock.pr_view.return_value = pr_view_returns
```

---

#### Issue 2: Line 54 [BLOCK_COMMENT]

**Assessment**: OBVIOUS: set statement

**Comment:**
```
Set default behaviors
```

**Context Before:**
```python
        mock = Mock(spec=GitManager)
```

**Context After:**
```python
        mock.list_branches.return_value = branches or MockBehaviors.Git.standard_branches()
        mock.list_worktrees.return_value = worktrees or []
        mock.get_working_directory_status.return_value = working_status or MockBehaviors.Git.clean_status()
```

---
