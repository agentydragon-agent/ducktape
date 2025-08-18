# Jupyter Config Strategy (Sandboxed Kernel)

We force Jupyter to only see and use our kernelspecs by constraining config and data paths and setting defaults.

- Environment (set by wrapper for Jupyter Server process):
  - JUPYTER_RUNTIME_DIR = <RUN_ROOT>/runtime
  - JUPYTER_DATA_DIR = <RUN_ROOT>/data
  - JUPYTER_CONFIG_DIR = <RUN_ROOT>/config
  - JUPYTER_PATH = <RUN_ROOT>/data  (limits data search path)
- Config file: <RUN_ROOT>/config/jupyter_server_config.py
  - KernelSpecManager.kernel_dirs = ["<RUN_ROOT>/data/kernels"]
  - KernelSpecManager.ensure_native_kernel = False
  - ServerApp.default_kernel_name = "python3"
  - ServerApp.open_browser = False, ip=127.0.0.1, disable_check_xsrf=True
- Kernelspec override:
  - <RUN_ROOT>/data/kernels/python3/kernel.json wraps sandbox-exec with WORKSPACE/RUN_ROOT params
  - This ensures any doc with default "python3" uses the sandboxed kernel

## Python bytecode caches

If sources/venv are mounted read-only, configure Python bytecode handling to avoid writes next to .py files:
- Prefer setting PYTHONPYCACHEPREFIX=<RUN_ROOT>/pycache (redirects __pycache__ writes)
- Or set PYTHONDONTWRITEBYTECODE=1 to disable .pyc writes entirely (slightly slower imports)

This locks kernel selection to our provided spec, avoiding global/user kernels.
