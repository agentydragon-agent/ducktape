#!/usr/bin/env bash
set -euo pipefail
: "${WS:?}" : "${PORT:?}"
TS="$(date +%s)"
MCP_OUT="/tmp/sjmcp-${TS}-stdout.log"
MCP_ERR="/tmp/sjmcp-${TS}-stderr.log"
exec sandbox-jupyter-mcp \
  --workspace "${WS}" \
  --mode seatbelt \
  --jupyter-port "${PORT}" \
  --trace-sandbox \
  | tee "$MCP_OUT" \
  2> >(tee "$MCP_ERR" >&2)
