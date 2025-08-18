# Jupyter MCP STDIO Guard — Manual tmux Testing Recipe

This is a concise, repeatable workflow to drive the MCP server over stdio manually using tmux.
Use this to debug and validate before encoding flows into pytest.

## 0) Layout & Environment

- Three tmux panes in one window:
  - Pane 1: Jupyter Server
  - Pane 2: MCP server (stdio)
  - Pane 3: Logs and clipboard (paste JSON lines here or into Pane 2)

Create layout
```bash
# New tmux session with 3 panes (left, right, bottom-left)
tmux new-session -s mcp-dev -n jupyter -d
tmux split-window -t mcp-dev:0 -h
tmux split-window -t mcp-dev:0.0 -v
# Focus left-top (Pane 1)
tmux select-pane -t mcp-dev:0.0
# Attach
tmux attach -t mcp-dev
```

Set up workspace variables (run in any pane, recommended Pane 3):
```bash
WS="$PWD/_mcp_ws"; mkdir -p "$WS/.mcp" "$WS/logs"
PORT=$(python - <<'PY'
import socket
s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()
PY)
TOKEN=$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(16))
PY)
```

Create minimal notebook once (or reuse existing):
```bash
cat >"$WS/.mcp/test.ipynb" <<'JSON'
{"cells":[],"metadata":{"kernelspec":{"name":"python3","display_name":"Python 3","language":"python"}},"nbformat":4,"nbformat_minor":5}
JSON
```

## 1) Pane 1 — Launch Jupyter Server

```bash
set -euxo pipefail
: "${WS:?}"; : "${PORT:?}"; : "${TOKEN:?}"
cd "$WS"
jupyter server \
  --port "$PORT" \
  --ip 127.0.0.1 \
  --ServerApp.root_dir "$WS" \
  --ServerApp.open_browser False \
  --ServerApp.token "$TOKEN" \
  --ServerApp.password '' \
  --ServerApp.disable_check_xsrf True \
  >"$WS/logs/jupyter.out" 2>"$WS/logs/jupyter.err"
```

Verify port readiness (optional):
```bash
python - <<'PY'
import socket, os, time
port = int(os.environ['PORT']); deadline=time.time()+20
ok=False
while time.time()<deadline:
  try:
    with socket.create_connection(("127.0.0.1", port), 0.5): ok=True; break
  except OSError: time.sleep(0.1)
print("READY" if ok else "NOT READY")
PY
```

## 2) Pane 2 — Start MCP server (stdio)

Option A: Direct jupyter-mcp-server (baseline unsandbox)
```bash
set -euxo pipefail
: "${WS:?}"; : "${PORT:?}"; : "${TOKEN:?}"
TS=$(date +%s)
MCP_OUT="/tmp/sjmcp-${TS}-stdout.log"
MCP_ERR="/tmp/sjmcp-${TS}-stderr.log"

jupyter-mcp-server start \
  --transport stdio \
  --provider jupyter \
  --document-url "http://127.0.0.1:${PORT}" \
  --document-id ".mcp/test.ipynb" \
  --document-token "${TOKEN}" \
  --runtime-url "http://127.0.0.1:${PORT}" \
  --runtime-token "${TOKEN}" \
  --start-new-runtime true \
  | tee "$MCP_OUT" \
  2> >(tee "$MCP_ERR" >&2)
```

Option B: Wrapper (kernel unsandboxed)
```bash
python -m jupyter_mcp_stdio_guard \
  --workspace "$WS" \
  --mode seatbelt \
  --jupyter-port "$PORT" \
  --no-kernel-sandbox \
  | tee "$MCP_OUT" 2> >(tee "$MCP_ERR" >&2)
```

Option C: Wrapper (macOS seatbelt)
```bash
python -m jupyter_mcp_stdio_guard \
  --workspace "$WS" \
  --mode seatbelt \
  --jupyter-port "$PORT" \
  --trace-sandbox \
  | tee "$MCP_OUT" 2> >(tee "$MCP_ERR" >&2)
```

## 3) Pane 3 — Drive MCP JSON over stdio

Paste the following (one JSON per line, press Enter after each):

Initialize
```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"clientInfo":{"name":"tmux-dev","version":"0.0.1"}}}
```

Notify initialized
```json
{"jsonrpc":"2.0","method":"notifications/initialized"}
```

Call tool
```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"append_execute_code_cell","arguments":{"cell_source":"print('hello world')"}}}
```

Expected: Response for `id=1` with `result`, then response for `id=2` with `result` containing text "hello world" (either in `content` or `structuredContent`).

## 4) Logs & Diagnostics

Follow logs (Pane 3 or another pane):
```bash
tail -F "$WS/logs/jupyter.out" "$WS/logs/jupyter.err" /tmp/sjmcp-*-stdout.log /tmp/sjmcp-*-stderr.log
```

Jupyter API probe (token-protected):
```bash
curl -s "http://127.0.0.1:${PORT}/api" -H "Authorization: token ${TOKEN}" | head -c 200
```

macOS seatbelt denials (if using seatbelt mode):
```bash
log show --style syslog --last 2m --predicate 'subsystem == "com.apple.sandbox"' | tail -n +1 | tail -200
```

## 5) Helper Scripts

Use these tiny wrappers to reduce typing in Pane 2.

- scripts/mcp_start_direct.sh
- scripts/mcp_start_wrapper_unsandbox.sh
- scripts/mcp_start_wrapper_seatbelt.sh

Each expects WS, PORT, TOKEN set in the environment.

## 6) Encode into Tests (after manual success)

- Unsandbox baseline → direct jupyter-mcp-server pytest
- Wrapper (no kernel sandbox) → pytest
- macOS seatbelt → pytest

Keep tests DRY using these fixtures: `launch_proc`, `launch_jupyter_server`, `mcp_stdio_protocol`, `pick_free_port`, `gen_token`, `pkg_src_env_update`, `collect_mcp_logs_fn`.
