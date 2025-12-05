local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The call site constructs a tiny literal object only to pass it to write_text; prefer inlining the single-line construction at the call site for concision and to avoid one-off temporary names.

    Example: replace
      kernelspec = {"name": "python3", "display_name": "Python 3", "language": "python"}
      (ks_dir / "kernel.json").write_text(json.dumps(kernelspec))
    with
      (ks_dir / "kernel.json").write_text(json.dumps({"name": "python3", "display_name": "Python 3", "language": "python"}))

    This reduces lines and the mental map of short-lived temporaries without harming readability for small literal payloads.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py': [[202, 208]],
  },
)
