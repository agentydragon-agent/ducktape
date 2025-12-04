local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The code builds a derived label for timeout:

      timeout_label = (
        "infinite" if config.timeout is None else f"{int(config.timeout.total_seconds())}s"
      )
      print(f"# Resolved model={config.model_str}, timeout={timeout_label}", file=sys.stderr)

    This transformation adds extra code and makes output worse (coarser granularity and an arbitrary "s" suffix),
    while providing no extra clarity. Prefer logging the `config.timeout` value directly (or its standard
    representation), and drop this one-off label entirely.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[792, 799]],
  },
)
