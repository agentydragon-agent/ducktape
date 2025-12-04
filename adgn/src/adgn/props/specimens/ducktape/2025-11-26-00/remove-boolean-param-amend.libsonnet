local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Lines 539-547 define `_get_previous_message_if_amend()` which takes `is_amend: bool` and returns None if False. Function wraps an if-statement (antipattern).

    Remove boolean parameter. Rename to `_get_previous_commit_message()` with non-nullable `str` return type. Move condition to call site (line 731): `previous_message = _get_previous_commit_message(repo) if is_amend else None`. Or inline entirely since it's called only once.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [539, 547],  // Function with boolean parameter
      731,  // Call site
    ],
  },
)
