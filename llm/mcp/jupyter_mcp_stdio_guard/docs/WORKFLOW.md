# Manual-first Workflow: Sandbox Jupyter MCP

Principle: Always make it work manually (in tmux) before encoding into automation. When automation/tests fail, reproduce manually, debug in place, fix, then re-encode.

## Panes and Roles

- Pane 1 — Jupyter Server
  - You control env, kernelspec directories, and config explicitly
- Pane 2 — MCP stdio process (wrapper or direct jupyter-mcp-server)
  - You paste JSON one line per message (initialize → notifications/initialized → tools/call)
- Pane 3 — Logs and probes
  - Tail Jupyter logs; run readiness checks; grep seatbelt denials on macOS

## Sequence (ladder)

1) Direct MCP, unsandboxed kernel (baseline)
   - Pane 1: Jupyter server with token; default kernel
   - Pane 2: jupyter-mcp-server start (stdio); drive JSON; verify hello world
2) Wrapper with --no-kernel-sandbox
   - Pane 2: sandbox-jupyter-mcp --no-kernel-sandbox; drive JSON; verify hello world
3) Seatbelt kernel
   - Pane 1: Launch Jupyter with locked config (JUPYTER_* env) and kernelspec override for python3 that wraps sandbox-exec
   - Pane 2: wrapper or direct MCP; drive JSON; verify hello world and a denial for writes outside WORKSPACE

## Locked Jupyter config (explicit control)

- Set for the Jupyter process:
  - JUPYTER_RUNTIME_DIR = <RUN_ROOT>/runtime
  - JUPYTER_DATA_DIR = <RUN_ROOT>/data
  - JUPYTER_CONFIG_DIR = <RUN_ROOT>/config
  - JUPYTER_PATH = <RUN_ROOT>/data (restrict search)
- Write <RUN_ROOT>/config/jupyter_server_config.py:
  - KernelSpecManager.kernel_dirs = ["<RUN_ROOT>/data/kernels"]
  - KernelSpecManager.ensure_native_kernel = False
  - ServerApp.default_kernel_name = "python3"
- Provide only the kernels you want in <RUN_ROOT>/data/kernels
  - python3/kernel.json argv begins with: sandbox-exec -f <policy> -D WORKSPACE=… -D RUN_ROOT=… python -m ipykernel_launcher -f {connection_file}

## Debug loop

- One command at a time; observe; adjust
- If MCP doesn’t respond: check port readiness and stderr; increase timeouts
- If kernel isn’t sandboxed: verify kernelspec list, default name, argv; fix JUPYTER_* and config
- If write outside WORKSPACE succeeds: your kernel isn’t sandboxed or policy is too permissive

## Automation encoding

- After manual green, encode the exact sequence into pytest using fixtures
- On test failure, go back to manual tmux and reproduce with the same args/env
- Only then tweak tests; avoid speculative changes without observed manual behavior
