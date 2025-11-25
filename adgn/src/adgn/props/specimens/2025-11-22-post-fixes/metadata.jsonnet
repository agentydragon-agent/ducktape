local I = import '../lib.libsonnet';

I.specimen(
  source={
    vcs: 'git',
    url: 'file://../../bundles/specimens-2025-11-20-22.bundle',
    ref: 'refs/tags/specimen-2025-11-22-post-fixes',
  },
  commit='18294559d39a9547e29d8a63183ee71797532ae2',
  timestamp='2025-11-22T10:00:00Z',
  description='Post-fixes specimen after applying all 37 fixes from 2025-11-22-ducktape-repo-2',
  notes=|||
    This specimen captures the state after:
    1. All 37 fixes from specimen 2025-11-22-ducktape-repo-2 were applied
    2. Two critical bugs introduced by those fixes were fixed:
       - KeyError handling in approve/reject tools
       - Type error in set_policy() method

    Remaining issues identified during code review are documented here.
  |||,
)
