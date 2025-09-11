local I = import '../../specimen_issues.libsonnet';

  // iss-036: Prefer comprehension for simple arg filtering in CLI
  I.issueOneOccurrence(
    id='iss-036',
    rationale= |||
  Prefer a single pre-check + list comprehension for simple arg filtering to reduce nesting and eliminate one-off append/continue state.
  
  Before:
  ```python
  for arg in all_args:
      if arg in {"--help", "-h"}:
          show_help()
          return
      if arg in ["-c", "--force"]:
          filtered_args.append(arg)
      elif arg.startswith("-"):
          continue
      else:
          filtered_args.append(arg)
  ```
  After:
  ```python
  if {"--help", "-h"} & set(all_args):
      show_help(); return
  filtered_args = [
      arg for arg in all_args
      if not arg.startswith("-") or arg in ("-c", "--force")
  ]
  ```
|||,
    properties=['minimize-nesting'],
    filesToRanges={"wt/wt/cli.py": [[137, 186]]},
    gap_note='GAP: Prefer comprehensions for simple filter/map over loops with append/continue when it fits on one readable line. This matches "No unnecessary nesting" but needs a bit more heuristic guidance.',
  )
