local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    `ParallelTaskRunner.__init__(..., master_fd)` accepts `master_fd` but never stores or uses it; the FD is
    only passed to `_stream_output(master_fd)` at call time. Either drop the parameter from `__init__` (pass the
    FD directly to `_stream_output`) or store it as `self.master_fd` and wire it into actual usage.

    This eliminates a misleading, unused parameter and makes data flow explicit.
  |||,

  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[544, 549], [615, 615]],
  },
)
