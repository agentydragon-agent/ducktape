local I = import '../../specimen_issues.libsonnet';

I.issueWithOccurrences(
  rationale=|||
    Post‑creation script check: shorten and use walrus. Also:
    - Drop redundant existence check
    - Fold error message into a concise one‑liner (can be done without loss of expressiveness).
    Also see: [No useless documentation or comments](../../props/no-useless-docs.md).
  |||,
  properties=['walrus'],
  occurrences=[{
    files: {
      'wt/wt/server/wt_server.py': [[1971, 1977]],
    },
    note: |||
      Post‑creation script check: shorten and use walrus. Also:
      - Drop redundant existence check
      - Fold error message into a concise one‑liner (can be done without loss of expressiveness).

      Before:
      ```python
      # If a post-creation script is configured, validate it exists before any side effects
      if self.config.post_creation_script:
          script = self.config.post_creation_script
          if not script.exists() or not script.is_file():
              raise ValueError(
                  f"Post-creation script configured but not found or not a file: {script}",
              )
      ```
      After:
      ```python
      if (script := self.config.post_creation_script) and not script.is_file():
          raise ValueError(f"Post-creation script is not a file: {script}")
      ```
    |||,
  }],
  gap_note='GAP: Beyond walrus, codify concise guard patterns (drop redundant existence checks; prefer single clear validation and message).',
)
