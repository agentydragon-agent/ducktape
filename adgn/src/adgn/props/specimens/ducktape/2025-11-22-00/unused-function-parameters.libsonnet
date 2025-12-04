local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Two functions declare parameters never used in the function body. Vestigial
    from previous implementations.

    Problem 1 (auto_attach.py:40-42): `attach_default_servers()` declares
    `agent_id`, `persistence`, and `docker_client` but never uses them. Only
    `comp`, `ui_bus`, and `approval_engine` are used.

    Problem 2 (handlers.py:19-31): `build_handlers()` declares `approval_engine`,
    `approval_hub`, and `agent_id` but never uses them. Only `poll_notifications`,
    `manager`, `persistence`, `get_run_id`, and `ui_bus` are used.

    Likely happened during refactoring: helper functions changed to get data
    elsewhere, parameters removed from helpers but not from top-level functions.
    Fix: remove unused parameters. Use Ruff ARG001/ARG002 to detect.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/runtime/auto_attach.py': [[40, 42]],
    'adgn/src/adgn/agent/runtime/handlers.py': [[19, 31]],
  },
  expect_caught_from=[
    ['adgn/src/adgn/agent/runtime/auto_attach.py'],
    ['adgn/src/adgn/agent/runtime/handlers.py'],
  ],
)
