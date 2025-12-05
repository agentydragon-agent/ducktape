local I = import '../../lib.libsonnet';

I.issue(
  expect_caught_from=[[
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py',
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py',
  ]],
  rationale=|||
    The helper `_ensure_dir(p: Path) -> None` is a trivial passthrough around `p.mkdir(parents=True, exist_ok=True)`.
    Such single-line wrappers add indirection without adding durable abstraction, and they increase the cognitive load for readers who must jump to see what the helper actually does.

    They also waste lines of code for no reason; lines of code are a cost. Keep helpers only when they provide durable abstraction or clear semantic value.

    Think in terms of value (V) vs cost (C): a wrapper provides V at call sites (less duplication, shorter call site, clearer semantic name, easier test overrides) and imposes cost C (extra lines, indirection, additional API surface). Only keep a helper when V > C. If the wrapper is a pure one-to-one forwarder (e.g., `wrapper(a, b) -> preexisting_function(a, b)`), then V≈0 while C≥1 — delete it.

    Prefer inlining this call at call sites (or elevate it to a small utility only if multiple call sites need the same documented semantic) and delete the helper to reduce indirection.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [[32, 34]],
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py': [[44, 44]],
  },
)
