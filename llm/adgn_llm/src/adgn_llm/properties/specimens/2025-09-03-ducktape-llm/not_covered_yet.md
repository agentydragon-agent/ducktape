## git_commit_ai/cli.py

- Unnecessary formatting that adds negative value
  - Finding: `timeout_label = ("infinite" if config.timeout is None else f"{int(config.timeout.total_seconds())}s")` introduces extra code while making the output worse (coarser and with arbitrary suffix). Prefer logging `config.timeout` directly; the extra transformation provides no value and reduces clarity.
  - Rationale: No existing property explicitly covers “avoid pointless transformations in logs/formatting.” Closest related (e.g., no-oneoff-vars-and-trivial-wrappers) doesn’t apply because this is a formatting transform, not a pass-through. Keeping as not-covered-yet.

- Merge adjacent debug logging blocks
  - Finding: Two `if known.debug:` blocks perform closely related logging; combine to reduce duplication and keep debug side-effects together.
  - Rationale: No explicit property for combining adjacent identical guards; related to maintainability/DRY but not covered by a current definition.

- Comment placement for suppress context
  - Finding: Comment describing exception-suppressed behavior sits below the `with contextlib.suppress(Exception):` line. Prefer combined single-line comment before the suppress, e.g., "Truncate to fit terminal width. If we can't get terminal size, use full status."
  - Rationale: Style/readability improvement; not clearly covered by an existing Markdown/code property.
- Duplication of git diff arguments
  - Finding: Multiple places build nearly identical git diff invocations with only a single flag difference (HEAD vs --cached, plus common flags like --name-status/--unified=0/--stat). Compute the common args once, then join for display and splat for execution to reduce duplication and drift.
  - Rationale: This is a DRY/maintainability concern; there is no current property that explicitly requires deduplication of argument lists. Keeping as not-covered-yet.
  - Anchors (cli.py): 144–153, 187–193, 301–317, 321–324, 343–346, 373–389, 430–431
- Functional return over in-place mutation
  - Finding: Helper `_cap_append` mutates the `parts` list; prefer a pure helper that returns a single string to append at call sites (not performance-critical; StringBuilder pattern unnecessary here). This reduces side effects and clarifies the flow (functional > imperative for this context).
  - Rationale: No current property explicitly covers preferring return over mutation for non‑critical paths. Keeping as not-covered-yet.
  - Subject: git_commit_ai/cli.py (`_cap_append` and its call sites)
- Shebangs on library modules with console-entry scripts
  - Finding: Files under packages that are exposed via console_scripts should not carry `#!/usr/bin/env python3` shebangs or be executable; the shim handles execution. Remove shebangs on modules (keep only on true scripts under bin/ if any).
  - Anchors (examples): llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:1, multiple others across repo (see grep list in specimen).
  - Rationale: No explicit property covering shebang policy for library modules; capture as not-covered-yet.

- Redundant AppConfig fields (model_str alongside provider and model_name)
  - Finding: `AppConfig(provider=..., model_name=..., model_str=...)` passes an easily-derivable `model_str = f"{provider}:{model_name}"` used once; prefer deriving at the point of use instead of storing redundant state.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:74–95
  - Rationale: Not covered by an existing property; this is a design hygiene/avoid redundant state recommendation.
- Fold adjacent single-purpose comments
  - Finding: Two consecutive comment lines describe a single obvious condition; fold into one concise line above the code to avoid line waste.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:625–627
  - Rationale: Style/readability; not covered by an explicit property.

- Debug print does not need model_str
  - Finding: `model_str` exists only to feed a debug print; instead print provider and model_name separately and drop the redundant field.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:74–95
  - Rationale: Redundant state/design hygiene; still not covered by an explicit property.
- Use walrus for returncode check when no check=True available
  - Finding: asyncio.create_subprocess_exec lacks check=True; prefer walrus to bind and test in one line: `if (rc := await proc.wait()) != 0: raise CalledProcessError(rc, ...)`.
  - Anchors: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:599–606 (pattern repeats similarly for other subprocess execs)
  - Rationale: Covered by [walrus](../../definitions/python/walrus.md) only when a freshly computed value is immediately checked; logging here matches that rule, but since this is outside agent-edited scope we keep it as a recommendation. If treated strictly, this could be filed under walrus when in edited hunks.
- Existence check only (let exec surface misconfiguration)
  - Finding: `if not (precommit_path.exists() and precommit_path.is_file()): return` silently ignores the case where the path exists but is not a regular file. Prefer checking only `.exists()` and letting the exec path surface an error for non-file cases (or, optionally, raise a specific error). Fewer branches; misconfigurations don’t get hidden.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:596–601
  - Rationale: Simplicity/robustness; not covered by an explicit property.

- Consider raising SystemExit at failure site (with note on cleanup)
  - Finding: Instead of raising `CalledProcessError` and catching it only to `sys.exit`, consider `raise SystemExit(returncode)` in the pre-commit runner. This allows inner/outer `finally` blocks to run (fd close and task teardown) before process exit. Add a short comment explaining we raise SystemExit to let cleanups run.
  - Anchors: detection at 599–607; outer try/except/finally at 621–644
  - Verification note: SystemExit is a BaseException; outer except blocks won’t catch it, but the outer `finally` still runs, so cleanup executes before exit. Ensure no code catches BaseException higher up.
- Avoid raising foreign exception types unnecessarily
  - Finding: Pre-commit failure is surfaced by raising `subprocess.CalledProcessError`, which is a foreign/type-mismatched exception for this domain. Prefer a local exception (e.g., `PrecommitFailed(returncode)`) or `raise SystemExit(returncode)` with a short comment explaining that cleanup `finally` blocks will still run. Reduces coupling and makes intent explicit.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:606–608
  - Rationale: Not covered by an explicit property; record as design hygiene. Keep or convert depending on chosen exit strategy, but avoid misleading cross-module exception types when not required.
- Naming: avoid shadowing builtins when not adding clarity
  - Finding: Parameter name `dir` shadows Python built-in `dir()`. While shadowing can be acceptable if it clearly improves clarity, in this context a more specific name would be better (e.g., `cache_dir` or `base_path`).
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:445
  - Rationale: Judgment/taste; we do not currently have a strict property banning builtin shadowing. Recording as not-covered-yet with recommendation.
- Truncation note should derive from the cap
  - Finding: Truncation message is hardcoded as "[Context truncated to 100 KiB]" in multiple places while cap is MAX_PROMPT_CONTEXT_BYTES. Prefer a single source of truth for the message (derive bytes from the cap with formatting) or a simple generic note ("[Context truncated]").
  - Anchors: cli.py:135–136, 154–156, 174–176, 193–195, 201–205
  - Rationale: DRY/consistency; not covered by an explicit property.

- Prefer character/token-based cap over bytes
  - Finding: Prompt capping is implemented in bytes with encode/decode/ignore-error slicing, which is brittle with multibyte encodings and not aligned with tokenizer semantics. Prefer a character-length cap (or, ideally, token-based) and drop byte-level slicing.
  - Anchor: cli.py:102–205 (cap helper and final truncation)
  - Rationale: Design improvement; no explicit property today. Record as not-covered-yet.
- Duplicate prompt construction for amend vs new commit
  - Finding: Two large f-string prompt templates differ in only a few words; refactor to share a common base and inject differences (e.g., helper that formats the Requirements and Context once, parameterizing the intro).
  - Anchors: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:1112, 1122
  - Rationale: DRY/maintainability; not covered by an explicit property.
- Logging: avoid gating debug logs with a separate boolean
  - Finding: `if self.debug: logger.debug(...)` double-gates logging; prefer relying on logger level (`logger.isEnabledFor(logging.DEBUG)` implicitly) and emit debug logs unconditionally at the call site (optionally guard only expensive formatting). This keeps configuration in the logger, not in call sites.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:1172–1176
  - Rationale: Style/architecture preference; not covered by an explicit property. Record as not-covered-yet.
- Consolidate duplicate pre-commit read loops
  - Finding: The pre-commit PTY reader uses two loops (poll-until-done + drain) but the logic is equivalent to a single `while True` drain loop that exits on EOF/error, since `.done()` becomes true only when the task completes and the drain loop already handles remaining data. Suggest consolidating to one loop with clear exit conditions and comments.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:568–583
  - Rationale: Simplify control flow; not covered by an explicit property.

- Dead argument: master_fd on runner init
  - Finding: `ParallelTaskRunner.__init__(..., master_fd)` takes `master_fd` but does not store/use it; the FD is only passed to `_stream_output` at call time. Remove from `__init__` or store in `self.master_fd` and use consistently.
  - Anchors: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:544–546, 615
  - Rationale: Clarity and API hygiene; not covered by explicit property.

- Useless docstring
  - Finding: `class TaskStatus(StrEnum): """Status of a task."""` repeats the class name and adds no signal. Remove trivial docstrings.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:468–470
  - Rationale: Aligns with "no useless docs" property intent, but since this is not in an edited hunk we’re recording as not-covered-yet guidance.
- Useless inline comment
  - Finding: `# Print the status` restates the next line; remove trivial comments that add no signal.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:694–695
  - Rationale: Style/readability; aligns with "no useless docs" intent, recording here as guidance.

- Prefer GitPython for git var over raw subprocess
  - Finding: `_get_editor` shells out to `git var GIT_EDITOR` via asyncio subprocess; prefer `repo.git.var('GIT_EDITOR')` (or `config_reader().get_value('core', 'editor', ...)` fallback) to avoid external process overhead and centralize error handling.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:731–744
  - Rationale: API usage/maintainability improvement; not covered by an explicit property.

- Make -a/--all an explicit CLI flag we own
  - Finding: Relying on passthru to detect  is fragile; define and parse our own  (and short ) flag, use it to set include_all, and pass the remaining passthru to git unchanged.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:342
  - Rationale: Clear ownership of flags; improves UX and maintainability; not covered by an explicit property.
- Reuse include_all; don’t reparse passthru here
  - Finding: diffstat rechecks "-a/--all" in passthru instead of using the upstream include_all decision. Accept include_all as a parameter and use it consistently to avoid duplicated flag parsing.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:342–346
  - Rationale: DRY and separation of concerns for flag parsing; not covered by an explicit property.

- Prefer argparse handling for disallowed -m/--message
  - Finding: Manual passthru scan blocks -m/--message; define an argparse option (e.g., `--message`) with help noting it’s unsupported, then `if args.message: print+exit` for a cleaner UX and consistent parsing.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:764–769
  - Rationale: CLI ergonomics/maintainability; not covered by explicit property.

- Inline mtime in cache eviction loop
  - Finding: `mtime_s = path.stat().st_mtime` used once; inline the expression in the condition.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py (Cache cleanup loop)
  - Rationale: Aligns with “no one-off variables” spirit; recording as not-covered-yet.

- Inline path and drop trivial docstring in __setitem__
  - Finding: Inline `path = self.dir / f"{key}.txt"` used once; the docstring restates the method name; can be removed or kept minimal.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py: around __setitem__ in Cache
  - Rationale: Minor style refactor; no explicit property enforcement here.
- Determine include_verbose via argparse + walrus
  - Finding: Verbose detection scans passthru for -v/--verbose and then git config; prefer parsing -v/--verbose in argparse (store_true) and using walrus for the config fallback: `include_verbose = args.verbose or (val := ... and str(val).strip().lower() in {...})`.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:421–429
  - Rationale: Cleaner flag ownership plus walrus for immediate-use value; not covered by an explicit property.
- Useless inline comment
  - Finding: `# Print the status` restates the next line; remove trivial comments that add no signal.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:694–695
  - Rationale: Style/readability; aligns with "no useless docs" intent, recording here as guidance.
- Useless inline comment
  - Finding: `# Detect --amend flag` restates the next line; remove trivial comments that add no signal.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py (near amend handling)
  - Rationale: Style/readability; aligns with "no useless docs" intent.

- Do not derive is_amend from passthru; own the flag via argparse
  - Finding: `is_amend = "--amend" in passthru` reparses passthru. Prefer `parser.add_argument("--amend", action="store_true")` and use `args.amend` consistently.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py (amend detection)
  - Rationale: Clear flag ownership; avoids duplicated parsing.

- Inline single-use log_file
  - Finding: `log_file = Path(repo.git_dir) / "git_commit_ai.log"` then used immediately to construct `logging.FileHandler`; inline the expression at the call site.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py (logging setup)
  - Rationale: Avoid one-off variables that add no signal.

- Rename ambiguous variable name "known"
  - Finding: `known, passthru = parser.parse_known_args()` and subsequent `if known.debug:` read oddly in broader context; prefer `args, passthru` or `known_args` for clarity.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py (args parsing and debug check)
  - Rationale: Naming clarity; not covered by an explicit property.
- Useless inline comment
  - Finding: `# Factor out task creation to a single place` is historical and restates the code; remove archaeology-style comments that provide no present-tense signal.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:873
  - Rationale: Style/readability; aligns with "no useless docs" intent.
- Move single-use variable to first use site
  - Finding: `commit_msg_path = Path(repo.git_dir) / "COMMIT_EDITMSG"` is declared many lines before the only use; move it to the first use location to improve locality.
  - Anchors: decl at cli.py:884; use at cli.py:918
  - Rationale: Avoid one-off variables and keep declarations close to use; not covered by an explicit property.
- Inline editor returncode check with walrus
  - Finding: Replace two-step wait+check with `if (rc := await editor_proc.wait()) != 0: ...`.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:927–928
  - Rationale: Matches walrus guidance for immediate condition checks.
- Extract function for scissors-strip + non-comment collapse
  - Finding: The loop that strips content below scissors and collapses non-comment lines would be a natural small helper (e.g., ), improving testability and reuse.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:936 (around empty-message check)
  - Rationale: Refactor suggestion; no explicit property.

- Avoid duplicating cleanup logic between git flag and Python parsing
  - Finding: Using  while also performing custom Python cleanup (scissors/comment stripping) risks partial duplication/drift. Prefer a single source of truth (either rely on git cleanup plus a minimal check, or centralize in Python helper and align flags accordingly).
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:(flag location) and the scissors parsing loop above
  - Rationale: DRY/consistency; not covered by explicit property.
- Extract function for scissors-strip + non-comment collapse
  - Finding: The loop that strips content below scissors and collapses non-comment lines would be a natural small helper (e.g., `extract_commit_content(text)`), improving testability and reuse.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py (around empty-message check after editor)
  - Rationale: Refactor suggestion; no explicit property.

- Avoid duplicating cleanup logic between git flag and Python parsing
  - Finding: Using `--cleanup=strip` while also performing custom Python cleanup (scissors/comment stripping) risks partial duplication/drift. Prefer a single source of truth (either rely on git cleanup plus a minimal check, or centralize in Python helper and align flags accordingly).
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py (`--cleanup=strip` near commit invocation; empty-message check loop nearby)
  - Rationale: DRY/consistency; not covered by explicit property.
- Inline or exec commit return code
  - Finding: Two-step `exit_code = await commit_proc.wait(); sys.exit(exit_code)` can be inlined with walrus or replaced by an exec approach (handing control to git). Exec has tradeoffs (no post-commit cleanup), but inlining is straightforward.
  - Anchors: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:902–904, 978–981
  - Rationale: Minor cleanup; not covered by explicit property.

- Factor shared commit trunk (fast vs editor paths)
  - Finding: The fast-path (accept AI) and editor-path duplicate the commit subprocess setup. Extract a common function (e.g., `_run_git_commit(repo, message, passthru, include_all, verbose)`), reducing duplication and keeping arg handling uniform.
  - Anchors: commit blocks at cli.py:892–904 and 967–981
  - Rationale: DRY/maintainability; not covered by an explicit property.
- Prefer module-level logger over per-instance logger
  - Finding: `self.logger = logging.getLogger(__name__)` inside classes; prefer a top-level `logger = logging.getLogger(__name__)` and use it, unless instances need distinct names or context.
  - Anchors: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:1011, 1101
  - Rationale: Consistency and simpler configuration; not covered by an explicit property.

- Unify prompt-length cap configuration
  - Finding: Claude path uses env var and a 20k cap; Codex path uses a different mechanism. Define a single env var (e.g., GIT_AI_MAX_PROMPT) with a consistent fallback and apply uniformly across providers.
  - Anchor: provider-specific sections where caps are applied
  - Rationale: Consistency; not covered by explicit property.
- Add reference link to git’s template assembly
  - Finding (suggestion): In `build_commit_template`, include a docstring reference to the relevant git source that assembles the standard commit message (e.g., sequencer/commit.c or the code path for COMMIT_EDITMSG construction), to aid maintainers.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:363
  - Rationale: Documentation enhancement for future readers; optional.
- Reduce variables in editor flow
  - Finding: In the editor path, `final_text = msg` then `final_text += ...` and later `content_before = final_text` creates 3 names where 1–2 suffice. Keep `final_text` only (or compute `content_before` only if needed without the extra transient).
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py (editor commit-message assembly just before COMMIT_EDITMSG write)
  - Rationale: Minor DRY/simplicity; no explicit property.
- Avoid `prompt = prompt + ...`; prefer `+=`
  - Finding: When appending to a string repeatedly, prefer `prompt += ...` over `prompt = prompt + ...` for brevity and readability.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:253–264
  - Rationale: Minor style; not covered by an explicit property.
- Deduplicate shared prompt footer across amend/non-amend
  - Finding: The instruction block (tags requirement and surrounding boilerplate) is duplicated between amend and non-amend prompts. Extract a shared helper/constant and parameterize only the intro line(s).
  - Anchors: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:214–221, 227–229
  - Rationale: DRY; not covered by an explicit property.

- Align amend and non-amend prompt sections (Context/examples/diffstat)
  - Finding: The amend prompt omits sections that the non-amend path includes (Context, example outputs, diffstat) without a clear reason. Either include the same sections for parity or document the intentional difference.
  - Anchors: amend intro 214–221 vs context/diff additions beginning 243–264 and later
  - Rationale: Consistency/clarity of prompt contract; not covered by an explicit property.

- Remove unnecessary "Diffstat:" label
  - Finding: The heading "Diffstat:" is redundant given the immediately following git command; remove extra label/noise.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:245–246
  - Rationale: Brevity/readability; not covered by an explicit property.
- One constant for staged diff preview cap
  - Finding: The magic number 5000 is duplicated across branches for the staged diff preview. Replace with a single named constant (e.g., STAGED_DIFF_PREVIEW_CHARS = 5000) and use it in both places.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:253–264
  - Rationale: DRY/maintainability; not covered by explicit property.

- Remove unused default for previous_message
  - Finding: `previous_message: str | None = None` is never omitted by callers; drop the default to reduce unnecessary degrees of freedom.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:280–281
  - Rationale: API clarity; not covered by explicit property.

- Remove archaeological comment about provider:model parsing
  - Finding: Comment “provider:model parsing handled by AppConfig.resolve” is historical and redundant now that the abstraction exists. Delete trivial archaeology comments.
  - Anchor: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py (near where provider and model_name are read from config)
  - Rationale: Style/readability; aligns with no-useless-docs intent.
- Make provider.generate(model) parameter required (non-optional)
  - Finding: `async def generate(self, include_all: bool, model: str | None = None)` is always called with a model in production paths; drop the `| None = None` to tighten the contract. Tests can pass a dummy string if needed.
  - Anchors: llm/adgn_llm/src/adgn_llm/git_commit_ai/cli.py:1013, 1103 (and test override at tests/test_git_commit_ai_amend.py:33)
  - Rationale: Type correctness/specificity; aligns with type-correctness property but recording here as design tightening.
- Cap handling: constant params, per-block vs total, and naming
  - Finding: `_cap_append(parts, chunk, MAX_PROMPT_CONTEXT_BYTES, "[Context truncated…]")` passes constants every time; consider defaulting `cap_bytes` and `truncation_note` inside the helper (or deriving the note from the cap) to avoid repetitive arguments.
  - Finding: Current caps apply per Git output block (status/name-status/diff/log), not to the total prompt, so effective max can be N× the cap. Prefer a single accumulator-based total cap enforced once over the fully assembled prompt, or track remaining bytes across calls to `_cap_append`.
  - Finding: The name `MAX_PROMPT_CONTEXT_BYTES` is tautological (“prompt” ≈ “context” here); pick one term or use a scope‑specific name. Either (a) rename to reflect the true scope (e.g., `MAX_PROMPT_GIT_OUTPUT_BYTES` for per‑block caps), or (b) switch to a true total `MAX_PROMPT_BYTES` and enforce globally.
  - Anchors: constant decl at cli.py:60; helper signature at cli.py:102–104; uses at cli.py:132–136, 154–156, 174–176, 193–195; final cap at cli.py:201–205.
  - Rationale: DRY and correctness of limits; clearer terminology for maintainers.
- Cache key → path helper (with key validation)
  - Finding: Both `get` and `__setitem__` compute `self.dir / f"{key}.txt"` inline. Extract a shared helper (e.g., `_path_for(key) -> Path`) that also validates keys (no slashes, reasonable length) to prevent path traversal and centralize logic.
  - Anchor: Cache class (get/__setitem__) in git_commit_ai/cli.py
  - Rationale: Small refactor + safety; not covered by an explicit property.

- Use walrus for single-use `path` in Cache.get
  - Finding: `path = ...; return path.read_text() if path.exists() else None` can be simplified with walrus: `return path.read_text() if (path := self._path_for(key)).exists() else None`.
  - Anchor: Cache.get in git_commit_ai/cli.py
  - Rationale: Matches walrus guidance for immediate condition checks.

- Inline get_short_commitish (single use)
  - Finding: `get_short_commitish(repo)` is used once; inline the `repo.git.rev_parse("HEAD", short=True)` call and remove the helper.
  - Anchor: get_short_commitish in git_commit_ai/cli.py
  - Rationale: Reduce indirection; not covered by explicit property.

- Extract provider-selection + caching into a helper to enable early bailout
  - Finding: The branch that selects provider (claude/codex), creates the task, optionally runs pre-commit, awaits `ParallelTaskRunner.create_and_run`, and writes cache is a natural cohesive unit. Move into a function (e.g., `_generate_commit_message(repo, include_all, provider, model_name, previous_message, passthru, config, debug) -> tuple[msg, cached]`) so the call site becomes a small early-bailing wrapper; consider a decorator for timing/logging. Also include cache-key computation nearby for cohesion.
  - Anchor: Block around `if msg := cache.get(key): ... else: ...` in git_commit_ai/cli.py
  - Rationale: Early-bailout and DRY; improves readability and testability.

## mini_codex

- Dict comprehension for local_tools
  - Finding: Build `local_tools` via a dict-comprehension from `local` instead of nested loops.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py (local_tools construction)
  - Rationale: Style/DRY; not covered explicitly.

- Truthiness check
  - Finding: Prefer `if mcp_manager:` over `if mcp_manager is not None:`. It’s the only non-truthy value by type, so truthiness is clearer and idiomatic.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py (tool dispatch)
  - Rationale: Python style; not covered explicitly.

- Future annotations (drop quoted types)
  - Finding: Enable `from __future__ import annotations` and use non-quoted annotations instead of `-> "McpManager"`.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py (classmethod return annotation)
  - Rationale: Modern Python typing; not covered explicitly.

- Deduplicate Pydantic message models
  - Finding: Pydantic models (UserMessage/AssistantMessage/FunctionCallOutput) are defined in multiple modules with comments about avoiding cross-module deps. Define once (or reconsider if needed) and import; duplication is not justified by that rationale.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex (agent.py and mcp_manager.py)
  - Rationale: DRY and API cohesion; not covered explicitly.

- Structured return type for call_tool (avoid exit/stdout/stderr schema)
  - Finding: `call_tool` returns a subprocess-like schema; MCP tool outputs are not inherently process-exit-shaped. Define a structured return type (TypedDict/dataclass) appropriate to each tool, avoid assuming exit/stdout/stderr universally.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py:call_tool
  - Rationale: API design; not covered explicitly.

- Preserve OpenAI messages structure
  - Finding: Concatenating all assistant text blocks into one string loses fidelity vs using multi-part content per the OpenAI API; preserve block structure rather than "\n".join.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/agent.py (assistant_text_chunks handling)
  - Rationale: API correctness/clarity; not covered explicitly.

- DI _openai_client for tests
  - Finding: `self._client = _openai_client()` should be injected for testing; e.g., accept a client factory or client param with a default.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/agent.py:110
  - Rationale: Testability/design; not covered explicitly.

- Rename ambiguous parameter `system` (note)
  - Finding: `system` is overloaded; prefer `system_message`. Current property doesn’t strictly mandate this; leave as not-covered-yet.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/agent.py (parameter `system: str | None`)
  - Rationale: Naming clarity; not covered explicitly.

- Consolidate local vs local_servers vs local_tools
  - Finding: `McpManager.from_servers(local, local_servers)` naming collides; if `local_tools` is subsumed by a local exec server, remove the dict and keep `local_servers`. Clarify naming to avoid `local` vs `local_servers` ambiguity.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py: from_servers signature and related types
  - Rationale: API cohesion; not covered explicitly.

- Simplify prompt tool reference (avoid extracting exact tool name)
  - Finding: Instead of resolving the exact MCP tool name for docker and interpolating it into the prompt, describe the desired action (“operate on the connected Docker container …”) and rely on the tool’s schema; reduces brittleness and saves lines of code that aren’t worth the runtime reflection.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/examples/run_minicodex_docker_demo.py (docker_tool extraction and prompt assembly)
  - Rationale: Prompt robustness/maintainability; not covered explicitly.

- Deduplicate helper functions across modules
  - Finding: `_responses_create_with_retry` is defined in both mini_codex/agent.py and mini_codex/cli.py; define once (e.g., in agent) and import to avoid drift.
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/agent.py:42
    - llm/adgn_llm/src/adgn_llm/mini_codex/cli.py:184
  - Rationale: DRY; not covered explicitly.

- Unify OpenAI client factory
  - Finding: `openai_client()` is duplicated in agent.py and cli.py; define in one place and import. Combined with “remove manual OPENAI_API_KEY plumbing” this simplifies configuration.
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/agent.py:45
    - llm/adgn_llm/src/adgn_llm/mini_codex/cli.py:158
  - Rationale: DRY; not covered explicitly.

- Deduplicate error paths in call_tool
  - Finding: Unknown function vs generic exception produce near-identical subprocess-shaped dicts; consolidate into one path (or better: structured returns per tool as noted elsewhere).
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py:call_tool
  - Rationale: DRY; not covered explicitly.

- FunctionCallOutput payload should be a plain string
  - Finding: Avoid JSON-wrapping arbitrary dicts for FunctionCallOutput; send human-readable text (e.g., “No such function: …”) unless the consumer requires JSON.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py: FunctionCallOutput emission
  - Rationale: Simplicity/clarity; not covered explicitly.

- Import spacing (ruff)
  - Finding: Ensure one blank line between imports and constants/variables (ruff fix); e.g., after `from adgn_llm.mini_codex.agent import MiniCodex, load_mcp_file` before `LOCAL_EXEC_SERVER_NAME`.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py (module header)
  - Rationale: Style; not covered explicitly.

- Deduplicate truncation and append TIMEOUT after truncation
  - Finding: Duplicate `_truncate_bytes` calls in success/timeout branches; consider a common post-processing step. Append "[TIMEOUT]" after truncation to avoid losing the marker. Also hoist the “[TRUNCATED]” marker into a CONSTANT and reuse it in one place.
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py:39
    - llm/adgn_llm/src/adgn_llm/mini_codex/cli.py:100
    - llm/adgn_llm/src/adgn_llm/inop/runners/minicodex_runner.py:270, 320
  - Rationale: DRY and correct marker visibility; not covered explicitly.

- Remove manual OPENAI_API_KEY plumbing in client factory
  - Finding: The OpenAI SDK already reads OPENAI_API_KEY/OPENAI_BASE_URL from the environment; avoid hand-rolling a wrapper that fetches env vars and just call `openai.OpenAI()` (or use DI to pass a client) to reduce code and duplication of config paths.
  - Anchor: llm/adgn_llm/src/adgn_llm/mini_codex/agent.py (`_openai_client`/`openai_client` factory)
  - Rationale: Simplicity/avoid redundant env handling; not covered explicitly.

- Duplicate instruction block (two places)
  - Finding: The try/except around mcp_manager.instruction_block is duplicated; extract a small helper and reuse.
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/cli.py:199–204 and 285–290
  - Rationale: DRY; not covered explicitly.

- Collapse CLI to agent (remove duplicated Responses flow)
  - Finding: responses_turn and responses_followup_with_tool_outputs duplicate ~20 lines (instructions assembly, tool listing, serialization). Collapse: agent.py should manage the agent loop and Responses flow; cli.py should delegate (thin wrapper), avoiding copy/paste.
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/cli.py:188–218 vs 276–306 (and surrounding setup)
  - Rationale: DRY/maintainability; not covered explicitly.

## mcp/docker_exec/server.py

- Avoid mutable global state for clients/refs
  - Finding: Global Docker client and container reference create mutable global state, hindering tests and multi-instance usage. Inject clients via factory/parameters or manage per-request context; avoid module-level singletons.
  - Anchor:
    - llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py: globals `_DOCKER_CLIENT` and `_CONTAINER_REF`
  GAP: Add a property banning mutable global state in production code except for true constants and safe caches; prefer dependency injection.
