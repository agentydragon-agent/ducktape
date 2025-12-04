local I = import '../../lib.libsonnet';

I.issue(
  rationale=|||
    The loop that strips everything below the Git scissors line and collects non-comment, non-blank lines
    is an ideal small helper for clarity and reuse:

      content_lines: list[str] = []
      for line in final_content.splitlines():
        if line.startswith("# ------------------------ >8 ------------------------"):
          break
        if line.strip() and not line.strip().startswith("#"):
          content_lines.append(line)

    Refactor into a function (e.g., `extract_message_body(final_content: str) -> list[str]` or
    `is_empty_message(text: str) -> bool`) so the behavior is testable and consistently reused.
  |||,

  filesToRanges={
    'llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py': [[955, 964]],
  },
)
