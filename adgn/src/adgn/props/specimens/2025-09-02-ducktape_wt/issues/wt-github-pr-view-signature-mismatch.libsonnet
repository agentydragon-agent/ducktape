local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    GitHub PR view API signature and return type are inconsistent and misleading.

    Observed:
    - DisabledGitHubInterface.pr_view(self, pr_number: int) -> PRStatus | None (docstring implies status type)
    - GitHubInterface.pr_view(self, branch_name: str) -> dict[str, str]
      • Parameter name suggests a branch name, but the implementation calls
        `repo.get_pull(int(branch_name))`, i.e., it expects a PR number string.
      • Return type is an untyped dict, not the shared PRStatus model used elsewhere.

    Why this is bad:
    - Callers are misled by the parameter name and type hints; passing a real branch name will fail.
    - The interface pair is inconsistent (Disabled vs real); return shapes differ, defeating shared models.

    Acceptance criteria (agnostic to exact shape, but require consistency):
    - Make the parameter and name reflect actual semantics (e.g., `pr_number: int`), or provide two
      distinct methods: `view_pr_by_number(pr_number: int)` and `search_prs_by_branch(branch_name: str)`.
    - Return a single, shared typed model (e.g., PRStatus) from both DisabledGitHubInterface and
      GitHubInterface implementations; do not return ad-hoc dicts.
    - Ensure callers of PR view use the same typed contract across all codepaths.
  |||,
  filesToRanges={
    'wt/wt/server/github_client.py': [[16, 34], [110, 119]],
  },
)
