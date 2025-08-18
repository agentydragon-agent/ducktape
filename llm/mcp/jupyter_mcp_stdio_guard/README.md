# jupyter-mcp-stdio-guard

A tiny wrapper that starts a Jupyter server in a sandbox (Docker or macOS seatbelt) and runs `jupyter-mcp-server` in stdio mode.

Caller must provide:
- JP_PORT
- JUPYTER_RUNTIME_DIR, JUPYTER_DATA_DIR, JUPYTER_CONFIG_DIR, MPLCONFIGDIR

Example (seatbelt):

```
JP_PORT=18888 \
JUPYTER_RUNTIME_DIR=/tmp/jmcp/runtime \
JUPYTER_DATA_DIR=/tmp/jmcp/data \
JUPYTER_CONFIG_DIR=/tmp/jmcp/config \
MPLCONFIGDIR=/tmp/jmcp/mpl \
python -m jupyter_mcp_stdio_guard --workspace /abs/path --mode seatbelt
```
