local I = import '../../lib.libsonnet';


I.issue(
  rationale= |||
    Lines 155, 160, and 188 in app.py store `docker_client` in `app.state` but only
    use it locally within the same function where it's created.

    **Analysis:**
    - `docker_client` is set once on line 155
    - Accessed ONLY on lines 160 and 188 in the SAME function
    - NEVER accessed elsewhere in the codebase
    - Only used to pass to constructors during initialization

    **Problem:**
    Putting it in `app.state` makes it global mutable state unnecessarily. This increases
    the "bag of random global state items", suggests the client might be used elsewhere
    (misleading), and makes usage harder to track.

    **Fix:**
    Change line 155 to `docker_client = docker.from_env()` (local variable) and replace
    both uses of `app.state.docker_client` (lines 160, 188) with `docker_client`.

    This reduces global state, clarifies scope, and makes the code easier to test.
    Only put things in `app.state` if they need to be accessed from request handlers
    or other parts of the application.
  |||,
  filesToRanges={
    'adgn/src/adgn/agent/server/app.py': [
      [155, 155],  // app.state.docker_client = (set)
      [160, 160],  // docker_client=app.state.docker_client (use 1)
      [188, 188],  // docker_client=app.state.docker_client (use 2)
    ],
  },
)
