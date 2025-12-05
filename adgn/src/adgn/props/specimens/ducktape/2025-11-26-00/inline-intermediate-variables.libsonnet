local I = import '../../lib.libsonnet';


I.issueMulti(
  rationale= |||
    Multiple locations create intermediate variables that are immediately consumed,
    adding no clarity. These single-use variables should be inlined.

    **General pattern:**
    Variables used only once in the next line(s) create unnecessary intermediate state
    without improving readability. Inlining makes data flow more direct.

    **Benefits of inlining:**
    - Fewer lines of code
    - Direct data flow (no intermediate state to track)
    - Same or better readability
    - Clearer intent (expression used directly where needed)
  |||,
  occurrences=[
    {
      files: {
        'adgn/src/adgn/agent/runtime/container.py': [
          [323, 332],
          [372, 372],
        ],
      },
      note: 'policy_gateway variable assigned then immediately stored in field. Inline: self._policy_gateway = install_policy_gateway(...)',
      expect_caught_from: [['adgn/src/adgn/agent/runtime/container.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/server/app.py': [[290, 296]],
      },
      note: 'rows and items variables immediately consumed. Inline both into single return statement',
      expect_caught_from: [['adgn/src/adgn/agent/server/app.py']],
    },
    {
      files: {
        'adgn/src/adgn/agent/reducer.py': [[200, 201]],
      },
      note: 'tagged variable immediately returned. Inline: return UserMessage.text(f"...")',
      expect_caught_from: [['adgn/src/adgn/agent/reducer.py']],
    },
    {
      files: {
        'adgn/src/adgn/git_commit_ai/cli.py': [[154, 156]],
      },
      note: 'raw variable immediately passed to function. Inline into return statement',
      expect_caught_from: [['adgn/src/adgn/git_commit_ai/cli.py']],
    },
    {
      files: {
        'adgn/src/adgn/git_commit_ai/cli.py': [[735, 736]],
      },
      note: 'status variable immediately used in if-check. Inline: if not _format_status_porcelain(repo):',
      expect_caught_from: [['adgn/src/adgn/git_commit_ai/cli.py']],
    },
  ],
)
