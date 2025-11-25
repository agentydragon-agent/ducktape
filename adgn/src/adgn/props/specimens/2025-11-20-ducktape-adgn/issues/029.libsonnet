local I = import '../../specimens/lib.libsonnet';

// iss-029: Should inline one-use variables in attach methods

I.issueOneOccurrence(
  rationale=|||
    Sidecar attach() methods create single-use variables that are immediately
    passed to mount_inproc.

    Current pattern (sidecars.py:35-36):
    ui_server = make_ui_server("UI", self.ui_bus)
    await running.compositor.mount_inproc(UI_SERVER_NAME, ui_server)

    Current pattern (sidecars.py:58-59):
    loop_server = make_loop_server("loop")
    await running.compositor.mount_inproc("loop", loop_server)

    Should inline:
    await running.compositor.mount_inproc(
        UI_SERVER_NAME, make_ui_server("UI", self.ui_bus)
    )

    await running.compositor.mount_inproc("loop", make_loop_server("loop"))

    Benefits:
    - Less code: removes intermediate variable
    - Clearer scope: server only exists at call site
    - Standard pattern: inline single-use function results

    The variables have no semantic value and aren't reused.
  |||,
  properties=['no-oneoff-vars-and-trivial-wrappers'],
  filesToRanges={
    'adgn/src/adgn/agent/runtime/sidecars.py': [
      [35, 36],     // ui_server one-use variable
      [58, 59],     // loop_server one-use variable
    ],
  },
)
