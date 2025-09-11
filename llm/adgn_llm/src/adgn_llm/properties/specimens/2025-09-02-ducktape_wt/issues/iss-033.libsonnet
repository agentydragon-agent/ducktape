local I = import '../../specimen_issues.libsonnet';

  // iss-033: Scope try/except to minimal risky call — path-within-worktrees check
  I.issueOneOccurrence(
    id='iss-033',
    rationale= |||
      In the path-within-worktrees check, scope the try/except to only the relative_to(...) call so it does not capture unrelated exceptions and hides real errors.

      Before:
      ```python
      try:
          rel_path = absolute_path.relative_to(self.config.worktrees_dir)
          worktree_name = rel_path.parts[0] if rel_path.parts else None
          if len(rel_path.parts) > 1:
              relative_path = str(Path(*rel_path.parts[1:]))
          else:
              relative_path = ""
      except ValueError:
          # Path is not within worktrees directory - check if it's main repo
          ...
      ```

      After:
      ```python
      try:
          rel_path = absolute_path.relative_to(self.config.worktrees_dir)
      except ValueError:
          if not absolute_path.is_relative_to(self.config.main_repo):
              raise ValueError(f"Path {absolute_path} is not a managed worktree")
          worktree_name = MAIN_WORKTREE_DISPLAY_NAME
          relative_path = str(absolute_path.relative_to(self.config.main_repo))
          return self._create_success_response(...)
      # happy path (in worktrees dir)
      worktree_name = rel_path.parts[0] if rel_path.parts else None
      relative_path = "" if len(rel_path.parts) <= 1 else str(Path(*rel_path.parts[1:]))
      ```

      This reduces nesting, keeps the happy path flat, and prevents the try/except from swallowing unrelated errors.
    |||,
    properties=['scoped-try-except', 'early-bailout'],
    filesToRanges={
      'wt/wt/server/wt_server.py': [[2186, 2240]],
    },
  )
