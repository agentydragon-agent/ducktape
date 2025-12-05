local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    The `generate_commit_message_minicodex()` backend function (minicodex_backend.py, lines
    190-194) calls `configure_logging()` and silences logger levels for several packages.
    Main already has logging configuration (cli.py, lines 490-505, 675 via `_init_logging()`).

    **Problems:**
    1. Duplicate configuration: both main and backend configure logging independently
    2. Conflicting state: backend's `configure_logging()` may override main's setup
    3. Layering violation: backend functions shouldn't configure global state
    4. Hard to test: backend function has side effects on global logging configuration
    5. Inflexible: caller can't control logging behavior (forced to WARNING levels)
    6. Order-dependent: works differently depending on whether main or backend runs first

    **Fix:** Move all logging configuration to the entry point (main). Backend should get
    a logger via `logging.getLogger(__name__)` but NOT configure it. Main's `_init_logging()`
    should handle silencing noisy libraries. Benefits: single responsibility, predictable,
    testable, flexible, composable. General principle: library/backend functions should USE
    logging but NOT CONFIGURE it. Configuration belongs at the application boundary.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/minicodex_backend.py': [
      [190, 194],  // configure_logging() and logger silencing in backend
    ],
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [490, 505],  // _init_logging: existing logging setup in main
      [675, 675],  // Call to _init_logging in async_main
    ],
  },
  expect_caught_from=[
    ['adgn/src/adgn/git_commit_ai/minicodex_backend.py'],
    ['adgn/src/adgn/git_commit_ai/cli.py'],
  ],
)
