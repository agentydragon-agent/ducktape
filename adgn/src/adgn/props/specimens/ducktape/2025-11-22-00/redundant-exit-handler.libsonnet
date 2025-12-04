local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    cli.py async_main() (lines 659-734) has a try-except handler that catches
    ExitWithCode exceptions only to immediately call sys.exit() with the same code.
    This adds 4 lines and indents 70+ lines of main logic for no benefit.

    Problems: (1) redundant indentation of all main logic, (2) handler doesn't
    transform, log, or enrich the exit code, (3) misleading - suggests special
    handling that doesn't exist, (4) verbosity.

    Remove the try-except entirely. Let ExitWithCode propagate to the top level;
    Python's default behavior will still terminate with the exit code. Or if clean
    exit is needed, the existing sys.exit() calls at the end are sufficient.

    Benefits: 4 fewer lines, one less indent level, clearer code without false
    suggestion of special handling. Top-level functions typically don't catch their
    own exit exceptions.
  |||,
  filesToRanges={
    'adgn/src/adgn/git_commit_ai/cli.py': [
      [660, 660],  // try: at start of async_main
      [733, 734],  // except ExitWithCode as e: sys.exit(e.code)
    ],
  },
)
