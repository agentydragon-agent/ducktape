# Configuration Details (Explicit)

This wrapper performs zero implicit environment or path mutations. All behavior is driven by YAML.

- No automatic stripping of env vars
- No implicit HOME/MPLCONFIGDIR/TMPDIR/etc. settings
- No auto-injected read roots or write roots
- No network policy inference

You MUST provide all necessary environment variables and paths explicitly in the YAML `env` map and `fs_read`/`fs_write`.

Recommended keys (caller decides values):
- JUPYTER_RUNTIME_DIR, JUPYTER_DATA_DIR, JUPYTER_CONFIG_DIR, JUPYTER_PATH
- PYTHONPYCACHEPREFIX, MPLCONFIGDIR, TMPDIR/TMP/TEMP
- HOME (if isolating kernel home)
- JUPYTER_TOKEN (if not using auto token; normally wrapper provides token argument to the server and MCP, but env is your control)

Notes:
- Kernel sandboxing is controlled purely by the kernelspec (seatbelt policy file path) and your env.
- If Python or Jupyter require additional read access, add those paths explicitly to `fs_read`.
- Network policy is controlled by `net` field — enforcement hooks TBD; today policy base allows networking and should be tightened as you specify.
