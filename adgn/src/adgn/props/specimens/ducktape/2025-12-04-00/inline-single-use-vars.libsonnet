local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Variables and helper functions used only once should be inlined at their call site to reduce unnecessary indirection. This applies to both simple variables assigned and immediately used, and to trivial helper functions that wrap a single operation without adding semantic value.
  |||,
  occurrences=[
    {
      files: {'src/adgn/llm/sysrw/extract_dataset_crush.py': [[63, 64]]},
      note: 'dt variable used once immediately after assignment',
      expect_caught_from: [['src/adgn/llm/sysrw/extract_dataset_crush.py']],
    },
    {
      files: {'src/adgn/props/cli_app/cmd_build_bundle.py': [[188, 190]]},
      note: 'author, committer, message variables used once each immediately after assignment',
      expect_caught_from: [['src/adgn/props/cli_app/cmd_build_bundle.py']],
    },
    {
      files: {'src/adgn/agent/agent.py': [[132, 133], [139, 140], 412, 427, 623]},
      note: 'Functions _make_error_result and _abort_result - _make_error_result called only from _abort_result, and _abort_result called only 3 times without any reason argument, making the abstraction unnecessary',
      expect_caught_from: [['src/adgn/agent/agent.py']],
    },
    {
      files: {'src/adgn/agent/db_event_handler.py': [52, 59]},
      note: 'Variable event_type extracted then immediately used once on line 59',
      expect_caught_from: [['src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'src/adgn/agent/db_event_handler.py': [56, 63]},
      note: 'Variable event created then immediately used once on line 63',
      expect_caught_from: [['src/adgn/agent/db_event_handler.py']],
    },
    {
      files: {'src/adgn/agent/server/runtime.py': [59, 60]},
      note: 'Variable bus extracted then immediately used once on line 60',
      expect_caught_from: [['src/adgn/agent/server/runtime.py']],
    },
    {
      files: {'src/adgn/agent/server/runtime.py': [82, 83]},
      note: 'Variable tasks created then immediately used once on line 83',
      expect_caught_from: [['src/adgn/agent/server/runtime.py']],
    },
    {
      files: {'src/adgn/props/prompt_optimizer.py': [[294, 296]]},
      note: 'return statement could move into lines 294-296',
      expect_caught_from: [['src/adgn/props/prompt_optimizer.py']],
    },
    {
      files: {'src/adgn/props/grader/grader.py': [[104, 104]]},
      note: 'tp_files variable',
      expect_caught_from: [['src/adgn/props/grader/grader.py']],
    },
    {
      files: {'src/adgn/props/grader/grader.py': [[107, 107]]},
      note: 'critique_files variable',
      expect_caught_from: [['src/adgn/props/grader/grader.py']],
    },
    {
      files: {'src/adgn/props/grader/grader.py': [[201, 201]]},
      note: 'db_run variable in session.add',
      expect_caught_from: [['src/adgn/props/grader/grader.py']],
    },
    {
      files: {'src/adgn/props/grader/grader.py': [[226, 226]]},
      note: 'submit_tool_name variable',
      expect_caught_from: [['src/adgn/props/grader/grader.py']],
    },
    {
      files: {'src/adgn/props/grader/grader.py': [[249, 257]]},
      note: 'handlers variable',
      expect_caught_from: [['src/adgn/props/grader/grader.py']],
    },
    {
      files: {'src/adgn/mcp/_shared/resources.py': [[55, 57]]},
      note: 'Variables rr and s assigned once and immediately used (lines 55-57)',
      expect_caught_from: [['src/adgn/mcp/_shared/resources.py']],
    },
    {
      files: {'src/adgn/mcp/compositor/server.py': [[173, 174]]},
      note: 'Variable client_factory assigned at line 173 and used only at line 174',
      expect_caught_from: [['src/adgn/mcp/compositor/server.py']],
    },
  ],
)
