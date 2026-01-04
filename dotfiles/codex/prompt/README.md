## `codex_vanilla.md`

Vanilla prompt from Codex.

Features:

- Instructed to use `apply_patch`.
- Disabled internet access.
- You don't need to `git commit`
- Run `pre-commit` but don't fix pre-existing errors.
- Revert scratch files / changes when done coding.
- `apply_patch` spec - does not show very explicitly what if file has `+` at start of line.

## `claude_code_vanilla.md`

Vanilla prompt from Claude Code.

From: <https://gist.github.com/transitive-bullshit/487c9cb52c75a9701d312334ed53b20c>

Removed:

- /help
- /compact
- slash-commands, `claude -h`
- feedback (bug reports)
- Environment details (`cwd`, is git repo, platform, date, model)
- Agent tool
- Malicious code guard
- Reduced strength of "answer concisely".

Kept:

- CLAUDE.md
