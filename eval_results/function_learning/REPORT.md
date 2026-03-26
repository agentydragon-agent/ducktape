# Function Learning Eval Report — Haiku 4.5

**Date:** 2026-03-26
**Model:** `claude-haiku-4-5-20251001`
**Skill:** noskill (baseline)
**Turn limit:** 12
**Functions:** 8→4 bits (256 possible inputs, 1024 total output bits)

## Results Summary

| Variant       | Total Hamming Loss | Final Turn Loss | Solved?      | Run Time |
| ------------- | ------------------ | --------------- | ------------ | -------- |
| parity_groups | 2,326              | 0               | Yes (turn 7) | ~73s     |
| junta_3       | 5,847              | 480             | No           | ~70s     |
| linear_simple | 6,202              | 522             | No           | ~79s     |

**Max possible loss per turn:** 1,024 (256 inputs x 4 output bits)
**Random baseline per turn:** ~512 (expected Hamming distance of random 4-bit strings)

## Per-Turn Loss Curves

### parity_groups (SOLVED)

```
Turn  1: loss=522  query=00000000  (baseline guess)
Turn  2: loss=520  query=11111111
Turn  3: loss=512  query=10000000  (started probing single bits)
Turn  4: loss=388  query=01000000  (discovered first pair)
Turn  5: loss=256  query=00100000  (discovered second pair)
Turn  6: loss=128  query=00010000  (discovered third pair)
Turn  7: loss=  0  query=00001000  (fully solved — all 4 pairs found)
Turn  8: loss=  0  (verification queries, perfect program maintained)
...
Turn 12: loss=  0
```

Haiku correctly identified the XOR-pair structure by querying standard basis vectors and observing which pairs produce the same output. By turn 7 it had a perfect program.

### linear_simple (NOT SOLVED)

```
Turn  1: loss=561  query=00000000  (gets bias vector b)
Turn  2: loss=515  query=11111111
Turn  3: loss=506  query=10000000  (standard basis — correct strategy!)
...
Turn 10: loss=512  query=00000001  (queried all 8 basis vectors + zero)
Turn 11: loss=512  query=11110000
Turn 12: loss=522  query=10101010
```

Haiku **used the optimal query strategy** (zero vector + 8 standard basis vectors in turns 1-10), which gives it all the information needed to reconstruct the matrix A and bias b. However, it **failed to synthesize a correct program** from the query results. The loss stayed at ~512 (random baseline) throughout — the model never translated its observations into a working GF(2) matrix multiply program.

### junta_3 (NOT SOLVED)

```
Turn  1: loss=552  query=00000000
Turn  2: loss=480  query=11111111
Turn  3: loss=480  query=10000000  (probing individual bits)
...
Turn 10: loss=487  query=00000001
Turn 11: loss=480  query=11111110
Turn 12: loss=480  query=10101010
```

Similar to linear_simple — Haiku queried systematically but couldn't turn the observations into a working program. Loss plateaued at ~480 (slightly below random baseline of 512, suggesting partial learning).

## Timing

**Per-input evaluation:** ~500ms avg, ~1.0-1.6s max (Docker exec overhead dominates)
**Per-turn scoring (256 inputs, 32-way parallel):** ~4.1s avg
**Total run time per variant:** ~70-80s (12 turns x ~4s scoring + ~2s LLM per turn)

The Docker exec overhead is significant — each input requires container exec setup (~400ms) plus Python startup (~100ms). With 32-way parallelism, 256 inputs take ~4s wall clock.

## Key Observations

1. **Parity groups is well-calibrated.** Haiku solves it in 7 turns (needs 6 queries to identify all 4 pairs, plus 1 to confirm). The model demonstrates genuine active learning — probing individual bits and updating its program after each observation.

2. **Linear functions expose a program synthesis gap.** Haiku queries optimally (standard basis vectors) but can't write the GF(2) matrix multiply program. The model has the information to solve it after turn 10, but the loss never drops below ~500. This is a **code generation failure**, not an information gathering failure.

3. **Junta shows the same pattern.** Good query strategy (toggling individual bits to find relevant ones), but the model can't translate observations into a discriminating program.

4. **The eval discriminates well.** Three difficulty levels emerge clearly: parity (simple XOR, easy to program), junta (need to identify bits AND program the lookup), linear (need matrix math in code).

## Difficulties Encountered

- **Docker image needed pre-pulling.** `python:3.13-slim` wasn't cached and the first run failed with "No such image". Required explicit `docker pull` before running.
- **Docker exec overhead is ~500ms/input.** This makes scoring expensive (~4s per turn for 256 inputs). For production use, consider batching inputs into fewer exec calls (trading isolation for speed).
- **Runfiles issue with direct binary execution.** The binary couldn't find its runfiles when run directly; had to use `bazel run` instead.

## Raw Data

Results are in `eval_results/function_learning/haiku_{variant}/` with:

- `*_calls.jsonl` — turn-by-turn log with queries, programs, and results
- `*_summary.json` — game outcome
- `run.log` — full execution log with timing
