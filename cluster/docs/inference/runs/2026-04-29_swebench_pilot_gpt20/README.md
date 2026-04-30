# 2026-04-29 SWE-bench Verified pilot (N=1) on gpt-oss:20b

> **Status:** partial — agent loop ran but crashed mid-trajectory on
> Inspect-side JSON-RPC framing. **0 samples scored.** Switched from
> Lite to Verified mid-pilot because the task pins a Verified-specific
> revision SHA that doesn't exist on Lite (see "Pre-pilot fixes" below).

One-problem smoke pilot of `inspect_evals/swe_bench` against the
cluster Ollama deployment. The point is **not** to score the model on
SWE-bench — it's to verify the agent loop works end-to-end on
`gpt-oss:20b` over Ollama's OpenAI-compat tool-call surface, before
committing several hours to a real SWE-bench run.

Expansion plan: if the pilot succeeds (model emits valid tool calls,
the agent loop terminates, the scorer runs) → run N=20–50 on SWE-bench
Lite as the actual measurement. If the pilot fails (tool calls
malformed, infinite loops, sandbox issues) → diagnose and revisit.

## Why a pilot before a full run

SWE-bench is structurally heavier than HumanEval/AIME:

- **Per-problem Docker images** pulled on demand from
  `ghcr.io/epoch-research/swe-bench.eval.<arch>.<id>:latest`. Each is
  ~0.5–2 GB. Authentication via `gh auth token | docker login ghcr.io`
  (handled by the run script).
- **Agentic, multi-turn loop.** Default solver is
  `swe_bench_agent_with_inspect_tool_support` — a custom ReAct agent
  with `bash_session`, `python`, and `text_editor` tools. ~10–50 turns
  per problem typical.
- **Tool-call reliability dependency.** The agent needs the model to
  consistently emit valid OpenAI-shaped `tool_calls` chunks via
  Ollama's compat shim. `gpt-oss:20b` advertises tool-call support but
  we haven't exercised it under sustained pressure. A 1-problem pilot
  catches `tool_calls`-related failures before a long run wastes
  hours.
- **`reasoning_effort` does NOT pass through** the SWE-bench task to
  generate calls (verified from inspect_evals source). So no effort
  sweep here — model uses its default behavior.

Total run time at full N would be hours per problem × N. At N=1 with a
50-message ceiling: **~15–45 min** wall.

## What ran

- **Driver**: <run_swebench.py>
  (`inspect_evals/swe_bench`, `--limit 1`, `--message-limit 50`,
  `--sandbox docker`, dataset = `princeton-nlp/SWE-bench_Lite`).
- **Inspect log**: <eval_logs/\*.eval>.
- **Stdout transcript**: <raw_output.txt>.
- **Summary JSON**: <summary.json>.
- **Endpoint**: `https://ollama.allegedly.works/v1` with bearer token.
- **GHCR auth**: `gh auth token | docker login ghcr.io -u agentydragon`
  (script does this automatically; pre-existing login also works).

### Configuration

| Knob               | Value                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------- |
| Model              | `gpt-oss:20b` via `https://ollama.allegedly.works/v1` (bearer-token auth)                   |
| Eval               | `inspect_evals/swe_bench`, dataset `princeton-nlp/SWE-bench_Lite` (~300 problems available) |
| Limit              | 1 (pilot)                                                                                   |
| Message limit      | 50 (per-problem cap on agent turns)                                                         |
| Sandbox            | `docker` (per-problem image from `ghcr.io/epoch-research/...`)                              |
| Tool timeout       | 210 s (Inspect default for swe_bench task)                                                  |
| `reasoning_effort` | not applicable (does not flow through agent loop)                                           |

## Pilot success criteria

The pilot is "successful" if **all** of these hold:

1. ghcr.io login succeeds and the per-problem image pulls without
   error.
2. Inspect launches the agent loop. Logs show at least one
   well-formed `tool_calls` chunk from the model (`bash_session`,
   `python`, or `text_editor`).
3. The agent loop terminates — either by submitting a patch or by
   hitting the 50-message limit. (Either is a pass for the pilot;
   we're testing plumbing, not capability.)
4. The scorer runs without erroring (passes/fails are both fine).

If any of those don't hold, capture the failure mode in
"## Findings" and don't expand to a larger N until fixed.

## Pre-pilot fixes (caught during scaffolding)

Two stand-alone errors before the agent ever ran. Both fixed in the
committed `run_swebench.py`; documenting because they'd hit anyone
else trying to drive `inspect_evals/swe_bench`:

1. **Missing optional dep.** `inspect_evals.swe_bench` imports
   `swebench` at task-construction time:
   `AssertionError: To run SWE-bench, please install the optional
SWE-bench dependency` — fixed by adding `inspect-evals[swe_bench]`
   and `swebench` to the uv hashbang script's dependency list.
2. **Default `revision` SHA is Verified-specific.** Setting
   `-T dataset=princeton-nlp/SWE-bench_Lite` without overriding
   revision throws
   `DatasetNotFoundError: Revision 'c104f840…' doesn't exist for
dataset 'princeton-nlp/SWE-bench_Lite'`. The task pins a SHA that
   only exists in the Verified repo. Fixed by swapping the pilot
   default to `verified`; the script now also auto-clears revision to
   `main` when overriding to Lite.

## Findings

### Healthy plumbing observed

1. **ghcr.io auth via `gh auth token`** worked end-to-end. Docker
   could pull the per-problem image without further config.
2. **Inspect sandbox lifecycle** — `docker compose up` for the chosen
   problem `astropy__astropy-12907` started cleanly and the agent
   exec'd into it.
3. **Tool-call surface works on `gpt-oss:20b` over Ollama OpenAI-
   compat.** The agent emitted hundreds of well-formed tool calls
   before the failure (the JSON-RPC `id` was 673 at crash time).

### What broke (forensic walkthrough)

The eval log (`inspect log dump …eval`) lets us reconstruct exactly
what happened. The crash isn't generic; it traces to one specific
command the model ran early in the trajectory.

**The agent's command sequence**, each `bash_session(action=type_submit)`:

| msg | command                                                         | result size                  |
| --- | --------------------------------------------------------------- | ---------------------------- |
| 2   | `ls -R . \| head -200`                                          | 2 750 chars                  |
| 4   | `grep -R "def separability_matrix" -n .. \| head`               | 79 chars (heavily truncated) |
| 6   | `grep -R "separability_matrix" -n astropy \| head`              | 16 523 chars (Inspect cap)   |
| 8   | `grep -n "separability_matrix" -R astropy/modeling \| head`     | 16 523 chars (Inspect cap)   |
| 10  | `grep -R "def separability_matrix" -n astropy/modeling \| head` | 16 523 chars (Inspect cap)   |
| 12  | `ls -R astropy/modeling/separable \| head`                      | 16 523 chars (Inspect cap)   |
| 14  | `find astropy/modeling -maxdepth 2 … \| grep -i separable`      | (never returned — crashed)   |

**Root cause: command 4 escaped the working directory with `..`.**
From `/testbed`, `..` is the container's `/` — the container's own
root, not the host's; the docker namespace does isolate that. But
docker's default mounts include a real `sysfs` at `/sys` inside the
container, and **sysfs has kernel-imposed symlink cycles** regardless
of which namespace you're in: `/sys/class/thermal/cooling_device*/`
points at `/sys/devices/LNXSYSTM:00/…/cooling_device13`, which has
`subsystem` and `device` and `physical_node` links that loop back
through the bus/class hierarchy. These cycles are in every sysfs
mount on every Linux container with default mount config.

The first result line Inspect showed was
`grep: ../sys/kernel/mm/hugepages/hugepages-1048576kB/demote: Permission denied`
— grep walking the container's `/sys`. Subsequent output flooded with
"Too many levels of symbolic links" errors as `grep -r` followed
those cycles.

`head` cut the displayed output, but the bash session is interactive
and the underlying `grep` process kept running and buffering stderr
into the persistent shell. The subsequent commands (6 through 12) all
came back at exactly Inspect's max-output cap (16 523 chars), which is
not a coincidence — the bash session's stdout was saturated with
ongoing leakage from command 4's runaway `grep`.

By message 14, the agent's 7th tool call accumulated enough buffered
content in the bash-tool-server's wire response that the JSON-RPC
envelope exceeded what Inspect's stdio reader could parse correctly.
The pydantic validator got just the tail:

```text
input_value='rmal/cooling_device13/de... loop\\n", "id": 673}\n'
```

The fragment starts mid-string in a `/sys/.../thermal/cooling_device13/…`
path, contains the `loop\n` ending of "Too many levels of symbolic
links", and closes with the JSON-RPC envelope (`, "id": 673}\n`). The
prefix of the JSON message — including the `{"jsonrpc": "2.0",
"result": "…` opener — never made it to the parser. That's a
Content-Length-style framing desync, not a model error.

**`id: 673` is the JSON-RPC sequence number**, not the tool-call
number. The id generator starts at 666 (`_util/_json_rpc.py:369`:
`id_generator = count(666)`), so `id: 673` is just the **8th RPC of
the entire eval session** — directly mapping to the agent's 7th tool
call. One large response, not 673 small ones.

### The exact corruption path (Inspect source dive)

`/home/agentydragon/.cache/uv/environments-v2/run-swebench-fba1694160db4bb3/lib/python3.12/site-packages/inspect_ai/`:

1. Model issues `bash_session(action=type_submit, input="find …")`.
2. `tool/_tools/_bash_session.py:230` calls
   `exec_scalar_request(method="bash_session", …)`.
3. `_util/_json_rpc.py:exec_scalar_request` →`_exec_request` →
   `transport(method, params, …)`.
4. Transport is `util/_sandbox/_json_rpc_transport.py:SandboxJSONRPCTransport.__call__`,
   which calls `self.sandbox.exec([SANDBOX_CLI, "exec"], input=…)`
   inside the docker container.
5. The bash-tool MCP server returns the **full terminal-buffer state**
   as the `result` field of a JSON-RPC envelope. After ~5 tool calls
   of accumulated `grep` stderr from `/sys` symlink cycles, that
   buffer is >10 MiB.
6. `util/_sandbox/exec_remote.py:606` allocates
   `stdout_buffer = CircularByteBuffer(MAX_EXEC_OUTPUT_SIZE)` to
   capture stdout. Default `MAX_EXEC_OUTPUT_SIZE = 10 * 1024**2 =
10 MiB` (`util/_sandbox/limits.py:5`).
7. `CircularByteBuffer.write`
   (`util/_subprocess.py:308–316`) **discards from the front of the
   buffer** when total bytes exceed the limit:

   ```python
   while self._total_bytes > self._max_bytes and len(self._chunks) > 1:
       removed = self._chunks.popleft()
       self._total_bytes -= len(removed)
   if self._total_bytes > self._max_bytes and self._chunks:
       excess = self._total_bytes - self._max_bytes
       self._chunks[0] = self._chunks[0][excess:]
   ```

   So the buffer's `getvalue()` returns the **last 10 MiB** of the
   JSON-RPC response — chopping off the `{"jsonrpc":"2.0","result":"`
   opener.

8. Transport returns this corrupted string to `_exec_request`.
9. `_util/_json_rpc.py:parse_json_rpc_response` calls
   `JSONRPCResponse.model_validate_json(response_str)`. Pydantic
   fails at line 1 column 1 because the buffer now starts mid-string
   (`rmal/cooling_device13/de…`).
10. `ValidationError` propagates → sample errored → entire eval aborts.

**This is unambiguously a bug in `inspect_ai`.** A circular byte
buffer is not safe to apply to structured wire data — silently
discarding the prefix of a JSON-RPC envelope corrupts it. Two
sensible upstream fixes:

- Bound `bash_session`'s response **at the application layer** (cap
  the terminal state inside the JSON `result` field) so the wire
  envelope stays small, regardless of `MAX_EXEC_OUTPUT_SIZE`.
- Make `CircularByteBuffer` for sandbox `exec` **raise on overflow**
  rather than silently corrupting; or at minimum, surface a
  `truncated_output` error like `util/_sandbox/limits.py:108` already
  knows how to do for other limits.

### Workaround knob

Inspect exposes `INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE` as an env var
(parsed in `util/_sandbox/limits.py:87`). Bumping it to e.g. 1 GiB
would let larger responses through:

```bash
INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE=$((1024 * 1024 * 1024)) ./run_swebench.py
```

But this just delays the failure — a long enough agent run with one
runaway-stderr command will still saturate. **It's a workaround, not
a fix.** The model already runs `head` to bound stdout; covering
stderr requires a tooling-side bound, not a knob the model can
reliably hit.

`Task interrupted (no samples completed before interruption)` —
Inspect aborts the entire run on the first JSON-RPC parse failure
rather than retrying or skipping the sample.

### Lessons for an actual SWE-bench run later

1. **The bash tool isn't scoped to `/testbed`.** Docker isolates the
   container from the host fine — the container has its own root —
   but inside the container, `/sys` is a real sysfs mount with
   kernel-imposed symlink cycles, so `grep -R … ..` from `/testbed`
   walks them and triggers the saturation. Mitigation options:
   chroot/cwd-pin the bash tool so `..` can't escape `/testbed`, mount
   `/sys` and `/proc` as `tmpfs` empties in the SWE-bench task's
   compose template, or in the agent prompt explicitly forbid walking
   above the working dir.
2. **Inspect's `CircularByteBuffer` should not be applied to JSON-RPC
   wire data.** See "The exact corruption path" above —
   `MAX_EXEC_OUTPUT_SIZE = 10 MiB` and the buffer drops bytes from the
   front. That's safe for displayed bash output but corrupts JSON-RPC
   envelopes silently. File upstream against `UKGovernmentBEIS/inspect_ai`.
3. **`message_limit=50` was never the binding constraint** — the
   crash hit at 7 assistant messages. The framing bug fires well
   below any sensible step budget.

### Pilot success criteria — partial pass

- ✅ ghcr.io auth + image pull worked.
- ✅ Inspect launched the agent loop with a real problem.
- ✅ Model emitted valid tool calls (~673 of them).
- ❌ Loop didn't terminate cleanly — Inspect's plumbing crashed mid-
  trajectory.
- ❌ Scorer never ran (no completed samples).

The loop **does** work for `gpt-oss:20b` for many turns; we can't yet
get a clean end-to-end SWE-bench score on this stack.

## Next steps (deferred)

Not pursuing further on this branch — SWE-bench-on-Ollama for `gpt-
oss:20b` is blocked on the Inspect-side framing issue, and chasing
that is a yak-shave for the broader inference-evaluation goal.

If we revisit:

1. **Reproduce on a smaller problem** with shorter command outputs to
   confirm whether long stdio buffers are the trigger.
2. **File upstream issue** at github.com/UKGovernmentBEIS/inspect_ai
   if the framing bug reproduces consistently.
3. **Try with `tool_timeout` lowered** to force the agent to run more
   smaller commands rather than one big find — workaround, not a fix.
4. **Try Verified-mini** (`swe_bench_verified_mini` task name) for a
   smaller, possibly-more-stable subset.

For now, **moving on to BigCodeBench** (TODO P1#3) — non-agentic
coding eval, doesn't depend on Inspect's tool-stdio plumbing, will
discriminate `gpt-oss:20b` from alternatives without saturation.

## Reproducing

```bash
cd cluster/docs/inference/runs/2026-04-29_swebench_pilot_gpt20
./run_swebench.py                      # default: lite, N=1, 50-msg limit
./run_swebench.py --limit 5            # small-N expansion
./run_swebench.py --dataset verified   # switch to Verified dataset
```

Requires: `kubectl`, `gh` (logged in), `uv`, **Docker on the host**.
Driven from any host that can reach `ollama.allegedly.works/v1` over
HTTPS and pull from `ghcr.io`.

## Caveats

- **No effort sweep.** The standard Inspect `--reasoning-effort` flag
  doesn't propagate into SWE-bench's generate calls. If we want to
  test effort effects on agentic coding, that's a code change in
  inspect_evals (or a custom solver wrapper).
- **First-run image pull.** Each new SWE-bench problem ID pulls a new
  Docker image. At N=1 only one image; at N=20–50 expect ~10–100 GB
  of pulls.
- **Realistic score expectation:** very low (single-digit %). Strong
  frontier models score ~25–50% on Lite/Verified; 20B models without
  scaffolding tend to land in 0–10% range. For ranking we'd need a
  much larger model or proper agent scaffolding; for "does the loop
  work at all" the pilot is enough.
- **Concurrent runs share the Ollama endpoint.** `OLLAMA_NUM_PARALLEL=1`
  in the deployment means parallel SWE-bench problems serialize at
  the model. `--max-workers 2` is the default in the script; raising
  it doesn't help past the bottleneck.
