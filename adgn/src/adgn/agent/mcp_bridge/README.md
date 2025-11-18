# HTTP MCP Bridge

Exposes policy-gated MCP infrastructure to external agents (ChatGPT, Claude.ai, etc.) via HTTP/SSE transport.

## What It Does

The MCP Bridge allows external agents to connect to your local infrastructure and execute commands through the approval policy system:

- **Policy-Gated Execution**: All tool calls go through approval policy evaluation
- **Docker Execution**: Run commands in isolated Docker containers (optionally with repo mounted)
- **Approval Management**: Propose policy changes, read active policy
- **Live Reconfiguration**: Attach/detach MCP servers at runtime (policy-gated)

## Usage

### Basic (No Docker Exec)

```bash
adgn-mcp-bridge serve --agent-id external-agent
```

This starts the bridge at `http://127.0.0.1:8080` with:
- Core infrastructure (compositor, policy gateway, approval policy)
- No docker exec (add via `--mcp-config` if needed)
- Default policy (allows resources, denies compositor_admin by default)

### With Repo-Mounted Docker Exec

1. Create `docker-exec.json`:
```json
{
  "mcpServers": {
    "docker": {
      "transport": "stdio",
      "command": "docker-exec-mcp",
      "args": ["--mount", "/home/user/ducktape:/workspace:ro"]
    }
  }
}
```

2. Start bridge:
```bash
adgn-mcp-bridge serve \\
    --agent-id external-chatgpt \\
    --mcp-config ./docker-exec.json
```

### With Custom Policy

```bash
adgn-mcp-bridge serve \\
    --agent-id external-agent \\
    --initial-policy ./my-policy.py
```

## Architecture

```
External Agent (ChatGPT/Claude)
    ↓ (MCP over HTTP/SSE)
HTTP MCP Bridge (FastAPI + SSE)
    ↓
RunningInfrastructure
    ├─ Compositor (FastMCP server aggregator)
    ├─ Policy Gateway (approval enforcement middleware)
    └─ Approval Policy Engine (Docker-based evaluation)
        ↓
Mounted MCP Servers (via MCPConfig)
    ├─ docker (exec with optional repo mount)
    ├─ approval_policy (read + propose)
    └─ compositor_admin (attach/detach servers)
```

## External Agent Configuration

External agents connect using standard MCP-over-HTTP configuration:

```json
{
  "mcpServers": {
    "my-infrastructure": {
      "transport": "http",
      "url": "http://localhost:8080/mcp",
      "timeout_secs": 30
    }
  }
}
```

## Security Considerations

### Approval Policy

The default policy for external agents:
- **ALLOW**: Resource reads, proposal creation
- **DENY_ABORT**: compositor_admin (attach/detach requires explicit policy approval)
- **ASK**: Not recommended (external agents timeout on blocking approvals)

### Repo Mounting

When mounting your repository:
- Use **read-only** mode (`:ro`) by default
- Add writable scratch directory if needed: `--mount /path/.agent-scratch:/scratch:rw`
- Review your policy to ensure safe command execution

### Network Exposure

- Default binds to `127.0.0.1` (localhost only)
- For external access, use reverse proxy (nginx, caddy) with TLS + auth
- TODO: Add built-in token authentication (token → agent_id mapping)

## CLI Options

```
--agent-id          Agent identifier (required)
--db-path           SQLite database path (default: XDG user data dir)
--mcp-config        Path to .mcp.json (servers to mount)
--host              Bind host (default: 127.0.0.1)
--port              Bind port (default: 8080)
--initial-policy    Path to initial policy .py file
```

## Status

**Core Functionality: ✅ Complete (Single Agent)**

The HTTP MCP Bridge is fully functional for a single external agent:
- ✅ HTTP/SSE transport endpoint (via FastMCP's `http_app()`)
- ✅ Policy-gated tool execution
- ✅ Compositor with mounted MCP servers
- ✅ Approval policy engine (Docker-based evaluation)
- ✅ Standard MCP server resources and tools

**Current Limitation**: Single agent per bridge instance. The `agent_id` is configured at startup via CLI, and all connections share the same infrastructure. For multiple external agents, run separate bridge instances on different ports.

## Future Enhancements

These features would improve production deployment:

- [ ] **Token Authentication + Multi-Tenancy**:
  - Read `Authorization: Bearer <token>` header to determine agent_id
  - Create/cache separate infrastructure per agent_id
  - Enables multiple external agents connecting to single bridge instance
  - Example: ChatGPT on port 8080, Claude.ai on same port, different tokens

- [ ] **Idle Cleanup**: Auto-shutdown infrastructure after N minutes of inactivity

- [ ] **Unified Instructions**: Merge server instructions in initialization message

- [ ] **Web UI**: Browser-based approval management (human-in-the-loop oversight)
