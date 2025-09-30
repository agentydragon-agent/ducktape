local I = import '../../specimens/lib.libsonnet';

I.issueOneOccurrence(
  rationale= |||
    In wt/shared/error_handling.py (handle_git_errors), a broad `except Exception` appears before
    specific handlers (`except (GitError, WorktreeError)` and `except GitTimeoutError`), making the
    specific handlers unreachable. Re-raising from the broad handler exits the try block and does not
    “fall through” to later except clauses. The broad branch also uses brittle substring tests
    (“git”/“repository”) to classify errors instead of explicit types.

    Acceptance criteria:
    - Order specific exception handlers first; keep `except Exception` last (or remove if not needed).
    - Eliminate substring-based classification; rely on explicit exception types.
  |||,
  filesToRanges={
    'wt/wt/shared/error_handling.py': [[46, 59]],  // except sequence window
  },
)
