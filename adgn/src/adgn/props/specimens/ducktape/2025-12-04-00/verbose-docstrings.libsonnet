local I = import '../../lib.libsonnet';

I.issueMulti(
  rationale= |||
    Docstrings that are unnecessarily verbose and repeat information already clear from signatures, type hints, or context. Concise docstrings should focus on non-obvious behavior, not restate obvious facts.
  |||,
  occurrences=[
    {
      files: {'adgn/src/adgn/mcp/_shared/calltool.py': [[61, 70]]},
      note: 'Docstring restates parameter names/types from signature; Returns section just says "instance of output_type"',
      expect_caught_from: [['adgn/src/adgn/mcp/_shared/calltool.py']],
    },
    {
      files: {'adgn/src/adgn/agent/transcript_handler.py': [[22, 32]]},
      note: 'TranscriptHandler docstring uses weasel word "Unified" and includes obvious usage snippet (lines 29-31)',
      expect_caught_from: [['adgn/src/adgn/agent/transcript_handler.py']],
    },
    {
      files: {'adgn/src/adgn/mcp/_shared/resources.py': [[61, 75]]},
      note: 'Docstring includes unnecessary implementation detail (lines 63-64) and restates Args/Returns from signature',
      expect_caught_from: [['adgn/src/adgn/mcp/_shared/resources.py']],
    },
    {
      files: {'adgn/src/adgn/agent/bootstrap.py': [[177, 185]]},
      note: 'read_resource_call docstring Args/Returns sections restate parameter types and return type',
      expect_caught_from: [['adgn/src/adgn/agent/bootstrap.py']],
    },
    {
      files: {'adgn/src/adgn/agent/bootstrap.py': [[196, 204]]},
      note: 'docker_exec_call docstring Args/Returns sections restate parameter types and return type',
      expect_caught_from: [['adgn/src/adgn/agent/bootstrap.py']],
    },
    {
      files: {'adgn/src/adgn/props/grader/grader.py': [[294, 305]]},
      note: 'grade_critique_by_id docstring restates obvious parameter info; only client and session docs add value',
      expect_caught_from: [['adgn/src/adgn/props/grader/grader.py']],
    },
  ],
)
