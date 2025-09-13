local I = import '../../specimen_issues.libsonnet';

// iss-052e: Inline trivial resolve_command wrapper
I.issueOneOccurrence(
  rationale='`resolve_command` is a trivial wrapper over get_plugin_commands(pm).get(name); inline the call at callers instead of keeping the wrapper. Suggested change for lines 76-78: replace usage sites with `get_plugin_commands(pm).get(name)` and remove the wrapper if unused elsewhere.',
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'wt/wt/plugins.py': [[76, 78]],
  },
)
