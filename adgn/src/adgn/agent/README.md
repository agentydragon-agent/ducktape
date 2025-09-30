# MiniCodex (local agent + UI)

MiniCodex is a small, local, OpenAI Responses‑based code agent with a simple WebSocket UI.
It can run as a CLI REPL or launch a local FastAPI server with a Svelte frontend.

## Requirements
- Python env via direnv/devenv in this repo (see adgn/CLAUDE.md)
- OPENAI_API_KEY set in your environment
- Optional: one or more MCP servers configured via .mcp.json

## Quick start
- REPL (stdin/stdout): `adgn-mini-codex run`
- Local UI server: `adgn-mini-codex serve`, open http://127.0.0.1:8765/
- Dev mode (auto‑picks free ports starting at 8765/5173 for backend+frontend): `adgn-mini-codex dev`

## CLI options (selected)
- `--model MODEL` (default from OPENAI_MODEL or `o4-mini`)
- `--system TEXT`
  - REPL: default from SYSTEM_INSTRUCTIONS
  - UI (serve/dev): if omitted, a UI‑specific default system message is used
- `--mcp-config PATH` (repeatable): merge additional `.mcp.json` files (each must exist)
  - Baseline: if present, `./.mcp.json` in the current working directory is always loaded first
- `--host`, `--port`: bind address for the UI server (serve/dev)
- `--frontend-port`: Vite dev server port (dev)

.mcp.json shape (example)
```json
{
  "mcpServers": {
    "scraper": {"type": "stdio", "command": "scraper-mcp"},
    "github":  {"type": "stdio", "command": "github-mcp-proxy"}
  }
}
```

## UI overview
- Full‑page layout with:
  - Left: chat transcript (newest at bottom) and a bottom‑docked textarea composer
  - Right sidebar: WebSocket status dot, current run status, list of MCP servers, pending approvals
- On connect the server sends an "accepted" ack and a Snapshot that includes any transcript seen in this process
- Approvals: when a tool call requires approval, the UI shows a pending item with Approve / Deny (continue) / Deny (abort)
- Dev UX: optional Markdown render for assistant responses (toggle in the sidebar); JSON tree view for tool args/outputs

## Dev workflows
There are two convenient ways to develop the UI + backend:

1) One‑command dev (recommended):
   - `adgn-mini-codex dev`
   - Starts FastAPI backend and Vite (frontend HMR). The CLI sets up ports, wiring, and WS endpoints automatically.

2) Split processes:
   - Shell A: `adgn-mini-codex serve` (backend)
   - Shell B: `npm --prefix src/adgn/llm/mini_codex/ui/web run dev` (Vite)
   - By default, the frontend uses Vite’s proxy to forward `/ws` (and some simple JSON endpoints like `/transcript`) to the backend.
   - You can set `VITE_BACKEND_ORIGIN=http://127.0.0.1:8765` for Vite if needed; otherwise the CLI/dev mode will pass it for you.

Notes:
- Dev mode picks free ports starting at `--port` (default 8765) and `--frontend-port` (default 5173).
- Static production assets are served from `src/adgn/llm/mini_codex/ui/static/web` (Vite build copies there).
- The server emits typed Pydantic protocol payloads over a single WS endpoint at `/ws`.

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
npm --prefix src/adgn/llm/mini_codex/ui/web run dev
# (optional) Vite: export VITE_BACKEND_ORIGIN=http://127.0.0.1:8765
```

## Troubleshooting
- MCP startup errors: if an MCP server fails to launch, MiniCodex continues with others; check terminal logs for the failing server
- WebSocket diagnostics: the UI shows a banner on ws error/close; browser console includes details
- For production UI, rebuild assets:
  - `npm --prefix src/adgn/llm/mini_codex/ui/web install`
  - `npm --prefix src/adgn/llm/mini_codex/ui/web run build`
