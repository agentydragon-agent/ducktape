local I = import '../../lib.libsonnet';

I.falsePositive(
  rationale= |||
    Critics might flag that _run_in_sandbox accepts cwd as string without validating it's absolute,
    and passing relative paths to bubblewrap's --bind/--chdir will fail. However,
    this is acceptable because bubblewrap invoked with relative paths produces clear error messages
    ("Can't mkdir subdir: Read-only file system" or "Can't chdir to subdir: No such file or directory")
    that the LLM agent can use to figure out it needs absolute paths. We could validate in Python
    pre-emptively, but it isn't necessary - it's fine to allow the LLM to pass relative paths
    and then let it handle errors from bwrap as we currently do.
  |||,
  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py': [[50, 90]],
  },
)
