# 2026-04-29 SWE-bench Verified N=100 on gpt-oss:20b

> **Status:** in-progress / scaffolded.

Capability run after the N=1 pilot at
<../2026-04-29_swebench_pilot_gpt20/> proved the plumbing works (with
the `INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE=1 GiB` workaround for
inspect_ai's `CircularByteBuffer` corruption bug).

## Goal

Establish a real `gpt-oss:20b` baseline on SWE-bench Verified. One
sample at 0.0 isn't a signal; N=100 with stderr ~0.03 (assuming
~5–10% pass@1) gives us a number to cite.

## What runs

- Same `run_swebench.py` as the pilot, just with `DEFAULT_LIMIT = 100`.
- Workaround knob `INSPECT_SANDBOX_MAX_EXEC_OUTPUT_SIZE=1 GiB` baked
  in via `env.setdefault`.
- Same `--message-limit 50`, `--max-connections 2`.

## Estimated cost

| Resource | Estimate                         | Notes                                               |
| -------- | -------------------------------- | --------------------------------------------------- |
| Wall     | 6–10 hours                       | Pilot took 6 min/sample; some will be slower        |
| Disk     | ~30–60 GB (effective)            | 100 docker images, heavy layer sharing within repos |
| Tokens   | ~50 M prompt + ~400 K completion | 100 × pilot's 521 K tokens                          |

The pilot at N=1 used 521 K tokens (517 K input, 3 773 output). At
N=100 expect ~52 M total — well within Ollama's no-billing context.

## Caveats / risks

- **Disk pressure.** 159 GB free at start; 100 SWE-bench images at
  ~2 GB shown size but layer-shared on disk. Watch `docker system df`
  during the run; abort if it gets tight (`<20 GB free`).
- **Sample interrupt cascading.** If one sample hits the same
  CircularByteBuffer bug despite the 1 GiB cap (long agent run, lots
  of stderr accumulation), Inspect aborts the entire run with
  `Task interrupted`. The 1 GiB workaround likely holds for most
  samples but isn't guaranteed.
- **`OLLAMA_NUM_PARALLEL=1` in the deployment** caps real concurrency
  regardless of `--max-connections`. Effective parallelism ~1.5–2×.
- **Score expectation:** 0–10% pass@1 for `gpt-oss:20b`. Anything
  notably higher would be surprising.

## Reproducing

```bash
cd cluster/docs/inference/runs/2026-04-29_swebench_n100_gpt20
./run_swebench.py                      # full N=100, ~6–10 h wall
./run_swebench.py --limit 20           # cheaper partial repro
```

Same prereqs as the pilot: `kubectl`, `gh` (logged in), `uv`,
**Docker on the host** with ~60 GB free.

## Results

TBD.
