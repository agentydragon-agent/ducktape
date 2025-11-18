# HTTP MCP Bridge

Exposes policy-gated MCP infrastructure to external agents (ChatGPT, Claude.ai, etc.) via HTTP/SSE transport.

## What It Does

The MCP Bridge allows external agents to connect to your local infrastructure and execute commands through the approval policy system:

- **Policy-Gated Execution**: All tool calls go through approval policy evaluation
- **Docker Execution**: Run commands in isolated Docker containers (optionally with repo mounted)
- **Approval Management**: Propose policy changes, read active policy
- **Live Reconfiguration**: Attach/detach MCP servers at runtime (policy-gated)

## Usage

### Single-Agent Mode (Simple)

```bash
adgn-mcp-bridge serve --agent-id external-agent
```

This starts the bridge at `http://127.0.0.1:8080` with:
- Core infrastructure (compositor, policy gateway, approval policy)
- No docker exec (add via `--mcp-config` if needed)
- Default policy (allows resources, denies compositor_admin by default)
- All connections share the same agent infrastructure

### Multi-Agent Mode (Token Authentication)

1. Create `tokens.json`:
```json
{
  "secret-token-123": "chatgpt-agent",
  "secret-token-456": "claude-agent"
}
```

2. Start bridge:
```bash
adgn-mcp-bridge serve --auth-tokens ./tokens.json
```

This enables multiple agents on the same bridge:
- Each token maps to a unique agent_id
- Infrastructure is created lazily per agent_id
- Requests must include `Authorization: Bearer <token>` header

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

### Single-Agent Mode

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

### Multi-Agent Mode

When using token authentication, include the Authorization header:

```json
{
  "mcpServers": {
    "my-infrastructure": {
      "transport": "http",
      "url": "http://localhost:8080/mcp",
      "timeout_secs": 30,
      "headers": {
        "Authorization": "Bearer secret-token-123"
      }
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
- For external access, use reverse proxy (nginx, caddy) with TLS
- Use `--auth-tokens` for built-in token authentication (token → agent_id mapping)
- Token auth enables safe multi-agent deployment on single port

## CLI Options

```
--agent-id          Agent identifier for single-agent mode (mutually exclusive with --auth-tokens)
--auth-tokens       Path to JSON token mapping file for multi-agent mode (mutually exclusive with --agent-id)
--db-path           SQLite database path (default: XDG user data dir)
--mcp-config        Path to .mcp.json (servers to mount)
--host              Bind host (default: 127.0.0.1)
--port              Bind port (default: 8080)
--initial-policy    Path to initial policy .py file
```

**Note**: Must provide exactly one of `--agent-id` or `--auth-tokens`.

## Status

**Core Functionality: ✅ Complete**

The HTTP MCP Bridge is fully functional with support for both single-agent and multi-agent deployments:
- ✅ HTTP/SSE transport endpoint (via FastMCP's `http_app()`)
- ✅ Policy-gated tool execution
- ✅ Compositor with mounted MCP servers
- ✅ Approval policy engine (Docker-based evaluation)
- ✅ Standard MCP server resources and tools
- ✅ Token authentication for multi-tenancy
- ✅ Lazy infrastructure creation per agent_id

**Deployment Modes**:
- **Single-agent**: Simple mode with `--agent-id` (all connections share infrastructure)
- **Multi-agent**: Token auth mode with `--auth-tokens` (separate infrastructure per agent_id)

## Future Enhancements

These features would improve production deployment:

- [ ] **Idle Cleanup**: Auto-shutdown infrastructure after N minutes of inactivity per agent_id

- [ ] **Token Reload**: Hot-reload token mapping file without restart (watch file for changes)

- [ ] **Unified Instructions**: Merge server instructions in initialization message

- [ ] **Web UI**: Browser-based approval management (human-in-the-loop oversight)

- [ ] **Metrics**: Per-agent usage metrics (tool calls, approvals, policy evaluations)
