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

### What broke

**Inspect's JSON-RPC tool stdio framing**, not the model. After ~673
tool calls into the agent loop, `parse_json_rpc_response` got a
truncated payload:

```text
ValidationError: 1 validation error for JSONRPCResponse
  Invalid JSON: expected value at line 1 column 1 [type=json_invalid,
   input_value='rmal/cooling_device13/de... loop\\n", "id": 673}\n', …]
```

The fragment starts mid-string (`rmal/cooling_device13/...`) and ends
with the JSON-RPC envelope tail (`"id": 673}\n`). So Inspect read
_part of_ response 673 — the prefix was lost or chunked into a
previous read. Looks like a Content-Length-based framing
desynchronization in the tool-stdio bridge, not a model output issue.

The bash command that triggered it appears to have been listing
something under `/sys/class/thermal/cooling_device*/` (paths leaked
into the truncated payload). The agent likely ran a wide `find` or
recursive `ls` that produced a long output and tickled the framing
bug.

`Task interrupted (no samples completed before interruption)` —
Inspect aborts the entire run on the first JSON-RPC parse failure
rather than retrying or skipping the sample.

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
