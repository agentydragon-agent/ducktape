local I = import '../../specimens/lib.libsonnet';

// iss-016: Logging configuration in backend function instead of main

I.issueOneOccurrence(
  rationale= |||
    The `generate_commit_message_minicodex()` backend function calls `configure_logging()`
    and configures logger levels, but logging configuration should be done at the application
    entry point (main), not in backend/library functions.

    **Current implementation (minicodex_backend.py, lines 190-194):**
    ```python
    async def generate_commit_message_minicodex(model: str, *, debug: bool = False, amend: bool = False) -> str:
        # ... setup code ...

        # Initialize global logging (console at WARNING; file at ADGN_LOG_DIR if set)
        configure_logging()
        # Silence MiniCodex/structlog chatter for git_commit_ai invocations
        for name in ("mini_codex", "MiniCodex", "adgn_llm.mini_codex", "mcp", "openai"):
            logging.getLogger(name).setLevel(logging.WARNING)

        # ... rest of function ...
    ```

    **Main already has logging configuration (cli.py, lines 490-505, 675):**
    ```python
    def _init_logging(repo: pygit2.Repository, debug: bool) -> logging.Logger:
        """Configure root logger to file (always) and stderr (when debug)."""
        log_file = Path(repo.path) / "git_commit_ai.log"
        file_handler = logging.FileHandler(log_file, mode="a")
        # ... configure handlers ...
        return logger

    # In async_main():
    _init_logging(repo, args.debug)
    ```

    **Problems:**

    1. **Duplicate configuration**: Both main and backend configure logging independently
    2. **Conflicting state**: Backend's `configure_logging()` may override main's setup
    3. **Layering violation**: Backend functions shouldn't configure global state
    4. **Hard to test**: Backend function has side effects on global logging configuration
    5. **Inflexible**: Caller can't control logging behavior (forced to WARNING levels)
    6. **Order-dependent**: Works differently depending on whether main or backend runs first

    **The correct approach:**

    Move all logging configuration to the entry point (main):

    ```python
    # In cli.py async_main():
    def _init_logging(repo: pygit2.Repository, debug: bool) -> logging.Logger:
        """Configure root logger to file (always) and stderr (when debug)."""
        log_file = Path(repo.path) / "git_commit_ai.log"
        file_handler = logging.FileHandler(log_file, mode="a")
        # ... configure handlers ...

        # Silence noisy libraries (not just for minicodex backend)
        for name in ("mini_codex", "MiniCodex", "adgn_llm.mini_codex", "mcp", "openai"):
            logging.getLogger(name).setLevel(logging.WARNING)

        return logger

    # In minicodex_backend.py:
    async def generate_commit_message_minicodex(model: str, *, debug: bool = False, amend: bool = False) -> str:
        """Run MiniCodex with docker_exec + submit_commit_message MCP servers."""
        # NO logging configuration here - assume caller has set it up
        logger = logging.getLogger(__name__)  # Get logger, don't configure

        # ... rest of implementation ...
    ```

    **Benefits:**

    1. **Single responsibility**: Main configures logging, backends do work
    2. **Predictable**: Logging setup happens once at startup
    3. **Testable**: Backend functions have no global side effects
    4. **Flexible**: Caller controls all logging behavior
    5. **Composable**: Backend can be used in different contexts (tests, other tools)
    6. **Standard pattern**: Application entry point owns configuration

    **General principle:**

    Library/backend functions should:
    - Use logging (`logger.info()`, etc.) - YES
    - Configure logging (`basicConfig()`, `setLevel()` on root) - NO

    Configuration belongs at the application boundary (main/CLI), not in business logic.
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
)
