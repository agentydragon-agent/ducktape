# Jupyter MCP STDIO Guard — Manual tmux Testing Recipe (Manual-first)

Follow this step-by-step. Type each command, press Enter, read the output. Do not run large scripts.

## 0) Layout

```bash
# 0.1 Three panes
tmux new-session -s sjmcp-manual -n jup -d
# Right pane
tmux split-window -t sjmcp-manual:0 -h
# Bottom-left pane
tmux split-window -t sjmcp-manual:0.0 -v
# Attach
tmux attach -t sjmcp-manual
```

## 1) Environment (Pane 3)

```bash
WS="$PWD/_mcp_ws"; OUTSIDE="$PWD/_mcp_outside"; mkdir -p "$WS/.mcp" "$WS/logs" "$OUTSIDE"
PORT=$(python - <<'PY'
import socket
s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()
PY)
TOKEN=$(python - <<'PY'
import secrets
print(secrets.token_urlsafe(16))
PY)
cat >"$WS/.mcp/test.ipynb" <<'JSON'
{"cells":[],"metadata":{"kernelspec":{"name":"python3","display_name":"Python 3","language":"python"}},"nbformat":4,"nbformat_minor":5}
JSON
```

## 2) Jupyter Server (Pane 1)

```bash
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

## 3) Logs/Readiness (Pane 3)

```bash
python - <<'PY'
import socket, os, time
port=int(os.environ['PORT']); deadline=time.time()+20
ok=False
while time.time()<deadline:
  try:
    with socket.create_connection(("127.0.0.1", port), 0.5): ok=True; break
  except OSError: time.sleep(0.1)
print("READY" if ok else "NOT READY")
PY
tail -F "$WS/logs/jupyter.out" "$WS/logs/jupyter.err"
```

## 4) MCP — Direct (Pane 2)

```bash
jupyter-mcp-server start \
  --transport stdio \
  --provider jupyter \
  --document-url "http://127.0.0.1:${PORT}" \
  --document-id ".mcp/test.ipynb" \
  --document-token "${TOKEN}" \
  --runtime-url "http://127.0.0.1:${PORT}" \
  --runtime-token "${TOKEN}" \
  --start-new-runtime true
```

Paste MCP JSON lines (one per line):

```text
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{"tools":{}},"clientInfo":{"name":"tmux","version":"0.0.1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"append_execute_code_cell","arguments":{"cell_source":"print('hello world')"}}}
```

## 5) Kernel Sandbox (Pane 1 — locked config)

Use when testing sandboxed kernel explicitly. This manual recipe uses sandbox-exec -D WORKSPACE/RUN_ROOT macro defs for convenience; the wrapper generates explicit seatbelt policies without macros.

```bash
# Choose run root under /tmp
RUN_ROOT="/tmp/sjmcp_$$"; mkdir -p "$RUN_ROOT/runtime" "$RUN_ROOT/data/kernels" "$RUN_ROOT/config"
# Write sandboxed python3 kernelspec (wraps sandbox-exec)
POLICY="$PWD/llm/mcp/jupyter_mcp_stdio_guard/policies/kernel_base.sb"
KDIR="$RUN_ROOT/data/kernels/python3"; mkdir -p "$KDIR"
cat >"$KDIR/kernel.json" <<JSON
{
  "argv": ["sandbox-exec","-f","$POLICY","-D","WORKSPACE=$WS","-D","RUN_ROOT=$RUN_ROOT","$(which python)","-m","ipykernel_launcher","-f","{connection_file}"],
  "display_name": "Python 3",
  "language": "python"
}
JSON
# Write server config to use only our kernels
cat >"$RUN_ROOT/config/jupyter_server_config.py" <<CFG
c = get_config() if 'get_config' in globals() else None
c.KernelSpecManager.kernel_dirs = ["$RUN_ROOT/data/kernels"]
c.KernelSpecManager.ensure_native_kernel = False
CFG
# Export env for this pane
export JUPYTER_RUNTIME_DIR="$RUN_ROOT/runtime" JUPYTER_DATA_DIR="$RUN_ROOT/data" JUPYTER_CONFIG_DIR="$RUN_ROOT/config" JUPYTER_PATH="$RUN_ROOT/data"
# Restart Jupyter server to use the locked config
pkill -f "jupyter server" || true
jupyter server --port "$PORT" --ip 127.0.0.1 --ServerApp.root_dir "$WS" --ServerApp.open_browser False --ServerApp.token "$TOKEN" --ServerApp.password '' --ServerApp.disable_check_xsrf True >"$WS/logs/jupyter.out" 2>"$WS/logs/jupyter.err"
```

Then, in Pane 2, use direct MCP (section 4) and paste a cell that attempts to write outside WORKSPACE:

```text
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"append_execute_code_cell","arguments":{"cell_source":"import pathlib\np=pathlib.Path(r'${OUTSIDE}/denied.txt')\ntry:\n    p.write_text('x')\n    print('wrote OUTSIDE')\nexcept Exception as e:\n    print(type(e).__name__, str(e))\n"}}}
```

Expected: Permission error (Operation not permitted), not "wrote OUTSIDE".

## 6) When automation fails

- Reproduce with this manual recipe exactly
- Fix config/policy/args in-place and re-run single steps
- Only after it works here, update the tests/fixtures
