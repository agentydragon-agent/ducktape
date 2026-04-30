# 2026-04-29 SWE-bench Verified N=100 (shuffled) on gpt-oss:20b

> **Status:** in-progress.

Replacement for the earlier N=100 attempt at
<../2026-04-29_swebench_n100_gpt20/> which was started before we
noticed the `--sample-shuffle` flag was missing. The earlier run
loaded samples in alpha-by-repo order, so the first 90 (it stopped
at 90/100) were 22× `astropy` + 68× `django` — not a representative
cross-section of Verified's 12+ repos.

This run uses `--sample-shuffle 42` so the 100 sampled problems are
drawn at random from the 500 in Verified.

## What runs

- `run_swebench.py` points at the local `swebench_react_task.py@swe_bench_react`
  wrapper (not the canonical `inspect_evals/swe_bench`), which swaps the
  default `bash_session` solver for `swe_bench_react_agent` (stateless
  `bash` + `python` + `think`). `gpt-oss:20b` was getting confused by
  `bash_session`'s `type` / `type_submit` semantics in the previous
  attempt — issuing `action: "type"` without a follow-up submit, leaving
  the shell waiting on input.
- Flags: `--sample-shuffle 42`, `--display plain`,
  `INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE=1 GiB`, `--limit 100`,
  `--message-limit 1000`, `--max-connections 2`.

## Why we expect a different headline

The partial unshuffled run gave **0.122** (11/90), heavily
django-weighted (django 15%, astropy 5%). At N=100 spread across all
~12 Verified repos, the aggregate could land lower (if django was an
outlier for this model) or higher (unlikely; published 20B-class
baselines are 5–15%). Stderr at N=100 is ~0.03.

## Estimated cost

- **Wall:** ~3.5 h, based on the partial run's ~28 samples/h throughput.
- **Disk:** the shuffled set will pull ~30+ new images we haven't seen
  before (sympy, scikit-learn, sphinx, matplotlib, pylint, requests,
  pytest, …); start with ~120 GB free, expect ~30–50 GB of net pulls.
- **Tokens:** ~50 M input + ~400 K completion (per pilot extrapolation).

## Caveats / risks

- **Same Inspect bug exposure** as the pilot (CircularByteBuffer in
  `bash_session`'s docker-exec wire — see <upstream_issue.md>). The
  react agent uses `bash` (one-shot exec, no persistent TTY), so the
  1 GiB cap is mostly insurance now; the long-running wire reads that
  triggered the bug aren't on this code path.
- **Disk pressure.** New repos = new image base layers. Watch `df` and
  prune if needed; the hourly monitor will alert.
- **No effort sweep.** SWE-bench's solver doesn't propagate
  `--reasoning-effort` to the underlying generate calls; model uses
  its default.

## Reproducing

```bash
cd cluster/docs/inference/runs/2026-04-29_swebench_n100_shuffled_gpt20
./run_swebench.py
```

## Results

TBD.
