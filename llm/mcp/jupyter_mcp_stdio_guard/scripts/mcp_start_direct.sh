#!/usr/bin/env bash
set -euo pipefail
: "${WS:?}" : "${PORT:?}" : "${TOKEN:?}"
TS="$(date +%s)"
MCP_OUT="/tmp/sjmcp-${TS}-stdout.log"
MCP_ERR="/tmp/sjmcp-${TS}-stderr.log"
exec jupyter-mcp-server start \
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
