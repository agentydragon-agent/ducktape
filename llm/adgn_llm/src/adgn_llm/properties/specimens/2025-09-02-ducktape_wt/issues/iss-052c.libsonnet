local I = import '../../specimen_issues.libsonnet';

// iss-052c: PluginIO thin wrapper should be removed or refactored
I.issueOneOccurrence(
  rationale='`PluginIO` is a stateless thin wrapper over shell_utils. Remove it or, if future design intent actually needs this abstraction, wire it in and briefly document the intent at `PluginIO` site.',
  properties=['no-dead-code', 'no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'wt/wt/plugins.py': [[39, 49]],
  },
)
