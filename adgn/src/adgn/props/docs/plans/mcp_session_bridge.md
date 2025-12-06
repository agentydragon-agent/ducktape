# MCP Session Bridge: Unix Socket to HTTP SSE

## Overview

The MCP Session Bridge is a transparent forwarder that maintains a single persistent MCP session over HTTP SSE while allowing multiple ephemeral processes to connect via Unix domain socket.

**Problem it solves:** Agent code runs as ephemeral `docker__exec` subprocesses that can't maintain state between invocations. But we want:
- One persistent MCP session to the upstream server (avoiding re-initialization overhead)
- Background notification accumulation (while no subprocess is connected)
- Multiple sequential subprocess connections sharing the same session

**Solution:** A bridge process that:
1. Maintains one HTTP SSE connection to upstream MCP server
2. Exposes a Unix domain socket for local connections
3. Forwards JSON-RPC frames bidirectionally
4. Buffers notifications when no client is connected

## Architecture

```
Host Machine:
  MCP Server (HTTP SSE at host.docker.internal:54321)
       ↑
       │ persistent HTTP SSE connection
       │ (single MCP session)
       │
Container:
  Bridge Process (/tmp/mcp.sock)
       ↑
       │ Unix domain socket
       │ (ephemeral connections)
       │
  Agent Subprocess 1 ─→ connect, send request, read response, disconnect
  Agent Subprocess 2 ─→ connect, send request, read response, disconnect
  Agent Subprocess 3 ─→ connect, read notifications, disconnect
```

## Key Properties

- **Protocol-agnostic:** Bridge doesn't parse or understand MCP protocol - just forwards frames
- **First client initializes:** First subprocess sends the `initialize` request with desired capabilities
- **Notification buffering:** When no client connected, incoming notifications are queued
- **Buffer flush on connect:** Client gets all buffered notifications immediately on connection
- **Sequential access:** Only one subprocess connected at a time (matches `docker__exec` pattern)
- **Transparent forwarding:** Upstream server sees a normal MCP client, subprocess sees a normal MCP server

## Protocol Details: Streamable HTTP Session Flow

### Initial Connection and Session ID

When the bridge starts, `streamablehttp_client` establishes the connection:

**Step 1: Open SSE Stream**

```http
GET /mcp/v1 HTTP/1.1
Host: host.docker.internal:54321
Accept: text/event-stream
Authorization: Bearer secret-token-123
```

Server response:

```http
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-MCP-Session-ID: sess_abc123def456
```

**Key:** Server assigns a session ID in `X-MCP-Session-ID` header. The `streamablehttp_client` reads this and stores it. This is what `get_session_id()` returns.

```python
async with streamablehttp_client(url, headers={...}) as (read, write, get_session_id):
    session_id = get_session_id()  # Returns "sess_abc123def456"
```

### Initialization Handshake

**Step 2: Client Sends Initialize (via POST)**

```http
POST /mcp/v1/messages?sessionId=sess_abc123def456 HTTP/1.1
Host: host.docker.internal:54321
Content-Type: application/json
Authorization: Bearer secret-token-123

{
  "jsonrpc": "2.0",
  "id": 0,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {"roots": {"listChanged": true}, "sampling": {}},
    "clientInfo": {"name": "mcp-bridge", "version": "1.0.0"}
  }
}
```

**Key:** Session ID goes in query parameter `?sessionId=...`. The POST returns immediately (HTTP 202 Accepted).

**Step 3: Server Responds via SSE Stream**

Response arrives over the SSE stream opened in Step 1:

```
data: {"jsonrpc":"2.0","id":0,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{},"resources":{"subscribe":true}},"serverInfo":{"name":"critic_submit","version":"1.0.0"}}}

```

**Key:** Response comes over SSE stream, NOT as HTTP response to POST.

**Step 4: Client Sends Initialized Notification**

```http
POST /mcp/v1/messages?sessionId=sess_abc123def456 HTTP/1.1
Content-Type: application/json

{"jsonrpc": "2.0", "method": "notifications/initialized"}
```

No SSE response (notifications are fire-and-forget).

### Session Active - Request/Response Flow

**Step 5: Tool Call**

```http
POST /mcp/v1/messages?sessionId=sess_abc123def456 HTTP/1.1
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {"name": "submit", "arguments": {...}}
}
```

Response via SSE:

```
data: {"jsonrpc":"2.0","id":2,"result":{"success":true}}

```

**Step 6: Server Notification (Asynchronous)**

Server pushes notification over SSE:

```
data: {"jsonrpc":"2.0","method":"notifications/resources/updated","params":{"uri":"resource://..."}}

```

**Key:** No request ID - this is unsolicited.

### What streamablehttp_client Handles

The bridge doesn't manage session IDs directly. `streamablehttp_client` does:

```python
# Simplified internal view
class StreamableHttpClient:
    async def __aenter__(self):
        # 1. Open SSE stream, extract session ID from header
        response = await httpx_client.get(url, headers={"Accept": "text/event-stream", ...})
        self.session_id = response.headers.get("X-MCP-Session-ID")

        # 2. Return read/write streams
        return (self.sse_reader, self._write_with_session_id, lambda: self.session_id)

    async def _write_with_session_id(self, message_bytes):
        """Automatically adds session ID to POST requests"""
        await httpx_client.post(
            f"{url}/messages?sessionId={self.session_id}",
            content=message_bytes,
            headers={"Content-Type": "application/json"}
        )
```

**Bridge's simplified view:**

```python
async with streamablehttp_client(...) as (read, write, get_session_id):
    # Bridge just:
    await write(json_frame)  # Session ID added automatically
    frame = await read()     # Gets responses AND notifications
```

### Complete Timeline

```
T=0ms: Bridge connects
  GET /mcp/v1 → HTTP 200, X-MCP-Session-ID: sess_abc123

T=100ms: First subprocess connects to /tmp/mcp.sock
  Sends: {"id": 0, "method": "initialize", ...}

T=110ms: Bridge forwards
  POST /messages?sessionId=sess_abc123 → HTTP 202

T=120ms: Server responds via SSE
  data: {"id": 0, "result": {...}}

T=125ms: Bridge forwards to subprocess
  Unix socket: {"id": 0, "result": {...}}

T=200ms: First subprocess disconnects

T=2000ms: Server sends notification
  SSE: data: {"method": "notifications/resources/updated", ...}

T=2005ms: Bridge buffers (no client connected)

T=5000ms: Second subprocess connects
  Bridge flushes buffered notification

T=5010ms: Subprocess sends tool call
  Bridge forwards: POST /messages?sessionId=sess_abc123  # Same session!

T=5100ms: Server responds via SSE
  Bridge forwards to subprocess
```

**Key insight:** The same session ID (`sess_abc123`) is used for ALL requests, even from different subprocesses. This is what makes the bridge valuable - multiple subprocess invocations share one persistent upstream session.

## Implementation

```python
import asyncio
import json
import os
from collections import deque
from pathlib import Path
from mcp.client.streamable_http import streamablehttp_client

class MCPSessionBridge:
    """
    Transparent forwarder between Unix socket and HTTP SSE MCP connection.

    Maintains one persistent upstream session, allows multiple sequential
    local clients via Unix socket.
    """

    def __init__(self, upstream_url: str, token: str, socket_path: str):
        """
        Args:
            upstream_url: HTTP SSE endpoint (e.g., "http://host.docker.internal:54321")
            token: Bearer token for upstream auth
            socket_path: Unix socket path to create (e.g., "/tmp/mcp.sock")
        """
        self.upstream_url = upstream_url
        self.token = token
        self.socket_path = Path(socket_path)
        self.notification_buffer = deque(maxlen=1000)
        self.current_client = None
        self.initialized = False

    async def start(self):
        """Main bridge lifecycle - blocks until upstream closes"""

        print(f"[Bridge] Connecting to {self.upstream_url}")
        async with streamablehttp_client(
            self.upstream_url,
            headers={"Authorization": f"Bearer {self.token}"}
        ) as (http_read, http_write, get_session_id):

            self.http_read = http_read
            self.http_write = http_write

            print(f"[Bridge] Connected, session ID: {get_session_id()}")

            # Start background task: read from upstream, forward or buffer
            notification_task = asyncio.create_task(
                self._collect_from_upstream()
            )

            # Serve Unix socket - blocks here
            print(f"[Bridge] Ready at {self.socket_path}")
            await self._serve_unix_socket()

    async def _collect_from_upstream(self):
        """
        Background task: Read from upstream SSE stream.
        Forward to current client if connected, otherwise buffer notifications.
        """
        while True:
            try:
                frame_raw = await self.http_read()
                if frame_raw is None:
                    print("[Bridge] Upstream closed")
                    break

                # Optional: detect initialization (for logging)
                try:
                    message = json.loads(frame_raw)
                    if not self.initialized and message.get("id") == 0:
                        self.initialized = True
                        server_info = message.get("result", {}).get("serverInfo", {})
                        print(f"[Bridge] Session initialized: {server_info.get('name')}")
                except (json.JSONDecodeError, KeyError):
                    pass

                # Forward to current client or buffer
                if self.current_client:
                    self.current_client.write(frame_raw + b'\n')
                    await self.current_client.drain()
                else:
                    # No client connected - buffer (only notifications, not responses)
                    try:
                        message = json.loads(frame_raw)
                        # Notification = has 'method' but no 'id'
                        if "method" in message and "id" not in message:
                            self.notification_buffer.append(frame_raw)
                    except json.JSONDecodeError:
                        pass

            except Exception as e:
                print(f"[Bridge] Error in upstream reader: {e}")
                break

    async def _serve_unix_socket(self):
        """Serve Unix socket - handle client connections"""
        self.socket_path.unlink(missing_ok=True)

        async def handle_client(reader, writer):
            print("[Bridge] Client connected")
            self.current_client = writer

            try:
                # Flush buffered notifications on connect
                while self.notification_buffer:
                    buffered = self.notification_buffer.popleft()
                    writer.write(buffered + b'\n')
                    await writer.drain()

                # Forward client → upstream
                while True:
                    line = await reader.readline()
                    if not line:
                        break

                    # Forward to upstream (strip trailing newline)
                    await self.http_write(line.rstrip(b'\n'))

            except Exception as e:
                print(f"[Bridge] Error handling client: {e}")

            finally:
                print("[Bridge] Client disconnected")
                self.current_client = None
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_unix_server(
            handle_client, path=str(self.socket_path)
        )

        async with server:
            await server.serve_forever()


# Entry point
async def main():
    """Start bridge from environment variables"""
    upstream_url = os.getenv('MCP_SERVER_URL')
    token = os.getenv('MCP_SERVER_TOKEN')
    socket_path = os.getenv('MCP_SOCKET_PATH', '/tmp/mcp.sock')

    if not upstream_url or not token:
        raise ValueError("MCP_SERVER_URL and MCP_SERVER_TOKEN required")

    bridge = MCPSessionBridge(upstream_url, token, socket_path)
    await bridge.start()

if __name__ == '__main__':
    asyncio.run(main())
```

## Usage

### Starting the Bridge

In container entrypoint or as background process:

```bash
# Environment setup
export MCP_SERVER_URL="http://host.docker.internal:54321"
export MCP_SERVER_TOKEN="secret-token-here"
export MCP_SOCKET_PATH="/tmp/mcp.sock"

# Start bridge (blocks)
python -m mcp_bridge
```

Or as background task:

```bash
python -m mcp_bridge &
BRIDGE_PID=$!
```

### First Client: Initialize Session

```python
# Subprocess 1: Initialize with desired capabilities
import socket
import json

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/tmp/mcp.sock')

# Send initialize
init_request = {
    "jsonrpc": "2.0",
    "id": 0,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {
            "roots": {"listChanged": True},
            "sampling": {},
        },
        "clientInfo": {
            "name": "my-agent",
            "version": "1.0.0"
        }
    }
}
sock.sendall(json.dumps(init_request).encode() + b'\n')

# Read response
response = json.loads(sock.recv(65536).decode())
print(f"Server: {response['result']['serverInfo']['name']}")

# Send initialized notification
initialized = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized"
}
sock.sendall(json.dumps(initialized).encode() + b'\n')

sock.close()
```

### Subsequent Clients: Use Existing Session

```python
# Subprocess 2: Subscribe to resources (no init needed)
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/tmp/mcp.sock')

subscribe_request = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "resources/subscribe",
    "params": {"uri": "resource://snapshot/metadata"}
}
sock.sendall(json.dumps(subscribe_request).encode() + b'\n')

response = json.loads(sock.recv(65536).decode())
print(f"Subscribed: {response}")

sock.close()
```

```python
# Subprocess 3: Call tool
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/tmp/mcp.sock')

tool_call = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "submit",
        "arguments": {"issue_id": "foo", "rationale": "bar"}
    }
}
sock.sendall(json.dumps(tool_call).encode() + b'\n')

response = json.loads(sock.recv(65536).decode())
print(f"Result: {response['result']}")

sock.close()
```

### Reading Notifications

```python
# Subprocess 4: Check for notifications
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/tmp/mcp.sock')

# On connect, bridge flushes any buffered notifications
# Set non-blocking to read what's available
sock.setblocking(False)

try:
    while True:
        data = sock.recv(4096)
        if not data:
            break
        message = json.loads(data.decode())
        if message.get("method") == "notifications/resources/updated":
            print(f"Resource updated: {message['params']['uri']}")
except BlockingIOError:
    # No more buffered notifications
    pass

sock.close()
```

## Complete Example Workflow

```python
async def agent_workflow():
    """Simulate agent workflow using bridge"""

    # === Setup (once, in container entrypoint) ===
    bridge = MCPSessionBridge(
        upstream_url="http://host.docker.internal:54321",
        token="secret-token",
        socket_path="/tmp/mcp.sock"
    )
    bridge_task = asyncio.create_task(bridge.start())
    await asyncio.sleep(0.5)  # Let it connect

    # === Agent subprocess 1: Initialize ===
    reader1, writer1 = await asyncio.open_unix_connection("/tmp/mcp.sock")

    init = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {...}}
    writer1.write(json.dumps(init).encode() + b'\n')
    await writer1.drain()

    response = await reader1.readline()
    print(f"Initialized: {json.loads(response)}")

    writer1.close()
    await writer1.wait_closed()

    # === Agent subprocess 2: Subscribe ===
    reader2, writer2 = await asyncio.open_unix_connection("/tmp/mcp.sock")

    subscribe = {"jsonrpc": "2.0", "id": 1, "method": "resources/subscribe", ...}
    writer2.write(json.dumps(subscribe).encode() + b'\n')
    await writer2.drain()

    response = await reader2.readline()
    print(f"Subscribed: {json.loads(response)}")

    writer2.close()
    await writer2.wait_closed()

    # === (Time passes, server sends notification) ===
    await asyncio.sleep(2)

    # === Agent subprocess 3: Read notifications + call tool ===
    reader3, writer3 = await asyncio.open_unix_connection("/tmp/mcp.sock")

    # Immediately get buffered notification
    notif = await reader3.readline()
    print(f"Got notification: {json.loads(notif)}")

    # Call tool
    tool_call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", ...}
    writer3.write(json.dumps(tool_call).encode() + b'\n')
    await writer3.drain()

    response = await reader3.readline()
    print(f"Tool result: {json.loads(response)}")

    writer3.close()
    await writer3.wait_closed()
```

## When to Use This Pattern

**Use the bridge when:**
- Agent runs as ephemeral subprocesses (e.g., `docker__exec`)
- Need background notification accumulation
- Want to avoid re-initialization overhead
- Want to maintain subscriptions across subprocess invocations

**Don't use the bridge when:**
- Agent can maintain long-lived Python process
- No need for notifications between invocations
- Single-shot tool calls only (direct MCP connection is simpler)

## Design Decisions

### Why Unix Socket?

- **Zero network overhead:** In-kernel IPC
- **No port conflicts:** Named path in filesystem
- **Simple auth:** File permissions control access
- **Standard:** Works with any language that has socket support

### Why Not Maintain Multiple Sessions?

Could have bridge create a new upstream session per client, but:
- Initialization overhead on every subprocess
- Lose notification subscriptions between calls
- Server sees rapid connect/disconnect churn
- More complex bridge implementation

### Why Buffer Notifications?

If we drop notifications when no client connected:
- Client polls miss updates
- Need server-side re-subscription on every connect
- Can't accumulate state between subprocess calls

Buffering allows:
- Reliable notification delivery
- Client reads what happened while it was disconnected
- Natural "check for updates" pattern

### Why Protocol-Agnostic?

Bridge could parse and validate MCP frames, but:
- Simpler implementation (just forward bytes)
- Future-proof (works with protocol changes)
- Lower latency (no parse/serialize overhead)
- Works with protocol extensions

The only protocol knowledge: distinguish notifications (buffer) from responses (forward immediately).

## Container Integration

### Dockerfile

```dockerfile
# Install bridge script
COPY mcp_bridge.py /usr/local/bin/mcp-bridge
RUN chmod +x /usr/local/bin/mcp-bridge

# Optional: Make bridge PID 1 for automatic cleanup
ENTRYPOINT ["/usr/local/bin/mcp-bridge"]
```

### Docker Environment

```yaml
environment:
  - MCP_SERVER_URL=http://host.docker.internal:54321
  - MCP_SERVER_TOKEN=secret-token
  - MCP_SOCKET_PATH=/tmp/mcp.sock
```

### Agent Runbook Instructions

Include in agent prompt:

```markdown
## Long-Running MCP Session (Optional)

If you need background notifications, a bridge maintains a persistent MCP session at `/tmp/mcp.sock`.

### First time: Initialize
```python
import socket, json
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/tmp/mcp.sock')
sock.send(json.dumps({"jsonrpc": "2.0", "id": 0, "method": "initialize", ...}).encode() + b'\n')
response = json.loads(sock.recv(65536))
sock.close()
```

### Subsequent calls: Just use it
```python
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('/tmp/mcp.sock')
sock.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", ...}).encode() + b'\n')
response = json.loads(sock.recv(65536))
sock.close()
```

On connect, you'll immediately receive any buffered notifications.
```

## Future Enhancements

- **Multiple concurrent clients:** Track request IDs to route responses correctly
- **Reconnect logic:** Auto-reconnect upstream on connection loss
- **Metrics:** Track request counts, buffer size, connection duration
- **Notification filters:** Let clients specify which notifications to buffer
- **TTL for buffered notifications:** Expire old notifications after N seconds
- **Bridge control API:** Query status, clear buffer, force reconnect

## References

- MCP Protocol Spec: https://spec.modelcontextprotocol.io
- Streamable HTTP Transport: https://spec.modelcontextprotocol.io/specification/architecture/transports/#streamable-http
- Unix Domain Sockets: `man 7 unix`
