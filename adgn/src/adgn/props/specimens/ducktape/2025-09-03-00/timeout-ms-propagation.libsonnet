local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    exec_handler converts timeout_ms to seconds early with int(timeout_ms / 1000), truncating
    sub-second precision (1500ms becomes 1s, 500ms becomes 0→1s). Timeout should be propagated
    as milliseconds (int) throughout the call chain and only divided by 1000.0 at the final
    subprocess.communicate() call. This requires changing: exec_handler to pass timeout_ms
    directly, _run_in_sandbox(timeout_s: int) → _run_in_sandbox(timeout_ms: int),
    _run_proc(timeout_s: int) → _run_proc(timeout_ms: int), and _run_proc to convert at
    communicate: p.communicate(timeout=timeout_ms / 1000.0). Python >=3.11 is required
    and subprocess.communicate() has supported float timeout since Python 3.3.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py': [[28, 43], [50, 90], [110, 127]],
  },
)
