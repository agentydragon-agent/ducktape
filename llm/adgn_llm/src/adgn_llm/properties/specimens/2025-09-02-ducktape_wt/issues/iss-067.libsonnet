local I = import '../../specimen_issues.libsonnet';

// iss-067: Simplify boolean-property implementations to concise one-liners
I.issueOneOccurrence(
  rationale='Shorten trivial boolean property implementations to concise truthy one-liners (no change in semantics), improving readability. Example: `return self.is_git_repository and bool(self.untracked_files)`.',
  properties=['no-useless-docs'],
  gap_note="GAP: When you have a type that has only 1 Falsey / Truthy members, use it to leverage truthiness instead of complex checks where it does not make code more confusing. e.g.: `if array:` instead of `if array != []:`. `if len(array) > 0:` is OK either way - `if array:` can be concise sometimes to the point of making it more confusing / hiding that it's an array (not a bool). Use truthiness where readable (re. original code had `(x or 0) > 0`)",
  filesToRanges={
    'wt/wt/server/gitstatusd_client.py': [[119, 123], [126, 130]],
  },
)
