local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale=|||
    Test files extract values into variables and then immediately use them once
    in an assertion. These should be inlined directly into the assertion.

    **Why inline?**
    - Variables are used exactly once, immediately after definition
    - No clarifying benefit from variable name (dec, res vs the call itself)
    - Less code to read and maintain
    - Standard pattern: only extract to variable if used multiple times, adds
      semantic clarity, or expression is very complex
  |||,
  occurrences=[
    {
      files: {
        'adgn/tests/agent/test_loop_reducer_skip_sampling.py': [[24, 31], [38, 45]],
      },
      note: 'dec = ctrl.on_before_sample() then assert on dec; two instances',
      expect_caught_from: [['adgn/tests/agent/test_loop_reducer_skip_sampling.py']],
    },
    {
      files: {
        'adgn/tests/agent/test_aggregating_inserts.py': [[35, 42]],
      },
      note: 'dec = ctrl.on_before_sample() then assert on dec',
      expect_caught_from: [['adgn/tests/agent/test_aggregating_inserts.py']],
    },
    {
      files: {
        'adgn/tests/agent/test_exec_roundtrip.py': [[24, 32]],
      },
      note: 'res = await stub(ExecInput(...)) then assert on res',
      expect_caught_from: [['adgn/tests/agent/test_exec_roundtrip.py']],
    },
    {
      files: {
        'adgn/tests/agent/test_editor_inproc.py': [[29, 30]],
      },
      note: 'done_result = await stub.done(...) then assert on done_result',
      expect_caught_from: [['adgn/tests/agent/test_editor_inproc.py']],
    },
  ],
)
