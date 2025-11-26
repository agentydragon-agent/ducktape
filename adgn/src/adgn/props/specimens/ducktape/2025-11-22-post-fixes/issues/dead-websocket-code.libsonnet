local I = import '../../specimens/lib.libsonnet';

// iss-035: Dead WebSocket code and outdated documentation

I.issueOneOccurrence(
  rationale= |||
    Multiple issues related to WebSocket code that's no longer used:

    **Problem 1: Outdated documentation calling ConnectionManager a "WebSocket connection manager"**

    The `AgentRuntime` docstring describes `_ui_manager` as a "WebSocket connection
    manager", but WebSocket endpoints no longer exist. The ConnectionManager is now
    used for sending messages via other mechanisms (ServerBus), not actual WebSocket
    connections.

    **Current implementation (registry.py, lines 20-29):**
    ```python
    @dataclass
    class AgentRuntime:
        """Holds components for a running local agent.

        Components:
        - running: Infrastructure (MCP + policy gateway)
        - runtime: Local agent (MiniCodex + session)
        - _ui_manager: WebSocket connection manager (optional)  # ← Outdated
        - _ui_bus: UI event bus (optional)

        This is a pure data holder for lifecycle management only.
        Handlers access components directly (e.g., container.running.compositor).
        """
    ```

    **The correct approach:**

    Update the documentation to reflect current usage:
    ```python
    @dataclass
    class AgentRuntime:
        """Holds components for a running local agent.

        Components:
        - running: Infrastructure (MCP + policy gateway)
        - runtime: Local agent (MiniCodex + session)
        - _ui_manager: Connection manager for UI message delivery (optional)
        - _ui_bus: UI event bus (optional)

        This is a pure data holder for lifecycle management only.
        Handlers access components directly (e.g., container.running.compositor).
        """
    ```

    Or better: rename `_ui_manager` to something more accurate like `_message_sender`
    or `_ui_connection`.

    **Problem 2: Setting fields after construction instead of in initializer**

    The `AgentRuntime` dataclass has `_ui_manager` and `_ui_bus` fields, but
    `AgentRegistry.create()` sets them after construction instead of passing them
    to the constructor.

    **Current implementation (registry.py, lines 80-83):**
    ```python
    agent_runtime = AgentRuntime(agent_id=agent_id, running=running, runtime=runtime)
    # Set UI components for backward compatibility
    agent_runtime._ui_manager = conn_mgr_out
    agent_runtime._ui_bus = ui_bus_out
    ```

    **Problems:**

    1. **Breaks dataclass contract**: Dataclass fields should be set in `__init__`
    2. **Confusing comment**: "backward compatibility" suggests this is temporary workaround
    3. **Type confusion**: Fields are nullable but always set after construction
    4. **No immutability**: Can't use `frozen=True` if setting fields after init

    **The correct approach:**

    Pass all fields to the constructor:
    ```python
    agent_runtime = AgentRuntime(
        agent_id=agent_id,
        running=running,
        runtime=runtime,
        _ui_manager=conn_mgr_out,
        _ui_bus=ui_bus_out,
    )
    ```

    Or if they're truly optional and sometimes None:
    ```python
    # build_local_agent returns None instead of creating empty objects
    running, runtime, ui_bus, conn_mgr = await build_local_agent(...)

    agent_runtime = AgentRuntime(
        agent_id=agent_id,
        running=running,
        runtime=runtime,
        _ui_manager=conn_mgr,  # Could be None
        _ui_bus=ui_bus,        # Could be None
    )
    ```

    **Problem 3: Dead WebSocket code in ConnectionManager**

    The `ConnectionManager` class in `server/runtime.py` has extensive WebSocket-related
    code (imports, methods, fields) that is never used because WebSocket endpoints are
    no longer mounted.

    **Dead WebSocket code (runtime.py):**

    **Imports (lines 11-12):**
    ```python
    from fastapi import WebSocket
    from starlette.websockets import WebSocketState
    ```

    **Fields (line 54):**
    ```python
    self._clients: dict[int, tuple[WebSocket, asyncio.Queue[Any | None], asyncio.Task]] = {}
    ```

    **Methods (lines 62-109):**
    ```python
    async def connect(self, ws: WebSocket) -> None:
        # Accept only if not already accepted by the route handler
        if ws.application_state is not WebSocketState.CONNECTED:
            try:
                await ws.accept()
            except Exception as e:
                logger.error("WebSocket accept failed", extra={"error": str(e)}, exc_info=True)
                raise
        # ... 15 more lines

    async def disconnect(self, ws: WebSocket) -> None:
        # ... 12 lines

    async def _sender_loop(self, client_id: int, ws: WebSocket, queue: asyncio.Queue[Any | None]) -> None:
        # ... 17 lines
    ```

    **Comments (line 135):**
    ```python
    # Run status mirroring removed with WebSocket status broadcasts
    ```

    **Evidence these are dead:**

    1. No WebSocket endpoints mounted (no `@app.websocket(...)` decorators)
    2. `connect()` and `disconnect()` methods never called
    3. `_sender_loop()` never called (runs when client connects)
    4. Comment in app.py: "## WebSocket message models moved to ws.py"
    5. No imports of `ConnectionManager.connect` or `.disconnect`

    **The correct approach:**

    Remove all WebSocket-specific code:

    ```python
    class ConnectionManager(BaseHandler):
        """Manages message delivery to UI clients via ServerBus."""

        def __init__(self) -> None:
            self._session: AgentSession | None = None
            self._bg_tasks: set[asyncio.Task[Any]] = set()
            self._event_id: int = 0
            self._session_id: str = str(uuid.uuid4())
            # Optional: session state change notifier for MCP resource updates
            self._session_state_notifier: Callable[[], None] | None = None
            # Remove: _clients field (was for WebSocket connections)

        # Remove: connect(), disconnect(), _sender_loop() methods

        def _next_event_id(self) -> int:
            self._event_id += 1
            return self._event_id

        async def send_payload(self, payload: ServerMessage) -> None:
            """Send message via ServerBus (not WebSocket)."""
            # ... keep the actual message sending logic
    ```

    **Or if WebSocket support is planned for the future:**

    Add clear comments and potentially move dead code to a separate branch:

    ```python
    # NOTE: WebSocket support removed - UI now uses ServerBus
    # See commit <hash> for WebSocket implementation
    # If re-adding WebSocket support, the following methods need to be restored:
    # - connect(ws: WebSocket)
    # - disconnect(ws: WebSocket)
    # - _sender_loop(...)
    ```

    But this is worse than just deleting - version control already has the history.

    **Summary:**

    1. Update AgentRuntime docstring: "WebSocket connection manager" → "UI message sender"
    2. Set `_ui_manager`/`_ui_bus` in AgentRuntime constructor, not after
    3. Remove comment about "backward compatibility"
    4. Delete dead WebSocket code from ConnectionManager:
       - Remove `WebSocket` and `WebSocketState` imports
       - Remove `_clients` field
       - Remove `connect()`, `disconnect()`, `_sender_loop()` methods
       - Remove WebSocket-related comments
    5. Consider renaming `ConnectionManager` to `MessageSender` or `UiEventEmitter`

    **Why this happened:**

    WebSocket endpoints were removed (moved to a different architecture using ServerBus),
    but the ConnectionManager wasn't cleaned up. The class evolved from managing actual
    WebSocket connections to just sending messages via an event bus, but kept the old
    infrastructure "just in case".

    This is a common pattern of technical debt: infrastructure remains after the use case
    changes, making the codebase harder to understand.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/registry.py': [
      [27, 27],   // Outdated "WebSocket connection manager" documentation
      [80, 83],   // Setting fields after construction instead of in __init__
    ],
    'adgn/src/adgn/agent/server/runtime.py': [
      [11, 12],   // Dead WebSocket imports
      [54, 54],   // Dead _clients field for WebSocket connections
      [62, 77],   // Dead connect() method
      [79, 90],   // Dead disconnect() method
      [93, 109],  // Dead _sender_loop() method
      [135, 135], // Comment about removed WebSocket functionality
    ],
  },
)
