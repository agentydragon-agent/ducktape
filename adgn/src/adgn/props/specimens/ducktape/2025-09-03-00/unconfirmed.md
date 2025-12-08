# Unconfirmed findings (auto-generated)

## git_commit_ai

```text
**Type Annotations & Type Correctness**
- Missing type annotations on functions/args: mypy strict flags numerous defs; add return/param types to improve safety (cli.py:72, 209, 453, 458, 480, 486, 501, 506, 517, 523, 544, 550, 555, 585, 594, 648, 656, 659, 665, 698, 710, 729, 747, 1196).
- Returning Any where str is declared: results from GitPython calls are typed Any; coerce or narrow (cli.py:345–346 in `diffstat`, 353 in `get_short_commitish`, 646 in `ParallelTaskRunner.create_and_run`).
- `dict.get(...).ljust(...)` optional access: pyright reports potential None; make non-optional (`status_map.get(k) or f\"{status}:\"`) (cli.py:385, 399).
- `asyncio.create_subprocess_exec` arg types: `cmd` inferred as `list[Path|str|None]` because `self.codex_bin: str|None`; ensure it’s `str` and avoid `None` in list (cli.py:1150, 1180).
- `__all__` needs a type annotation (use `list[str]`) (__init__.py:1).

**Python Version Compatibility (StrEnum)**
- Uses `from enum import StrEnum` (3.11+) but project targets Python >=3.10; import will fail on 3.10. Either bump `requires-python` to >=3.11 or switch to `class TaskStatus(str, Enum)` or a backport (cli.py:48; pyproject.toml:[project].requires-python).

**Dynamic Attribute Access (forbidden)**
- Uses `getattr` to probe argparse namespace; prefer explicit attribute access or `argparse` defaults (cli.py:78). Violates “Forbid dynamic attribute access and catching AttributeError”.

**Lint (Ruff)**
- PLR0913 Too many arguments in `ClaudeAI.__init__` (6 > 5). Consider grouping into a settings object or reducing parameters (cli.py:996–1004).

**Security (Bandit)**
- subprocess use: import flagged for awareness (B404) (cli.py:42).
- Start process with partial path 'git' (B607) and general subprocess args handling (B603) in dry-run call; verify inputs are trusted from CLI passthrough (cli.py:283–289).

**Complexity & Duplication**
- High cyclomatic complexity: consider refactors
  - `async_main` CCN=36 (cli.py:747–981)
  - `CodexAI.generate` CCN=17 (cli.py:1103–1193)
  - `build_commit_template` CCN=16 (cli.py:363–441)
- Duplicate blocks (lizard):
  - cli.py:132–158 ≈ 174–197
  - cli.py:1042–1063 ≈ 1147–1168

**Scoped Try/Except**
- Broad `except Exception` outside clear boundary; scope to expected exceptions where feasible (cli.py:138, 157, 177, 196, 304, 497, 631). Boundary cases at 818, 1186 include exception objects.

**PathLike Passing (mypy)**
- `CalledProcessError` arg2 expects str/bytes/PathLike or sequence; passing `cmd: list[Path|str|None]` triggers type error. Normalize to `list[str|os.PathLike]` with no `None` (cli.py:1180).

**Missing tools**
- Ruff binary execution was sandbox-restricted; partial lint surfaced PLR0913, but full lint coverage wasn’t possible. Other tools (mypy, pyright, vulture, deptry, bandit, lizard, radon) ran successfully.
```

## mini_codex

```text
Imports inside functions (violates “Imports at the top”); move to module level unless truly justified
- llm/adgn_llm/src/adgn_llm/mini_codex/agent.py:_is_retryable (lines 22–33), _openai_client (lines 46–53), load_mcp_file (lines 85–90)
- llm/adgn_llm/src/adgn_llm/mini_codex/cli.py:_run_proc (line 87)
- llm/adgn_llm/src/adgn_llm/mini_codex/local_tools.py:_run_proc (line 26)
- llm/adgn_llm/src/adgn_llm/mini_codex/mcp_manager.py:_sanitize_name (line 101)

Pathlib required for paths and joins (violates “Use pathlib for path manipulation” and “Pass Path objects to PathLike APIs”)
- agent.load_mcp_file uses open(path) on str and manual open (agent.py:85–92)
- cli.main_async uses os.path.join/os.getcwd/os.path.exists (cli.py:340–342)
- local_tools._run_in_sandbox uses os.getcwd (local_tools.py:58)
- mcp_manager._load_mcp_config uses os.path.join/os.getcwd/os.path.exists/open (mcp_manager.py:33–36); _LiveServer.__init__ uses Path(os.getcwd()) twice (mcp_manager.py:49, 54)

Dynamic attribute probing via hasattr/getattr (violates “Forbid dynamic attribute access”)
- agent.maybe_await uses hasattr(res, "__await__") (agent.py:283–285)
- mcp_manager._collect_tools_live uses getattr on init.serverInfo fields (mcp_manager.py:118–124)
- mcp_manager._call_mcp_tool_live uses getattr/hasattr multiple times (mcp_manager.py:145, 148, 151, 155–163)
- examples.run_minicodex_docker_demo: hasattr(exec_res, "output") (examples/run_minicodex_docker_demo.py:114)

Modern typing required (use builtin generics and PEP 604 syntax) — multiple legacy typing.List/Dict/Tuple and typing.* imports
- agent.py:7 (AsyncIterator, Callable, Dict, Iterable, List, Literal, Tuple), 24 (ToolMap = Dict[...] ), 51, 60–61, 76, 80–81, 111, 123, 125–126, 141, 145, 161–165, 195, 278
- local_server.py:4 (Callable, Dict, Mapping, Tuple), 6 (ToolDef = Tuple[...]), 19 (get_tools -> Dict[...])
- local_exec_server.py:3 (Dict), 15 (get_tools -> Dict[...])
- cli.py already uses builtin generics in most places, but ruff flagged union isinstance tuple in _is_retryable (see separate item)
- mcp_manager.py:18 (Callable, Mapping, Iterable) should come from collections.abc; other type aliases OK

Prefer isinstance with union types (PEP 604) if supported; ruff flagged tuple form
- agent._is_retryable isinstance(err, (APITimeoutError, APIConnectionError, RateLimitError)) (agent.py:30)
- cli._is_retryable isinstance(err, (APITimeoutError, APIConnectionError, RateLimitError)) (cli.py:170)

Path-like open should use Path.open and remove redundant mode arg (violates pathlib usage)
- agent.load_mcp_file: with open(path, "r", …) (agent.py:86)
- mcp_manager._load_mcp_config: with open(path, "r", …) (mcp_manager.py:36)

Swallowing broad exceptions (violates “Try/except is scoped around the operation it guards” and poor error hygiene)
- agent.run: try/except Exception: pass while appending model_dump (agent.py:204–207)
- cli.responses_turn and responses_followup_with_tool_outputs: broad except Exception around instruction_block (cli.py:203–204, 289–290)
- examples.run_minicodex_docker_demo: multiple try/except Exception: pass blocks (examples/run_minicodex_docker_demo.py:45–49, 120–127)

Use walrus for trivial compute-then-check guards (violates “Use walrus for trivial immediate conditions”)
- agent.run: extra = self._mcp.instruction_block(); if extra: ... (agent.py:172–181)
- cli.responses_turn: extra = mcp_manager.instruction_block(); if extra: ... (cli.py:200–203)
- cli.responses_followup_with_tool_outputs: same pattern (cli.py:286–290)

Undefined name/type in annotations (type correctness)
- cli.responses_turn/mcp_manager parameter uses McpManager without import (cli.py:189, 281)

Union misuse: code assumes AgentResult, but type is AgentResult | AsyncIterator (type correctness)
- cli.main_async uses result.sequence/result.text directly (cli.py:358–369)

Mypy/pyright import resolution/type issues (environment/type stubs or missing deps)
- openai, openai.types.responses, tenacity, pydantic unresolved (agent.py:9–16; cli.py:11–19)
- mcp/mcp.client.stdio unresolved; unknown import symbols ClientSession/StdioServerParameters (mcp_manager.py:20–21)
- examples: docker stubs missing (examples/run_minicodex_docker_demo.py:26)
- mcp_manager._call_mcp_tool_live: variable “parts” redefined in same scope (mcp_manager.py:149 and 159)

Dead code / unused symbols (violates “No dead code”)
- agent.py: unused import field (line 5); class ToolRun appears unused (lines 57–63)
- vulture suspects: agent.metrics fields flagged as unused; verify usage or suppress carefully (agent.py:63, 68–70, 77)
- agent.py: in Agent.close, dataclass field names tool_calls/turns flagged (agent.py:251, 254)
- cli.py: MAX_CYCLES constant unused (cli.py:39); run_in_sandbox unused (cli.py:110)
- local_exec_server.py: attribute invocations unused outside increment (local_exec_server.py:13, 17)
- local_tools.py: build_local_tools unused (local_tools.py:127)
- mcp_manager.py: McpManager.from_config is not referenced within scope (mcp_manager.py:184)

Security findings (Bandit)
- Try/except/pass pattern (low severity; hide failures) — agent.py:206–207; examples/run_minicodex_docker_demo.py:45–49, 120–123, 124–127
- Hardcoded tmp directory in sandbox binds/sets HOME=/tmp (medium severity; B108) — local_tools.py:82–85
- Use of assert in runtime logic (low severity; B101) — mcp_manager.py:113, 267

Path handling with os.getcwd()/os.path.* instead of Path API (violates domain types and pathlib usage)
- cli.py: cwd_val/cfg_path exists check (cli.py:122, 340–342)
- local_tools.py: cwd_val (local_tools.py:58)
- mcp_manager.py: path resolution and fallback log_dir (mcp_manager.py:33–36, 49, 54)

API/status handling: broad BaseException then attribute access (type correctness and robustness)
- agent._is_retryable / cli._is_retryable use isinstance guards but rely on err.status_code; ensure APIStatusError is properly imported/typed to avoid attribute access issues (agent.py:31–33; cli.py:171–175)

Ruff style findings (selected; many similar)
- Import sorting/formatting (I001) — agent.py:1, 29; cli.py:1; examples/run_minicodex_docker_demo.py:20; local_exec_server.py:1; mcp_manager.py:15
- Trailing comma missing in multi-line literals/calls — agent.py:247; local_exec_server.py:25; local_tools.py:135–136; mcp_manager.py:71, 125, 137; examples/run_minicodex_docker_demo.py:67, 90
- Prefer collections.abc for Callable/Iterable/Mapping — agent.py:7; local_server.py:4; mcp_manager.py:18
- Prefer dict/list/tuple builtins in annotations — widespread in agent.py/local_server.py/local_exec_server.py

Radon complexity “D” (consider refactor for readability/maintainability)
- agent.Agent.run (agent.py:148) — D (23)
- cli.responses_turn (cli.py:188) — C (20)
- cli.responses_followup_with_tool_outputs (cli.py:277) — D (21)
- examples.run_demo (examples/run_minicodex_docker_demo.py:41) — D (21)

Dependency hygiene (Deptry)
- Missing declared dependencies: openai, tenacity, pydantic, mcp, docker (agent.py:9–16, 29; cli.py:11–19; mcp_manager.py:20–21; examples/run_minicodex_docker_demo.py:26)
- Transitive import used directly: adgn_llm subpackages imported as if top-level dependency (cli.py:20–21; examples/run_minicodex_docker_demo.py:28, 36)

Domain types and units — Path and time
- File path parameters/locals are plain str rather than Path (agent.load_mcp_file path: str; mcp_manager._load_mcp_config path: str | None) — consider Path types (agent.py:84; mcp_manager.py:27)

Missing tools
- lizard/jscpd unavailable; duplicate-code detection limited. Radon complexity results provided; ruff/mypy/pyright/vulture/deptry/bandit ran successfully without caches.
```

## docker_exec

```text
- Imports unsorted/unformatted; group and sort consistently (llm/adgn_llm/src/adgn_llm/mcp/docker_exec/server.py:32–47).
- Prefer modern typing: use builtin generics and collections.abc; replace `List/Dict/Tuple/Optional/Iterator` (server.py:41, 73, 79, 85, 91–92, 105–111, 132).
- Avoid alias import for `mcp.types`; use `from mcp import types` (server.py:46).
- Import inside function without justified exception; move to top (imports at the top) (server.py:254 in `_run_stdio`).
- Too many parameters (7) in `_docker_exec`; consider grouping args into a dataclass or config (server.py:103–112, function `_docker_exec`).
- Unused variable `container` assigned and never used; remove assignment or use it (server.py:117–121, `_docker_exec`).
- Missing trailing commas per formatter/linter in multi-line constructs (server.py:91, 242).
- Use of `global` to mutate `_DOCKER_CLIENT`, `_CONTAINER_REF`, `_DEFAULT_TIMEOUT` is discouraged; prefer encapsulation or a singleton holder (server.py:61, function `_init_docker`).
- Use of `assert` in non-test code; assertions can be stripped with optimization (server.py:114–115).
- Potential command injection risk path: allowing `shell=True` leads to `sh -lc "<joined cmd>"` execution; validate inputs rigorously even though `shlex.join` is used (server.py:127, 242).
- Pyright: type mismatch passing `user: str | None` to API expecting `str`; handle None explicitly (server.py:143, `_docker_exec`).
- Pyright/mypy: missing imports/stubs prevent full type checking for external libs (`docker`, `mcp.*`) (server.py:43–47, 254).
- Redundant boolean condition can be simplified: `if shell and not isinstance(prepared_cmd, list):` (server.py:129–133).
- Declared iterator type conflicts with runtime handling: `_iter_stream_demux` annotates `Iterator[tuple[bytes|None, bytes|None]]` but `reader()` handles non-tuple items; either fix annotation or remove unreachable branch (server.py:85–87, 153–161).
- Empty try/finally and empty timed-out branch add noise; remove no-op `finally: pass` and `if timed_out: pass` (server.py:151–164, 181–183).
- Durations/timestamps use raw floats; prefer `datetime.timedelta` and aware datetimes internally (time.md). Offenders: `_DEFAULT_TIMEOUT` float, `timeout_secs` floats, `deadline = monotonic() + float(effective_timeout)` (server.py:55, 91, 111, 123, 169–178).
- Self-describing names: `_DEFAULT_TIMEOUT` lacks unit suffix; rename to `_DEFAULT_TIMEOUT_SECS` if keeping primitives (server.py:55).
- Cyclomatic complexity: `_docker_exec` rated C (17); consider extracting helpers for stream read/join/inspect to reduce complexity (server.py:103–199, radon).

Missing tools/stubs
- mypy/pyright lacked stubs or modules for `docker` and `mcp.*`, limiting type-check depth; consider adding typeshed stubs (e.g., `types-docker`) or configuring imports. Deptry couldn’t be reliably scoped to a single file, so its broader project findings were excluded.```

## sandboxed_jupyter_mcp

```text
Resolved scope: static set of files under llm/adgn_llm/src/adgn_llm/mcp/sandboxed_jupyter_mcp/**/*.py. Analyzed only those files.

Type checker and packaging findings
- Missing stubs/imports (mypy/pyright): yaml and pydantic not resolved; add dependencies or types (jupyter_sandbox_compose.py:12–13; wrapper.py:19–20)
- Python version mismatch: uses datetime.UTC (Py 3.11+) but project targets >=3.10; breaks type checking/runtime on 3.10 (kernel_bootstrap.py:7; kernel_shim.py:6)
- Missing dependency declarations (deptry): PyYAML (yaml), pydantic, ipykernel not declared; adgn_llm flagged as transitive import (jupyter_sandbox_compose.py:12–14; kernel_bootstrap.py:49; wrapper.py:19–21)

Dead code / unused symbols
- Unused imports and symbols (vulture): wrapper.py: asyncio(4), dataclass(14), Any(17), model_validator(20); unused class PolicyConfig and nested ‘extra’ (26–28). jupyter_sandbox_compose.py: os(6), subprocess(7)

Security (bandit)
- Subprocess use; ensure inputs are trusted (imports): jupyter_mcp_launch.py:10; jupyter_sandbox_compose.py:7; wrapper.py:11
- Subprocess execution (no shell, but still review args’ provenance): jupyter_mcp_launch.py:68, 173; wrapper.py:151, 255, 324, 416
- Broad try/except pass swallowing errors: jupyter_mcp_launch.py:178–183; jupyter_sandbox_compose.py:104, 119; kernel_bootstrap.py:19–20, 26–27, 41–43; kernel_shim.py:16, 31; kernel_exec.py:11–12
- Hardcoded tmp dir path: wrapper.py:121
- “Hardcoded password” heuristic: token default string “auto” flagged (likely benign) (jupyter_mcp_launch.py:129)

Complexity (radon)
- High cognitive complexity; consider refactor:
  - wrapper._seatbelt — D (23) (wrapper.py:function _seatbelt)
  - jupyter_mcp_launch.main — C (16) (jupyter_mcp_launch.py:function main)
  - jupyter_sandbox_compose._ensure_policy_minimums — C (19) (jupyter_sandbox_compose.py:function _ensure_policy_minimums)

Property violations

Modern type hints (builtin generics, PEP 604 unions)
- Uses typing.Optional instead of | None (prefer Path | None):
  - jupyter_mcp_launch.py:14, 23–31 (parameter log_dir: Optional[Path])
  - jupyter_sandbox_compose.py:10, 47–52 (parameter extra_py: Optional[str])

Time and duration use rich time types
- Float seconds used in readiness loops (prefer datetime/timedelta):
  - jupyter_mcp_launch.py:70–77 (deadline = time.time() + 12; sleep(0.25))
  - wrapper.py:257–264 (deadline = time.time() + 10; sleep(0.25))

URLs are built with standard libraries
- Manual f-string assembly instead of urllib.parse:
  - jupyter_mcp_launch.py:157, 163 (http://127.0.0.1:{port})
  - wrapper.py:391, 397 (http://127.0.0.1:{jupyter_port})

PathLike (pass Path objects; no str())
- Unnecessary str() for subprocess args (accepts PathLike):
  - jupyter_mcp_launch.py:47, 57 (cmd list entries str(workspace), str(config_path))
  - wrapper.py:231, 243 (cmd list entries str(workspace), str(run_root/…/jupyter_server_config.py))
- Unnecessary str() for os.open (accepts PathLike):
  - kernel_exec.py:44 (os.open(str(log_path), …))

Pydantic v2 only (no v1 config/shims)
- v1-style Config used (keep only v2 idioms); legacy or not used but still in prod module:
  - wrapper.py:26–28 (class PolicyConfig: class Config: extra = "forbid")

Scoped try/except (keep minimal and specific)
- Broad except Exception with pass/logless swallowing (narrow exceptions and scope):
  - jupyter_mcp_launch.py:176–183
  - jupyter_sandbox_compose.py:89–121 (multiple broad catches around path resolution)
  - kernel_bootstrap.py:15–21, 24–28, 36–43
  - kernel_shim.py:11–16, 21–33
  - kernel_exec.py:8–12

Type correctness and specificity
- DEVNULL assigned to file-handle variables requires type: ignore; prefer consistent typing (TextIO | int) or branch variable types (jupyter_mcp_launch.py:65–66)

Additional robustness observations
- Silent fallbacks in _ensure_policy_minimums may hide path-computation errors (IndexError on parents[1], resolve(), etc.), leading to incomplete policy with no diagnostics; narrow exception handling and log context (jupyter_sandbox_compose.py:89–121)

Missing tools
- Unavailable during run: ruff, lizard. This limited lint (style/pycodestyle/pyflakes) and duplicate-code detection; issues above rely on mypy/pyright, vulture, deptry, bandit, radon.
```
