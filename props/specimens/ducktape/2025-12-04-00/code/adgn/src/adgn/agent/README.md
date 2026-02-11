# MiniCodex (local agent + UI)

MiniCodex is a small, local, OpenAI Responses‑based code agent with an MCP-based UI.
It can run as a CLI REPL or launch a local FastAPI server with a Svelte frontend.

## Requirements
- Python env via direnv/devenv in this repo (see adgn/CLAUDE.md)
- OPENAI_API_KEY set in your environment
- Optional: one or more MCP servers configured via .mcp.json
- Authentication token in `~/.config/adgn/tokens.yaml` (see Authentication below)

## Quick start
- REPL (stdin/stdout): `adgn-mini-codex run`
- Local UI server: `adgn-mini-codex serve` (prints authenticated URL with token)
- Dev mode (auto‑picks free ports starting at 8765/5173 for backend+frontend): `adgn-mini-codex dev`

## Authentication
The UI requires bearer token authentication via MCP. Create `~/.config/adgn/tokens.yaml`:
```yaml
users:
  admin: "your-hex-token-here"
```
The CLI will print the authenticated URL with `?token=...` when you run `serve` or `dev`.

## Agent Presets
- Agents are created from presets (YAML files) discovered in:
  - `${XDG_CONFIG_HOME:-~/.config}/adgn/presets` (default via platformdirs)
  - Or the directory set in `ADGN_AGENT_PRESETS_DIR`
- Preset YAML shape:

  name: dev-echo
  description: Echo MCP + helpful system
  system: |
    You are a helpful echo agent.
  specs:
    echo:
      transport: http
      url: http://127.0.0.1:8768/mcp
      auth: <replace-with-token>

- System prompt composition: preset.system (if provided, else UI default) plus a header listing attached MCP servers
- All operations (list presets, create agents, etc.) are done via MCP tools and resources

## CLI options (selected)
- `--model MODEL` (default from OPENAI_MODEL or `o4-mini`)
- `--system TEXT`
  - REPL: default from SYSTEM_INSTRUCTIONS
  - UI (serve/dev): the server composes system from presets; CLI `--system` may still override for REPL mode
- `--mcp-config PATH` (repeatable): merge additional `.mcp.json` files (each must exist)
  - Baseline: if present, `./.mcp.json` in the current working directory is always loaded first
- `--host`, `--port`: bind address for the UI server (serve/dev)
- `--frontend-port`: Vite dev server port (dev)

.mcp.json shape (example)
```json
{
  "mcpServers": {
    "scraper": {"transport": "stdio", "command": "scraper-mcp"},
    "github":  {"transport": "stdio", "command": "github-mcp-proxy"}
  }
}
```

## UI overview
- Full‑page layout with:
  - Left: chat transcript (newest at bottom) and a bottom‑docked textarea composer
- Right sidebar: MCP connection status, current run status, list of MCP servers, pending approvals
- Server info modal: click a server row to view handshake details (instructions, server_info, protocol version, capabilities), available tools, and whether it supports resources.
- Approvals: when a tool call requires approval, the UI shows a pending item with Approve / Deny (continue) / Deny (abort)
- Dev UX: optional Markdown render for assistant responses (toggle in the sidebar); JSON tree view for tool args/outputs

## Dev workflows
There are two convenient ways to develop the UI + backend:

1) One‑command dev (recommended):
   - `adgn-mini-codex dev`
   - Starts FastAPI backend and Vite (frontend HMR). The CLI sets up ports, wiring, and MCP endpoint automatically.

2) Split processes:
   - Shell A: `adgn-mini-codex serve` (backend)
   - Shell B: `npm --prefix src/adgn/agent/web run dev` (Vite)
   - By default, the frontend uses Vite's proxy to forward `/mcp` to the backend.
   - You can set `VITE_BACKEND_ORIGIN=http://127.0.0.1:8765` for Vite if needed; otherwise the CLI/dev mode will pass it for you.

Notes:
- Dev mode picks free ports starting at `--port` (default 8765) and `--frontend-port` (default 5173).
- Static production assets are served from `src/adgn/agent/server/static` (Vite build copies there).
- All frontend-backend communication uses a single MCP endpoint at `/mcp`.

### Resources MCP Server
- A synthetic `resources` MCP server is automatically injected by the runtime. It aggregates resources across all attached servers and exposes two tools:
- `resources_list` — list resources with optional `server` and `uri_prefix` filters
- `resources_read` — windowed read for text/base64 contents (`start_offset`, `max_bytes`)
- Discovery is capability‑gated: only servers that advertise `initialize.capabilities.resources` are queried.
- See docs/mcp/resources_server.md for API details and usage patterns.

## Commands recap
```bash
# REPL
adgn-mini-codex run --model o4-mini --mcp-config /path/a.json --mcp-config /path/b.json

# UI server
adgn-mini-codex serve --host 127.0.0.1 --port 8765 --mcp-config /path/extra.json

# Dev (frontend HMR + backend)
adgn-mini-codex dev --port 8765 --frontend-port 5173 --mcp-config /path/extra.json

# Split dev (backend + Vite in separate shells)
adgn-mini-codex serve --port 8765 --mcp-config /path/extra.json
npm --prefix src/adgn/agent/web run dev
# (optional) Vite: export VITE_BACKEND_ORIGIN=http://127.0.0.1:8765
```

## Deleting Agents
- The UI provides a Delete action (Agents list and Settings → Danger Zone) that force-stops the agent and permanently deletes all of its persisted history.
- MCP tool: `agents_delete_agent` purges runs, events, approvals, policies, and proposals for the agent.
- On rare failure to flush pending writes during shutdown, the operation returns `{ ok: false, error: "drain_failed" }` and does not purge. The agent is closed and removed from the live registry; you can retry deletion once the issue is resolved (see server logs for details).

## Troubleshooting
- MCP startup errors: if an MCP server fails to launch, MiniCodex continues with others; check terminal logs for the failing server
- MCP connection issues: the UI shows a banner on connection error/close; browser console includes details
- For production UI, rebuild assets:
  - `npm --prefix src/adgn/agent/web install`
  - `npm --prefix src/adgn/agent/web run build`
