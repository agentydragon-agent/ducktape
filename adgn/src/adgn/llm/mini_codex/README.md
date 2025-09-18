# MiniCodex (local agent + UI)

MiniCodex is a small, local, OpenAI Responses‑based code agent with a simple WebSocket UI.
It can run as a CLI REPL or launch a local FastAPI server with a Svelte frontend.

## Requirements
- Python env via direnv/devenv in this repo (see adgn/CLAUDE.md)
- OPENAI_API_KEY set in your environment
- Optional: one or more MCP servers configured via .mcp.json

## Quick start
- REPL (stdin/stdout):
  - adgn-mini-codex run
- Local UI server:
  - adgn-mini-codex serve
  - Open http://127.0.0.1:8765/

## CLI options (selected)
- --model MODEL (default from OPENAI_MODEL or o4-mini)
- --system TEXT (default from SYSTEM_INSTRUCTIONS)
- --mcp-config PATH: primary .mcp.json (required to exist when passed)
- --extra-mcp-config PATH: merge additional .mcp.json file(s); may repeat; each must exist
- --host, --port: bind address for the UI server

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

## Notes & troubleshooting
- Snapshot on hello: the UI should display MCP server names and any prior messages in this process
- MCP startup errors: if an MCP server fails to launch, MiniCodex continues with others; check terminal logs for the failing server
- WebSocket diagnostics: the UI shows a banner on ws error/close; browser console includes details
- Server logs: adgn-mini-codex serve runs uvicorn with log_level=debug; look for "WS OUT" lines and exceptions
- If the UI doesn’t update, hard refresh the page; for development changes, rebuild the UI:
  - npm --prefix src/adgn/llm/mini_codex/ui/web install
  - npm --prefix src/adgn/llm/mini_codex/ui/web run build

## Dev tips
- Static assets are served from src/adgn/llm/mini_codex/ui/static/web (vite build copies there)
- The server emits typed Pydantic protocol payloads over a single WS endpoint at /ws
- The Reducer fans out typed events to handlers; the UI’s ConnectionManager is a handler

## Commands recap
```bash
# REPL
adgn-mini-codex run --model o4-mini \
  --mcp-config /path/to/.mcp.json \
  --extra-mcp-config /path/extra1.json --extra-mcp-config /path/extra2.json

# UI server
adgn-mini-codex serve --host 127.0.0.1 --port 8765 \
  --mcp-config /path/to/.mcp.json \
  --extra-mcp-config /path/extra.json
```
