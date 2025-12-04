local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    The codebase contains extensive WebSocket-related code and documentation that is no longer used because WebSocket endpoints are no longer mounted.

    **Problem 1: Outdated documentation in AgentRuntime**

    The `AgentRuntime` docstring (registry.py line 27) describes `_ui_manager` as a "WebSocket connection manager", but WebSocket endpoints no longer exist. The ConnectionManager is now used for sending messages via ServerBus, not actual WebSocket connections.

    Update documentation to reflect current usage: "Connection manager for UI message delivery (optional)" or rename `_ui_manager` to something more accurate like `_message_sender` or `_ui_connection`.

    **Problem 2: Dead WebSocket code in ConnectionManager**

    The `ConnectionManager` class in `runtime.py` has extensive WebSocket-related code (imports, methods, fields) that is never used:

    **Dead code includes:**
    - WebSocket imports (lines 11-12): `from fastapi import WebSocket`, `from starlette.websockets import WebSocketState`
    - `_clients` field (line 54): `dict[int, tuple[WebSocket, asyncio.Queue[Any | None], asyncio.Task]]`
    - `connect()` method (lines 62-77): accepts and registers WebSocket connections
    - `disconnect()` method (lines 79-90): unregisters WebSocket connections
    - `_sender_loop()` method (lines 93-109): sends messages over WebSocket
    - Comment (line 135): "Run status mirroring removed with WebSocket status broadcasts"

    **Evidence these are dead:**
    1. No WebSocket endpoints mounted (no `@app.websocket(...)` decorators)
    2. `connect()` and `disconnect()` methods never called
    3. `_sender_loop()` never called (runs when client connects)
    4. No imports of `ConnectionManager.connect` or `.disconnect`

    **Correct approach:**

    Remove all WebSocket-specific code. The ConnectionManager should focus on its current purpose: managing message delivery to UI clients via ServerBus. Version control already has the history if WebSocket support needs to be restored.

    Optionally rename `ConnectionManager` to `MessageSender` or `UiEventEmitter` to reflect its actual purpose.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/registry.py': [[27, 27]],
    'adgn/src/adgn/agent/server/runtime.py': [
      [11, 12],
      [54, 54],
      [62, 77],
      [79, 90],
      [93, 109],
      [135, 135],
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/runtime/registry.py'],
    ['adgn/src/adgn/agent/server/runtime.py'],
  ],
)
