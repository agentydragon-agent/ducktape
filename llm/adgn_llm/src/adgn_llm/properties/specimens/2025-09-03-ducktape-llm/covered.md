## git_commit_ai/cli.py

- [early-bailout](../../definitions/early-bailout.md)
  - Finding: Flip the TTY guard to an early bailout so the main body is not nested. Current pattern uses `if sys.stdout.isatty(): ...`; prefer `if not sys.stdout.isatty(): return/skip` followed by the terminal sizing logic.
  - Anchor: cli.py:714 (approx)

- [scoped try/except](../../definitions/python/scoped-try-except.md)
  - Handlers swallow errors instead of failing loudly in cases that represent actual problems; raise specific exceptions (anchors: 138, 157, 177, 196).

- [scoped try/except](../../definitions/python/scoped-try-except.md)
  - “First commit” detection via catching a diff failure swallows unrelated errors; use a positive Repo capability check with early bailout (anchor: 304).

- [truthfulness](../../definitions/truthfulness.md)
  - Do not substitute stdout when reading the codex --output-last-message file fails; this violates the contract that final output is only in the designated file/JSON. Fail loudly or request a new run (location: code path reading last_msg_path and falling back to stdout on exception).
- [early-bailout](../../definitions/early-bailout.md), [minimize-nesting](../../definitions/minimize-nesting.md)
  - Finding: Branch-specific duplication in ParallelTaskRunner.create_and_run; the runner construction and update loop are started inside both branches, with only the output stream differing. Prefer a single shared trunk with early bailout/guard for pre-commit.
  - Anchors: git_commit_ai/cli.py:590–621 (branch setup)
  GAP: Clarify guidance for a shared-trunk-after-guard refactor in parallel task setup; prefer a single runner/update trunk and gate stream by fd presence.
  - Suggested refactor:
    1) Compute precommit_task (real or noop) and master_fd (int or None)
    2) Construct runner once: runner = cls(TaskState(ai_task), TaskState(precommit_task), master_fd)
    3) Start update_task once after runner construction
    4) Start _stream_output only when master_fd is not None
    5) Optionally extract a helper that immediately returns when run_precommit is False to keep the main path flat


### [No useless documentation or comments](../../definitions/no-useless-docs.md)
  - Useless inline comment “Build status string” — anchors: cli.py:686–687
  - Useless inline comment “Detect --amend flag” — anchor: cli.py (near amend handling)
  - Trivial docstring on enum: `class TaskStatus(StrEnum): """Status of a task."""` — anchors: cli.py:468–470
  - Historical comment “Factor out task creation to a single place” — anchor: cli.py:873

### [Use walrus for trivial immediate conditions](../../definitions/python/walrus.md)
  - Inline editor returncode check with walrus instead of two-step wait+check — anchors: cli.py:927–928
  - Returncode check after create_subprocess_exec (no check=) — prefer `if (rc := await proc.wait()) != 0: ...` — anchors: cli.py:599–606
  - Cache.get: single-use path can use walrus in the condition — anchor: Cache.get in cli.py

### [No one-off variables or trivial pass-through wrappers](../../definitions/no-oneoff-vars-and-trivial-wrappers.md)
  - Inline single-use log_file in logging setup — anchor: cli.py (logging setup)
  - Inline mtime expression in cache eviction loop — anchor: Cache cleanup loop in cli.py
  - Move single-use `commit_msg_path` to first use site (avoid early one-off) — anchors: cli.py:884 (decl), 918 (use)
  - Reduce redundant names in editor flow (`final_text`/`content_before`) — anchor: editor message assembly in cli.py

### [Type correctness and specificity](../../definitions/type-correctness-and-specificity.md)
  - Optional parameters that are never None: drop `| None = None` when callers always pass a value to tighten contracts.
    - Anchors: git_commit_ai/cli.py:280–281 (`previous_message` default), 1013 and 1103 (`generate(..., model: str | None = None)`).

### [Use walrus for trivial immediate conditions](../../definitions/python/walrus.md)
  - Include-verbose detection: use walrus for the git config fallback (bind and test immediately) instead of a temporary variable.
    - Anchor: git_commit_ai/cli.py:421–429.


## mini_codex

- [truthfulness](../../definitions/truthfulness.md)
  - Finding: `_run_in_sandbox` only sandboxes on Linux and otherwise runs unsandboxed, which is misleading given the name. Either enforce sandboxing consistently (or fail when unavailable), or rename to reflect behavior and make the contract explicit.
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py (`_run_in_sandbox`)
    - llm/adgn_llm/src/adgn_llm/mini_codex/cli.py (`run_in_sandbox`)

- [scoped try/except](../../definitions/python/scoped-try-except.md)
  - Finding: Broad try/except swallows MCP-related errors; catch specific exceptions or let failures surface.
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/cli.py:199–204, 285–290 (instruction_block); 343–346 (config load)

- [pathlib](../../definitions/python/pathlib.md)
  - Finding: Prefer Path-based APIs: Path.exists()/Path.cwd() over os.path/os.getcwd().
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/cli.py:340–343 (cfg_path), 122–123 (cwd handling)

- [Imports at the top](../../definitions/python/imports-top.md)
  - Finding: Imports inside functions; move to module level unless truly justified.
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/agent.py:_is_retryable (line 29), _openai_client (line 46), load_mcp_file (line 85)
    - llm/adgn_llm/src/adgn_llm/mini_codex/cli.py:_run_proc (line 87)
    - llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py:_run_proc (line 26)
    - llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py:_sanitize_name (line 101)

- [Pathlib usage (Python)](../../definitions/python/pathlib.md)
  - Finding: Use Path methods for file IO (one-liner Path.read_text / Path.open) instead of open(path, ...).
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/agent.py:85–92 (oneliner pathlib)

- [Pathlib usage (Python)](../../definitions/python/pathlib.md)
  - Finding: Prefer Path.cwd() instead of Path(os.getcwd()).
  - Anchor:
    - llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py (config/log dir paths)

- [scoped try/except](../../definitions/python/scoped-try-except.md)
  - Finding: Broad `except Exception: pass` swallows errors while appending `model_dump`; catch specific, expected exceptions or let it crash.
  - Anchor:
    - llm/adgn_llm/src/adgn_llm/mini_codex/agent.py:204–207

- [Use StrEnum for string‑valued enums (Python)](../../definitions/python/strenum.md)
  - Finding: Prefer StrEnum over Literal for string-valued tool policy.
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/agent.py:101, 121

- [Forbid dynamic attribute access](../../definitions/python/forbid-dynamic-attrs.md)
  - Finding: Avoid getattr/hasattr probing when handling result.content items; access known fields directly with proper typing.
  - Anchor:
    - llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py:_call_mcp_tool_live

- [Type hints (Python)](../../definitions/python/type-hints.md)
  - Finding: Avoid quoted return annotations; enable `from __future__ import annotations` and use real types (e.g., `-> McpManager`).
  - Anchor:
    - llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py (classmethod return annotation)

- [No one-off variables or trivial pass-through wrappers](../../definitions/no-oneoff-vars-and-trivial-wrappers.md)
  - Finding: Inline `command = shell` and pass directly to StdioServerParameters; avoid one-off variable.
  - Anchors:
    - llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py:61–71

- [Pathlib usage (Python)](../../definitions/python/pathlib.md)
  - Finding: Replace os.path.exists with Path(cfg_path).exists() for MCP config path checks.
  - Anchor:
    - llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py (config loading)

- [scoped try/except](../../definitions/python/scoped-try-except.md)
  - Finding: Broad try/except around load_mcp_file ignores config errors and continues; fail loudly or handle specific, expected errors.
  - Anchor:
    - llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py (MCP config ignored)


### [Modern type hints (PEP 604 unions, builtin generics)](../../definitions/python/type-hints.md)
- Finding: Legacy typing.Optional/List/Dict/Tuple/Iterator used instead of modern PEP 604 unions and builtin generics.
- Anchors:
  - mcp/sandboxed_jupyter_mcp/jupyter_sandbox_compose.py:48 (_write_default_jupyter_config: extra_py: Optional[str])
  - mcp/sandboxed_jupyter_mcp/jupyter_mcp_launch.py:23-31 (_start_jupyter_server: log_dir: Optional[Path])
  - mcp/docker_exec/server.py:41 (typing imports Any, Dict, Iterator, List, Optional, Tuple), 77-83 (ExecResult: Optional[int]), 85-100 (_iter_stream_demux, _build_exec_cmd signatures)
  - mini_codex/agent.py:7 (typing imports), 24 (ToolMap = Dict[str, Any]), 76 (AgentResult.sequence: List[AgentEvent]), 111 (self._messages: List[Message])
  - mini_codex/local_server.py:4 (typing imports), 19 (get_tools() -> Dict[str, ToolDef])
  - mini_codex/local_exec_server.py:3 (typing imports), 15 (get_tools() -> Dict[str, ToolDef])


## mcp

- [no-dead-code](../../definitions/no-dead-code.md)
  - Finding: Legacy wrapper PolicyConfig retained only for import compatibility in older tests; wrapper no longer used by current code. Delete entirely as dead code.
  - Anchor:
    - llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/wrapper.py (class PolicyConfig)

- [No one-off variables or trivial pass-through wrappers](../../definitions/no-oneoff-vars-and-trivial-wrappers.md)
  - Finding: mcp/sandboxed_jupyter_mcp/cli.py `main()` trivially delegates to `wrapper.main()` without adding value; remove or document an explicit boundary if intentional.
  - Anchor:
    - llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/cli.py:6–7

- [Time and duration use rich time types](../../definitions/domain-types-and-units/time.md)
  - Finding: `_DEFAULT_TIMEOUT` is a float without unit suffix; prefer `timedelta` for internals or add unit suffix `_SECS` and convert at boundaries.
  - Anchor:
    - llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py:55
