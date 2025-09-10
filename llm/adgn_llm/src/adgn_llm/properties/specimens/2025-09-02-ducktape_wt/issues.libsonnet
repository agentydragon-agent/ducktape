local I = import '../../specimen_issues.libsonnet';

I.rootV2(
  I.sourceGitHub('agentydragon', 'ducktape', '315fe021dbccbbb0682f10954f45d0145c92faf4'),
  I.scope(['wt/**']),
  [

  // iss-001: Imports at the top — many single-line occurrences across files
  I.issueOccurrencesFromLines(
    id='iss-001',
    rationale='Inline imports inside functions that have no reason to be lazy. Move to module top.',
    properties=['imports-top'],
    linesByFile={
      'wt/wt/cli.py': [101, 158, 193, 198, 206, 253],
      'wt/wt/client/handlers.py': [10, 16, 50, 75, 86, 89, 94, 97, 104, 120, 127, 134, 136, 142, 152, [164, 168], 194, 196, 201, 214, 220, 226, 238, 240, [242, 243], 249, 254, 263, 277, 298, [301, 302], 310, 342],
      'wt/wt/client/shell_utils.py': [9, 20],
      'wt/wt/client/worktree_utils.py': [83, [108, 109], 148],
      'wt/wt/client/wt_client.py': [42, 67, 99, 168],
      'wt/wt/server/github_client.py': [109],
      'wt/wt/server/copy_strategies.py': [123, 139],
      'wt/wt/plugins.py': [41, 46],
      'wt/wt/server/worktree_service.py': [105, 197, 214, 264, 281, 293, [300, 301], 388, 445, 490, 507, 513],
      'wt/wt/server/wt_server.py': [85, 102, 1149, 1171, 1186, 1217, 1240, 1608, 1736, 1741, 1815, 1864, [1884, 1888], 1996, 2021, 2103, 2117, 2155, [2583, 2587]],
      'wt/wt/shared/configuration.py': [69],
      'wt/wt/shared/error_handling.py': [141],
      'wt/tests/e2e/test_path_watcher_integration.py': [23, 60],
      'wt/tests/integration/test_shell_integration.py': [41, 42, 57, 63, 64, 66],
      'wt/tests/test_utils.py': [10, 15],
      'wt/tests/repo_factory.py': [165],
      'wt/tests/conftest.py': [109, 111, 212, 217, 296, 354],
    },
  ),

  // iss-002: Use StrEnum for string-valued enums
  I.issueOccurrencesFromLines(
    id='iss-002',
    rationale=|||
     Use StrEnum for closed sets of string domain values so they behave as plain strings at boundaries
     (serialization/APIs/JSON) without forcing callers to unwrap .value, while still enforcing the
     allowed set.
    |||,
    properties=['strenum'],
    linesByFile={
      'wt/wt/shared/github_models.py': [[13, 18], [49, 52], [60, 62]],
      'wt/wt/shared/configuration.py': [[21, 27]],
      'wt/wt/shared/protocol.py': [[34, 40], [317, 322], [435, 441], [443, 449]],
      'wt/wt/server/gitstatusd_client.py': [[29, 43]],
      'wt/wt/server/copy_strategies.py': [[18, 23]],
    },
  ),

  // iss-003: Markdown inline formatting for identifiers/flags/paths/URIs
  I.issueOccurrencesFromLines(
    id='iss-003',
    rationale='Use Markdown inline code for environment variable names (e.g., WT_DIR).',
    properties=['inline-formatting'],
    linesByFile={
      'wt/ARCHITECTURE.md': [256, 259],
      'wt/WORKTREE_IDEAS.md': [7, 16],
      'wt/tests/README.md': [68, 71],
    },
  ),
  I.issueOccurrencesFromLines(
    id='iss-004',
    rationale='In Markdown, format environment variables (e.g. PATH) with inline code.',
    properties=['inline-formatting'],
    linesByFile={
      'wt/README.md': [16, 18, 190],
    },
  ),

  // iss-005: Pass PathLike to filesystem/subprocess APIs
  I.issueOccurrencesFromLines(
    id='iss-005',
    rationale='Pass Path/PathLike directly to subprocess and filesystem APIs; avoid unnecessary str().',
    properties=['pathlike'],
    linesByFile={
      'wt/wt/server/copy_strategies.py': [46, 63, 111],
      'wt/wt/server/worktree_service.py': [337],
      'wt/wt/shared/git_utils.py': [29],
      'wt/wt/server/wt_server.py': [2052],
      'wt/tests/repo_factory.py': [172, 188],
    },
  ),
  I.issueOneOccurrence(
    id='iss-006',
    rationale=|||
     `_get_copyable_entries` casts `Path` to `str` only to pass it to `subprocess.run`.
     But that method is fine with `Path`s. Remove the unnecessary cast and just keep paths as `Path`s.
    |||,
    properties=['pathlike'],
    filesToRanges={"wt/wt/server/copy_strategies.py": [[12, 15]]},
  ),

  // iss-007: Scoped try/except
  I.issueOneOccurrence(
    id='iss-007',
    rationale=|||
     This code silently hides ImportError/AttributeError when loading plugins.
     Those would be real and severe errors that should:
       - At the very least be logged if nothing better is possible
       - Ideally (if interactive) they should trigger a loud crash
         - Easiest way to do that: just not catch these exceptions here at all
    |||,
    properties=[],
    filesToRanges={
      'wt/wt/plugins.py': [[59, 63]],
    },
  ),
  I.issueOneOccurrence(
    id='iss-008',
    rationale=|||
     `_refresh_github_cache` swallows exceptions and returns silently in non-boundary code.
     Narrow the try to the minimal risky repo access.
     Catch specific exceptions or let them propagate, and log appropriately.
    |||,
    properties=['scoped-try-except'],
    filesToRanges={
      'wt/wt/server/wt_server.py': [[586, 593]],
    },
  ),
  I.issueOneOccurrence(
    id='iss-009',
    rationale=|||
     In `PRService.get_pr_info`, a blanket `except Exception` in non-boundary code silently swallows
     errors and the try wraps a long block. Scope the try to just the GitHub call and catch specific
     expected exceptions (or let them propagate) with proper logging.
    |||,
    properties=['scoped-try-except'],
    filesToRanges={
      'wt/wt/server/wt_server.py': [[613, 635]],
    },
  ),
  I.issueOneOccurrence(
    id='iss-010',
    rationale=|||
     Blanket `except Exception:` silenlty swallows *ANY* `Exception` by just setting `git_paths=[]` and continuing.
     Either:
     - Catch only exact specific expected errors (e.g., Git errors) and scope the try narrowly to the list_worktrees call
     - Or remove the try-catch wrap entirely and just let exceptions crash
    |||,
    properties=['scoped-try-except'],
    filesToRanges={
      'wt/wt/server/wt_server.py': [[1621, 1624]],
    },
  ),
  I.issueOneOccurrence(
    id='iss-011',
    rationale=|||
     Do not catch case of "fd3 not open/not present" by catching arbitrary OSErrors. In this case,
     positive and explicit probe is not too difficult so should be used: probe fd3 with fcntl
     (F_GETFD/F_GETFL) to verify it exists and is opened for writing.
    |||,
    properties=[],
    filesToRanges={
      'wt/wt/client/shell_utils.py': [[6, 15]],
    },
  ),

  // iss-012: Forbid dynamic attribute access
  I.issueOccurrencesFromLines(
    id='iss-012a',
    rationale='`getattr(pygit2, "GIT_STATUS_...", 0)` should be plain `pygit2.GIT_STATUS_...`',
    properties=['forbid-dynamic-attrs'],
    linesByFile={
      'wt/wt/server/git_manager.py': [[116, 123]],
      'wt/wt/server/worktree_service.py': [143],
    },
  ),
  I.issueOneOccurrence(
    id='iss-012b',
    rationale='Pass presets by value (`ConfigPresets.FOO`) instead of by name and `getattr`.',
    properties=['forbid-dynamic-attrs'],
    filesToRanges={
      'wt/tests/config_factory.py': [[45, 46], 128],
    },
    gap_note=|||
     This does use bad unnecessary dynamic attribute access, but the deeper issue is that this name-based pattern is brittle and there's an easily available better alternative.
     With value-based presets, this code path is unnecessary no name lookup or error-name formatting needed.
     Prefer value-based API and delete this path.
     Avoid string→getattr→constant-dict indirection.
     Instead:
     - Pass the constant directly (`PRESET = "preset"`), or
     - Have the constant hold the config object itself (`PRESET = Preset(...)`).
    |||,
  ),

  // iss-013: No dead code — logging_config and duplicate paths
  I.issueOneOccurrence(
    id='iss-013',
    rationale='OperationLogger is dead code; JSONFormatter also becomes unused once it’s removed.',
    properties=['no-dead-code'],
    filesToRanges={
      'wt/wt/shared/logging_config.py': [[31, 94], [8, 29]],
    },
  ),
  I.issueOneOccurrence(
    id='iss-013b',
    rationale=|||
     Duplicate hydration/post-creation script invocation paths: a duplicate implementation exists that’s
     only used by tests; production path is separate and not covered. Consolidate on the prod path.
    |||,
    properties=['no-dead-code'],
    filesToRanges={
      'wt/wt/server/worktree_service.py': [[98, 164], [299, 380]],
    },
  ),
  I.issueOccurrencesFromLines(
    id='iss-013c',
    rationale='Dead code; should be deleted.',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/server/git_manager.py': [[40, 41, 'get_status_porcelain'], [200, 224, 'status_porcelain',], [310, 312, 'rev_count()'], [313, 315, 'CannotDeleteWorktree']],
    },
  ),

  // iss-014: Dead code — remove unused classes and helper
  I.issueOccurrencesFromLines(
    id='iss-014',
    rationale='Dead code declarations; never used and should be removed.',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/server/wt_server.py': [[413, 424, 'StatusSnapshot'], [425, 429, 'WorktreeRuntime'], [640, 1144, 'GitStatusdProcess'], [1230, 1233, '_record_github_error ']],
    },
  ),

  // iss-015: No dead code — DisabledGitHubInterface is unused
  I.issueOccurrencesFromLines(
    id='iss-015',
    rationale='DisabledGitHubInterface is not referenced; remove the dead class.',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/server/github_client.py': [[18, 36, 'DisabledGitHubInterface']],
    },
  ),

  // iss-016: No dead code — remove unused guard helpers and parser finalize
  I.issueOccurrencesFromLines(
    id='iss-016',
    rationale='Dead code: remove unused guard helpers and parser finalize method.',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/shared/models.py': [[40, 42, 'Worktree.require_exists'], [44, 46, 'Worktree.require_not_exists'], [145, 151, 'WorktreeParseState.finalize']],
    },
  ),

  // iss-017: No dead code — unused error types and wrappers
  I.issueOccurrencesFromLines(
    id='iss-017',
    rationale='Dead error types and error-handling helpers add API surface without callers; remove them.',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/shared/error_handling.py': [
        [23, 24, 'WorktreeNotFoundError'],
        [27, 28, 'WorktreeAlreadyExistsError'],
        [31, 32, 'ProcessCheckError'],
        [43, 61, 'handle_git_errors'],
        [76, 100, 'handle_process_errors'],
        [102, 117, 'convert_to_click_exception'],
        [120, 139, 'safe_execute'],
      ],
    },
  ),

  // iss-018: No dead code — WorktreeService helpers (service path not used in prod)
  I.issueOccurrencesFromLines(
    id='iss-018',
    rationale=|||
     WorktreeService.{create_worktree, execute_post_creation_script} are dead. Only call sites are in test code.

     Likely cause: responsibilities were moved from client to server (triggered by JSON‑RPC), but Service methods were left behind.

     Evidence to demonstrate:
     1) Only call sites are in tests: rg -n "WorktreeService\.create_worktree\(|execute_post_creation_script\(" wt/ -g '!wt/tests/**'
     2) Trace the prod path in wt_server for worktree_create (JSON‑RPC) — CLI "wt -c" → client handlers.handle_create_worktree →
        daemon_client.create_worktree (JSON‑RPC) → server handle_client_request(...) → _handle_worktree_create_request(..., writer)
     3) Tracer: add temporary log/exception in WorktreeService.create_worktree; exercising worktree creation from CLI should not fire it.

     Recommendation:
     - Delete WorktreeService.create_worktree and execute_post_creation_script; keep only JSON‑RPC server path.
     - Start post-creation script only from within server (_run_post_creation_script_streaming), never from client
       and make tests target the prod path.
    |||,
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/server/worktree_service.py': [
        [98, 164, 'WorktreeService.create_worktree'],
        [299, 380, 'WorktreeService.execute_post_creation_script'],
      ],
    },
  ),

  // iss-019: Prefer Path/PathLike over str for filesystem paths
  I.issueOccurrencesFromLines(
    id='iss-019',
    rationale='Accept Path/PathLike in function signatures and pass Path directly to subprocess/filesystem APIs; avoid str paths.',
    properties=['pathlike'],
    linesByFile={
      'wt/wt/server/git_manager.py': [
        [259, '`path` param of `worktree_add` should be `Path`, not `str`'],
        [297, '`path` param of `worktree_remove` should be `Path`, not `str`'],
      ],
      'wt/tests/integration/test_shell_integration.py': [
        [34, 38, '`run_shell_script` should take `cwd: Path`, not `str`']
      ],
      'wt/wt/client/wt_client.py': [
        [586, '`identify_worktree` should take `absolute_path: Path`, not `str`']
      ],
      'wt/wt/server/wt_server.py': [
        [227, '`trigger_refresh` should take `file_path: Path | None`, not `str | None`'],
        [381, 385, '`_should_trigger_refresh` should take `file_path: Path`, not raw `str`. Avoid redundant `str(file_path)`'],
        [2044, 2052, '`_run_post_creation_script_streaming` should take `script_path` as `Path`, not `str`'],
      ],
      'wt/wt/server/worktree_service.py': [
        [299, 'Change signature to: def execute_post_creation_script(script_path: Path, worktree_path: Path) -> dict']
      ],
    },
  ),

  // iss-020: Scoped try/except — do not silently swallow streaming errors
  I.issueOccurrencesFromLines(
    id='iss-020',
    rationale=|||
     Streaming hook output handler swallows all exceptions with `except Exception: pass`, discarding real errors.
     Either:
     - Catch only exact exceptions that have a specific reason to be ignored here (e.g., BrokenPipeError).
       Log them with context, and decide whether to re-raise or gracefully terminate stream.
     - Just not have any try-catch here at all and let "first, do no harm": i.e., surface errors by crashing
    |||,
    properties=['scoped-try-except'],
    linesByFile={
      'wt/wt/server/wt_server.py': [
        [2069, 2074],
      ],
    },
  ),

  // iss-021: Use pathlib for path writes (avoid open(...))
  I.issueOneOccurrence(
    id='iss-021',
    rationale=|||
     Use pathlib API to reduce this to a oneliner: `config_path.write_text(yaml.dump(config_file.model_dump()))`.
     (This may not be appropriate in huge or perf-critical cases as it loads the whole file into a str, but neither of these are the case here.)
    |||,
    properties=['pathlib'],
    filesToRanges={
      'wt/tests/conftest.py': [[422, 423]],
    },
  ),

  // iss-022: Minimize nesting — remove redundant inner guard under while
  I.issueOccurrencesFromLines(
    id='iss-022',
    rationale='Inner if self.is_running under a while self.is_running loop is redundant; flatten the loop body to reduce nesting.',
    properties=['minimize-nesting'],
    linesByFile={
      'wt/wt/server/wt_server.py': [
        [257, 275],
      ],
    },
  ),

  // iss-023: Prefer comprehensions over for+append
  I.issueOneOccurrence(
    id='iss-023',
    rationale=|||
     Replace for+append loop with a list comprehension. It's shorter, more expressive and takes less units of state.

     Before:
     ```python
     for wtid in worktree_ids:
         worktree_name = parse_worktree_id(wtid)
         worktree_path = self.config.worktrees_dir / worktree_name
         worktree_paths.append(worktree_path)
     ```

     After:
     ```python
     worktree_paths = [
         self.config.worktrees_dir / parse_worktree_id(wtid)
         for wtid in worktree_ids
     ]
     ```
    |||,
    properties=[],
    filesToRanges={
      'wt/wt/server/wt_server.py': [[1610, 1614]],
    },
    gap_note='GAP: Prefer comprehensions for simple constructions over loops with append when readable.',
  ),

  // iss-024: No useless documentation or comments — trim conftest.py docstrings/comments
  I.issueOccurrencesFromLines(
    id='iss-024',
    rationale='Trim historical/obvious documentation; describe only current behavior; keep only non-obvious notes.',
    properties=['no-useless-docs'],
    linesByFile={
      'wt/tests/conftest.py': [
        [391, 394, 'Helper docstring includes historical workflow; trim to describe only current behavior.'],
        [426, 'Remove historical comment about removed fixture. It describes no longer relevant state of codebase. Not useful to keep.'],
        [302, 308, 'Shorten real_temp_repo docstring to a single descriptive line; drop compatibility notes.'],
        [312, 337, 'Trim real_env docstring and meta-comments; keep only non-obvious behavior.'],
      ],
    },
  ),

  // iss-025: Use walrus operator — combine read-and-check
  I.issueOccurrencesFromLines(
    id='iss-025',
    rationale='Use walrus to combine read‑and‑check.',
    properties=['walrus'],
    linesByFile={
      'wt/wt/server/wt_server.py': [
        [1482, 1484, 'Use walrus to combine read‑and‑check: `if not (data := await reader.readline()): return`'],
      ],
    },
  ),

  // iss-026: Walrus operator — bind and check gitstatusd response in one line
  I.issueWithOccurrences(
    id='iss-026',
    rationale='Use walrus to bind and check the parsed response in a single, readable line.',
    properties=['walrus'],
    occurrences=[ { files: {
      'wt/wt/server/gitstatusd_client.py': [ [188, 188] ],
    }, note: |||
      Before:
      ```python
      response_data = raw_response.rstrip("\x1e")
      if not response_data:
          raise GitStatusdParseError("Empty response from gitstatusd")
      ```
      After:
      ```python
      if not (response_data := raw_response.rstrip("\x1e")):
          raise GitStatusdParseError("Empty response from gitstatusd")
      ```
    |||,
    } ],
  ),

  // iss-027: Post‑creation script check — walrus + concise one‑liner
  I.issueWithOccurrences(
    id='iss-027',
    rationale=|||
     Post‑creation script check: shorten and use walrus. Also:
     - Drop redundant existence check
     - Fold error message into a concise one‑liner (can be done without loss of expressiveness).
     Also see: [No useless documentation or comments](../../definitions/no-useless-docs.md).
    |||,
    properties=['walrus'],
    occurrences=[ { files: {
      'wt/wt/server/wt_server.py': [ [1971, 1977] ],
    }, note: |||
      Post‑creation script check: shorten and use walrus. Also:
      - Drop redundant existence check
      - Fold error message into a concise one‑liner (can be done without loss of expressiveness).

      Before:
      ```python
      # If a post-creation script is configured, validate it exists before any side effects
      if self.config.post_creation_script:
          script = self.config.post_creation_script
          if not script.exists() or not script.is_file():
              raise ValueError(
                  f"Post-creation script configured but not found or not a file: {script}",
              )
      ```
      After:
      ```python
      if (script := self.config.post_creation_script) and not script.is_file():
          raise ValueError(f"Post-creation script is not a file: {script}")
      ```
    |||,
    } ],
    gap_note='GAP: Beyond walrus, codify concise guard patterns (drop redundant existence checks; prefer single clear validation and message).',
  ),

  // iss-028: No useless docs — remove/rewrite trivial docstrings and historical comments
  I.issueOccurrencesFromLines(
    id='iss-028',
    rationale=|||
     Remove or simplify docstrings/comments that restate the obvious or describe merely-historical workflows.
     Keep only documentation that has actual value for current state of the codebase.
     (One particular case: does not restate what's obviousl immediately from source code.)
    |||,
    properties=['no-useless-docs'],
    linesByFile={
      'wt/wt/server/wt_server.py': [ [674, 675, 'Remove historical comment (filesystem watching moved); document current state only.'] ],
      'wt/wt/client/handlers.py': [ [5, 'Docstring for `handle_status` restates the obvious; delete.'] ],
      'wt/wt/shared/github_models.py': [ [21, 23, '`is_merged` docstrings restate the obvious; remove or drop property if unused.'], [55, 57, '`is_merged` docstrings restate the obvious; remove or drop property if unused.'] ],
      'wt/wt/server/gitstatusd_client.py': [ [133, 141, '`is_ahead_of_upstream` / `is_behind_upstream` docstrings restate the obvious; remove.'] ],
    },
  ),

  // iss-029: No dead code — configuration legacy aliases
  I.issueOccurrencesFromLines(
    id='iss-029',
    rationale='Dead legacy aliases: migrate callers and delete: main_repo_resolved, worktrees_dir_resolved, daemon_dir, daemon_socket_file, daemon_pid_file.',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/shared/configuration.py': [[92, 116]],
    },
  ),

  // iss-030: No dead code — GitHub models unused types
  I.issueOccurrencesFromLines(
    id='iss-030',
    rationale='Dead/unused GitHub types: PullRequest (L65), PullRequestView (L92), PullRequestCache; remove or consolidate.',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/shared/github_models.py': [[65, 65, 'PullRequest'], [92, 92, 'PullRequestView'], [105, 105, 'PullRequestCache']],
    },
  ),

  // iss-031: No dead code — protocol dead declarations
  I.issueOccurrencesFromLines(
    id='iss-031',
    rationale='Dead/unused protocol declarations: ProgressUpdate (L426), SUPPORTED_METHODS (L497).',
    properties=['no-dead-code'],
    linesByFile={
      'wt/wt/shared/protocol.py': [[426, 426, 'ProgressUpdate'], [497, 497, 'SUPPORTED_METHODS']],
    },
  ),

  // TODO: add in false_positives.md
])
