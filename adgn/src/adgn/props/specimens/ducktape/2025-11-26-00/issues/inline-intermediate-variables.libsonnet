local I = import '../../specimens/lib.libsonnet';

// iss-003: Unnecessary intermediate variables should be inlined

I.issueWithOccurrences(
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
      // policy_gateway variable assigned then immediately stored in field
      // Inline: self._policy_gateway = install_policy_gateway(...)
      files: {
        'adgn/src/adgn/agent/runtime/container.py': [
          [323, 332],
          [372, 372],
        ],
      },
    },
    {
      // rows and items variables immediately consumed
      // Inline both into single return statement
      files: {
        'adgn/src/adgn/agent/server/app.py': [[290, 296]],
      },
    },
    {
      // tagged variable immediately returned
      // Inline: return UserMessage.text(f"...")
      files: {
        'adgn/src/adgn/agent/reducer.py': [[200, 201]],
      },
    },
    {
      // raw variable immediately passed to function
      // Inline into return statement
      files: {
        'adgn/src/adgn/git_commit_ai/cli.py': [[154, 156]],
      },
    },
    {
      // status variable immediately used in if-check
      // Inline: if not _format_status_porcelain(repo):
      files: {
        'adgn/src/adgn/git_commit_ai/cli.py': [[735, 736]],
      },
    },
  ],
)
