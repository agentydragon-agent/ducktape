local I = import '../../lib.libsonnet';


I.issue(
  rationale=|||
    Line 130 imports `from .events import EventRecord, TypedPayload  # noqa: E402`, using
    `# noqa: E402` to suppress "module level import not at top of file" linting error.

    Problems: (1) Suppresses legitimate linting error - real code smell should be fixed, not
    suppressed. (2) Violates PEP 8 - imports should be at top after module docstring.
    (3) Hides potential circular import - `noqa` suggests circular dependency being papered
    over. (4) Inconsistent with rest of file - all other imports (lines 1-10) are at top.
    (5) Scattered imports make dependencies hard to see at a glance.

    Recommended approaches: (1) If circular import, refactor - move EventRecord/TypedPayload
    to separate `types.py`, have both `__init__.py` and `events.py` import from it.
    (2) If no circular dependency, move import to top. (3) If TYPE_CHECKING needed for forward
    refs, use `if TYPE_CHECKING:` block at top.

    Check if circular import actually exists by trying to move import to top. If fails,
    refactor module structure to break cycle rather than suppressing warning.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/persist/__init__.py': [
      [130, 130],  // Late import with noqa suppression
    ],
  },
)
