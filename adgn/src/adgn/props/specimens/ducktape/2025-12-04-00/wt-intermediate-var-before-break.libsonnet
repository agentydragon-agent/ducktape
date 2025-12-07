local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Lines 373-374 assign to an intermediate variable then break:
      response_json = obj
      break

    Since the function returns immediately after the loop, this should be a
    direct return:
      return obj, hook_stdout, hook_stderr

    The intermediate variable serves no purpose and obscures control flow.
  |||,
  filesToRanges={'wt/src/wt/client/wt_client.py': [[373, 374]]},
)
