local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    run_jupyter_mcp starts a Jupyter server at line 146 but the try/finally cleanup block
    doesn't start until line 165. If any operation between lines 147-164 raises (building
    mcp_cmd, validation, etc.), the try block is never entered, so the finally block never
    executes, leaving the Jupyter server process running. The finally block only protects
    against failures inside the try block (subprocess.Popen and proc.wait), not failures
    before entering it.

    A more robust pattern would wrap the server in a context manager that guarantees cleanup
    via Python's __exit__ protocol. This makes it impossible to acquire the server resource
    without automatic cleanup, eliminating the fragile dependency on try block placement:
    @contextmanager def _jupyter_server_context(...) with yield and finally cleanup, then
    use it via "with _jupyter_server_context(...) as jl:". The context manager ensures
    cleanup runs even on exception or early return, and makes resource ownership explicit.
  |||,
  filesToRanges={
    'adgn/src/adgn/mcp/sandboxed_jupyter/launch.py': [[146, 146], [165, 171]],
  },
)
