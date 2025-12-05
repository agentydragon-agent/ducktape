local I = import '../../lib.libsonnet';

I.issue(
  rationale= |||
    Errors are ignored in operational code, hiding failures and making diagnosis difficult.

    Example
    - internal/tui/tui.go: List sessions in a command handler discards the error (`allSessions, _ := a.app.Sessions.List(context.Background())`).

    Why it matters
    - Swallowing errors causes silent feature breakage and confusing UX; upstream systems cannot react or present actionable messages.

    Acceptance criteria
    - Do not ignore errors. Handle or log explicitly; in TUI, return an errMsg so the UI can inform the user.
    - If the code cannot proceed sensibly without the value, fail fast. Prefer returning an error; if you absolutely cannot propagate, panic is acceptable over silently swallowing.
    - Prefer passing a caller context (with cancellation) rather than context.Background() where possible.
  |||,
  filesToRanges={
    'internal/tui/tui.go': [[161, 168]],
  },
)
